from datetime import UTC, datetime, timedelta

import pytest

from seshat.query.timeline import timeline_page
from seshat.store.db import Store
from seshat.store.schema import JournalEntry

T0 = datetime(2026, 3, 1, 9, 0, 0, tzinfo=UTC)


def ts(hours: float) -> str:
    return (T0 + timedelta(hours=hours)).isoformat(timespec="seconds")


@pytest.fixture
def store():
    with Store.in_memory() as s:
        yield s


def page(store: Store, **kwargs):
    """Just the items — most tests here don't care about the total."""
    return timeline_page(store, **kwargs)[0]


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

    items = page(store)
    kinds = [i.kind for i in items]
    assert set(kinds) == {"session", "paper", "artifact"}
    # Sorted by ts desc: artifact (now) > paper (h2) > session (h0).
    assert [i.ts for i in items] == sorted((i.ts for i in items), reverse=True)


def test_session_item_uses_journal_summary(store: Store):
    sid = journaled_session(store, 0, "Added SMOTE oversampling.")
    (item,) = [i for i in page(store) if i.kind == "session"]
    assert item.id == sid
    assert item.title == "Added SMOTE oversampling."
    assert item.meta["intent_status"] == "inferred"
    assert item.meta["files"] == ["train.py"]


def test_unjournaled_session_shows_pending_label(store: Store):
    sid = store.create_session(started_at=ts(0))
    store.close_session(sid)
    (item,) = [i for i in page(store) if i.kind == "session"]
    assert "queued for journaling" in item.title
    assert item.meta["status"] == "closed"


def test_kinds_filter(store: Store):
    journaled_session(store, 0, "x")
    store.add_paper("papers/p.pdf", title="P", added_at=ts(1))
    items = page(store, kinds={"paper"})
    assert {i.kind for i in items} == {"paper"}


def test_since_filter(store: Store):
    journaled_session(store, 0, "old")
    store.add_paper("papers/recent.pdf", title="recent", added_at=ts(10))
    items = page(store, since=ts(5))
    assert [i.kind for i in items] == ["paper"]


def test_limit(store: Store):
    for h in range(5):
        store.add_paper(f"papers/p{h}.pdf", title=f"p{h}", added_at=ts(h))
    assert len(page(store, limit=3)) == 3


def test_paper_falls_back_to_filename(store: Store):
    store.add_paper("papers/untitled.pdf", title=None, added_at=ts(0))
    (item,) = [i for i in page(store) if i.kind == "paper"]
    assert item.title == "untitled.pdf"


def test_empty_timeline(store: Store):
    assert page(store) == []


# -- search -------------------------------------------------------------------


def test_query_matches_title_case_insensitively(store: Store):
    journaled_session(store, 0, "Added SMOTE oversampling.")
    journaled_session(store, 2, "Swapped the learning rate schedule.")
    items = page(store, query="smote")
    assert [i.title for i in items] == ["Added SMOTE oversampling."]


def test_query_matches_inferred_intent(store: Store):
    """The 'why' is usually only in the intent, not the summary line."""
    sid = store.create_session(started_at=ts(0))
    store.close_session(sid, ended_at=ts(1))
    store.mark_session_processed(sid)
    store.add_entry(JournalEntry(
        session_id=sid, what_changed="Edited train.py.",
        inferred_intent="recall was capped by class imbalance",
        model_version="m", prompt_version="v2",
    ))
    assert len(page(store, query="class imbalance")) == 1
    assert page(store, query="nothing here") == []


def test_query_matches_subtitle(store: Store):
    store.add_paper("papers/smote.pdf", title="Untitled", added_at=ts(0))
    assert len(page(store, query="papers/smote")) == 1


def test_query_combines_with_kinds_filter(store: Store):
    journaled_session(store, 0, "SMOTE in the training script")
    store.add_paper("papers/smote.pdf", title="SMOTE paper", added_at=ts(1))
    items = page(store, query="smote", kinds={"paper"})
    assert [i.kind for i in items] == ["paper"]


def test_blank_query_is_not_a_filter(store: Store):
    journaled_session(store, 0, "x")
    assert len(page(store, query="   ")) == 1


# -- paging -------------------------------------------------------------------


def test_total_counts_all_matches_not_just_the_page(store: Store):
    for h in range(5):
        store.add_paper(f"papers/p{h}.pdf", title=f"p{h}", added_at=ts(h))
    items, total = timeline_page(store, limit=2)
    assert len(items) == 2
    assert total == 5


def test_total_respects_the_filters(store: Store):
    journaled_session(store, 0, "only match")
    for h in range(3):
        store.add_paper(f"papers/p{h}.pdf", title=f"p{h}", added_at=ts(h + 1))
    _, total = timeline_page(store, query="only match")
    assert total == 1


def test_offset_walks_the_feed_without_gaps_or_repeats(store: Store):
    for h in range(5):
        store.add_paper(f"papers/p{h}.pdf", title=f"p{h}", added_at=ts(h))
    everything = [i.title for i in page(store)]
    walked = []
    for offset in (0, 2, 4):
        walked += [i.title for i in page(store, limit=2, offset=offset)]
    assert walked == everything


def test_offset_past_the_end_is_empty_not_an_error(store: Store):
    store.add_paper("papers/p.pdf", title="p", added_at=ts(0))
    items, total = timeline_page(store, offset=50)
    assert items == []
    assert total == 1
