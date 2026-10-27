from contextlib import contextmanager
from datetime import date
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from test_catalog import client, field
from app.main import app, db
from app.db import DocumentType, Record, Copy, Acquisition, AcquisitionLine
from app.book_fund import classify, LANGUAGES


def marc(code=None, lang=None, label=None):
    fields = [field()]
    for tag, sub, value in [('952', 'a', code), ('041', 'a', lang), ('952', 'c', label)]:
        for v in value if isinstance(value, list) else [value]:
            if v is not None:
                fields.append(field(tag, sub, v))
    return {'leader': '00000nam a2200000   4500', 'fields': fields}


@pytest.mark.parametrize('code,lang,label,expected', [
    (' КУК ', 'kaz', None, ('study', 'kaz', False)),
    ('кур', None, None, ('study', 'rus', False)),
    ('КУИ', 'eng', None, ('study', 'foreign', False)),
    ('КУМК', 'kaz', None, ('methodical', 'kaz', False)),
    ('КУМР', 'rus', None, ('methodical', 'rus', False)),
    ('МИ/иностр.яз.', 'eng', None, ('methodical', 'foreign', False)),
    ('КНР', 'rus', None, ('science', 'rus', False)),
    ('КСК', 'kaz', None, ('reference', 'kaz', False)),
    ('КХР', 'rus', None, ('fiction', 'rus', False)),
    ('КУР', 'rus', 'Учебно - методическое  пособие', ('methodical', 'rus', False)),
    ('КУК', 'kaz', 'Оқу-әдістемелік құралы', ('methodical', 'kaz', False)),
    (None, 'kaz', 'Оқулық', ('study', 'kaz', False)),
    (None, 'rus', 'Справочник', ('reference', 'rus', False)),
    (None, 'rus', 'Монография', ('science', 'rus', False)),
    (None, None, None, ('other', 'unknown', False)),
    ('новый код', 'rus', 'Учебник', ('other', 'rus', False)),
    (['КУР', 'новый код'], 'rus', None, ('other', 'rus', False)),
    (['КУР', 'КНР'], 'rus', None, ('other', 'rus', False)),
    ('КУК', 'rus', None, ('study', 'unknown', False)),
    ('КУИ', 'eng; rus', None, ('study', 'multilingual', False)),
    ('КУК', ['kaz', 'rus'], None, ('study', 'multilingual', False)),
    ('КУИ', 'engchi', None, ('study', 'multilingual', False)),
    ('КУИ', ['eng', 'eng'], None, ('study', 'foreign', False)),
    ('КУР', 'mul', None, ('study', 'multilingual', False)),
    ('КУР', 'und', None, ('study', 'unknown', False)),
    ('КУК', '???', None, ('study', 'unknown', False)),
    ('CD/рус.яз.', 'rus', None, ('other', 'rus', True)),
    ('АУД/каз.яз.', 'kaz', None, ('other', 'kaz', True)),
    ('ДКИ', 'eng', None, ('other', 'foreign', True)),
    (['CD/рус.яз.', 'КУР'], 'rus', None, ('other', 'rus', False)),
    ('Бр./каз.яз.', 'kaz', None, ('other', 'kaz', False)),
])
def test_classification(code, lang, label, expected):
    assert classify(marc(code, lang, label)) == expected


@contextmanager
def session():
    gen = app.dependency_overrides[db]()
    try:
        yield next(gen)
    finally:
        gen.close()


def test_count_copies_from_both_origins_and_reconcile(client):
    with session() as s:
        t = DocumentType(name='Книга', config=[]); s.add(t); s.flush()
        def record(code=None, lang=None):
            r = Record(type_id=t.id, marc=marc(code, lang), search_text=''); s.add(r); s.flush()
            return r
        def copies(r, n, status='active', line=None):
            for _ in range(n):
                key = str(uuid4())
                s.add(Copy(record_id=None if line else r.id, line_id=line.id if line else None,
                           request_key=key, payload_hash='test', inventory_number=key,
                           barcode=key, sigla='', status=status))
        def receipt_line(r, status='posted'):
            a = Acquisition(request_key=str(uuid4()), payload_hash='test', invoice='',
                            source='', received_on=date(2026, 1, 1), status=status)
            s.add(a); s.flush()
            # Deliberate mismatch: the report must count actual copies, not quantity.
            line = AcquisitionLine(acquisition_id=a.id, record_id=r.id, title_snapshot='',
                                   quantity=999, unit_price=None, currency='KZT', sigla='')
            s.add(line); s.flush()
            return line
        study = record('КУК', 'kaz'); copies(study, 2)
        copies(study, 3, line=receipt_line(study))
        copies(study, 4, status='withdrawn')
        copies(study, 6, status='cancelled')
        copies(study, 7, line=receipt_line(study, 'cancelled'))
        copies(record('КУМР', 'rus'), 2)
        copies(record('КНИ', 'eng'), 3)
        copies(record('КСР', 'rus'), 1)
        copies(record('КХР', 'rus'), 1)
        copies(record('КУИ', 'eng; rus'), 2)
        copies(record('КУК', 'rus'), 4)
        unknown = record(); copies(unknown, 5)
        copies(record('CD/рус.яз.', 'rus'), 8)
        record('КНР', 'rus')  # A catalog record without copies contributes nothing.
        s.commit()
        unknown_id = unknown.id
    response = client.get('/api/statistics/book-fund')
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['totals'] == dict(total=23, kaz=5, rus=4, foreign=3, multilingual=2, unknown=9)
    assert data['records'] == 8 and data['excluded_non_book'] == 8
    assert data['needs_review'] == 9
    for col in ('total', *LANGUAGES):
        assert sum(row[col] for row in data['rows']) == data['totals'][col]
    for row in data['rows']:
        assert row['total'] == sum(row[col] for col in LANGUAGES)
    # Classification follows current catalog edits and does not cache old values.
    with session() as s:
        s.get(Record, unknown_id).marc = marc('КСК', 'kaz'); s.commit()
    updated = client.get('/api/statistics/book-fund').json()
    assert updated['totals']['total'] == 23 and updated['totals']['kaz'] == 10
    assert updated['needs_review'] == 4


def test_loan_does_not_reduce_fund_and_withdrawal_does(client):
    from test_circulation import seed, issue, close
    from test_stock_operations import withdrawal
    readers, copies, record_id = seed(2)
    with session() as s:
        s.get(Record, record_id).marc = marc('КУР', 'rus'); s.commit()
    response = issue(client, readers[0], [copies[0]])
    assert response.status_code == 200, response.text
    assert client.get('/api/statistics/book-fund').json()['totals']['rus'] == 2
    holdings = client.get(f'/api/records/{record_id}/copies').json()['items']
    free = next(c for c in holdings if c['id'] == copies[1])
    assert client.post('/api/withdrawals', json=withdrawal(free)).status_code == 201
    assert client.get('/api/statistics/book-fund').json()['totals']['rus'] == 1
    assert close(client, response.json()['loans'][0]['id']).status_code == 200
    assert client.get('/api/statistics/book-fund').json()['totals']['rus'] == 1


def test_empty_and_permissions(client):
    from test_security import add, login
    empty = client.get('/api/statistics/book-fund').json()
    assert len(empty['rows']) == 6 and empty['totals']['total'] == 0
    assert empty['records'] == empty['needs_review'] == empty['excluded_non_book'] == 0
    add(client, username='viewer', permissions=['catalog.view'])
    add(client, username='analyst', permissions=['statistics.view'])
    with TestClient(app) as c:
        assert c.get('/api/statistics/book-fund').status_code == 401
        login(c, 'viewer')
        assert c.get('/api/statistics/book-fund').status_code == 403
        login(c, 'analyst')
        assert c.get('/api/statistics/book-fund').status_code == 200
