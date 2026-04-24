from pathlib import Path
import sys

from app.app_paths import resolve_app_data_dir, resolve_project_root


def test_resolve_app_data_dir_prefers_env(tmp_path, monkeypatch):
    monkeypatch.setenv("TOKEN_BI_APP_DATA_DIR", str(tmp_path / "Token BI Data"))
    assert resolve_app_data_dir() == tmp_path / "Token BI Data"


def test_resolve_app_data_dir_defaults_to_application_support(monkeypatch):
    monkeypatch.delenv("TOKEN_BI_APP_DATA_DIR", raising=False)
    monkeypatch.setenv("HOME", "/Users/example")
    assert resolve_app_data_dir() == Path("/Users/example/Library/Application Support/Token BI")


def test_resolve_project_root_still_finds_repo_root():
    root = resolve_project_root()
    assert (root / "app").exists()
    assert (root / "src-tauri").exists()


def test_resolve_project_root_uses_pyinstaller_meipass(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    assert resolve_project_root() == tmp_path
