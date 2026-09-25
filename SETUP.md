# Token BI 安装与开发

适用于 v1.2.6。macOS 11+，Apple Silicon。普通用户不需要安装 Python、Node、CLI 或 Chrome。

## 安装与入口

1. 从 [GitHub Releases](https://github.com/gbs00/Token_BI/releases) 下载当前 DMG，将 Token BI 拖入“应用程序”。
2. 打开 App，在 Mac 顶部菜单栏寻找双环图标；首次引导会指出入口。左键显示额度，右键显示快捷菜单。
3. 点击“扫码连接副屏”，让闲置设备使用同一局域网。二维码默认使用局域网地址；固定 `.local` 入口依赖网络支持 Bonjour/mDNS。
4. 设置中的“检查更新”可检测新版并手动确认安装。不要从旧开发构建目录启动另一份 App。

当前是 ad hoc 签名，尚未 Developer ID 签名及公证；不要以关闭系统安全保护作为安装步骤。构建目录、备份和下载目录里的旧 App 可能产生重复搜索入口，日常从“应用程序”启动。

## 账号读取

- 优先读取已登录的 Codex OAuth，再尝试已登录的 Codex CLI RPC，最后为 WKWebView 网页会话。
- 网页兜底使用 Token BI 自己的登录窗口，不复用或导入 Safari、Chrome、旧 Probe 的 Cookie。升级后首次需要该路径时手动登录一次。
- 同账号才可切换来源。出现账号不一致时，先确认本机 Codex、CLI 与 Token BI 网页中是否为同一用户；不通过昵称或脱敏邮箱合并。
- 登录由用户完成密码、验证码及人工挑战。成功读取额度后登录窗口隐藏，后台不反复弹窗。窗口关闭不清除网站登录状态。
- “退出账号”只解除 Token BI 接入并停止读取、清除本工具的账号绑定与额度展示，不退出 Codex、CLI 或网页。重新点击“登录账号”才恢复接入。
- 不提供存储重置兑换功能，仅展示官方返回的逐项到期时间。

后台正常同步每 180 秒一次，副屏每 15 秒读取本地快照。手动刷新与自动刷新合并在同一个在途任务中。断网、超时或限流保留上次成功数据和时间，恢复后正常同步，不清零、不凭到期推算满额。

## 局域网排查

- 同 Wi-Fi 名称不一定允许设备互访：访客网络、AP 隔离、VPN、防火墙或不同子网都可能阻断连接。
- 固定域名失败但 LAN 地址正常时，优先使用 LAN 二维码，检查网络的 mDNS 支持。
- 看板能打开但额度旧，查看同步时间和状态；“接口暂不可用”不同于“无法连接 Mac”。
- Mac 睡眠或退出 App 时不会继续提供服务；唤醒后按既有频率恢复。切换 Wi-Fi 后重新获取二维码。

主看板默认 8787，被占用时选择 8788–8877；以当前二维码中的实际端口为准。管理服务只监听回环，不应从副屏执行账号或更新操作。

## 开发环境

需要 macOS、Xcode 命令行工具、Python、Node 和 Rust。遵循现有锁文件；测试浏览器不随安装包分发。

```sh
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements-dev.txt
npm ci
./.venv/bin/python -m playwright install chromium webkit
./.venv/bin/python scripts/build_web_session.py
npm run app:dev
```

日常 UI 调整可使用 `npm run desktop:preview`。真实账号测试要显式指定场景；隔离预览使用现有 `scripts/start_mock_preview.sh`，不要把 mock 配置写入正式数据目录。

## 测试与打包

```sh
./.venv/bin/python scripts/build_web_session.py
./.venv/bin/python scripts/build_wkwebview_probe.py
TOKEN_BI_NATIVE_WK_TEST=1 ./.venv/bin/python -m pytest -q
npm run desktop:test
cargo test --manifest-path src-tauri/Cargo.toml --target-dir src-tauri/target.noindex --lib
```

原生测试使用隔离本机 HTTP fixture 和专用会话，不操作真实账号。普通 pytest 未启用环境变量时跳过原生测试，不等于完整发布验证。

发布按 [Release Guide](docs/RELEASE.md) 使用原 Updater 私钥，不生成替代密钥。`npm run app:build` 构建原生网页登录 helper、Python 服务及 Tauri App；正式发布使用 `scripts/release_local.sh`。脚本不自动上传、不替换已安装 App。

## 数据与清理

- 正式数据目录：`~/Library/Application Support/Token BI/`。
- `config/accounts.json`：Token BI 账号绑定与接入开关。
- `runtime/cache/latest_dashboard.json`：同账号最后成功快照，无 usage 历史。
- `runtime/web-session.json`：原生 WebKit profile UUID，无 Token/Cookie 副本。网站会话由系统 WebKit 存储维护。
- 不删除用户的 Codex/CLI 授权文件，不在日志或反馈中附带完整账号、Cookie 或 Token。
- `npm run workspace:clean` 只预览工程清理；核对后显式 `-- --apply`。旧 Chrome 会话不随本次升级自动删除。

架构与验证边界见 [WKWebView 接入说明](docs/TECH_WKWEBVIEW_PRODUCTION.md)，前期探针过程见 [可行性记录](docs/TECH_WKWEBVIEW_FEASIBILITY.md)。
