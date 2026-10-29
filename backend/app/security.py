"""Cookie sessions and explicit server-side capabilities. No browser admin-key bypass."""
import hashlib
import os
import re
import secrets
import time
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Request, Response, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select, delete, text
from sqlalchemy.exc import IntegrityError
from .db import User, UserSession, LoginAttempt, UserAudit, get_db, Session

PERMISSIONS={
 'site.manage':'Управление ресурсами, репозиторием, новостями и событиями сайта',
 'circulation.issue':'Выдача книг',
 'circulation.return':'Возврат книг',
 'circulation.renew':'Продление выдач',
 'circulation.override_limits':'Обход лимитов и срока билета с причиной',
 'circulation.override_due_date':'Увеличенный срок выдачи с причиной',
 'circulation.view_any_history':'Просмотр всей истории выдач',
 'circulation.view_own_history':'Просмотр своих операций выдачи',
 'loans.view_own':'Свои книги читателя',
 'loans.renew_own':'Продление своих книг',
 'fines.manage':'Учёт штрафов и оплаты',
 'fines.waive':'Освобождение от штрафа',
 'reservations.manage':'Управление бронями',
 'incidents.manage':'Решения по утратам и повреждениям',
 'circulation.settings':'Настройки книговыдачи и лимитов',
 'circulation.copies':'Состояние и доступность экземпляров',

 'readers.registry.view':'Просмотр реестра читателей',
 'readers.registry.edit':'Редактирование читателей и пунктов обслуживания',
 'readers.registry.export':'Выгрузка читателей',
 'readers.analytics.view':'Аналитика читателей',
 'readers.personal_data.view':'Персональные данные читателей (ИИН и дата рождения)',
 'readers.ticket.print':'Печать читательского билета',
 'readers.source.import':'Поиск и загрузка читателей из AD / Platonus',
 'readers.sync.admin':'Администрирование синхронизации читателей',
 'visits.record':'Регистрация посещений',
 'visits.view':'Журнал и статистика посещений',
 'catalog.view':'Просмотр каталога и экземпляров',
 'catalog.edit':'Создание и редактирование записей',
 'catalog.delete':'Удаление записей каталога',
 'copies.edit':'Создание и изменение экземпляров',
 'statistics.view':'Просмотр статистики',
 'ksu.view':'Просмотр и выгрузка КСУ',
 'ksu.edit':'Настройка соответствий литературы для КСУ',
 'acquisitions.view':'Просмотр поступлений',
 'acquisitions.edit':'Создание и изменение поступлений',
 'acquisitions.cancel':'Отмена поступлений',
 'withdrawals.view':'Просмотр журнала списания',
 'withdrawals.create':'Списание экземпляров',
 'settings.edit':'Настройка типов, полей и справочников',
 'import.run':'Импорт MARCSQL',
}
PRESETS={'viewer':['catalog.view'],'librarian':['catalog.view','catalog.edit','copies.edit','acquisitions.view','acquisitions.edit','withdrawals.view']}
PRESETS['librarian']+=['readers.registry.view','visits.record','circulation.issue','circulation.return','circulation.renew','circulation.view_own_history','reservations.manage']
PRESETS['manager']=list(PERMISSIONS)
PRESETS['reader']=['loans.view_own','loans.renew_own']
COOKIE='library_session'
LIFETIME=12*60*60

def digest(value): return hashlib.sha256(value.encode()).hexdigest()
def password_hash(password):
    salt=secrets.token_hex(16)
    key=hashlib.scrypt(password.encode(),salt=bytes.fromhex(salt),n=16384,r=8,p=1).hex()
    return 'scrypt$'+salt+'$'+key

def verify(password,encoded):
    try:
        algorithm,salt,key=encoded.split('$')
        return algorithm=='scrypt' and secrets.compare_digest(hashlib.scrypt(password.encode(),salt=bytes.fromhex(salt),n=16384,r=8,p=1).hex(),key)
    except (ValueError,TypeError): return False

DUMMY_HASH=password_hash('dummy password, never an account')

def public(user):
    return {'id':user.id,'username':user.username,'display_name':user.display_name,'role':user.role,'permissions':list(PERMISSIONS) if user.role=='admin' else user.permissions,'active':user.active,'version':user.version}

def has(user,permission): return user.role=='admin' or permission in user.permissions

def require(user,permission):
    if not has(user,permission): raise HTTPException(403,'Недостаточно прав: '+PERMISSIONS.get(permission,permission))

def same_origin(request):
    # Custom CSRF header is also required for all authenticated mutations.
    origin=request.headers.get('origin')
    if origin:
        from urllib.parse import urlsplit
        if urlsplit(origin).netloc!=request.headers.get('host'): raise HTTPException(403,'Недопустимый источник запроса')
    if request.headers.get('sec-fetch-site')=='cross-site': raise HTTPException(403,'Недопустимый источник запроса')

def identity(request:Request,s=Depends(get_db)):
    # Explicit header credentials must never be silently replaced with browser cookies.
    if request.headers.get('x-admin-key') is not None: raise HTTPException(401,'Войдите с логином и паролем')
    token=request.cookies.get(COOKIE,'')
    session=s.get(UserSession,digest(token)) if token else None
    user=s.get(User,session.user_id) if session and session.expires_at>int(time.time()) else None
    if not user or not user.active or user.deleted: raise HTTPException(401,'Сеанс завершён. Войдите снова.')
    if request.method not in ('GET','HEAD','OPTIONS'):
        same_origin(request)
        if not secrets.compare_digest(request.headers.get('x-csrf-token',''),digest('csrf:'+token)): raise HTTPException(403,'Обновите страницу и повторите действие')
    request.state.user_id=user.id
    return user

# Every existing endpoint has a permission; unmatched paths are denied.
def permission_for(method,path):
    if path.startswith('/api/site-content'): return 'site.manage'
    # Mobile routes delegate this capability through a scoped token and recheck its owner's login.
    if path.startswith('/api/photo-transfer/'): return 'catalog.edit'
    if path in ('/api/book-photos/config','/api/book-photos/analyze'): return 'catalog.edit'
    if path.startswith('/api/circulation/'):
        suffix=path[len('/api/circulation/'):]
        if suffix=='options': return 'circulation.options'
        if suffix=='issue': return 'circulation.issue'
        if suffix.startswith('mine'): return 'loans.renew_own' if method=='POST' else 'loans.view_own'
        if suffix.endswith('/return'): return 'circulation.return'
        if suffix.endswith('/renew'): return 'circulation.renew'
        if suffix.endswith('/limits') or suffix.endswith('/account') or suffix in ('settings','accounts'): return 'circulation.settings'
        if suffix.startswith('fines'): return 'fines.manage'
        if suffix.startswith('incidents'): return 'incidents.manage'
        if suffix.startswith('reservations'): return 'reservations.manage'
        if suffix.startswith('copies/') and method=='POST': return 'circulation.copies'
        if suffix=='loans': return 'circulation.history'
        if suffix.startswith('loans/') and method=='GET': return 'circulation.loan'
        if suffix in ('audit','notices'): return 'circulation.view_any_history'
        return 'circulation.desk'
    if path=='/api/reader-branches': return 'readers.registry.edit' if method!='GET' else 'readers.branches.access'
    if path.startswith('/api/reader-branches/'): return 'readers.registry.edit'
    if path.startswith('/api/readers'):
        if path in ('/api/readers/source-search','/api/readers/source-import'): return 'readers.source.import'
        if path.startswith('/api/readers/conflicts/'): return 'readers.sync.admin'
        if path.endswith('/export'): return 'readers.registry.export'
        if path.endswith('/analytics'): return 'readers.analytics.view'
        if path.endswith('/sync-status'): return 'readers.sync.admin'
        if path.endswith('/ticket'): return 'readers.ticket.print'
        return 'readers.registry.view' if method=='GET' else 'readers.registry.edit'
    if path.startswith('/api/visits'): return 'visits.record' if method=='POST' or path.endswith('/lookup') else 'visits.view'
    if path.startswith('/api/settings-transfer/'): return 'settings.edit'
    if path in ('/api/catalog-attention','/api/catalog-attention/options') and method=='GET': return 'catalog.view'
    if path.startswith('/api/import/'): return 'import.run'
    if path in ('/api/dictionary','/api/types'): return 'catalog.view' if method=='GET' else 'settings.edit'
    if path.startswith('/api/types/'): return 'catalog.view' if method=='GET' else 'settings.edit'
    if path.startswith('/api/statistics/') and method=='GET': return 'statistics.view'
    if path.startswith('/api/ksu/'): return 'ksu.view' if method=='GET' else 'ksu.edit'
    if path.startswith('/api/acquisitions'): return 'acquisitions.view' if method=='GET' else ('acquisitions.cancel' if path.endswith('/cancel') else 'acquisitions.edit')
    if path.startswith('/api/withdrawals'): return 'withdrawals.view' if method=='GET' else 'withdrawals.create'
    if path.startswith('/api/copies/'): return 'catalog.view' if method=='GET' else 'copies.edit'
    if re.fullmatch(r'/api/records/\d+/copies',path): return 'catalog.view' if method=='GET' else 'copies.edit'
    if path=='/api/records' or re.fullmatch(r'/api/records/\d+(?:/marcsql-source)?',path):
        return 'catalog.view' if method=='GET' else ('catalog.delete' if method=='DELETE' else 'catalog.edit')
    if path in ('/api/gost/preview','/api/isbn-lookup'): return 'catalog.view'
    raise HTTPException(403,'Действие не разрешено')

def auth(request:Request,s=Depends(get_db)):
    key=request.headers.get('x-admin-key')
    if key is not None:
        configured=os.getenv('ADMIN_KEY','')
        if not configured or not secrets.compare_digest(key,configured): raise HTTPException(401,'Неверный ключ импорта')
        if request.method!='POST' or request.url.path not in ('/api/import/marcsql','/api/import/marcsql-copies'): raise HTTPException(403,'Ключ доступен только для импорта')
        lock(s,'circulation-stock-gate')
        return None
    user=identity(request,s)
    permission=permission_for(request.method,request.url.path)
    if (request.method not in ('GET','HEAD','OPTIONS') and request.url.path != '/api/book-photos/analyze'
            and not request.url.path.startswith('/api/photo-transfer/')):
        lock(s,'circulation-stock-gate')
    if permission=='circulation.options':
        if not any(has(user,p) for p in ('circulation.issue','circulation.return','circulation.renew','circulation.view_any_history','circulation.view_own_history','reservations.manage','fines.manage','incidents.manage','circulation.settings','circulation.copies')): raise HTTPException(403,'Нет доступа к настройкам рабочего места')
    elif permission=='circulation.desk':
        if not any(has(user,p) for p in ('circulation.issue','circulation.return','circulation.renew','circulation.view_any_history','reservations.manage','circulation.copies')): raise HTTPException(403,'Нет доступа к рабочему месту книговыдачи')
    elif permission=='circulation.loan':
        if not any(has(user,p) for p in ('circulation.issue','circulation.return','circulation.renew','circulation.view_any_history','circulation.view_own_history')): raise HTTPException(403,'Нет доступа к выдаче')
    elif permission=='circulation.history':
        if not any(has(user,p) for p in ('circulation.view_any_history','circulation.view_own_history')): raise HTTPException(403,'Нет доступа к истории')
    elif permission=='readers.branches.access':
        if not any(has(user,p) for p in ('readers.registry.view','readers.registry.edit','visits.record','visits.view')): raise HTTPException(403,'Недостаточно прав')
    else: require(user,permission)
    return user

def admin(user=Depends(identity)):
    if user.role!='admin': raise HTTPException(403,'Доступно только администратору')
    return user

class Strict(BaseModel): model_config=ConfigDict(extra='forbid')
class Login(Strict):
    username:str=Field(min_length=1,max_length=80)
    password:str=Field(min_length=1,max_length=256)
class UserInput(Strict):
    username:str=Field(pattern=r'^[A-Za-z0-9_.-]{3,80}$')
    display_name:str=Field(min_length=1,max_length=160)
    role:Literal['admin','manager','librarian','viewer','reader']='viewer'
    permissions:list[str]=Field(default_factory=lambda:['catalog.view'],max_length=100)
    active:bool=True
    password:str|None=Field(default=None,min_length=8,max_length=256)
    version:int|None=None
    @field_validator('username')
    @classmethod
    def lower(cls,v): return v.lower()
    @field_validator('display_name')
    @classmethod
    def name(cls,v):
        if not v.strip(): raise ValueError('Введите имя')
        return v.strip()
    @field_validator('permissions')
    @classmethod
    def rights(cls,values):
        if set(values)-set(PERMISSIONS): raise ValueError('Неизвестные права')
        result=set(values)|{'catalog.view'}
        if 'acquisitions.edit' in result or 'acquisitions.cancel' in result: result.add('acquisitions.view')
        if 'ksu.edit' in result: result.add('ksu.view')
        if 'withdrawals.create' in result: result.add('withdrawals.view')
        return sorted(result)
class PasswordChange(Strict):
    current_password:str=Field(min_length=1,max_length=256)
    new_password:str=Field(min_length=8,max_length=256)

def lock(s,key):
    if s.bind.dialect.name=='postgresql': s.execute(text('SELECT pg_advisory_xact_lock(:key)'),{'key':int(digest(key)[:15],16)})

def audit(s,actor,target,action,details):
    s.add(UserAudit(actor_id=actor,target_id=target,action=action,details=details))

def bootstrap(s,password):
    lock(s,'bootstrap-admin')
    if s.scalar(select(User.id).limit(1)) is None:
        user=User(username='admin',display_name='Администратор',role='admin',permissions=[],password_hash=password_hash(password),active=True,version=1)
        s.add(user);s.flush();audit(s,None,user.id,'bootstrap',{});s.commit()

router=APIRouter(prefix='/api',tags=['users'])
@router.post('/auth/login')
def login(body:Login,request:Request,response:Response,s=Depends(get_db)):
    same_origin(request)
    now=int(time.time());username=body.username.strip().lower()
    # The proxy does not pass user-controlled Forwarded headers into this decision.
    lock(s,'login:'+username)
    bucket_key=digest(username)
    bucket=s.get(LoginAttempt,bucket_key)
    if bucket and bucket.expires_at>now and bucket.count>=10: raise HTTPException(429,'Слишком много попыток. Повторите через 15 минут.')
    user=s.scalar(select(User).where(User.username==username))
    correct=verify(body.password,user.password_hash if user else DUMMY_HASH)
    if not correct or not user or not user.active or user.deleted:
        if not bucket: bucket=LoginAttempt(key=bucket_key,count=0,expires_at=now+900);s.add(bucket)
        if bucket.expires_at<=now: bucket.count=0;bucket.expires_at=now+900
        bucket.count+=1;s.commit();raise HTTPException(401,'Неверный логин или пароль')
    if bucket: s.delete(bucket)
    s.execute(delete(UserSession).where(UserSession.expires_at<=now))
    token=secrets.token_urlsafe(32)
    s.add(UserSession(token_hash=digest(token),user_id=user.id,expires_at=now+LIFETIME));audit(s,user.id,user.id,'login',{});s.commit()
    response.set_cookie(COOKIE,token,max_age=LIFETIME,httponly=True,samesite='strict',secure=os.getenv('COOKIE_SECURE','false').lower()=='true',path='/')
    response.headers['Cache-Control']='no-store'
    return {'user':public(user),'csrf_token':digest('csrf:'+token)}

@router.get('/auth/me')
def me(request:Request,response:Response,user=Depends(identity)):
    response.headers['Cache-Control']='no-store'
    return {'user':public(user),'csrf_token':digest('csrf:'+request.cookies[COOKIE])}

@router.post('/auth/logout',status_code=204)
def logout(request:Request,response:Response,user=Depends(identity),s=Depends(get_db)):
    s.execute(delete(UserSession).where(UserSession.token_hash==digest(request.cookies[COOKIE])));s.commit()
    response.delete_cookie(COOKIE,path='/')

@router.post('/auth/password',status_code=204)
def change_password(body:PasswordChange,response:Response,user=Depends(identity),s=Depends(get_db)):
    if not verify(body.current_password,user.password_hash): raise HTTPException(400,'Текущий пароль неверен')
    user.password_hash=password_hash(body.new_password);user.version+=1
    s.execute(delete(UserSession).where(UserSession.user_id==user.id));audit(s,user.id,user.id,'password_change',{});s.commit()
    response.delete_cookie(COOKIE,path='/')

@router.get('/users')
def users(user=Depends(admin),s=Depends(get_db)):
    return {'items':[public(u) for u in s.scalars(select(User).where(User.deleted==False).order_by(User.id))],'permissions':PERMISSIONS,'presets':PRESETS}

def save_user(body,s,actor,id=None):
    # Serialize account administration, including last-admin invariant and stale edits.
    lock(s,'user-administration')
    target=s.get(User,id,populate_existing=True) if id else None
    if id and (not target or target.deleted): raise HTTPException(404,'Пользователь не найден')
    if target and body.version!=target.version: raise HTTPException(409,'Пользователь изменён. Обновите список.')
    if target and target.role=='admin' and target.active and (body.role!='admin' or not body.active):
        others=s.scalar(select(User.id).where(User.role=='admin',User.active==True,User.deleted==False,User.id!=target.id).limit(1))
        if others is None: raise HTTPException(409,'Нельзя отключить или понизить последнего активного администратора')
    if not target and not body.password: raise HTTPException(422,'Укажите пароль нового пользователя (минимум 8 символов)')
    before=public(target) if target else None
    if target is None: target=User(password_hash=password_hash(body.password),version=0);s.add(target)
    elif body.password: target.password_hash=password_hash(body.password)
    target.username=body.username;target.display_name=body.display_name;target.role=body.role
    target.permissions=[] if body.role=='admin' else [p for p in body.permissions if p in ('loans.view_own','loans.renew_own')] if body.role=='reader' else body.permissions;target.active=body.active;target.version+=1
    try:
        s.flush()
        if id: s.execute(delete(UserSession).where(UserSession.user_id==id))
        audit(s,actor.id,target.id,'update' if id else 'create',{'before':before,'after':public(target),'password_reset':bool(body.password)})
        s.commit()
    except IntegrityError:
        s.rollback();raise HTTPException(409,'Этот логин уже занят')
    return public(target)

@router.post('/users',status_code=201)
def create_user(body:UserInput,user=Depends(admin),s=Depends(get_db)): return save_user(body,s,user)
@router.put('/users/{id}')
def update_user(id:int,body:UserInput,user=Depends(admin),s=Depends(get_db)): return save_user(body,s,user,id)
@router.delete('/users/{id}',status_code=204)
def delete_user(id:int,version:int=Query(ge=1),user=Depends(admin),s=Depends(get_db)):
    lock(s,'user-administration')
    target=s.get(User,id,populate_existing=True)
    if not target or target.deleted: raise HTTPException(404,'Пользователь не найден')
    if target.version!=version: raise HTTPException(409,'Пользователь изменён. Обновите список.')
    if target.role=='admin' and target.active:
        other=s.scalar(select(User.id).where(User.role=='admin',User.active==True,User.deleted==False,User.id!=id).limit(1))
        if other is None: raise HTTPException(409,'Нельзя удалить последнего активного администратора')
    before=public(target)
    target.deleted=True;target.active=False;target.version+=1
    target.password_hash=password_hash(secrets.token_urlsafe(48))
    s.execute(delete(UserSession).where(UserSession.user_id==id))
    audit(s,user.id,id,'delete',{'before':before})
    s.commit()

@router.get('/users/audit')
def user_audit(user=Depends(admin),s=Depends(get_db)):
    return [{k:getattr(a,k) for k in ('id','actor_id','target_id','action','created_at','details')} for a in s.scalars(select(UserAudit).order_by(UserAudit.id.desc()).limit(100))]

if __name__=='__main__':
    password=os.environ.get('ADMIN_INITIAL_PASSWORD')
    with Session() as s:
        if password: bootstrap(s,password)
        elif not s.scalar(select(User.id).limit(1)): raise RuntimeError('Set ADMIN_INITIAL_PASSWORD for first startup')
