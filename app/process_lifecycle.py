from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

import psutil


def stop_owned_process(pid: int, owns: Callable[[psutil.Process], bool], timeout: float = 5.0) -> bool:
    """身份无法确认时拒绝发送信号；psutil 同时防止 PID 复用误杀。"""
    if pid <= 1 or pid == os.getpid():
        return False
    try:
        process = psutil.Process(pid)
        if process.uids().real != os.getuid() or not owns(process):
            return False
        process.terminate()
        try:
            process.wait(timeout=timeout)
        except psutil.TimeoutExpired:
            if not process.is_running() or not owns(process):
                return False
            process.kill()
            process.wait(timeout=1)
        return True
    except psutil.NoSuchProcess:
        return True
    except (psutil.Error, OSError, ValueError):
        return False


def owns_dev_service(process: psutil.Process, project_root: Path, service: str) -> bool:
    args = process.cmdline()
    if not args or not Path(process.exe()).name.lower().startswith("python"):
        return False
    root = project_root.resolve()
    if service == "main":
        return args[1:4] == ["-m", "app.cli", "main-server"] and Path(process.cwd()).resolve() == root
    if service == "control":
        script = root / "scripts" / "control_panel.py"
        return (
            len(args) == 2 and (Path(process.cwd()) / args[1]).resolve() == script
        ) or (
            args[1:3] == ["-m", "scripts.control_cli"] and Path(process.cwd()).resolve() == root
        )
    return False


def stop_dev_service(project_root: Path, service: str) -> bool:
    filename = "token_bi.pid" if service == "main" else "control_panel.pid"
    data_root = Path(os.getenv("TOKEN_BI_APP_DATA_DIR") or project_root).expanduser().resolve()
    pid_file = data_root / "runtime" / filename
    if not pid_file.exists():
        return True
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False
    stopped = stop_owned_process(pid, lambda process: owns_dev_service(process, project_root, service))
    if stopped:
        try:
            if pid_file.read_text(encoding="utf-8").strip() == str(pid):
                pid_file.unlink(missing_ok=True)
        except FileNotFoundError:
            pass
    return stopped


def stop_owned_chrome_workers(contexts_root: Path) -> None:
    root = contexts_root.resolve()
    def owns(process: psutil.Process) -> bool:
        if Path(process.exe()).name != "Google Chrome":
            return False
        profile = next((arg.split("=", 1)[1] for arg in process.cmdline()
                        if arg.startswith("--user-data-dir=")), None)
        if not profile:
            return False
        profile_path = Path(profile).resolve()
        return profile_path == root or root in profile_path.parents
    for process in psutil.process_iter():
        try:
            if process.uids().real == os.getuid() and owns(process):
                stop_owned_process(process.pid, owns)
        except (psutil.Error, OSError, ValueError):
            continue
