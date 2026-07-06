"""Vector store tests using a deterministic bag-of-words embedder.

The real bge-small-en-v1.5 model is exercised only when SESHAT_REAL_EMBEDDINGS=1
(it downloads ~130 MB on first run); CI uses the fake embedder to stay fast.
"""

import math
import os
from pathlib import Path

import pytest

from seshat.store.vectors import VectorStore, VectorStoreError

DIMS = 64


def fake_embedder(texts: list[str]) -> list[list[float]]:
    vectors = []
    for text in texts:
        vec = [0.0] * DIMS
        for token in text.lower().split():
            vec[hash(token) % DIMS] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        vectors.append([v / norm for v in vec])
    return vectors


@pytest.fixture
def vs(tmp_path: Path) -> VectorStore:
    return VectorStore(tmp_path, embedder=fake_embedder)


DOCS = {
    "e1": "added SMOTE oversampling to handle class imbalance",
    "e2": "tuned xgboost learning rate and max depth",
    "e3": "dropped region_code column in preprocessing",
}


def test_add_and_query_returns_most_relevant(vs: VectorStore):
    vs.add("entries", list(DOCS), list(DOCS.values()), [{"session_id": i} for i in (1, 2, 3)])
    hits = vs.query("entries", "have I tried SMOTE oversampling before")
    assert hits[0].id == "e1"
    assert hits[0].metadata["session_id"] == 1
    assert hits[0].distance <= hits[-1].distance


def test_query_with_metadata_filter(vs: VectorStore):
    vs.add("entries", list(DOCS), list(DOCS.values()), [{"session_id": i} for i in (1, 2, 3)])
    hits = vs.query("entries", "SMOTE oversampling", where={"session_id": 2})
    assert [h.id for h in hits] == ["e2"]


def test_query_empty_collection_returns_no_hits(vs: VectorStore):
    assert vs.query("entries", "anything") == []


def test_upsert_replaces_document(vs: VectorStore):
    vs.add("entries", ["e1"], ["first version"])
    vs.add("entries", ["e1"], ["second version"])
    assert vs.count("entries") == 1
    assert vs.query("entries", "version")[0].text == "second version"


def test_collections_are_isolated(vs: VectorStore):
    vs.add("entries", ["e1"], ["smote oversampling session"])
    vs.add("papers", ["p1"], ["smote paper chunk"])
    assert [h.id for h in vs.query("papers", "smote")] == ["p1"]


def test_unknown_collection_rejected(vs: VectorStore):
    with pytest.raises(VectorStoreError, match="Unknown collection"):
        vs.add("nope", ["x"], ["y"])


def test_persists_across_reopen(tmp_path: Path):
    VectorStore(tmp_path, embedder=fake_embedder).add(
        "entries", list(DOCS), list(DOCS.values())
    )
    reopened = VectorStore(tmp_path, embedder=fake_embedder)
    assert reopened.count("entries") == 3
    assert reopened.query("entries", "xgboost learning rate")[0].id == "e2"


@pytest.mark.skipif(
    os.environ.get("SESHAT_REAL_EMBEDDINGS") != "1",
    reason="set SESHAT_REAL_EMBEDDINGS=1 to test the real bge-small model",
)
def test_real_model_end_to_end(tmp_path: Path):
    vs = VectorStore(tmp_path)  # default SentenceTransformerEmbedder
    vs.add("entries", list(DOCS), list(DOCS.values()))
    hits = vs.query("entries", "have I tried resampling for imbalanced classes?")
    assert hits[0].id == "e1"
