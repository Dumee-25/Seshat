"""PDF ingestion: watched papers folder -> extract -> chunk -> embed.

Papers land in the same vector store as journal entries (separate
collection), so session work and reading history are searchable together.
`added_at` comes from the file's mtime, not ingestion time — a PDF that sat
in the folder for a month before `seshat watch` first ran shouldn't look
freshly read to the time-proximity linker.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from seshat.store.db import Store
from seshat.store.vectors import VectorStore

CHUNK_CHARS = 1500
CHUNK_OVERLAP = 200
MAX_CHUNKS = 200  # ~300k chars; beyond that it's a book, not a paper
MAX_TITLE_CHARS = 200
TITLE_FONT_SIZES = 6  # distinct sizes to try on page 1 before giving up

# Metadata titles are frequently the typesetter's leftovers rather than the
# paper's name: "Microsoft Word - S2 Text.docx", "HDBMR_2420948 1..16".
_TITLE_JUNK = re.compile(
    r"^microsoft\s+word\s*-|\.(docx?|pdf|tex|indd|qxd)$|\d+\.\.\d+", re.IGNORECASE
)
# Journals often set the article type in the same style as the title.
_ARTICLE_LABEL = re.compile(
    r"^(research|review|original|short)\s+(article|communication|paper|report)\s+",
    re.IGNORECASE,
)


class PaperIngestError(Exception):
    pass


def _plausible_title(text: str) -> bool:
    """Whether a candidate reads like a paper's name rather than page furniture.

    The rejects are the ones that actually turn up: a decorative journal
    initial ("G"), a masthead ("diagnostics", "SLJM"), a bare page number,
    and filename-shaped metadata.
    """
    text = text.strip()
    if len(text) < 12 or len(text.split()) < 2:
        return False
    if _TITLE_JUNK.search(text):
        return False
    # Mostly letters — rules out running heads like "IJID Regions 13 (2024) 100436".
    return sum(c.isalpha() for c in text) >= len(text) * 0.5


def _font_title_candidates(page) -> list[str]:
    """Page-1 text grouped by font size, largest first.

    A paper's title is nearly always the biggest thing on the first page, but
    not always *the* biggest — a journal masthead can outrank it — so this
    offers each size in turn and lets the caller take the first plausible one.
    """
    spans = []
    for block in page.get_text("dict").get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                content = span.get("text", "").strip()
                if content:
                    spans.append((round(span.get("size", 0.0), 1), span["bbox"][1], content))
    candidates = []
    for size in sorted({s[0] for s in spans}, reverse=True)[:TITLE_FONT_SIZES]:
        # Same visual size, read top-to-bottom: a title wrapped over two lines
        # comes back whole rather than cut off at the first one.
        group = sorted((s for s in spans if abs(s[0] - size) < 0.6), key=lambda s: s[1])
        candidates.append(re.sub(r"\s+", " ", " ".join(c for _, _, c in group)).strip())
    return candidates


def _clean_title(text: str) -> str:
    return _ARTICLE_LABEL.sub("", text.strip())[:MAX_TITLE_CHARS].strip()


def _derive_title(doc, text: str, stem: str) -> str:
    """Best available title: usable metadata, else the page-1 typography."""
    metadata = ((doc.metadata or {}).get("title") or "").strip()
    if _plausible_title(metadata):
        return _clean_title(metadata)

    if doc.page_count:
        try:
            for candidate in _font_title_candidates(doc[0]):
                if _plausible_title(candidate):
                    return _clean_title(candidate)
        except Exception:
            pass  # malformed page structure: fall through to the raw text

    for line in text.splitlines():
        if _plausible_title(line):
            return _clean_title(line)
    # Nothing convincing anywhere; the filename beats a stray glyph.
    return (metadata or stem)[:MAX_TITLE_CHARS].strip() or stem


def extract_pdf(path: Path) -> tuple[str, str]:
    """Return (title, full text) for a PDF."""
    import pymupdf  # deferred: import is not free and most calls never ingest

    try:
        with pymupdf.open(path) as doc:
            text = "\n".join(page.get_text() for page in doc)
            title = _derive_title(doc, text, path.stem)
    except Exception as exc:
        raise PaperIngestError(f"Could not read {path.name}: {exc}") from exc
    return title, text


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
