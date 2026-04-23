from __future__ import annotations

import json
import os
import socket
import subprocess
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = PROJECT_ROOT / "runtime"
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

START_SCRIPT = PROJECT_ROOT / "scripts" / "start_server.sh"
STOP_SCRIPT = PROJECT_ROOT / "scripts" / "stop_server.sh"
ACCOUNTS_FILE = PROJECT_ROOT / "config" / "accounts.json"


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


def _run_script(path: Path) -> tuple[int, str]:
    try:
        result = subprocess.run(
            [str(path)],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        return 1, str(exc)

    output = (result.stdout + result.stderr).strip()
    return result.returncode, output


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
    running, pid = _main_server_running()
    if running:
        return True, f"Token BI is already running · PID {pid or '--'}"

    code, output = _run_script(START_SCRIPT)
    if code != 0:
        return False, output or "Unable to start Token BI."
    if not _wait_for_main_server():
        return False, "Token BI start command completed, but the API did not become ready in time."
    return True, output or "Token BI started."


def _add_account_flow() -> dict:
    ok, message = _ensure_main_server()
    if not ok:
        return {"ok": False, "message": message}

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

    accounts = [account for account in _read_accounts() if not account.get("account_id", "").startswith("acc_demo_")]
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
        labels = ", ".join(item.get("masked_email") or item["account_id"] for item in ready)
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


def _status_payload() -> dict:
    running, pid = _main_server_running()
    account = _preferred_account()
    urls = _dashboard_urls()
    return {
        "running": running,
        "pid": pid,
        "port": MAIN_PORT,
        "hostname": LOCAL_HOSTNAME,
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
        --bg: #0d1220;
        --panel: #161d2d;
        --panel-alt: #212a3d;
        --line: rgba(255,255,255,.08);
        --text: #f4f7ff;
        --muted: #aab5ca;
        --accent: #66d7ef;
        --ok: #77d97b;
        --warn: #f7c968;
      }
      * { box-sizing: border-box; }
      body {
        margin: 0;
        font-family: "Avenir Next", "SF Pro Display", sans-serif;
        color: var(--text);
        background:
          radial-gradient(circle at top, rgba(84,118,255,.22), transparent 34%),
          linear-gradient(180deg, #0b1021 0%, #17171e 100%);
      }
      .shell {
        min-height: 100vh;
        display: grid;
        place-items: center;
        padding: 24px;
      }
      .panel {
        width: min(100%, 820px);
        border-radius: 24px;
        padding: 24px;
        background: rgba(19,22,31,.92);
        border: 1px solid var(--line);
        box-shadow: 0 24px 70px rgba(0,0,0,.35);
      }
      h1 {
        margin: 0 0 8px;
        font-size: 32px;
      }
      p { margin: 0; }
      .sub {
        color: var(--muted);
        font-size: 14px;
      }
      .status {
        margin-top: 18px;
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 14px;
      }
      .card {
        background: var(--panel-alt);
        border: 1px solid var(--line);
        border-radius: 18px;
        padding: 16px;
        min-width: 0;
      }
      .label {
        color: var(--muted);
        font-size: 12px;
        text-transform: uppercase;
        letter-spacing: .08em;
      }
      .value {
        margin-top: 10px;
        font-size: 22px;
        font-weight: 700;
        word-break: break-word;
      }
      .ok { color: var(--ok); }
      .warn { color: var(--warn); }
      .actions {
        margin-top: 18px;
        display: flex;
        flex-wrap: wrap;
        gap: 12px;
      }
      button {
        appearance: none;
        border: 1px solid rgba(102,215,239,.25);
        background: rgba(102,215,239,.14);
        color: var(--text);
        border-radius: 999px;
        padding: 12px 18px;
        font-size: 15px;
        font-weight: 700;
        cursor: pointer;
      }
      button.secondary {
        background: rgba(255,255,255,.06);
        border-color: var(--line);
      }
      button.add {
        background: linear-gradient(135deg, rgba(102,215,239,.28), rgba(119,217,123,.20));
        border-color: rgba(102,215,239,.42);
      }
      .links {
        margin-top: 18px;
        display: grid;
        gap: 10px;
      }
      .link-row {
        display: grid;
        gap: 4px;
      }
      .link-label {
        color: var(--muted);
        font-size: 12px;
      }
      .link-value {
        color: var(--text);
        word-break: break-all;
      }
      pre {
        margin: 18px 0 0;
        padding: 14px;
        border-radius: 16px;
        background: #0f1420;
        border: 1px solid var(--line);
        color: #dbe4f7;
        min-height: 160px;
        overflow: auto;
        white-space: pre-wrap;
      }
      .flash {
        margin-top: 14px;
        color: var(--muted);
        min-height: 20px;
      }
      @media (max-width: 720px) {
        .status { grid-template-columns: 1fr; }
        .panel { padding: 18px; }
      }
    </style>
  </head>
  <body>
    <div class="shell">
      <section class="panel">
        <h1>Token BI 控制台</h1>
        <p class="sub">在这页直接管理本地看板服务，不需要每次再通过 Codex 启动。</p>

        <div class="status">
          <div class="card">
            <div class="label">服务状态</div>
            <div class="value" id="serverState">加载中...</div>
          </div>
          <div class="card">
            <div class="label">当前账号</div>
            <div class="value" id="accountState">--</div>
          </div>
        </div>

        <div class="actions">
          <button id="startBtn">启动 Token BI</button>
          <button id="stopBtn" class="secondary">停止 Token BI</button>
          <button id="addAccountBtn" class="add">添加账号</button>
          <button id="openDashboardBtn">打开看板</button>
          <button id="refreshBtn" class="secondary">刷新状态</button>
        </div>

        <div class="links">
          <div class="link-row">
            <div class="link-label">固定入口</div>
            <div class="link-value" id="fixedUrl">--</div>
          </div>
          <div class="link-row">
            <div class="link-label">局域网入口</div>
            <div class="link-value" id="lanUrl">--</div>
          </div>
          <div class="link-row">
            <div class="link-label">本机入口</div>
            <div class="link-value" id="localUrl">--</div>
          </div>
        </div>

        <div class="flash" id="flash"></div>
        <pre id="logTail">加载日志中...</pre>
      </section>
    </div>

    <script>
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

        serverState.textContent = payload.running
          ? `运行中 · PID ${payload.pid || '--'}`
          : '已停止';
        serverState.className = 'value ' + (payload.running ? 'ok' : 'warn');

        if (payload.account) {
          accountState.textContent = `${payload.account.masked_email} · ${payload.account.status}`;
        } else {
          accountState.textContent = '暂无账号';
        }

        fixedUrl.textContent = payload.urls.fixed || '不可用';
        lanUrl.textContent = payload.urls.lan || '不可用';
        localUrl.textContent = payload.urls.local || '不可用';
        logTail.textContent = payload.log_tail || 'No server log yet.';
      }

      async function postAction(path) {
        const flash = document.getElementById('flash');
        flash.textContent = '处理中...';
        const res = await fetch(path, { method: 'POST' });
        const payload = await res.json();
        flash.textContent = payload.message || '完成';
        await refreshStatus();
      }

      async function refreshStatus() {
        const payload = await readStatus();
        renderStatus(payload);
      }

      document.getElementById('startBtn').addEventListener('click', () => postAction('/api/start'));
      document.getElementById('stopBtn').addEventListener('click', () => postAction('/api/stop'));
      document.getElementById('addAccountBtn').addEventListener('click', () => postAction('/api/add-account'));
      document.getElementById('openDashboardBtn').addEventListener('click', () => postAction('/api/open-dashboard'));
      document.getElementById('refreshBtn').addEventListener('click', () => postAction('/api/refresh-status'));

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
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/start":
            code, output = _run_script(START_SCRIPT)
            self._send_json({"ok": code == 0, "message": output or "Started."})
            return
        if parsed.path == "/api/stop":
            code, output = _run_script(STOP_SCRIPT)
            self._send_json({"ok": code == 0, "message": output or "Stopped."})
            return
        if parsed.path == "/api/open-dashboard":
            urls = _dashboard_urls()
            target = urls["fixed"] or urls["local"]
            code, output = _open_url(target)
            self._send_json({"ok": code == 0, "message": output, "url": target})
            return
        if parsed.path == "/api/add-account":
            self._send_json(_add_account_flow())
            return
        if parsed.path == "/api/refresh-status":
            self._send_json(_refresh_live_accounts())
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
