from __future__ import annotations

import socket

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


def test_control_panel_uses_single_service_button_and_hidden_qr_modal() -> None:
    assert 'id="serviceActionBtn"' in control_panel.HTML
    assert 'id="startBtn"' not in control_panel.HTML
    assert 'id="stopBtn"' not in control_panel.HTML
    assert 'id="pairModal" class="modal-backdrop hidden"' in control_panel.HTML
    assert "closePairModal" in control_panel.HTML


def test_control_panel_uses_v102_console_layout() -> None:
    assert 'class="app"' in control_panel.HTML
    assert 'class="summary"' in control_panel.HTML
    assert 'class="main-grid"' in control_panel.HTML
    assert 'class="action-panel"' in control_panel.HTML
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
    assert "primaryAction = payload.account ? 'dashboard' : 'account'" in control_panel.HTML
    assert "primaryAction === 'account'" in control_panel.HTML
    assert "payload.account ? '打开看板' : '登录账号'" in control_panel.HTML
    assert "accountActionLabel.textContent = payload.account_action_label || '登录账号'" in control_panel.HTML
