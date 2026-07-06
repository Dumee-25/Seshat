"""Backfill: reconstruct a timeline from existing git history.

Commits are grouped into pseudo-sessions by the same idle-gap rule the live
watcher uses, then stored as closed sessions of git_commit events — which
puts them straight into the normal inference queue. Journal generation is
deliberately decoupled (months of history through a local 8B model takes
hours): ingesting is fast and safe to re-run, generation happens via
`seshat process` / `seshat watch` at its own pace.

Resumable by construction: commits already in the store (from a previous
backfill run or the live post-commit hook) are skipped by hash.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from seshat.store.db import Store
from seshat.watcher.scripts import git_output, read_commit


class BackfillError(Exception):
    pass


@dataclass
class CommitRef:
    hash: str
    ts: str  # ISO 8601, UTC-normalized
    subject: str


def _to_utc(iso_ts: str) -> str:
    return datetime.fromisoformat(iso_ts).astimezone(UTC).isoformat(timespec="seconds")


def list_commits(root: Path) -> list[CommitRef]:
    """All commits, oldest first. Cheap: no diffs are read here."""
    if not (root / ".git").exists():
        raise BackfillError(f"{root} is not a git repository.")
    try:
        log = git_output(root, "log", "--reverse", "--pretty=format:%H%x00%aI%x00%s")
    except subprocess.CalledProcessError:
        return []  # repository with no commits yet
    refs = []
    for line in log.splitlines():
        if not line.strip():
            continue
        commit_hash, authored_at, subject = line.split("\x00", 2)
        refs.append(CommitRef(hash=commit_hash, ts=_to_utc(authored_at), subject=subject))
    return refs


def group_commits(refs: list[CommitRef], idle_gap_minutes: int) -> list[list[CommitRef]]:
    """Split a chronological commit list into pseudo-sessions by time gap."""
    gap = timedelta(minutes=idle_gap_minutes)
    groups: list[list[CommitRef]] = []
    for ref in refs:
        if (
            groups
            and datetime.fromisoformat(ref.ts) - datetime.fromisoformat(groups[-1][-1].ts) <= gap
        ):
            groups[-1].append(ref)
        else:
            groups.append([ref])
    return groups


def backfill(
    root: Path,
    store: Store,
    idle_gap_minutes: int,
    log: Callable[[str], None] = lambda msg: None,
) -> tuple[int, int]:
    """Ingest git history as closed pseudo-sessions.

    Returns (sessions_created, commits_ingested). Already-ingested commits
    are skipped, so re-running after an interruption (or after new commits)
    only adds what's missing.
    """
    refs = list_commits(root)
    known = {e.payload.get("hash") for e in store.events(kind="git_commit")}
    new_refs = [r for r in refs if r.hash not in known]
    if known:
        log(f"{len(refs) - len(new_refs)} commit(s) already ingested; skipping.")
    if not new_refs:
        return 0, 0

    sessions_created = 0
    commits_ingested = 0
    for group in group_commits(new_refs, idle_gap_minutes):
        session_id = store.create_session(started_at=group[0].ts)
        for ref in group:
            payload = read_commit(root, ref.hash)
            event_id = store.append_event("git_commit", payload, ts=ref.ts)
            store.assign_events_to_session([event_id], session_id)
            commits_ingested += 1
        store.close_session(session_id, ended_at=group[-1].ts)
        sessions_created += 1
        log(
            f"session {session_id}: {len(group)} commit(s), "
            f"{group[0].ts} .. {group[-1].ts}"
        )
    return sessions_created, commits_ingested
