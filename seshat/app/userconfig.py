"""User-level app state, separate from any single project's seshat.toml.

An installed app launched from a Start Menu shortcut has no meaningful working
directory, so it needs to remember which project to open. This is that memory
— a tiny TOML file in the user's home, holding the default project path.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from seshat.config import CONFIG_FILENAME

USER_DIR = Path.home() / ".seshat"
USER_CONFIG = USER_DIR / "app.toml"


def _read() -> dict:
    if not USER_CONFIG.exists():
        return {}
    try:
        return tomllib.loads(USER_CONFIG.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def get_default_project() -> Path | None:
    raw = _read().get("default_project")
    if not raw:
        return None
    path = Path(raw)
    return path if (path / CONFIG_FILENAME).exists() else None


def set_default_project(path: Path) -> None:
    USER_DIR.mkdir(parents=True, exist_ok=True)
    resolved = str(path.resolve()).replace("\\", "\\\\")
    USER_CONFIG.write_text(
        f'default_project = "{resolved}"\n', encoding="utf-8"
    )


def resolve_project(cwd: Path | None = None) -> Path | None:
    """The project to operate on: the current directory if it is one, else the
    remembered default. None if neither is available."""
    cwd = cwd or Path.cwd()
    if (cwd / CONFIG_FILENAME).exists():
        return cwd
    return get_default_project()
