"""Run only against an explicitly supplied disposable PostgreSQL database."""
import os
import pytest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from sqlalchemy import create_engine,select,func
from sqlalchemy.orm import sessionmaker
from app.db import Base,User,utcnow
from app.reader_models import Reader,Branch,LibraryVisit
from app.reader_core import allocate_ticket
from app.main import app,db
from fastapi.testclient import TestClient
pytestmark=pytest.mark.skipif(not os.getenv('TEST_READERS_DATABASE_URL'),reason='Disposable PostgreSQL not configured')

def test_concurrent_scans_and_numbering():
    engine=create_engine(os.environ['TEST_READERS_DATABASE_URL']);factory=sessionmaker(engine)
    # Dedicated test schema, never the application database schema.
    schema='reader_test_'+__import__('uuid').uuid4().hex
    with engine.begin() as c:c.exec_driver_sql('CREATE SCHEMA '+schema)
    scoped=engine.execution_options(schema_translate_map={None:schema});Base.metadata.create_all(scoped);factory=sessionmaker(scoped)
    try:
        from app.security import bootstrap
        with factory() as s:
            bootstrap(s,'test-secret');b=Branch(code='MAIN',name='Test');s.add(b);ticket,barcode=allocate_ticket(s,'student',2026,'');r=Reader(full_name='Concurrent',category='student',ticket_number=ticket,barcode=barcode);s.add(r);s.commit();rid=r.id;bid=b.id
        def dependency():
            with factory() as s:yield s
        app.dependency_overrides[db]=dependency
        with TestClient(app) as c:
            auth=c.post('/api/auth/login',json={'username':'admin','password':'test-secret'}).json();headers={'X-CSRF-Token':auth['csrf_token']}
            def scan(_):
                response=c.post('/api/visits',json={'code':barcode,'branch_id':bid},headers=headers);assert response.status_code==200,response.text;return response.json()
            with ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(scan,range(8)))
            assert len({r['id'] for r in results})==1 and sum(not r['duplicate'] for r in results)==1
            with factory() as s:
                visit=s.scalar(select(LibraryVisit));visit.scanned_at=utcnow()-timedelta(minutes=11);s.commit()
            assert scan(0)['duplicate'] is False
        def number(_):
            with factory() as s:
                pair=allocate_ticket(s,'student',2026,'');s.commit();return pair
        with ThreadPoolExecutor(max_workers=8) as pool:pairs=list(pool.map(number,range(30)))
        assert len({p[0] for p in pairs})==30 and len({p[1] for p in pairs})==30
    finally:
        app.dependency_overrides.clear()
        with engine.begin() as c:c.exec_driver_sql('DROP SCHEMA '+schema+' CASCADE')
        engine.dispose()

def test_shared_sync_lock_and_registry_scale():
    from app.reader_sync import sync_lock,synchronize
    engine=create_engine(os.environ['TEST_READERS_DATABASE_URL']);factory=sessionmaker(engine)
    with sync_lock(engine):
        with pytest.raises(ValueError,match='синхронизация'):
            synchronize(factory,'platonus',[],dry_run=True)
    schema='reader_scale_'+__import__('uuid').uuid4().hex
    with engine.begin() as c:c.exec_driver_sql('CREATE SCHEMA '+schema)
    scoped=engine.execution_options(schema_translate_map={None:schema});Base.metadata.create_all(scoped);factory=sessionmaker(scoped)
    try:
        from app.security import bootstrap
        with factory() as s:
            bootstrap(s,'test-secret')
            for start in range(0,20000,500):
                s.execute(Reader.__table__.insert(),[{'full_name':f'Читатель {i:05d}','ticket_number':f'TEST-{i:05d}','barcode':f'RDR{i:08d}','category':'student','faculty':'Тест'} for i in range(start,start+500)])
            s.commit()
        def dependency():
            with factory() as s:yield s
        app.dependency_overrides[db]=dependency
        with TestClient(app) as c:
            auth=c.post('/api/auth/login',json={'username':'admin','password':'test-secret'}).json();c.headers['X-CSRF-Token']=auth['csrf_token']
            result=c.get('/api/readers?offset=19950&limit=50').json();assert result['total']==20000 and len(result['items'])==50
            assert c.get('/api/readers?q=TEST-19999').json()['total']==1
            result=c.get('/api/readers/export?q=Читатель%20199').text;assert len(result.splitlines())==101
    finally:
        app.dependency_overrides.clear()
        with engine.begin() as c:c.exec_driver_sql('DROP SCHEMA '+schema+' CASCADE')
        engine.dispose()
