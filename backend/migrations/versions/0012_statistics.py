"""Prospective staff catalog activity."""
from alembic import op
from app.db import RecordActivity
revision='0012_statistics'
down_revision='0011_auto_ksu'
branch_labels=None
depends_on=None

def upgrade():
    RecordActivity.__table__.create(op.get_bind())

def downgrade():
    raise RuntimeError('Preserve staff activity history with a forward migration.')
