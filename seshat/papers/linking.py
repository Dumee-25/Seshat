"""Time-proximity linking between papers and sessions (Seshat.md §3, Layer 3).

MVP linking is deliberately weak: a paper added within ~7 days before a
session *might* have inspired it. Nearby papers' most relevant chunks (vector
search against the session's own diff text) are offered to the journal model
as optional context, and a low-confidence `time-proximity` edge is recorded.
Explicit citation edges and highlight tracking are post-MVP.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from seshat.store.db import Store
from seshat.store.schema import Paper, Session
from seshat.store.vectors import VectorStore

PROXIMITY_DAYS = 7
LINK_CONFIDENCE = 0.3
MAX_PAPERS = 3
MAX_CONTEXT_CHUNKS = 3
CHUNK_SNIPPET_CHARS = 600


def papers_near_session(store: Store, session: Session) -> list[Paper]:
    """Papers added in the window [session start - 7 days, session end]."""
    start = datetime.fromisoformat(session.started_at) - timedelta(days=PROXIMITY_DAYS)
    end = datetime.fromisoformat(session.ended_at or session.started_at)
    nearby = []
    for paper in store.papers():
        if paper.added_at is None:
            continue
        added = datetime.fromisoformat(paper.added_at)
        if start <= added <= end:
            nearby.append(paper)
    return nearby[:MAX_PAPERS]


def paper_context(
    store: Store,
    vectors: VectorStore,
    session: Session,
    query_text: str,
) -> tuple[list[Paper], str]:
    """(nearby papers, prompt context block). Empty context if no papers."""
    nearby = papers_near_session(store, session)
    if not nearby or not query_text.strip():
        return nearby, _titles_only(nearby)

    hits = vectors.query(
        "papers",
        query_text[:2000],
        n_results=MAX_CONTEXT_CHUNKS,
        where={"paper_id": {"$in": [p.id for p in nearby]}},
    )
    if not hits:
        return nearby, _titles_only(nearby)

    lines = []
    seen_titles = set()
    for hit in hits:
        title = hit.metadata.get("title", "?")
        seen_titles.add(title)
        lines.append(f'- from "{title}": {hit.text[:CHUNK_SNIPPET_CHARS]}')
    for paper in nearby:
        if (paper.title or "?") not in seen_titles:
            lines.append(f'- "{paper.title}" (no closely matching passage)')
    return nearby, "\n".join(lines)


def _titles_only(papers: list[Paper]) -> str:
    return "\n".join(f'- "{p.title}"' for p in papers)


def link_session_papers(store: Store, session_id: int, papers: list[Paper]) -> int:
    """Record low-confidence time-proximity edges; idempotent."""
    created = 0
    for paper in papers:
        existing = store.edges(
            src=("session", session_id), dst=("paper", paper.id), kind="time-proximity"
        )
        if not existing:
            store.add_edge(
                "session", session_id, "paper", paper.id,
                "time-proximity", LINK_CONFIDENCE,
            )
            created += 1
    return created
