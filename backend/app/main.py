import json, os, secrets
from pathlib import Path
from typing import Annotated
from fastapi import FastAPI, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update, delete, or_
from sqlalchemy.exc import IntegrityError
from .db import Session, DocumentType, Record, VocabularyEntry, MarcsqlSource, RecordCreation, AcquisitionLine, Copy
from .validation import validate_config, validate_marc, search_text
from .worksheet import definitions, default_config
from .vocabulary import add_entry, apply_vocabularies, normalized, backfill_automatic, collect_automatic
from .technical import populate, validate_coded
DATA=json.loads(Path(os.getenv('MARC_PATH','/data/marc21.json')).read_text())
DICTIONARY={f['tag']:f for f in DATA['fields']}
LOCAL_DICTIONARY=definitions(DICTIONARY)
app=FastAPI(title='Каталогизация и классификация',version='0.1.0')
from .security import auth, router as security_router, require
from .db import get_db as db
app.include_router(security_router)
class Strict(BaseModel): model_config=ConfigDict(extra='forbid')
class VocabularyConfig(Strict):
    auto_add: bool=False
    allow_edit: bool=False
class ConfigField(Strict):
    vocabularies: dict[str,VocabularyConfig]=Field(default_factory=dict)
    tag: str=Field(pattern=r'^\d{3}$')
    label: str=''
    local: bool=False
    required: bool=False
    subfields: list[str]=Field(default_factory=list)
class TypeInput(Strict):
    name: str=Field(min_length=1,max_length=120)
    config: list[ConfigField]
class Subfield(Strict):
    code: str=Field(pattern=r'^[a-z0-9]$')
    value: str
class MarcField(Strict):
    tag: str=Field(pattern=r'^\d{3}$')
    value: str|None=None
    ind1: str|None=None
    ind2: str|None=None
    subfields: list[Subfield]|None=None
class Marc(Strict):
    leader: str
    fields: list[MarcField]
from uuid import UUID
from .acquisitions import InitialAcquisition, initial_body, register, digest, lock_request, make_router

class RecordInput(Strict):
    request_key: UUID|None=None
    initial_acquisition: InitialAcquisition|None=None
    type_id: int
    marc: Marc
    version: int|None=None
@app.get('/api/health')
def health(s=Depends(db)):
    s.execute(select(DocumentType.id).limit(1)); return {'status':'ok'}
@app.get('/api/dictionary',dependencies=[Depends(auth)])
def dictionary(): return {**DATA,'local_fields':list(LOCAL_DICTIONARY.values()),'default_config':default_config()}
@app.get('/api/types',dependencies=[Depends(auth)])
def types(s=Depends(db)):
    return [{'id':t.id,'name':t.name,'config':t.config} for t in s.scalars(select(DocumentType).order_by(DocumentType.id))]
def check_type(body):
    config=[c.model_dump() for c in body.config]
    errors=validate_config(config,DICTIONARY,LOCAL_DICTIONARY)
    if not body.name.strip(): errors.append('Name is empty')
    for c in config:
        spec=(LOCAL_DICTIONARY if c.get('local') else DICTIONARY).get(c['tag'],{})
        allowed={'_'} if int(c['tag'])<10 else {sf['code'] for sf in spec.get('subfields',[])}
        for code in c['vocabularies']:
            if code not in allowed: errors.append(c['tag']+': неизвестная строка справочника')
            if c['tag'] in ('000','001','005','008') or (c['tag']=='990' and c.get('local') and code in ('d','e','f')): errors.append(c['tag']+': служебное поле заполняется автоматически')
    if errors: raise HTTPException(422,errors)
    return config

def save_type(body,s,id=None):
    config=check_type(body)
    t=s.get(DocumentType,id) if id else DocumentType()
    if t is None: raise HTTPException(404,'Type not found')
    from .catalog_vocabularies import configure,seed_literature
    t.name=body.name.strip(); t.config=configure(config) if not id else config; s.add(t)
    try:
        if not id and any(c['tag']=='952' for c in config):
            s.flush();seed_literature(s,t)
        s.flush()
        backfill_automatic(s,t)
        s.commit()
    except IntegrityError: s.rollback(); raise HTTPException(409,'Type name already exists')
    return {'id':t.id,'name':t.name,'config':t.config}
@app.post('/api/types',dependencies=[Depends(auth)],status_code=201)
def create_type(body:TypeInput,s=Depends(db)): return save_type(body,s)
@app.put('/api/types/{id}',dependencies=[Depends(auth)])
def edit_type(id:int,body:TypeInput,s=Depends(db)): return save_type(body,s,id)
def output(r): return {'id':r.id,'type_id':r.type_id,'version':r.version,'marc':r.marc}
@app.get('/api/records',dependencies=[Depends(auth)])
def records(q:str='',type_id:int|None=None,offset:int=Query(0,ge=0),limit:int=Query(50,ge=1,le=100),s=Depends(db)):
    stmt=select(Record)
    q=q.strip()
    if q:
        matching_copies=select(Copy.record_id).where(or_(
            Copy.inventory_number.icontains(q,autoescape=True),
            Copy.barcode.icontains(q,autoescape=True),
        ))
        stmt=stmt.where(or_(
            Record.search_text.contains(q.casefold(),autoescape=True),
            Record.id.in_(matching_copies),
        ))
    if type_id: stmt=stmt.where(Record.type_id==type_id)
    return [output(r) for r in s.scalars(stmt.order_by(Record.id.desc()).offset(offset).limit(limit))]
@app.get('/api/records/{id}',dependencies=[Depends(auth)])
def record(id:int,s=Depends(db)):
    r=s.get(Record,id)
    if r is None: raise HTTPException(404,'Record not found')
    return output(r)
def save_record(body,s,id=None,user=None):
    if id and (body.initial_acquisition or body.request_key):
        raise HTTPException(422,'Для новых экземпляров используйте «Добавить экземпляры»')
    request_hash=digest(body.model_dump(mode='json'))
    if not id and body.request_key:
        lock_request(s,'record:',body.request_key)
        prior=s.get(RecordCreation,str(body.request_key))
        if prior:
            if prior.payload_hash!=request_hash: raise HTTPException(409,'Эта операция уже сохранена с другими данными')
            saved=s.get(Record,prior.record_id) if prior.record_id else None
            if saved is None: raise HTTPException(409,'Запись этой операции уже удалена; повтор не создаёт новую запись')
            return {**output(saved),'warnings':[]}
    creating=id is None
    t=s.get(DocumentType,body.type_id)
    if t is None: raise HTTPException(422,'Unknown document type')
    marc=body.marc.model_dump(exclude_none=True)
    previous=s.get(Record,id) if id else None
    if id and (previous is None or previous.version!=body.version):
        raise HTTPException(409,'Record changed or deleted; reload before saving')
    previous_marc=previous.marc if previous else None
    previous_type=previous.type_id if previous else None
    marc=populate(marc,t.config,t.name,previous_marc)
    from .statistics import comparable, record_activity
    meaningful=creating or previous_type!=t.id or comparable(marc)!=comparable(previous_marc)
    if not creating and meaningful and user is not None and (any(c['tag']=='097' for c in t.config) or any(f['tag']=='097' for f in marc['fields'])):
        from .catalog_vocabularies import set_operator
        set_operator(marc,user.display_name)
    effective={**DICTIONARY,**{c['tag']:LOCAL_DICTIONARY[c['tag']] for c in t.config if c.get('local') and c['tag'] in LOCAL_DICTIONARY}}
    errors,warnings=validate_marc(marc,t.config,effective,previous=previous_marc)
    errors+=validate_coded(marc,previous.marc if previous else None)
    if errors: raise HTTPException(422,errors)
    if id:
        if body.version is None: raise HTTPException(422,'Version required')
        changed=s.execute(update(Record).where(Record.id==id,Record.version==body.version).values(type_id=t.id,marc=marc,search_text=search_text(marc),version=body.version+1))
        if changed.rowcount!=1: raise HTTPException(409,'Record changed or deleted; reload before saving')
    else:
        r=Record(type_id=t.id,marc=marc,search_text=search_text(marc)); s.add(r); s.flush(); id=r.id
    vocab_errors,vocab_warnings=apply_vocabularies(s,t,marc,previous_marc)
    if vocab_errors:
        s.rollback(); raise HTTPException(422,vocab_errors)
    warnings+=vocab_warnings
    if creating:
        receipt=initial_body(marc,id,body.request_key,body.initial_acquisition) if body.initial_acquisition else None
        if receipt: register(s,receipt)
        if body.request_key:
            s.add(RecordCreation(request_key=str(body.request_key),payload_hash=request_hash,record_id=id))
    if user is not None and meaningful: record_activity(s,user,id,marc,creating)
    s.commit(); return {**output(s.get(Record,id)),'warnings':warnings}
@app.post('/api/records',dependencies=[Depends(auth)],status_code=201)
def create_record(body:RecordInput,s=Depends(db),user=Depends(auth)):
    if body.initial_acquisition: require(user,"acquisitions.edit")
    return save_record(body,s,user=user)
@app.put('/api/records/{id}',dependencies=[Depends(auth)])
def edit_record(id:int,body:RecordInput,s=Depends(db),user=Depends(auth)): return save_record(body,s,id,user=user)

@app.delete('/api/records/{id}',dependencies=[Depends(auth)],status_code=204)
def delete_record(id:int,version:int=Query(ge=1),s=Depends(db)):
    if s.scalar(select(Record).where(Record.id==id).with_for_update()) is None: raise HTTPException(404,'Record not found')
    if s.scalar(select(AcquisitionLine.id).where(AcquisitionLine.record_id==id).limit(1)) is not None or s.scalar(select(Copy.id).where(Copy.record_id==id).limit(1)) is not None:
        raise HTTPException(409,'У записи есть поступления и экземпляры. Удаление запрещено для сохранения истории учёта.')
    result=s.execute(delete(Record).where(Record.id==id,Record.version==version))
    if result.rowcount!=1:
        s.rollback();raise HTTPException(409,'Record changed or deleted; reload before saving')
    s.commit()

from typing import Literal
from .gost import describe
class GostInput(Strict):
    marc: Marc
    kind: Literal['single','component']='single'
@app.post('/api/gost/preview',dependencies=[Depends(auth)])
def gost_preview(body:GostInput):
    return describe(body.marc.model_dump(exclude_none=True),body.kind)

class VocabularyEntryInput(Strict):
    value: str=Field(min_length=1,max_length=1000)
    label: str=Field(default='',max_length=1000)
def entry_output(e): return {'id':e.id,'tag':e.tag,'code':e.code,'value':e.value,'label':e.label}
@app.get('/api/types/{id}/vocabulary',dependencies=[Depends(auth)])
def vocabulary(id:int,s=Depends(db)):
    if s.get(DocumentType,id) is None: raise HTTPException(404,'Type not found')
    from .catalog_vocabularies import employee_entries
    stored=[entry_output(e) for e in s.scalars(select(VocabularyEntry).where(VocabularyEntry.type_id==id).order_by(VocabularyEntry.value,VocabularyEntry.id)) if (e.tag,e.code)!=('097','b')]
    return stored+(employee_entries(s) if any(c['tag']=='097' for c in s.get(DocumentType,id).config) else [])
@app.post('/api/types/{id}/vocabulary/{tag}/{code}',dependencies=[Depends(auth)],status_code=201)
def create_entry(id:int,tag:str,code:str,body:VocabularyEntryInput,s=Depends(db)):
    t=s.get(DocumentType,id)
    if t is None: raise HTTPException(404,'Type not found')
    if (tag,code)==('097','b'): raise HTTPException(422,'Список операторов формируется из пользователей системы')
    if not any(c['tag']==tag and code in c.get('vocabularies',{}) for c in t.config): raise HTTPException(422,'Сначала сохраните настройку справочника для этой строки')
    if not normalized(body.value): raise HTTPException(422,'Введите непустое значение')
    e=add_entry(s,id,tag,code,body.value,body.label);s.commit();return entry_output(e)
@app.delete('/api/types/{id}/vocabulary/{entry_id}',dependencies=[Depends(auth)],status_code=204)
def delete_entry(id:int,entry_id:int,s=Depends(db)):
    e=s.get(VocabularyEntry,entry_id)
    if e is None or e.type_id!=id: raise HTTPException(404,'Значение не найдено')
    s.delete(e);s.commit()

from .marcsql import parse_item, fingerprint

class MarcsqlInput(Strict):
    source: str=Field(min_length=1,max_length=200)
    doc_id: int
    type_id: int
    rectype: str=Field(min_length=1,max_length=1)
    biblevel: str=Field(min_length=1,max_length=1)
    item: str=Field(min_length=1,max_length=2000000)
    preview: bool=True

@app.post('/api/import/marcsql',dependencies=[Depends(auth)])
def import_marcsql(body:MarcsqlInput,s=Depends(db)):
    t=s.get(DocumentType,body.type_id)
    if t is None: raise HTTPException(422,'Unknown document type')
    checksum=fingerprint(body.item,body.rectype,body.biblevel)
    previous=s.scalar(select(MarcsqlSource).where(MarcsqlSource.source==body.source,MarcsqlSource.doc_id==body.doc_id))
    if previous:
        if previous.checksum!=checksum:
            raise HTTPException(409,'Исходная запись изменилась: требуется ручное сравнение')
        return {'status':'skipped','record_id':previous.record_id,'doc_id':body.doc_id}
    try: marc,warnings=parse_item(body.item,body.rectype,body.biblevel)
    except ValueError as exc: raise HTTPException(422,str(exc))
    effective={**DICTIONARY,**{c['tag']:LOCAL_DICTIONARY[c['tag']] for c in t.config if c.get('local') and c['tag'] in LOCAL_DICTIONARY}}
    errors,notices=validate_marc(marc,t.config,effective)
    warnings += errors+notices
    # Legacy validation issues are reported, never "corrected" silently.
    # Do not call populate(): it would replace historical 005.
    if body.preview:
        return {'status':'preview','doc_id':body.doc_id,'marc':marc,'warnings':warnings}
    r=Record(type_id=t.id,marc=marc,search_text=search_text(marc))
    s.add(r);s.flush()
    collect_automatic(s,t,marc)
    s.add(MarcsqlSource(source=body.source,doc_id=body.doc_id,record_id=r.id,
                       item=body.item,rectype=body.rectype,biblevel=body.biblevel,checksum=checksum))
    try: s.commit()
    except IntegrityError:
        s.rollback()
        raise HTTPException(409,'Одновременный импорт: повторите запрос')
    return {'status':'imported','record_id':r.id,'doc_id':body.doc_id,'warnings':warnings}

@app.get('/api/records/{id}/marcsql-source',dependencies=[Depends(auth)])
def marcsql_source(id:int,s=Depends(db)):
    original=s.scalar(select(MarcsqlSource).where(MarcsqlSource.record_id==id))
    if original is None: raise HTTPException(404,'Original not found')
    return {k:getattr(original,k) for k in ('source','doc_id','item','rectype','biblevel','checksum')}

app.include_router(make_router(auth,db))

from .stock_operations import make_router as stock_router
app.include_router(stock_router(auth,db))

from .marcsql_copies import make_router as marcsql_copies_router
app.include_router(marcsql_copies_router(auth,db))

from .isbn_lookup import router as isbn_router
app.include_router(isbn_router(auth))

from .ksu import make_router as ksu_router
app.include_router(ksu_router(auth,db))

from .statistics import make_router as statistics_router
app.include_router(statistics_router(auth,db))

from .settings_transfer import make_router as settings_router
app.include_router(settings_router(auth,db,TypeInput,check_type,DICTIONARY,LOCAL_DICTIONARY))

from .readers import make_router as readers_router
app.include_router(readers_router(auth,db))

@app.middleware('http')
async def reader_private_responses(request:Request,call_next):
    response=await call_next(request)
    if request.url.path.startswith(('/api/readers','/api/visits','/api/reader-branches')):
        response.headers['Cache-Control']='private, no-store'
        response.headers['X-Content-Type-Options']='nosniff'
    return response
