"""Primary catalogue specialty and frozen KSU allocations."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision='0022_primary_specialty'
down_revision='0021_copy_deletions'
branch_labels=None
depends_on=None


def upgrade():
    op.add_column('records',sa.Column('primary_specialty',sa.Text(),nullable=True))
    allocations=op.create_table('ksu_specialty_allocations',
        sa.Column('entry_id',sa.Integer(),sa.ForeignKey('ksu_entries.id',ondelete='RESTRICT'),primary_key=True),
        sa.Column('record_id',sa.Integer(),sa.ForeignKey('records.id',ondelete='CASCADE'),primary_key=True),
        sa.Column('primary_specialty',sa.Text(),nullable=True),
        sa.Column('specialties',sa.JSON().with_variant(JSONB,'postgresql'),nullable=False),
        sa.Column('version',sa.Integer(),nullable=False))
    conn=op.get_bind()
    records={}
    for row in conn.execute(sa.text('SELECT id, marc FROM records')).mappings():
        values=sorted({sf.get('value','').strip() for f in row['marc'].get('fields',[]) if f.get('tag')=='952'
            for sf in (f.get('subfields') or []) if sf.get('code')=='j' and sf.get('value','').strip()})
        selected=values[0] if len(values)==1 else None
        records[row['id']]=(values,selected)
    updates=[{'rid':rid,'specialty':selected} for rid,(_,selected) in records.items() if selected]
    if updates:conn.execute(sa.text('UPDATE records SET primary_specialty=:specialty WHERE id=:rid'),updates)
    pairs=conn.execute(sa.text('''SELECT DISTINCT c.ksu_entry_id, COALESCE(c.record_id,l.record_id) AS record_id
        FROM copies c LEFT JOIN acquisition_lines l ON l.id=c.line_id WHERE c.ksu_entry_id IS NOT NULL''')).mappings()
    rows=[{'entry_id':p['ksu_entry_id'],'record_id':p['record_id'],'specialties':records[p['record_id']][0],
           'primary_specialty':records[p['record_id']][1],'version':1} for p in pairs]
    if rows:conn.execute(allocations.insert(),rows)


def downgrade():
    op.drop_table('ksu_specialty_allocations')
    op.drop_column('records','primary_specialty')
