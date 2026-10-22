"""Shared validation and atomic operations used by HTTP and import commands."""
import hashlib, io, json, os, time
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from fastapi import HTTPException
from sqlalchemy import select, func, or_
from .db import utcnow
from .reader_models import Reader, ReaderCounter, ReaderAudit, ReaderRateLimit, ReaderPhoto

CATEGORIES={'student':'Студент','bachelor':'Бакалавр','specialist':'Специалист','master':'Магистрант','doctoral':'Докторант','teacher':'Преподаватель','faculty':'ППС','researcher':'Исследователь','staff':'Сотрудник'}
STATUSES={'active':'Активен','blocked':'Заблокирован','suspended':'Приостановлен'}
PERSONAL={'iin','birth_date','gender_source'}
TZ=ZoneInfo(os.getenv('LIBRARY_TIMEZONE','Asia/Almaty'))

def local_bounds(day):
    return datetime.combine(day,datetime.min.time(),TZ).astimezone(timezone.utc),datetime.combine(day+timedelta(days=1),datetime.min.time(),TZ).astimezone(timezone.utc)

def iin_data(value):
    if len(value)!=12 or not value.isascii() or not value.isdigit(): raise ValueError('ИИН: требуется 12 цифр')
    digits=list(map(int,value)); n=sum(a*b for a,b in zip(digits,range(1,12)))%11
    if n==10: n=sum(a*b for a,b in zip(digits,[3,4,5,6,7,8,9,10,11,1,2]))%11
    if n==10 or n!=digits[-1]: raise ValueError('ИИН: неверная контрольная сумма')
    century={1:1800,2:1800,3:1900,4:1900,5:2000,6:2000}.get(digits[6])
    if century is None: raise ValueError('ИИН: неверный код века')
    try: birthday=date(century+int(value[:2]),int(value[2:4]),int(value[4:6]))
    except ValueError: raise ValueError('ИИН: неверная дата рождения') from None
    if birthday>date.today(): raise ValueError('ИИН: дата рождения в будущем')
    return birthday,'male' if digits[6]%2 else 'female'

def validate_personal(s,values,reader_id=None,known_iins=None):
    iin=values.get('iin') or None; birthday=values.get('birth_date')
    if isinstance(birthday,str): birthday=date.fromisoformat(birthday) if birthday else None
    if birthday and birthday>date.today(): raise ValueError('Дата рождения в будущем')
    if iin:
        expected,gender=iin_data(iin)
        if birthday and expected!=birthday: raise ValueError('ИИН не соответствует дате рождения')
        duplicate=(known_iins.get(iin) if known_iins is not None else s.scalar(select(Reader.id).where(Reader.iin==iin,Reader.id!=reader_id)))
        if duplicate==reader_id: duplicate=None
        if duplicate: raise ValueError('ИИН уже связан с другим читателем')
    return iin,birthday

def increment(s,name):
    if s.bind.dialect.name=='postgresql': from sqlalchemy.dialects.postgresql import insert
    else: from sqlalchemy.dialects.sqlite import insert
    stmt=insert(ReaderCounter).values(name=name,value=1)
    return s.scalar(stmt.on_conflict_do_update(index_elements=['name'],set_={'value':ReaderCounter.value+1}).returning(ReaderCounter.value))

def allocate_ticket(s,category,cohort,faculty):
    prefix=os.getenv('READER_TICKET_PREFIX','KazTBU')
    codes=json.loads(os.getenv('READER_FACULTY_CODES','{}'))
    category_codes={'student':'U','bachelor':'B','specialist':'S','master':'M','doctoral':'D','teacher':'P','faculty':'P','researcher':'P','staff':'A'}
    year=cohort or datetime.now(TZ).year
    namespace=f'{prefix}-{category_codes[category]}{year%100:02d}-{codes.get(faculty,"UNI")}'
    number=increment(s,'ticket:'+namespace); barcode=increment(s,'barcode')
    if barcode>99999999: raise ValueError('Исчерпан диапазон штрихкодов')
    return f'{namespace}-{number:05d}',f'RDR{barcode:08d}'

def audit(s,action,actor=None,reader=None,**details):
    # Only call with metadata/field names, never values of personal fields.
    s.add(ReaderAudit(action=action,actor_id=actor,reader_id=reader,details=details))

def lookup(s,code,lock=False):
    code=code.strip().lower()
    if not code or len(code)>100: raise HTTPException(422,'Введите номер билета или штрихкод (до 100 символов)')
    stmt=select(Reader).where(or_(func.lower(Reader.ticket_number)==code,func.lower(Reader.barcode)==code))
    if lock: stmt=stmt.with_for_update()
    reader=s.scalar(stmt)
    if reader is None: raise HTTPException(404,'Читатель с таким билетом не найден')
    return reader

def rate_limit(s,actor,action,maximum):
    if s.bind.dialect.name=='postgresql': from sqlalchemy.dialects.postgresql import insert
    else: from sqlalchemy.dialects.sqlite import insert
    from sqlalchemy import case
    window=int(time.time())//60; key=f'{actor}:{action}'
    stmt=insert(ReaderRateLimit).values(key=key,count=1,window=window)
    count=s.scalar(stmt.on_conflict_do_update(index_elements=['key'],set_={'count':case((ReaderRateLimit.window==window,ReaderRateLimit.count+1),else_=1),'window':window}).returning(ReaderRateLimit.count))
    s.commit()
    if count>maximum: raise HTTPException(429,'Слишком много запросов. Повторите через минуту.')

def store_photo(s,reader_id,raw):
    from PIL import Image, UnidentifiedImageError
    if len(raw)>3_000_000: raise ValueError('Фото превышает 3 МБ')
    try:
        with Image.open(io.BytesIO(raw)) as im:
            if im.width*im.height>16_000_000: raise ValueError('Слишком большое фото')
            im=im.convert('RGB'); im.thumbnail((600,800)); out=io.BytesIO(); im.save(out,format='JPEG',quality=85)
    except (UnidentifiedImageError,OSError,Image.DecompressionBombError): raise ValueError('Некорректное фото') from None
    content=out.getvalue(); digest=hashlib.sha256(content).hexdigest(); photo=s.get(ReaderPhoto,reader_id)
    if photo and photo.sha256==digest: return
    if not photo: photo=ReaderPhoto(reader_id=reader_id); s.add(photo)
    photo.content=content; photo.sha256=digest; photo.updated_at=utcnow()

def public_reader(reader,personal=False):
    result={c.name:getattr(reader,c.name) for c in Reader.__table__.columns if c.name not in {'user_id','limits_override'}}
    if not personal:
        for key in PERSONAL: result.pop(key,None)
    return result


def personal_error_code(exc):
    if str(exc)=='ИИН не соответствует дате рождения': return 'iin_birth_mismatch'
    if str(exc)=='ИИН уже связан с другим читателем': return 'duplicate_iin'
    return 'invalid_personal_or_profile_data'
