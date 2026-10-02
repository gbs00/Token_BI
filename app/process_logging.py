from __future__ import annotations

import logging
import os
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import BinaryIO


MAX_LOG_BYTES = 5 * 1024 * 1024
LOG_BACKUP_COUNT = 2


class _PrivateLogHandler(RotatingFileHandler):
    def _open(self):
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(self.baseFilename, flags, 0o600)
        os.fchmod(descriptor, 0o600)
        return os.fdopen(descriptor, "a", encoding="utf-8", errors="replace")

    def shouldRollover(self, record):
        message = (self.format(record) + self.terminator).encode("utf-8", errors="replace")
        self.stream.seek(0, os.SEEK_END)
        return self.stream.tell() + len(message) > self.maxBytes


def open_process_log(path: Path, *, max_bytes: int = MAX_LOG_BYTES,
                     backup_count: int = LOG_BACKUP_COUNT) -> RotatingFileHandler:
    path.parent.mkdir(parents=True, exist_ok=True)
    # 首次升级时也限制历史日志，避免巨大的旧文件一直占用备份名额。
    for candidate in [path, *(path.with_name(f"{path.name}.{i}") for i in range(1, backup_count + 1))]:
        if candidate.is_symlink():
            raise OSError("运行日志路径不允许使用符号链接。")
        if candidate.is_file() and candidate.stat().st_size > max_bytes:
            with candidate.open("r+b") as handle:
                handle.seek(-max_bytes, os.SEEK_END)
                suffix = handle.read(max_bytes)
                handle.seek(0)
                handle.write(suffix)
                handle.truncate()
        if candidate.exists():
            candidate.chmod(0o600)
    handler = _PrivateLogHandler(path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    return handler


def capture_process_output(stream: BinaryIO, handler: RotatingFileHandler) -> threading.Thread:
    def drain() -> None:
        try:
            # 有界分段，长行和无效 UTF-8 也不能绕过日志容量上限。
            limit = min(65536, max(1, handler.maxBytes // 4))
            while chunk := stream.readline(limit):
                message = chunk.decode("utf-8", errors="replace").rstrip("\r\n")
                handler.handle(logging.LogRecord("token-bi.server", logging.INFO, "", 0, message, (), None))
        finally:
            stream.close()
            handler.close()

    thread = threading.Thread(target=drain, name="token-bi-server-log", daemon=True)
    thread.start()
    return thread
