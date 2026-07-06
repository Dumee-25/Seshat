"""Seshat Streamlit UI, "kohl" theme.

Design language: an archivist's ledger. Kohl/sand base, gold accent used
sparingly, rubric red for inferred intents (scribes wrote cautionary passages
in red), faience teal for confirmed ones. Serif for the record, sans for the
chrome, mono for diffs. No emojis anywhere.

Chat history is persisted in the store (single source of truth — the UI
renders whatever `chat_history()` returns), so conversations survive
restarts and citations stay live after `seshat reprocess`.

Run from a project root via `seshat ui`, which also injects the base theme
colors as Streamlit config environment variables.
"""

from __future__ import annotations

import html
from pathlib import Path

import streamlit as st

from seshat.config import ConfigError, load_config
from seshat.inference.provider import GenerationError, get_provider
from seshat.query.engine import QueryEngine
from seshat.store.db import Store, StoreError
from seshat.store.schema import RawEvent
from seshat.watcher.sessions import parse_ts

GOLD = "#C9A227"
RUBRIC = "#A63A2B"
RUBRIC_TEXT = "#D98A76"
FAIENCE = "#2F7E78"
FAIENCE_TEXT = "#6FB3AC"
MUTED = "#8A7F68"
BORDER = "#3A3225"
PANEL = "#1C1812"
DIFF_ADD = "#7FAE6A"
DIFF_DEL = "#C96B52"

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,500&family=Inter:wght@400;500&family=JetBrains+Mono:wght@400&display=swap');
html, body, [class*="st-"] {{ font-family: 'Inter', sans-serif; }}
h1, h2, h3 {{ font-family: 'Fraunces', serif !important; letter-spacing: 0.02em; }}
#MainMenu, footer, [data-testid="stToolbar"], [data-testid="stDecoration"] {{ visibility: hidden; }}
[data-testid="stHeader"] {{ background: transparent; }}
[data-testid="stChatMessageAvatarUser"],
[data-testid="stChatMessageAvatarAssistant"] {{ display: none; }}
[data-testid="stSidebar"] {{ border-right: 1px solid {BORDER}; }}
[data-testid="stExpander"] details {{ border: 1px solid {BORDER}; border-radius: 8px; }}
.seshat-brand {{ display: flex; align-items: center; gap: 10px; padding-bottom: 4px; }}
.seshat-wordmark {{ font-family: 'Fraunces', serif; font-size: 20px; letter-spacing: 0.14em; }}
.seshat-label {{ font-size: 11px; letter-spacing: 0.14em; color: {MUTED};
  text-transform: uppercase; }}
.seshat-badge {{ font-size: 11px; padding: 1px 9px; border-radius: 10px; white-space: nowrap; }}
.seshat-answer {{ font-family: 'Fraunces', serif; font-size: 16px; line-height: 1.65; }}
.seshat-rail {{ border-left: 2px solid {BORDER}; padding-left: 14px; margin-left: 4px; }}
.seshat-rail-item {{ position: relative; margin-bottom: 14px; }}
.seshat-rail-item::before {{ content: ""; position: absolute; left: -20px; top: 7px;
  width: 10px; height: 2px; background: {MUTED}; }}
.seshat-rail-item.current::before {{ background: {GOLD}; width: 13px; }}
.seshat-diff {{ font-family: 'JetBrains Mono', monospace; font-size: 12.5px; line-height: 1.65;
  background: #12100C; border: 1px solid {BORDER}; border-radius: 6px;
  padding: 10px 12px; overflow-x: auto; white-space: pre; }}
</style>
"""

STAR = f"""
<svg width="20" height="20" viewBox="0 0 20 20" aria-hidden="true">
  <g stroke="{GOLD}" stroke-width="1.4" stroke-linecap="round">
    <line x1="10" y1="10" x2="10" y2="2.5"/><line x1="10" y1="10" x2="15.9" y2="5.6"/>
    <line x1="10" y1="10" x2="17.3" y2="12.3"/><line x1="10" y1="10" x2="13.3" y2="17.1"/>
    <line x1="10" y1="10" x2="6.7" y2="17.1"/><line x1="10" y1="10" x2="2.7" y2="12.3"/>
    <line x1="10" y1="10" x2="4.1" y2="5.6"/>
  </g>
  <circle cx="10" cy="10" r="2" fill="{GOLD}"/>
</svg>
"""

st.set_page_config(page_title="Seshat", layout="wide")


@st.cache_resource
def open_project(root_str: str):
    from seshat.store.vectors import VectorStore

    root = Path(root_str)
    config = load_config(root)
    store = Store.open(root)
    engine = QueryEngine(store, VectorStore(root), get_provider(config))
    return config, store, engine


def esc(text: str | None) -> str:
    return html.escape(text or "")


def intent_badge(entry) -> str:
    if not entry.inferred_intent:
        return ""
    if entry.intent_status == "inferred":
        confidence = (
            f" · {entry.intent_confidence:.1f}" if entry.intent_confidence is not None else ""
        )
        return (
            f'<span class="seshat-badge" style="border:1px solid {RUBRIC};'
            f'color:{RUBRIC_TEXT}">inferred{confidence}</span>'
        )
    color = FAIENCE if entry.intent_status == "confirmed" else MUTED
    text_color = FAIENCE_TEXT if entry.intent_status == "confirmed" else MUTED
    return (
        f'<span class="seshat-badge" style="border:1px solid {color};'
        f'color:{text_color}">{entry.intent_status}</span>'
    )


def diff_block(text: str) -> str:
    lines = []
    for line in text.splitlines():
        color = MUTED
        if line.startswith("+") and not line.startswith("+++"):
            color = DIFF_ADD
        elif line.startswith("-") and not line.startswith("---"):
            color = DIFF_DEL
        elif line.startswith("@@"):
            color = GOLD
        lines.append(f'<span style="color:{color}">{esc(line)}</span>')
    return f'<div class="seshat-diff">{"<br>".join(lines)}</div>'


def render_event(event: RawEvent) -> None:
    p = event.payload
    st.markdown(
        f'<div class="seshat-label">{esc(event.ts)} · {esc(event.kind)} '
        f"{esc(event.path)}</div>",
        unsafe_allow_html=True,
    )
    if event.kind == "notebook_diff":
        for cell in p.get("added", []):
            st.code(cell["source"], language="python")
            for out in cell.get("outputs", []):
                st.markdown(diff_block(out), unsafe_allow_html=True)
        for cell in p.get("modified", []):
            st.markdown(
                diff_block(
                    "\n".join(
                        [f"- {line}" for line in cell["old_source"].splitlines()]
                        + [f"+ {line}" for line in cell["source"].splitlines()]
                    )
                ),
                unsafe_allow_html=True,
            )
            for out in cell.get("outputs", []):
                st.markdown(diff_block(out), unsafe_allow_html=True)
        for cell in p.get("removed", []):
            st.markdown(
                diff_block("\n".join(f"- {line}" for line in cell["source"].splitlines())),
                unsafe_allow_html=True,
            )
        if p.get("kernel_restarted"):
            st.markdown(
                '<div class="seshat-label">kernel was restarted</div>',
                unsafe_allow_html=True,
            )
    elif event.kind in ("script_change", "git_commit"):
        if event.kind == "git_commit":
            st.markdown(f"**{esc(p.get('message', ''))}**")
        st.markdown(diff_block(p.get("diff", "")), unsafe_allow_html=True)
    elif event.kind == "result_file":
        st.markdown(diff_block(p.get("preview", "")), unsafe_allow_html=True)


def render_entry(store: Store, entry, session, key_prefix: str) -> None:
    duration = ""
    if session.ended_at:
        minutes = int(
            (parse_ts(session.ended_at) - parse_ts(session.started_at)).total_seconds() // 60
        )
        duration = f" · {minutes} min"
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:10px">'
        f'<span class="seshat-label" style="color:{GOLD}">session {session.id}</span>'
        f'<span class="seshat-label">{esc(session.started_at)}{duration}</span>'
        f"{intent_badge(entry)}</div>",
        unsafe_allow_html=True,
    )
    body = esc(entry.what_changed)
    if entry.observable_outcome:
        body += f"<br><span style='color:{MUTED}'>Outcome:</span> {esc(entry.observable_outcome)}"
    if entry.inferred_intent:
        body += f"<br><span style='color:{MUTED}'>Why:</span> {esc(entry.inferred_intent)}"
    st.markdown(f'<div class="seshat-answer">{body}</div>', unsafe_allow_html=True)

    if entry.intent_status == "inferred" and entry.inferred_intent:
        col_confirm, col_fix = st.columns([1, 3])
        if col_confirm.button("Confirm intent", key=f"{key_prefix}confirm{entry.id}"):
            store.set_intent(entry.id, entry.inferred_intent, status="confirmed")
            st.rerun()
        with col_fix:
            corrected = st.text_input(
                "Correct the intent", key=f"{key_prefix}fix{entry.id}",
                label_visibility="collapsed", placeholder="Correct the intent",
            )
            if corrected:
                store.set_intent(entry.id, corrected, status="corrected")
                st.rerun()


def render_session_citation(store: Store, session_id: int, key_prefix: str) -> None:
    try:
        session = store.get_session(session_id)
    except StoreError:
        return
    entries = store.entries(session_id=session_id)
    label = f"session {session_id} · {session.started_at}"
    with st.expander(label):
        for entry in entries:
            render_entry(store, entry, session, key_prefix)
        st.markdown('<div class="seshat-label">underlying events</div>', unsafe_allow_html=True)
        for event in store.events(session_id=session_id):
            render_event(event)


def sidebar(store: Store, config) -> dict:
    with st.sidebar:
        st.markdown(
            f'<div class="seshat-brand">{STAR}'
            f'<span class="seshat-wordmark">SESHAT</span></div>'
            f'<div class="seshat-label">{esc(config.name)}</div>',
            unsafe_allow_html=True,
        )
        st.divider()
        st.markdown('<div class="seshat-label">filters</div>', unsafe_allow_html=True)
        filters = {
            "file_filter": st.text_input("File path contains") or None,
            "since": st.text_input("Since (YYYY-MM-DD)") or None,
            "until": st.text_input("Until (YYYY-MM-DD)") or None,
        }
        if st.button("Clear chat"):
            store.clear_chat()
            st.rerun()
        st.divider()
        st.markdown('<div class="seshat-label">timeline</div>', unsafe_allow_html=True)
        sessions = store.sessions()
        items = []
        for i, session in enumerate(reversed(sessions[-20:])):
            entries = store.entries(session_id=session.id)
            summary = esc(entries[0].what_changed[:70]) if entries else f"({session.status})"
            current = " current" if i == 0 else ""
            items.append(
                f'<div class="seshat-rail-item{current}">'
                f'<div style="font-size:11px;color:{GOLD if i == 0 else MUTED}">'
                f"{esc((session.started_at or '')[:10])} · session {session.id}</div>"
                f'<div style="font-size:12.5px;line-height:1.45">{summary}</div></div>'
            )
        if items:
            st.markdown(
                f'<div class="seshat-rail">{"".join(items)}</div>', unsafe_allow_html=True
            )
        else:
            st.caption("Nothing recorded yet.")
    return filters


def chat_tab(store: Store, engine: QueryEngine, filters: dict) -> None:
    for i, message in enumerate(store.chat_history()):
        with st.chat_message(message.role):
            if message.role == "user":
                st.markdown(esc(message.text))
            else:
                st.markdown(
                    f'<div class="seshat-answer">{esc(message.text)}</div>',
                    unsafe_allow_html=True,
                )
                for session_id in message.session_ids:
                    render_session_citation(store, session_id, key_prefix=f"chat{i}_")

    question = st.chat_input("What did I already try?")
    if question:
        store.add_chat_message("user", question)
        try:
            answer = engine.ask(question, **filters)
        except GenerationError as exc:
            st.error(f"The answer model is unavailable: {exc}")
            st.stop()
        store.add_chat_message(
            "assistant", answer.text,
            session_ids=[c.session.id for c in answer.citations],
        )
        st.rerun()


def timeline_tab(store: Store) -> None:
    sessions = store.sessions()
    if not sessions:
        st.markdown(
            '<div class="seshat-label">Nothing recorded yet — run seshat watch '
            "or seshat backfill.</div>",
            unsafe_allow_html=True,
        )
        return
    for session in reversed(sessions):
        entries = store.entries(session_id=session.id)
        title = entries[0].what_changed[:80] if entries else f"({session.status})"
        with st.expander(f"session {session.id} · {session.started_at} · {title}"):
            for entry in entries:
                render_entry(store, entry, session, key_prefix="tl_")
                st.divider()
            st.markdown(
                '<div class="seshat-label">events</div>', unsafe_allow_html=True
            )
            for event in store.events(session_id=session.id):
                render_event(event)


def main() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    try:
        config, store, engine = open_project(str(Path.cwd()))
    except ConfigError as exc:
        st.error(str(exc))
        st.stop()
    filters = sidebar(store, config)
    tab_chat, tab_timeline = st.tabs(["Chat", "Record"])
    with tab_chat:
        chat_tab(store, engine, filters)
    with tab_timeline:
        timeline_tab(store)


main()
