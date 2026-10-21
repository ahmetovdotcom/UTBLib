"""Import only the INV population explicitly approved by the library; no source connection."""
from decimal import Decimal,InvalidOperation
from uuid import uuid5,NAMESPACE_URL
import hashlib
import re
from fastapi import APIRouter,Depends,HTTPException
from pydantic import Field,ConfigDict
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from .db import Copy,MarcsqlCopySource,MarcsqlSource,Record
from .acquisitions import Strict,digest,lock_request,money

class CopyBatch(Strict):
    source: str=Field(min_length=1,max_length=200)
    rows: list[dict]=Field(min_length=1,max_length=100)
    preview: bool=True

def text_value(row,key):
    v=row.get(key)
    if v is None:return ''
    if not isinstance(v,str):raise ValueError(f'{key}: ожидалось текстовое значение')
    return v.strip()

def integer(row,key):
    v=row.get(key)
    if type(v) is not int:raise ValueError(f'{key}: ожидалось целое число')
    return v

def prepare_row(source,row):
    inv_id=integer(row,'INV_ID');doc_id=integer(row,'DOC_ID')
    for key in ['INVMODE','STATE','CNT','OFFDATE','T090e','T876p','T876c','SIGLA_ID']:
        if key not in row:raise ValueError(f'Не передано поле {key}')
    approved=(text_value(row,'INVMODE')=='I' and row['STATE']==1 and row['CNT']==1 and row['OFFDATE'] in (None,0,0.0))
    if not approved:return {'inv_id':inv_id,'doc_id':doc_id,'status':'skipped','reason':'Вне согласованной группы INVMODE=I, STATE=1, CNT=1, без OFFDATE','raw':row}
    inventory=text_value(row,'T090e')
    if not inventory:raise ValueError('Пустой инвентарный номер: экземпляр не создан')
    barcode=text_value(row,'T876p');generated=not barcode
    if generated:barcode=f"MARC-NOBARCODE-{hashlib.sha256(source.encode()).hexdigest()[:12]}-{inv_id}"
    for key,value,limit in [('Инвентарный номер',inventory,100),('Штрихкод',barcode,100)]:
        if len(value)>limit:raise ValueError(f'{key}: более {limit} символов')
    value=text_value(row,'T876c');price=None
    if value:
        normalized=re.sub(r'\s+','',value).replace(',','.')
        if not re.fullmatch(r'\d+(?:\.\d{1,2})?',normalized):raise ValueError('Цена T876c имеет неизвестный формат')
        price=Decimal(normalized)
        if price>Decimal('999999999999.99'):raise ValueError('Цена превышает допустимый диапазон')
    sigla=text_value(row,'T090f') or text_value(row,'_SIGLA_SHORTNAME')
    source_name=text_value(row,'SOURCE');note=text_value(row,'NOTES')
    if len(sigla)>255 or len(source_name)>255:raise ValueError('Сигла или источник длиннее 255 символов')
    return {'inv_id':inv_id,'doc_id':doc_id,'inventory_number':inventory,'barcode':barcode,
        'barcode_generated':generated,'sigla':sigla,'unit_price':money(price),'source':source_name,'note':note,'currency':'KZT'}

def import_row(s,source,row,preview):
    parsed=prepare_row(source,row)
    if parsed.get('status')=='skipped':return parsed
    inv_id=parsed['inv_id'];doc_id=parsed['doc_id'];checksum=digest(row)
    lock_request(s,'marcsql-inventory:',source+':'+str(inv_id))
    old=s.scalar(select(MarcsqlCopySource).where(MarcsqlCopySource.source==source,MarcsqlCopySource.inv_id==inv_id))
    if old:
        if old.checksum!=checksum:raise ValueError('Исходная строка INV изменилась: существующий экземпляр не перезаписан')
        if old.copy_id is None:raise ValueError('Импортированный экземпляр был удалён: автоматическое восстановление запрещено')
        return {'inv_id':inv_id,'doc_id':doc_id,'copy_id':old.copy_id,'status':'unchanged'}
    origin=s.scalar(select(MarcsqlSource).where(MarcsqlSource.source==source,MarcsqlSource.doc_id==doc_id))
    if origin is None or origin.record_id is None:raise ValueError('Книга для DOC_ID не импортирована или удалена; сначала импортируйте каталог')
    record=s.scalar(select(Record).where(Record.id==origin.record_id).with_for_update())
    if record is None:raise ValueError('Библиографическая запись не найдена')
    existing=s.scalar(select(Copy.id).where((Copy.inventory_number==parsed['inventory_number'])|(Copy.barcode==parsed['barcode'])).limit(1))
    if existing is not None:raise ValueError(f'Номер или штрихкод занят экземпляром №{existing}; перезапись запрещена')
    result={**parsed,'record_id':record.id,'status':'preview' if preview else 'created',
        'warnings':['Даты REGDATE/DATE1/OFFDATE сохранены в оригинале без преобразования; валюта цены принята KZT']}
    if parsed['barcode_generated']:result['warnings'].append('Штрихкод источника пуст; назначен явно служебный идентификатор MARC-NOBARCODE')
    if preview:return result
    c=Copy(record_id=record.id,request_key=str(uuid5(NAMESPACE_URL,'marcsql-inventory:'+source+':'+str(inv_id))),payload_hash=checksum,
        inventory_number=parsed['inventory_number'],barcode=parsed['barcode'],sigla=parsed['sigla'],unit_price=parsed['unit_price'],
        currency='KZT',source=parsed['source'],note=parsed['note'],received_on=None,checked_on=None,status='active')
    s.add(c);s.flush();s.add(MarcsqlCopySource(source=source,inv_id=inv_id,doc_id=doc_id,copy_id=c.id,raw=row,checksum=checksum));s.flush()
    return {**result,'copy_id':c.id}

def make_router(auth,db):
    router=APIRouter(prefix='/api',dependencies=[Depends(auth)])
    @router.post('/import/marcsql-copies')
    def batch(body:CopyBatch,s=Depends(db)):
        results=[]
        for row in body.rows:
            try:
                with s.begin_nested(): result=import_row(s,body.source,row,body.preview)
                results.append(result)
            except (ValueError,IntegrityError) as exc:
                message='Конфликт номера или штрихкода; ничего не перезаписано' if isinstance(exc,IntegrityError) else str(exc)
                results.append({'inv_id':row.get('INV_ID'),'doc_id':row.get('DOC_ID'),'status':'error','error':message})
        if body.preview:s.rollback()
        else:s.commit()
        return {'results':results}
    @router.get('/copies/{id}/marcsql-source')
    def original(id:int,s=Depends(db)):
        row=s.scalar(select(MarcsqlCopySource).where(MarcsqlCopySource.copy_id==id))
        if row is None:raise HTTPException(404,'Исходная строка MARCSQL не найдена')
        return {'source':row.source,'inv_id':row.inv_id,'doc_id':row.doc_id,'raw':row.raw,'checksum':row.checksum}
    return router
