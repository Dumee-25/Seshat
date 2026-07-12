"""SQLite store: immutable raw events, sessions, journal entries, and graph edges.

All Seshat state lives under <project root>/.seshat/, which is gitignored by
`seshat init` defaults.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType

from seshat.store.schema import (
    MIGRATIONS,
    Artifact,
    ChatMessage,
    Edge,
    JournalEntry,
    Paper,
    RawEvent,
    Session,
)

STATE_DIR = ".seshat"
DB_FILENAME = "seshat.sqlite3"


def utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class StoreError(Exception):
    """Raised for invalid store operations."""


class Store:
    """Handle to a project's SQLite database. Use `Store.open(project_root)`."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    @classmethod
    def open(cls, root: Path) -> Store:
        state_dir = root / STATE_DIR
        state_dir.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: the watch service may run its processing
        # loop on a thread other than the one that opened the store. All
        # writes still happen on a single thread at a time.
        # timeout=15: the post-commit hook writes from a separate process
        # while `seshat watch` holds the database.
        conn = sqlite3.connect(
            state_dir / DB_FILENAME, check_same_thread=False, timeout=15
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")  # concurrent hook + daemon writers
        conn.execute("PRAGMA foreign_keys = ON")
        store = cls(conn)
        store._migrate()
        return store

    @classmethod
    def in_memory(cls) -> Store:
        """An ephemeral store, for tests."""
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        store = cls(conn)
        store._migrate()
        return store

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Store:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    # -- migrations ---------------------------------------------------------

    def _migrate(self) -> None:
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_version "
            "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        row = self._conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
        current = row["v"] or 0
        for version, ddl in enumerate(MIGRATIONS[current:], start=current + 1):
            self._conn.executescript(ddl)
            self._conn.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                (version, utcnow()),
            )
        self._conn.commit()

    def schema_version(self) -> int:
        row = self._conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
        return row["v"] or 0

    # -- raw events (append-only) -------------------------------------------

    def append_event(
        self,
        kind: str,
        payload: dict,
        path: str | None = None,
        ts: str | None = None,
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO raw_events (ts, kind, path, payload) VALUES (?, ?, ?, ?)",
            (ts or utcnow(), kind, path, json.dumps(payload)),
        )
        self._conn.commit()
        return cur.lastrowid

    def events(
        self,
        session_id: int | None = None,
        kind: str | None = None,
        ungrouped: bool = False,
    ) -> list[RawEvent]:
        clauses, params = [], []
        if session_id is not None:
            clauses.append("session_id = ?")
            params.append(session_id)
        if kind is not None:
            clauses.append("kind = ?")
            params.append(kind)
        if ungrouped:
            clauses.append("session_id IS NULL")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._conn.execute(
            f"SELECT * FROM raw_events {where} ORDER BY ts, id", params
        ).fetchall()
        return [
            RawEvent(
                id=r["id"],
                ts=r["ts"],
                kind=r["kind"],
                path=r["path"],
                payload=json.loads(r["payload"]),
                session_id=r["session_id"],
            )
            for r in rows
        ]

    # -- sessions -------------------------------------------------------------

    def create_session(self, started_at: str | None = None) -> int:
        cur = self._conn.execute(
            "INSERT INTO sessions (started_at) VALUES (?)", (started_at or utcnow(),)
        )
        self._conn.commit()
        return cur.lastrowid

    def close_session(self, session_id: int, ended_at: str | None = None) -> None:
        cur = self._conn.execute(
            "UPDATE sessions SET ended_at = ?, status = 'closed' "
            "WHERE id = ? AND status = 'open'",
            (ended_at or utcnow(), session_id),
        )
        if cur.rowcount == 0:
            raise StoreError(f"No open session with id {session_id}.")
        self._conn.commit()

    def mark_session_processed(self, session_id: int) -> None:
        cur = self._conn.execute(
            "UPDATE sessions SET status = 'processed' WHERE id = ? AND status = 'closed'",
            (session_id,),
        )
        if cur.rowcount == 0:
            raise StoreError(f"No closed session with id {session_id}.")
        self._conn.commit()

    def get_session(self, session_id: int) -> Session:
        row = self._conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if row is None:
            raise StoreError(f"No session with id {session_id}.")
        return Session(
            id=row["id"],
            started_at=row["started_at"],
            ended_at=row["ended_at"],
            status=row["status"],
        )

    def sessions(self, status: str | None = None) -> list[Session]:
        where, params = ("WHERE status = ?", [status]) if status else ("", [])
        rows = self._conn.execute(
            f"SELECT * FROM sessions {where} ORDER BY started_at, id", params
        ).fetchall()
        return [
            Session(
                id=r["id"],
                started_at=r["started_at"],
                ended_at=r["ended_at"],
                status=r["status"],
            )
            for r in rows
        ]

    def assign_events_to_session(self, event_ids: list[int], session_id: int) -> None:
        self.get_session(session_id)  # raises if missing
        self._conn.executemany(
            "UPDATE raw_events SET session_id = ? WHERE id = ?",
            [(session_id, event_id) for event_id in event_ids],
        )
        self._conn.commit()

    # -- journal entries -------------------------------------------------------

    def add_entry(self, entry: JournalEntry) -> int:
        cur = self._conn.execute(
            """
            INSERT INTO entries (
                session_id, what_changed, observable_outcome,
                inferred_intent, intent_confidence, intent_status,
                files_touched, raw_event_ids,
                model_version, prompt_version, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry.session_id,
                entry.what_changed,
                entry.observable_outcome,
                entry.inferred_intent,
                entry.intent_confidence,
                entry.intent_status,
                json.dumps(entry.files_touched),
                json.dumps(entry.raw_event_ids),
                entry.model_version,
                entry.prompt_version,
                entry.created_at or utcnow(),
            ),
        )
        self._conn.commit()
        return cur.lastrowid

    def get_entry(self, entry_id: int) -> JournalEntry:
        row = self._conn.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
        if row is None:
            raise StoreError(f"No entry with id {entry_id}.")
        return self._entry_from_row(row)

    def entries(self, session_id: int | None = None) -> list[JournalEntry]:
        where, params = ("WHERE session_id = ?", [session_id]) if session_id else ("", [])
        rows = self._conn.execute(
            f"SELECT * FROM entries {where} ORDER BY created_at, id", params
        ).fetchall()
        return [self._entry_from_row(r) for r in rows]

    def delete_entries(self, session_id: int) -> int:
        """Remove a session's entries (reprocess replaces them). Raw events stay."""
        cur = self._conn.execute("DELETE FROM entries WHERE session_id = ?", (session_id,))
        self._conn.commit()
        return cur.rowcount

    def set_intent(self, entry_id: int, intent: str, status: str = "corrected") -> None:
        """The one-click correction path: user fixes an inferred intent."""
        if status not in ("confirmed", "corrected"):
            raise StoreError(f"Intent status must be 'confirmed' or 'corrected', got {status!r}.")
        cur = self._conn.execute(
            "UPDATE entries SET inferred_intent = ?, intent_status = ? WHERE id = ?",
            (intent, status, entry_id),
        )
        if cur.rowcount == 0:
            raise StoreError(f"No entry with id {entry_id}.")
        self._conn.commit()

    @staticmethod
    def _entry_from_row(row: sqlite3.Row) -> JournalEntry:
        return JournalEntry(
            id=row["id"],
            session_id=row["session_id"],
            what_changed=row["what_changed"],
            observable_outcome=row["observable_outcome"],
            inferred_intent=row["inferred_intent"],
            intent_confidence=row["intent_confidence"],
            intent_status=row["intent_status"],
            files_touched=json.loads(row["files_touched"]),
            raw_event_ids=json.loads(row["raw_event_ids"]),
            model_version=row["model_version"],
            prompt_version=row["prompt_version"],
            created_at=row["created_at"],
        )

    # -- snapshots (latest indexed version of each watched file) ---------------

    def get_snapshot(self, path: str) -> str | None:
        row = self._conn.execute(
            "SELECT content FROM snapshots WHERE path = ?", (path,)
        ).fetchone()
        return row["content"] if row else None

    def set_snapshot(self, path: str, content: str) -> None:
        self._conn.execute(
            "INSERT INTO snapshots (path, content, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(path) DO UPDATE SET content = excluded.content, "
            "updated_at = excluded.updated_at",
            (path, content, utcnow()),
        )
        self._conn.commit()

    # -- chat history -------------------------------------------------------------

    def add_chat_message(
        self, role: str, text: str, session_ids: list[int] | None = None
    ) -> int:
        if role not in ("user", "assistant"):
            raise StoreError(f"Chat role must be 'user' or 'assistant', got {role!r}.")
        cur = self._conn.execute(
            "INSERT INTO chat_messages (ts, role, text, session_ids) VALUES (?, ?, ?, ?)",
            (utcnow(), role, text, json.dumps(session_ids or [])),
        )
        self._conn.commit()
        return cur.lastrowid

    def chat_history(self) -> list[ChatMessage]:
        """Messages of the current (uncleared) conversation, oldest first."""
        rows = self._conn.execute(
            "SELECT * FROM chat_messages WHERE cleared = 0 ORDER BY id"
        ).fetchall()
        return [
            ChatMessage(
                id=r["id"],
                ts=r["ts"],
                role=r["role"],
                text=r["text"],
                session_ids=json.loads(r["session_ids"]),
            )
            for r in rows
        ]

    def clear_chat(self) -> int:
        """Start a fresh conversation. Messages are hidden, not deleted."""
        cur = self._conn.execute("UPDATE chat_messages SET cleared = 1 WHERE cleared = 0")
        self._conn.commit()
        return cur.rowcount

    # -- query log (dogfooding metric) ------------------------------------------

    def log_query(self, question: str, ts: str | None = None) -> None:
        self._conn.execute(
            "INSERT INTO query_log (ts, question) VALUES (?, ?)", (ts or utcnow(), question)
        )
        self._conn.commit()

    def query_log(self) -> list[tuple[str, str]]:
        rows = self._conn.execute("SELECT ts, question FROM query_log ORDER BY ts").fetchall()
        return [(r["ts"], r["question"]) for r in rows]

    # -- artifacts, papers, edges ---------------------------------------------

    def add_artifact(self, path: str, kind: str, meta: dict | None = None) -> int:
        cur = self._conn.execute(
            "INSERT INTO artifacts (path, kind, created_at, meta) VALUES (?, ?, ?, ?)",
            (path, kind, utcnow(), json.dumps(meta or {})),
        )
        self._conn.commit()
        return cur.lastrowid

    def artifacts(self) -> list[Artifact]:
        rows = self._conn.execute(
            "SELECT * FROM artifacts ORDER BY created_at, id"
        ).fetchall()
        return [
            Artifact(
                id=r["id"],
                path=r["path"],
                kind=r["kind"],
                created_at=r["created_at"],
                meta=json.loads(r["meta"]),
            )
            for r in rows
        ]

    def get_artifact(self, artifact_id: int) -> Artifact | None:
        row = self._conn.execute(
            "SELECT * FROM artifacts WHERE id = ?", (artifact_id,)
        ).fetchone()
        if row is None:
            return None
        return Artifact(
            id=row["id"], path=row["path"], kind=row["kind"],
            created_at=row["created_at"], meta=json.loads(row["meta"]),
        )

    def artifact_id_for_path(self, path: str) -> int | None:
        row = self._conn.execute(
            "SELECT id FROM artifacts WHERE path = ? ORDER BY id DESC LIMIT 1", (path,)
        ).fetchone()
        return row["id"] if row else None

    def add_paper(
        self,
        path: str,
        title: str | None = None,
        meta: dict | None = None,
        added_at: str | None = None,
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO papers (path, title, added_at, meta) VALUES (?, ?, ?, ?)",
            (path, title, added_at or utcnow(), json.dumps(meta or {})),
        )
        self._conn.commit()
        return cur.lastrowid

    def paper_by_path(self, path: str) -> Paper | None:
        row = self._conn.execute("SELECT * FROM papers WHERE path = ?", (path,)).fetchone()
        return self._paper_from_row(row) if row else None

    def papers(self) -> list[Paper]:
        rows = self._conn.execute("SELECT * FROM papers ORDER BY added_at, id").fetchall()
        return [self._paper_from_row(r) for r in rows]

    def get_paper(self, paper_id: int) -> Paper | None:
        row = self._conn.execute("SELECT * FROM papers WHERE id = ?", (paper_id,)).fetchone()
        return self._paper_from_row(row) if row else None

    def set_paper_content(self, paper_id: int, text: str) -> None:
        self._conn.execute(
            "INSERT INTO paper_content (paper_id, text) VALUES (?, ?) "
            "ON CONFLICT(paper_id) DO UPDATE SET text = excluded.text",
            (paper_id, text),
        )
        self._conn.commit()

    def get_paper_content(self, paper_id: int) -> str | None:
        row = self._conn.execute(
            "SELECT text FROM paper_content WHERE paper_id = ?", (paper_id,)
        ).fetchone()
        return row["text"] if row else None

    @staticmethod
    def _paper_from_row(row: sqlite3.Row) -> Paper:
        return Paper(
            id=row["id"], path=row["path"], title=row["title"],
            added_at=row["added_at"], meta=json.loads(row["meta"]),
        )

    def add_edge(
        self,
        src_type: str,
        src_id: int,
        dst_type: str,
        dst_id: int,
        kind: str,
        confidence: float | None = None,
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO edges (src_type, src_id, dst_type, dst_id, kind, confidence, "
            "created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (src_type, src_id, dst_type, dst_id, kind, confidence, utcnow()),
        )
        self._conn.commit()
        return cur.lastrowid

    def edges(
        self,
        src: tuple[str, int] | None = None,
        dst: tuple[str, int] | None = None,
        kind: str | None = None,
    ) -> list[Edge]:
        clauses, params = [], []
        if src is not None:
            clauses.append("src_type = ? AND src_id = ?")
            params.extend(src)
        if dst is not None:
            clauses.append("dst_type = ? AND dst_id = ?")
            params.extend(dst)
        if kind is not None:
            clauses.append("kind = ?")
            params.append(kind)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._conn.execute(f"SELECT * FROM edges {where} ORDER BY id", params).fetchall()
        return [
            Edge(
                id=r["id"],
                src_type=r["src_type"],
                src_id=r["src_id"],
                dst_type=r["dst_type"],
                dst_id=r["dst_id"],
                kind=r["kind"],
                confidence=r["confidence"],
                created_at=r["created_at"],
            )
            for r in rows
        ]
