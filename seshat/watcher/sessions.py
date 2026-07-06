"""Idle-gap session grouping.

Events arriving within `idle_gap_minutes` of the previous one belong to the
same session; a longer gap closes the session (backdated to its last event)
and starts a new one. The tracker is stateless between runs — the open
session and its last-event timestamp live in the store — so restarting
`seshat watch` never loses or duplicates a session.

Session-boundary misfires (two unrelated bursts merged, one burst split) are
an accepted imperfection per Seshat.md §6.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from seshat.store.db import Store, utcnow


class SessionTracker:
    def __init__(
        self,
        store: Store,
        idle_gap_minutes: int,
        on_close: Callable[[int], None] | None = None,
    ) -> None:
        self._store = store
        self._gap = timedelta(minutes=idle_gap_minutes)
        self._on_close = on_close

    def _open_session(self):
        sessions = self._store.sessions(status="open")
        return sessions[-1] if sessions else None

    def _last_activity(self, session_id: int, started_at: str) -> datetime:
        events = self._store.events(session_id=session_id)
        last = events[-1].ts if events else started_at
        return datetime.fromisoformat(last)

    def on_event(self, ts: str | None = None) -> int:
        """Return the session id the event at *ts* belongs to."""
        now = datetime.fromisoformat(ts) if ts else datetime.now(UTC)
        current = self._open_session()
        if current is not None:
            last = self._last_activity(current.id, current.started_at)
            if now - last <= self._gap:
                return current.id
            self._close(current.id, ended_at=last.isoformat(timespec="seconds"))
        return self._store.create_session(started_at=now.isoformat(timespec="seconds"))

    def flush_if_idle(self, now: str | None = None) -> int | None:
        """Close the open session if it has gone idle; return its id if closed."""
        current = self._open_session()
        if current is None:
            return None
        now_dt = datetime.fromisoformat(now) if now else datetime.now(UTC)
        last = self._last_activity(current.id, current.started_at)
        if now_dt - last <= self._gap:
            return None
        self._close(current.id, ended_at=last.isoformat(timespec="seconds"))
        return current.id

    def _close(self, session_id: int, ended_at: str) -> None:
        self._store.close_session(session_id, ended_at=ended_at)
        if self._on_close is not None:
            self._on_close(session_id)


def parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


__all__ = ["SessionTracker", "parse_ts", "utcnow"]
