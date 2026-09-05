from __future__ import annotations

import ipaddress
import json
import os
import socket
import subprocess
import sys
import threading
import time
from functools import lru_cache
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

from app.app_paths import resolve_app_data_dir, resolve_project_root
from app.process_lifecycle import stop_owned_process, stop_owned_chrome_workers, owns_dev_service
from app.http_access import allows_local_management
import psutil


def _command_stdout(command: list[str]) -> str:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return ""
    return result.stdout.strip()


def _system_local_hostname() -> str:
    hostname = _command_stdout(["scutil", "--get", "LocalHostName"])
    return hostname or socket.gethostname().split(".")[0]


PROJECT_ROOT = resolve_project_root()
APP_DATA_DIR = resolve_app_data_dir()
RUNTIME_DIR = APP_DATA_DIR / "runtime"
LOG_DIR = RUNTIME_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_MAIN_PORT = int(os.getenv("TOKEN_BI_PORT", "8787"))
MAX_MAIN_PORT = int(os.getenv("TOKEN_BI_PORT_MAX", "8877"))
CONTROL_HOST = os.getenv("TOKEN_BI_CONTROL_HOST", "127.0.0.1")
CONTROL_PORT = int(os.getenv("TOKEN_BI_CONTROL_PORT", "8790"))
MAIN_SERVICE_MARKER = "token-bi-main-service"
MAIN_SERVER_START_TIMEOUT_SECONDS = 30
DASHBOARD_URL_CACHE_TTL_SECONDS = 5
PID_FILE = RUNTIME_DIR / "token_bi.pid"
RUNTIME_STATE_FILE = RUNTIME_DIR / "token_bi_runtime.json"
LOCAL_HOSTNAME = _system_local_hostname()
_dashboard_url_cache: tuple[float, int, dict[str, str]] | None = None

ACCOUNTS_FILE = APP_DATA_DIR / "config" / "accounts.json"


def _read_accounts() -> list[dict]:
    if not ACCOUNTS_FILE.exists():
        return []
    try:
        payload = json.loads(ACCOUNTS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return payload.get("accounts", []) if payload.get("access_enabled", True) else []


def _preferred_account() -> dict | None:
    accounts = _read_accounts()
    if not accounts:
        return None
    active = [item for item in accounts if item.get("status") == "active"]
    if active:
        return active[0]
    return accounts[0]


def _local_visible_accounts() -> list[dict]:
    accounts = [account for account in _read_accounts() if not account.get("account_id", "").startswith("acc_demo_")]
    active_accounts = [account for account in accounts if account.get("status") == "active"]
    return active_accounts or accounts


def _main_visible_accounts() -> list[dict]:
    payload = _main_api_request("GET", "/api/v1/accounts", timeout=5)
    items = payload.get("items") or []
    return [item for item in items if item.get("account_id")]


def _main_runtime_status() -> dict:
    payload = _main_api_request("GET", "/api/v1/runtime-status", timeout=5)
    if payload.get("service") != MAIN_SERVICE_MARKER:
        raise RuntimeError("Token BI main service identity check failed.")
    return payload


def _status_account(running: bool, runtime_status: dict | None = None) -> dict | None:
    if runtime_status is not None and "account" in runtime_status:
        return runtime_status["account"]
    if running:
        runtime_account = (runtime_status or {}).get("account")
        if runtime_account:
            return runtime_account
        try:
            accounts = _main_visible_accounts()
        except RuntimeError:
            accounts = []
        if accounts:
            active_accounts = [account for account in accounts if account.get("status") == "active"]
            return (active_accounts or accounts)[0]
    return _preferred_account()


def _read_runtime_state() -> dict:
    if not RUNTIME_STATE_FILE.exists():
        return {}
    try:
        return json.loads(RUNTIME_STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _write_runtime_state(port: int, pid: int | str | None) -> None:
    RUNTIME_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME_STATE_FILE.write_text(
        json.dumps({"port": port, "pid": str(pid or "")}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _invalidate_dashboard_url_cache()


def _clear_runtime_state() -> None:
    RUNTIME_STATE_FILE.unlink(missing_ok=True)
    _invalidate_dashboard_url_cache()


def _current_main_port() -> int:
    state = _read_runtime_state()
    try:
        port = int(state.get("port") or DEFAULT_MAIN_PORT)
    except (TypeError, ValueError):
        port = DEFAULT_MAIN_PORT
    return port


def _cleanup_stale_runtime_state() -> None:
    if PID_FILE.exists():
        pid = PID_FILE.read_text(encoding="utf-8").strip()
        process_identity = _pid_is_token_bi_main(pid) if pid and _pid_alive(pid) else False
        if process_identity is not False:
            return
        PID_FILE.unlink(missing_ok=True)
        _clear_runtime_state()
        return

    state = _read_runtime_state()
    pid = str(state.get("pid") or "").strip()
    if pid and not _pid_alive(pid):
        _clear_runtime_state()


def _port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.2)
        if probe.connect_ex(("127.0.0.1", port)) == 0:
            return False

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("0.0.0.0", port))
        except OSError:
            return False
    return True


def _select_main_port(start_port: int = DEFAULT_MAIN_PORT, max_port: int = MAX_MAIN_PORT) -> int:
    for port in range(start_port, max_port + 1):
        if _port_available(port):
            return port
    raise RuntimeError(f"没有可用端口：{start_port}-{max_port} 都被占用。")


def _main_server_running() -> tuple[bool, str | None]:
    pid = None
    if PID_FILE.exists():
        pid = PID_FILE.read_text(encoding="utf-8").strip() or None
        if pid and _pid_alive(pid):
            process_identity = _pid_is_token_bi_main(pid)
            if process_identity is not False:
                return True, pid
        PID_FILE.unlink(missing_ok=True)
        _clear_runtime_state()

    return False, None


def _pid_alive(pid: str) -> bool:
    try:
        pid_int = int(pid)
    except ValueError:
        return False

    try:
        waited_pid, _ = os.waitpid(pid_int, os.WNOHANG)
        if waited_pid == pid_int:
            return False
    except ChildProcessError:
        # 控制台重启后主服务可能已不是当前进程的直接子进程。
        pass
    except OSError:
        return False

    try:
        os.kill(pid_int, 0)
    except OSError:
        return False

    try:
        result = subprocess.run(
            ["ps", "-p", str(pid_int), "-o", "state="],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return True
    if result.returncode != 0:
        return False
    if result.stdout.strip().upper().startswith("Z"):
        return False
    return True


def _pid_is_token_bi_main(pid: str) -> bool | None:
    try:
        process = psutil.Process(int(pid))
        args = process.cmdline()
        if process.uids().real != os.getuid():
            return False
        if getattr(sys, "frozen", False):
            return (len(args) > 1 and args[1] == "main-server"
                    and Path(process.exe()).resolve() == Path(_backend_command([])[0]).resolve())
        return owns_dev_service(process, PROJECT_ROOT, "main")
    except psutil.NoSuchProcess:
        return False
    except (psutil.Error, OSError, ValueError):
        return None


def _backend_command(args: list[str]) -> list[str]:
    if getattr(sys, "frozen", False):
        override = os.getenv("TOKEN_BI_MAIN_BACKEND_BIN")
        backend_path = (
            Path(override)
            if override
            else Path(sys.executable).with_name("token-bi-backend")
        )
        return [str(backend_path), *args]
    return [sys.executable, "-m", "app.cli", *args]


def _stop_pid(pid: str) -> bool:
    try:
        pid_int = int(pid)
    except ValueError:
        return False
    if not _pid_alive(pid):
        return False
    if _pid_is_token_bi_main(pid) is not True:
        return False

    return stop_owned_process(pid_int, lambda process: _pid_is_token_bi_main(str(process.pid)) is True)


def _default_route_interface() -> str:
    route_output = _command_stdout(["route", "-n", "get", "default"])
    for line in route_output.splitlines():
        key, separator, value = line.strip().partition(":")
        if separator and key == "interface":
            return value.strip()
    return ""


def _interface_ipv4(interface: str) -> str:
    if not interface:
        return ""
    candidate = _command_stdout(["ipconfig", "getifaddr", interface])
    try:
        address = ipaddress.ip_address(candidate)
    except ValueError:
        return ""
    if (
        address.version != 4
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
    ):
        return ""
    return str(address)


def _current_lan_ipv4() -> str:
    interfaces = [_default_route_interface(), "en0", "en1"]
    for interface in dict.fromkeys(item for item in interfaces if item):
        if address := _interface_ipv4(interface):
            return address
    return ""


def _invalidate_dashboard_url_cache() -> None:
    global _dashboard_url_cache
    _dashboard_url_cache = None


def _dashboard_urls() -> dict[str, str]:
    global _dashboard_url_cache

    now = time.monotonic()
    port = _current_main_port()
    if _dashboard_url_cache is not None:
        cached_at, cached_port, cached_urls = _dashboard_url_cache
        if cached_port == port and now - cached_at < DASHBOARD_URL_CACHE_TTL_SECONDS:
            return dict(cached_urls)

    base = {
        "local": f"http://127.0.0.1:{port}/dashboard",
        "fixed": f"http://{LOCAL_HOSTNAME}.local:{port}/dashboard" if LOCAL_HOSTNAME else "",
    }
    wifi_ip = _current_lan_ipv4()
    base["lan"] = f"http://{wifi_ip}:{port}/dashboard" if wifi_ip else ""
    _dashboard_url_cache = (now, port, dict(base))
    return base


def _qrcode_svg(url: str) -> str:
    try:
        import qrcode
        import qrcode.image.svg
    except ImportError as exc:
        raise RuntimeError("Missing qrcode dependency. Run ./.venv/bin/pip install -r requirements.txt") from exc

    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=2,
    )
    qr.add_data(url)
    qr.make(fit=True)
    image = qr.make_image(image_factory=qrcode.image.svg.SvgPathImage)
    raw = image.to_string()
    if isinstance(raw, bytes):
        return raw.decode("utf-8")
    return raw


def _start_main_server_process() -> tuple[bool, str]:
    running, pid = _main_server_running()
    if running:
        return True, f"Token BI is already running · PID {pid or '--'} · Port {_current_main_port()}"

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        port = _select_main_port(DEFAULT_MAIN_PORT, MAX_MAIN_PORT)
    except RuntimeError as exc:
        return False, str(exc)

    env = os.environ.copy()
    env["TOKEN_BI_HOST"] = os.getenv("TOKEN_BI_HOST", "0.0.0.0")
    env["TOKEN_BI_PORT"] = str(port)
    env["TOKEN_BI_APP_DATA_DIR"] = str(APP_DATA_DIR)
    if getattr(sys, "frozen", False):
        # 主服务是 one-file sidecar 的独立实例，不能复用控制台临时解压目录。
        env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    command = _backend_command(
        [
            "main-server",
            "--host",
            env["TOKEN_BI_HOST"],
            "--port",
            str(port),
        ]
    )

    try:
        log_handle = (LOG_DIR / "server.log").open("ab")
        process = subprocess.Popen(
            command,
            cwd=str(PROJECT_ROOT),
            env=env,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        log_handle.close()
    except OSError as exc:
        return False, str(exc)

    PID_FILE.write_text(str(process.pid), encoding="utf-8")
    _write_runtime_state(port=port, pid=process.pid)
    if not _wait_for_main_server(port=port):
        _stop_pid(str(process.pid))
        PID_FILE.unlink(missing_ok=True)
        _clear_runtime_state()
        return False, "Token BI start command completed, but the API did not become ready in time."
    return True, f"Token BI started · PID {process.pid} · Port {port}"


def _stop_main_server_process() -> tuple[bool, str]:
    stopped = False
    messages = []
    if PID_FILE.exists():
        existing_pid = PID_FILE.read_text(encoding="utf-8").strip()
        if existing_pid and _pid_alive(existing_pid):
            if not _stop_pid(existing_pid):
                return False, f"Token BI 主服务无法停止（PID {existing_pid}）。"
            stopped = True
            messages.append(f"Token BI stopped (PID {existing_pid}).")
        PID_FILE.unlink(missing_ok=True)

    if stopped:
        _clear_runtime_state()
        return True, " ".join(dict.fromkeys(messages))
    _clear_runtime_state()
    return True, "Token BI is not running."


def _main_api_url(path: str, port: int | None = None) -> str:
    return f"http://127.0.0.1:{port or _current_main_port()}{path}"


def _main_api_request(method: str, path: str, payload: dict | None = None, timeout: int = 30) -> dict:
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = Request(
        _main_api_url(path),
        data=body,
        headers=headers,
        method=method,
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(raw or f"Main service returned HTTP {exc.code}.") from exc
    except (URLError, OSError) as exc:
        raise RuntimeError(f"Unable to reach Token BI service: {exc}") from exc


def _wait_for_main_server(
    timeout_seconds: int = MAIN_SERVER_START_TIMEOUT_SECONDS,
    port: int | None = None,
) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        running, _ = _main_server_running()
        if running:
            try:
                payload = _main_api_request("GET", "/api/v1/health", timeout=3)
                if payload.get("ok") and payload.get("service") == MAIN_SERVICE_MARKER:
                    return True
            except RuntimeError:
                pass
        time.sleep(0.5)
    return False


def _ensure_main_server() -> tuple[bool, str]:
    return _start_main_server_process()


def _login_account_flow() -> dict:
    ok, message = _ensure_main_server()
    if not ok:
        return {"ok": False, "message": message}

    try:
        payload = _main_api_request("POST", "/api/v1/account-session/login", payload={}, timeout=80)
    except RuntimeError as exc:
        return _error_payload("login_required", details=str(exc))

    return {
        "ok": payload.get("ok", True),
        "message": payload.get("message")
        or "已打开 Token BI 专用 Chrome 登录窗口。完成 Codex 登录后回到控制台刷新状态。",
        "account": payload.get("account"),
        "session": payload.get("session"),
        "action": payload.get("action", "login"),
    }


def _logout_account_flow() -> dict:
    ok, message = _ensure_main_server()
    if not ok:
        return _error_payload("service_stopped", details=message)

    account = _preferred_account()
    account_id = account.get("account_id") if account else None
    path = "/api/v1/account-session/logout"
    if account_id:
        path = f"{path}?account_id={account_id}"
    try:
        payload = _main_api_request("POST", path, payload={})
    except RuntimeError as exc:
        return _error_payload("worker_lost", details=str(exc))

    return {
        "ok": True,
        "message": payload.get("message") or "已退出账号。",
        "account_id": payload.get("account_id"),
        "action": "logout",
    }


def _account_action_flow() -> dict:
    account = _preferred_account()
    if _account_action_label(account) == "退出账号":
        return _logout_account_flow()
    return _login_account_flow()


def _refresh_live_accounts() -> dict:
    running, _ = _main_server_running()
    if not running:
        return {"ok": False, "message": "Token BI is not running. Start it first."}

    try:
        accounts = _main_visible_accounts()
    except RuntimeError:
        accounts = _local_visible_accounts()
    if not accounts:
        try:
            payload = _main_api_request(
                "POST",
                "/api/v1/dashboard/refresh",
                payload={},
                timeout=50,
            )
            results = [
                {
                    "account_id": (payload.get("account") or {}).get("account_id"),
                    "state": payload.get("state"),
                    "masked_email": (payload.get("account") or {}).get("masked_email"),
                    "source_type": (payload.get("summary") or {}).get("source_type"),
                    "source_detail": (payload.get("summary") or {}).get("source_detail"),
                    "connector_name": (payload.get("summary") or {}).get("connector_name"),
                    "message": payload.get("message"),
                }
            ]
        except RuntimeError as exc:
            results = [{"account_id": None, "state": "error", "message": str(exc)}]

        ready = [item for item in results if item.get("state") == "ready"]
        if ready:
            labels = ", ".join(dict.fromkeys(item.get("masked_email") or "Codex 本机账号" for item in ready))
            sources = ", ".join(
                dict.fromkeys(
                    (
                        f"{item.get('source_type') or 'unknown'}"
                        f"/{item.get('connector_name') or item.get('source_detail') or 'unknown'}"
                    )
                    for item in ready
                )
            )
            return {
                "ok": True,
                "message": f"状态已刷新，已获取 usage：{labels}。数据源：{sources}",
                "results": results,
            }

        payload = _error_payload("login_required")
        payload["message"] = next((item["message"] for item in results if item.get("message")), "本次同步未成功，将自动重试。")
        payload["results"] = results
        return payload

    results = []
    for account in accounts:
        account_id = account.get("account_id")
        if not account_id:
            continue
        try:
            payload = _main_api_request(
                "POST",
                f"/api/v1/dashboard/refresh?account_id={account_id}",
                payload={},
                timeout=50,
            )
            results.append(
                {
                    "account_id": account_id,
                    "state": payload.get("state"),
                    "masked_email": (payload.get("account") or {}).get("masked_email"),
                    "source_type": (payload.get("summary") or {}).get("source_type"),
                    "source_detail": (payload.get("summary") or {}).get("source_detail"),
                    "connector_name": (payload.get("summary") or {}).get("connector_name"),
                    "message": payload.get("message"),
                }
            )
        except RuntimeError as exc:
            results.append({"account_id": account_id, "state": "error", "message": str(exc)})

    ready = [item for item in results if item.get("state") == "ready"]
    if ready:
        labels = ", ".join(dict.fromkeys(item.get("masked_email") or item["account_id"] for item in ready))
        sources = ", ".join(
            dict.fromkeys(
                (
                    f"{item.get('source_type') or 'unknown'}"
                    f"/{item.get('connector_name') or item.get('source_detail') or 'unknown'}"
                )
                for item in ready
            )
        )
        return {
            "ok": True,
            "message": f"状态已刷新，已获取 usage：{labels}。数据源：{sources}",
            "results": results,
        }
    payload = _error_payload("login_required")
    payload["message"] = next((item["message"] for item in results if item.get("message")), "本次同步未成功，将自动重试。")
    payload["results"] = results
    return payload


def _diagnostics_items() -> list[dict]:
    running, _ = _main_server_running()
    if not running:
        return []
    try:
        payload = _main_api_request("GET", "/api/v1/diagnostics", timeout=5)
    except RuntimeError:
        return []
    return payload.get("items") or []


def _data_source_status(diagnostics: list[dict]) -> str:
    if not diagnostics:
        return "数据源：服务启动后检查 OAuth / CLI RPC / Web Session"
    by_code = {item.get("code"): item for item in diagnostics}
    labels = []
    for code, label in (
        ("codex_auth_available", "OAuth"),
        ("codex_cli_available", "CLI RPC"),
        ("web_session_available", "Web Session"),
    ):
        item = by_code.get(code) or {}
        severity = item.get("severity")
        marker = "可用" if severity in {"ok", "info"} else "需检查"
        labels.append(f"{label}{marker}")
    last_error = (by_code.get("last_connector_error") or {}).get("next_step")
    if last_error and last_error != "No connector errors recorded.":
        return f"数据源：{' / '.join(labels)}；最近降级：{last_error}"
    return f"数据源：{' / '.join(labels)}；暂无降级记录"


def _open_url(url: str) -> tuple[int, str]:
    try:
        result = subprocess.run(
            ["open", url],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        return 1, str(exc)
    output = (result.stdout + result.stderr).strip()
    return result.returncode, output or f"Opened {url}"


def _tail_log(lines: int = 20) -> str:
    log_file = LOG_DIR / "server.log"
    if not log_file.exists():
        return "No server log yet."
    content = log_file.read_text(encoding="utf-8", errors="ignore").splitlines()
    return "\n".join(content[-lines:]) if content else "No server log yet."


def _clear_log() -> tuple[bool, str]:
    log_file = LOG_DIR / "server.log"
    try:
        log_file.write_text("", encoding="utf-8")
    except OSError as exc:
        return False, str(exc)
    return True, "日志已清空。"


def _close_token_bi_chrome_workers() -> None:
    stop_owned_chrome_workers(RUNTIME_DIR / "contexts")


@lru_cache(maxsize=1)
def _chrome_available() -> bool:
    candidates = [
        Path("/Applications/Google Chrome.app"),
        Path.home() / "Applications" / "Google Chrome.app",
    ]
    if any(path.exists() for path in candidates):
        return True
    try:
        result = subprocess.run(
            ["mdfind", "kMDItemCFBundleIdentifier == 'com.google.Chrome'"],
            capture_output=True,
            text=True,
            check=False,
        )
        return bool(result.stdout.strip())
    except OSError:
        return False


def _account_action_label(account: dict | None) -> str:
    if account and account.get("status") == "active":
        return "退出账号"
    return "登录账号"


def _service_action_label(running: bool) -> str:
    return "关闭服务" if running else "开启服务"


def _service_action_flow() -> dict:
    running, _ = _main_server_running()
    ok, message = _stop_main_server_process() if running else _start_main_server_process()
    return {"ok": ok, "message": message, "action": "stop" if running else "start"}


ERROR_COPIES = {
    "chrome_missing": (
        "未检测到 Chrome",
        "Token BI 需要使用 Google Chrome 打开专用登录窗口。请安装 Chrome 后重新启动 App。",
    ),
    "service_stopped": (
        "服务未启动",
        "请点击“启动 Token BI”。如果端口被占用，Token BI 会自动切换到下一个可用端口。",
    ),
    "login_required": (
        "需要登录账号",
        "请点击“登录账号”，在弹出的 Token BI 专用 Chrome 窗口完成 Codex 登录和真人验证。",
    ),
    "worker_lost": (
        "登录窗口已关闭或失联",
        "请点击“登录账号”重新拉起专用窗口，登录后再点击“刷新状态”。",
    ),
    "usage_page_changed": (
        "Usage 页面结构可能变化",
        "请点击“打开看板”跳到官方 usage 页面核对；如果官方页面正常，请更新 Token BI。",
    ),
    "network_unreachable": (
        "副屏无法访问 Mac",
        "请确认副屏设备和 Mac 在同一 Wi-Fi，关闭路由器客户端隔离，并检查 Mac 防火墙。",
    ),
}


def _error_payload(code: str, details: str | None = None) -> dict:
    title, next_step = ERROR_COPIES.get(
        code,
        ("出现未知问题", "请刷新状态；如果仍失败，查看运行日志中的最近错误。"),
    )
    message = f"{title}。{next_step}"
    if details:
        message = f"{message}（{details}）"
    return {
        "ok": False,
        "code": code,
        "title": title,
        "next_step": next_step,
        "message": message,
    }


def _guide_payload(
    running: bool,
    account: dict | None,
    urls: dict[str, str],
    chrome_available: bool,
) -> dict:
    account_ready = bool(account and account.get("status") == "active")
    checklist = [
        {"label": "检测 Chrome", "done": chrome_available},
        {"label": "启动本地服务", "done": running},
        {"label": "登录 Codex 账号", "done": account_ready},
        {"label": "刷新 usage 数据", "done": account_ready},
        {"label": "扫码连接副屏", "done": bool(urls.get("fixed") or urls.get("lan")) and running},
    ]
    return {
        "completed": all(item["done"] for item in checklist),
        "items": checklist,
    }


def _status_payload() -> dict:
    running, pid = _main_server_running()
    runtime_status = {}
    health_error = None
    if running:
        try:
            runtime_status = _main_runtime_status()
        except RuntimeError:
            health_error = "主服务进程存在，但状态接口未响应；请关闭并重新开启服务。"
            runtime_status = {"account": _preferred_account()}
    healthy = running and runtime_status.get("service") == MAIN_SERVICE_MARKER
    account = _status_account(running, runtime_status)
    urls = _dashboard_urls()
    chrome_available = _chrome_available()
    account_action_label = _account_action_label(account)
    diagnostics = _diagnostics_items() if healthy else []
    return {
        "running": running,
        "healthy": healthy,
        "health_error": health_error,
        "access_enabled": runtime_status.get("access_enabled", True),
        "pid": pid,
        "port": _current_main_port(),
        "control_port": CONTROL_PORT,
        "hostname": LOCAL_HOSTNAME,
        "packaged": bool(getattr(sys, "frozen", False)),
        "app_data_dir": str(APP_DATA_DIR),
        "chrome_available": chrome_available,
        "urls": urls,
        "service_action_label": _service_action_label(running),
        "account_action_label": account_action_label,
        "guide": _guide_payload(
            running=running,
            account=account,
            urls=urls,
            chrome_available=chrome_available,
        ),
        "diagnostics": diagnostics,
        "data_source_status": _data_source_status(diagnostics),
        "usage": runtime_status.get("usage"),
        "account": {
            "masked_email": account.get("masked_email"),
            "status": account.get("status"),
            "account_id": account.get("account_id"),
        }
        if account
        else None,
        "log_tail": _tail_log(),
    }


def _app_health_payload() -> dict:
    _cleanup_stale_runtime_state()
    running, pid = _main_server_running()
    return {
        "ok": True,
        "service": "token-bi-control-panel",
        "control_port": CONTROL_PORT,
        "main_port": _current_main_port(),
        "pid": pid or "",
        "main_running": running,
        "app_data_dir": str(APP_DATA_DIR),
        "packaged": bool(getattr(sys, "frozen", False)),
    }


CONTROL_PANEL_HTML_PATH = Path(__file__).with_name("control_panel.html")
HTML = CONTROL_PANEL_HTML_PATH.read_text(encoding="utf-8")


class ControlPanelHandler(BaseHTTPRequestHandler):
    def _allow_request(self) -> bool:
        try:
            host = urlparse("http://" + self.headers.get("Host", "")).hostname or ""
        except ValueError:
            host = ""
        if allows_local_management(self.client_address[0], host, self.headers.get("Origin")):
            return True
        self.send_error(HTTPStatus.FORBIDDEN, "Local console requests only")
        return False

    def do_GET(self) -> None:
        if not self._allow_request():
            return
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send_html(HTML)
            return
        if parsed.path == "/api/status":
            self._send_json(_status_payload())
            return
        if parsed.path == "/api/app/health":
            self._send_json(_app_health_payload())
            return
        if parsed.path == "/api/qrcode":
            kind = parse_qs(parsed.query).get("kind", ["fixed"])[0]
            urls = _dashboard_urls()
            target = urls.get(kind) or ""
            if not target:
                self.send_error(HTTPStatus.NOT_FOUND, "Dashboard URL unavailable")
                return
            try:
                self._send_svg(_qrcode_svg(target))
            except RuntimeError as exc:
                self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self) -> None:
        if not self._allow_request():
            return
        parsed = urlparse(self.path)
        if parsed.path == "/api/service-action":
            self._send_json(_service_action_flow())
            return
        if parsed.path == "/api/start":
            ok, message = _start_main_server_process()
            self._send_json({"ok": ok, "message": message})
            return
        if parsed.path == "/api/stop":
            ok, message = _stop_main_server_process()
            self._send_json({"ok": ok, "message": message})
            return
        if parsed.path == "/api/open-dashboard":
            urls = _dashboard_urls()
            target = urls["fixed"] or urls["local"]
            code, output = _open_url(target)
            self._send_json({"ok": code == 0, "message": output, "url": target})
            return
        if parsed.path == "/api/open-url":
            kind = parse_qs(parsed.query).get("kind", [""])[0]
            urls = _dashboard_urls()
            target = urls.get(kind) or ""
            if not target:
                self._send_json({"ok": False, "message": "入口不可用。"})
                return
            code, output = _open_url(target)
            self._send_json({"ok": code == 0, "message": output, "url": target})
            return
        if parsed.path == "/api/account-action":
            self._send_json(_account_action_flow())
            return
        if parsed.path == "/api/add-account":
            self._send_json(_login_account_flow())
            return
        if parsed.path == "/api/refresh-status":
            _invalidate_dashboard_url_cache()
            self._send_json(_refresh_live_accounts())
            return
        if parsed.path == "/api/clear-log":
            ok, message = _clear_log()
            self._send_json({"ok": ok, "message": message})
            return
        if parsed.path == "/api/app/shutdown":
            ok, message = _stop_main_server_process()
            _close_token_bi_chrome_workers()
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            self._send_json({"ok": ok, "message": message or "Token BI app services stopped."})
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return

    def _send_html(self, body: str) -> None:
        content = body.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _send_json(self, payload: dict) -> None:
        content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _send_svg(self, body: str) -> None:
        content = body.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "image/svg+xml; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


def main() -> None:
    server = ThreadingHTTPServer((CONTROL_HOST, CONTROL_PORT), ControlPanelHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
