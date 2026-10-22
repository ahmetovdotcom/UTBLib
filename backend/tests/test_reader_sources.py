"""Synthetic source fixtures: no connection to AD or Platonus."""
import os
os.environ.setdefault('DATABASE_URL','sqlite://')
from datetime import datetime, timezone
from types import SimpleNamespace
import pytest
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker
from app.db import Base
from app.reader_directory import ad_fields, teaching, academic, technical
from app import reader_sources as sources
from app.reader_sync import synchronize
from app.reader_models import Reader, ReaderIdentity

NOW=datetime(2026,10,22,tzinfo=timezone.utc)


def test_reference_ad_student_mapping():
    result=ad_fields({
        'displayName':['Тестовый Студент'],'sAMAccountName':['Student1'],
        'distinguishedName':['CN=Student,OU=students,OU=Univer,DC=example,DC=test'],
        'title':['Бакалавр'],'info':['2 курс'],'employeeNumber':['АиУ-252'],
        'division':['Технологический факультет'],'department':['Автоматизация'],
        'proxyAddresses':['smtp:old@example.test','SMTP:Студент@example.test'],
        'mail':['fallback@example.test'],'whenCreated':[NOW],
    },NOW)
    assert result['category']==result['education_level']=='bachelor'
    assert (result['course'],result['cohort_year'],result['program_code'])==(2,2025,'АиУ')
    assert result['faculty']=='Технологический факультет'
    assert result['email']=='студент@example.test'
    assert result['position']=='' and result['login']=='student1'
    assert 'gender' not in result


@pytest.mark.parametrize('title,expected',[
    ('Заведующий кафедрой',True),('Проректор, профессор',False),
    ('Библиотекарь',False),('Старший преподаватель',True),('Инженер',False),
])
def test_reference_staff_roles(title,expected):
    assert teaching(title)==expected
    fields=ad_fields({'title':[title],'employeeType':['Кафедра'],'department':['Запасная'],
        'division':['Факультет'],'company':['Подразделение'],'cn':['Тестовый Сотрудник'],
        'userPrincipalName':['Тест@example.test']},NOW)
    assert fields['category']==('teacher' if expected else 'staff')
    assert fields['department']=='Кафедра' and fields['subdivision']=='Подразделение'
    assert fields['email']=='тест@example.test'


def test_source_fallbacks_and_technical_accounts():
    result=ad_fields({'platonusUserType':['1'],'title':['Докторант'],'company':['БТ 251/3'],'info':['1 курс'],'sn':['Фамилия'],'givenName':['Имя'],'mail':['x@x@x'],'userPrincipalName':['a@example.test']},NOW)
    assert result['category']=='doctoral' and result['full_name']=='Фамилия Имя'
    assert result['cohort_year']==2025 and result['study_group']=='БТ 251/3'
    assert result['email']=='a@example.test'
    assert academic('', '3 курс',NOW)['cohort_year']==2024
    assert academic('Без номера','нет',NOW)['course'] is None
    assert technical('SVC-service') and technical('Administrator') and not technical('Ivanov')


@pytest.fixture
def fake_ad(monkeypatch):
    import ldap3
    monkeypatch.setenv('AD_ENABLED','true');monkeypatch.setenv('AD_FILTER_CONFIRMED','true')
    for key,value in {'AD_HOST':'unused.test','AD_BIND_DN':'service','AD_BIND_PASSWORD':'fake','AD_BASE_DN':'DC=example,DC=test','AD_ATTRIBUTE_MAP':'{}','AD_PLATONUS_LINK_CONFIRMED':'true'}.items(): monkeypatch.setenv(key,value)
    class Connection:
        def __init__(self): self.calls=[];self.result={};self.entries=[];self.closed=False
        def open(self): pass
        def bind(self): return True
        def unbind(self): self.closed=True
        def search(self,base,query,**kwargs):
            self.calls.append(kwargs)
            i=len(self.calls)
            def entry(login,disabled=0):
                return SimpleNamespace(entry_dn='CN=test,OU=students,DC=example,DC=test',entry_attributes_as_dict={
                    'objectGUID':[f'00000000-0000-0000-0000-{i:012d}'],
                    'sAMAccountName':[login],'displayName':['Тестовый Читатель'],
                    'userAccountControl':[disabled],'platonusUserId':['7'],
                    'platonusUserType':['1'],'title':['Магистрант'],'info':['1 курс']})
            self.entries=[entry('student')] if i==1 else [entry('svc-test'),entry('disabled',2)]
            self.result={'result':0,'controls':{'1.2.840.113556.1.4.319':{'value':{'cookie':b'next' if i==1 else b''}}}}
    conn=Connection()
    monkeypatch.setattr(ldap3,'Server',lambda *a,**k: None)
    monkeypatch.setattr(ldap3,'Connection',lambda *a,**k: conn)
    return conn


def test_ad_pages_attributes_and_typed_link(fake_ad):
    rows=list(sources.ad_rows(no_photos=True))
    assert len(rows)==1 and fake_ad.closed and len(fake_ad.calls)==2
    assert fake_ad.calls[0]['paged_size']==500 and fake_ad.calls[1]['paged_cookie']==b'next'
    assert {'employeeNumber','info','company','whenCreated','userPrincipalName'}<=set(fake_ad.calls[0]['attributes'])
    assert rows[0]['fields']['category']=='master'
    assert rows[0]['platonus_link']=={'entity_type':'student','external_id':'7','confirmed':True}


def test_ad_failure_is_not_a_complete_harvest(fake_ad):
    original=fake_ad.search
    def search(*a,**kw):
        original(*a,**kw)
        if len(fake_ad.calls)==2: fake_ad.result['result']=4
    fake_ad.search=search
    with pytest.raises(ValueError,match='incomplete'): list(sources.ad_rows(True))
    assert fake_ad.closed


@pytest.fixture
def fake_mysql(monkeypatch):
    class Connection:
        def __init__(self): self.query='';self.params=();self.calls=[];self.closed=False
        def cursor(self): return self
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def execute(self,q,p=()): self.query=q;self.params=p;self.calls.append((q,p))
        def fetchall(self):
            if 'information_schema' in self.query:
                return [{'TABLE_NAME':t,'COLUMN_NAME':c,'DATA_TYPE':'varchar'} for t,cols in sources.SCHEMA.items() for c in cols]
            if self.params[0]>0: return []
            common={'external_id':7,'lastname':'Тестовая','firstname':'Персона','patronymic':'','SexID':1,'Login':'','mail':'test@example.test','mobilePhone':'123','phone':'','faculty':'Факультет','department':'Кафедра'}
            if 'FROM students' in self.query:
                return [{**common,'CourseNumber':2,'study_group':'БТ 251/3','degreeID':2}]
            return [{**common,'job_title':'Лаборант'}]
        def close(self): self.closed=True
    conn=Connection();monkeypatch.setattr(sources,'mysql',lambda:conn)
    monkeypatch.setenv('PLATONUS_GENDER_MAP','{}');monkeypatch.setenv('PLATONUS_DEGREE_MAP','{}')
    return conn


def test_platonus_reference_query_and_values(fake_mysql):
    rows=list(sources.platonus_rows(2026,True))
    assert fake_mysql.closed and len(rows)==2
    student,tutor=rows
    assert student['fields']['category']=='master' and student['fields']['education_level']=='master'
    assert student['fields']['gender']=='female' and student['fields']['program_code']=='БТ'
    assert student['fields']['login']=='platonus-student-7'
    assert tutor['fields']['category']=='staff' and not tutor['fields']['is_teaching_staff']
    assert student['external_id']==tutor['external_id'] and student['entity_type']!=tutor['entity_type']
    student_queries=[(q,p) for q,p in fake_mysql.calls if 'FROM students' in q]
    assert all('s.isStudent=1' in q and 'EXISTS' in q and 'g.year=%s' in q and p[1]==2026 for q,p in student_queries)
    assert any('t.deleted=0' in q for q,p in fake_mysql.calls)


def test_ad_then_platonus_keeps_one_reader_and_stable_ticket(fake_ad,fake_mysql):
    engine=create_engine('sqlite://');Base.metadata.create_all(engine);factory=sessionmaker(engine)
    try:
        ad=list(sources.ad_rows(True));platonus=list(sources.platonus_rows(2026,True))
        result=synchronize(factory,'active_directory',ad,complete=True)
        assert result['counts']['created']==1,result
        with factory() as s: original=s.scalar(select(Reader)).ticket_number
        result=synchronize(factory,'platonus',platonus,complete=True)
        assert result['counts']['created']==1 and result['counts']['updated']==1,result
        result=synchronize(factory,'active_directory',ad,complete=True)
        assert result['counts']['created']==0,result
        with factory() as s:
            assert s.scalar(select(func.count()).select_from(Reader))==2
            reader=s.get(Reader,1)
            assert reader.ticket_number==original and reader.full_name=='Тестовый Читатель'
            assert reader.source=='active_directory'
            assert s.scalar(select(func.count()).select_from(ReaderIdentity))==3
    finally: engine.dispose()


def test_leaver_and_return_preserve_manual_block():
    engine=create_engine('sqlite://');Base.metadata.create_all(engine);factory=sessionmaker(engine)
    row={'entity_type':'student','external_id':'1','fields':{'full_name':'Тестовый Читатель'}}
    try:
        result=synchronize(factory,'platonus',[{**row,'leaver':True}]);assert result['counts']['created']==0
        synchronize(factory,'platonus',[row])
        result=synchronize(factory,'platonus',[{**row,'leaver':True}]);assert result['counts']['suspended']==1
        synchronize(factory,'platonus',[row])
        with factory() as s:
            reader=s.get(Reader,1);assert reader.status=='active'
            reader.status='blocked';reader.block_reason='Ручная блокировка';s.commit()
        synchronize(factory,'platonus',[{**row,'leaver':True}])
        synchronize(factory,'platonus',[row])
        with factory() as s: assert s.get(Reader,1).status=='blocked'
    finally: engine.dispose()


def test_targeted_ad_is_escaped_and_bounded(fake_ad):
    original=fake_ad.search;filters=[]
    def capture(base,query,**kw):
        filters.append(query);return original(base,query,**kw)
    fake_ad.search=capture
    assert len(list(sources.ad_rows(search='a*)(objectClass=*)')))==1
    assert len(fake_ad.calls)==1 and fake_ad.calls[0]['paged_size']==21
    assert r'\2a\29\28' in filters[0]


def test_targeted_platonus_is_parameterized_and_includes_new_student(fake_mysql):
    rows=list(sources.platonus_rows(search="Тест' OR 1=1"))
    queries=[(q,p) for q,p in fake_mysql.calls if 'AS external_id' in q]
    assert len(queries)==2 and len(rows)==2
    assert all('Тест' not in q and p[-1]==21 for q,p in queries)
    assert 'EXISTS' not in queries[0][0] and 's.isStudent=1' in queries[0][0]
    fake_mysql.calls=[]
    list(sources.platonus_rows(identity=('tutor','7')))
    queries=[(q,p) for q,p in fake_mysql.calls if 'AS external_id' in q]
    assert len(queries)==1 and 't.TutorID=%s' in queries[0][0] and queries[0][1]==(0,'7',21)
