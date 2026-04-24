from app.cli import build_parser
from scripts import control_panel


def test_cli_has_control_panel_command():
    args = build_parser().parse_args(["control-panel", "--port", "8790"])
    assert args.command == "control-panel"
    assert args.port == 8790


def test_cli_has_main_server_command():
    args = build_parser().parse_args(["main-server", "--host", "0.0.0.0", "--port", "8787"])
    assert args.command == "main-server"
    assert args.host == "0.0.0.0"
    assert args.port == 8787


def test_control_panel_backend_command_uses_module_in_dev(monkeypatch):
    monkeypatch.setattr(control_panel.sys, "executable", "/tmp/python")
    monkeypatch.setattr(control_panel.sys, "frozen", False, raising=False)

    assert control_panel._backend_command(["health"]) == ["/tmp/python", "-m", "app.cli", "health"]


def test_control_panel_backend_command_uses_executable_when_frozen(monkeypatch):
    monkeypatch.setattr(control_panel.sys, "executable", "/tmp/token-bi-backend")
    monkeypatch.setattr(control_panel.sys, "frozen", True, raising=False)

    assert control_panel._backend_command(["health"]) == ["/tmp/token-bi-backend", "health"]
