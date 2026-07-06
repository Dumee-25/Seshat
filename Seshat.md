# Seshat

*A research memory layer.*

A local-first app that watches a researcher's working files (notebooks, scripts, papers, experiment outputs), reconstructs what was tried and why, and makes all of it searchable. The question it exists to answer: *"What did I already try, and why did it fail?"*

Named after the Egyptian goddess of records, writing, and measurement — the archivist who kept the account of what happened. Target user: student researchers and solo academics running ML/data science experiments.

---

## 1. The problem

Every tool in the research workflow captures artifacts but not reasoning.

- Git captures code changes, but not why you made them.
- MLflow captures that run 47 scored 0.83 AUC, but not that you tried class weighting because a paper suggested it would help with your imbalance problem.
- Notebooks capture the final state of your experimentation, which is misleading: cells get run out of order, dead ends get deleted.
- Notion/Obsidian hold notes but can't see your code. Zotero knows your papers but not your experiments.

The reasoning lives in the researcher's head, and it decays. Three weeks after a session you can't remember whether you already tested XGBoost with that feature set, why you dropped a column in preprocessing, or which paper gave you the resampling idea. Undergrads doing their first serious research projects lose enormous time to re-running dead ends and reconstructing their own decisions.

Manual journaling doesn't fix this because nobody keeps it up. Researchers stop journaling after about four days of any tool that demands input. This gives the core design constraint for everything below:

**Zero required input. Capture must be passive.**

## 2. What the app does

It sits in the background, indexes everything you touch in a project, and after each work session writes a journal entry on your behalf: what changed, what the observable result was, and an inferred guess at *why* you did it. Papers you read get linked to the code changes they inspired. Then a chat interface answers questions over the whole history.

Queries it should handle well:

- "Have I tried SMOTE before?" → yes, sessions on March 3 and March 11, F1 went from 0.61 to 0.68, abandoned after it hurt precision.
- "Why is `region_code` dropped in preprocessing?" → traced to the session where it happened, with the inferred reason.
- "Show me every run where validation loss diverged." (In MVP this only covers metrics visible in notebook outputs or dropped into the results folder — see §7.)
- "Draft the methods section for the resampling experiments." The journal is raw material for the methods section, which is where the tool pays off hardest near a paper deadline.

## 3. Architecture

Four layers, each feeding the next.

### Layer 1: The watcher

A background daemon watching project directories.

- **Notebooks.** On save, diff against the last indexed version at the *cell* level, not the file level. Raw .ipynb JSON diffs are noise; `nbdime` gets partway there but session reconstruction from out-of-order execution needs custom logic. Capture cell outputs too: printed metrics, generated plots, thrown errors.
- **Scripts.** Git hooks (post-commit, or a filesystem watcher for uncommitted work).
- **Experiment outputs.** MVP: watch a plain results folder and index CSV/JSON files as searchable artifacts — no schema understanding, just text. MLflow directory parsing is deferred to post-MVP.

**Watch scope.** A per-project `seshat.toml` (created by `seshat init`) defines include/exclude globs. Defaults: respect `.gitignore`, and always ignore `.venv/`, `data/`, `mlruns/`, model checkpoints, and any file over a size threshold (~5 MB for text; binaries are skipped except notebook-embedded images). Without this, an ML project's gigabytes of artifacts would drown the watcher on day one.

Everything is timestamped. Events are grouped into "sessions" by activity gaps (e.g. a 45-minute idle threshold ends a session). Session boundary detection is heuristic and will sometimes merge two unrelated bursts of work; that's an accepted imperfection, not a blocker.

This layer is where most of the engineering time goes. The edge cases (kernel restarts, reordered cells, deleted-then-recreated cells, giant output blobs) are the real work.

### Layer 2: Reasoning inference

After each session closes, a local LLM receives the session's diffs and outputs and writes a structured journal entry. Inference jobs go into a queue and a worker runs them only when the GPU is idle (VRAM check via `pynvml`, or N minutes of no GPU activity) — the researcher's training job always wins. Entries are read hours or days later, so overnight processing is fine; CPU fallback is a config option, not a default.

The fixed entry schema:

```
entry: session_id, started_at, ended_at, files_touched[],
       what_changed, observable_outcome,
       inferred_intent, intent_confidence, intent_status (inferred|confirmed|corrected),
       linked_papers[], raw_event_ids[], model_version, prompt_version
```

Fields the LLM fills:

- **What changed** — "added SMOTE oversampling before the classifier."
- **Observable outcome** — "F1 on the minority class went from 0.61 to 0.68."
- **Inferred intent** — "addressing class imbalance." Marked as inferred, correctable with one click, never required.

Even a wrong guess ("changed the resampling strategy") is more searchable than nothing. Expect roughly 30% of intent guesses to be wrong early on; the UI has to make wrong guesses cheap rather than trust-destroying. Corrections also become fine-tuning or few-shot data over time.

**Reprocessing.** Raw session events (diffs, outputs) are stored immutably in SQLite, separate from generated entries. Every entry carries `model_version`/`prompt_version` stamps, and `seshat reprocess` regenerates entries from raw events — so when the model or prompt improves, the whole journal can be upgraded in place.

**Backfill.** `seshat backfill` reconstructs a timeline from existing git history: commits are grouped into pseudo-sessions by commit-time gaps and fed through the same inference pipeline. A new user gets a populated journal on day one instead of an empty tool. (Notebook-checkpoint reconstruction is skipped — `.ipynb_checkpoints` only holds the last state, so there's little history to mine.)

Intent inference improves sharply with cross-referencing: if the user highlighted a paper section about focal loss on Tuesday and added focal loss to the training script on Wednesday, the connection is nearly certain. That cross-referencing depends on Layer 3.

### Layer 3: Paper linkage

MVP scope: a watched PDF folder → PyMuPDF extraction → chunk and embed into the same vector store as journal entries, with *weak time-proximity linking* — a paper added within ~7 days before a session is included in that session's inference context and gets a low-confidence edge. Zotero sync, highlighted passages, and explicit citation edges are deferred; this keeps the paper-to-code connection working without the full graph machinery.

The resulting graph has three node types and typed edges:

| Node type | Examples |
|---|---|
| Paper | PDFs, chunks, highlighted passages |
| Session | journal entries with diffs and outcomes |
| Artifact | datasets, model checkpoints, figures |

Edges: `cites-idea-from` (session → paper), `produced` (session → artifact), `modified` (session → artifact), `supersedes` (session → session).

### Layer 4: Query interface

A chat over the graph. Retrieval is hybrid: vector search over journal entries and paper chunks, plus structured filters (date ranges, metric thresholds, file paths). Answers cite the underlying sessions so the user can click through to the actual diff.

## 4. Tech stack (MVP)

- **Watcher:** Python process (`seshat watch`, foreground/tray — packaging as a real service is post-MVP), `watchdog` for filesystem events, `nbdime` internals for notebook diffing, git hooks for scripts.
- **LLM:** a local ~8B model (Qwen3 8B class) for journal generation. Runs on a 6GB consumer GPU with quantization, scheduled via the idle-GPU queue (`pynvml`). Provider-agnostic layer so users can swap in an API model if they prefer quality over privacy.
- **Embeddings:** `bge-small-en-v1.5` via sentence-transformers — local and CPU-friendly, so the privacy claim holds end to end.
- **Store:** ChromaDB for embeddings; SQLite for the graph structure, metadata, and immutable raw events. Local-first, no server required.
- **Frontend:** Streamlit to start; a proper React front end only once the query patterns stabilize.
- **Paper ingestion:** PyMuPDF for extraction (Zotero API sync post-MVP).
- **Platform:** Windows-first (that's where dogfooding happens), Linux kept working via CI — all core libs are cross-platform.

Local-first matters here beyond privacy: research code is often under NDA, embargo, or just embarrassing, and "your half-broken experiments never leave your machine" is a genuine adoption argument.

## 5. Why this doesn't already exist

Three reasons, roughly in order:

1. **Feasibility is recent.** You need a local model good enough at code-diff summarization to run on consumer hardware. That's a 2024-onward capability.
2. **The money is elsewhere.** The obvious commercial players (Weights & Biases, MLflow's backers) monetize teams at companies. This problem bites hardest for solo researchers and students, who won't pay much.
3. **The plumbing is annoying.** Notebook diffing plus session reconstruction is fiddly enough that most people who start down this road quit before the interesting parts.

## 6. Honest hard parts and risks

- **Intent inference accuracy.** Wrong ~30% early. Mitigation: mark guesses as guesses, make correction one click, keep even wrong entries searchable by their factual content (the diff itself never lies).
- **Session boundaries.** Idle-gap heuristics will occasionally merge or split sessions wrongly. Acceptable if entries remain individually editable.
- **Cold start.** The tool is useless in week one and indispensable in month three. Mitigation: the git-only backfill importer (in MVP scope) reconstructs journal entries from existing git history, so a new user gets a populated timeline on day one.
- **GPU contention.** Journal generation shares the GPU with the researcher's training jobs. Mitigation: the inference queue only runs when the GPU is idle; latency doesn't matter because entries are read later, not live.
- **Output volume.** Cell outputs can be huge (dataframes, images). Need aggressive truncation and summarization before anything hits the LLM or the store.
- **Trust.** If the journal confidently states a wrong reason and the user acts on it, that's worse than no journal. Every answer must cite the underlying session and diff.

## 7. MVP scope

A realistic semester of work:

1. Watcher for notebooks + git + a plain results folder, with session grouping and `seshat.toml` watch-scope config. (Biggest chunk. Most of the edge-case debugging lives here.)
2. Journal generation with one local model, the fixed entry schema from §3, idle-GPU queueing, and raw events stored separately from entries (enables `seshat reprocess`).
3. Git-only backfill importer (`seshat backfill`) so the timeline is populated on day one.
4. Minimal paper ingestion: watched PDF folder, embedding, time-proximity linking into session inference.
5. ChromaDB + SQLite store.
6. Streamlit chat with citation links back to sessions.

Deliberately deferred: Zotero sync, MLflow parsing, paper highlights and explicit citation edges, the correction/feedback loop beyond a basic edit button, multi-project support, service/daemon packaging, any collaboration features.

## 8. How to evaluate it

- **Retrieval:** build a test set of ~50 questions about a known project history ("did I try X?", "when did metric Y first exceed Z?") with ground-truth answers; measure answer accuracy and citation correctness.
- **Intent inference:** sample 100 journal entries, have the researcher label each inferred intent correct/partially/wrong. Track the rate over time as corrections accumulate.
- **The real test:** after four weeks of dogfooding on an actual project, count how many times per week you query it voluntarily. If that number isn't rising, the capture layer isn't earning its keep.

## 9. Adjacent ideas (out of scope for v1)

- Methods-section drafting from journal entries, tuned to a target venue template.
- A "contradiction detector" that flags when a new experiment repeats a previously failed configuration.
- Team mode: shared memory across a group project, with per-member attribution.
- Export to a static HTML "lab notebook" for supervisors or reproducibility appendices.
