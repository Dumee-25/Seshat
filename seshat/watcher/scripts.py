"""Script change tracking: filesystem diffs plus a post-commit git hook.

The watcher diffs saved .py files against the last indexed snapshot, catching
uncommitted work. The git hook records commits as their own events, which
also carry the commit message — a rare piece of *explicit* researcher intent.
"""

from __future__ import annotations

import difflib
import subprocess
from pathlib import Path

from seshat.watcher.truncation import truncate_lines, truncate_text

HOOK_MARKER = "# installed by seshat"

POST_COMMIT_HOOK = f"""#!/bin/sh
{HOOK_MARKER}
python -m seshat.cli record-commit >/dev/null 2>&1 || true
"""


def diff_script(old_text: str, new_text: str, rel_path: str) -> dict | None:
    """Unified diff payload for a saved script, or None if unchanged."""
    if old_text == new_text:
        return None
    diff_lines = list(
        difflib.unified_diff(
            old_text.splitlines(),
            new_text.splitlines(),
            fromfile=f"a/{rel_path}",
            tofile=f"b/{rel_path}",
            lineterm="",
        )
    )
    return {
        "diff": truncate_lines("\n".join(diff_lines)),
        "lines_added": sum(
            1 for line in diff_lines if line.startswith("+") and not line.startswith("+++")
        ),
        "lines_removed": sum(
            1 for line in diff_lines if line.startswith("-") and not line.startswith("---")
        ),
    }


def install_post_commit_hook(root: Path) -> Path:
    """Install (or refuse to clobber) the post-commit hook. Returns hook path."""
    hooks_dir = root / ".git" / "hooks"
    if not hooks_dir.parent.exists():
        raise FileNotFoundError(f"{root} is not a git repository.")
    hooks_dir.mkdir(exist_ok=True)
    hook = hooks_dir / "post-commit"
    if hook.exists() and HOOK_MARKER not in hook.read_text(encoding="utf-8"):
        raise FileExistsError(
            f"{hook} already exists and was not installed by seshat; "
            "add `python -m seshat.cli record-commit` to it manually."
        )
    hook.write_text(POST_COMMIT_HOOK, encoding="utf-8", newline="\n")
    hook.chmod(0o755)
    return hook


def git_output(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=True,
        encoding="utf-8", errors="replace",
    ).stdout


def read_commit(root: Path, rev: str = "HEAD") -> dict:
    """Payload describing one commit: hash, timestamps, message, files, diff."""
    commit_hash, authored_at, subject = git_output(
        root, "log", "-1", "--pretty=format:%H%x00%aI%x00%s", rev
    ).split("\x00", 2)
    # --root: a repository's first commit has no parent to diff against.
    files = [
        f
        for f in git_output(
            root, "diff-tree", "-r", "--root", "--name-only", "--no-commit-id", rev
        ).splitlines()
        if f
    ]
    diff = git_output(root, "show", rev, "--format=", "--unified=1")
    return {
        "hash": commit_hash,
        "authored_at": authored_at,
        "message": truncate_text(subject, 500),
        "files": files,
        "diff": truncate_lines(diff),
    }


def read_head_commit(root: Path) -> dict:
    return read_commit(root, "HEAD")
