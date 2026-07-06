import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from conftest import FakeProvider, fake_embedder

from seshat.backfill.git_history import (
    BackfillError,
    backfill,
    group_commits,
    list_commits,
)
from seshat.inference.queue import InferenceWorker
from seshat.store.db import Store
from seshat.store.vectors import VectorStore

T0 = datetime(2026, 3, 1, 9, 0, 0, tzinfo=UTC)


def commit_at(root: Path, minutes: int, message: str, filename: str = "train.py") -> None:
    (root / filename).write_text(f"# {message}\n", encoding="utf-8")
    when = (T0 + timedelta(minutes=minutes)).isoformat()
    env = {**os.environ, "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when}
    subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", message], cwd=root, check=True, capture_output=True, env=env
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@t.local"], cwd=tmp_path, check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "T"], cwd=tmp_path, check=True, capture_output=True
    )
    return tmp_path


def test_list_commits_ordered_with_utc_timestamps(repo: Path):
    commit_at(repo, 0, "first")
    commit_at(repo, 10, "second")
    refs = list_commits(repo)
    assert [r.subject for r in refs] == ["first", "second"]
    assert refs[0].ts == "2026-03-01T09:00:00+00:00"
    assert refs[1].ts < refs[1].ts.replace("09:10", "09:11")  # sanity: ISO sorts


def test_list_commits_empty_repo(repo: Path):
    assert list_commits(repo) == []


def test_not_a_repo_raises(tmp_path: Path):
    with pytest.raises(BackfillError, match="not a git repository"):
        list_commits(tmp_path)


def test_grouping_by_idle_gap(repo: Path):
    commit_at(repo, 0, "a")
    commit_at(repo, 30, "b")       # 30 min gap: same session
    commit_at(repo, 150, "c")      # 2h gap: new session
    commit_at(repo, 160, "d")
    groups = group_commits(list_commits(repo), idle_gap_minutes=45)
    assert [[r.subject for r in g] for g in groups] == [["a", "b"], ["c", "d"]]


def test_backfill_creates_closed_sessions_with_events(repo: Path):
    commit_at(repo, 0, "add baseline model")
    commit_at(repo, 20, "try class weighting", filename="weights.py")
    commit_at(repo, 200, "drop leaky column")

    with Store.open(repo) as store:
        sessions, commits = backfill(repo, store, idle_gap_minutes=45)
        assert (sessions, commits) == (2, 3)

        all_sessions = store.sessions()
        assert [s.status for s in all_sessions] == ["closed", "closed"]
        first = all_sessions[0]
        assert first.started_at == "2026-03-01T09:00:00+00:00"
        assert first.ended_at == "2026-03-01T09:20:00+00:00"

        events = store.events(session_id=first.id)
        assert [e.payload["message"] for e in events] == [
            "add baseline model",
            "try class weighting",
        ]
        assert "weights.py" in events[1].payload["files"]
        assert events[0].ts == first.started_at


def test_backfill_is_resumable(repo: Path):
    commit_at(repo, 0, "a")
    with Store.open(repo) as store:
        assert backfill(repo, store, 45) == (1, 1)
        assert backfill(repo, store, 45) == (0, 0)  # nothing new, no duplicates

        commit_at(repo, 500, "b")
        sessions, commits = backfill(repo, store, 45)
        assert (sessions, commits) == (1, 1)
        assert len(store.events(kind="git_commit")) == 2


def test_backfill_skips_hook_recorded_commits(repo: Path):
    """A commit already captured live by the post-commit hook isn't re-ingested."""
    from seshat.watcher.scripts import read_commit

    commit_at(repo, 0, "recorded live")
    with Store.open(repo) as store:
        store.append_event("git_commit", read_commit(repo))
        assert backfill(repo, store, 45) == (0, 0)


def test_backfilled_sessions_flow_through_inference_queue(repo: Path):
    commit_at(repo, 0, "add smote oversampling")
    commit_at(repo, 300, "tune xgboost depth")

    with Store.open(repo) as store:
        backfill(repo, store, 45)
        vectors = VectorStore(repo, embedder=fake_embedder)
        worker = InferenceWorker(store, vectors, FakeProvider(), busy_check=lambda: False)
        assert worker.run_pending() == 2
        assert all(s.status == "processed" for s in store.sessions())
        assert vectors.count("entries") == 2
