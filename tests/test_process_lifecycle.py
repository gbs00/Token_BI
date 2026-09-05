from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from app import process_lifecycle


def test_stale_pid_file_cannot_stop_an_unrelated_process(tmp_path, monkeypatch):
    monkeypatch.setenv("TOKEN_BI_APP_DATA_DIR", str(tmp_path))
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    pid_file = runtime / "token_bi.pid"
    pid_file.write_text(str(child.pid), encoding="utf-8")
    try:
        assert process_lifecycle.stop_dev_service(tmp_path, "main") is False
        assert child.poll() is None
        assert pid_file.exists()
    finally:
        child.terminate()
        child.wait(3)


def test_no_pid_file_does_not_probe_or_kill_port_listeners(tmp_path, monkeypatch):
    monkeypatch.setenv("TOKEN_BI_APP_DATA_DIR", str(tmp_path))
    def forbidden(*_args, **_kwargs):
        raise AssertionError("没有 PID 记录时不应探测或终止进程")
    monkeypatch.setattr(process_lifecycle.psutil, "Process", forbidden)
    assert process_lifecycle.stop_dev_service(tmp_path, "main") is True


def test_dev_process_must_match_project_and_real_command(tmp_path):
    process = SimpleNamespace(
        cmdline=lambda: [sys.executable, "-m", "app.cli", "main-server"],
        exe=lambda: sys.executable, cwd=lambda: str(tmp_path),
    )
    assert process_lifecycle.owns_dev_service(process, tmp_path, "main") is True
    assert process_lifecycle.owns_dev_service(process, tmp_path / "other", "main") is False
    process.cmdline = lambda: [sys.executable, "-c", "print('-m app.cli main-server')"]
    assert process_lifecycle.owns_dev_service(process, tmp_path, "main") is False


def test_owned_child_is_terminated_and_reaped():
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        assert process_lifecycle.stop_owned_process(child.pid, lambda p: p.cmdline()[1] == "-c")
        assert child.poll() is not None
    finally:
        if child.poll() is None:
            child.terminate()
            child.wait(3)


def test_identity_is_rechecked_before_force_kill(monkeypatch):
    calls = []
    def timeout(**_kwargs):
        raise process_lifecycle.psutil.TimeoutExpired(0.1)
    process = SimpleNamespace(
        pid=999999, uids=lambda: SimpleNamespace(real=os.getuid()),
        terminate=lambda: calls.append("terminate"), wait=timeout,
        is_running=lambda: True, kill=lambda: calls.append("kill"),
    )
    monkeypatch.setattr(process_lifecycle.psutil, "Process", lambda _pid: process)
    checks = iter([True, False])
    assert process_lifecycle.stop_owned_process(process.pid, lambda _process: next(checks)) is False
    assert calls == ["terminate"]


def test_stop_scripts_have_no_port_or_pattern_kill_fallback():
    root = Path(__file__).resolve().parents[1]
    for name in ("stop_server.sh", "stop_control_panel.sh", "stop_app_services.sh"):
        source = (root / "scripts" / name).read_text(encoding="utf-8")
        assert "--stop-dev" in source
        assert "lsof" not in source
        assert "pkill" not in source
        assert "kill -" not in source
