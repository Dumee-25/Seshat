"""Manages the headless Streamlit server the desktop window points at.

The GUI shell (a native window) never renders Streamlit itself; it just loads
`http://localhost:<port>`. This module owns that server's lifecycle — port
selection, launch, readiness, shutdown — none of which touches a GUI, so it is
fully unit-testable.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

APP_SCRIPT = Path(__file__).resolve().parent.parent / "ui" / "app.py"

# The "kohl" Seshat theme, passed to Streamlit as config env vars (see
# seshat.ui.app). Centralised here so `seshat ui` and `seshat app` agree.
THEME_ENV = {
    "STREAMLIT_THEME_BASE": "dark",
    "STREAMLIT_THEME_PRIMARY_COLOR": "#C9A227",
    "STREAMLIT_THEME_BACKGROUND_COLOR": "#16130F",
    "STREAMLIT_THEME_SECONDARY_BACKGROUND_COLOR": "#1C1812",
    "STREAMLIT_THEME_TEXT_COLOR": "#E6DCC4",
    "STREAMLIT_BROWSER_GATHER_USAGE_STATS": "false",
    "STREAMLIT_SERVER_HEADLESS": "true",
}


def theme_env(base: dict | None = None) -> dict:
    """A copy of the environment with the theme vars applied (setdefault),
    so an explicit env var or local config.toml still wins."""
    import os

    env = dict(base if base is not None else os.environ)
    for key, value in THEME_ENV.items():
        env.setdefault(key, value)
    return env


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _http_ok(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            return 200 <= response.status < 500
    except (urllib.error.URLError, OSError):
        return False


class StreamlitServer:
    def __init__(
        self,
        project_root: Path,
        port: int | None = None,
        python: str | None = None,
        app_script: Path = APP_SCRIPT,
    ) -> None:
        self.project_root = Path(project_root)
        self.port = port
        self._python = python or sys.executable
        self._app_script = app_script
        self._proc: subprocess.Popen | None = None

    @property
    def url(self) -> str:
        if self.port is None:
            raise RuntimeError("Server has no port yet; call start() first.")
        return f"http://localhost:{self.port}"

    def command(self, port: int) -> list[str]:
        return [
            self._python, "-m", "streamlit", "run", str(self._app_script),
            "--server.port", str(port),
            "--server.address", "localhost",
            "--server.headless", "true",
        ]

    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self, runner: Callable[[list[str]], subprocess.Popen] | None = None) -> None:
        if self.is_running():
            return
        if self.port is None:
            self.port = find_free_port()
        cmd = self.command(self.port)
        if runner is not None:
            self._proc = runner(cmd)
        else:
            self._proc = subprocess.Popen(
                cmd, cwd=str(self.project_root), env=theme_env()
            )

    def wait_until_ready(
        self,
        timeout: float = 40.0,
        interval: float = 0.4,
        probe: Callable[[str], bool] = _http_ok,
        sleep: Callable[[float], None] | None = None,
    ) -> bool:
        import time

        sleep = sleep or time.sleep
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not self.is_running():
                return False  # the process died during startup
            if probe(self.url):
                return True
            sleep(interval)
        return False

    def stop(self) -> None:
        if self._proc is None:
            return
        if self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None
