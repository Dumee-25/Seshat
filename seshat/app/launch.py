"""Frozen-aware process launching.

The desktop app spawns two kinds of child process: the Streamlit server and
each UI window. In development those are `python -m streamlit ...` and
`python -m seshat.app.window ...`. Inside a PyInstaller bundle there is no
`python -m` — `sys.executable` is the frozen `Seshat.exe` — so instead the exe
re-invokes itself with an internal flag, and `dispatch()` (called first thing
in the entry point) routes that invocation to the right sub-mode.

Keeping this in one module means the command builders and the dispatcher agree
on the flag names, and both are unit-testable without actually freezing.
"""

from __future__ import annotations

import sys
from pathlib import Path

# The Streamlit app script, bundled as data in the frozen build. Resolved from
# this file, so it points into _MEIPASS when frozen.
APP_SCRIPT = Path(__file__).resolve().parent.parent / "ui" / "app.py"

RUN_STREAMLIT_FLAG = "--seshat-run-streamlit"
RUN_WINDOW_FLAG = "--seshat-run-window"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def streamlit_command(port: int, app_script: Path = APP_SCRIPT) -> list[str]:
    if is_frozen():
        return [sys.executable, RUN_STREAMLIT_FLAG, str(port)]
    return [
        sys.executable, "-m", "streamlit", "run", str(app_script),
        "--server.port", str(port),
        "--server.address", "localhost",
        "--server.headless", "true",
    ]


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
    mode = argv[0]
    if mode == RUN_STREAMLIT_FLAG:
        port = int(argv[1]) if len(argv) > 1 else 8501
        _run_streamlit_in_process(port)
        return True
    if mode == RUN_WINDOW_FLAG:
        from seshat.app.window import open_window

        open_window(argv[1], argv[2] if len(argv) > 2 else "Seshat")
        return True
    return False


def _run_streamlit_in_process(port: int, app_script: Path = APP_SCRIPT) -> None:
    from streamlit.web import bootstrap

    flag_options = {
        "server.port": port,
        "server.address": "localhost",
        "server.headless": True,
        "global.developmentMode": False,
    }
    bootstrap.load_config_options(flag_options=flag_options)
    bootstrap.run(str(app_script), False, [], flag_options)
