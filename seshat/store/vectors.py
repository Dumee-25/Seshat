"""Vector search over sqlite-vec, sharing the project's SQLite database.

Embeddings live in `vec0` virtual tables inside the same `.seshat/seshat.sqlite3`
as everything else — one file for the whole project, nothing else to ship or
back up. Embeddings themselves are produced by an injected embedder (Ollama by
default), so there is no torch/onnx dependency here; that is what lets Seshat
package as a self-contained desktop app.

The public interface (add/query/delete/count with the same Hit shape) is
unchanged from the previous ChromaDB implementation, so callers and tests did
not have to move.
"""

from __future__ import annotations

import json
import sqlite3
import struct
from collections.abc import Callable
from pathlib import Path

from seshat.store.db import DB_FILENAME, STATE_DIR

Embedder = Callable[[list[str]], list[list[float]]]

COLLECTIONS = ("entries", "papers")


class VectorStoreError(Exception):
    """Raised for embedding/vector-store problems."""


class Hit:
    __slots__ = ("id", "text", "metadata", "distance")

    def __init__(self, id: str, text: str, metadata: dict, distance: float) -> None:
        self.id = id
        self.text = text
        self.metadata = metadata
        self.distance = distance

    def __repr__(self) -> str:
        return f"Hit(id={self.id!r}, distance={self.distance:.4f})"


def _serialize(vector: list[float]) -> bytes:
    return struct.pack(f"{len(vector)}f", *vector)


def _matches(metadata: dict, where: dict) -> bool:
    """Replicates the subset of the Chroma `where` grammar Seshat used:
    equality (`{"session_id": 2}`) and membership (`{"paper_id": {"$in": [...]}}`)."""
    for key, condition in where.items():
        value = metadata.get(key)
        if isinstance(condition, dict):
            if "$in" in condition and value not in condition["$in"]:
                return False
        elif value != condition:
            return False
    return True


class VectorStore:
    """Vector collections for journal entries and paper chunks."""

    def __init__(self, root: Path, embedder: Embedder) -> None:
        self._embedder = embedder
        state_dir = root / STATE_DIR
        state_dir.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(state_dir / DB_FILENAME, timeout=15)
        try:
            import sqlite_vec
        except ImportError as exc:  # pragma: no cover - install-time guard
            raise VectorStoreError(
                "sqlite-vec is not installed. Reinstall Seshat, or `pip install sqlite-vec`."
            ) from exc
        try:
            self._conn.enable_load_extension(True)
            sqlite_vec.load(self._conn)
            self._conn.enable_load_extension(False)
        except (AttributeError, sqlite3.OperationalError) as exc:  # pragma: no cover
            raise VectorStoreError(
                "This Python's sqlite3 cannot load extensions, so vector search is "
                "unavailable. Use a python.org build or a conda Python."
            ) from exc
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS vec_meta (collection TEXT PRIMARY KEY, dim INTEGER)"
        )
        self._dims: dict[str, int] = {
            row[0]: row[1]
            for row in self._conn.execute("SELECT collection, dim FROM vec_meta")
        }

    def close(self) -> None:
        self._conn.close()

    def _table(self, collection: str) -> str:
        if collection not in COLLECTIONS:
            raise VectorStoreError(
                f"Unknown collection {collection!r}; expected one of {COLLECTIONS}."
            )
        return f"vec_{collection}"

    def _ensure_table(self, collection: str, dim: int) -> None:
        table = self._table(collection)
        if collection in self._dims:
            if self._dims[collection] != dim:
                raise VectorStoreError(
                    f"Embedding dimension for {collection!r} changed "
                    f"({self._dims[collection]} -> {dim}); the embedding model was "
                    "swapped. Delete the .seshat directory and re-run to reindex."
                )
            return
        self._conn.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS {table} USING vec0("
            f"id TEXT PRIMARY KEY, embedding float[{dim}] distance_metric=cosine, "
            f"+document TEXT, +metadata TEXT)"
        )
        self._conn.execute(
            "INSERT OR REPLACE INTO vec_meta (collection, dim) VALUES (?, ?)",
            (collection, dim),
        )
        self._conn.commit()
        self._dims[collection] = dim

    def add(
        self,
        collection: str,
        ids: list[str],
        texts: list[str],
        metadatas: list[dict] | None = None,
    ) -> None:
        self._table(collection)  # validate name early
        if not ids:
            return
        if len(ids) != len(texts):
            raise VectorStoreError("ids and texts must have the same length.")
        embeddings = self._embedder(texts)
        if not embeddings or not embeddings[0]:
            raise VectorStoreError("The embedder returned no vectors.")
        self._ensure_table(collection, len(embeddings[0]))
        table = self._table(collection)
        metadatas = metadatas or [{} for _ in ids]
        for id_, embedding, text, metadata in zip(
            ids, embeddings, texts, metadatas, strict=True
        ):
            # Upsert: vec0 has no ON CONFLICT, so delete-then-insert by id.
            self._conn.execute(f"DELETE FROM {table} WHERE id = ?", (id_,))
            self._conn.execute(
                f"INSERT INTO {table} (id, embedding, document, metadata) "
                "VALUES (?, ?, ?, ?)",
                (id_, _serialize(embedding), text, json.dumps(metadata or {})),
            )
        self._conn.commit()

    def query(
        self,
        collection: str,
        text: str,
        n_results: int = 5,
        where: dict | None = None,
    ) -> list[Hit]:
        self._table(collection)
        total = self.count(collection)
        if total == 0:
            return []
        table = self._table(collection)
        query_embedding = self._embedder([text])[0]
        # Over-fetch when filtering, since the metadata filter runs after KNN.
        k = min(total, n_results * 4 if where else n_results)
        rows = self._conn.execute(
            f"SELECT id, document, metadata, distance FROM {table} "
            f"WHERE embedding MATCH ? AND k = {int(k)} ORDER BY distance",
            (_serialize(query_embedding),),
        ).fetchall()
        hits = []
        for id_, document, metadata_json, distance in rows:
            metadata = json.loads(metadata_json) if metadata_json else {}
            if where and not _matches(metadata, where):
                continue
            hits.append(Hit(id=id_, text=document, metadata=metadata, distance=distance))
            if len(hits) >= n_results:
                break
        return hits

    def delete(self, collection: str, ids: list[str]) -> None:
        self._table(collection)
        if not ids or collection not in self._dims:
            return
        self._conn.executemany(
            f"DELETE FROM {self._table(collection)} WHERE id = ?", [(i,) for i in ids]
        )
        self._conn.commit()

    def count(self, collection: str) -> int:
        self._table(collection)
        if collection not in self._dims:
            return 0
        return self._conn.execute(
            f"SELECT count(*) FROM {self._table(collection)}"
        ).fetchone()[0]
