"""Circulation extends existing readers and copies; no duplicate catalogue."""
from datetime import datetime
from decimal import Decimal
from sqlalchemy import String, Text, Integer, JSON, DateTime, Numeric, ForeignKey, Index, CheckConstraint, text
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base, utcnow

class CopyCirculation(Base):
    __tablename__='copy_circulation'
    copy_id:Mapped[int]=mapped_column(ForeignKey('copies.id',ondelete='RESTRICT'),primary_key=True)
    branch_id:Mapped[int|None]=mapped_column(ForeignKey('reader_branches.id',ondelete='RESTRICT'),index=True)
    condition:Mapped[str]=mapped_column(String(30),default='good',server_default='good')
    defects:Mapped[str]=mapped_column(Text,default='',server_default='')
    operation_state:Mapped[str]=mapped_column(String(30),default='normal',server_default='normal')
    access:Mapped[str]=mapped_column(String(20),default='free',server_default='free')
    issue_count:Mapped[int]=mapped_column(Integer,default=0,server_default='0')
    version:Mapped[int]=mapped_column(Integer,default=1,server_default='1')
    __table_args__=(CheckConstraint("condition IN ('good','worn','minor','moderate','severe','irreparable','lost')"),CheckConstraint("operation_state IN ('normal','repair','processing','lost','transfer','display','reserve_stock')"),CheckConstraint("access IN ('free','reading_room','limited')"),CheckConstraint('issue_count>=0'))

class Loan(Base):
    __tablename__='loans'
    id:Mapped[int]=mapped_column(primary_key=True)
    reader_id:Mapped[int]=mapped_column(ForeignKey('reader_profiles.id',ondelete='RESTRICT'))
    copy_id:Mapped[int]=mapped_column(ForeignKey('copies.id',ondelete='RESTRICT'))
    branch_id:Mapped[int|None]=mapped_column(ForeignKey('reader_branches.id',ondelete='RESTRICT'))
    status:Mapped[str]=mapped_column(String(20),default='active')
    issued_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)
    due_at:Mapped[datetime]=mapped_column(DateTime(timezone=True))
    calculated_due_at:Mapped[datetime]=mapped_column(DateTime(timezone=True))
    returned_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    lost_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    closed_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    renewal_count:Mapped[int]=mapped_column(Integer,default=0)
    issued_by:Mapped[int]=mapped_column(ForeignKey('users.id',ondelete='RESTRICT'))
    returned_to:Mapped[int|None]=mapped_column(ForeignKey('users.id',ondelete='RESTRICT'))
    condition_on_return:Mapped[str]=mapped_column(String(30),default='')
    notes:Mapped[str]=mapped_column(Text,default='')
    version:Mapped[int]=mapped_column(Integer,default=1)
    updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)
    __table_args__=(CheckConstraint("(status IN ('active','overdue') AND closed_at IS NULL AND returned_at IS NULL AND lost_at IS NULL) OR (status='returned' AND returned_at IS NOT NULL AND closed_at IS NOT NULL AND lost_at IS NULL) OR (status='lost' AND lost_at IS NOT NULL AND closed_at IS NOT NULL AND returned_at IS NULL)"),CheckConstraint('due_at>issued_at'),Index('ix_loan_reader_status','reader_id','status'),Index('ix_loan_copy_status','copy_id','status'),Index('ix_loan_due','status','due_at'))
Index('uq_open_loan_copy',Loan.copy_id,unique=True,postgresql_where=Loan.closed_at.is_(None),sqlite_where=Loan.closed_at.is_(None))

class LoanEvent(Base):
    __tablename__='loan_events'
    id:Mapped[int]=mapped_column(primary_key=True)
    loan_id:Mapped[int]=mapped_column(ForeignKey('loans.id',ondelete='RESTRICT'),index=True)
    kind:Mapped[str]=mapped_column(String(30))
    at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)
    actor_id:Mapped[int|None]=mapped_column(ForeignKey('users.id',ondelete='RESTRICT'))
    previous_due:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    new_due:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    details:Mapped[dict]=mapped_column(JSON,default=dict)

class Reservation(Base):
    __tablename__='reservations'
    id:Mapped[int]=mapped_column(primary_key=True)
    reader_id:Mapped[int]=mapped_column(ForeignKey('reader_profiles.id',ondelete='RESTRICT'),index=True)
    record_id:Mapped[int]=mapped_column(ForeignKey('records.id',ondelete='RESTRICT'),index=True)
    assigned_copy_id:Mapped[int|None]=mapped_column(ForeignKey('copies.id',ondelete='RESTRICT'))
    pickup_branch_id:Mapped[int|None]=mapped_column(ForeignKey('reader_branches.id',ondelete='RESTRICT'))
    status:Mapped[str]=mapped_column(String(30),default='queued')
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)
    assigned_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    ready_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    expires_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    closed_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    reason:Mapped[str]=mapped_column(Text,default='')
    actor_id:Mapped[int|None]=mapped_column(ForeignKey('users.id',ondelete='RESTRICT'))
    extensions:Mapped[int]=mapped_column(Integer,default=0)
    version:Mapped[int]=mapped_column(Integer,default=1)
    __table_args__=(CheckConstraint("status IN ('pending','queued','confirmed','in_transit','ready_for_pickup','fulfilled','cancelled','expired')"),)
ACTIVE_RESERVATIONS=('pending','queued','confirmed','in_transit','ready_for_pickup')
Index('uq_reservation_reader_record',Reservation.reader_id,Reservation.record_id,unique=True,postgresql_where=Reservation.status.in_(ACTIVE_RESERVATIONS),sqlite_where=Reservation.status.in_(ACTIVE_RESERVATIONS))
Index('uq_reservation_copy',Reservation.assigned_copy_id,unique=True,postgresql_where=Reservation.status.in_(ACTIVE_RESERVATIONS),sqlite_where=Reservation.status.in_(ACTIVE_RESERVATIONS))

class Incident(Base):
    __tablename__='circulation_incidents'
    id:Mapped[int]=mapped_column(primary_key=True)
    reader_id:Mapped[int]=mapped_column(ForeignKey('reader_profiles.id',ondelete='RESTRICT'),index=True)
    loan_id:Mapped[int]=mapped_column(ForeignKey('loans.id',ondelete='RESTRICT'),index=True)
    copy_id:Mapped[int]=mapped_column(ForeignKey('copies.id',ondelete='RESTRICT'))
    kind:Mapped[str]=mapped_column(String(30))
    status:Mapped[str]=mapped_column(String(20),default='open')
    before:Mapped[str]=mapped_column(String(30),default='')
    after:Mapped[str]=mapped_column(String(30),default='')
    description:Mapped[str]=mapped_column(Text,default='')
    action:Mapped[str]=mapped_column(String(30),default='')
    responsible_id:Mapped[int|None]=mapped_column(ForeignKey('users.id',ondelete='RESTRICT'))
    decision:Mapped[str]=mapped_column(Text,default='')
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)
    resolved_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    version:Mapped[int]=mapped_column(Integer,default=1)
    __table_args__=(CheckConstraint("status IN ('open','resolved')"),)

class Fine(Base):
    __tablename__='circulation_fines'
    id:Mapped[int]=mapped_column(primary_key=True)
    reader_id:Mapped[int]=mapped_column(ForeignKey('reader_profiles.id',ondelete='RESTRICT'),index=True)
    loan_id:Mapped[int]=mapped_column(ForeignKey('loans.id',ondelete='RESTRICT'))
    copy_id:Mapped[int]=mapped_column(ForeignKey('copies.id',ondelete='RESTRICT'))
    incident_id:Mapped[int|None]=mapped_column(ForeignKey('circulation_incidents.id',ondelete='RESTRICT'))
    amount:Mapped[Decimal]=mapped_column(Numeric(14,2))
    currency:Mapped[str]=mapped_column(String(3),default='KZT')
    reason:Mapped[str]=mapped_column(String(20))
    status:Mapped[str]=mapped_column(String(20),default='pending')
    charged_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)
    resolved_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    resolved_by:Mapped[int|None]=mapped_column(ForeignKey('users.id',ondelete='RESTRICT'))
    notes:Mapped[str]=mapped_column(Text,default='')
    __table_args__=(CheckConstraint('amount>0'),CheckConstraint("status IN ('pending','paid','waived')"),Index('uq_loan_fine_reason','loan_id','reason',unique=True))

class CirculationAudit(Base):
    __tablename__='circulation_audit'
    id:Mapped[int]=mapped_column(primary_key=True)
    entity:Mapped[str]=mapped_column(String(30))
    entity_id:Mapped[int]=mapped_column(Integer,index=True)
    action:Mapped[str]=mapped_column(String(40))
    actor_id:Mapped[int|None]=mapped_column(ForeignKey('users.id',ondelete='RESTRICT'))
    at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)
    before:Mapped[dict]=mapped_column(JSON,default=dict)
    after:Mapped[dict]=mapped_column(JSON,default=dict)
    reason:Mapped[str]=mapped_column(Text,default='')

class CirculationOperation(Base):
    __tablename__='circulation_operations'
    key:Mapped[str]=mapped_column(String(150),primary_key=True)
    fingerprint:Mapped[str]=mapped_column(String(64))
    result:Mapped[dict]=mapped_column(JSON)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)

class CirculationSettings(Base):
    __tablename__='circulation_settings'
    id:Mapped[int]=mapped_column(primary_key=True)
    value:Mapped[dict]=mapped_column(JSON)
    version:Mapped[int]=mapped_column(Integer,default=1)

class CirculationNotice(Base):
    __tablename__='circulation_notices'
    id:Mapped[int]=mapped_column(primary_key=True)
    key:Mapped[str]=mapped_column(String(200),unique=True)
    reader_id:Mapped[int]=mapped_column(ForeignKey('reader_profiles.id',ondelete='RESTRICT'),index=True)
    loan_id:Mapped[int|None]=mapped_column(ForeignKey('loans.id',ondelete='RESTRICT'))
    kind:Mapped[str]=mapped_column(String(30))
    body:Mapped[dict]=mapped_column(JSON)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)
    # Durable local notification/outbox. No external provider is configured.
    channel:Mapped[str]=mapped_column(String(20),default='local')
