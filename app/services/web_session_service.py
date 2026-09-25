from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from app.config import Settings
from app.models.account import AccountRecord
from app.models.browser_session import BrowserSessionSnapshot, BrowserSessionState
from app.services.source_errors import AnalyticsPageChangedError, LiveSessionRequiredError, ScraperUnavailableError


class NativeWebSession:
    """持有唯一子进程，通过匿名管道收发有界 JSON；不监听网络端口。"""

    def __init__(self, executable: Path, profile: Optional[str], on_event: Callable[[str], None], *, fixture: Optional[str] = None):
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._responses: dict[str, Optional[dict]] = {}
        self._closed = False
        self._on_event = on_event
        args = [str(executable), "--stdio"]
        if profile:
            args += ["--profile", profile]
        elif not fixture:
            raise ValueError("Production web session requires a profile")
        if fixture:
            args += ["--fixture", fixture]
        self._process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.DEVNULL, close_fds=True)
        self._reader = threading.Thread(target=self._read, name="token-bi-web-session", daemon=True)
        self._reader.start()

    def _read(self) -> None:
        try:
            while True:
                line = self._process.stdout.readline(131073)
                if not line or len(line) > 131072 or not line.endswith(b"\n"):
                    break
                try:
                    value = json.loads(line)
                except (ValueError, UnicodeError):
                    break
                if not isinstance(value, dict):
                    break
                with self._condition:
                    if self._closed:
                        break
                    request_id = value.get("id")
                    if isinstance(request_id, str) and request_id in self._responses:
                        result = value.get("result")
                        self._responses[request_id] = result if isinstance(result, dict) else {"category": "schema_changed"}
                        self._condition.notify_all()
                    event = value.get("event")
                if event in {"session_ready", "wake", "login_closed", "network_online", "network_offline"}:
                    self._on_event(event)
        finally:
            with self._condition:
                self._closed = True
                self._condition.notify_all()
            if self._process.poll() is None:
                self._process.terminate()

    @property
    def alive(self) -> bool:
        return not self._closed and self._process.poll() is None

    def request(self, method: str, identity: Optional[str] = None, timeout: float = 28) -> dict:
        if method not in {"collect", "login", "status", "hide"}:
            raise ValueError("Unknown native operation")
        request_id = uuid.uuid4().hex
        command = {"id": request_id, "method": method}
        if identity:
            command["expected_identity"] = identity
        with self._condition:
            if not self.alive:
                raise LiveSessionRequiredError("原生网页组件已停止。")
            self._responses[request_id] = None
            try:
                self._process.stdin.write((json.dumps(command) + "\n").encode())
                self._process.stdin.flush()
                completed = self._condition.wait_for(
                    lambda: self._closed or self._responses.get(request_id) is not None, timeout,
                )
                result = self._responses.get(request_id)
                if not completed:
                    raise TimeoutError("原生网页组件未在截止时间内响应。")
                if not isinstance(result, dict):
                    raise LiveSessionRequiredError("原生网页组件已停止。")
                return result
            finally:
                self._responses.pop(request_id, None)

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()
            if self._process.stdin:
                try:
                    self._process.stdin.close()
                except OSError:
                    pass
        try:
            self._process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self._process.terminate()
            try:
                self._process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=2)
        if threading.current_thread() is not self._reader:
            self._reader.join(timeout=1)
        if self._process.stdout:
            self._process.stdout.close()


class WebSessionService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._lock = threading.RLock()
        self._bridge: Optional[NativeWebSession] = None
        self._generation = 0
        self._restart_after = 0.0
        self._stopped = False
        self._online: Optional[bool] = None
        self._session: Optional[BrowserSessionSnapshot] = None
        self._profile_path = settings.runtime_dir / "web-session.json"
        self.on_event: Callable[[str], None] = lambda event: None
        self.access_enabled: Callable[[], bool] = lambda: True

    def available(self) -> bool:
        return self._settings.web_session_bin.is_file() and os.access(self._settings.web_session_bin, os.X_OK)

    def network_available(self) -> Optional[bool]:
        with self._lock:
            return self._online if self._bridge and self._bridge.alive else None

    def _profile(self, create: bool) -> str:
        if self._profile_path.exists():
            try:
                return str(uuid.UUID(json.loads(self._profile_path.read_text())["profile"]))
            except (ValueError, KeyError, OSError, TypeError):
                raise AnalyticsPageChangedError("网页会话配置无法读取，请重新连接账号。")
        if not create:
            raise LiveSessionRequiredError("尚未建立 Token BI 网页会话，请在 Mac 端登录。")
        value = str(uuid.uuid4())
        descriptor = os.open(self._profile_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "w") as handle:
            json.dump({"profile": value}, handle)
        return value

    def _get_bridge(self, *, login: bool = False) -> NativeWebSession:
        with self._lock:
            if self._stopped or not self.access_enabled():
                raise LiveSessionRequiredError("Token BI 账号接入已断开。")
            if self._bridge and self._bridge.alive:
                return self._bridge
            if not self.available():
                raise LiveSessionRequiredError("原生网页登录组件缺失，请重新安装 Token BI。")
            if not login and time.monotonic() < self._restart_after:
                raise LiveSessionRequiredError("网页组件正在等待重试。")
            profile = self._profile(create=login)
            if self._bridge:
                self._bridge.close()
            self._generation += 1
            self._online = None
            generation = self._generation
            def event(value: str) -> None:
                # 不在管道读取线程中同步采集，避免读写互等；回调仅唤醒协调器。
                if generation == self._generation:
                    if value in {"network_online", "network_offline"}:
                        self._online = value == "network_online"
                    self.on_event(value)
            self._restart_after = time.monotonic() + 60
            self._bridge = NativeWebSession(self._settings.web_session_bin, profile, event)
            return self._bridge

    def fetch_usage(self, account: AccountRecord) -> dict:
        bridge = self._get_bridge()
        result = bridge.request("collect", account.identity_key)
        with self._lock:
            if bridge is not self._bridge:
                raise LiveSessionRequiredError("账号接入已断开。")
            category = result.get("category")
            state = BrowserSessionState.READY if category == "success" else BrowserSessionState.ERROR
            self._session = self._snapshot(account.account_id, state)
        return result

    def start_login_session(self, account_id: str, context_dir: Path, *, expected_identity: Optional[str] = None) -> BrowserSessionSnapshot:
        try:
            result = self._get_bridge(login=True).request("login", expected_identity, timeout=5)
            state = BrowserSessionState(result.get("state", "error"))
            error = None
        except (OSError, ValueError, ScraperUnavailableError):
            state, error = BrowserSessionState.ERROR, "无法启动原生登录窗口，请重试。"
        with self._lock:
            self._session = self._snapshot(account_id, state, error)
            return self._session

    def _snapshot(self, account_id: str, state: BrowserSessionState, error: Optional[str] = None) -> BrowserSessionSnapshot:
        return BrowserSessionSnapshot(account_id=account_id, state=state, context_dir=str(self._profile_path),
                                      browser_app_name="WKWebView", last_error=error,
                                      last_seen_at=datetime.now(timezone.utc))

    def get_session_snapshot(self, account_id: str) -> Optional[BrowserSessionSnapshot]:
        # 状态读取不拉起进程、不访问网页，也不等待正在进行的网络请求。
        with self._lock:
            return self._session if self._session and self._session.account_id == account_id else None

    def minimize_session(self, account_id: str) -> bool:
        with self._lock:
            bridge = self._bridge
        if bridge is None:
            return False
        try:
            bridge.request("hide", timeout=2)
            return True
        except (OSError, ScraperUnavailableError):
            return False

    def close_session(self, account_id: Optional[str] = None) -> None:
        with self._lock:
            self._generation += 1
            bridge, self._bridge = self._bridge, None
            self._session = None
            self._restart_after = 0
        if bridge:
            bridge.close()
        # 不清理 WebKit 持久化存储、Cookie 或旧 Chrome 配置。

    def shutdown(self) -> None:
        with self._lock:
            self._stopped = True
        self.close_session()
