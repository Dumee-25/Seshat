"""Idle-GPU inference queue.

The queue is the database: pending work = sessions with status 'closed'
(captured but not yet journaled), so nothing is lost across restarts and no
separate job table is needed. The worker refuses to run while the GPU looks
busy — the researcher's training job always wins (Seshat.md §6, GPU
contention) — unless cpu_fallback is enabled. Journal latency is free:
entries are read hours later, so overnight processing is fine.
"""

from __future__ import annotations

from collections.abc import Callable

from seshat.inference.journal import generate_entry
from seshat.inference.provider import GenerationError, LLMProvider
from seshat.store.db import Store
from seshat.store.vectors import VectorStore, VectorStoreError

GPU_BUSY_UTILIZATION_PCT = 25


def gpu_busy(threshold_pct: int = GPU_BUSY_UTILIZATION_PCT) -> bool:
    """True if any NVIDIA GPU is under real load. No GPU/NVML -> not busy."""
    try:
        import pynvml

        pynvml.nvmlInit()
    except Exception:
        return False  # no NVIDIA GPU or driver: nothing to contend with
    try:
        for i in range(pynvml.nvmlDeviceGetCount()):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)
            if pynvml.nvmlDeviceGetUtilizationRates(handle).gpu > threshold_pct:
                return True
        return False
    except Exception:
        return False
    finally:
        try:
            pynvml.nvmlShutdown()
        except Exception:
            pass


class InferenceWorker:
    def __init__(
        self,
        store: Store,
        vectors: VectorStore,
        provider: LLMProvider,
        cpu_fallback: bool = False,
        busy_check: Callable[[], bool] = gpu_busy,
        log: Callable[[str], None] = lambda msg: None,
    ) -> None:
        self._store = store
        self._vectors = vectors
        self._provider = provider
        self._cpu_fallback = cpu_fallback
        self._busy_check = busy_check
        self._log = log

    def pending_sessions(self) -> list[int]:
        return [s.id for s in self._store.sessions(status="closed")]

    def run_pending(self, force: bool = False) -> int:
        """Process queued sessions; returns how many entries were written.

        Stops early if the GPU becomes busy between sessions. A provider
        failure logs and stops (the sessions stay queued for the next run).
        """
        written = 0
        for session_id in self.pending_sessions():
            if not force and not self._cpu_fallback and self._busy_check():
                self._log("GPU busy; deferring journal generation.")
                break
            try:
                entry = generate_entry(self._store, self._vectors, self._provider, session_id)
            except (GenerationError, VectorStoreError) as exc:
                # Ollama unreachable, embedding model not pulled, ... — the
                # session stays queued; capture must keep running regardless.
                self._log(f"journal generation failed (will retry): {exc}")
                break
            if entry is not None:
                written += 1
                self._log(f"journal entry {entry.id} written for session {session_id}")
        return written
