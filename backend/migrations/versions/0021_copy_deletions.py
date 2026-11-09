"""Keep deletion audit outside stock so identifiers can be reused."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0021_copy_deletions'
down_revision = '0020_events'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('copy_deletions',
        sa.Column('copy_id', sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column('request_key', sa.String(36), nullable=False, unique=True),
        sa.Column('payload_hash', sa.String(64), nullable=False),
        sa.Column('creation_request_key', sa.String(36), unique=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('snapshot', sa.JSON().with_variant(JSONB, 'postgresql'), nullable=False),
        sa.Column('result', sa.JSON().with_variant(JSONB, 'postgresql'), nullable=False))


def downgrade():
    raise RuntimeError('Deletion audit must be preserved; use a forward migration.')
