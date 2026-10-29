"""Staff-managed publications; only explicitly published content leaves this boundary."""
from datetime import datetime, timezone
from io import BytesIO
import re
from typing import Literal
from urllib.parse import urlsplit, quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import DateTime, ForeignKey, Integer, JSON, LargeBinary, String, UniqueConstraint, select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base, get_db, utcnow
from .security import auth

Kind = Literal['resources', 'repository', 'news', 'events']
PUBLIC_PATHS = frozenset({'/api/public/v1/content/{kind}', '/api/public/v1/content/{kind}/{identifier}', '/api/public/v1/content-assets/{item_id}/{slot}'})


class SiteContent(Base):
    __tablename__ = 'site_content'
    __table_args__ = (UniqueConstraint('kind', 'slug', name='uq_site_content_slug'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), index=True)
    slug: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(20), default='draft')
    version: Mapped[int] = mapped_column(Integer, default=1)
    data: Mapped[dict] = mapped_column(JSON)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SiteAsset(Base):
    __tablename__ = 'site_assets'
    __table_args__ = (UniqueConstraint('item_id', 'slot', name='uq_site_asset_slot'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey('site_content.id', ondelete='CASCADE'))
    slot: Mapped[str] = mapped_column(String(10))
    name: Mapped[str] = mapped_column(String(200))
    mime: Mapped[str] = mapped_column(String(50))
    size: Mapped[int] = mapped_column(Integer)
    content: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)


class SiteAudit(Base):
    __tablename__ = 'site_content_audit'
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey('site_content.id'))
    actor_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    action: Mapped[str] = mapped_column(String(30))
    snapshot: Mapped[dict] = mapped_column(JSON)


class Translation(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    title: str = Field(default='', max_length=500)
    description: str = Field(default='', max_length=5000)
    body: str = Field(default='', max_length=100000)
    instructions: str = Field(default='', max_length=10000)
    venue: str = Field(default='', max_length=500)
    image_alt: str = Field(default='', max_length=500)


class Details(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    translations: dict[Literal['ru', 'kk', 'en'], Translation] = Field(default_factory=dict)
    featured: bool = False
    category: str = Field(default='', max_length=100)
    url: str = Field(default='', max_length=2000)
    provider: str = Field(default='', max_length=300)
    resource_type: Literal['licensed', 'open_access', 'partner', 'internal'] = 'open_access'
    access_type: Literal['open', 'campus', 'remote_auth'] = 'open'
    content_types: list[str] = Field(default_factory=list, max_length=30)
    audiences: list[Literal['guest', 'student', 'teacher', 'library_staff']] = Field(default_factory=list, max_length=4)
    expires_on: str = Field(default='', max_length=10)
    news_type: Literal['announcement', 'update'] = 'announcement'
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    registration_url: str = Field(default='', max_length=2000)
    online_url: str = Field(default='', max_length=2000)
    organizer: str = Field(default='', max_length=500)
    authors: list[str] = Field(default_factory=list, max_length=100)
    keywords: list[str] = Field(default_factory=list, max_length=100)
    work_type: Literal['bachelor_thesis', 'master_thesis', 'phd_dissertation', 'scientific_article', 'research_report', 'university_publication', 'thesis_abstract'] = 'scientific_article'
    year: int | None = Field(default=None, ge=1000, le=2200)
    language: Literal['ru', 'kk', 'en', 'other'] = 'ru'
    faculty: str = Field(default='', max_length=500)
    department: str = Field(default='', max_length=500)
    educational_programme: str = Field(default='', max_length=500)
    supervisor: str = Field(default='', max_length=500)
    udc_code: str = Field(default='', max_length=100)
    university: str = Field(default='', max_length=500)
    doi: str = Field(default='', max_length=500)
    source: str = Field(default='', max_length=1000)
    rights_holder: str = Field(default='', max_length=500)
    licence_type: str = Field(default='', max_length=300)
    access_policy: Literal['full_public', 'metadata_only'] = 'metadata_only'
    embargo_until: datetime | None = None

    @field_validator('url', 'registration_url', 'online_url')
    @classmethod
    def safe_url(cls, value):
        if not value:
            return value
        parsed = urlsplit(value)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or any(c.isspace() for c in value):
            raise ValueError('Укажите публичную ссылку http:// или https:// без пароля')
        return value

    @field_validator('authors', 'keywords', 'content_types')
    @classmethod
    def clean_list(cls, values):
        if any(len(v) > 500 for v in values):
            raise ValueError('Слишком длинное значение списка')
        return list(dict.fromkeys(v.strip() for v in values if v.strip()))

    @field_validator('starts_at', 'ends_at', 'embargo_until')
    @classmethod
    def zoned(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError('Для даты укажите часовой пояс')
        return value

    @field_validator('expires_on')
    @classmethod
    def date_value(cls, value):
        if value:
            from datetime import date
            date.fromisoformat(value)
        return value

    @model_validator(mode='after')
    def dates(self):
        if self.starts_at and self.ends_at and self.ends_at < self.starts_at:
            raise ValueError('Окончание не может быть раньше начала')
        return self


class ContentInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    kind: Kind
    slug: str = Field(pattern=r'^[a-z0-9][a-z0-9-]{0,159}$')
    status: Literal['draft', 'published', 'archived'] = 'draft'
    version: int | None = Field(default=None, ge=1)
    published_at: datetime | None = None
    data: Details

    @model_validator(mode='after')
    def publication(self):
        if not any(t.title for t in self.data.translations.values()):
            raise ValueError('Введите название хотя бы на одном языке')
        if self.published_at and self.published_at.tzinfo is None:
            raise ValueError('Для даты публикации укажите часовой пояс')
        if self.status == 'published':
            if self.kind == 'resources' and not self.data.url:
                raise ValueError('Для публикации ресурса нужна ссылка')
            if self.kind == 'events' and not self.data.starts_at:
                raise ValueError('Для публикации события нужны дата и время начала')
        return self


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


def published(item):
    return item.status == 'published' and item.published_at and aware(item.published_at) <= utcnow()


def file_open(item):
    end = item.data.get('embargo_until')
    return item.kind == 'repository' and item.data.get('access_policy') == 'full_public' and (not end or datetime.fromisoformat(end) <= utcnow())


def present(s, item, staff=False):
    result = {'id': item.id, 'kind': item.kind, 'slug': item.slug, 'published_at': aware(item.published_at), 'data': item.data}
    result['assets'] = {a.slot: {'name': a.name, 'size': a.size, 'mime': a.mime,
        'url': f'/api/public/v1/content-assets/{item.id}/{a.slot}?v={item.version}' if a.slot == 'image' or file_open(item) else None}
        for a in s.scalars(select(SiteAsset).where(SiteAsset.item_id == item.id))}
    if staff:
        result.update(status=item.status, version=item.version, updated_at=aware(item.updated_at))
    return result


def audit(s, item, user, action):
    s.add(SiteAudit(item_id=item.id, actor_id=user.id, action=action, snapshot={
        'slug': item.slug, 'status': item.status, 'version': item.version, 'data': item.data,
        'published_at': item.published_at.isoformat() if item.published_at else None}))


def commit(s):
    try:
        s.commit()
    except IntegrityError:
        s.rollback()
        raise HTTPException(409, 'Такой адрес уже используется в этом разделе')


def locked(s, item_id, version):
    item = s.scalar(select(SiteContent).where(SiteContent.id == item_id).with_for_update())
    if not item:
        raise HTTPException(404, 'Материал не найден')
    if item.version != version:
        raise HTTPException(409, 'Материал изменён другим сотрудником. Откройте его заново.')
    return item


staff_router = APIRouter(prefix='/api/site-content', dependencies=[Depends(auth)])
public_router = APIRouter(prefix='/api/public/v1')


@staff_router.get('')
def staff_list(kind: Kind, q: str = Query('', max_length=200), page: int = Query(1, ge=1), s=Depends(get_db)):
    query = select(SiteContent).where(SiteContent.kind == kind)
    if q.strip():
        query = query.where(SiteContent.data.cast(String).ilike('%' + q.strip().replace('%', '\\%').replace('_', '\\_') + '%', escape='\\'))
    total = s.scalar(select(func.count()).select_from(query.subquery()))
    rows = s.scalars(query.order_by(SiteContent.id.desc()).offset((page-1)*30).limit(30)).all()
    return {'items': [present(s, r, True) for r in rows], 'total': total, 'page': page}


@staff_router.post('', status_code=201)
def create(body: ContentInput, user=Depends(auth), s=Depends(get_db)):
    item = SiteContent(kind=body.kind, slug=body.slug, status=body.status, data=body.data.model_dump(mode='json'),
        published_at=body.published_at or (utcnow() if body.status == 'published' else None))
    s.add(item)
    try:
        s.flush()
    except IntegrityError:
        s.rollback(); raise HTTPException(409, 'Такой адрес уже используется в этом разделе')
    audit(s, item, user, 'create'); commit(s)
    return present(s, item, True)


@staff_router.put('/{item_id}')
def update(item_id: int, body: ContentInput, user=Depends(auth), s=Depends(get_db)):
    item = locked(s, item_id, body.version)
    if body.kind != item.kind:
        raise HTTPException(422, 'Раздел материала нельзя менять')
    item.slug, item.status, item.data = body.slug, body.status, body.data.model_dump(mode='json')
    item.published_at = body.published_at or item.published_at or (utcnow() if item.status == 'published' else None)
    item.version += 1; item.updated_at = utcnow()
    audit(s, item, user, 'update'); commit(s)
    return present(s, item, True)


@staff_router.put('/{item_id}/assets/{slot}')
async def upload(item_id: int, slot: Literal['image', 'pdf'], request: Request, version: int = Query(ge=1), user=Depends(auth), s=Depends(get_db)):
    item = locked(s, item_id, version)
    if slot == 'pdf' and item.kind != 'repository':
        raise HTTPException(422, 'PDF можно прикрепить к работе репозитория')
    limit = (25 if slot == 'pdf' else 8) * 1024 * 1024
    chunks = bytearray()
    async for chunk in request.stream():
        chunks.extend(chunk)
        if len(chunks) > limit:
            raise HTTPException(413, 'Файл слишком большой: изображение до 8 МБ, PDF до 25 МБ')
    data = bytes(chunks)
    if slot == 'pdf':
        if not data.startswith(b'%PDF-') or b'%%EOF' not in data[-4096:]:
            raise HTTPException(422, 'Выберите корректный PDF')
        mime, name = 'application/pdf', 'document.pdf'
    else:
        try:
            with Image.open(BytesIO(data)) as image:
                if image.format not in ('JPEG', 'PNG', 'WEBP') or image.width * image.height > 25000000:
                    raise ValueError()
                image.load(); image.thumbnail((2400, 2400))
                output = BytesIO(); image.convert('RGB').save(output, 'JPEG', quality=90)
                data = output.getvalue()
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
            raise HTTPException(422, 'Выберите изображение JPEG, PNG или WebP до 25 мегапикселей')
        mime, name = 'image/jpeg', 'image.jpg'
    asset = s.scalar(select(SiteAsset).where(SiteAsset.item_id == item_id, SiteAsset.slot == slot))
    if not asset:
        asset = SiteAsset(item_id=item_id, slot=slot); s.add(asset)
    asset.content, asset.mime, asset.name, asset.size = data, mime, name, len(data)
    item.version += 1; item.updated_at = utcnow()
    audit(s, item, user, 'upload_' + slot); commit(s)
    return present(s, item, True)


@staff_router.delete('/{item_id}/assets/{slot}')
def remove_asset(item_id: int, slot: Literal['image', 'pdf'], version: int = Query(ge=1), user=Depends(auth), s=Depends(get_db)):
    item = locked(s, item_id, version)
    asset = s.scalar(select(SiteAsset).where(SiteAsset.item_id == item_id, SiteAsset.slot == slot))
    if asset:
        s.delete(asset)
    item.version += 1; item.updated_at = utcnow()
    audit(s, item, user, 'remove_' + slot); commit(s)
    return present(s, item, True)


@staff_router.get('/{item_id}/assets/{slot}')
def preview_asset(item_id: int, slot: Literal['image', 'pdf'], s=Depends(get_db)):
    asset = s.scalar(select(SiteAsset).where(SiteAsset.item_id == item_id, SiteAsset.slot == slot))
    if not asset:
        raise HTTPException(404, 'Файл не найден')
    return Response(asset.content, media_type=asset.mime, headers={'Cache-Control': 'no-store',
        'X-Content-Type-Options': 'nosniff', 'Content-Security-Policy': 'sandbox'})


@public_router.get('/content/{kind}')
def public_list(kind: Kind, page: int = Query(1, ge=1), limit: int = Query(100, ge=1, le=100), s=Depends(get_db)):
    query = select(SiteContent).where(SiteContent.kind == kind, SiteContent.status == 'published', SiteContent.published_at <= utcnow())
    total = s.scalar(select(func.count()).select_from(query.subquery()))
    rows = s.scalars(query.order_by(SiteContent.published_at.desc(), SiteContent.id.desc()).offset((page-1)*limit).limit(limit)).all()
    return {'data': [present(s, r) for r in rows], 'meta': {'total': total, 'page': page, 'last_page': max(1, (total+limit-1)//limit)}}


@public_router.get('/content/{kind}/{identifier}')
def public_detail(kind: Kind, identifier: str, s=Depends(get_db)):
    condition = SiteContent.id == int(identifier[7:]) if re.fullmatch(r'utblib-\d+', identifier) else SiteContent.slug == identifier
    item = s.scalar(select(SiteContent).where(SiteContent.kind == kind, condition))
    if not item or not published(item):
        raise HTTPException(404, 'Материал не найден')
    return {'data': present(s, item)}


@public_router.get('/content-assets/{item_id}/{slot}')
def public_asset(item_id: int, slot: Literal['image', 'pdf'], s=Depends(get_db)):
    item = s.get(SiteContent, item_id)
    if not item or not published(item) or (slot == 'pdf' and not file_open(item)):
        raise HTTPException(404, 'Файл не найден')
    asset = s.scalar(select(SiteAsset).where(SiteAsset.item_id == item_id, SiteAsset.slot == slot))
    if not asset:
        raise HTTPException(404, 'Файл не найден')
    return Response(asset.content, media_type=asset.mime, headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
        'Content-Security-Policy': "sandbox", 'Content-Disposition': 'inline; filename="' + quote(asset.name) + '"'})
