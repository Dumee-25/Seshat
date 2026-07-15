# Seshat Cockpit — design

*A research workspace that sits alongside your editor.*

The cockpit turns Seshat from a background memory layer into a place you open: one window for a research project, with organized surfaces for papers, links, data, and code, a chat that answers across all of it, and a timeline that ties everything together. You keep writing code in VS Code and Jupyter — the cockpit is where you *see* the project, not where you edit it.

## 1. The founding constraint still holds

Seshat's original thesis was **zero required input; capture is passive**, because researchers stop journaling after a few days. The cockpit does not break that. The passive watcher and the automatic journal keep running underneath exactly as they do now. The cockpit is an *active* surface layered on top of a *passive* substrate:

- The substrate (watcher, journal, store) demands nothing and runs itself.
- The cockpit is where you go when you *want* to look — to browse, search, read, and ask.

This is the line that keeps Seshat from becoming "another tool you have to feed." An IDE is something you must live in; the cockpit is something you glance at.

**Explicit non-goal: it is not an editor.** No code editing, no language server, no kernels. Researchers do not leave VS Code, and rebuilding it badly is a multi-year fight with no payoff. The cockpit complements the editor; it never competes with it.

## 2. The timeline is the spine

Everything Seshat records is already a timestamped event: raw events, sessions, journal entries, papers (`added_at`), artifacts (`created_at`), commits. The cockpit is organized around a single **activity timeline** that merges all of them into one feed — *what has happened and what is happening now*.

Every other surface is a lens on that spine:

- **Papers & links** = the timeline filtered to reading.
- **Code** = the timeline filtered to changes.
- **Data** = the timeline filtered to produced artifacts.
- **Chat** citations are jumps *into* the timeline — every answer links back to the moment it draws on.

This is not a feature bolted onto the data model; it is the view the data model was already shaped for. The live "happening now" tail is what makes the cockpit feel alive: save a notebook, and the event appears at the top of the feed within seconds.

## 3. Surfaces

| Surface | What it does | Backend status |
|---|---|---|
| **Timeline** | Unified, filterable feed of every event; live tail of current activity. | Data exists (all events timestamped); needs a merge query + live stream. |
| **Chat** | One RAG chat answering across papers, links, data, and code, with citations into the timeline. | Query engine, retrieval, citations exist. Extend to span all sources. |
| **Papers & links** | Browse and read ingested PDFs; **add a URL** (arxiv, blog, docs) as a new source. | Paper ingestion exists. **URL ingestion is new** but reuses the pipeline. |
| **Code** | File tree plus recent changes, each linked to the session/entry that touched it. | Watcher captures all of this; needs a read API + panel. |
| **Data** | Preview and track datasets and results (CSV/JSON) as artifacts. | `results/` watched; Artifact nodes exist. Needs preview UI. |

Roughly 70% of the backbone already exists. The bulk of the work is UI plus one new ingestion source (links).

## 4. The one new source: links

`POST /api/links {url}` → fetch the page → extract the main content → chunk → embed into the shared vector store, recorded as a source node with `kind = "link"` and its own `added_at`. It reuses the paper chunking/embedding path wholesale; only fetch + main-content extraction are new. Time-proximity linking to sessions works the same way it does for papers. Extraction quality varies by site and some sites block fetching — the first version stays simple (fetch + readability-style extraction) and improves from real use.

## 5. Architecture

The cockpit is the React frontend the earlier phases were building toward. The desktop shell (pywebview + tray + watcher + installer) from Phases A–C is the container; only the *contents* of the window changed from Streamlit to React. As of phase 6 that swap is complete: the Streamlit UI is gone, and `seshat app` serves the cockpit.

```
pywebview window  ─►  React app (Vite build)  ◄─►  FastAPI  ─►  Store / QueryEngine / VectorStore
        ▲                                                              │
   system tray  ◄──────────────  WatchService (background thread) ─────┘
```

- **FastAPI** — a thin HTTP layer over the *existing* store and query engine. It adds no new intelligence; it exposes what is already there. Runs on localhost, on a background thread inside the app process.
- **React + Vite + TypeScript** — the workspace. The "kohl" theme carries over. Components are hand-rolled and the CSS is hand-written (the surface count is small; Tailwind was not worth the build step).
- **pywebview** — in development the window points at the Vite dev server; in a build, FastAPI serves the compiled static files and the window points at FastAPI.

### API surface

Built, as of phase 6:

```
GET  /api/health                     liveness, for the window's readiness probe
GET  /api/status                     watcher state, queued count (polled)
GET  /api/timeline?since=&kinds=     merged activity feed
GET  /api/sessions/{id}              session detail + raw events
POST /api/chat                       question -> cited answer
GET  /api/chat/history               persisted conversation
POST /api/chat/clear                 forget the conversation
GET  /api/papers                     ingested papers + links
GET  /api/papers/{id}                reader content
POST /api/links                      ingest a URL
GET  /api/files                      project file tree
GET  /api/files/changes              recent changes, linked to sessions
GET  /api/files/history?path=        one file's change history
GET  /api/data                       results/artifacts
GET  /api/data/{id}                  artifact preview + producing sessions
POST /api/entries/{id}/intent        confirm / correct an inferred intent
```

Still deferred:

```
GET  /api/events/stream              server-sent events for the live tail
```

The live tail is a 5-second poll of `/api/timeline` for now. It is good enough that SSE has not earned its plumbing yet; new rows flash in on arrival either way.

### What is reused unchanged

The SQLite store, the vector store, the query engine, the graph (edges + Artifact nodes), and the watcher all stay as they are. The timeline needs one new store method that merges event sources by time; the chat needs retrieval widened to include links. Everything else is additive UI.

## 6. Opening a project

The cockpit implies "start / open a project." A light version is in scope: a folder picker that runs `seshat init` if needed and remembers the choice (the `~/.seshat/app.toml` default-project mechanism already exists). Switching between multiple projects in one window, and watching several at once, stay deferred.

## 7. Build plan

Highest reuse and value first, so the cockpit feels real early.

1. ~~**Shell + timeline.**~~ *Done.* FastAPI skeleton, React/Vite app inside the pywebview window, the merged timeline endpoint and view, and live status. This forces the whole stack into place and delivers the spine.
2. ~~**Chat over everything.**~~ *Done.* Bring the query engine into the workspace; citations jump into the timeline.
3. ~~**Papers & links.**~~ *Done.* Reader for PDFs plus URL ingestion.
4. ~~**Code panel.**~~ *Done.* File tree + recent changes linked to sessions.
5. ~~**Data panel.**~~ *Done.* Results/artifact preview and tracking.
6. ~~**Package & retire Streamlit.**~~ *Done.* The build script builds the React app and the PyInstaller spec bundles it beside FastAPI; the spec refuses to freeze without it. `seshat app` now serves the cockpit, and `seshat ui`, `seshat/ui/`, the Streamlit server, and the `ui` extra are gone. Intent confirm/correct — the one thing Streamlit could do that the cockpit could not — moved to `POST /api/entries/{id}/intent` and into the timeline rows first, so nothing was lost in the swap.

Each phase ships behind the same PR-per-phase, CI-green rhythm as the rest of the project. The Streamlit UI kept working until step 6, so the tool was never broken mid-build.

## 8. Honest hard parts

- **Two-language build.** *Settled.* `build.ps1` builds the static assets before freezing rather than committing them, and the spec hard-fails if they are missing — the failure mode this risked (shipping a backend with no UI) is now a build error, not a blank window. The cost is that the build box needs Node.
- **Scope discipline on the frontend.** A React app invites sprawl. The fixed surface list above is the whole v1 — no editor, no settings pages, no dashboards beyond the five surfaces.
- **Link extraction.** Web content is messy; some sites block fetching. Start simple, accept imperfection, improve from real use.
- **Live tail.** *Deferred.* A 5-second poll turned out to be enough; SSE's plumbing across FastAPI, the store, and React has not paid for itself yet.
- **It is the biggest rock yet.** The backbone exists, but a real frontend codebase is the largest new surface the project has taken on. It is a multi-phase build, not a weekend.

## 9. Still deferred

In-app code editing and execution; multiple projects open at once; team/collaboration mode; Zotero sync; MLflow parsing; methods-section drafting; the contradiction detector. These remain out of scope for the cockpit v1.
