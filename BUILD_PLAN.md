# Seshat — Build Plan

Working plan for the MVP described in [Seshat.md](Seshat.md). Scoped to roughly a semester (~14 weeks), ordered so every phase produces something runnable and each layer feeds the next.

---

## Repo layout (target)

```
seshat/
├── seshat/
│   ├── __init__.py
│   ├── cli.py              # seshat init / watch / backfill / reprocess / ui
│   ├── config.py           # seshat.toml loading, defaults, ignore rules
│   ├── watcher/
│   │   ├── daemon.py       # watchdog observer, event routing
│   │   ├── notebooks.py    # cell-level diffing (nbdime internals + custom logic)
│   │   ├── scripts.py      # git hook handler + uncommitted-change tracking
│   │   ├── results.py      # plain results-folder indexer (CSV/JSON as text)
│   │   └── sessions.py     # idle-gap session grouping
│   ├── store/
│   │   ├── db.py           # SQLite: raw events (immutable), entries, graph edges
│   │   ├── vectors.py      # ChromaDB wrapper, bge-small-en-v1.5 embeddings
│   │   └── schema.py       # entry schema, migrations
│   ├── inference/
│   │   ├── queue.py        # idle-GPU job queue (pynvml)
│   │   ├── provider.py     # provider-agnostic LLM interface (local / API)
│   │   ├── journal.py      # session → journal entry generation
│   │   └── prompts.py      # versioned prompt templates
│   ├── papers/
│   │   ├── ingest.py       # watched PDF folder, PyMuPDF extraction, chunking
│   │   └── linking.py      # time-proximity linking into session context
│   ├── backfill/
│   │   └── git_history.py  # commits → pseudo-sessions → inference pipeline
│   └── ui/
│       └── app.py          # Streamlit chat + timeline + citations
├── tests/
├── pyproject.toml
├── Seshat.md               # design doc
└── BUILD_PLAN.md           # this file
```

---

## Phase 0 — Scaffolding (week 1)

Everything else assumes this exists.

- [x] Package skeleton (`pyproject.toml`, `seshat/` layout above, `pytest` wired up).
- [x] `seshat init`: creates `seshat.toml` in a project root with default include/exclude globs (respect `.gitignore`; always ignore `.venv/`, `data/`, `mlruns/`, checkpoints, files > 5 MB).
- [x] Config loader with validation and sane errors.
- [x] CI: GitHub Actions running tests on Windows + Linux (Windows is the dogfooding platform; Linux must stay green).

**Exit criteria:** `pip install -e .` works, `seshat init` produces a valid config, CI is green on both platforms.

## Phase 1 — Store (week 2)

Built *before* the watcher so events have somewhere to land from day one.

- [x] SQLite schema: `raw_events` (immutable, append-only), `sessions`, `entries` (with `model_version`/`prompt_version` stamps), `edges`, `artifacts`.
- [x] Entry schema from Seshat.md §3 implemented in `schema.py`.
- [x] ChromaDB collection setup + `bge-small-en-v1.5` embedding wrapper (CPU).
- [x] Migration story: schema version table, forward-only migrations.

**Exit criteria:** round-trip tests — write raw events, read them back, embed and query a document.

## Phase 2 — Watcher (weeks 3–6, the biggest chunk)

Most of the edge-case debugging lives here. Build in this order:

- [x] **2a. Filesystem daemon** — `seshat watch` foreground process, `watchdog` observer honoring the config ignore rules. Debounce rapid saves.
- [x] **2b. Notebook diffing** — on save, cell-level diff against last indexed version. Handle: reordered cells, deleted-then-recreated cells, kernel restarts, out-of-order execution counts. Capture outputs with aggressive truncation (dataframes → head + shape, images → reference only, errors → full traceback).
- [x] **2c. Script tracking** — post-commit git hook installer + watcher fallback for uncommitted changes.
- [x] **2d. Results folder** — index CSV/JSON files as searchable artifact text. No schema parsing.
- [x] **2e. Session grouping** — 45-minute idle-gap heuristic closes a session and emits a `session_closed` event. Configurable threshold.

**Exit criteria:** a real work session on a sample notebook project produces a coherent, correctly-bounded session with cell-level diffs and truncated outputs in SQLite.

## Phase 3 — Journal generation (weeks 7–9)

- [x] Provider-agnostic LLM interface; first backend: local Qwen3-8B-class model, quantized for 6 GB VRAM.
- [x] Idle-GPU queue: jobs enqueue on `session_closed`, worker runs only when GPU is idle (`pynvml` VRAM/activity check). CPU fallback behind a config flag.
- [x] Journal prompt: session diffs + outputs → `what_changed`, `observable_outcome`, `inferred_intent` (+ confidence). Prompts versioned in `prompts.py`.
- [x] Entries embedded into ChromaDB on write.
- [x] `seshat reprocess`: regenerate entries from raw events for a given model/prompt version.

**Exit criteria:** close a session, come back later, find a journal entry that correctly describes what changed — with intent clearly marked as inferred.

## Phase 4 — Backfill (week 10)

- [x] `seshat backfill`: walk git history, group commits into pseudo-sessions by commit-time gaps, feed through the Phase 3 pipeline.
- [x] Progress reporting + resumability (backfilling months of history through a local 8B model takes hours).

**Exit criteria:** run against an existing real project repo; day-one timeline is populated and entries are plausible.

## Phase 5 — Paper ingestion (week 11)

- [x] Watched PDF folder → PyMuPDF extraction → chunk → embed into the shared ChromaDB collection.
- [x] Time-proximity linking: papers added within ~7 days before a session get a low-confidence edge and are included in that session's inference context.

**Exit criteria:** drop a paper in the folder, make a related code change, and the resulting journal entry references the paper.

## Phase 6 — Query interface (weeks 12–13)

- [x] Streamlit app: chat pane + session timeline.
- [x] Hybrid retrieval: vector search over entries + paper chunks, structured filters (date range, file path, metric mentions).
- [x] Every answer cites its sessions; clicking a citation shows the underlying diff and outputs.
- [x] Basic edit button on entries (`intent_status`: inferred → confirmed/corrected). Nothing fancier.

**Exit criteria:** the four flagship queries from Seshat.md §2 return correct, cited answers on the dogfood project.

## Phase 7 — Evaluation & dogfooding (week 14 → ongoing)

Tooling (built):

- [x] `seshat eval --questions <file>`: measures citation + answer accuracy against a ground-truth question set (`--retrieval-only` works without an LLM). Example set: `eval/questions.example.json`.
- [x] `seshat audit`: interactive correct/partial/wrong labeling of inferred intents; labels update entries and accumulate in `.seshat/audit_log.jsonl`.
- [x] `seshat stats`: capture counts, intent-status breakdown, audit rates, and queries per week (chat queries are logged automatically; eval queries are excluded).

The actual evaluation (ongoing, on a real project):

- [ ] Write the ~50-question ground-truth set over a known project history; run `seshat eval` and track accuracy.
- [ ] Audit 100 real journal entries; watch the correct-rate trend as corrections accumulate.
- [ ] Four weeks of dogfooding: `seshat stats` queries-per-week must rise, or the capture layer isn't earning its keep.

---

## Dependency graph

```
Phase 0 ─→ Phase 1 ─→ Phase 2 ─→ Phase 3 ─→ Phase 4
                          │           ├────→ Phase 5
                          └───────────┴────→ Phase 6 ─→ Phase 7
```

Phases 4 and 5 are independent of each other and can swap order if a deadline demands it. Phase 6 needs Phase 3's entries but can start with backfilled data before 5 lands.

## Explicitly deferred (do not build in MVP)

Zotero sync · MLflow parsing · paper highlights + explicit citation edges · correction loop beyond the edit button · multi-project support · service/daemon packaging · React frontend · collaboration features.
