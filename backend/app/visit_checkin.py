"""Branch QR check-in. A QR identifies a place, never a person or an account."""
import hashlib
import hmac
import json
import os
import secrets
import time
import unicodedata
from datetime import timedelta
from urllib.parse import urlsplit
from uuid import UUID

import qrcode
from qrcode.image.svg import SvgPathImage
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from .acquisitions import lock_request
from .db import get_db, utcnow
from .reader_core import audit, rate_limit
from .reader_models import Branch, LibraryVisit, Reader, VisitQrPoint
from .student_bridge import reader_for_subject, iso

public_router = APIRouter(prefix='/api/check-in/v1')


class PointInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    base_url: str = Field(max_length=250)
    rotate: bool = False
    enabled: bool | None = None

    @field_validator('base_url')
    @classmethod
    def origin(cls, value):
        parsed = urlsplit(value.strip())
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment or parsed.path not in ('', '/')):
            raise ValueError('Введите адрес сайта библиотеки без пути, например https://elibrary.kaztbu.edu.kz')
        return value.strip().rstrip('/')


class CheckIn(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    token: str = Field(pattern=r'^[A-Za-z0-9_-]{43}$')
    full_name: str | None = Field(default=None, min_length=2, max_length=300)
    study_group: str | None = Field(default=None, min_length=1, max_length=150)
    course: int | None = Field(default=None, ge=1, le=20, strict=True)

    @field_validator('full_name', 'study_group')
    @classmethod
    def text(cls, value):
        if value is None:
            return value
        value = ' '.join(value.split())
        if not value or any(unicodedata.category(c).startswith('C') for c in value):
            raise ValueError('Введите корректное значение')
        return value


def active_point(s, token):
    point = s.scalar(select(VisitQrPoint).where(VisitQrPoint.token == token, VisitQrPoint.enabled.is_(True)))
    branch = s.get(Branch, point.branch_id) if point else None
    if not branch or not branch.active:
        raise HTTPException(404, 'QR-код недействителен. Обратитесь к сотруднику библиотеки.')
    return branch


def record_visit(s, branch_id, *, reader=None, actor=None, source='qr_account', guest=None, guest_key=None, notes=''):
    # Same lock is also used by the staff scanner. Different branches are distinct visits.
    identity = f'reader:{reader.id}' if reader else f'guest:{guest_key}'
    lock_request(s, 'visit:', identity + ':' + str(branch_id))
    now = utcnow()
    condition = LibraryVisit.reader_id == reader.id if reader else LibraryVisit.guest_key == guest_key
    previous = s.scalar(select(LibraryVisit).where(condition, LibraryVisit.branch_id == branch_id,
        LibraryVisit.scanned_at >= now - timedelta(minutes=10)).order_by(LibraryVisit.scanned_at.desc()).limit(1))
    visit = previous
    if visit is None:
        visit = LibraryVisit(reader_id=reader.id if reader else None, branch_id=branch_id,
            scanned_by=actor, scanned_at=now, source=source, notes=notes,
            guest_name=guest.full_name if guest else None, guest_group=guest.study_group if guest else None,
            guest_course=guest.course if guest else None, guest_key=guest_key)
        s.add(visit); s.flush()
        audit(s, 'visit.record', actor, reader.id if reader else None, visit_id=visit.id, source=source)
    return visit, previous is not None


@public_router.get('/points/{token}')
def point_info(token: str, s=Depends(get_db)):
    if len(token) != 43:
        raise HTTPException(404, 'QR-код недействителен')
    from .events import event_by_token, public_info
    event = event_by_token(s, token)
    if event is not None: return public_info(event)
    branch = active_point(s, token)
    return {'name': branch.name}


async def assertion(request: Request):
    key = os.getenv('STUDENT_BRIDGE_KEY', '')
    if len(key) < 32:
        raise HTTPException(503, 'Student integration is not configured')
    raw = await request.body()
    if len(raw) > 4096:
        raise HTTPException(413, 'Запрос слишком большой')
    subject = request.headers.get('x-reader-subject', '')
    stamp = request.headers.get('x-reader-time', '')
    signature = request.headers.get('x-reader-signature', '')
    try:
        guid = subject.removeprefix('guest:')
        if str(UUID(guid)) != guid or abs(time.time() - int(stamp)) > 60:
            raise ValueError()
    except (ValueError, TypeError):
        raise HTTPException(401, 'Invalid assertion')
    message = '\n'.join(('visit-v1', request.method, request.url.path,
        request.scope['query_string'].decode('ascii'), subject, stamp, hashlib.sha256(raw).hexdigest()))
    expected = hmac.new(key.encode(), message.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(401, 'Invalid assertion')
    return subject


@public_router.post('/visits')
def check_in(body: CheckIn, subject=Depends(assertion), s=Depends(get_db)):
    # Public browsers cannot sign requests. library supplies either the verified AD
    # subject or its own anonymous session UUID; guest data grants no account access.
    rate_limit(s, subject, 'qr-visit', 15)
    from .events import event_by_token, record_attendance
    event = event_by_token(s, body.token)
    if event is None:
        branch = active_point(s, body.token)
        lock_request(s, 'visit-point:', branch.id)
        s.expire_all()
        branch = active_point(s, body.token)
    def save(**kwargs):
        if event is not None:
            return record_attendance(s, event.id, token=body.token, **kwargs)
        return record_visit(s, branch.id, **kwargs)
    if subject.startswith('guest:'):
        if body.full_name is None or body.study_group is None or body.course is None:
            raise HTTPException(422, 'Заполните ФИО, группу и курс')
        data = json.dumps([subject, body.full_name.casefold(), body.study_group.casefold(), body.course], ensure_ascii=False)
        key = hmac.new(os.environ['STUDENT_BRIDGE_KEY'].encode(), data.encode(), hashlib.sha256).hexdigest()
        visit, duplicate = save(source='qr_guest', guest=body, guest_key=key)
    else:
        if any(v is not None for v in (body.full_name, body.study_group, body.course)):
            raise HTTPException(422, 'Данные читателя берутся из его учётной записи')
        reader = reader_for_subject(s, subject)
        visit, duplicate = save(reader=reader)
    result = {'duplicate': duplicate, 'scanned_at': iso(visit.scanned_at), 'branch': event.title if event is not None else branch.name,
              'verification': 'self_reported' if subject.startswith('guest:') else 'account'}
    if event is not None: result['kind'] = 'event'
    s.commit()
    return result


def make_staff_router(auth):
    router = APIRouter(prefix='/api/visits/qr-points')

    @router.post('/{branch_id}')
    def prepare(branch_id: int, body: PointInput, user=Depends(auth), s=Depends(get_db)):
        branch = s.get(Branch, branch_id)
        if not branch or not branch.active:
            raise HTTPException(422, 'Выберите действующий пункт обслуживания')
        lock_request(s, 'visit-point:', branch.id)
        point = s.get(VisitQrPoint, branch.id)
        if point is None:
            point = VisitQrPoint(branch_id=branch.id, token=secrets.token_urlsafe(32))
            s.add(point)
        elif body.rotate:
            point.token = secrets.token_urlsafe(32)
        if body.enabled is not None:
            point.enabled = body.enabled
        elif point.enabled is None:
            point.enabled = True
        link = body.base_url + '/visit/' + point.token
        qr = qrcode.make(link, image_factory=SvgPathImage, border=4)
        result = {'name': branch.name, 'link': link, 'enabled': point.enabled, 'qr_svg': qr.to_string(encoding='unicode')}
        audit(s, 'visit.qr.configure', user.id, branch_id=branch.id, rotated=body.rotate, enabled=point.enabled)
        s.commit()
        return result

    return router
