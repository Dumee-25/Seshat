"""Entry point for the bundled executable.

PyInstaller points `Seshat.exe` here. Order matters:
  0. the standard streams are made real, before anything can touch them;
  1. internal sub-modes (`--seshat-run-window`) are handled before Click ever
     sees argv;
  2. a bare launch (double-click, no args) becomes `seshat app`;
  3. anything else falls through to the normal CLI.
"""

from __future__ import annotations

import sys
from pathlib import Path

LOG_DIR = Path.home() / ".seshat"
LOG_FILE = LOG_DIR / "app.log"
MAX_LOG_BYTES = 1_000_000


def _open_log():
    """A file for the windowed app's output, since it has no console to print
    to. Rolled by truncation — this is a breadcrumb trail for "it won't start",
    not an audit log, so one generation is enough."""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > MAX_LOG_BYTES:
            LOG_FILE.unlink()
        return open(LOG_FILE, "a", encoding="utf-8", buffering=1)
    except OSError:
        import os

        return open(os.devnull, "w", encoding="utf-8")


def ensure_streams(stream_factory=_open_log) -> None:
    """Give the process real stdout/stderr if it has none.

    A frozen windowed build (`console=False`) launched by double-click gets no
    console, so Python sets sys.stdout and sys.stderr to None. Anything that
    touches them then dies: uvicorn's log formatter calls `sys.stdout.isatty()`
    while configuring logging, which raised `Unable to configure formatter
    'default'` and killed the app before its window ever opened. Running the exe
    with output redirected hid the bug, because redirection supplies real
    handles.

    Fixing it here, before any import that might log, covers every windowed
    entry path at once rather than teaching each caller to be careful.
    """
    if sys.stdout is not None and sys.stderr is not None:
        return
    stream = stream_factory()
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream


def main(argv: list[str] | None = None) -> None:
    ensure_streams()

    argv = argv if argv is not None else sys.argv[1:]

    from seshat.app.launch import dispatch

    if dispatch(argv):
        return

    if not argv:
        # Double-clicked: launch the desktop app rather than printing help.
        sys.argv = [sys.argv[0], "app"]

    from seshat.cli import main as cli_main

    cli_main()


if __name__ == "__main__":
    main()
