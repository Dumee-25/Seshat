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


def _not_yet(phase: str) -> None:
    raise click.ClickException(f"Not implemented yet - coming in {phase} of BUILD_PLAN.md.")


@main.command()
def watch() -> None:
    """Watch the project and capture work sessions (Ctrl+C to stop)."""
    from seshat.store.db import Store
    from seshat.watcher.daemon import WatchService

    config = _require_config()
    root = Path(".").resolve()
    with Store.open(root) as store:
        service = WatchService(root, config, store, log=click.echo)
        indexed = service.baseline_scan()
        click.echo(f"Baseline: {indexed} new file(s) snapshotted.")
        try:
            service.run()
        except KeyboardInterrupt:
            click.echo("Stopped.")


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
def backfill() -> None:
    """Reconstruct journal entries from existing git history."""
    _require_config()
    _not_yet("Phase 4")


@main.command()
def reprocess() -> None:
    """Regenerate journal entries from stored raw events."""
    _require_config()
    _not_yet("Phase 3")


@main.command()
def ui() -> None:
    """Open the chat interface."""
    _require_config()
    _not_yet("Phase 6")


def _require_config():
    try:
        return load_config(Path("."))
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from exc


if __name__ == "__main__":
    main()
