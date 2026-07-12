# Token BI 版本记录

本文记录 Token BI 从需求探索到可运行 MVP 的关键版本变化。版本号用于产品与架构沟通，不强绑定发布包。

## v1.1.1 - 账号链路、启动性能与控制台/看板重构

日期：2026-07-12

数据源与账号：

- 当前版本明确为单 Codex 账号模式，同步优先级固定为 Codex OAuth -> Codex CLI RPC -> Web Session。
- 已存在本机 OAuth 或 CLI 登录态时，不再被历史 `pending` 账号记录阻断；登录成功会复用当前单账号记录，不再累积重复账号。
- OAuth 账号身份优先从 `id_token.email` 读取，再回退到 access token profile；同步成功后会自动纠正历史错误别名。
- 缩紧 Web 页面账号识别规则，仅接受明确的 email 字段，避免把任意网络响应中的 `name` 误当为当前 Codex 账号。
- 控制台与看板改为展示本次真实成功数据源及实际同步时间，不再因 connector 已注册就显示 `OAuth 可用`，也不再用当前时钟伪造“最近同步”。
- 强制刷新失败时保留最近一次可用数据；官方仅返回不可识别窗口时进入明确错误态，不再展示空白的正常看板。
- `config/accounts.json` 改为本机运行数据并移出版本控制，仓库仅保留空的 `config/accounts.example.json`。

启动与退出：

- 本机日志已确认首次启动失败的直接原因：打包后的 control sidecar 使用 `sys.executable` 拉起独立 main server 时复用了 PyInstaller 临时解压环境，父进程退出后子进程报 `No module named 'encodings'`。
- 拉起独立 main server 前设置 `PYINSTALLER_RESET_ENVIRONMENT=1`，并使用主服务专用健康标识校验启动结果。
- Tauri 退出改为等待控制服务返回完整关停结果，仅在优雅退出失败时强制结束 sidecar，避免固定 500ms 后终止导致残留进程。
- PID 操作前校验实际进程命令，拒绝停止已被其他进程复用的过期 PID。

验证：

- Python 完整回归：112 passed。
- Rust/Tauri 单元测试：5 passed。
- PyInstaller sidecar 构建通过，`npx tauri build --bundles app` 通过，生成 `Token BI.app`。
- 受当前执行环境禁止本地 `socket.bind` 影响，4 个端口探测用例需在无沙箱本机环境补跑。
- 在完整本机环境重新执行 `npm run app:build`，App 与 `Token BI_1.0.2_aarch64.dmg` 均封装成功。

启动性能复核（2026-07-11）：

- 用户首次复测时 `/Applications/Token BI.app` 仍是 2026-05-30 旧包，主程序与 sidecar 哈希均与当日构建不同；已完整替换为 2026-07-11 构建。
- 新包首次安装后启动：控制台健康检查 15.383s，窗口可见 15.865s；Tauri 在 12s 时提前进入“启动失败”。
- P0 稳定性修复将 Tauri 控制台健康检查门禁调整为 30s，轮询间隔调整为 200ms；仅修复冷启动误报，不将延长等待当作性能优化。
- 重新安装后的真实首次启动验收：控制台 16.138s 就绪，窗口 16.624s 可见，窗口标题为正常 `Token BI`，未进入错误页。
- 同一 PyInstaller one-file sidecar 独立启动 5 次：6.714–9.393s，平均 7.341s；源码模式启动同一控制台仅 0.135s。
- macOS 统一日志记录 AMFI 对 `token-bi-backend` 的 ad-hoc 签名校验；首次执行的额外延迟与未正式签名、磁盘冷缓存及 one-file 启动成本一致。
- 结论：主要瓶颈是把控制台与完整 FastAPI / Playwright 能力合并为 48MB PyInstaller one-file sidecar，不是账号同步或控制台 HTML 渲染逻辑。

启动架构优化（2026-07-11）：

- Tauri 不再等待 Python 健康检查后才创建窗口；先立即显示与正式控制台一致的本地壳层，再在后台连接轻量控制服务。启动失败也在同一控制台中显示原因，不再切换独立错误页。
- 原单个重型 `token-bi-backend` one-file sidecar 拆分为 Rust 启动器、轻量 `token-bi-control` onedir 运行时和按需启动的 `token-bi-backend` onedir 运行时；用户界面仍是一个控制台，仅拆分进程职责。
- 启动阶段不再预加载 FastAPI、Playwright 与 usage connector 依赖；主服务只在用户开启服务时拉起。
- 修复主服务终止后的子进程回收：不再把已退出的僵尸态进程误判为“无法停止”。
- 打包运行时验证：轻量控制服务首次约 2.54s 就绪，主服务约 0.54s 就绪，完整关闭成功且无残留进程。
- `/Applications` 实际安装验证：新包首次执行窗口 2.885s 可见、控制服务 3.504s 就绪；完全退出后第二次启动窗口 0.056s 可见、控制服务 0.369s 就绪。首次额外时间为新 App 校验与冷缓存成本，日常启动不再承担原 one-file 解包延迟。
- 性能优先的代价是 App 从约 63MB 增长到约 184MB；DMG 从约 53MB 增长到约 61MB。当前决策优先保证长期使用中的启动速度和稳定性。

最终验证：

- Python 完整回归：122 passed。
- Rust/Tauri 单元测试：5 passed。
- `npm run app:build` 通过，生成 `Token BI.app` 与 `Token BI_1.1.1_aarch64.dmg`。
- macOS App 使用 ad hoc 签名保证包内资源完整性，App 深度签名验证与 DMG 镜像校验均通过；当前仍未使用 Apple Developer ID 签名或完成 Apple 公证。
- 本次 Release 由本地构建和验证后手动发布，远端 GitHub Actions 发布流水线保持停用。

控制台与看板 UI 重构（2026-07-12）：

- 以 `docs/design-previews/preview-v110-console.html` 与 `preview-v110-dashboard.html` 为视觉基准，统一暗色/亮色设计变量、文字层级、状态色和操作控件。
- 控制台调整为顶部服务总状态、账号/数据源/端口/同步摘要、快捷操作、服务状态、副屏入口与最近日志的工作台布局。
- 控制台新增真实状态驱动的退出账号确认、登录后刷新、二维码、完整日志与 toast 反馈，保留现有后端 API 契约。
- 控制台 HTML 从 `control_panel.py` 的大型内联字符串拆分到 `scripts/control_panel.html`，并纳入 PyInstaller control onedir 资源。
- Tauri 本地启动壳同步新视觉，保持首屏与完整控制台一致，启动失败仍在同一工作台中显示原因。
- 看板顶部重构为账号、实际数据源、下次同步、最近同步与同步按钮；额度卡增加统一的重置剩余信息行。
- 看板保留 SVG 真实圆周长算法和额度阶梯显色，没有引入旧 iOS Safari 不支持的 `conic-gradient` 或 `aspect-ratio`。
- 响应式实测：320×568 竖屏无横向溢出，568×320 iPhone 5s 横屏的两张额度卡同屏完整展示，页面无横向或纵向滚动。
- 浏览器交互验证覆盖服务启停、副屏二维码、日志弹窗和强制同步；控制台与看板无 console error/warning。

## v1.0.2 - 控制台稳定性、图标与 iPhone 5s 看板兼容修复

日期：2026-05-30

控制台：

- App 启动健康检查从端口探测升级为 `/api/app/health` 标识校验，避免误复用非 Token BI 服务。
- App 启动失败时不再白屏；控制台无法就绪时展示失败原因、端口、数据目录和建议动作。
- 控制台正式界面按 v1.0.2 PRD 调整为顶部服务总状态、摘要卡片、快捷操作、服务状态、副屏入口和最近日志。
- 快捷操作保留 `打开看板`、`扫码连接副屏`、`刷新状态`，账号卡保留 `登录账号` / `退出账号` 状态按钮。
- 未登录时主操作自动切换为 `登录账号`，已登录时主操作恢复为 `打开看板`。

图标：

- 替换 Tauri 正式图标为蓝色 Token 仪表标，去除容易与 macOS 运行指示点混淆的底部小点和细碎横线。
- 重新生成 `icon.png` 与 `icon.icns`，用于 v1.0.2 打包资源。

看板：

- 将 BI 看板环形图从 CSS `conic-gradient` / `aspect-ratio` 实现调整为 SVG stroke 圆环，兼容 iPhone 5s 可用的旧版 iOS Safari。
- 修复旧版 iOS Safari 忽略 SVG `pathLength` 归一化后，92% / 99% 等高额度仍显示为固定短弧的问题；圆环比例改为基于真实圆周长计算。
- 新增 iPhone 5s 横屏短屏断点，压缩顶部账号、数据源、下次同步、同步按钮和双额度卡片尺寸，保证 568×320 视口无横向或纵向溢出。
- 按 `preview-d-emphasis-dashboard.html` 将看板卡片调整为“额度优先”视觉层级，短横屏下圆环和中心百分比显著放大，同时保持重置剩余时间的原有比例和样式。
- 修复周额度卡被固定为黄色的问题，圆环和中心百分比颜色重新按剩余额度阶梯计算，99% / 100% 周额度进入高额度档位。
- 补充看板页面回归测试，锁定 SVG 圆环结构、旧 Safari 兼容样式和动态刷新创建卡片的一致性。

## v1.0.0 - 技术设计收敛与主链路改造

日期：2026-05-23

设计：

- 新增 [docs/TECH_ARCHITECTURE_V1.0.0.md](/Users/gbs00/我的文件夹/Projects/Token_BI/docs/TECH_ARCHITECTURE_V1.0.0.md)，作为 v1.0.0 后续开发技术蓝图。
- 数据源主链路从 Chrome/CDP 抓取调整为 Codex OAuth / Codex CLI RPC 优先，Web Session 兜底。
- 看板展示从固定 `session_*` / `weekly_*` 调整为官方 usage / rate limit 窗口透传。
- 明确敏感数据与日志边界：不落库 usage 历史，不写入 token、cookie、账号明文或官方原始响应。
- 补充本地验证计划和迁移策略：无历史 usage 迁移，直接替换刷新主链路。

实现进展：

- 新增 `CodexOAuthConnector` 与 `CodexCliRpcConnector`，并将默认 connector 顺序调整为 OAuth、CLI RPC、Web Session；本地 snapshot connector 仅作为测试/开发开关使用。
- `CodexCliRpcConnector` 默认通过 `codex app-server --listen stdio://` 完成 `initialize` 后读取 `account/read` 与 `account/rateLimits/read`，避免依赖当前本机缺失的 managed daemon/proxy 安装形态。
- 后端新增官方 usage / rate limit 窗口归一化层，`DashboardPayload.metrics[]` 改为动态窗口列表，不再依赖固定 `session` / `weekly` 业务枚举。
- 看板前端支持成功恢复后动态创建指标卡，未知窗口兜底文案改为中性的 `Usage window`。
- 主服务启动阶段不再默认拉起 Chrome worker，只尝试恢复已有 worker；Web Session 仅在 fallback/login 路径使用。
- 诊断接口补充 OAuth、CLI RPC、Web Session 与最近 connector 降级状态。
- 控制台账号卡新增数据源链路状态，“刷新状态”反馈会展示本次成功使用的数据源与 connector。
- BI 看板端落地夜间模式圆环卡片：顶部保留账号、数据源、下次同步和 `同步额度`，卡片中心唯一展示剩余额度百分比，底部只展示重置剩余时间。
- BI 看板只展示已识别的 `5h 额度` 与 `周额度`；未知窗口、链路、日志、运维状态和多余辅助标签不进入看板。
- 补充 [docs/DASHBOARD_UI_OPTIMIZATION_V1.0.0_NOTES.md](/Users/gbs00/我的文件夹/Projects/Token_BI/docs/DASHBOARD_UI_OPTIMIZATION_V1.0.0_NOTES.md)，记录本轮 UI 决策、技术变更和验证证据。

发布验证：

- `.venv/bin/python -m pytest -q`：89 passed。
- `npm run app:build`：通过，生成 `Token BI_1.0.0_aarch64.dmg`。
- 打包 sidecar 冒烟验证 `/dashboard` 返回 200，并确认新圆环看板、`同步额度`、无进度条、无“官方额度窗口”、无未知窗口展示。

已知限制：

- 当前 DMG 未进行 Apple Developer ID 签名与 notarization，首次安装仍可能出现 macOS Gatekeeper 提示。

## Unreleased - Codex analytics 周额度单卡兼容

日期：2026-04-29

修复：

- Codex 官方 analytics 页面删除 `5h` / `5 小时额度` 后，抓取器不再把缺少 session quota 视为页面结构整体失效。
- `Web Session Connector`、DOM fallback、`/backend-api/wham/usage` JSON 解析和本地 snapshot connector 均支持只返回 `weekly_*` 字段。
- 看板会根据实际返回的指标动态渲染额度卡；当只有周额度时，只显示 `Weekly` / `周额度` 卡片，不再渲染空的 `5h Session` 卡片。
- 当前页面若已处于 `connector_error` 错误态，下一次 `同步额度` 成功后可动态创建额度卡并恢复显示，无需整页刷新。

## v0.9.1 - 跨设备看板与控制台体验修复

日期：2026-04-26

定位变化：

- 在 `v0.9.0` 可信测试版基础上，聚焦真实副屏验收中的 UI、兼容性和启动稳定性问题。
- 本轮继续保持本地优先，不进入正式公开分发；DMG 仍按 prerelease / 测试包语义使用。

控制台变化：

- 控制台按最新设计稿重排为桌面 App 信息面板：顶部服务状态、三张环境说明卡、当前账号、首次启动引导、快捷操作、入口地址与运行日志。
- 首次启动引导完成后自动收缩为与上下内容齐平的通栏小卡片，右侧保留 `查看引导` 操作；点击后可重新展开步骤条。
- `启动 Token BI` / `停止 Token BI` 合并为一个服务主按钮：服务停止时显示 `开启服务`，服务运行时显示 `关闭服务`。
- `扫码连接副屏` 改为点击后弹出二维码卡片；点击右上角 `x`、遮罩或按 `Esc` 可关闭，不再默认常驻展示。
- 控制台继续保留单一账号主按钮：按状态显示 `登录账号` 或 `退出账号`。
- 修复主服务启动失败后 PID 与 runtime 状态残留的问题，避免控制台误以为服务仍在运行。
- 主服务端口检测改为先探测 `127.0.0.1` 连接、再尝试绑定 `0.0.0.0`，减少 `8787` 端口状态误判。

看板变化：

- BI 看板按最新设计稿重构为双额度卡布局，突出 `5 小时额度` 与 `周额度`。
- 看板顶部账号区域不再提供下拉框或多账号切换控件，直接显示当前脱敏账号信息。
- `Refresh` 改为 `同步额度`，语义明确为同步最新 usage 数据与账号信息。
- `同步额度` 直接调用 `POST /api/v1/dashboard/refresh`，绕过短时缓存，尽量读取最新 Codex analytics usage。
- 额度百分比数字进一步放大，并继续按剩余额度梯度改变数字和进度条颜色：`>75%`、`>50 且 <=75%`、`>25 且 <=50%`、`<=25%`。
- 修复 iPhone 5s / iOS Safari 对 `clamp()` 与 flex `gap` 支持不完整导致的字号偏小、`left` 文字贴得过近的问题，增加旧 Safari 可识别的字号与间距 fallback。

浏览器 worker 变化：

- 修复 Token BI 专用 Chrome profile 路径包含空格时，已有 CDP worker 无法被正确识别和复用的问题。
- 该修复主要覆盖 `~/Library/Application Support/Token BI/...` 这类产品化 App 默认数据目录。

验收结果：

- 已补充控制台、看板和 worker 相关回归测试。
- 已通过 Python 测试与编译检查。

## v0.9.0 - 可信测试版体验增强

日期：2026-04-25

定位变化：

- 从“本人可用的本地安装版”推进到“可给新测试用户试用的可信测试版体验”。
- 本轮不进入正式公开分发，不做 Developer ID 签名、公证、Universal DMG 和正式自动更新。

功能变化：

- 控制台账号入口收敛为单一主按钮：无账号、未登录、登录中断或 worker 丢失时显示 `登录账号`；账号可读取 usage 后显示 `退出账号`。
- `登录账号` 会确保主服务运行，创建或复用待登录账号，并打开 Token BI 专用 Chrome 登录窗口。
- `退出账号` 会关闭该账号 worker、删除账号记录、清理内存 usage 缓存，并删除 Token BI 专用 Chrome profile；不影响用户日常 Chrome。
- 主服务优先使用 `8787`，若端口被占用，会自动在 `8788-8877` 内选择第一个可用端口。
- 控制台、二维码、固定入口、局域网入口、本机入口都会使用实际运行端口。
- 新增运行态端口文件 `token_bi_runtime.json`，供控制台、二维码、App shutdown 和排障使用。
- `刷新状态` 或账号校验成功读取 usage 后，会尝试通过 CDP 最小化 Token BI 管理的 Chrome worker，降低对主桌面的打扰。
- 新增首次启动 checklist：检测 Chrome、启动服务、登录账号、刷新 usage、扫码连接副屏；完成后默认折叠。
- 新增诊断与错误文案体系，覆盖 Chrome 缺失、服务未启动、登录态失效、worker 丢失、usage 页面变化和局域网不可达等场景。

接口变化：

- 新增 `POST /api/v1/account-session/login`。
- 新增 `POST /api/v1/account-session/logout`。
- 新增 `POST /api/v1/accounts/{account_id}/minimize-worker`。
- 新增 `GET /api/v1/diagnostics`。
- 控制台新增 `POST /api/account-action`，由当前账号状态决定执行登录或退出。

体验边界：

- Chrome worker 仍采用“登录时可见，登录并成功刷新后自动最小化”的策略，不尝试完全后台隐藏。
- 端口 fallback 只管理 Token BI 记录的主服务进程，避免误杀占用同端口的其他程序。
- Usage 历史仍不落库，仍不保存账号密码。

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
