"""User accounts, revocable sessions and access administration history."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
revision='0008_users'
down_revision='0007_marcsql_copies'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('users',sa.Column('id',sa.Integer(),primary_key=True),sa.Column('username',sa.String(80),nullable=False,unique=True),sa.Column('display_name',sa.String(160),nullable=False),sa.Column('password_hash',sa.Text(),nullable=False),sa.Column('role',sa.String(20),nullable=False),sa.Column('permissions',JSONB(),nullable=False),sa.Column('active',sa.Boolean(),nullable=False),sa.Column('version',sa.Integer(),nullable=False))
    op.create_table('user_sessions',sa.Column('token_hash',sa.String(64),primary_key=True),sa.Column('user_id',sa.Integer(),sa.ForeignKey('users.id',ondelete='CASCADE'),nullable=False),sa.Column('expires_at',sa.BigInteger(),nullable=False))
    op.create_index('ix_user_sessions_user_id','user_sessions',['user_id'])
    op.create_index('ix_user_sessions_expires_at','user_sessions',['expires_at'])
    op.create_table('login_attempts',sa.Column('key',sa.String(64),primary_key=True),sa.Column('count',sa.Integer(),nullable=False),sa.Column('expires_at',sa.BigInteger(),nullable=False))
    op.create_table('user_audit',sa.Column('id',sa.Integer(),primary_key=True),sa.Column('actor_id',sa.Integer(),sa.ForeignKey('users.id')),sa.Column('target_id',sa.Integer(),sa.ForeignKey('users.id'),nullable=False),sa.Column('action',sa.String(40),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('details',JSONB(),nullable=False))

def downgrade():
    if op.get_bind().execute(sa.text('SELECT count(*) FROM users')).scalar():
        raise RuntimeError('Accounts exist: use a forward migration to preserve access and history.')
    for name in ('user_audit','login_attempts','user_sessions','users'): op.drop_table(name)
