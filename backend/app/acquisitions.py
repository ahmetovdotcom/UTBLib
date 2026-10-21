"""Acquisitions are posted once and immutable; copy metadata has a separate audit trail."""
import hashlib
import json
import re
from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select, func, update, text
from sqlalchemy.exc import IntegrityError
from .db import Acquisition, AcquisitionLine, Copy, CopyHistory, Record

class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)

class InitialAcquisition(Strict):
    received_on: date
    currency: str=Field(default='KZT',pattern=r'^[A-Z]{3}$')
    note: str=Field(default='',max_length=4000)

class LineInput(Strict):
    record_id: int=Field(gt=0)
    quantity: int=Field(gt=0,le=10000,strict=True)
    unit_price: Decimal|None=Field(default=None,ge=0,max_digits=14,decimal_places=2)
    currency: str=Field(default='KZT',pattern=r'^[A-Z]{3}$')
    sigla: str=Field(default='',max_length=255)
    note: str=Field(default='',max_length=4000)

class AcquisitionInput(Strict):
    document_on: date|None=None
    request_key: UUID
    invoice: str=Field(default='',max_length=255)
    received_on: date
    source: str=Field(min_length=1,max_length=255)
    note: str=Field(default='',max_length=4000)
    lines: list[LineInput]=Field(min_length=1,max_length=100)
    @model_validator(mode='after')
    def bounded(self):
        if sum(l.quantity for l in self.lines)>10000: raise ValueError('Не более 10 000 экземпляров за одно поступление')
        return self

class CopyInput(Strict):
    version: int=Field(ge=1)
    inventory_number: str=Field(min_length=1,max_length=100)
    barcode: str=Field(min_length=1,max_length=100)
    sigla: str=Field(default='',max_length=255)
    checked_on: date|None=None
    note: str=Field(default='',max_length=4000)
    @field_validator('checked_on')
    @classmethod
    def past_check(cls,v):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        if v and v>datetime.now(ZoneInfo('Asia/Almaty')).date(): raise ValueError('Дата проверки не может быть в будущем')
        return v


class ExistingCopyInput(Strict):
    request_key: UUID
    inventory_number: str=Field(default='',max_length=100)
    barcode: str=Field(default='',max_length=100)
    sigla: str=Field(default='',max_length=255)
    unit_price: Decimal|None=Field(default=None,ge=0,max_digits=14,decimal_places=2)
    currency: str=Field(default='KZT',pattern=r'^[A-Z]{3}$')
    received_on: date|None=None
    source: str=Field(default='',max_length=255)
    checked_on: date|None=None
    note: str=Field(default='',max_length=4000)
    @field_validator('checked_on')
    @classmethod
    def past_check(cls,v): return CopyInput.past_check(v)


def digest(body):
    return hashlib.sha256(json.dumps(body,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()

def lock_request(s,namespace,key):
    # Transaction-scoped lock makes simultaneous network retries wait for the first commit.
    if s.bind.dialect.name=='postgresql':
        number=int.from_bytes(hashlib.sha256((namespace+str(key)).encode()).digest()[:8],signed=True)
        s.execute(text('SELECT pg_advisory_xact_lock(:key)'),{'key':number})

def single(marc,tag,code):
    values=[sf['value'].strip() for f in marc['fields'] if f['tag']==tag for sf in f.get('subfields',[]) if sf['code']==code and sf['value'].strip()]
    if len(values)>1: raise HTTPException(422,f'{tag}${code}: для первого поступления укажите одно значение')
    return values[0] if values else ''

def initial_body(marc,record_id,key,settings):
    qty=single(marc,'541','n')
    if not qty:
        if settings: raise HTTPException(422,'Укажите количество поступивших экземпляров в 541$n')
        return None
    if not re.fullmatch(r'[1-9][0-9]*',qty) or int(qty)>10000:
        raise HTTPException(422,'Количество поступивших экземпляров: целое число от 1 до 10 000, без «экз»')
    if not key or not settings: raise HTTPException(422,'Заполните дату первого поступления и ключ операции')
    price=single(marc,'541','h')
    parsed=None
    if price:
        value=re.sub(r'\s+','',price).replace(',','.')
        suffix='₸' if settings.currency=='KZT' else ''
        if suffix: value=value.removesuffix(suffix)
        value=value.removesuffix(settings.currency)
        if not re.fullmatch(r'\d+(?:\.\d{1,2})?',value):
            raise HTTPException(422,'Цена приобретения: укажите сумму с двумя знаками после запятой и выбранной валютой')
        parsed=Decimal(value)
    from pydantic import ValidationError
    try:
        return AcquisitionInput(request_key=key,invoice=single(marc,'990','c'),source=single(marc,'990','w'),
            received_on=settings.received_on,note=settings.note,lines=[LineInput(record_id=record_id,quantity=int(qty),
                unit_price=parsed,currency=settings.currency,sigla=single(marc,'090','f'))])
    except ValidationError:
        raise HTTPException(422,'Проверьте первое поступление: источник (990$w) обязателен, цена должна быть неотрицательной и не превышать 999999999999.99')

def register(s,body):
    payload=body.model_dump(mode='json')
    if payload.get('document_on') is None:payload.pop('document_on',None)
    key=str(body.request_key); hashed=digest(payload)
    lock_request(s,'acquisition:',key)
    old=s.scalar(select(Acquisition).where(Acquisition.request_key==key))
    if old:
        if old.payload_hash!=hashed: raise HTTPException(409,'Эта операция уже выполнена с другими данными. Откройте сохранённое поступление.')
        return old
    # Hold record locks until posting completes; a concurrent catalogue delete must not win.
    ids=sorted({line.record_id for line in body.lines})
    records={r.id:r for r in s.scalars(select(Record).where(Record.id.in_(ids)).order_by(Record.id).with_for_update())}
    if set(records)!=set(ids): raise HTTPException(422,'Одна из библиографических записей не найдена')
    receipt=Acquisition(request_key=key,payload_hash=hashed,invoice=body.invoice,source=body.source,
                        received_on=body.received_on,document_on=body.document_on,note=body.note)
    s.add(receipt);s.flush()
    for entry in body.lines:
        r=records[entry.record_id]
        title=' '.join(sf['value'] for f in r.marc['fields'] if f['tag']=='245' for sf in f.get('subfields',[]) if sf['code'] in ('a','b')) or 'Без заглавия'
        line=AcquisitionLine(acquisition_id=receipt.id,title_snapshot=title,**entry.model_dump())
        s.add(line);s.flush()
        for _ in range(entry.quantity):
            token=uuid4().hex
            s.add(Copy(line_id=line.id,inventory_number='INV-'+token,barcode='BC-'+token,sigla=line.sigla,note=line.note))
    s.flush()
    from .ksu_auto import ensure_entry
    ensure_entry(s,receipt)
    return receipt

def money(value): return None if value is None else format(value,'.2f')

def receipt_output(s,receipt):
    lines=list(s.scalars(select(AcquisitionLine).where(AcquisitionLine.acquisition_id==receipt.id).order_by(AcquisitionLine.id)))
    totals={};unknown=0
    for line in lines:
        if line.unit_price is None: unknown+=line.quantity
        else: totals[line.currency]=totals.get(line.currency,Decimal(0))+line.unit_price*line.quantity
    return {'id':receipt.id,'status':receipt.status,'version':receipt.version,'invoice':receipt.invoice,'received_on':receipt.received_on,'source':receipt.source,
            'document_on':receipt.document_on,'note':receipt.note,'created_at':receipt.created_at,'quantity':sum(l.quantity for l in lines),
            'totals':{k:money(v) for k,v in totals.items()},'unpriced_count':unknown,
            'lines':[{'id':l.id,'record_id':l.record_id,'title':l.title_snapshot,'quantity':l.quantity,
                      'unit_price':money(l.unit_price),'currency':l.currency,'amount':money(None if l.unit_price is None else l.unit_price*l.quantity),
                      'sigla':l.sigla,'note':l.note} for l in lines]}

def copy_output(c,line=None,receipt=None):
    return {'id':c.id,'status':c.status,'version':c.version,'line_id':c.line_id,'record_id':line.record_id if line else c.record_id,
        'acquisition_id':receipt.id if receipt else None,'origin':'acquisition' if receipt else 'existing_fund',
        'inventory_number':c.inventory_number,'barcode':c.barcode,'sigla':c.sigla,'checked_on':c.checked_on,'note':c.note,
        'unit_price':money(line.unit_price if line else c.unit_price),'currency':line.currency if line else c.currency,
        'received_on':receipt.received_on if receipt else c.received_on,'source':receipt.source if receipt else c.source,
        'invoice':receipt.invoice if receipt else None}

def make_router(auth,db):
    router=APIRouter(prefix='/api',dependencies=[Depends(auth)])
    @router.post('/acquisitions')
    def create(body:AcquisitionInput,s=Depends(db)):
        receipt=register(s,body)
        try: s.commit()
        except IntegrityError:
            s.rollback();raise HTTPException(409,'Конфликт регистрации поступления. Повторите ту же операцию.')
        return receipt_output(s,receipt)

    @router.get('/acquisitions')
    def receipts(record_id:int|None=None,offset:int=Query(0,ge=0),limit:int=Query(20,ge=1,le=100),s=Depends(db)):
        stmt=select(Acquisition)
        if record_id is not None: stmt=stmt.where(Acquisition.id.in_(select(AcquisitionLine.acquisition_id).where(AcquisitionLine.record_id==record_id)))
        return {'total':s.scalar(select(func.count()).select_from(stmt.subquery())),
                'items':[receipt_output(s,r) for r in s.scalars(stmt.order_by(Acquisition.id.desc()).offset(offset).limit(limit))]}

    @router.get('/acquisitions/summary')
    def summary(date_from:date|None=None,date_to:date|None=None,s=Depends(db)):
        if date_from and date_to and date_from>date_to: raise HTTPException(422,'Начальная дата позже конечной')
        stmt=select(AcquisitionLine).join(Acquisition).where(Acquisition.status=='posted',AcquisitionLine.quantity>0)
        if date_from: stmt=stmt.where(Acquisition.received_on>=date_from)
        if date_to: stmt=stmt.where(Acquisition.received_on<=date_to)
        rows=list(s.scalars(stmt));totals={};unknown=0
        for row in rows:
            if row.unit_price is None: unknown+=row.quantity
            else: totals[row.currency]=totals.get(row.currency,Decimal(0))+row.quantity*row.unit_price
        return {'acquisitions':len({r.acquisition_id for r in rows}),'titles':len({r.record_id for r in rows}),
                'quantity':sum(r.quantity for r in rows),'unpriced_count':unknown,'totals':{k:money(v) for k,v in totals.items()}}

    @router.post('/records/{id}/copies',status_code=201)
    def create_existing_copy(id:int,body:ExistingCopyInput,s=Depends(db)):
        key=str(body.request_key);hashed=digest({'record_id':id,**body.model_dump(mode='json')})
        lock_request(s,'existing-copy:',key)
        old=s.scalar(select(Copy).where(Copy.request_key==key))
        if old:
            if old.payload_hash!=hashed: raise HTTPException(409,'Эта операция уже выполнена с другими данными')
            return copy_output(old)
        if s.scalar(select(Record).where(Record.id==id).with_for_update()) is None:
            raise HTTPException(404,'Запись не найдена')
        values=body.model_dump(exclude={'request_key'})
        token=uuid4().hex
        values['inventory_number']=values['inventory_number'] or 'INV-'+token
        values['barcode']=values['barcode'] or 'BC-'+token
        c=Copy(record_id=id,request_key=key,payload_hash=hashed,**values)
        s.add(c)
        try: s.commit()
        except IntegrityError:
            s.rollback();raise HTTPException(409,'Инвентарный номер или штрихкод уже используется')
        return copy_output(c)

    @router.get('/records/{id}/copies')
    def copies(id:int,q:str='',offset:int=Query(0,ge=0),limit:int=Query(50,ge=1,le=100),s=Depends(db)):
        if s.get(Record,id) is None: raise HTTPException(404,'Запись не найдена')
        stmt=select(Copy,AcquisitionLine,Acquisition).outerjoin(AcquisitionLine,Copy.line_id==AcquisitionLine.id).outerjoin(Acquisition,AcquisitionLine.acquisition_id==Acquisition.id).where((AcquisitionLine.record_id==id)|(Copy.record_id==id))
        total=s.scalar(select(func.count()).select_from(stmt.subquery()))
        if q: stmt=stmt.where(Copy.inventory_number.contains(q,autoescape=True)|Copy.barcode.contains(q,autoescape=True))
        count=s.scalar(select(func.count()).select_from(stmt.subquery()))
        active=s.scalar(select(func.count()).select_from(select(Copy.id).where(((Copy.line_id.in_(select(AcquisitionLine.id).where(AcquisitionLine.record_id==id)))|(Copy.record_id==id)),Copy.status=='active').subquery()))
        return {'total':total,'active':active,'matched':count,'items':[copy_output(*row) for row in s.execute(stmt.order_by(Copy.id).offset(offset).limit(limit))]}

    @router.put('/copies/{id}')
    def edit_copy(id:int,body:CopyInput,s=Depends(db)):
        c=s.get(Copy,id)
        if c is None: raise HTTPException(404,'Экземпляр не найден')
        if c.version!=body.version or c.status!='active': raise HTTPException(409,'Экземпляр изменён, списан или отменён. Обновите список.')
        before={k:getattr(c,k) for k in type(body).model_fields};before['checked_on']=str(c.checked_on) if c.checked_on else None
        values=body.model_dump(exclude={'version'});values['version']=body.version+1
        try:
            result=s.execute(update(Copy).where(Copy.id==id,Copy.version==body.version,Copy.status=='active').values(**values))
            if result.rowcount!=1: raise HTTPException(409,'Экземпляр изменён. Обновите список.')
            s.add(CopyHistory(copy_id=id,before=before,after={**body.model_dump(mode='json'),'version':body.version+1}))
            s.commit()
        except IntegrityError:
            s.rollback();raise HTTPException(409,'Инвентарный номер или штрихкод уже используется')
        c=s.get(Copy,id);line=s.get(AcquisitionLine,c.line_id) if c.line_id else None
        return copy_output(c,line,s.get(Acquisition,line.acquisition_id) if line else None)

    @router.get('/copies/{id}/history')
    def history(id:int,s=Depends(db)):
        if s.get(Copy,id) is None: raise HTTPException(404,'Экземпляр не найден')
        return [{'created_at':h.created_at,'before':h.before,'after':h.after} for h in s.scalars(select(CopyHistory).where(CopyHistory.copy_id==id).order_by(CopyHistory.id))]
    return router
