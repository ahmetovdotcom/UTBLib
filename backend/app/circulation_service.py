"""All desk writes are transactional; global gate + reader/copy row locks.
The coarse gate also serializes reservations/stock operations at MVP scale.
"""
import hashlib,json
from datetime import datetime,date,time,timedelta,timezone
from decimal import Decimal
from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select,func,or_
from sqlalchemy.exc import IntegrityError
from .db import Copy,Record,AcquisitionLine,User,utcnow,CopyHistory
from .reader_models import Reader,Branch,ReaderPhoto
from .reader_core import TZ
from .security import require,has,lock
from .circulation_models import *
from .circulation_schemas import Policy

OPEN=('active','overdue')
def fail(message,code=409): raise HTTPException(code,message)
def aware(t):return t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t
def today():return utcnow().astimezone(TZ).date()
def end_day(d):return datetime.combine(d,time.max,TZ).astimezone(timezone.utc)
def gate(s):lock(s,'circulation-stock-gate')
def policy(s):
    row=s.get(CirculationSettings,1)
    return Policy(**row.value) if row else Policy()
def snapshot(obj):return jsonable_encoder({c.name:getattr(obj,c.name) for c in obj.__table__.columns})
def audit(s,entity,id,action,actor,before=None,after=None,reason=''):
    s.add(CirculationAudit(entity=entity,entity_id=id,action=action,actor_id=actor.id if actor else None,before=jsonable_encoder(before or {}),after=jsonable_encoder(after or {}),reason=reason))
def event(s,loan,kind,actor,previous=None,details=None):
    s.add(LoanEvent(loan_id=loan.id,kind=kind,actor_id=actor.id if actor else None,previous_due=previous,new_due=loan.due_at,details=jsonable_encoder(details or {})))
    audit(s,'loan',loan.id,kind,actor,{'due_at':previous} if previous else {},snapshot(loan),(details or {}).get('reason',''))
def notice(s,reader,kind,key,body,loan=None):
    if not s.scalar(select(CirculationNotice.id).where(CirculationNotice.key==key)):
        s.add(CirculationNotice(reader_id=reader,loan_id=loan,key=key,kind=kind,body=jsonable_encoder(body)));return 1
    return 0
def operation(s,actor,scope,body,fn):
    gate(s); key=f'{actor.id}:{scope}:{body.request_key}'
    fingerprint=hashlib.sha256(body.model_dump_json().encode()).hexdigest()
    prior=s.get(CirculationOperation,key)
    if prior:
        if prior.fingerprint!=fingerprint:fail('Этот ключ операции уже использован с другими данными')
        return prior.result
    try:
        result=jsonable_encoder(fn())
        s.add(CirculationOperation(key=key,fingerprint=fingerprint,result=result));s.commit()
        return result
    except IntegrityError:
        s.rollback();fail('Данные изменились или нарушена уникальность операции. Обновите карточку.')

def reader(s,id):
    r=s.scalar(select(Reader).where(Reader.id==id).with_for_update().execution_options(populate_existing=True))
    if not r:fail('Читатель не найден',404)
    return r

def copy(s,id):
    c=s.scalar(select(Copy).where(Copy.id==id).with_for_update().execution_options(populate_existing=True))
    if not c:fail('Экземпляр не найден',404)
    return c

def detail(s,c,create=False):
    d=s.get(CopyCirculation,c.id)
    if d is None:
        d=CopyCirculation(copy_id=c.id,condition='good',defects='',operation_state='normal',access='free',issue_count=0,version=1)
        if create:s.add(d);s.flush()
    return d

def record_id(s,c):return c.record_id if c.record_id else s.get(AcquisitionLine,c.line_id).record_id
def record_copies(s,rid):return select(Copy).where(or_(Copy.record_id==rid,Copy.line_id.in_(select(AcquisitionLine.id).where(AcquisitionLine.record_id==rid))))
def text_field(r,tag,code):return ' '.join(sf.get('value','') for f in r.marc.get('fields',[]) if f.get('tag')==tag for sf in f.get('subfields',[]) if sf.get('code')==code)
def title(s,c):
    r=s.get(Record,record_id(s,c));return text_field(r,'245','a') or 'Без заглавия'
def active_loan(s,cid):return s.scalar(select(Loan).where(Loan.copy_id==cid,Loan.closed_at.is_(None)))
def active_reservation(s,cid):return s.scalar(select(Reservation).where(Reservation.assigned_copy_id==cid,Reservation.status.in_(ACTIVE_RESERVATIONS)))
def queued_others(s,rid,reader_id):return bool(s.scalar(select(Reservation.id).where(Reservation.record_id==rid,Reservation.reader_id!=reader_id,Reservation.status.in_(ACTIVE_RESERVATIONS)).limit(1)))
def availability(s,c):
    d=detail(s,c)
    if c.status!='active':return c.status
    if d.operation_state!='normal':return d.operation_state
    if d.condition in ('severe','irreparable','lost'):return 'unavailable'
    if active_loan(s,c.id):return 'on_loan'
    if active_reservation(s,c.id):return 'reserved'
    return 'available'
def suggested(s,c,p=None):
    p=p or policy(s);rid=record_id(s,c)
    count=s.scalar(select(func.count()).select_from(record_copies(s,rid).where(Copy.status=='active',~Copy.id.in_(select(CopyCirculation.copy_id).where(CopyCirculation.operation_state=='lost'))).subquery()))
    days=p.scarce_days if count<=p.scarce_max else p.standard_days if count<=p.standard_max else p.abundant_days
    return end_day(today()+timedelta(days=days)),count,days

def copy_output(s,c):
    d=detail(s,c);due,count,days=suggested(s,c);r=s.get(Record,record_id(s,c));loan=active_loan(s,c.id)
    return {**snapshot(c),'record_id':r.id,'title':text_field(r,'245','a'),'author':text_field(r,'100','a'),
      'circulation':snapshot(d),'availability':availability(s,c),'suggested_on':due.astimezone(TZ).date(),'copy_count':count,'period_days':days,
      'branch':s.get(Branch,d.branch_id).name if d.branch_id else c.sigla,'loan_id':loan.id if loan else None}

def reader_check(s,r,p,actor=None,override=False,reason='',additional=0,renew=False):
    if r.status!='active':fail('Читатель заблокирован или приостановлен: '+r.block_reason)
    if s.scalar(select(Fine.id).where(Fine.reader_id==r.id,Fine.status=='pending').limit(1)):fail('Есть незакрытый штраф')
    if (p.block_incidents or renew) and s.scalar(select(Incident.id).where(Incident.reader_id==r.id,Incident.status=='open').limit(1)):fail('Есть открытое дело об инциденте')
    violations=[];now=utcnow()
    u=s.scalar(select(User).where(User.id==r.user_id).with_for_update().execution_options(populate_existing=True)) if r.user_id else None
    if r.valid_until and r.valid_until<today():violations.append('Истёк срок билета')
    if r.user_id and (not u or not u.active or u.deleted):violations.append('Учётная запись не действует')
    loans=list(s.scalars(select(Loan).where(Loan.reader_id==r.id,Loan.closed_at.is_(None))))
    limit=r.limits_override.get('max_active_loans',p.max_loans)
    if additional and len(loans)+additional>limit:violations.append('Превышен лимит выдач')
    if p.block_overdue and any(aware(x.due_at)<now for x in loans):violations.append('Есть просроченные книги')
    if override:
        if not actor:fail('Исключение недоступно',403)
        require(actor,'circulation.override_limits');valid_reason(reason)
    if violations:
        if not override:fail('; '.join(violations))
        audit(s,'reader',r.id,'override_limits',actor,{}, {'violations':violations},reason)
    return loans,limit

def valid_reason(reason):
    if len(reason.strip())<5 or len(set(reason.strip()))<3:fail('Укажите содержательную причину (не менее 5 символов)',422)
def due_date(s,c,r,p,actor,requested,calculated,reason,previous=None):
    due=end_day(requested) if requested else calculated
    if due<=utcnow() or (previous and due<=aware(previous)):fail('Дата должна быть в будущем и позже предыдущего срока',422)
    if due.astimezone(TZ).date()>today()+timedelta(days=365):fail('Максимальный срок — один год',422)
    if requested and due!=calculated:
        valid_reason(reason)
        if due.astimezone(TZ).date()>today()+timedelta(days=p.manual_days):require(actor,'circulation.override_due_date')
    if queued_others(s,record_id(s,c),r.id) and due>calculated:fail('Очередь других читателей не позволяет увеличить срок')
    return due

def copy_history(s,c,d,before,action,actor,loan=None,reader_id=None,reason=''):
    d.version+=1;c.version+=1
    after=snapshot(d)
    audit(s,'copy',c.id,action,actor,before,{**after,'loan_id':loan.id if loan else None,'reader_id':reader_id},reason)
    s.add(CopyHistory(copy_id=c.id,before={'circulation':before},after={'circulation':after,'operation':action,'actor_id':actor.id if actor else None,'loan_id':loan.id if loan else None}))

def reservation_change(s,res,status,actor,reason=''):
    before=snapshot(res);res.status=status;res.version+=1;res.reason=reason
    if status not in ACTIVE_RESERVATIONS:res.closed_at=utcnow();res.assigned_copy_id=None
    audit(s,'reservation',res.id,status,actor,before,snapshot(res),reason);s.flush()

def queue(s,rid,actor=None):
    p=policy(s)
    copies=list(s.scalars(record_copies(s,rid).order_by(Copy.id).with_for_update()))
    pending=list(s.scalars(select(Reservation).where(Reservation.record_id==rid,Reservation.status=='queued').order_by(Reservation.created_at,Reservation.id).with_for_update()))
    for res in pending:
        r=reader(s,res.reader_id)
        try:reader_check(s,r,p,additional=1)
        except HTTPException as exc:
            reservation_change(s,res,'pending',actor,'Приостановлена в очереди: '+str(exc.detail));continue
        c=next((c for c in copies if availability(s,c)=='available' and detail(s,c).access!='reading_room' and (res.pickup_branch_id is None or detail(s,c).branch_id==res.pickup_branch_id)),None)
        if c is None:continue
        res.assigned_copy_id=c.id;res.assigned_at=utcnow();res.expires_at=utcnow()+timedelta(days=p.preparation_days);reservation_change(s,res,'confirmed',actor,'Экземпляр выделен; сотрудник должен подтвердить готовность')

def issue(s,actor,body):
    r=reader(s,body.reader_id);p=policy(s)
    ids=[x.copy_id for x in body.items]
    if len(set(ids))!=len(ids):fail('Один экземпляр добавлен дважды',422)
    reader_check(s,r,p,actor,body.override,body.reason,len(ids))
    copies={id:copy(s,id) for id in sorted(ids)};results=[];release=set()
    # Re-check the whole basket before changing anything; rollback covers every side effect.
    for item in body.items:
        c=copies[item.copy_id];d=detail(s,c,True);res=active_reservation(s,c.id)
        if availability(s,c) not in ('available','reserved'):fail(f'Экземпляр {c.inventory_number} недоступен')
        if not c.barcode.strip():fail('У экземпляра отсутствует штрихкод')
        if d.access=='reading_room':fail('Этот экземпляр доступен только в читальном зале')
        if res and res.expires_at and aware(res.expires_at)<=utcnow():fail('Истёк срок получения брони. Дождитесь обработки очереди')
        if res and res.reader_id!=r.id:fail('Экземпляр закреплён за другим читателем')
        if res and res.status!='ready_for_pickup':fail('Бронь ещё не готова к получению')
        rid=record_id(s,c)
        own=s.scalar(select(Reservation).where(Reservation.record_id==rid,Reservation.reader_id==r.id,Reservation.status.in_(ACTIVE_RESERVATIONS)))
        if own and own.assigned_copy_id and own.status!='ready_for_pickup':fail('Собственная бронь ещё не готова к получению')
        due,count,days=suggested(s,c,p);actual=due_date(s,c,r,p,actor,item.due_on,due,item.reason)
        before=snapshot(d)
        loan=Loan(reader_id=r.id,copy_id=c.id,branch_id=d.branch_id,due_at=actual,calculated_due_at=due,issued_by=actor.id,status='active',notes=body.reason)
        s.add(loan);s.flush();d.issue_count+=1
        copy_history(s,c,d,before,'issued',actor,loan,r.id)
        event(s,loan,'issued',actor,details={'reason':item.reason,'override_reason':body.reason,'copy_count':count,'period_days':days,'calculated_due_at':due})
        if own:reservation_change(s,own,'fulfilled',actor,'Исполнено выдачей №'+str(loan.id));release.add(rid)
        notice(s,r.id,'issued',f'issued:{loan.id}',{'due_at':actual,'title':title(s,c)},loan.id)
        results.append({'id':loan.id,'copy_id':c.id,'inventory_number':c.inventory_number,'title':title(s,c),'due_at':actual})
    s.flush()
    for rid in sorted(release):queue(s,rid,actor)
    return {'loans':results}

def lock_loan(s,id):
    loan=s.get(Loan,id)
    if not loan:fail('Выдача не найдена',404)
    r=reader(s,loan.reader_id);c=copy(s,loan.copy_id)
    loan=s.scalar(select(Loan).where(Loan.id==id).with_for_update().execution_options(populate_existing=True))
    return loan,r,c

def renew(s,actor,id,body,own=False):
    loan,r,c=lock_loan(s,id);p=policy(s)
    if own and r.user_id!=actor.id:fail('Выдача другого читателя',403)
    if loan.closed_at or aware(loan.due_at)<utcnow():fail('Закрытую или просроченную выдачу продлить нельзя')
    if body.version!=loan.version:fail('Выдача уже изменена. Обновите карточку')
    if not p.renewals_enabled or loan.renewal_count>=p.max_renewals:fail('Лимит продлений исчерпан или продление отключено')
    reader_check(s,r,p,actor,body.override if not own else False,body.reason,renew=True)
    if queued_others(s,record_id(s,c),r.id):fail('Есть бронь другого читателя')
    prev=loan.due_at;calculated=aware(prev)+timedelta(days=p.renewal_days)
    if own and body.due_on:fail('Ручная дата доступна только сотруднику',403)
    loan.due_at=due_date(s,c,r,p,actor,body.due_on,calculated,body.reason,prev)
    loan.version+=1;loan.renewal_count+=1;loan.updated_at=utcnow()
    event(s,loan,'renewed',actor,prev,{'reason':body.reason});notice(s,r.id,'renewed',f'renew:{loan.id}:{loan.version}',{'due_at':loan.due_at},loan.id)
    return {'id':loan.id,'due_at':loan.due_at,'version':loan.version}

def fine(s,loan,amount,reason,incident=None,actor=None):
    if amount<=0:return
    entry=Fine(reader_id=loan.reader_id,loan_id=loan.id,copy_id=loan.copy_id,incident_id=incident.id if incident else None,amount=amount,reason=reason);s.add(entry);s.flush();audit(s,'fine',entry.id,'charged',actor,{},snapshot(entry),reason)
def return_loan(s,actor,id,body):
    loan,r,c=lock_loan(s,id);p=policy(s)
    if loan.closed_at:fail('Выдача уже закрыта')
    if body.version!=loan.version:fail('Выдача изменена. Повторите поиск')
    d=detail(s,c,True);before=snapshot(d);now=utcnow()
    loan.closed_at=now;loan.returned_to=actor.id;loan.condition_on_return=body.condition;loan.version+=1;loan.updated_at=now
    loan.notes=body.notes;loan.status='lost' if body.incident=='lost' else 'returned'
    if loan.status=='lost':loan.lost_at=now;d.condition='lost';d.operation_state='lost'
    else:
        loan.returned_at=now
        if body.condition!='unchanged':d.condition=body.condition
    days=max(0,(now.astimezone(TZ).date()-aware(loan.due_at).astimezone(TZ).date()).days)
    fine(s,loan,Decimal(days)*p.fine_per_day,'overdue',actor=actor)
    incident=None
    if body.incident!='none':
        incident=Incident(reader_id=r.id,loan_id=loan.id,copy_id=c.id,kind=body.incident,before=before['condition'],after=d.condition,description=body.notes,action=body.action,responsible_id=actor.id)
        s.add(incident);s.flush();audit(s,'incident',incident.id,'opened',actor,{},snapshot(incident),body.notes)
        if body.incident=='damaged':d.operation_state='repair' if body.action=='repair' else 'processing' if body.action in ('replacement','write_off') else 'normal';d.defects=body.notes
        if body.amount:require(actor,'fines.manage');fine(s,loan,body.amount,body.incident,incident,actor)
    if d.condition in ('good','worn','minor','moderate') and d.operation_state=='normal':
        for case in s.scalars(select(Incident).where(Incident.loan_id==loan.id,Incident.kind=='presumed_lost',Incident.status=='open')):
            old=snapshot(case);case.status='resolved';case.resolved_at=now;case.decision='Книга возвращена';case.version+=1;audit(s,'incident',case.id,'resolved',actor,old,snapshot(case),'Книга возвращена')
    event(s,loan,'lost' if loan.status=='lost' else 'returned',actor,details={'reason':body.notes,'overdue_days':days})
    copy_history(s,c,d,before,loan.status,actor,loan,r.id,body.notes);s.flush();queue(s,record_id(s,c),actor)
    notice(s,r.id,loan.status,f'close:{loan.id}',{'status':loan.status,'overdue_days':days},loan.id)
    return {'id':loan.id,'status':loan.status,'overdue_days':days,'overdue_fine':str(Decimal(days)*p.fine_per_day),'incident_id':incident.id if incident else None}

def loan_output(s,l):
    c=s.get(Copy,l.copy_id);r=s.get(Reader,l.reader_id)
    return {**snapshot(l),'status':'overdue' if not l.closed_at and aware(l.due_at)<utcnow() else l.status,'title':title(s,c),
     'inventory_number':c.inventory_number,'barcode':c.barcode,'reader_name':r.full_name,'ticket_number':r.ticket_number,
     'issued_by_name':s.get(User,l.issued_by).display_name,'returned_to_name':s.get(User,l.returned_to).display_name if l.returned_to else None,
     'days_remaining':(aware(l.due_at).astimezone(TZ).date()-today()).days}

def summary(s,r):
    p=policy(s);loans=list(s.scalars(select(Loan).where(Loan.reader_id==r.id,Loan.closed_at.is_(None)).order_by(Loan.due_at)))
    fines=list(s.scalars(select(Fine).where(Fine.reader_id==r.id,Fine.status=='pending')))
    cases=list(s.scalars(select(Incident).where(Incident.reader_id==r.id,Incident.status=='open')))
    maximum=r.limits_override.get('max_active_loans',p.max_loans)
    return {**{key:getattr(r,key) for key in ('id','full_name','ticket_number','barcode','category','status','block_reason','valid_until','study_group','department')},
      'loans':[loan_output(s,l) for l in loans],'fines':[snapshot(f) for f in fines],'incidents':[snapshot(c) for c in cases],
      'max_loans':maximum,'used':len(loans),'near_limit':len(loans)>=max(0,maximum-2),'has_photo':s.get(ReaderPhoto,r.id) is not None,
      'overdue':sum(aware(l.due_at)<utcnow() for l in loans)}

def reserve(s,actor,body):
    r=reader(s,body.reader_id);p=policy(s);reader_check(s,r,p,additional=1)
    if not s.get(Record,body.record_id):fail('Издание не найдено',404)
    if body.branch_id:
        b=s.get(Branch,body.branch_id)
        if not b or not b.active:fail('Пункт обслуживания недоступен',422)
    if s.scalar(select(Reservation.id).where(Reservation.reader_id==r.id,Reservation.record_id==body.record_id,Reservation.status.in_(ACTIVE_RESERVATIONS))):fail('Уже есть активная бронь этого издания')
    count=s.scalar(select(func.count()).select_from(Reservation).where(Reservation.reader_id==r.id,Reservation.status.in_(ACTIVE_RESERVATIONS)))
    if count>=p.max_reservations:fail('Достигнут лимит броней')
    res=Reservation(reader_id=r.id,record_id=body.record_id,pickup_branch_id=body.branch_id,actor_id=actor.id,status='queued');s.add(res);s.flush()
    audit(s,'reservation',res.id,'created',actor,{},snapshot(res));queue(s,body.record_id,actor)
    return snapshot(res)

def reservation_action(s,actor,id,body):
    res=s.get(Reservation,id)
    if not res:fail('Бронь не найдена',404)
    reader(s,res.reader_id)
    if res.version!=body.version:fail('Бронь уже изменена')
    p=policy(s)
    if res.status not in ACTIVE_RESERVATIONS:fail('Бронь закрыта')
    if body.action=='cancel':valid_reason(body.reason);reservation_change(s,res,'cancelled',actor,body.reason)
    elif body.action=='retry':
        if res.status!='pending':fail('Повтор доступен только для приостановленной очереди')
        reader_check(s,s.get(Reader,res.reader_id),p,additional=1);reservation_change(s,res,'queued',actor,'Повторная проверка сотрудником')
    elif body.action=='ready':
        if res.status!='confirmed' or not res.assigned_copy_id:fail('Экземпляр ещё не выделен')
        c=copy(s,res.assigned_copy_id);d=detail(s,c)
        if res.pickup_branch_id is not None and d.branch_id!=res.pickup_branch_id:fail('Экземпляр находится в другом пункте. Перемещение не подтверждено')
        reader_check(s,s.get(Reader,res.reader_id),p,additional=1)
        res.ready_at=utcnow();res.expires_at=utcnow()+timedelta(days=p.pickup_days)
        reservation_change(s,res,'ready_for_pickup',actor,'Сотрудник подтвердил физическую готовность')
        notice(s,res.reader_id,'reservation_ready',f'reservation:{res.id}:ready',{'reservation_id':res.id,'expires_at':res.expires_at})
    else:
        if res.status!='ready_for_pickup' or res.extensions>=p.reservation_extensions or aware(res.expires_at)<=utcnow():fail('Продление срока брони недоступно')
        valid_reason(body.reason);res.expires_at=aware(res.expires_at)+timedelta(days=p.pickup_days);res.extensions+=1;reservation_change(s,res,res.status,actor,body.reason)
    queue(s,res.record_id,actor);return snapshot(res)

def resolve_incident(s,actor,id,body):
    case=s.get(Incident,id)
    if not case:fail('Дело не найдено',404)
    loan,r,c=lock_loan(s,case.loan_id);d=detail(s,c,True)
    if case.status!='open' or case.version!=body.version:fail('Дело уже изменено или закрыто')
    old=snapshot(case);before=snapshot(d);valid_reason(body.reason)
    if body.action in ('found','repaired'):
        if loan.closed_at is None:fail('Сначала оформите возврат открытой выдачи')
        if c.status!='active':fail('Списанный или отменённый экземпляр нельзя вернуть в оборот')
        if body.action=='found' and case.kind!='lost':fail('Решение «найдена» доступно по делу об утрате')
        if body.action=='repaired' and case.kind!='damaged':fail('Ремонт доступен по делу о повреждении')
        d.condition='good';d.operation_state='normal';d.defects='';copy_history(s,c,d,before,body.action,actor,loan,r.id,body.reason)
    elif body.action in ('written_off','replacement'):
        if c.status!='withdrawn':fail('Сначала оформите реальный акт списания в разделе «Списание». Заменяющую книгу зарегистрируйте отдельным экземпляром')
    else:
        if d.operation_state=='lost' or case.kind=='lost':fail('Утрата требует решения: книга найдена, списана или заменена')
        if case.kind=='presumed_lost' and loan.closed_at is None:fail('Сначала верните книгу либо оформите утрату')
    case.status='resolved';case.resolved_at=utcnow();case.decision=body.reason;case.action=body.action;case.version+=1;case.responsible_id=actor.id
    audit(s,'incident',case.id,'resolved',actor,old,snapshot(case),body.reason);s.flush();queue(s,record_id(s,c),actor)
    return snapshot(case)

def sweep(s):
    gate(s);now=utcnow();p=policy(s);counts={'overdue':0,'notices':0,'expired':0,'presumed_lost':0}
    ids=list(s.scalars(select(Loan.id).where(Loan.closed_at.is_(None)).order_by(Loan.reader_id,Loan.copy_id)))
    for id in ids:
        loan,r,c=lock_loan(s,id)
        if loan.closed_at:continue
        due=aware(loan.due_at);stamp=due.isoformat()
        if due<now:
            if loan.status!='overdue':loan.status='overdue';loan.version+=1;event(s,loan,'overdue',None);counts['overdue']+=1
            counts['notices']+=notice(s,r.id,'overdue',f'overdue:{id}:{stamp}',{'due_at':due},id)
            if p.presumed_lost_days and (today()-due.astimezone(TZ).date()).days>=p.presumed_lost_days and not s.scalar(select(Incident.id).where(Incident.loan_id==id,Incident.kind=='presumed_lost')):
                case=Incident(reader_id=r.id,loan_id=id,copy_id=c.id,kind='presumed_lost',description='Длительная просрочка: требуется проверка');s.add(case);s.flush();audit(s,'incident',case.id,'opened',None,{},snapshot(case));event(s,loan,'presumed_lost',None);counts['presumed_lost']+=1
        elif due.astimezone(TZ).date()==today()+timedelta(days=1):counts['notices']+=notice(s,r.id,'due_tomorrow',f'tomorrow:{id}:{stamp}',{'due_at':due},id)
    held=list(s.scalars(select(Reservation).where(Reservation.status.in_(('confirmed','ready_for_pickup'))).order_by(Reservation.id).with_for_update()))
    affected=set()
    for res in held:
        if res.expires_at and aware(res.expires_at)<=now:
            reservation_change(s,res,'expired',None,'Истёк срок подготовки или получения');affected.add(res.record_id);counts['expired']+=1
            continue
        r=reader(s,res.reader_id)
        try:reader_check(s,r,p,additional=1)
        except HTTPException as exc:
            res.assigned_copy_id=None;res.expires_at=None
            reservation_change(s,res,'pending',None,'Выделение приостановлено: '+str(exc.detail));affected.add(res.record_id)
    for rid in sorted(affected):queue(s,rid)
    s.commit();return counts
