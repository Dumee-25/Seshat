"""Versioned journal prompts.

PROMPT_VERSION is stamped onto every generated entry, so `seshat reprocess`
can tell which entries came from an older prompt. Never change a prompt
without bumping the version.
"""

from __future__ import annotations

from seshat.store.schema import RawEvent, Session

PROMPT_VERSION = "v1"

MAX_EVENT_CHARS = 1500
MAX_EVENTS_CHARS = 9000

JOURNAL_PROMPT = """\
You are Seshat, a research journal assistant. Below are the recorded changes \
from one work session on a machine learning research project.

Write a journal entry describing the session. Respond with ONLY a JSON object \
with exactly these keys:
- "what_changed": 1-3 factual sentences, past tense, describing what was done.
- "observable_outcome": metrics, errors, or outputs actually visible in the \
events, as a short string — or null if none are visible.
- "inferred_intent": your single best guess at WHY the researcher made these \
changes, one sentence — or null if you cannot guess.
- "intent_confidence": a number from 0.0 to 1.0 for how confident you are in \
the inferred intent.

Base what_changed and observable_outcome strictly on the events; never invent \
metrics. The intent is allowed to be a guess.

Session from {started_at} to {ended_at}:

{events}

JSON:"""


def render_event(event: RawEvent) -> str:
    lines = [f"[{event.kind}] {event.path or ''}".rstrip()]
    p = event.payload
    if event.kind == "notebook_diff":
        for cell in p.get("added", []):
            lines.append(f"+ added cell: {cell['source']}")
            lines.extend(f"  output: {o}" for o in cell.get("outputs", []))
        for cell in p.get("modified", []):
            lines.append(
                f"~ modified cell:\n  before: {cell['old_source']}\n  after: {cell['source']}"
            )
            lines.extend(f"  output: {o}" for o in cell.get("outputs", []))
        for cell in p.get("removed", []):
            lines.append(f"- removed cell: {cell['source']}")
        if p.get("kernel_restarted"):
            lines.append("(kernel was restarted)")
        if p.get("reordered"):
            lines.append("(cells were reordered)")
    elif event.kind == "script_change":
        lines.append(p.get("diff", ""))
    elif event.kind == "git_commit":
        lines.append(f'commit message: "{p.get("message", "")}"')
        lines.append(f"files: {', '.join(p.get('files', []))}")
        lines.append(p.get("diff", ""))
    elif event.kind == "result_file":
        lines.append(f"results file content:\n{p.get('preview', '')}")
    else:
        lines.append(str(p))
    text = "\n".join(lines)
    if len(text) > MAX_EVENT_CHARS:
        return text[:MAX_EVENT_CHARS] + "\n... [event truncated]"
    return text


def build_journal_prompt(session: Session, events: list[RawEvent]) -> str:
    rendered, used = [], 0
    for event in events:
        block = render_event(event)
        if used + len(block) > MAX_EVENTS_CHARS:
            rendered.append(f"... [{len(events) - len(rendered)} more events omitted]")
            break
        rendered.append(block)
        used += len(block)
    return JOURNAL_PROMPT.format(
        started_at=session.started_at,
        ended_at=session.ended_at or "?",
        events="\n\n".join(rendered) or "(no events)",
    )
