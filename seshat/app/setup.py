"""First-run setup: make sure Ollama is present and the models are pulled.

Pure logic with injectable hooks (which/http/pull), so the whole flow is
testable without a real Ollama. The CLI wiring lives in cli.py.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field

from seshat.config import SeshatConfig
from seshat.inference.provider import OLLAMA_DEFAULT_URL


@dataclass
class SetupReport:
    ollama_installed: bool
    ollama_running: bool
    present_models: list[str] = field(default_factory=list)
    pulled: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.ollama_installed and self.ollama_running and not self.missing


def ollama_installed(which: Callable[[str], str | None] = shutil.which) -> bool:
    return which("ollama") is not None


def installed_models(base_url: str, opener=urllib.request.urlopen) -> list[str] | None:
    """Model names from /api/tags, or None if Ollama is unreachable."""
    try:
        with opener(f"{base_url.rstrip('/')}/api/tags", timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        return None
    return [m.get("name", "") for m in data.get("models", [])]


def _base_name(model: str) -> str:
    # "qwen3:8b" and "qwen3:8b" match; a bare "qwen3" matches "qwen3:latest".
    return model.split(":", 1)[0]


def _have(model: str, present: list[str]) -> bool:
    if model in present:
        return True
    return any(_base_name(p) == _base_name(model) for p in present)


def pull_model(model: str, runner=subprocess.run) -> bool:
    try:
        result = runner(["ollama", "pull", model], capture_output=True, text=True)
    except (OSError, subprocess.SubprocessError):
        return False
    return getattr(result, "returncode", 1) == 0


def run_setup(
    config: SeshatConfig,
    base_url: str = "",
    pull: bool = True,
    which: Callable[[str], str | None] = shutil.which,
    opener=urllib.request.urlopen,
    runner=subprocess.run,
    log: Callable[[str], None] = lambda msg: None,
) -> SetupReport:
    base_url = base_url or config.inference.base_url or OLLAMA_DEFAULT_URL
    wanted = [config.inference.model, config.inference.embed_model]

    if not ollama_installed(which):
        log("Ollama is not installed. Get it from https://ollama.com/download")
        return SetupReport(False, False, missing=wanted)

    present = installed_models(base_url, opener)
    if present is None:
        log("Ollama is installed but not running. Start it, then re-run setup.")
        return SetupReport(True, False, missing=wanted)

    report = SetupReport(True, True, present_models=present)
    for model in wanted:
        if _have(model, present):
            continue
        if not pull:
            report.missing.append(model)
            continue
        log(f"Pulling {model} (first time only, this can take a while)...")
        if pull_model(model, runner):
            report.pulled.append(model)
        else:
            report.missing.append(model)
            log(f"Failed to pull {model}. Run `ollama pull {model}` manually.")
    return report
