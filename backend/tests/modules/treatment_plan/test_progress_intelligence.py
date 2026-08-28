"""Unit coverage for deterministic treatment progress intelligence."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from app.modules.treatment_plan.progress_intelligence import build_progress_intelligence


def _session(status: str, completed_at: datetime | None = None) -> SimpleNamespace:
    return SimpleNamespace(status=status, completed_at=completed_at)


def _item(
    status: str,
    sequence_order: int,
    *,
    sessions: list[SimpleNamespace],
    completed_at: datetime | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        status=status,
        sequence_order=sequence_order,
        sessions=sessions,
        completed_at=completed_at,
    )


def _plan(status: str, items: list[SimpleNamespace]) -> SimpleNamespace:
    return SimpleNamespace(id=uuid4(), status=status, items=items)


def test_progress_counts_actionable_rows_and_preserves_sequence() -> None:
    now = datetime(2026, 8, 26, 10, 0, tzinfo=UTC)
    completed_at = now - timedelta(days=2)
    done = _item(
        "completed",
        2,
        sessions=[_session("completed", completed_at), _session("completed", completed_at)],
        completed_at=completed_at,
    )
    pending_later = _item("pending", 5, sessions=[_session("pending")])
    pending_first = _item("pending", 3, sessions=[_session("cancelled")])

    snapshot = build_progress_intelligence(
        _plan("active", [done, pending_later, pending_first]),
        next_appointment_at=now + timedelta(days=4),
        now=now,
    )

    assert snapshot.items.total == 3
    assert snapshot.items.completed == 1
    assert snapshot.items.pending == 2
    assert snapshot.items.completion_percent == 33.3
    assert snapshot.sessions.total == 4
    assert snapshot.sessions.completed == 2
    assert snapshot.sessions.pending == 1
    assert snapshot.sessions.cancelled == 1
    assert snapshot.sessions.completion_percent == 66.7
    assert snapshot.first_pending_item_id == pending_first.id
    assert snapshot.last_completed_at == completed_at
    assert snapshot.days_since_last_completion == 2
    assert snapshot.operational_state == "in_progress"


def test_active_progress_without_future_appointment_needs_scheduling() -> None:
    now = datetime(2026, 8, 26, 10, 0, tzinfo=UTC)
    done = _item(
        "completed",
        1,
        sessions=[_session("completed", now - timedelta(days=1))],
        completed_at=now - timedelta(days=1),
    )
    pending = _item("pending", 2, sessions=[_session("pending")])

    snapshot = build_progress_intelligence(
        _plan("active", [done, pending]),
        next_appointment_at=None,
        now=now,
    )

    assert snapshot.operational_state == "needs_scheduling"


def test_terminal_and_empty_plans_have_stable_operational_states() -> None:
    now = datetime(2026, 8, 26, 10, 0, tzinfo=UTC)
    closed_item = _item("pending", 1, sessions=[_session("pending")])

    closed = build_progress_intelligence(
        _plan("closed", [closed_item]), next_appointment_at=None, now=now
    )
    empty = build_progress_intelligence(_plan("draft", []), next_appointment_at=None, now=now)

    assert closed.operational_state == "closed"
    assert empty.operational_state == "not_started"
    assert empty.items.completion_percent == 0.0
    assert empty.sessions.completion_percent == 0.0
