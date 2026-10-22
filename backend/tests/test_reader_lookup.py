import os
os.environ.setdefault('DATABASE_URL','sqlite://')
from datetime import datetime,timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo
from sqlalchemy import create_engine,select,func
from sqlalchemy.orm import sessionmaker
from app.db import Base
from app.reader_models import Reader
from app.reader_scheduler import due
from app import reader_lookup
from test_catalog import client


def test_schedule_restart_retry_and_timezone():
    now=datetime(2026,10,22,3,20,tzinfo=ZoneInfo('Asia/Almaty'))
    assert due(now,[])
    assert not due(now-timedelta(minutes=1),[])
    run=SimpleNamespace(parameters={'day':'2026-10-22'},complete=False,started_at=now)
    assert not due(now+timedelta(minutes=59),[run])
    assert due(now+timedelta(hours=1),[run])
    assert not due(now+timedelta(hours=3),[run,run,run])
    run.complete=True
    assert not due(now+timedelta(hours=5),[run])
    assert due(now+timedelta(days=1),[run])


def test_single_import_idempotent_and_typed(monkeypatch):
    e=create_engine('sqlite://');Base.metadata.create_all(e);factory=sessionmaker(e)
    calls=[]
    def lookup(source,search=None,identity=None):
        calls.append(identity)
        return [{'entity_type':identity[0],'external_id':identity[1],'fields':{'full_name':'Тестовый Читатель','category':'teacher'}}]
    monkeypatch.setattr(reader_lookup,'lookup',lookup)
    first=reader_lookup.import_one(factory,'platonus','tutor','42')
    with factory() as s: barcode=s.get(Reader,first['id']).barcode
    second=reader_lookup.import_one(factory,'platonus','tutor','42')
    assert first['id']==second['id'] and calls==[('tutor','42'),('tutor','42')]
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(Reader))==1
        assert s.get(Reader,first['id']).barcode==barcode


def test_lookup_api_ignores_client_profile(client,monkeypatch):
    row={'entity_type':'tutor','external_id':'42','fields':{'full_name':'Тестовый Читатель','iin':'do-not-expose'}}
    monkeypatch.setattr(reader_lookup,'lookup',lambda *a,**kw:[row])
    response=client.get('/api/readers/source-search',params={'source':'platonus','q':'Тест'})
    assert response.status_code==200,response.text
    assert 'iin' not in response.text
    assert client.post('/api/readers/source-import',json={'source':'platonus','entity_type':'tutor','external_id':'42','full_name':'Forged'}).status_code==422
    assert client.post('/api/readers/source-import',json={'source':'platonus','entity_type':'ad_user','external_id':'42'}).status_code==422


def test_nightly_partial_rows_continue_but_interrupted_source_stops(monkeypatch):
    from app import reader_scheduler as scheduler
    from app.reader_models import ReaderSyncRun
    e=create_engine('sqlite://');Base.metadata.create_all(e);factory=sessionmaker(e)
    class Lock:
        def connect(self):return self
        def execution_options(self,**kw):return self
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def scalar(self,*args):return True
        def execute(self,*args):pass
    monkeypatch.setattr(scheduler,'engine',Lock());monkeypatch.setattr(scheduler,'Session',factory)
    monkeypatch.setenv('READERS_NIGHTLY_ENABLED','true');monkeypatch.setenv('READERS_NIGHTLY_TIME','00:00')
    monkeypatch.setenv('AD_ENABLED','true');monkeypatch.setenv('PLATONUS_ENABLED','true')
    calls=[]
    monkeypatch.setattr(scheduler,'source_rows',lambda source:[])
    def sync(factory,source,rows,**kw):
        calls.append(source)
        return {'counts':{'read':10,'errors':1},'complete':False,'processed':True}
    monkeypatch.setattr(scheduler,'synchronize',sync)
    monkeypatch.setattr(scheduler,'logged_personal',lambda *a,**kw:{'counts':{'errors':2},'message':''})
    scheduler.tick();scheduler.tick()
    assert calls==['active_directory','platonus']
    with factory() as s:
        run=s.scalar(select(ReaderSyncRun));assert run.complete and run.message
        s.delete(run);s.commit()
    calls.clear()
    def failed(*a,**kw):
        calls.append(a[1]);return {'counts':{'read':0,'errors':1},'processed':False}
    monkeypatch.setattr(scheduler,'synchronize',failed)
    scheduler.tick();scheduler.tick()
    assert calls==['active_directory']
    with factory() as s: assert not s.scalar(select(ReaderSyncRun)).complete
