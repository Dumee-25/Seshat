"""The watch service: filesystem events -> debounce -> route -> raw events.

Watchdog callbacks only enqueue paths; all processing happens on the main
loop thread, so the store never sees concurrent writes. Saves are debounced
(editors often write a temp file then rename, producing bursts of events for
one logical save).
"""

from __future__ import annotations

import queue
import threading
import time
from collections.abc import Callable
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from seshat.config import SeshatConfig
from seshat.store.db import Store
from seshat.watcher import notebooks, results, scripts
from seshat.watcher.ignore import PathFilter
from seshat.watcher.sessions import SessionTracker

DEBOUNCE_SECONDS = 1.5
IDLE_CHECK_SECONDS = 30


class _Handler(FileSystemEventHandler):
    def __init__(self, sink: Callable[[Path], None]) -> None:
        self._sink = sink

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._sink(Path(str(event.src_path)))

    def on_modified(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._sink(Path(str(event.src_path)))

    def on_moved(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._sink(Path(str(event.dest_path)))


class WatchService:
    def __init__(
        self,
        root: Path,
        config: SeshatConfig,
        store: Store,
        log: Callable[[str], None] = lambda msg: None,
        on_session_closed: Callable[[int], None] | None = None,
    ) -> None:
        self.root = root.resolve()
        self._config = config
        self._store = store
        self._log = log
        self._filter = PathFilter(self.root, config)
        self._tracker = SessionTracker(
            store,
            config.session.idle_gap_minutes,
            on_close=on_session_closed or (lambda sid: log(f"session {sid} closed")),
        )
        self._queue: queue.Queue[Path] = queue.Queue()
        self._stop = threading.Event()

    # -- processing -----------------------------------------------------------

    def process_file(self, path: Path) -> int | None:
        """Index one saved file. Returns the raw event id, or None if skipped."""
        if not path.is_file() or not self._filter.should_index(path):
            return None
        rel = self._filter.relative(path)

        if self._filter.is_result_file(path):
            kind, payload = "result_file", results.index_result_file(self._store, path, rel)
        elif path.suffix == ".ipynb":
            kind, payload = "notebook_diff", self._process_notebook(path, rel)
        elif path.suffix == ".py":
            kind, payload = "script_change", self._process_script(path, rel)
        else:
            return None

        if payload is None:
            return None
        session_id = self._tracker.on_event()
        event_id = self._store.append_event(kind, payload, path=rel)
        self._store.assign_events_to_session([event_id], session_id)
        self._log(f"{kind}: {rel} (session {session_id})")
        return event_id

    def _process_notebook(self, path: Path, rel: str) -> dict | None:
        try:
            cells = notebooks.parse_notebook(path.read_text(encoding="utf-8"))
        except (OSError, notebooks.NotebookParseError) as exc:
            self._log(f"skipping {rel}: {exc}")
            return None
        snapshot = self._store.get_snapshot(rel)
        self._store.set_snapshot(rel, notebooks.cells_to_json(cells))
        if snapshot is None:
            return None  # first sight: baseline only, no diff to report
        return notebooks.diff_notebooks(notebooks.cells_from_json(snapshot), cells)

    def _process_script(self, path: Path, rel: str) -> dict | None:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        snapshot = self._store.get_snapshot(rel)
        self._store.set_snapshot(rel, text)
        if snapshot is None:
            return None
        return scripts.diff_script(snapshot, text, rel)

    def baseline_scan(self) -> int:
        """Snapshot every watched file so the first real save diffs cleanly."""
        count = 0
        for path in self.root.rglob("*"):
            if not path.is_file() or not self._filter.should_index(path):
                continue
            rel = self._filter.relative(path)
            if self._store.get_snapshot(rel) is not None:
                continue
            if path.suffix == ".ipynb":
                try:
                    cells = notebooks.parse_notebook(path.read_text(encoding="utf-8"))
                except (OSError, notebooks.NotebookParseError):
                    continue
                self._store.set_snapshot(rel, notebooks.cells_to_json(cells))
                count += 1
            elif path.suffix == ".py":
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                self._store.set_snapshot(rel, text)
                count += 1
        return count

    # -- run loop ---------------------------------------------------------------

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        """Watch until stop() is called (or KeyboardInterrupt)."""
        observer = Observer()
        observer.schedule(_Handler(self._queue.put), str(self.root), recursive=True)
        observer.start()
        self._log(f"watching {self.root}")

        pending: dict[Path, float] = {}
        last_idle_check = time.monotonic()
        try:
            while not self._stop.is_set():
                try:
                    pending[self._queue.get(timeout=0.5)] = time.monotonic()
                except queue.Empty:
                    pass
                now = time.monotonic()
                for path, seen in list(pending.items()):
                    if now - seen >= DEBOUNCE_SECONDS:
                        del pending[path]
                        self.process_file(path)
                if now - last_idle_check >= IDLE_CHECK_SECONDS:
                    last_idle_check = now
                    self._tracker.flush_if_idle()
        finally:
            observer.stop()
            observer.join()
