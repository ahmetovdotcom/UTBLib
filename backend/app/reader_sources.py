"""Optional read-only adapters. No connection is made until an explicit sync command."""
import base64, json, os, re, ssl, uuid
from datetime import datetime
from sqlalchemy import select
from .reader_core import TZ, validate_personal, audit, personal_error_code
from .reader_models import Reader, ReaderIdentity, ReaderSyncRun, ReaderConflict
from .db import utcnow
from .reader_sync import batches, sync_lock
from .reader_directory import ad_fields, technical, academic, teaching, clean, email, SEX, DEGREES, AD_LINK_TYPES

def enabled(name):
    if os.getenv(name+'_ENABLED','false').lower()!='true': raise ValueError(name+' отключён')

def mysql():
    enabled('PLATONUS')
    import pymysql
    timeout=min(30,max(1,int(os.getenv('PLATONUS_QUERY_TIMEOUT_SECONDS','5'))))
    ca=os.getenv('PLATONUS_DB_SSL_CA')
    conn=pymysql.connect(host=os.environ['PLATONUS_DB_HOST'],port=int(os.getenv('PLATONUS_DB_PORT','6080')),user=os.environ['PLATONUS_DB_USER'],password=os.environ['PLATONUS_DB_PASSWORD'],database=os.environ['PLATONUS_DB_NAME'],charset='utf8mb4',cursorclass=pymysql.cursors.DictCursor,connect_timeout=timeout,read_timeout=timeout,write_timeout=timeout,ssl={'ca':ca,'check_hostname':True} if ca else None,autocommit=False)
    with conn.cursor() as c:
        c.execute('SET SESSION TRANSACTION READ ONLY')
        c.execute('SET SESSION MAX_EXECUTION_TIME=%s',(timeout*1000,))
    return conn

SCHEMA={'students':['StudentID','lastname','firstname','patronymic','SexID','CourseNumber','StartDate','Login','mail','mobilePhone','phone','photo','groupID','StudyFormID','isStudent','iinplt','BirthDate'],'studentstudygroup':['StudentID','studyGroupID'],'studygroups':['StudyGroupID','year'],'groups':['groupID','name','specializationID'],'specializations':['id','prof_caf_id'],'profession_cafedra':['id','cafedraID'],'cafedras':['cafedraID','cafedraNameRU','FacultyID'],'faculties':['FacultyID','facultyNameRU'],'studyforms':['Id','degreeID'],'tutors':['TutorID','lastname','firstname','patronymic','SexID','Login','mail','mobilePhone','phone','photo','job_title','CafedraID','deleted']}
def inspect_schema(conn):
    with conn.cursor() as c:
        c.execute('SELECT TABLE_NAME,COLUMN_NAME,DATA_TYPE FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE()')
        available={(r['TABLE_NAME'].lower(),r['COLUMN_NAME'].lower()):r['DATA_TYPE'] for r in c.fetchall()}
    for table,columns in SCHEMA.items():
        for col in columns:
            if (table.lower(),col.lower()) not in available: raise ValueError('Схема Platonus не совпадает с подтверждённым образцом')
    return available

def status_column(entity,schema):
    column=os.getenv('PLATONUS_'+entity.upper()+'_STATUS_COLUMN','')
    if not column: return ''
    table='students' if entity=='student' else 'tutors'
    if not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*',column) or (table,column.lower()) not in schema: raise ValueError('Неизвестная колонка статуса')
    return column

def platonus_rows(year=None,no_photos=False,search=None,identity=None):
    now=datetime.now(TZ); year=year or int((os.getenv('PLATONUS_ACADEMIC_YEAR') or str(now.year if now.month>=9 else now.year-1)))
    size=min(1000,max(1,int(os.getenv('PLATONUS_CHUNK','500'))))
    conn=mysql()
    try:
        schema=inspect_schema(conn)
        for entity in ('student','tutor'):
            if identity and identity[0]!=entity: continue
            col=status_column(entity,schema); alias='s' if entity=='student' else 't'; status=f', {alias}.`{col}` AS external_status' if col else ''
            photo='' if no_photos else f', {alias}.photo'
            sex_map={**SEX,**json.loads(os.getenv('PLATONUS_GENDER_MAP','{}'))}; degree_map={**DEGREES,**json.loads(os.getenv('PLATONUS_DEGREE_MAP','{}'))}
            inactive=set(json.loads(os.getenv('PLATONUS_INACTIVE_'+entity.upper()+'_STATUSES','[]') or '[]'))
            last=0
            while True:
                if entity=='student':
                    query=f'''SELECT DISTINCT s.StudentID AS external_id,s.lastname,s.firstname,s.patronymic,s.SexID,s.CourseNumber,YEAR(s.StartDate) AS cohort,s.Login,s.mail,s.mobilePhone,s.phone,gr.name AS study_group,f.facultyNameRU AS faculty,c.cafedraNameRU AS department,sf.degreeID {status}{photo}
                    FROM students s LEFT JOIN `groups` gr ON gr.groupID=s.groupID LEFT JOIN specializations sp ON sp.id=gr.specializationID LEFT JOIN profession_cafedra pc ON pc.id=sp.prof_caf_id LEFT JOIN cafedras c ON c.cafedraID=pc.cafedraID LEFT JOIN faculties f ON f.FacultyID=c.FacultyID LEFT JOIN studyforms sf ON sf.Id=s.StudyFormID
                    WHERE s.isStudent=1 AND s.StudentID>%s AND EXISTS(SELECT 1 FROM studentstudygroup ssg JOIN studygroups g ON g.StudyGroupID=ssg.studyGroupID WHERE ssg.StudentID=s.StudentID AND g.year=%s) ORDER BY s.StudentID LIMIT %s'''
                    params=(last,year,size)
                else:
                    query=f'''SELECT t.TutorID AS external_id,t.lastname,t.firstname,t.patronymic,t.SexID,t.Login,t.mail,t.mobilePhone,t.phone,t.job_title,f.facultyNameRU AS faculty,c.cafedraNameRU AS department {status}{photo} FROM tutors t LEFT JOIN cafedras c ON c.cafedraID=t.CafedraID LEFT JOIN faculties f ON f.FacultyID=c.FacultyID WHERE t.deleted=0 AND t.TutorID>%s ORDER BY t.TutorID LIMIT %s''';params=(last,size)
                if search or identity:
                    if entity=='student':
                        query=query.replace(' AND EXISTS(SELECT 1 FROM studentstudygroup ssg JOIN studygroups g ON g.StudyGroupID=ssg.studyGroupID WHERE ssg.StudentID=s.StudentID AND g.year=%s)','')
                        params=(last,size)
                    pk='StudentID' if entity=='student' else 'TutorID'
                    if identity:
                        condition=f'{alias}.{pk}=%s'; values=[identity[1]]
                    else:
                        terms=search.split()
                        condition=' AND '.join([f"CONCAT_WS(' ',{alias}.lastname,{alias}.firstname,{alias}.patronymic,{alias}.Login) LIKE %s"]*len(terms))
                        values=['%'+term.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%' for term in terms]
                    query=query.replace(' ORDER BY ',f' AND ({condition}) ORDER BY ')
                    params=(*params[:-1],*values,21)
                with conn.cursor() as c: c.execute(query,params); rows=c.fetchall()
                if not rows: break
                for row in rows:
                    last=max(last,int(row['external_id']))
                    leaver=col and str(row.get('external_status')).casefold() in {str(v).casefold() for v in inactive}
                    fields={'full_name':' '.join(str(row.get(k) or '').strip() for k in ('lastname','firstname','patronymic')).strip(),'category':degree_map.get(str(row.get('degreeID')),'student') if entity=='student' else 'teacher','is_teaching_staff':entity=='tutor','login':row.get('Login') or '','email':row.get('mail') or '','phone':row.get('mobilePhone') or row.get('phone') or '','faculty':row.get('faculty') or '','department':row.get('department') or '','external_status':str(row.get('external_status') or '')}
                    fields['login']=clean(row.get('Login')).lower() or f'platonus-{entity}-{last}'
                    fields['email']=email([row.get('mail')])
                    if entity=='student':
                        fields.update(academic(row.get('study_group'),row.get('CourseNumber'),now))
                        fields['education_level']=degree_map.get(str(row.get('degreeID')),'')
                    else:
                        fields['position']=clean(row.get('job_title')) or 'Преподаватель'
                        fields['is_teaching_staff']=teaching(fields['position'])
                        fields['category']='teacher' if fields['is_teaching_staff'] else 'staff'
                        fields['subdivision']=fields['department']
                        fields['cohort_year']=now.year
                    gender=sex_map.get(str(row.get('SexID')))
                    if gender in ('male','female'): fields['gender']=gender
                    yield {'entity_type':entity,'external_id':str(row['external_id']),'fields':fields,'technical':technical(fields['login']),'leaver':bool(leaver),'photo':base64.b64encode(row['photo']).decode() if row.get('photo') and not no_photos else None}
                if search or identity: break
    finally: conn.close()

def ad_rows(no_photos=False,search=None,identity=None):
    enabled('AD')
    import ldap3
    if os.getenv('AD_REQUIRE_CERT','true').lower()!='true': raise ValueError('Проверку сертификата AD отключать нельзя')
    tls=ldap3.Tls(validate=ssl.CERT_REQUIRED,ca_certs_file=os.getenv('AD_CA_CERT_PATH') or None)
    use_ssl=os.getenv('AD_USE_SSL','true').lower()=='true'
    server=ldap3.Server(os.environ['AD_HOST'],port=int(os.getenv('AD_PORT','636' if use_ssl else '389')),use_ssl=use_ssl,tls=tls,connect_timeout=10)
    conn=ldap3.Connection(server,user=os.environ['AD_BIND_DN'],password=os.environ['AD_BIND_PASSWORD'],receive_timeout=15,raise_exceptions=True)
    try:
        conn.open()
        if not use_ssl and not conn.start_tls(): raise ValueError('AD STARTTLS failed')
        if not conn.bind(): raise ValueError('AD bind failed')
        mapping={'platonus_id':'platonusUserId','platonus_type':'platonusUserType',**json.loads(os.getenv('AD_ATTRIBUTE_MAP','{}'))}
        required=['objectGUID','sAMAccountName','userPrincipalName','distinguishedName','displayName','cn','givenName','sn','mail','mobile','telephoneNumber','title','department','division','company','employeeType','employeeNumber','info','platonusUserStatus','proxyAddresses','whenCreated','userAccountControl']
        attrs=list(set(required+list(mapping.values())+([] if no_photos else ['thumbnailPhoto'])))
        cookie=None; seen_cookies=set()
        user_filter=os.getenv('AD_USER_FILTER','(&(objectCategory=person)(objectClass=user))')
        if os.getenv('AD_FILTER_CONFIRMED','false')!='true': raise ValueError('Подтвердите фильтр AD, исключающий технические учётные записи')
        if search or identity:
            from ldap3.utils.conv import escape_filter_chars
            if identity:
                guid=''.join('\\'+format(b,'02x') for b in uuid.UUID(identity).bytes_le)
                extra='(objectGUID='+guid+')'
            else:
                extra=''.join('(|(displayName=*'+escape_filter_chars(term)+'*)(sAMAccountName=*'+escape_filter_chars(term)+'*))' for term in search.split())
            user_filter='(&'+user_filter+extra+')'
        while True:
            conn.search(os.environ['AD_BASE_DN'],user_filter,attributes=attrs,paged_size=21 if search or identity else 500,paged_cookie=cookie)
            if conn.result.get('result')!=0: raise ValueError('AD incomplete page')
            for entry in conn.entries:
                d={k.lower():v for k,v in entry.entry_attributes_as_dict.items()}
                d.setdefault('distinguishedname',[entry.entry_dn])
                def val(key):
                    v=d.get(key.lower(),[]); return v[0] if isinstance(v,list) and v else ('' if isinstance(v,list) else v)
                if int(val('userAccountControl') or 0)&2 or technical(val('sAMAccountName')): continue
                guid=val('objectGUID'); guid=str(uuid.UUID(bytes_le=guid)) if isinstance(guid,bytes) else str(guid).strip('{}').lower()
                if not guid or not val('sAMAccountName'): raise ValueError('AD identity missing')
                fields=ad_fields(d,datetime.now(TZ))
                category=json.loads(os.getenv('AD_CATEGORY_MAP','{}')).get(str(val('employeeType')))
                if category: fields['category']=category
                for field,attribute in mapping.items():
                    if field not in ('platonus_id','platonus_type'): fields[field]=val(attribute)
                row={'entity_type':'ad_user','external_id':guid,'fields':fields,'leaver':fields['external_status'].casefold() in {str(x).casefold() for x in json.loads(os.getenv('AD_LEAVER_STATUSES','[]'))}}
                if mapping.get('platonus_id') and mapping.get('platonus_type') and val(mapping['platonus_id']):
                    type_map={**AD_LINK_TYPES,**json.loads(os.getenv('AD_PLATONUS_TYPE_MAP','{}'))}; kind=type_map.get(str(val(mapping['platonus_type'])))
                    row['platonus_link']={'entity_type':kind,'external_id':str(val(mapping['platonus_id'])),'confirmed':os.getenv('AD_PLATONUS_LINK_CONFIRMED','true')=='true'}
                if not no_photos and val('thumbnailPhoto'): row['photo']=base64.b64encode(val('thumbnailPhoto')).decode()
                yield row
            if search or identity: break
            control=conn.result.get('controls',{}).get('1.2.840.113556.1.4.319')
            if control is None: raise ValueError('AD pagination control missing')
            cookie=control['value']['cookie']
            if not cookie: break
            if cookie in seen_cookies: raise ValueError('AD repeated pagination cookie')
            seen_cookies.add(cookie)
    finally: conn.unbind()

def source_rows(source,year=None,no_photos=False):
    yield from ad_rows(no_photos) if source=='active_directory' else platonus_rows(year,no_photos)

def personal_rows(factory,dry_run=False,overwrite=False,limit=None,reader_id=None):
    with factory() as probe: engine=probe.get_bind()
    counts={'updated':0,'errors':0}
    with sync_lock(engine),factory() as s:
        conn=mysql()
        try:
            inspect_schema(conn)
            stmt=select(ReaderIdentity).where(ReaderIdentity.source=='platonus',ReaderIdentity.entity_type=='student').order_by(ReaderIdentity.id)
            if reader_id is not None: stmt=stmt.where(ReaderIdentity.reader_id==reader_id)
            if limit: stmt=stmt.limit(limit)
            for chunk in batches(s.scalars(stmt).yield_per(500)):
                ids=[x.external_id for x in chunk]
                with conn.cursor() as c:
                    c.execute('SELECT StudentID,iinplt,BirthDate FROM students WHERE StudentID IN ('+','.join(['%s']*len(ids))+')',ids); upstream={str(r['StudentID']):r for r in c.fetchall()}
                readers={r.id:r for r in s.scalars(select(Reader).where(Reader.id.in_([x.reader_id for x in chunk])).with_for_update())}
                iins={str(r.get('iinplt')) for r in upstream.values() if r.get('iinplt')}|{r.iin for r in readers.values() if r.iin}
                known_iins=dict(s.execute(select(Reader.iin,Reader.id).where(Reader.iin.in_(iins))).all())
                for identity in chunk:
                    data=upstream.get(identity.external_id)
                    if not data: continue
                    reader=readers[identity.reader_id]
                    try:
                        values={key:(data.get(column) or None) if overwrite or not getattr(reader,key) else getattr(reader,key) for key,column in [('iin','iinplt'),('birth_date','BirthDate')]}
                        if isinstance(values['birth_date'],datetime): values['birth_date']=values['birth_date'].date()
                        iin,birth=validate_personal(s,values,reader.id,known_iins)
                        if overwrite or 'iin' not in reader.manual_overrides: reader.iin=iin
                        if overwrite or 'birth_date' not in reader.manual_overrides: reader.birth_date=birth
                        if iin: known_iins[iin]=reader.id
                        reader.version+=1; audit(s,'reader.personal_sync',reader=reader.id); counts['updated']+=1
                    except ValueError as exc:
                        counts['errors']+=1
                        s.add(ReaderConflict(reader_id=reader.id,source='platonus',entity_type='student',external_id=identity.external_id,code=personal_error_code(exc)))
            if dry_run: s.rollback()
            else: s.commit()
        finally: conn.close()
    return counts
