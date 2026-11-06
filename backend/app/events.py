"""Staff event registry and separate, once-per-event attendance."""
import csv
import io
import secrets
from datetime import date, datetime
from typing import Literal
from urllib.parse import urlsplit

import qrcode
from qrcode.image.svg import SvgPathImage
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import func, or_, select

from . import attendance
from .acquisitions import lock_request
from .db import get_db, utcnow
from .event_models import EventAttendance, LibraryEvent
from .reader_core import TZ, audit, lookup, rate_limit
from .reader_models import Branch
from .visit_checkin import PointInput

STATUSES = {'planned': 'Запланировано', 'completed': 'Завершено', 'cancelled': 'Отменено'}
EVENT_RULES = ('Участник с читательским билетом учитывается один раз за мероприятие независимо от способа отметки. '
    'Повторные отметки гостя с теми же данными в том же браузере исключаются. '
    'Гость с другого устройства или с изменёнными данными может учитываться повторно; личность не подтверждена. '
    'Отметки мероприятий не включены в обычную посещаемость библиотеки. ' + attendance.RULES)


class EventInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=500)
    date_from: date
    date_to: date
    format: str = Field(default='', max_length=150)
    branch_id: int = Field(gt=0)
    location: str = Field(default='', max_length=300)
    responsible: str = Field(default='', max_length=500)
    coorganizers: str = Field(default='', max_length=500)
    protocol: bool = False
    protocol_url: str = Field(default='', max_length=2000)
    instagram_url: str = Field(default='', max_length=2000)
    notes: str = Field(default='', max_length=10000)
    status: Literal['planned', 'completed', 'cancelled'] = 'planned'

    @field_validator('protocol_url', 'instagram_url')
    @classmethod
    def web_url(cls, value):
        if value:
            parsed = urlsplit(value)
            if parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError('Укажите ссылку http:// или https://')
        return value

    @model_validator(mode='after')
    def dates(self):
        if not date(1900, 1, 1) <= self.date_from <= self.date_to <= date(2200, 12, 31):
            raise ValueError('Укажите корректные даты мероприятия')
        if (self.date_to - self.date_from).days > 365:
            raise ValueError('Продолжительность мероприятия — не более года')
        return self


class EventUpdate(EventInput):
    version: int = Field(ge=1)


class ScanInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    code: str = Field(min_length=1, max_length=100)


def get_event(s, event_id, *, lock=False):
    if lock:
        lock_request(s, 'event:', event_id)
    event = s.get(LibraryEvent, event_id, populate_existing=True)
    if event is None or event.deleted_at is not None:
        raise HTTPException(404, 'Мероприятие не найдено')
    return event


def event_by_token(s, token):
    return s.scalar(select(LibraryEvent).where(LibraryEvent.qr_token == token,
        LibraryEvent.qr_enabled.is_(True), LibraryEvent.deleted_at.is_(None)))


def available(event):
    return event.status == 'planned' and event.date_from <= datetime.now(TZ).date() <= event.date_to


def public_info(event):
    return {'name': event.title, 'kind': 'event', 'date_from': str(event.date_from),
            'date_to': str(event.date_to), 'location': event.location, 'can_check_in': available(event)}


def record_attendance(s, event_id, *, reader=None, actor=None, source='qr_account', guest=None, guest_key=None, token=None):
    event = get_event(s, event_id, lock=True)
    if token is not None and (event.qr_token != token or not event.qr_enabled):
        raise HTTPException(404, 'QR-код недействителен')
    if not available(event):
        raise HTTPException(409, 'Отметка доступна только в даты проведения незавершённого мероприятия')
    condition = EventAttendance.reader_id == reader.id if reader else EventAttendance.guest_key == guest_key
    previous = s.scalar(select(EventAttendance).where(EventAttendance.event_id == event.id, condition))
    if previous is not None:
        return previous, True
    row = EventAttendance(event_id=event.id, branch_id=event.branch_id, reader_id=reader.id if reader else None,
        scanned_by=actor, source=source, guest_key=guest_key,
        guest_name=guest.full_name if guest else None, guest_group=guest.study_group if guest else None,
        guest_course=guest.course if guest else None)
    s.add(row); s.flush()
    audit(s, 'event.attendance', actor, reader.id if reader else None, event_id=event.id, attendance_id=row.id, source=source)
    return row, False


def serialize(s, event, count=None):
    result = {key: getattr(event, key) for key in EventInput.model_fields}
    result.update(id=event.id, version=event.version, qr_enabled=event.qr_enabled,
                  branch=s.get(Branch, event.branch_id).name, can_check_in=available(event))
    result['participants'] = count if count is not None else s.scalar(select(func.count(EventAttendance.id)).where(EventAttendance.event_id == event.id))
    return result


def validate_branch(s, branch_id, previous=None):
    branch = s.get(Branch, branch_id)
    if not branch or (not branch.active and branch_id != previous):
        raise HTTPException(422, 'Выберите действующий пункт обслуживания')


def scope(event_id):
    return (EventAttendance.event_id == event_id,)


def event_report(s, event, f):
    result = attendance.report(s, f, EventAttendance, scope(event.id))
    result.update(title='Участие в мероприятии: ' + event.title, rules=EVENT_RULES)
    return result


def make_router(auth):
    router = APIRouter(prefix='/api/events', dependencies=[Depends(auth)])

    def selection(q='', date_from: date | None = None, date_to: date | None = None,
                  branch_id: int | None = None, status: Literal['planned', 'completed', 'cancelled'] | None = None):
        if date_from and date_to and date_from > date_to:
            raise HTTPException(422, 'Начало периода позже окончания')
        stmt = select(LibraryEvent).where(LibraryEvent.deleted_at.is_(None))
        if q:
            pattern = '%' + q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
            stmt = stmt.where(or_(*(c.ilike(pattern, escape='\\') for c in (LibraryEvent.title, LibraryEvent.format, LibraryEvent.responsible, LibraryEvent.coorganizers))))
        if date_from: stmt = stmt.where(LibraryEvent.date_to >= date_from)
        if date_to: stmt = stmt.where(LibraryEvent.date_from <= date_to)
        if branch_id: stmt = stmt.where(LibraryEvent.branch_id == branch_id)
        if status: stmt = stmt.where(LibraryEvent.status == status)
        return stmt

    @router.get('')
    def listing(q: str = Query('', max_length=200), date_from: date | None = None, date_to: date | None = None,
                branch_id: int | None = None, status: Literal['planned', 'completed', 'cancelled'] | None = None,
                offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), s=Depends(get_db)):
        stmt = selection(q, date_from, date_to, branch_id, status)
        total = s.scalar(select(func.count()).select_from(stmt.subquery()))
        ids = stmt.with_only_columns(LibraryEvent.id)
        participants = s.scalar(select(func.count(EventAttendance.id)).where(EventAttendance.event_id.in_(ids)))
        events = s.scalars(stmt.order_by(LibraryEvent.date_from.desc(), LibraryEvent.id.desc()).offset(offset).limit(limit)).all()
        counts = dict(s.execute(select(EventAttendance.event_id, func.count(EventAttendance.id)).where(EventAttendance.event_id.in_([e.id for e in events])).group_by(EventAttendance.event_id)).all())
        return {'items': [serialize(s, e, counts.get(e.id, 0)) for e in events], 'total': total, 'participants': participants}

    @router.get('/options')
    def options(s=Depends(get_db)):
        return {'branches': [{'id': b.id, 'name': b.name, 'active': b.active} for b in s.scalars(select(Branch).order_by(Branch.position, Branch.name))],
                'formats': list(s.scalars(select(LibraryEvent.format).where(LibraryEvent.format != '', LibraryEvent.deleted_at.is_(None)).distinct().order_by(LibraryEvent.format))),
                'statuses': STATUSES}

    @router.get('/export')
    def export_registry(q: str = Query('', max_length=200), date_from: date | None = None, date_to: date | None = None,
                        branch_id: int | None = None, status: Literal['planned', 'completed', 'cancelled'] | None = None,
                        format: Literal['xlsx', 'csv'] = 'xlsx', s=Depends(get_db)):
        from .readers import safe_cell
        stmt = selection(q, date_from, date_to, branch_id, status)
        table = [['№', 'Название мероприятия', 'Дата с', 'Дата по', 'Формат', 'Посетителей', 'Протокол', 'Ссылка на протокол', 'Instagram', 'Ответственный', 'Соорганизаторы', 'Примечания', 'Пункт', 'Место', 'Статус']]
        counts = dict(s.execute(select(EventAttendance.event_id, func.count(EventAttendance.id)).where(EventAttendance.event_id.in_(stmt.with_only_columns(LibraryEvent.id))).group_by(EventAttendance.event_id)).all())
        branches = {b.id: b.name for b in s.scalars(select(Branch))}
        for i, e in enumerate(s.scalars(stmt.order_by(LibraryEvent.date_from, LibraryEvent.id)), 1):
            table.append([i, e.title, str(e.date_from), str(e.date_to), e.format, counts.get(e.id, 0), '+' if e.protocol else '', e.protocol_url, e.instagram_url, e.responsible, e.coorganizers, e.notes, branches[e.branch_id], e.location, STATUSES[e.status]])
        table = [[safe_cell(v) if isinstance(v, str) else v for v in row] for row in table]
        headers = {'Content-Disposition': f'attachment; filename="events.{format}"'}
        if format == 'csv':
            out = io.StringIO(); csv.writer(out, delimiter=';').writerows(table)
            return Response('\ufeff' + out.getvalue(), media_type='text/csv; charset=utf-8', headers=headers)
        from openpyxl import Workbook
        from openpyxl.styles import Font, Alignment
        from openpyxl.utils import get_column_letter
        wb = Workbook(); ws = wb.active; ws.title = 'Мероприятия'
        for row in table: ws.append(row)
        for cell in ws[1]: cell.font = Font(bold=True)
        for row in ws:
            for cell in row: cell.alignment = Alignment(wrap_text=True, vertical='top')
        for i in range(1, 16): ws.column_dimensions[get_column_letter(i)].width = 24
        ws.column_dimensions['B'].width = 50; ws.freeze_panes = 'C2'; ws.auto_filter.ref = ws.dimensions
        out = io.BytesIO(); wb.save(out)
        return Response(out.getvalue(), media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', headers=headers)

    @router.post('')
    def create(body: EventInput, user=Depends(auth), s=Depends(get_db)):
        validate_branch(s, body.branch_id)
        event = LibraryEvent(**body.model_dump()); s.add(event); s.flush()
        audit(s, 'event.create', user.id, event_id=event.id); s.commit()
        return serialize(s, event)

    @router.get('/{event_id}')
    def detail(event_id: int, s=Depends(get_db)):
        return serialize(s, get_event(s, event_id))

    @router.put('/{event_id}')
    def update(event_id: int, body: EventUpdate, user=Depends(auth), s=Depends(get_db)):
        event = get_event(s, event_id, lock=True)
        if event.version != body.version: raise HTTPException(409, 'Мероприятие уже изменено. Откройте карточку заново.')
        validate_branch(s, body.branch_id, event.branch_id)
        for key, value in body.model_dump(exclude={'version'}).items(): setattr(event, key, value)
        event.version += 1; event.updated_at = utcnow()
        audit(s, 'event.update', user.id, event_id=event.id); s.commit()
        return serialize(s, event)

    @router.delete('/{event_id}')
    def delete(event_id: int, version: int = Query(ge=1), user=Depends(auth), s=Depends(get_db)):
        event = get_event(s, event_id, lock=True)
        if event.version != version: raise HTTPException(409, 'Мероприятие уже изменено. Обновите список.')
        event.deleted_at = utcnow(); event.qr_enabled = False; event.version += 1
        audit(s, 'event.delete', user.id, event_id=event.id); s.commit()
        return {'ok': True}

    @router.post('/{event_id}/qr')
    def prepare_qr(event_id: int, body: PointInput, user=Depends(auth), s=Depends(get_db)):
        event = get_event(s, event_id, lock=True)
        if not event.qr_token:
            event.qr_token = secrets.token_urlsafe(32); event.qr_enabled = True
        elif body.rotate: event.qr_token = secrets.token_urlsafe(32)
        if body.enabled is not None: event.qr_enabled = body.enabled
        link = body.base_url + '/visit/' + event.qr_token
        qr = qrcode.make(link, image_factory=SvgPathImage, border=4)
        result = {'name': event.title, 'link': link, 'enabled': event.qr_enabled, 'qr_svg': qr.to_string(encoding='unicode')}
        audit(s, 'event.qr.configure', user.id, event_id=event.id, rotated=body.rotate, enabled=event.qr_enabled)
        s.commit(); return result

    @router.post('/{event_id}/attendance')
    def scan(event_id: int, body: ScanInput, user=Depends(auth), s=Depends(get_db)):
        rate_limit(s, user.id, 'event-scan', 180)
        reader = lookup(s, body.code)
        row, duplicate = record_attendance(s, event_id, reader=reader, actor=user.id, source='desk')
        result = {'duplicate': duplicate, 'full_name': reader.full_name, 'scanned_at': row.scanned_at}
        s.commit(); return result

    @router.get('/{event_id}/report/options')
    def report_options(event_id: int, s=Depends(get_db)):
        get_event(s, event_id)
        return attendance.options(s, EventAttendance)

    @router.get('/{event_id}/report')
    def report(event_id: int, f=Depends(attendance.parse_filters), s=Depends(get_db)):
        return event_report(s, get_event(s, event_id), f)

    @router.get('/{event_id}/report/export')
    def export(event_id: int, format: Literal['xlsx', 'csv'] = 'xlsx', f=Depends(attendance.parse_filters), s=Depends(get_db)):
        data = event_report(s, get_event(s, event_id), f)
        return attendance.export_report(data, f, format, attendance.options(s, EventAttendance)['filters'])

    @router.get('/{event_id}/report/journal')
    def journal(event_id: int, f=Depends(attendance.parse_filters), offset: int = Query(0, ge=0),
                limit: int = Query(50, ge=1, le=100), s=Depends(get_db)):
        get_event(s, event_id)
        return attendance.journal_report(s, f, offset, limit, EventAttendance, scope(event_id))

    return router
