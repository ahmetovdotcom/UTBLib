"""Circulation, reservations, fines and incidents (additive)."""
from alembic import op
revision='0016_circulation'
down_revision='0015_readers_visits'
branch_labels=None
depends_on=None

def upgrade():
    op.execute('\nCREATE TABLE circulation_operations (\n\tkey VARCHAR(150) NOT NULL, \n\tfingerprint VARCHAR(64) NOT NULL, \n\tresult JSON NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (key)\n)\n\n')
    op.execute('\nCREATE TABLE circulation_settings (\n\tid SERIAL NOT NULL, \n\tvalue JSON NOT NULL, \n\tversion INTEGER NOT NULL, \n\tPRIMARY KEY (id)\n)\n\n')
    op.execute('\nCREATE TABLE circulation_audit (\n\tid SERIAL NOT NULL, \n\tentity VARCHAR(30) NOT NULL, \n\tentity_id INTEGER NOT NULL, \n\taction VARCHAR(40) NOT NULL, \n\tactor_id INTEGER, \n\tat TIMESTAMP WITH TIME ZONE NOT NULL, \n\tbefore JSON NOT NULL, \n\tafter JSON NOT NULL, \n\treason TEXT NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(actor_id) REFERENCES users (id) ON DELETE RESTRICT\n)\n\n')
    op.execute('CREATE INDEX ix_circulation_audit_entity_id ON circulation_audit (entity_id)')
    op.execute("\nCREATE TABLE copy_circulation (\n\tcopy_id INTEGER NOT NULL, \n\tbranch_id INTEGER, \n\tcondition VARCHAR(30) DEFAULT 'good' NOT NULL, \n\tdefects TEXT DEFAULT '' NOT NULL, \n\toperation_state VARCHAR(30) DEFAULT 'normal' NOT NULL, \n\taccess VARCHAR(20) DEFAULT 'free' NOT NULL, \n\tissue_count INTEGER DEFAULT '0' NOT NULL, \n\tversion INTEGER DEFAULT '1' NOT NULL, \n\tPRIMARY KEY (copy_id), \n\tCHECK (condition IN ('good','worn','minor','moderate','severe','irreparable','lost')), \n\tCHECK (operation_state IN ('normal','repair','processing','lost','transfer','display','reserve_stock')), \n\tCHECK (access IN ('free','reading_room','limited')), \n\tCHECK (issue_count>=0), \n\tFOREIGN KEY(copy_id) REFERENCES copies (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(branch_id) REFERENCES reader_branches (id) ON DELETE RESTRICT\n)\n\n")
    op.execute('CREATE INDEX ix_copy_circulation_branch_id ON copy_circulation (branch_id)')
    op.execute("\nCREATE TABLE loans (\n\tid SERIAL NOT NULL, \n\treader_id INTEGER NOT NULL, \n\tcopy_id INTEGER NOT NULL, \n\tbranch_id INTEGER, \n\tstatus VARCHAR(20) NOT NULL, \n\tissued_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tdue_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tcalculated_due_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\treturned_at TIMESTAMP WITH TIME ZONE, \n\tlost_at TIMESTAMP WITH TIME ZONE, \n\tclosed_at TIMESTAMP WITH TIME ZONE, \n\trenewal_count INTEGER NOT NULL, \n\tissued_by INTEGER NOT NULL, \n\treturned_to INTEGER, \n\tcondition_on_return VARCHAR(30) NOT NULL, \n\tnotes TEXT NOT NULL, \n\tversion INTEGER NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tCHECK ((status IN ('active','overdue') AND closed_at IS NULL AND returned_at IS NULL AND lost_at IS NULL) OR (status='returned' AND returned_at IS NOT NULL AND closed_at IS NOT NULL AND lost_at IS NULL) OR (status='lost' AND lost_at IS NOT NULL AND closed_at IS NOT NULL AND returned_at IS NULL)), \n\tCHECK (due_at>issued_at), \n\tFOREIGN KEY(reader_id) REFERENCES reader_profiles (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(copy_id) REFERENCES copies (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(branch_id) REFERENCES reader_branches (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(issued_by) REFERENCES users (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(returned_to) REFERENCES users (id) ON DELETE RESTRICT\n)\n\n")
    op.execute('CREATE INDEX ix_loan_copy_status ON loans (copy_id, status)')
    op.execute('CREATE INDEX ix_loan_due ON loans (status, due_at)')
    op.execute('CREATE INDEX ix_loan_reader_status ON loans (reader_id, status)')
    op.execute('CREATE UNIQUE INDEX uq_open_loan_copy ON loans (copy_id) WHERE closed_at IS NULL')
    op.execute("\nCREATE TABLE reservations (\n\tid SERIAL NOT NULL, \n\treader_id INTEGER NOT NULL, \n\trecord_id INTEGER NOT NULL, \n\tassigned_copy_id INTEGER, \n\tpickup_branch_id INTEGER, \n\tstatus VARCHAR(30) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tassigned_at TIMESTAMP WITH TIME ZONE, \n\tready_at TIMESTAMP WITH TIME ZONE, \n\texpires_at TIMESTAMP WITH TIME ZONE, \n\tclosed_at TIMESTAMP WITH TIME ZONE, \n\treason TEXT NOT NULL, \n\tactor_id INTEGER, \n\textensions INTEGER NOT NULL, \n\tversion INTEGER NOT NULL, \n\tPRIMARY KEY (id), \n\tCHECK (status IN ('pending','queued','confirmed','in_transit','ready_for_pickup','fulfilled','cancelled','expired')), \n\tFOREIGN KEY(reader_id) REFERENCES reader_profiles (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(record_id) REFERENCES records (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(assigned_copy_id) REFERENCES copies (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(pickup_branch_id) REFERENCES reader_branches (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(actor_id) REFERENCES users (id) ON DELETE RESTRICT\n)\n\n")
    op.execute('CREATE INDEX ix_reservations_reader_id ON reservations (reader_id)')
    op.execute('CREATE INDEX ix_reservations_record_id ON reservations (record_id)')
    op.execute("CREATE UNIQUE INDEX uq_reservation_copy ON reservations (assigned_copy_id) WHERE status IN ('pending', 'queued', 'confirmed', 'in_transit', 'ready_for_pickup')")
    op.execute("CREATE UNIQUE INDEX uq_reservation_reader_record ON reservations (reader_id, record_id) WHERE status IN ('pending', 'queued', 'confirmed', 'in_transit', 'ready_for_pickup')")
    op.execute("\nCREATE TABLE circulation_incidents (\n\tid SERIAL NOT NULL, \n\treader_id INTEGER NOT NULL, \n\tloan_id INTEGER NOT NULL, \n\tcopy_id INTEGER NOT NULL, \n\tkind VARCHAR(30) NOT NULL, \n\tstatus VARCHAR(20) NOT NULL, \n\tbefore VARCHAR(30) NOT NULL, \n\tafter VARCHAR(30) NOT NULL, \n\tdescription TEXT NOT NULL, \n\taction VARCHAR(30) NOT NULL, \n\tresponsible_id INTEGER, \n\tdecision TEXT NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tresolved_at TIMESTAMP WITH TIME ZONE, \n\tversion INTEGER NOT NULL, \n\tPRIMARY KEY (id), \n\tCHECK (status IN ('open','resolved')), \n\tFOREIGN KEY(reader_id) REFERENCES reader_profiles (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(loan_id) REFERENCES loans (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(copy_id) REFERENCES copies (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(responsible_id) REFERENCES users (id) ON DELETE RESTRICT\n)\n\n")
    op.execute('CREATE INDEX ix_circulation_incidents_loan_id ON circulation_incidents (loan_id)')
    op.execute('CREATE INDEX ix_circulation_incidents_reader_id ON circulation_incidents (reader_id)')
    op.execute('\nCREATE TABLE circulation_notices (\n\tid SERIAL NOT NULL, \n\tkey VARCHAR(200) NOT NULL, \n\treader_id INTEGER NOT NULL, \n\tloan_id INTEGER, \n\tkind VARCHAR(30) NOT NULL, \n\tbody JSON NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tchannel VARCHAR(20) NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (key), \n\tFOREIGN KEY(reader_id) REFERENCES reader_profiles (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(loan_id) REFERENCES loans (id) ON DELETE RESTRICT\n)\n\n')
    op.execute('CREATE INDEX ix_circulation_notices_reader_id ON circulation_notices (reader_id)')
    op.execute('\nCREATE TABLE loan_events (\n\tid SERIAL NOT NULL, \n\tloan_id INTEGER NOT NULL, \n\tkind VARCHAR(30) NOT NULL, \n\tat TIMESTAMP WITH TIME ZONE NOT NULL, \n\tactor_id INTEGER, \n\tprevious_due TIMESTAMP WITH TIME ZONE, \n\tnew_due TIMESTAMP WITH TIME ZONE, \n\tdetails JSON NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(loan_id) REFERENCES loans (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(actor_id) REFERENCES users (id) ON DELETE RESTRICT\n)\n\n')
    op.execute('CREATE INDEX ix_loan_events_loan_id ON loan_events (loan_id)')
    op.execute("\nCREATE TABLE circulation_fines (\n\tid SERIAL NOT NULL, \n\treader_id INTEGER NOT NULL, \n\tloan_id INTEGER NOT NULL, \n\tcopy_id INTEGER NOT NULL, \n\tincident_id INTEGER, \n\tamount NUMERIC(14, 2) NOT NULL, \n\tcurrency VARCHAR(3) NOT NULL, \n\treason VARCHAR(20) NOT NULL, \n\tstatus VARCHAR(20) NOT NULL, \n\tcharged_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tresolved_at TIMESTAMP WITH TIME ZONE, \n\tresolved_by INTEGER, \n\tnotes TEXT NOT NULL, \n\tPRIMARY KEY (id), \n\tCHECK (amount>0), \n\tCHECK (status IN ('pending','paid','waived')), \n\tFOREIGN KEY(reader_id) REFERENCES reader_profiles (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(loan_id) REFERENCES loans (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(copy_id) REFERENCES copies (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(incident_id) REFERENCES circulation_incidents (id) ON DELETE RESTRICT, \n\tFOREIGN KEY(resolved_by) REFERENCES users (id) ON DELETE RESTRICT\n)\n\n")
    op.execute('CREATE INDEX ix_circulation_fines_reader_id ON circulation_fines (reader_id)')
    op.execute('CREATE UNIQUE INDEX uq_loan_fine_reason ON circulation_fines (loan_id, reason)')
    op.execute("ALTER TABLE copies ADD CONSTRAINT ck_copy_barcode_nonempty CHECK (length(btrim(barcode))>0) NOT VALID")
    op.execute("""CREATE FUNCTION circulation_copy_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.status <> 'active' AND (EXISTS(SELECT 1 FROM loans WHERE copy_id=NEW.id AND closed_at IS NULL)
        OR EXISTS(SELECT 1 FROM reservations WHERE assigned_copy_id=NEW.id AND status IN ('pending','queued','confirmed','in_transit','ready_for_pickup')))
      THEN RAISE EXCEPTION 'Copy has an open loan or reservation'; END IF;
      RETURN NEW;
    END $$""")
    op.execute("CREATE TRIGGER circulation_copy_guard BEFORE UPDATE OF status ON copies FOR EACH ROW EXECUTE FUNCTION circulation_copy_guard()")

def downgrade():
    op.execute("DROP TRIGGER circulation_copy_guard ON copies")
    op.execute("DROP FUNCTION circulation_copy_guard()")
    op.drop_constraint("ck_copy_barcode_nonempty","copies",type_="check")
    op.drop_table('circulation_fines')
    op.drop_table('loan_events')
    op.drop_table('circulation_notices')
    op.drop_table('circulation_incidents')
    op.drop_table('reservations')
    op.drop_table('loans')
    op.drop_table('copy_circulation')
    op.drop_table('circulation_audit')
    op.drop_table('circulation_settings')
    op.drop_table('circulation_operations')
