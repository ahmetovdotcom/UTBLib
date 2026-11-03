import json
import os
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from test_catalog import field
from app.main import app, db
from app.db import Base, DocumentType, Record, Copy
from app.security import bootstrap
from app.validation import search_text


@pytest.fixture
def search_client():
    # Optional PostgreSQL run uses only a dedicated disposable database.
    url=os.environ.get('CATALOG_SEARCH_TEST_DATABASE_URL','sqlite://')
    if url!='sqlite://':
        assert make_url(url).database=='utblib_search_test', 'Use a disposable test database'
    opts={'connect_args':{'check_same_thread':False},'poolclass':StaticPool} if url=='sqlite://' else {}
    engine=create_engine(url,**opts)
    Base.metadata.create_all(engine)
    factory=sessionmaker(engine)
    def session():
        with factory() as s:yield s
    app.dependency_overrides[db]=session
    with factory() as s:bootstrap(s,'test-secret')
    try:
        with TestClient(app) as client:
            login=client.post('/api/auth/login',json={'username':'admin','password':'test-secret'})
            assert login.status_code==200,login.text
            client.headers['X-CSRF-Token']=login.json()['csrf_token']
            yield client
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine);engine.dispose()


@pytest.fixture
def data(search_client):
    c=search_client;g=app.dependency_overrides[db]();s=next(g)
    try:
        types=[DocumentType(name='Книга',config=[]),DocumentType(name='Статья',config=[])]
        s.add_all(types);s.flush()
        rows=[]
        for tid,title,fields in [
            (0,'Экономика',[field('245','b','  МОНОГРАФИЯ  '),field('041','a','kaz'),field('080','a','336'),field('952','j','Финансы'),field('952','j','Экономика')]),
            (0,'История',[field('245','b','Коллективная монография'),field('041','a','rus'),field('080','a','94'),field('952','j','Қазақ тілі')]),
            (0,'Монография в заглавии',[field('245','c','монография'),field('500','a','Монография')]),
            (1,'Монография-статья',[field('245','b','монография'),field('041','a','rus')]),
            (0,'Спецсимволы',[field('245','b',r'100%_\\данные'),field('245','b',"' OR 1=1 --"),field('001','a','placeholder')]),
        ]:
            if title=='Спецсимволы':fields[-1]={'tag':'001','value':'ТЕСТ-001'}
            marc={'leader':'00000nam a2200000   4500','fields':[field(value=title),*fields]}
            r=Record(type_id=types[tid].id,marc=marc,search_text=search_text(marc));s.add(r);rows.append(r)
        s.flush()
        s.add(Copy(record_id=rows[0].id,request_key=str(uuid4()),payload_hash='qa',inventory_number='INV-X',barcode='BC-X',sigla=''))
        s.commit();ids=[r.id for r in rows];type_id=types[0].id
    finally:g.close()
    return c,ids,type_id


def search(c,*conditions,**params):
    response=c.get('/api/records',params={'conditions':json.dumps(list(conditions),ensure_ascii=False),**params})
    assert response.status_code==200,response.text
    return [r['id'] for r in response.json()]


def condition(field='245$b',value='монография',operator='contains'):
    return dict(field=field,value=value,operator=operator)


def test_subtitle_only_case_insensitive_whole_field_exact_and_prefix(data):
    c,ids,_=data
    assert search(c,condition())==[ids[3],ids[1],ids[0]]
    assert search(c,condition(operator='equals'))==[ids[3],ids[0]]
    assert search(c,condition(value='МОНО',operator='starts_with'))==[ids[3],ids[0]]
    assert search(c,condition(field='245'))==[ids[3],ids[2],ids[1],ids[0]]
    assert search(c,condition(field='952$j',value='ҚАЗАҚ'))==[ids[1]]
    assert search(c,condition(field='001',value='тест-001',operator='equals'))==[ids[4]]
    assert len(search(c,condition(field='000',value='a2200000')))==5


def test_multiple_conditions_repetitions_and_other_filters_before_pagination(data):
    c,ids,tid=data
    assert search(c,condition(),condition('041$a','kaz'))==[ids[0]]
    assert search(c,condition(),condition('500$a','МОНОГРАФИЯ'),match='any')==[ids[3],ids[2],ids[1],ids[0]]
    # Multiple values of the same field can match in different occurrences.
    assert search(c,condition('952$j','Финансы'),condition('952$j','Экономика'))==[ids[0]]
    assert search(c,condition(),type_id=tid,limit=1)==[ids[1]]
    assert search(c,condition(),type_id=tid,limit=1,offset=1)==[ids[0]]
    assert search(c,condition(),type_id=tid,limit=1,offset=2)==[]
    assert search(c,condition(),udc='33',q='экономика')==[ids[0]]
    assert search(c,condition(),q='INV-X')==[ids[0]]
    assert search(c,condition('245$b','нет'),condition('952$j','Қазақ'),match='any',q='история')==[ids[1]]


def test_literal_wildcards_sql_quotes_empty_and_repeated_matches(data):
    c,ids,_=data
    for value in ['%', '_', '\\', "' OR 1=1 --"]:
        assert search(c,condition(value=value))==[ids[4]]
    assert search(c,condition('245$b','%'),condition('245$b','_'),match='any')==[ids[4]]
    assert search(c)==list(reversed(ids))
    assert search(c,condition(value='несуществующее'))==[]
    assert c.get('/api/records',params={'conditions':json.dumps([condition()])},headers={'X-Admin-Key':'bad'}).status_code==401


@pytest.mark.parametrize('raw',[
    'not-json', '{}', json.dumps([condition(field='245;DROP')]),
    json.dumps([condition(field='999$z')]),json.dumps([condition(field='001$a')]),
    json.dumps([condition(operator='regex')]),json.dumps([condition(value='   ')]),
    json.dumps([condition(value='x'*20001)]),json.dumps([condition()]*9),
    json.dumps([dict(condition(),extra=True)]),
])
def test_invalid_conditions_rejected(search_client,raw):
    assert search_client.get('/api/records',params={'conditions':raw}).status_code==422


def test_invalid_match_rejected(search_client):
    assert search_client.get('/api/records',params={'match':'not-a-mode'}).status_code==422


def test_term_values_counts_match_exact_results_and_type_scope(data):
    c,ids,tid=data
    g=app.dependency_overrides[db]();s=next(g)
    try:
        row=s.get(Record,ids[0]);marc=json.loads(json.dumps(row.marc))
        marc['fields'].append(field('245','b','монография'))
        row.marc=marc;s.commit()
    finally:g.close()
    r=c.get('/api/catalog-search/values',params={'field':'245$b'})
    assert r.status_code==200,r.text
    terms=r.json();assert terms['total']==4
    mono=next(t for t in terms['items'] if t['value'].lower()=='монография')
    assert mono['count']==2 # Repeated field in the same record counts once.
    for t in terms['items']:
        result=c.post('/api/catalog-search/records',json={'conditions':[condition(value=t['value'],operator='equals')]})
        assert result.status_code==200,result.text
        assert len(result.json())==t['count']
    r=c.get('/api/catalog-search/values',params={'field':'245$b','type_id':tid,'q':'МОНО'})
    assert r.json()['total']==2
    assert all(t['count']==1 for t in r.json()['items'])
    r=c.get('/api/catalog-search/values',params={'field':'245','q':'монография'})
    assert next(t for t in r.json()['items'] if t['value'].lower()=='монография')['count']==3


def test_term_options_used_and_configured_fields_and_empty_fields(data):
    c,ids,tid=data
    g=app.dependency_overrides[db]();s=next(g)
    try:
        t=s.get(DocumentType,tid);t.config=[{'tag':'260','subfields':['a','b']}];s.commit()
    finally:g.close()
    r=c.get('/api/catalog-search/options',params={'type_id':tid})
    assert r.status_code==200,r.text
    options={f['key']:f for f in r.json()['fields']}
    assert options['245$b']['count']==3 and not options['245$b']['configured']
    assert options['245']['count']==4
    assert options['260$a']['configured'] and options['260$a']['count']==0
    assert not options['260$c']['configured']
    assert c.get('/api/catalog-search/values',params={'field':'260$b'}).json()['items']==[]
    assert options['000']['count']==4
    assert options['001']['count']==1


def test_term_filter_pagination_literals_and_control_values(data):
    c,ids,tid=data
    one=c.get('/api/catalog-search/values',params={'field':'245$b','limit':2}).json()
    two=c.get('/api/catalog-search/values',params={'field':'245$b','limit':2,'offset':2}).json()
    assert one['total']==two['total']==4
    assert len(one['items'])==len(two['items'])==2
    assert not ({t['value'] for t in one['items']}&{t['value'] for t in two['items']})
    for q in ['%', '_', '\\', "' OR 1=1 --"]:
        r=c.get('/api/catalog-search/values',params={'field':'245$b','q':q})
        assert r.status_code==200,r.text
        assert r.json()['total']==1
    for key in ['000','001','952$j']:
        r=c.get('/api/catalog-search/values',params={'field':key})
        assert r.status_code==200,r.text
        assert r.json()['items']
    assert c.get('/api/catalog-search/values',params={'field':'952$j','q':'ҚАЗАҚ'}).json()['items']==[{'value':'Қазақ тілі','count':1}]
    assert c.get('/api/catalog-search/values',params={'field':'245$b','offset':100}).json()['total']==4


def test_long_term_post_search_and_invalid_inputs(data):
    c,ids,tid=data
    value='Длинная аннотация на казахском языке. '*150
    g=app.dependency_overrides[db]();s=next(g)
    try:
        row=s.get(Record,ids[0]);marc=json.loads(json.dumps(row.marc));marc['fields'].append(field('520','a',value));row.marc=marc;s.commit()
    finally:g.close()
    terms=c.get('/api/catalog-search/values',params={'field':'520$a'}).json()['items']
    assert terms==[{'value':value.strip(),'count':1}]
    r=c.post('/api/catalog-search/records',json={'conditions':[condition('520$a',terms[0]['value'],'equals')]})
    assert r.status_code==200,r.text
    assert [x['id'] for x in r.json()]==[ids[0]]
    assert c.post('/api/catalog-search/records',json={'conditions':[condition()], 'offset':1,'limit':1}).json()[0]['id']==ids[1]
    for params,status in [({'field':'245;drop'},422),({'field':'999$z'},422),({'field':'001$a'},422),({'field':'245$b','limit':101},422),({'field':'245$b','type_id':999},404)]:
        assert c.get('/api/catalog-search/values',params=params).status_code==status
    assert c.get('/api/catalog-search/options',params={'type_id':999}).status_code==404
    assert c.post('/api/catalog-search/records',json={'conditions':[condition(field='999$z')]}).status_code==422
    assert c.post('/api/catalog-search/records',json={'conditions':[condition()]*9}).status_code==422


def test_term_routes_auth_and_viewer_access(data):
    from test_security import add,login
    c,ids,tid=data
    add(c)
    with TestClient(app) as viewer:
        for path in ['/api/catalog-search/options','/api/catalog-search/values?field=245$b']:
            assert viewer.get(path).status_code==401
        assert viewer.post('/api/catalog-search/records',json={}).status_code==401
        login(viewer)
        assert viewer.get('/api/catalog-search/options').status_code==200
        assert viewer.get('/api/catalog-search/values?field=245$b').status_code==200
        assert viewer.post('/api/catalog-search/records',json={'conditions':[condition()]}).status_code==200
        assert viewer.post('/api/catalog-search/records',json={},headers={'X-CSRF-Token':''}).status_code==403
    c.post('/api/users',json={'username':'visits','display_name':'Visits','password':'strong-password','role':'librarian','permissions':['visits.view']})
    with TestClient(app) as restricted:
        login(restricted,'visits')
        # Some presets include catalogue view automatically; remove only in the fixture.
        g=app.dependency_overrides[db]();s=next(g)
        try:
            from app.db import User
            from sqlalchemy import select
            user=s.scalar(select(User).where(User.username=='visits'));user.permissions=['visits.view'];s.commit()
        finally:g.close()
        assert restricted.get('/api/catalog-search/options').status_code==403
        assert restricted.get('/api/catalog-search/values?field=245$b').status_code==403
        assert restricted.post('/api/catalog-search/records',json={}).status_code==403
