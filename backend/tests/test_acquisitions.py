from uuid import uuid4
from copy import deepcopy
from test_catalog import client, make_type, payload, field

def new_body(client,quantity='10',price='5000'):
    p=payload(make_type(client));p['request_key']=str(uuid4())
    p['marc']['fields'] += [field('541','n',quantity),field('990','w','УТБ')]
    p['marc']['fields'][-2]['subfields'].append({'code':'h','value':price})
    p['marc']['fields'][-1]['subfields'].append({'code':'c','value':'№10'})
    p['initial_acquisition']={'received_on':'2026-10-20','currency':'KZT'}
    return p

def add_body(record_id,quantity=5,price='6000',currency='KZT'):
    return {'request_key':str(uuid4()),'received_on':'2026-10-21','source':'Другая организация','invoice':'№25',
            'lines':[{'record_id':record_id,'quantity':quantity,'unit_price':price,'currency':currency,'sigla':'аб. 2'}]}

def save(client,p):
    r=client.post('/api/records',json=p);assert r.status_code==201,r.text
    return r.json()

def test_initial_atomic_and_idempotent_and_edit_does_not_add(client):
    p=new_body(client);saved=save(client,p);id=saved['id']
    assert save(client,p)['id']==id
    copies=client.get(f'/api/records/{id}/copies').json();assert copies['total']==10
    assert len({c['inventory_number'] for c in copies['items']})==10
    assert len({c['barcode'] for c in copies['items']})==10
    for c in copies['items']:
        assert c['unit_price']=='5000.00' and c['source']=='УТБ' and c['received_on']=='2026-10-20'
    p['marc']['fields'][0]['subfields'][0]['value']='Другой запрос'
    assert client.post('/api/records',json=p).status_code==409
    body={k:saved[k] for k in ('type_id','marc','version')}
    next(f for f in body['marc']['fields'] if f['tag']=='541')['subfields'][0]['value']='999'
    assert client.put(f'/api/records/{id}',json=body).status_code==200
    assert client.get(f'/api/records/{id}/copies').json()['total']==10
    summary=client.get('/api/acquisitions/summary').json()
    assert summary['quantity']==10 and summary['totals']=={'KZT':'50000.00'}
    assert client.delete(f'/api/records/{id}?version=2').status_code==409

def test_second_party_same_book_price_and_duplicate_retry(client):
    id=save(client,new_body(client))['id'];p=add_body(id)
    r=client.post('/api/acquisitions',json=p);assert r.status_code==200,r.text
    assert client.post('/api/acquisitions',json=p).json()['id']==r.json()['id']
    assert client.get(f'/api/records/{id}/copies').json()['total']==15
    summary=client.get('/api/acquisitions/summary').json()
    assert summary=={'acquisitions':2,'titles':1,'quantity':15,'unpriced_count':0,'totals':{'KZT':'80000.00'}}
    assert client.get('/api/acquisitions/summary?date_from=2026-10-21').json()['totals']=={'KZT':'30000.00'}
    p['lines'][0]['quantity']=7
    assert client.post('/api/acquisitions',json=p).status_code==409
    assert client.get(f'/api/records/{id}/copies').json()['total']==15

def test_multiple_titles_one_invoice_and_unknown_price_not_zero(client):
    t=make_type(client);a=save(client,payload(t));b=save(client,payload(t));p=add_body(a['id'],3,'10.10')
    p['lines'].append({'record_id':b['id'],'quantity':2,'unit_price':None,'currency':'KZT'})
    p['lines'].append({'record_id':b['id'],'quantity':1,'unit_price':'1.99','currency':'USD'})
    result=client.post('/api/acquisitions',json=p);assert result.status_code==200,result.text
    r=result.json();assert r['quantity']==6 and r['unpriced_count']==2 and r['totals']=={'KZT':'30.30','USD':'1.99'}
    assert client.get('/api/acquisitions?record_id='+str(b['id'])).json()['total']==1
    assert client.get('/api/acquisitions/summary').json()['titles']==2

def test_existing_record_with_quantity_never_generates_copies(client):
    t=make_type(client);r=save(client,payload(t));body={k:r[k] for k in ('type_id','marc','version')}
    body['marc']['fields'].append(field('541','n','26 экз'))
    assert client.put('/api/records/'+str(r['id']),json=body).status_code==200
    assert client.get('/api/records/'+str(r['id'])+'/copies').json()['total']==0

def test_invalid_initial_rolls_back_record_and_operation(client):
    p=new_body(client);p['marc']['fields'][-1]['subfields'][0]['value']=''
    assert client.post('/api/records',json=p).status_code==422
    assert client.get('/api/records').json()==[]
    assert client.get('/api/acquisitions').json()['total']==0
    p['marc']['fields'][-1]['subfields'][0]['value']='УТБ'
    assert save(client,p)['id']

def test_invalid_multi_line_rolls_back_everything(client):
    r=save(client,payload(make_type(client)));p=add_body(r['id'])
    p['lines'].append({'record_id':9999999,'quantity':2})
    assert client.post('/api/acquisitions',json=p).status_code==422
    assert client.get('/api/acquisitions').json()['total']==0
    assert client.get(f"/api/records/{r['id']}/copies").json()['total']==0

def test_copy_edit_uniqueness_optimistic_lock_audit_and_ledger(client):
    id=save(client,new_body(client,quantity='2'))['id']
    first,second=client.get(f'/api/records/{id}/copies').json()['items']
    body={k:first[k] for k in ('version','inventory_number','barcode','sigla','checked_on','note')}
    body.update(inventory_number='12345',barcode='200000001',sigla='Читальный зал',checked_on='2026-10-19',note='Проверено')
    r=client.put('/api/copies/'+str(first['id']),json=body);assert r.status_code==200,r.text
    assert r.json()['unit_price']=='5000.00' and r.json()['source']=='УТБ'
    assert client.put('/api/copies/'+str(first['id']),json=body).status_code==409
    body['version']=second['version']
    assert client.put('/api/copies/'+str(second['id']),json=body).status_code==409
    assert len(client.get('/api/copies/'+str(first['id'])+'/history').json())==1
    assert client.get('/api/acquisitions/summary').json()['totals']=={'KZT':'10000.00'}
    body['unit_price']='1'
    assert client.put('/api/copies/'+str(first['id']),json=body).status_code==422

def test_acquisition_auth_limits_and_malformed_quantity(client):
    r=save(client,payload(make_type(client)));p=add_body(r['id'])
    assert client.post('/api/acquisitions',json=p,headers={'X-Admin-Key':'bad'}).status_code==401
    for qty in (0,-1,10001,1.5,'2',True):
        p['lines'][0]['quantity']=qty
        assert client.post('/api/acquisitions',json=p).status_code==422
    p['lines'][0]['quantity']=1;p['lines'][0]['unit_price']='2.001'
    assert client.post('/api/acquisitions',json=p).status_code==422
    assert client.get('/api/acquisitions/summary?date_from=2026-10-21&date_to=2026-10-20').status_code==422

def test_initial_price_currency_and_quantity_validation(client):
    p=new_body(client,quantity='2',price='1 234,50 ₸');r=save(client,p)
    assert client.get(f"/api/records/{r['id']}/copies").json()['items'][0]['unit_price']=='1234.50'
    p['request_key']=str(uuid4());p['marc']['fields'][-2]['subfields'][0]['value']='2 экз'
    assert client.post('/api/records',json=p).status_code==422
