"""Portable settings only: document types are matched by name, never database ID."""
import hashlib
import json
from typing import Literal
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,ConfigDict,Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from .db import DocumentType,VocabularyEntry
from .vocabulary import normalized,value_key,add_entry,backfill_automatic


class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid')


class Entry(Strict):
    tag:str=Field(pattern=r'^\d{3}$')
    code:str=Field(pattern=r'^[a-z0-9_]$')
    value:str=Field(min_length=1,max_length=1000)
    label:str=Field(default='',max_length=1000)


def export_settings(s):
    groups={}
    for e in s.scalars(select(VocabularyEntry).order_by(VocabularyEntry.id)):
        if (e.tag,e.code)==('097','b'):continue
        groups.setdefault(e.type_id,[]).append({'tag':e.tag,'code':e.code,'value':e.value,'label':e.label})
    return {'format':'utblib-settings','version':1,'types':[
        {'name':t.name,'config':t.config,'entries':groups.get(t.id,[])}
        for t in s.scalars(select(DocumentType).order_by(DocumentType.id))]}


def fingerprint(data):
    return hashlib.sha256(json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def make_router(auth,db,type_input,check_type,dictionary,local_dictionary):
    class TransferType(type_input):
        entries:list[Entry]=Field(default_factory=list,max_length=100000)
    class Bundle(Strict):
        format:Literal['utblib-settings']
        version:Literal[1]
        types:list[TransferType]=Field(min_length=1,max_length=1000)
    class Apply(Strict):
        bundle:Bundle
        expected_state:str=Field(pattern=r'^[a-f0-9]{64}$')
        expected_bundle:str=Field(pattern=r'^[a-f0-9]{64}$')

    router=APIRouter(prefix='/api/settings-transfer',dependencies=[Depends(auth)])

    def validate(bundle):
        names=set()
        for t in bundle.types:
            name=t.name.strip()
            if name in names:raise HTTPException(422,'Повторяющийся тип документа: '+name)
            names.add(name)
            check_type(t)
            seen=set()
            for e in t.entries:
                if (e.tag,e.code)==('097','b'):raise HTTPException(422,'Операторы берутся из пользователей сервера и не переносятся')
                spec=local_dictionary.get(e.tag) or dictionary.get(e.tag)
                if not spec:raise HTTPException(422,'Неизвестное поле справочника: '+e.tag)
                allowed={'_'} if int(e.tag)<10 else {sf['code'] for sf in spec.get('subfields',[])}
                if e.code not in allowed or not normalized(e.value):raise HTTPException(422,'Недопустимое значение справочника '+e.tag+'$'+e.code)
                key=(e.tag,e.code,value_key(e.value))
                if key in seen:raise HTTPException(422,'Повторяющееся значение справочника '+e.tag+'$'+e.code)
                seen.add(key)

    def plan(s,bundle):
        current=export_settings(s)
        existing={t['name']:t for t in current['types']}
        rows=[]
        for t in bundle.types:
            target=existing.get(t.name.strip())
            known={(e['tag'],e['code'],value_key(e['value'])):e for e in target['entries']} if target else {}
            added=sum((e.tag,e.code,value_key(e.value)) not in known for e in t.entries)
            conflicts=sum(bool(known.get((e.tag,e.code,value_key(e.value)),{}).get('label')) and known[(e.tag,e.code,value_key(e.value))]['label']!=e.label for e in t.entries if e.label)
            rows.append({'name':t.name.strip(),'action':'replace' if target else 'create','fields_before':len(target['config']) if target else 0,'fields_after':len(t.config),'entries_added':added,'labels_preserved':conflicts,'before_config':target['config'] if target else [],'config':[c.model_dump() for c in t.config]})
        return {'expected_state':fingerprint(current),'expected_bundle':fingerprint(bundle.model_dump()),'types':rows}

    @router.get('/export')
    def export(s=Depends(db)):return export_settings(s)

    @router.post('/preview')
    def preview(bundle:Bundle,s=Depends(db)):
        validate(bundle)
        return plan(s,bundle)

    @router.post('/apply')
    def apply(body:Apply,s=Depends(db)):
        validate(body.bundle)
        # Lock existing settings while checking the reviewed state and applying one transaction.
        list(s.scalars(select(DocumentType).order_by(DocumentType.id).with_for_update()))
        list(s.scalars(select(VocabularyEntry).order_by(VocabularyEntry.id).with_for_update()))
        preview=plan(s,body.bundle)
        if body.expected_state!=preview['expected_state'] or body.expected_bundle!=preview['expected_bundle']:
            raise HTTPException(409,'Настройки или файл изменились. Выполните предварительную проверку заново.')
        try:
            for incoming in body.bundle.types:
                name=incoming.name.strip()
                t=s.scalar(select(DocumentType).where(DocumentType.name==name))
                if t is None:
                    t=DocumentType(name=name,config=[]);s.add(t)
                t.config=[c.model_dump() for c in incoming.config]
                s.flush()
                for e in incoming.entries:
                    entry=add_entry(s,t.id,e.tag,e.code,e.value,e.label)
                    if not entry.label.strip() and e.label.strip():entry.label=e.label.strip()
                backfill_automatic(s,t)
            s.commit()
        except IntegrityError:
            s.rollback();raise HTTPException(409,'Настройки изменились одновременно. Повторите предварительную проверку.')
        return {'types':preview['types']}
    return router
