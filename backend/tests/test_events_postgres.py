"""Use a disposable PostgreSQL schema to test concurrent event check-ins."""
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from uuid import uuid4
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from app.db import Base, User
from app.event_models import LibraryEvent, EventAttendance
from app.events import record_attendance
from app.reader_core import TZ
from app.reader_models import Branch, Reader, LibraryVisit
from app.visit_checkin import CheckIn

pytestmark = pytest.mark.skipif(not os.getenv('TEST_READERS_DATABASE_URL'), reason='Disposable PostgreSQL not configured')


def test_concurrent_scans_and_report_sql():
    from app.attendance import Filters, report, journal_report
    engine = create_engine(os.environ['TEST_READERS_DATABASE_URL'])
    schema = 'event_test_' + uuid4().hex
    with engine.begin() as c: c.exec_driver_sql('CREATE SCHEMA ' + schema)
    scoped = engine.execution_options(schema_translate_map={None: schema})
    Base.metadata.create_all(scoped); factory = sessionmaker(scoped)
    try:
        today = datetime.now(TZ).date()
        with factory() as s:
            s.add(User(id=1, username='test', display_name='Test', password_hash='unused', role='admin', permissions=[]))
            s.add(Branch(id=1, code='TEST', name='Test'))
            s.add(Reader(id=1, full_name='Test', category='bachelor', ticket_number='TEST', barcode='TEST', course=2))
            s.flush()
            s.add(LibraryEvent(id=1, title='Test', date_from=today, date_to=today, branch_id=1)); s.commit()
        def account(i):
            with factory() as s:
                row, duplicate = record_attendance(s, 1, reader=s.get(Reader, 1), actor=1 if i%2 else None, source='desk' if i%2 else 'qr_account')
                result = row.id, duplicate; s.commit(); return result
        def guest(i):
            with factory() as s:
                row, duplicate = record_attendance(s, 1, guest=CheckIn(token='A'*43, full_name='Test Guest', study_group='TEST', course=2), guest_key='test', source='qr_guest')
                result = row.id, duplicate; s.commit(); return result
        for scan in (account, guest):
            with ThreadPoolExecutor(8) as pool: results = list(pool.map(scan, range(8)))
            assert len({r[0] for r in results}) == 1
            assert sum(not r[1] for r in results) == 1
        with factory() as s:
            assert s.scalar(select(func.count(EventAttendance.id))) == 2
            f = Filters(date_from=today, date_to=today, course=['2'])
            data = report(s, f, EventAttendance, (EventAttendance.event_id == 1,))
            assert data['totals']['visits'] == 2 and data['totals']['unique'] == 1
            assert sum(row['visits'] for row in data['hours']) == 2
            assert journal_report(s, f, visit_model=EventAttendance, scope=(EventAttendance.event_id == 1,))['total'] == 2
            assert s.scalar(select(func.count(LibraryVisit.id))) == 0
    finally:
        with engine.begin() as c: c.exec_driver_sql('DROP SCHEMA ' + schema + ' CASCADE')
        engine.dispose()
