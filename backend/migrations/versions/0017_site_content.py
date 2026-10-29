"""Staff content store for the separate library frontend (no reader/account changes)."""
from alembic import op
import sqlalchemy as sa
revision = '0017_site_content'
down_revision = '0016_circulation'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('site_content', sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('kind', sa.String(20), nullable=False), sa.Column('slug', sa.String(160), nullable=False),
        sa.Column('status', sa.String(20), nullable=False), sa.Column('version', sa.Integer, nullable=False),
        sa.Column('data', sa.JSON, nullable=False), sa.Column('published_at', sa.DateTime(timezone=True)),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('kind', 'slug', name='uq_site_content_slug'))
    op.create_index('ix_site_content_kind', 'site_content', ['kind'])
    op.create_table('site_assets', sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('item_id', sa.Integer, sa.ForeignKey('site_content.id', ondelete='CASCADE'), nullable=False),
        sa.Column('slot', sa.String(10), nullable=False), sa.Column('name', sa.String(200), nullable=False),
        sa.Column('mime', sa.String(50), nullable=False), sa.Column('size', sa.Integer, nullable=False),
        sa.Column('content', sa.LargeBinary, nullable=False), sa.UniqueConstraint('item_id', 'slot', name='uq_site_asset_slot'))
    op.create_table('site_content_audit', sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('item_id', sa.Integer, sa.ForeignKey('site_content.id'), nullable=False),
        sa.Column('actor_id', sa.Integer, sa.ForeignKey('users.id'), nullable=False),
        sa.Column('at', sa.DateTime(timezone=True), nullable=False), sa.Column('action', sa.String(30), nullable=False),
        sa.Column('snapshot', sa.JSON, nullable=False))


def downgrade():
    op.drop_table('site_content_audit')
    op.drop_table('site_assets')
    op.drop_table('site_content')
