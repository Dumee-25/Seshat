from datetime import UTC, datetime, timedelta

import pytest

from seshat.query.timeline import build_timeline
from seshat.store.db import Store
from seshat.store.schema import JournalEntry

T0 = datetime(2026, 3, 1, 9, 0, 0, tzinfo=UTC)


def ts(hours: float) -> str:
    return (T0 + timedelta(hours=hours)).isoformat(timespec="seconds")


@pytest.fixture
def store():
    with Store.in_memory() as s:
        yield s


def journaled_session(store: Store, hour: float, what: str) -> int:
    sid = store.create_session(started_at=ts(hour))
    store.close_session(sid, ended_at=ts(hour + 1))
    store.mark_session_processed(sid)
    store.add_entry(JournalEntry(
        session_id=sid, what_changed=what, inferred_intent="a guess",
        intent_confidence=0.7, files_touched=["train.py"],
        model_version="m", prompt_version="v2",
    ))
    return sid


def test_timeline_merges_and_orders_newest_first(store: Store):
    journaled_session(store, 0, "Added SMOTE oversampling.")
    store.add_paper("papers/smote.pdf", title="SMOTE paper", added_at=ts(2))
    store.add_artifact("results/metrics.csv", kind="result")  # created_at = now (latest)

    items = build_timeline(store)
    kinds = [i.kind for i in items]
    assert set(kinds) == {"session", "paper", "artifact"}
    # Sorted by ts desc: artifact (now) > paper (h2) > session (h0).
    assert [i.ts for i in items] == sorted((i.ts for i in items), reverse=True)


def test_session_item_uses_journal_summary(store: Store):
    sid = journaled_session(store, 0, "Added SMOTE oversampling.")
    (item,) = [i for i in build_timeline(store) if i.kind == "session"]
    assert item.id == sid
    assert item.title == "Added SMOTE oversampling."
    assert item.meta["intent_status"] == "inferred"
    assert item.meta["files"] == ["train.py"]


def test_unjournaled_session_shows_pending_label(store: Store):
    sid = store.create_session(started_at=ts(0))
    store.close_session(sid)
    (item,) = [i for i in build_timeline(store) if i.kind == "session"]
    assert "queued for journaling" in item.title
    assert item.meta["status"] == "closed"


def test_kinds_filter(store: Store):
    journaled_session(store, 0, "x")
    store.add_paper("papers/p.pdf", title="P", added_at=ts(1))
    items = build_timeline(store, kinds={"paper"})
    assert {i.kind for i in items} == {"paper"}


def test_since_filter(store: Store):
    journaled_session(store, 0, "old")
    store.add_paper("papers/recent.pdf", title="recent", added_at=ts(10))
    items = build_timeline(store, since=ts(5))
    assert [i.kind for i in items] == ["paper"]


def test_limit(store: Store):
    for h in range(5):
        store.add_paper(f"papers/p{h}.pdf", title=f"p{h}", added_at=ts(h))
    assert len(build_timeline(store, limit=3)) == 3


def test_paper_falls_back_to_filename(store: Store):
    store.add_paper("papers/untitled.pdf", title=None, added_at=ts(0))
    (item,) = [i for i in build_timeline(store) if i.kind == "paper"]
    assert item.title == "untitled.pdf"


def test_empty_timeline(store: Store):
    assert build_timeline(store) == []
