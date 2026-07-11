"""Phase A: embeddings via the provider, and the sqlite-vec dimension guard."""

from pathlib import Path

import pytest
from conftest import fake_embedder

from seshat.inference.provider import (
    GenerationError,
    OllamaProvider,
    OpenAICompatProvider,
    get_embedder,
)
from seshat.store.vectors import VectorStore, VectorStoreError


class FakeHTTP:
    """Captures the last request and returns a canned response, replacing the
    provider's urllib POST so no network is touched."""

    def __init__(self, response: dict) -> None:
        self.response = response
        self.url = None
        self.body = None

    def __call__(self, url, body, headers=None):
        self.url = url
        self.body = body
        return self.response


def test_ollama_embed_hits_embed_endpoint(monkeypatch):
    http = FakeHTTP({"embeddings": [[0.1, 0.2], [0.3, 0.4]]})
    monkeypatch.setattr("seshat.inference.provider._post_json", http)
    provider = OllamaProvider("qwen3:8b", embed_model="nomic-embed-text")
    vectors = provider.embed(["a", "b"])
    assert vectors == [[0.1, 0.2], [0.3, 0.4]]
    assert http.url.endswith("/api/embed")
    assert http.body["model"] == "nomic-embed-text"
    assert http.body["input"] == ["a", "b"]


def test_ollama_embed_missing_model_is_clear(monkeypatch):
    http = FakeHTTP({"error": "model not found"})
    monkeypatch.setattr("seshat.inference.provider._post_json", http)
    with pytest.raises(GenerationError, match="ollama pull nomic-embed-text"):
        OllamaProvider("qwen3:8b").embed(["x"])


def test_openai_embed_parses_data_list(monkeypatch):
    http = FakeHTTP({"data": [{"embedding": [1.0, 2.0]}, {"embedding": [3.0, 4.0]}]})
    monkeypatch.setattr("seshat.inference.provider._post_json", http)
    provider = OpenAICompatProvider("gpt", "http://api.local/v1", "key", "text-embed")
    assert provider.embed(["a", "b"]) == [[1.0, 2.0], [3.0, 4.0]]
    assert http.url.endswith("/embeddings")


def test_get_embedder_from_config(tmp_path: Path, monkeypatch):
    from seshat.config import load_config, write_default_config

    write_default_config(tmp_path)
    config = load_config(tmp_path)
    assert config.inference.embed_model == "nomic-embed-text"
    http = FakeHTTP({"embeddings": [[0.5, 0.5]]})
    monkeypatch.setattr("seshat.inference.provider._post_json", http)
    embedder = get_embedder(config)
    assert embedder(["hello"]) == [[0.5, 0.5]]


def test_dimension_mismatch_is_guarded(tmp_path: Path):
    """Swapping to an embedding model of a different width must fail loudly,
    not silently corrupt the index."""
    VectorStore(tmp_path, fake_embedder).add("entries", ["e1"], ["text"])  # 64-dim

    def wide_embedder(texts):
        return [[0.0] * 128 for _ in texts]

    vs = VectorStore(tmp_path, wide_embedder)
    with pytest.raises(VectorStoreError, match="dimension"):
        vs.add("entries", ["e2"], ["other"])


def test_paper_in_filter_survives_over_fetch(tmp_path: Path):
    """The `$in` metadata filter (used by paper linking) must still work now
    that filtering happens after KNN over-fetch."""
    vs = VectorStore(tmp_path, fake_embedder)
    docs = {f"p{i}": f"paper chunk about topic {i} smote oversampling" for i in range(6)}
    vs.add(
        "papers", list(docs), list(docs.values()),
        [{"paper_id": i} for i in range(6)],
    )
    hits = vs.query("papers", "smote oversampling", where={"paper_id": {"$in": [2, 4]}})
    assert all(h.metadata["paper_id"] in (2, 4) for h in hits)
    assert hits
