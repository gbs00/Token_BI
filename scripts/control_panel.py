from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

from app.app_paths import resolve_app_data_dir, resolve_project_root


PROJECT_ROOT = resolve_project_root()
APP_DATA_DIR = resolve_app_data_dir()
RUNTIME_DIR = APP_DATA_DIR / "runtime"
LOG_DIR = RUNTIME_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

MAIN_PORT = int(os.getenv("TOKEN_BI_PORT", "8787"))
CONTROL_HOST = os.getenv("TOKEN_BI_CONTROL_HOST", "127.0.0.1")
CONTROL_PORT = int(os.getenv("TOKEN_BI_CONTROL_PORT", "8790"))
PID_FILE = RUNTIME_DIR / "token_bi.pid"
LOCAL_HOSTNAME = (
    subprocess.run(
        ["scutil", "--get", "LocalHostName"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
)

ACCOUNTS_FILE = APP_DATA_DIR / "config" / "accounts.json"


def _read_accounts() -> list[dict]:
    if not ACCOUNTS_FILE.exists():
        return []
    try:
        payload = json.loads(ACCOUNTS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return payload.get("accounts", [])


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


def _main_server_running() -> tuple[bool, str | None]:
    pid = None
    if PID_FILE.exists():
        pid = PID_FILE.read_text(encoding="utf-8").strip() or None
        if pid and _pid_alive(pid):
            return True, pid

    try:
        result = subprocess.run(
            ["lsof", "-tiTCP:" + str(MAIN_PORT), "-sTCP:LISTEN"],
            capture_output=True,
            text=True,
            check=False,
        )
        pids = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if pids:
            return True, pids[0]
    except OSError:
        pass
    return False, None


def _pid_alive(pid: str) -> bool:
    try:
        os.kill(int(pid), 0)
    except (OSError, ValueError):
        return False
    return True


def _backend_command(args: list[str]) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, *args]
    return [sys.executable, "-m", "app.cli", *args]


def _stop_pid(pid: str) -> bool:
    try:
        pid_int = int(pid)
    except ValueError:
        return False
    if not _pid_alive(pid):
        return False

    try:
        os.kill(pid_int, signal.SIGTERM)
    except OSError:
        return False

    for _ in range(20):
        if not _pid_alive(pid):
            return True
        time.sleep(0.5)

    try:
        os.kill(pid_int, signal.SIGKILL)
    except OSError:
        return False
    time.sleep(0.5)
    return not _pid_alive(pid)


def _dashboard_urls() -> dict[str, str]:
    base = {
        "local": f"http://127.0.0.1:{MAIN_PORT}/dashboard",
        "fixed": f"http://{LOCAL_HOSTNAME}.local:{MAIN_PORT}/dashboard" if LOCAL_HOSTNAME else "",
    }
    try:
        wifi_ip = subprocess.run(
            ["ipconfig", "getifaddr", "en0"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        if not wifi_ip:
            wifi_ip = subprocess.run(
                ["ipconfig", "getifaddr", "en1"],
                capture_output=True,
                text=True,
                check=False,
            ).stdout.strip()
    except OSError:
        wifi_ip = ""

    base["lan"] = f"http://{wifi_ip}:{MAIN_PORT}/dashboard" if wifi_ip else ""
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
        return True, f"Token BI is already running · PID {pid or '--'}"

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["TOKEN_BI_HOST"] = os.getenv("TOKEN_BI_HOST", "0.0.0.0")
    env["TOKEN_BI_PORT"] = str(MAIN_PORT)
    env["TOKEN_BI_APP_DATA_DIR"] = str(APP_DATA_DIR)
    command = _backend_command(
        [
            "main-server",
            "--host",
            env["TOKEN_BI_HOST"],
            "--port",
            str(MAIN_PORT),
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
    if not _wait_for_main_server():
        return False, "Token BI start command completed, but the API did not become ready in time."
    return True, f"Token BI started · PID {process.pid}"


def _stop_main_server_process() -> tuple[bool, str]:
    stopped = False
    messages = []
    if PID_FILE.exists():
        existing_pid = PID_FILE.read_text(encoding="utf-8").strip()
        if existing_pid and _stop_pid(existing_pid):
            stopped = True
            messages.append(f"Token BI stopped (PID {existing_pid}).")
        PID_FILE.unlink(missing_ok=True)

    try:
        result = subprocess.run(
            ["lsof", "-tiTCP:" + str(MAIN_PORT), "-sTCP:LISTEN"],
            capture_output=True,
            text=True,
            check=False,
        )
        for pid in [line.strip() for line in result.stdout.splitlines() if line.strip()]:
            if _stop_pid(pid):
                stopped = True
                messages.append(f"Token BI stopped (PID {pid}).")
    except OSError:
        pass

    if stopped:
        return True, " ".join(dict.fromkeys(messages))
    return True, "Token BI is not running."


def _main_api_url(path: str) -> str:
    return f"http://127.0.0.1:{MAIN_PORT}{path}"


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


def _wait_for_main_server(timeout_seconds: int = 12) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        running, _ = _main_server_running()
        if running:
            try:
                _main_api_request("GET", "/api/v1/accounts", timeout=3)
                return True
            except RuntimeError:
                pass
        time.sleep(0.5)
    return False


def _ensure_main_server() -> tuple[bool, str]:
    return _start_main_server_process()


def _add_account_flow() -> dict:
    ok, message = _ensure_main_server()
    if not ok:
        return {"ok": False, "message": message}

    try:
        existing_accounts = _main_visible_accounts()
    except RuntimeError:
        existing_accounts = _local_visible_accounts()
    if existing_accounts:
        refreshed = _refresh_live_accounts()
        if refreshed.get("ok"):
            return {
                **refreshed,
                "message": (
                    "已发现可用的已登录窗口，并已刷新 usage。"
                    "无需新开登录窗口，可以直接打开看板。"
                ),
                "reused_existing_worker": True,
            }

    try:
        created = _main_api_request("POST", "/api/v1/accounts", payload={})
        account = created.get("account") or {}
        account_id = account.get("account_id")
        if not account_id:
            return {"ok": False, "message": "Account record was not created correctly."}
        reauth = _main_api_request("POST", f"/api/v1/accounts/{account_id}/reauth", payload={})
    except RuntimeError as exc:
        return {"ok": False, "message": str(exc)}

    session = reauth.get("session") or {}
    return {
        "ok": True,
        "message": (
            "已创建待登录账号并打开 Chrome。请在新窗口完成 Codex 登录，"
            "保持窗口不关闭，然后回到控制台点击“刷新状态”。"
        ),
        "account": account,
        "session": session,
    }


def _refresh_live_accounts() -> dict:
    running, _ = _main_server_running()
    if not running:
        return {"ok": False, "message": "Token BI is not running. Start it first."}

    try:
        accounts = _main_visible_accounts()
    except RuntimeError:
        accounts = _local_visible_accounts()
    if not accounts:
        return {"ok": True, "message": "暂无账号。点击“添加账号”开始登录。"}

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
                timeout=45,
            )
            results.append(
                {
                    "account_id": account_id,
                    "state": payload.get("state"),
                    "masked_email": (payload.get("account") or {}).get("masked_email"),
                }
            )
        except RuntimeError as exc:
            results.append({"account_id": account_id, "state": "error", "message": str(exc)})

    ready = [item for item in results if item.get("state") == "ready"]
    if ready:
        labels = ", ".join(dict.fromkeys(item.get("masked_email") or item["account_id"] for item in ready))
        return {"ok": True, "message": f"状态已刷新，已获取 usage：{labels}", "results": results}
    return {"ok": False, "message": "状态已刷新，但还没有可用 usage。请确认登录窗口未关闭且已完成登录。", "results": results}


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
    subprocess.run(
        ["pkill", "-f", str(RUNTIME_DIR / "contexts")],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )


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


def _status_payload() -> dict:
    running, pid = _main_server_running()
    account = _preferred_account()
    urls = _dashboard_urls()
    return {
        "running": running,
        "pid": pid,
        "port": MAIN_PORT,
        "hostname": LOCAL_HOSTNAME,
        "packaged": bool(getattr(sys, "frozen", False)),
        "app_data_dir": str(APP_DATA_DIR),
        "chrome_available": _chrome_available(),
        "urls": urls,
        "account": {
            "masked_email": account.get("masked_email"),
            "status": account.get("status"),
            "account_id": account.get("account_id"),
        }
        if account
        else None,
        "log_tail": _tail_log(),
    }


HTML = """<!DOCTYPE html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Token BI 控制台</title>
    <style>
      :root {
        --bg: #0c121c;
        --panel: #121926;
        --panel-2: #171f2e;
        --panel-3: #1f2939;
        --line: rgba(201, 217, 255, .10);
        --line-strong: rgba(123, 218, 244, .45);
        --text: #f2f6ff;
        --muted: #a9b3c7;
        --soft: #cdd6e6;
        --accent: #73def3;
        --accent-2: #9bf3a7;
        --ok: #7de184;
        --warn: #f4cc69;
        --danger: #ff867d;
        --shadow: 0 28px 90px rgba(0, 0, 0, .36);
      }
      * { box-sizing: border-box; }
      body {
        margin: 0;
        min-height: 100vh;
        font-family: "Avenir Next", "SF Pro Display", "PingFang SC", sans-serif;
        color: var(--text);
        background:
          radial-gradient(circle at 18% 0%, rgba(64, 118, 236, .22), transparent 28%),
          radial-gradient(circle at 90% 10%, rgba(87, 226, 191, .10), transparent 24%),
          linear-gradient(180deg, #0b111b 0%, #101721 100%);
      }
      .shell {
        min-height: 100vh;
        padding: 34px 38px 74px;
      }
      .panel {
        width: min(100%, 1120px);
        margin: 0 auto;
      }
      h1 {
        margin: 0;
        font-size: clamp(34px, 5.2vw, 56px);
        letter-spacing: .01em;
        line-height: 1;
      }
      p { margin: 0; }
      .sub {
        color: var(--muted);
        margin-top: 18px;
        font-size: 17px;
        letter-spacing: .02em;
      }
      .notice {
        margin-top: 22px;
        display: grid;
        gap: 10px;
        border: 1px solid rgba(115, 222, 243, .18);
        border-radius: 16px;
        padding: 16px 18px;
        background:
          linear-gradient(180deg, rgba(24, 35, 54, .84), rgba(14, 22, 35, .86));
        color: var(--soft);
        line-height: 1.5;
      }
      .notice strong {
        color: var(--text);
      }
      .notice-warning {
        color: var(--warn);
        font-weight: 800;
      }
      .notice-ok {
        color: var(--ok);
        font-weight: 800;
      }
      .status {
        margin-top: 28px;
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 18px;
      }
      .card {
        display: grid;
        grid-template-columns: auto 1fr;
        align-items: center;
        gap: 22px;
        min-height: 116px;
        background:
          linear-gradient(180deg, rgba(31, 40, 57, .86), rgba(20, 27, 40, .94));
        border: 1px solid var(--line);
        border-radius: 18px;
        padding: 22px 24px;
        min-width: 0;
        box-shadow: inset 0 1px 0 rgba(255, 255, 255, .03);
      }
      .status-icon {
        width: 56px;
        height: 56px;
        display: grid;
        place-items: center;
        border-radius: 999px;
        color: var(--warn);
        border: 1px solid rgba(244, 204, 105, .34);
        background: rgba(244, 204, 105, .05);
      }
      .status-icon.ok {
        color: var(--ok);
        border-color: rgba(125, 225, 132, .34);
        background: rgba(125, 225, 132, .06);
      }
      .status-icon svg {
        width: 28px;
        height: 28px;
        stroke: currentColor;
        fill: none;
        stroke-width: 2.1;
      }
      .label {
        color: var(--muted);
        font-size: 15px;
        font-weight: 700;
        letter-spacing: .08em;
      }
      .value {
        margin-top: 12px;
        font-size: clamp(20px, 2.4vw, 27px);
        font-weight: 800;
        letter-spacing: .02em;
        word-break: break-word;
      }
      .ok { color: var(--ok); }
      .warn { color: var(--warn); }
      .danger { color: var(--danger); }
      .actions {
        margin-top: 26px;
        display: grid;
        grid-template-columns: repeat(6, minmax(130px, auto));
        gap: 14px;
        justify-content: start;
      }
      button {
        appearance: none;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: 10px;
        min-height: 50px;
        border: 1px solid var(--line);
        background: linear-gradient(180deg, rgba(42, 53, 73, .95), rgba(31, 41, 58, .96));
        color: var(--soft);
        border-radius: 12px;
        padding: 12px 18px;
        font-size: 16px;
        font-weight: 800;
        letter-spacing: .02em;
        cursor: pointer;
        box-shadow: inset 0 1px 0 rgba(255, 255, 255, .04);
        transition: transform .16s ease, border-color .16s ease, background .16s ease;
      }
      button:hover {
        transform: translateY(-1px);
        border-color: rgba(115, 222, 243, .34);
      }
      button.secondary {
        background: rgba(255,255,255,.05);
        border-color: var(--line);
      }
      button.add {
        background: rgba(255,255,255,.07);
      }
      button.connect {
        color: var(--text);
        border-color: rgba(155, 243, 167, .34);
        background:
          linear-gradient(180deg, rgba(125, 225, 132, .18), rgba(37, 88, 82, .42));
      }
      button.primary {
        color: var(--text);
        border-color: var(--line-strong);
        background:
          linear-gradient(180deg, rgba(83, 170, 199, .34), rgba(36, 93, 119, .60));
      }
      button .icon {
        width: 18px;
        height: 18px;
        stroke: currentColor;
        fill: none;
        stroke-width: 2.2;
      }
      .links {
        margin-top: 26px;
        display: grid;
        overflow: hidden;
        border: 1px solid var(--line);
        border-radius: 16px;
        background: rgba(16, 23, 34, .72);
      }
      .link-row {
        display: grid;
        grid-template-columns: 160px minmax(0, 1fr) auto auto;
        align-items: center;
        gap: 16px;
        padding: 14px 18px;
        border-bottom: 1px solid rgba(255, 255, 255, .055);
      }
      .link-row:last-child {
        border-bottom: 0;
      }
      .link-label {
        color: var(--muted);
        font-size: 16px;
        font-weight: 800;
        letter-spacing: .04em;
      }
      .link-value {
        color: var(--text);
        word-break: break-all;
        font-size: 18px;
        letter-spacing: .01em;
      }
      .icon-button {
        min-height: 38px;
        min-width: 48px;
        padding: 8px 12px;
        border-radius: 10px;
      }
      .log-card {
        margin-top: 22px;
        overflow: hidden;
        border: 1px solid var(--line);
        border-radius: 16px;
        background: rgba(11, 16, 24, .72);
      }
      .log-head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 12px 18px;
        border-bottom: 1px solid rgba(255, 255, 255, .07);
      }
      .log-title {
        color: var(--soft);
        font-weight: 800;
        letter-spacing: .08em;
      }
      pre {
        margin: 0;
        padding: 14px 18px 18px;
        height: 210px;
        background: #0c121a;
        color: #bfc9d8;
        font-family: "SF Mono", "Menlo", "Consolas", monospace;
        font-size: 14px;
        line-height: 1.52;
        overflow: auto;
        white-space: pre-wrap;
      }
      .flash {
        margin-top: 16px;
        color: var(--muted);
        min-height: 20px;
      }
      .bottom-bar {
        position: fixed;
        left: 0;
        right: 0;
        bottom: 0;
        min-height: 58px;
        display: flex;
        justify-content: flex-end;
        align-items: center;
        gap: 22px;
        padding: 12px 34px;
        color: var(--muted);
        background: rgba(17, 24, 34, .92);
        border-top: 1px solid rgba(255, 255, 255, .08);
        backdrop-filter: blur(16px);
      }
      .bar-item {
        display: inline-flex;
        align-items: center;
        gap: 9px;
        font-weight: 800;
      }
      .dot {
        width: 10px;
        height: 10px;
        border-radius: 999px;
        background: var(--warn);
        box-shadow: 0 0 18px rgba(244, 204, 105, .28);
      }
      .dot.ok {
        background: var(--ok);
        box-shadow: 0 0 18px rgba(125, 225, 132, .34);
      }
      .modal-backdrop {
        position: fixed;
        inset: 0;
        z-index: 20;
        display: grid;
        place-items: center;
        padding: 28px;
        background:
          radial-gradient(circle at 50% 15%, rgba(115, 222, 243, .16), transparent 28%),
          rgba(3, 7, 12, .72);
        backdrop-filter: blur(18px);
      }
      .modal-backdrop.hidden {
        display: none;
      }
      .modal {
        width: min(820px, 100%);
        max-height: min(760px, calc(100vh - 56px));
        overflow: auto;
        border: 1px solid rgba(126, 157, 212, .22);
        border-radius: 24px;
        background:
          linear-gradient(180deg, rgba(24, 34, 51, .98), rgba(13, 20, 31, .98));
        box-shadow: var(--shadow);
      }
      .modal-head {
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: 18px;
        padding: 26px 28px 10px;
      }
      .modal-title {
        margin: 0;
        font-size: clamp(26px, 3vw, 34px);
        line-height: 1.05;
      }
      .modal-sub {
        margin-top: 10px;
        color: var(--muted);
        font-size: 15px;
        line-height: 1.5;
      }
      .close-button {
        min-width: 44px;
        min-height: 44px;
        padding: 10px;
        border-radius: 999px;
      }
      .pair-warning {
        margin: 8px 28px 0;
        color: var(--warn);
        font-weight: 800;
        min-height: 22px;
      }
      .qr-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 18px;
        padding: 20px 28px 28px;
      }
      .qr-card {
        min-width: 0;
        padding: 18px;
        border: 1px solid var(--line);
        border-radius: 20px;
        background: rgba(255, 255, 255, .045);
      }
      .qr-card.primary-qr {
        border-color: rgba(115, 222, 243, .34);
        background: rgba(33, 70, 98, .24);
      }
      .qr-title {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        color: var(--text);
        font-size: 17px;
        font-weight: 900;
      }
      .pill {
        border: 1px solid rgba(125, 225, 132, .34);
        border-radius: 999px;
        padding: 5px 9px;
        color: var(--accent-2);
        font-size: 12px;
        letter-spacing: .06em;
      }
      .qr-box {
        margin-top: 14px;
        display: grid;
        place-items: center;
        aspect-ratio: 1;
        border-radius: 18px;
        padding: 14px;
        background:
          linear-gradient(180deg, #f8fbff, #eaf2ff);
        box-shadow: inset 0 0 0 1px rgba(30, 50, 80, .12);
      }
      .qr-box img {
        width: 100%;
        height: 100%;
        object-fit: contain;
      }
      .qr-url {
        margin-top: 12px;
        color: var(--soft);
        font-size: 14px;
        line-height: 1.45;
        word-break: break-all;
      }
      .qr-actions {
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
        margin-top: 14px;
      }
      .qr-hint {
        padding: 0 28px 28px;
        color: var(--muted);
        font-size: 14px;
        line-height: 1.6;
      }
      @media (max-width: 720px) {
        .shell { padding: 24px 18px 84px; }
        .status { grid-template-columns: 1fr; }
        .actions { grid-template-columns: 1fr 1fr; }
        .link-row { grid-template-columns: 1fr auto auto; }
        .link-label { grid-column: 1 / -1; }
        .qr-grid { grid-template-columns: 1fr; }
        .modal-backdrop { padding: 14px; }
        .bottom-bar { justify-content: flex-start; flex-wrap: wrap; }
      }
    </style>
  </head>
  <body>
    <div class="shell">
      <section class="panel">
        <h1>Token BI 控制台</h1>
        <p class="sub">在这页直接管理本地看板服务，不需要每次再通过 Codex 启动。</p>
        <div class="notice">
          <p><strong>本机隐私说明：</strong>Token BI 只在这台 Mac 上保存账号元信息、浏览器登录态和运行日志；不上传 usage，不保存历史趋势，也不读取聊天内容。</p>
          <p id="chromeNotice" class="notice-warning">正在检测 Google Chrome...</p>
          <p id="storageNotice">数据目录：检查中</p>
        </div>

        <div class="status">
          <div class="card">
            <div class="status-icon" id="serverIcon">
              <svg viewBox="0 0 24 24"><rect x="8" y="8" width="8" height="8" rx="1.5"/></svg>
            </div>
            <div>
              <div class="label">服务状态</div>
              <div class="value" id="serverState">加载中...</div>
            </div>
          </div>
          <div class="card">
            <div class="status-icon ok">
              <svg viewBox="0 0 24 24"><circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/><path d="M8 17h8"/></svg>
            </div>
            <div>
              <div class="label">当前账号</div>
              <div class="value" id="accountState">--</div>
            </div>
          </div>
        </div>

        <div class="actions">
          <button id="startBtn" class="primary"><svg class="icon" viewBox="0 0 24 24"><path d="m8 5 11 7-11 7z"/></svg>启动 Token BI</button>
          <button id="stopBtn" class="secondary"><svg class="icon" viewBox="0 0 24 24"><circle cx="12" cy="12" r="8"/></svg>停止 Token BI</button>
          <button id="addAccountBtn" class="add"><svg class="icon" viewBox="0 0 24 24"><circle cx="9" cy="8" r="4"/><path d="M2.5 21a7 7 0 0 1 13 0"/><path d="M18 8v6"/><path d="M15 11h6"/></svg>添加账号</button>
          <button id="openDashboardBtn"><svg class="icon" viewBox="0 0 24 24"><path d="M14 4h6v6"/><path d="m10 14 10-10"/><path d="M20 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1h5"/></svg>打开看板</button>
          <button id="pairDeviceBtn" class="connect"><svg class="icon" viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="7" rx="1.2"/><rect x="14" y="3" width="7" height="7" rx="1.2"/><rect x="3" y="14" width="7" height="7" rx="1.2"/><path d="M14 14h3v3h-3z"/><path d="M18 18h3v3h-3z"/><path d="M14 21v-2"/><path d="M21 14h-2"/></svg>扫码连接副屏</button>
          <button id="refreshBtn" class="secondary"><svg class="icon" viewBox="0 0 24 24"><path d="M20 12a8 8 0 1 1-2.34-5.66"/><path d="M20 4v6h-6"/></svg>刷新状态</button>
        </div>

        <div class="links">
          <div class="link-row">
            <div class="link-label">固定入口</div>
            <div class="link-value" id="fixedUrl">--</div>
            <button class="icon-button" data-copy="fixed"><svg class="icon" viewBox="0 0 24 24"><rect x="8" y="8" width="11" height="11" rx="2"/><path d="M5 16H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg></button>
            <button class="icon-button" data-open="fixed"><svg class="icon" viewBox="0 0 24 24"><path d="M14 4h6v6"/><path d="m10 14 10-10"/><path d="M20 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1h5"/></svg></button>
          </div>
          <div class="link-row">
            <div class="link-label">局域网入口</div>
            <div class="link-value" id="lanUrl">--</div>
            <button class="icon-button" data-copy="lan"><svg class="icon" viewBox="0 0 24 24"><rect x="8" y="8" width="11" height="11" rx="2"/><path d="M5 16H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg></button>
            <button class="icon-button" data-open="lan"><svg class="icon" viewBox="0 0 24 24"><path d="M14 4h6v6"/><path d="m10 14 10-10"/><path d="M20 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1h5"/></svg></button>
          </div>
          <div class="link-row">
            <div class="link-label">本机入口</div>
            <div class="link-value" id="localUrl">--</div>
            <button class="icon-button" data-copy="local"><svg class="icon" viewBox="0 0 24 24"><rect x="8" y="8" width="11" height="11" rx="2"/><path d="M5 16H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg></button>
            <button class="icon-button" data-open="local"><svg class="icon" viewBox="0 0 24 24"><path d="M14 4h6v6"/><path d="m10 14 10-10"/><path d="M20 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1h5"/></svg></button>
          </div>
        </div>

        <div class="flash" id="flash"></div>
        <section class="log-card">
          <div class="log-head">
            <div class="log-title">运行日志</div>
            <button id="clearLogBtn" class="secondary icon-button"><svg class="icon" viewBox="0 0 24 24"><path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M19 6l-1 14H6L5 6"/></svg>清空日志</button>
          </div>
          <pre id="logTail">加载日志中...</pre>
        </section>
      </section>
    </div>
    <div id="pairModal" class="modal-backdrop hidden" role="dialog" aria-modal="true" aria-labelledby="pairTitle">
      <section class="modal">
        <div class="modal-head">
          <div>
            <h2 id="pairTitle" class="modal-title">扫码连接副屏</h2>
            <p class="modal-sub">让闲置手机、平板或旧电脑连接到和 Mac 相同的 Wi-Fi 后，用系统相机或浏览器扫码打开看板。</p>
          </div>
          <button id="closePairModal" class="secondary close-button" aria-label="关闭扫码连接弹窗">
            <svg class="icon" viewBox="0 0 24 24"><path d="M6 6l12 12"/><path d="M18 6 6 18"/></svg>
          </button>
        </div>
        <div id="pairWarning" class="pair-warning"></div>
        <div class="qr-grid">
          <article class="qr-card primary-qr" id="fixedQrCard">
            <div class="qr-title">固定入口 <span class="pill">推荐</span></div>
            <div class="qr-box"><img id="fixedQr" alt="固定入口二维码" /></div>
            <div class="qr-url" id="fixedQrUrl">--</div>
            <div class="qr-actions">
              <button class="icon-button" data-copy="fixed"><svg class="icon" viewBox="0 0 24 24"><rect x="8" y="8" width="11" height="11" rx="2"/><path d="M5 16H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>复制</button>
              <button class="icon-button" data-open="fixed"><svg class="icon" viewBox="0 0 24 24"><path d="M14 4h6v6"/><path d="m10 14 10-10"/><path d="M20 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1h5"/></svg>打开</button>
            </div>
          </article>
          <article class="qr-card" id="lanQrCard">
            <div class="qr-title">局域网入口 <span class="pill">备用</span></div>
            <div class="qr-box"><img id="lanQr" alt="局域网入口二维码" /></div>
            <div class="qr-url" id="lanQrUrl">--</div>
            <div class="qr-actions">
              <button class="icon-button" data-copy="lan"><svg class="icon" viewBox="0 0 24 24"><rect x="8" y="8" width="11" height="11" rx="2"/><path d="M5 16H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>复制</button>
              <button class="icon-button" data-open="lan"><svg class="icon" viewBox="0 0 24 24"><path d="M14 4h6v6"/><path d="m10 14 10-10"/><path d="M20 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1h5"/></svg>打开</button>
            </div>
          </article>
        </div>
        <p class="qr-hint">如果固定入口无法打开，通常是设备或路由器不支持 `.local` 解析，请改扫局域网入口。若仍无法访问，检查 Mac 防火墙、路由器客户端隔离，以及 Token BI 主服务是否已启动。</p>
      </section>
    </div>
    <footer class="bottom-bar">
      <span class="bar-item"><span class="dot" id="barDot"></span><span id="barService">本地服务：检查中</span></span>
      <span class="bar-item">端口：<span id="barPort">8787</span></span>
      <span class="bar-item">模式：<span id="modeLabel">检查中</span></span>
    </footer>

    <script>
      let latestUrls = {};
      let latestRunning = false;

      async function readStatus() {
        const res = await fetch('/api/status');
        return await res.json();
      }

      function renderStatus(payload) {
        const serverState = document.getElementById('serverState');
        const accountState = document.getElementById('accountState');
        const fixedUrl = document.getElementById('fixedUrl');
        const lanUrl = document.getElementById('lanUrl');
        const localUrl = document.getElementById('localUrl');
        const logTail = document.getElementById('logTail');
        const serverIcon = document.getElementById('serverIcon');
        const barDot = document.getElementById('barDot');
        const barService = document.getElementById('barService');
        const barPort = document.getElementById('barPort');
        const chromeNotice = document.getElementById('chromeNotice');
        const storageNotice = document.getElementById('storageNotice');
        const modeLabel = document.getElementById('modeLabel');

        latestUrls = payload.urls || {};
        latestRunning = Boolean(payload.running);

        serverState.textContent = payload.running
          ? `运行中 · PID ${payload.pid || '--'}`
          : '已停止';
        serverState.className = 'value ' + (payload.running ? 'ok' : 'warn');
        serverIcon.className = 'status-icon ' + (payload.running ? 'ok' : '');
        barDot.className = 'dot ' + (payload.running ? 'ok' : '');
        barService.textContent = payload.running ? '本地服务：运行中' : '本地服务：已停止';
        barPort.textContent = payload.port || '--';
        modeLabel.textContent = payload.packaged ? 'App sidecar' : '开发模式';
        storageNotice.textContent = `数据目录：${payload.app_data_dir || '--'}`;
        if (payload.chrome_available) {
          chromeNotice.className = 'notice-ok';
          chromeNotice.textContent = '已检测到 Google Chrome。Token BI 会使用本机 Chrome 登录 Codex 并读取 usage。';
        } else {
          chromeNotice.className = 'notice-warning';
          chromeNotice.textContent = '未检测到 Google Chrome。Token BI 需要使用本机 Chrome 登录 Codex 并读取 usage，请安装 Chrome 后重新启动。';
        }

        if (payload.account) {
          const status = payload.account.status ? ` · ${payload.account.status}` : '';
          accountState.textContent = `${payload.account.masked_email || payload.account.account_id}${status}`;
        } else {
          accountState.textContent = '暂无账号';
        }

        fixedUrl.textContent = payload.urls.fixed || '不可用';
        lanUrl.textContent = payload.urls.lan || '不可用';
        localUrl.textContent = payload.urls.local || '不可用';
        logTail.textContent = payload.log_tail || 'No server log yet.';
      }

      function refreshQrCard(kind, imageId, urlId) {
        const image = document.getElementById(imageId);
        const label = document.getElementById(urlId);
        const url = latestUrls[kind] || '';
        label.textContent = url || '当前入口不可用';
        if (url) {
          image.removeAttribute('hidden');
          image.src = `/api/qrcode?kind=${encodeURIComponent(kind)}&t=${Date.now()}`;
        } else {
          image.setAttribute('hidden', 'hidden');
          image.removeAttribute('src');
        }
      }

      function openPairModal() {
        refreshQrCard('fixed', 'fixedQr', 'fixedQrUrl');
        refreshQrCard('lan', 'lanQr', 'lanQrUrl');
        const warning = document.getElementById('pairWarning');
        warning.textContent = latestRunning
          ? '扫码后会打开当前 Mac 提供的看板入口。请保持 Token BI 运行。'
          : 'Token BI 主服务当前未启动。可以先扫码保存入口，但设备打开时会显示无法连接。';
        document.getElementById('pairModal').classList.remove('hidden');
      }

      function closePairModal() {
        document.getElementById('pairModal').classList.add('hidden');
      }

      async function postAction(path) {
        const flash = document.getElementById('flash');
        flash.textContent = '处理中...';
        const res = await fetch(path, { method: 'POST' });
        const payload = await res.json();
        flash.textContent = payload.message || '完成';
        await refreshStatus();
      }

      async function copyUrl(kind) {
        const value = latestUrls[kind];
        const flash = document.getElementById('flash');
        if (!value) {
          flash.textContent = '当前入口不可用。';
          return;
        }
        if (navigator.clipboard && navigator.clipboard.writeText) {
          await navigator.clipboard.writeText(value);
        } else {
          const textarea = document.createElement('textarea');
          textarea.value = value;
          textarea.style.position = 'fixed';
          textarea.style.opacity = '0';
          document.body.appendChild(textarea);
          textarea.select();
          document.execCommand('copy');
          textarea.remove();
        }
        flash.textContent = '已复制入口：' + value;
      }

      async function openUrl(kind) {
        const value = latestUrls[kind];
        const flash = document.getElementById('flash');
        if (!value) {
          flash.textContent = '当前入口不可用。';
          return;
        }
        await postAction('/api/open-url?kind=' + encodeURIComponent(kind));
      }

      async function refreshStatus() {
        const payload = await readStatus();
        renderStatus(payload);
      }

      document.getElementById('startBtn').addEventListener('click', () => postAction('/api/start'));
      document.getElementById('stopBtn').addEventListener('click', () => postAction('/api/stop'));
      document.getElementById('addAccountBtn').addEventListener('click', () => postAction('/api/add-account'));
      document.getElementById('openDashboardBtn').addEventListener('click', () => postAction('/api/open-dashboard'));
      document.getElementById('pairDeviceBtn').addEventListener('click', openPairModal);
      document.getElementById('closePairModal').addEventListener('click', closePairModal);
      document.getElementById('refreshBtn').addEventListener('click', () => postAction('/api/refresh-status'));
      document.getElementById('clearLogBtn').addEventListener('click', () => postAction('/api/clear-log'));
      document.getElementById('pairModal').addEventListener('click', (event) => {
        if (event.target.id === 'pairModal') {
          closePairModal();
        }
      });
      document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') {
          closePairModal();
        }
      });
      document.querySelectorAll('[data-copy]').forEach((button) => {
        button.addEventListener('click', () => copyUrl(button.dataset.copy));
      });
      document.querySelectorAll('[data-open]').forEach((button) => {
        button.addEventListener('click', () => openUrl(button.dataset.open));
      });

      refreshStatus();
      setInterval(refreshStatus, 5000);
    </script>
  </body>
</html>
"""


class ControlPanelHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send_html(HTML)
            return
        if parsed.path == "/api/status":
            self._send_json(_status_payload())
            return
        if parsed.path == "/api/app/health":
            self._send_json({"ok": True})
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
        parsed = urlparse(self.path)
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
        if parsed.path == "/api/add-account":
            self._send_json(_add_account_flow())
            return
        if parsed.path == "/api/refresh-status":
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
