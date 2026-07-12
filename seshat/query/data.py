"""Data-panel queries: tracked result/dataset artifacts, a preview of each,
and the sessions that produced them.

Artifacts are what the watcher records for files under the results folder. The
list and the producing-session links come from the store; the preview reads
the file fresh (parsed for CSV/JSON) so you see the current data, not a stale
snapshot.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path as FsPath
from pathlib import PurePosixPath

from seshat.store.db import Store

MAX_PREVIEW_BYTES = 200_000
MAX_ROWS = 100


def list_artifacts(store: Store) -> list[dict]:
    return [
        {
            "id": a.id,
            "path": a.path,
            "name": PurePosixPath(a.path).name,
            "kind": a.kind,
            "created_at": a.created_at,
        }
        for a in store.artifacts()
    ]


def preview_file(
    root: FsPath, path: str, max_bytes: int = MAX_PREVIEW_BYTES, max_rows: int = MAX_ROWS
) -> dict:
    file = FsPath(root) / path
    if not file.exists():
        return {"kind": "missing"}
    try:
        text = file.read_text(encoding="utf-8", errors="replace")[:max_bytes]
    except OSError:
        return {"kind": "missing"}

    suffix = file.suffix.lower()
    if suffix == ".csv":
        rows = list(csv.reader(io.StringIO(text)))
        columns = rows[0] if rows else []
        data = rows[1 : max_rows + 1]
        return {
            "kind": "csv",
            "columns": columns,
            "rows": data,
            "truncated": len(rows) > max_rows + 1,
        }
    if suffix == ".json":
        try:
            pretty = json.dumps(json.loads(text), indent=2)[:max_bytes]
        except json.JSONDecodeError:
            pretty = text
        return {"kind": "json", "text": pretty}
    return {"kind": "text", "text": text}


def artifact_sessions(store: Store, path: str) -> list[dict]:
    """Sessions whose result-file events touched this artifact, newest first."""
    session_ids: list[int] = []
    for event in store.events(kind="result_file"):
        if event.path == path and event.session_id and event.session_id not in session_ids:
            session_ids.append(event.session_id)
    out = []
    for sid in session_ids:
        session = store.get_session(sid)
        entries = store.entries(session_id=sid)
        out.append({
            "session_id": sid,
            "started_at": session.started_at,
            "what_changed": entries[0].what_changed if entries else None,
        })
    out.sort(key=lambda r: r["started_at"], reverse=True)
    return out
