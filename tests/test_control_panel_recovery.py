"""Fault injection for owned process recovery and updater shutdown handoff."""
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import psutil

from scripts import control_panel as control


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    monkeypatch.setattr(control, "PID_FILE", tmp_path / "main.pid")
    monkeypatch.setattr(control, "RUNTIME_STATE_FILE", tmp_path / "runtime.json")
    monkeypatch.setattr(control, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(control, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(control, "_shutdown_requested", threading.Event())
    monkeypatch.setattr(control, "_pid_alive", lambda _pid: True)
    monkeypatch.setattr(control, "_port_available", lambda _port: True)
    control.PID_FILE.write_text("12345", encoding="utf-8")
    control._write_runtime_state(port=9876, pid=12345)
    return control


@pytest.mark.parametrize("port_busy", [False, True])
def test_failed_stop_preserves_runtime_for_retry(runtime, monkeypatch, port_busy):
    stopped = []
    monkeypatch.setattr(runtime, "_stop_pid", lambda pid: stopped.append(pid) or port_busy)
    monkeypatch.setattr(runtime, "_port_available", lambda _port: not port_busy)
    for _ in range(2):
        assert runtime._stop_main_server_process()[0] is False
        assert runtime.PID_FILE.read_text() == "12345"
        assert runtime._current_main_port() == 9876
    assert stopped == ["12345", "12345"]


def test_start_reuses_only_matching_healthy_service(runtime, monkeypatch):
    monkeypatch.setattr(runtime, "_main_server_running", lambda: (True, "12345"))
    monkeypatch.setattr(runtime, "_main_api_request", lambda *_args, **_kwargs:
                        {"ok": True, "service": runtime.MAIN_SERVICE_MARKER, "pid": 12345})
    monkeypatch.setattr(runtime, "_stop_pid", lambda _pid: pytest.fail("healthy service was stopped"))
    assert runtime._start_main_server_process()[0] is True


@pytest.mark.parametrize("can_stop", [True, False])
@pytest.mark.parametrize("health", [None, {"ok": True, "service": "token-bi-main-service", "pid": 999}])
def test_retry_recovers_unhealthy_service_only_after_owned_stop(runtime, monkeypatch, can_stop, health):
    events = []
    def probe(*_args, **_kwargs):
        if health is None:
            raise RuntimeError("timeout")
        return health
    monkeypatch.setattr(runtime, "_main_server_running", lambda: (True, "12345"))
    monkeypatch.setattr(runtime, "_main_api_request", probe)
    monkeypatch.setattr(runtime, "_stop_pid", lambda pid: events.append(("stop", pid)) or can_stop)
    monkeypatch.setattr(runtime, "_select_main_port", lambda *_args: 9876)
    monkeypatch.setattr(runtime, "_backend_command", lambda _args: ["fake-backend"])
    monkeypatch.setattr(runtime.subprocess, "Popen", lambda *_args, **_kwargs:
                        events.append(("start", "23456")) or SimpleNamespace(pid=23456))
    monkeypatch.setattr(runtime, "_wait_for_main_server", lambda **_kwargs: True)
    assert runtime._start_main_server_process()[0] is can_stop
    assert events == ([("stop", "12345"), ("start", "23456")] if can_stop else [("stop", "12345")])
    assert runtime.PID_FILE.read_text() == ("23456" if can_stop else "12345")


def test_shutdown_blocks_new_starts(runtime, monkeypatch):
    runtime._shutdown_requested.set()
    monkeypatch.setattr(runtime, "_main_server_running", lambda: pytest.fail("must not start while exiting"))
    assert runtime._start_main_server_process()[0] is False


def test_start_timeout_retains_process_ownership_if_cleanup_fails(runtime, monkeypatch):
    monkeypatch.setattr(runtime, "_main_server_running", lambda: (False, None))
    monkeypatch.setattr(runtime, "_select_main_port", lambda *_args: 9876)
    monkeypatch.setattr(runtime, "_backend_command", lambda _args: ["fake-backend"])
    monkeypatch.setattr(runtime.subprocess, "Popen", lambda *_args, **_kwargs: SimpleNamespace(pid=23456))
    monkeypatch.setattr(runtime, "_wait_for_main_server", lambda **_kwargs: False)
    monkeypatch.setattr(runtime, "_stop_pid", lambda _pid: False)
    assert runtime._start_main_server_process()[0] is False
    assert runtime.PID_FILE.read_text() == "23456"
    assert runtime.RUNTIME_STATE_FILE.exists()


def test_shutdown_failure_keeps_control_alive_and_allows_retry(runtime, monkeypatch):
    stops = []
    def stop():
        stops.append(1)
        return len(stops) > 1, "test stop result"
    monkeypatch.setattr(runtime, "_stop_main_server_process", stop)
    server = runtime.ThreadingHTTPServer(("127.0.0.1", 0), runtime.ControlPanelHandler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{server.server_port}", trust_env=False) as client:
            response = client.post("/api/app/shutdown", headers={"X-Token-BI-Control-Pid": "-1"})
            assert response.json()["ok"] is False
            assert stops == []
            response = client.post("/api/app/shutdown", headers={"X-Token-BI-Control-Pid": str(os.getpid())})
            assert response.json()["ok"] is False
            assert worker.is_alive() and not runtime._shutdown_requested.is_set()
            assert client.post("/api/app/shutdown").json()["ok"] is True
            worker.join(2)
            assert not worker.is_alive()
            assert runtime._shutdown_requested.is_set()
    finally:
        server.shutdown()
        server.server_close()
        worker.join(2)


@pytest.mark.skipif(not hasattr(signal, "SIGSTOP"), reason="requires POSIX process suspension")
def test_real_control_recovers_hung_owned_backend_and_shuts_down(tmp_path):
    root = Path(__file__).resolve().parents[1]
    accounts = tmp_path / "config/accounts.json"
    accounts.parent.mkdir()
    accounts.write_text('{"accounts":[],"access_enabled":false}', encoding="utf-8")
    ports = []
    reservations = [socket.socket(), socket.socket()]
    for reservation in reservations:
        reservation.bind(("127.0.0.1", 0))
        ports.append(reservation.getsockname()[1])
    for reservation in reservations:
        reservation.close()
    environment = {**os.environ, "HOME": str(tmp_path), "CODEX_HOME": str(tmp_path / "no-auth"),
                   "TOKEN_BI_APP_DATA_DIR": str(tmp_path), "TOKEN_BI_CODEX_CLI_BIN": "/missing/codex",
                   "TOKEN_BI_HOST": "127.0.0.1", "TOKEN_BI_PORT_MAX": str(ports[1]),
                   "TOKEN_BI_USE_MOCK_SCRAPER": "false", "PYTHONDONTWRITEBYTECODE": "1",
                   "HTTP_PROXY": "http://127.0.0.1:1", "http_proxy": "http://127.0.0.1:1",
                   "NO_PROXY": "", "no_proxy": ""}
    process = subprocess.Popen([sys.executable, "-m", "scripts.control_cli", "--port", str(ports[0]),
                                "--main-port", str(ports[1])], cwd=root, env=environment,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    owned = []
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{ports[0]}", trust_env=False, timeout=20) as client:
            deadline = time.monotonic() + 10
            while True:
                try:
                    if client.get("/api/app/health").status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                assert process.poll() is None and time.monotonic() < deadline
                time.sleep(0.05)
            result = client.post("/api/start").json()
            assert result["ok"] is True, result
            pid_file = tmp_path / "runtime/token_bi.pid"
            first = psutil.Process(int(pid_file.read_text()))
            owned.append(first)
            assert first.cmdline()[1:4] == ["-m", "app.cli", "main-server"]
            first.send_signal(signal.SIGSTOP)
            result = client.post("/api/start").json()
            assert result["ok"] is True, result
            second = psutil.Process(int(pid_file.read_text()))
            owned.append(second)
            assert second.pid != first.pid and not first.is_running()
            assert client.post("/api/app/shutdown", headers={"X-Token-BI-Control-Pid": str(process.pid)}).json()["ok"] is True
            assert process.wait(timeout=5) == 0
            assert not second.is_running()
            for port in ports:
                with socket.socket() as probe:
                    assert probe.connect_ex(("127.0.0.1", port)) != 0
    finally:
        for child in owned:
            try:
                if child.is_running():
                    child.kill()
                    child.wait(timeout=3)
            except psutil.NoSuchProcess:
                pass
        if process.poll() is None:
            process.kill()
            process.wait(timeout=3)
