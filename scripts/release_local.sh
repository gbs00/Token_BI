#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"

: "${TAURI_SIGNING_PRIVATE_KEY:?Set TAURI_SIGNING_PRIVATE_KEY to the private key path or CI secret}"

TEST_DATA="$(mktemp -d "${TMPDIR:-/tmp}/token-bi-release.XXXXXX")"
trap 'rm -rf "$TEST_DATA"' EXIT
export TOKEN_BI_APP_DATA_DIR="$TEST_DATA"
export PYTHONDONTWRITEBYTECODE=1

"$PROJECT_ROOT/.venv/bin/python" -m pip check
"$PROJECT_ROOT/.venv/bin/python" -c 'from pathlib import Path; from playwright.sync_api import sync_playwright; p = sync_playwright().start(); assert all(Path(b.executable_path).is_file() for b in (p.chromium, p.webkit)), "Install Chromium and WebKit before releasing"; p.stop()'
"$PROJECT_ROOT/.venv/bin/pytest" -q -p no:cacheprovider
npm run desktop:test
npm run desktop:assets
cargo fmt --manifest-path src-tauri/Cargo.toml --check
cargo test --manifest-path src-tauri/Cargo.toml --target-dir src-tauri/target.noindex --lib
cargo clippy --manifest-path src-tauri/Cargo.toml --target-dir src-tauri/target.noindex --all-targets -- -D warnings
npm run app:build

APP_PATH="$PROJECT_ROOT/src-tauri/target.noindex/release/bundle/macos/Token BI.app"
VERSION="$(node -p 'require("./package.json").version')"
DMG_PATH="$PROJECT_ROOT/src-tauri/target.noindex/release/bundle/dmg/Token BI_${VERSION}_aarch64.dmg"
test -f "$DMG_PATH"
codesign --verify --deep --strict "$APP_PATH"
hdiutil verify "$DMG_PATH"
"$PROJECT_ROOT/.venv/bin/python" "$PROJECT_ROOT/scripts/verify_bundle.py" "$APP_PATH"
"$PROJECT_ROOT/.venv/bin/python" "$PROJECT_ROOT/scripts/prepare_release.py"
cargo test --manifest-path src-tauri/Cargo.toml --target-dir src-tauri/target.noindex --test updater_artifact -- --ignored --nocapture

echo "Release artifacts:"
echo "App: $APP_PATH"
echo "DMG: $DMG_PATH"
echo "No upload or git push was performed."
