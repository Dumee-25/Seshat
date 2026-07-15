"""Phase B: desktop app plumbing. GUI (window, tray icon) is not tested here —
no display in CI — but every non-GUI piece it relies on is."""

import importlib.util
import json
import socket
import threading
import urllib.request
from pathlib import Path

import pytest
from click.testing import CliRunner

from seshat.api.server import ApiServer, find_free_port
from seshat.app.supervisor import Status, WatcherSupervisor
from seshat.cli import main
from seshat.config import load_config, write_default_config
from seshat.store.db import Store

# -- server (the cockpit API the window points at) -----------------------------


@pytest.fixture
def project(tmp_path: Path):
    write_default_config(tmp_path)
    return tmp_path, load_config(tmp_path)


def test_find_free_port_is_bindable():
    port = find_free_port()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", port))  # must not raise


def test_server_takes_a_free_port_when_none_given(project):
    root, config = project
    server = ApiServer(root, config)
    assert server.port > 0
    assert server.url == f"http://localhost:{server.port}"
    assert not server.is_running()  # constructing does not start it


def test_server_honours_an_explicit_port(project):
    root, config = project
    assert ApiServer(root, config, port=8765).port == 8765


def test_wait_until_ready_is_false_before_start(project):
    root, config = project
    assert not ApiServer(root, config).wait_until_ready(timeout=0.2)


def test_server_serves_the_api_then_stops(project):
    """The one end-to-end check that the desktop app's window will have
    something to load: start the real server, hit it over HTTP, stop it."""
    root, config = project
    server = ApiServer(root, config)
    server.start()
    try:
        assert server.wait_until_ready(timeout=20)
        server.start()  # idempotent: no second thread
        with urllib.request.urlopen(f"{server.url}/api/health", timeout=5) as response:
            assert json.loads(response.read())["ok"] is True
    finally:
        server.stop()
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
        importlib.util.find_spec(n)
        for n in ("fastapi", "uvicorn", "webview", "pystray", "PIL")
    ):
        pytest.skip("desktop extra present; invoking would launch a GUI")
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        assert runner.invoke(main, ["init"]).exit_code == 0
        result = runner.invoke(main, ["app"])
        assert result.exit_code != 0
        assert "seshat[desktop]" in result.output


def test_ui_command_is_gone():
    """`seshat ui` was the Streamlit entry point; it should not come back."""
    result = CliRunner().invoke(main, ["ui"])
    assert result.exit_code != 0
    assert "No such command" in result.output
