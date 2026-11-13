"""Private catalogue PDFs. Uploads are staged; publication happens with record save."""
import json
import re
import subprocess
import sys
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import delete, func, select
from starlette.concurrency import run_in_threadpool

from .db import CatalogFile, Record, get_db, utcnow
from .security import auth
from .student_bridge import authenticated_subject

router=APIRouter(tags=['Catalogue publications'])
MAX_FILE=50*1024*1024
PRIVATE={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'}


def file_info(row):
    return {'name':row.name,'size':row.size,'pages':row.pages} if row else None


def render_pdf(content):
    with TemporaryDirectory(prefix='utblib-pdf-') as directory:
        path=Path(directory)
        (path/'book.pdf').write_bytes(content)
        try:
            result=subprocess.run([sys.executable,str(Path(__file__).with_name('pdf_cover.py')),directory],
                                  stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=30,check=True)
            pages=json.loads(result.stdout)['pages']
            cover=(path/'cover.jpg').read_bytes()
            if not 0<len(cover)<4*1024*1024: raise ValueError()
            return pages,cover
        except (subprocess.SubprocessError,ValueError,OSError,KeyError):
            raise HTTPException(422,'Не удалось прочитать PDF. Загрузите исправный файл без пароля.')


@router.post('/api/catalog-files',status_code=201)
async def upload(request:Request, filename:str=Query(min_length=1,max_length=255), user=Depends(auth),s=Depends(get_db)):
    if not filename.lower().endswith('.pdf') or request.headers.get('content-type','').split(';')[0]!='application/pdf':
        raise HTTPException(422,'Загрузите книгу в формате PDF (до 50 МБ).')
    data=bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data)>MAX_FILE: raise HTTPException(413,'Размер PDF не должен превышать 50 МБ.')
    if not data.startswith(b'%PDF-'): raise HTTPException(422,'Файл не является PDF.')
    s.execute(delete(CatalogFile).where(CatalogFile.record_id.is_(None),CatalogFile.created_at<utcnow()-timedelta(days=1)))
    if s.scalar(select(func.count()).select_from(CatalogFile).where(CatalogFile.owner_id==user.id,CatalogFile.record_id.is_(None)))>=10:
        raise HTTPException(409,'Слишком много незавершённых загрузок. Сохраните записи или повторите через сутки.')
    pages,cover=await run_in_threadpool(render_pdf,bytes(data))
    name=re.sub(r'[\x00-\x1f\x7f/\\]','_',filename).strip() or 'book.pdf'
    row=CatalogFile(id=str(uuid4()),owner_id=user.id,created_at=utcnow(),name=name,size=len(data),pages=pages,content=bytes(data),cover=cover)
    s.add(row);s.commit()
    return {'token':row.id,**file_info(row)}


def save_publication(s,record,body,user):
    changed=False
    for key in ('is_faculty_work','use_first_page_cover'):
        if key in body.model_fields_set and getattr(record,key)!=getattr(body,key):
            setattr(record,key,getattr(body,key));changed=True
    if 'digital_upload' in body.model_fields_set:
        old=record.digital_file
        if body.digital_upload:
            row=s.scalar(select(CatalogFile).where(CatalogFile.id==str(body.digital_upload)).with_for_update())
            if (row is None or row.owner_id!=getattr(user,'id',None) or row.record_id not in (None,record.id)
                or (row.record_id is None and row.created_at.replace(tzinfo=utcnow().tzinfo)<utcnow()-timedelta(days=1))):
                raise HTTPException(409,'Загрузка устарела или недоступна. Выберите PDF заново.')
        else: row=None
        if old!=row:
            if old: s.delete(old);s.flush()
            record.digital_file=row
            changed=True
    if record.use_first_page_cover and not record.digital_file:
        raise HTTPException(422,'Для обложки из первой страницы загрузите PDF или снимите галочку обложки.')
    return changed


def get_record(s,identifier):
    if not re.fullmatch(r'utblib-[1-9][0-9]*',identifier): raise HTTPException(404)
    record=s.get(Record,int(identifier[7:]))
    if not record or not record.is_faculty_work: raise HTTPException(404)
    return record


@router.get('/api/public/v1/book-covers/{identifier}')
def cover(identifier:str,s=Depends(get_db)):
    record=get_record(s,identifier)
    if not record.use_first_page_cover or not record.digital_file: raise HTTPException(404)
    return Response(record.digital_file.cover,media_type='image/jpeg',headers={'Cache-Control':'no-cache','X-Content-Type-Options':'nosniff'})


@router.get('/api/student/v1/books/{identifier}')
def detail(identifier:str,response:Response,subject=Depends(authenticated_subject),s=Depends(get_db)):
    from .public_catalog import project,present,inventory
    from .db import DocumentType
    record=get_record(s,identifier)
    book=present(project(record,dict(s.execute(select(DocumentType.id,DocumentType.name)).all())),inventory(s).get(record.id,{}),full=True)
    response.headers.update(PRIVATE)
    return {'data':book,'success':True}


@router.get('/api/student/v1/books/{identifier}/file')
def file(identifier:str,request:Request,subject=Depends(authenticated_subject),s=Depends(get_db)):
    record=get_record(s,identifier)
    if not record.digital_file: raise HTTPException(404)
    content=record.digital_file.content
    size=len(content)
    headers={**PRIVATE,'Content-Disposition':'inline; filename="book.pdf"','Accept-Ranges':'bytes','Content-Security-Policy':"sandbox"}
    value=request.headers.get('range','')
    if value:
        match=re.fullmatch(r'bytes=(\d*)-(\d*)',value)
        if not match or not any(match.groups()): return Response(status_code=416,headers={**headers,'Content-Range':f'bytes */{size}'})
        start,end=match.groups()
        start,end=(int(start),min(int(end),size-1) if end else size-1) if start else (max(0,size-int(end)),size-1)
        if start>end or start>=size: return Response(status_code=416,headers={**headers,'Content-Range':f'bytes */{size}'})
        headers['Content-Range']=f'bytes {start}-{end}/{size}'
        return Response(content[start:end+1],status_code=206,media_type='application/pdf',headers=headers)
    return Response(content,media_type='application/pdf',headers=headers)
