from io import BytesIO
from copy import deepcopy
from datetime import date
from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import select, update
from test_catalog import client, field
from app.main import app, db
from app.db import Copy, Record, DocumentType, KsuEntry, Acquisition, AcquisitionLine, User
from test_security import add, login


def definition(**changes):
    return {'source':'copies','layout':'titles','columns':[{'key':k} for k in ['inventory','title','price','quantity','amount','unpriced']],**changes}


def preview(c,d,**kw):
    r=c.post('/api/reports/preview',json={'definition':d,**kw});assert r.status_code==200,r.text;return r.json()


def seed():
    gen=app.dependency_overrides[db]();s=next(gen)
    try:
        t=DocumentType(name='Книга',config=[]);s.add(t);s.flush()
        a=Record(type_id=t.id,marc={'fields':[field('245','a','=TEST(1)'),field('041','a','kaz'),field('041','a','kaz'),field('952','j','Финансы'),field('952','j','Туризм'),field('260','c','2024')]},search_text='',primary_specialty='Финансы')
        b=Record(type_id=t.id,marc={'fields':[field('245','a','Книга без экземпляров')]},search_text='');s.add_all([a,b]);s.flush()
        e=KsuEntry(year=2025,number=5,registered_on=date(2026,11,5),request_key=str(uuid4()),payload_hash='h',source='',invoice='',note='',snapshot={});s.add(e);s.flush()
        for n,price,status,currency in [(1,'10.25','active','KZT'),(2,'20','active','KZT'),(3,None,'active','KZT'),(4,'0','active','KZT'),(5,'5','withdrawn','KZT'),(6,'90','cancelled','KZT')]:
            s.add(Copy(record_id=a.id,ksu_entry_id=e.id,request_key=str(uuid4()),payload_hash='h',inventory_number=f'000{n}',barcode=f'code{n}',unit_price=Decimal(price) if price is not None else None,currency=currency,status=status,source='Источник 100%',sigla='АБ1' if n==1 else 'АБ2',received_on=date(2025,2,1)))
        s.commit();return a.id,b.id,e.id
    finally: gen.close()


def test_counts_missing_prices_and_multiple_specialties(client):
    seed();r=preview(client,definition())
    assert r['total']==1
    assert r['totals']=={'titles':1,'quantity':4,'unpriced':1,'amounts':{'KZT':'30.25'}}
    assert r['rows'][0]['amount']=='30.25' and r['rows'][0]['quantity']==4
    assert 'без цены' in r['rows'][0]['price'] and '0001' in r['rows'][0]['inventory']
    d=definition(layout='summary',group_by='primary_specialty',sort='primary_specialty',columns=[{'key':k} for k in ['primary_specialty','titles','quantity','amount']])
    r=preview(client,d);assert len(r['rows'])==1 and r['rows'][0]['primary_specialty']=='Финансы' and r['rows'][0]['quantity']==4
    d['filters']=[{'key':'specialties','operator':'equals','value':'Туризм'}];assert preview(client,d)['totals']['quantity']==4


def test_stock_receipts_and_catalog_semantics(client):
    seed()
    assert preview(client,definition(source='catalog'))['totals']['titles']==2
    assert preview(client,definition(source='receipts'))['totals']['quantity']==5
    d=definition(source='receipts',filters=[{'key':'ksu_year','operator':'equals','value':'2025'},{'key':'ksu_date','operator':'between','value':'2026-11-01','end':'2026-11-30'}])
    assert preview(client,d)['totals']['amounts']=={'KZT':'35.25'}
    d['filters'][1]['key']='received_on';assert preview(client,d)['total']==0
    d=definition(source='catalog',filters=[{'key':'price','operator':'empty'}]);r=preview(client,d)
    assert r['totals']=={'titles':1,'quantity':1,'unpriced':1,'amounts':{}}
    assert r['rows'][0]['amount'] is None


def test_same_copy_filters_unicode_and_literal_search(client):
    seed()
    d=definition(filters=[{'key':'sigla','operator':'equals','value':'аб1'},{'key':'price','operator':'gte','value':'15'}])
    assert preview(client,d)['total']==0
    d['filters']=[{'key':'source','value':'100%','operator':'contains'}];assert preview(client,d)['totals']['quantity']==4
    d['filters']=[{'key':'marc:952$j','value':'туризм','operator':'equals'}];assert preview(client,d)['totals']['quantity']==4
    d['filters']=[{'key':'price','operator':'equals','value':'0'}];assert preview(client,d)['totals']['amounts']=={'KZT':'0.00'}


def test_line_price_and_cancelled_receipts(client):
    a,_,_=seed();gen=app.dependency_overrides[db]();s=next(gen)
    try:
        receipt=Acquisition(request_key=str(uuid4()),payload_hash='h',invoice='',source='',received_on=date(2025,1,1));s.add(receipt);s.flush()
        line=AcquisitionLine(acquisition_id=receipt.id,record_id=a,title_snapshot='Тест',quantity=1,unit_price=Decimal('7.25'),currency='USD',sigla='АБ3',note='');s.add(line);s.flush()
        s.add(Copy(line_id=line.id,inventory_number='007',barcode='007',unit_price=Decimal('999'),currency='KZT',sigla='АБ3'));s.commit()
        r=preview(client,definition());assert r['totals']['amounts']=={'KZT':'30.25','USD':'7.25'}
        assert 'USD' in r['rows'][0]['amount'] and 'USD' in r['rows'][0]['price']
        receipt.status='cancelled';s.commit();assert preview(client,definition())['totals']['quantity']==4
    finally:gen.close()


def test_export_all_pages_numeric_cells_leading_zeros_and_formula_safety(client):
    seed();d=definition(layout='copies',sort='inventory',columns=[{'key':'inventory','label':'=danger()'},{'key':'title'},{'key':'price'},{'key':'amount'}])
    r=preview(client,d,page_size=1,page=2);assert len(r['rows'])==1 and r['total']==4 and r['totals']['quantity']==4
    x=client.post('/api/reports/export',json=d);assert x.status_code==200,x.text
    book=load_workbook(BytesIO(x.content));ws=book.active
    assert ws.max_row==5 and ws['A1'].data_type=='s' and ws['A1'].value=='=danger()'
    assert ws['A2'].value=='0001' and ws['A2'].data_type=='s'
    assert ws['B2'].value=='=TEST(1)' and ws['B2'].data_type=='s'
    assert ws['C2'].value==10.25 and ws['C2'].data_type=='n'
    assert ws['C4'].value is None and ws['C5'].value==0
    assert ws.freeze_panes=='B2' and 'Параметры и итоги' in book.sheetnames


def test_permissions_templates_ownership_version_and_csrf(client,monkeypatch):
    seed();add(client,username='viewer');add(client,username='other');add(client,username='blocked',permissions=['visits.view'])
    gen=app.dependency_overrides[db]();session=next(gen)
    session.execute(update(User).where(User.username=='blocked').values(permissions=['visits.view']));session.commit();gen.close()
    from app import security
    def forbidden_lock(session,name):
        assert name!='circulation-stock-gate', 'Reports must not lock circulation'
    monkeypatch.setattr(security,'lock',forbidden_lock)
    with TestClient(app) as c:
        login(c,'viewer')
        assert all(f['scope']!='ksu' for f in c.get('/api/reports/fields').json()['fields'])
        assert preview(c,definition())['total']==1
        assert c.post('/api/reports/preview',json={'definition':definition(source='receipts')}).status_code==403
        assert c.post('/api/reports/export',json=definition(columns=[{'key':'ksu'}])).status_code==403
        body={'name':'Мой отчёт','definition':definition()};r=c.post('/api/reports/templates',json=body);assert r.status_code==201,r.text;t=r.json()
        body['version']=t['version'];assert c.put(f"/api/reports/templates/{t['id']}",json=body).status_code==200
        assert c.put(f"/api/reports/templates/{t['id']}",json=body).status_code==409
        assert c.post('/api/reports/preview',json={'definition':definition()},headers={'X-CSRF-Token':''}).status_code==403
        login(c,'other');assert c.get('/api/reports/templates').json()==[]
        body['version']=2;assert c.put(f"/api/reports/templates/{t['id']}",json=body).status_code==409
        assert c.delete(f"/api/reports/templates/{t['id']}?version=2").status_code==409
        login(c,'blocked');assert c.get('/api/reports/fields').status_code==403
        login(c,'viewer');assert c.delete(f"/api/reports/templates/{t['id']}?version=2").status_code==204


def test_invalid_definitions_and_empty_results(client):
    for change in [dict(columns=[{'key':'title'},{'key':'title'}]),dict(columns=[{'key':'secret'}]),dict(filters=[{'key':'amount','operator':'equals','value':'10'}]),dict(filters=[{'key':'price','operator':'between','value':'20','end':'10'}]),dict(filters=[{'key':'price','operator':'equals','value':'NaN'}]),dict(layout='summary')]:
        r=client.post('/api/reports/preview',json={'definition':definition(**change)});assert r.status_code==422,r.text
    assert preview(client,definition())['totals']=={'titles':0,'quantity':0,'unpriced':0,'amounts':{}}


def test_limits_fail_explicitly_and_private_results(client,monkeypatch):
    seed()
    from app import reports
    r=client.post('/api/reports/preview',json={'definition':definition()})
    assert r.headers['cache-control']=='private, no-store'
    monkeypatch.setattr(reports,'MAX_COPIES',2)
    r=client.post('/api/reports/preview',json={'definition':definition()})
    assert r.status_code==422 and 'лимит' in r.json()['detail']
