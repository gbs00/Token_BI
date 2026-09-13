# Token BI Release Guide

## 发布边界

未经用户明确确认，不提交推送、不创建标签、不上传 Release。本项目使用本地验证后手动发布；GitHub Actions 的旧发布工作流处于停用状态，不应与手动发布同时运行。

当前分发为 Apple Silicon macOS App / DMG，使用 ad hoc 签名，未进行 Developer ID 签名或公证；不提供签名自动更新。菜单栏版不再以旧大控制台作为验收入口。

## 本地构建

安装项目 Python / Node / Rust 依赖，并准备 Chromium、WebKit 测试浏览器：

```sh
./.venv/bin/python -m playwright install chromium webkit
./scripts/release_local.sh
```

脚本使用临时数据目录，执行 Python、JS、Rust 测试与 Clippy / 格式 / 依赖检查；然后完整构建 control、backend、shell，验证 App 深度签名及当前版本 DMG。不自动安装、不上传。

产物：

- `src-tauri/target.noindex/release/bundle/macos/Token BI.app`
- `src-tauri/target.noindex/release/bundle/dmg/Token BI_<version>_aarch64.dmg`

版本保持一致：`app/__init__.py`、`package.json`、`package-lock.json`、`src-tauri/Cargo.toml`、`Cargo.lock`、`tauri.conf.json`。API 和 CLI RPC 共用 Python 版本常量，元数据一致性由测试检查。

## 验收清单

- App 在菜单栏常驻，首开、重复打开、失焦收起、固定面板和显式退出符合预期。
- 局域网服务自动启动；8787 冲突时选择可用端口，control 只监听回环。
- 账号和额度由同一次缓存状态提供；OAuth 优先，缺失窗口不补 0，失败不伪装同步成功。
- 登录与退出入口有效；退出 Token BI 账号不删除本机 Codex 凭据。
- 默认 LAN 二维码与复制链接一致，固定入口受 mDNS 限制，不将本机可达当作手机验收。
- 菜单栏的 0/99/100%、单/双额度、QR、异常和矮屏均能使用。
- Web 横竖屏、地址栏变化、用户缩放、离线恢复和旧浏览器回退通过；真机未覆盖项明确披露。
- 用成套打包的 control/backend 做隔离健康与网页测试，不能只验证源码服务。
- DMG 可挂载、包内 App 签名有效。保留用户数据；不要把演示页、凭据、运行日志和备份 App 上传仓库。

## 手动上传

1. 核对当前分支、差异、版本和 CHANGELOG；仅提交本轮确认的源码、测试、文档及相关设计证据。
2. 完成上述构建和验收，将 DMG 复制到忽略目录中的发布暂存区；发布文件名使用 `Token.BI_<version>_aarch64.dmg`。
3. 为该文件生成 SHA-256 校验文件；保留 Python 依赖版本快照与对应提交，方便复现。
4. 提交并推送主分支，创建并推送 `v<version>` 标签。禁止移动已有标签或覆盖既有正式附件。
5. 使用 `gh release create` 上传 DMG、校验文件，版本名和说明来自 `docs/RELEASE_NOTES_v<version>.md`。
6. 回读 Release，确认发布状态、标签提交、附件名称、大小及校验值。

## 签名与后续工作

Developer ID 证书、公证凭据和 updater 私钥必须保存在仓库外。当前配置中的 updater 公钥是占位符，菜单栏没有注册自动更新流程，不应发布无效 `latest.json`。

将来启用更新时，需单独实现并验证 Tauri updater 安装归档、签名和 manifest，不将普通 DMG 当作自动更新包。签名、公证、Intel / Universal 支持、干净机器安装与长期常驻测试均应有独立验收记录。
