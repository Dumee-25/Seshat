"""Seshat command-line interface."""

from __future__ import annotations

from pathlib import Path

import click

from seshat import __version__
from seshat.config import ConfigError, load_config, write_default_config


@click.group()
@click.version_option(__version__, prog_name="seshat")
def main() -> None:
    """Seshat: a research memory layer.

    Watches your project, journals your sessions, and answers
    "what did I already try, and why did it fail?"
    """


@main.command()
@click.option(
    "--path",
    type=click.Path(file_okay=False, path_type=Path),
    default=".",
    help="Project root to initialize (default: current directory).",
)
@click.option("--name", default=None, help="Project name (default: directory name).")
@click.option("--force", is_flag=True, help="Overwrite an existing seshat.toml.")
def init(path: Path, name: str | None, force: bool) -> None:
    """Create a seshat.toml in the project root."""
    path.mkdir(parents=True, exist_ok=True)
    try:
        config_file = write_default_config(path, name=name, force=force)
        load_config(path)  # sanity-check what we just wrote
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Created {config_file}")
    click.echo("Edit the [watch] globs if needed, then run `seshat watch` to start capturing.")


def _make_vectors(config):
    from seshat.inference.provider import get_embedder
    from seshat.store.vectors import VectorStore

    return VectorStore(Path(".").resolve(), get_embedder(config))


def _make_worker(config, store, vectors=None):
    from seshat.inference.provider import get_provider
    from seshat.inference.queue import InferenceWorker

    return InferenceWorker(
        store,
        vectors if vectors is not None else _make_vectors(config),
        get_provider(config),
        cpu_fallback=config.inference.cpu_fallback,
        log=click.echo,
    )


@main.command()
@click.option(
    "--no-journal",
    is_flag=True,
    help="Capture only; don't generate journal entries while watching.",
)
def watch(no_journal: bool) -> None:
    """Watch the project and capture work sessions (Ctrl+C to stop)."""
    from seshat.store.db import Store
    from seshat.watcher.daemon import WatchService

    config = _require_config()
    root = Path(".").resolve()
    with Store.open(root) as store:
        vectors = _make_vectors(config)
        background = None
        if not no_journal:
            worker = _make_worker(config, store, vectors)
            background = lambda: worker.run_pending()  # noqa: E731
        service = WatchService(
            root, config, store, log=click.echo,
            background_task=background, vectors=vectors,
        )
        indexed = service.baseline_scan()
        click.echo(f"Baseline: {indexed} new file(s) snapshotted.")
        try:
            service.run()
        except KeyboardInterrupt:
            click.echo("Stopped.")


@main.command()
@click.option("--force", is_flag=True, help="Run even if the GPU is busy.")
def process(force: bool) -> None:
    """Generate journal entries for all captured-but-unprocessed sessions."""
    from seshat.store.db import Store

    config = _require_config()
    with Store.open(Path(".").resolve()) as store:
        worker = _make_worker(config, store)
        pending = worker.pending_sessions()
        if not pending:
            click.echo("Nothing to process.")
            return
        click.echo(f"{len(pending)} session(s) queued.")
        written = worker.run_pending(force=force)
        click.echo(f"Wrote {written} journal entr{'y' if written == 1 else 'ies'}.")


@main.command("install-hooks")
def install_hooks() -> None:
    """Install the post-commit git hook that records commits."""
    from seshat.watcher.scripts import install_post_commit_hook

    _require_config()
    try:
        hook = install_post_commit_hook(Path(".").resolve())
    except (FileNotFoundError, FileExistsError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Installed {hook}")


@main.command("record-commit", hidden=True)
def record_commit() -> None:
    """Record HEAD as a git_commit event (called by the post-commit hook)."""
    from seshat.store.db import Store
    from seshat.watcher.scripts import read_head_commit
    from seshat.watcher.sessions import SessionTracker

    config = _require_config()
    root = Path(".").resolve()
    payload = read_head_commit(root)
    with Store.open(root) as store:
        tracker = SessionTracker(store, config.session.idle_gap_minutes)
        session_id = tracker.on_event()
        event_id = store.append_event("git_commit", payload)
        store.assign_events_to_session([event_id], session_id)
    click.echo(f"Recorded commit {payload['hash'][:7]} (session {session_id})")


@main.command()
@click.option(
    "--process/--no-process",
    default=False,
    help="Also generate journal entries now (default: leave them queued).",
)
def backfill(process: bool) -> None:
    """Ingest existing git history as pseudo-sessions.

    Gives a new project a populated timeline on day one. Safe to re-run:
    already-ingested commits are skipped.
    """
    from seshat.backfill.git_history import BackfillError
    from seshat.backfill.git_history import backfill as run_backfill
    from seshat.store.db import Store

    config = _require_config()
    root = Path(".").resolve()
    with Store.open(root) as store:
        try:
            sessions, commits = run_backfill(
                root, store, config.session.idle_gap_minutes, log=click.echo
            )
        except BackfillError as exc:
            raise click.ClickException(str(exc)) from exc
        click.echo(f"Backfilled {commits} commit(s) into {sessions} session(s).")
        if not process:
            if sessions:
                click.echo(
                    "Journal entries are queued; run `seshat process` "
                    "(or just `seshat watch`) to generate them."
                )
            return
        worker = _make_worker(config, store)
        written = worker.run_pending()
        click.echo(f"Wrote {written} journal entr{'y' if written == 1 else 'ies'}.")


@main.command()
@click.option("--session", "session_id", type=int, default=None,
              help="Reprocess one session (default: every processed session).")
def reprocess(session_id: int | None) -> None:
    """Regenerate journal entries from stored raw events.

    Useful after a model or prompt upgrade: old entries are replaced, raw
    events are never touched.
    """
    from seshat.inference.journal import generate_entry
    from seshat.inference.provider import GenerationError, get_embedder, get_provider
    from seshat.store.db import Store
    from seshat.store.vectors import VectorStore

    config = _require_config()
    root = Path(".").resolve()
    with Store.open(root) as store:
        vectors = VectorStore(root, get_embedder(config))
        provider = get_provider(config)
        if session_id is not None:
            targets = [session_id]
        else:
            targets = [s.id for s in store.sessions(status="processed")]
        if not targets:
            click.echo("No processed sessions to reprocess.")
            return
        done = 0
        for sid in targets:
            try:
                entry = generate_entry(store, vectors, provider, sid)
            except GenerationError as exc:
                raise click.ClickException(f"session {sid}: {exc}") from exc
            if entry is not None:
                done += 1
                click.echo(f"session {sid}: entry {entry.id} ({provider.model_version})")
        click.echo(f"Reprocessed {done} session(s).")


@main.command()
def ui() -> None:
    """Open the chat + timeline interface in the browser."""
    import importlib.util
    import subprocess
    import sys

    from seshat.app.server import APP_SCRIPT, theme_env

    _require_config()
    if importlib.util.find_spec("streamlit") is None:
        raise click.ClickException(
            "streamlit is not installed. Run `pip install seshat[ui]` first."
        )
    subprocess.run(
        [sys.executable, "-m", "streamlit", "run", str(APP_SCRIPT)],
        check=False,
        env=theme_env(),
    )


@main.command()
def app() -> None:
    """Launch the Seshat desktop app: a native window plus a background,
    tray-based watcher (Ctrl+C or the tray's Quit to stop)."""
    import importlib.util

    config = _require_config()
    missing = [
        name
        for name in ("streamlit", "webview", "pystray", "PIL")
        if importlib.util.find_spec(name) is None
    ]
    if missing:
        raise click.ClickException(
            "The desktop app needs extra packages "
            f"({', '.join(sorted(missing))}). Install them with "
            "`pip install \"seshat[ui,desktop]\"`."
        )
    from seshat.app.desktop import run_desktop

    run_desktop(Path(".").resolve(), config, log=click.echo)


@main.command("eval")
@click.option("--questions", "questions_path", required=True,
              type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="JSON file of eval cases (see eval/questions.example.json).")
@click.option("--k", default=5, help="Citations retrieved per question.")
@click.option("--retrieval-only", is_flag=True,
              help="Skip answer generation; measure citation accuracy only (no LLM needed).")
@click.option("--json", "json_out", type=click.Path(dir_okay=False, path_type=Path),
              default=None, help="Also write the full report as JSON.")
def eval_command(questions_path: Path, k: int, retrieval_only: bool, json_out: Path | None):
    """Measure retrieval and answer accuracy against a ground-truth question set."""
    import json as jsonlib

    from seshat.eval.runner import EvalError, load_cases, run_eval
    from seshat.inference.provider import get_provider
    from seshat.query.engine import QueryEngine
    from seshat.store.db import Store

    config = _require_config()
    root = Path(".").resolve()
    with Store.open(root) as store:
        engine = QueryEngine(store, _make_vectors(config), get_provider(config))
        try:
            cases = load_cases(questions_path)
            report = run_eval(engine, cases, k=k, retrieval_only=retrieval_only)
        except EvalError as exc:
            raise click.ClickException(str(exc)) from exc

    for r in report.results:
        mark = {True: "PASS", False: "FAIL", None: "  - "}
        click.echo(
            f"[cite {mark[r.citation_ok]}] [answer {mark[r.answer_ok]}] {r.case.question}"
        )
        if r.citation_ok is False:
            click.echo(f"    expected sessions {r.case.expect_sessions}, cited {r.cited_sessions}")
    if report.citation_accuracy is not None:
        click.echo(f"Citation accuracy: {report.citation_accuracy:.0%}")
    if report.answer_accuracy is not None:
        click.echo(f"Answer accuracy:   {report.answer_accuracy:.0%}")
    if json_out is not None:
        json_out.write_text(jsonlib.dumps(report.to_dict(), indent=2), encoding="utf-8")
        click.echo(f"Report written to {json_out}")


@main.command()
@click.option("--sample", default=20, help="How many inferred entries to audit.")
def audit(sample: int) -> None:
    """Label a sample of inferred intents correct / partial / wrong.

    Powers the intent-accuracy metric from Seshat.md §8. Labels update the
    entries (correct -> confirmed, wrong -> corrected) and append to
    .seshat/audit_log.jsonl for rate tracking over time.
    """
    import json as jsonlib
    import random

    from seshat.store.db import Store, utcnow

    _require_config()
    root = Path(".").resolve()
    log_path = root / ".seshat" / "audit_log.jsonl"
    counts = {"correct": 0, "partial": 0, "wrong": 0, "skipped": 0}
    with Store.open(root) as store:
        pool = [
            e for e in store.entries()
            if e.intent_status == "inferred" and e.inferred_intent
        ]
        if not pool:
            click.echo("No inferred intents to audit.")
            return
        picked = random.sample(pool, min(sample, len(pool)))
        for i, entry in enumerate(picked, 1):
            click.echo(f"\n[{i}/{len(picked)}] entry {entry.id} (session {entry.session_id})")
            click.echo(f"  what changed: {entry.what_changed}")
            if entry.observable_outcome:
                click.echo(f"  outcome:      {entry.observable_outcome}")
            click.echo(f"  inferred:     {entry.inferred_intent}")
            choice = click.prompt(
                "  [c]orrect / [p]artial / [w]rong / [s]kip / [q]uit",
                type=click.Choice(["c", "p", "w", "s", "q"]),
                show_choices=False,
            )
            if choice == "q":
                break
            if choice == "s":
                counts["skipped"] += 1
                continue
            label = {"c": "correct", "p": "partial", "w": "wrong"}[choice]
            counts[label] += 1
            if choice == "c":
                store.set_intent(entry.id, entry.inferred_intent, status="confirmed")
            elif choice == "w":
                corrected = click.prompt("  actual intent")
                store.set_intent(entry.id, corrected, status="corrected")
            with log_path.open("a", encoding="utf-8") as f:
                f.write(jsonlib.dumps(
                    {"ts": utcnow(), "entry_id": entry.id, "label": label}
                ) + "\n")

    labeled = counts["correct"] + counts["partial"] + counts["wrong"]
    if labeled:
        click.echo(
            f"\nAudited {labeled}: {counts['correct']} correct, "
            f"{counts['partial']} partial, {counts['wrong']} wrong "
            f"({counts['correct'] / labeled:.0%} fully correct)."
        )


@main.command()
def stats() -> None:
    """Capture, intent-accuracy, and usage statistics."""
    import json as jsonlib
    from collections import Counter
    from datetime import datetime

    from seshat.store.db import Store

    _require_config()
    root = Path(".").resolve()
    with Store.open(root) as store:
        sessions = store.sessions()
        entries = store.entries()
        by_status = Counter(s.status for s in sessions)
        by_intent = Counter(e.intent_status for e in entries)
        click.echo(
            f"Sessions: {len(sessions)} "
            f"(open {by_status.get('open', 0)}, closed {by_status.get('closed', 0)}, "
            f"processed {by_status.get('processed', 0)})"
        )
        click.echo(
            f"Entries:  {len(entries)} "
            f"(inferred {by_intent.get('inferred', 0)}, "
            f"confirmed {by_intent.get('confirmed', 0)}, "
            f"corrected {by_intent.get('corrected', 0)})"
        )
        click.echo(f"Papers:   {len(store.papers())}")

        audit_log = root / ".seshat" / "audit_log.jsonl"
        if audit_log.exists():
            labels = Counter(
                jsonlib.loads(line)["label"]
                for line in audit_log.read_text(encoding="utf-8").splitlines()
                if line.strip()
            )
            total = sum(labels.values())
            if total:
                click.echo(
                    f"Audits:   {total} labeled, {labels.get('correct', 0) / total:.0%} correct, "
                    f"{labels.get('wrong', 0) / total:.0%} wrong"
                )

        queries = store.query_log()
        if queries:
            weeks = Counter(
                datetime.fromisoformat(ts).strftime("%G-W%V") for ts, _ in queries
            )
            click.echo(f"Queries:  {len(queries)} total")
            for week in sorted(weeks)[-6:]:
                click.echo(f"  {week}: {weeks[week]}")
        else:
            click.echo("Queries:  none logged yet — the number that matters is "
                       "whether this rises week over week.")


def _require_config():
    try:
        return load_config(Path("."))
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from exc


if __name__ == "__main__":
    main()
