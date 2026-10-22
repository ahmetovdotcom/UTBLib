"""Bounded read-only directory lookup and idempotent single-person import."""
from sqlalchemy import select
from .reader_models import ReaderIdentity
from .reader_sources import ad_rows, platonus_rows, personal_rows
from .reader_sync import synchronize


def lookup(source, search=None, identity=None):
    rows=ad_rows(search=search,identity=identity,no_photos=identity is None) if source=='active_directory' else platonus_rows(search=search,identity=identity,no_photos=identity is None)
    return [r for r in rows if not r.get('technical') and not r.get('leaver')]


def import_one(factory,source,entity,external_id):
    identity=external_id if source=='active_directory' else (entity,external_id)
    rows=lookup(source,identity=identity)
    if len(rows)!=1: raise LookupError('Человек больше не доступен в источнике. Повторите поиск.')
    result=synchronize(factory,source,rows)
    if result['counts']['errors']: raise LookupError('Карточка не загружена: проверьте журнал синхронизации и связь AD / Platonus.')
    with factory() as s:
        reader_id=s.scalar(select(ReaderIdentity.reader_id).where(ReaderIdentity.source==source,ReaderIdentity.entity_type==entity,ReaderIdentity.external_id==external_id))
    if not reader_id: raise LookupError('Карточка не загружена. Проверьте журнал синхронизации.')
    warning=''
    if source=='platonus' and entity=='student':
        try:
            if personal_rows(factory,reader_id=reader_id)['errors']: warning='Карточка загружена; персональные данные требуют проверки.'
        except Exception:
            warning='Карточка загружена; персональные данные обновятся при следующей синхронизации.'
    return {'id':reader_id,'warning':warning}
