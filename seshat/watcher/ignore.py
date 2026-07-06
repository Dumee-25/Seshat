"""Decides which files the watcher indexes.

Order of precedence: always-ignored directories, then config excludes, then
.gitignore (if respected), then include globs. Files under the results
directory are a special case: they are indexed if they are CSV/JSON, whatever
the include globs say.
"""

from __future__ import annotations

from pathlib import Path

import pathspec

from seshat.config import ALWAYS_IGNORED_DIRS, SeshatConfig

RESULT_SUFFIXES = (".csv", ".json")


class PathFilter:
    def __init__(self, root: Path, config: SeshatConfig) -> None:
        self._root = root.resolve()
        self._max_bytes = int(config.watch.max_file_size_mb * 1024 * 1024)
        self._results_dir = config.watch.results_dir
        self._include = pathspec.PathSpec.from_lines("gitwildmatch", config.watch.include)
        self._exclude = pathspec.PathSpec.from_lines("gitwildmatch", config.watch.exclude)
        self._gitignore = None
        if config.watch.respect_gitignore:
            gitignore = self._root / ".gitignore"
            if gitignore.exists():
                self._gitignore = pathspec.PathSpec.from_lines(
                    "gitwildmatch", gitignore.read_text(encoding="utf-8").splitlines()
                )

    def relative(self, path: Path) -> str | None:
        """Project-relative POSIX path, or None if outside the project."""
        try:
            return path.resolve().relative_to(self._root).as_posix()
        except ValueError:
            return None

    def is_result_file(self, path: Path) -> bool:
        rel = self.relative(path)
        if rel is None:
            return False
        return (
            rel.startswith(self._results_dir + "/")
            and path.suffix.lower() in RESULT_SUFFIXES
        )

    def should_index(self, path: Path) -> bool:
        rel = self.relative(path)
        if rel is None:
            return False
        if any(part in ALWAYS_IGNORED_DIRS for part in Path(rel).parts):
            return False
        if self._exclude.match_file(rel):
            return False
        if self._gitignore is not None and self._gitignore.match_file(rel):
            # The results dir is typically gitignored but is exactly what we
            # want to capture, so it wins over .gitignore.
            if not self.is_result_file(path):
                return False
        if not (self._include.match_file(rel) or self.is_result_file(path)):
            return False
        try:
            if path.stat().st_size > self._max_bytes:
                return False
        except OSError:
            return False
        return True
