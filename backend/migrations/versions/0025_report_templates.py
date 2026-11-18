"""Private, reusable report definitions; no catalogue or accounting changes."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0025_report_templates'
down_revision = '0024_catalog_file_chunks'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('report_templates',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(120), nullable=False),
        sa.Column('definition', postgresql.JSONB(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_report_templates_user_id', 'report_templates', ['user_id'])


def downgrade():
    op.drop_table('report_templates')
