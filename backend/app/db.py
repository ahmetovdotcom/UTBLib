import os
from sqlalchemy import create_engine, JSON, String, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
engine=create_engine(os.getenv('DATABASE_URL','postgresql+psycopg://catalog:catalog@db/catalog'))
Session=sessionmaker(engine)
class Base(DeclarativeBase): pass
class DocumentType(Base):
    __tablename__='document_types'
    id: Mapped[int]=mapped_column(primary_key=True)
    name: Mapped[str]=mapped_column(String(120),unique=True)
    config: Mapped[list]=mapped_column(JSON().with_variant(JSONB,'postgresql'))
class Record(Base):
    __tablename__='records'
    id: Mapped[int]=mapped_column(primary_key=True)
    type_id: Mapped[int]=mapped_column(__import__('sqlalchemy').ForeignKey('document_types.id'))
    version: Mapped[int]=mapped_column(Integer,default=1)
    marc: Mapped[dict]=mapped_column(JSON().with_variant(JSONB,'postgresql'))
    search_text: Mapped[str]=mapped_column(Text)
class VocabularyEntry(Base):
    __tablename__='vocabulary_entries'
    __table_args__=(__import__('sqlalchemy').UniqueConstraint('type_id','tag','code','value_key',name='uq_vocabulary_value'),)
    id: Mapped[int]=mapped_column(primary_key=True)
    type_id: Mapped[int]=mapped_column(__import__('sqlalchemy').ForeignKey('document_types.id'),index=True)
    tag: Mapped[str]=mapped_column(String(3))
    code: Mapped[str]=mapped_column(String(1))
    value: Mapped[str]=mapped_column(Text)
    label: Mapped[str]=mapped_column(Text,default='')
    value_key: Mapped[str]=mapped_column(String(64))

class MarcsqlSource(Base):
    __tablename__='marcsql_sources'
    __table_args__=(__import__('sqlalchemy').UniqueConstraint('source','doc_id',name='uq_marcsql_source_doc'),)
    id: Mapped[int]=mapped_column(primary_key=True)
    source: Mapped[str]=mapped_column(String(200))
    doc_id: Mapped[int]=mapped_column(Integer)
    record_id: Mapped[int|None]=mapped_column(__import__('sqlalchemy').ForeignKey('records.id',ondelete='SET NULL'),nullable=True)
    item: Mapped[str]=mapped_column(Text)
    rectype: Mapped[str]=mapped_column(String(1))
    biblevel: Mapped[str]=mapped_column(String(1))
    checksum: Mapped[str]=mapped_column(String(64))

from datetime import date, datetime, timezone
from decimal import Decimal
from sqlalchemy import Date, DateTime, Numeric, ForeignKey, CheckConstraint

def utcnow(): return datetime.now(timezone.utc)

class Acquisition(Base):
    document_on: Mapped[date|None]=mapped_column(Date,nullable=True)
    __tablename__='acquisitions'
    status: Mapped[str]=mapped_column(String(20),default='posted',server_default='posted')
    version: Mapped[int]=mapped_column(Integer,default=1,server_default='1')
    id: Mapped[int]=mapped_column(primary_key=True)
    request_key: Mapped[str]=mapped_column(String(36),unique=True)
    payload_hash: Mapped[str]=mapped_column(String(64))
    invoice: Mapped[str]=mapped_column(String(255))
    received_on: Mapped[date]=mapped_column(Date,index=True)
    source: Mapped[str]=mapped_column(String(255))
    note: Mapped[str]=mapped_column(Text,default='')
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)

class AcquisitionLine(Base):
    __tablename__='acquisition_lines'
    __table_args__=(CheckConstraint('quantity >= 0 AND quantity <= 10000',name='ck_acq_quantity'),CheckConstraint('unit_price IS NULL OR unit_price >= 0',name='ck_acq_price'),)
    id: Mapped[int]=mapped_column(primary_key=True)
    acquisition_id: Mapped[int]=mapped_column(ForeignKey('acquisitions.id',ondelete='RESTRICT'),index=True)
    record_id: Mapped[int]=mapped_column(ForeignKey('records.id',ondelete='RESTRICT'),index=True)
    title_snapshot: Mapped[str]=mapped_column(Text)
    quantity: Mapped[int]=mapped_column(Integer)
    unit_price: Mapped[Decimal|None]=mapped_column(Numeric(14,2),nullable=True)
    currency: Mapped[str]=mapped_column(String(3))
    sigla: Mapped[str]=mapped_column(String(255))
    note: Mapped[str]=mapped_column(Text,default='')

class Copy(Base):
    __tablename__='copies'
    status: Mapped[str]=mapped_column(String(20),default='active',server_default='active')
    __table_args__=(CheckConstraint('(line_id IS NOT NULL AND record_id IS NULL) OR (line_id IS NULL AND record_id IS NOT NULL AND request_key IS NOT NULL AND payload_hash IS NOT NULL)',name='ck_copy_origin'),CheckConstraint("length(trim(barcode))>0",name='ck_copy_barcode_nonempty'),CheckConstraint('unit_price IS NULL OR unit_price >= 0',name='ck_copy_price'),)
    id: Mapped[int]=mapped_column(primary_key=True)
    line_id: Mapped[int|None]=mapped_column(ForeignKey('acquisition_lines.id',ondelete='RESTRICT'),index=True,nullable=True)
    record_id: Mapped[int|None]=mapped_column(ForeignKey('records.id',ondelete='RESTRICT'),index=True,nullable=True)
    request_key: Mapped[str|None]=mapped_column(String(36),unique=True,nullable=True)
    payload_hash: Mapped[str|None]=mapped_column(String(64),nullable=True)
    unit_price: Mapped[Decimal|None]=mapped_column(Numeric(14,2),nullable=True)
    currency: Mapped[str]=mapped_column(String(3),default='KZT',server_default='KZT')
    received_on: Mapped[date|None]=mapped_column(Date,nullable=True)
    source: Mapped[str]=mapped_column(String(255),default='',server_default='')
    inventory_number: Mapped[str]=mapped_column(String(100),unique=True)
    barcode: Mapped[str]=mapped_column(String(100),unique=True)
    sigla: Mapped[str]=mapped_column(String(255))
    checked_on: Mapped[date|None]=mapped_column(Date,nullable=True)
    note: Mapped[str]=mapped_column(Text,default='')
    version: Mapped[int]=mapped_column(Integer,default=1)

class CopyHistory(Base):
    __tablename__='copy_history'
    id: Mapped[int]=mapped_column(primary_key=True)
    copy_id: Mapped[int]=mapped_column(ForeignKey('copies.id',ondelete='RESTRICT'),index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)
    before: Mapped[dict]=mapped_column(JSON().with_variant(JSONB,'postgresql'))
    after: Mapped[dict]=mapped_column(JSON().with_variant(JSONB,'postgresql'))

class RecordCreation(Base):
    __tablename__='record_creations'
    request_key: Mapped[str]=mapped_column(String(36),primary_key=True)
    payload_hash: Mapped[str]=mapped_column(String(64))
    record_id: Mapped[int|None]=mapped_column(ForeignKey('records.id',ondelete='SET NULL'),nullable=True)

class AcquisitionHistory(Base):
    __tablename__='acquisition_history'
    id: Mapped[int]=mapped_column(primary_key=True)
    acquisition_id: Mapped[int]=mapped_column(ForeignKey('acquisitions.id',ondelete='RESTRICT'),index=True)
    request_key: Mapped[str]=mapped_column(String(36),unique=True)
    payload_hash: Mapped[str]=mapped_column(String(64))
    action: Mapped[str]=mapped_column(String(20))
    reason: Mapped[str]=mapped_column(Text)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)
    before: Mapped[dict]=mapped_column(JSON().with_variant(JSONB,'postgresql'))
    after: Mapped[dict]=mapped_column(JSON().with_variant(JSONB,'postgresql'))

class Withdrawal(Base):
    __tablename__='withdrawals'
    id: Mapped[int]=mapped_column(primary_key=True)
    copy_id: Mapped[int]=mapped_column(ForeignKey('copies.id',ondelete='RESTRICT'),unique=True)
    request_key: Mapped[str]=mapped_column(String(36),unique=True)
    payload_hash: Mapped[str]=mapped_column(String(64))
    withdrawn_on: Mapped[date]=mapped_column(Date,index=True)
    act_number: Mapped[str]=mapped_column(String(255))
    reason: Mapped[str]=mapped_column(Text)
    note: Mapped[str]=mapped_column(Text,default='')
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)
    snapshot: Mapped[dict]=mapped_column(JSON().with_variant(JSONB,'postgresql'))

class MarcsqlCopySource(Base):
    __tablename__='marcsql_copy_sources'
    __table_args__=(__import__('sqlalchemy').UniqueConstraint('source','inv_id',name='uq_marcsql_copy_source_inv'),)
    id: Mapped[int]=mapped_column(primary_key=True)
    source: Mapped[str]=mapped_column(String(200))
    inv_id: Mapped[int]=mapped_column(Integer)
    doc_id: Mapped[int]=mapped_column(Integer)
    copy_id: Mapped[int|None]=mapped_column(ForeignKey('copies.id',ondelete='SET NULL'),nullable=True,index=True)
    raw: Mapped[dict]=mapped_column(JSON().with_variant(JSONB,'postgresql'))
    checksum: Mapped[str]=mapped_column(String(64))

from sqlalchemy import Boolean, BigInteger

def get_db():
    with Session() as s: yield s

class User(Base):
    __tablename__='users'
    deleted: Mapped[bool]=mapped_column(Boolean,default=False,server_default='false')
    id: Mapped[int]=mapped_column(primary_key=True)
    username: Mapped[str]=mapped_column(String(80),unique=True)
    display_name: Mapped[str]=mapped_column(String(160))
    password_hash: Mapped[str]=mapped_column(Text)
    role: Mapped[str]=mapped_column(String(20))
    permissions: Mapped[list]=mapped_column(JSON().with_variant(JSONB,'postgresql'))
    active: Mapped[bool]=mapped_column(Boolean,default=True)
    version: Mapped[int]=mapped_column(Integer,default=1)

class UserSession(Base):
    __tablename__='user_sessions'
    token_hash: Mapped[str]=mapped_column(String(64),primary_key=True)
    user_id: Mapped[int]=mapped_column(ForeignKey('users.id',ondelete='CASCADE'),index=True)
    expires_at: Mapped[int]=mapped_column(BigInteger,index=True)

class LoginAttempt(Base):
    __tablename__='login_attempts'
    key: Mapped[str]=mapped_column(String(64),primary_key=True)
    count: Mapped[int]=mapped_column(Integer)
    expires_at: Mapped[int]=mapped_column(BigInteger)

class UserAudit(Base):
    __tablename__='user_audit'
    id: Mapped[int]=mapped_column(primary_key=True)
    actor_id: Mapped[int|None]=mapped_column(ForeignKey('users.id'),nullable=True)
    target_id: Mapped[int]=mapped_column(ForeignKey('users.id'))
    action: Mapped[str]=mapped_column(String(40))
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)
    details: Mapped[dict]=mapped_column(JSON().with_variant(JSONB,'postgresql'))

class KsuEntry(Base):
    __tablename__='ksu_entries'
    __table_args__=(__import__('sqlalchemy').UniqueConstraint('year','number',name='uq_ksu_number'),)
    id: Mapped[int]=mapped_column(primary_key=True)
    acquisition_id: Mapped[int]=mapped_column(ForeignKey('acquisitions.id',ondelete='RESTRICT'),unique=True)
    acquisition_version: Mapped[int]=mapped_column(Integer)
    year: Mapped[int]=mapped_column(Integer)
    number: Mapped[int]=mapped_column(Integer)
    registered_on: Mapped[date]=mapped_column(Date)
    document_on: Mapped[date]=mapped_column(Date)
    version: Mapped[int]=mapped_column(Integer,default=1)
    snapshot: Mapped[dict]=mapped_column(JSON().with_variant(JSONB,'postgresql'))

class KsuHistory(Base):
    __tablename__='ksu_history'
    id: Mapped[int]=mapped_column(primary_key=True)
    entry_id: Mapped[int]=mapped_column(ForeignKey('ksu_entries.id',ondelete='RESTRICT'),index=True)
    actor_id: Mapped[int]=mapped_column(ForeignKey('users.id'))
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)
    reason: Mapped[str]=mapped_column(Text)
    before: Mapped[dict]=mapped_column(JSON().with_variant(JSONB,'postgresql'))
    after: Mapped[dict]=mapped_column(JSON().with_variant(JSONB,'postgresql'))

class KsuRule(Base):
    __tablename__='ksu_rules'
    code: Mapped[str]=mapped_column(String(120),primary_key=True)
    version: Mapped[int]=mapped_column(Integer,default=1)
    settings: Mapped[dict]=mapped_column(JSON().with_variant(JSONB,'postgresql'))

class RecordActivity(Base):
    __tablename__='record_activity'
    id: Mapped[int]=mapped_column(primary_key=True)
    actor_id: Mapped[int]=mapped_column(ForeignKey('users.id'),index=True)
    actor_name: Mapped[str]=mapped_column(Text)
    record_id: Mapped[int]=mapped_column(Integer,index=True)  # Historical identity survives deletion.
    action: Mapped[str]=mapped_column(String(10))
    title: Mapped[str]=mapped_column(Text)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow,index=True)

# Register library people with the same metadata/migration lifecycle as the catalogue.
from . import reader_models  # noqa: E402,F401

from . import circulation_models  # noqa: E402,F401
