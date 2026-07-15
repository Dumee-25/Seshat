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


def test_commands_require_config(tmp_path: Path):
    runner = CliRunner()
    for command in ("watch", "backfill", "reprocess", "install-hooks"):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(main, [command])
            assert result.exit_code != 0
            assert "seshat init" in result.output


def _seed_project(root: Path) -> int:
    from seshat.store.db import Store
    from seshat.store.schema import JournalEntry

    with Store.open(root) as store:
        sid = store.create_session(started_at="2026-03-01T09:00:00+00:00")
        store.close_session(sid)
        store.mark_session_processed(sid)
        return store.add_entry(JournalEntry(
            session_id=sid,
            what_changed="Added SMOTE oversampling.",
            inferred_intent="class imbalance",
            intent_confidence=0.8,
            model_version="fake", prompt_version="v2",
        ))


def test_audit_confirms_and_logs(tmp_path: Path):
    from seshat.store.db import Store

    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
        assert runner.invoke(main, ["init"]).exit_code == 0
        entry_id = _seed_project(Path(fs))
        result = runner.invoke(main, ["audit", "--sample", "5"], input="c\n")
        assert result.exit_code == 0, result.output
        assert "1 correct" in result.output
        with Store.open(Path(fs)) as store:
            assert store.get_entry(entry_id).intent_status == "confirmed"
        log = (Path(fs) / ".seshat" / "audit_log.jsonl").read_text(encoding="utf-8")
        assert '"label": "correct"' in log


def test_audit_wrong_asks_for_correction(tmp_path: Path):
    from seshat.store.db import Store

    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
        assert runner.invoke(main, ["init"]).exit_code == 0
        entry_id = _seed_project(Path(fs))
        result = runner.invoke(main, ["audit"], input="w\nleaked target column\n")
        assert result.exit_code == 0, result.output
        with Store.open(Path(fs)) as store:
            entry = store.get_entry(entry_id)
        assert entry.intent_status == "corrected"
        assert entry.inferred_intent == "leaked target column"


def test_stats_reports_counts(tmp_path: Path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
        assert runner.invoke(main, ["init"]).exit_code == 0
        _seed_project(Path(fs))
        result = runner.invoke(main, ["stats"])
        assert result.exit_code == 0, result.output
        assert "Sessions: 1" in result.output
        assert "processed 1" in result.output
        assert "inferred 1" in result.output


def test_version_flag():
    result = CliRunner().invoke(main, ["--version"])
    assert result.exit_code == 0
    assert "seshat" in result.output
