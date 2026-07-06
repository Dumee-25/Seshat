"""Regression tests for the post-MVP bug hunt. Each test pins one fix."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from conftest import FakeProvider, fake_embedder

from seshat.config import load_config, write_default_config
from seshat.inference.queue import InferenceWorker
from seshat.papers.linking import papers_near_session
from seshat.query.engine import QueryEngine
from seshat.store.db import Store
from seshat.store.schema import JournalEntry
from seshat.store.vectors import VectorStore, VectorStoreError
from seshat.watcher.daemon import WatchService

T0 = datetime(2026, 3, 1, 9, 0, 0, tzinfo=UTC)


def ts(days: float) -> str:
    return (T0 + timedelta(days=days)).isoformat(timespec="seconds")


def test_worker_survives_missing_embeddings(tmp_path: Path):
    """Bug 1: a VectorStoreError (embeddings extra not installed) crashed the
    watch loop. It must keep the session queued instead."""

    class BrokenVectors:
        def query(self, *a, **k):
            raise VectorStoreError("sentence-transformers is not installed")

        def add(self, *a, **k):
            raise VectorStoreError("sentence-transformers is not installed")

        def delete(self, *a, **k):
            raise VectorStoreError("sentence-transformers is not installed")

    with Store.open(tmp_path) as store:
        sid = store.create_session(started_at=ts(0))
        eid = store.append_event("script_change", {"diff": "+x"}, ts=ts(0))
        store.assign_events_to_session([eid], sid)
        store.close_session(sid)

        worker = InferenceWorker(
            store, BrokenVectors(), FakeProvider(), busy_check=lambda: False
        )
        assert worker.run_pending() == 0  # no crash
        assert store.get_session(sid).status == "closed"  # still queued


def test_watch_loop_survives_processing_errors(tmp_path: Path):
    """Bug 2: an unexpected exception in process_file or the background task
    must not kill the run loop."""
    import threading
    import time

    write_default_config(tmp_path)
    with Store.open(tmp_path) as store:
        boom_count = {"n": 0}

        def boom():
            boom_count["n"] += 1
            raise RuntimeError("background boom")

        service = WatchService(
            tmp_path, load_config(tmp_path), store, background_task=boom
        )
        # Force an immediate idle-check tick by shrinking the interval.
        import seshat.watcher.daemon as daemon_mod

        original = daemon_mod.IDLE_CHECK_SECONDS
        daemon_mod.IDLE_CHECK_SECONDS = 0.1
        try:
            thread = threading.Thread(target=service.run, daemon=True)
            thread.start()
            deadline = time.monotonic() + 10
            while boom_count["n"] < 2 and time.monotonic() < deadline:
                time.sleep(0.1)
            assert thread.is_alive()  # loop survived the first boom
            assert boom_count["n"] >= 2  # and kept ticking after it
        finally:
            daemon_mod.IDLE_CHECK_SECONDS = original
            service.stop()
            thread.join(timeout=10)


def test_until_filter_includes_its_own_day(tmp_path: Path):
    """Bug 4: until=YYYY-MM-DD excluded sessions from that same day."""
    store = Store.open(tmp_path)
    vectors = VectorStore(tmp_path, embedder=fake_embedder)
    sid = store.create_session(started_at="2026-03-05T09:00:00+00:00")
    store.close_session(sid)
    store.mark_session_processed(sid)
    entry_id = store.add_entry(JournalEntry(
        session_id=sid, what_changed="Added SMOTE oversampling.",
        model_version="fake", prompt_version="v2",
    ))
    vectors.add("entries", [str(entry_id)], ["smote oversampling"], [{"session_id": sid}])

    engine = QueryEngine(store, vectors, FakeProvider())
    citations, _ = engine.retrieve("smote?", until="2026-03-05")
    assert [c.session.id for c in citations] == [sid]
    store.close()


def test_concurrent_store_handles(tmp_path: Path):
    """Bug 5: the post-commit hook writes from a second process while the
    daemon holds the DB. WAL + busy timeout must let both write."""
    store_a = Store.open(tmp_path)
    store_b = Store.open(tmp_path)  # separate connection, same file
    store_a.append_event("script_change", {"diff": "+a"})
    store_b.append_event("git_commit", {"hash": "abc", "message": "m"})
    assert len(store_a.events()) == 2
    assert len(store_b.events()) == 2
    store_a.close()
    store_b.close()


def test_baseline_scan_prunes_ignored_dirs(tmp_path: Path):
    """Bug 6: the scan used to descend into data/.venv even though every file
    inside was rejected."""
    write_default_config(tmp_path)
    (tmp_path / "train.py").write_text("x = 1", encoding="utf-8")
    deep = tmp_path / "data" / "a" / "b" / "c"
    deep.mkdir(parents=True)
    (deep / "junk.py").write_text("y = 2", encoding="utf-8")

    with Store.open(tmp_path) as store:
        service = WatchService(tmp_path, load_config(tmp_path), store)
        visited = list(service._walk_files())
        assert tmp_path / "train.py" in visited
        assert all("data" not in p.parts for p in (v.relative_to(tmp_path) for v in visited))
        assert service.baseline_scan() == 1  # only train.py


def test_nearby_papers_prefer_most_recent(tmp_path: Path):
    """Bug 7: with >3 nearby papers, the oldest three were kept."""
    with Store.open(tmp_path) as store:
        for day in (0, 1, 2, 3, 4):
            store.add_paper(f"papers/p{day}.pdf", title=f"paper{day}", added_at=ts(day))
        sid = store.create_session(started_at=ts(5))
        store.close_session(sid, ended_at=ts(5.1))
        nearby = papers_near_session(store, store.get_session(sid))
        assert [p.title for p in nearby] == ["paper4", "paper3", "paper2"]
