from datetime import UTC, datetime, timedelta

import pytest

from seshat.store.db import Store
from seshat.watcher.sessions import SessionTracker

T0 = datetime(2026, 7, 6, 10, 0, 0, tzinfo=UTC)


def ts(minutes: float) -> str:
    return (T0 + timedelta(minutes=minutes)).isoformat(timespec="seconds")


@pytest.fixture
def store():
    with Store.in_memory() as s:
        yield s


def record(store: Store, tracker: SessionTracker, minutes: float) -> int:
    session_id = tracker.on_event(ts(minutes))
    event_id = store.append_event("script_change", {}, ts=ts(minutes))
    store.assign_events_to_session([event_id], session_id)
    return session_id


def test_events_within_gap_share_a_session(store: Store):
    tracker = SessionTracker(store, idle_gap_minutes=45)
    ids = {record(store, tracker, m) for m in (0, 10, 40, 80)}  # each gap <= 45
    assert len(ids) == 1


def test_gap_closes_old_session_and_backdates_end(store: Store):
    tracker = SessionTracker(store, idle_gap_minutes=45)
    first = record(store, tracker, 0)
    record(store, tracker, 20)
    second = record(store, tracker, 120)  # 100-minute gap
    assert first != second
    closed = store.get_session(first)
    assert closed.status == "closed"
    assert closed.ended_at == ts(20)  # backdated to last event, not to now


def test_flush_if_idle(store: Store):
    tracker = SessionTracker(store, idle_gap_minutes=45)
    session_id = record(store, tracker, 0)
    assert tracker.flush_if_idle(now=ts(30)) is None  # still fresh
    assert tracker.flush_if_idle(now=ts(60)) == session_id
    assert store.get_session(session_id).status == "closed"
    assert tracker.flush_if_idle(now=ts(120)) is None  # nothing open


def test_on_close_callback_fires(store: Store):
    closed = []
    tracker = SessionTracker(store, idle_gap_minutes=45, on_close=closed.append)
    first = record(store, tracker, 0)
    record(store, tracker, 120)
    tracker.flush_if_idle(now=ts(999))
    assert closed[0] == first
    assert len(closed) == 2  # gap-close and idle-flush


def test_tracker_survives_restart(store: Store):
    """State lives in the store, so a new tracker continues the open session."""
    first = record(store, SessionTracker(store, 45), 0)
    resumed = record(store, SessionTracker(store, 45), 10)
    assert resumed == first
