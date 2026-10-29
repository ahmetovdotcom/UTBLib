import time
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_catalog import client,make_type,payload
from app.main import app,db
from app.db import User,UserSession,UserAudit
from app.security import password_hash,verify,permission_for


def add(client,**kw):
    body={'username':'reader','display_name':'Читатель','password':'strong-password','role':'viewer','permissions':['catalog.view'],**kw}
    r=client.post('/api/users',json=body);assert r.status_code==201,r.text
    return r.json()

def login(c,name='reader',password='strong-password'):
    r=c.post('/api/auth/login',json={'username':name,'password':password});assert r.status_code==200,r.text
    c.headers['X-CSRF-Token']=r.json()['csrf_token'];return r


def test_cookie_login_logout_expiry_and_password(client):
    add(client)
    with TestClient(app) as c:
        assert c.get('/api/records').status_code==401
        assert c.post('/api/auth/login',json={'username':'reader','password':'wrong'}).status_code==401
        response=login(c)
        cookie=response.headers['set-cookie'];assert 'HttpOnly' in cookie and 'SameSite=strict' in cookie
        assert c.get('/api/auth/me').json()['user']['username']=='reader'
        assert c.post('/api/auth/password',json={'current_password':'wrong','new_password':'new-password'}).status_code==400
        assert c.post('/api/auth/password',json={'current_password':'strong-password','new_password':'new-password'}).status_code==204
        assert c.get('/api/auth/me').status_code==401
        login(c,password='new-password')
        assert c.post('/api/auth/logout').status_code==204
        assert c.get('/api/records').status_code==401
        login(c,password='new-password')
        gen=app.dependency_overrides[db]();s=next(gen)
        try:
            u=s.scalar(select(User).where(User.username=='reader'))
            for session in s.scalars(select(UserSession).where(UserSession.user_id==u.id)): session.expires_at=int(time.time())-1
            s.commit()
        finally: gen.close()
        assert c.get('/api/records').status_code==401


def test_permissions_enforced_on_server_and_csrf(client):
    t=make_type(client);saved=client.post('/api/records',json=payload(t)).json();add(client)
    with TestClient(app) as c:
        login(c)
        assert c.get('/api/records').status_code==200
        assert c.get(f"/api/records/{saved['id']}/copies").status_code==200
        for method,path in [('POST','/api/records'),('PUT',f"/api/records/{saved['id']}"),('DELETE',f"/api/records/{saved['id']}?version=1"),('POST',f"/api/records/{saved['id']}/copies"),('PUT','/api/copies/1'),('POST','/api/types'),('POST','/api/acquisitions'),('GET','/api/acquisitions'),('POST','/api/withdrawals'),('GET','/api/withdrawals'),('GET','/api/users'),('POST','/api/import/marcsql')]:
            assert c.request(method,path,json={}).status_code==403,(method,path)
        assert c.post('/api/auth/logout',headers={'X-CSRF-Token':''}).status_code==403
        assert c.post('/api/auth/logout',headers={'Origin':'https://evil.example'}).status_code==403
        assert c.post('/api/auth/login',headers={'Origin':'https://evil.example'},json={'username':'reader','password':'strong-password'}).status_code==403


def test_custom_rights_no_privilege_escalation_or_embedded_acquisition(client):
    t=make_type(client);add(client,role='librarian',permissions=['catalog.edit'])
    with TestClient(app) as c:
        login(c)
        assert c.post('/api/records',json=payload(t)).status_code==201
        assert c.post('/api/users',json={'username':'evil','role':'admin'}).status_code==403
        p=payload(t);p['initial_acquisition']={'received_on':'2026-10-20','currency':'KZT'}
        assert c.post('/api/records',json=p).status_code==403
        assert c.post('/api/types',json={'name':'no','config':[]}).status_code==403


def test_admin_changes_revoke_sessions_unique_login_and_last_admin(client):
    user=add(client)
    assert client.post('/api/users',json={'username':'READER','display_name':'Другой','password':'strong-password'}).status_code==409
    with TestClient(app) as c:
        login(c)
        before=client.get('/api/users').json()['items'];root=next(u for u in before if u['role']=='admin')
        root.pop('id');root['active']=False
        assert client.put('/api/users/1',json=root).status_code==409
        body={k:v for k,v in user.items() if k!='id'};body['permissions']=['catalog.edit'];body['role']='librarian'
        assert client.put('/api/users/'+str(user['id']),json=body).status_code==200
        assert c.get('/api/records').status_code==401
        assert client.put('/api/users/'+str(user['id']),json=body).status_code==409
        login(c)
        fresh=next(u for u in client.get('/api/users').json()['items'] if u['id']==user['id']);fresh.pop('id');fresh['active']=False
        assert client.put('/api/users/'+str(user['id']),json=fresh).status_code==200
        assert c.get('/api/records').status_code==401
        assert c.post('/api/auth/login',json={'username':'reader','password':'strong-password'}).status_code==401
    assert 'password_hash' not in str(client.get('/api/users').json())
    assert 'strong-password' not in str(client.get('/api/users/audit').json())


def test_import_key_is_not_browser_backdoor(client):
    with TestClient(app,headers={'X-Admin-Key':'test-secret'}) as c:
        assert c.get('/api/records').status_code==403
        assert c.post('/api/users',json={}).status_code==401
        assert c.post('/api/import/marcsql',json={}).status_code==422 # accepted auth, schema rejected
        assert c.get('/api/auth/me').status_code==401


def test_login_throttle_and_hashes(client):
    add(client)
    with TestClient(app) as c:
        for i in range(10): assert c.post('/api/auth/login',json={'username':'reader','password':'bad'}).status_code==401
        assert c.post('/api/auth/login',json={'username':'reader','password':'strong-password'}).status_code==429
    hashed=password_hash('abc')
    assert hashed!=password_hash('abc') and verify('abc',hashed) and not verify('wrong',hashed)


def test_every_protected_business_route_has_permission():
    from app.public_catalog import PUBLIC_PATHS
    from app.site_content import PUBLIC_PATHS as CONTENT_PATHS
    PUBLIC_PATHS = PUBLIC_PATHS | CONTENT_PATHS
    for route in app.routes:
        path=getattr(route,'path','')
        if path in PUBLIC_PATHS:
            assert route.methods == {'GET'}
            continue
        if not path.startswith('/api/') or path=='/api/health' or path.startswith(('/api/auth/','/api/users')): continue
        import re
        path=re.sub(r'\{[^}]+\}','1',path)
        for method in route.methods: assert permission_for(method,path)


def test_delete_user_revokes_access_preserves_audit_and_rejects_restore(client):
    user=add(client)
    with TestClient(app) as c:
        login(c)
        url='/api/users/'+str(user['id'])
        assert c.delete(url+'?version=1').status_code==403
        assert client.delete(url).status_code==422
        assert client.delete(url+'?version=999').status_code==409
        assert client.delete(url+'?version=1',headers={'X-CSRF-Token':''}).status_code==403
        assert client.delete(url+'?version=1').status_code==204
        assert c.get('/api/records').status_code==401
        assert c.post('/api/auth/login',json={'username':'reader','password':'strong-password'}).status_code==401
        assert user['id'] not in [u['id'] for u in client.get('/api/users').json()['items']]
        assert client.delete(url+'?version=2').status_code==404
        body={k:v for k,v in user.items() if k!='id'};body['version']=2;body['active']=True
        assert client.put(url,json=body).status_code==404
        assert any(a['action']=='delete' and a['target_id']==user['id'] for a in client.get('/api/users/audit').json())
        assert client.post('/api/users',json={'username':'reader','display_name':'New','password':'new-password'}).status_code==409


def test_delete_last_admin_and_self_delete_when_another_exists(client):
    root=client.get('/api/auth/me').json()['user'];url=f"/api/users/{root['id']}?version={root['version']}"
    assert client.delete(url).status_code==409
    add(client,username='anotheradmin',role='admin')
    assert client.delete(url).status_code==204
    assert client.get('/api/auth/me').status_code==401
    with TestClient(app) as c:
        login(c,'anotheradmin')
        assert len(c.get('/api/users').json()['items'])==1


def test_operator_manual_value_preserved(client):
    from app.worksheet import default_config
    from uuid import uuid4
    t=client.post('/api/types',json={'name':'Оператор','config':default_config()}).json()['id']
    author=add(client,username='cataloguer',display_name='Иванов Иван Иванович',role='librarian',permissions=['catalog.edit'])
    with TestClient(app) as c:
        login(c,'cataloguer')
        p=payload(t);p['request_key']=str(uuid4())
        p['marc']['fields'][0]['subfields'].append({'code':'c','value':'Сведения об ответственности'})
        p['marc']['fields'].append({'tag':'097','ind1':' ','ind2':' ','subfields':[{'code':'b','value':'Петров Пётр Петрович'}]})
        r=c.post('/api/records',json=p);assert r.status_code==201,r.text
        saved=r.json()
        def operator(record):return [sf['value'] for f in record['marc']['fields'] if f['tag']=='097' for sf in f.get('subfields',[]) if sf['code']=='b']
        assert operator(saved)==['Петров Пётр Петрович']
        assert c.post('/api/records',json=p).json()['id']==saved['id']
        # A different user edits the record without changing its original operator.
        body={k:saved[k] for k in ('type_id','version','marc')}
        edited=client.put('/api/records/'+str(saved['id']),json=body);assert edited.status_code==200,edited.text
        assert operator(edited.json())==['Петров Пётр Петрович']
        cleared={k:edited.json()[k] for k in ('type_id','version','marc')}
        cleared['marc']['fields']=[f for f in cleared['marc']['fields'] if f['tag']!='097']
        cleared['request_key']=str(uuid4())
        cleared.pop('version')
        empty=c.post('/api/records',json=cleared)
        assert empty.status_code==201,empty.text
        assert not any(operator(empty.json()))
        # The operator remains a name snapshot after the account is deleted.
        assert client.delete('/api/users/'+str(author['id'])+'?version=1').status_code==204
        assert operator(client.get('/api/records/'+str(saved['id'])).json())==['Петров Пётр Петрович']
