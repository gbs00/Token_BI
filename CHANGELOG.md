# Token BI 版本记录

本文记录 Token BI 从需求探索到可运行 MVP 的关键版本变化。版本号用于产品与架构沟通，不强绑定发布包。

## v0.8.1 - 本地安装与副屏验收

日期：2026-04-25

验收结果：

- 已通过本地 DMG 将 `Token BI.app` 安装到 Mac。
- 已验证从安装后的 App 启动控制台，而不是依赖 Codex 或手动脚本进入控制台。
- 已验证控制台可启动本地看板服务，并可连接副屏设备访问看板。
- 已确认当前源码项目地址统一为 `/Users/gbs00/我的文件夹/Projects/Token_BI`。
- 已确认 `.config/superpowers/worktrees/Token_BI` 仅是开发阶段临时 worktree，后续应在合并与推送后清理。

发布状态：

- 当前 GitHub 推送目标为 `git@github.com:gbs00/Token_BI.git`。
- 当前 DMG 仍为 unsigned local build；可用于本人本机验收，不建议直接作为公开分发包。
- 下一阶段面向更多用户分发前，仍需完成 Developer ID 签名、notarization、release manifest 和更新链路验证。

## v0.8.0 - Mac App 产品化基础

日期：2026-04-24

定位变化：

- `Token BI.app` 从项目目录型原型升级为可生成 DMG 的自包含 App 基础形态。
- Python 后端被打包为 Tauri sidecar，不再要求用户理解 `.venv`、脚本或项目目录结构。
- 默认用户数据目录迁移为 `~/Library/Application Support/Token BI/`。

功能变化：

- 新增 `token-bi-backend` sidecar CLI，支持 `control-panel`、`main-server`、`migrate`、`health`。
- Tauri App 启动时直接拉起 sidecar 控制台，关闭时停止主服务和 Token BI 管理的 Chrome worker。
- 新增 PyInstaller sidecar 构建脚本和本地 release 检查脚本。
- 新增 DMG 构建目标与 GitHub Releases updater 预留配置。

体验变化：

- 控制台新增本机隐私说明、数据目录提示、Chrome 检测提示和运行模式提示。
- 打包后的 sidecar 已验证可启动控制台、启动主服务、返回 dashboard，并在 shutdown 后释放端口。

分发边界：

- 当前 DMG 仍为本地 unsigned build；正式给更多用户使用前仍需 Developer ID 签名、notarization 和正式 GitHub Release manifest。

## v0.7.1 - 扫码自联副屏入口

日期：2026-04-24

功能变化：

- 控制台新增 `扫码连接副屏` 按钮。
- 点击后展示固定 `.local` 看板入口二维码，副屏设备扫码即可打开 `http://<MacLocalName>.local:8787/dashboard`。
- 同时展示局域网 IP 备用二维码，解决部分设备或路由器不支持 `.local` 解析的问题。
- 新增本地控制台接口 `GET /api/qrcode?kind=fixed|lan|local`，由 Mac 本地生成 SVG 二维码，不依赖外部服务。

体验边界：

- 扫码只能打开看板地址，不能跨浏览器强制指定“默认浏览器”。
- 副屏设备仍需和 Mac 在同一 Wi-Fi / 同一局域网。
- Token BI 主服务未启动时二维码仍可复制和展示，但副屏设备打开会无法连接。

## v0.7.0 - Token BI.app 原型

日期：2026-04-23

定位变化：

- 新增 `Token BI.app` 作为 Mac 端推荐入口。
- 用户可双击 App 打开内嵌控制台，不再需要手动打开脚本或记住 `127.0.0.1:8790`。
- App 是 Token BI 的本地总开关：退出 App 即释放本项目运行资源。

功能变化：

- 新增 Tauri 2 壳层工程。
- 新增 `scripts/start_control_panel.sh`，用于启动控制台但不打开系统浏览器。
- 新增 `scripts/stop_control_panel.sh`，用于停止控制台服务。
- 新增 `scripts/stop_app_services.sh`，用于 App 退出时停止控制台、停止 `8787` 主服务，并关闭 Token BI 管理的 Chrome worker。
- 保留 `scripts/open_control_panel.command` 作为非 App 备用入口。

视觉变化：

- 根据设计稿重绘 `Token BI.app` 图标，采用深蓝玻璃底、机器人面板、额度条和绿色状态灯。
- 新增 macOS `icon.icns`，确保 App bundle 使用自定义图标。
- 控制台页面升级为桌面 App 风格：顶部标题、服务/账号双状态卡、按钮组、入口列表、日志面板和底部状态栏。
- 控制台入口列表新增复制与打开操作。
- 控制台新增 `清空日志` 操作。

分发判断：

- 当前 `Token BI.app` 是项目目录型原型，依赖项目内 `.venv`、`scripts`、`app`、`config` 与 `runtime`。
- 可生成 `.dmg` 并上传 GitHub Releases 作为开发预览版，但普通用户开箱即用还需要进一步把后端、Python runtime、脚本和用户数据目录迁入 App bundle / `~/Library/Application Support/Token BI/`。
- 正式分发建议后续补充 Apple Developer ID 签名与 notarization。

验收结果：

- 已成功构建 `Token BI.app`。
- 已验证 App 打开后可拉起控制台。
- 已验证通过控制台启动 `8787` 主服务后，退出 App 会停止 `8790` 控制台和 `8787` 主服务。
- 已验证 `npm run app:build` 成功生成包含自定义图标的 App bundle。

## v0.6.0 - 局域网副屏设备版本

日期：2026-04-23

定位调整：

- 产品定位从 `iPhone 5s 专用看板` 升级为 `任意同局域网副屏设备的 Codex Usage 看板`。
- 支持范围扩展为 iPhone、Android 手机、小米手机、平板、旧手机、旧电脑、部分电子墨水屏等可访问局域网 Web 页面的设备。
- `iPhone 5s 横屏` 保留为首个重点视觉适配基准。

功能变化：

- Mac 本地控制台新增 `添加账号`。
- `添加账号` 会优先复用已有可读取 usage 的登录窗口；不可复用时才新建待登录账号和独立 Chrome 窗口。
- 登录后通过 `刷新状态` 触发 usage 校验、账号识别与脱敏写入。
- 控制台可启动、停止、打开看板、刷新状态。

体验变化：

- 看板固定入口统一为 `.local` 地址，减少局域网 IP 变化带来的访问失效。
- 副屏页面采用后台 API 刷新，不再每 3 分钟整页 reload。
- 服务短暂重启时保留旧内容并自动重试。
- 百分比数字放大，并按剩余额度划分 4 档颜色。

## v0.5.0 - Mac 本地控制台版本

日期：2026-04-23

功能变化：

- 新增 `scripts/open_control_panel.command`，用户可双击打开本地控制台。
- 新增 `scripts/start_server.sh` 与 `scripts/stop_server.sh`。
- 新增 `scripts/control_panel.py`，控制台默认运行在 `127.0.0.1:8790`。
- 主看板服务默认运行在 `0.0.0.0:8787`，供局域网设备访问。

架构变化：

- 服务启动时尝试恢复或拉起 `active` 账号的 browser worker。
- 服务关闭时不主动杀掉已登录 Chrome worker。
- 根路由固定跳转 `/dashboard`，避免手机入口依赖 `account_id`。

## v0.4.0 - CDP 真实账号抓取版本

日期：2026-04-22

功能变化：

- 将主抓取方案切换为 `普通 Chrome/Edge 窗口 + CDP attach`。
- 避免 Playwright 直启浏览器导致的 Cloudflare 真人验证和自动化标记问题。
- 每次抓取前强制进入 `Codex analytics#usage` 并显式 reload，避免读取旧页面数据。
- 已验证可读取真实账号 usage：`5h Session`、`Weekly`、重置时间。

## v0.3.0 - 长驻浏览器 worker 版本

日期：2026-04-22

架构变化：

- 从“关闭浏览器后复用 profile”调整为“长驻浏览器 worker”。
- 每个账号拥有独立 worker 与独立 context 目录。
- 后端通过 worker 获取 usage，而不是依赖手机端登录。

经验结论：

- Playwright 持久化 profile 后离线复用不稳定，不适合作为 MVP 主方案。
- 登录态应尽量保留在 Mac 侧活会话中。

## v0.2.0 - 无历史存储 MVP 版本

日期：2026-04-21

产品变化：

- 明确不保存 usage 历史。
- 取消 7 日趋势、skills 历史统计和最近 session 列表。
- MVP 聚焦当前额度、重置时间、更新时间、Usage 外链。

数据策略：

- 不落库 usage 历史。
- 只保存最小账号元信息与本地会话目录。
- 允许短时内存缓存。

## v0.1.0 - 初始方案版本

日期：2026-04-21

初始目标：

- 将旧 iPhone 作为 Mac 的 Codex 额度副屏。
- 支持多账号切换查看。
- 每 3 分钟刷新。
- UI 参考 Codex usage 页面与用户提供的多账号样式图。

初始判断：

- 采用 `Mac 本地采集 + H5 看板`，不做原生 iOS App。
- iPhone 5s 作为首个视觉和性能约束基准。
