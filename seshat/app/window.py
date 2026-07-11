"""Native window that displays the Seshat UI, run as its own process.

Launched by the tray via `python -m seshat.app.window <url> [title]`. Running
the webview in a separate process — rather than in the tray's process —
sidesteps the constraint that both pywebview and the tray want to own the main
thread. Each window is disposable: closing it exits only this process; the
tray and the watcher keep running, and "Open" spawns a fresh one.

This is thin GUI glue and is not exercised by the test suite (no display in
CI); the logic it depends on lives in server.py and supervisor.py.
"""

from __future__ import annotations

import sys

WINDOW_WIDTH = 1180
WINDOW_HEIGHT = 800


def open_window(url: str, title: str = "Seshat") -> None:
    try:
        import webview
    except ImportError:
        sys.stderr.write(
            "pywebview is not installed. Install the desktop extra:\n"
            "  python -m pip install \"seshat[desktop]\"\n"
        )
        raise SystemExit(1) from None
    webview.create_window(
        title, url, width=WINDOW_WIDTH, height=WINDOW_HEIGHT, min_size=(900, 600)
    )
    webview.start()


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        sys.stderr.write("usage: python -m seshat.app.window <url> [title]\n")
        return 2
    url = argv[0]
    title = argv[1] if len(argv) > 1 else "Seshat"
    open_window(url, title)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
