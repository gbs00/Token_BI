# Token BI Mac App Productization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn Token BI from a project-directory prototype into a distributable macOS app with a Python sidecar backend, App Support data storage, DMG packaging, and GitHub updater readiness.

**Architecture:** Keep the existing FastAPI/control-panel backend and package it as a sidecar executable. Tauri becomes the app supervisor: it starts the sidecar, opens the local control panel, stops owned processes on exit, and later checks GitHub Releases for updates.

**Tech Stack:** Tauri 2, Rust, Python 3.9+, FastAPI, PyInstaller, GitHub Releases, Apple Developer ID signing/notarization when credentials are available.

---

## Files And Responsibilities

- Create `app/app_paths.py`: resolves project-root mode vs packaged-app mode, including `TOKEN_BI_APP_DATA_DIR`.
- Create `app/migration.py`: migrates config/runtime data from the old project directory to `~/Library/Application Support/Token BI/`.
- Create `app/cli.py`: sidecar CLI with `control-panel`, `main-server`, `migrate`, and `health` commands.
- Modify `app/config.py`: use App Support directories for user data while keeping templates/static from packaged resources.
- Modify `scripts/control_panel.py`: add `/api/app/health` and `/api/app/shutdown`, and allow main service control without project-root scripts.
- Create `token-bi-backend.spec`: PyInstaller spec for sidecar packaging.
- Create `scripts/build_sidecar.sh`: builds the Python sidecar into `src-tauri/binaries/`.
- Modify `src-tauri/tauri.conf.json`: add `dmg`, `externalBin`, updater metadata placeholder, and sidecar bundle config.
- Modify `src-tauri/src/lib.rs`: replace project-root script calls with Tauri sidecar process management.
- Modify `package.json`: add `app:sidecar`, `app:release:local`, updater dependencies, and build orchestration.
- Create tests: `tests/test_app_paths.py`, `tests/test_migration.py`, `tests/test_cli.py`.
- Update docs: `README.md`, `SETUP.md`, `TECH_ARCHITECTURE.md`, `CHANGELOG.md`.

## Task 1: App Data Paths

**Files:**
- Create: `app/app_paths.py`
- Modify: `app/config.py`
- Test: `tests/test_app_paths.py`

- [ ] **Step 1: Write failing tests for data directory resolution**

```python
from pathlib import Path

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
```

- [ ] **Step 2: Run tests to verify failure**

Run: `./.venv/bin/pytest tests/test_app_paths.py -q`

Expected: fails because `app.app_paths` does not exist.

- [ ] **Step 3: Implement app path helpers**

Create `app/app_paths.py` with deterministic path resolution:

```python
from __future__ import annotations

import os
import sys
from pathlib import Path


APP_NAME = "Token BI"


def resolve_project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def resolve_app_data_dir() -> Path:
    override = os.getenv("TOKEN_BI_APP_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    home = Path(os.getenv("HOME", str(Path.home()))).expanduser()
    return home / "Library" / "Application Support" / APP_NAME
```

- [ ] **Step 4: Update settings to use App Support for user data**

Modify `app/config.py` so `project_root`, `templates_dir`, and `static_dir` still resolve from resources, while `config_dir` and `runtime_dir` resolve from `resolve_app_data_dir()`:

```python
from app.app_paths import resolve_app_data_dir, resolve_project_root

project_root = resolve_project_root()
app_data_dir = resolve_app_data_dir()
config_dir = app_data_dir / "config"
runtime_dir = app_data_dir / "runtime"
templates_dir = project_root / "app" / "templates"
static_dir = project_root / "app" / "static"
```

- [ ] **Step 5: Run tests**

Run: `./.venv/bin/pytest tests/test_app_paths.py -q`

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add app/app_paths.py app/config.py tests/test_app_paths.py
git commit -m "feat: resolve token bi app data paths"
```

Do not push.

## Task 2: Data Migration

**Files:**
- Create: `app/migration.py`
- Test: `tests/test_migration.py`

- [ ] **Step 1: Write failing migration tests**

```python
import json

from app.migration import migrate_project_data


def test_migration_copies_accounts_and_runtime_contexts(tmp_path):
    old_root = tmp_path / "old"
    app_data = tmp_path / "app-data"
    (old_root / "config").mkdir(parents=True)
    (old_root / "runtime" / "contexts" / "acc_1").mkdir(parents=True)
    (old_root / "config" / "accounts.json").write_text(
        json.dumps(
            {
                "accounts": [
                    {
                        "account_id": "acc_1",
                        "account_alias": "8754****@qq.com",
                        "masked_email": "8754****@qq.com",
                        "status": "active",
                        "session_storage_path": str(old_root / "runtime" / "contexts" / "acc_1"),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    result = migrate_project_data(old_root=old_root, app_data_dir=app_data)

    assert result.migrated is True
    assert (app_data / "config" / "accounts.json").exists()
    assert (app_data / "runtime" / "contexts" / "acc_1").exists()
    payload = json.loads((app_data / "config" / "accounts.json").read_text(encoding="utf-8"))
    assert payload["accounts"][0]["session_storage_path"] == str(app_data / "runtime" / "contexts" / "acc_1")


def test_migration_does_not_overwrite_existing_app_data(tmp_path):
    old_root = tmp_path / "old"
    app_data = tmp_path / "app-data"
    (old_root / "config").mkdir(parents=True)
    (app_data / "config").mkdir(parents=True)
    (old_root / "config" / "accounts.json").write_text('{"accounts": []}', encoding="utf-8")
    (app_data / "config" / "accounts.json").write_text('{"accounts": [{"account_id": "existing"}]}', encoding="utf-8")

    result = migrate_project_data(old_root=old_root, app_data_dir=app_data)

    assert result.migrated is False
    assert "existing" in (app_data / "config" / "accounts.json").read_text(encoding="utf-8")
```

- [ ] **Step 2: Run tests to verify failure**

Run: `./.venv/bin/pytest tests/test_migration.py -q`

Expected: fails because `app.migration` does not exist.

- [ ] **Step 3: Implement migration**

Create `app/migration.py`:

```python
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MigrationResult:
    migrated: bool
    message: str


def migrate_project_data(old_root: Path, app_data_dir: Path) -> MigrationResult:
    source_accounts = old_root / "config" / "accounts.json"
    target_accounts = app_data_dir / "config" / "accounts.json"
    if not source_accounts.exists():
        return MigrationResult(False, "No project accounts file found.")
    if target_accounts.exists():
        return MigrationResult(False, "App data already exists; migration skipped.")

    target_accounts.parent.mkdir(parents=True, exist_ok=True)
    (app_data_dir / "runtime").mkdir(parents=True, exist_ok=True)

    source_runtime = old_root / "runtime"
    target_runtime = app_data_dir / "runtime"
    if source_runtime.exists():
        shutil.copytree(source_runtime, target_runtime, dirs_exist_ok=True)

    payload = json.loads(source_accounts.read_text(encoding="utf-8"))
    for account in payload.get("accounts", []):
        account_id = account.get("account_id")
        if account_id:
            account["session_storage_path"] = str(target_runtime / "contexts" / account_id)
    target_accounts.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return MigrationResult(True, "Project data migrated to Application Support.")
```

- [ ] **Step 4: Run tests**

Run: `./.venv/bin/pytest tests/test_migration.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/migration.py tests/test_migration.py
git commit -m "feat: migrate token bi app data"
```

Do not push.

## Task 3: Python Sidecar CLI

**Files:**
- Create: `app/cli.py`
- Modify: `scripts/control_panel.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write failing CLI tests**

```python
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
```

- [ ] **Step 2: Run tests to verify failure**

Run: `./.venv/bin/pytest tests/test_cli.py -q`

Expected: fails because `app.cli` does not exist.

- [ ] **Step 3: Implement CLI parser and command dispatch**

Create `app/cli.py` with:

```python
from __future__ import annotations

import argparse
import os


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="token-bi-backend")
    subparsers = parser.add_subparsers(dest="command", required=True)

    control = subparsers.add_parser("control-panel")
    control.add_argument("--host", default="127.0.0.1")
    control.add_argument("--port", type=int, default=8790)
    control.add_argument("--main-port", type=int, default=8787)

    main = subparsers.add_parser("main-server")
    main.add_argument("--host", default="0.0.0.0")
    main.add_argument("--port", type=int, default=8787)

    subparsers.add_parser("migrate")
    subparsers.add_parser("health")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "control-panel":
        os.environ["TOKEN_BI_CONTROL_HOST"] = args.host
        os.environ["TOKEN_BI_CONTROL_PORT"] = str(args.port)
        os.environ["TOKEN_BI_PORT"] = str(args.main_port)
        from scripts.control_panel import main as control_main

        control_main()
        return
    if args.command == "main-server":
        import uvicorn

        uvicorn.run("app.main:app", host=args.host, port=args.port)
        return
    if args.command == "migrate":
        from app.app_paths import resolve_app_data_dir, resolve_project_root
        from app.migration import migrate_project_data

        print(migrate_project_data(resolve_project_root(), resolve_app_data_dir()).message)
        return
    if args.command == "health":
        print("ok")
        return
    raise SystemExit(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Add control-panel app endpoints**

Modify `scripts/control_panel.py`:

- `GET /api/app/health` returns `{"ok": true}`.
- `POST /api/app/shutdown` stops the main service and closes project-owned Chrome workers, then shuts down the control-panel server from a background thread.

- [ ] **Step 5: Run tests**

Run: `./.venv/bin/pytest tests/test_cli.py -q`

Expected: all tests pass.

- [ ] **Step 6: Smoke test CLI**

Run: `./.venv/bin/python -m app.cli health`

Expected: prints `ok`.

- [ ] **Step 7: Commit**

```bash
git add app/cli.py scripts/control_panel.py tests/test_cli.py
git commit -m "feat: add token bi backend sidecar cli"
```

Do not push.

## Task 4: Sidecar Packaging

**Files:**
- Create: `token-bi-backend.spec`
- Create: `scripts/build_sidecar.sh`
- Modify: `requirements.txt`
- Modify: `.gitignore`

- [ ] **Step 1: Add PyInstaller dependency**

Modify `requirements.txt`:

```text
pyinstaller>=6.0,<7.0
```

- [ ] **Step 2: Create PyInstaller spec**

Create `token-bi-backend.spec` that includes `app/templates`, `app/static`, and `scripts/control_panel.py` as package data and uses `app/cli.py` as the entrypoint.

- [ ] **Step 3: Create sidecar build script**

Create `scripts/build_sidecar.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TARGET_DIR="$PROJECT_ROOT/src-tauri/binaries"

mkdir -p "$TARGET_DIR"
"$PROJECT_ROOT/.venv/bin/pyinstaller" "$PROJECT_ROOT/token-bi-backend.spec" --noconfirm
cp "$PROJECT_ROOT/dist/token-bi-backend" "$TARGET_DIR/token-bi-backend-aarch64-apple-darwin"
chmod +x "$TARGET_DIR/token-bi-backend-aarch64-apple-darwin"
echo "Built sidecar: $TARGET_DIR/token-bi-backend-aarch64-apple-darwin"
```

- [ ] **Step 4: Ignore generated binaries and build outputs**

Modify `.gitignore` to include:

```gitignore
build/
dist/
src-tauri/binaries/token-bi-backend-*
```

- [ ] **Step 5: Build sidecar**

Run: `./scripts/build_sidecar.sh`

Expected: creates `src-tauri/binaries/token-bi-backend-aarch64-apple-darwin`.

- [ ] **Step 6: Smoke test sidecar**

Run: `./src-tauri/binaries/token-bi-backend-aarch64-apple-darwin health`

Expected: prints `ok`.

- [ ] **Step 7: Commit**

```bash
git add requirements.txt .gitignore token-bi-backend.spec scripts/build_sidecar.sh
git commit -m "build: package token bi backend sidecar"
```

Do not push.

## Task 5: Tauri Sidecar Supervision

**Files:**
- Modify: `src-tauri/tauri.conf.json`
- Modify: `src-tauri/src/lib.rs`
- Modify: `src-tauri/Cargo.toml`
- Modify: `package.json`

- [ ] **Step 1: Configure sidecar and DMG target**

Modify `src-tauri/tauri.conf.json`:

```json
{
  "bundle": {
    "active": true,
    "targets": ["app", "dmg"],
    "externalBin": ["binaries/token-bi-backend"],
    "macOS": {
      "minimumSystemVersion": "10.15"
    }
  }
}
```

- [ ] **Step 2: Add shell plugin dependency**

Modify `src-tauri/Cargo.toml`:

```toml
tauri-plugin-shell = "2"
```

- [ ] **Step 3: Replace project-root scripts with sidecar process management**

Modify `src-tauri/src/lib.rs` so setup spawns:

```rust
let sidecar = app.shell().sidecar("token-bi-backend")?;
let (mut rx, child) = sidecar
    .args(["control-panel", "--host", "127.0.0.1", "--port", "8790", "--main-port", "8787"])
    .spawn()?;
```

Keep the existing `wait_for_control_panel()` logic, but remove `TOKEN_BI_PROJECT_ROOT` and shell script execution.

- [ ] **Step 4: Stop via app shutdown endpoint**

On close, call `POST http://127.0.0.1:8790/api/app/shutdown`. If the endpoint fails, kill the sidecar child process.

- [ ] **Step 5: Add npm scripts**

Modify `package.json`:

```json
{
  "scripts": {
    "app:sidecar": "./scripts/build_sidecar.sh",
    "app:build": "npm run app:sidecar && tauri build",
    "app:release:local": "npm run app:build"
  }
}
```

- [ ] **Step 6: Build App**

Run: `npm run app:build`

Expected: `src-tauri/target/release/bundle/dmg/Token BI_*.dmg` exists.

- [ ] **Step 7: Commit**

```bash
git add src-tauri/tauri.conf.json src-tauri/src/lib.rs src-tauri/Cargo.toml package.json
git commit -m "feat: run token bi backend as tauri sidecar"
```

Do not push.

## Task 6: Updater And Release Readiness

**Files:**
- Modify: `src-tauri/tauri.conf.json`
- Modify: `src-tauri/Cargo.toml`
- Modify: `package.json`
- Create: `scripts/release_local.sh`
- Create: `docs/RELEASE.md`

- [ ] **Step 1: Add updater dependencies**

Add npm and Rust updater packages:

```bash
npm install @tauri-apps/plugin-updater
cargo add tauri-plugin-updater --manifest-path src-tauri/Cargo.toml
```

- [ ] **Step 2: Configure updater endpoint placeholder**

In `src-tauri/tauri.conf.json`, add an updater endpoint pointing to GitHub Releases manifest URL:

```json
{
  "plugins": {
    "updater": {
      "endpoints": [
        "https://github.com/gbs00/Token_BI/releases/latest/download/latest.json"
      ],
      "pubkey": "$TOKEN_BI_UPDATER_PUBKEY"
    }
  }
}
```

- [ ] **Step 3: Add local release script**

Create `scripts/release_local.sh` that:

- verifies tests pass,
- builds sidecar,
- builds Tauri app and DMG,
- prints paths to DMG, `.app`, and updater artifacts,
- does not upload or push.

- [ ] **Step 4: Document release process**

Create `docs/RELEASE.md` with:

- local unsigned build steps,
- signed build environment variables,
- notarization prerequisites,
- GitHub Releases upload checklist,
- updater manifest checklist,
- explicit rule: no GitHub push or release without user confirmation.

- [ ] **Step 5: Commit**

```bash
git add src-tauri/tauri.conf.json src-tauri/Cargo.toml package.json package-lock.json scripts/release_local.sh docs/RELEASE.md
git commit -m "build: prepare github release updater workflow"
```

Do not push.

## Task 7: Product UX And Documentation

**Files:**
- Modify: `scripts/control_panel.py`
- Modify: `README.md`
- Modify: `SETUP.md`
- Modify: `TECH_ARCHITECTURE.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Add user-facing App readiness copy**

Update the control panel to show:

- data is stored locally on this Mac,
- login state is stored in the Mac user data directory,
- usage data is not uploaded,
- Chrome is required,
- sidecar status is visible.

- [ ] **Step 2: Add Chrome detection copy**

If Chrome is missing, show:

```text
未检测到 Google Chrome。Token BI 需要使用本机 Chrome 登录 Codex 并读取 usage。
请安装 Chrome 后重新启动 Token BI。
```

- [ ] **Step 3: Update docs**

Document:

- `Token BI.app` is the recommended entry,
- user data path is `~/Library/Application Support/Token BI/`,
- DMG distribution path,
- updater release path,
- signing/notarization status,
- no GitHub push without explicit confirmation.

- [ ] **Step 4: Commit**

```bash
git add scripts/control_panel.py README.md SETUP.md TECH_ARCHITECTURE.md CHANGELOG.md
git commit -m "docs: document token bi app distribution model"
```

Do not push.

## Final Verification

- [ ] Run Python tests:

```bash
./.venv/bin/pytest -q
```

Expected: all tests pass.

- [ ] Run compile check:

```bash
./.venv/bin/python -m compileall app scripts tests
```

Expected: no syntax errors.

- [ ] Build sidecar:

```bash
./scripts/build_sidecar.sh
```

Expected: sidecar binary exists and `health` prints `ok`.

- [ ] Build DMG:

```bash
npm run app:build
```

Expected: DMG exists under `src-tauri/target/release/bundle/dmg/`.

- [ ] Run packaged App from build output:

```bash
open "src-tauri/target/release/bundle/macos/Token BI.app"
```

Expected: control panel opens, starts/stops `8787`, and can show QR code.

- [ ] Quit App and verify cleanup:

```bash
lsof -nP -iTCP:8790 -sTCP:LISTEN
lsof -nP -iTCP:8787 -sTCP:LISTEN
```

Expected: no listeners remain.

## Push Policy

Do not push to GitHub during implementation. Recommend a GitHub push only after:

- all commits in this plan are complete,
- final verification passes,
- DMG can be opened locally,
- a concise release/commit summary is ready for user confirmation.
