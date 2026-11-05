"""Concurrent account/staff and guest scans, in an isolated PostgreSQL schema."""
import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from app.db import Base, User
from app.reader_models import Branch, Reader, LibraryVisit
from app.visit_checkin import CheckIn, record_visit

pytestmark = pytest.mark.skipif(not os.getenv('TEST_READERS_DATABASE_URL'), reason='Disposable PostgreSQL not configured')


def test_concurrent_account_staff_and_guest_checkins():
    engine = create_engine(os.environ['TEST_READERS_DATABASE_URL'])
    schema = 'visit_qr_test_' + uuid4().hex
    with engine.begin() as c:
        c.exec_driver_sql('CREATE SCHEMA ' + schema)
    scoped = engine.execution_options(schema_translate_map={None: schema})
    Base.metadata.create_all(scoped)
    factory = sessionmaker(scoped)
    try:
        with factory() as s:
            s.add(User(id=1, username='test', display_name='Test', password_hash='unused', role='admin', permissions=[]))
            s.add(Branch(id=1, code='TEST', name='Test'))
            s.add(Reader(id=1, full_name='Test', category='student', ticket_number='TEST', barcode='TEST'))
            s.commit()

        def account(i):
            with factory() as s:
                visit, duplicate = record_visit(s, 1, reader=s.get(Reader, 1), actor=1 if i % 2 else None,
                    source='desk' if i % 2 else 'qr_account')
                result = visit.id, duplicate
                s.commit()
                return result

        def guest(_):
            with factory() as s:
                body = CheckIn(token='A' * 43, full_name='Test Guest', study_group='TEST', course=1)
                visit, duplicate = record_visit(s, 1, guest=body, guest_key='test-key', source='qr_guest')
                result = visit.id, duplicate
                s.commit()
                return result

        for scan in (account, guest):
            with ThreadPoolExecutor(8) as pool:
                results = list(pool.map(scan, range(8)))
            assert len({r[0] for r in results}) == 1
            assert sum(not r[1] for r in results) == 1
        with factory() as s:
            assert s.scalar(select(func.count()).select_from(LibraryVisit)) == 2
    finally:
        with engine.begin() as c:
            c.exec_driver_sql('DROP SCHEMA ' + schema + ' CASCADE')
        engine.dispose()
