# Token BI Release Guide

## 发布边界

未经用户明确确认，不提交推送、不创建标签、不上传 Release。本项目使用本地验证后手动发布；GitHub Actions 的旧发布工作流处于停用状态，不应与手动发布同时运行。

当前分发为 Apple Silicon macOS App / DMG，使用 ad hoc 签名，未进行 Developer ID 签名或公证；1.2.1 起提供独立签名的 Tauri 更新归档。菜单栏版不再以旧大控制台作为验收入口。

## 本地构建

安装项目 Python / Node / Rust 依赖，并准备 Chromium、WebKit 测试浏览器：

```sh
./.venv/bin/python -m playwright install chromium webkit
TAURI_SIGNING_PRIVATE_KEY=/path/to/updater.key TAURI_SIGNING_PRIVATE_KEY_PASSWORD= ./scripts/release_local.sh
```

脚本使用临时数据目录，执行 Python、JS、Rust 测试与 Clippy / 格式 / 依赖检查；然后完整构建 control、backend、shell，验证 App 深度签名、当前版本 DMG 和真实签名更新归档。安装测试只替换临时副本，不替换本地安装、不上传。

产物：

- `src-tauri/target.noindex/release/bundle/macos/Token BI.app`
- `src-tauri/target.noindex/release/bundle/dmg/Token BI_<version>_aarch64.dmg`
- `dist/release-v<version>/`：版本化 DMG、app.tar.gz、app.tar.gz.sig、latest.json、SHA256SUMS；上传这个暂存目录的全部文件。

版本保持一致：`app/__init__.py`、`package.json`、`package-lock.json`、`src-tauri/Cargo.toml`、`Cargo.lock`、`tauri.conf.json`。API 和 CLI RPC 共用 Python 版本常量，元数据一致性由测试检查。

## 验收清单

- App 在菜单栏常驻，首次引导、重复打开、失焦收起和显式退出符合预期；无固定开关或图钉。
- 设置可检查更新，有更新时红点持续到安装完成。隐藏不停止下载，签名失败不能安装，安装需用户单独确认。
- 局域网服务自动启动；8787 冲突时选择可用端口，control 只监听回环。
- 账号和额度由同一次缓存状态提供；OAuth 优先，缺失窗口不补 0，失败不伪装同步成功。
- 登录与退出入口有效；退出 Token BI 账号不删除本机 Codex 凭据。
- 默认 LAN 二维码与复制链接一致，固定入口受 mDNS 限制，不将本机可达当作手机验收。
- 菜单栏的 0/99/100%、单/双额度、QR、异常和矮屏均能使用。
- Web 横竖屏、地址栏变化、用户缩放、离线恢复和旧浏览器回退通过；真机未覆盖项明确披露。
- 用成套打包的 control/backend 做隔离健康与网页测试，不能只验证源码服务。
- `verify_bundle.py` 同时检查 Python framework 链接完整且未越出运行库、旧控制台未入包，以及 App 不超过 195MB（十进制、符号链接不重复计入）的体积预算。macOS 运行库使用 `bundle.macOS.files` 保留链接；不要改回逐文件复制的 `bundle.resources`，也不要签名后修改 App。
- DMG 可挂载、包内 App 签名有效。保留用户数据；不要把演示页、凭据、运行日志和备份 App 上传仓库。

## 手动上传

1. 核对当前分支、差异、版本和 CHANGELOG；仅提交本轮确认的源码、测试、文档及相关设计证据。
2. 完成上述构建和验收，发布暂存区由 `scripts/prepare_release.py` 生成；不把 DMG 当作 Updater 归档。
3. 核对 latest.json 的版本、平台、URL、签名内容和所有文件的 SHA-256；保留 Python 依赖快照，方便复现。更新说明修改后重新制备暂存区。
4. 提交并推送主分支，创建并推送 `v<version>` 标签。禁止移动已有标签或覆盖既有正式附件。
5. 使用 `gh release create --draft` 上传完整暂存目录，版本说明来自 `docs/RELEASE_NOTES_v<version>.md`。
6. 回读草稿附件确认完整及校验值，再 `gh release edit v<version> --draft=false --latest` 发布。检查 latest/download/latest.json 可访问且与本地一致；不得提前暴露不完整清单。

## 签名与后续工作

Developer ID 证书、公证凭据和 updater 私钥必须保存在仓库外，私钥权限应为 0600 并安全备份。当前公钥已固化；后续版本必须继续使用同一私钥，不能随意重新生成，否则现有客户端无法校验。私钥不进入客户端或更新说明。

Actions 工作流仍停用。启用前需由发布者配置 `TAURI_SIGNING_PRIVATE_KEY` 和对应密码 Secret，确认 arm64 runner。新流程只创建包含完整资源的草稿，验收后人工发布，避免与手动流程重复。

Apple 签名/公证、Intel/Universal、干净机器安装、真实运行版本 N → N+1 重启及副屏恢复、长期常驻仍需独立验收。详见 [技术纪要](TECH_v1.2.1.md)。

## 本地产物保留

`npm run workspace:clean` 默认预览，核对后执行 `npm run workspace:clean -- --apply`。保留最新两份 App 备份、最近两个版本发布暂存和当前 `target.noindex`；只清理已退役的 `target` 与不再引用、无占用且至少 30 天无修改的开发浏览器配置。清理记录位于 `dist/cleanup-reports`，不随 App 发布。该命令不在用户 App 启动或更新时自动执行，也不删除远端 Release。
