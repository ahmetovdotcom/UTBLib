from fastapi.testclient import TestClient
from test_catalog import client,payload
from test_security import add,login
from app.main import app
from app.worksheet import default_config
from app.catalog_vocabularies import LITERATURE

def test_literature_and_dynamic_staff(client):
    t=client.post('/api/types',json={'name':'Книга','config':default_config()}).json()['id']
    def entries():return client.get(f'/api/types/{t}/vocabulary').json()
    actual={e['value']:e['label'] for e in entries() if (e['tag'],e['code'])==('952','a')}
    assert actual==dict(LITERATURE) and len(actual)==35
    u=add(client,display_name='Сотрудник Новый')
    assert any(e['value']=='Сотрудник Новый' and e['managed'] for e in entries())
    assert client.delete(f"/api/users/{u['id']}?version=1").status_code==204
    assert not any(e['value']=='Сотрудник Новый' for e in entries())

def test_operator_preserved_on_real_edit_and_manual_change_audited(client):
    t=client.post('/api/types',json={'name':'Книга','config':default_config()}).json()['id']
    editor=add(client,display_name='Редактор Новый',permissions=['catalog.edit'])
    colleague=add(client,username='colleague',display_name='Коллега из справочника')
    p=payload(t);p['marc']['fields'][0]['subfields'].append({'code':'c','value':'Автор'})
    p['marc']['fields'].append({'tag':'097','ind1':' ','ind2':' ','subfields':[{'code':'b','value':'Прежний оператор'}]})
    r=client.post('/api/records',json=p);assert r.status_code==201,r.text
    saved=r.json()
    def operator(r):return [s['value'] for f in r['marc']['fields'] if f['tag']=='097' for s in f['subfields'] if s['code']=='b']
    with TestClient(app) as c:
        login(c)
        body={k:saved[k] for k in ('type_id','version','marc')}
        unchanged=c.put('/api/records/'+str(saved['id']),json=body);assert unchanged.status_code==200,unchanged.text
        assert operator(unchanged.json())==['Прежний оператор']
        body={k:unchanged.json()[k] for k in ('type_id','version','marc')}
        body['marc']['fields'][0]['subfields'][0]['value']='Новое заглавие'
        changed=c.put('/api/records/'+str(saved['id']),json=body);assert changed.status_code==200,changed.text
        assert operator(changed.json())==['Прежний оператор']
        assert c.put('/api/records/'+str(saved['id']),json=body).status_code==409
        # A suggested colleague and an arbitrary name are equally valid metadata.
        for name in (colleague['display_name'],'Оператор без учётной записи'):
            body={k:changed.json()[k] for k in ('type_id','version','marc')}
            next(f for f in body['marc']['fields'] if f['tag']=='097')['subfields'][0]['value']=name
            changed=c.put('/api/records/'+str(saved['id']),json=body)
            assert changed.status_code==200,changed.text
            assert operator(changed.json())==[name]
        body={k:changed.json()[k] for k in ('type_id','version','marc')}
        body['marc']['fields'][0]['subfields'][0]['value']='Последующее исправление'
        changed=c.put('/api/records/'+str(saved['id']),json=body)
        assert changed.status_code==200,changed.text
        assert operator(changed.json())==['Оператор без учётной записи']
        # Saving an unchanged description does not add a staff operation.
        body={k:changed.json()[k] for k in ('type_id','version','marc')}
        assert c.put('/api/records/'+str(saved['id']),json=body).status_code==200
    stats=client.get('/api/statistics/staff').json()
    assert stats['summary']['updated']==1
    updates=[row for row in stats['rows'] if row['action']=='updated']
    assert len(updates)==1
    assert updates[0]['actor_id']==editor['id']
    assert updates[0]['name']=='Редактор Новый'
    assert updates[0]['operations']==4
    assert all(row['actor_id']!=colleague['id'] for row in stats['rows'])
