from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from conftest import FakeProvider, fake_embedder

from seshat.query.engine import NO_RESULTS_TEXT, QueryEngine
from seshat.store.db import Store
from seshat.store.schema import JournalEntry
from seshat.store.vectors import VectorStore

T0 = datetime(2026, 3, 1, 9, 0, 0, tzinfo=UTC)


def ts(days: float) -> str:
    return (T0 + timedelta(days=days)).isoformat(timespec="seconds")


def seed_entry(
    store: Store,
    vectors: VectorStore,
    day: float,
    what: str,
    outcome: str | None,
    intent: str | None,
    files: list[str],
) -> tuple[int, int]:
    session_id = store.create_session(started_at=ts(day))
    store.close_session(session_id, ended_at=ts(day + 0.1))
    store.mark_session_processed(session_id)
    entry = JournalEntry(
        session_id=session_id,
        what_changed=what,
        observable_outcome=outcome,
        inferred_intent=intent,
        intent_confidence=0.7,
        files_touched=files,
        model_version="fake/test-1",
        prompt_version="v2",
    )
    entry_id = store.add_entry(entry)
    text = "\n".join(filter(None, [what, outcome, intent]))
    vectors.add("entries", [str(entry_id)], [text], [{"session_id": session_id}])
    return session_id, entry_id


@pytest.fixture
def env(tmp_path: Path):
    store = Store.open(tmp_path)
    vectors = VectorStore(tmp_path, embedder=fake_embedder)
    smote = seed_entry(
        store, vectors, 0,
        "Added SMOTE oversampling before the classifier.",
        "minority F1 went from 0.61 to 0.68",
        "addressing class imbalance",
        ["train.ipynb"],
    )
    xgb = seed_entry(
        store, vectors, 5,
        "Tuned xgboost max depth and learning rate.",
        "validation AUC 0.83",
        "squeezing more out of the boosted model",
        ["train.ipynb", "tune.py"],
    )
    dropped = seed_entry(
        store, vectors, 10,
        "Dropped region_code column in preprocessing.",
        None,
        "column leaked target information",
        ["preprocess.py"],
    )
    engine = QueryEngine(store, vectors, FakeProvider("You tried SMOTE [session 1]."))
    yield store, vectors, engine, {"smote": smote, "xgb": xgb, "dropped": dropped}
    store.close()


def test_retrieve_ranks_relevant_session_first(env):
    _, _, engine, seeds = env
    citations, _ = engine.retrieve("have I tried SMOTE oversampling before?")
    assert citations[0].session.id == seeds["smote"][0]
    assert citations[0].entry.what_changed.startswith("Added SMOTE")


def test_retrieve_file_filter(env):
    _, _, engine, seeds = env
    citations, _ = engine.retrieve("what changed?", file_filter="preprocess.py")
    assert {c.session.id for c in citations} == {seeds["dropped"][0]}


def test_retrieve_date_filters(env):
    _, _, engine, seeds = env
    citations, _ = engine.retrieve("what changed?", since=ts(4), until=ts(6))
    assert {c.session.id for c in citations} == {seeds["xgb"][0]}


def test_retrieve_skips_stale_vectors(env):
    store, vectors, engine, seeds = env
    # Simulate a reprocess race: entry deleted from SQLite, vector left behind.
    store.delete_entries(seeds["smote"][0])
    citations, _ = engine.retrieve("have I tried SMOTE oversampling before?")
    assert seeds["smote"][0] not in {c.session.id for c in citations}


def test_ask_returns_cited_answer(env):
    _, _, engine, seeds = env
    answer = engine.ask("have I tried SMOTE oversampling before?")
    assert "[session 1]" in answer.text
    assert answer.citations[0].session.id == seeds["smote"][0]


def test_ask_prompt_grounds_on_entries(env):
    store, vectors, _, _ = env
    provider = FakeProvider("answer text")
    engine = QueryEngine(store, vectors, provider)
    engine.ask("why is region_code dropped in preprocessing?")
    prompt = provider.prompts[0]
    assert "Dropped region_code column" in prompt
    assert "column leaked target information" in prompt
    assert "inferred" in prompt  # intent status is visible to the answer model
    assert "never invent" in prompt


def test_ask_strips_think_tags(env):
    store, vectors, _, _ = env
    provider = FakeProvider("<think>reasoning...</think>The answer [session 2].")
    engine = QueryEngine(store, vectors, provider)
    assert engine.ask("xgboost tuning?").text == "The answer [session 2]."


def test_ask_with_no_data_short_circuits(tmp_path: Path):
    store = Store.open(tmp_path)
    vectors = VectorStore(tmp_path, embedder=fake_embedder)
    provider = FakeProvider("should never be called")
    engine = QueryEngine(store, vectors, provider)
    answer = engine.ask("anything?")
    assert answer.text == NO_RESULTS_TEXT
    assert provider.prompts == []  # LLM was not consulted
    store.close()


def test_papers_included_when_relevant(env):
    store, vectors, engine, _ = env
    paper_id = store.add_paper("papers/smote.pdf", title="SMOTE paper", added_at=ts(0))
    vectors.add(
        "papers",
        [f"p{paper_id}c0"],
        ["SMOTE synthetic minority oversampling improves imbalanced classification"],
        [{"paper_id": paper_id, "title": "SMOTE paper", "path": "papers/smote.pdf"}],
    )
    answer = engine.ask("have I tried SMOTE oversampling before?")
    assert any(p.title == "SMOTE paper" for p in answer.papers)
