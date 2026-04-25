from __future__ import annotations

import socket

from scripts import control_panel


def test_select_main_port_uses_default_when_available() -> None:
    assert control_panel._select_main_port(8787, 8789) == 8787


def test_select_main_port_falls_back_when_default_is_occupied() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        occupied_port = sock.getsockname()[1]

        assert control_panel._select_main_port(occupied_port, occupied_port + 2) == occupied_port + 1


def test_account_action_button_label_is_state_driven() -> None:
    assert control_panel._account_action_label(None) == "登录账号"
    assert control_panel._account_action_label({"status": "pending"}) == "登录账号"
    assert control_panel._account_action_label({"status": "expired"}) == "登录账号"
    assert control_panel._account_action_label({"status": "active"}) == "退出账号"


def test_error_payload_maps_known_failures_to_next_steps() -> None:
    payload = control_panel._error_payload("login_required")

    assert payload["ok"] is False
    assert "登录" in payload["title"]
    assert payload["next_step"]
