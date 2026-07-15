"""Phase C: frozen-aware launching, first-run setup, autostart, user config.

The PyInstaller/Inno build itself is a Windows-only manual step; here we test
the code the build relies on, plus the spec's bundling contract (cheap text
assertions — a broken spec is only discovered at build time otherwise)."""

import json
from pathlib import Path

import pytest

from seshat.app import autostart, launch, setup, userconfig
from seshat.config import load_config, write_default_config

SPEC = (Path(__file__).resolve().parent.parent / "packaging" / "seshat.spec").read_text()
BUILD_PS1 = (Path(__file__).resolve().parent.parent / "packaging" / "build.ps1").read_text()


# -- the frozen bundle's contract ---------------------------------------------


def test_spec_bundles_the_built_react_app():
    assert 'str(STATIC), "seshat/api/static"' in SPEC


def test_spec_collects_uvicorns_runtime_imports():
    for hidden in ("uvicorn.loops.auto", "uvicorn.protocols.http.auto"):
        assert hidden in SPEC


def test_spec_excludes_streamlit():
    assert '"streamlit", "altair", "pyarrow"' in SPEC
    assert "collect_all" in SPEC and "streamlit" not in SPEC.split("excludes=")[0]


def test_build_script_builds_the_frontend_before_freezing():
    assert BUILD_PS1.index("npm run build") < BUILD_PS1.index("PyInstaller")

# -- launch (frozen-aware commands) -------------------------------------------


def test_dev_commands_use_python_dash_m():
    assert launch.is_frozen() is False
    wcmd = launch.window_command("http://localhost:8080", "Seshat")
    assert "-m" in wcmd and "seshat.app.window" in wcmd


def test_frozen_commands_reinvoke_the_exe(monkeypatch):
    monkeypatch.setattr(launch.sys, "frozen", True, raising=False)
    monkeypatch.setattr(launch.sys, "executable", "C:/Program Files/Seshat/Seshat.exe")
    wcmd = launch.window_command("http://x", "Seshat")
    assert wcmd[:2] == ["C:/Program Files/Seshat/Seshat.exe", launch.RUN_WINDOW_FLAG]


def test_dispatch_ignores_normal_argv():
    assert launch.dispatch([]) is False
    assert launch.dispatch(["watch"]) is False


def test_dispatch_routes_window(monkeypatch):
    opened = {}
    monkeypatch.setattr(
        "seshat.app.window.open_window",
        lambda url, title="Seshat": opened.update(url=url, title=title),
    )
    assert launch.dispatch([launch.RUN_WINDOW_FLAG, "http://localhost:8765", "Seshat"]) is True
    assert opened == {"url": "http://localhost:8765", "title": "Seshat"}


def test_no_streamlit_sub_mode_remains():
    """The API runs in-process now; nothing should re-invoke the exe for a UI
    server."""
    assert not hasattr(launch, "RUN_STREAMLIT_FLAG")
    assert launch.dispatch(["--seshat-run-streamlit", "8600"]) is False


# -- user config (default project memory) -------------------------------------


@pytest.fixture
def userdir(tmp_path, monkeypatch):
    monkeypatch.setattr(userconfig, "USER_DIR", tmp_path / ".seshat")
    monkeypatch.setattr(userconfig, "USER_CONFIG", tmp_path / ".seshat" / "app.toml")
    return tmp_path


def test_default_project_roundtrip(userdir, tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    write_default_config(project)
    userconfig.set_default_project(project)
    assert userconfig.get_default_project() == project


def test_default_project_ignored_if_config_gone(userdir, tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    write_default_config(project)
    userconfig.set_default_project(project)
    (project / "seshat.toml").unlink()  # project deconfigured
    assert userconfig.get_default_project() is None


def test_resolve_prefers_cwd_then_default(userdir, tmp_path):
    cwd_project = tmp_path / "here"
    cwd_project.mkdir()
    write_default_config(cwd_project)
    assert userconfig.resolve_project(cwd=cwd_project) == cwd_project

    other = tmp_path / "there"
    other.mkdir()
    write_default_config(other)
    userconfig.set_default_project(other)
    assert userconfig.resolve_project(cwd=tmp_path) == other  # tmp_path is not a project


def test_resolve_none_when_nothing(userdir, tmp_path):
    assert userconfig.resolve_project(cwd=tmp_path) is None


# -- setup (Ollama detection + pulls) -----------------------------------------


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return json.dumps(self._payload).encode()


def opener_with(models):
    def opener(url, timeout=5):
        return FakeResponse({"models": [{"name": m} for m in models]})

    return opener


def unreachable_opener(url, timeout=5):
    raise OSError("connection refused")


@pytest.fixture
def config(tmp_path):
    write_default_config(tmp_path)
    return load_config(tmp_path)


def test_setup_ollama_not_installed(config):
    report = setup.run_setup(config, which=lambda name: None)
    assert not report.ollama_installed
    assert not report.ok
    assert set(report.missing) == {config.inference.model, config.inference.embed_model}


def test_setup_ollama_not_running(config):
    report = setup.run_setup(
        config, which=lambda name: "ollama", opener=unreachable_opener
    )
    assert report.ollama_installed and not report.ollama_running
    assert not report.ok


def test_setup_all_models_present(config):
    report = setup.run_setup(
        config,
        which=lambda name: "ollama",
        opener=opener_with(["qwen3:8b", "nomic-embed-text:latest"]),
    )
    assert report.ok
    assert report.pulled == []


def test_setup_pulls_missing(config):
    class Result:
        returncode = 0

    pulled = []
    report = setup.run_setup(
        config,
        which=lambda name: "ollama",
        opener=opener_with(["qwen3:8b"]),  # embed model missing
        runner=lambda cmd, **kw: pulled.append(cmd[-1]) or Result(),
    )
    assert report.ok
    assert report.pulled == ["nomic-embed-text"]


def test_setup_no_pull_reports_missing(config):
    report = setup.run_setup(
        config, which=lambda name: "ollama", opener=opener_with([]), pull=False
    )
    assert not report.ok
    assert set(report.missing) == {config.inference.model, config.inference.embed_model}


# -- autostart (run at login) -------------------------------------------------


class FakeRegistry:
    def __init__(self):
        self.store = {}

    def get(self, key, name):
        return self.store.get((key, name))

    def set(self, key, name, value):
        self.store[(key, name)] = value

    def delete(self, key, name):
        self.store.pop((key, name), None)


def test_autostart_enable_disable_status():
    reg = FakeRegistry()
    assert autostart.is_enabled(backend=reg) is False
    autostart.enable(command='"C:/Seshat/Seshat.exe"', backend=reg)
    assert autostart.is_enabled(backend=reg) is True
    assert reg.store[(autostart.RUN_KEY, "Seshat")] == '"C:/Seshat/Seshat.exe"'
    autostart.disable(backend=reg)
    assert autostart.is_enabled(backend=reg) is False


def test_launch_command_dev_form():
    cmd = autostart.launch_command()
    assert "seshat.cli" in cmd and "app" in cmd


# -- entry (frozen dispatch + default to app) ---------------------------------


def test_entry_handles_internal_mode(monkeypatch):
    from seshat.app import entry

    monkeypatch.setattr(launch, "dispatch", lambda argv: True)
    called = {"cli": False}
    monkeypatch.setattr("seshat.cli.main", lambda: called.__setitem__("cli", True))
    entry.main(["--seshat-run-window", "http://x"])
    assert called["cli"] is False  # dispatch handled it; CLI never ran


def test_entry_no_args_becomes_app(monkeypatch):
    from seshat.app import entry

    monkeypatch.setattr(launch, "dispatch", lambda argv: False)
    seen = {}
    monkeypatch.setattr("seshat.cli.main", lambda: seen.update(argv=list(entry.sys.argv)))
    entry.main([])
    assert seen["argv"][-1] == "app"


def test_entry_passes_through_cli(monkeypatch):
    from seshat.app import entry

    monkeypatch.setattr(launch, "dispatch", lambda argv: False)
    ran = {"cli": False}
    monkeypatch.setattr("seshat.cli.main", lambda: ran.__setitem__("cli", True))
    entry.main(["stats"])
    assert ran["cli"] is True
