"""Remove accounts from use without breaking audit references."""
from alembic import op
import sqlalchemy as sa
revision='0009_deleted_users'
down_revision='0008_users'
branch_labels=None
depends_on=None

def upgrade():
    op.add_column('users',sa.Column('deleted',sa.Boolean(),nullable=False,server_default=sa.false()))

def downgrade():
    if op.get_bind().execute(sa.text('SELECT count(*) FROM users WHERE deleted')).scalar():
        raise RuntimeError('Deleted accounts exist; use a forward migration to preserve deletion state.')
    op.drop_column('users','deleted')
