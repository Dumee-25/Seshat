"""The unified activity timeline — the spine of the cockpit.

Every recorded thing is a timestamped event, so the timeline merges sessions
(with their journal summary), papers/links, and produced artifacts into one
feed ordered newest-first. Each item carries enough to render a row and to
drill down (its kind and id). Pure store reads, so it is fully testable.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import PurePosixPath

from seshat.store.db import Store

KINDS = ("session", "paper", "artifact")


@dataclass
class TimelineItem:
    ts: str  # ISO 8601, UTC — the sort key
    kind: str  # "session" | "paper" | "artifact"
    id: int
    title: str
    subtitle: str | None = None
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def _session_item(store: Store, session) -> TimelineItem:
    entries = store.entries(session_id=session.id)
    entry = entries[0] if entries else None
    if entry:
        title = entry.what_changed
        subtitle = entry.observable_outcome
        meta = {
            "status": session.status,
            "entry_id": entry.id,
            "intent": entry.inferred_intent,
            "intent_status": entry.intent_status,
            "intent_confidence": entry.intent_confidence,
            "files": entry.files_touched,
            "ended_at": session.ended_at,
        }
    else:
        # Captured but not yet journaled.
        pending = {"open": "in progress", "closed": "queued for journaling"}
        title = f"Work session ({pending.get(session.status, session.status)})"
        subtitle = None
        meta = {"status": session.status, "ended_at": session.ended_at}
    return TimelineItem(
        ts=session.started_at, kind="session", id=session.id,
        title=title, subtitle=subtitle, meta=meta,
    )


def _haystack(item: TimelineItem) -> str:
    """The text a search matches against: what the row shows, plus the intent.

    Searching the intent matters more than it looks — "why did I drop
    region_code" is usually recorded as an inference, not in the summary line.
    """
    intent = item.meta.get("intent")
    parts = [item.title, item.subtitle or "", intent if isinstance(intent, str) else ""]
    return "\n".join(parts).casefold()


def timeline_page(
    store: Store,
    limit: int = 100,
    offset: int = 0,
    kinds: set[str] | None = None,
    since: str | None = None,
    query: str | None = None,
) -> tuple[list[TimelineItem], int]:
    """One page of the timeline, plus how many items match in total.

    The total is what lets the cockpit say "there is more" — without it a
    short page is indistinguishable from the end of history, which is how the
    feed silently truncated at its default limit before.
    """
    items = _collect(store, kinds=kinds, since=since, query=query)
    start = max(offset, 0)
    return items[start : start + limit], len(items)


def _collect(
    store: Store,
    kinds: set[str] | None = None,
    since: str | None = None,
    query: str | None = None,
) -> list[TimelineItem]:
    kinds = kinds or set(KINDS)
    items: list[TimelineItem] = []

    if "session" in kinds:
        items.extend(_session_item(store, s) for s in store.sessions())
    if "paper" in kinds:
        for paper in store.papers():
            items.append(
                TimelineItem(
                    ts=paper.added_at or "", kind="paper", id=paper.id,
                    title=paper.title or PurePosixPath(paper.path).name,
                    subtitle=paper.path,
                    meta={"path": paper.path},
                )
            )
    if "artifact" in kinds:
        for artifact in store.artifacts():
            items.append(
                TimelineItem(
                    ts=artifact.created_at or "", kind="artifact", id=artifact.id,
                    title=PurePosixPath(artifact.path).name,
                    subtitle=artifact.kind,
                    meta={"path": artifact.path, "artifact_kind": artifact.kind},
                )
            )

    if since:
        items = [item for item in items if item.ts >= since]
    if query and query.strip():
        needle = query.strip().casefold()
        items = [item for item in items if needle in _haystack(item)]
    items.sort(key=lambda item: item.ts, reverse=True)
    return items
