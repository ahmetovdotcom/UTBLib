import hashlib
import hmac
import time
from io import BytesIO
from uuid import uuid4

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from test_catalog import client,make_type,payload,field
from test_circulation import session
from app.db import CatalogFile, Record
from app.main import app


def pdf():
    output=BytesIO()
    Image.new('RGB',(120,180),'blue').save(output,format='PDF',save_all=True,append_images=[Image.new('RGB',(120,180),'white')])
    return output.getvalue()


def upload(client):
    response=client.post('/api/catalog-files?filename=sample.pdf',content=pdf(),headers={'Content-Type':'application/pdf'})
    assert response.status_code==201,response.text
    assert response.json()['pages']==2
    return response.json()['token']


def signed(path,key='test-faculty-bridge-key-0123456789012345',**extra):
    stamp=str(int(time.time()));subject='12345678-1111-2222-3333-123456789012'
    return {'X-Reader-Subject':subject,'X-Reader-Time':stamp,'X-Reader-Signature':hmac.new(key.encode(),'\n'.join(['GET',path,'',subject,stamp]).encode(),hashlib.sha256).hexdigest(),**extra}


def test_publication_atomic_private_detail_cover_and_reading(client,monkeypatch):
    monkeypatch.setenv('STUDENT_BRIDGE_KEY','test-faculty-bridge-key-0123456789012345')
    token=upload(client)
    body=payload(make_type(client));body['marc']['fields'] += [field('520',value='Public annotation'),field('300',value='FULL_EXTENT'),field('097','b','PRIVATE_OPERATOR'),field('020',value='9786010433649')]
    body.update(is_faculty_work=True,use_first_page_cover=True,digital_upload=token,request_key=str(uuid4()))
    saved=client.post('/api/records',json=body);assert saved.status_code==201,saved.text
    rid=saved.json()['id'];identifier=f'utblib-{rid}'
    assert saved.json()['electronic_file']['pages']==2
    assert client.post('/api/records',json=body).json()['id']==rid
    with TestClient(app) as guest:
        for path in ('/api/public/v1/catalog?faculty_works_only=true','/api/public/v1/catalog',f'/api/public/v1/books/{identifier}','/api/public/v1/books/9786010433649'):
            response=guest.get(path);assert response.status_code==200,response.text
            assert 'FULL_EXTENT' not in response.text and 'PRIVATE_OPERATOR' not in response.text
            assert 'Public annotation' in response.text
            assert 'electronicFile' not in response.text
        cover=guest.get(f'/api/public/v1/book-covers/{identifier}')
        assert cover.status_code==200 and cover.content.startswith(b'\xff\xd8')
        with Image.open(BytesIO(cover.content)) as image: assert max(image.size)<=1400
        detail=f'/api/student/v1/books/{identifier}';stream=detail+'/file'
        assert guest.get(detail).status_code==401
        assert guest.get(stream).status_code==401
        assert guest.get(stream,headers=signed(detail)).status_code==401
        full=guest.get(detail,headers=signed(detail));assert full.status_code==200
        assert full.json()['data']['physicalExtent']=='FULL_EXTENT' and not full.json()['data']['loginRequired']
        assert 'PRIVATE_OPERATOR' not in full.text
        result=guest.get(stream,headers=signed(stream,Range='bytes=0-19'))
        assert result.status_code==206 and result.content==pdf()[:20]
        assert result.headers['cache-control']=='private, no-store'
        assert guest.get(stream,headers=signed(stream,Range='bytes=99999999-')).status_code==416
        # Hiding is immediate on all public and private paths; PDF remains in the staff record.
        edit={k:saved.json()[k] for k in ('type_id','version','marc')};edit['is_faculty_work']=False
        assert client.put('/api/records/'+str(rid),json=edit).status_code==200
        assert guest.get('/api/public/v1/catalog?faculty_works_only=true').json()['meta']['total']==0
        assert guest.get(stream,headers=signed(stream)).status_code==404
        assert guest.get(f'/api/public/v1/book-covers/{identifier}').status_code==404


def test_upload_validation_csrf_permissions_and_record_conflict(client):
    with TestClient(app) as guest:
        assert guest.post('/api/catalog-files?filename=x.pdf',content=pdf()).status_code==401
    assert client.post('/api/catalog-files?filename=x.pdf',content=b'%PDF-broken',headers={'Content-Type':'application/pdf'}).status_code==422
    assert client.post('/api/catalog-files?filename=x.exe',content=pdf(),headers={'Content-Type':'application/pdf'}).status_code==422
    token=upload(client);body=payload(make_type(client));body.update(is_faculty_work=True,digital_upload=token,use_first_page_cover=True)
    saved=client.post('/api/records',json=body).json();rid=saved['id']
    replacement=upload(client)
    edit={k:saved[k] for k in ('type_id','version','marc')};edit.update(digital_upload=replacement)
    result=client.put('/api/records/'+str(rid),json=edit);assert result.status_code==200,result.text
    assert client.put('/api/records/'+str(rid),json={**edit,'digital_upload':None}).status_code==409
    with session() as s:
        assert s.get(CatalogFile,token) is None
        assert s.get(Record,rid).digital_file.id==replacement
    # Old clients may edit bibliography without erasing the file and flag.
    edit['version']=result.json()['version'];edit.pop('digital_upload')
    result=client.put('/api/records/'+str(rid),json=edit)
    assert result.json()['is_faculty_work'] and result.json()['electronic_file']
    edit['version']=result.json()['version'];edit.update(digital_upload=None,use_first_page_cover=False)
    result=client.put('/api/records/'+str(rid),json=edit);assert result.status_code==200,result.text
    assert result.json()['electronic_file'] is None
    with session() as s: assert s.get(CatalogFile,replacement) is None


def test_foreign_upload_and_failed_save_do_not_publish(client):
    token=upload(client);body=payload(make_type(client));body.update(digital_upload=token,is_faculty_work=True,use_first_page_cover=True)
    body['marc']['fields']=[]
    assert client.post('/api/records',json=body).status_code==422
    with session() as s: assert s.get(CatalogFile,token).record_id is None
    body['marc']['fields']=[field()]
    with session() as s:
        s.get(CatalogFile,token).owner_id=9999;s.commit()
    response=client.post('/api/records',json=body)
    assert response.status_code==409,response.text
    with session() as s: assert list(s.scalars(select(Record)))==[]
