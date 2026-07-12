"""Cockpit chat endpoints, with an injected fake engine (no Ollama needed)."""

from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from seshat.api.app import create_app
from seshat.config import load_config, write_default_config
from seshat.query.engine import Answer, SessionCitation
from seshat.store.db import Store
from seshat.store.schema import JournalEntry


class FakeEngine:
    """Returns a canned answer citing a real seeded session, and records the
    query in chat history the way the real engine's store path does."""

    def __init__(self, store: Store, session_id: int) -> None:
        self._store = store
        self._session_id = session_id

    def ask(self, question, **kwargs) -> Answer:
        session = self._store.get_session(self._session_id)
        entry = self._store.entries(session_id=self._session_id)[0]
        return Answer(
            text=f"You did that [session {self._session_id}].",
            citations=[SessionCitation(session=session, entry=entry, score=0.1)],
            papers=[],
        )


@pytest.fixture
def client(tmp_path: Path):
    write_default_config(tmp_path)
    config = load_config(tmp_path)
    store = Store.open(tmp_path)
    sid = store.create_session(started_at="2026-03-01T09:00:00+00:00")
    store.close_session(sid, ended_at="2026-03-01T10:00:00+00:00")
    store.mark_session_processed(sid)
    store.add_entry(JournalEntry(
        session_id=sid, what_changed="Added SMOTE oversampling.",
        inferred_intent="class imbalance", intent_confidence=0.8,
        model_version="m", prompt_version="v2",
    ))

    @contextmanager
    def engine_cm():
        yield FakeEngine(store, sid), store

    api = TestClient(create_app(tmp_path, config, engine_cm=engine_cm))
    yield api, store, sid
    store.close()


def test_chat_returns_cited_answer(client):
    api, _, sid = client
    r = api.post("/api/chat", json={"question": "did I try SMOTE?"})
    assert r.status_code == 200
    body = r.json()
    assert f"[session {sid}]" in body["answer"]
    assert body["citations"][0]["session_id"] == sid
    assert body["citations"][0]["what_changed"] == "Added SMOTE oversampling."


def test_chat_persists_history(client):
    api, store, sid = client
    api.post("/api/chat", json={"question": "did I try SMOTE?"})
    hist = api.get("/api/chat/history").json()["messages"]
    assert [m["role"] for m in hist] == ["user", "assistant"]
    assert hist[0]["text"] == "did I try SMOTE?"
    # Assistant message keeps resolvable citations for old history too.
    assert hist[1]["citations"][0]["session_id"] == sid


def test_chat_clear(client):
    api, _, _ = client
    api.post("/api/chat", json={"question": "q1"})
    assert len(api.get("/api/chat/history").json()["messages"]) == 2
    cleared = api.post("/api/chat/clear").json()["cleared"]
    assert cleared == 2
    assert api.get("/api/chat/history").json()["messages"] == []


def test_chat_history_empty_initially(client):
    api, _, _ = client
    assert api.get("/api/chat/history").json()["messages"] == []
