# Token BI Release Guide

Token BI release builds are local-first. Do not push commits, create tags, upload artifacts, or publish GitHub Releases without explicit user confirmation.

## Local Unsigned Build

```bash
./scripts/release_local.sh
```

Expected artifacts:

- `src-tauri/target.noindex/release/bundle/macos/Token BI.app`
- `src-tauri/target.noindex/release/bundle/dmg/Token BI_<version>_aarch64.dmg`

This build is suitable for local validation. It is not notarized, so macOS Gatekeeper may warn users.

## GitHub Release

GitHub Actions 发布流水线保持停用。正式版本由本地完成测试、构建和签名校验后，使用 Git 与 GitHub CLI 手动发布。

发布流程：

1. 确认 `CHANGELOG.md`、`package.json`、`package-lock.json`、`src-tauri/Cargo.toml`、`src-tauri/Cargo.lock` 和 `src-tauri/tauri.conf.json` 使用同一版本号。
2. 在本地执行完整测试并运行 `npm run app:build`。
3. 校验 App 深度签名、DMG 挂载结果，并生成 DMG 的 SHA-256 校验文件。
4. 提交并推送 `main`，创建并推送版本标签。
5. 使用 `gh release create` 上传 DMG 与 SHA-256 校验文件，并使用 `CHANGELOG.md` 对应章节撰写更新说明。

Current release artifacts are unsigned and not notarized. Treat the GitHub Release as the official project download package, while still documenting the macOS Gatekeeper warning until Developer ID signing and notarization are in place.

## Signed Build Prerequisites

Prepare these outside the repository:

- Apple Developer Program membership
- Developer ID Application certificate
- App-specific password or App Store Connect API key for notarization
- Tauri updater private key stored outside git

Never commit certificates, passwords, API keys, updater private keys, or notarization credentials.

## Signing And Notarization Environment

Use local shell environment variables or a private `.env` file excluded from git:

```bash
export APPLE_SIGNING_IDENTITY="Developer ID Application: Example (TEAMID)"
export APPLE_ID="name@example.com"
export APPLE_PASSWORD="app-specific-password"
export APPLE_TEAM_ID="TEAMID"
export TOKEN_BI_UPDATER_PUBKEY="updater-public-key"
```

Then run:

```bash
npm run app:release:local
```

## GitHub Releases Checklist

Before uploading:

- `./.venv/bin/pytest -q` passes
- `./.venv/bin/python -m compileall app scripts tests` passes
- `npm run app:build` passes
- The packaged App opens the control panel
- The packaged App can start and stop the main service, including fallback from `8787` to the next available port
- The account button switches between `登录账号` and `退出账号`
- The service button switches between `开启服务` and `关闭服务`
- The completed first-run guide collapses into a full-width compact card and can be reopened
- The QR card only appears after clicking `扫码连接副屏` and can be closed
- The dashboard `同步额度` button triggers a fresh usage refresh
- The dashboard supports weekly-only usage when Codex analytics no longer returns the 5h/session quota
- The iPhone 5s / iOS Safari dashboard keeps large quota numbers and clear `left` spacing
- The DMG can be mounted and the App can be copied to `/Applications`
- Release notes summarize user-visible changes and known limitations

GitHub Release artifacts should include:

- `Token BI_<version>_aarch64.dmg`
- `Token BI_<version>_aarch64.dmg.sha256`
- updater signature and `latest.json` only when a Tauri updater private key is configured

## Updater Manifest

The updater endpoint is:

```text
https://github.com/gbs00/Token_BI/releases/latest/download/latest.json
```

`latest.json` must match the Tauri updater schema and reference the uploaded DMG URL and signature.

## Push Policy

Only recommend pushing to GitHub after all release checks pass and a concise commit/release summary is ready. Wait for explicit confirmation before running any `git push` or release upload command.
