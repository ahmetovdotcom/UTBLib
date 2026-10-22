import os
os.environ.setdefault('DATABASE_URL','sqlite://')
from test_catalog import client
from sqlalchemy import select,func
from app.db import Base,Session
from app.reader_models import Reader,ReaderIdentity,LibraryVisit,ReaderCounter,ReaderPhoto
from app.reader_core import local_bounds,iin_data
from app.reader_sync import synchronize
from datetime import date

def create(c,**kw):
    r=c.post('/api/readers',json={'full_name':'Тестовый читатель','category':'student',**kw}); assert r.status_code==200,r.text; return r.json()
def branch(c):
    r=c.post('/api/reader-branches',json={'code':'MAIN','name':'Читальный зал'}); assert r.status_code==200,r.text;return r.json()['id']
def test_registry_visits_ticket(client):
    c=client;r=create(c,status='blocked',block_reason='Ручная блокировка',department='Туризм и сервис');b=branch(c)
    assert c.get('/api/visits/lookup',params={'code':' '+r['barcode'].lower()+' '}).json()['id']==r['id']
    first=c.post('/api/visits',json={'code':r['barcode'],'branch_id':b});assert first.status_code==200,first.text
    b2=c.post('/api/reader-branches',json={'code':'SECOND','name':'Абонемент'}).json()['id']
    second=c.post('/api/visits',json={'code':r['ticket_number'],'branch_id':b2}).json();assert second['duplicate'] and second['id']==first.json()['id']
    card=c.get('/api/readers/'+str(r['id'])).json();assert card['status']=='blocked' and card['visits_count']==1
    ticket=c.get(f"/api/readers/{r['id']}/ticket");assert ticket.status_code==200 and '<svg' in ticket.json()['svg'];assert ticket.json()['barcode']==r['barcode']
    assert '<svg' in ticket.json()['qr_svg'] and ticket.json()['department']=='Туризм и сервис'
    assert 'viewBox=' in ticket.json()['svg']
    assert 'iin' not in ticket.json() and 'birth_date' not in ticket.json()
    assert c.get('/api/visits/analytics').json()['today']['visits']==1
    assert c.post('/api/visits',json={'code':'unknown','branch_id':b}).status_code==404
    assert c.post('/api/visits',json={'code':r['barcode'],'branch_id':b,'scanned_by':999}).status_code==422

def test_filters_exports_and_version(client):
    c=client;r=create(c,faculty='Технологический',full_name='=Формула');create(c,faculty='Экономический')
    q={'faculty':'Технологический'}
    assert c.get('/api/readers',params=q).json()['total']==1
    assert c.get('/api/readers/analytics',params=q).json()['total']==1
    export=c.get('/api/readers/export',params=q);assert export.status_code==200 and "'=Формула" in export.text and 'Экономический' not in export.text
    assert c.get('/api/readers/export',params={**q,'format':'xlsx'}).content[:2]==b'PK'
    assert c.put('/api/readers/'+str(r['id']),json={'full_name':'Новое имя','version':0}).status_code==409

def test_iin_and_time():
    start,end=local_bounds(date(2026,10,22));assert start.hour==19 and start.day==21 and (end-start).total_seconds()==86400
    import pytest
    with pytest.raises(ValueError): iin_data('000000000000')
    # Generate a valid synthetic IIN with a leading zero, using the documented check weights.
    prefix='01010150000'; digits=list(map(int,prefix)); check=sum(a*b for a,b in zip(digits,range(1,12)))%11
    if check==10: check=sum(a*b for a,b in zip(digits,[3,4,5,6,7,8,9,10,11,1,2]))%11
    assert check<10
    assert iin_data(prefix+str(check))[0]==date(2001,1,1)

def test_sync_idempotent_typed_dry_run():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    engine=create_engine('sqlite://',poolclass=StaticPool);Base.metadata.create_all(engine);factory=sessionmaker(engine)
    rows=[{'entity_type':'student','external_id':'123','fields':{'full_name':'Студент'}},{'entity_type':'tutor','external_id':'123','fields':{'full_name':'Преподаватель','category':'teacher'}}]
    result=synchronize(factory,'platonus',rows,dry_run=True,complete=True);assert result['counts']['errors']==0,result
    with factory() as s: assert s.scalar(select(func.count()).select_from(Reader))==0 and s.scalar(select(func.count()).select_from(ReaderCounter))==0
    result=synchronize(factory,'platonus',rows,complete=True);assert result['counts']['created']==2,result
    with factory() as s: original=[(r.id,r.ticket_number,r.barcode) for r in s.scalars(select(Reader))];r=s.get(Reader,1);r.status='blocked';r.manual_overrides=['phone'];r.phone='123';s.commit()
    rows[0]['fields']['phone']='456'
    result=synchronize(factory,'platonus',rows,complete=True);assert result['counts']['updated']==2,result
    with factory() as s:
        assert [(r.id,r.ticket_number,r.barcode) for r in s.scalars(select(Reader))]==original
        assert s.get(Reader,1).status=='blocked' and s.get(Reader,1).phone=='123'
    result=synchronize(factory,'platonus',[],complete=True,deactivate_missing=True,status_confirmed=True);assert result['counts']['suspended']==0 and result['message']
    result=synchronize(factory,'platonus',rows[:1],complete=True,limit=1,deactivate_missing=True,status_confirmed=True);assert result['counts']['suspended']==0
    def broken():
        yield rows[0]
        raise RuntimeError('network down')
    result=synchronize(factory,'platonus',broken(),complete=True,deactivate_missing=True,status_confirmed=True);assert result['counts']['errors']==1 and result['counts']['suspended']==0
    engine.dispose()

def test_permissions_direct_routes(client):
    c=client;r=create(c)
    user=c.post('/api/users',json={'username':'readeronly','display_name':'Наблюдатель','password':'strong-password','role':'viewer','permissions':['readers.registry.view']});assert user.status_code==201,user.text
    auth=c.post('/api/auth/login',json={'username':'readeronly','password':'strong-password'}).json();c.headers['X-CSRF-Token']=auth['csrf_token']
    assert c.get('/api/readers').status_code==200
    assert 'iin' not in c.get('/api/readers/'+str(r['id'])).json()
    for path in ['/api/readers/export','/api/readers/analytics','/api/readers/sync-status',f"/api/readers/{r['id']}/ticket",'/api/visits/lookup?code='+r['barcode'],'/api/visits']:
        assert c.get(path).status_code==403,path
    assert c.get('/api/readers?missing=iin').status_code==403
    assert c.post('/api/readers',json={'full_name':'Нет доступа'}).status_code==403

def test_cross_source_link_and_conflict():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    engine=create_engine('sqlite://');Base.metadata.create_all(engine);factory=sessionmaker(engine)
    import io,base64
    from PIL import Image
    out=io.BytesIO();Image.new('RGB',(20,20),'red').save(out,format='PNG')
    photo=base64.b64encode(out.getvalue()).decode()
    row={'photo':photo,'entity_type':'ad_user','external_id':'guid1','fields':{'full_name':'Имя AD'},'platonus_link':{'entity_type':'student','external_id':'1','confirmed':True}}
    result=synchronize(factory,'active_directory',[row],complete=True);assert result['counts']['created']==1,result
    result=synchronize(factory,'platonus',[{'entity_type':'student','external_id':'1','photo':'invalid; must not override AD photo','fields':{'full_name':'Имя Platonus','faculty':'Факультет'}}],complete=True);assert result['counts']['updated']==1,result
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(Reader))==1
        r=s.scalar(select(Reader));assert r.full_name=='Имя AD' and r.faculty=='Факультет'
    bad={**row,'external_id':'guid2','platonus_link':{'entity_type':'student','external_id':'1','confirmed':False}}
    result=synchronize(factory,'active_directory',[bad]);assert result['counts']['errors']==1
    engine.dispose()

def test_disabled_sources():
    from app.reader_sources import source_rows
    import pytest
    with pytest.raises(ValueError): list(source_rows('platonus'))
    with pytest.raises(ValueError): list(source_rows('active_directory'))

def test_iin_persistence_duplicates_and_csv(client):
    c=client;prefix='01010150000';weights=range(1,12);n=sum(int(a)*b for a,b in zip(prefix,weights))%11
    if n==10:n=sum(int(a)*b for a,b in zip(prefix,[3,4,5,6,7,8,9,10,11,1,2]))%11
    iin=prefix+str(n)
    r=create(c,iin=iin,birth_date='2001-01-01');assert r['iin']==iin
    assert c.post('/api/readers',json={'full_name':'Другой','iin':iin}).status_code==422
    assert c.post('/api/readers',json={'full_name':'Другой','iin':iin,'birth_date':'2002-01-01'}).status_code==422
    assert c.get('/api/readers/export').text.count(iin)==1

def test_photo_validation_and_permissions(client):
    import io,base64
    from PIL import Image
    c=client;r=create(c);img=Image.new('RGB',(20,20),'red');out=io.BytesIO();img.save(out,format='PNG')
    path=f"/api/readers/{r['id']}/photo"
    assert c.post(path,json={'content':base64.b64encode(out.getvalue()).decode()}).status_code==200
    assert c.get(path).headers['content-type']=='image/jpeg'
    assert c.get('/api/readers/'+str(r['id'])).json()['field_owners']['photo']=='manual'
    assert c.post(path,json={'content':base64.b64encode(b'<svg>not a photo</svg>').decode()}).status_code==422
    user=c.post('/api/users',json={'username':'scanonly','display_name':'Сканирование','password':'strong-password','role':'viewer','permissions':['visits.record']});assert user.status_code==201
    auth=c.post('/api/auth/login',json={'username':'scanonly','password':'strong-password'}).json();c.headers['X-CSRF-Token']=auth['csrf_token']
    assert c.get(path).status_code==403
    assert c.get('/api/reader-branches').status_code==200
    assert c.get('/api/visits/lookup',params={'code':r['barcode']}).status_code==200

def test_access_log_does_not_expose_search():
    import logging
    from app.readers import ReaderAccessLogFilter
    record=logging.LogRecord('uvicorn.access',20,'',0,'%s %s %s %s %s',('local','GET','/api/readers?q=010101500001','1.1',200),None)
    ReaderAccessLogFilter().filter(record)
    assert '010101500001' not in record.getMessage() and '/api/readers' in record.getMessage()

def test_ad_without_confirmed_category_keeps_detailed_category():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    engine=create_engine('sqlite://');Base.metadata.create_all(engine);factory=sessionmaker(engine)
    synchronize(factory,'platonus',[{'entity_type':'student','external_id':'1','fields':{'full_name':'Студент','category':'bachelor'}}])
    result=synchronize(factory,'active_directory',[{'entity_type':'ad_user','external_id':'guid','fields':{'full_name':'Имя AD'},'platonus_link':{'entity_type':'student','external_id':'1','confirmed':True}}])
    assert result['counts']['updated']==1,result
    with factory() as s: assert s.scalar(select(Reader.category))=='bachelor'
    engine.dispose()

def test_personal_conflict_filter_and_review(client):
    from app.main import app,db
    from app.reader_models import ReaderConflict
    c=client;r=create(c)
    gen=app.dependency_overrides[db]();s=next(gen)
    try:
        conflict=ReaderConflict(reader_id=r['id'],source='platonus',entity_type='student',external_id='test',code='iin_birth_mismatch');s.add(conflict);s.commit();conflict_id=conflict.id
    finally: gen.close()
    assert c.get('/api/readers?iin_mismatch=true').json()['total']==1
    assert c.get('/api/readers/analytics?iin_mismatch=true').json()['total']==1
    assert c.post(f'/api/readers/conflicts/{conflict_id}/resolve').status_code==200
    assert c.get('/api/readers?iin_mismatch=true').json()['total']==0

def test_editor_without_personal_permission_preserves_private_overrides(client):
    from app.main import app,db
    c=client;r=create(c);gen=app.dependency_overrides[db]();s=next(gen)
    try:
        reader=s.get(Reader,r['id']);reader.manual_overrides=['iin','birth_date'];s.commit()
    finally:gen.close()
    c.post('/api/users',json={'username':'profileeditor','display_name':'Редактор','password':'strong-password','role':'viewer','permissions':['readers.registry.view','readers.registry.edit']})
    auth=c.post('/api/auth/login',json={'username':'profileeditor','password':'strong-password'}).json();c.headers['X-CSRF-Token']=auth['csrf_token']
    result=c.put('/api/readers/'+str(r['id']),json={'full_name':'Изменено','version':r['version'],'manual_overrides':[]})
    assert result.status_code==200,result.text
    assert set(result.json()['manual_overrides'])=={'iin','birth_date'} and 'iin' not in result.json()
