import sqlite3
from pathlib import Path

import pytest

from seshat.store.db import Store, StoreError
from seshat.store.schema import SCHEMA_VERSION, JournalEntry


@pytest.fixture
def store():
    with Store.in_memory() as s:
        yield s


def test_migrations_apply_and_are_idempotent(tmp_path: Path):
    with Store.open(tmp_path) as store:
        assert store.schema_version() == SCHEMA_VERSION
    # Reopening must not re-apply or fail.
    with Store.open(tmp_path) as store:
        assert store.schema_version() == SCHEMA_VERSION
    assert (tmp_path / ".seshat" / "seshat.sqlite3").exists()


def test_raw_event_roundtrip(store: Store):
    event_id = store.append_event(
        "notebook_diff",
        {"cells_changed": 2, "summary": "added SMOTE oversampling"},
        path="train.ipynb",
    )
    events = store.events()
    assert len(events) == 1
    assert events[0].id == event_id
    assert events[0].kind == "notebook_diff"
    assert events[0].path == "train.ipynb"
    assert events[0].payload["summary"] == "added SMOTE oversampling"
    assert events[0].session_id is None


def test_raw_events_are_immutable(store: Store):
    store.append_event("script_change", {"diff": "original"}, path="train.py")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        store._conn.execute("UPDATE raw_events SET payload = '{}' WHERE id = 1")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        store._conn.execute("DELETE FROM raw_events")


def test_session_assignment_is_the_allowed_mutation(store: Store):
    event_id = store.append_event("script_change", {"diff": "x"})
    session_id = store.create_session()
    store.assign_events_to_session([event_id], session_id)
    assert store.events(session_id=session_id)[0].id == event_id
    assert store.events(ungrouped=True) == []


def test_session_lifecycle(store: Store):
    session_id = store.create_session()
    assert store.get_session(session_id).status == "open"
    store.close_session(session_id)
    assert store.get_session(session_id).status == "closed"
    store.mark_session_processed(session_id)
    assert store.get_session(session_id).status == "processed"
    # Transitions cannot repeat or skip.
    with pytest.raises(StoreError):
        store.close_session(session_id)
    with pytest.raises(StoreError):
        store.mark_session_processed(session_id)


def test_entry_roundtrip_with_json_fields(store: Store):
    session_id = store.create_session()
    entry_id = store.add_entry(
        JournalEntry(
            session_id=session_id,
            what_changed="added SMOTE oversampling before the classifier",
            observable_outcome="minority-class F1 0.61 -> 0.68",
            inferred_intent="addressing class imbalance",
            intent_confidence=0.8,
            files_touched=["train.ipynb", "preprocess.py"],
            raw_event_ids=[1, 2, 3],
            model_version="qwen3-8b-q4",
            prompt_version="v1",
        )
    )
    entry = store.get_entry(entry_id)
    assert entry.files_touched == ["train.ipynb", "preprocess.py"]
    assert entry.raw_event_ids == [1, 2, 3]
    assert entry.intent_status == "inferred"
    assert entry.model_version == "qwen3-8b-q4"
    assert entry.created_at is not None


def test_intent_correction(store: Store):
    session_id = store.create_session()
    entry_id = store.add_entry(
        JournalEntry(session_id=session_id, what_changed="dropped region_code column")
    )
    store.set_intent(entry_id, "column leaked target information", status="corrected")
    entry = store.get_entry(entry_id)
    assert entry.inferred_intent == "column leaked target information"
    assert entry.intent_status == "corrected"
    with pytest.raises(StoreError, match="confirmed"):
        store.set_intent(entry_id, "nope", status="inferred")


def test_edges_between_node_types(store: Store):
    session_id = store.create_session()
    paper_id = store.add_paper("papers/smote.pdf", title="SMOTE")
    artifact_id = store.add_artifact("results/model_v2.json", kind="result")

    store.add_edge("session", session_id, "paper", paper_id, "cites-idea-from", 0.9)
    store.add_edge("session", session_id, "artifact", artifact_id, "produced")

    from_session = store.edges(src=("session", session_id))
    assert {e.kind for e in from_session} == {"cites-idea-from", "produced"}
    to_paper = store.edges(dst=("paper", paper_id), kind="cites-idea-from")
    assert len(to_paper) == 1
    assert to_paper[0].confidence == 0.9
    with pytest.raises(sqlite3.IntegrityError):
        store.add_edge("session", session_id, "banana", 1, "produced")


def test_events_filter_by_kind(store: Store):
    store.append_event("notebook_diff", {})
    store.append_event("git_commit", {})
    store.append_event("git_commit", {})
    assert len(store.events(kind="git_commit")) == 2
    assert len(store.events(kind="notebook_diff")) == 1
