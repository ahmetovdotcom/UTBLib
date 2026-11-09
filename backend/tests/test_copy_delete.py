from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select, func

from test_catalog import client
from app.main import app
from app.db import Copy, CopyHistory
from app.marcsql_copies import MarcsqlCopySource
from test_copy_ksu import book, ksu, copy, edit, report
from test_acquisitions import add_body
from test_stock_operations import correction, withdrawal
from test_circulation import seed, issue, close, session
from test_security import add, login


def delete(c, item, body=None):
    return c.request('DELETE', f"/api/copies/{item['id']}", json=body or {
        'version': item['version'], 'request_key': str(uuid4())})


def test_delete_excludes_from_fund_and_ksu_preserving_source_and_history(client):
    r=book(client); e=ksu(client)
    item=copy(client,r,e); other=copy(client,r,e,unit_price='100.25')
    with session() as s:
        s.add(MarcsqlCopySource(source='test',inv_id=123,doc_id=456,copy_id=item['id'],
            raw={'T990t':'17/2026'},checksum='test'))
        s.commit()
    body={'version':item['version'],'request_key':str(uuid4())}
    response=delete(client,item,body)
    assert response.status_code==200,response.text
    assert response.json()['status']=='cancelled'
    assert response.json()['version']==item['version']+1
    assert delete(client,item,body).json()==response.json()
    assert delete(client,item,{**body,'version':2}).status_code==409
    assert delete(client,item).status_code==409
    holdings=client.get(f"/api/records/{r['id']}/copies").json()
    assert holdings['active']==1 and holdings['total']==2
    assert not next(c for c in holdings['items'] if c['id']==item['id'])['can_edit']
    assert client.get('/api/statistics/book-fund').json()['totals']['total']==1
    assert report(client)['totals']['copies']==1
    assert report(client)['totals']['on_amount']=='100.25'
    members=client.get(f"/api/ksu/entries/{e['id']}/copies").json()
    assert members['total']==1 and members['items'][0]['id']==other['id']
    assert client.get('/api/acquisitions').json()['total']==0
    assert client.get(f"/api/records/{r['id']}").status_code==200
    history=client.get(f"/api/copies/{item['id']}/history").json()
    assert len(history)==1 and history[0]['before']['status']=='active'
    assert history[0]['after']['action']=='delete' and history[0]['after']['actor_id']==1
    with session() as s:
        assert s.scalar(select(MarcsqlCopySource)).copy_id==item['id']
        assert s.get(Copy,item['id']).inventory_number==item['inventory_number']


def test_delete_receipt_copy_updates_quantity_amount_version_and_audit(client):
    r=book(client)
    receipt=client.post('/api/acquisitions',json=add_body(r['id'],3,'100')).json()
    url=f"/api/acquisitions/{receipt['id']}"
    items=client.get(f"/api/records/{r['id']}/copies").json()['items']
    item=edit(client,items[0],unit_price='250')  # A separate price line.
    stale_correction=correction(client,receipt)
    body={'version':item['version'],'request_key':str(uuid4())}
    response=delete(client,item,body)
    assert response.status_code==200,response.text
    assert delete(client,item,body).json()==response.json()
    detail=client.get(url).json()
    assert detail['quantity']==2 and detail['totals']=={'KZT':'200.00'}
    assert detail['version']==3 and detail['status']=='posted'
    assert next(l for l in detail['lines'] if l['id']==item['line_id'])['quantity']==0
    assert client.get('/api/acquisitions/summary').json()['quantity']==2
    assert report(client)['totals']['on_amount']=='200.00'
    history=client.get(url+'/history').json()
    deleted=next(h for h in history if h['action']=='copy_delete')
    assert deleted['before']['quantity']==3 and deleted['after']['quantity']==2
    assert client.put(url,json=stale_correction).status_code==409
    assert client.put(url,json=correction(client,detail,invoice='Исправлено')).status_code==200

    # Deleting the remaining copies cancels an empty receipt. An unrelated
    # independent member of its KSU remains included in the reports.
    copy(client,r,{'id':item['ksu_entry_id']},unit_price='50')
    refreshed=client.get(f"/api/records/{r['id']}/copies").json()['items']
    for remaining in [c for c in refreshed if c['id'] in {x['id'] for x in items[1:]}]:
        assert delete(client,remaining).status_code==200
    detail=client.get(url).json()
    assert detail['status']=='cancelled' and detail['quantity']==0
    assert client.get('/api/acquisitions/summary').json()['quantity']==0
    assert report(client)['totals']['copies']==1
    assert report(client)['totals']['on_amount']=='50.00'


def test_delete_blocks_stale_form_and_withdrawn_copy_without_side_effects(client):
    r=book(client);item=copy(client,r,None)
    changed=edit(client,item,note='Другой сотрудник исправил данные')
    assert delete(client,item).status_code==409
    assert client.get('/api/statistics/book-fund').json()['totals']['total']==1
    assert client.post('/api/withdrawals',json=withdrawal(changed)).status_code==201
    assert delete(client,changed).status_code==409
    with session() as s:
        assert s.get(Copy,item['id']).status=='withdrawn'
        assert s.scalar(select(func.count()).select_from(CopyHistory))==2
    assert delete(client,{'id':999999,'version':1}).status_code==404


def test_delete_blocks_loans_and_reservations_then_preserves_closed_loan(client):
    readers,ids,rid=seed(2)
    item=client.get(f'/api/records/{rid}/copies').json()['items'][0]
    loan=issue(client,readers[0],[ids[0]]).json()['loans'][0]
    assert delete(client,item).status_code==409
    assert close(client,loan['id']).status_code==200
    # Refresh after circulation changes; the closed loan must not be removed.
    item=client.get(f'/api/records/{rid}/copies').json()['items'][0]
    response=delete(client,item);assert response.status_code==200,response.text
    assert client.get(f"/api/circulation/loans/{loan['id']}").status_code==200
    assert issue(client,readers[1],[ids[0]],override=True,reason='Не разрешает удалённый экземпляр').status_code==409
    reservation=client.post('/api/circulation/reservations',json={
        'request_key':str(uuid4()),'reader_id':readers[1],'record_id':rid})
    assert reservation.status_code==200,reservation.text
    reserved=client.get(f'/api/records/{rid}/copies').json()['items'][1]
    assert reserved['availability']=='reserved'
    assert delete(client,reserved).status_code==409


def test_delete_requires_copy_rights_and_csrf(client):
    r=book(client);item=copy(client,r,None)
    add(client,username='viewer')
    add(client,username='cataloger',permissions=['catalog.view','copies.edit'])
    with TestClient(app) as c:
        assert delete(c,item).status_code==401
        login(c,'viewer')
        assert delete(c,item).status_code==403
        login(c,'cataloger')
        csrf=c.headers.pop('X-CSRF-Token')
        assert delete(c,item).status_code==403
        c.headers['X-CSRF-Token']=csrf
        assert delete(c,item).status_code==200
