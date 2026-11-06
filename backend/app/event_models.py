"""Event attendance is independent of library visits and public announcements."""
from datetime import date, datetime
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base, utcnow


class LibraryEvent(Base):
    __tablename__ = 'library_events'
    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(default=1)
    title: Mapped[str] = mapped_column(String(500))
    date_from: Mapped[date] = mapped_column(Date, index=True)
    date_to: Mapped[date] = mapped_column(Date)
    format: Mapped[str] = mapped_column(String(150), default='')
    branch_id: Mapped[int] = mapped_column(ForeignKey('reader_branches.id', ondelete='RESTRICT'))
    location: Mapped[str] = mapped_column(String(300), default='')
    responsible: Mapped[str] = mapped_column(String(500), default='')
    coorganizers: Mapped[str] = mapped_column(String(500), default='')
    protocol: Mapped[bool] = mapped_column(Boolean, default=False)
    protocol_url: Mapped[str] = mapped_column(String(2000), default='')
    instagram_url: Mapped[str] = mapped_column(String(2000), default='')
    notes: Mapped[str] = mapped_column(Text, default='')
    status: Mapped[str] = mapped_column(String(20), default='planned')
    qr_token: Mapped[str | None] = mapped_column(String(64), unique=True)
    qr_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EventAttendance(Base):
    __tablename__ = 'event_attendance'
    __table_args__ = (
        UniqueConstraint('event_id', 'reader_id', name='uq_event_reader'),
        UniqueConstraint('event_id', 'guest_key', name='uq_event_guest'),
        Index('ix_event_attendance_event_scanned', 'event_id', 'scanned_at'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey('library_events.id', ondelete='RESTRICT'))
    reader_id: Mapped[int | None] = mapped_column(ForeignKey('reader_profiles.id', ondelete='RESTRICT'))
    branch_id: Mapped[int] = mapped_column(ForeignKey('reader_branches.id', ondelete='RESTRICT'))
    scanned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    scanned_by: Mapped[int | None] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'))
    source: Mapped[str] = mapped_column(String(20))
    guest_name: Mapped[str | None] = mapped_column(String(300))
    guest_group: Mapped[str | None] = mapped_column(String(150))
    guest_course: Mapped[int | None] = mapped_column()
    guest_key: Mapped[str | None] = mapped_column(String(64))
