import os
from pathlib import Path
os.environ.setdefault('DATABASE_URL','sqlite://')
os.environ.setdefault('ADMIN_KEY','test-secret')
os.environ.setdefault('MARC_PATH',str(Path(__file__).resolve().parents[2]/'data/marc21.json'))
import copy, json, hashlib
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db import Base
from app.main import app,db,DATA,DICTIONARY
from app.import_marc import parse
from app.validation import validate_marc

@pytest.fixture
def client():
    engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    Base.metadata.create_all(engine); factory=sessionmaker(engine)
    def session():
        with factory() as s: yield s
    app.dependency_overrides[db]=session
    from app.security import bootstrap
    with factory() as s: bootstrap(s,'test-secret')
    with TestClient(app) as c:
        result=c.post('/api/auth/login',json={'username':'admin','password':'test-secret'})
        assert result.status_code==200,result.text
        c.headers['X-CSRF-Token']=result.json()['csrf_token']
        yield c
    app.dependency_overrides.clear(); engine.dispose()

def field(tag='245',code='a',value='Тест'):
    return {'tag':tag,'ind1':'0' if tag=='245' else ' ','ind2':'0' if tag=='245' else ' ','subfields':[{'code':code,'value':value}]}
def payload(type_id):
    return {'type_id':type_id,'marc':{'leader':'00000nam a2200000   4500','fields':[field()]}}
def make_type(c):
    r=c.post('/api/types',json={'name':'Книга','config':[{'tag':'245','required':True}]}); assert r.status_code==201,r.text
    return r.json()['id']
def test_official_snapshot():
    path=Path(os.environ['MARC_PATH']).with_suffix('.source.html')
    raw=path.read_bytes()
    assert hashlib.sha256(raw).hexdigest()==DATA['sha256']
    assert parse(raw)==DATA
    assert len(DICTIONARY)==291
    assert DICTIONARY['245']['repeatable'] is False
    assert DICTIONARY['700']['repeatable'] is True
    assert len(DICTIONARY['245']['indicators'][1]['values'])==10
    assert 'historical_variants' in DICTIONARY['090']
def test_auth(client):
    assert client.get('/api/types',headers={'X-Admin-Key':'wrong'}).status_code==401

def test_roundtrip_hidden_repeat_order_search_and_conflict(client):
    id=make_type(client); p=payload(id)
    p['marc']['fields'] += [field('700',value='Автор А'),field('700',value='Автор Б'),field('999',value='Локальные данные')]
    for f in p['marc']['fields'][1:3]: f['ind1']='1'
    p['marc']['fields'][1]['subfields'] += [{'code':'e','value':'редактор'},{'code':'e','value':'переводчик'}]
    r=client.post('/api/records',json=p); assert r.status_code==201,r.text
    saved=r.json(); assert saved['marc']==p['marc']; assert saved['warnings']
    assert client.get('/api/records',params={'q':'автор б'}).json()[0]['id']==saved['id']
    assert client.get('/api/records',params={'q':'%'}).json()==[]
    assert client.put(f'/api/types/{id}',json={'name':'Книга','config':[]}).status_code==200
    body={'type_id':id,'version':saved['version'],'marc':saved['marc']}
    r=client.put(f"/api/records/{saved['id']}",json=body); assert r.status_code==200,r.text
    assert r.json()['marc']==p['marc']
    assert client.put(f"/api/records/{saved['id']}",json=body).status_code==409

@pytest.mark.parametrize('change,status',[
    (lambda p:p['marc']['fields'].append(field()),201),
    (lambda p:p['marc']['fields'][0]['subfields'].append({'code':'a','value':'duplicate'}),201),
    (lambda p:p['marc']['fields'][0].update(ind1='9'),201),
    (lambda p:p['marc'].update(leader='short'),422),
    (lambda p:p['marc'].update(fields=[]),201),
    (lambda p:p['marc']['fields'].append({'tag':'008','value':'short'}),422),
])
def test_validation(client,change,status):
    p=payload(make_type(client)); change(p)
    r=client.post('/api/records',json=p); assert r.status_code==status,r.text
    if status==201:
        assert r.json()['warnings']
        assert r.json()['marc']==p['marc']

def test_profile_validation(client):
    assert client.post('/api/types',json={'name':'Invalid','config':[{'tag':'999'}]}).status_code==422
    assert client.post('/api/types',json={'name':'Invalid','config':[{'tag':'245','subfields':['!']}]}).status_code==422
    make_type(client)
    assert client.post('/api/types',json={'name':'Книга','config':[]}).status_code==409

def test_classification(client):
    p=payload(make_type(client))
    p['marc']['fields'] += [field('080',value='004.8'),field('084',value='32.81'),field('650',value='Искусственный интеллект')]
    p['marc']['fields'][-1]['ind2']='4'
    p['marc']['fields'][-2]['subfields'].append({'code':'2','value':'rubbk'})
    r=client.post('/api/records',json=p); assert r.status_code==201,r.text
    for q in ('004.8','32.81','искусственный'):
        assert len(client.get('/api/records',params={'q':q}).json())==1

def test_local_profile_api_and_gost_preview(client):
    from app.worksheet import default_config
    response=client.post('/api/types',json={'name':'MARCSQL','config':default_config()})
    assert response.status_code==201,response.text
    p=payload(response.json()['id'])
    p['marc']['fields'][0]['subfields'].append({'code':'c','value':'И. И. Иванов'})
    p['marc']['fields'].append(field('952','d','Факультет'))
    r=client.post('/api/records',json=p)
    assert r.status_code==201,r.text
    assert r.json()['marc']['fields'][:len(p['marc']['fields'])]==p['marc']['fields']
    preview=client.post('/api/gost/preview',json={'marc':p['marc'],'kind':'single'})
    assert preview.status_code==200
    assert preview.json()['requires_review'] is True
    assert ' / И. И. Иванов' in preview.json()['text']
    assert 'Факультет' not in preview.json()['text']

def test_automatic_fields_api(client):
    from app.worksheet import default_config
    t=client.post('/api/types',json={'name':'Автоматические поля','config':default_config()}).json()
    saved=client.post('/api/records',json=payload(t['id']))
    assert saved.status_code==201,saved.text
    saved=saved.json(); fields={f['tag']:f for f in saved['marc']['fields']}
    assert len(fields['008']['value'])==40
    assert len(fields['005']['value'])==16
    number=fields['001']['value'];fields['001']['value']='replacement'
    updated=client.put('/api/records/'+str(saved['id']),json={k:saved[k] for k in ('type_id','version','marc')})
    assert updated.status_code==200,updated.text
    assert next(f['value'] for f in updated.json()['marc']['fields'] if f['tag']=='001')==number

def vocabulary_type(client,auto=True,name='Справочник',tag='080'):
    r=client.post('/api/types',json={'name':name,'config':[{'tag':'245','required':True},{'tag':tag,'subfields':['a'],'vocabularies':{'a':{'auto_add':auto}}}]})
    assert r.status_code==201,r.text
    return r.json()['id']

def test_vocabulary_manual_choice_and_description(client):
    t=vocabulary_type(client,False)
    entry=client.post(f'/api/types/{t}/vocabulary/080/a',json={'value':'3','label':'Общественные науки'})
    assert entry.status_code==201,entry.text
    p=payload(t);p['marc']['fields'].append(field('080',value='3'))
    saved=client.post('/api/records',json=p);assert saved.status_code==201,saved.text
    assert saved.json()['marc']['fields'][-1]['subfields'][0]['value']=='3'
    p['marc']['fields'][-1]['subfields'][0]['value']='unknown'
    manual=client.post('/api/records',json=p)
    assert manual.status_code==201,manual.text
    assert any('080$a:' in w for w in manual.json()['warnings'])
    entries=client.get(f'/api/types/{t}/vocabulary').json();assert len(entries)==1;assert entries[0]['label']=='Общественные науки'
    assert client.delete(f"/api/types/{t}/vocabulary/{entry.json()['id']}").status_code==204
    # Removing a suggestion never invalidates an unchanged existing record.
    body={k:saved.json()[k] for k in ('type_id','marc','version')}
    assert client.put('/api/records/'+str(saved.json()['id']),json=body).status_code==200

def test_vocabulary_auto_deduplicates_and_isolates_types(client):
    t=vocabulary_type(client);p=payload(t);p['marc']['fields']+=[field('080',value=' 378 '),field('080',value='378')]
    saved=client.post('/api/records',json=p);assert saved.status_code==201,saved.text
    entries=client.get(f'/api/types/{t}/vocabulary').json();assert len(entries)==1;assert entries[0]['value']=='378'
    assert saved.json()['marc']['fields'][-2]['subfields'][0]['value']==' 378 '
    other=vocabulary_type(client,name='Другой тип');assert client.get(f'/api/types/{other}/vocabulary').json()==[]
    assert client.delete(f"/api/types/{other}/vocabulary/{entries[0]['id']}").status_code==404
    # Failed validation and stale writes must not contribute values.
    invalid=payload(t);invalid['marc']['leader']='short';invalid['marc']['fields']=[field('080',value='999')]
    assert client.post('/api/records',json=invalid).status_code==422
    stale={k:saved.json()[k] for k in ('type_id','marc','version')};stale['version']=999;stale['marc']['fields'].append(field('080',value='777'))
    assert client.put('/api/records/'+str(saved.json()['id']),json=stale).status_code==409
    assert len(client.get(f'/api/types/{t}/vocabulary').json())==1

def test_manual_vocabulary_value_warns_without_adding_it_to_controlled_list(client):
    t=client.post('/api/types',json={'name':'Два справочника','config':[{'tag':'080','vocabularies':{'a':{'auto_add':True}}},{'tag':'260','vocabularies':{'b':{'auto_add':False}}}]}).json()['id']
    p=payload(t);p['marc']['fields'] += [field('080',value='new'),field('260','b','unknown')]
    saved=client.post('/api/records',json=p)
    assert saved.status_code==201,saved.text
    assert saved.json()['marc']==p['marc']
    assert any('260$b:' in w for w in saved.json()['warnings'])
    entries=client.get(f'/api/types/{t}/vocabulary').json()
    assert [(e['tag'],e['value']) for e in entries]==[('080','new')]
    assert len(client.get('/api/records',params={'type_id':t}).json())==1

def test_vocabulary_config_guards(client):
    for tag,code in [('005','_'),('080','Z')]:
        assert client.post('/api/types',json={'name':tag,'config':[{'tag':tag,'vocabularies':{code:{'auto_add':True}}}]}).status_code==422
    t=vocabulary_type(client)
    assert client.post(f'/api/types/{t}/vocabulary/080/a',json={'value':'  '}).status_code==422
    assert client.post(f'/api/types/{t}/vocabulary/260/b',json={'value':'No'}).status_code==422

def test_record_delete_requires_auth_and_current_version(client):
    t=make_type(client)
    first=client.post('/api/records',json=payload(t)).json()
    second=client.post('/api/records',json=payload(t)).json()
    endpoint='/api/records/'+str(first['id'])
    assert client.delete(endpoint+'?version=1',headers={'X-Admin-Key':'wrong'}).status_code==401
    assert client.delete(endpoint).status_code==422
    assert client.delete(endpoint+'?version=999').status_code==409
    assert client.get(endpoint).status_code==200
    assert client.delete(endpoint+'?version=1').status_code==204
    assert client.get(endpoint).status_code==404
    assert client.delete(endpoint+'?version=1').status_code==404
    assert client.get('/api/records/'+str(second['id'])).status_code==200
    assert any(x['id']==t for x in client.get('/api/types').json())

def test_delete_keeps_dictionary_and_rejects_stale_editor(client):
    t=vocabulary_type(client);p=payload(t);p['marc']['fields'].append(field('080',value='378'))
    original=client.post('/api/records',json=p).json();endpoint='/api/records/'+str(original['id'])
    body={k:original[k] for k in ('type_id','version','marc')}
    updated=client.put(endpoint,json=body).json()
    assert client.delete(endpoint+'?version='+str(original['version'])).status_code==409
    assert client.delete(endpoint+'?version='+str(updated['version'])).status_code==204
    assert client.get(f'/api/types/{t}/vocabulary').json()[0]['value']=='378'


def test_vocabulary_edit_selected_without_changing_dictionary(client):
    t=vocabulary_type(client,False)
    client.post(f'/api/types/{t}/vocabulary/080/a',json={'value':'3','label':'Общественные науки'})
    config=next(x for x in client.get('/api/types').json() if x['id']==t)
    config['config'][1]['vocabularies']['a']['allow_edit']=True
    saved_type=client.put(f'/api/types/{t}',json={k:config[k] for k in ('name','config')})
    assert saved_type.status_code==200,saved_type.text
    assert saved_type.json()['config'][1]['vocabularies']['a']['allow_edit'] is True
    p=payload(t);p['marc']['fields'].append(field('080',value='378.1'))
    result=client.post('/api/records',json=p);assert result.status_code==201,result.text
    saved=result.json();p['version']=saved['version'];p['marc']['fields'][-1]['subfields'][0]['value']='378.2'
    assert client.put(f"/api/records/{saved['id']}",json=p).status_code==200
    assert [x['value'] for x in client.get(f'/api/types/{t}/vocabulary').json()]==['3']
    config['config'][1]['vocabularies']['a']['allow_edit']=False
    assert client.put(f'/api/types/{t}',json={k:config[k] for k in ('name','config')}).status_code==200
    p.pop('version')
    manual=client.post('/api/records',json=p)
    assert manual.status_code==201,manual.text
    assert any('080$a:' in w for w in manual.json()['warnings'])
    config['config'][1]['vocabularies']['a'].update(allow_edit=True,auto_add=True)
    client.put(f'/api/types/{t}',json={k:config[k] for k in ('name','config')})
    assert client.post('/api/records',json=p).status_code==201
    assert set(x['value'] for x in client.get(f'/api/types/{t}/vocabulary').json())=={'3','378.2'}


@pytest.mark.parametrize('local',[False,True])
@pytest.mark.parametrize('tag',['100','245','440','650','700'])
def test_edit_imported_description_preserves_source_and_warns(client,local,tag):
    config=[{'tag':'245','required':True,'local':local}]
    if tag!='245': config.append({'tag':tag,'local':local})
    type_id=client.post('/api/types',json={'name':'Legacy','config':config}).json()['id']
    item='245  \x1faСтарое заглавие'
    if tag!='245': item+=f'\x1e{tag}  \x1faИсходное значение'
    imported=client.post('/api/import/marcsql',json={
        'source':'regression','doc_id':1,'type_id':type_id,
        'rectype':'a','biblevel':'m','item':item,'preview':False,
    })
    assert imported.status_code==200,imported.text
    endpoint=f"/api/records/{imported.json()['record_id']}"
    saved=client.get(endpoint).json()
    body={k:saved[k] for k in ('type_id','version','marc')}
    next(f for f in body['marc']['fields'] if f['tag']=='245')['subfields'][0]['value']='Уточнённое заглавие'
    updated=client.put(endpoint,json=body)
    assert updated.status_code==200,updated.text
    result=updated.json()
    assert result['marc']==body['marc']
    assert any(w.startswith(tag+':') and ('индикатор' in w or 'indicator' in w) for w in result['warnings'])
    assert client.get(endpoint+'/marcsql-source').json()['item']==item


@pytest.mark.parametrize('tag,ind1,ind2',[
    ('100',' ',' '),('245',' ',' '),('245','9','x'),
    ('440','1','x'),('650',' ',' '),('650','9','x'),('700','x',' '),
])
def test_nonstandard_description_indicators_save_as_warnings(client,tag,ind1,ind2):
    body=payload(make_type(client))
    if tag=='245': target=body['marc']['fields'][0]
    else:
        target=field(tag,value='Исходное значение')
        body['marc']['fields'].append(target)
    target.update(ind1=ind1,ind2=ind2)
    created=client.post('/api/records',json=body)
    assert created.status_code==201,created.text
    assert created.json()['marc']==body['marc']
    assert any(w.startswith(tag+':') and 'invalid indicator' in w for w in created.json()['warnings'])
    endpoint=f"/api/records/{created.json()['id']}"
    body['version']=created.json()['version']
    target['ind1']='z'
    updated=client.put(endpoint,json=body)
    assert updated.status_code==200,updated.text
    assert updated.json()['marc']==body['marc']
    assert any(w.startswith(tag+':') and 'invalid indicator 1' in w for w in updated.json()['warnings'])


@pytest.mark.parametrize('change',[
    lambda m:m.update(leader='short'),
    lambda m:m.update(leader='я'*24),
    lambda m:m['fields'][0].update(ind1=''),
    lambda m:m['fields'][0].update(ind1='12'),
    lambda m:m['fields'][0].update(ind1='я'),
    lambda m:m['fields'][0].update(ind1=None),
    lambda m:m['fields'][0].update(value='wrong structure'),
    lambda m:m['fields'][0].update(subfields=None),
    lambda m:m['fields'].append({'tag':'008','value':'short'}),
    lambda m:m['fields'].append({'tag':'006','value':'short'}),
    lambda m:m['fields'].append({'tag':'001','value':'id','ind1':' '}),
    lambda m:m['fields'].append({'tag':'000','value':'not a field'}),
    lambda m:m['fields'].append({'tag':'bad','value':'not a tag'}),
])
def test_structural_errors_still_block_without_changing_record(client,change):
    saved=client.post('/api/records',json=payload(make_type(client))).json()
    endpoint=f"/api/records/{saved['id']}"
    body=copy.deepcopy({k:saved[k] for k in ('type_id','version','marc')})
    change(body['marc'])
    rejected=client.put(endpoint,json=body)
    assert rejected.status_code==422,rejected.text
    unchanged=client.get(endpoint).json()
    assert unchanged['version']==saved['version']
    assert unchanged['marc']==saved['marc']


@pytest.mark.parametrize('tag,code',[('001',None),('005',None),('008',None),('990',None),('990','d')])
def test_automatic_field_duplicates_still_block(client,tag,code):
    from app.worksheet import default_config
    t=client.post('/api/types',json={'name':'Служебные поля','config':default_config()}).json()
    saved=client.post('/api/records',json=payload(t['id'])).json()
    body=copy.deepcopy({k:saved[k] for k in ('type_id','version','marc')})
    target=next(f for f in body['marc']['fields'] if f['tag']==tag)
    if code:
        target['subfields'].append(copy.deepcopy(next(s for s in target['subfields'] if s['code']==code)))
    else:
        body['marc']['fields'].append(copy.deepcopy(target))
    rejected=client.put(f"/api/records/{saved['id']}",json=body)
    assert rejected.status_code==422,rejected.text
    assert 'not repeatable' in str(rejected.json()['detail'])


def test_fixed_width_description_codes_warn_without_rewriting(client):
    body=payload(make_type(client))
    value='261120sabcd    kz '+'|'*17+'RUS'+'||'
    assert len(value)==40
    body['marc']['fields'].append({'tag':'008','value':value})
    created=client.post('/api/records',json=body)
    assert created.status_code==201,created.text
    assert created.json()['marc']==body['marc']
    assert any('первая дата' in w for w in created.json()['warnings'])
    assert any('язык' in w for w in created.json()['warnings'])
    body['version']=created.json()['version']
    body['marc']['fields'][-1]['value']=value[:35]+'KAZ'+value[38:]
    updated=client.put(f"/api/records/{created.json()['id']}",json=body)
    assert updated.status_code==200,updated.text
    assert updated.json()['marc']==body['marc']
    assert any('язык' in w for w in updated.json()['warnings'])
