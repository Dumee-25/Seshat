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

4. **Query.** `seshat ui` opens a chat over the whole history. Retrieval is hybrid: vector search over journal entries and paper chunks combined with structured filters (file path, date range). Every answer cites the sessions it draws on, and each citation expands to the underlying diffs and outputs, so trust never rests on the model's word alone.

Everything runs locally: SQLite and ChromaDB for storage, `bge-small-en-v1.5` on CPU for embeddings, Ollama for generation. Nothing leaves the machine, including telemetry. Users who prefer quality over privacy can point the provider at any OpenAI-compatible API instead.

## Installation

Requires Python 3.11+. Seshat is not on PyPI yet; install it straight from this repository:

```
python -m pip install "seshat[embeddings,ui] @ git+https://github.com/Dumee-25/Seshat.git"
```

Or, from a local clone (editable, so updates apply without reinstalling):

```
git clone https://github.com/Dumee-25/Seshat.git
python -m pip install -e "Seshat[embeddings,ui]"
```

The extras are optional: `embeddings` pulls the local embedding model (needed for search and journaling), `ui` pulls Streamlit (needed for the chat interface). Without extras you get capture only.

For journal generation, install [Ollama](https://ollama.com) and pull a model (`ollama pull qwen3:8b`), or configure an API provider in `seshat.toml`.

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
seshat ui              # chat + timeline in the browser
```

Journal entries are generated in the background while `seshat watch` runs, or on demand with `seshat process`.

## Commands

| Command | Purpose |
|---|---|
| `seshat init` | Create the project configuration (`seshat.toml`). |
| `seshat watch` | Watch the project and capture work sessions. `--no-journal` captures without generating entries. |
| `seshat backfill` | Ingest existing git history as pseudo-sessions. Safe to re-run; already-ingested commits are skipped. |
| `seshat install-hooks` | Install the post-commit hook that records commits. |
| `seshat process` | Generate journal entries for all queued sessions. `--force` ignores the GPU-idle check. |
| `seshat reprocess` | Regenerate entries from raw events after a model or prompt upgrade. |
| `seshat ui` | Open the chat and timeline interface. |
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
