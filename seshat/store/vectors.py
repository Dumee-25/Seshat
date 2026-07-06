"""ChromaDB wrapper with a pluggable embedding function.

The default embedder is bge-small-en-v1.5 via sentence-transformers on CPU
(install with `pip install seshat[embeddings]`), which keeps embeddings fully
local. The embedder is injectable so tests — and future providers — can swap
it without touching storage code. Embeddings are always computed by us and
passed to Chroma explicitly, so Chroma's own default embedding function (and
its model download) is never triggered.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from seshat.store.db import STATE_DIR

Embedder = Callable[[list[str]], list[list[float]]]

DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"
COLLECTIONS = ("entries", "papers")


class VectorStoreError(Exception):
    """Raised for embedding/vector-store problems."""


@dataclass
class Hit:
    id: str
    text: str
    metadata: dict
    distance: float


class SentenceTransformerEmbedder:
    """Default local embedder. Loads the model lazily on first use."""

    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        self._model_name = model_name
        self._model = None

    def __call__(self, texts: list[str]) -> list[list[float]]:
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise VectorStoreError(
                    "sentence-transformers is not installed. "
                    "Run `pip install seshat[embeddings]` for local embeddings, "
                    "or inject a custom embedder."
                ) from exc
            self._model = SentenceTransformer(self._model_name, device="cpu")
        return self._model.encode(texts, normalize_embeddings=True).tolist()


class VectorStore:
    """Vector collections for journal entries and paper chunks."""

    def __init__(self, root: Path, embedder: Embedder | None = None) -> None:
        import chromadb  # deferred: importing chromadb takes seconds
        from chromadb.config import Settings

        self._embedder: Embedder = embedder or SentenceTransformerEmbedder()
        self._client = chromadb.PersistentClient(
            path=str(root / STATE_DIR / "chroma"),
            # Local-first means nothing leaves the machine, including telemetry.
            settings=Settings(anonymized_telemetry=False),
        )
        self._collections = {
            name: self._client.get_or_create_collection(
                name, metadata={"hnsw:space": "cosine"}
            )
            for name in COLLECTIONS
        }

    def _collection(self, name: str):
        if name not in self._collections:
            raise VectorStoreError(
                f"Unknown collection {name!r}; expected one of {COLLECTIONS}."
            )
        return self._collections[name]

    def add(
        self,
        collection: str,
        ids: list[str],
        texts: list[str],
        metadatas: list[dict] | None = None,
    ) -> None:
        if not ids:
            return
        if len(ids) != len(texts):
            raise VectorStoreError("ids and texts must have the same length.")
        self._collection(collection).upsert(
            ids=ids,
            embeddings=self._embedder(texts),
            documents=texts,
            metadatas=metadatas,
        )

    def query(
        self,
        collection: str,
        text: str,
        n_results: int = 5,
        where: dict | None = None,
    ) -> list[Hit]:
        coll = self._collection(collection)
        if coll.count() == 0:
            return []
        result = coll.query(
            query_embeddings=self._embedder([text]),
            n_results=min(n_results, coll.count()),
            where=where,
        )
        return [
            Hit(id=i, text=doc, metadata=meta or {}, distance=dist)
            for i, doc, meta, dist in zip(
                result["ids"][0],
                result["documents"][0],
                result["metadatas"][0],
                result["distances"][0],
                strict=True,
            )
        ]

    def delete(self, collection: str, ids: list[str]) -> None:
        if ids:
            self._collection(collection).delete(ids=ids)

    def count(self, collection: str) -> int:
        return self._collection(collection).count()
