from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision='0001'
down_revision=None
branch_labels=None
depends_on=None
def upgrade():
    op.create_table('document_types',sa.Column('id',sa.Integer(),primary_key=True),sa.Column('name',sa.String(120),nullable=False,unique=True),sa.Column('config',postgresql.JSONB(),nullable=False))
    op.create_table('records',sa.Column('id',sa.Integer(),primary_key=True),sa.Column('type_id',sa.Integer(),sa.ForeignKey('document_types.id'),nullable=False),sa.Column('version',sa.Integer(),nullable=False),sa.Column('marc',postgresql.JSONB(),nullable=False),sa.Column('search_text',sa.Text(),nullable=False))
    op.create_index('ix_records_type_id','records',['type_id'])
def downgrade():
    op.drop_table('records'); op.drop_table('document_types')
