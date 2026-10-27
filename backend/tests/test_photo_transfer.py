import base64
from uuid import uuid4
from urllib.parse import urlsplit, parse_qs

import pytest
from fastapi.testclient import TestClient

from test_catalog import client
from app import photo_transfer as transfer
from app.main import app
from test_book_photos import photo
from test_security import add, login

BASE = '/api/photo-transfer'


@pytest.fixture(autouse=True)
def clean_store():
    transfer.store = transfer.TransferStore()
    yield
    transfer.store.rooms.clear()


def start(client):
    r = client.post(BASE+'/sessions', json={'origin':'http://testserver'})
    assert r.status_code == 201, r.text
    data = r.json()
    assert r.headers['cache-control'] == 'private, no-store'
    assert data['qr'].startswith('data:image/png;base64,')
    assert base64.b64decode(data['qr'].split(',')[1]).startswith(b'\x89PNG')
    target = str(uuid4())
    assert client.post(BASE+f"/sessions/{data['id']}/target", json={'target_id':target,'label':'Қазақ тілі'}).status_code == 200
    pair = parse_qs(urlsplit(data['link']).fragment)['pair'][0]
    return data['id'], target, pair


def pair_phone(phone, pairing):
    r = phone.post(BASE+'/mobile/pair',headers={'Authorization':'Bearer '+pairing})
    assert r.status_code == 200, r.text
    phone.headers['Authorization'] = 'Bearer '+r.json()['token']
    return r.json()['token']


def upload(phone, target, request_id=None, image=None):
    return phone.post(BASE+'/mobile/photos',json={'target_id':target,'label':'Книга',
        'request_id':request_id or str(uuid4()),'name':'page.jpg','image':image or photo()})


def test_pair_once_sequential_books_and_manual_editor_is_untouched(client):
    room, target, pairing = start(client)
    with TestClient(app) as phone:
        token = pair_phone(phone, pairing)
        assert phone.post(BASE+'/mobile/pair',headers={'Authorization':'Bearer '+pairing}).status_code == 401
        assert phone.get('/api/records').status_code == 401
        assert phone.get(BASE+f'/sessions/{room}').status_code == 401
        assert upload(phone,target).status_code == 201
        state = client.post(BASE+f'/sessions/{room}/heartbeat',json={'target_id':target,'label':'Қазақ тілі'}).json()
        assert len(state['photos']) == 1
        photo_id = state['photos'][0]['id']
        data = client.get(BASE+f'/sessions/{room}/photos/{photo_id}').json()
        assert data['target_id'] == target and data['url'].startswith('data:image/jpeg;base64,')
        assert client.get('/api/records').json() == []
        target2 = str(uuid4())
        assert client.post(BASE+f'/sessions/{room}/target',json={'target_id':target2,'label':'English Book'}).json()['photos'] == []
        assert phone.get(BASE+'/mobile').json()['label'] == 'English Book'
        assert upload(phone,target).status_code == 409
        assert upload(phone,target2).status_code == 201
        assert phone.headers['Authorization'] == 'Bearer '+token
        assert client.get(BASE+f'/sessions/{room}/photos/{photo_id}').status_code == 404
        assert client.delete(BASE+f'/sessions/{room}').status_code == 204
        assert phone.get(BASE+'/mobile').status_code == 401


def test_retry_and_removal_do_not_duplicate_or_resurrect_photo(client):
    room,target,pairing = start(client)
    with TestClient(app) as phone:
        pair_phone(phone,pairing)
        request_id = str(uuid4())
        assert upload(phone,target,request_id).status_code == 201
        assert len(upload(phone,target,request_id).json()['photos']) == 1
        assert client.delete(BASE+f'/sessions/{room}/photos/{request_id}').status_code == 204
        assert upload(phone,target,request_id).json()['photos'] == []
        assert phone.get(BASE+'/mobile').json()['photos'] == []


def test_pause_lease_and_late_upload_after_decoding(client,monkeypatch):
    room,target,pairing = start(client)
    with TestClient(app) as phone:
        pair_phone(phone,pairing)
        path=BASE+f'/sessions/{room}/gate'
        assert client.post(path,json={'target_id':target,'accepting':False}).status_code == 200
        assert upload(phone,target).status_code == 409
        client.post(path,json={'target_id':target,'accepting':True})
        transfer.store.rooms[room].desktop_seen -= transfer.DESKTOP_LEASE+1
        assert phone.get(BASE+'/mobile').json()['accepting'] is False
        assert upload(phone,target).status_code == 409
        client.post(path,json={'target_id':target,'accepting':True})
        original=transfer.prepare_image
        def decode_then_switch(image):
            result=original(image)
            transfer.store.rooms[room].target_id=str(uuid4())
            return result
        monkeypatch.setattr(transfer,'prepare_image',decode_then_switch)
        assert upload(phone,target).status_code == 409
        assert not transfer.store.rooms[room].photos
        # A delayed teardown of the old editor must not pause the next book.
        assert client.post(path,json={'target_id':target,'accepting':False}).status_code == 409
        assert transfer.store.rooms[room].accepting


def test_owner_permissions_csrf_and_logout(client):
    room,target,pairing=start(client)
    add(client,username='other',permissions=['catalog.edit'])
    with TestClient(app) as other, TestClient(app) as phone:
        login(other,'other')
        assert other.get(BASE+f'/sessions/{room}').status_code == 404
        assert other.delete(BASE+f'/sessions/{room}').status_code == 404
        assert client.post(BASE+f'/sessions/{room}/gate',headers={'X-CSRF-Token':''},json={'target_id':target,'accepting':False}).status_code == 403
        pair_phone(phone,pairing)
        assert phone.post(BASE+'/mobile/photos',headers={'Origin':'https://evil.example'},json={}).status_code == 403
        assert client.post('/api/auth/logout').status_code == 204
        assert phone.get(BASE+'/mobile').status_code == 401
        assert room not in transfer.store.rooms


def test_viewer_cannot_create_or_pair_without_secret(client):
    add(client)
    with TestClient(app) as viewer:
        login(viewer)
        assert viewer.post(BASE+'/sessions',json={'origin':'http://testserver'}).status_code == 403
        assert viewer.get(BASE+'/mobile').status_code == 401
        assert viewer.post(BASE+'/mobile/pair',headers={'Authorization':'Bearer wrong'}).status_code == 401
    assert client.post(BASE+'/sessions',json={'origin':'https://evil.example'}).status_code == 422


def test_limits_expiry_and_private_responses(client,monkeypatch):
    room,target,pairing=start(client)
    with TestClient(app) as phone:
        pair_phone(phone,pairing)
        for _ in range(6):
            assert upload(phone,target).status_code == 201
        assert upload(phone,target).status_code == 409
        r=phone.get(BASE+'/mobile')
        assert 'url' not in r.json()['photos'][0]
        assert r.headers['referrer-policy'] == 'no-referrer'
        transfer.store.rooms[room].desktop_seen-=transfer.PHOTO_IDLE+1
        transfer.store.cleanup()
        assert not transfer.store.rooms[room].photos
        assert not phone.get(BASE+'/mobile').json()['accepting']
        transfer.store.rooms[room].expires=0
        assert phone.get(BASE+'/mobile').status_code == 401
    room,target,pairing=start(client)
    transfer.store.rooms[room].pair_expires=0
    with TestClient(app) as phone:
        assert phone.post(BASE+'/mobile/pair',headers={'Authorization':'Bearer '+pairing}).status_code == 401


def test_invalid_images_and_memory_budget(client,monkeypatch):
    room,target,pairing=start(client)
    with TestClient(app) as phone:
        pair_phone(phone,pairing)
        for value in ('data:image/jpeg;base64,AAAA','https://example.org/photo.jpg',photo(size=(10,10))):
            r=upload(phone,target,image=value)
            assert r.status_code == 422
            assert value not in r.text
        monkeypatch.setattr(transfer,'MAX_BODY',50)
        assert upload(phone,target).status_code == 413
        monkeypatch.setattr(transfer,'MAX_BODY',1_500_000)
        monkeypatch.setattr(transfer,'MAX_BYTES',1)
        assert upload(phone,target).status_code == 429
        assert not transfer.store.rooms[room].photos


def test_transfer_does_not_acquire_accounting_lock(client,monkeypatch):
    from app import security
    calls=[]
    monkeypatch.setattr(security,'lock',lambda *args: calls.append(args))
    room,target,pairing=start(client)
    client.post(BASE+f'/sessions/{room}/heartbeat',json={'target_id':target,'label':'Книга'})
    with TestClient(app) as phone:
        pair_phone(phone,pairing)
        transfer.store.uploading.add(room)
        assert upload(phone,target).status_code == 429
        transfer.store.uploading.clear()
        assert upload(phone,target).status_code == 201
    assert not calls
