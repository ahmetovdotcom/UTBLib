from datetime import datetime, timedelta, timezone, date
from uuid import uuid4
import io
import pytest
from openpyxl import load_workbook
from sqlalchemy import select
from test_catalog import client, make_type, payload, field
from test_security import add as add_user, login
from app.main import app, db
from app.db import User, Record, DocumentType, Copy, Acquisition, AcquisitionLine
from app.reader_models import Reader, Branch
from app.reader_core import TZ
from app.circulation_models import Loan, LoanEvent

PATH = '/api/statistics/circulation'
PERIOD = {'date_from': '2026-10-01', 'date_to': '2026-10-06'}

def stamp(value):
    return datetime.fromisoformat(value).replace(tzinfo=TZ).astimezone(timezone.utc)

@pytest.fixture
def data(client):
    gen = app.dependency_overrides[db](); s = next(gen)
    try:
        actor = s.scalar(select(User.id))
        t = DocumentType(name='Книга', config=[]); s.add(t); s.flush()
        records = []
        for title, more in [
            ('Одинаковое название', [('952','a','КУК'),('952','c','Учебник'),('041','a','kazrus'),
              ('952','j','Экономика'),('952','j','Экономика'),('952','j','Финансы'),
              ('952','i','Математика'),('952','i','Финансы')]),
            ('Одинаковое название', [('952','a','КНР'),('041','a','rus'),('952','j','Экономика')]),
            ('=HYPERLINK("https://example.invalid")', []),
        ]:
            r = Record(type_id=t.id, marc={'leader':'00000nam a2200000   4500','fields':
                [field('245','a',title),field('100','a','Тестовый автор')]+[field(*v) for v in more]}, search_text=title)
            s.add(r); records.append(r)
        readers = [Reader(full_name='Тест '+str(i),ticket_number='T'+str(i),barcode='R'+str(i),category=c)
                   for i,c in enumerate(['bachelor','teacher'])];s.add_all(readers)
        branch = Branch(code='OLD',name='Закрытый зал',active=False);s.add(branch);s.flush()
        acquisition=Acquisition(request_key=str(uuid4()),payload_hash='test',invoice='Тест',received_on=date(2026,1,1),source='Тест')
        s.add(acquisition);s.flush()
        line=AcquisitionLine(acquisition_id=acquisition.id,record_id=records[0].id,title_snapshot='Тест',quantity=1,unit_price=10,currency='KZT',sigla='',note='')
        s.add(line);s.flush()
        copies=[]
        for i,idx in enumerate([0,0,0,1,2]):
            origin={'line_id':line.id} if i==2 else {'record_id':records[idx].id,'request_key':str(uuid4()),'payload_hash':'test'}
            c=Copy(**origin,inventory_number='INV'+str(i),barcode='BC'+str(i),sigla='',status='withdrawn' if i==1 else 'active')
            s.add(c);copies.append(c)
        s.flush()
        schedule=[(0,0,'2026-09-30T23:59','returned'),(0,0,'2026-10-01T00:00','returned'),
                  (0,0,'2026-10-02T10:00','returned'),(1,1,'2026-10-03T11:00','lost'),
                  (2,1,'2026-10-04T12:00','active'),(3,0,'2026-10-05T12:00','returned'),
                  (4,1,'2026-10-06T23:59','returned'),(0,0,'2026-10-07T00:00','active')]
        loans=[]
        for ci,ri,day,status in schedule:
            at=stamp(day);end=at+timedelta(hours=1)
            l=Loan(copy_id=copies[ci].id,reader_id=readers[ri].id,branch_id=branch.id if ri==0 else None,
                issued_by=actor,issued_at=at,due_at=at+timedelta(days=30),calculated_due_at=at+timedelta(days=30),status=status,
                closed_at=end if status!='active' else None,returned_at=end if status=='returned' else None,lost_at=end if status=='lost' else None)
            s.add(l);loans.append(l)
        s.flush()
        for _ in range(2):s.add(LoanEvent(loan_id=loans[1].id,kind='renew',actor_id=actor))
        s.commit();ids={'records':[r.id for r in records],'branch':str(branch.id),'type':str(t.id)}
    finally:gen.close()
    return client,ids

def get(c,**kw):
    response=c.get(PATH,params={**PERIOD,**kw});assert response.status_code==200,response.text
    return response.json()

def test_distinct_readers_copies_records_renewals_and_local_period(data):
    c,ids=data;r=get(c)
    assert r['totals']=={'loans':6,'readers':2,'copies':5,'records':3}
    a=next(row for row in r['rows'] if row['record_id']==ids['records'][0])
    assert {k:a[k] for k in ['loans','readers','copies','records']}=={'loans':4,'readers':2,'copies':3,'records':1}
    assert len([v for v in r['rows'] if v['label']=='Одинаковое название'])==2
    assert [r['loans'] for r in r['trend']]==[1,1,1,1,1,1]
    assert get(c,date_from='2026-09-29')['trend'][0]['loans']==0
    assert get(c,date_from='2026-10-01',date_to='2026-10-01')['totals']['loans']==1
    assert get(c,date_from='2026-01-01')['trend_unit']=='month'
    assert get(c,record_id=ids['records'][0])['totals']['loans']==4

def test_multivalue_grouping_missing_values_and_compound_filters(data):
    c,ids=data;r=get(c,group_by='specialty')
    counts={v['key']:v['loans'] for v in r['rows']}
    assert counts=={'Экономика':5,'Финансы':4,'':1}
    assert r['totals']['loans']==6  # Sum of multi-valued groups is intentionally 10.
    assert get(c,group_by='language')['totals']['readers']==2
    languages={v['key']:v['loans'] for v in get(c,group_by='language')['rows']}
    assert languages=={'kaz':4,'rus':5,'':1}
    assert get(c,specialty=['Экономика','Финансы'],discipline=['Математика'],language=['rus'],document_type=[ids['type']])['totals']['loans']==4
    assert get(c,discipline=[''])['totals']['loans']==2
    assert get(c,branch_id=[ids['branch']])['totals']['loans']==3
    assert get(c,branch_id=[''],category=['teacher'])['totals']['loans']==3
    assert get(c,kind=['science'])['totals']['loans']==1
    assert get(c,literature_type=['Учебник'])['totals']['loans']==4
    assert get(c,q='%',specialty=['Экономика'])['totals']['loans']==0
    assert get(c,q='ОДИНАКОВОЕ')['totals']['loans']==5
    assert get(c,q='Тестовый автор')['totals']['loans']==6
    assert get(c,specialty=['Несуществующая'])['rows']==[]

@pytest.mark.parametrize('group', ['kind','literature_type','specialty','discipline','language','document_type','branch_id','category'])
def test_all_groupings(data,group):
    c,_=data;r=get(c,group_by=group)
    assert r['rows'] and all(v['readers']<=2 for v in r['rows'])
    assert r['totals']=={'loans':6,'readers':2,'copies':5,'records':3}

def test_options_and_exports(data):
    c,ids=data;options=c.get(PATH+'/options').json()['filters']
    assert {'value':ids['branch'],'label':'Закрытый зал'} in options['branch_id']
    assert {'value':'','label':'Не указано'} in options['discipline']
    assert len([v for v in options['specialty'] if v['value']=='Экономика'])==1
    r=c.get(PATH+'/export',params={**PERIOD,'format':'xlsx','specialty':'Экономика'})
    assert r.status_code==200,r.text
    rows=list(load_workbook(io.BytesIO(r.content)).active.values)
    assert next(v for v in rows if v[0]=='Итого без повторов')[3:7]==(5,2,4,2)
    assert any(v[0]=='Специальность' and v[1]=='Экономика' for v in rows)
    r=c.get(PATH+'/export',params={**PERIOD,'format':'csv'});assert r.status_code==200
    assert "'=HYPERLINK" in r.text
    wb=load_workbook(io.BytesIO(c.get(PATH+'/export',params={**PERIOD,'format':'xlsx'}).content))
    assert all(cell.data_type!='f' for row in wb.active for cell in row)

@pytest.mark.parametrize('params',[
    {'date_from':'2026-11-01','date_to':'2026-01-01'},{'date_from':'1900-01-01','date_to':'2026-01-01'},
    {'group_by':'bad'},{'branch_id':'-1'},{'record_id':'0'},{'unknown':'x'},{'kind':'bad'},{'language':'x'*1001},
])
def test_validation(client,params):
    assert client.get(PATH,params=params).status_code==422

def test_permissions_and_no_personal_data(client):
    add_user(client,username='stats',permissions=['statistics.view']);login(client,'stats')
    assert client.get(PATH,params=PERIOD).status_code==200
    assert client.get(PATH+'/options').status_code==200
    assert client.get(PATH+'/export',params=PERIOD).status_code==200
    login(client,'admin','test-secret');add_user(client,username='catalog',permissions=['catalog.view']);login(client,'catalog')
    for suffix in ['', '/options','/export']:assert client.get(PATH+suffix,params=PERIOD).status_code==403
    client.post('/api/auth/logout')
    assert client.get(PATH).status_code==401


def test_saved_description_single_component_and_permissions(client):
    t=make_type(client);p=payload(t)
    p['marc']['fields'][0]['subfields'].append({'code':'c','value':'Тестовый автор'})
    p['marc']['fields'] += [field('260','a','Алматы'),field('300','a','120 с.')]
    created=client.post('/api/records',json=p);assert created.status_code==201,created.text
    id=created.json()['id'];url=f'/api/records/{id}/description'
    r=client.get(url);assert r.status_code==200
    assert 'Алматы' in r.json()['text'] and '120 с.' in r.json()['text'] and 'Тестовый автор' in r.json()['text']
    assert r.json()['text']==client.post('/api/gost/preview',json={'marc':created.json()['marc'],'kind':'single'}).json()['text']
    gen=app.dependency_overrides[db]();s=next(gen)
    try:
        record=s.get(Record,id);marc=dict(record.marc);marc['leader']='00000naa a2200000   4500';marc['fields']=[*marc['fields'],field('773','t','Тестовый журнал')];record.marc=marc;s.commit()
    finally:gen.close()
    assert '// Тестовый журнал' in client.get(url).json()['text']
    assert client.get('/api/records/999999/description').status_code==404
    add_user(client,username='view',permissions=['catalog.view']);login(client,'view')
    assert client.get(url).status_code==200
    login(client,'admin','test-secret');add_user(client,username='none',role='reader',permissions=['loans.view_own']);login(client,'none')
    assert client.get(url).status_code==403
