"""Separate event registry and attendance; ordinary visits remain unchanged."""
from alembic import op
import sqlalchemy as sa

revision = '0020_events'
down_revision = '0019_copy_ksu'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('library_events',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(500), nullable=False),
        sa.Column('date_from', sa.Date(), nullable=False),
        sa.Column('date_to', sa.Date(), nullable=False),
        sa.Column('format', sa.String(150), nullable=False),
        sa.Column('branch_id', sa.Integer(), sa.ForeignKey('reader_branches.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('location', sa.String(300), nullable=False),
        sa.Column('responsible', sa.String(500), nullable=False),
        sa.Column('coorganizers', sa.String(500), nullable=False),
        sa.Column('protocol', sa.Boolean(), nullable=False),
        sa.Column('protocol_url', sa.String(2000), nullable=False),
        sa.Column('instagram_url', sa.String(2000), nullable=False),
        sa.Column('notes', sa.Text(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('qr_token', sa.String(64), unique=True),
        sa.Column('qr_enabled', sa.Boolean(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_library_events_date_from', 'library_events', ['date_from'])
    op.create_table('event_attendance',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('event_id', sa.Integer(), sa.ForeignKey('library_events.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('reader_id', sa.Integer(), sa.ForeignKey('reader_profiles.id', ondelete='RESTRICT')),
        sa.Column('branch_id', sa.Integer(), sa.ForeignKey('reader_branches.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('scanned_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('scanned_by', sa.Integer(), sa.ForeignKey('users.id', ondelete='RESTRICT')),
        sa.Column('source', sa.String(20), nullable=False),
        sa.Column('guest_name', sa.String(300)),
        sa.Column('guest_group', sa.String(150)),
        sa.Column('guest_course', sa.Integer()),
        sa.Column('guest_key', sa.String(64)),
        sa.UniqueConstraint('event_id', 'reader_id', name='uq_event_reader'),
        sa.UniqueConstraint('event_id', 'guest_key', name='uq_event_guest'))
    op.create_index('ix_event_attendance_event_scanned', 'event_attendance', ['event_id', 'scanned_at'])


def downgrade():
    raise RuntimeError('Event attendance must be preserved; use a forward migration.')
