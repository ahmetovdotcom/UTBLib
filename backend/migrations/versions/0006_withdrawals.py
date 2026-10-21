"""Audited corrections, cancellations and inventory withdrawals."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
revision='0006_withdrawals'
down_revision='0005_existing_copies'
branch_labels=None
depends_on=None

def upgrade():
    op.add_column('acquisitions',sa.Column('status',sa.String(20),nullable=False,server_default='posted'))
    op.add_column('acquisitions',sa.Column('version',sa.Integer(),nullable=False,server_default='1'))
    op.add_column('copies',sa.Column('status',sa.String(20),nullable=False,server_default='active'))
    op.create_check_constraint('ck_receipt_status','acquisitions',"status IN ('posted','cancelled')")
    op.create_check_constraint('ck_copy_status','copies',"status IN ('active','withdrawn','cancelled')")
    op.drop_constraint('ck_acq_quantity','acquisition_lines',type_='check')
    op.create_check_constraint('ck_acq_quantity','acquisition_lines','quantity >= 0 AND quantity <= 10000')
    op.create_table('acquisition_history',sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('acquisition_id',sa.Integer(),sa.ForeignKey('acquisitions.id',ondelete='RESTRICT'),nullable=False),
        sa.Column('request_key',sa.String(36),nullable=False,unique=True),sa.Column('payload_hash',sa.String(64),nullable=False),
        sa.Column('action',sa.String(20),nullable=False),sa.Column('reason',sa.Text(),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('before',JSONB(),nullable=False),sa.Column('after',JSONB(),nullable=False))
    op.create_index('ix_acquisition_history_acquisition_id','acquisition_history',['acquisition_id'])
    op.create_table('withdrawals',sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('copy_id',sa.Integer(),sa.ForeignKey('copies.id',ondelete='RESTRICT'),nullable=False,unique=True),
        sa.Column('request_key',sa.String(36),nullable=False,unique=True),sa.Column('payload_hash',sa.String(64),nullable=False),
        sa.Column('withdrawn_on',sa.Date(),nullable=False),sa.Column('act_number',sa.String(255),nullable=False),
        sa.Column('reason',sa.Text(),nullable=False),sa.Column('note',sa.Text(),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('snapshot',JSONB(),nullable=False))
    op.create_index('ix_withdrawals_withdrawn_on','withdrawals',['withdrawn_on'])

def downgrade():
    db=op.get_bind()
    if db.execute(sa.text('SELECT (SELECT count(*) FROM withdrawals)+(SELECT count(*) FROM acquisition_history)')).scalar():
        raise RuntimeError('Audit operations exist: use a forward migration to retain history.')
    op.drop_table('withdrawals');op.drop_table('acquisition_history')
    op.drop_constraint('ck_acq_quantity','acquisition_lines',type_='check')
    op.create_check_constraint('ck_acq_quantity','acquisition_lines','quantity > 0 AND quantity <= 10000')
    op.drop_constraint('ck_copy_status','copies',type_='check');op.drop_constraint('ck_receipt_status','acquisitions',type_='check')
    op.drop_column('copies','status');op.drop_column('acquisitions','version');op.drop_column('acquisitions','status')
