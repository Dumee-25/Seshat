"""PDF ingestion: watched papers folder -> extract -> chunk -> embed.

Papers land in the same vector store as journal entries (separate
collection), so session work and reading history are searchable together.
`added_at` comes from the file's mtime, not ingestion time — a PDF that sat
in the folder for a month before `seshat watch` first ran shouldn't look
freshly read to the time-proximity linker.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from seshat.store.db import Store
from seshat.store.vectors import VectorStore

CHUNK_CHARS = 1500
CHUNK_OVERLAP = 200
MAX_CHUNKS = 200  # ~300k chars; beyond that it's a book, not a paper


class PaperIngestError(Exception):
    pass


def extract_pdf(path: Path) -> tuple[str, str]:
    """Return (title, full text) for a PDF."""
    import pymupdf  # deferred: import is not free and most calls never ingest

    try:
        with pymupdf.open(path) as doc:
            text = "\n".join(page.get_text() for page in doc)
            title = (doc.metadata or {}).get("title") or ""
    except Exception as exc:
        raise PaperIngestError(f"Could not read {path.name}: {exc}") from exc
    if not title.strip():
        first_lines = [line.strip() for line in text.splitlines() if line.strip()]
        title = first_lines[0][:200] if first_lines else path.stem
    return title.strip(), text


def chunk_text(text: str, size: int = CHUNK_CHARS, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Overlapping character chunks, preferring paragraph boundaries."""
    text = text.strip()
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text) and len(chunks) < MAX_CHUNKS:
        end = min(start + size, len(text))
        if end < len(text):
            # Cut at the last paragraph (or line) break inside the window.
            window = text[start:end]
            cut = max(window.rfind("\n\n"), window.rfind("\n"))
            if cut > size // 2:
                end = start + cut
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


def ingest_pdf(
    store: Store,
    vectors: VectorStore,
    path: Path,
    rel_path: str,
    added_at: str | None = None,
) -> int | None:
    """Ingest one PDF. Returns the paper id, or None if already ingested/empty."""
    if store.paper_by_path(rel_path) is not None:
        return None
    title, text = extract_pdf(path)
    chunks = chunk_text(text)
    if not chunks:
        return None
    if added_at is None:
        added_at = datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(
            timespec="seconds"
        )
    paper_id = store.add_paper(
        rel_path, title=title, meta={"source": "pdf"}, added_at=added_at
    )
    store.set_paper_content(paper_id, text)
    vectors.add(
        "papers",
        ids=[f"p{paper_id}c{i}" for i in range(len(chunks))],
        texts=chunks,
        metadatas=[
            {"paper_id": paper_id, "chunk": i, "path": rel_path, "title": title}
            for i in range(len(chunks))
        ],
    )
    return paper_id
