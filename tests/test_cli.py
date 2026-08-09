import json
import re
from pathlib import Path

from app.main import create_app
from app.cli import build_parser
from scripts import control_panel
from scripts.control_cli import build_parser as build_control_parser


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_VERSION = "1.1.2"


def test_control_cli_has_control_panel_arguments():
    args = build_control_parser().parse_args(["--port", "8790"])
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
    monkeypatch.setattr(control_panel.sys, "executable", "/tmp/token-bi-control")
    monkeypatch.setattr(control_panel.sys, "frozen", True, raising=False)
    monkeypatch.delenv("TOKEN_BI_MAIN_BACKEND_BIN", raising=False)

    assert control_panel._backend_command(["health"]) == ["/tmp/token-bi-backend", "health"]


def test_release_version_metadata_matches_v111() -> None:
    package_json = json.loads((PROJECT_ROOT / "package.json").read_text(encoding="utf-8"))
    package_lock = json.loads((PROJECT_ROOT / "package-lock.json").read_text(encoding="utf-8"))
    tauri_config = json.loads(
        (PROJECT_ROOT / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8")
    )
    cargo_toml = (PROJECT_ROOT / "src-tauri" / "Cargo.toml").read_text(encoding="utf-8")

    assert package_json["version"] == EXPECTED_VERSION
    assert package_lock["version"] == EXPECTED_VERSION
    assert package_lock["packages"][""]["version"] == EXPECTED_VERSION
    assert tauri_config["version"] == EXPECTED_VERSION
    assert re.search(r'^version = "1\.1\.2"$', cargo_toml, flags=re.MULTILINE)
    assert create_app().version == EXPECTED_VERSION
