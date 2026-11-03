from copy import deepcopy
import pytest
from test_catalog import client, field, payload
from test_settings_transfer import export, preview, apply
from app.main import DICTIONARY
from app.worksheet import definitions, default_config
from app.book_photos import configured_fields
from app.repeatability import configured_spec
from app.validation import validate_marc


def create_type(client, config):
    r=client.post('/api/types',json={'name':'Повторение','config':config})
    assert r.status_code==201,r.text
    return r.json()['id']


def update_record(client, record):
    return client.put(f"/api/records/{record['id']}",json={k:record[k] for k in ('type_id','version','marc')})


def test_specialty_repeats_by_default_and_survives_disabling(client):
    config=default_config()
    t=create_type(client,config)
    body=payload(t)
    body['marc']['fields'].append(field('952','j','Финансы'))
    body['marc']['fields'][-1]['subfields'].append({'code':'j','value':'Экономика'})
    r=client.post('/api/records',json=body)
    assert r.status_code==201,r.text
    saved=r.json()
    cfg=next(c for c in config if c['tag']=='952')
    cfg['subfield_repeatable']={'j':False}
    assert client.put(f'/api/types/{t}',json={'name':'Повторение','config':config}).status_code==200
    # Existing values can be edited and saved after disabling; neither is lost.
    specialty=next(f for f in saved['marc']['fields'] if f['tag']=='952')
    specialty['subfields'][1]['value']='Менеджмент'
    r=update_record(client,saved)
    assert r.status_code==200,r.text
    saved=r.json()
    assert next(f for f in saved['marc']['fields'] if f['tag']=='952')['subfields']==specialty['subfields']
    assert any('повторения' in w for w in saved['warnings'])
    third=deepcopy(saved)
    next(f for f in third['marc']['fields'] if f['tag']=='952')['subfields'].append({'code':'j','value':'Туризм'})
    assert update_record(client,third).status_code==422
    # A fresh record gets no legacy allowance.
    assert client.post('/api/records',json=body).status_code==422
    cfg['subfield_repeatable']['j']=True
    client.put(f'/api/types/{t}',json={'name':'Повторение','config':config})
    assert update_record(client,third).status_code==200


def test_field_and_subfield_overrides_are_independent_and_type_scoped(client):
    cfg={'tag':'245','repeatable':True,'subfield_repeatable':{'a':True}}
    t=create_type(client,[cfg])
    p=payload(t);p['marc']['fields'][0]['subfields'].append({'code':'a','value':'Второе'})
    p['marc']['fields'].append(field(value='Другое поле'))
    r=client.post('/api/records',json=p);assert r.status_code==201,r.text
    saved=r.json()
    assert DICTIONARY['245']['repeatable'] is False
    assert next(s for s in DICTIONARY['245']['subfields'] if s['code']=='a')['repeatable'] is False
    other=client.post('/api/types',json={'name':'Без настройки','config':[{'tag':'245'}]}).json()['id']
    p['type_id']=other
    assert client.post('/api/records',json=p).status_code==422
    cfg['repeatable']=False;cfg['subfield_repeatable']['a']=False
    client.put(f'/api/types/{t}',json={'name':'Повторение','config':[cfg]})
    saved['marc']['fields'].reverse()
    r=update_record(client,saved);assert r.status_code==200,r.text
    saved=r.json();saved['marc']['fields'].append(field(value='Третье'))
    assert update_record(client,saved).status_code==422
    p=payload(t);p['marc']['fields'].append(field(value='Второе'))
    assert client.post('/api/records',json=p).status_code==422
    # Re-enable field only: multiple fields allowed, repeated $a still rejected.
    cfg['repeatable']=True
    client.put(f'/api/types/{t}',json={'name':'Повторение','config':[cfg]})
    assert client.post('/api/records',json=p).status_code==201
    p['marc']['fields'][0]['subfields'].append({'code':'a','value':'Повтор'})
    assert client.post('/api/records',json=p).status_code==422


def test_cloning_old_repeated_group_does_not_grant_new_subfield_repeats():
    config=[{'tag':'700','required':False,'repeatable':True,'subfield_repeatable':{'a':False}}]
    previous=payload(1)['marc']
    f=field('700',value='Автор');f['ind1']='1';f['subfields'].append({'code':'a','value':'Второй'})
    previous['fields'].append(f)
    current=deepcopy(previous);current['fields'].append(deepcopy(f))
    errors,_=validate_marc(current,config,DICTIONARY,previous)
    assert '700$a: not repeatable' in errors
    current['fields'][-1]['subfields'].pop()
    assert validate_marc(current,config,DICTIONARY,previous)[0]==[]


@pytest.mark.parametrize('cfg',[
    {'tag':'001','repeatable':True}, {'tag':'000','repeatable':True},
    {'tag':'005','repeatable':True}, {'tag':'008','repeatable':True},
    {'tag':'990','local':True,'repeatable':True},
    {'tag':'990','local':True,'subfield_repeatable':{'d':True}},
    {'tag':'245','subfield_repeatable':{'!':True}},
    {'tag':'245','repeatable':'yes'}, {'tag':'245','subfield_repeatable':{'a':'false'}},
])
def test_rejects_invalid_or_automatic_repetition(client,cfg):
    assert client.post('/api/types',json={'name':'Invalid','config':[cfg]}).status_code==422


def test_settings_transfer_and_ai_use_same_rules(client):
    config=[{'tag':'245'}, {'tag':'952','local':True,'repeatable':False,'subfields':['j'],
        'subfield_repeatable':{'j':True}}]
    t=create_type(client,config)
    bundle=export(client)
    client.put(f'/api/types/{t}',json={'name':'Повторение','config':[{'tag':'245'}]})
    assert apply(client,bundle,preview(client,bundle)).status_code==200
    restored=client.get('/api/types').json()[0]['config']
    local=definitions(DICTIONARY)
    assert next(c for c in restored if c['tag']=='952')['subfield_repeatable']=={'j':True}
    assert configured_fields(restored,DICTIONARY,local)['952$j']['repeatable'] is True
    restored[-1]['subfield_repeatable']['j']=False
    assert configured_fields(restored,DICTIONARY,local)['952$j']['repeatable'] is False
    assert next(s for s in local['952']['subfields'] if s['code']=='j')['repeatable'] is True
    assert configured_spec(local['952'],restored[-1])['repeatable'] is False
