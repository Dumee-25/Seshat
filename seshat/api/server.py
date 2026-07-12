"""Runs the cockpit API with uvicorn, and reports its own readiness."""

from __future__ import annotations

import threading
from pathlib import Path

from seshat.config import SeshatConfig


class ApiServer:
    """Runs the FastAPI app on a background thread (the desktop shell owns the
    main thread for the tray, as in the Streamlit app)."""

    def __init__(self, root: Path, config: SeshatConfig, port: int) -> None:
        self.root = Path(root)
        self._config = config
        self.port = port
        self._server = None
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        return f"http://localhost:{self.port}"

    def start(self) -> None:
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
            time.sleep(0.1)
        return False

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=10)
