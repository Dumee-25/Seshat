from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from seshat.api.app import create_app
from seshat.config import load_config, write_default_config
from seshat.query.data import artifact_sessions, list_artifacts, preview_file
from seshat.store.db import Store
from seshat.store.schema import JournalEntry


@pytest.fixture
def seeded(tmp_path: Path):
    write_default_config(tmp_path)
    results = tmp_path / "results"
    results.mkdir()
    (results / "metrics.csv").write_text(
        "epoch,val_loss,val_auc\n1,0.52,0.78\n2,0.31,0.83\n", encoding="utf-8"
    )
    (results / "config.json").write_text('{"lr": 0.01, "depth": 6}', encoding="utf-8")

    store = Store.open(tmp_path)
    sid = store.create_session(started_at="2026-03-01T09:00:00+00:00")
    csv_id = store.add_artifact("results/metrics.csv", kind="result")
    store.add_artifact("results/config.json", kind="result")
    eid = store.append_event(
        "result_file", {"artifact_id": csv_id, "preview": "epoch,val_loss"},
        path="results/metrics.csv", ts="2026-03-01T09:30:00+00:00",
    )
    store.assign_events_to_session([eid], sid)
    store.close_session(sid, ended_at="2026-03-01T10:00:00+00:00")
    store.mark_session_processed(sid)
    store.add_entry(JournalEntry(
        session_id=sid, what_changed="Logged eval metrics.",
        model_version="m", prompt_version="v2",
    ))
    yield tmp_path, store, csv_id, sid
    store.close()


def test_list_artifacts(seeded):
    _, store, _, _ = seeded
    arts = list_artifacts(store)
    assert {a["name"] for a in arts} == {"metrics.csv", "config.json"}


def test_preview_csv(seeded):
    root, _, _, _ = seeded
    preview = preview_file(root, "results/metrics.csv")
    assert preview["kind"] == "csv"
    assert preview["columns"] == ["epoch", "val_loss", "val_auc"]
    assert preview["rows"][1] == ["2", "0.31", "0.83"]


def test_preview_json(seeded):
    root, _, _, _ = seeded
    preview = preview_file(root, "results/config.json")
    assert preview["kind"] == "json"
    assert '"lr": 0.01' in preview["text"]


def test_preview_missing_file(seeded):
    root, _, _, _ = seeded
    assert preview_file(root, "results/gone.csv")["kind"] == "missing"


def test_artifact_sessions(seeded):
    _, store, _, sid = seeded
    sessions = artifact_sessions(store, "results/metrics.csv")
    assert sessions[0]["session_id"] == sid
    assert sessions[0]["what_changed"] == "Logged eval metrics."


# -- API ----------------------------------------------------------------------


@pytest.fixture
def client(seeded):
    root = seeded[0]
    return TestClient(create_app(root, load_config(root))), seeded[2], seeded[3]


def test_data_list_endpoint(client):
    api, _, _ = client
    arts = api.get("/api/data").json()["artifacts"]
    assert len(arts) == 2


def test_data_detail_endpoint(client):
    api, csv_id, sid = client
    body = api.get(f"/api/data/{csv_id}").json()
    assert body["artifact"]["path"] == "results/metrics.csv"
    assert body["preview"]["kind"] == "csv"
    assert body["preview"]["columns"] == ["epoch", "val_loss", "val_auc"]
    assert body["sessions"][0]["session_id"] == sid


def test_data_detail_404(client):
    api, _, _ = client
    assert api.get("/api/data/9999").status_code == 404
