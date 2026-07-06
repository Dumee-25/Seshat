"""SQLite schema, migrations, and row dataclasses.

Raw events are append-only: entries can be regenerated from them at any time
(`seshat reprocess`), so events must never be mutated after capture. The only
column that may change on a raw event is `session_id`, which is assigned once
session grouping runs; SQL triggers enforce the rest.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Forward-only migrations. Never edit an entry in this list after it has
# shipped — append a new one. Index N applies schema version N+1.
MIGRATIONS: list[str] = [
    # v1: initial schema.
    """
    CREATE TABLE raw_events (
        id INTEGER PRIMARY KEY,
        ts TEXT NOT NULL,                 -- ISO 8601, UTC
        kind TEXT NOT NULL,               -- notebook_diff | script_change | result_file
                                          -- | git_commit | pdf_added
        path TEXT,                        -- project-relative file path, if any
        payload TEXT NOT NULL,            -- JSON: diff, outputs, metadata
        session_id INTEGER REFERENCES sessions(id)
    );

    CREATE TRIGGER raw_events_immutable
    BEFORE UPDATE OF ts, kind, path, payload ON raw_events
    BEGIN
        SELECT RAISE(ABORT, 'raw_events is append-only (only session_id may be set)');
    END;

    CREATE TRIGGER raw_events_no_delete
    BEFORE DELETE ON raw_events
    BEGIN
        SELECT RAISE(ABORT, 'raw_events is append-only');
    END;

    CREATE TABLE sessions (
        id INTEGER PRIMARY KEY,
        started_at TEXT NOT NULL,
        ended_at TEXT,
        status TEXT NOT NULL DEFAULT 'open'
            CHECK (status IN ('open', 'closed', 'processed'))
    );

    CREATE TABLE entries (
        id INTEGER PRIMARY KEY,
        session_id INTEGER NOT NULL REFERENCES sessions(id),
        what_changed TEXT NOT NULL,
        observable_outcome TEXT,
        inferred_intent TEXT,
        intent_confidence REAL,
        intent_status TEXT NOT NULL DEFAULT 'inferred'
            CHECK (intent_status IN ('inferred', 'confirmed', 'corrected')),
        files_touched TEXT NOT NULL DEFAULT '[]',   -- JSON list of paths
        raw_event_ids TEXT NOT NULL DEFAULT '[]',   -- JSON list of raw_events.id
        model_version TEXT NOT NULL,
        prompt_version TEXT NOT NULL,
        created_at TEXT NOT NULL
    );

    CREATE TABLE artifacts (
        id INTEGER PRIMARY KEY,
        path TEXT NOT NULL,
        kind TEXT NOT NULL,               -- dataset | checkpoint | figure | result
        created_at TEXT NOT NULL,
        meta TEXT NOT NULL DEFAULT '{}'
    );

    CREATE TABLE papers (
        id INTEGER PRIMARY KEY,
        path TEXT NOT NULL UNIQUE,
        title TEXT,
        added_at TEXT NOT NULL,
        meta TEXT NOT NULL DEFAULT '{}'
    );

    -- Typed graph edges between sessions, papers, and artifacts.
    -- Linked papers for an entry (Seshat.md schema: linked_papers[]) live here
    -- as session -> paper edges rather than a JSON column, so they are
    -- queryable in both directions.
    CREATE TABLE edges (
        id INTEGER PRIMARY KEY,
        src_type TEXT NOT NULL CHECK (src_type IN ('session', 'paper', 'artifact')),
        src_id INTEGER NOT NULL,
        dst_type TEXT NOT NULL CHECK (dst_type IN ('session', 'paper', 'artifact')),
        dst_id INTEGER NOT NULL,
        kind TEXT NOT NULL,               -- cites-idea-from | produced | modified
                                          -- | supersedes | time-proximity
        confidence REAL,
        created_at TEXT NOT NULL
    );

    CREATE INDEX idx_raw_events_session ON raw_events(session_id);
    CREATE INDEX idx_raw_events_ts ON raw_events(ts);
    CREATE INDEX idx_entries_session ON entries(session_id);
    CREATE INDEX idx_edges_src ON edges(src_type, src_id);
    CREATE INDEX idx_edges_dst ON edges(dst_type, dst_id);
    """,
    # v2: latest-indexed snapshots of watched files, so the watcher can diff a
    # save against what it last saw. Mutable by design (unlike raw_events):
    # only the newest version is kept; history lives in the diffs.
    """
    CREATE TABLE snapshots (
        path TEXT PRIMARY KEY,
        content TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """,
    # v3: entry ids must never be reused. Reprocessing deletes and re-adds
    # entries; without AUTOINCREMENT, SQLite recycles the freed rowid and a
    # stale citation would silently point at different content.
    """
    CREATE TABLE entries_v3 (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL REFERENCES sessions(id),
        what_changed TEXT NOT NULL,
        observable_outcome TEXT,
        inferred_intent TEXT,
        intent_confidence REAL,
        intent_status TEXT NOT NULL DEFAULT 'inferred'
            CHECK (intent_status IN ('inferred', 'confirmed', 'corrected')),
        files_touched TEXT NOT NULL DEFAULT '[]',
        raw_event_ids TEXT NOT NULL DEFAULT '[]',
        model_version TEXT NOT NULL,
        prompt_version TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    INSERT INTO entries_v3 SELECT * FROM entries;
    DROP TABLE entries;
    ALTER TABLE entries_v3 RENAME TO entries;
    CREATE INDEX idx_entries_session ON entries(session_id);
    """,
]

SCHEMA_VERSION = len(MIGRATIONS)


@dataclass
class RawEvent:
    ts: str
    kind: str
    payload: dict
    path: str | None = None
    session_id: int | None = None
    id: int | None = None


@dataclass
class Session:
    started_at: str
    ended_at: str | None = None
    status: str = "open"
    id: int | None = None


@dataclass
class JournalEntry:
    session_id: int
    what_changed: str
    observable_outcome: str | None = None
    inferred_intent: str | None = None
    intent_confidence: float | None = None
    intent_status: str = "inferred"
    files_touched: list[str] = field(default_factory=list)
    raw_event_ids: list[int] = field(default_factory=list)
    model_version: str = "unknown"
    prompt_version: str = "unknown"
    created_at: str | None = None
    id: int | None = None


@dataclass
class Paper:
    path: str
    title: str | None = None
    added_at: str | None = None
    id: int | None = None


@dataclass
class Edge:
    src_type: str
    src_id: int
    dst_type: str
    dst_id: int
    kind: str
    confidence: float | None = None
    created_at: str | None = None
    id: int | None = None
