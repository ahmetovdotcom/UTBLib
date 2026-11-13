import copy
from datetime import timedelta
from io import BytesIO
import pytest
from PIL import Image
from test_catalog import client
from test_site_content import body, change
from test_security import add, login
from fastapi.testclient import TestClient
from app.main import app
from app.db import utcnow
from app.website_content import WEBSITE_SCHEMA, empty_node


def page(slug='contacts'):
    return {'kind': 'pages', 'slug': slug, 'status': 'published', 'data': {
        'translations': {'ru': {'title': 'Страница'}},
        'page_content': empty_node(WEBSITE_SCHEMA[slug]['schema'])}}


def test_website_pages_languages_lists_versions_and_boundaries(client):
    p = page()
    d = p['data']['page_content']
    d['ru']['location_email'] = 'library@example.test'
    d['ru']['hours_rows'] = [{'days': 'Понедельник', 'hours': '09:00–18:00'}]
    d['kk']['hero_title_a'] = 'Кітапхана'
    d['ru']['hero_title_a'] = '<script>text, not HTML</script>'
    created = client.post('/api/site-content', json=p)
    assert created.status_code == 201, created.text
    row = created.json()
    public = '/api/public/v1/content/pages/contacts'
    assert client.get(public).json()['data']['data']['page_content']['kk']['hero_title_a'] == 'Кітапхана'
    changed = copy.deepcopy(row['data'])
    changed['page_content']['ru']['hours_rows'] = []
    saved = change(client, row, data=changed).json()
    assert client.get(public).json()['data']['data']['page_content']['ru']['hours_rows'] == []
    assert change(client, row, data=changed).status_code == 409
    assert change(client, saved, slug='rules').status_code == 422
    assert change(client, saved, status='draft').status_code == 422
    assert change(client, saved, published_at=(utcnow()+timedelta(days=1)).isoformat()).status_code == 422
    assert client.delete(f"/api/site-content/{row['id']}?version={saved['version']}").status_code == 422
    for target, value in [('instagram_url','javascript:alert(1)'),('instagram_url','//bad.test'),('location_email','bad@email'),('unexpected','bad')]:
        invalid=page(); invalid['data']['page_content']['ru'][target]=value
        assert client.post('/api/site-content',json=invalid).status_code == 422
    invalid=page('header');invalid['data']['page_content']['ru']['links']=[['home','Main','https://external.test']]
    assert client.post('/api/site-content',json=invalid).status_code == 422
    invalid=page('header');invalid['data']['page_content']['ru']['links']=[['home']]
    assert client.post('/api/site-content',json=invalid).status_code == 422
    invalid=page(); invalid['data']['page_content']['ru']['hours_rows']=[{'days':'','hours':''}]*101
    assert client.post('/api/site-content',json=invalid).status_code == 422


def test_people_crud_photo_order_visibility_and_no_resurrection(client):
    p=body('people','published',show_contacts=True,show_leadership=True,sort_order=5,email='person@example.test',phone='+7 000 000 0000')
    p['data']['translations']['ru']['role']='Директор'
    row=client.post('/api/site-content',json=p).json()
    path=f"/api/site-content/{row['id']}"
    data=row['data']; data['show_contacts']=False
    row=change(client,row,data=data).json()
    public=f"/api/public/v1/content/people/utblib-{row['id']}"
    assert client.get(public).json()['data']['data']['show_contacts'] is False
    picture=BytesIO();Image.new('RGB',(10,10)).save(picture,'PNG')
    row=client.put(path+f"/assets/image?version={row['version']}",content=picture.getvalue()).json()
    asset=f"/api/public/v1/content-assets/{row['id']}/image"
    assert client.get(asset).status_code == 200
    assert client.delete(path+'?version=1').status_code == 409
    assert client.delete(path+f"?version={row['version']}").status_code == 200
    assert client.get(public).status_code == 404
    assert client.get(asset).status_code == 404
    assert client.get('/api/site-content?kind=people').json()['total'] == 0
    assert client.get('/api/public/v1/content/people').json()['meta']['total'] == 0
    assert change(client,row).status_code == 404
    assert client.put(path+f"/assets/image?version={row['version']+1}",content=picture.getvalue()).status_code == 404


def test_schema_and_deletion_require_site_permission_and_csrf(client):
    row=client.post('/api/site-content',json=body('people')).json()
    path=f"/api/site-content/{row['id']}?version=1"
    add(client)
    with TestClient(app) as c:
        assert c.get('/api/site-content/website-schema').status_code == 401
        login(c)
        assert c.get('/api/site-content/website-schema').status_code == 403
        assert c.delete(path).status_code == 403
    assert client.delete(path,headers={'X-CSRF-Token':''}).status_code == 403
    schema=client.get('/api/site-content/website-schema').json()
    assert set(schema)==set(WEBSITE_SCHEMA)


@pytest.mark.parametrize('slug',list(WEBSITE_SCHEMA))
def test_every_page_schema_accepts_its_empty_shape(client,slug):
    response=client.post('/api/site-content',json=page(slug))
    assert response.status_code==201,response.text
