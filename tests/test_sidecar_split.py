from __future__ import annotations

from pathlib import Path

import pytest

from app.cli import build_parser as build_backend_parser
from scripts.control_cli import build_parser as build_control_parser


def test_control_cli_owns_control_panel_arguments() -> None:
    args = build_control_parser().parse_args(
        ["--host", "127.0.0.1", "--port", "8790", "--main-port", "8787"]
    )

    assert args.host == "127.0.0.1"
    assert args.port == 8790
    assert args.main_port == 8787


def test_backend_cli_does_not_bundle_control_panel_command() -> None:
    with pytest.raises(SystemExit):
        build_backend_parser().parse_args(["control-panel"])


def test_control_runtime_packages_external_console_template() -> None:
    spec = Path("token-bi-control.spec").read_text(encoding="utf-8")
    source = Path("scripts/control_panel.py").read_text(encoding="utf-8")

    assert '"control_panel.html"' in spec
    assert 'Path(__file__).with_name("control_panel.html")' in source
    assert Path("scripts/control_panel.html").is_file()
