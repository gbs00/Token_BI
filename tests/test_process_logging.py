from __future__ import annotations

import io
import stat
import subprocess
import sys

import pytest

from app.process_logging import capture_process_output, open_process_log


def test_process_log_limits_size_count_and_keeps_latest_output(tmp_path):
    path = tmp_path / "server.log"
    path.write_bytes(b"old log\n" * 1000)
    path.with_name("server.log.1").write_bytes(b"older log\n" * 1000)
    path.with_name("server.log.2").write_bytes(b"oldest log\n" * 1000)
    handler = open_process_log(path, max_bytes=256, backup_count=2)
    stream = io.BytesIO(("日志片段\n" * 100).encode() + b"\xff" * 512 + b"\nfinal marker\n")

    worker = capture_process_output(stream, handler)
    worker.join(timeout=2)

    assert not worker.is_alive()
    assert stream.closed
    files = list(tmp_path.glob("server.log*"))
    assert len(files) == 3
    assert all(file.stat().st_size <= 256 for file in files)
    assert all(stat.S_IMODE(file.stat().st_mode) == 0o600 for file in files)
    assert "final marker" in path.read_text()


def test_process_log_captures_stderr_and_finishes_after_child_exit(tmp_path):
    process = subprocess.Popen(
        [sys.executable, "-c", "print('stdout fixture', flush=True); raise RuntimeError('stderr fixture')"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    path = tmp_path / "server.log"
    worker = capture_process_output(process.stdout, open_process_log(path))
    try:
        assert process.wait(timeout=5) == 1
        worker.join(timeout=2)
        assert not worker.is_alive()
        assert "stdout fixture" in path.read_text()
        assert "RuntimeError: stderr fixture" in path.read_text()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


def test_log_retention_does_not_modify_symlink_target(tmp_path):
    external = tmp_path / "unrelated-file.txt"
    external.write_bytes(b"unrelated data\n" * 100)
    original = external.read_bytes()
    (tmp_path / "server.log").symlink_to(external)

    with pytest.raises(OSError, match="符号链接"):
        open_process_log(tmp_path / "server.log", max_bytes=256)

    assert external.read_bytes() == original
