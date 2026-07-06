"""Aggressive truncation of captured text before it hits the store or the LLM.

Cell outputs can be enormous (dataframes, training logs); Seshat.md §6 calls
for truncating early. Head + tail are kept because the interesting part of a
long training log is usually the last few lines.
"""

from __future__ import annotations

MAX_OUTPUT_CHARS = 2000
MAX_SOURCE_CHARS = 4000
MAX_DIFF_LINES = 200


def truncate_text(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    head = int(limit * 0.6)
    tail = limit - head
    omitted = len(text) - head - tail
    return f"{text[:head]}\n... [{omitted} chars truncated] ...\n{text[-tail:]}"


def truncate_lines(text: str, limit: int = MAX_DIFF_LINES) -> str:
    lines = text.splitlines()
    if len(lines) <= limit:
        return text
    head = int(limit * 0.6)
    tail = limit - head
    omitted = len(lines) - head - tail
    return "\n".join(
        [*lines[:head], f"... [{omitted} lines truncated] ...", *lines[-tail:]]
    )
