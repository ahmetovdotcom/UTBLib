from test_catalog import client,make_type,payload
from app.statistics import comparable

def test_statistics_work_and_noop(client):
    body=payload(make_type(client))
    r=client.post('/api/records',json=body).json()
    def save():
        nonlocal r
        response=client.put('/api/records/'+str(r['id']),json={k:r[k] for k in ('type_id','version','marc')})
        assert response.status_code==200,response.text
        r=response.json()
    save()
    data=client.get('/api/statistics/staff').json()
    assert data['summary']=={'created':1,'updated':0,'processed':1,'operations':1}
    r['marc']['fields'][0]['subfields'][0]['value']='Новое заглавие';save()
    r['marc']['fields'][0]['subfields'][0]['value']='Другое заглавие';save()
    data=client.get('/api/statistics/staff').json()
    assert data['summary']=={'created':1,'updated':1,'processed':1,'operations':3}
    assert data['rows'][0]['operations']==2
    assert data['rows'][0]['title']=='Другое заглавие'
    assert client.get('/api/statistics/staff?date_from=2100-01-01').json()['total']==0
    assert client.get('/api/statistics/staff?date_from=2026-12-01&date_to=2026-01-01').status_code==422
    assert client.delete(f"/api/records/{r['id']}?version={r['version']}").status_code==204
    data=client.get('/api/statistics/staff').json()
    assert data['summary']['created']==1 and not data['rows'][0]['exists']

def test_technical_changes_ignored():
    a={'leader':'00000nam a2200000   4500','fields':[{'tag':'005','value':'old'}]}
    b={'leader':'00000cam a2200000   4500','fields':[{'tag':'005','value':'new'}]}
    assert comparable(a)==comparable(b)

def test_identity_permissions_and_failed_save(client):
    from fastapi.testclient import TestClient
    from test_security import add,login
    from app.main import app
    t=make_type(client)
    u=add(client,permissions=['catalog.edit'])
    with TestClient(app) as c:
        login(c)
        assert c.get('/api/statistics/staff').status_code==403
        body=payload(t)
        body['marc']['fields'].append({'tag':'097','ind1':' ','ind2':' ','subfields':[{'code':'b','value':'Чужое ФИО'}]})
        r=c.post('/api/records',json=body)
        assert r.status_code==201,r.text
        saved=r.json()
        bad={**body,'version':999}
        assert c.put('/api/records/'+str(saved['id']),json=bad).status_code==409
    data=client.get('/api/statistics/staff').json()
    assert data['summary']['operations']==1
    assert data['employees'][0]['actor_id']==u['id']
    assert data['rows'][0]['name']=='Читатель'
    assert client.get('/api/statistics/staff',params={'user_id':u['id'],'action':'created','limit':1}).json()['total']==1
    assert client.get('/api/statistics/staff?user_id=999').json()['total']==0

def test_retry_and_local_date_boundary(client):
    from uuid import uuid4
    from datetime import datetime,timezone
    from sqlalchemy import select
    from app.main import app,db
    from app.db import RecordActivity
    body=payload(make_type(client));body['request_key']=str(uuid4())
    first=client.post('/api/records',json=body)
    assert first.status_code==201
    assert client.post('/api/records',json=body).json()['id']==first.json()['id']
    gen=app.dependency_overrides[db]();s=next(gen)
    try:
        event=s.scalar(select(RecordActivity));event.created_at=datetime(2026,10,20,19,0,tzinfo=timezone.utc);s.commit()
    finally:gen.close()
    assert client.get('/api/statistics/staff?date_from=2026-10-21&date_to=2026-10-21').json()['total']==1
    assert client.get('/api/statistics/staff?date_to=2026-10-20').json()['total']==0
