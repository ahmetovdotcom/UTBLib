"""Persistent nightly schedule. Run as one restartable Docker service."""
import os
import time
from datetime import datetime, timedelta
from sqlalchemy import select, text
from .db import Session, engine, utcnow
from .reader_core import TZ
from .reader_models import ReaderSyncRun
from .reader_sync import synchronize, logged_personal
from .reader_sources import source_rows, personal_rows

LOCK_ID=58421947002


def due(now,runs,hour=3,minute=20):
    if (now.hour,now.minute)<(hour,minute): return False
    today=[r for r in runs if r.parameters.get('day')==now.date().isoformat()]
    if any(r.complete for r in today) or len(today)>=3: return False
    if today:
        last=max(r.started_at for r in today)
        if last.tzinfo is None: last=last.replace(tzinfo=__import__('datetime').timezone.utc)
        if now-last<timedelta(hours=1): return False
    return True


def tick(force=False):
    if os.getenv('READERS_NIGHTLY_ENABLED','false').lower()!='true': return
    now=datetime.now(TZ)
    hour,minute=map(int,os.getenv('READERS_NIGHTLY_TIME','03:20').split(':'))
    if not 0<=hour<=23 or not 0<=minute<=59: raise ValueError('Invalid schedule')
    # Session advisory lock also prevents two deployed scheduler replicas running together.
    with engine.connect().execution_options(isolation_level='AUTOCOMMIT') as lock:
        if not lock.scalar(text('SELECT pg_try_advisory_lock(:key)'),{'key':LOCK_ID}): return
        try:
            with Session() as s:
                runs=list(s.scalars(select(ReaderSyncRun).where(ReaderSyncRun.source=='nightly').order_by(ReaderSyncRun.id.desc()).limit(10)))
                if not force and not due(now,runs,hour,minute): return
                for old in runs:
                    if old.status=='running':
                        old.status='error';old.ended_at=utcnow();old.message='Процесс был прерван. Повторный запуск безопасен.'
                run=ReaderSyncRun(source='nightly',parameters={'day':now.date().isoformat(),'timezone':'Asia/Almaty','time':f'{hour:02}:{minute:02}'})
                s.add(run);s.commit();run_id=run.id
            complete=False; results={}; message=''
            try:
                enabled=[source for source,key in [('active_directory','AD_ENABLED'),('platonus','PLATONUS_ENABLED')] if os.getenv(key,'false').lower()=='true']
                if not enabled: raise RuntimeError('No sources')
                for source in enabled:
                    result=synchronize(Session,source,source_rows(source),complete=True)
                    results[source]=result['counts']
                    if not result.get('processed') or not result['counts']['read']: raise RuntimeError('Source incomplete')
                if 'platonus' in enabled:
                    result=logged_personal('platonus-personal',lambda:personal_rows(Session),False)
                    results['platonus-personal']=result['counts']
                    if result.get('message'): raise RuntimeError('Personal source incomplete')
                complete=True
                if any(c.get('errors',0) for c in results.values()): message='Обновление выполнено; отдельные карточки требуют проверки в журнале.'
            except Exception:
                message='Обновление не завершено. Повтор через час, не более трёх попыток в день. Проверьте доступность источников.'
            with Session() as s:
                run=s.get(ReaderSyncRun,run_id);run.complete=complete;run.counts=results;run.ended_at=utcnow();run.status='success' if complete else 'error';run.message=message;s.commit()
        finally:
            lock.execute(text('SELECT pg_advisory_unlock(:key)'),{'key':LOCK_ID})


def main():
    while True:
        try: tick()
        except Exception: print('Ночное обновление: проверьте подключение и настройки расписания.',flush=True)
        time.sleep(30)

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--run-now',action='store_true',help='Один запуск сейчас, с записью в журнал')
    args=parser.parse_args()
    if args.run_now: tick(force=True)
    else: main()
