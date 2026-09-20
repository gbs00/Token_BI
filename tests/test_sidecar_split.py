from __future__ import annotations

import pytest

from app.cli import build_parser as build_backend_parser
from scripts.control_cli import build_parser as build_control_parser


@pytest.mark.parametrize("arguments", [[], ["--host", "127.0.0.1", "--port", "8790", "--main-port", "8787"]])
def test_control_cli_owns_control_panel_arguments(arguments) -> None:
    args = build_control_parser().parse_args(arguments)

    assert args.host == "127.0.0.1"
    assert args.port == 8790
    assert args.main_port == 8787


def test_backend_cli_does_not_bundle_control_panel_command() -> None:
    with pytest.raises(SystemExit):
        build_backend_parser().parse_args(["control-panel"])
