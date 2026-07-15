from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from seshat.api.app import create_app
from seshat.config import load_config, write_default_config
from seshat.store.db import Store
from seshat.store.schema import JournalEntry


@pytest.fixture
def client(tmp_path: Path):
    write_default_config(tmp_path)
    config = load_config(tmp_path)
    with Store.open(tmp_path) as store:
        sid = store.create_session(started_at="2026-03-01T09:00:00+00:00")
        eid = store.append_event(
            "script_change", {"diff": "+sm = SMOTE()"}, path="train.py",
            ts="2026-03-01T09:05:00+00:00",
        )
        store.assign_events_to_session([eid], sid)
        store.close_session(sid, ended_at="2026-03-01T10:00:00+00:00")
        store.mark_session_processed(sid)
        store.add_entry(JournalEntry(
            session_id=sid, what_changed="Added SMOTE oversampling.",
            observable_outcome="F1 0.61 -> 0.68", inferred_intent="class imbalance",
            intent_confidence=0.8, files_touched=["train.py"],
            model_version="m", prompt_version="v2",
        ))
        store.add_paper("papers/smote.pdf", title="SMOTE paper",
                        added_at="2026-02-28T12:00:00+00:00")
    return TestClient(create_app(tmp_path, config)), sid


def test_health(client):
    api, _ = client
    r = api.get("/api/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_status_counts(client):
    api, _ = client
    body = api.get("/api/status").json()
    assert body["project"]
    assert body["sessions"] == 1
    assert body["queued"] == 0  # the session is processed
    assert body["papers"] == 1


def test_timeline_endpoint(client):
    api, sid = client
    items = api.get("/api/timeline").json()["items"]
    kinds = {i["kind"] for i in items}
    assert kinds == {"session", "paper"}
    session_item = next(i for i in items if i["kind"] == "session")
    assert session_item["id"] == sid
    assert session_item["title"] == "Added SMOTE oversampling."


def test_timeline_kinds_filter(client):
    api, _ = client
    items = api.get("/api/timeline?kinds=paper").json()["items"]
    assert {i["kind"] for i in items} == {"paper"}


def test_session_detail(client):
    api, sid = client
    body = api.get(f"/api/sessions/{sid}").json()
    assert body["session"]["id"] == sid
    assert body["entries"][0]["what_changed"] == "Added SMOTE oversampling."
    assert body["events"][0]["kind"] == "script_change"
    assert "+sm = SMOTE()" in body["events"][0]["payload"]["diff"]


def test_session_detail_404(client):
    api, _ = client
    assert api.get("/api/sessions/9999").status_code == 404


# -- intent confirm / correct -------------------------------------------------


def entry_id_of(api) -> int:
    item = next(i for i in api.get("/api/timeline").json()["items"] if i["kind"] == "session")
    return item["meta"]["entry_id"]


def test_timeline_carries_entry_id(client):
    api, _ = client
    item = next(i for i in api.get("/api/timeline").json()["items"] if i["kind"] == "session")
    assert item["meta"]["entry_id"] == entry_id_of(api)
    assert item["meta"]["intent_status"] == "inferred"


def test_confirm_intent_keeps_the_inferred_text(client):
    api, sid = client
    eid = entry_id_of(api)
    body = api.post(f"/api/entries/{eid}/intent", json={}).json()
    assert body == {"id": eid, "intent": "class imbalance", "intent_status": "confirmed"}
    entry = api.get(f"/api/sessions/{sid}").json()["entries"][0]
    assert entry["inferred_intent"] == "class imbalance"
    assert entry["intent_status"] == "confirmed"


def test_correcting_intent_records_a_correction(client):
    api, sid = client
    eid = entry_id_of(api)
    body = api.post(f"/api/entries/{eid}/intent", json={"intent": "recall was capped"}).json()
    assert body["intent_status"] == "corrected"
    entry = api.get(f"/api/sessions/{sid}").json()["entries"][0]
    assert entry["inferred_intent"] == "recall was capped"
    assert entry["intent_status"] == "corrected"


def test_resubmitting_the_same_text_is_a_confirmation(client):
    api, _ = client
    eid = entry_id_of(api)
    body = api.post(f"/api/entries/{eid}/intent", json={"intent": "  class imbalance  "}).json()
    assert body["intent_status"] == "confirmed"  # unchanged text is not a correction


def test_blank_intent_is_rejected(client):
    api, _ = client
    eid = entry_id_of(api)
    assert api.post(f"/api/entries/{eid}/intent", json={"intent": "   "}).status_code == 400


def test_intent_404(client):
    api, _ = client
    assert api.post("/api/entries/9999/intent", json={}).status_code == 404
