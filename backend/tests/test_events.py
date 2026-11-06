from datetime import datetime, timedelta
from uuid import uuid4
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import func, select
from test_catalog import client
from test_circulation import session
from test_readers import branch, create
from test_security import add, login
from test_visit_checkin import KEY, PATH, send
from app.main import app
from app.events import EventInput
from app.event_models import EventAttendance, LibraryEvent
from app.reader_core import TZ
from app.reader_models import ReaderIdentity, LibraryVisit


def new_event(c, branch_id, **changes):
    today = str(datetime.now(TZ).date())
    body = dict(title='Тестовая выставка', date_from=today, date_to=today, branch_id=branch_id,
                format='Выставка', responsible='Библиотека', coorganizers='Кафедра', protocol=True,
                instagram_url='https://www.instagram.com/example/', notes='Тестовые данные', **changes)
    r = c.post('/api/events', json=body)
    assert r.status_code == 200, r.text
    return r.json()


def qr(c, event, **kw):
    r = c.post(f"/api/events/{event['id']}/qr", json={'base_url': 'https://library.test', **kw})
    assert r.status_code == 200, r.text
    return r.json()


def update_body(event, **changes):
    return {**{k: event[k] for k in EventInput.model_fields}, 'version': event['version'], **changes}


@pytest.fixture
def event(client, monkeypatch):
    monkeypatch.setenv('STUDENT_BRIDGE_KEY', KEY)
    return new_event(client, branch(client))


def test_crud_filters_exports_and_optimistic_lock(client, event):
    eid = event['id']
    assert client.get('/api/events?status=completed').json()['total'] == 0
    assert client.get('/api/events?q=Тестовая').json()['total'] == 1
    assert client.get('/api/events?date_from=2200-01-01').json()['total'] == 0
    assert client.get('/api/events/options').json()['formats'] == ['Выставка']
    changed = client.put(f'/api/events/{eid}', json=update_body(event, title='=Новое название'))
    assert changed.status_code == 200, changed.text
    assert changed.json()['version'] == 2
    assert client.put(f'/api/events/{eid}', json=update_body(event)).status_code == 409
    assert client.delete(f'/api/events/{eid}?version=1').status_code == 409
    csv = client.get('/api/events/export?format=csv')
    assert "'=Новое название" in csv.text
    xlsx = client.get('/api/events/export')
    assert load_workbook(BytesIO(xlsx.content)).active['B2'].value == "'=Новое название"
    assert client.delete(f'/api/events/{eid}?version=2').status_code == 200
    assert client.get('/api/events').json()['total'] == 0
    assert client.get(f'/api/events/{eid}').status_code == 404
    with session() as s: assert s.get(LibraryEvent, eid).deleted_at is not None


def test_qr_guest_and_account_dedup_reports_do_not_change_library_visits(client, event):
    token = qr(client, event)['link'].rsplit('/', 1)[-1]
    reader = create(client, category='bachelor', course=2, study_group='Т-2', faculty='Тестовый факультет')
    guid = str(uuid4())
    with session() as s:
        s.add(ReaderIdentity(reader_id=reader['id'], source='active_directory', entity_type='ad_user', external_id=guid)); s.commit()
    with TestClient(app) as c:
        info = c.get('/api/check-in/v1/points/'+token)
        assert info.json()['kind'] == 'event' and info.json()['can_check_in']
        assert set(info.json()) == {'name', 'kind', 'date_from', 'date_to', 'location', 'can_check_in'}
        assert c.post(PATH, json={'token': token}).status_code == 401
        r = send(c, guid, {'token': token})
        assert r.status_code == 200, r.text
        assert r.json()['kind'] == 'event' and not r.json()['duplicate']
        assert send(c, guid, {'token': token}).json()['duplicate']
        assert send(c, guid, {'token': token, 'reader_id': 100}).status_code == 422
        guest = {'token': token, 'full_name': 'Гость тест', 'study_group': 'Т-3', 'course': 3}
        subject = 'guest:'+str(uuid4())
        assert send(c, subject, guest).json()['duplicate'] is False
        assert send(c, subject, guest).json()['duplicate'] is True
    endpoint = f"/api/events/{event['id']}"
    assert client.post(endpoint+'/attendance', json={'code': reader['barcode']}).json()['duplicate']
    assert client.get('/api/visits').json()['total'] == 0
    assert client.get('/api/statistics/attendance').json()['totals']['visits'] == 0
    report = client.get(endpoint+'/report', params={'date_from': event['date_from'], 'date_to': event['date_to']})
    assert report.status_code == 200, report.text
    data = report.json()
    assert data['totals']['visits'] == 2 and data['totals']['unique'] == 1
    assert data['totals']['categories']['guest']['visits'] == 1
    assert data['rows'][0]['visits'] == 2 and data['months'][0]['visits'] == 2
    assert sum(x['visits'] for x in data['hours']) == 2
    assert sum(x['visits'] for x in data['breakdown']) == 2
    assert client.get(endpoint+'/report?course=3&source=qr_guest').json()['totals']['visits'] == 1
    journal = client.get(endpoint+'/report/journal?study_group=Т-3').json()
    assert journal['total'] == 1 and journal['items'][0]['reader_id'] is None
    assert client.get(endpoint+'/report/options').json()['filters']['course']
    assert client.get(endpoint+'/report/export?format=csv').text.startswith('\ufeffУчастие в мероприятии:')
    assert client.get(endpoint+'/report/export').content.startswith(b'PK')
    assert client.get('/api/events').json()['participants'] == 2
    other = new_event(client, event['branch_id'])
    assert client.get(f"/api/events/{other['id']}/report").json()['totals']['visits'] == 0
    assert client.post(f"/api/events/{other['id']}/attendance", json={'code': reader['barcode']}).json()['duplicate'] is False
    # Removal invalidates the QR and preserves the attendance rows for audit.
    assert client.delete(endpoint+'?version=1').status_code == 200
    assert client.get('/api/check-in/v1/points/'+token).status_code == 404
    with session() as s:
        assert s.scalar(select(func.count(EventAttendance.id))) == 3
        assert s.scalar(select(func.count(LibraryVisit.id))) == 0


def test_qr_rotation_disable_dates_completion_and_validation(client, event):
    original = qr(client, event)
    assert original['enabled']
    assert qr(client, event)['link'] == original['link']
    token = original['link'].rsplit('/', 1)[-1]
    fresh = qr(client, event, rotate=True)['link'].rsplit('/', 1)[-1]
    assert client.get('/api/check-in/v1/points/'+token).status_code == 404
    qr(client, event, enabled=False)
    assert qr(client, event)['enabled'] is False
    assert client.get('/api/check-in/v1/points/'+fresh).status_code == 404
    qr(client, event, enabled=True)
    tomorrow = str(datetime.now(TZ).date()+timedelta(days=1))
    changed = client.put(f"/api/events/{event['id']}", json=update_body(event, date_from=tomorrow, date_to=tomorrow)).json()
    assert client.get('/api/check-in/v1/points/'+fresh).json()['can_check_in'] is False
    guest = {'token': fresh, 'full_name': 'Тестовый гость', 'study_group': 'Т-1', 'course': 1}
    assert send(client, 'guest:'+str(uuid4()), guest).status_code == 409
    changed = client.put(f"/api/events/{event['id']}", json=update_body(changed, date_from=event['date_from'], date_to=event['date_to'], status='completed')).json()
    assert send(client, 'guest:'+str(uuid4()), guest).status_code == 409
    for updates in ({'date_to':'1900-01-01'}, {'protocol_url':'javascript:alert(1)'}, {'title':'  '}, {'status':'unknown'}):
        assert client.put(f"/api/events/{event['id']}", json=update_body(changed, **updates)).status_code == 422
    assert client.get('/api/events?date_from=2026-12-01&date_to=2026-01-01').status_code == 422


def test_staff_permissions_and_csrf(client, event):
    add(client, permissions=['events.view'])
    endpoint = f"/api/events/{event['id']}"
    with TestClient(app) as c:
        assert c.get('/api/events').status_code == 401
        login(c)
        assert c.get('/api/events').status_code == 200
        assert c.get(endpoint+'/report').status_code == 200
        for method, url in [('POST','/api/events'),('PUT',endpoint),('DELETE',endpoint+'?version=1'),('POST',endpoint+'/qr'),('POST',endpoint+'/attendance')]:
            assert c.request(method,url,json={}).status_code == 403
    reader = create(client)
    add(client, username='scanner', permissions=['events.view','events.record'])
    with TestClient(app) as c:
        login(c, name='scanner')
        assert c.post(endpoint+'/attendance',json={'code':reader['barcode']},headers={'X-CSRF-Token':''}).status_code == 403
        assert c.post(endpoint+'/attendance',json={'code':reader['barcode']}).status_code == 200
        assert c.post(endpoint+'/qr',json={'base_url':'https://library.test'}).status_code == 403
