"""Immutable acquisition headers/lines, copies and retry receipts. No data backfill."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
revision='0004_acquisitions'
down_revision='0003_marcsql'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('acquisitions',sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('request_key',sa.String(36),nullable=False,unique=True),sa.Column('payload_hash',sa.String(64),nullable=False),
        sa.Column('invoice',sa.String(255),nullable=False),sa.Column('received_on',sa.Date(),nullable=False),
        sa.Column('source',sa.String(255),nullable=False),sa.Column('note',sa.Text(),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False))
    op.create_index('ix_acquisitions_received_on','acquisitions',['received_on'])
    op.create_table('acquisition_lines',sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('acquisition_id',sa.Integer(),sa.ForeignKey('acquisitions.id',ondelete='RESTRICT'),nullable=False),
        sa.Column('record_id',sa.Integer(),sa.ForeignKey('records.id',ondelete='RESTRICT'),nullable=False),
        sa.Column('title_snapshot',sa.Text(),nullable=False),sa.Column('quantity',sa.Integer(),nullable=False),
        sa.Column('unit_price',sa.Numeric(14,2),nullable=True),sa.Column('currency',sa.String(3),nullable=False),
        sa.Column('sigla',sa.String(255),nullable=False),sa.Column('note',sa.Text(),nullable=False),
        sa.CheckConstraint('quantity > 0 AND quantity <= 10000',name='ck_acq_quantity'),sa.CheckConstraint('unit_price IS NULL OR unit_price >= 0',name='ck_acq_price'))
    op.create_index('ix_acquisition_lines_acquisition_id','acquisition_lines',['acquisition_id'])
    op.create_index('ix_acquisition_lines_record_id','acquisition_lines',['record_id'])
    op.create_table('copies',sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('line_id',sa.Integer(),sa.ForeignKey('acquisition_lines.id',ondelete='RESTRICT'),nullable=False),
        sa.Column('inventory_number',sa.String(100),nullable=False,unique=True),sa.Column('barcode',sa.String(100),nullable=False,unique=True),
        sa.Column('sigla',sa.String(255),nullable=False),sa.Column('checked_on',sa.Date(),nullable=True),
        sa.Column('note',sa.Text(),nullable=False),sa.Column('version',sa.Integer(),nullable=False))
    op.create_index('ix_copies_line_id','copies',['line_id'])
    op.create_table('copy_history',sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('copy_id',sa.Integer(),sa.ForeignKey('copies.id',ondelete='RESTRICT'),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('before',JSONB(),nullable=False),sa.Column('after',JSONB(),nullable=False))
    op.create_index('ix_copy_history_copy_id','copy_history',['copy_id'])
    op.create_table('record_creations',sa.Column('request_key',sa.String(36),primary_key=True),sa.Column('payload_hash',sa.String(64),nullable=False),
        sa.Column('record_id',sa.Integer(),sa.ForeignKey('records.id',ondelete='SET NULL'),nullable=True))

def downgrade():
    for table in ['record_creations','copy_history','copies','acquisition_lines','acquisitions']: op.drop_table(table)
