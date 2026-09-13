from __future__ import annotations

from pathlib import Path
import os
import subprocess

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


def test_control_runtime_packages_external_console_template() -> None:
    spec = Path("token-bi-control.spec").read_text(encoding="utf-8")
    source = Path("scripts/control_panel.py").read_text(encoding="utf-8")

    assert '"control_panel.html"' in spec
    assert 'Path(__file__).with_name("control_panel.html")' in source
    assert Path("scripts/control_panel.html").is_file()


@pytest.mark.parametrize("start_result", [0, 1])
def test_open_console_only_opens_after_successful_start(tmp_path, start_result) -> None:
    script = tmp_path / "open_control_panel.sh"
    script.write_text(Path("scripts/open_control_panel.sh").read_text())
    start = tmp_path / "start_control_panel.sh"
    start.write_text(f"#!/bin/bash\nprintf 'start\\n'\nexit {start_result}\n")
    start.chmod(0o755)
    opener = tmp_path / "open"
    opener.write_text('#!/bin/bash\nprintf "open:%s\\n" "$1"\n')
    opener.chmod(0o755)
    result = subprocess.run(
        ["/bin/bash", str(script)], capture_output=True, text=True, timeout=5,
        env={**os.environ, "PATH": f"{tmp_path}:/usr/bin:/bin",
             "TOKEN_BI_CONTROL_HOST": "127.0.0.1", "TOKEN_BI_CONTROL_PORT": "18890"},
    )
    assert result.returncode == start_result
    assert result.stdout.splitlines() == (["start", "open:http://127.0.0.1:18890/"] if start_result == 0 else ["start"])
