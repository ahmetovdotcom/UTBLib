from alembic import op
import sqlalchemy as sa
revision='0002'
down_revision='0001'
branch_labels=None
depends_on=None
def upgrade():
    op.create_table('vocabulary_entries',sa.Column('id',sa.Integer(),primary_key=True),sa.Column('type_id',sa.Integer(),sa.ForeignKey('document_types.id'),nullable=False),sa.Column('tag',sa.String(3),nullable=False),sa.Column('code',sa.String(1),nullable=False),sa.Column('value',sa.Text(),nullable=False),sa.Column('label',sa.Text(),nullable=False),sa.Column('value_key',sa.String(64),nullable=False),sa.UniqueConstraint('type_id','tag','code','value_key',name='uq_vocabulary_value'))
    op.create_index('ix_vocabulary_entries_type_id','vocabulary_entries',['type_id'])
def downgrade():
    op.drop_table('vocabulary_entries')
