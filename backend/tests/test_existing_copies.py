from uuid import uuid4
from test_catalog import client, make_type, payload, field
from test_acquisitions import save, add_body

def body(**overrides):
    return {'request_key':str(uuid4()),'inventory_number':'OLD-123','barcode':'OLD-456',
            'unit_price':'1500.50','source':'Архив','received_on':'2020-01-01',**overrides}

def test_existing_fund_without_receipt_retry_and_ledger(client):
    record=save(client,payload(make_type(client)));url=f"/api/records/{record['id']}/copies";p=body()
    before=client.get('/api/acquisitions/summary').json()
    r=client.post(url,json=p);assert r.status_code==201,r.text
    copy=r.json()
    assert copy['origin']=='existing_fund' and copy['acquisition_id'] is None and copy['line_id'] is None
    assert copy['unit_price']=='1500.50' and copy['invoice'] is None
    assert client.post(url,json=p).json()['id']==copy['id']
    assert client.get(url).json()['total']==1
    assert client.get('/api/acquisitions/summary').json()==before
    assert client.get('/api/acquisitions').json()['total']==0
    p['note']='Изменённый запрос'
    assert client.post(url,json=p).status_code==409
    assert client.delete(f"/api/records/{record['id']}?version=1").status_code==409

def test_existing_and_acquired_copies_share_list_and_unique_numbers(client):
    id=save(client,payload(make_type(client)))['id'];url=f'/api/records/{id}/copies'
    p=body();copy=client.post(url,json=p).json()
    assert client.post(url,json=body()).status_code==409
    assert client.post('/api/acquisitions',json=add_body(id,2,'2000')).status_code==200
    rows=client.get(url).json()
    assert rows['total']==3 and {c['origin'] for c in rows['items']}=={'existing_fund','acquisition'}
    assert client.get(url+'?q=OLD-123').json()['matched']==1
    assert client.get('/api/acquisitions/summary').json()['quantity']==2
    assert client.get('/api/acquisitions/summary').json()['totals']=={'KZT':'4000.00'}
    update={k:copy[k] for k in ('version','inventory_number','barcode','sigla','checked_on','note')}
    update['note']='Проверен'
    r=client.put(f"/api/copies/{copy['id']}",json=update);assert r.status_code==200,r.text
    assert r.json()['unit_price']=='1500.50' and r.json()['origin']=='existing_fund'
    assert len(client.get(f"/api/copies/{copy['id']}/history").json())==1

def test_existing_copy_validation_auth_and_record_key_scope(client):
    t=make_type(client);a=save(client,payload(t));b=save(client,payload(t))
    url=f"/api/records/{a['id']}/copies"
    assert client.post(url,json=body(),headers={'X-Admin-Key':'bad'}).status_code==401
    assert client.post(url,json=body(unit_price='-1')).status_code==422
    assert client.post(url,json=body(invoice='Нельзя')).status_code==422
    assert client.post('/api/records/999999/copies',json=body()).status_code==404
    p=body(inventory_number='',barcode='',unit_price=None,received_on=None,source='')
    c=client.post(url,json=p).json();assert c['inventory_number'].startswith('INV-') and c['unit_price'] is None
    assert client.post(f"/api/records/{b['id']}/copies",json=p).status_code==409

def test_new_description_quantity_does_not_implicitly_create_acquisition(client):
    p=payload(make_type(client));p['marc']['fields'].append(field('541','n','10'))
    r=save(client,p)
    assert client.get(f"/api/records/{r['id']}/copies").json()['total']==0
    assert client.get('/api/acquisitions').json()['total']==0


def test_catalog_search_by_copy_identifiers(client):
    t=make_type(client)
    a=save(client,payload(t))
    b=save(client,payload(t))
    other=client.post('/api/types',json={'name':'Статья','config':[]}).json()['id']
    c=save(client,payload(other))
    for record,number,barcode in [(a,'FUND-100','00070128'),(a,'FUND-101','00070129'),
                                  (b,'FUND-200','CODE%_42'),(c,'FUND-300','00070130')]:
        r=client.post(f"/api/records/{record['id']}/copies",json=body(inventory_number=number,barcode=barcode))
        assert r.status_code==201,r.text
    def ids(q,**params):
        r=client.get('/api/records',params={'q':q,**params})
        assert r.status_code==200,r.text
        return [row['id'] for row in r.json()]
    assert ids(' 00070128 ')==[a['id']]
    assert ids('fund-100')==[a['id']]
    assert ids('0007012')==[a['id']]  # Two matching copies, one catalog result.
    assert ids('FUND-',type_id=t)==[b['id'],a['id']]
    assert ids('FUND-',type_id=t,limit=1,offset=1)==[a['id']]
    assert ids('%_')==[b['id']]  # Literal characters, not SQL wildcards.
    assert ids('missing-barcode')==[]
    assert set(ids('Тест'))=={a['id'],b['id'],c['id']}
