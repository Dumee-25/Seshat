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
GET  /api/status                     watcher state, queued count, and whether
                                     a busy GPU is what is holding the queue
GET  /api/setup                      is Ollama reachable, which models are
                                     missing (read-only; never pulls)
GET  /api/timeline?since=&kinds=     merged activity feed; also `q` (text search
     &q=&limit=&offset=              over titles, outcomes, and intents),
                                     `limit`/`offset`, and a `total` in the
                                     response so the feed knows there is more
GET  /api/sessions/{id}              session detail + raw events
POST /api/chat                       question -> cited answer
GET  /api/chat/history               persisted conversation
POST /api/chat/clear                 forget the conversation
GET  /api/papers                     ingested papers + links
GET  /api/papers/{id}                reader content
POST /api/links                      ingest a URL
POST /api/open-external              hand an http(s) link to the system browser
GET  /api/files                      project file tree
GET  /api/files/changes              recent changes, linked to sessions
GET  /api/files/history?path=        one file's change history
GET  /api/data                       results/artifacts
GET  /api/data/{id}                  artifact preview + producing sessions
POST /api/entries/{id}/intent        confirm / correct an inferred intent
POST /api/entries/{id}/intent/reset  undo that, restoring the model's guess
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
6. ~~**Package & retire Streamlit.**~~ *Done.* The build script builds the React app and the PyInstaller spec bundles it beside FastAPI; the spec refuses to freeze without it. `seshat app` now serves the cockpit, and `seshat ui`, `seshat/ui/`, the Streamlit server, and the `ui` extra are gone. Intent confirm/correct moved to `POST /api/entries/{id}/intent` and into the timeline rows first. One capability did not survive the swap — expanding an entry into its underlying diffs — because the parity check stopped at the first gap it found instead of enumerating what the old UI could do. Step 7 put it back.

7. ~~**Depth on the spine.**~~ *Done.* The timeline stopped being a fixed window onto the last 100 events and became something you can actually search and walk:
   - **Session evidence.** Every session row expands into its raw events — notebook cell diffs, script and commit diffs in red/green, result-file previews — restoring the parity gap from step 6. Landing on a row from a citation opens the evidence with it, so "check the guess against the diff" is one click from the answer that made the guess.
   - **Search, filters, paging.** A text search over titles, outcomes, and intents; kind chips; a time-range selector; and a "load more" that reports how many matches it is drawing from. Answering "have I tried SMOTE?" no longer costs a local generation pass.

   The timeline also became self-fetching in the process: filter state, paging, and its poll live in `Timeline.tsx` rather than being threaded down from `App.tsx`.

8. ~~**Legibility of the answer surface.**~~ *Done.* The chat worked but read badly, and two of its controls were traps:
   - **Citations name themselves.** "Aug 1 · Added SMOTE oversampling…" instead of "session 12" — the date and the summary were already fetched and only used as a tooltip. A session id tells a reader nothing about whether to trust an answer.
   - **Answers render as markdown.** A small hand-rolled renderer (`markdown.tsx`) covers what local models actually emit — headings, lists, fenced code, emphasis. It builds React elements, so nothing a model writes can inject markup, and it deliberately leaves `region_code`, `k_neighbors`, and `2 * 3` alone rather than reading them as emphasis.
   - **`Clear` takes two steps.** It sat beside `Ask` and erased the conversation on a single misclick.
   - **A question can be cancelled**, and the wait shows elapsed seconds so a slow local model does not look hung.
   - **The input is multi-line** (Enter sends, Shift+Enter breaks).
   - **Reader links open in the system browser** via `POST /api/open-external`. The desktop window has no chrome, so following a link in place replaced the cockpit with a web page the user could not get back from.

9. ~~**Say what is actually happening.**~~ *Done.* The cockpit was confidently wrong in several places at once:
   - **The status bar told the truth.** A failed poll left the stale status in place, so the footer kept saying "Connected" with a cheerfully pulsing dot while nothing was reaching the server. It now reports the *last poll*, keeps the last known counts (they are still the most recent truth), and colours the dot accordingly.
   - **A stalled queue explains itself.** `/api/status` reports whether a busy GPU is the reason nothing is draining, so "3 queued" that never moves during a training run reads as the design working rather than the tool being broken.
   - **Panels stopped swallowing failures.** `Code` and `Data` caught errors into `() => {}`, so a dead backend rendered as "No watched code files" — asserting the opposite of the truth. Every panel now distinguishes "could not load" from "nothing here", and a load failure never falls through to an empty state.
   - **A broken install is visible.** `GET /api/setup` (read-only; it never pulls) backs a banner naming what is wrong and the command that fixes it. Journaling fails silently by design, because capture must survive it — this is what stops that silence from looking like nothing happening.
   - **Everything is keyboard reachable.** Nav entries and every row are real `<button>`s with focus styling and ARIA state, not `div`s with `onClick`.
   - **Triage is cheap and reversible.** Timeline rows take focus; `↑↓`/`j`/`k` move, `c` confirms, `e` edits, `u` undoes, `Enter` opens the evidence. Undo is backed by schema v7 (below).

   **Schema v7 — `entries.model_intent`.** Correcting an intent used to overwrite `inferred_intent`, destroying what the model had actually guessed. That made corrections irreversible and quietly cost the audit trail its ground truth. The model's guess is now stored separately, written once at entry creation and never again.

Each phase ships behind the same PR-per-phase, CI-green rhythm as the rest of the project. The Streamlit UI kept working until step 6, so the tool was never broken mid-build.

## 8. Honest hard parts

- **Two-language build.** *Settled.* `build.ps1` builds the static assets before freezing rather than committing them, and the spec hard-fails if they are missing — the failure mode this risked (shipping a backend with no UI) is now a build error, not a blank window. The cost is that the build box needs Node.
- **Scope discipline on the frontend.** A React app invites sprawl. The fixed surface list above is the whole v1 — no editor, no settings pages, no dashboards beyond the five surfaces.
- **Link extraction.** Web content is messy; some sites block fetching. Start simple, accept imperfection, improve from real use.
- **Live tail.** *Deferred.* A 5-second poll turned out to be enough; SSE's plumbing across FastAPI, the store, and React has not paid for itself yet.
- **It is the biggest rock yet.** The backbone exists, but a real frontend codebase is the largest new surface the project has taken on. It is a multi-phase build, not a weekend.

## 9. Still deferred

**Search is substring, not semantic.** The timeline's search matches literal text in titles, outcomes, and intents. It is instant and needs no model, which is the point — but "class imbalance" will not find an entry that only ever says "the minority class was ignored". The vector store already holds journal embeddings for chat retrieval; wiring it into the timeline search as a second, slower pass is the obvious next step. Substring search first because it answers most lookups and costs nothing.

**Filters do not survive a restart.** Kind chips, time range, and the search box reset when the window closes. Persisting them (or putting them in the URL) is cheap and has not been done.

**Answers arrive whole, not streamed.** `POST /api/chat` returns once the model is finished, so a long answer shows nothing until all of it exists. A cancel button and an elapsed-seconds counter make the wait honest, which is most of the benefit for a fraction of the work — real streaming needs SSE through FastAPI, the provider, and React, the same plumbing the live tail has not yet justified.

**There is no "process now" button, deliberately.** Surfacing *why* the queue is stalled was the easy half; letting the cockpit drain it is not. `InferenceWorker.run_pending` has no claim on a session — `generate_entry` reads a closed session and writes an entry unconditionally — so a second worker triggered from the API would race the watcher's own 30-second drain and write two entries for one session. Making that safe needs a lease on the queue (claim `closed` → `processing` and hand stranded claims back after a crash), which is a change to the queue's contract, not a UI affordance. Until then the cockpit reports the state and `seshat process --force` remains the way to override it.

**Opening a project from the window is still unbuilt** (§6). The health banner tells a user what is wrong with their *install*; it does not help them point the cockpit at a different folder.

**The frontend has no test suite.** `markdown.tsx` is hand-rolled parsing and the riskiest logic in the UI; it was verified against adversarial fixtures in a browser, not by tests. Adding vitest is a toolchain decision worth making deliberately rather than smuggling into a UX change.

Genuinely out of scope for cockpit v1: in-app code editing and execution; multiple projects open at once; team/collaboration mode; Zotero sync; MLflow parsing; methods-section drafting; the contradiction detector.
