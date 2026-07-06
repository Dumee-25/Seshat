import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from conftest import FakeProvider, fake_embedder

from seshat.eval.runner import EvalCase, EvalError, load_cases, run_eval
from seshat.query.engine import QueryEngine
from seshat.store.db import Store
from seshat.store.schema import JournalEntry
from seshat.store.vectors import VectorStore

T0 = datetime(2026, 3, 1, 9, 0, 0, tzinfo=UTC)


def ts(days: float) -> str:
    return (T0 + timedelta(days=days)).isoformat(timespec="seconds")


def seed(store: Store, vectors: VectorStore, day: float, what: str, intent: str) -> int:
    session_id = store.create_session(started_at=ts(day))
    store.close_session(session_id, ended_at=ts(day + 0.1))
    store.mark_session_processed(session_id)
    entry_id = store.add_entry(JournalEntry(
        session_id=session_id, what_changed=what, inferred_intent=intent,
        intent_confidence=0.7, model_version="fake", prompt_version="v2",
    ))
    vectors.add("entries", [str(entry_id)], [f"{what}\n{intent}"],
                [{"session_id": session_id}])
    return session_id


@pytest.fixture
def env(tmp_path: Path):
    store = Store.open(tmp_path)
    vectors = VectorStore(tmp_path, embedder=fake_embedder)
    smote_sid = seed(store, vectors, 0,
                     "Added SMOTE oversampling to training.", "class imbalance")
    xgb_sid = seed(store, vectors, 5,
                   "Tuned xgboost max depth.", "better boosted model")
    yield store, vectors, {"smote": smote_sid, "xgb": xgb_sid}
    store.close()


def test_run_eval_scores_citations_and_answers(env):
    store, vectors, sids = env
    engine = QueryEngine(store, vectors, FakeProvider("You used SMOTE oversampling."))
    cases = [
        EvalCase("did I try SMOTE oversampling?",
                 expect_sessions=[sids["smote"]], expect_keywords=["smote"]),
        EvalCase("did I tune xgboost max depth?",
                 expect_sessions=[sids["xgb"]], expect_keywords=["xgboost"]),
    ]
    report = run_eval(engine, cases)
    assert report.citation_accuracy == 1.0
    # FakeProvider always answers about SMOTE, so only case 1's keyword matches.
    assert report.answer_accuracy == 0.5
    assert report.results[0].answer_ok is True
    assert report.results[1].answer_ok is False


def test_retrieval_only_never_calls_the_llm(env):
    store, vectors, sids = env
    provider = FakeProvider("should not be called")
    engine = QueryEngine(store, vectors, provider)
    cases = [EvalCase("smote oversampling?", expect_sessions=[sids["smote"]])]
    report = run_eval(engine, cases, retrieval_only=True)
    assert report.citation_accuracy == 1.0
    assert report.answer_accuracy is None
    assert provider.prompts == []


def test_eval_queries_not_logged_but_chat_queries_are(env):
    store, vectors, sids = env
    engine = QueryEngine(store, vectors, FakeProvider("answer"))
    run_eval(engine, [EvalCase("smote?")])
    assert store.query_log() == []

    engine.ask("did I try smote oversampling?")  # a real chat query
    assert len(store.query_log()) == 1
    assert store.query_log()[0][1] == "did I try smote oversampling?"


def test_missed_citation_reported(env):
    store, vectors, sids = env
    engine = QueryEngine(store, vectors, FakeProvider("x"))
    report = run_eval(
        engine,
        [EvalCase("smote oversampling?", expect_sessions=[999])],
        retrieval_only=True,
    )
    assert report.citation_accuracy == 0.0
    assert report.results[0].cited_sessions  # something was cited, just not 999


def test_load_cases_roundtrip(tmp_path: Path):
    path = tmp_path / "q.json"
    path.write_text(json.dumps([
        {"question": "q1", "expect_sessions": [1], "expect_keywords": ["a"]},
        {"question": "q2"},
    ]), encoding="utf-8")
    cases = load_cases(path)
    assert cases[0].expect_sessions == [1]
    assert cases[1].expect_keywords == []


@pytest.mark.parametrize("bad", ["not json", "[]", '[{"no_question": 1}]'])
def test_load_cases_rejects_bad_files(tmp_path: Path, bad: str):
    path = tmp_path / "q.json"
    path.write_text(bad, encoding="utf-8")
    with pytest.raises(EvalError):
        load_cases(path)


def test_example_questions_file_is_valid():
    cases = load_cases(Path(__file__).parent.parent / "eval" / "questions.example.json")
    assert len(cases) >= 3
