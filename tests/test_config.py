from pathlib import Path

import pytest

from seshat.config import (
    ALWAYS_IGNORED_DIRS,
    ConfigError,
    load_config,
    write_default_config,
)


def test_write_then_load_roundtrip(tmp_path: Path):
    write_default_config(tmp_path, name="myproj")
    cfg = load_config(tmp_path)
    assert cfg.name == "myproj"
    assert cfg.watch.include == ["**/*.ipynb", "**/*.py"]
    assert cfg.watch.respect_gitignore is True
    assert cfg.watch.max_file_size_mb == 5.0
    assert cfg.session.idle_gap_minutes == 45
    assert cfg.inference.provider == "local"


def test_name_defaults_to_directory(tmp_path: Path):
    write_default_config(tmp_path)
    cfg = load_config(tmp_path)
    assert cfg.name == tmp_path.resolve().name


def test_write_refuses_overwrite_without_force(tmp_path: Path):
    write_default_config(tmp_path)
    with pytest.raises(ConfigError, match="already exists"):
        write_default_config(tmp_path)
    write_default_config(tmp_path, force=True)  # no raise


def test_missing_config_mentions_init(tmp_path: Path):
    with pytest.raises(ConfigError, match="seshat init"):
        load_config(tmp_path)


def test_invalid_toml_reports_path(tmp_path: Path):
    (tmp_path / "seshat.toml").write_text("this is [not toml", encoding="utf-8")
    with pytest.raises(ConfigError, match="not valid TOML"):
        load_config(tmp_path)


@pytest.mark.parametrize(
    ("snippet", "match"),
    [
        ("[watch]\ninclude = []", "at least one glob"),
        ("[watch]\nmax_file_size_mb = 0", "must be positive"),
        ("[watch]\nmax_file_size_mb = 'big'", "must be a number"),
        ("[watch]\ninclude = [1, 2]", "list of strings"),
        ("[session]\nidle_gap_minutes = -5", "must be positive"),
        ("[inference]\nprovider = 'cloud'", 'must be "local" or "api"'),
        ("[inference]\ncpu_fallback = 'yes'", "must be a bool"),
    ],
)
def test_invalid_values_rejected(tmp_path: Path, snippet: str, match: str):
    (tmp_path / "seshat.toml").write_text(snippet, encoding="utf-8")
    with pytest.raises(ConfigError, match=match):
        load_config(tmp_path)


def test_partial_config_gets_defaults(tmp_path: Path):
    (tmp_path / "seshat.toml").write_text(
        '[session]\nidle_gap_minutes = 30\n', encoding="utf-8"
    )
    cfg = load_config(tmp_path)
    assert cfg.session.idle_gap_minutes == 30
    assert cfg.watch.include  # defaults applied
    assert cfg.inference.provider == "local"


def test_always_ignored_covers_the_heavy_dirs():
    for d in (".git", ".venv", "data", "mlruns", "checkpoints", ".seshat"):
        assert d in ALWAYS_IGNORED_DIRS
