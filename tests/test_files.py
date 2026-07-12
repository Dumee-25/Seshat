from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from seshat.api.app import create_app
from seshat.config import load_config, write_default_config
from seshat.query.files import build_tree, code_files, file_history, recent_changes
from seshat.store.db import Store
from seshat.store.schema import JournalEntry


def make_project(tmp_path: Path) -> Path:
    write_default_config(tmp_path)
    (tmp_path / "train.py").write_text("x = 1", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "model.py").write_text("y = 2", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("ignore me", encoding="utf-8")  # not code
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "gen.py").write_text("z = 3", encoding="utf-8")  # ignored dir
    return tmp_path


def test_code_files_lists_only_watched_code(tmp_path: Path):
    make_project(tmp_path)
    config = load_config(tmp_path)
    files = code_files(tmp_path, config)
    assert "train.py" in files
    assert "src/model.py" in files
    assert "notes.txt" not in files  # not a code suffix
    assert not any("data/" in f for f in files)  # ignored dir pruned


def test_build_tree_nests_dirs_first():
    tree = build_tree(
        ["train.py", "src/model.py"],
        {"train.py": {"changes": 3, "last_changed": "2026-03-01T09:00:00+00:00"}},
    )
    names = [n["name"] for n in tree]
    assert names == ["src", "train.py"]  # dir before file
    src = tree[0]
    assert src["type"] == "dir"
    assert src["children"][0]["path"] == "src/model.py"
    train = tree[1]
    assert train["changes"] == 3


@pytest.fixture
def seeded(tmp_path: Path):
    make_project(tmp_path)
    store = Store.open(tmp_path)
    sid = store.create_session(started_at="2026-03-01T09:00:00+00:00")
    for ts, payload in [
        ("2026-03-01T09:01:00+00:00", {"diff": "+a", "lines_added": 1, "lines_removed": 0}),
        ("2026-03-01T09:05:00+00:00", {"diff": "+b", "lines_added": 2, "lines_removed": 1}),
    ]:
        eid = store.append_event("script_change", payload, path="train.py", ts=ts)
        store.assign_events_to_session([eid], sid)
    store.close_session(sid, ended_at="2026-03-01T10:00:00+00:00")
    store.mark_session_processed(sid)
    store.add_entry(JournalEntry(
        session_id=sid, what_changed="Tuned the training loop.",
        model_version="m", prompt_version="v2",
    ))
    yield tmp_path, store, sid
    store.close()


def test_file_history_links_to_sessions(seeded):
    _, store, sid = seeded
    history = file_history(store, "train.py")
    assert len(history) == 1
    assert history[0]["session_id"] == sid
    assert history[0]["what_changed"] == "Tuned the training loop."


def test_recent_changes_newest_first(seeded):
    _, store, _ = seeded
    changes = recent_changes(store)
    assert changes[0]["ts"] > changes[1]["ts"]
    assert changes[0]["summary"] == "+2 -1"
    assert changes[0]["path"] == "train.py"


# -- API ----------------------------------------------------------------------


@pytest.fixture
def client(seeded):
    root, _, _ = seeded
    return TestClient(create_app(root, load_config(root))), seeded[2]


def test_files_endpoint(client):
    api, _ = client
    tree = api.get("/api/files").json()["tree"]
    paths = {n["path"] for n in tree}
    assert "train.py" in paths
    train = next(n for n in tree if n["path"] == "train.py")
    assert train["changes"] == 2


def test_files_changes_endpoint(client):
    api, _ = client
    changes = api.get("/api/files/changes").json()["changes"]
    assert changes[0]["path"] == "train.py"


def test_files_history_endpoint(client):
    api, sid = client
    body = api.get("/api/files/history", params={"path": "train.py"}).json()
    assert body["sessions"][0]["session_id"] == sid
