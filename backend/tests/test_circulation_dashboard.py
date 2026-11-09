"""Dashboard links must match totals, local dates and history permissions."""
from datetime import date, datetime, timedelta, timezone

import pytest
from app.db import User
from app.circulation_models import Loan
from app.reader_core import local_bounds
from app.security import password_hash
from app import circulation_service as svc
from test_catalog import client
from test_circulation import session, seed, desk_id


def setup_loans(monkeypatch):
    day = date(2026, 11, 9)
    monkeypatch.setattr(svc, 'today', lambda: day)
    monkeypatch.setattr(svc, 'utcnow', lambda: datetime(2026, 11, 9, 7, tzinfo=timezone.utc))
    start, end = local_bounds(day)
    week = local_bounds(day - timedelta(days=6))[0]
    readers, copies, _ = seed(8)
    # Boundary timestamps are UTC, while today and the seven-day window are local.
    cases = [
        ('active', start, end + timedelta(days=5), None),
        ('overdue', week, start - timedelta(seconds=1), None),
        ('returned', start - timedelta(days=30), start - timedelta(days=5), start),
        ('returned', start - timedelta(days=30), start - timedelta(days=5), start - timedelta(microseconds=1)),
        ('returned', start - timedelta(days=30), start - timedelta(days=5), end),
        ('lost', start, end + timedelta(days=5), start + timedelta(hours=1)),
        ('active', end - timedelta(microseconds=1), end + timedelta(days=5), None),
        ('active', end, end + timedelta(days=5), None),
    ]
    with session() as s:
        loans = []
        for copy_id, (status, issued, due, closed) in zip(copies, cases):
            loan = Loan(reader_id=readers[0], copy_id=copy_id, branch_id=desk_id(),
                        issued_by=1, issued_at=issued, due_at=due, calculated_due_at=due,
                        status=status, closed_at=closed,
                        returned_at=closed if status == 'returned' else None,
                        lost_at=closed if status == 'lost' else None)
            s.add(loan); loans.append(loan)
        s.commit()
        return day, [loan.id for loan in loans]


def test_dashboard_drilldowns_match_counts_and_local_day(client, monkeypatch):
    day, loans = setup_loans(monkeypatch)
    dashboard = client.get('/api/circulation/dashboard').json()
    assert dashboard['scope'] == 'all'
    assert dashboard['date'] == str(day)
    assert dashboard['week_from'] == str(day - timedelta(days=6))
    checks = [
        ('open', {'status': 'open'}, [loans[i] for i in [0, 1, 6, 7]]),
        ('overdue', {'status': 'overdue'}, [loans[1]]),
        ('issued_today', {'from_on': str(day), 'to_on': str(day)}, [loans[i] for i in [0, 5, 6]]),
        ('returned_today', {'from_on': str(day), 'to_on': str(day), 'date_field': 'returned'}, [loans[2]]),
        ('issued_week', {'from_on': dashboard['week_from'], 'to_on': str(day)}, [loans[i] for i in [0, 1, 5, 6]]),
    ]
    for key, params, expected in checks:
        response = client.get('/api/circulation/loans', params=params)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result['total'] == dashboard[key] == len(expected)
        assert {row['id'] for row in result['items']} == set(expected)
    # Existing active-only filtering still excludes overdue books.
    active = client.get('/api/circulation/loans?status=active').json()
    assert {row['id'] for row in active['items']} == {loans[i] for i in [0, 6, 7]}


def test_own_history_metrics_do_not_include_another_staff_member(client, monkeypatch):
    day, loans = setup_loans(monkeypatch)
    with session() as s:
        user = User(username='desk-metrics', display_name='Test desk', role='librarian',
                    permissions=['circulation.issue', 'circulation.view_own_history'],
                    password_hash=password_hash('test-secret'))
        s.add(user); s.flush()
        for index in [0, 2]: s.get(Loan, loans[index]).issued_by = user.id
        s.commit()
    assert client.post('/api/auth/login', json={'username': 'desk-metrics', 'password': 'test-secret'}).status_code == 200
    dashboard = client.get('/api/circulation/dashboard').json()
    assert dashboard['scope'] == 'own'
    assert dashboard['open'] == dashboard['returned_today'] == dashboard['issued_today'] == 1
    for params, expected in [({'status': 'open'}, loans[0]),
                             ({'date_field': 'returned', 'from_on': str(day), 'to_on': str(day)}, loans[2])]:
        result = client.get('/api/circulation/loans', params=params).json()
        assert result['total'] == 1
        assert [row['id'] for row in result['items']] == [expected]


@pytest.mark.parametrize('params', [
    {'date_field': 'invalid'},
    {'from_on': '2026-11-10', 'to_on': '2026-11-09'},
])
def test_invalid_history_period_is_rejected(client, params):
    assert client.get('/api/circulation/loans', params=params).status_code == 422
