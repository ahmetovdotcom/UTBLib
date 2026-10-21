"""Automatic KSU numbers and one-time literature mappings."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session
from app.db import KsuRule,Acquisition,KsuEntry
revision='0011_auto_ksu'
down_revision='0010_ksu'
branch_labels=None
depends_on=None

def upgrade():
    op.add_column('acquisitions',sa.Column('document_on',sa.Date(),nullable=True))
    KsuRule.__table__.create(op.get_bind())
    # Preserve all existing KSU numbers, including cancelled receipts. Fill only missing associations.
    from app.ksu_auto import ensure_entry
    with Session(bind=op.get_bind()) as s:
        for a in s.scalars(sa.select(Acquisition).order_by(Acquisition.received_on,Acquisition.id)):
            ensure_entry(s,a)
        s.flush()

def downgrade():
    raise RuntimeError('Use a forward migration to preserve KSU mappings and numbers.')
