from uuid import uuid4
from io import BytesIO
from openpyxl import load_workbook
from test_catalog import client, make_type, payload, field
from test_acquisitions import save, add_body
from test_stock_operations import correction, withdrawal


def ksu(c, number=17, **changes):
    body={'request_key':str(uuid4()),'number':number,'year':2026,'registered_on':'2026-11-05',
          'source':'Дарение','invoice':'Акт 17',**changes}
    response=c.post('/api/ksu/entries',json=body)
    assert response.status_code==201,response.text
    assert c.post('/api/ksu/entries',json=body).json()==response.json()
    return response.json()


def book(c):
    p=payload(make_type(c))
    p['marc']['fields'] += [field('952','a','КУК'),field('952','j','Финансы'),field('041','a','kaz'),field('080','a','3')]
    return save(c,p)


def copy(c,r,e,**changes):
    response=c.post(f"/api/records/{r['id']}/copies",json={'request_key':str(uuid4()),
        'unit_price':'250.50','ksu_entry_id':e['id'] if e else None,**changes})
    assert response.status_code==201,response.text
    return response.json()


def edit(c,x,**changes):
    response=c.put(f"/api/copies/{x['id']}",json={'version':x['version'],
        'inventory_number':x['inventory_number'],'barcode':x['barcode'],**changes})
    assert response.status_code==200,response.text
    return response.json()


def report(c):return c.get('/api/ksu/report?year=2026').json()


def test_create_independent_ksu_copy_workflow_both_reports_and_export(client):
    r=book(client);e=ksu(client)
    assert report(client)['rows'][0]['metrics']['copies']==0
    x=copy(client,r,e,invoice='Накладная 2',source='Поставщик',received_on='2026-10-01')
    copy(client,r,e,unit_price='100.25');copy(client,r,None,unit_price='999')
    d=report(client)
    assert d['totals']['copies']==2 and d['totals']['titles']==1 and d['totals']['on_amount']=='350.75'
    assert d['totals']['study_kaz']==2 and d['issue_count']==0
    assert client.get('/api/acquisitions').json()['total']==0
    assert x['invoice']=='Накладная 2' and x['source']=='Поставщик'
    members=client.get(f"/api/ksu/entries/{e['id']}/copies?limit=1").json()
    assert members['total']==2 and members['items'][0]['id']==x['id']
    assert client.get(f"/api/records/{r['id']}/copies").json()['items'][0]['ksu_number']=='17/2026'
    specs=client.get('/api/ksu/specialties/report?date_from=2026-11-05&date_to=2026-11-05').json()
    assert specs['total']=={'titles':1,'copies':2,'amount':'350.75','unpriced_count':0}
    assert specs['totals']['specialty:Финансы']['copies']==2
    ws=load_workbook(BytesIO(client.get('/api/ksu/export?year=2026').content)).active
    assert ws['F4'].value==2 and ws['G4'].value==350.75


def test_edit_all_copy_fields_move_unlink_and_clear_price(client):
    r=book(client);a=ksu(client);b=ksu(client,18);x=copy(client,r,a)
    x=edit(client,x,unit_price='750.25',currency='KZT',received_on='2025-01-01',source='Архив',
        invoice='Старый документ',sigla='АБ1',checked_on='2026-10-01',note='Исправлено',ksu_entry_id=b['id'])
    assert x['unit_price']=='750.25' and x['invoice']=='Старый документ' and x['source']=='Архив'
    rows=report(client)['rows'];assert rows[0]['metrics']['copies']==0 and rows[1]['metrics']['on_amount']=='750.25'
    assert client.put(f"/api/copies/{x['id']}",json={'version':1,'inventory_number':x['inventory_number'],'barcode':x['barcode'],'unit_price':'1'}).status_code==409
    x=edit(client,x,unit_price=None,received_on=None,source='',invoice='',checked_on=None)
    assert x['unit_price'] is None and x['received_on'] is None
    assert report(client)['unpriced_count']==1
    assert client.get('/api/ksu/export?year=2026').status_code==409
    x=edit(client,x,unit_price='0');assert report(client)['unpriced_count']==0
    x=edit(client,x,ksu_entry_id=None);assert report(client)['totals']['copies']==0
    h=client.get(f"/api/copies/{x['id']}/history").json()
    assert len(h)==4 and h[0]['before']['ksu_entry_id']==a['id'] and h[0]['after']['ksu_entry_id']==b['id']


def test_receipt_price_edit_changes_only_one_copy_and_preserves_batch_operations(client):
    r=book(client);a=client.post('/api/acquisitions',json=add_body(r['id'],3,'100')).json()
    copies=client.get(f"/api/records/{r['id']}/copies").json()['items'];x=copies[0]
    x=edit(client,x,unit_price='200',invoice='Личный документ',source='Другой источник',received_on='2026-01-02')
    assert client.get('/api/acquisitions/summary').json()['totals']=={'KZT':'400.00'}
    assert report(client)['totals']['on_amount']=='400.00'
    prices=[c['unit_price'] for c in client.get(f"/api/records/{r['id']}/copies").json()['items']]
    assert prices==['200.00','100.00','100.00']
    detail=client.get(f"/api/acquisitions/{a['id']}").json();assert detail['version']==2
    assert sum(l['quantity'] for l in detail['lines'])==3
    p=correction(client,detail,source='Новый источник',invoice='Новая накладная')
    assert client.put(f"/api/acquisitions/{a['id']}",json=p).status_code==200
    rows=client.get(f"/api/records/{r['id']}/copies").json()['items']
    assert rows[0]['source']=='Другой источник' and rows[0]['invoice']=='Личный документ'
    assert rows[1]['source']=='Новый источник' and rows[1]['invoice']=='Новая накладная'
    # Cancellation still handles every split line; unrelated members are retained.
    other=copy(client,r,{'id':x['ksu_entry_id']})
    assert client.post(f"/api/acquisitions/{a['id']}/cancel",json={'request_key':str(uuid4()),'version':3,'reason':'Ошибка'}).status_code==200
    assert report(client)['totals']['copies']==1 and report(client)['totals']['on_amount']=='250.50'
    assert client.get(f"/api/ksu/entries/{x['ksu_entry_id']}/copies").json()['items'][0]['id']==other['id']


def test_entry_number_uniqueness_edit_history_and_permissions(client):
    a=ksu(client);b=ksu(client,18)
    assert client.post('/api/ksu/entries',json={'request_key':str(uuid4()),'number':17,'year':2026,'registered_on':'2026-11-05'}).status_code==409
    body={k:a[k] for k in ('version','number','year','registered_on','document_on','source','invoice','note')}
    body.update(number=18,reason='Исправление номера')
    assert client.put(f"/api/ksu/entries/{a['id']}",json=body).status_code==409
    body['number']=19
    assert client.put(f"/api/ksu/entries/{a['id']}",json=body).status_code==200
    assert client.put(f"/api/ksu/entries/{a['id']}",json=body).status_code==409
    assert len(client.get(f"/api/ksu/history/{a['id']}").json())==2
    from test_security import add,login
    from fastapi.testclient import TestClient
    from app.main import app
    add(client,username='copycataloger',permissions=['catalog.view','copies.edit'],role='viewer')
    with TestClient(app) as c:
        login(c,'copycataloger')
        assert c.get('/api/copies/ksu-options').status_code==200
        assert c.post('/api/ksu/entries',json={}).status_code==403


def test_invalid_links_withdrawals_and_optional_fields_on_old_clients(client):
    r=book(client);e=ksu(client);x=copy(client,r,e)
    assert client.post(f"/api/records/{r['id']}/copies",json={'request_key':str(uuid4()),'ksu_entry_id':999999}).status_code==422
    assert client.put(f"/api/copies/{x['id']}",json={'version':1,'inventory_number':x['inventory_number'],'barcode':x['barcode'],'ksu_entry_id':999999}).status_code==422
    x=edit(client,x,note='Только примечание')
    assert x['unit_price']=='250.50' and x['ksu_entry_id']==e['id']
    response=client.post('/api/withdrawals',json=withdrawal(x));assert response.status_code==201,response.text
    assert report(client)['totals']['copies']==1
    assert client.put(f"/api/copies/{x['id']}",json={'version':x['version'],'inventory_number':x['inventory_number'],'barcode':x['barcode']}).status_code==409
