import hashlib
import hmac
import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func

from test_catalog import client
from test_circulation import seed, session, issue, close
from app.main import app
from app.reader_models import Reader, ReaderIdentity
from app.circulation_models import Loan

KEY = 'test-only-student-key-' + 'x'*40
PATH = '/api/student/v1/me'

def signed(subject, query='', path=PATH, stamp=None):
    stamp = str(int(time.time()) if stamp is None else stamp)
    message = '\n'.join(('GET', path, query, subject, stamp))
    return {'X-Reader-Subject': subject, 'X-Reader-Time': stamp,
            'X-Reader-Signature': hmac.new(KEY.encode(), message.encode(), hashlib.sha256).hexdigest()}

@pytest.fixture
def people(client, monkeypatch):
    monkeypatch.setenv('STUDENT_BRIDGE_KEY', KEY)
    readers, copies, record = seed(2)
    subjects = [str(uuid4()), str(uuid4())]
    with session() as s:
        for reader, subject in zip(readers, subjects):
            s.add(ReaderIdentity(reader_id=reader, source='active_directory', entity_type='ad_user', external_id=subject))
            s.get(Reader, reader).full_name = 'Same Name'
        s.commit()
    assert issue(client, readers[0], [copies[0]]).status_code == 200
    assert issue(client, readers[1], [copies[1]]).status_code == 200
    return readers, copies, record, subjects

def test_anonymous_staff_and_import_key_cannot_read_student_data(client, people):
    with TestClient(app) as guest:
        assert guest.get(PATH).status_code == 401
        assert guest.get(PATH, headers={'X-Admin-Key':'test-secret'}).status_code == 401
    assert client.get(PATH).status_code == 401

def test_exact_ad_identity_and_live_return(client, people):
    readers, copies, record, subjects = people
    query = 'section=loans&page=1'
    with TestClient(app) as guest:
        result = guest.get(PATH+'?'+query, headers=signed(subjects[0], query))
        assert result.status_code == 200, result.text
        data = result.json()
        assert data['profile']['barcode'] == 'RDR-TEST0'
        assert data['summary']['loans'] == 1
        assert data['data'][0]['book_id'] == f'utblib-{record}'
        assert len(data['data']) == 1
        assert 'private' in result.headers['cache-control'] and 'no-store' in result.headers['cache-control']
        assert not {'iin','birth_date','login','reader_id','field_owners','notes'} & set(data['profile'])
        loan = data['data'][0]['id']
        assert close(client, loan).status_code == 200
        current = guest.get(PATH, headers=signed(subjects[0])).json()
        assert current['summary']['loans'] == 0 and current['summary']['history'] == 1
        assert guest.get(PATH, headers=signed(subjects[1])).json()['summary']['loans'] == 1

@pytest.mark.parametrize('tamper', ['subject','query','path','expired','future','key'])
def test_signature_cannot_change_reader_resource_or_scope(client, people, tamper):
    subject = people[3][0]
    headers = signed(subject)
    path = PATH
    if tamper == 'subject': headers['X-Reader-Subject'] = people[3][1]
    if tamper == 'query': path += '?section=history'
    if tamper == 'path': path = '/api/student/v1/photo'
    if tamper == 'expired': headers = signed(subject, stamp=int(time.time())-120)
    if tamper == 'future': headers = signed(subject, stamp=int(time.time())+120)
    if tamper == 'key': headers['X-Reader-Signature'] = '0'*64
    assert client.get(path, headers=headers).status_code == 401

def test_missing_ambiguous_identity_never_matches_by_name_or_email(client, people):
    assert client.get(PATH, headers=signed(str(uuid4()))).status_code == 404
    readers, _, _, subjects = people
    with session() as s:
        s.add(ReaderIdentity(reader_id=readers[1], source='active_directory', entity_type='ad_user', external_id=subjects[0].upper()))
        s.commit()
    assert client.get(PATH, headers=signed(subjects[0])).status_code == 409

def test_scoped_pagination_and_read_only(client, people, monkeypatch):
    subject = people[3][0]
    for section in ['history','reservations','fines','incidents','visits','profile','card']:
        query = f'section={section}&page=1'
        assert client.get(PATH+'?'+query, headers=signed(subject, query)).status_code == 200
    query = 'section=loans&page=2'
    data = client.get(PATH+'?'+query, headers=signed(subject, query)).json()
    assert data['data'] == [] and data['meta']['total'] == 1
    assert client.post(PATH, headers=signed(subject), json={}).status_code == 405
    with session() as s:
        assert s.scalar(select(func.count()).select_from(Reader)) == len(people[0])
        assert s.scalar(select(func.count()).select_from(Loan)) == 2
    monkeypatch.delenv('STUDENT_BRIDGE_KEY')
    assert client.get(PATH, headers=signed(subject)).status_code == 503
