"""The actual issuing desk must survive copy transfers and remain reportable."""
import io
from uuid import uuid4
import pytest
from openpyxl import load_workbook
from sqlalchemy import select, func
from test_catalog import client
from test_circulation import session, seed, desk_id, issue, close, renew
from app.reader_models import Branch
from app.circulation_models import CopyCirculation, Loan, LoanEvent, CirculationNotice, CirculationOperation
from app.circulation_service import today


@pytest.mark.parametrize('point', ['missing', None, 0, -1, 999999, 'inactive'])
def test_requires_an_active_issuing_desk_without_side_effects(client, point):
    readers, copies, _ = seed()
    if point == 'inactive':
        with session() as s:
            b = Branch(code='CLOSED', name='Закрытый абонемент', active=False)
            s.add(b); s.commit(); point = b.id
    body = {'request_key':str(uuid4()), 'reader_id':readers[0], 'items':[{'copy_id':copies[0]}]}
    if point != 'missing': body['branch_id'] = point
    response = client.post('/api/circulation/issue', json=body)
    assert response.status_code == 422, response.text
    with session() as s:
        for model in [Loan, LoanEvent, CirculationNotice, CirculationOperation, CopyCirculation]:
            assert s.scalar(select(func.count()).select_from(model)) == 0


def test_batch_desk_is_independent_of_copy_location_and_idempotent(client):
    readers, copies, _ = seed()
    issuing = desk_id()
    with session() as s:
        storage = Branch(code='STORE', name='Хранилище')
        s.add(storage); s.flush(); storage_id = storage.id
        s.add(CopyCirculation(copy_id=copies[0], branch_id=storage_id))
        s.commit()
    body = {'request_key':str(uuid4()), 'reader_id':readers[0], 'branch_id':issuing,
            'items':[{'copy_id':c} for c in copies[:2]]}
    response = client.post('/api/circulation/issue', json=body)
    assert response.status_code == 200, response.text
    result = response.json()
    assert all(l['branch_id'] == issuing and l['branch_name'] == 'Тестовый абонемент' for l in result['loans'])
    assert client.post('/api/circulation/issue', json=body).json() == result
    assert client.post('/api/circulation/issue', json={**body, 'branch_id':storage_id}).status_code == 409
    with session() as s:
        assert s.get(CopyCirculation, copies[0]).branch_id == storage_id
        assert s.get(CopyCirculation, copies[1]).branch_id is None
        assert all(l.branch_id == issuing for l in s.scalars(select(Loan)))
        assert all(e.details['branch_name'] == 'Тестовый абонемент' for e in s.scalars(select(LoanEvent)))
        assert s.scalar(select(func.count()).select_from(Loan)) == 2


def test_point_filter_export_and_history_survive_return_transfer_and_closure(client):
    readers, copies, _ = seed()
    first = desk_id()
    with session() as s:
        other = Branch(code='DESK-2', name='Абонемент 2')
        s.add(other); s.commit(); second = other.id
    response = issue(client, readers[0], [copies[0]], branch_id=first)
    assert response.status_code == 200, response.text
    loan = response.json()['loans'][0]['id']
    assert renew(client, loan).status_code == 200
    assert close(client, loan, version=2).status_code == 200
    with session() as s:
        s.get(CopyCirculation, copies[0]).branch_id = second
        s.get(Branch, first).active = False
        s.commit()
    # The same physical copy is subsequently issued at another desk.
    assert issue(client, readers[1], [copies[0]], branch_id=second).status_code == 200
    detail = client.get(f'/api/circulation/loans/{loan}').json()
    assert detail['branch_id'] == first and detail['branch_name'] == 'Тестовый абонемент'
    options = client.get('/api/circulation/options').json()
    assert first not in [b['id'] for b in options['branches']]
    assert first in [b['id'] for b in options['history_branches']]
    assert client.get('/api/circulation/loans', params={'branch_id':first}).json()['total'] == 1

    path = '/api/statistics/circulation'
    period = {'date_from':str(today()), 'date_to':str(today()), 'group_by':'branch_id'}
    report = client.get(path, params=period)
    assert report.status_code == 200, report.text
    assert report.json()['totals']['loans'] == 2
    assert {r['key']:r['loans'] for r in report.json()['rows']} == {str(first):1, str(second):1}
    assert client.get(path, params={**period, 'branch_id':str(first)}).json()['totals']['readers'] == 1
    assert client.get(path, params={**period, 'branch_id':[str(first),str(second)]}).json()['totals']['loans'] == 2
    options = client.get(path+'/options').json()['filters']['branch_id']
    assert {'value':str(first), 'label':'Тестовый абонемент'} in options
    exported = client.get(path+'/export', params={**period, 'branch_id':str(first), 'format':'xlsx'})
    assert exported.status_code == 200, exported.text
    rows = list(load_workbook(io.BytesIO(exported.content)).active.values)
    assert any(row[0]=='Пункт выдачи (абонемент)' and row[1]=='Тестовый абонемент' for row in rows)
    assert next(row for row in rows if row[0]=='Итого без повторов')[3:7] == (1,1,1,1)
