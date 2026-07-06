"""The watch service: filesystem events -> debounce -> route -> raw events.

Watchdog callbacks only enqueue paths; all processing happens on the main
loop thread, so the store never sees concurrent writes. Saves are debounced
(editors often write a temp file then rename, producing bursts of events for
one logical save).
"""

from __future__ import annotations

import os
import queue
import threading
import time
from collections.abc import Callable
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from seshat.config import ALWAYS_IGNORED_DIRS, SeshatConfig
from seshat.papers.ingest import PaperIngestError, ingest_pdf
from seshat.store.db import Store
from seshat.store.vectors import VectorStore
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
        background_task: Callable[[], None] | None = None,
        vectors: VectorStore | None = None,
    ) -> None:
        # vectors is needed only for PDF ingestion; without it, papers
        # dropped into the watched folder are logged and skipped.
        self._vectors = vectors
        # background_task runs on each idle check (~every 30s); Phase 3 uses it
        # to drain the inference queue. It runs inline on the loop thread, so a
        # long generation delays (but never loses) queued file events.
        self._background_task = background_task
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

        if self._filter.is_paper_file(path):
            self._ingest_paper(path, rel)
            return None  # papers aren't session events; linking is by time
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

    def _ingest_paper(self, path: Path, rel: str) -> bool:
        if self._vectors is None:
            self._log(f"skipping paper {rel}: no vector store configured")
            return False
        try:
            paper_id = ingest_pdf(self._store, self._vectors, path, rel)
        except PaperIngestError as exc:
            self._log(f"skipping paper {rel}: {exc}")
            return False
        if paper_id is not None:
            self._log(f"paper ingested: {rel} (paper {paper_id})")
            return True
        return False

    def _walk_files(self):
        """Like rglob, but prunes ignored directories instead of descending
        into them — data/, .venv/, mlruns/ can hold millions of files."""
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d not in ALWAYS_IGNORED_DIRS]
            for name in filenames:
                yield Path(dirpath) / name

    def baseline_scan(self) -> int:
        """Snapshot watched files (and ingest pre-existing papers) so the
        first real save diffs cleanly."""
        count = 0
        for path in self._walk_files():
            if not path.is_file() or not self._filter.should_index(path):
                continue
            rel = self._filter.relative(path)
            if self._filter.is_paper_file(path):
                # Idempotent; added_at uses file mtime, so an old PDF doesn't
                # look freshly read to the proximity linker.
                if self._ingest_paper(path, rel):
                    count += 1
                continue
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
                        # One unreadable/adversarial file must not end capture.
                        try:
                            self.process_file(path)
                        except Exception as exc:  # noqa: BLE001
                            self._log(f"error processing {path}: {exc}")
                if now - last_idle_check >= IDLE_CHECK_SECONDS:
                    last_idle_check = now
                    self._tracker.flush_if_idle()
                    if self._background_task is not None:
                        try:
                            self._background_task()
                        except Exception as exc:  # noqa: BLE001
                            self._log(f"background task failed (will retry): {exc}")
        finally:
            observer.stop()
            observer.join()
