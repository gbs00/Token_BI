from app.cli import build_parser


def test_cli_has_control_panel_command():
    args = build_parser().parse_args(["control-panel", "--port", "8790"])
    assert args.command == "control-panel"
    assert args.port == 8790


def test_cli_has_main_server_command():
    args = build_parser().parse_args(["main-server", "--host", "0.0.0.0", "--port", "8787"])
    assert args.command == "main-server"
    assert args.host == "0.0.0.0"
    assert args.port == 8787
