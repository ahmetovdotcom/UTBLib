"""Self check-in, including explicitly unlinked, self-reported visitors."""
from alembic import op
import sqlalchemy as sa

revision = '0018_visit_qr'
down_revision = '0017_site_content'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('visit_qr_points',
        sa.Column('branch_id', sa.Integer, sa.ForeignKey('reader_branches.id', ondelete='RESTRICT'), primary_key=True),
        sa.Column('token', sa.String(64), nullable=False, unique=True),
        sa.Column('enabled', sa.Boolean, nullable=False))
    with op.batch_alter_table('library_visits') as batch:
        batch.alter_column('reader_id', existing_type=sa.Integer(), nullable=True)
        batch.alter_column('scanned_by', existing_type=sa.Integer(), nullable=True)
        batch.add_column(sa.Column('guest_name', sa.String(300)))
        batch.add_column(sa.Column('guest_group', sa.String(150)))
        batch.add_column(sa.Column('guest_course', sa.Integer))
        batch.add_column(sa.Column('guest_key', sa.String(64)))
        batch.create_index('ix_library_visits_guest_key', ['guest_key'])


def downgrade():
    # Never silently discard recorded visits to satisfy the old NOT NULL schema.
    count = op.get_bind().scalar(sa.text('SELECT count(*) FROM library_visits WHERE reader_id IS NULL OR scanned_by IS NULL'))
    if count:
        raise RuntimeError('QR visits exist; export and explicitly resolve them before downgrading')
    with op.batch_alter_table('library_visits') as batch:
        batch.drop_index('ix_library_visits_guest_key')
        for name in ('guest_name', 'guest_group', 'guest_course', 'guest_key'):
            batch.drop_column(name)
        batch.alter_column('reader_id', existing_type=sa.Integer(), nullable=False)
        batch.alter_column('scanned_by', existing_type=sa.Integer(), nullable=False)
    op.drop_table('visit_qr_points')
