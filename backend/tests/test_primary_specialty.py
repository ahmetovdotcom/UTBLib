from uuid import uuid4
from fastapi.testclient import TestClient
from test_catalog import client,make_type,payload,field
from test_acquisitions import save,add_body
from test_copy_ksu import ksu,copy,edit
from test_stock_operations import correction

REPORT='/api/ksu/specialties/report?date_from=2026-01-01&date_to=2026-12-31'


def book(c,values=('Туризм','Финансы'),selected=None):
    p=payload(make_type(c));p['marc']['fields'] += [field('952','j',v) for v in values]
    if selected is not None:p['primary_specialty']=selected
    return save(c,p)


def update(c,r,**changes):
    b={k:r[k] for k in ('type_id','version','marc')};b.update(changes)
    return c.put(f"/api/records/{r['id']}",json=b)


def allocations(c,e):
    response=c.get(f"/api/ksu/entries/{e['id']}/specialties")
    assert response.status_code==200,response.text
    return response.json()['items']


def test_catalog_choice_validation_singleton_duplicates_and_legacy_clients(client):
    r=book(client,(' Туризм ','Туризм'))
    assert r['primary_specialty']=='Туризм'
    r['marc']['fields'].append(field('952','j','Финансы'))
    r=update(client,r).json() # Older clients keep the chosen primary.
    assert r['primary_specialty']=='Туризм'
    bad=update(client,r,primary_specialty='Право');assert bad.status_code==422
    changed=update(client,r,primary_specialty=' Финансы ')
    assert changed.status_code==200,changed.text
    new=changed.json();assert new['primary_specialty']=='Финансы' and new['version']==r['version']+1
    assert update(client,r,primary_specialty='Туризм').status_code==409
    assert update(client,new,primary_specialty=None).json()['primary_specialty'] is None


def test_multiple_without_choice_does_not_guess(client):
    r=book(client);assert r['primary_specialty'] is None
    e=ksu(client);copy(client,r,e)
    report=client.get(REPORT).json()
    assert report['totals']['missing']['copies']==1
    assert report['total']['amount']=='250.50'


def test_catalog_changes_recalculate_every_ksu_without_duplicate_counts(client):
    from io import BytesIO
    from openpyxl import load_workbook
    r=book(client,selected='Туризм');e=ksu(client);other=ksu(client,18)
    first=copy(client,r,e);copy(client,r,e,unit_price='100');copy(client,r,other,unit_price='50')
    before=client.get(REPORT).json()
    r=update(client,r,primary_specialty='Финансы').json()
    after=client.get(REPORT).json()
    assert after['total']==before['total']=={'titles':2,'copies':3,'amount':'400.50','unpriced_count':0}
    assert list(after['totals'])==['specialty:Финансы']
    assert after['totals']['specialty:Финансы']==after['total']
    assert allocations(client,e)[0]['primary_specialty']=='Финансы'
    assert allocations(client,other)[0]['primary_specialty']=='Финансы'
    assert allocations(client,e)[0]['additional_specialties']==['Туризм']
    export=client.get(REPORT.replace('/report?','/export?'));assert export.status_code==200
    ws=load_workbook(BytesIO(export.content)).worksheets[0]
    assert ws['E2'].value=='Финансы'
    assert ws['E6'].value==2 and ws['F6'].value==3 and ws['G6'].value==400.5
    # Clearing the choice redistributes to one unassigned column, without losing amounts.
    r=update(client,r,primary_specialty=None).json()
    missing=client.get(REPORT).json()
    assert missing['total']==before['total'] and missing['totals']['missing']==missing['total']
    # The old and new copies follow the same catalogue source after moving between KSUs.
    r=update(client,r,primary_specialty='Туризм').json()
    edit(client,first,ksu_entry_id=other['id'])
    assert allocations(client,other)[0]['primary_specialty']=='Туризм'
    assert allocations(client,other)[0]['copies']==2


def test_existing_unassigned_copies_and_acquisitions_follow_catalog(client):
    r=book(client)
    a=client.post('/api/acquisitions',json=add_body(r['id'],2,'10')).json()
    e={'id':client.get(REPORT).json()['rows'][0]['id']}
    assert allocations(client,e)[0]['primary_specialty'] is None
    r=update(client,r,primary_specialty='Финансы').json()
    assert client.get(REPORT).json()['totals']['specialty:Финансы']['copies']==2
    b=correction(client,a);b['lines'][0]['quantity']=3
    response=client.put(f"/api/acquisitions/{a['id']}",json=b)
    assert response.status_code==200,response.text
    assert allocations(client,e)[0]['copies']==3 and allocations(client,e)[0]['primary_specialty']=='Финансы'
    detached=copy(client,r,None);fresh=ksu(client,99);edit(client,detached,ksu_entry_id=fresh['id'])
    r=update(client,r,primary_specialty='Туризм').json()
    assert allocations(client,fresh)[0]['primary_specialty']=='Туризм'
    assert allocations(client,e)[0]['primary_specialty']=='Туризм'


def test_ksu_distribution_is_read_only_even_for_admin_and_ksu_editor(client):
    from app.main import app
    from test_security import add as user,login
    r=book(client,selected='Туризм');e=ksu(client);copy(client,r,e)
    url=f"/api/ksu/entries/{e['id']}/specialties/{r['id']}"
    for method in ('PUT','POST','PATCH','DELETE'):
        assert client.request(method,url,json={'primary_specialty':'Финансы'}).status_code in (404,405)
    assert allocations(client,e)[0]['primary_specialty']=='Туризм'
    user(client,username='ksueditor',permissions=['ksu.edit'],role='viewer')
    with TestClient(app) as viewer:
        login(viewer,'ksueditor')
        assert viewer.get(f"/api/ksu/entries/{e['id']}/specialties").status_code==200
        assert update(viewer,r,primary_specialty='Финансы').status_code==403
        assert viewer.put(url,json={'primary_specialty':'Финансы'}).status_code in (404,405)
    assert client.get(f"/api/records/{r['id']}").json()['primary_specialty']=='Туризм'


def test_legacy_snapshot_does_not_override_catalog_or_change_on_read(client):
    from app.main import app,db
    from app.db import KsuSpecialtyAllocation
    r=book(client,selected='Туризм');e=ksu(client);copy(client,r,e)
    session=app.dependency_overrides[db]();s=next(session)
    s.add(KsuSpecialtyAllocation(entry_id=e['id'],record_id=r['id'],primary_specialty='Финансы',specialties=['Финансы'],version=4));s.commit();session.close()
    assert client.get(REPORT).json()['totals']['specialty:Туризм']['copies']==1
    assert allocations(client,e)[0]['primary_specialty']=='Туризм'
    r=update(client,r,primary_specialty='Финансы').json()
    assert allocations(client,e)[0]['primary_specialty']=='Финансы'
    session=app.dependency_overrides[db]();s=next(session)
    assert s.get(KsuSpecialtyAllocation,(e['id'],r['id'])).version==4
    session.close()


def test_initial_receipt_captures_primary_and_creation_retry(client):
    from test_acquisitions import new_body
    p=new_body(client,quantity='2',price='10');p['marc']['fields'] += [field('952','j','Туризм'),field('952','j','Финансы')]
    p.update(primary_specialty='Финансы',request_key=str(uuid4()),initial_acquisition={
        'received_on':'2026-11-10','currency':'KZT','note':''})
    response=client.post('/api/records',json=p)
    assert response.status_code==201,response.text
    assert client.post('/api/records',json=p).json()['id']==response.json()['id']
    report=client.get(REPORT).json()
    assert report['total']['copies']==2 and report['totals']['specialty:Финансы']['amount']=='20.00'
