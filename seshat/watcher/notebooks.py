"""Cell-level notebook diffing.

A notebook save is diffed against the last indexed snapshot, not the previous
git commit. Cells are matched by nbformat cell id when present (stable across
edits and reorders); id-less cells fall back to exact-source matching, then
difflib similarity pairing, so an edited cell shows up as *modified* rather
than a remove+add pair.

Snapshots store the already-simplified representation (sources capped,
outputs summarized), never raw .ipynb JSON — giant output blobs are dropped
at the door.
"""

from __future__ import annotations

import difflib
import json
from dataclasses import asdict, dataclass, field

from seshat.watcher.truncation import MAX_SOURCE_CHARS, truncate_text

SIMILARITY_THRESHOLD = 0.5


@dataclass
class Cell:
    id: str | None
    cell_type: str
    source: str
    execution_count: int | None = None
    outputs: list[str] = field(default_factory=list)


class NotebookParseError(Exception):
    pass


def parse_notebook(text: str) -> list[Cell]:
    """Parse .ipynb JSON into simplified cells with summarized outputs."""
    try:
        nb = json.loads(text)
        raw_cells = nb["cells"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise NotebookParseError(f"Not a parseable notebook: {exc}") from exc

    cells = []
    for raw in raw_cells:
        if not isinstance(raw, dict):
            continue
        source = raw.get("source", "")
        if isinstance(source, list):
            source = "".join(source)
        cells.append(
            Cell(
                id=raw.get("id"),
                cell_type=raw.get("cell_type", "code"),
                source=truncate_text(source, MAX_SOURCE_CHARS),
                execution_count=raw.get("execution_count"),
                outputs=[_summarize_output(o) for o in raw.get("outputs", [])],
            )
        )
    return cells


def _summarize_output(output: dict) -> str:
    kind = output.get("output_type")
    if kind == "stream":
        text = output.get("text", "")
        if isinstance(text, list):
            text = "".join(text)
        return truncate_text(text)
    if kind in ("execute_result", "display_data"):
        data = output.get("data", {})
        if "text/plain" in data:
            text = data["text/plain"]
            if isinstance(text, list):
                text = "".join(text)
            return truncate_text(text)
        if any(mime.startswith("image/") for mime in data):
            return "[image output]"
        return f"[{'/'.join(data.keys()) or 'empty'} output]"
    if kind == "error":
        traceback = output.get("traceback", [])
        tail = "\n".join(traceback[-3:])
        return truncate_text(f"Error: {output.get('ename')}: {output.get('evalue')}\n{tail}")
    return f"[{kind} output]"


def cells_to_json(cells: list[Cell]) -> str:
    return json.dumps([asdict(c) for c in cells])


def cells_from_json(text: str) -> list[Cell]:
    return [Cell(**c) for c in json.loads(text)]


def diff_notebooks(old: list[Cell], new: list[Cell]) -> dict | None:
    """Return a diff payload, or None if nothing meaningful changed."""
    pairs, added, removed = _match_cells(old, new)

    modified = []
    for old_cell, _old_idx, new_cell, new_idx in pairs:
        if old_cell.source != new_cell.source or old_cell.outputs != new_cell.outputs:
            modified.append(
                {
                    "id": new_cell.id,
                    "index": new_idx,
                    "old_source": old_cell.source,
                    "source": new_cell.source,
                    "outputs": new_cell.outputs,
                    "execution_count": new_cell.execution_count,
                }
            )

    matched_old_indices = [old_idx for _, old_idx, _, new_idx in pairs]
    reordered = matched_old_indices != sorted(matched_old_indices)

    old_max = max((c.execution_count or 0 for c in old), default=0)
    new_max = max((c.execution_count or 0 for c in new), default=0)
    kernel_restarted = new_max > 0 and new_max < old_max

    if not (added or removed or modified or reordered or kernel_restarted):
        return None
    return {
        "added": [
            {
                "id": c.id,
                "index": i,
                "source": c.source,
                "outputs": c.outputs,
                "execution_count": c.execution_count,
            }
            for c, i in added
        ],
        "removed": [{"id": c.id, "source": c.source} for c, _ in removed],
        "modified": modified,
        "reordered": reordered,
        "kernel_restarted": kernel_restarted,
        "cell_count": len(new),
    }


def _match_cells(
    old: list[Cell], new: list[Cell]
) -> tuple[
    list[tuple[Cell, int, Cell, int]],
    list[tuple[Cell, int]],
    list[tuple[Cell, int]],
]:
    """Pair old and new cells; return (pairs, added, removed) with indices."""
    old_left = dict(enumerate(old))
    new_left = dict(enumerate(new))
    pairs: list[tuple[Cell, int, Cell, int]] = []

    # 1. Match by nbformat cell id (survives edits and reorders).
    old_by_id = {c.id: i for i, c in old_left.items() if c.id}
    for new_idx, new_cell in list(new_left.items()):
        old_idx = old_by_id.get(new_cell.id)
        if new_cell.id and old_idx is not None and old_idx in old_left:
            pairs.append((old_left.pop(old_idx), old_idx, new_left.pop(new_idx), new_idx))

    # 2. Match remaining id-less cells by exact source (survives reorders).
    old_by_source: dict[str, list[int]] = {}
    for i, c in old_left.items():
        old_by_source.setdefault(c.source, []).append(i)
    for new_idx, new_cell in list(new_left.items()):
        candidates = old_by_source.get(new_cell.source)
        if candidates:
            old_idx = candidates.pop(0)
            pairs.append((old_left.pop(old_idx), old_idx, new_left.pop(new_idx), new_idx))

    # 3. Pair leftovers by similarity, so edits show as modifications.
    for new_idx, new_cell in list(new_left.items()):
        best_idx, best_score = None, SIMILARITY_THRESHOLD
        for old_idx, old_cell in old_left.items():
            score = difflib.SequenceMatcher(
                None, old_cell.source, new_cell.source
            ).ratio()
            if score > best_score:
                best_idx, best_score = old_idx, score
        if best_idx is not None:
            pairs.append((old_left.pop(best_idx), best_idx, new_left.pop(new_idx), new_idx))

    pairs.sort(key=lambda p: p[3])
    added = [(c, i) for i, c in sorted(new_left.items())]
    removed = [(c, i) for i, c in sorted(old_left.items())]
    return pairs, added, removed
