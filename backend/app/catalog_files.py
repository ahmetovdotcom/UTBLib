"""Private catalogue PDFs. Uploads are staged; publication happens with record save."""
import json
import re
import subprocess
import sys
from itertools import chain
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from anyio import open_file
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import delete, func, insert, select
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool
from starlette.responses import StreamingResponse

from .db import CatalogFile, CatalogFileChunk, Record, User, get_db, utcnow
from .security import auth
from .student_bridge import authenticated_subject

router=APIRouter(tags=['Catalogue publications'])
MAX_FILE=1024*1024*1024
CHUNK_SIZE=4*1024*1024
PRIVATE={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'}


def file_info(row):
    return {'name':row.name,'size':row.size,'pages':row.pages} if row else None


def render_pdf(path):
    try:
        result=subprocess.run([sys.executable,str(Path(__file__).with_name('pdf_cover.py')),str(path.parent)],
                              stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=120,check=True)
        pages=json.loads(result.stdout)['pages']
        cover=(path.parent/'cover.jpg').read_bytes()
        if not 0<len(cover)<4*1024*1024: raise ValueError()
        return pages,cover
    except (subprocess.SubprocessError,ValueError,OSError,KeyError):
        raise HTTPException(422,'Не удалось прочитать PDF. Загрузите исправный файл без пароля.')


def check_upload_quota(s,owner_id):
    stale=select(CatalogFile.id).where(CatalogFile.record_id.is_(None),CatalogFile.created_at<utcnow()-timedelta(days=1))
    s.execute(delete(CatalogFileChunk).where(CatalogFileChunk.file_id.in_(stale)))
    s.execute(delete(CatalogFile).where(CatalogFile.id.in_(stale)))
    if s.scalar(select(func.count()).select_from(CatalogFile).where(CatalogFile.owner_id==owner_id,CatalogFile.record_id.is_(None)))>=10:
        raise HTTPException(409,'Слишком много незавершённых загрузок. Сохраните записи или повторите через сутки.')


def store_pdf(s,path,owner_id,filename,size,pages,cover):
    try:
        # Serialize the final quota check for parallel uploads by one employee.
        s.execute(select(User.id).where(User.id==owner_id).with_for_update())
        check_upload_quota(s,owner_id)
        name=re.sub(r'[\x00-\x1f\x7f/\\]','_',filename).strip() or 'book.pdf'
        row=CatalogFile(id=str(uuid4()),owner_id=owner_id,created_at=utcnow(),name=name,size=size,
                        pages=pages,content=b'',cover=cover,chunk_size=CHUNK_SIZE)
        s.add(row);s.flush()
        with path.open('rb') as source:
            position=0
            while chunk:=source.read(CHUNK_SIZE):
                s.execute(insert(CatalogFileChunk).values(file_id=row.id,position=position,content=chunk))
                position+=1
        result={'token':row.id,**file_info(row)}
        s.commit()
        return result
    except BaseException:
        s.rollback()
        raise


@router.post('/api/catalog-files',status_code=201)
async def upload(request:Request, filename:str=Query(min_length=1,max_length=255), user=Depends(auth),s=Depends(get_db)):
    if not filename.lower().endswith('.pdf') or request.headers.get('content-type','').split(';')[0]!='application/pdf':
        raise HTTPException(422,'Загрузите книгу в формате PDF (до 1 ГБ / 1024 МБ).')
    length=request.headers.get('content-length')
    if length is not None:
        if not re.fullmatch(r'[0-9]{1,20}',length): raise HTTPException(400,'Некорректный размер файла.')
        if int(length)>MAX_FILE: raise HTTPException(413,'Размер PDF не должен превышать 1 ГБ (1024 МБ).')
    owner_id=user.id
    await run_in_threadpool(check_upload_quota,s,owner_id)
    s.commit()  # Release the database connection during a potentially long transfer.
    try:
        with TemporaryDirectory(prefix='utblib-pdf-') as directory:
            path=Path(directory)/'book.pdf'
            size=0;signature=b''
            async with await open_file(path,'wb') as output:
                async for chunk in request.stream():
                    size+=len(chunk)
                    if size>MAX_FILE: raise HTTPException(413,'Размер PDF не должен превышать 1 ГБ (1024 МБ).')
                    signature=(signature+chunk[:5])[:5] if len(signature)<5 else signature
                    if len(signature)==5 and signature!=b'%PDF-': raise HTTPException(422,'Файл не является PDF.')
                    await output.write(chunk)
            if signature!=b'%PDF-': raise HTTPException(422,'Файл не является PDF.')
            pages,cover=await run_in_threadpool(render_pdf,path)
            return await run_in_threadpool(store_pdf,s,path,owner_id,filename,size,pages,cover)
    except OSError as error:
        if error.errno==28: raise HTTPException(507,'Недостаточно места для загрузки PDF. Обратитесь к администратору.') from error
        raise


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
            if old:
                s.execute(delete(CatalogFileChunk).where(CatalogFileChunk.file_id==old.id))
                s.delete(old);s.flush()
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
    row=record.digital_file
    file_id,chunk_size,size=row.id,row.chunk_size,row.size
    headers={**PRIVATE,'Content-Disposition':'inline; filename="book.pdf"','Accept-Ranges':'bytes',
             'Content-Security-Policy':"sandbox",'X-Accel-Buffering':'no'}
    value=request.headers.get('range','')
    start,end=0,size-1
    if value:
        match=re.fullmatch(r'bytes=([0-9]*)-([0-9]*)',value) if len(value)<=128 else None
        if not match or not any(match.groups()): return Response(status_code=416,headers={**headers,'Content-Range':f'bytes */{size}'})
        start,end=match.groups()
        start,end=(int(start),min(int(end),size-1) if end else size-1) if start else (max(0,size-int(end)),size-1)
        if start>end or start>=size: return Response(status_code=416,headers={**headers,'Content-Range':f'bytes */{size}'})
        headers['Content-Range']=f'bytes {start}-{end}/{size}'
    headers['Content-Length']=str(end-start+1)
    bind=s.get_bind()
    s.rollback()
    stream=read_chunks(bind,file_id,chunk_size,start,end)
    # Start the SELECT before sending headers. Its cursor keeps a consistent
    # snapshot even if the employee replaces/deletes the book while it is read.
    try: first=next(stream)
    except StopIteration: raise HTTPException(404)
    return StreamingResponse(chain((first,),stream),status_code=206 if value else 200,media_type='application/pdf',
                             headers=headers,background=BackgroundTask(stream.close))


def read_chunks(bind,file_id,chunk_size,start,end):
    with bind.connect() as connection:
        if not chunk_size:  # PDFs uploaded before 0024; never rewrite them during migration.
            content=connection.scalar(select(func.substr(CatalogFile.content,start+1,end-start+1)).where(CatalogFile.id==file_id))
            if content is not None:
                for offset in range(0,len(content),64*1024): yield content[offset:offset+64*1024]
            return
        first,last=start//chunk_size,end//chunk_size
        query=select(CatalogFileChunk.position,CatalogFileChunk.content).where(
            CatalogFileChunk.file_id==file_id,CatalogFileChunk.position.between(first,last)).order_by(CatalogFileChunk.position)
        with connection.execution_options(yield_per=1).execute(query) as chunks:
            expected=first
            for position,content in chunks:
                if position!=expected: raise RuntimeError('Missing PDF chunk')
                left=max(0,start-position*chunk_size);right=min(len(content),end-position*chunk_size+1)
                yield content[left:right]
                expected+=1
            if expected!=last+1: raise RuntimeError('Incomplete PDF storage')
