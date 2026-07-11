"""Runs the file watcher in a background thread for the desktop app.

The tray owns the process's main thread, so the watcher (a blocking run loop)
lives here on a daemon thread. Status is derived from the store, so the tray
can show "Watching / N queued" without the watcher having to push updates.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass

from seshat.store.db import Store
from seshat.watcher.daemon import WatchService


@dataclass
class Status:
    running: bool
    paused: bool
    queued: int  # closed-but-unprocessed sessions
    sessions: int

    def label(self) -> str:
        if not self.running:
            return "Stopped"
        state = "Paused" if self.paused else "Watching"
        return f"{state} · {self.queued} queued" if self.queued else state


class WatcherSupervisor:
    def __init__(
        self,
        service: WatchService,
        store: Store,
        log: Callable[[str], None] = lambda msg: None,
    ) -> None:
        self._service = service
        self._store = store
        self._log = log
        self._thread: threading.Thread | None = None

    def _run(self) -> None:
        try:
            indexed = self._service.baseline_scan()
            self._log(f"baseline: {indexed} file(s) snapshotted")
            self._service.run()
        except Exception as exc:  # noqa: BLE001 - a watcher crash must not kill the app
            self._log(f"watcher stopped unexpectedly: {exc}")

    def start(self) -> None:
        if self.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="seshat-watch", daemon=True)
        self._thread.start()

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def pause(self) -> None:
        self._service.pause()

    def resume(self) -> None:
        self._service.resume()

    @property
    def paused(self) -> bool:
        return self._service.paused

    def toggle_pause(self) -> bool:
        """Flip pause state; returns the new paused value."""
        if self._service.paused:
            self._service.resume()
        else:
            self._service.pause()
        return self._service.paused

    def status(self) -> Status:
        queued = len(self._store.sessions(status="closed"))
        total = len(self._store.sessions())
        return Status(
            running=self.is_alive(),
            paused=self._service.paused,
            queued=queued,
            sessions=total,
        )

    def stop(self, timeout: float = 10.0) -> None:
        self._service.stop()
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None
