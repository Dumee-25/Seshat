"""Session -> journal entry generation.

Idempotent by design: generating for a session first deletes any previous
entries (and their vectors), so a retry after a partial failure — or a
deliberate `seshat reprocess` — never duplicates. The session is marked
processed only after the entry is stored and embedded.
"""

from __future__ import annotations

import json
import re

from seshat.inference.prompts import PROMPT_VERSION, build_journal_prompt
from seshat.inference.provider import GenerationError, LLMProvider
from seshat.store.db import Store
from seshat.store.schema import JournalEntry
from seshat.store.vectors import VectorStore

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)  # qwen3-style reasoning tags


def parse_response(text: str) -> dict:
    """Extract the journal JSON object from a model response."""
    cleaned = _THINK_RE.sub("", text)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        raise GenerationError(f"No JSON object in model response: {text[:200]!r}")
    try:
        parsed = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        raise GenerationError(f"Model response is not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict) or not str(parsed.get("what_changed") or "").strip():
        raise GenerationError("Model response missing required key 'what_changed'.")
    return parsed


def entry_embedding_text(entry: JournalEntry) -> str:
    parts = [entry.what_changed]
    if entry.observable_outcome:
        parts.append(entry.observable_outcome)
    if entry.inferred_intent:
        parts.append(f"Intent: {entry.inferred_intent}")
    return "\n".join(parts)


def delete_session_entries(store: Store, vectors: VectorStore, session_id: int) -> int:
    old = store.entries(session_id=session_id)
    if old:
        vectors.delete("entries", [str(e.id) for e in old])
        store.delete_entries(session_id)
    return len(old)


def generate_entry(
    store: Store,
    vectors: VectorStore,
    provider: LLMProvider,
    session_id: int,
) -> JournalEntry | None:
    """Generate, store, and embed the journal entry for a closed session.

    Returns None (and marks the session processed) for empty sessions.
    Raises GenerationError on LLM failure — callers leave the session closed
    so the queue retries later.
    """
    session = store.get_session(session_id)
    events = store.events(session_id=session_id)
    if not events:
        if session.status == "closed":
            store.mark_session_processed(session_id)
        return None

    parsed = parse_response(provider.generate(build_journal_prompt(session, events)))

    confidence = parsed.get("intent_confidence")
    if isinstance(confidence, (int, float)) and not isinstance(confidence, bool):
        confidence = min(1.0, max(0.0, float(confidence)))
    else:
        confidence = None

    entry = JournalEntry(
        session_id=session_id,
        what_changed=str(parsed["what_changed"]).strip(),
        observable_outcome=_optional_str(parsed.get("observable_outcome")),
        inferred_intent=_optional_str(parsed.get("inferred_intent")),
        intent_confidence=confidence,
        intent_status="inferred",
        files_touched=sorted({e.path for e in events if e.path}),
        raw_event_ids=[e.id for e in events],
        model_version=provider.model_version,
        prompt_version=PROMPT_VERSION,
    )

    delete_session_entries(store, vectors, session_id)
    entry.id = store.add_entry(entry)
    vectors.add(
        "entries",
        ids=[str(entry.id)],
        texts=[entry_embedding_text(entry)],
        metadatas=[{"session_id": session_id, "entry_id": entry.id}],
    )
    if session.status == "closed":
        store.mark_session_processed(session_id)
    return entry


def _optional_str(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
