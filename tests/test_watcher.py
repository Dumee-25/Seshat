"""Integration tests for the watch service (direct processing + one real
filesystem-event test at the end)."""

import json
import subprocess
import threading
import time
from pathlib import Path

import pytest

from seshat.config import load_config, write_default_config
from seshat.store.db import Store
from seshat.watcher.daemon import WatchService
from seshat.watcher.scripts import install_post_commit_hook, read_head_commit


def make_nb(*sources: str) -> str:
    return json.dumps({
        "cells": [
            {"id": f"c{i}", "cell_type": "code", "source": src,
             "execution_count": i + 1, "outputs": [], "metadata": {}}
            for i, src in enumerate(sources)
        ],
        "nbformat": 4,
        "nbformat_minor": 5,
    })


@pytest.fixture
def project(tmp_path: Path):
    write_default_config(tmp_path)
    store = Store.open(tmp_path)
    service = WatchService(tmp_path, load_config(tmp_path), store)
    yield tmp_path, store, service
    store.close()


def test_notebook_save_produces_cell_diff_event(project):
    root, store, service = project
    nb = root / "train.ipynb"

    nb.write_text(make_nb("import pandas"), encoding="utf-8")
    assert service.process_file(nb) is None  # first sight: baseline, no event

    nb.write_text(make_nb("import pandas", "model.fit(X, y)"), encoding="utf-8")
    event_id = service.process_file(nb)
    assert event_id is not None

    (event,) = store.events(kind="notebook_diff")
    assert event.path == "train.ipynb"
    assert event.session_id is not None
    assert event.payload["added"][0]["source"] == "model.fit(X, y)"


def test_script_save_produces_unified_diff(project):
    root, store, service = project
    script = root / "preprocess.py"

    script.write_text("df = df.dropna()\n", encoding="utf-8")
    service.process_file(script)
    script.write_text("df = df.dropna()\ndf = df.drop(columns=['region_code'])\n", encoding="utf-8")
    service.process_file(script)

    (event,) = store.events(kind="script_change")
    assert "+df = df.drop(columns=['region_code'])" in event.payload["diff"]
    assert event.payload["lines_added"] == 1


def test_unchanged_save_emits_no_event(project):
    root, store, service = project
    script = root / "train.py"
    script.write_text("x = 1\n", encoding="utf-8")
    service.process_file(script)
    assert service.process_file(script) is None  # resave, no change
    assert store.events() == []


def test_result_file_indexed_with_artifact(project):
    root, store, service = project
    result = root / "results" / "metrics.csv"
    result.parent.mkdir()
    result.write_text("epoch,val_loss\n1,0.52\n2,0.31\n", encoding="utf-8")
    service.process_file(result)

    (event,) = store.events(kind="result_file")
    assert "val_loss" in event.payload["preview"]
    assert store.artifact_id_for_path("results/metrics.csv") == event.payload["artifact_id"]
    # Re-saving reuses the artifact rather than duplicating it.
    service.process_file(result)
    assert store.artifact_id_for_path("results/metrics.csv") == event.payload["artifact_id"]


def test_ignored_file_produces_nothing(project):
    root, store, service = project
    junk = root / "data" / "gen.py"
    junk.parent.mkdir()
    junk.write_text("x = 1", encoding="utf-8")
    assert service.process_file(junk) is None
    assert store.events() == []


def test_baseline_scan_snapshots_without_events(project):
    root, store, service = project
    (root / "a.py").write_text("a = 1", encoding="utf-8")
    (root / "b.ipynb").write_text(make_nb("b = 2"), encoding="utf-8")
    assert service.baseline_scan() == 2
    assert store.events() == []
    # A later edit diffs against the baseline.
    (root / "a.py").write_text("a = 2", encoding="utf-8")
    assert service.process_file(root / "a.py") is not None


def test_events_share_session(project):
    root, store, service = project
    for name in ("one.py", "two.py"):
        f = root / name
        f.write_text("x = 1", encoding="utf-8")
        service.process_file(f)
        f.write_text("x = 2", encoding="utf-8")
        service.process_file(f)
    sessions = {e.session_id for e in store.events()}
    assert len(sessions) == 1


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=True
    ).stdout


@pytest.fixture
def git_project(tmp_path: Path) -> Path:
    write_default_config(tmp_path)
    git(tmp_path, "init")
    git(tmp_path, "config", "user.email", "test@test.local")
    git(tmp_path, "config", "user.name", "Test")
    return tmp_path


def test_read_head_commit(git_project: Path):
    (git_project / "train.py").write_text("model.fit(X, y)\n", encoding="utf-8")
    git(git_project, "add", ".")
    git(git_project, "commit", "-m", "try class weighting for imbalance")

    payload = read_head_commit(git_project)
    assert payload["message"] == "try class weighting for imbalance"
    assert "train.py" in payload["files"]
    assert "+model.fit(X, y)" in payload["diff"]


def test_install_post_commit_hook(git_project: Path):
    hook = install_post_commit_hook(git_project)
    assert hook.exists()
    assert "record-commit" in hook.read_text(encoding="utf-8")
    install_post_commit_hook(git_project)  # reinstall over our own hook is fine

    hook.write_text("#!/bin/sh\necho custom hook\n", encoding="utf-8")
    with pytest.raises(FileExistsError, match="manually"):
        install_post_commit_hook(git_project)


def test_hook_install_requires_git_repo(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="not a git repository"):
        install_post_commit_hook(tmp_path)


def test_real_filesystem_watch_end_to_end(project):
    """Full loop: watchdog event -> debounce -> diff -> raw event in SQLite."""
    root, store, service = project
    script = root / "train.py"
    script.write_text("x = 1\n", encoding="utf-8")
    service.baseline_scan()

    thread = threading.Thread(target=service.run, daemon=True)
    thread.start()
    time.sleep(1.0)  # let the observer start
    script.write_text("x = 2\n", encoding="utf-8")

    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if store.events(kind="script_change"):
                break
            time.sleep(0.25)
        (event,) = store.events(kind="script_change")
        assert "+x = 2" in event.payload["diff"]
    finally:
        service.stop()
        thread.join(timeout=10)
