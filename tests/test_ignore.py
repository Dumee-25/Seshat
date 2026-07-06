from pathlib import Path

import pytest

from seshat.config import load_config, write_default_config
from seshat.watcher.ignore import PathFilter


@pytest.fixture
def project(tmp_path: Path) -> Path:
    write_default_config(tmp_path)
    return tmp_path


def make_filter(project: Path) -> PathFilter:
    return PathFilter(project, load_config(project))


def touch(project: Path, rel: str, content: str = "x") -> Path:
    path = project / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_include_globs_match_watched_types(project: Path):
    f = make_filter(project)
    assert f.should_index(touch(project, "train.py"))
    assert f.should_index(touch(project, "notebooks/eda.ipynb", "{}"))
    assert not f.should_index(touch(project, "notes.txt"))


def test_always_ignored_dirs_win_over_includes(project: Path):
    f = make_filter(project)
    for rel in (".venv/lib/pkg.py", "data/gen.py", "mlruns/x/meta.py", ".seshat/tmp.py"):
        assert not f.should_index(touch(project, rel))


def test_gitignore_respected(project: Path):
    touch(project, ".gitignore", "secret_*.py\n")
    f = make_filter(project)
    assert not f.should_index(touch(project, "secret_keys.py"))
    assert f.should_index(touch(project, "train.py"))


def test_results_files_win_over_gitignore(project: Path):
    # results/ is typically gitignored, but it's exactly what Seshat captures.
    touch(project, ".gitignore", "results/\n")
    f = make_filter(project)
    assert f.should_index(touch(project, "results/metrics.csv"))
    assert f.is_result_file(project / "results" / "metrics.csv")
    assert not f.should_index(touch(project, "results/model.bin"))


def test_config_exclude_glob(project: Path):
    (project / "seshat.toml").write_text(
        '[watch]\ninclude = ["**/*.py"]\nexclude = ["experiments/**"]\n',
        encoding="utf-8",
    )
    f = make_filter(project)
    assert not f.should_index(touch(project, "experiments/scratch.py"))
    assert f.should_index(touch(project, "train.py"))


def test_size_cap(project: Path):
    (project / "seshat.toml").write_text(
        '[watch]\ninclude = ["**/*.py"]\nmax_file_size_mb = 0.0001\n',  # ~104 bytes
        encoding="utf-8",
    )
    f = make_filter(project)
    assert not f.should_index(touch(project, "big.py", "x" * 1000))
    assert f.should_index(touch(project, "small.py", "x"))


def test_outside_project_rejected(project: Path, tmp_path_factory):
    outside = tmp_path_factory.mktemp("elsewhere") / "train.py"
    outside.write_text("x", encoding="utf-8")
    assert not make_filter(project).should_index(outside)
