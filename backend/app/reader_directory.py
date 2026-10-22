"""KazTBU mapping ported from library/app/Directory/DirectoryReaderClassifier.php.

This is the university's source profile, not universal LDAP/Platonus semantics.
No network operations or credentials are used here.
"""
import re
from datetime import datetime

TECHNICAL_LOGINS={'api','glpi','krbtgt','guest','administrator'}
TECHNICAL_PREFIXES=('api-','svc-','srv-')
LEVELS={'бакалавр':'bachelor','bachelor':'bachelor','специалитет':'specialist','магистрант':'master','магистр':'master','master':'master','докторант':'doctoral','phd':'doctoral','doctoral':'doctoral'}
TEACHING_OVERRIDES=('заведующий кафедрой','заведующая кафедрой','зав. кафедрой','зав.кафедрой')
ADMINISTRATIVE=('руководител','специалист','секретар','офис регистратор','офис-регистратор','администратор','лаборант','библиотекар','библиограф','методист','бухгалтер','комендант','архивариус','заведующий архивом','заведующая лаборатории','заведующий лаборатори','разработчик','проректор','ректор','президент','директор','инженер','диспетчер','менеджер','куратор','психолог','юрист')
TEACHING=('лектор','профессор','ассистент','доцент','преподавател','декан','тьютор','магистр','кандидат наук','доктор phd','phd','оқытушы','lecturer','teacher')
SEX={'1':'female','2':'male'}
DEGREES={'1':'bachelor','2':'master','3':'master','6':'doctoral','8':'specialist'}
AD_LINK_TYPES={'1':'student','2':'tutor'}


def clean(value):
    value=re.sub(r'\s+',' ',str(value or '')).strip()
    return '' if value in ('—','-') else value


def technical(login):
    login=clean(login).casefold()
    return login in TECHNICAL_LOGINS or login.startswith(TECHNICAL_PREFIXES)


def teaching(position):
    position=clean(position).casefold()
    if any(x in position for x in TEACHING_OVERRIDES): return True
    if any(x in position for x in ADMINISTRATIVE): return False
    return any(x in position for x in TEACHING)


def academic(group,course,reference):
    group=clean(group)
    match=re.search(r'[-\s]\s*(\d{2})\d',group)
    cohort=2000+int(match[1]) if match else None
    if cohort and cohort>datetime.now().year+1: cohort=None
    number=re.search(r'\d+',str(course or ''))
    course=int(number[0]) if number and 1<=int(number[0])<=8 else None
    if cohort is None and course:
        cohort=reference.year-(reference.month<9)-course+1
    program=re.match(r'^\s*([^\d]+?)\s*[-\s]\s*\d',group)
    return {'study_group':group,'course':course,'cohort_year':cohort,'program_code':program[1].strip(' -–—') if program else ''}


def email(values):
    for value in values:
        value=str(value or '').strip().lower()
        if len(value)>250 or value.count('@')!=1 or re.search(r'[\s\x00-\x1f\x7f]',value): continue
        local,domain=value.split('@')
        if local and '.' in domain and not domain.startswith('.') and not domain.endswith('.'): return value
    return ''


def ad_fields(attributes,now):
    d={k.lower():v for k,v in attributes.items()}
    def get(key):
        value=d.get(key.lower(),[])
        return value[0] if isinstance(value,list) and value else ('' if isinstance(value,list) else value)
    login=clean(get('sAMAccountName')).lower()
    name=clean(get('displayName')) or clean(get('cn')) or clean(f"{get('sn')} {get('givenName')}") or login
    created=get('whenCreated')
    if not isinstance(created,datetime):
        try: created=datetime.strptime(str(created).split('.')[0].rstrip('Z'),'%Y%m%d%H%M%S')
        except ValueError: created=now
    proxies=d.get('proxyaddresses',[])
    if not isinstance(proxies,list): proxies=[proxies]
    addresses=[str(x)[5:] for x in proxies if str(x).startswith('SMTP:')]
    fields={'full_name':name,'login':login,'email':email(addresses+[get('mail'),get('userPrincipalName')]),'phone':clean(get('mobile')) or clean(get('telephoneNumber')),'faculty':clean(get('division')),'external_status':clean(get('platonusUserStatus'))}
    # The OU/user-type rules come from the reference university project.
    ous=re.findall(r'(?:^|(?<!\\),)\s*OU=([^,]+)',str(get('distinguishedName')),re.I)
    student=any('student' in x.lower() for x in ous) or str(get('platonusUserType')).strip()=='1'
    if student:
        title=clean(get('title')).casefold()
        level=next((v for k,v in LEVELS.items() if k in title),'')
        group=next((clean(get(k)) for k in ('employeeNumber','company') if re.search(r'\d',clean(get(k)))),'')
        fields.update(category=level or 'student',education_level=level,department=clean(get('department')),position='',subdivision='',is_teaching_staff=False)
        fields.update(academic(group,get('info'),created))
    else:
        position=clean(get('title')); is_teacher=teaching(position)
        fields.update(category='teacher' if is_teacher else 'staff',education_level='',study_group='',course=None,cohort_year=created.year,program_code='',department=clean(get('employeeType')) or clean(get('department')),subdivision=clean(get('company')) or clean(get('department')),position=position,is_teaching_staff=is_teacher)
    # AD does not record gender. Do not turn a name-based guess into a fact.
    return fields
