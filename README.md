# Seshat

A local-first research memory layer. Seshat watches a researcher's working files (notebooks, scripts, experiment outputs, papers), reconstructs what was tried and why after each work session, and makes the entire history searchable through a chat interface.

The question it exists to answer: **"What did I already try, and why did it fail?"**

Named after the Egyptian goddess of records, writing, and measurement. Built for student researchers and solo academics running ML and data science experiments.

## The problem

Every tool in the research workflow captures artifacts but not reasoning. Git captures code changes, but not why you made them. Experiment trackers capture that run 47 scored 0.83 AUC, but not that you tried class weighting because a paper suggested it. Notebooks capture the final state of your experimentation, which is misleading: cells run out of order, dead ends get deleted.

The reasoning lives in the researcher's head, and it decays. Manual journaling does not fix this because nobody keeps it up. Seshat's core design constraint follows from that:

**Zero required input. Capture is passive.**

## How it works

Seshat is a pipeline of four layers, each feeding the next:

1. **Capture.** `seshat watch` runs a filesystem watcher over the project. Notebook saves are diffed at the cell level (robust to reordered cells, kernel restarts, and deleted-then-recreated cells), script saves become unified diffs, commits arrive through a post-commit git hook, and CSV/JSON files in the results folder are indexed as searchable text. Large outputs are truncated at capture time. Events are grouped into work sessions by an idle-gap heuristic (default 45 minutes) and stored in SQLite as immutable, append-only raw events.

2. **Journaling.** When a session closes, it enters an inference queue. A local LLM (Ollama, default `qwen3:8b`) writes a structured journal entry: *what changed*, *observable outcome*, and *inferred intent* -- explicitly marked as a guess with a confidence score, correctable in one click. The queue runs only while the GPU is idle, so journal generation never competes with a training job. Because raw events are immutable and every entry is stamped with model and prompt versions, `seshat reprocess` can regenerate the whole journal after a model or prompt upgrade.

3. **Paper linkage.** PDFs dropped into the papers folder are extracted, chunked, and embedded into the same vector store. A paper added within roughly a week before a session is linked to it with a low-confidence edge, and its most relevant passages are provided to the journal model -- connecting what you read to what you changed.

4. **Query.** `seshat cockpit` opens a chat over the whole history. Retrieval is hybrid: vector search over journal entries and paper chunks combined with structured filters (file path, date range). Every answer cites the sessions it draws on, and each citation expands to the underlying diffs and outputs, so trust never rests on the model's word alone.

Everything runs locally and in a single SQLite file: the store, the graph, and the vector index (via `sqlite-vec`) all live in one `.seshat/seshat.sqlite3`. Ollama serves both generation and embeddings, so there is no heavyweight ML runtime to install. Nothing leaves the machine, including telemetry. Users who prefer quality over privacy can point the provider at any OpenAI-compatible API instead.

## Installation

Requires Python 3.11+. Seshat is not on PyPI yet; install it straight from this repository:

```
python -m pip install "seshat[cockpit] @ git+https://github.com/Dumee-25/Seshat.git"
```

Or, from a local clone (editable, so updates apply without reinstalling):

```
git clone https://github.com/Dumee-25/Seshat.git
python -m pip install -e "Seshat[cockpit]"
```

The `cockpit` extra pulls FastAPI for the workspace; without it you get capture and the CLI. Add the `desktop` extra (`seshat[desktop]`, which includes `cockpit`) for the native desktop app. There is no separate embeddings extra — embeddings run through Ollama.

The cockpit's React frontend is built from `frontend/` (`npm ci && npm run build`); a packaged install ships it prebuilt.

For generation and search, install [Ollama](https://ollama.com) and pull both models:

```
ollama pull qwen3:8b          # journal generation
ollama pull nomic-embed-text  # search embeddings
```

Note for Windows/conda users: prefer `python -m pip` over bare `pip` — the `pip.exe` shim in conda environments is sometimes blocked by antivirus ("Access is denied").

## Quick start

From your research project's root directory:

```
seshat init            # create seshat.toml with sensible defaults
seshat backfill        # build a timeline from existing git history
seshat install-hooks   # record future commits automatically
seshat watch           # start capturing (leave running while you work)
```

Then, in a second terminal whenever you want answers:

```
seshat cockpit         # the workspace: timeline, chat, papers, code, data
```

Journal entries are generated in the background while `seshat watch` runs, or on demand with `seshat process`.

### Desktop app

With the `desktop` extra installed, a single command replaces the separate watch and UI terminals:

```
seshat app
```

It opens a native window for the chat and timeline, and runs the watcher in the background behind a system-tray icon. The tray shows status (watching, and how many sessions are queued for journaling), can pause capture, opens the window on demand, and quits everything cleanly. On Windows the window uses the built-in WebView2 runtime — no browser tab, no extra download.

To build a double-click Windows installer (`SeshatSetup.exe`) from source, see [packaging/README.md](packaging/README.md).

## Commands

| Command | Purpose |
|---|---|
| `seshat app` | Launch the desktop app: native window plus a background, tray-based watcher. |
| `seshat setup` | Check Ollama and pull the models Seshat needs (`--no-pull` to only report). |
| `seshat autostart` | Run the desktop app at login (`--enable` / `--disable` / `--status`, Windows). |
| `seshat init` | Create the project configuration (`seshat.toml`). |
| `seshat watch` | Watch the project and capture work sessions. `--no-journal` captures without generating entries. |
| `seshat backfill` | Ingest existing git history as pseudo-sessions. Safe to re-run; already-ingested commits are skipped. |
| `seshat install-hooks` | Install the post-commit hook that records commits. |
| `seshat process` | Generate journal entries for all queued sessions. `--force` ignores the GPU-idle check. |
| `seshat reprocess` | Regenerate entries from raw events after a model or prompt upgrade. |
| `seshat cockpit` | Open the research cockpit (timeline, chat, papers, code, data). `--no-window` serves the API only, for frontend development. |
| `seshat eval` | Measure retrieval and answer accuracy against a ground-truth question set (see `eval/questions.example.json`). |
| `seshat audit` | Label a sample of inferred intents correct/partial/wrong; tracks intent accuracy over time. |
| `seshat stats` | Capture counts, intent-status breakdown, audit rates, and queries per week. |

## Configuration

`seshat init` writes a commented `seshat.toml`. The defaults respect `.gitignore`, always ignore heavyweight directories (`.venv/`, `data/`, `mlruns/`, checkpoints), skip files over 5 MB, close sessions after 45 idle minutes, and use the local Ollama provider. All of it is adjustable:

```toml
[watch]
include = ["**/*.ipynb", "**/*.py"]
results_dir = "results"
papers_dir = "papers"

[session]
idle_gap_minutes = 45

[inference]
provider = "local"     # "local" (Ollama) or "api" (OpenAI-compatible)
model = "qwen3:8b"
embed_model = "nomic-embed-text"
```

All Seshat state lives in `.seshat/` inside the project, which is gitignored by default.

## Design notes

- **Raw events are append-only.** Journal entries are derived data and can always be regenerated; the diffs themselves never lie and are never mutated.
- **Wrong guesses are cheap.** Roughly a third of intent inferences are expected to be wrong early on. Every guess is labeled as such, correctable in one click, and even a wrong entry remains searchable by its factual content.
- **Capture never dies.** Failures in journaling, embeddings, or individual files are logged and retried; the watcher keeps running.
- **The honest metric.** If `seshat stats` does not show voluntary queries rising week over week, the capture layer is not earning its keep.

## Development

```
pip install -e .[dev]
pytest
ruff check .
```

CI runs the test suite and linter on Windows and Linux, Python 3.11 and 3.12.

## License

MIT
