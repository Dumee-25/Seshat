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


def queued_client(tmp_path: Path, busy: bool):
    """A project with one session still awaiting journaling."""
    write_default_config(tmp_path)
    config = load_config(tmp_path)
    with Store.open(tmp_path) as store:
        store.close_session(store.create_session(started_at="2026-03-01T09:00:00+00:00"))
    return TestClient(create_app(tmp_path, config, busy_check=lambda: busy))


def test_status_reports_a_busy_gpu_behind_a_stalled_queue(tmp_path: Path):
    body = queued_client(tmp_path, busy=True).get("/api/status").json()
    assert body["queued"] == 1
    assert body["gpu_busy"] is True


def test_status_reports_an_idle_gpu(tmp_path: Path):
    body = queued_client(tmp_path, busy=False).get("/api/status").json()
    assert body["queued"] == 1
    assert body["gpu_busy"] is False


def test_status_skips_the_gpu_check_when_nothing_is_queued(client):
    """Nothing is waiting, so the GPU's state is not a reason for anything."""
    api, _ = client
    assert api.get("/api/status").json()["gpu_busy"] is False


def test_setup_endpoint_reports_a_healthy_ollama(tmp_path: Path):
    from seshat.app.setup import SetupReport

    write_default_config(tmp_path)
    config = load_config(tmp_path)
    api = TestClient(create_app(
        tmp_path, config,
        setup_check=lambda: SetupReport(True, True, present_models=["qwen3:8b"]),
    ))
    assert api.get("/api/setup").json() == {
        "ollama_installed": True, "ollama_running": True,
        "missing_models": [], "ok": True,
    }


def test_setup_endpoint_reports_what_is_missing(tmp_path: Path):
    from seshat.app.setup import SetupReport

    write_default_config(tmp_path)
    config = load_config(tmp_path)
    api = TestClient(create_app(
        tmp_path, config,
        setup_check=lambda: SetupReport(True, False, missing=["qwen3:8b", "nomic-embed-text"]),
    ))
    body = api.get("/api/setup").json()
    assert body["ok"] is False
    assert body["ollama_running"] is False
    assert body["missing_models"] == ["qwen3:8b", "nomic-embed-text"]


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


def test_timeline_search(client):
    api, sid = client
    body = api.get("/api/timeline?q=oversampling").json()
    assert [i["id"] for i in body["items"]] == [sid]
    assert body["total"] == 1


def test_timeline_search_finds_the_intent(client):
    api, _ = client
    assert api.get("/api/timeline?q=class+imbalance").json()["total"] == 1


def test_timeline_reports_total_beyond_the_page(client):
    api, _ = client
    body = api.get("/api/timeline?limit=1").json()
    assert len(body["items"]) == 1
    assert body["total"] == 2  # a session and a paper


def test_timeline_offset_pages_through(client):
    api, _ = client
    first = api.get("/api/timeline?limit=1").json()["items"]
    second = api.get("/api/timeline?limit=1&offset=1").json()["items"]
    assert first[0]["kind"] != second[0]["kind"]


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


def test_reset_undoes_a_correction(client):
    api, sid = client
    eid = entry_id_of(api)
    api.post(f"/api/entries/{eid}/intent", json={"intent": "recall was capped"})
    body = api.post(f"/api/entries/{eid}/intent/reset").json()
    assert body == {"id": eid, "intent": "class imbalance", "intent_status": "inferred"}
    entry = api.get(f"/api/sessions/{sid}").json()["entries"][0]
    assert entry["inferred_intent"] == "class imbalance"
    assert entry["intent_status"] == "inferred"


def test_reset_undoes_a_confirmation(client):
    api, _ = client
    eid = entry_id_of(api)
    api.post(f"/api/entries/{eid}/intent", json={})
    assert api.post(f"/api/entries/{eid}/intent/reset").json()["intent_status"] == "inferred"


def test_reset_can_be_repeated(client):
    """Triage is fast and clicky; undoing twice must not become an error."""
    api, _ = client
    eid = entry_id_of(api)
    api.post(f"/api/entries/{eid}/intent", json={"intent": "wrong"})
    assert api.post(f"/api/entries/{eid}/intent/reset").status_code == 200
    assert api.post(f"/api/entries/{eid}/intent/reset").status_code == 200


def test_reset_unknown_entry_is_404(client):
    api, _ = client
    assert api.post("/api/entries/9999/intent/reset").status_code == 404


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
