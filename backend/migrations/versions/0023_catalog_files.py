"""Faculty works and private PDF files; existing records remain unchanged."""
from alembic import op
import sqlalchemy as sa
revision='0023_catalog_files'
down_revision='0022_primary_specialty'
branch_labels=None
depends_on=None

def upgrade():
    op.add_column('records',sa.Column('is_faculty_work',sa.Boolean(),nullable=False,server_default=sa.false()))
    op.add_column('records',sa.Column('use_first_page_cover',sa.Boolean(),nullable=False,server_default=sa.false()))
    op.create_table('catalog_files',
        sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('record_id',sa.Integer(),sa.ForeignKey('records.id',ondelete='CASCADE'),unique=True),
        sa.Column('owner_id',sa.Integer(),sa.ForeignKey('users.id'),nullable=False,index=True),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('name',sa.String(255),nullable=False),
        sa.Column('size',sa.Integer(),nullable=False),
        sa.Column('pages',sa.Integer(),nullable=False),
        sa.Column('content',sa.LargeBinary(),nullable=False),
        sa.Column('cover',sa.LargeBinary(),nullable=False))

def downgrade():
    op.drop_table('catalog_files')
    op.drop_column('records','use_first_page_cover')
    op.drop_column('records','is_faculty_work')
