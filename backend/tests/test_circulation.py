import os
os.environ.setdefault('DATABASE_URL','sqlite://')
from uuid import uuid4
from datetime import timedelta
from contextlib import contextmanager
import pytest
from sqlalchemy import select,func
from app.db import Base,User,Copy,Record,DocumentType,utcnow
from app.reader_models import Reader,LibraryVisit
from app.circulation_models import *
from app.circulation_service import today,end_day,sweep,suggested
from app.main import app,db
from test_catalog import client

@contextmanager
def session():
    g=app.dependency_overrides[db]();s=next(g)
    try:yield s
    finally:g.close()

def seed(n=3):
    with session() as s:
        t=DocumentType(name='Тест книги',config=[]);s.add(t);s.flush()
        r=Record(type_id=t.id,version=1,marc={'leader':'00000nam a2200000   4500','fields':[{'tag':'245','subfields':[{'code':'a','value':'Тестовая книга'}]},{'tag':'020','subfields':[{'code':'a','value':'978-601-04-3364-9'}]}]},search_text='тестовая книга 978-601-04-3364-9');s.add(r);s.flush()
        readers=[Reader(full_name='Тест '+str(i),category='student',ticket_number='TEST'+str(i),barcode='RDR-TEST'+str(i)) for i in range(3)];s.add_all(readers)
        copies=[Copy(record_id=r.id,request_key=str(uuid4()),payload_hash='test',inventory_number='00'+str(i),barcode='BC00'+str(i),sigla='Тест',note='') for i in range(n)];s.add_all(copies);s.commit()
        return [v.id for v in readers],[v.id for v in copies],r.id

def issue(c,r,copies,**kwargs):return c.post('/api/circulation/issue',json={'request_key':str(uuid4()),'reader_id':r,'items':[{'copy_id':x} for x in copies],**kwargs})
def close(c,id,**kwargs):return c.post(f'/api/circulation/loans/{id}/return',json={'request_key':str(uuid4()),'version':1,**kwargs})
def renew(c,id,**kwargs):return c.post(f'/api/circulation/loans/{id}/renew',json={'request_key':str(uuid4()),'version':1,**kwargs})

def test_basket_repeat_history_and_no_visit(client):
    readers,copies,_=seed();body={'request_key':str(uuid4()),'reader_id':readers[0],'items':[{'copy_id':c} for c in copies[:2]]}
    first=client.post('/api/circulation/issue',json=body);assert first.status_code==200,first.text
    assert client.post('/api/circulation/issue',json=body).json()==first.json()
    with session() as s:
        assert s.scalar(select(func.count()).select_from(Loan))==2
        assert s.scalar(select(func.count()).select_from(LoanEvent))==2
        assert s.scalar(select(func.count()).select_from(LibraryVisit))==0
        assert s.scalar(select(func.count()).select_from(CirculationNotice))==2
        assert all(l.due_at==end_day(today()+timedelta(days=5)).replace(tzinfo=None) for l in s.scalars(select(Loan)))
    assert client.get('/api/circulation/loans').json()['total']==2
    assert client.get('/api/readers/'+str(readers[0])).json()['circulation']['used']==2

def test_basket_rollback_duplicate_and_isbn(client):
    readers,copies,rid=seed();assert issue(client,readers[0],[copies[0]]).status_code==200
    assert issue(client,readers[1],[copies[1],copies[0]]).status_code==409
    assert issue(client,readers[0],[copies[1],copies[1]]).status_code==422
    with session() as s:
        assert s.scalar(select(func.count()).select_from(Loan))==1
        assert s.scalar(select(func.count()).select_from(CirculationNotice))==1
    found=client.get('/api/circulation/copies?q=978-601-04-3364-9').json();assert found['kind']=='editions' and found['items'][0]['id']==rid
    a=client.get('/api/circulation/copies?q=001').json()['items'][0]['id'];b=client.get('/api/circulation/copies?q=BC001').json()['items'][0]['id'];assert a==b

@pytest.mark.parametrize('kind',['blocked','fine','incident','reading_room','repair','lost','withdrawn','transfer'])
def test_hard_blocks_never_overridden(client,kind):
    readers,copies,_=seed()
    with session() as s:
        if kind=='blocked':s.get(Reader,readers[0]).status='blocked'
        elif kind=='withdrawn':s.get(Copy,copies[0]).status='withdrawn'
        elif kind in ('reading_room','repair','lost','transfer'):
            s.add(CopyCirculation(copy_id=copies[0],access=kind if kind=='reading_room' else 'free',operation_state=kind if kind!='reading_room' else 'normal'))
        else:
            l=Loan(reader_id=readers[0],copy_id=copies[1],due_at=end_day(today()+timedelta(days=3)),calculated_due_at=end_day(today()+timedelta(days=3)),issued_by=1);s.add(l);s.flush()
            if kind=='fine':s.add(Fine(reader_id=readers[0],copy_id=copies[1],loan_id=l.id,reason='lost',amount=10))
            else:s.add(Incident(reader_id=readers[0],copy_id=copies[1],loan_id=l.id,kind='damaged'))
        s.commit()
    assert issue(client,readers[0],[copies[0]],override=True,reason='Разрешил руководитель').status_code==409

def test_limits_expired_ticket_exception_and_audit(client):
    readers,copies,_=seed()
    with session() as s:r=s.get(Reader,readers[0]);r.valid_until=today()-timedelta(days=1);r.limits_override={'max_active_loans':1};s.commit()
    assert issue(client,readers[0],copies[:2]).status_code==409
    assert issue(client,readers[0],copies[:2],override=True,reason='').status_code==422
    assert issue(client,readers[0],copies[:2],override=True,reason='Разрешил руководитель').status_code==200
    with session() as s:assert s.scalar(select(CirculationAudit).where(CirculationAudit.action=='override_limits')).reason=='Разрешил руководитель'

def test_renewal_and_stale_form(client):
    readers,copies,_=seed();id=issue(client,readers[0],[copies[0]]).json()['loans'][0]['id']
    before=client.get(f'/api/circulation/loans/{id}').json()
    body={'request_key':str(uuid4()),'version':1}
    result=client.post(f'/api/circulation/loans/{id}/renew',json=body);assert result.status_code==200,result.text
    assert client.post(f'/api/circulation/loans/{id}/renew',json=body).json()==result.json()
    assert renew(client,id).status_code==409
    result=client.get(f'/api/circulation/loans/{id}').json();assert len(result['events'])==2 and result['renewal_count']==1
    assert result['events'][1]['previous_due']==before['due_at']


def test_return_blocked_overdue_fine_once_and_sweep(client):
    readers,copies,_=seed();id=issue(client,readers[0],[copies[0]]).json()['loans'][0]['id']
    with session() as s:
        r=s.get(Reader,readers[0]);r.status='blocked';l=s.get(Loan,id);l.issued_at=utcnow()-timedelta(days=10);l.due_at=end_day(today()-timedelta(days=3));s.add(CirculationSettings(id=1,value={'fine_per_day':'10.25'}));s.commit();sweep(s);sweep(s)
        version=s.get(Loan,id).version
        assert s.scalar(select(func.count()).select_from(LoanEvent).where(LoanEvent.kind=='overdue'))==1
    body={'request_key':str(uuid4()),'version':version}
    result=client.post(f'/api/circulation/loans/{id}/return',json=body);assert result.status_code==200,result.text
    assert result.json()['overdue_fine']=='30.75'
    assert client.post(f'/api/circulation/loans/{id}/return',json=body).status_code==200
    with session() as s:
        sweep(s);assert s.scalar(select(func.count()).select_from(Fine))==1
        assert s.get(Loan,id).status=='returned'
    assert close(client,id).status_code==409

@pytest.mark.parametrize('condition,incident,action,state',[('moderate','damaged','repair','repair'),('irreparable','damaged','write_off','processing'),('lost','lost','none','lost')])
def test_incidents_do_not_writeoff(client,condition,incident,action,state):
    readers,copies,_=seed();id=issue(client,readers[0],[copies[0]]).json()['loans'][0]['id']
    result=close(client,id,condition=condition,incident=incident,action=action,notes='Обнаружено повреждение при приёме');assert result.status_code==200,result.text
    with session() as s:
        assert s.get(Copy,copies[0]).status=='active'
        assert s.get(CopyCirculation,copies[0]).operation_state==state
        l=s.get(Loan,id);assert bool(l.returned_at)==(incident!='lost') and bool(l.lost_at)==(incident=='lost')
        assert s.scalar(select(func.count()).select_from(Incident))==1

def test_reservation_queue_ready_and_other_copy(client):
    readers,copies,rid=seed(1);id=issue(client,readers[0],copies).json()['loans'][0]['id']
    result=client.post('/api/circulation/reservations',json={'request_key':str(uuid4()),'reader_id':readers[1],'record_id':rid});assert result.status_code==200,result.text
    assert result.json()['status']=='queued'
    assert renew(client,id).status_code==409
    assert close(client,id).status_code==200
    res=client.get('/api/circulation/reservations').json()['items'][0];assert res['status']=='confirmed'
    assert issue(client,readers[0],copies,override=True,reason='Причина исключения').status_code==409
    assert issue(client,readers[1],copies).status_code==409
    assert client.post('/api/circulation/reservations/'+str(res['id']),json={'request_key':str(uuid4()),'version':res['version'],'action':'ready'}).status_code==200
    assert issue(client,readers[1],copies).status_code==200
    assert client.get('/api/circulation/reservations').json()['items'][0]['status']=='fulfilled'

@pytest.mark.parametrize('count,days',[(1,3),(2,3),(3,5),(5,5),(6,7)])
def test_policy_scale_and_local_time(client,count,days):
    _,copies,_=seed(count)
    with session() as s:
        due,total,period=suggested(s,s.get(Copy,copies[0]));assert total==count and period==days
        assert due.hour==18 and due.minute==59 and due.astimezone(__import__('zoneinfo').ZoneInfo('Asia/Almaty')).date()==today()+timedelta(days=days)

def test_due_hard_cap_and_invalid_return(client):
    readers,copies,_=seed()
    assert issue(client,readers[0],[],items=[]).status_code==422
    body={'request_key':str(uuid4()),'reader_id':readers[0],'items':[{'copy_id':copies[0],'due_on':str(today()+timedelta(days=366)),'reason':'Особый срок'}]}
    assert client.post('/api/circulation/issue',json=body).status_code==422
    id=issue(client,readers[0],[copies[0]]).json()['loans'][0]['id']
    assert close(client,id,condition='lost',incident='none').status_code==422


def test_permissions_and_local_only(client,monkeypatch):
    from app.security import password_hash
    readers,copies,_=seed()
    with session() as s:s.add(User(username='desk',display_name='Desk',role='librarian',permissions=['circulation.issue'],password_hash=password_hash('test-secret')));s.commit()
    auth=client.post('/api/auth/login',json={'username':'desk','password':'test-secret'}).json();client.headers['X-CSRF-Token']=auth['csrf_token']
    monkeypatch.setenv('PLATONUS_DB_HOST','unreachable.invalid');monkeypatch.setenv('AD_HOST','unreachable.invalid')
    assert issue(client,readers[0],[copies[0]]).status_code==200
    assert issue(client,readers[0],[copies[1]],override=True,reason='Нельзя обходить').status_code==403
    assert client.get('/api/circulation/fines').status_code==403
    assert client.get('/api/readers/'+str(readers[0])).status_code==403
    assert client.post('/api/circulation/issue',json={'request_key':str(uuid4()),'reader_id':readers[0],'items':[{'copy_id':copies[1]}]},headers={'X-CSRF-Token':'bad'}).status_code==403

def test_own_account_scope_and_foreign_renewal(client):
    from app.security import password_hash
    readers,copies,_=seed();one=issue(client,readers[0],[copies[0]]).json()['loans'][0]['id'];other=issue(client,readers[1],[copies[1]]).json()['loans'][0]['id']
    with session() as s:
        u=User(username='reader-login',display_name='Читатель',role='reader',permissions=['loans.view_own','loans.renew_own'],password_hash=password_hash('test-secret'));s.add(u);s.flush();s.get(Reader,readers[0]).user_id=u.id;s.commit()
    auth=client.post('/api/auth/login',json={'username':'reader-login','password':'test-secret'}).json();client.headers['X-CSRF-Token']=auth['csrf_token']
    own=client.get('/api/circulation/mine').json();assert own['total']==1 and own['items'][0]['id']==one
    assert client.get('/api/circulation/loans').status_code==403
    assert client.get('/api/circulation/readers').status_code==403
    assert client.post(f'/api/circulation/mine/{other}/renew',json={'request_key':str(uuid4()),'version':1}).status_code==403
    assert client.post(f'/api/circulation/mine/{one}/renew',json={'request_key':str(uuid4()),'version':1}).status_code==200

def test_reservation_expiry_releases_to_next_reader(client):
    readers,copies,rid=seed(1)
    first=client.post('/api/circulation/reservations',json={'request_key':str(uuid4()),'reader_id':readers[0],'record_id':rid}).json()
    second=client.post('/api/circulation/reservations',json={'request_key':str(uuid4()),'reader_id':readers[1],'record_id':rid}).json()
    assert first['status']=='confirmed' and second['status']=='queued'
    with session() as s:
        s.get(Reservation,first['id']).expires_at=utcnow()-timedelta(seconds=1);s.commit();assert sweep(s)['expired']==1
        assert s.get(Reservation,first['id']).status=='expired';assert s.get(Reservation,second['id']).status=='confirmed'
        assert sweep(s)['expired']==0

def test_reminder_new_deadline_and_presumed_loss(client):
    readers,copies,_=seed();id=issue(client,readers[0],[copies[0]]).json()['loans'][0]['id']
    with session() as s:
        l=s.get(Loan,id);l.due_at=end_day(today()+timedelta(days=1));s.commit()
        assert sweep(s)['notices']==1 and sweep(s)['notices']==0
        l=s.get(Loan,id);l.issued_at=utcnow()-timedelta(days=10);l.due_at=end_day(today()-timedelta(days=3));s.add(CirculationSettings(id=1,value={'presumed_lost_days':2}));s.commit();assert sweep(s)['presumed_lost']==1
        assert s.get(Loan,id).closed_at is None and s.scalar(select(func.count()).select_from(Fine))==0
        version=s.get(Loan,id).version
    assert close(client,id,version=version).status_code==200
    with session() as s:assert s.scalar(select(Incident)).status=='resolved';assert sweep(s)['overdue']==0


def test_return_good_condition_is_normal_and_idempotent(client):
    readers,copies,_=seed()
    id=issue(client,readers[0],[copies[0]]).json()['loans'][0]['id']
    body={'request_key':str(uuid4()),'version':1,'condition':'good','incident':'none','action':'none','notes':'','amount':'0'}
    first=client.post(f'/api/circulation/loans/{id}/return',json=body)
    assert first.status_code==200,first.text
    assert client.post(f'/api/circulation/loans/{id}/return',json=body).json()==first.json()
    with session() as s:
        loan=s.get(Loan,id)
        assert loan.status=='returned' and loan.returned_at is not None
        assert loan.condition_on_return=='good'
        assert s.get(CopyCirculation,copies[0]).condition=='good'
        assert s.scalar(select(func.count()).select_from(Incident))==0
        assert s.scalar(select(func.count()).select_from(Fine))==0
        assert s.scalar(select(func.count()).select_from(LoanEvent).where(LoanEvent.kind=='returned'))==1
