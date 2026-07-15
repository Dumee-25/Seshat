"""Frozen-aware process launching.

The desktop app spawns one kind of child process: each UI window. In
development that is `python -m seshat.app.window ...`. Inside a PyInstaller
bundle there is no `python -m` — `sys.executable` is the frozen `Seshat.exe` —
so instead the exe re-invokes itself with an internal flag, and `dispatch()`
(called first thing in the entry point) routes that invocation to the right
sub-mode.

Keeping this in one module means the command builder and the dispatcher agree
on the flag name, and both are unit-testable without actually freezing.

The UI server used to have a sub-mode here too, back when it was a Streamlit
child process. It now runs on a thread inside the main process (see
seshat.api.server), so only the window needs re-invocation.
"""

from __future__ import annotations

import sys

RUN_WINDOW_FLAG = "--seshat-run-window"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def window_command(url: str, title: str = "Seshat") -> list[str]:
    if is_frozen():
        return [sys.executable, RUN_WINDOW_FLAG, url, title]
    return [sys.executable, "-m", "seshat.app.window", url, title]


def dispatch(argv: list[str]) -> bool:
    """If argv selects an internal sub-mode, run it and return True.

    Called at the very top of the frozen entry point, before Click sees argv.
    """
    if not argv:
        return False
    if argv[0] == RUN_WINDOW_FLAG:
        from seshat.app.window import open_window

        open_window(argv[1], argv[2] if len(argv) > 2 else "Seshat")
        return True
    return False
