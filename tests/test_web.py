from pathlib import Path

import pytest
from conftest import fake_embedder

from seshat.papers.ingest import PaperIngestError
from seshat.papers.web import extract_html, ingest_url
from seshat.store.db import Store
from seshat.store.vectors import VectorStore

HTML = """
<html><head><title>SMOTE for Imbalanced Data</title>
<style>.x{color:red}</style></head>
<body>
<nav>home about</nav>
<script>console.log('ignore me')</script>
<h1>Synthetic Minority Oversampling</h1>
<p>We over-sample the minority class by creating synthetic examples, which
improves recall on imbalanced classification problems.</p>
<footer>copyright</footer>
</body></html>
"""


@pytest.fixture
def env(tmp_path: Path):
    store = Store.open(tmp_path)
    vectors = VectorStore(tmp_path, fake_embedder)
    yield store, vectors
    store.close()


def test_extract_drops_chrome_and_scripts():
    title, text = extract_html(HTML, "http://x")
    assert title == "SMOTE for Imbalanced Data"
    assert "synthetic examples" in text
    assert "console.log" not in text
    assert "copyright" not in text
    assert "home about" not in text


def test_ingest_url_creates_link_paper(env):
    store, vectors = env
    pid = ingest_url(store, vectors, "https://ex.com/smote", fetch=lambda url: HTML)
    paper = store.get_paper(pid)
    assert paper.path == "https://ex.com/smote"
    assert paper.meta["source"] == "url"
    assert paper.title == "SMOTE for Imbalanced Data"
    assert "synthetic examples" in store.get_paper_content(pid)
    assert vectors.count("papers") >= 1
    hits = vectors.query("papers", "minority oversampling")
    assert hits[0].metadata["source"] == "url"


def test_ingest_url_idempotent(env):
    store, vectors = env
    url = "https://ex.com/smote"
    assert ingest_url(store, vectors, url, fetch=lambda u: HTML) is not None
    assert ingest_url(store, vectors, url, fetch=lambda u: HTML) is None
    assert len(store.papers()) == 1


def test_ingest_url_rejects_non_http(env):
    store, vectors = env
    with pytest.raises(PaperIngestError, match="http"):
        ingest_url(store, vectors, "ftp://nope", fetch=lambda u: HTML)


def test_ingest_url_empty_content(env):
    store, vectors = env
    with pytest.raises(PaperIngestError, match="No readable text"):
        ingest_url(store, vectors, "https://ex.com/blank",
                   fetch=lambda u: "<html><body></body></html>")
