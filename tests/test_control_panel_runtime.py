from __future__ import annotations

import socket
import subprocess
import sys
from types import SimpleNamespace

from scripts import control_panel


def test_select_main_port_uses_default_when_available() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        free_port = sock.getsockname()[1]

    assert control_panel._select_main_port(free_port, free_port + 2) == free_port


def test_select_main_port_falls_back_when_default_is_occupied() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        occupied_port = sock.getsockname()[1]

        assert control_panel._select_main_port(occupied_port, occupied_port + 2) == occupied_port + 1


def test_port_available_detects_wildcard_listener() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("0.0.0.0", 0))
        sock.listen()
        occupied_port = sock.getsockname()[1]

        assert control_panel._port_available(occupied_port) is False


def test_port_available_allows_recently_closed_listener() -> None:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client.connect(("127.0.0.1", port))
    connection, _ = listener.accept()
    connection.close()
    client.close()
    listener.close()

    assert control_panel._port_available(port) is True


def test_stop_pid_reaps_exited_child_process(monkeypatch) -> None:
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        start_new_session=True,
    )
    monkeypatch.setattr(control_panel, "_pid_is_token_bi_main", lambda _pid: True)

    try:
        assert control_panel._stop_pid(str(process.pid)) is True
        assert control_panel._pid_alive(str(process.pid)) is False
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


def test_start_main_server_cleans_runtime_files_when_readiness_fails(monkeypatch, tmp_path) -> None:
    pid_file = tmp_path / "token_bi.pid"
    runtime_file = tmp_path / "token_bi_runtime.json"
    log_dir = tmp_path / "logs"

    class FakeProcess:
        pid = 12345

    monkeypatch.setattr(control_panel, "PID_FILE", pid_file)
    monkeypatch.setattr(control_panel, "RUNTIME_STATE_FILE", runtime_file)
    monkeypatch.setattr(control_panel, "LOG_DIR", log_dir)
    monkeypatch.setattr(control_panel, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(control_panel, "_main_server_running", lambda: (False, None))
    monkeypatch.setattr(control_panel, "_select_main_port", lambda start_port, max_port: 8787)
    monkeypatch.setattr(control_panel, "_backend_command", lambda args: ["fake-token-bi"])
    monkeypatch.setattr(control_panel, "_wait_for_main_server", lambda port=None: False)
    monkeypatch.setattr(control_panel.subprocess, "Popen", lambda *args, **kwargs: FakeProcess())

    ok, message = control_panel._start_main_server_process()

    assert ok is False
    assert "did not become ready" in message
    assert not pid_file.exists()
    assert not runtime_file.exists()


def test_packaged_main_server_resets_pyinstaller_environment(monkeypatch, tmp_path) -> None:
    pid_file = tmp_path / "token_bi.pid"
    runtime_file = tmp_path / "token_bi_runtime.json"
    log_dir = tmp_path / "logs"
    captured = {}

    class FakeProcess:
        pid = 12345

    def fake_popen(*args, **kwargs):
        captured["env"] = kwargs["env"]
        return FakeProcess()

    monkeypatch.setattr(control_panel, "PID_FILE", pid_file)
    monkeypatch.setattr(control_panel, "RUNTIME_STATE_FILE", runtime_file)
    monkeypatch.setattr(control_panel, "LOG_DIR", log_dir)
    monkeypatch.setattr(control_panel, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(control_panel, "APP_DATA_DIR", tmp_path)
    monkeypatch.setattr(control_panel, "_main_server_running", lambda: (False, None))
    monkeypatch.setattr(control_panel, "_select_main_port", lambda start_port, max_port: 8787)
    monkeypatch.setattr(control_panel, "_backend_command", lambda args: ["fake-token-bi"])
    monkeypatch.setattr(control_panel, "_wait_for_main_server", lambda port=None: False)
    monkeypatch.setattr(control_panel.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(control_panel.sys, "frozen", True, raising=False)

    control_panel._start_main_server_process()

    assert captured["env"]["PYINSTALLER_RESET_ENVIRONMENT"] == "1"


def test_packaged_control_uses_sibling_backend_binary(monkeypatch, tmp_path) -> None:
    control_binary = tmp_path / "token-bi-control"
    monkeypatch.setattr(control_panel.sys, "frozen", True, raising=False)
    monkeypatch.setattr(control_panel.sys, "executable", str(control_binary))
    monkeypatch.delenv("TOKEN_BI_MAIN_BACKEND_BIN", raising=False)

    command = control_panel._backend_command(["main-server", "--port", "8787"])

    assert command == [
        str(tmp_path / "token-bi-backend"),
        "main-server",
        "--port",
        "8787",
    ]


def test_dashboard_urls_cache_system_network_probe(monkeypatch) -> None:
    calls = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        return SimpleNamespace(stdout="192.168.1.8\n")

    monkeypatch.setattr(control_panel, "_dashboard_url_cache", None)
    monkeypatch.setattr(control_panel, "_current_main_port", lambda: 8787)
    monkeypatch.setattr(control_panel.subprocess, "run", fake_run)

    first = control_panel._dashboard_urls()
    second = control_panel._dashboard_urls()

    assert first == second
    assert first["lan"] == "http://192.168.1.8:8787/dashboard"
    assert calls == [["ipconfig", "getifaddr", "en0"]]


def test_account_action_button_label_is_state_driven() -> None:
    assert control_panel._account_action_label(None) == "登录账号"
    assert control_panel._account_action_label({"status": "pending"}) == "登录账号"
    assert control_panel._account_action_label({"status": "expired"}) == "登录账号"
    assert control_panel._account_action_label({"status": "active"}) == "退出账号"


def test_service_action_button_label_is_state_driven() -> None:
    assert control_panel._service_action_label(False) == "开启服务"
    assert control_panel._service_action_label(True) == "关闭服务"


def test_error_payload_maps_known_failures_to_next_steps() -> None:
    payload = control_panel._error_payload("login_required")

    assert payload["ok"] is False
    assert "登录" in payload["title"]
    assert payload["next_step"]


def test_app_health_payload_identifies_token_bi_control_panel(monkeypatch, tmp_path) -> None:
    pid_file = tmp_path / "token_bi.pid"
    runtime_file = tmp_path / "token_bi_runtime.json"

    monkeypatch.setattr(control_panel, "PID_FILE", pid_file)
    monkeypatch.setattr(control_panel, "RUNTIME_STATE_FILE", runtime_file)
    monkeypatch.setattr(control_panel, "APP_DATA_DIR", tmp_path)
    monkeypatch.setattr(control_panel.sys, "frozen", False, raising=False)

    payload = control_panel._app_health_payload()

    assert payload["ok"] is True
    assert payload["service"] == "token-bi-control-panel"
    assert payload["control_port"] == control_panel.CONTROL_PORT
    assert payload["main_port"] == control_panel.DEFAULT_MAIN_PORT
    assert payload["pid"] == ""
    assert payload["app_data_dir"] == str(tmp_path)
    assert payload["packaged"] is False


def test_app_health_payload_cleans_stale_runtime_state(monkeypatch, tmp_path) -> None:
    pid_file = tmp_path / "token_bi.pid"
    runtime_file = tmp_path / "token_bi_runtime.json"
    stale_pid = "999999"
    pid_file.write_text(stale_pid, encoding="utf-8")
    runtime_file.write_text('{"port": 8799, "pid": "999999"}\n', encoding="utf-8")

    monkeypatch.setattr(control_panel, "PID_FILE", pid_file)
    monkeypatch.setattr(control_panel, "RUNTIME_STATE_FILE", runtime_file)
    monkeypatch.setattr(control_panel, "_pid_alive", lambda pid: False)

    payload = control_panel._app_health_payload()

    assert payload["pid"] == ""
    assert payload["main_port"] == control_panel.DEFAULT_MAIN_PORT
    assert not pid_file.exists()
    assert not runtime_file.exists()


def test_status_payload_prefers_main_service_account(monkeypatch) -> None:
    monkeypatch.setattr(control_panel, "_main_server_running", lambda: (True, "12345"))
    monkeypatch.setattr(
        control_panel,
        "_main_visible_accounts",
        lambda: [
            {
                "account_id": "acc_real",
                "masked_email": "tim****@gmail.com",
                "status": "active",
            }
        ],
    )
    monkeypatch.setattr(
        control_panel,
        "_preferred_account",
        lambda: {
            "account_id": "acc_old",
            "masked_email": "Lark...",
            "status": "pending",
        },
    )
    monkeypatch.setattr(control_panel, "_dashboard_urls", lambda: {})
    monkeypatch.setattr(control_panel, "_main_runtime_status", lambda: {})
    monkeypatch.setattr(control_panel, "_diagnostics_items", lambda: [])
    monkeypatch.setattr(control_panel, "_data_source_status", lambda diagnostics: "")
    monkeypatch.setattr(control_panel, "_chrome_available", lambda: True)
    monkeypatch.setattr(control_panel, "_tail_log", lambda: "")
    monkeypatch.setattr(control_panel, "_current_main_port", lambda: 8787)

    payload = control_panel._status_payload()

    assert payload["account"]["account_id"] == "acc_real"
    assert payload["account"]["masked_email"] == "tim****@gmail.com"
    assert payload["account_action_label"] == "退出账号"


def test_status_payload_uses_actual_last_successful_source_and_time(monkeypatch) -> None:
    monkeypatch.setattr(control_panel, "_main_server_running", lambda: (True, "12345"))
    monkeypatch.setattr(
        control_panel,
        "_main_runtime_status",
        lambda: {
            "service": "token-bi-main-service",
            "account": {
                "account_id": "acc_real",
                "masked_email": "tim****@gmail.com",
                "status": "active",
            },
            "usage": {
                "state": "ready",
                "updated_at": "2026-07-11T10:20:00+08:00",
                "source_type": "cli_rpc",
                "source_detail": "cli_rate_limits",
                "connector_name": "codex_cli_rpc",
            },
        },
    )
    monkeypatch.setattr(control_panel, "_dashboard_urls", lambda: {})
    monkeypatch.setattr(control_panel, "_diagnostics_items", lambda: [])
    monkeypatch.setattr(control_panel, "_data_source_status", lambda diagnostics: "")
    monkeypatch.setattr(control_panel, "_chrome_available", lambda: True)
    monkeypatch.setattr(control_panel, "_tail_log", lambda: "")
    monkeypatch.setattr(control_panel, "_current_main_port", lambda: 8787)

    payload = control_panel._status_payload()

    assert payload["usage"]["source_type"] == "cli_rpc"
    assert payload["usage"]["updated_at"] == "2026-07-11T10:20:00+08:00"


def test_refresh_live_accounts_bootstraps_local_codex_when_no_accounts(monkeypatch) -> None:
    def fake_request(method: str, path: str, payload: dict | None = None, timeout: int = 30) -> dict:
        assert method == "POST"
        assert path == "/api/v1/dashboard/refresh"
        return {
            "state": "ready",
            "account": {
                "account_id": "acc_local",
                "masked_email": "tim****@gmail.com",
            },
            "summary": {
                "source_type": "oauth",
                "source_detail": "oauth_usage_api",
                "connector_name": "codex_oauth",
            },
        }

    monkeypatch.setattr(control_panel, "_main_server_running", lambda: (True, "12345"))
    monkeypatch.setattr(control_panel, "_main_visible_accounts", lambda: [])
    monkeypatch.setattr(control_panel, "_main_api_request", fake_request)

    payload = control_panel._refresh_live_accounts()

    assert payload["ok"] is True
    assert "tim****@gmail.com" in payload["message"]
    assert payload["results"][0]["source_type"] == "oauth"


def test_control_panel_uses_single_service_button_and_hidden_qr_modal() -> None:
    assert 'id="serviceActionBtn"' in control_panel.HTML
    assert 'id="startBtn"' not in control_panel.HTML
    assert 'id="stopBtn"' not in control_panel.HTML
    assert 'id="pairModal" class="modal-backdrop hidden"' in control_panel.HTML
    assert 'data-close="pairModal"' in control_panel.HTML


def test_control_panel_uses_latest_console_layout() -> None:
    assert 'class="app-shell"' in control_panel.HTML
    assert 'class="topnav"' in control_panel.HTML
    assert 'class="summary-grid"' in control_panel.HTML
    assert 'class="main-grid"' in control_panel.HTML
    assert 'class="card panel action-panel"' in control_panel.HTML
    assert 'class="bottom-grid"' in control_panel.HTML
    assert 'class="service-list"' in control_panel.HTML
    assert "本机隐私说明" not in control_panel.HTML


def test_control_panel_keeps_confirmed_v102_actions_only() -> None:
    assert "快捷操作" in control_panel.HTML
    assert 'id="openDashboardBtn"' in control_panel.HTML
    assert "打开看板" in control_panel.HTML
    assert 'id="pairDeviceBtn"' in control_panel.HTML
    assert "扫码连接副屏" in control_panel.HTML
    assert 'id="refreshBtn"' in control_panel.HTML
    assert "刷新状态" in control_panel.HTML
    assert "清理残留" not in control_panel.HTML
    assert "打开日志" not in control_panel.HTML
    assert "首次启动引导" not in control_panel.HTML


def test_control_panel_primary_action_matches_account_state() -> None:
    assert 'primaryAction = hasActiveAccount ? "dashboard" : "account"' in control_panel.HTML
    assert 'primaryAction === "account"' in control_panel.HTML
    assert 'hasActiveAccount ? "打开看板" : "登录账号"' in control_panel.HTML
    assert 'payload.account_action_label || "登录账号"' in control_panel.HTML


def test_control_panel_latest_ui_keeps_real_dialog_actions() -> None:
    assert 'id="logsModal" class="modal-backdrop hidden"' in control_panel.HTML
    assert 'id="accountModal" class="modal-backdrop hidden"' in control_panel.HTML
    assert 'id="loginModal" class="modal-backdrop hidden"' in control_panel.HTML
    assert 'id="confirmLogoutButton"' in control_panel.HTML
    assert 'id="confirmLoginButton"' in control_panel.HTML
    assert 'id="toast"' in control_panel.HTML
    assert 'postAction("/api/account-action"' in control_panel.HTML


def test_control_panel_does_not_fake_oauth_or_sync_time() -> None:
    assert "dataSourceValue.textContent = payload.account ? 'OAuth'" not in control_panel.HTML
    assert "lastRefreshValue.textContent = now.toLocaleTimeString" not in control_panel.HTML
    assert "sourceLabel(usage.source_type)" in control_panel.HTML
    assert "formatSyncTime(usage && usage.updated_at)" in control_panel.HTML
