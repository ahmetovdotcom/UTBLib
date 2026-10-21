from copy import deepcopy
from uuid import uuid4
from test_catalog import client,make_type
from test_marcsql import ITEM
from app.main import app,db
from app.reset_local_catalog import clear

def setup(client):
    t=make_type(client)
    r=client.post('/api/import/marcsql',json={'source':'test','doc_id':3,'type_id':t,'rectype':'a','biblevel':'m','item':ITEM,'preview':False})
    assert r.status_code==200,r.text
    return r.json()['record_id']

def row(**kwargs):
    return {'INV_ID':106,'DOC_ID':3,'T090e':'00112494','T876p':'00070128','T090f':'ЧЗ','T876c':'2250.00',
        'INVMODE':'I','STATE':1,'CNT':1,'REGDATE':45712.0,'DATE1':None,'OFFDATE':None,'WROFFACT':None,
        'SIGLA_ID':11,'_SIGLA_SHORTNAME':'ЧЗ','SOURCE':'УТБ','NOTES':'Старый фонд','CUSTOM1':'Исходное значение',**kwargs}

def post(client,rows,preview=False):
    r=client.post('/api/import/marcsql-copies',json={'source':'test','rows':rows,'preview':preview})
    assert r.status_code==200,r.text
    return r.json()['results']

def test_preview_and_import_preserve_identifiers_archive_and_no_receipts(client):
    id=setup(client);raw=row()
    assert post(client,[raw],True)[0]['status']=='preview'
    assert client.get(f'/api/records/{id}/copies').json()['total']==0
    out=post(client,[raw])[0];assert out['status']=='created',out
    c=client.get(f'/api/records/{id}/copies').json()['items'][0]
    assert c['inventory_number']=='00112494' and c['barcode']=='00070128'
    assert c['unit_price']=='2250.00' and c['record_id']==id and c['acquisition_id'] is None
    assert c['received_on'] is None and c['checked_on'] is None
    assert client.get(f"/api/copies/{c['id']}/marcsql-source").json()['raw']==raw
    assert client.get('/api/acquisitions/summary').json()['quantity']==0
    assert client.get('/api/withdrawals').json()['total']==0
    assert post(client,[raw])[0]['status']=='unchanged'
    assert client.get(f'/api/records/{id}/copies').json()['total']==1

def test_skips_four_disputed_rows_and_preserves_raw_in_report(client):
    setup(client)
    rows=[row(INV_ID=i,STATE=2,OFFDATE=45932.3,WROFFACT='1',NOTES='Дефектность') for i in (11746,13183,24247)]
    rows.append(row(INV_ID=64313,DOC_ID=16512,INVMODE='U',T090e='',T876p=''))
    out=post(client,rows)
    assert all(r['status']=='skipped' for r in out)
    assert [r['raw'] for r in out]==rows

def test_missing_barcode_is_explicit_stable_internal_identifier_and_unknown_price(client):
    id=setup(client);out=post(client,[row(T876p='',T876c='',T090f='')])[0]
    assert out['barcode_generated'] and out['barcode'].startswith('MARC-NOBARCODE-')
    assert out['unit_price'] is None and out['sigla']=='ЧЗ'
    assert post(client,[row(T876p='',T876c='',T090f='')])[0]['status']=='unchanged'

def test_one_invalid_row_does_not_rollback_other_rows_and_conflicts_never_overwrite(client):
    id=setup(client)
    rows=[row(),row(INV_ID=107),row(INV_ID=108,T090e='108',T876p='',T876c='0.00'),row(INV_ID=109,T090e='109',T876p='',T876c='неизвестно')]
    out=post(client,rows);assert [r['status'] for r in out]==['created','error','created','error']
    assert client.get(f'/api/records/{id}/copies').json()['total']==2
    assert out[2]['unit_price']=='0.00'
    assert post(client,[row(NOTES='Изменено в источнике')])[0]['status']=='error'
    assert client.get(f'/api/records/{id}/copies').json()['items'][0]['note']=='Старый фонд'

def test_missing_catalog_and_auth_and_required_columns(client):
    assert post(client,[row()])[0]['status']=='error'
    assert client.post('/api/import/marcsql-copies',json={'source':'test','rows':[row()]},headers={'X-Admin-Key':'bad'}).status_code==401
    broken=row();del broken['STATE']
    assert post(client,[broken])[0]['status']=='error'
    assert post(client,[row(T090e='')])[0]['status']=='error'

def test_reimport_does_not_overwrite_local_edits(client):
    id=setup(client);out=post(client,[row()])[0]
    c=client.get(f'/api/records/{id}/copies').json()['items'][0]
    p={k:c[k] for k in ['version','inventory_number','barcode','sigla','checked_on','note']};p['sigla']='аб1'
    assert client.put('/api/copies/'+str(c['id']),json=p).status_code==200
    assert post(client,[row()])[0]['status']=='unchanged'
    assert client.get(f'/api/records/{id}/copies').json()['items'][0]['sigla']=='аб1'

def test_local_reset_clears_archive_and_stock_preserves_configuration(client):
    id=setup(client);post(client,[row()]);types=client.get('/api/types').json()
    g=app.dependency_overrides[db]();s=next(g)
    try:
        counts=clear(s);s.commit()
        assert counts['copies']==1 and counts['marcsql_sources']==1
    finally:g.close()
    assert client.get('/api/types').json()==types
    assert client.get('/api/records').json()==[]
    # The old source identity can be imported again after the explicit full reset.
    r=client.post('/api/import/marcsql',json={'source':'test','doc_id':3,'type_id':types[0]['id'],'rectype':'a','biblevel':'m','item':ITEM,'preview':False})
    assert r.json()['status']=='imported'
    assert post(client,[row()])[0]['status']=='created'
