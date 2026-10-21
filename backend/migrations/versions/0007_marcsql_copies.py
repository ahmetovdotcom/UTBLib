"""Archive inventory source rows independently of editable copy metadata."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
revision='0007_marcsql_copies'
down_revision='0006_withdrawals'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('marcsql_copy_sources',sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('source',sa.String(200),nullable=False),sa.Column('inv_id',sa.Integer(),nullable=False),
        sa.Column('doc_id',sa.Integer(),nullable=False),sa.Column('copy_id',sa.Integer(),sa.ForeignKey('copies.id',ondelete='SET NULL'),nullable=True),
        sa.Column('raw',JSONB(),nullable=False),sa.Column('checksum',sa.String(64),nullable=False),
        sa.UniqueConstraint('source','inv_id',name='uq_marcsql_copy_source_inv'))
    op.create_index('ix_marcsql_copy_sources_copy_id','marcsql_copy_sources',['copy_id'])

def downgrade():
    if op.get_bind().execute(sa.text('SELECT count(*) FROM marcsql_copy_sources')).scalar():
        raise RuntimeError('Imported source archive exists; use a forward migration to preserve originals.')
    op.drop_table('marcsql_copy_sources')
