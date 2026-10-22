"""Library people are independent of staff accounts; no implicit login or privileges."""
from datetime import date, datetime
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, JSON, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base, utcnow

class Branch(Base):
    __tablename__='reader_branches'
    id: Mapped[int]=mapped_column(primary_key=True)
    code: Mapped[str]=mapped_column(String(40),unique=True)
    name: Mapped[str]=mapped_column(String(200))
    active: Mapped[bool]=mapped_column(Boolean,default=True)
    position: Mapped[int]=mapped_column(Integer,default=0)

class Reader(Base):
    __tablename__='reader_profiles'
    id: Mapped[int]=mapped_column(primary_key=True)
    user_id: Mapped[int|None]=mapped_column(ForeignKey('users.id',ondelete='RESTRICT'),unique=True)
    version: Mapped[int]=mapped_column(default=1)
    full_name: Mapped[str]=mapped_column(String(300),index=True)
    ticket_number: Mapped[str]=mapped_column(String(100),unique=True)
    barcode: Mapped[str]=mapped_column(String(40),unique=True)
    category: Mapped[str]=mapped_column(String(30),index=True)
    status: Mapped[str]=mapped_column(String(20),default='active',index=True)
    block_reason: Mapped[str]=mapped_column(String(1000),default='')
    limits_override: Mapped[dict]=mapped_column(JSON,default=dict)
    email: Mapped[str]=mapped_column(String(250),default='',index=True)
    login: Mapped[str]=mapped_column(String(150),default='',index=True)
    phone: Mapped[str]=mapped_column(String(100),default='')
    additional_email: Mapped[str]=mapped_column(String(250),default='')
    iin: Mapped[str|None]=mapped_column(String(12),unique=True)
    birth_date: Mapped[date|None]=mapped_column(Date)
    gender: Mapped[str]=mapped_column(String(20),default='')
    gender_source: Mapped[str]=mapped_column(String(30),default='')
    faculty: Mapped[str]=mapped_column(String(250),default='',index=True)
    department: Mapped[str]=mapped_column(String(250),default='',index=True)
    study_group: Mapped[str]=mapped_column(String(150),default='',index=True)
    education_level: Mapped[str]=mapped_column(String(100),default='')
    education_program: Mapped[str]=mapped_column(String(250),default='',index=True)
    program_code: Mapped[str]=mapped_column(String(100),default='')
    course: Mapped[int|None]=mapped_column(Integer,index=True)
    cohort_year: Mapped[int|None]=mapped_column(Integer,index=True)
    position: Mapped[str]=mapped_column(String(250),default='')
    subdivision: Mapped[str]=mapped_column(String(250),default='')
    is_teaching_staff: Mapped[bool]=mapped_column(Boolean,default=False)
    registered_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow,index=True)
    reregistered_at: Mapped[date|None]=mapped_column(Date)
    valid_until: Mapped[date|None]=mapped_column(Date)
    preferred_branch_id: Mapped[int|None]=mapped_column(ForeignKey('reader_branches.id',ondelete='RESTRICT'))
    source: Mapped[str]=mapped_column(String(30),default='manual',index=True)
    external_status: Mapped[str]=mapped_column(String(100),default='')
    last_synced_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    field_owners: Mapped[dict]=mapped_column(JSON,default=dict)
    manual_overrides: Mapped[list]=mapped_column(JSON,default=list)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)

Index('ix_reader_ticket_lower',__import__('sqlalchemy').func.lower(Reader.ticket_number),unique=True)
Index('ix_reader_barcode_lower',__import__('sqlalchemy').func.lower(Reader.barcode),unique=True)

class ReaderIdentity(Base):
    __tablename__='reader_identities'
    __table_args__=(UniqueConstraint('source','entity_type','external_id',name='uq_reader_identity'),)
    id: Mapped[int]=mapped_column(primary_key=True)
    reader_id: Mapped[int]=mapped_column(ForeignKey('reader_profiles.id',ondelete='RESTRICT'),index=True)
    source: Mapped[str]=mapped_column(String(30))
    entity_type: Mapped[str]=mapped_column(String(30))
    external_id: Mapped[str]=mapped_column(String(200))
    last_synced_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)

class ReaderServicePoint(Base):
    __tablename__='reader_service_points'
    reader_id: Mapped[int]=mapped_column(ForeignKey('reader_profiles.id',ondelete='RESTRICT'),primary_key=True)
    branch_id: Mapped[int]=mapped_column(ForeignKey('reader_branches.id',ondelete='RESTRICT'),primary_key=True)
    primary: Mapped[bool]=mapped_column(Boolean,default=False)

class ReaderPhoto(Base):
    __tablename__='reader_photos'
    reader_id: Mapped[int]=mapped_column(ForeignKey('reader_profiles.id',ondelete='RESTRICT'),primary_key=True)
    content: Mapped[bytes]=mapped_column(LargeBinary)
    sha256: Mapped[str]=mapped_column(String(64))
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)

class LibraryVisit(Base):
    __tablename__='library_visits'
    __table_args__=(Index('ix_visits_reader_time','reader_id','scanned_at'),Index('ix_visits_branch_time','branch_id','scanned_at'))
    id: Mapped[int]=mapped_column(primary_key=True)
    reader_id: Mapped[int]=mapped_column(ForeignKey('reader_profiles.id',ondelete='RESTRICT'))
    branch_id: Mapped[int]=mapped_column(ForeignKey('reader_branches.id',ondelete='RESTRICT'))
    scanned_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow,index=True)
    scanned_by: Mapped[int]=mapped_column(ForeignKey('users.id',ondelete='RESTRICT'))
    source: Mapped[str]=mapped_column(String(20),default='desk')
    notes: Mapped[str]=mapped_column(String(1000),default='')

class ReaderCounter(Base):
    __tablename__='reader_counters'
    name: Mapped[str]=mapped_column(String(200),primary_key=True)
    value: Mapped[int]=mapped_column(Integer)

class ReaderAudit(Base):
    __tablename__='reader_audit'
    id: Mapped[int]=mapped_column(primary_key=True)
    reader_id: Mapped[int|None]=mapped_column(ForeignKey('reader_profiles.id',ondelete='RESTRICT'),index=True)
    actor_id: Mapped[int|None]=mapped_column(ForeignKey('users.id',ondelete='RESTRICT'))
    action: Mapped[str]=mapped_column(String(50))
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)
    details: Mapped[dict]=mapped_column(JSON,default=dict)

class ReaderSyncRun(Base):
    __tablename__='reader_sync_runs'
    id: Mapped[int]=mapped_column(primary_key=True)
    source: Mapped[str]=mapped_column(String(40),index=True)
    started_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)
    ended_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    status: Mapped[str]=mapped_column(String(30),default='running')
    complete: Mapped[bool]=mapped_column(Boolean,default=False)
    parameters: Mapped[dict]=mapped_column(JSON,default=dict)
    counts: Mapped[dict]=mapped_column(JSON,default=dict)
    message: Mapped[str]=mapped_column(String(1000),default='')

class ReaderConflict(Base):
    __tablename__='reader_conflicts'
    id: Mapped[int]=mapped_column(primary_key=True)
    reader_id: Mapped[int|None]=mapped_column(ForeignKey('reader_profiles.id',ondelete='RESTRICT'),index=True)
    run_id: Mapped[int|None]=mapped_column(ForeignKey('reader_sync_runs.id',ondelete='RESTRICT'))
    source: Mapped[str]=mapped_column(String(30))
    entity_type: Mapped[str]=mapped_column(String(30))
    external_id: Mapped[str]=mapped_column(String(200))
    code: Mapped[str]=mapped_column(String(100))
    resolved: Mapped[bool]=mapped_column(Boolean,default=False,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)

class ReaderRateLimit(Base):
    __tablename__='reader_rate_limits'
    key: Mapped[str]=mapped_column(String(120),primary_key=True)
    count: Mapped[int]=mapped_column(Integer)
    window: Mapped[int]=mapped_column(Integer)
