from pathlib import Path

from click.testing import CliRunner

from seshat.cli import main


def test_init_creates_valid_config(tmp_path: Path):
    runner = CliRunner()
    result = runner.invoke(main, ["init", "--path", str(tmp_path), "--name", "demo"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "seshat.toml").exists()
    assert "Created" in result.output


def test_init_twice_fails_without_force(tmp_path: Path):
    runner = CliRunner()
    assert runner.invoke(main, ["init", "--path", str(tmp_path)]).exit_code == 0
    result = runner.invoke(main, ["init", "--path", str(tmp_path)])
    assert result.exit_code != 0
    assert "already exists" in result.output

    result = runner.invoke(main, ["init", "--path", str(tmp_path), "--force"])
    assert result.exit_code == 0


def test_stub_commands_require_config(tmp_path: Path):
    runner = CliRunner()
    for command in ("watch", "backfill", "reprocess", "ui"):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(main, [command])
            assert result.exit_code != 0
            assert "seshat init" in result.output


def test_stub_commands_point_at_build_plan(tmp_path: Path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        assert runner.invoke(main, ["init"]).exit_code == 0
        for command in ("watch", "backfill", "reprocess", "ui"):
            result = runner.invoke(main, [command])
            assert result.exit_code != 0
            assert "BUILD_PLAN.md" in result.output


def test_version_flag():
    result = CliRunner().invoke(main, ["--version"])
    assert result.exit_code == 0
    assert "seshat" in result.output
