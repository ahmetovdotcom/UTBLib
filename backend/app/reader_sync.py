"""Offline-first, source-scoped reader synchronization. Sources never write upstream."""
import argparse, base64, csv, json, os, tempfile, threading
from contextlib import contextmanager
from datetime import date
from itertools import islice
from sqlalchemy import select, text, func
from .db import Session, utcnow
from .reader_models import Reader, ReaderIdentity, ReaderSyncRun, ReaderConflict
from .reader_core import allocate_ticket, validate_personal, store_photo, audit, personal_error_code
from .readers import ReaderInput

_LOCK=threading.Lock()
LOCK_ID=58421947001
EXTERNAL_FIELDS={'full_name','email','login','phone','gender','faculty','department','study_group','education_level','education_program','program_code','course','cohort_year','position','subdivision','is_teaching_staff','category','external_status'}

@contextmanager
def sync_lock(engine):
    if engine.dialect.name=='postgresql':
        with engine.connect().execution_options(isolation_level='AUTOCOMMIT') as conn:
            acquired=conn.scalar(text('SELECT pg_try_advisory_lock(:key)'),{'key':LOCK_ID})
            if not acquired: raise ValueError('Другая синхронизация уже выполняется')
            try: yield
            finally: conn.execute(text('SELECT pg_advisory_unlock(:key)'),{'key':LOCK_ID})
    else:
        if not _LOCK.acquire(blocking=False): raise ValueError('Другая синхронизация уже выполняется')
        try: yield
        finally: _LOCK.release()

def batches(iterable,size=500):
    iterator=iter(iterable)
    while chunk:=list(islice(iterator,size)): yield chunk

def synchronize(factory,source,rows,*,dry_run=False,limit=None,no_photos=False,deactivate_missing=False,complete=False,status_confirmed=False,min_ratio=.8,overwrite=False):
    if source not in ('active_directory','platonus'): raise ValueError('Неизвестный источник')
    if limit is not None and limit<1: raise ValueError('limit должен быть положительным')
    with factory() as probe: engine=probe.get_bind()
    with sync_lock(engine):
        with factory() as s:
            run=ReaderSyncRun(source=source,parameters={'dry_run':dry_run,'limit':limit,'no_photos':no_photos,'deactivate_missing':deactivate_missing,'overwrite':overwrite})
            s.add(run); s.commit(); run_id=run.id
        counts=dict(read=0,created=0,updated=0,skipped=0,suspended=0,errors=0); seen=set(); seen_keys=set(); message=''; completed=False; processed=False
        try:
            # Stage the full source before changing profiles. Network failures cannot become a successful partial scan.
            with tempfile.TemporaryFile(mode='w+t',encoding='utf-8') as staged:
                for row in rows:
                    if limit is not None and counts['read']>=limit: break
                    staged.write(json.dumps(row,ensure_ascii=False,default=str)+'\n'); counts['read']+=1
                staged.seek(0)
                with factory() as s:
                    if s.bind.dialect.name=='sqlite': s.execute(text('BEGIN'))
                    existing=list(s.scalars(select(ReaderIdentity).where(ReaderIdentity.source==source)))
                    baseline=len(existing)
                    for chunk in batches((json.loads(line) for line in staged)):
                        keys=[str(r.get('external_id','')) for r in chunk]
                        identities={(i.entity_type,i.external_id):i for i in s.scalars(select(ReaderIdentity).where(ReaderIdentity.source==source,ReaderIdentity.external_id.in_(keys)))}
                        reader_ids={i.reader_id for i in identities.values()}
                        # Confirmed cross-source keys are fetched in the same batch; no name/email matching.
                        linked_ids=[str(r['platonus_link']['external_id']) for r in chunk if r.get('platonus_link')]
                        links={(i.entity_type,i.external_id):i for i in s.scalars(select(ReaderIdentity).where(ReaderIdentity.source=='platonus',ReaderIdentity.external_id.in_(linked_ids)))} if linked_ids else {}
                        reader_ids.update(i.reader_id for i in links.values())
                        ad_links={i.reader_id:i.external_id for i in s.scalars(select(ReaderIdentity).where(ReaderIdentity.source=='active_directory',ReaderIdentity.reader_id.in_(reader_ids)))}
                        readers={r.id:r for r in s.scalars(select(Reader).where(Reader.id.in_(reader_ids)).with_for_update())}
                        for item in chunk:
                            entity=item.get('entity_type',''); external=str(item.get('external_id','')); key=(entity,external)
                            reader=None
                            try:
                                if entity not in (('ad_user',) if source=='active_directory' else ('student','tutor')) or not external or len(external)>200: raise ValueError('invalid_identity')
                                if key in seen_keys: raise ValueError('duplicate_source_identity')
                                seen_keys.add(key)
                                identity=identities.get(key); reader=readers.get(identity.reader_id) if identity else None
                                link=item.get('platonus_link')
                                if link:
                                    if source!='active_directory' or link.get('confirmed') is not True or link.get('entity_type') not in ('student','tutor'): raise ValueError('unconfirmed_cross_source_link')
                                    linked=links.get((link['entity_type'],str(link['external_id'])))
                                    if linked:
                                        if (reader and reader.id!=linked.reader_id) or (ad_links.get(linked.reader_id) and ad_links[linked.reader_id]!=external): raise ValueError('ambiguous_cross_source_link')
                                        reader=readers[linked.reader_id]
                                if identity: seen.add(identity.id)
                                if item.get('disabled') or item.get('technical'):
                                    counts['skipped']+=1; continue
                                if item.get('leaver'):
                                    # Confirmed status lists explicitly exclude departed people,
                                    # even when --deactivate-missing was not requested.
                                    if reader and reader.status=='active' and (source=='active_directory' or reader.source!='active_directory'):
                                        reader.status='suspended';reader.block_reason='Статус источника: выбыл';reader.version+=1
                                        reader.external_status=str(item.get('fields',{}).get('external_status',''))
                                        audit(s,'reader.source_suspend',reader=reader.id,source=source)
                                        counts['suspended']+=1
                                    counts['skipped']+=1
                                    continue
                                data={k:v for k,v in item.get('fields',{}).items() if k in EXTERNAL_FIELDS|{'iin','birth_date'}}
                                external_status=data.pop('external_status','')
                                validated=ReaderInput(**data).model_dump(exclude_unset=True); validated.pop('branch_ids',None)
                                if not reader and not validated.get('full_name'): raise ValueError('missing_name')
                                personal={field:(validated.get(field) if (overwrite or not reader or not getattr(reader,field)) and validated.get(field) is not None else (getattr(reader,field) if reader else None)) for field in ('iin','birth_date')}
                                personal['iin'],personal['birth_date']=validate_personal(s,personal,reader.id if reader else None)
                                with s.begin_nested():
                                    new=reader is None
                                    if new:
                                        category=validated.get('category','student' if entity=='student' else (os.getenv('AD_DEFAULT_CATEGORY','staff') if source=='active_directory' else 'teacher'))
                                        ticket,barcode=allocate_ticket(s,category,validated.get('cohort_year'),validated.get('faculty',''))
                                        reader=Reader(full_name=validated['full_name'],category=category,ticket_number=ticket,barcode=barcode,source=source,field_owners={},manual_overrides=[])
                                        s.add(reader); s.flush(); readers[reader.id]=reader
                                        audit(s,'reader.import',reader=reader.id); audit(s,'ticket.assign',reader=reader.id)
                                    owners=dict(reader.field_owners); overrides=set(reader.manual_overrides)
                                    for field,value in validated.items():
                                        if field in ('iin','birth_date'): continue
                                        if field in overrides or (owners.get(field)=='active_directory' and source!='active_directory'): continue
                                        setattr(reader,field,value); owners[field]=source
                                        if field=='gender': reader.gender_source=source
                                    for field,value in personal.items():
                                        if field not in overrides or overwrite: setattr(reader,field,value)
                                    reader.field_owners=owners; reader.last_synced_at=utcnow(); reader.updated_at=utcnow()
                                    if source=='active_directory': reader.source=source
                                    if source=='active_directory' or reader.source!='active_directory':
                                        reader.external_status=external_status
                                        if reader.status=='suspended' and reader.block_reason in ('Статус источника: выбыл','Отсутствует в подтверждённой полной выгрузке'):
                                            reader.status='active';reader.block_reason=''
                                    if not new: reader.version+=1
                                    if not identity:
                                        identity=ReaderIdentity(source=source,entity_type=entity,external_id=external,reader_id=reader.id); s.add(identity); s.flush(); identities[key]=identity
                                    identity.last_synced_at=utcnow(); seen.add(identity.id)
                                    if source=='active_directory': ad_links[reader.id]=external
                                    if link and not links.get((link['entity_type'],str(link['external_id']))):
                                        linked_identity=ReaderIdentity(source='platonus',entity_type=link['entity_type'],external_id=str(link['external_id']),reader_id=reader.id)
                                        s.add(linked_identity); s.flush(); links[(link['entity_type'],str(link['external_id']))]=linked_identity
                                    if item.get('photo') and not no_photos and owners.get('photo')!='manual' and (owners.get('photo')!='active_directory' or source=='active_directory'):
                                        store_photo(s,reader.id,base64.b64decode(item['photo'],validate=True))
                                        reader.field_owners={**owners,'photo':source}
                                    audit(s,'reader.sync',reader=reader.id,source=source,fields=sorted(validated))
                                    counts['created' if new else 'updated']+=1
                            except Exception as exc:
                                counts['errors']+=1
                                # Store error class/code only, never raw upstream messages or personal values.
                                code=str(exc) if isinstance(exc,ValueError) and str(exc) in ('invalid_identity','duplicate_source_identity','unconfirmed_cross_source_link','ambiguous_cross_source_link','missing_name') else personal_error_code(exc)
                                if not dry_run: s.add(ReaderConflict(reader_id=reader.id if reader and reader.id and s.get(Reader,reader.id) else None,run_id=run_id,source=source,entity_type=entity[:30],external_id=external[:200],code=code))
                        s.flush()
                    completed=complete and limit is None and not counts['errors']
                    safe=completed and status_confirmed and counts['read']>0 and (not baseline or len(seen & {x.id for x in existing})>=baseline*min_ratio)
                    if deactivate_missing and not safe: message='Приостановление запрещено: неполное чтение, ошибки, лимит, пустой/короткий ответ либо неподтверждённые статусы.'
                    if deactivate_missing and safe:
                        missing={x.reader_id for x in existing if x.id not in seen}
                        by_reader={}
                        for x in existing: by_reader.setdefault(x.reader_id,[]).append(x)
                        other_readers=set(s.scalars(select(ReaderIdentity.reader_id).where(ReaderIdentity.source!=source,ReaderIdentity.reader_id.in_(missing))))
                        for reader in s.scalars(select(Reader).where(Reader.id.in_(missing),Reader.status=='active').with_for_update()):
                            identities_for_reader=by_reader[reader.id]
                            other=reader.id in other_readers
                            if not other and not any(x.id in seen for x in identities_for_reader): reader.status='suspended'; reader.block_reason='Отсутствует в подтверждённой полной выгрузке'; reader.version+=1; counts['suspended']+=1
                    if dry_run: s.rollback()
                    else: s.commit()
                    processed=True
        except Exception:
            completed=False; counts['created']=counts['updated']=counts['suspended']=0; counts['errors']+=1; message='Источник или обработка недоступны. Синхронизация не завершена; отсутствующие читатели не приостановлены.'
        with factory() as s:
            run=s.get(ReaderSyncRun,run_id); run.counts=counts; run.complete=completed; run.status='error' if counts['errors'] else ('dry_run' if dry_run else 'success'); run.ended_at=utcnow(); run.message=message
            audit(s,'sync.finish',source=source,run_id=run_id,counts=counts); s.commit()
        return {'run_id':run_id,'counts':counts,'complete':completed,'processed':processed,'message':message}

def import_personal(factory,path,dry_run=False,overwrite=False):
    with factory() as probe: engine=probe.get_bind()
    counts={'updated':0,'errors':0}
    with sync_lock(engine),factory() as s,open(path,encoding='utf-8-sig',newline='') as file:
        for row in csv.DictReader(file):
            reader=None
            try:
                field=next((k for k in ('ticket_number','barcode','login') if row.get(k)),None)
                if not field: raise ValueError('Missing identity')
                matches=list(s.scalars(select(Reader).where(func.lower(getattr(Reader,field))==row[field].strip().lower()).limit(2)))
                if len(matches)!=1: raise ValueError('Ambiguous identity')
                reader=matches[0]
                if field=='login' and not s.scalar(select(ReaderIdentity.id).where(ReaderIdentity.reader_id==reader.id).limit(1)): raise ValueError('Unconfirmed login')
                values={k:(row.get(k) or None) if overwrite or not getattr(reader,k) else getattr(reader,k) for k in ('iin','birth_date')}
                iin,birthday=validate_personal(s,values,reader.id); reader.iin=iin; reader.birth_date=birthday; reader.version+=1
                reader.manual_overrides=list(set(reader.manual_overrides)|{'iin','birth_date'})
                audit(s,'reader.personal_csv',reader=reader.id); counts['updated']+=1
            except (ValueError,KeyError) as exc:
                counts['errors']+=1
                s.add(ReaderConflict(reader_id=reader.id if reader else None,source='csv',entity_type='local',external_id=str(reader.id) if reader else '',code=personal_error_code(exc)))
        if dry_run: s.rollback()
        else: s.commit()
    return counts

def logged_personal(source,operation,dry_run):
    with Session() as s:
        run=ReaderSyncRun(source=source,parameters={'dry_run':dry_run});s.add(run);s.commit();run_id=run.id
    try:
        counts=operation(); message=''
    except Exception:
        counts={'errors':1};message='Чтение или обработка не завершены; проверьте настройки источника.'
    with Session() as s:
        run=s.get(ReaderSyncRun,run_id);run.counts=counts;run.complete=not counts.get('errors');run.status='error' if counts.get('errors') else ('dry_run' if dry_run else 'success');run.ended_at=utcnow();run.message=message;audit(s,'sync.finish',source=source,run_id=run_id,counts=counts);s.commit()
    return {'run_id':run_id,'counts':counts,'message':message}

def main():
    parser=argparse.ArgumentParser(description='Синхронизация локального реестра читателей')
    parser.add_argument('source',choices=['active_directory','platonus','platonus-personal','csv'])
    parser.add_argument('--fixture'); parser.add_argument('--file'); parser.add_argument('--dry-run',action='store_true'); parser.add_argument('--limit',type=int); parser.add_argument('--no-photos',action='store_true'); parser.add_argument('--deactivate-missing',action='store_true'); parser.add_argument('--overwrite',action='store_true'); parser.add_argument('--year',type=int)
    args=parser.parse_args()
    if args.limit is not None and args.limit<1: parser.error('--limit должен быть положительным')
    if args.source=='csv' and args.limit is not None: parser.error('Для CSV предварительная проверка: --dry-run; --limit не поддерживается')
    if args.source=='csv':
        if not args.file: parser.error('--file обязателен')
        result=logged_personal('csv',lambda:import_personal(Session,args.file,args.dry_run,args.overwrite),args.dry_run)
    else:
        from .reader_sources import source_rows, personal_rows
        if args.source=='platonus-personal':
            result=logged_personal('platonus-personal',lambda:personal_rows(Session,dry_run=args.dry_run,overwrite=args.overwrite,limit=args.limit),args.dry_run)
        else:
            rows=(json.loads(line) for line in open(args.fixture,encoding='utf-8') if line.strip()) if args.fixture else source_rows(args.source,args.year,args.no_photos)
            result=synchronize(Session,args.source,rows,dry_run=args.dry_run,limit=args.limit,no_photos=args.no_photos,deactivate_missing=args.deactivate_missing,complete=True,status_confirmed=os.getenv('PLATONUS_STATUS_MAPPING_CONFIRMED' if args.source=='platonus' else 'AD_STATUS_MAPPING_CONFIRMED','false')=='true',min_ratio=float(os.getenv('READER_SYNC_MIN_RATIO','.8')),overwrite=args.overwrite)
    print(json.dumps(result,ensure_ascii=False,default=str))
    if result.get('counts',result).get('errors',0): raise SystemExit(1)
if __name__=='__main__':
    try: main()
    except Exception:
        print(json.dumps({'error':'Команда не завершена. Проверьте настройки источника, доступность, схему и журнал синхронизаций.'},ensure_ascii=False))
        raise SystemExit(1)
