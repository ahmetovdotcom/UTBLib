"""Concurrency and real SQL constraints: explicitly supplied disposable PostgreSQL."""
import os
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import pytest
from sqlalchemy import create_engine,select,func,text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException
from app.db import Base,User,Copy,Record,DocumentType
from app.reader_models import Reader
from app.circulation_models import Loan,Reservation,CirculationNotice
from app.circulation_schemas import IssueInput,RenewInput,ReturnInput
from app import circulation_service as svc
pytestmark=pytest.mark.skipif(not os.getenv('TEST_CIRCULATION_DATABASE_URL'),reason='Dedicated PostgreSQL required')

@pytest.fixture
def factory():
    engine=create_engine(os.environ['TEST_CIRCULATION_DATABASE_URL']);schema='circulation_test_'+uuid4().hex
    with engine.begin() as c:c.exec_driver_sql('CREATE SCHEMA '+schema)
    scoped=engine.execution_options(schema_translate_map={None:schema});Base.metadata.create_all(scoped);factory=sessionmaker(scoped)
    with factory() as s:
        s.add(User(id=1,username='test-admin',display_name='Test admin',role='admin',password_hash='unused',permissions=[]))
        s.add(DocumentType(id=1,name='Test',config=[]));s.flush()
        s.add(Record(id=1,type_id=1,marc={'fields':[{'tag':'245','subfields':[{'code':'a','value':'Test'}]}]},search_text='test'))
        s.add_all([Reader(id=i,full_name='Test '+str(i),ticket_number='T'+str(i),barcode='R'+str(i),category='student',limits_override={'max_active_loans':1}) for i in (1,2)])
        s.flush();s.add_all([Copy(id=i,record_id=1,request_key=str(uuid4()),payload_hash='test',inventory_number='00'+str(i),barcode='B00'+str(i),sigla='',note='') for i in (1,2,3)]);s.commit()
    try:yield factory
    finally:
        with engine.begin() as c:c.exec_driver_sql('DROP SCHEMA '+schema+' CASCADE')
        engine.dispose()

def issue(factory,rid,cid,key=None):
    with factory() as s:
        user=s.get(User,1);body=IssueInput(request_key=key or uuid4(),reader_id=rid,items=[{'copy_id':cid}])
        try:return svc.operation(s,user,'issue',body,lambda:svc.issue(s,user,body))
        except HTTPException as exc:s.rollback();return exc.status_code

def test_two_readers_same_copy_and_database_index(factory):
    with ThreadPoolExecutor(2) as pool:results=list(pool.map(lambda rid:issue(factory,rid,1),(1,2)))
    assert sum(isinstance(v,dict) for v in results)==1
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(Loan))==1
        s.add(Loan(reader_id=2,copy_id=1,issued_by=1,due_at=svc.end_day(svc.today()+timedelta(days=2)),calculated_due_at=svc.end_day(svc.today()+timedelta(days=2))))
        with pytest.raises(IntegrityError):s.commit()

def test_same_reader_different_copies_limit(factory):
    with ThreadPoolExecutor(2) as pool:results=list(pool.map(lambda cid:issue(factory,1,cid),(1,2)))
    assert sum(isinstance(v,dict) for v in results)==1
    with factory() as s:assert s.scalar(select(func.count()).select_from(Loan))==1

def test_simultaneous_retry_and_return_renew_race(factory):
    key=uuid4()
    with ThreadPoolExecutor(2) as pool:results=list(pool.map(lambda _:issue(factory,1,1,key),(1,2)))
    assert results[0]==results[1];id=results[0]['loans'][0]['id']
    def run(kind):
        with factory() as s:
            user=s.get(User,1);body=(RenewInput if kind=='renew' else ReturnInput)(request_key=uuid4(),version=1)
            try:return svc.operation(s,user,kind,body,lambda:(svc.renew if kind=='renew' else svc.return_loan)(s,user,id,body))
            except HTTPException as exc:s.rollback();return exc.status_code
    with ThreadPoolExecutor(2) as pool:results=list(pool.map(run,('renew','return')))
    assert sum(isinstance(v,dict) for v in results)==1
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(Loan))==1
        loan=s.get(Loan,id);assert loan.version==2

def test_failed_basket_rolls_back_notices_and_profile_lock(factory):
    issue(factory,1,1)
    with factory() as s:
        user=s.get(User,1);r=s.get(Reader,2);r.limits_override={'max_active_loans':3};s.commit()
        body=IssueInput(request_key=uuid4(),reader_id=2,items=[{'copy_id':2},{'copy_id':1}])
        with pytest.raises(HTTPException):svc.operation(s,user,'issue',body,lambda:svc.issue(s,user,body))
        s.rollback()
        assert s.scalar(select(func.count()).select_from(Loan))==1
        assert s.scalar(select(func.count()).select_from(CirculationNotice))==1

def test_sweep_racing_return_never_reopens(factory):
    from app.db import utcnow
    id=issue(factory,1,1)['loans'][0]['id']
    with factory() as s:
        l=s.get(Loan,id);l.issued_at=utcnow()-timedelta(days=10);l.due_at=svc.end_day(svc.today()-timedelta(days=2));s.commit()
    def sweep():
        with factory() as s:return svc.sweep(s)
    def close():
        with factory() as s:
            body=ReturnInput(request_key=uuid4(),version=1);u=s.get(User,1)
            try:return svc.operation(s,u,'return:'+str(id),body,lambda:svc.return_loan(s,u,id,body))
            except HTTPException:s.rollback();return None
    with ThreadPoolExecutor(2) as pool:
        a=pool.submit(sweep);b=pool.submit(close);a.result();result=b.result()
    if result is None:
        with factory() as s:
            body=ReturnInput(request_key=uuid4(),version=s.get(Loan,id).version);u=s.get(User,1);svc.operation(s,u,'return:'+str(id),body,lambda:svc.return_loan(s,u,id,body))
    with factory() as s:
        svc.sweep(s);l=s.get(Loan,id);assert l.status=='returned' and l.closed_at is not None
