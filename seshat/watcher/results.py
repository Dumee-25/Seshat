"""Results folder indexing: CSV/JSON files become searchable artifact text.

No schema understanding (that's post-MVP MLflow territory) — just a truncated
text preview, so "val_loss diverged in run 12" is findable if the researcher's
own results file says so.
"""

from __future__ import annotations

from pathlib import Path

from seshat.store.db import Store
from seshat.watcher.truncation import truncate_text

PREVIEW_CHARS = 2000


def index_result_file(store: Store, path: Path, rel_path: str) -> dict | None:
    """Register the artifact and return a result_file event payload."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    artifact_id = store.artifact_id_for_path(rel_path)
    if artifact_id is None:
        artifact_id = store.add_artifact(rel_path, kind="result")
    return {
        "artifact_id": artifact_id,
        "preview": truncate_text(text, PREVIEW_CHARS),
        "bytes": path.stat().st_size,
    }
