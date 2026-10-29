from datetime import timedelta
from io import BytesIO
from PIL import Image
from fastapi.testclient import TestClient
from test_catalog import client
from test_security import add, login
from app.main import app
from app.db import utcnow


def body(kind='news', status='draft', **data):
    return {'kind': kind, 'slug': 'first-item', 'status': status, 'data': {
        'translations': {'ru': {'title': 'Новость', 'body': '<script>alert(1)</script>\n\nТекст'}, 'kk': {'title': 'Жаңалық'}}, **data}}


def change(c, row, **fields):
    payload = {k: row[k] for k in ('kind', 'slug', 'status', 'version', 'published_at', 'data')}
    payload.update(fields)
    return c.put('/api/site-content/'+str(row['id']), json=payload)


def test_publication_schedule_archive_version_and_privacy(client):
    r = client.post('/api/site-content', json=body()); assert r.status_code == 201, r.text
    row = r.json(); path = '/api/public/v1/content/news/first-item'
    with TestClient(app) as guest:
        assert guest.get(path).status_code == 404
        assert guest.get('/api/site-content?kind=news').status_code == 401
        scheduled = change(client, row, status='published', published_at=(utcnow()+timedelta(days=1)).isoformat()).json()
        assert guest.get(path).status_code == 404
        assert guest.get('/api/public/v1/content/news').json()['meta']['total'] == 0
        published = change(client, scheduled, published_at=(utcnow()-timedelta(seconds=2)).isoformat()).json()
        response = guest.get(path); assert response.status_code == 200, response.text
        assert response.json()['data']['data']['translations']['kk']['title'] == 'Жаңалық'
        for field in ('actor_id', 'version', 'updated_at', 'snapshot'):
            assert field not in response.text
        assert change(client, scheduled, status='draft').status_code == 409
        assert client.post('/api/site-content', json=body()).status_code == 409
        assert change(client, published, status='archived').status_code == 200
        assert guest.get(path).status_code == 404
        assert guest.post('/api/public/v1/content/news', json=body()).status_code == 405


def test_content_permissions_csrf_and_input_validation(client):
    add(client)
    with TestClient(app) as c:
        login(c)
        assert c.get('/api/site-content?kind=news').status_code == 403
        assert c.post('/api/site-content', json=body()).status_code == 403
    assert client.post('/api/site-content', json=body(), headers={'X-CSRF-Token': ''}).status_code == 403
    for invalid in (body('resources','published'), body('events','published'), body('resources',url='javascript:alert(1)'), body('resources',url='https://user:password@example.test')):
        assert client.post('/api/site-content', json=invalid).status_code == 422
    p=body('events', 'published', starts_at=(utcnow()+timedelta(days=2)).isoformat(), ends_at=utcnow().isoformat())
    assert client.post('/api/site-content', json=p).status_code == 422


def test_assets_follow_publication_access_embargo_and_revoke(client):
    row=client.post('/api/site-content', json=body('repository')).json()
    path=f"/api/site-content/{row['id']}/assets/pdf"
    assert client.put(path+'?version=1', content=b'bad').status_code == 422
    pdf=b'%PDF-1.4\n%%EOF'
    r=client.put(path+'?version=1', content=pdf); assert r.status_code == 200, r.text
    row=r.json(); public=f"/api/public/v1/content-assets/{row['id']}/pdf"
    assert client.get(public).status_code == 404
    row=change(client,row,status='published').json()
    assert client.get(public).status_code == 404
    assert row['assets']['pdf']['url'] is None
    data=row['data']; data['access_policy']='full_public'; data['embargo_until']=(utcnow()+timedelta(days=1)).isoformat()
    row=change(client,row,data=data).json(); assert client.get(public).status_code == 404
    data['embargo_until']=None
    row=change(client,row,data=data).json()
    r=client.get(public); assert r.status_code == 200 and r.content == pdf
    assert r.headers['cache-control']=='no-store'
    row=change(client,row,status='draft').json(); assert client.get(public).status_code == 404
    assert client.delete(path+'?version=1').status_code == 409
    assert client.delete(path+'?version='+str(row['version'])).json()['assets'] == {}


def test_images_are_reencoded_and_lists_paginate(client):
    row=client.post('/api/site-content', json=body('resources','published',url='https://example.org')).json()
    path=f"/api/site-content/{row['id']}/assets/image?version=1"
    assert client.put(path,content=b'<svg onload="alert(1)">').status_code == 422
    image=BytesIO(); Image.new('RGB',(5,5),'red').save(image,'PNG')
    result=client.put(path,content=image.getvalue()); assert result.status_code == 200, result.text
    assert client.get(f"/api/public/v1/content-assets/{row['id']}/image").headers['content-type']=='image/jpeg'
    for n in range(2):
        p=body('resources','published',url='https://example.org'); p['slug']=f'item-{n}'
        assert client.post('/api/site-content',json=p).status_code == 201
    response=client.get('/api/public/v1/content/resources?limit=2&page=2').json()
    assert len(response['data'])==1 and response['meta']['total']==3
    assert client.get('/api/public/v1/content/resources?limit=101').status_code == 422
