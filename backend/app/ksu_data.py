"""One copy belongs to at most one KSU. Both reports use the same live members."""
from types import SimpleNamespace
from sqlalchemy import select, func, or_
from fastapi import HTTPException
from .db import KsuEntry, Copy, AcquisitionLine, Acquisition, Record


def entries_query():
    return select(KsuEntry).outerjoin(Acquisition, Acquisition.id == KsuEntry.acquisition_id).where(
        or_(KsuEntry.acquisition_id.is_(None), Acquisition.status == 'posted',
            select(Copy.id).where(Copy.ksu_entry_id == KsuEntry.id, Copy.status != 'cancelled').exists()))


def entry_output(e):
    return {'id': e.id, 'version': e.version, 'acquisition_id': e.acquisition_id,
            'number': e.number, 'year': e.year, 'label': f'{e.number}/{e.year}',
            'registered_on': e.registered_on.isoformat(),
            'document_on': e.document_on.isoformat() if e.document_on else None,
            'source': e.source, 'invoice': e.invoice, 'note': e.note}


def validate_entry(s, id):
    if id is None:
        return
    e = s.scalar(entries_query().where(KsuEntry.id == id))
    if not e:
        raise HTTPException(422, 'КСУ не найдена или относится к отменённому поступлению. Обновите список.')


def member_query(ids):
    return (select(Copy, AcquisitionLine, Record).outerjoin(AcquisitionLine, Copy.line_id == AcquisitionLine.id)
            .outerjoin(Acquisition, Acquisition.id == AcquisitionLine.acquisition_id)
            .join(Record, Record.id == func.coalesce(Copy.record_id, AcquisitionLine.record_id))
            .where(Copy.ksu_entry_id.in_(ids), Copy.status != 'cancelled',
                   or_(Copy.line_id.is_(None), Acquisition.status == 'posted')))


def grouped_members(s, ids):
    """Group equal prices within a record; withdrawn copies remain historic receipts."""
    groups = {}
    if not ids:
        return groups
    for c, line, record in s.execute(member_query(ids).order_by(Copy.id)):
        price = line.unit_price if line else c.unit_price
        currency = line.currency if line else c.currency
        key = (c.ksu_entry_id, record.id, price, currency)
        if key not in groups:
            groups[key] = (SimpleNamespace(id=line.id if line else None, quantity=0, unit_price=price,
                currency=currency, title_snapshot=line.title_snapshot if line else '', copy_ids=[]), record)
        group = groups[key][0]
        group.quantity += 1
        group.copy_ids.append(c.id)
    by_entry = {}
    for (entry_id, *_), pair in groups.items():
        by_entry.setdefault(entry_id, []).append(pair)
    return by_entry
