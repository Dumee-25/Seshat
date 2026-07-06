"""Seshat Streamlit UI: chat over the journal + session timeline.

Run from a project root (where seshat.toml lives), normally via `seshat ui`.
Kept deliberately thin: all retrieval/answer logic lives in
seshat.query.engine so it stays testable without a browser.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from seshat.config import ConfigError, load_config
from seshat.inference.provider import GenerationError, get_provider
from seshat.query.engine import QueryEngine, SessionCitation
from seshat.store.db import Store
from seshat.store.schema import RawEvent
from seshat.store.vectors import VectorStore

st.set_page_config(page_title="Seshat", page_icon="📜", layout="wide")


@st.cache_resource
def open_project(root_str: str):
    root = Path(root_str)
    config = load_config(root)
    store = Store.open(root)
    vectors = VectorStore(root)
    engine = QueryEngine(store, vectors, get_provider(config))
    return config, store, vectors, engine


def render_event(event: RawEvent) -> None:
    p = event.payload
    if event.kind == "notebook_diff":
        for cell in p.get("added", []):
            st.caption("added cell")
            st.code(cell["source"], language="python")
            for out in cell.get("outputs", []):
                st.text(out)
        for cell in p.get("modified", []):
            st.caption("modified cell (before / after)")
            st.code(cell["old_source"], language="python")
            st.code(cell["source"], language="python")
            for out in cell.get("outputs", []):
                st.text(out)
        for cell in p.get("removed", []):
            st.caption("removed cell")
            st.code(cell["source"], language="python")
        if p.get("kernel_restarted"):
            st.caption("kernel was restarted")
    elif event.kind == "script_change":
        st.code(p.get("diff", ""), language="diff")
    elif event.kind == "git_commit":
        st.markdown(f"**commit:** {p.get('message', '')}")
        st.code(p.get("diff", ""), language="diff")
    elif event.kind == "result_file":
        st.text(p.get("preview", ""))
    else:
        st.json(p)


def render_session_detail(store: Store, session_id: int) -> None:
    for event in store.events(session_id=session_id):
        st.markdown(f"`{event.ts}` — **{event.kind}** `{event.path or ''}`")
        render_event(event)
        st.divider()


def render_entry(store: Store, citation_or_entry, session_id: int) -> None:
    entry = citation_or_entry
    st.markdown(entry.what_changed)
    if entry.observable_outcome:
        st.markdown(f"**Outcome:** {entry.observable_outcome}")
    if entry.inferred_intent:
        badge = {"inferred": "🤔 inferred", "confirmed": "✅ confirmed",
                 "corrected": "✏️ corrected"}[entry.intent_status]
        confidence = (
            f" ({entry.intent_confidence:.0%})" if entry.intent_confidence is not None else ""
        )
        st.markdown(f"**Why** *({badge}{confidence})*: {entry.inferred_intent}")

    if entry.intent_status == "inferred" and entry.inferred_intent:
        col_confirm, col_fix = st.columns([1, 3])
        if col_confirm.button("Confirm intent", key=f"confirm{entry.id}"):
            store.set_intent(entry.id, entry.inferred_intent, status="confirmed")
            st.rerun()
        with col_fix:
            corrected = st.text_input(
                "Correct the intent", key=f"fix{entry.id}", label_visibility="collapsed",
                placeholder="Correct the intent...",
            )
            if corrected:
                store.set_intent(entry.id, corrected, status="corrected")
                st.rerun()
    st.caption(
        f"session {session_id} · {entry.model_version} · prompt {entry.prompt_version}"
    )


def render_citation(store: Store, citation: SessionCitation) -> None:
    session = citation.session
    label = f"session {session.id} — {session.started_at}"
    with st.expander(label):
        render_entry(store, citation.entry, session.id)
        st.markdown("**Underlying events**")
        render_session_detail(store, session.id)


def chat_tab(store: Store, engine: QueryEngine) -> None:
    with st.sidebar:
        st.subheader("Filters")
        file_filter = st.text_input("File path contains") or None
        since = st.text_input("Since (YYYY-MM-DD)") or None
        until = st.text_input("Until (YYYY-MM-DD)") or None

    if "history" not in st.session_state:
        st.session_state.history = []
    for role, payload in st.session_state.history:
        with st.chat_message(role):
            if role == "user":
                st.markdown(payload)
            else:
                st.markdown(payload.text)
                for citation in payload.citations:
                    render_citation(store, citation)
                for paper in payload.papers:
                    with st.expander(f'paper: "{paper.title}"'):
                        st.text(paper.snippet)
                        st.caption(paper.path)

    question = st.chat_input("What did I already try?")
    if question:
        st.session_state.history.append(("user", question))
        try:
            answer = engine.ask(
                question, file_filter=file_filter, since=since, until=until
            )
        except GenerationError as exc:
            st.error(f"The answer model is unavailable: {exc}")
            st.stop()
        st.session_state.history.append(("assistant", answer))
        st.rerun()


def timeline_tab(store: Store) -> None:
    sessions = store.sessions()
    if not sessions:
        st.info("No sessions captured yet. Run `seshat watch` or `seshat backfill`.")
        return
    for session in reversed(sessions):
        entries = store.entries(session_id=session.id)
        title = entries[0].what_changed[:80] if entries else f"({session.status})"
        with st.expander(f"session {session.id} · {session.started_at} · {title}"):
            for entry in entries:
                render_entry(store, entry, session.id)
                st.divider()
            st.markdown("**Events**")
            render_session_detail(store, session.id)


def main() -> None:
    try:
        config, store, vectors, engine = open_project(str(Path.cwd()))
    except ConfigError as exc:
        st.error(str(exc))
        st.stop()
    st.title(f"📜 Seshat — {config.name}")
    tab_chat, tab_timeline = st.tabs(["Chat", "Timeline"])
    with tab_chat:
        chat_tab(store, engine)
    with tab_timeline:
        timeline_tab(store)


main()
