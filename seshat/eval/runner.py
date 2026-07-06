"""Retrieval/answer evaluation over a known project history (Seshat.md §8).

A questions file holds cases with ground truth: which sessions should be
cited, and which keywords the answer must contain. Two metrics come out:

- citation accuracy: an expected session appears in the retrieved citations
  (works without any LLM — use retrieval_only when Ollama isn't running);
- answer accuracy: every expected keyword appears in the generated answer.

Eval queries are never written to the query log; that log counts only
voluntary usage.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from seshat.query.engine import QueryEngine


class EvalError(Exception):
    pass


@dataclass
class EvalCase:
    question: str
    expect_sessions: list[int] = field(default_factory=list)
    expect_keywords: list[str] = field(default_factory=list)


@dataclass
class CaseResult:
    case: EvalCase
    cited_sessions: list[int]
    citation_ok: bool | None  # None when the case has no session expectation
    answer_ok: bool | None  # None in retrieval-only mode or no keyword expectation
    answer_text: str | None = None


@dataclass
class EvalReport:
    results: list[CaseResult]

    def _rate(self, values: list[bool]) -> float | None:
        return sum(values) / len(values) if values else None

    @property
    def citation_accuracy(self) -> float | None:
        return self._rate([r.citation_ok for r in self.results if r.citation_ok is not None])

    @property
    def answer_accuracy(self) -> float | None:
        return self._rate([r.answer_ok for r in self.results if r.answer_ok is not None])

    def to_dict(self) -> dict:
        return {
            "citation_accuracy": self.citation_accuracy,
            "answer_accuracy": self.answer_accuracy,
            "cases": [
                {
                    "question": r.case.question,
                    "expect_sessions": r.case.expect_sessions,
                    "cited_sessions": r.cited_sessions,
                    "citation_ok": r.citation_ok,
                    "expect_keywords": r.case.expect_keywords,
                    "answer_ok": r.answer_ok,
                    "answer_text": r.answer_text,
                }
                for r in self.results
            ],
        }


def load_cases(path: Path) -> list[EvalCase]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvalError(f"Could not read questions file {path}: {exc}") from exc
    if not isinstance(raw, list) or not raw:
        raise EvalError(f"{path} must contain a non-empty JSON list of cases.")
    cases = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict) or not str(item.get("question", "")).strip():
            raise EvalError(f"{path}: case {i} needs a non-empty 'question'.")
        cases.append(
            EvalCase(
                question=item["question"],
                expect_sessions=[int(s) for s in item.get("expect_sessions", [])],
                expect_keywords=[str(k) for k in item.get("expect_keywords", [])],
            )
        )
    return cases


def run_eval(
    engine: QueryEngine,
    cases: list[EvalCase],
    k: int = 5,
    retrieval_only: bool = False,
) -> EvalReport:
    results = []
    for case in cases:
        citations, _ = engine.retrieve(case.question, k=k)
        cited = [c.session.id for c in citations]
        citation_ok = (
            any(s in cited for s in case.expect_sessions) if case.expect_sessions else None
        )
        answer_ok, answer_text = None, None
        if not retrieval_only:
            answer = engine.ask(case.question, k=k, record=False)
            answer_text = answer.text
            if case.expect_keywords:
                answer_ok = all(
                    kw.lower() in answer.text.lower() for kw in case.expect_keywords
                )
        results.append(
            CaseResult(
                case=case,
                cited_sessions=cited,
                citation_ok=citation_ok,
                answer_ok=answer_ok,
                answer_text=answer_text,
            )
        )
    return EvalReport(results=results)
