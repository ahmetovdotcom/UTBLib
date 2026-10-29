import csv, io, os, tempfile
from datetime import date, datetime, timedelta
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.responses import Response, StreamingResponse, FileResponse
from starlette.background import BackgroundTask
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select, func, or_, exists, delete
from sqlalchemy.exc import IntegrityError
from .db import User, UserAudit, utcnow
from .security import has, require
from .reader_models import *
from .reader_core import *

class ReaderInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    full_name:str=Field(min_length=1,max_length=300)
    category:Literal['student','bachelor','specialist','master','doctoral','teacher','faculty','researcher','staff','external']='student'
    status:Literal['active','blocked','suspended']='active'
    block_reason:str=Field(default='',max_length=1000)
    email:str=Field(default='',max_length=250)
    login:str=Field(default='',max_length=150)
    phone:str=Field(default='',max_length=100)
    additional_email:str=Field(default='',max_length=250)
    iin:str|None=Field(default=None,pattern=r'^\d{12}$')
    birth_date:date|None=None
    gender:Literal['','male','female']=''
    faculty:str=Field(default='',max_length=250)
    department:str=Field(default='',max_length=250)
    study_group:str=Field(default='',max_length=150)
    education_level:str=Field(default='',max_length=100)
    education_program:str=Field(default='',max_length=250)
    program_code:str=Field(default='',max_length=100)
    course:int|None=Field(default=None,ge=1,le=20)
    cohort_year:int|None=Field(default=None,ge=1900,le=2200)
    position:str=Field(default='',max_length=250)
    subdivision:str=Field(default='',max_length=250)
    is_teaching_staff:bool=False
    reregistered_at:date|None=None
    valid_until:date|None=None
    preferred_branch_id:int|None=None
    branch_ids:list[int]=Field(default_factory=list,max_length=100)
    manual_overrides:list[str]=Field(default_factory=list,max_length=40)
    version:int|None=None
    @field_validator('full_name')
    @classmethod
    def name(cls,v):
        if not v.strip(): raise ValueError('Введите ФИО')
        return v.strip()

class SourceImportInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    source:Literal['active_directory','platonus']
    entity_type:Literal['ad_user','student','tutor']
    external_id:str=Field(min_length=1,max_length=100)

class BranchInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    code:str=Field(pattern=r'^[A-Za-z0-9_-]{1,40}$')
    name:str=Field(min_length=1,max_length=200)
    active:bool=True
    position:int=0
class PhotoInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    content:str=Field(min_length=1,max_length=4_000_000)

class ScanInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    code:str=Field(min_length=1,max_length=100)
    branch_id:int
    source:Literal['desk','kiosk','turnstile']='desk'
    notes:str=Field(default='',max_length=1000)

FILTER_FIELDS=('category','status','education_level','faculty','department','education_program','study_group','course','cohort_year','gender')
def filtered(request,user):
    p=request.query_params; stmt=select(Reader)
    if p.get('q'):
        term=p['q'].strip()[:200]; pattern='%'+term.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
        cols=[Reader.full_name,Reader.ticket_number,Reader.barcode,Reader.login,Reader.email]
        if has(user,'readers.personal_data.view'): cols.append(Reader.iin)
        stmt=stmt.where(or_(*(c.ilike(pattern,escape='\\') for c in cols)))
    for key in FILTER_FIELDS:
        if p.get(key):
            value=p[key]
            if key in ('course','cohort_year'):
                try: value=int(value)
                except ValueError: raise HTTPException(422,'Некорректный числовой фильтр')
            stmt=stmt.where(getattr(Reader,key)==value)
    if p.get('audience')=='students': stmt=stmt.where(Reader.category.in_(['student','bachelor','specialist','master','doctoral']))
    elif p.get('audience')=='faculty': stmt=stmt.where(or_(Reader.is_teaching_staff.is_(True),Reader.category.in_(['teacher','faculty','researcher'])))
    elif p.get('audience')=='staff': stmt=stmt.where(Reader.category=='staff')
    if p.get('branch_id'):
        try: branch=int(p['branch_id'])
        except ValueError: raise HTTPException(422,'Некорректный пункт обслуживания')
        stmt=stmt.where(exists(select(1).where(ReaderServicePoint.reader_id==Reader.id,ReaderServicePoint.branch_id==branch)))
    if p.get('source'):
        identity=exists(select(1).where(ReaderIdentity.reader_id==Reader.id,ReaderIdentity.source==p['source']))
        stmt=stmt.where(~identity if p.get('source_presence')=='absent' else identity)
    for key,operator in [('registered_from','from'),('registered_to','to')]:
        if p.get(key):
            try: start,end=local_bounds(date.fromisoformat(p[key]))
            except ValueError: raise HTTPException(422,'Некорректная дата')
            stmt=stmt.where(Reader.registered_at>=start if operator=='from' else Reader.registered_at<end)
    missing=p.get('missing')
    if missing:
        if missing in ('iin','birth_date'): require(user,'readers.personal_data.view')
        if missing=='photo': stmt=stmt.where(~exists(select(1).where(ReaderPhoto.reader_id==Reader.id)))
        elif missing in ('iin','birth_date','phone','email','faculty'):
            col=getattr(Reader,missing); stmt=stmt.where(col.is_(None) if missing=='birth_date' else or_(col.is_(None),col==''))
        else: raise HTTPException(422,'Неизвестный фильтр полноты')
    if p.get('iin_mismatch')=='true':
        require(user,'readers.personal_data.view')
        stmt=stmt.where(exists(select(1).where(ReaderConflict.reader_id==Reader.id,ReaderConflict.code=='iin_birth_mismatch',ReaderConflict.resolved.is_(False))))
    if p.get('conflicts')=='true': stmt=stmt.where(exists(select(1).where(ReaderConflict.reader_id==Reader.id,ReaderConflict.resolved.is_(False))))
    if p.get('login_activity'):
        logged=exists(select(1).where(UserAudit.target_id==Reader.user_id,UserAudit.action=='login'))
        stmt=stmt.where(logged if p['login_activity']=='yes' else ~logged)
    sort=p.get('sort','full_name'); descending=sort.startswith('-'); sort=sort.lstrip('-')
    if sort not in ('full_name','ticket_number','registered_at','category','status','id'): raise HTTPException(422,'Неизвестная сортировка')
    col=getattr(Reader,sort)
    return stmt.order_by(col.desc() if descending else col,Reader.id)

def get_reader(s,id,lock=False):
    stmt=select(Reader).where(Reader.id==id)
    reader=s.scalar(stmt.with_for_update() if lock else stmt)
    if not reader: raise HTTPException(404,'Читатель не найден')
    return reader

def safe_cell(value):
    value='' if value is None else str(value)
    return "'"+value if value.lstrip().startswith(('=','+','-','@','\t','\r')) else value

def make_router(auth,db):
    router=APIRouter()
    @router.get('/api/readers/options')
    def options(s=Depends(db),user=Depends(auth)):
        return {'categories':CATEGORIES,'statuses':STATUSES,'timezone':str(TZ),'circulation_available':False}
    @router.get('/api/reader-branches')
    def branches(s=Depends(db),user=Depends(auth)):
        return [{c.name:getattr(b,c.name) for c in Branch.__table__.columns} for b in s.scalars(select(Branch).order_by(Branch.position,Branch.name))]
    @router.post('/api/reader-branches')
    @router.put('/api/reader-branches/{id}')
    def save_branch(body:BranchInput,id:int|None=None,s=Depends(db),user=Depends(auth)):
        branch=s.get(Branch,id) if id else Branch()
        if not branch: raise HTTPException(404,'Пункт не найден')
        for key,value in body.model_dump().items(): setattr(branch,key,value)
        s.add(branch); audit(s,'branch.edit',user.id)
        try: s.commit()
        except IntegrityError: s.rollback(); raise HTTPException(409,'Код пункта уже существует')
        return {'id':branch.id}
    @router.get('/api/readers')
    def registry(request:Request,offset:int=Query(0,ge=0),limit:int=Query(50,ge=1,le=100),s=Depends(db),user=Depends(auth)):
        rate_limit(s,user.id,'search',120); stmt=filtered(request,user)
        total=s.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
        return {'total':total,'items':[public_reader(r,has(user,'readers.personal_data.view')) for r in s.scalars(stmt.offset(offset).limit(limit))]}
    @router.get('/api/readers/analytics')
    def analytics(request:Request,s=Depends(db),user=Depends(auth)):
        sub=filtered(request,user).order_by(None).subquery(); result={'scope':'Текущая отфильтрованная выборка','total':s.scalar(select(func.count()).select_from(sub))}
        for key in ('category','faculty','course','status'):
            result[key]=[{'label':v or 'Не указано','count':n} for v,n in s.execute(select(sub.c[key],func.count()).group_by(sub.c[key]))]
        result['missing']={key:s.scalar(select(func.count()).select_from(sub).where(or_(sub.c[key].is_(None),sub.c[key]==''))) for key in ('phone','email','faculty')}
        if has(user,'readers.personal_data.view'):
            result['missing'].update({key:s.scalar(select(func.count()).select_from(sub).where(sub.c[key].is_(None))) for key in ('iin','birth_date')})
        result['branches']=[{'label':name,'count':count} for name,count in s.execute(select(Branch.name,func.count()).join(ReaderServicePoint,Branch.id==ReaderServicePoint.branch_id).where(ReaderServicePoint.reader_id.in_(select(sub.c.id))).group_by(Branch.name))]
        result['missing']['photo']=s.scalar(select(func.count()).select_from(sub).where(~exists(select(1).where(ReaderPhoto.reader_id==sub.c.id))))
        today=datetime.now(TZ).date(); trend=[]
        for n in range(11,-1,-1):
            month_index=today.year*12+today.month-1-n; year,month=divmod(month_index,12); a,_=local_bounds(date(year,month+1,1)); next_year,next_month=divmod(month_index+1,12); b,_=local_bounds(date(next_year,next_month+1,1))
            trend.append({'month':f'{year}-{month+1:02d}','count':s.scalar(select(func.count()).select_from(sub).where(sub.c.registered_at>=a,sub.c.registered_at<b))})
        result['registrations']=trend
        a,_=local_bounds(today-timedelta(days=29)); _,b=local_bounds(today)
        result['activity_period']={'from':today-timedelta(days=29),'to':today,'timezone':str(TZ)}
        result['physical_visits_30_days']=s.scalar(select(func.count()).where(LibraryVisit.reader_id.in_(select(sub.c.id)),LibraryVisit.scanned_at>=a,LibraryVisit.scanned_at<b))
        result['website_logins_30_days']=s.scalar(select(func.count()).where(UserAudit.target_id.in_(select(sub.c.user_id)),UserAudit.action=='login',UserAudit.created_at>=a,UserAudit.created_at<b))
        result['website_logins']='Доступны только для явно связанных учётных записей; импорт не создаёт вход на сайт.'
        return result
    @router.get('/api/readers/export')
    def export(request:Request,format:Literal['csv','xlsx']='csv',s=Depends(db),user=Depends(auth)):
        rate_limit(s,user.id,'export',5); stmt=filtered(request,user); personal=has(user,'readers.personal_data.view')
        keys=['ticket_number','barcode','full_name','category','status','faculty','department','study_group','course','cohort_year','email','phone']+(['iin','birth_date'] if personal else [])
        audit(s,'export',user.id,format=format,personal=personal,filter_names=list(request.query_params.keys())); s.commit()
        # Bounded fetches; a temporary file lets the DB session end before a slow download.
        f=tempfile.NamedTemporaryFile(suffix='.'+format,delete=False); path=f.name; f.close()
        try:
            if format=='csv':
                with open(path,'w',encoding='utf-8-sig',newline='') as out:
                    writer=csv.writer(out); writer.writerow(keys)
                    for r in s.scalars(stmt.execution_options(yield_per=500)): writer.writerow([safe_cell(getattr(r,k)) for k in keys])
            else:
                from openpyxl import Workbook
                from openpyxl.cell import WriteOnlyCell
                book=Workbook(write_only=True); sheet=book.create_sheet('Читатели'); sheet.append(keys)
                for r in s.scalars(stmt.execution_options(yield_per=500)):
                    cells=[]
                    for key in keys:
                        cell=WriteOnlyCell(sheet,value=safe_cell(getattr(r,key))); cell.data_type='s'; cell.number_format='@'; cells.append(cell)
                    sheet.append(cells)
                book.save(path)
        except Exception:
            os.unlink(path); raise
        return FileResponse(path,filename='readers.'+format,background=BackgroundTask(os.unlink,path))
    @router.get('/api/readers/source-search')
    def source_search(source:Literal['active_directory','platonus'],q:str=Query(min_length=3,max_length=100),s=Depends(db),user=Depends(auth)):
        require(user,'readers.source.import')
        from .reader_lookup import lookup
        try: rows=lookup(source,search=q.strip()) if len(q.strip())>=3 else []
        except Exception: raise HTTPException(503,'Источник недоступен. Проверьте подключение или повторите позже.')
        items=[]
        for row in rows[:20]:
            f=row['fields']; identity=s.scalar(select(ReaderIdentity).where(ReaderIdentity.source==source,ReaderIdentity.entity_type==row['entity_type'],ReaderIdentity.external_id==row['external_id']))
            items.append({**{k:f.get(k,'') for k in ('full_name','login','category','study_group','department')},'source':source,'entity_type':row['entity_type'],'external_id':row['external_id'],'reader_id':identity.reader_id if identity else None})
        audit(s,'reader.source_search',user.id,source=source,count=len(items));s.commit()
        return {'items':items,'truncated':len(rows)>20}

    @router.post('/api/readers/source-import')
    def source_import(body:SourceImportInput,s=Depends(db),user=Depends(auth)):
        require(user,'readers.source.import')
        if (body.source=='active_directory')!=(body.entity_type=='ad_user'): raise HTTPException(422,'Тип не соответствует источнику')
        import uuid
        if body.source=='active_directory':
            try: body.external_id=str(uuid.UUID(body.external_id))
            except ValueError: raise HTTPException(422,'Некорректный идентификатор AD')
        elif not body.external_id.isdecimal(): raise HTTPException(422,'Некорректный идентификатор Platonus')
        else: body.external_id=str(int(body.external_id))
        from sqlalchemy.orm import sessionmaker
        from .reader_lookup import import_one
        try: result=import_one(sessionmaker(bind=s.get_bind()),body.source,body.entity_type,body.external_id)
        except LookupError as exc: raise HTTPException(409,str(exc))
        except ValueError: raise HTTPException(409,'Синхронизация занята. Повторите немного позже.')
        except Exception: raise HTTPException(503,'Источник недоступен. Повторите позже.')
        audit(s,'reader.source_import',user.id,result['id'],source=body.source);s.commit()
        return result

    @router.get('/api/readers/sync-status')
    def sync_status(s=Depends(db),user=Depends(auth)):
        runs=[{c.name:getattr(r,c.name) for c in ReaderSyncRun.__table__.columns} for r in s.scalars(select(ReaderSyncRun).order_by(ReaderSyncRun.id.desc()).limit(30))]
        last_success={source:next(({c.name:getattr(r,c.name) for c in ReaderSyncRun.__table__.columns} for r in s.scalars(select(ReaderSyncRun).where(ReaderSyncRun.source==source,ReaderSyncRun.status=='success').order_by(ReaderSyncRun.id.desc()).limit(1))),None) for source in ('active_directory','platonus','platonus-personal','csv')}
        return {'nightly_enabled':os.getenv('READERS_NIGHTLY_ENABLED','false').lower()=='true','nightly_time':os.getenv('READERS_NIGHTLY_TIME','03:20'),'last_success':last_success,'runs':runs,'ad_enabled':os.getenv('AD_ENABLED','false').lower()=='true','platonus_enabled':os.getenv('PLATONUS_ENABLED','false').lower()=='true','status_mapping_confirmed':os.getenv('PLATONUS_STATUS_MAPPING_CONFIRMED','false')=='true','conflicts':[{'id':c.id,'reader_id':c.reader_id,'source':c.source,'entity_type':c.entity_type,'external_id':c.external_id,'code':c.code} for c in s.scalars(select(ReaderConflict).where(ReaderConflict.resolved.is_(False)).order_by(ReaderConflict.id.desc()).limit(100))]}
    @router.post('/api/readers/conflicts/{id}/resolve')
    def resolve_conflict(id:int,s=Depends(db),user=Depends(auth)):
        conflict=s.get(ReaderConflict,id)
        if not conflict: raise HTTPException(404,'Проблема не найдена')
        conflict.resolved=True; audit(s,'conflict.reviewed',user.id,conflict.reader_id,conflict_id=id); s.commit()
        return {'ok':True}
    @router.post('/api/readers')
    @router.put('/api/readers/{id}')
    def save(body:ReaderInput,id:int|None=None,s=Depends(db),user=Depends(auth)):
        values=body.model_dump(); reader=get_reader(s,id,True) if id else None
        if reader and body.version!=reader.version: raise HTTPException(409,'Карточка изменена другим сотрудником. Откройте её снова.')
        personal=has(user,'readers.personal_data.view')
        if not personal and (body.iin is not None or body.birth_date is not None): raise HTTPException(403,'Недостаточно прав для персональных данных')
        if not personal:
            values.pop('iin'); values.pop('birth_date')
        else:
            try: values['iin'],values['birth_date']=validate_personal(s,values,id)
            except ValueError as e: raise HTTPException(422,str(e))
        branch_ids=set(values.pop('branch_ids')); preferred=values['preferred_branch_id']
        if preferred: branch_ids.add(preferred)
        if branch_ids and len(list(s.scalars(select(Branch.id).where(Branch.id.in_(branch_ids)))))!=len(branch_ids): raise HTTPException(422,'Пункт обслуживания не найден')
        overrides=values.pop('manual_overrides'); values.pop('version')
        if set(overrides)-(set(values)|{'iin','birth_date'}): raise HTTPException(422,'Неизвестное ручное переопределение')
        if not personal:
            overrides=[key for key in overrides if key not in ('iin','birth_date')]+[key for key in (reader.manual_overrides if reader else []) if key in ('iin','birth_date')]
        changed=[]
        if not reader:
            ticket,barcode=allocate_ticket(s,body.category,body.cohort_year,body.faculty)
            reader=Reader(ticket_number=ticket,barcode=barcode); s.add(reader)
        else:
            for key,value in values.items():
                if getattr(reader,key)!=value and reader.field_owners.get(key) and key not in overrides: raise HTTPException(422,f'{key}: поле управляется источником. Включите ручное переопределение.')
        for key,value in values.items():
            if getattr(reader,key,None)!=value: changed.append(key)
            setattr(reader,key,value)
        reader.manual_overrides=overrides; reader.updated_at=utcnow()
        if id: reader.version+=1
        try:
            s.flush(); s.execute(delete(ReaderServicePoint).where(ReaderServicePoint.reader_id==reader.id))
            s.add_all([ReaderServicePoint(reader_id=reader.id,branch_id=b,primary=b==preferred) for b in branch_ids])
            audit(s,'reader.edit' if id else 'reader.create',user.id,reader.id,fields=changed)
            if 'status' in changed: audit(s,'reader.status',user.id,reader.id,status=reader.status)
            if not id: audit(s,'ticket.assign',user.id,reader.id)
            s.commit()
        except IntegrityError: s.rollback(); raise HTTPException(409,'Конфликт уникальных данных читателя')
        return public_reader(reader,personal)
    @router.get('/api/readers/{id}')
    def card(id:int,s=Depends(db),user=Depends(auth)):
        reader=get_reader(s,id); result=public_reader(reader,has(user,'readers.personal_data.view'))
        result['branch_ids']=list(s.scalars(select(ReaderServicePoint.branch_id).where(ReaderServicePoint.reader_id==id)))
        result['has_photo']=s.get(ReaderPhoto,id) is not None
        result['identities']=[{'source':x.source,'entity_type':x.entity_type,'external_id':x.external_id,'last_synced_at':x.last_synced_at} for x in s.scalars(select(ReaderIdentity).where(ReaderIdentity.reader_id==id))]
        result['visits_count'],result['last_visit']=s.execute(select(func.count(),func.max(LibraryVisit.scanned_at)).where(LibraryVisit.reader_id==id)).one()
        result['visits']=[{'id':v.id,'scanned_at':v.scanned_at,'branch_id':v.branch_id} for v in s.scalars(select(LibraryVisit).where(LibraryVisit.reader_id==id).order_by(LibraryVisit.scanned_at.desc()).limit(10))]
        result['website_logins']=None if not reader.user_id else s.scalar(select(func.count()).where(UserAudit.target_id==reader.user_id,UserAudit.action=='login'))
        if user.role=='admin':result['user_id']=reader.user_id
        result['circulation']=None; result['clearance_available']=False
        if any(has(user,p) for p in ('circulation.issue','circulation.return','circulation.view_any_history')):
            from .circulation_service import summary
            result['circulation']=summary(s,reader)
        result['problems']=list(s.scalars(select(ReaderConflict.code).where(ReaderConflict.reader_id==id,ReaderConflict.resolved.is_(False))))
        return result
    @router.post('/api/readers/{id}/photo')
    def upload_photo(id:int,body:PhotoInput,s=Depends(db),user=Depends(auth)):
        import base64, binascii
        reader=get_reader(s,id,True)
        try: store_photo(s,id,base64.b64decode(body.content,validate=True))
        except (ValueError,binascii.Error): raise HTTPException(422,'Нужна фотография JPEG/PNG до 3 МБ и 16 мегапикселей')
        reader.field_owners={**reader.field_owners,'photo':'manual'}
        audit(s,'reader.photo',user.id,id); s.commit(); return {'ok':True}
    @router.get('/api/readers/{id}/photo')
    def photo(id:int,s=Depends(db),user=Depends(auth)):
        p=s.get(ReaderPhoto,id)
        if not p: raise HTTPException(404,'Фото отсутствует')
        return Response(p.content,media_type='image/jpeg',headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'})
    @router.get('/api/readers/{id}/ticket')
    def ticket(id:int,s=Depends(db),user=Depends(auth)):
        from .reader_ticket import ticket_codes
        reader=get_reader(s,id); svg,qr_svg=ticket_codes(reader.barcode)
        audit(s,'ticket.print',user.id,id); s.commit()
        return {'full_name':reader.full_name,'category':CATEGORIES[reader.category],
                'department':reader.department,'ticket_number':reader.ticket_number,
                'barcode':reader.barcode,'svg':svg,'qr_svg':qr_svg,
                'brand':os.getenv('READER_TICKET_BRAND','Kazakh University of Technology and Business named after K. Kulazhanov'),
                'library_name':os.getenv('LIBRARY_NAME','Библиотека КазУТБ'),
                'has_photo':s.get(ReaderPhoto,id) is not None}
    @router.get('/api/visits/lookup')
    def visit_lookup(code:str=Query(min_length=1,max_length=100),s=Depends(db),user=Depends(auth)):
        rate_limit(s,user.id,'lookup',180); r=lookup(s,code)
        return {k:getattr(r,k) for k in ('id','full_name','ticket_number','barcode','category','status','block_reason')}
    @router.post('/api/visits')
    def scan(body:ScanInput,s=Depends(db),user=Depends(auth)):
        rate_limit(s,user.id,'scan',180)
        branch=s.get(Branch,body.branch_id)
        if not branch or not branch.active: raise HTTPException(422,'Выберите действующий пункт обслуживания')
        reader=lookup(s,body.code,lock=True); now=utcnow()
        previous=s.scalar(select(LibraryVisit).where(LibraryVisit.reader_id==reader.id,LibraryVisit.scanned_at>=now-timedelta(minutes=10)).order_by(LibraryVisit.scanned_at.desc()).limit(1))
        duplicate=previous is not None
        visit=previous or LibraryVisit(reader_id=reader.id,branch_id=body.branch_id,scanned_at=now,scanned_by=user.id,source=body.source,notes=body.notes)
        if not duplicate:
            s.add(visit); s.flush(); audit(s,'visit.record',user.id,reader.id,visit_id=visit.id)
        s.commit()
        return {'id':visit.id,'reader_id':reader.id,'full_name':reader.full_name,'scanned_at':visit.scanned_at,'branch_id':visit.branch_id,'duplicate':duplicate}
    @router.get('/api/visits')
    def visits(offset:int=Query(0,ge=0),limit:int=Query(50,ge=1,le=100),reader_id:int|None=None,branch_id:int|None=None,s=Depends(db),user=Depends(auth)):
        stmt=select(LibraryVisit,Reader.full_name,Reader.ticket_number,Branch.name,User.display_name).join(Reader,Reader.id==LibraryVisit.reader_id).join(Branch,Branch.id==LibraryVisit.branch_id).join(User,User.id==LibraryVisit.scanned_by)
        if reader_id: stmt=stmt.where(LibraryVisit.reader_id==reader_id)
        if branch_id: stmt=stmt.where(LibraryVisit.branch_id==branch_id)
        total=s.scalar(select(func.count()).select_from(stmt.subquery()))
        return {'total':total,'items':[{'id':v.id,'reader_id':v.reader_id,'full_name':name,'ticket_number':ticket,'branch':branch,'actor':actor,'scanned_at':v.scanned_at,'source':v.source,'notes':v.notes} for v,name,ticket,branch,actor in s.execute(stmt.order_by(LibraryVisit.scanned_at.desc(),LibraryVisit.id.desc()).offset(offset).limit(limit))]}
    @router.get('/api/visits/analytics')
    def visit_analytics(days:int=Query(7,ge=1,le=90),s=Depends(db),user=Depends(auth)):
        today=datetime.now(TZ).date(); start,_=local_bounds(today-timedelta(days=days-1)); _,end=local_bounds(today)
        result=[]
        for n in range(days):
            day=today-timedelta(days=days-1-n); a,b=local_bounds(day)
            count,unique=s.execute(select(func.count(),func.count(func.distinct(LibraryVisit.reader_id))).where(LibraryVisit.scanned_at>=a,LibraryVisit.scanned_at<b)).one()
            result.append({'date':day,'visits':count,'unique':unique})
        branches=[{'name':name,'visits':count} for name,count in s.execute(select(Branch.name,func.count()).join(LibraryVisit,Branch.id==LibraryVisit.branch_id).where(LibraryVisit.scanned_at>=start,LibraryVisit.scanned_at<end).group_by(Branch.name))]
        weeks={}
        for row in result:
            monday=row['date']-timedelta(days=row['date'].weekday()); weeks[str(monday)]=weeks.get(str(monday),0)+row['visits']
        return {'timezone':str(TZ),'days':result,'weeks':weeks,'branches':branches,'visits':sum(x['visits'] for x in result),'today':result[-1]}
    return router

# Uvicorn normally includes query strings, which may contain an IIN search.
# Keep route/method/status for diagnostics, without reader search values.
import logging
class ReaderAccessLogFilter(logging.Filter):
    def filter(self,record):
        if isinstance(record.args,tuple) and len(record.args)>=3:
            args=list(record.args)
            if isinstance(args[2],str) and args[2].startswith(('/api/readers','/api/visits','/api/statistics/attendance')):
                args[2]=args[2].split('?',1)[0];record.args=tuple(args)
        return True
logging.getLogger('uvicorn.access').addFilter(ReaderAccessLogFilter())
