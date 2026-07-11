"""Project configuration: seshat.toml loading, defaults, and validation."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_FILENAME = "seshat.toml"

# Directories Seshat never watches, regardless of user config. These are the
# places ML projects accumulate gigabytes of artifacts that would drown the
# watcher (see Seshat.md §3, "Watch scope").
ALWAYS_IGNORED_DIRS = frozenset(
    {
        ".git",
        ".seshat",
        ".venv",
        "venv",
        "__pycache__",
        ".ipynb_checkpoints",
        "node_modules",
        "data",
        "mlruns",
        "checkpoints",
    }
)

_TEMPLATE = """\
# Seshat project configuration — created by `seshat init`.
# Globs are relative to this file's directory (the project root).

[project]
name = "{name}"

[watch]
include = ["**/*.ipynb", "**/*.py"]
# Extends the built-in ignore list (.git, .venv, data, mlruns, checkpoints, ...).
exclude = []
respect_gitignore = true
max_file_size_mb = 5
results_dir = "results"
papers_dir = "papers"

[session]
idle_gap_minutes = 45

[inference]
provider = "local"  # "local" (Ollama) or "api" (any OpenAI-compatible endpoint)
model = "qwen3:8b"
# Embedding model for search (also served by Ollama / the API provider).
# Pull it once with `ollama pull nomic-embed-text`.
embed_model = "nomic-embed-text"
# base_url defaults to http://localhost:11434 for "local". For "api", set it
# here or via SESHAT_API_BASE; the key comes from SESHAT_API_KEY.
base_url = ""
# When true, journal generation runs even while the GPU is busy training.
cpu_fallback = false
"""


class ConfigError(Exception):
    """Raised when seshat.toml is missing or invalid."""


@dataclass
class WatchConfig:
    include: list[str] = field(default_factory=lambda: ["**/*.ipynb", "**/*.py"])
    exclude: list[str] = field(default_factory=list)
    respect_gitignore: bool = True
    max_file_size_mb: float = 5.0
    results_dir: str = "results"
    papers_dir: str = "papers"


@dataclass
class SessionConfig:
    idle_gap_minutes: int = 45


@dataclass
class InferenceConfig:
    provider: str = "local"
    model: str = "qwen3:8b"
    embed_model: str = "nomic-embed-text"
    base_url: str = ""
    cpu_fallback: bool = False


@dataclass
class SeshatConfig:
    root: Path
    name: str
    watch: WatchConfig = field(default_factory=WatchConfig)
    session: SessionConfig = field(default_factory=SessionConfig)
    inference: InferenceConfig = field(default_factory=InferenceConfig)


def config_path(root: Path) -> Path:
    return root / CONFIG_FILENAME


def write_default_config(root: Path, name: str | None = None, force: bool = False) -> Path:
    """Write a default seshat.toml into *root* and return its path."""
    path = config_path(root)
    if path.exists() and not force:
        raise ConfigError(
            f"{path} already exists. Use --force to overwrite it with defaults."
        )
    path.write_text(_TEMPLATE.format(name=name or root.resolve().name), encoding="utf-8")
    return path


def load_config(root: Path) -> SeshatConfig:
    """Load and validate seshat.toml from *root*.

    Raises ConfigError with a message that tells the user exactly what to fix.
    """
    path = config_path(root)
    if not path.exists():
        raise ConfigError(
            f"No {CONFIG_FILENAME} found in {root.resolve()}. "
            "Run `seshat init` in your project root first."
        )
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path} is not valid TOML: {exc}") from exc

    name = _get(raw, "project", "name", str, default=root.resolve().name)

    watch = WatchConfig(
        include=_get_str_list(raw, "watch", "include", default=WatchConfig().include),
        exclude=_get_str_list(raw, "watch", "exclude", default=[]),
        respect_gitignore=_get(raw, "watch", "respect_gitignore", bool, default=True),
        max_file_size_mb=_get_number(raw, "watch", "max_file_size_mb", default=5.0),
        results_dir=_get(raw, "watch", "results_dir", str, default="results"),
        papers_dir=_get(raw, "watch", "papers_dir", str, default="papers"),
    )
    session = SessionConfig(
        idle_gap_minutes=int(_get_number(raw, "session", "idle_gap_minutes", default=45)),
    )
    inference = InferenceConfig(
        provider=_get(raw, "inference", "provider", str, default="local"),
        model=_get(raw, "inference", "model", str, default="qwen3:8b"),
        embed_model=_get(raw, "inference", "embed_model", str, default="nomic-embed-text"),
        base_url=_get(raw, "inference", "base_url", str, default=""),
        cpu_fallback=_get(raw, "inference", "cpu_fallback", bool, default=False),
    )

    _validate(path, watch, session, inference)
    return SeshatConfig(
        root=root, name=name, watch=watch, session=session, inference=inference
    )


def _validate(
    path: Path, watch: WatchConfig, session: SessionConfig, inference: InferenceConfig
) -> None:
    if not watch.include:
        raise ConfigError(f"{path}: [watch] include must list at least one glob.")
    if watch.max_file_size_mb <= 0:
        raise ConfigError(f"{path}: [watch] max_file_size_mb must be positive.")
    if session.idle_gap_minutes <= 0:
        raise ConfigError(f"{path}: [session] idle_gap_minutes must be positive.")
    if inference.provider not in ("local", "api"):
        raise ConfigError(
            f"{path}: [inference] provider must be \"local\" or \"api\", "
            f"got {inference.provider!r}."
        )


def _section(raw: dict, section: str) -> dict:
    value = raw.get(section, {})
    if not isinstance(value, dict):
        raise ConfigError(f"[{section}] must be a table, got {type(value).__name__}.")
    return value


def _get(raw: dict, section: str, key: str, kind: type, default):
    value = _section(raw, section).get(key, default)
    if not isinstance(value, kind) or (kind is not bool and isinstance(value, bool)):
        raise ConfigError(
            f"[{section}] {key} must be a {kind.__name__}, got {type(value).__name__}."
        )
    return value


def _get_number(raw: dict, section: str, key: str, default: float) -> float:
    value = _section(raw, section).get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(
            f"[{section}] {key} must be a number, got {type(value).__name__}."
        )
    return float(value)


def _get_str_list(raw: dict, section: str, key: str, default: list[str]) -> list[str]:
    value = _section(raw, section).get(key, default)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ConfigError(f"[{section}] {key} must be a list of strings.")
    return list(value)
