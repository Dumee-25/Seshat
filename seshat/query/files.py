"""Code-panel queries: the project's code files, their change history, and
recent activity — each change linked back to the session that made it.

The file tree comes from the filesystem (the watched code files that exist
now); the change stats and history come from the store's captured events. So
the tree shows what's there, and every file links to the sessions that touched
it.
"""

from __future__ import annotations

import os
from pathlib import Path

from seshat.config import ALWAYS_IGNORED_DIRS, SeshatConfig
from seshat.store.db import Store
from seshat.watcher.ignore import PathFilter

CODE_SUFFIXES = (".py", ".ipynb")
CHANGE_KINDS = ("notebook_diff", "script_change")


def code_files(root: Path, config: SeshatConfig) -> list[str]:
    """Project-relative paths of watched code files that exist now."""
    root = Path(root)
    path_filter = PathFilter(root, config)
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in ALWAYS_IGNORED_DIRS]
        for name in filenames:
            path = Path(dirpath) / name
            if path.suffix in CODE_SUFFIXES and path_filter.should_index(path):
                rel = path_filter.relative(path)
                if rel:
                    out.append(rel)
    return sorted(out)


def _change_summary(event) -> str:
    p = event.payload
    if event.kind == "script_change":
        return f"+{p.get('lines_added', 0)} -{p.get('lines_removed', 0)}"
    added = len(p.get("added", []))
    modified = len(p.get("modified", []))
    removed = len(p.get("removed", []))
    return f"{added} added, {modified} modified, {removed} removed"


def file_stats(store: Store) -> dict[str, dict]:
    """Per-path change count and last-changed time, from captured events."""
    stats: dict[str, dict] = {}
    for event in store.events():
        if event.kind in CHANGE_KINDS and event.path:
            s = stats.setdefault(event.path, {"changes": 0, "last_changed": ""})
            s["changes"] += 1
            if event.ts > s["last_changed"]:
                s["last_changed"] = event.ts
    return stats


def build_tree(paths: list[str], stats: dict[str, dict]) -> list[dict]:
    """Nested file tree (dirs first, then files), files annotated with stats."""
    tree: dict = {}
    for path in paths:
        parts = path.split("/")
        cursor = tree
        for part in parts[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[parts[-1]] = None  # file marker

    def to_nodes(node: dict, prefix: str) -> list[dict]:
        nodes = []
        for name in sorted(node, key=lambda n: (node[n] is None, n.lower())):
            full = f"{prefix}{name}"
            if node[name] is None:
                st = stats.get(full, {})
                nodes.append({
                    "name": name, "path": full, "type": "file",
                    "changes": st.get("changes", 0),
                    "last_changed": st.get("last_changed") or None,
                })
            else:
                nodes.append({
                    "name": name, "path": full, "type": "dir",
                    "children": to_nodes(node[name], full + "/"),
                })
        return nodes

    return to_nodes(tree, "")


def file_history(store: Store, path: str) -> list[dict]:
    """Sessions that touched a file, newest first, for jump-to-timeline."""
    session_ids: list[int] = []
    for event in store.events():
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


def recent_changes(store: Store, limit: int = 30) -> list[dict]:
    """Most recent file changes, each linked to its session."""
    out = []
    for event in reversed(store.events()):
        if event.kind in CHANGE_KINDS and event.path:
            out.append({
                "path": event.path,
                "kind": event.kind,
                "ts": event.ts,
                "session_id": event.session_id,
                "summary": _change_summary(event),
            })
            if len(out) >= limit:
                break
    return out
