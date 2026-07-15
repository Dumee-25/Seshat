"""The cockpit API: a thin HTTP layer over the existing store.

It adds no new intelligence — it exposes what Seshat already records. A fresh
Store is opened per request (cheap for SQLite, and it sidesteps sharing a
connection across FastAPI's threadpool). The built React app, if present, is
served at the root; in development the frontend runs on Vite and calls this
API cross-origin.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from seshat.config import SeshatConfig
from seshat.query.timeline import KINDS, build_timeline
from seshat.store.db import Store, StoreError

STATIC_DIR = Path(__file__).resolve().parent / "static"


class ChatRequest(BaseModel):
    question: str
    file_filter: str | None = None
    since: str | None = None
    until: str | None = None


class LinkRequest(BaseModel):
    url: str


class IntentRequest(BaseModel):
    """Omit `intent` to confirm what was inferred as-is; send text to correct it."""

    intent: str | None = None


def _default_link_ingestor(root: Path, config: SeshatConfig, url: str) -> int | None:
    from seshat.inference.provider import get_embedder
    from seshat.papers.web import ingest_url
    from seshat.store.vectors import VectorStore

    store = Store.open(root)
    vectors = VectorStore(root, get_embedder(config))
    try:
        return ingest_url(store, vectors, url)
    finally:
        store.close()
        vectors.close()


@contextmanager
def _default_engine(root: Path, config: SeshatConfig) -> Iterator[tuple]:
    """Build a QueryEngine and hand back (engine, its store). The store is
    shared so a chat request logs its history through the same connection the
    answer was generated with."""
    from seshat.inference.provider import get_embedder, get_provider
    from seshat.query.engine import QueryEngine
    from seshat.store.vectors import VectorStore

    store = Store.open(root)
    vectors = VectorStore(root, get_embedder(config))
    try:
        yield QueryEngine(store, vectors, get_provider(config)), store
    finally:
        store.close()
        vectors.close()


def _resolve_citations(store: Store, session_ids: list[int]) -> list[dict]:
    """Turn cited session ids into rows the frontend can render and click
    through to the timeline, even for old chat history."""
    out = []
    for sid in session_ids:
        try:
            session = store.get_session(sid)
        except StoreError:
            continue
        entries = store.entries(session_id=sid)
        out.append({
            "session_id": sid,
            "started_at": session.started_at,
            "what_changed": entries[0].what_changed if entries else None,
        })
    return out


def create_app(
    root: Path,
    config: SeshatConfig,
    engine_cm: Callable | None = None,
    link_ingestor: Callable[[str], int | None] | None = None,
) -> FastAPI:
    root = Path(root)
    engine_cm = engine_cm or (lambda: _default_engine(root, config))
    link_ingestor = link_ingestor or (lambda url: _default_link_ingestor(root, config, url))
    app = FastAPI(title="Seshat", version="0.1.0")

    # The frozen build serves same-origin, but the Vite dev server is a
    # different port, so allow localhost during development.
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def store() -> Store:
        return Store.open(root)

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True, "project": config.name}

    @app.get("/api/status")
    def status() -> dict:
        with store() as s:
            sessions = s.sessions()
            return {
                "project": config.name,
                "root": str(root),
                "sessions": len(sessions),
                "queued": sum(1 for x in sessions if x.status == "closed"),
                "papers": len(s.papers()),
            }

    @app.get("/api/timeline")
    def timeline(
        limit: int = 100, kinds: str | None = None, since: str | None = None
    ) -> dict:
        selected = (
            {k for k in kinds.split(",") if k in KINDS} if kinds else set(KINDS)
        )
        with store() as s:
            items = build_timeline(s, limit=limit, kinds=selected, since=since)
        return {"items": [item.to_dict() for item in items]}

    @app.get("/api/sessions/{session_id}")
    def session_detail(session_id: int) -> dict:
        with store() as s:
            try:
                session = s.get_session(session_id)
            except StoreError:
                raise HTTPException(status_code=404, detail="No such session") from None
            entries = s.entries(session_id=session_id)
            events = s.events(session_id=session_id)
            return {
                "session": {
                    "id": session.id,
                    "started_at": session.started_at,
                    "ended_at": session.ended_at,
                    "status": session.status,
                },
                "entries": [
                    {
                        "id": e.id,
                        "what_changed": e.what_changed,
                        "observable_outcome": e.observable_outcome,
                        "inferred_intent": e.inferred_intent,
                        "intent_status": e.intent_status,
                        "intent_confidence": e.intent_confidence,
                        "files_touched": e.files_touched,
                    }
                    for e in entries
                ],
                "events": [
                    {"ts": ev.ts, "kind": ev.kind, "path": ev.path, "payload": ev.payload}
                    for ev in events
                ],
            }

    @app.post("/api/entries/{entry_id}/intent")
    def set_intent(entry_id: int, req: IntentRequest) -> dict:
        """Confirm or correct an inferred intent — the one place the cockpit
        writes back. An empty body confirms the inference as it stands; text
        that matches it is still a confirmation, not a correction."""
        with store() as s:
            try:
                entry = s.get_entry(entry_id)
            except StoreError:
                raise HTTPException(status_code=404, detail="No such entry") from None
            intent = req.intent if req.intent is not None else entry.inferred_intent
            if not intent or not intent.strip():
                raise HTTPException(status_code=400, detail="An intent needs some text.")
            intent = intent.strip()
            status = "confirmed" if intent == (entry.inferred_intent or "") else "corrected"
            s.set_intent(entry_id, intent, status=status)
            return {"id": entry_id, "intent": intent, "intent_status": status}

    @app.get("/api/chat/history")
    def chat_history() -> dict:
        with store() as s:
            return {
                "messages": [
                    {
                        "role": m.role,
                        "text": m.text,
                        "ts": m.ts,
                        "citations": _resolve_citations(s, m.session_ids),
                    }
                    for m in s.chat_history()
                ]
            }

    @app.post("/api/chat")
    def chat(req: ChatRequest) -> dict:
        from seshat.inference.provider import GenerationError

        with engine_cm() as (engine, s):
            s.add_chat_message("user", req.question)
            try:
                answer = engine.ask(
                    req.question,
                    file_filter=req.file_filter,
                    since=req.since,
                    until=req.until,
                )
            except GenerationError as exc:
                raise HTTPException(
                    status_code=503, detail=f"The model is unavailable: {exc}"
                ) from exc
            session_ids = [c.session.id for c in answer.citations]
            s.add_chat_message("assistant", answer.text, session_ids=session_ids)
            return {
                "answer": answer.text,
                "citations": _resolve_citations(s, session_ids),
                "papers": [
                    {"title": p.title, "snippet": p.snippet, "path": p.path}
                    for p in answer.papers
                ],
            }

    @app.post("/api/chat/clear")
    def chat_clear() -> dict:
        with store() as s:
            cleared = s.clear_chat()
        return {"cleared": cleared}

    @app.get("/api/papers")
    def papers() -> dict:
        with store() as s:
            return {
                "papers": [
                    {
                        "id": p.id,
                        "title": p.title,
                        "path": p.path,
                        "added_at": p.added_at,
                        "source": p.meta.get("source", "pdf"),
                    }
                    for p in s.papers()
                ]
            }

    @app.get("/api/papers/{paper_id}")
    def paper_detail(paper_id: int) -> dict:
        with store() as s:
            paper = s.get_paper(paper_id)
            if paper is None:
                raise HTTPException(status_code=404, detail="No such paper")
            return {
                "id": paper.id,
                "title": paper.title,
                "path": paper.path,
                "added_at": paper.added_at,
                "source": paper.meta.get("source", "pdf"),
                "content": s.get_paper_content(paper_id) or "",
            }

    @app.get("/api/data")
    def data() -> dict:
        from seshat.query.data import list_artifacts

        with store() as s:
            return {"artifacts": list_artifacts(s)}

    @app.get("/api/data/{artifact_id}")
    def data_detail(artifact_id: int) -> dict:
        from seshat.query.data import artifact_sessions, preview_file

        with store() as s:
            artifact = s.get_artifact(artifact_id)
            if artifact is None:
                raise HTTPException(status_code=404, detail="No such artifact")
            return {
                "artifact": {
                    "id": artifact.id,
                    "path": artifact.path,
                    "kind": artifact.kind,
                    "created_at": artifact.created_at,
                },
                "preview": preview_file(root, artifact.path),
                "sessions": artifact_sessions(s, artifact.path),
            }

    @app.get("/api/files")
    def files() -> dict:
        from seshat.query.files import build_tree, code_files, file_stats

        with store() as s:
            stats = file_stats(s)
        return {"tree": build_tree(code_files(root, config), stats)}

    @app.get("/api/files/changes")
    def file_changes(limit: int = 30) -> dict:
        from seshat.query.files import recent_changes

        with store() as s:
            return {"changes": recent_changes(s, limit=limit)}

    @app.get("/api/files/history")
    def file_history(path: str) -> dict:
        from seshat.query.files import file_history as history

        with store() as s:
            return {"path": path, "sessions": history(s, path)}

    @app.post("/api/links")
    def add_link(req: LinkRequest) -> dict:
        from seshat.papers.ingest import PaperIngestError

        try:
            paper_id = link_ingestor(req.url)
        except PaperIngestError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if paper_id is None:
            raise HTTPException(status_code=409, detail="That URL is already added.")
        with store() as s:
            paper = s.get_paper(paper_id)
        return {
            "id": paper.id,
            "title": paper.title,
            "path": paper.path,
            "added_at": paper.added_at,
            "source": "url",
        }

    if STATIC_DIR.exists():
        from fastapi.staticfiles import StaticFiles

        app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")

    return app
