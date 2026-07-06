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


def _make_vectors():
    from seshat.store.vectors import VectorStore

    return VectorStore(Path(".").resolve())


def _make_worker(config, store, vectors=None):
    from seshat.inference.provider import get_provider
    from seshat.inference.queue import InferenceWorker

    return InferenceWorker(
        store,
        vectors if vectors is not None else _make_vectors(),
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
        vectors = _make_vectors()
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
    from seshat.inference.provider import GenerationError, get_provider
    from seshat.store.db import Store
    from seshat.store.vectors import VectorStore

    config = _require_config()
    root = Path(".").resolve()
    with Store.open(root) as store:
        vectors = VectorStore(root)
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

    _require_config()
    if importlib.util.find_spec("streamlit") is None:
        raise click.ClickException(
            "streamlit is not installed. Run `pip install seshat[ui]` first."
        )
    app_path = Path(__file__).parent / "ui" / "app.py"
    subprocess.run(
        [sys.executable, "-m", "streamlit", "run", str(app_path)], check=False
    )


def _require_config():
    try:
        return load_config(Path("."))
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from exc


if __name__ == "__main__":
    main()
