"""First KSU sheet: versioned acquisition snapshots, separate from stock."""
from alembic import op
from app.db import KsuEntry, KsuHistory
revision='0010_ksu'
down_revision='0009_deleted_users'
branch_labels=None
depends_on=None

def upgrade():
    KsuEntry.__table__.create(op.get_bind())
    KsuHistory.__table__.create(op.get_bind())

def downgrade():
    raise RuntimeError('KSU history must be preserved; use a forward migration.')
