"""Enable staff lookup and add library literature codes for existing types."""
from alembic import op
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db import DocumentType
from app.catalog_vocabularies import configure,seed_literature
revision='0013_library_vocabularies'
down_revision='0012_statistics'
branch_labels=None
depends_on=None

def upgrade():
    with Session(bind=op.get_bind()) as s:
        for t in s.scalars(select(DocumentType)):
            t.config=configure(t.config)
            seed_literature(s,t)
        s.flush()

def downgrade():
    raise RuntimeError('Preserve library vocabulary data; use a forward migration.')
