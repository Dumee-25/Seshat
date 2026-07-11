"""Phase B: desktop app plumbing. GUI (window, tray icon) is not tested here —
no display in CI — but every non-GUI piece it relies on is."""

import importlib.util
import socket
import threading
from pathlib import Path

import pytest
from click.testing import CliRunner

from seshat.app.server import StreamlitServer, find_free_port, theme_env
from seshat.app.supervisor import Status, WatcherSupervisor
from seshat.cli import main
from seshat.config import load_config, write_default_config
from seshat.store.db import Store

# -- server -------------------------------------------------------------------


class FakePopen:
    def __init__(self, alive: bool = True) -> None:
        self._alive = alive
        self.terminated = False
        self.killed = False

    def poll(self):
        return None if self._alive else 1

    def terminate(self):
        self.terminated = True
        self._alive = False

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.killed = True
        self._alive = False


def test_find_free_port_is_bindable():
    port = find_free_port()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", port))  # must not raise


def test_theme_env_sets_defaults_but_yields_to_existing():
    env = theme_env({"STREAMLIT_THEME_PRIMARY_COLOR": "#000000"})
    assert env["STREAMLIT_THEME_PRIMARY_COLOR"] == "#000000"  # not overridden
    assert env["STREAMLIT_THEME_BASE"] == "dark"  # filled in


def test_command_has_streamlit_run_and_port(tmp_path: Path):
    server = StreamlitServer(tmp_path)
    cmd = server.command(8080)
    assert "streamlit" in cmd and "run" in cmd
    assert "--server.port" in cmd and "8080" in cmd


def test_start_uses_runner_and_reports_running(tmp_path: Path):
    server = StreamlitServer(tmp_path)
    server.start(runner=lambda cmd: FakePopen())
    assert server.is_running()
    assert server.url.startswith("http://localhost:")
    server.start(runner=lambda cmd: FakePopen())  # idempotent, no second proc


def test_wait_until_ready_true_when_probe_passes(tmp_path: Path):
    server = StreamlitServer(tmp_path)
    server.start(runner=lambda cmd: FakePopen())
    assert server.wait_until_ready(probe=lambda url: True, sleep=lambda s: None)


def test_wait_until_ready_false_when_process_dies(tmp_path: Path):
    server = StreamlitServer(tmp_path)
    server.start(runner=lambda cmd: FakePopen(alive=False))
    assert not server.wait_until_ready(
        timeout=0.2, probe=lambda url: True, sleep=lambda s: None
    )


def test_wait_until_ready_times_out(tmp_path: Path):
    server = StreamlitServer(tmp_path)
    server.start(runner=lambda cmd: FakePopen())
    assert not server.wait_until_ready(
        timeout=0.05, probe=lambda url: False, sleep=lambda s: None
    )


def test_stop_terminates(tmp_path: Path):
    server = StreamlitServer(tmp_path)
    proc = FakePopen()
    server.start(runner=lambda cmd: proc)
    server.stop()
    assert proc.terminated
    assert not server.is_running()
    server.stop()  # safe when already stopped


# -- supervisor ---------------------------------------------------------------


class FakeService:
    def __init__(self) -> None:
        self.started = threading.Event()
        self._stop = threading.Event()
        self._paused = False
        self.scanned = False

    def baseline_scan(self) -> int:
        self.scanned = True
        return 0

    def run(self) -> None:
        self.started.set()
        self._stop.wait(5)

    def stop(self) -> None:
        self._stop.set()

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    @property
    def paused(self) -> bool:
        return self._paused


@pytest.fixture
def store():
    with Store.in_memory() as s:
        yield s


def test_supervisor_start_runs_thread_then_stops(store: Store):
    service = FakeService()
    sup = WatcherSupervisor(service, store)
    sup.start()
    assert service.started.wait(5)
    assert sup.is_alive()
    assert service.scanned
    sup.stop()
    assert not sup.is_alive()


def test_supervisor_toggle_pause(store: Store):
    service = FakeService()
    sup = WatcherSupervisor(service, store)
    assert sup.toggle_pause() is True
    assert sup.paused is True
    assert sup.toggle_pause() is False


def test_supervisor_status_counts_queued(store: Store):
    for _ in range(3):
        sid = store.create_session()
        store.close_session(sid)  # closed == queued for journaling
    sid = store.create_session()
    store.close_session(sid)
    store.mark_session_processed(sid)
    status = WatcherSupervisor(FakeService(), store).status()
    assert status.queued == 3
    assert status.sessions == 4


def test_status_label():
    assert Status(running=True, paused=False, queued=0, sessions=5).label() == "Watching"
    assert Status(running=True, paused=False, queued=2, sessions=5).label() == "Watching · 2 queued"
    assert Status(running=True, paused=True, queued=1, sessions=5).label() == "Paused · 1 queued"
    assert Status(running=False, paused=False, queued=0, sessions=0).label() == "Stopped"


# -- pause in the watch service -----------------------------------------------


def test_paused_service_drops_events(tmp_path: Path):
    from seshat.watcher.daemon import WatchService

    write_default_config(tmp_path)
    with Store.open(tmp_path) as store:
        service = WatchService(tmp_path, load_config(tmp_path), store)
        script = tmp_path / "train.py"
        script.write_text("x = 1", encoding="utf-8")
        service.process_file(script)  # baseline
        script.write_text("x = 2", encoding="utf-8")
        service.pause()
        assert service.process_file(script) is None  # dropped
        assert store.events() == []
        service.resume()
        assert service.process_file(script) is not None


# -- window entrypoint --------------------------------------------------------


def test_window_main_usage_without_args():
    from seshat.app.window import main as window_main

    assert window_main([]) == 2  # prints usage, does not import webview


# -- desktop app wiring (no GUI) ----------------------------------------------


def test_desktop_app_constructs_and_reports_status(tmp_path: Path):
    from seshat.app.desktop import DesktopApp

    write_default_config(tmp_path)
    app = DesktopApp(tmp_path, load_config(tmp_path), log=lambda m: None)
    try:
        assert isinstance(app.status_label(), str)
        assert app.is_paused() is False
        app.toggle_pause()
        assert app.is_paused() is True
    finally:
        app.quit()  # closes all store/vector connections


# -- CLI ----------------------------------------------------------------------


def test_app_command_errors_without_desktop_extra(tmp_path: Path):
    if all(
        importlib.util.find_spec(n) for n in ("streamlit", "webview", "pystray", "PIL")
    ):
        pytest.skip("desktop extra present; invoking would launch a GUI")
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        assert runner.invoke(main, ["init"]).exit_code == 0
        result = runner.invoke(main, ["app"])
        assert result.exit_code != 0
        assert "seshat[ui,desktop]" in result.output
