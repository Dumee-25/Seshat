"""Hybrid retrieval + cited answers over the journal (Seshat.md §3, Layer 4).

Retrieval is vector search over journal entries and paper chunks, combined
with structured post-filters (date range, file path) resolved against SQLite.
Every answer carries the retrieved sessions as citations — trust never rests
on the LLM's word alone; the UI links each citation to the underlying diffs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from seshat.inference.prompts import build_answer_prompt
from seshat.inference.provider import LLMProvider
from seshat.store.db import Store, StoreError
from seshat.store.schema import JournalEntry, Session
from seshat.store.vectors import VectorStore

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)

NO_RESULTS_TEXT = (
    "No matching journal entries found. Either nothing relevant was captured, "
    "or sessions are still queued — run `seshat process` to generate entries."
)


@dataclass
class SessionCitation:
    session: Session
    entry: JournalEntry
    score: float  # cosine distance; lower is closer


@dataclass
class PaperCitation:
    paper_id: int
    title: str
    path: str
    snippet: str
    score: float


@dataclass
class Answer:
    text: str
    citations: list[SessionCitation] = field(default_factory=list)
    papers: list[PaperCitation] = field(default_factory=list)


class QueryEngine:
    def __init__(self, store: Store, vectors: VectorStore, provider: LLMProvider) -> None:
        self._store = store
        self._vectors = vectors
        self._provider = provider

    def retrieve(
        self,
        question: str,
        k: int = 5,
        file_filter: str | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> tuple[list[SessionCitation], list[PaperCitation]]:
        """Vector hits, then structured filters against the SQLite side."""
        citations: list[SessionCitation] = []
        for hit in self._vectors.query("entries", question, n_results=max(k * 3, 12)):
            try:
                entry = self._store.get_entry(int(hit.id))
                session = self._store.get_session(entry.session_id)
            except (StoreError, ValueError):
                continue  # stale vector (entry replaced); skip rather than crash
            if file_filter and not any(
                file_filter.lower() in f.lower() for f in entry.files_touched
            ):
                continue
            # All timestamps are UTC ISO strings, so string comparison is safe.
            if since and session.started_at < since:
                continue
            if until and session.started_at > until:
                continue
            citations.append(SessionCitation(session=session, entry=entry, score=hit.distance))
            if len(citations) >= k:
                break

        papers = [
            PaperCitation(
                paper_id=hit.metadata.get("paper_id", -1),
                title=hit.metadata.get("title", "?"),
                path=hit.metadata.get("path", "?"),
                snippet=hit.text[:600],
                score=hit.distance,
            )
            for hit in self._vectors.query("papers", question, n_results=3)
        ]
        return citations, papers

    def ask(
        self,
        question: str,
        k: int = 5,
        file_filter: str | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> Answer:
        citations, papers = self.retrieve(
            question, k=k, file_filter=file_filter, since=since, until=until
        )
        if not citations and not papers:
            return Answer(text=NO_RESULTS_TEXT)
        prompt = build_answer_prompt(
            question,
            entry_blocks=[_entry_block(c) for c in citations],
            paper_blocks=[_paper_block(p) for p in papers],
        )
        text = _THINK_RE.sub("", self._provider.generate(prompt)).strip()
        return Answer(text=text, citations=citations, papers=papers)


def _entry_block(citation: SessionCitation) -> str:
    entry, session = citation.entry, citation.session
    lines = [
        f"[session {session.id}] {session.started_at} .. {session.ended_at or '?'}"
        f" (files: {', '.join(entry.files_touched) or '-'})",
        f"what changed: {entry.what_changed}",
    ]
    if entry.observable_outcome:
        lines.append(f"observed outcome: {entry.observable_outcome}")
    if entry.inferred_intent:
        status = entry.intent_status
        confidence = (
            f", confidence {entry.intent_confidence:.1f}"
            if entry.intent_confidence is not None
            else ""
        )
        lines.append(f"intent ({status}{confidence}): {entry.inferred_intent}")
    return "\n".join(lines)


def _paper_block(paper: PaperCitation) -> str:
    return f'[paper {paper.paper_id}] "{paper.title}": {paper.snippet}'
