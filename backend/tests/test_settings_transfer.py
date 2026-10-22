from copy import deepcopy
from fastapi.testclient import TestClient
from test_catalog import client,make_type,payload,field
from test_security import add,login
from app.main import app


def export(c):
    r=c.get('/api/settings-transfer/export');assert r.status_code==200,r.text;return r.json()
def preview(c,bundle):
    r=c.post('/api/settings-transfer/preview',json=bundle);assert r.status_code==200,r.text;return r.json()
def apply(c,bundle,p):return c.post('/api/settings-transfer/apply',json={'bundle':bundle,'expected_state':p['expected_state'],'expected_bundle':p['expected_bundle']})
def settings(name='Книга'):
    return {'name':name,'config':[{'tag':'245','required':True},{'tag':'080','subfields':['a'],'vocabularies':{'a':{'auto_add':True,'allow_edit':True}}}],'entries':[{'tag':'080','code':'a','value':'3','label':'Из файла'}]}
def bundle(*types):return {'format':'utblib-settings','version':1,'types':list(types)}


def test_preview_and_apply_preserve_records_ids_labels_other_types(client):
    client.post('/api/types',json={'name':'Остаётся','config':[]})
    t=make_type(client)
    p=payload(t);p['marc']['fields'].append(field('080',value='378'))
    record=client.post('/api/records',json=p).json();before=client.get(f"/api/records/{record['id']}").json()
    cfg=settings();client.put(f'/api/types/{t}',json={'name':cfg['name'],'config':cfg['config']})
    client.post(f'/api/types/{t}/vocabulary/080/a',json={'value':'3','label':'На сервере'})
    b=bundle(settings(),settings('Новый'))
    old=export(client);plan=preview(client,b)
    assert export(client)==old
    assert plan['types'][0]['labels_preserved']==1
    assert apply(client,b,plan).status_code==200
    types=client.get('/api/types').json();assert len(types)==3
    assert next(x for x in types if x['name']=='Книга')['id']==t
    assert client.get(f"/api/records/{record['id']}").json()==before
    entries=client.get(f'/api/types/{t}/vocabulary').json()
    assert {e['value']:e['label'] for e in entries}=={'3':'На сервере','378':''}
    assert apply(client,b,preview(client,b)).status_code==200
    assert len(client.get(f'/api/types/{t}/vocabulary').json())==2
    saved=export(client);assert saved['version']==1
    assert all('id' not in x for x in saved['types'])
    assert preview(client,saved)


def test_invalid_bundle_and_stale_preview_write_nothing(client):
    make_type(client);b=bundle(settings());p=preview(client,b)
    changed=deepcopy(b);changed['types'][0]['name']='Подмена'
    assert apply(client,changed,p).status_code==409
    client.post('/api/types',json={'name':'Параллельное изменение','config':[]})
    old=export(client)
    assert apply(client,b,p).status_code==409
    bad=bundle(settings('Первый'),settings('Второй'));bad['types'][1]['config'][0]['tag']='999'
    assert client.post('/api/settings-transfer/preview',json=bad).status_code==422
    assert export(client)==old
    assert client.post('/api/settings-transfer/preview',json=bundle(settings(),settings())).status_code==422
    wrong=deepcopy(b);wrong['version']=2
    assert client.post('/api/settings-transfer/preview',json=wrong).status_code==422
    wrong=deepcopy(b);wrong['types'][0]['id']=123
    assert client.post('/api/settings-transfer/preview',json=wrong).status_code==422


def test_hidden_entries_exported_operator_names_excluded_and_permissions(client):
    make_type(client);b=bundle(settings());assert apply(client,b,preview(client,b)).status_code==200
    t=client.get('/api/types').json()[0]['id']
    client.put(f'/api/types/{t}',json={'name':'Книга','config':[{'tag':'245'}]})
    saved=export(client);assert saved['types'][0]['entries'][0]['value']=='3'
    assert preview(client,saved)
    bad=deepcopy(saved);bad['types'][0]['entries'].append({'tag':'097','code':'b','value':'Старый оператор'})
    assert client.post('/api/settings-transfer/preview',json=bad).status_code==422
    add(client)
    with TestClient(app) as c:
        login(c)
        assert c.get('/api/settings-transfer/export').status_code==403
        assert c.post('/api/settings-transfer/preview',json=saved).status_code==403
        assert apply(c,saved,preview(client,saved)).status_code==403
    assert client.get('/api/settings-transfer/export',headers={'X-Admin-Key':'test-secret'}).status_code==403
