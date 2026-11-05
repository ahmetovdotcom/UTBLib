import hashlib
import hmac
import json
import time
from datetime import datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from test_catalog import client
from test_readers import branch, create
from test_circulation import session
from app.main import app
from app.reader_core import TZ
from app.reader_models import Reader, ReaderIdentity, LibraryVisit

KEY = 'test-only-check-in-key-' + 'x' * 40
PATH = '/api/check-in/v1/visits'


def send(c, subject, body, *, signed_body=None, stamp=None):
    raw = json.dumps(body, ensure_ascii=False).encode()
    stamp = str(stamp or int(time.time()))
    digest = hashlib.sha256(raw if signed_body is None else signed_body).hexdigest()
    msg = '\n'.join(('visit-v1', 'POST', PATH, '', subject, stamp, digest))
    return c.post(PATH, content=raw, headers={'Content-Type': 'application/json',
        'X-Reader-Subject': subject, 'X-Reader-Time': stamp,
        'X-Reader-Signature': hmac.new(KEY.encode(), msg.encode(), hashlib.sha256).hexdigest()})


@pytest.fixture
def point(client, monkeypatch):
    monkeypatch.setenv('STUDENT_BRIDGE_KEY', KEY)
    b = branch(client)
    result = client.post(f'/api/visits/qr-points/{b}', json={'base_url': 'https://library.test'})
    assert result.status_code == 200, result.text
    token = result.json()['link'].rsplit('/', 1)[-1]
    return b, token


def test_guest_is_not_matched_to_reader_and_is_present_in_reports(client, point):
    b, token = point
    create(client, full_name='Тест Читатель', study_group='А-1', course=1)
    subject = 'guest:' + str(uuid4())
    body = {'token': token, 'full_name': 'Тест Читатель', 'study_group': 'А-1', 'course': 1}
    with TestClient(app) as guest:
        assert guest.get(f'/api/check-in/v1/points/{token}').json() == {'name': 'Читальный зал'}
        assert guest.post(PATH, json=body).status_code == 401
        first = send(guest, subject, body)
        assert first.status_code == 200, first.text
        assert first.json()['duplicate'] is False
        assert send(guest, subject, body).json()['duplicate'] is True
        assert 'no-store' in first.headers['cache-control']
    with session() as s:
        assert s.scalar(select(func.count()).select_from(Reader)) == 1
        v = s.scalar(select(LibraryVisit)); assert v.reader_id is None and v.scanned_by is None
        assert v.guest_name == 'Тест Читатель' and v.source == 'qr_guest'
    journal = client.get('/api/visits').json()
    assert journal['total'] == 1 and journal['items'][0]['reader_id'] is None
    assert journal['items'][0]['full_name'] == 'Тест Читатель'
    day = str(datetime.now(TZ).date())
    filters = {'date_from': day, 'date_to': day, 'course': '1', 'study_group': 'А-1', 'source': 'qr_guest'}
    report = client.get('/api/statistics/attendance', params=filters).json()
    assert report['totals']['visits'] == 1 and report['totals']['unique'] == 0
    assert report['totals']['categories']['guest']['visits'] == 1
    assert client.get('/api/statistics/attendance/journal', params=filters).json()['total'] == 1
    assert client.get('/api/statistics/attendance/export', params={**filters, 'format': 'csv'}).status_code == 200
    assert client.get('/api/visits/analytics').json()['today']['visits'] == 1


def test_account_identity_dedup_including_staff_and_separate_branches(client, point):
    b, token = point
    r = create(client); subject = str(uuid4())
    with session() as s:
        s.add(ReaderIdentity(reader_id=r['id'], source='active_directory', entity_type='ad_user', external_id=subject)); s.commit()
    with TestClient(app) as guest:
        result = send(guest, subject, {'token': token})
        assert result.status_code == 200, result.text
        assert result.json()['verification'] == 'account'
        assert send(guest, subject, {'token': token, 'reader_id': 999}).status_code == 422
        assert send(guest, subject, {'token': token, 'full_name': 'Someone'}).status_code == 422
        assert send(guest, str(uuid4()), {'token': token}).status_code == 404
    assert client.post('/api/visits', json={'code': r['barcode'], 'branch_id': b}).json()['duplicate']
    b2 = client.post('/api/reader-branches', json={'code': 'SECOND', 'name': 'Абонемент 2'}).json()['id']
    assert client.post('/api/visits', json={'code': r['barcode'], 'branch_id': b2}).json()['duplicate'] is False
    assert client.get('/api/visits').json()['total'] == 2


def test_tokens_persist_rotate_disable_and_closed_branch(client, point):
    b, token = point
    url = f'/api/visits/qr-points/{b}'
    assert client.post(url, json={'base_url': 'https://library.test'}).json()['link'].endswith(token)
    fresh = client.post(url, json={'base_url': 'https://library.test', 'rotate': True}).json()['link'].rsplit('/', 1)[-1]
    assert fresh != token
    assert client.get(f'/api/check-in/v1/points/{token}').status_code == 404
    assert client.get(f'/api/check-in/v1/points/{fresh}').status_code == 200
    client.post(url, json={'base_url': 'https://library.test', 'enabled': False})
    assert client.get(f'/api/check-in/v1/points/{fresh}').status_code == 404
    assert client.post(url, json={'base_url': 'https://library.test'}).json()['enabled'] is False
    client.post(url, json={'base_url': 'https://library.test', 'enabled': True})
    client.put(f'/api/reader-branches/{b}', json={'code': 'MAIN', 'name': 'Зал', 'active': False})
    assert client.get(f'/api/check-in/v1/points/{fresh}').status_code == 404


def test_signed_body_timestamp_validation_and_rate_limit(client, point):
    _, token = point
    subject = 'guest:' + str(uuid4())
    body = {'token': token, 'full_name': 'Тест Читатель', 'study_group': 'А-1', 'course': 1}
    assert send(client, subject, body, signed_body=b'{}').status_code == 401
    assert send(client, subject, body, stamp=int(time.time()) - 120).status_code == 401
    assert send(client, subject, {**body, 'full_name': ' '}).status_code == 422
    assert send(client, subject, {**body, 'course': 0}).status_code == 422
    assert send(client, subject, {**body, 'course': True}).status_code == 422
    for _ in range(15): assert send(client, subject, body).status_code == 200
    assert send(client, subject, body).status_code == 429
    with TestClient(app) as guest:
        assert guest.post(f'/api/visits/qr-points/{point[0]}', json={'base_url':'https://library.test'}).status_code == 401
