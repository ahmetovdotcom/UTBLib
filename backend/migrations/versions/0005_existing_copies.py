"""Allow existing-fund copies without creating acquisition entries."""
from alembic import op
import sqlalchemy as sa
revision='0005_existing_copies'
down_revision='0004_acquisitions'
branch_labels=None
depends_on=None

def upgrade():
    op.alter_column('copies','line_id',nullable=True)
    op.add_column('copies',sa.Column('record_id',sa.Integer(),sa.ForeignKey('records.id',ondelete='RESTRICT'),nullable=True))
    op.add_column('copies',sa.Column('request_key',sa.String(36),nullable=True))
    op.add_column('copies',sa.Column('payload_hash',sa.String(64),nullable=True))
    op.add_column('copies',sa.Column('unit_price',sa.Numeric(14,2),nullable=True))
    op.add_column('copies',sa.Column('currency',sa.String(3),nullable=False,server_default='KZT'))
    op.add_column('copies',sa.Column('received_on',sa.Date(),nullable=True))
    op.add_column('copies',sa.Column('source',sa.String(255),nullable=False,server_default=''))
    op.create_index('ix_copies_record_id','copies',['record_id'])
    op.create_unique_constraint('uq_copies_request_key','copies',['request_key'])
    op.create_check_constraint('ck_copy_origin','copies','(line_id IS NOT NULL AND record_id IS NULL) OR (line_id IS NULL AND record_id IS NOT NULL AND request_key IS NOT NULL AND payload_hash IS NOT NULL)')
    op.create_check_constraint('ck_copy_price','copies','unit_price IS NULL OR unit_price >= 0')

def downgrade():
    # Refuse to discard existing-fund inventory on rollback.
    if op.get_bind().execute(sa.text('SELECT count(*) FROM copies WHERE line_id IS NULL')).scalar():
        raise RuntimeError('Cannot downgrade while existing-fund copies exist; retain schema and roll forward.')
    op.drop_constraint('ck_copy_origin','copies',type_='check')
    op.drop_constraint('ck_copy_price','copies',type_='check')
    op.drop_constraint('uq_copies_request_key','copies',type_='unique')
    op.drop_index('ix_copies_record_id',table_name='copies')
    for column in ['source','received_on','currency','unit_price','payload_hash','request_key','record_id']:
        op.drop_column('copies',column)
    op.alter_column('copies','line_id',nullable=False)
