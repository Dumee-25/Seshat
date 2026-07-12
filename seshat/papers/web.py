"""Link ingestion: fetch a URL, extract its main text, and index it like a paper.

This is the one genuinely new source in the cockpit. It reuses the paper
chunking and embedding path wholesale — a link becomes a `papers` row whose
`path` is the URL and whose `meta.source` is "url" — so time-proximity
linking, vector search, and the timeline all treat it like any other reading.

Extraction is deliberately simple (strip scripts/nav/chrome, keep text). It
will not be perfect on every site; it is good enough for arxiv pages, blog
posts, and docs, and improves from real use. Fetching is injectable so the
whole flow is testable offline.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from collections.abc import Callable
from html.parser import HTMLParser

from seshat.papers.ingest import PaperIngestError, chunk_text
from seshat.store.db import Store, utcnow
from seshat.store.vectors import VectorStore

USER_AGENT = "Mozilla/5.0 (compatible; Seshat/0.1; +local research tool)"
MAX_HTML_BYTES = 5 * 1024 * 1024


class _MainText(HTMLParser):
    """Collects visible text, dropping scripts, styles, and page chrome."""

    SKIP = {"script", "style", "noscript", "nav", "header", "footer", "aside", "form"}

    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self._parts: list[str] = []
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip_depth:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif self._skip_depth == 0:
            text = data.strip()
            if text:
                self._parts.append(text)

    def text(self) -> str:
        return "\n".join(self._parts)


def extract_html(html: str, url: str) -> tuple[str, str]:
    parser = _MainText()
    parser.feed(html)
    title = parser.title.strip() or url
    return title, parser.text()


def fetch_url(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read(MAX_HTML_BYTES)
            charset = response.headers.get_content_charset() or "utf-8"
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise PaperIngestError(f"Could not fetch {url}: {exc}") from exc
    return raw.decode(charset, errors="replace")


def ingest_url(
    store: Store,
    vectors: VectorStore,
    url: str,
    added_at: str | None = None,
    fetch: Callable[[str], str] = fetch_url,
) -> int | None:
    """Ingest a URL as a link. Returns the paper id, or None if already
    ingested or empty."""
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        raise PaperIngestError("Links must be an http(s) URL.")
    if store.paper_by_path(url) is not None:
        return None
    title, text = extract_html(fetch(url), url)
    chunks = chunk_text(text)
    if not chunks:
        raise PaperIngestError(f"No readable text found at {url}.")
    paper_id = store.add_paper(
        url, title=title, meta={"source": "url", "url": url},
        added_at=added_at or utcnow(),
    )
    store.set_paper_content(paper_id, text)
    vectors.add(
        "papers",
        ids=[f"p{paper_id}c{i}" for i in range(len(chunks))],
        texts=chunks,
        metadatas=[
            {"paper_id": paper_id, "chunk": i, "path": url, "title": title,
             "source": "url"}
            for i in range(len(chunks))
        ],
    )
    return paper_id
