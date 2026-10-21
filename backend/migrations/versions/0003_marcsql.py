"""Preserve MARCSQL originals and deduplicate imports."""
from alembic import op
import sqlalchemy as sa

revision = '0003_marcsql'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'marcsql_sources',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('source', sa.String(200), nullable=False),
        sa.Column('doc_id', sa.Integer(), nullable=False),
        sa.Column('record_id', sa.Integer(), sa.ForeignKey('records.id', ondelete='SET NULL'), nullable=True),
        sa.Column('item', sa.Text(), nullable=False),
        sa.Column('rectype', sa.String(1), nullable=False),
        sa.Column('biblevel', sa.String(1), nullable=False),
        sa.Column('checksum', sa.String(64), nullable=False),
        sa.UniqueConstraint('source', 'doc_id', name='uq_marcsql_source_doc'),
    )


def downgrade():
    op.drop_table('marcsql_sources')
