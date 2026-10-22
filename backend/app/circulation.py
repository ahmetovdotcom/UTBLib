from datetime import date,timedelta
from fastapi import APIRouter,Depends,Query,HTTPException,Request
from sqlalchemy import select,func,or_
from .db import User,Record,Copy,Withdrawal
from .reader_models import Reader,Branch
from .reader_core import rate_limit,local_bounds
from .security import require,has
from .circulation_models import *
from .circulation_schemas import *
from . import circulation_service as svc

def make_router(auth,db):
    router=APIRouter(prefix='/api/circulation',dependencies=[Depends(auth)])
    @router.get('/accounts')
    def accounts(s=Depends(db),user=Depends(auth)):
        if user.role!='admin':svc.fail('Связь учётной записи настраивает администратор',403)
        return [{'id':u.id,'name':u.display_name,'login':u.username} for u in s.scalars(select(User).where(User.role=='reader',User.deleted.is_(False)).order_by(User.display_name))]
    @router.post('/readers/{id}/account')
    def account(id:int,body:AccountLink,s=Depends(db),user=Depends(auth)):
        if user.role!='admin':svc.fail('Связь учётной записи настраивает администратор',403)
        def save():
            r=svc.reader(s,id);old=r.user_id
            if body.user_id:
                u=s.get(User,body.user_id)
                if not u or u.deleted or u.role!='reader':svc.fail('Выберите учётную запись с ролью «Читатель»',422)
                if s.scalar(select(Reader.id).where(Reader.user_id==u.id,Reader.id!=id)):svc.fail('Учётная запись уже связана с другим читателем')
            r.user_id=body.user_id;r.version+=1;svc.audit(s,'reader',id,'account_link',user,{'user_id':old},{'user_id':r.user_id});return {'ok':True}
        return svc.operation(s,user,'account:'+str(id),body,save)
    @router.get('/mine/notices')
    def own_notices(s=Depends(db),user=Depends(auth)):
        return [svc.snapshot(n) for n in s.scalars(select(CirculationNotice).where(CirculationNotice.reader_id.in_(select(Reader.id).where(Reader.user_id==user.id))).order_by(CirculationNotice.id.desc()).limit(50))]
    @router.get('/options')
    def options(s=Depends(db)):
        return {'policy':svc.policy(s).model_dump(mode='json'),'branches':[svc.snapshot(b) for b in s.scalars(select(Branch).where(Branch.active.is_(True)))],'timezone':'Asia/Almaty'}
    @router.get('/dashboard')
    def dashboard(s=Depends(db)):
        a,b=local_bounds(svc.today())
        return {'open':s.scalar(select(func.count()).select_from(Loan).where(Loan.closed_at.is_(None))),
         'overdue':s.scalar(select(func.count()).select_from(Loan).where(Loan.closed_at.is_(None),Loan.due_at<svc.utcnow())),
         'issued_week':s.scalar(select(func.count()).select_from(Loan).where(Loan.issued_at>=local_bounds(svc.today()-timedelta(days=6))[0],Loan.issued_at<b)),
         'issued_today':s.scalar(select(func.count()).select_from(Loan).where(Loan.issued_at>=a,Loan.issued_at<b)),
         'returned_today':s.scalar(select(func.count()).select_from(Loan).where(Loan.returned_at>=a,Loan.returned_at<b)),'date':svc.today()}
    @router.get('/readers')
    def find_readers(q:str=Query(min_length=1,max_length=150),s=Depends(db),user=Depends(auth)):
        rate_limit(s,user.id,'circulation-lookup',180);value=q.strip();pattern='%'+value.replace('%','\\%').replace('_','\\_')+'%'
        fields=[Reader.full_name,Reader.ticket_number,Reader.barcode,Reader.email]
        if has(user,'readers.personal_data.view'):fields.append(Reader.iin)
        found=list(s.scalars(select(Reader).where(or_(*(f.ilike(pattern,escape='\\') for f in fields))).order_by(Reader.full_name,Reader.id).limit(21)))
        return {'items':[{k:getattr(r,k) for k in ('id','full_name','ticket_number','barcode','category','study_group','department','status')} for r in found[:20]],'truncated':len(found)>20}
    @router.get('/readers/{id}')
    def reader_summary(id:int,s=Depends(db)):
        r=s.get(Reader,id)
        if not r:svc.fail('Читатель не найден',404)
        return svc.summary(s,r)
    @router.post('/readers/{id}/limits')
    def limits(id:int,body:ReaderLimits,s=Depends(db),user=Depends(auth)):
        def save():
            r=svc.reader(s,id);before=dict(r.limits_override);r.limits_override={} if body.max_loans is None else {'max_active_loans':body.max_loans};r.version+=1
            svc.audit(s,'reader',id,'limits',user,before,r.limits_override,body.reason);return {'ok':True}
        return svc.operation(s,user,'limits:'+str(id),body,save)
    @router.get('/copies')
    def find_copies(q:str=Query(default='',max_length=150),record_id:int|None=None,offset:int=Query(0,ge=0),s=Depends(db),user=Depends(auth)):
        rate_limit(s,user.id,'circulation-lookup',180)
        if record_id:
            stmt=svc.record_copies(s,record_id);total=s.scalar(select(func.count()).select_from(stmt.subquery()))
            return {'kind':'copies','total':total,'items':[svc.copy_output(s,c) for c in s.scalars(stmt.order_by(Copy.id).offset(offset).limit(50))]}
        if not q.strip():svc.fail('Введите код экземпляра или ISBN',422)
        from .isbn_lookup import normalize
        try:isbn=normalize(q)
        except ValueError:isbn=None
        matches=list(s.scalars(select(Copy).where(or_(Copy.barcode==q.strip(),Copy.inventory_number==q.strip())).order_by(Copy.id).limit(20)))
        if matches and not isbn:return {'kind':'copies','items':[svc.copy_output(s,c) for c in matches],'total':len(matches)}
        normalized=isbn or ''.join(ch for ch in q.upper() if ch.isdigit() or ch=='X')
        if len(normalized) not in (10,13):return {'kind':'copies','items':[],'total':0}
        # ISBN locates editions only; never pick an arbitrary physical copy.
        records=[]
        for r in s.scalars(select(Record).order_by(Record.id).execution_options(yield_per=500)):
            values=[sf.get('value','') for f in r.marc.get('fields',[]) if f.get('tag')=='020' for sf in f.get('subfields',[]) if sf.get('code')=='a']
            canonical=[]
            for value in values:
                try:canonical.append(normalize(value.split('(')[0].strip()))
                except ValueError:canonical.append(''.join(ch for ch in value.split('(')[0].upper() if ch.isdigit() or ch=='X'))
            if normalized in canonical:
                records.append({'id':r.id,'title':svc.text_field(r,'245','a')})
                if len(records)>=50:break
        return {'kind':'editions','items':records,'message':'ISBN относится к изданию. Выберите конкретный экземпляр.'}
    @router.post('/issue')
    def issue(body:IssueInput,s=Depends(db),user=Depends(auth)):return svc.operation(s,user,'issue',body,lambda:svc.issue(s,user,body))
    @router.post('/loans/{id}/return')
    def return_book(id:int,body:ReturnInput,s=Depends(db),user=Depends(auth)):return svc.operation(s,user,'return:'+str(id),body,lambda:svc.return_loan(s,user,id,body))
    @router.post('/loans/{id}/renew')
    def renew(id:int,body:RenewInput,s=Depends(db),user=Depends(auth)):return svc.operation(s,user,'renew:'+str(id),body,lambda:svc.renew(s,user,id,body))
    @router.post('/mine/{id}/renew')
    def renew_own(id:int,body:RenewInput,s=Depends(db),user=Depends(auth)):return svc.operation(s,user,'own-renew:'+str(id),body,lambda:svc.renew(s,user,id,body,True))
    @router.get('/loans')
    @router.get('/mine')
    def history(q:str='',status:str='',reader_id:int|None=None,branch_id:int|None=None,from_on:date|None=None,to_on:date|None=None,offset:int=Query(0,ge=0),s=Depends(db),user=Depends(auth),request:Request=None):
        mine=request.url.path.endswith('/mine');stmt=select(Loan).join(Reader,Reader.id==Loan.reader_id).join(Copy,Copy.id==Loan.copy_id)
        if mine:stmt=stmt.where(Reader.user_id==user.id)
        elif not has(user,'circulation.view_any_history'):
            require(user,'circulation.view_own_history');stmt=stmt.where(Loan.issued_by==user.id)
        if reader_id:stmt=stmt.where(Loan.reader_id==reader_id)
        if branch_id:stmt=stmt.where(Loan.branch_id==branch_id)
        if status=='overdue':stmt=stmt.where(Loan.closed_at.is_(None),Loan.due_at<svc.utcnow())
        elif status=='active':stmt=stmt.where(Loan.closed_at.is_(None),Loan.due_at>=svc.utcnow())
        elif status:stmt=stmt.where(Loan.status==status)
        if from_on:stmt=stmt.where(Loan.issued_at>=local_bounds(from_on)[0])
        if to_on:stmt=stmt.where(Loan.issued_at<local_bounds(to_on)[1])
        if q:stmt=stmt.where(or_(Reader.full_name.ilike('%'+q+'%'),Reader.ticket_number==q,Copy.inventory_number==q,Copy.barcode==q))
        total=s.scalar(select(func.count()).select_from(stmt.subquery()))
        return {'total':total,'items':[svc.loan_output(s,l) for l in s.scalars(stmt.order_by(Loan.id.desc()).offset(offset).limit(50))]}
    @router.get('/loans/{id}')
    def loan_detail(id:int,s=Depends(db),user=Depends(auth)):
        l=s.get(Loan,id)
        if not l:svc.fail('Выдача не найдена',404)
        if not any(has(user,p) for p in ('circulation.issue','circulation.return','circulation.renew','circulation.view_any_history')) and l.issued_by!=user.id:svc.fail('История другого сотрудника недоступна',403)
        result=svc.loan_output(s,l);result['events']=[svc.snapshot(e) for e in s.scalars(select(LoanEvent).where(LoanEvent.loan_id==id).order_by(LoanEvent.id))]
        result['incidents']=[svc.snapshot(c) for c in s.scalars(select(Incident).where(Incident.loan_id==id))];return result
    @router.get('/reservations')
    def reservations(offset:int=Query(0,ge=0),status:str='',s=Depends(db)):
        stmt=select(Reservation)
        if status:stmt=stmt.where(Reservation.status==status)
        total=s.scalar(select(func.count()).select_from(stmt.subquery()));items=[]
        for r in s.scalars(stmt.order_by(Reservation.id.desc()).offset(offset).limit(50)):
            items.append({**svc.snapshot(r),'reader_name':s.get(Reader,r.reader_id).full_name,'title':svc.text_field(s.get(Record,r.record_id),'245','a')})
        return {'items':items,'total':total}
    @router.post('/reservations')
    def reserve(body:ReserveInput,s=Depends(db),user=Depends(auth)):return svc.operation(s,user,'reserve',body,lambda:svc.reserve(s,user,body))
    @router.post('/reservations/{id}')
    def reserve_action(id:int,body:ReservationAction,s=Depends(db),user=Depends(auth)):return svc.operation(s,user,'reservation:'+str(id),body,lambda:svc.reservation_action(s,user,id,body))
    @router.get('/fines')
    def fines(status:str='pending',offset:int=Query(0,ge=0),s=Depends(db)):
        stmt=select(Fine)
        if status:stmt=stmt.where(Fine.status==status)
        return {'total':s.scalar(select(func.count()).select_from(stmt.subquery())),'items':[{**svc.snapshot(f),'reader_name':s.get(Reader,f.reader_id).full_name,'title':svc.title(s,s.get(Copy,f.copy_id))} for f in s.scalars(stmt.order_by(Fine.id.desc()).offset(offset).limit(50))]}
    @router.post('/fines/{id}')
    def fine_action(id:int,body:FineAction,s=Depends(db),user=Depends(auth)):
        if body.action=='waived':require(user,'fines.waive')
        def save():
            f=s.get(Fine,id)
            if not f:svc.fail('Штраф не найден',404)
            svc.reader(s,f.reader_id)
            if f.status!='pending':svc.fail('Штраф уже разрешён')
            svc.valid_reason(body.reason);before=svc.snapshot(f);f.status=body.action;f.resolved_at=svc.utcnow();f.resolved_by=user.id;f.notes=body.reason
            svc.audit(s,'fine',id,body.action,user,before,svc.snapshot(f),body.reason);return svc.snapshot(f)
        return svc.operation(s,user,'fine:'+str(id),body,save)
    @router.get('/incidents')
    def incidents(status:str='open',offset:int=Query(0,ge=0),s=Depends(db)):
        stmt=select(Incident)
        if status:stmt=stmt.where(Incident.status==status)
        return {'total':s.scalar(select(func.count()).select_from(stmt.subquery())),'items':[{**svc.snapshot(c),'reader_name':s.get(Reader,c.reader_id).full_name,'title':svc.title(s,s.get(Copy,c.copy_id))} for c in s.scalars(stmt.order_by(Incident.id.desc()).offset(offset).limit(50))]}
    @router.post('/incidents/{id}')
    def incident_action(id:int,body:IncidentAction,s=Depends(db),user=Depends(auth)):return svc.operation(s,user,'incident:'+str(id),body,lambda:svc.resolve_incident(s,user,id,body))
    @router.post('/copies/{id}')
    def copy_settings(id:int,body:CopySettings,s=Depends(db),user=Depends(auth)):
        def save():
            c=svc.copy(s,id);d=svc.detail(s,c,True)
            if d.version!=body.version:svc.fail('Экземпляр уже изменён')
            if svc.active_loan(s,id) or svc.active_reservation(s,id):svc.fail('Сначала завершите выдачу или бронь')
            if d.operation_state=='lost' or s.scalar(select(Incident.id).where(Incident.copy_id==id,Incident.status=='open')):svc.fail('Сначала разрешите инцидент')
            if body.branch_id and not s.scalar(select(Branch.id).where(Branch.id==body.branch_id,Branch.active.is_(True))):svc.fail('Пункт обслуживания недоступен',422)
            if body.condition in ('severe','irreparable') and body.operation_state=='normal':svc.fail('Непригодной книге нужен ремонт или обработка',422)
            before=svc.snapshot(d)
            for k in ('branch_id','condition','operation_state','access','defects'):setattr(d,k,getattr(body,k))
            svc.copy_history(s,c,d,before,'settings',user,reason=body.reason);s.flush();svc.queue(s,svc.record_id(s,c),user);return svc.copy_output(s,c)
        return svc.operation(s,user,'copy:'+str(id),body,save)
    @router.get('/settings')
    def settings(s=Depends(db)):
        row=s.get(CirculationSettings,1);return {'version':row.version if row else 0,'policy':svc.policy(s).model_dump(mode='json')}
    @router.post('/settings')
    def save_settings(body:SettingsInput,s=Depends(db),user=Depends(auth)):
        def save():
            row=s.get(CirculationSettings,1)
            if body.version!=(row.version if row else 0):svc.fail('Настройки уже изменены')
            before=row.value if row else {}
            if not row:row=CirculationSettings(id=1,value={},version=0);s.add(row)
            row.value=body.policy.model_dump(mode='json');row.version+=1;svc.audit(s,'settings',1,'update',user,before,row.value);return {'version':row.version,'policy':row.value}
        return svc.operation(s,user,'settings',body,save)
    @router.get('/audit')
    def audit(entity:str,entity_id:int,s=Depends(db)):
        return [svc.snapshot(a) for a in s.scalars(select(CirculationAudit).where(CirculationAudit.entity==entity,CirculationAudit.entity_id==entity_id).order_by(CirculationAudit.id))]
    @router.get('/notices')
    def notices(s=Depends(db)):
        return [svc.snapshot(n) for n in s.scalars(select(CirculationNotice).order_by(CirculationNotice.id.desc()).limit(100))]
    return router
