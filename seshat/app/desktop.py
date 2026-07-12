"""Desktop app orchestrator: tray + background watcher + on-demand window.

Threading model (chosen to avoid two GUI event loops fighting for the main
thread):
  - main thread runs the tray icon's message loop (`icon.run()`);
  - the file watcher runs on a daemon thread (WatcherSupervisor);
  - the Streamlit server runs as a child process;
  - each UI window is its own child process (seshat.app.window).

The store is opened twice on purpose: the watcher thread writes through one
connection, the tray thread reads status through another. Separate connections
+ WAL keep those two threads from sharing a cursor.
"""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path

from seshat.app.launch import window_command
from seshat.app.server import StreamlitServer
from seshat.app.supervisor import WatcherSupervisor
from seshat.config import SeshatConfig
from seshat.store.db import Store


class DesktopApp:
    def __init__(self, root: Path, config: SeshatConfig, log=print) -> None:
        from seshat.inference.provider import get_embedder, get_provider
        from seshat.inference.queue import InferenceWorker
        from seshat.store.vectors import VectorStore
        from seshat.watcher.daemon import WatchService

        self._root = Path(root)
        self._config = config
        self._log = log

        # Watcher-thread connections.
        self._store = Store.open(self._root)
        self._vectors = VectorStore(self._root, get_embedder(config))
        # Tray-thread connection, for status reads only.
        self._status_store = Store.open(self._root)

        worker = InferenceWorker(
            self._store, self._vectors, get_provider(config),
            cpu_fallback=config.inference.cpu_fallback, log=log,
        )
        service = WatchService(
            self._root, config, self._store, log=log,
            background_task=worker.run_pending, vectors=self._vectors,
        )
        self._supervisor = WatcherSupervisor(service, self._status_store, log=log)
        self._server = StreamlitServer(self._root)
        self._icon = None

    # -- TrayController interface ---------------------------------------------

    def open_window(self) -> None:
        if not self._server.is_running():
            self._server.start()
        # Wait for readiness off the tray thread so the menu stays responsive.
        threading.Thread(target=self._spawn_window, daemon=True).start()

    def _spawn_window(self) -> None:
        if self._server.wait_until_ready():
            subprocess.Popen(window_command(self._server.url, "Seshat"))
        else:
            self._log("UI server did not become ready in time.")

    def status_label(self) -> str:
        return self._supervisor.status().label()

    def is_paused(self) -> bool:
        return self._supervisor.paused

    def toggle_pause(self) -> None:
        self._supervisor.toggle_pause()
        if self._icon is not None:
            self._icon.update_menu()

    def quit(self) -> None:
        self._log("shutting down...")
        self._supervisor.stop()
        self._server.stop()
        self._store.close()
        self._status_store.close()
        self._vectors.close()
        if self._icon is not None:
            self._icon.stop()

    # -- run ------------------------------------------------------------------

    def run(self) -> None:
        from seshat.app.tray import build_icon

        self._supervisor.start()
        self._server.start()  # eager, so the first Open is quick
        self.open_window()  # show the UI on launch
        self._icon = build_icon(self)
        self._icon.run()  # blocks the main thread until quit()


def run_desktop(root: Path, config: SeshatConfig, log=print) -> None:
    DesktopApp(root, config, log=log).run()
