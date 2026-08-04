from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from seshat.api.app import create_app
from seshat.config import load_config, write_default_config
from seshat.store.db import Store


@pytest.fixture
def env(tmp_path: Path):
    write_default_config(tmp_path)
    config = load_config(tmp_path)
    store = Store.open(tmp_path)
    pid = store.add_paper(
        "papers/smote.pdf", title="SMOTE paper", meta={"source": "pdf"},
        added_at="2026-02-28T12:00:00+00:00",
    )
    store.set_paper_content(pid, "full text of the smote paper about oversampling")

    # A fake link ingestor stands in for the real (Ollama-backed) one.
    def fake_ingestor(url: str) -> int:
        return store.add_paper(url, title="A blog post", meta={"source": "url", "url": url})

    api = TestClient(create_app(tmp_path, config, link_ingestor=fake_ingestor))
    yield api, store, pid
    store.close()


def test_list_papers(env):
    api, _, pid = env
    papers = api.get("/api/papers").json()["papers"]
    assert len(papers) == 1
    assert papers[0]["id"] == pid
    assert papers[0]["source"] == "pdf"


def test_paper_reader_returns_content(env):
    api, _, pid = env
    body = api.get(f"/api/papers/{pid}").json()
    assert body["title"] == "SMOTE paper"
    assert "oversampling" in body["content"]


def test_paper_reader_404(env):
    api, _, _ = env
    assert api.get("/api/papers/9999").status_code == 404


def test_add_link(env):
    api, store, _ = env
    r = api.post("/api/links", json={"url": "https://example.com/post"})
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "url"
    assert body["path"] == "https://example.com/post"
    # It now shows up in the list alongside the PDF.
    assert len(api.get("/api/papers").json()["papers"]) == 2


def test_add_link_conflict_maps_to_409(tmp_path: Path):
    write_default_config(tmp_path)
    config = load_config(tmp_path)
    # An ingestor returning None means "already added".
    api = TestClient(create_app(tmp_path, config, link_ingestor=lambda url: None))
    assert api.post("/api/links", json={"url": "https://x.com"}).status_code == 409


# -- opening a link outside the window ----------------------------------------


def opener_client(tmp_path: Path):
    """A client whose 'system browser' just records what it was handed."""
    write_default_config(tmp_path)
    config = load_config(tmp_path)
    opened: list[str] = []
    api = TestClient(create_app(tmp_path, config, open_url=opened.append))
    return api, opened


def test_open_external_hands_the_url_to_the_browser(tmp_path: Path):
    api, opened = opener_client(tmp_path)
    r = api.post("/api/open-external", json={"url": "https://arxiv.org/abs/1106.1813"})
    assert r.status_code == 200
    assert opened == ["https://arxiv.org/abs/1106.1813"]


def test_open_external_allows_plain_http(tmp_path: Path):
    api, opened = opener_client(tmp_path)
    assert api.post("/api/open-external", json={"url": "http://localhost:9/x"}).status_code == 200
    assert opened == ["http://localhost:9/x"]


@pytest.mark.parametrize(
    "url",
    [
        "file:///C:/Windows/System32/calc.exe",
        "javascript:alert(1)",
        "mailto:someone@example.com",
        "not-a-url-at-all",
    ],
)
def test_open_external_refuses_non_http_schemes(tmp_path: Path, url: str):
    """The body reaches this from rendered page content, so only http(s) passes."""
    api, opened = opener_client(tmp_path)
    r = api.post("/api/open-external", json={"url": url})
    assert r.status_code == 400
    assert opened == []


def test_add_link_bad_url_maps_to_400(tmp_path: Path):
    from seshat.papers.ingest import PaperIngestError

    write_default_config(tmp_path)
    config = load_config(tmp_path)

    def bad(url):
        raise PaperIngestError("Links must be an http(s) URL.")

    api = TestClient(create_app(tmp_path, config, link_ingestor=bad))
    r = api.post("/api/links", json={"url": "ftp://nope"})
    assert r.status_code == 400
    assert "http" in r.json()["detail"]
