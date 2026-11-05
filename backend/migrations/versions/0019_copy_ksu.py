"""Independent KSU entries and explicit copy membership; preserve all stock/history."""
from alembic import op
import sqlalchemy as sa

revision = '0019_copy_ksu'
down_revision = '0018_visit_qr'
branch_labels = None
depends_on = None


def upgrade():
    # 0010 historically creates KsuEntry from model metadata on fresh installs.
    present = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('ksu_entries')}
    for name, type_, nullable, default in [
        ('request_key', sa.String(36), True, None),
        ('payload_hash', sa.String(64), True, None),
        ('source', sa.String(255), False, ''),
        ('invoice', sa.String(255), False, ''),
        ('note', sa.Text(), False, ''),
    ]:
        if name not in present:
            op.add_column('ksu_entries', sa.Column(name, type_, nullable=nullable, server_default=default))
    if 'request_key' not in present:
        op.create_unique_constraint('uq_ksu_request_key', 'ksu_entries', ['request_key'])
    for name in ('acquisition_id', 'acquisition_version', 'document_on'):
        op.alter_column('ksu_entries', name, nullable=True)
    op.add_column('copies', sa.Column('ksu_entry_id', sa.Integer(), sa.ForeignKey('ksu_entries.id', ondelete='RESTRICT'), nullable=True))
    op.create_index('ix_copies_ksu_entry_id', 'copies', ['ksu_entry_id'])
    op.add_column('copies', sa.Column('invoice', sa.String(255), nullable=False, server_default=''))
    op.execute('''UPDATE ksu_entries e SET source=a.source, invoice=a.invoice,
        note=a.note, document_on=a.document_on FROM acquisitions a WHERE a.id=e.acquisition_id''')
    op.execute('''UPDATE copies c SET ksu_entry_id=e.id, received_on=a.received_on,
        source=a.source, invoice=a.invoice FROM acquisition_lines l
        JOIN acquisitions a ON a.id=l.acquisition_id
        JOIN ksu_entries e ON e.acquisition_id=a.id WHERE c.line_id=l.id''')


def downgrade():
    raise RuntimeError('Copy accounting and KSU history must be preserved; use a forward migration.')
