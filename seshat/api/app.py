"""The cockpit API: a thin HTTP layer over the existing store.

It adds no new intelligence — it exposes what Seshat already records. A fresh
Store is opened per request (cheap for SQLite, and it sidesteps sharing a
connection across FastAPI's threadpool). The built React app, if present, is
served at the root; in development the frontend runs on Vite and calls this
API cross-origin.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from seshat.config import SeshatConfig
from seshat.query.timeline import KINDS, build_timeline
from seshat.store.db import Store

STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app(root: Path, config: SeshatConfig) -> FastAPI:
    root = Path(root)
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
        from seshat.store.db import StoreError

        with store() as s:
            try:
                session = s.get_session(session_id)
            except StoreError:
                from fastapi import HTTPException

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

    if STATIC_DIR.exists():
        from fastapi.staticfiles import StaticFiles

        app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")

    return app
