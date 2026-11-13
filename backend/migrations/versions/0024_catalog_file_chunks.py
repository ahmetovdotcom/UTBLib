"""Bounded-memory PDF storage; keep all existing inline files readable."""
from alembic import op
import sqlalchemy as sa

revision = '0024_catalog_file_chunks'
down_revision = '0023_catalog_files'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('catalog_files', sa.Column('chunk_size', sa.Integer(), nullable=False, server_default='0'))
    op.create_table('catalog_file_chunks',
        sa.Column('file_id', sa.String(36), sa.ForeignKey('catalog_files.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('position', sa.Integer(), primary_key=True),
        sa.Column('content', sa.LargeBinary(), nullable=False))


def downgrade():
    # A gigabyte cannot safely be merged into one PostgreSQL bytea value.
    # Never silently discard uploaded books on a schema rollback.
    if op.get_bind().scalar(sa.text('SELECT count(*) FROM catalog_files WHERE chunk_size > 0')):
        raise RuntimeError('Chunked PDFs exist; retain this schema when rolling back application code.')
    op.drop_table('catalog_file_chunks')
    op.drop_column('catalog_files', 'chunk_size')
