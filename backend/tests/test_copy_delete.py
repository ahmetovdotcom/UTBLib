from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select, func, text

from test_catalog import client
from app.main import app
from app.db import Copy, CopyHistory, CopyDeletion
from app.marcsql_copies import MarcsqlCopySource
from test_copy_ksu import book, ksu, copy, edit, report
from test_acquisitions import add_body
from test_stock_operations import correction, withdrawal
from test_circulation import seed, issue, close, session
from test_security import add, login


@pytest.fixture(autouse=True)
def enforce_foreign_keys(client):
    with session() as s:
        s.execute(text('PRAGMA foreign_keys=ON'))
        assert s.scalar(text('PRAGMA foreign_keys'))==1


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
    assert response.json()['status']=='deleted'
    assert response.json()['version']==item['version']+1
    assert delete(client,item,body).json()==response.json()
    assert delete(client,item,{**body,'version':2}).status_code==409
    assert delete(client,item).status_code==404
    holdings=client.get(f"/api/records/{r['id']}/copies").json()
    assert holdings['active']==1 and holdings['total']==1
    assert all(c['id']!=item['id'] for c in holdings['items'])
    assert client.get('/api/statistics/book-fund').json()['totals']['total']==1
    assert report(client)['totals']['copies']==1
    assert report(client)['totals']['on_amount']=='100.25'
    members=client.get(f"/api/ksu/entries/{e['id']}/copies").json()
    assert members['total']==1 and members['items'][0]['id']==other['id']
    assert client.get('/api/acquisitions').json()['total']==0
    assert client.get(f"/api/records/{r['id']}").status_code==200
    history=client.get(f"/api/copies/{item['id']}/history").json()
    assert len(history)==1 and history[0]['before']['status']=='active'
    assert history[0]['after']['action']=='delete_permanently' and history[0]['after']['actor_id']==1
    with session() as s:
        assert s.scalar(select(MarcsqlCopySource)).copy_id is None
        assert s.get(Copy,item['id']) is None
        assert s.scalar(select(func.count()).select_from(CopyHistory))==0
        assert s.get(CopyDeletion,item['id']).snapshot['copy']['inventory_number']==item['inventory_number']


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


def test_delete_blocks_active_and_historical_loans_and_reservations(client):
    readers,ids,rid=seed(2)
    item=client.get(f'/api/records/{rid}/copies').json()['items'][0]
    loan=issue(client,readers[0],[ids[0]]).json()['loans'][0]
    assert delete(client,item).status_code==409
    assert close(client,loan['id']).status_code==200
    # Refresh after circulation changes; the closed loan must not be removed.
    item=client.get(f'/api/records/{rid}/copies').json()['items'][0]
    response=delete(client,item);assert response.status_code==409,response.text
    assert 'история' in response.json()['detail']
    assert not item['can_delete'] and item['can_edit']
    assert client.get(f"/api/circulation/loans/{loan['id']}").status_code==200
    assert issue(client,readers[0],[ids[0]]).status_code==200
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


def test_delete_frees_both_identifiers_in_another_record_and_keeps_retries_safe(client):
    from test_catalog import payload
    from test_existing_copies import body as existing_body
    r=book(client)
    creation=existing_body(inventory_number='000123',barcode='000987')
    item=client.post(f"/api/records/{r['id']}/copies",json=creation).json()
    # Generate circulation detail and an edit audit before removing the copy.
    client.get(f"/api/records/{r['id']}/copies")
    item=edit(client,item,note='Ошибочно добавлен в эту карточку')
    body={'version':item['version'],'request_key':str(uuid4())}
    response=delete(client,item,body)
    assert response.status_code==200,response.text
    other=client.post('/api/records',json=payload(r['type_id'])).json()
    replacement=client.post(f"/api/records/{other['id']}/copies",json={**creation,'request_key':str(uuid4())})
    assert replacement.status_code==201,replacement.text
    new=replacement.json()
    assert new['id']!=item['id'] and new['inventory_number']=='000123' and new['barcode']=='000987'
    assert delete(client,item,body).json()==response.json()
    assert client.get(f"/api/records/{other['id']}/copies").json()['active']==1
    assert len(client.get(f"/api/copies/{item['id']}/history").json())==2
    # A delayed create or edit request cannot resurrect the deleted copy.
    retry=client.post(f"/api/records/{r['id']}/copies",json=creation)
    assert retry.status_code==409 and 'уже удалён' in retry.json()['detail']
    assert delete(client,new,body).status_code==409
    with session() as s:
        from app.circulation_models import CopyCirculation
        assert s.get(CopyCirculation,item['id']) is None
        assert s.get(Copy,new['id']) is not None


def test_deleted_import_is_not_recreated_but_numbers_can_be_reused(client):
    from test_marcsql_copies import setup, post, row
    from test_existing_copies import body as existing_body
    rid=setup(client); raw=row()
    post(client,[raw])
    item=client.get(f'/api/records/{rid}/copies').json()['items'][0]
    assert delete(client,item).status_code==200
    result=post(client,[raw])[0]
    assert result['status']=='error' and 'удалён' in result['error']
    result=client.post(f'/api/records/{rid}/copies',json=existing_body(
        inventory_number=item['inventory_number'],barcode=item['barcode']))
    assert result.status_code==201,result.text
    assert post(client,[raw])[0]['status']=='error'
    assert client.get(f'/api/records/{rid}/copies').json()['total']==1


@pytest.mark.parametrize('origin',['soft_delete','receipt_cancel','receipt_correction'])
def test_purge_previously_cancelled_copy_does_not_subtract_receipt_twice(client,origin):
    from app.acquisitions import copy_output, digest
    from app.db import AcquisitionLine,Acquisition
    from fastapi.encoders import jsonable_encoder
    r=book(client)
    receipt=client.post('/api/acquisitions',json=add_body(r['id'],2,'100')).json()
    url=f"/api/acquisitions/{receipt['id']}"
    item=client.get(f"/api/records/{r['id']}/copies").json()['items'][0]
    legacy_body={'version':item['version'],'request_key':str(uuid4())}
    if origin=='receipt_cancel':
        assert client.post(url+'/cancel',json={'version':1,'request_key':str(uuid4()),'reason':'Ошибка'}).status_code==200
    elif origin=='receipt_correction':
        p=correction(client,receipt)
        p['lines'][0].update(quantity=1,cancel_copy_ids=[item['id']])
        assert client.put(url,json=p).status_code==200
    else:
        # Precisely emulate the already deployed soft-delete behavior.
        with session() as s:
            c=s.get(Copy,item['id']);line=s.get(AcquisitionLine,c.line_id)
            acq=s.get(Acquisition,line.acquisition_id)
            before=jsonable_encoder(copy_output(c,line,acq))
            c.status='cancelled';c.version+=1;line.quantity-=1;acq.version+=1
            after={**jsonable_encoder(copy_output(c,line,acq)),'action':'delete',
                'delete_request_key':legacy_body['request_key'],
                'payload_hash':digest({'id':c.id,**legacy_body}),'actor_id':1}
            s.add(CopyHistory(copy_id=c.id,before=before,after=after));s.commit()
        assert delete(client,item,legacy_body).json()['status']=='cancelled'
    before_receipt=client.get(url).json()
    before_report=report(client)
    item=client.get(f"/api/records/{r['id']}/copies").json()['items'][0]
    assert not item['can_edit'] and item['can_delete']
    response=delete(client,item)
    assert response.status_code==200,response.text
    after_receipt=client.get(url).json()
    assert after_receipt.pop('copies')==[c for c in before_receipt.pop('copies') if c['id']!=item['id']]
    assert after_receipt==before_receipt
    assert report(client)==before_report
    with session() as s:
        assert s.get(Copy,item['id']) is None
