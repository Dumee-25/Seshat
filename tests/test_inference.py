import json
from pathlib import Path

import pytest
from conftest import FakeProvider, fake_embedder

from seshat.inference.journal import generate_entry, parse_response
from seshat.inference.prompts import PROMPT_VERSION, build_journal_prompt
from seshat.inference.provider import GenerationError
from seshat.inference.queue import InferenceWorker
from seshat.store.db import Store
from seshat.store.schema import RawEvent, Session
from seshat.store.vectors import VectorStore


@pytest.fixture
def env(tmp_path: Path):
    store = Store.open(tmp_path)
    vectors = VectorStore(tmp_path, embedder=fake_embedder)
    yield store, vectors
    store.close()


def closed_session_with_events(store: Store) -> int:
    session_id = store.create_session()
    for kind, path, payload in [
        ("notebook_diff", "train.ipynb", {
            "added": [{"id": "c1", "index": 0,
                       "source": "sm = SMOTE()\nX_res, y_res = sm.fit_resample(X, y)",
                       "outputs": ["F1: 0.68"], "execution_count": 5}],
            "removed": [], "modified": [], "reordered": False,
            "kernel_restarted": False, "cell_count": 3,
        }),
        ("git_commit", None, {"hash": "abc123", "message": "try smote",
                              "files": ["train.ipynb"], "diff": "+SMOTE()"}),
    ]:
        event_id = store.append_event(kind, payload, path=path)
        store.assign_events_to_session([event_id], session_id)
    store.close_session(session_id)
    return session_id


# -- prompts -------------------------------------------------------------------


def test_prompt_contains_events_and_instructions(env):
    store, _ = env
    session_id = closed_session_with_events(store)
    prompt = build_journal_prompt(
        store.get_session(session_id), store.events(session_id=session_id)
    )
    assert "fit_resample" in prompt
    assert "F1: 0.68" in prompt
    assert 'commit message: "try smote"' in prompt
    assert "what_changed" in prompt


def test_prompt_caps_total_size():
    session = Session(started_at="2026-07-06T10:00:00+00:00", id=1)
    events = [
        RawEvent(ts="t", kind="script_change", path=f"f{i}.py",
                 payload={"diff": "x" * 1400}, id=i)
        for i in range(50)
    ]
    prompt = build_journal_prompt(session, events)
    assert len(prompt) < 12000
    assert "omitted" in prompt


# -- response parsing ------------------------------------------------------------


def test_parse_plain_json():
    assert parse_response('{"what_changed": "x"}')["what_changed"] == "x"


def test_parse_json_with_prose_and_fences():
    text = (
        'Here is the entry:\n```json\n'
        '{"what_changed": "x", "intent_confidence": 0.5}\n```\nDone!'
    )
    assert parse_response(text)["intent_confidence"] == 0.5


def test_parse_strips_thinking_tags():
    text = '<think>{"what_changed": "draft"} hmm...</think>{"what_changed": "final"}'
    assert parse_response(text)["what_changed"] == "final"


@pytest.mark.parametrize(
    "bad",
    ["no json here", "{broken", '{"other_key": 1}', '{"what_changed": ""}'],
)
def test_parse_rejects_garbage(bad):
    with pytest.raises(GenerationError):
        parse_response(bad)


# -- entry generation ------------------------------------------------------------


def test_generate_entry_end_to_end(env):
    store, vectors = env
    session_id = closed_session_with_events(store)
    entry = generate_entry(store, vectors, FakeProvider(), session_id)

    assert entry.id is not None
    assert entry.intent_status == "inferred"
    assert entry.intent_confidence == 0.8
    assert entry.files_touched == ["train.ipynb"]
    assert len(entry.raw_event_ids) == 2
    assert entry.model_version == "fake/test-1"
    assert entry.prompt_version == PROMPT_VERSION
    assert store.get_session(session_id).status == "processed"
    hits = vectors.query("entries", "SMOTE oversampling class imbalance")
    assert hits[0].metadata["session_id"] == session_id


def test_generate_clamps_bad_confidence(env):
    store, vectors = env
    session_id = closed_session_with_events(store)
    provider = FakeProvider(json.dumps({"what_changed": "x", "intent_confidence": 3.5}))
    assert generate_entry(store, vectors, provider, session_id).intent_confidence == 1.0


def test_generate_empty_session_marks_processed_without_entry(env):
    store, vectors = env
    session_id = store.create_session()
    store.close_session(session_id)
    assert generate_entry(store, vectors, FakeProvider(), session_id) is None
    assert store.get_session(session_id).status == "processed"
    assert store.entries() == []


def test_regenerate_replaces_old_entry(env):
    store, vectors = env
    session_id = closed_session_with_events(store)
    first = generate_entry(store, vectors, FakeProvider(), session_id)
    second = generate_entry(
        store, vectors,
        FakeProvider(json.dumps({"what_changed": "Reprocessed with better model."})),
        session_id,
    )
    assert first.id != second.id
    entries = store.entries(session_id=session_id)
    assert len(entries) == 1
    assert entries[0].what_changed == "Reprocessed with better model."
    assert vectors.count("entries") == 1  # old vector removed too


# -- queue ------------------------------------------------------------------------


def test_worker_processes_pending_sessions(env):
    store, vectors = env
    first = closed_session_with_events(store)
    second = closed_session_with_events(store)
    worker = InferenceWorker(store, vectors, FakeProvider(), busy_check=lambda: False)
    assert set(worker.pending_sessions()) == {first, second}
    assert worker.run_pending() == 2
    assert worker.pending_sessions() == []


def test_worker_defers_while_gpu_busy(env):
    store, vectors = env
    closed_session_with_events(store)
    worker = InferenceWorker(store, vectors, FakeProvider(), busy_check=lambda: True)
    assert worker.run_pending() == 0
    assert len(worker.pending_sessions()) == 1  # still queued
    assert worker.run_pending(force=True) == 1


def test_cpu_fallback_ignores_gpu(env):
    store, vectors = env
    closed_session_with_events(store)
    worker = InferenceWorker(
        store, vectors, FakeProvider(), cpu_fallback=True, busy_check=lambda: True
    )
    assert worker.run_pending() == 1


def test_provider_failure_keeps_session_queued(env):
    store, vectors = env
    session_id = closed_session_with_events(store)
    worker = InferenceWorker(store, vectors, FakeProvider(fail=True), busy_check=lambda: False)
    assert worker.run_pending() == 0
    assert store.get_session(session_id).status == "closed"
    assert store.entries() == []

    worker = InferenceWorker(store, vectors, FakeProvider(), busy_check=lambda: False)
    assert worker.run_pending() == 1  # recovers on the next run
