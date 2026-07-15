"""Entry point for the bundled executable.

PyInstaller points `Seshat.exe` here. Order matters:
  1. internal sub-modes (`--seshat-run-window`) are handled before Click ever
     sees argv;
  2. a bare launch (double-click, no args) becomes `seshat app`;
  3. anything else falls through to the normal CLI.
"""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> None:
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
