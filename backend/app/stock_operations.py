"""Audited stock movements; all mutation paths lock receipt before its copies."""
from datetime import date, datetime
from zoneinfo import ZoneInfo
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from pydantic import Field, field_validator, model_validator
from sqlalchemy import select, func
from .db import Acquisition, AcquisitionLine, AcquisitionHistory, Copy, CopyHistory, Withdrawal, Record
from .acquisitions import Strict, LineInput, digest, lock_request, receipt_output, copy_output

class Operation(Strict):
    request_key: UUID
    version: int=Field(ge=1)
    reason: str=Field(min_length=1,max_length=4000)

class CorrectLine(LineInput):
    id: int|None=Field(default=None,gt=0)
    quantity: int=Field(ge=0,le=10000,strict=True)
    cancel_copy_ids: list[int]=Field(default_factory=list,max_length=10000)

class Correction(Operation):
    document_on: date|None=None
    invoice: str=Field(default='',max_length=255)
    received_on: date
    source: str=Field(min_length=1,max_length=255)
    note: str=Field(default='',max_length=4000)
    lines: list[CorrectLine]=Field(min_length=1,max_length=100)
    @model_validator(mode='after')
    def bounded(self):
        if not 1<=sum(l.quantity for l in self.lines)<=10000: raise ValueError('В поступлении должно быть от 1 до 10000 экземпляров. Для полной отмены используйте удаление поступления.')
        return self

class WithdrawInput(Operation):
    copy_id: int=Field(gt=0)
    withdrawn_on: date
    act_number: str=Field(min_length=1,max_length=255)
    note: str=Field(default='',max_length=4000)
    @field_validator('withdrawn_on')
    @classmethod
    def past_date(cls,v):
        if v>datetime.now(ZoneInfo('Asia/Almaty')).date(): raise ValueError('Дата списания не может быть в будущем')
        return v

def title(r):
    return ' '.join(sf['value'] for f in r.marc['fields'] if f['tag']=='245' for sf in f.get('subfields',[]) if sf['code'] in ('a','b')) or 'Без заглавия'

def full_copy(s,c):
    line=s.get(AcquisitionLine,c.line_id) if c.line_id else None
    receipt=s.get(Acquisition,line.acquisition_id) if line else None
    result=copy_output(c,line,receipt)
    result['title']=title(s.get(Record,result['record_id']))
    return result

def change_status(s,c,status,reason):
    from .circulation_service import active_loan,active_reservation
    if active_loan(s,c.id) or active_reservation(s,c.id):raise HTTPException(409,'Экземпляр выдан или закреплён бронью. Сначала завершите операцию книговыдачи.')
    before={'status':c.status,'version':c.version}
    c.status=status;c.version+=1
    s.add(CopyHistory(copy_id=c.id,before=before,after={'status':status,'version':c.version,'reason':reason}))

def receipt_copies(s,id,lock=False):
    stmt=select(Copy).where(Copy.line_id.in_(select(AcquisitionLine.id).where(AcquisitionLine.acquisition_id==id))).order_by(Copy.id)
    return list(s.scalars(stmt.with_for_update() if lock else stmt))

def receipt_snapshot(s,r):
    return jsonable_encoder({**receipt_output(s,r),'copies':[{'id':c.id,'inventory_number':c.inventory_number,'status':c.status,'version':c.version} for c in receipt_copies(s,r.id)]})

def prepare(s,id,body,action):
    payload=body.model_dump(mode='json')
    if payload.get('document_on') is None:payload.pop('document_on',None)
    hashed=digest({'id':id,'action':action,**payload});key=str(body.request_key)
    lock_request(s,'receipt-change:',key)
    old=s.scalar(select(AcquisitionHistory).where(AcquisitionHistory.request_key==key))
    if old:
        if old.payload_hash!=hashed: raise HTTPException(409,'Ключ операции уже использован с другими данными')
        return None,old.after,hashed
    r=s.scalar(select(Acquisition).where(Acquisition.id==id).with_for_update())
    if r is None: raise HTTPException(404,'Поступление не найдено')
    if r.version!=body.version: raise HTTPException(409,'Поступление изменено. Закройте форму и откройте актуальную версию.')
    if r.status!='posted': raise HTTPException(409,'Отменённое поступление нельзя изменять')
    copies=receipt_copies(s,id,True)
    if any(c.status=='withdrawn' for c in copies): raise HTTPException(409,'В поступлении уже есть списанные экземпляры. Его исправление или отмена заблокированы для сохранения истории списания.')
    return r,None,hashed

def audit(s,r,body,action,hashed,before):
    r.version+=1;s.flush();after=receipt_snapshot(s,r)
    s.add(AcquisitionHistory(acquisition_id=r.id,request_key=str(body.request_key),payload_hash=hashed,action=action,reason=body.reason,before=before,after=after))
    s.commit();return after

def make_router(auth,db):
    router=APIRouter(prefix='/api',dependencies=[Depends(auth)])
    @router.get('/acquisitions/{id}')
    def detail(id:int,s=Depends(db)):
        r=s.get(Acquisition,id)
        if not r: raise HTTPException(404,'Поступление не найдено')
        return {**receipt_output(s,r),'copies':[copy_output(c,s.get(AcquisitionLine,c.line_id),r) for c in receipt_copies(s,id)]}

    @router.get('/acquisitions/{id}/history')
    def history(id:int,s=Depends(db)):
        return [{'id':h.id,'action':h.action,'reason':h.reason,'created_at':h.created_at,'before':h.before,'after':h.after} for h in s.scalars(select(AcquisitionHistory).where(AcquisitionHistory.acquisition_id==id).order_by(AcquisitionHistory.id))]

    @router.put('/acquisitions/{id}')
    def correct(id:int,body:Correction,s=Depends(db)):
        r,repeated,hashed=prepare(s,id,body,'correct')
        if repeated is not None: return repeated
        before=receipt_snapshot(s,r)
        old={l.id:l for l in s.scalars(select(AcquisitionLine).where(AcquisitionLine.acquisition_id==id))}
        given=[l.id for l in body.lines if l.id is not None]
        if len(set(given))!=len(given) or set(given)!=set(old): raise HTTPException(422,'Передайте все существующие строки поступления; для удаления строки задайте количество 0')
        ids=sorted({l.record_id for l in body.lines})
        records={v.id:v for v in s.scalars(select(Record).where(Record.id.in_(ids)).order_by(Record.id).with_for_update())}
        if set(records)!=set(ids): raise HTTPException(422,'Одна из записей каталога не найдена')
        for entry in body.lines:
            if entry.id:
                line=old[entry.id]
                if line.record_id!=entry.record_id: raise HTTPException(422,'Нельзя подменить книгу в существующей строке: обнулите её и добавьте новую')
                active={c.id:c for c in s.scalars(select(Copy).where(Copy.line_id==line.id,Copy.status=='active'))}
                removed=entry.cancel_copy_ids
                if len(set(removed))!=len(removed) or not set(removed)<=set(active) or len(removed)!=max(0,line.quantity-entry.quantity):
                    raise HTTPException(422,'При уменьшении количества выберите ровно столько действующих экземпляров для отмены')
                for cid in removed: change_status(s,active[cid],'cancelled',body.reason)
                increase=max(0,entry.quantity-line.quantity)
                for k,v in entry.model_dump(exclude={'id','cancel_copy_ids','record_id'}).items(): setattr(line,k,v)
            else:
                if entry.quantity<1 or entry.cancel_copy_ids: raise HTTPException(422,'Новая строка должна содержать экземпляры без отмен')
                line=AcquisitionLine(acquisition_id=id,title_snapshot=title(records[entry.record_id]),**entry.model_dump(exclude={'id','cancel_copy_ids'}))
                s.add(line);s.flush();increase=entry.quantity
            for _ in range(increase):
                token=uuid4().hex;s.add(Copy(line_id=line.id,inventory_number='INV-'+token,barcode='BC-'+token,sigla=line.sigla,note=line.note))
        for k in ['invoice','received_on','source','note']: setattr(r,k,getattr(body,k))
        if 'document_on' in body.model_fields_set:r.document_on=body.document_on
        return audit(s,r,body,'correct',hashed,before)

    @router.post('/acquisitions/{id}/cancel')
    def cancel(id:int,body:Operation,s=Depends(db)):
        r,repeated,hashed=prepare(s,id,body,'cancel')
        if repeated is not None: return repeated
        before=receipt_snapshot(s,r)
        for c in receipt_copies(s,id):
            if c.status=='active': change_status(s,c,'cancelled',body.reason)
        r.status='cancelled'
        return audit(s,r,body,'cancel',hashed,before)

    @router.get('/copies/lookup')
    def lookup(inventory_number:str=Query(min_length=1,max_length=100),s=Depends(db)):
        c=s.scalar(select(Copy).where(Copy.inventory_number==inventory_number.strip()))
        if not c: raise HTTPException(404,'Экземпляр с таким инвентарным номером не найден')
        return full_copy(s,c)

    @router.post('/withdrawals',status_code=201)
    def withdraw(body:WithdrawInput,s=Depends(db)):
        key=str(body.request_key);hashed=digest(body.model_dump(mode='json'));lock_request(s,'withdrawal:',key)
        old=s.scalar(select(Withdrawal).where(Withdrawal.request_key==key))
        if old:
            if old.payload_hash!=hashed: raise HTTPException(409,'Ключ списания уже использован с другими данными')
            return withdrawal_output(old)
        c=s.get(Copy,body.copy_id)
        if c is None: raise HTTPException(404,'Экземпляр не найден')
        if c.line_id:
            line=s.get(AcquisitionLine,c.line_id)
            s.scalar(select(Acquisition).where(Acquisition.id==line.acquisition_id).with_for_update())
        s.expire_all()
        c=s.scalar(select(Copy).where(Copy.id==body.copy_id).with_for_update().execution_options(populate_existing=True))
        if c.status!='active' or c.version!=body.version: raise HTTPException(409,'Экземпляр уже списан, отменён или изменён. Найдите его заново.')
        snapshot=full_copy(s,c)
        if snapshot['received_on'] and body.withdrawn_on<snapshot['received_on']: raise HTTPException(422,'Списание не может быть раньше даты поступления')
        change_status(s,c,'withdrawn',body.reason)
        w=Withdrawal(copy_id=c.id,request_key=key,payload_hash=hashed,withdrawn_on=body.withdrawn_on,act_number=body.act_number,reason=body.reason,note=body.note,snapshot=jsonable_encoder(snapshot))
        s.add(w);s.commit();return withdrawal_output(w)

    @router.get('/withdrawals')
    def withdrawals(offset:int=Query(0,ge=0),limit:int=Query(20,ge=1,le=100),s=Depends(db)):
        return {'total':s.scalar(select(func.count()).select_from(Withdrawal)),
                'items':[withdrawal_output(w) for w in s.scalars(select(Withdrawal).order_by(Withdrawal.id.desc()).offset(offset).limit(limit))]}
    return router

def withdrawal_output(w):
    return {'id':w.id,'copy_id':w.copy_id,'withdrawn_on':w.withdrawn_on,'act_number':w.act_number,'reason':w.reason,'note':w.note,'created_at':w.created_at,'snapshot':w.snapshot}
