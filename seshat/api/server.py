"""Runs the cockpit API with uvicorn, and reports its own readiness.

This is the server the desktop shell points its window at. Unlike the Streamlit
server it replaced, it runs in-process on a background thread — there is no
child process to spawn, no port to hand across a process boundary, and no theme
to inject through environment variables (the React app owns its own styling).
The desktop shell keeps the main thread for the tray.
"""

from __future__ import annotations

import socket
import threading
from pathlib import Path

from seshat.config import SeshatConfig


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class ApiServer:
    """Runs the FastAPI app on a background thread. Pass `port=None` to take
    whatever port is free — what the desktop app wants, since nothing else needs
    to know the URL in advance."""

    def __init__(self, root: Path, config: SeshatConfig, port: int | None = None) -> None:
        self.root = Path(root)
        self._config = config
        self.port = port if port is not None else find_free_port()
        self._server = None
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        return f"http://localhost:{self.port}"

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_running():
            return
        import uvicorn

        from seshat.api.app import create_app

        config = uvicorn.Config(
            create_app(self.root, self._config),
            host="localhost",
            port=self.port,
            log_level="warning",
        )
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, daemon=True)
        self._thread.start()

    def wait_until_ready(self, timeout: float = 30.0) -> bool:
        import time

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._server is not None and self._server.started:
                return True
            if not self.is_running():
                return False  # the thread died during startup
            time.sleep(0.1)
        return False

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=10)
            self._thread = None
