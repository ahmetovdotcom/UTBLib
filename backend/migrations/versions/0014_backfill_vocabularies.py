"""Populate enabled automatic vocabularies from existing catalogue records."""
from alembic import op
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db import DocumentType
from app.vocabulary import backfill_automatic

revision='0014_backfill_vocabularies'
down_revision='0013_library_vocabularies'
branch_labels=None
depends_on=None


def upgrade():
    with Session(bind=op.get_bind()) as s:
        for t in s.scalars(select(DocumentType).order_by(DocumentType.id)):
            backfill_automatic(s,t)
        s.flush()


def downgrade():
    # Imported suggestions may now have descriptions added by staff. Preserve them.
    pass
