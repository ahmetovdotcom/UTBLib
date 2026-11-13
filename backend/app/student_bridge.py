"""Read-only personal cabinet for the trusted library frontend.

AD credentials stay in library. Every request carries a short-lived HMAC assertion
for the AD objectGUID verified at sign-in, never a browser-supplied reader ID.
The integration key grants no staff/import privileges and is not sent to browsers.
"""
import hashlib
import hmac
import os
import time
from datetime import timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func, select

from .db import AcquisitionLine, Copy, Record, get_db, utcnow
from .reader_models import Branch, LibraryVisit, Reader, ReaderIdentity, ReaderPhoto
from .circulation_models import ACTIVE_RESERVATIONS, Fine, Incident, Loan, Reservation
from .public_catalog import values

router = APIRouter(prefix='/api/student/v1', tags=['Student frontend'])


def authenticated_subject(request: Request):
    key = os.getenv('STUDENT_BRIDGE_KEY', '')
    if len(key) < 32:
        raise HTTPException(503, 'Student integration is not configured')
    subject = request.headers.get('x-reader-subject', '')
    stamp = request.headers.get('x-reader-time', '')
    signature = request.headers.get('x-reader-signature', '')
    try:
        if str(UUID(subject)) != subject or abs(time.time() - int(stamp)) > 60:
            raise ValueError()
    except (ValueError, TypeError):
        raise HTTPException(401, 'Invalid assertion')
    message = '\n'.join((request.method, request.url.path,
                         request.scope['query_string'].decode('ascii'), subject, stamp))
    expected = hmac.new(key.encode(), message.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(401, 'Invalid assertion')
    return subject


def authenticated_reader(subject=Depends(authenticated_subject), s=Depends(get_db)):
    return reader_for_subject(s, subject)


def reader_for_subject(s, subject):
    # No fuzzy name/login/email matching, no implicit registration or ticket issuance.
    ids = list(s.scalars(select(ReaderIdentity.reader_id).where(
        ReaderIdentity.source == 'active_directory', ReaderIdentity.entity_type == 'ad_user',
        func.lower(ReaderIdentity.external_id) == subject)).unique())
    if len(ids) != 1:
        raise HTTPException(404 if not ids else 409, 'Reader identity is not linked')
    reader = s.get(Reader, ids[0])
    if reader is None:
        raise HTTPException(404, 'Reader identity is not linked')
    return reader


def iso(value):
    return value.replace(tzinfo=timezone.utc).isoformat() if value and hasattr(value, 'hour') and value.tzinfo is None else value.isoformat() if value else None


def book(s, copy_id=None, record_id=None):
    copy = s.get(Copy, copy_id) if copy_id else None
    if copy:
        line = s.get(AcquisitionLine, copy.line_id) if copy.line_id else None
        record_id = copy.record_id or (line.record_id if line else None)
    record = s.get(Record, record_id) if record_id else None
    marc = record.marc if record else {}
    return {'book_id': f'utblib-{record_id}' if record else None,
            'title': ' · '.join(values(marc, '245', 'a')) or '—',
            'author': ' · '.join(values(marc, '100', 'a')),
            'inventory_number': copy.inventory_number if copy else ''}


def branch(s, branch_id):
    row = s.get(Branch, branch_id) if branch_id else None
    return row.name if row else ''


def serialize(s, row):
    if isinstance(row, Loan):
        overdue = row.closed_at is None and row.due_at.replace(tzinfo=timezone.utc) < utcnow()
        return {**book(s, copy_id=row.copy_id), 'id': row.id,
                'status': 'overdue' if overdue else row.status, 'issued_at': iso(row.issued_at),
                'due_at': iso(row.due_at), 'returned_at': iso(row.returned_at),
                'closed_at': iso(row.closed_at), 'renewal_count': row.renewal_count,
                'branch': branch(s, row.branch_id)}
    if isinstance(row, Reservation):
        return {**book(s, record_id=row.record_id), 'id': row.id, 'status': row.status,
                'created_at': iso(row.created_at), 'expires_at': iso(row.expires_at),
                'branch': branch(s, row.pickup_branch_id)}
    if isinstance(row, Fine):
        return {**book(s, copy_id=row.copy_id), 'id': row.id, 'status': row.status,
                'amount': str(row.amount), 'currency': row.currency, 'reason': row.reason,
                'charged_at': iso(row.charged_at), 'resolved_at': iso(row.resolved_at)}
    if isinstance(row, Incident):
        return {**book(s, copy_id=row.copy_id), 'id': row.id, 'status': row.status,
                'kind': row.kind, 'created_at': iso(row.created_at), 'resolved_at': iso(row.resolved_at)}
    return {'scanned_at': iso(row.scanned_at), 'branch': branch(s, row.branch_id)}


@router.get('/me')
def cabinet(response: Response,
            section: Literal['overview', 'loans', 'history', 'reservations', 'fines', 'incidents', 'visits', 'profile', 'card'] = 'overview',
            page: int = Query(1, ge=1, le=1000000), reader=Depends(authenticated_reader), s=Depends(get_db)):
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    statements = {
        'loans': select(Loan).where(Loan.reader_id == reader.id, Loan.closed_at.is_(None)).order_by(Loan.due_at, Loan.id),
        'history': select(Loan).where(Loan.reader_id == reader.id, Loan.closed_at.is_not(None)).order_by(Loan.closed_at.desc(), Loan.id.desc()),
        'reservations': select(Reservation).where(Reservation.reader_id == reader.id).order_by(Reservation.created_at.desc(), Reservation.id.desc()),
        'fines': select(Fine).where(Fine.reader_id == reader.id).order_by(Fine.charged_at.desc(), Fine.id.desc()),
        'incidents': select(Incident).where(Incident.reader_id == reader.id).order_by(Incident.created_at.desc(), Incident.id.desc()),
        'visits': select(LibraryVisit).where(LibraryVisit.reader_id == reader.id).order_by(LibraryVisit.scanned_at.desc(), LibraryVisit.id.desc()),
    }
    count = lambda stmt: s.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    overdue = statements['loans'].where(Loan.due_at < utcnow())
    pending = select(Fine).where(Fine.reader_id == reader.id, Fine.status == 'pending')
    summary = {
        'loans': count(statements['loans']), 'history': count(statements['history']), 'overdue': count(overdue),
        'reservations': count(statements['reservations'].where(Reservation.status.in_(ACTIVE_RESERVATIONS))),
        'fines': count(pending), 'incidents': count(statements['incidents'].where(Incident.status == 'open')),
        'visits': count(statements['visits']),
        'fine_totals': [{'currency': currency, 'amount': str(amount)} for currency, amount in s.execute(
            select(Fine.currency, func.sum(Fine.amount)).where(Fine.reader_id == reader.id, Fine.status == 'pending').group_by(Fine.currency))],
        'next_due_at': iso(s.scalar(select(func.min(Loan.due_at)).where(Loan.reader_id == reader.id, Loan.closed_at.is_(None)))),
    }
    profile = {name: getattr(reader, name) for name in (
        'full_name', 'ticket_number', 'barcode', 'category', 'status', 'block_reason', 'email', 'phone',
        'faculty', 'department', 'study_group', 'education_level', 'education_program', 'course', 'position')}
    profile.update(valid_until=iso(reader.valid_until), last_synced_at=iso(reader.last_synced_at),
                   has_photo=s.scalar(select(ReaderPhoto.reader_id).where(ReaderPhoto.reader_id == reader.id)) is not None)
    stmt = statements.get('loans' if section == 'overview' else section)
    total = count(stmt) if stmt is not None else 0
    items = [serialize(s, row) for row in s.scalars(stmt.offset((page-1)*50).limit(50))] if stmt is not None else []
    return {'profile': profile, 'summary': summary, 'data': items,
            'meta': {'page': page, 'per_page': 50, 'total': total, 'last_page': max(1, (total+49)//50)}}


@router.get('/photo')
def photo(reader=Depends(authenticated_reader), s=Depends(get_db)):
    row = s.get(ReaderPhoto, reader.id)
    if not row:
        raise HTTPException(404)
    from io import BytesIO
    from PIL import Image
    try:
        kind = Image.open(BytesIO(row.content)).format
        media = {'JPEG': 'image/jpeg', 'PNG': 'image/png', 'WEBP': 'image/webp'}[kind]
    except Exception:
        raise HTTPException(404)
    return Response(row.content, media_type=media, headers={'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'})
