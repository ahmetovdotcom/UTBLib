from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from test_catalog import client, field
from test_circulation import seed, session, issue, close
from app.main import app
from app.db import Acquisition, AcquisitionLine, Copy, DocumentType, Record, utcnow
from app.reader_models import Branch
from app.circulation_models import CopyCirculation, Reservation

ROOT = '/api/public/v1'


def test_public_projection_search_and_staff_privacy(client):
    _, _, rid = seed()
    with session() as s:
        r = s.get(Record, rid)
        r.marc['fields'] += [field('520', value='Казахская аннотация'), field('041', value='kaz'),
            field('080', value='54.1'), field('097', 'b', 'PRIVATE_OPERATOR'),
            field('500', value='PRIVATE_NOTE'), field('541', 'h', 'PRIVATE_PRICE'),
            field('856', 'u', 'https://private.invalid/attachment'), field('990', 'w', 'PRIVATE_SOURCE')]
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(r, 'marc'); s.commit()
    with TestClient(app) as guest:
        response = guest.get(ROOT + '/catalog', params={'q': 'тестовая книга', 'language': 'kk', 'udc': '54'})
        assert response.status_code == 200, response.text
        book = response.json()['data'][0]
        assert book['id'] == f'utblib-{rid}'
        assert book['annotation'] == 'Казахская аннотация'
        assert book['copies']['total'] == 3
        assert guest.get(ROOT + '/books/9786010433649').json()['data']['id'] == book['id']
        detail = guest.get(ROOT + '/books/' + book['id'])
        for word in ('PRIVATE', 'private.invalid', 'inventory_number', 'barcode', 'reader_id', 'notes', 'marc', 'search_text'):
            assert word not in response.text + detail.text
        assert detail.json()['data']['viewer']['canReserve'] is False
        assert guest.get(ROOT + '/catalog?q=PRIVATE').json()['meta']['total'] == 0
        assert guest.get('/api/records').status_code == 401
        for path in ('/catalog', '/facets', '/books/' + book['id']):
            assert guest.post(ROOT + path, json={}).status_code == 405


def test_availability_tracks_issue_return_reservation_and_restrictions(client):
    readers, copies, rid = seed(1)
    def stock(): return client.get(ROOT + f'/books/utblib-{rid}').json()['data']['copies']
    assert stock()['available'] == 1
    result = issue(client, readers[0], copies)
    assert result.status_code == 200, result.text
    assert stock() == {'available': 0, 'issued': 1, 'total': 1}
    assert client.get(ROOT + '/catalog?available_only=true').json()['data'] == []
    assert close(client, result.json()['loans'][0]['id']).status_code == 200
    assert stock()['available'] == 1
    with session() as s:
        res = Reservation(reader_id=readers[1], record_id=rid, assigned_copy_id=copies[0], status='ready_for_pickup')
        s.add(res); s.commit()
    assert stock()['available'] == 0
    with session() as s:
        res = s.query(Reservation).one(); res.status = 'cancelled'; res.assigned_copy_id = None
        d = s.get(CopyCirculation, copies[0]); d.operation_state = 'repair'; s.commit()
    assert stock()['available'] == 0
    with session() as s:
        d = s.get(CopyCirculation, copies[0]); d.operation_state = 'normal'; d.access = 'reading_room'; s.commit()
    assert stock()['available'] == 0
    with session() as s:
        s.get(Copy, copies[0]).status = 'withdrawn'; s.commit()
    assert stock()['total'] == 0


def test_linked_acquisition_copies_filters_and_cache_refresh(client):
    _, copies, rid = seed(1)
    with session() as s:
        branch = Branch(code='TEST-DESK', name='Тестовый зал'); s.add(branch); s.flush()
        acq = Acquisition(request_key=str(uuid4()), payload_hash='x', invoice='PRIVATE_INVOICE', received_on=utcnow().date(), source='PRIVATE_VENDOR')
        s.add(acq); s.flush()
        line = AcquisitionLine(acquisition_id=acq.id, record_id=rid, title_snapshot='Книга', quantity=1, currency='KZT', sigla='PRIVATE_STORAGE')
        s.add(line); s.flush()
        s.add(Copy(line_id=line.id, inventory_number='PRIVATE_INV', barcode='PRIVATE_BAR', sigla='PRIVATE_STORAGE'))
        s.add(CopyCirculation(copy_id=copies[0], branch_id=branch.id))
        t = s.get(Record, rid).type_id
        s.add(Record(type_id=t, marc={'fields': [field(value='Абрикос'), field('260', 'c', '2024')]}, search_text=''))
        s.commit()
    assert client.get(ROOT + '/catalog?branch=TEST-DESK').json()['data'][0]['copies']['total'] == 2
    facets = client.get(ROOT + '/facets').json()
    assert facets['total'] == 2 and facets['branches'][0]['count'] == 1
    result = client.get(ROOT + '/catalog?sort=title&limit=1').json()
    assert result['data'][0]['title']['display'] == 'Абрикос' and result['meta']['totalPages'] == 2
    assert client.get(ROOT + '/catalog?year_from=2020').json()['meta']['total'] == 1
    assert client.get(ROOT + '/catalog?physical_only=1').json()['meta']['total'] == 1
    assert client.get(ROOT + '/catalog?material_type=digital').json()['data'] == []
    with session() as s:
        r = s.get(Record, rid); r.marc = {'fields': [field(value='Обновлено')]}; r.version += 1; s.commit()
    assert client.get(ROOT + '/catalog?q=Обновлено').json()['meta']['total'] == 1
    assert client.get(ROOT + '/catalog?q=Тестовая').json()['meta']['total'] == 0
    assert client.get(ROOT + '/catalog?limit=101').status_code == 422
    assert client.get(ROOT + '/books/utblib-9999999').status_code == 404
