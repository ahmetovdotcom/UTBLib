"""Bounded, temporary photo handoff for the single-process API deployment.

No catalogue writes or OpenAI calls. Pairing and phone tokens never appear in URLs
sent to the server. All photographs disappear on restart or expiry.
"""
import asyncio
import base64
import io
import json
import secrets
import threading
import time
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from urllib.parse import urlsplit
from uuid import UUID

import qrcode
from PIL import Image
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.concurrency import run_in_threadpool

from .book_photos import prepare_image
from .db import User, UserSession
from .security import COOKIE, digest, has, same_origin, permission_for

LIFETIME = 8 * 60 * 60
PAIR_LIFETIME = 10 * 60
DESKTOP_LEASE = 60
PHOTO_IDLE = 30 * 60
MAX_SESSIONS = 32
MAX_BYTES = 96 * 1024 * 1024
MAX_BODY = 1_500_000


@dataclass
class Room:
    id: str
    owner_id: int
    login_hash: str
    expires: float
    pair_hash: str
    pair_expires: float
    phone_hash: str = ''
    target_id: str = ''
    label: str = ''
    accepting: bool = False
    desktop_seen: float = 0
    phone_seen: float = 0
    photos: dict = field(default_factory=dict)
    received: set = field(default_factory=set)


class TransferStore:
    def __init__(self):
        self.rooms = {}
        self.uploading = set()
        self.lock = threading.RLock()

    def cleanup(self):
        with self.lock:
            now = time.time()
            for key, room in list(self.rooms.items()):
                if room.expires <= now or (not room.phone_hash and room.pair_expires <= now):
                    del self.rooms[key]
                elif room.desktop_seen + PHOTO_IDLE < now:
                    room.photos.clear()
                    room.received.clear()


store = TransferStore()


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class Start(Strict):
    origin: str = Field(min_length=1, max_length=250)


class Target(Strict):
    target_id: str = Field(pattern=r'^[a-f0-9-]{36}$')
    label: str = Field(min_length=1, max_length=240)


class Heartbeat(Target):
    pass


class Gate(Strict):
    target_id: str = Field(pattern=r'^[a-f0-9-]{36}$')
    accepting: bool


class Upload(Target):
    request_id: str = Field(pattern=r'^[a-f0-9-]{36}$')
    name: str = Field(min_length=1, max_length=120)
    image: str = Field(min_length=1, max_length=1_400_000)


def snapshot(room):
    now = time.time()
    return {'id': room.id, 'target_id': room.target_id, 'label': room.label,
            'paired': bool(room.phone_hash), 'phone_online': room.phone_seen + 15 > now,
            'accepting': bool(room.target_id and room.accepting and room.desktop_seen + DESKTOP_LEASE > now),
            'expires_at': int(room.expires), 'photos': [
                {'id': key, 'name': photo['name']} for key, photo in room.photos.items()]}


def target_matches(room, target_id):
    if not room.target_id or room.target_id != target_id:
        raise HTTPException(409, 'На компьютере выбрана другая книга. Проверьте название и сделайте снимок заново.')


def accepts(room, target_id):
    target_matches(room, target_id)
    if not snapshot(room)['accepting']:
        raise HTTPException(409, 'Приём фото приостановлен. Откройте карточку на компьютере и дождитесь готовности.')


def make_router(auth, db):
    @asynccontextmanager
    async def lifespan(app):
        async def loop():
            while True:
                await asyncio.sleep(30)
                store.cleanup()
        task = asyncio.create_task(loop())
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    router = APIRouter(prefix='/api/photo-transfer', lifespan=lifespan)

    def owner(room_id, request, user):
        store.cleanup()
        room = store.rooms.get(room_id)
        if not room or room.owner_id != user.id or room.login_hash != digest(request.cookies.get(COOKIE, '')):
            raise HTTPException(404, 'Подключение завершено. Подключите телефон по новому QR-коду.')
        return room

    def mobile(request, s, pairing=False):
        same_origin(request)
        token = request.headers.get('authorization', '')
        if not token.startswith('Bearer ') or len(token) > 100:
            raise HTTPException(401, 'Подключите телефон по QR-коду на компьютере.')
        hashed = digest(token[7:])
        store.cleanup()
        room = next((r for r in store.rooms.values()
                     if secrets.compare_digest(r.pair_hash if pairing else r.phone_hash, hashed)), None)
        if not room or (pairing and room.pair_expires <= time.time()):
            raise HTTPException(401, 'Подключение завершено. Отсканируйте новый QR-код на компьютере.')
        session = s.get(UserSession, room.login_hash)
        user = s.get(User, room.owner_id)
        if (not session or session.expires_at <= time.time() or not user or
                not user.active or user.deleted or not has(user, permission_for(request.method, request.url.path))):
            store.rooms.pop(room.id, None)
            raise HTTPException(401, 'Сотрудник вышел из системы. Подключите телефон заново.')
        room.phone_seen = time.time()
        return room

    @router.post('/sessions', status_code=201)
    def create(body: Start, request: Request, user=Depends(auth)):
        url = urlsplit(body.origin)
        if (url.scheme not in ('http', 'https') or url.netloc != request.headers.get('host')
                or url.username or url.password or url.path not in ('', '/') or url.query or url.fragment):
            raise HTTPException(422, 'Откройте каталог по адресу, доступному телефону.')
        with store.lock:
            store.cleanup()
            if len(store.rooms) >= MAX_SESSIONS or sum(r.owner_id == user.id for r in store.rooms.values()) >= 4:
                raise HTTPException(429, 'Закройте прежние подключения телефона или дождитесь их завершения.')
            now = time.time()
            token = secrets.token_urlsafe(32)
            room = Room(secrets.token_hex(16), user.id, digest(request.cookies[COOKIE]),
                        now + LIFETIME, digest(token), now + PAIR_LIFETIME)
            store.rooms[room.id] = room
            link = body.origin.rstrip('/') + '/phone-photos#pair=' + token
            buffer = io.BytesIO()
            qrcode.make(link).save(buffer, format='PNG')
            return {**snapshot(room), 'link': link, 'qr': 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode()}

    @router.delete('/sessions/{room_id}', status_code=204)
    def disconnect(room_id: str, request: Request, user=Depends(auth)):
        with store.lock:
            owner(room_id, request, user)
            del store.rooms[room_id]

    @router.get('/sessions/{room_id}')
    def status(room_id: str, request: Request, user=Depends(auth)):
        with store.lock:
            return snapshot(owner(room_id, request, user))

    @router.post('/sessions/{room_id}/target')
    def target(room_id: str, body: Target, request: Request, user=Depends(auth)):
        with store.lock:
            room = owner(room_id, request, user)
            if room.target_id != body.target_id:
                room.photos.clear()
                room.received.clear()
            room.target_id, room.label = body.target_id, body.label
            room.accepting, room.desktop_seen = True, time.time()
            return snapshot(room)

    @router.post('/sessions/{room_id}/heartbeat')
    def heartbeat(room_id: str, body: Heartbeat, request: Request, user=Depends(auth)):
        with store.lock:
            room = owner(room_id, request, user)
            target_matches(room, body.target_id)
            room.desktop_seen, room.label = time.time(), body.label
            return snapshot(room)

    @router.post('/sessions/{room_id}/gate')
    def gate(room_id: str, body: Gate, request: Request, user=Depends(auth)):
        with store.lock:
            room = owner(room_id, request, user)
            target_matches(room, body.target_id)
            room.accepting = body.accepting
            room.desktop_seen = time.time()
            return snapshot(room)

    @router.get('/sessions/{room_id}/photos/{photo_id}')
    def download(room_id: str, photo_id: str, request: Request, user=Depends(auth)):
        with store.lock:
            room = owner(room_id, request, user)
            photo = room.photos.get(photo_id)
            if not photo:
                raise HTTPException(404, 'Фото больше не доступно.')
            return {**photo, 'target_id': room.target_id}

    @router.delete('/sessions/{room_id}/photos/{photo_id}', status_code=204)
    def remove(room_id: str, photo_id: str, request: Request, user=Depends(auth)):
        with store.lock:
            room = owner(room_id, request, user)
            room.photos.pop(photo_id, None)

    @router.post('/mobile/pair')
    def pair(request: Request, s=Depends(db)):
        with store.lock:
            room = mobile(request, s, pairing=True)
            token = secrets.token_urlsafe(32)
            room.phone_hash, room.pair_hash = digest(token), ''
            return {**snapshot(room), 'token': token}

    @router.get('/mobile')
    def phone_status(request: Request, s=Depends(db)):
        with store.lock:
            return snapshot(mobile(request, s))

    @router.post('/mobile/photos', status_code=201)
    async def upload(request: Request, s=Depends(db)):
        with store.lock:
            room = mobile(request, s)
            room_id = room.id
            if room_id in store.uploading or len(store.uploading) >= 8:
                raise HTTPException(429, 'Загружается другой снимок. Дождитесь завершения и повторите.')
            store.uploading.add(room_id)
        try:
            return await receive_photo(request, s)
        finally:
            with store.lock:
                store.uploading.discard(room_id)

    async def receive_photo(request, s):
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > MAX_BODY:
                raise HTTPException(413, 'Фотография слишком большая. Уменьшите её размер.')
        try:
            body = Upload.model_validate(json.loads(raw))
            UUID(body.target_id); UUID(body.request_id)
        except (ValueError, TypeError, ValidationError):
            raise HTTPException(422, 'Не удалось прочитать фотографию. Повторите съёмку.') from None
        with store.lock:
            room = mobile(request, s)
            accepts(room, body.target_id)
            if body.request_id in room.received:
                return snapshot(room)
            if len(room.photos) >= 6:
                raise HTTPException(409, 'Для одной книги можно загрузить до 6 фото. Удалите лишние на компьютере.')
        s.rollback()  # Release the read connection while decoding; recheck the login afterwards.
        image = await run_in_threadpool(prepare_image, body.image)
        if len(image) > 1_350_000:
            def compact():
                with Image.open(io.BytesIO(base64.b64decode(image.split(',', 1)[1]))) as decoded:
                    output = io.BytesIO()
                    decoded.save(output, format='JPEG', quality=75)
                    return 'data:image/jpeg;base64,' + base64.b64encode(output.getvalue()).decode('ascii')
            image = await run_in_threadpool(compact)
            if len(image) > 1_350_000:
                raise HTTPException(422, 'Фотография слишком подробная. Обрежьте её до страницы книги.')
        with store.lock:
            room = mobile(request, s)
            accepts(room, body.target_id)  # The desktop may have changed books while decoding.
            if body.request_id in room.received:
                return snapshot(room)
            if len(room.photos) >= 6 or len(room.received) >= 100:
                raise HTTPException(409, 'Лимит снимков этой книги достигнут. Начните новый комплект на компьютере.')
            if sum(len(p['url']) for r in store.rooms.values() for p in r.photos.values()) + len(image) > MAX_BYTES:
                raise HTTPException(429, 'Очередь фотографий заполнена. Завершите обработку предыдущих книг.')
            room.photos[body.request_id] = {'name': body.name, 'url': image}
            room.received.add(body.request_id)
            return snapshot(room)

    return router
