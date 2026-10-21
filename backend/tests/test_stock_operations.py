from uuid import uuid4
from datetime import date
from test_catalog import client,make_type,payload
from test_acquisitions import save,add_body
from test_existing_copies import body as existing_body

def setup(client,n=3):
    id=save(client,payload(make_type(client)))['id']
    p=add_body(id,n,'1000');p['received_on']='2020-01-01'
    receipt=client.post('/api/acquisitions',json=p).json()
    return id,receipt

def correction(client,r,**kwargs):
    detail=client.get('/api/acquisitions/'+str(r['id'])).json()
    result={k:detail[k] for k in ('version','invoice','received_on','source','note')}
    result.update(request_key=str(uuid4()),reason='Исправление ошибки',lines=[{k:l[k] for k in ('id','record_id','quantity','unit_price','currency','sigla','note')} for l in detail['lines']])
    result.update(kwargs);return result

def withdrawal(c,**kwargs):
    return {'request_key':str(uuid4()),'copy_id':c['id'],'version':c['version'],'reason':'Ветхость','act_number':'Акт 12','withdrawn_on':'2026-10-20',**kwargs}

def test_withdraw_by_inventory_preserves_incoming_and_blocks_repeat(client):
    id,r=setup(client);copies=client.get(f'/api/records/{id}/copies').json();c=copies['items'][0]
    found=client.get('/api/copies/lookup',params={'inventory_number':c['inventory_number']}).json()
    assert found['title'] and found['id']==c['id']
    before=client.get('/api/acquisitions/summary').json();p=withdrawal(c)
    out=client.post('/api/withdrawals',json=p);assert out.status_code==201,out.text
    assert out.json()['snapshot']['unit_price']=='1000.00'
    assert client.post('/api/withdrawals',json=p).json()['id']==out.json()['id']
    assert client.post('/api/withdrawals',json=withdrawal(c)).status_code==409
    assert client.get('/api/withdrawals').json()['total']==1
    assert client.get(f'/api/records/{id}/copies').json()['active']==2
    assert client.get('/api/acquisitions/summary').json()==before
    assert client.put('/api/acquisitions/'+str(r['id']),json=correction(client,r)).status_code==409
    assert client.post(f"/api/acquisitions/{r['id']}/cancel",json={'version':1,'request_key':str(uuid4()),'reason':'Ошибка'}).status_code==409

def test_existing_fund_can_be_withdrawn_without_receipt(client):
    id=save(client,payload(make_type(client)))['id']
    c=client.post(f'/api/records/{id}/copies',json=existing_body()).json()
    assert client.post('/api/withdrawals',json=withdrawal(c)).status_code==201
    assert client.get('/api/acquisitions/summary').json()['quantity']==0
    assert client.get(f'/api/records/{id}/copies').json()['active']==0
    edit={k:c[k] for k in ('version','inventory_number','barcode','sigla','checked_on','note')}
    assert client.put('/api/copies/'+str(c['id']),json=edit).status_code==409

def test_correction_adds_only_missing_copies_and_audits_prices(client):
    id,r=setup(client);p=correction(client,r,invoice='Исправлено')
    oldids={c['id'] for c in client.get(f'/api/records/{id}/copies').json()['items']}
    p['lines'][0].update(quantity=5,unit_price='2500.25')
    out=client.put('/api/acquisitions/'+str(r['id']),json=p);assert out.status_code==200,out.text
    assert out.json()['version']==2
    assert client.put('/api/acquisitions/'+str(r['id']),json=p).json()['version']==2
    copies=client.get(f'/api/records/{id}/copies').json();assert copies['active']==5 and oldids<={c['id'] for c in copies['items']}
    assert client.get('/api/acquisitions/summary').json()['totals']=={'KZT':'12501.25'}
    h=client.get(f"/api/acquisitions/{r['id']}/history").json();assert len(h)==1
    assert h[0]['before']['lines'][0]['unit_price']=='1000.00' and h[0]['after']['lines'][0]['unit_price']=='2500.25'
    p['request_key']=str(uuid4());assert client.put('/api/acquisitions/'+str(r['id']),json=p).status_code==409

def test_decrease_requires_specific_ids_and_retains_history(client):
    id,r=setup(client);copies=client.get(f'/api/records/{id}/copies').json()['items'];p=correction(client,r)
    p['lines'][0]['quantity']=1
    assert client.put('/api/acquisitions/'+str(r['id']),json=p).status_code==422
    assert client.get(f'/api/records/{id}/copies').json()['active']==3
    p['lines'][0]['cancel_copy_ids']=[c['id'] for c in copies[:2]]
    assert client.put('/api/acquisitions/'+str(r['id']),json=p).status_code==200
    rows=client.get(f'/api/records/{id}/copies').json();assert rows['active']==1 and rows['total']==3
    assert [c['id'] for c in rows['items'] if c['status']=='active']==[copies[2]['id']]
    assert client.get('/api/acquisitions/summary').json()['quantity']==1
    assert client.post('/api/withdrawals',json=withdrawal(copies[0])).status_code==409

def test_correction_new_title_and_zero_old_line(client):
    id,r=setup(client,1);other=save(client,payload(1))['id'];p=correction(client,r)
    c=client.get(f'/api/records/{id}/copies').json()['items'][0]
    p['lines'][0].update(quantity=0,cancel_copy_ids=[c['id']])
    p['lines'].append({'record_id':other,'quantity':2,'unit_price':None})
    out=client.put('/api/acquisitions/'+str(r['id']),json=p);assert out.status_code==200,out.text
    summary=client.get('/api/acquisitions/summary').json();assert summary['quantity']==2 and summary['titles']==1 and summary['unpriced_count']==2
    assert client.get(f'/api/records/{id}/copies').json()['active']==0

def test_cancel_excludes_totals_keeps_records_and_numbers(client):
    id,r=setup(client);p={'request_key':str(uuid4()),'version':1,'reason':'Ошибочный ввод'}
    out=client.post(f"/api/acquisitions/{r['id']}/cancel",json=p);assert out.status_code==200,out.text
    assert out.json()['status']=='cancelled'
    assert client.post(f"/api/acquisitions/{r['id']}/cancel",json=p).json()['version']==2
    assert client.get('/api/acquisitions/summary').json()['quantity']==0
    assert client.get('/api/acquisitions').json()['total']==1
    copies=client.get(f'/api/records/{id}/copies').json();assert copies['active']==0 and copies['total']==3
    assert all(c['status']=='cancelled' for c in copies['items'])
    assert client.post(f'/api/records/{id}/copies',json=existing_body(inventory_number=copies['items'][0]['inventory_number'])).status_code==409
    assert client.get('/api/records/'+str(id)).status_code==200

def test_withdrawal_validation_authorization_and_key_conflict(client):
    id,r=setup(client,1);c=client.get(f'/api/records/{id}/copies').json()['items'][0];p=withdrawal(c)
    assert client.post('/api/withdrawals',json=p,headers={'X-Admin-Key':'bad'}).status_code==401
    for changes in [{'act_number':''},{'reason':' '},{'withdrawn_on':'2999-01-01'},{'withdrawn_on':'2010-01-01'}]:
        assert client.post('/api/withdrawals',json={**p,**changes}).status_code==422
    assert client.post('/api/withdrawals',json=p).status_code==201
    assert client.post('/api/withdrawals',json={**p,'note':'Другой запрос'}).status_code==409
    assert client.get('/api/copies/lookup?inventory_number=not-found').status_code==404

def test_correction_invalid_new_record_rolls_back_all(client):
    id,r=setup(client);p=correction(client,r);p['lines'][0]['quantity']=10
    p['lines'].append({'record_id':999999,'quantity':1})
    assert client.put('/api/acquisitions/'+str(r['id']),json=p).status_code==422
    assert client.get(f'/api/records/{id}/copies').json()['active']==3
    assert client.get(f"/api/acquisitions/{r['id']}/history").json()==[]
