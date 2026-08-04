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


def build_db_at_version(root: Path, version: int) -> None:
    """A database frozen at an older schema, for testing an upgrade path.

    Pinned to an explicit version rather than sliced off the end of
    MIGRATIONS, so adding a later migration cannot silently change which
    upgrade a test is exercising.
    """
    from seshat.store.schema import MIGRATIONS

    db = root / ".seshat" / "seshat.sqlite3"
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    for n, ddl in enumerate(MIGRATIONS[:version], start=1):
        conn.executescript(ddl)
        conn.execute(
            "INSERT INTO schema_version (version, applied_at) VALUES (?, '2026-01-01')",
            (n,),
        )
    conn.commit()
    conn.close()


def test_migration_backfills_model_intent_on_an_existing_db(tmp_path: Path):
    """The v7 upgrade path: a database created before the column existed."""
    build_db_at_version(tmp_path, 6)  # the schema as it stood before v7
    conn = sqlite3.connect(tmp_path / ".seshat" / "seshat.sqlite3")
    conn.execute("INSERT INTO sessions (started_at, status) VALUES ('2026-01-01', 'processed')")
    conn.execute(
        "INSERT INTO entries (session_id, what_changed, inferred_intent, intent_status,"
        " model_version, prompt_version, created_at)"
        " VALUES (1, 'did a thing', 'a guess', 'inferred', 'm', 'v2', '2026-01-01')"
    )
    conn.commit()
    conn.close()

    with Store.open(tmp_path) as s:
        assert s.schema_version() == SCHEMA_VERSION
        (entry,) = s.entries()
        # The pre-existing guess is adopted as the model's, not left null.
        assert entry.model_intent == "a guess"
        assert s.reset_intent(entry.id) == "a guess"


def test_migration_adds_the_lease_column_to_an_existing_db(tmp_path: Path):
    """The v8 upgrade path: sessions predating the lease are unclaimed."""
    build_db_at_version(tmp_path, 7)
    conn = sqlite3.connect(tmp_path / ".seshat" / "seshat.sqlite3")
    conn.execute("INSERT INTO sessions (started_at, status) VALUES ('2026-01-01', 'closed')")
    conn.commit()
    conn.close()

    with Store.open(tmp_path) as s:
        assert s.schema_version() == SCHEMA_VERSION
        (session,) = s.sessions()
        assert session.claimed_at is None
        assert [x.id for x in s.queued_sessions()] == [session.id]


# -- the journaling lease -----------------------------------------------------


def closed_session(store: Store, started_at: str = "2026-03-01T09:00:00+00:00") -> int:
    sid = store.create_session(started_at=started_at)
    store.close_session(sid, ended_at="2026-03-01T10:00:00+00:00")
    return sid


def test_a_closed_session_starts_out_claimable(store: Store):
    sid = closed_session(store)
    assert [s.id for s in store.queued_sessions()] == [sid]
    assert store.claim_session(sid) is True


def test_only_one_worker_can_hold_a_session(store: Store):
    """The whole point: two workers, one entry."""
    sid = closed_session(store)
    assert store.claim_session(sid) is True
    assert store.claim_session(sid) is False


def test_a_claimed_session_leaves_the_queue(store: Store):
    sid = closed_session(store)
    store.claim_session(sid)
    assert store.queued_sessions() == []


def test_an_open_session_cannot_be_claimed(store: Store):
    sid = store.create_session(started_at="2026-03-01T09:00:00+00:00")
    assert store.claim_session(sid) is False


def test_a_processed_session_cannot_be_claimed(store: Store):
    sid = closed_session(store)
    store.mark_session_processed(sid)
    assert store.claim_session(sid) is False


def test_releasing_puts_a_session_straight_back_in_the_queue(store: Store):
    # A failed run must retry now, not once the lease lapses.
    sid = closed_session(store)
    store.claim_session(sid)
    store.release_session(sid)
    assert [s.id for s in store.queued_sessions()] == [sid]
    assert store.claim_session(sid) is True


def test_a_stale_claim_is_reclaimed(store: Store):
    """A worker that died holding a lease must not strand its session."""
    sid = closed_session(store)
    assert store.claim_session(sid, now="2026-03-01T10:00:00+00:00") is True
    # An hour later, with a 30-minute lease, the claim has lapsed.
    later = "2026-03-01T11:00:00+00:00"
    assert [s.id for s in store.queued_sessions(now=later)] == [sid]
    assert store.claim_session(sid, now=later) is True


def test_a_live_claim_is_not_stolen_mid_generation(store: Store):
    # Generation is slow; a lease that lapses under it causes the exact
    # double-write the lease exists to prevent.
    sid = closed_session(store)
    store.claim_session(sid, now="2026-03-01T10:00:00+00:00")
    during = "2026-03-01T10:29:00+00:00"  # inside the 30-minute window
    assert store.queued_sessions(now=during) == []
    assert store.claim_session(sid, now=during) is False


def test_finishing_a_session_clears_its_claim(store: Store):
    sid = closed_session(store)
    store.claim_session(sid)
    store.mark_session_processed(sid)
    session = store.get_session(sid)
    assert session.status == "processed"
    assert session.claimed_at is None


def test_claiming_one_session_leaves_the_others_alone(store: Store):
    first = closed_session(store, "2026-03-01T09:00:00+00:00")
    second = closed_session(store, "2026-03-01T11:00:00+00:00")
    store.claim_session(first)
    assert [s.id for s in store.queued_sessions()] == [second]


def test_two_stores_on_one_database_cannot_both_claim(tmp_path: Path):
    """The real shape of the race: separate processes, separate connections."""
    with Store.open(tmp_path) as watcher, Store.open(tmp_path) as cli:
        sid = closed_session(watcher)
        results = [watcher.claim_session(sid), cli.claim_session(sid)]
        assert sorted(results) == [False, True]


def make_entry(store: Store, intent: str = "a guess") -> int:
    sid = store.create_session(started_at="2026-03-01T09:00:00+00:00")
    return store.add_entry(JournalEntry(
        session_id=sid, what_changed="did a thing", inferred_intent=intent,
        model_version="m", prompt_version="v2",
    ))


def test_new_entry_records_the_model_guess(store: Store):
    eid = make_entry(store)
    assert store.get_entry(eid).model_intent == "a guess"


def test_correcting_an_intent_preserves_the_model_guess(store: Store):
    eid = make_entry(store)
    store.set_intent(eid, "what actually happened", status="corrected")
    entry = store.get_entry(eid)
    assert entry.inferred_intent == "what actually happened"
    assert entry.intent_status == "corrected"
    assert entry.model_intent == "a guess"  # not clobbered


def test_reset_intent_restores_the_guess_and_the_unreviewed_status(store: Store):
    eid = make_entry(store)
    store.set_intent(eid, "wrong edit", status="corrected")
    assert store.reset_intent(eid) == "a guess"
    entry = store.get_entry(eid)
    assert entry.inferred_intent == "a guess"
    assert entry.intent_status == "inferred"


def test_reset_intent_undoes_a_confirmation(store: Store):
    eid = make_entry(store)
    store.set_intent(eid, "a guess", status="confirmed")
    store.reset_intent(eid)
    assert store.get_entry(eid).intent_status == "inferred"


def test_reset_intent_without_a_recorded_guess_is_refused(store: Store):
    eid = make_entry(store, intent=None)  # type: ignore[arg-type]
    with pytest.raises(StoreError, match="no recorded model guess"):
        store.reset_intent(eid)


def test_reset_intent_unknown_entry(store: Store):
    with pytest.raises(StoreError, match="No entry with id"):
        store.reset_intent(9999)


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


def test_chat_history_roundtrip(store: Store):
    store.add_chat_message("user", "have I tried SMOTE?")
    store.add_chat_message("assistant", "Yes, twice [session 3].", session_ids=[3, 7])
    history = store.chat_history()
    assert [m.role for m in history] == ["user", "assistant"]
    assert history[1].session_ids == [3, 7]
    assert history[0].ts is not None


def test_clear_chat_hides_but_keeps_messages(store: Store):
    store.add_chat_message("user", "old question")
    assert store.clear_chat() == 1
    assert store.chat_history() == []
    store.add_chat_message("user", "new conversation")
    assert [m.text for m in store.chat_history()] == ["new conversation"]
    # The record itself is preserved, only hidden.
    total = store._conn.execute("SELECT COUNT(*) AS n FROM chat_messages").fetchone()["n"]
    assert total == 2


def test_chat_rejects_bad_role(store: Store):
    with pytest.raises(StoreError, match="role"):
        store.add_chat_message("system", "nope")


def test_events_filter_by_kind(store: Store):
    store.append_event("notebook_diff", {})
    store.append_event("git_commit", {})
    store.append_event("git_commit", {})
    assert len(store.events(kind="git_commit")) == 2
    assert len(store.events(kind="notebook_diff")) == 1
