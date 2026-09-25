# Token BI 版本记录

本文记录 Token BI 从需求探索到可运行 MVP 的关键版本变化。版本号用于产品与架构沟通，不强绑定发布包。

## v1.2.6 - 原生网页登录与动态额度图标

日期：2026-09-25。用户授权完成本地验证后正式发布；本机安装、自动化验证及正式 WKWebView 组件真人登录验收已完成。已于 20:34:27（北京时间）正式发布并设为 GitHub 最新版，[发布回执](docs/releases/v1.2.6-release.md)。

- 以原生 WKWebView 替换生产 Playwright/Chrome 登录兜底，保留 OAuth > CLI RPC > Web 优先级。网页组件延迟创建，通过匿名管道返回白名单额度数据；不向 Python、日志或副屏导出 Token/Cookie。
- 同账号验证、401 单次令牌重取、限流冷却、断网缓存和唤醒调度；退出只解除 Token BI 接入，保留 Codex/CLI/网页登录状态，拒绝迟到结果和后台自动恢复授权。
- 菜单栏内环随剩余额度同步：5h 优先，缺失时采用周额度，100% 满环、0% 空环，未知状态单独表示。
- 删除生产 Playwright、CDP worker 和旧网页登录脚本；测试依赖分离，构建校验阻止 Node/Playwright 回流。
- 最低 macOS 统一为 11，继续仅提供 Apple Silicon 包；旧网页配置不自动迁移，新网页登录需手动完成一次。
- 共享一套 Python 运行库、裁剪发布符号表并排除无用命令行依赖：首轮 1.2.6 App 54.74 MB → 40.14 MB，DMG 22.99 MB → 17.83 MB；两个服务仍独立运行。新增单运行库门禁与旧目录清理的更新安装验证，详见[精简验证记录](docs/releases/v1.2.6-shared-runtime.md)。随后按用户要求替换本机，账号保留、真实 OAuth、额度面板、看板及二维码检查通过；正式发布复用同一套制品。
- [更新说明](docs/RELEASE_NOTES_v1.2.6.md)、[接入说明](docs/TECH_WKWEBVIEW_PRODUCTION.md)、[首轮本地验证与性能基线](docs/releases/v1.2.6-verification.md)。服务就绪时间差异较小，不宣称整体启动显著提速。
- 发布前补齐正式组件的真人登录与自动收起、同账号隐藏读取、连续读取和进程重启恢复；原始验收数据只保留本机，不上传账号信息、Cookie 或 Token。

## v1.2.5 - macOS 菜单栏单色图标

日期：2026-09-24。用户确认图标迭代后授权正式发布，包含菜单栏图标、相关验证和版本元数据更新。

- 菜单栏从彩色应用图标切换为独立单色双环模板，由 AppKit 处理着色；应用包、面板品牌图标及非 macOS 平台原图标保持不变。
- 按本地反馈加粗描边并整体等比例放大约 8%，保留 18pt 菜单栏占位；缺口逆时针旋转至左上方，与原应用图标方向一致。最终有效描边约 1.5pt，36px Retina 模板仅 1,644 字节。
- 保留 macOS 27 左键额度面板、右键快捷菜单和失焦收起逻辑；额度、存储重置、扫码、副屏及更新流程不变，无新增依赖或账号迁移。
- 增加模板尺寸、单色、透明边界和中心检查；设计源图和离屏对比不进入生产安装包。
- 发布前 Python/浏览器 425 项、JavaScript 13 项、Rust 20 项及真实签名归档 1 项通过；格式、Clippy、依赖、打包服务、App/DMG 签名与只读挂载通过。App 为 184,506,082 字节，DMG 为 62,854,710 字节。
- 升级继续沿用原 Updater 签名密钥，提供 DMG、更新归档、签名与版本清单；[发布说明](docs/RELEASE_NOTES_v1.2.5.md)及[图标设计记录](docs/design-previews/menubar-template.md)。
- 已[正式发布](https://github.com/gbs00/Token_BI/releases/tag/v1.2.5)并通过本机应用内 1.2.4 → 1.2.5 下载、签名校验、安装与自动重启验证；[发布回执](docs/releases/v1.2.5-verification.md)。

## v1.2.4 - 存储重置与包体精简

日期：2026-09-21。用户确认本地验收后授权发布，包含此前两轮未发布的存储重置与工程精简改动；不改写旧版本 Release。

- 菜单栏新增“存储重置”，标题与无障碍名称统一；在额度与扫码按钮之间只显示各次到期倒计时，不重复显示总次数，保留 311px 紧凑布局。
- 沿用 OAuth 优先；同一登录态读取重置明细，最多等待 2 秒。明细失败保留主额度与已知次数，异常类型字段不会中断正常额度解析。CLI 只解析既有响应，不额外拉起进程，不提供兑换或消耗重置的操作。
- 区分零次、未返回字段和明细不全；过期条目本地消失，缓存、账号切换和退出保持隔离。
- macOS 运行库保留 framework 符号链接，去除重复副本；增加链接完整性、退役资源和 195MB 包体预算检查。
- 删除旧 HTTP 控制台、专属接口、打开脚本与无调用的会话辅助函数；清理工具默认预览，显式执行，保留最新安装备份与有效账号数据，不随 App 自动清理。
- Playwright 网页登录兜底保持不变，CDP 评估选型与重构明确放入后续版本。
- 发布前全量回归通过：Python/浏览器 425 项、JS 13 项、Rust 19 项与真实签名更新归档 1 项；真实 OAuth 只读校验、打包服务启停、App/DMG 签名及挂载通过。App 实测 188,708,434 字节，DMG 63,015,817 字节；不自动覆盖本机安装。
- [发布说明](docs/RELEASE_NOTES_v1.2.4.md)、[存储重置实现与历史验收](docs/TECH_RESET_CREDITS.md)、[包体与工作区精简](docs/MAINTENANCE_2026-09-21.md)。
- 已于 2026-09-21 00:32:37（北京时间）[正式发布](https://github.com/gbs00/Token_BI/releases/tag/v1.2.4)，五个附件摘要与公开更新清单均已核验；详见 [发布回执](docs/releases/v1.2.4-verification.md)。

## v1.2.3 - 代码审计与稳定性修复

日期：2026-09-19。用户已授权正式发布 v1.2.3，源码、安装包和应用内更新制品成套更新。

- 修复审计的 7 项问题：更新前后台停止确认、mock 预览隔离、OAuth 账号切换缓存隔离、GUI 环境 CLI 定位、回环通信绕过代理、Web 兜底错误归因、失联主服务安全重试。
- 删除无调用方的旧 mock/独立浏览器抓取路径与账号种子脚本；复用已有示例服务器，不新增依赖、不改变正常 OAuth > CLI > Web 优先级。
- 新增故障注入与进程恢复回归；实现、验证范围与兼容边界见 [审计修复纪要](docs/REVIEW_FIXES_2026-09-19.md)。
- 发布前 Python/浏览器 394 项、Rust 19 项、JS 9 项及额外签名归档安装测试通过；Clippy、格式、依赖检查、完整构建、App/DMG 深度签名和打包服务停止握手通过。真实运行版本跨版本重启与副屏真机仍需独立验收。
- 沿用原 Updater 密钥，无账号数据迁移。发布不会自动覆盖本机安装；安装包及应用内更新说明见 [v1.2.3 发布说明](docs/RELEASE_NOTES_v1.2.3.md)。
- 已于 2026-09-19 15:24（北京时间）[正式发布](https://github.com/gbs00/Token_BI/releases/tag/v1.2.3)，5 个附件摘要与公开更新清单均已核验；源码提交、校验值和验收边界见 [发布回执](docs/releases/v1.2.3-verification.md)。

## v1.2.2 - macOS 27 菜单栏点击兼容

日期：2026-09-16。本机安装的 1.2.1 出现左键只弹出快捷菜单、不能直接展开额度面板的问题。

- macOS 下取消常驻绑定图标菜单，改为收到右键按下事件后显式弹出，避免系统吞掉左键回调；左键展开/收起与失焦隐藏规则保持不变。
- 菜单关闭后清除图标高亮，保留查看额度、扫码和退出入口；不改账号、额度、副屏与更新逻辑，不新增依赖。
- 发布前以本地 1.2.1 兼容包覆盖测试，保留旧包与账号数据；用户已确认「左键面板、右键菜单均正常」。
- 根因、上游依据、安装校验值与验收清单见 [菜单栏技术纪要](docs/TECH_MENUBAR.md#macos-27-菜单栏点击兼容2026-09-16)。
- 用户验收后授权发布 v1.2.2，统一桌面、Python 与 API 版本，提供沿用原密钥的 Updater 签名包。Python 360 项、JS 9 项、Rust 17 项及额外签名归档安装测试通过；Clippy、格式、依赖、App/DMG 与打包服务校验通过。升级说明及包体校验值见 [v1.2.2 发布说明](docs/RELEASE_NOTES_v1.2.2.md)。

## v1.2.1 - 首次引导与应用内更新

日期：2026-09-14。依据用户验收通过的 HTML 原型实施。

- 首次打开显示菜单栏轻提示，确认或打开额度面板后持久化完成状态；不等待账号或后端网络。
- 设置接入 Tauri 官方 Updater，提供检查、说明、下载、校验、稍后及确认后安装重启。后台非阻塞检查，待更新时显示红点。
- 更新状态归 Rust 管理，面板隐藏不会取消任务；安装时阻止重复操作与普通退出，更新失败不误报成功。
- 完全删除固定面板状态、IPC、开关及图钉；原生窗口失焦即隐藏。
- 清理未使用的 JS API 依赖；生产资源精确白名单；打包排除未使用的 uvloop/watchfiles，保留浏览器兜底。
- 增加签名归档、latest.json、SHA256SUMS 的制备与隔离安装验证。现有 1.2.0 用户需手动安装一次，后续完整 Release 才能被客户端检测。
- [发布说明](docs/RELEASE_NOTES_v1.2.1.md)、[技术纪要与验收边界](docs/TECH_v1.2.1.md)、[迭代需求](docs/PRD_v1.2.1.md)。

## v1.2.0 - 菜单栏常驻与横屏自适应看板

日期：2026-09-13。发布范围包含下方三轮原未发布改动；历史安装与测试记录保留其当时状态。

- Mac 端改为 311 × 600 逻辑点菜单栏面板，局域网服务自动启动；保留账号、额度、重置时间、登录/退出和扫码连接副屏。
- 修复首次展开尺寸、原生圆角及额度数字排版；二维码默认 LAN，支持固定入口及链接复制。
- Web 看板按可见高度自适应，横屏优先、竖屏兼容，单/双额度不补造数据；保留旧 Safari 回退路径和用户缩放。
- 发布前复查修正：启动不再同步探测浏览器会话；手动刷新统一调用当前账号协调器，移除历史账号遍历和重复包装；失联保留同账号旧额度，退出不回填；首次菜单栏扫码请求不会因页面加载丢失。
- 打包仅包含正式桌面资源；统一 Python/API/RPC 与桌面版本校验，发布脚本增加 Rust、JS、浏览器依赖和产物验证。
- 完整回归与产物验证见 [1.2.0 发布说明](docs/RELEASE_NOTES_v1.2.0.md)。Apple Silicon DMG 使用 ad hoc 签名，未公证，无自动更新；真机旧 Safari、物理跨屏和长期睡眠唤醒仍是验收边界。

### 2026-09-13 实施记录：横屏优先的自适应看板

日期：2026-09-13。实现并开放独立预览，等待多设备验收；未打包、未覆盖本地 App、未发布。

- 移除小横屏特例及固定卡片最小高度，以浏览器可见高度分配空间；横屏双额度左右等宽，竖屏上下排列，单额度居中。
- 圆环根据卡片剩余空间保持正圆；数字使用固定字级，重置时间保持 14px。自动响应旋转、地址栏变化、字体及额度数量变化，不额外请求后端。
- 兼容无 VisualViewport / ResizeObserver 的回退路径，保留用户缩放；空间不足或长异常说明时允许滚动，不隐藏内容。普通浏览器同样预留安全区域。
- 58 项 Chromium/WebKit 布局行为测试通过，覆盖 12 组视口、单/双额度、动态变化、数字内圈边界和安全区留白；真机 Safari 仍待验收。
- 最终完整 Python 回归 305 项、菜单栏 JS 7 项通过，JS 语法及差异检查通过；未修改 Rust，也未打包。
- 沿用现有额度取值、颜色阶梯、SVG 周长、重置和同步逻辑；静态资源版本更新，新增不读取真实账号的示例预览服务。
- 实施、测试边界和预览方式见 [技术纪要](docs/TECH_DASHBOARD_RESPONSIVE.md)。

### 2026-09-12 实施记录：菜单栏常驻版「静谧列表」

日期：2026-09-12。用户确认方案 1；已按用户授权覆盖本地安装，等待实机验收，未推送或发布，版本暂不递增。

- App 改为菜单栏图标与紧凑弹层；LAN 服务自动启动，隐藏面板不停止服务，显式退出才清理本实例拥有的进程。
- 展示账号、有效额度窗口、统一颜色阶梯、重置剩余时间与同步状态，保留登录/退出、刷新及扫码入口。
- QR 默认局域网地址，可切换固定入口、复制、打开、固定面板；二维码与地址同次解析，缺失入口不报成功。
- 沿用 OAuth > CLI > Web 优先级、缓存及现有 Web 看板；状态读取不新增采集请求。新增显式退出、配对和受限 IPC，保留管理权限边界。
- 补充启停互斥锁、TLS 初始化、单窗口/阈值/隐藏轮询/账号退出/扫码及权限回归。Python 229 项、JS 7 项、Rust 7 项通过，独立 debug App 验证 WebView 与 IPC。
- 详情及待验收项见 [技术纪要](docs/TECH_MENUBAR.md) 和 [设计核验](design-qa.md)。旧大控制台仅保留开发兼容入口，App 不再导航到该页面。

本地试用安装（2026-09-12）：完整重建 shell、control 与 backend，Python 229 项、JS 7 项、Rust 7 项再次通过；构建和安装后深度签名检查、DMG 校验均通过。已替换 `/Applications/Token BI.app`，保留账号和运行数据，旧版备份为 `dist/Token BI-v1.1.3-before-menubar-20260912-142152.noindex`。新 App 自动启动后台，真实 OAuth 返回 `ready`，菜单栏显示官方返回的单一周额度，未补充不存在的窗口；扫码页展示正确的局域网二维码。本机回环、LAN IP 与 `.local` 看板均返回 200，其他设备的可达性仍待用户验证。版本号保持 1.1.3，本地测试包不等同于 GitHub 的 v1.1.3 Release；详细校验值见技术纪要。

后续验收修复（2026-09-12）：修复菜单栏首次展开被压窄与圆角露出矩形底色。macOS 窗口改用实际状态栏所属屏幕的逻辑坐标，一次设置位置和尺寸；公开 AppKit/QuartzCore 裁切原生内容层，未启用私有 WebKit API。15 项桌面行为、11 项 Rust、7 项 JS 测试和 Clippy 通过；完整重建并覆盖本地，旧包备份为 `dist/Token BI-before-window-fix-20260912-144432.noindex`。原生展开/重新展开/扫码页检查、收起后服务和真实 OAuth 检查通过；跨屏实际操作仍待用户验收。详见 [技术纪要](docs/TECH_MENUBAR.md)。

紧凑布局调整（2026-09-12）：按用户要求将弹层改为 311 × 600 逻辑尺寸，同步收紧间距、按钮和底栏，保留重置时间字号、跨屏定位与原生圆角；二维码调整为 200 × 200px。单/双额度及两种扫码入口均通过布局检查，19 项桌面行为、11 项 Rust、7 项 JS 测试通过。完整重建并覆盖本地 App，原生额度页/扫码页及真实 OAuth 检查通过，本机 LAN 看板返回 200；旧包备份为 `dist/Token BI-before-compact-311-20260912-150455.noindex`。账号与后台逻辑不变，未发布；安装校验值见 [技术纪要](docs/TECH_MENUBAR.md)。

额度数字排版（2026-09-12）：按验收反馈拆分数值、百分号与“剩余”的字号和字重，统一基线并弱化说明文字，避免 `100%` 整段粗大。311px 窗宽、实际额度、进度条颜色/比例及重置时间不变；27 项桌面行为与 7 项 JS 测试通过，覆盖 0/9/99/100 和 1×/2× 显示比例。已完整重建并覆盖本地 App，原生数字样式与后台健康检查通过；旧包备份为 `dist/Token BI-before-quota-typography-20260912-162112.noindex`，未推送或发布。

### 2026-09-05 实施记录：控制台轮询与冗余代码精简

日期：2026-09-05

- 正常控制台轮询仅请求一次 `runtime-status`，移除额外诊断请求及无页面消费的 `guide`、`chrome_available`、`diagnostics`、`data_source_status` 字段；主服务诊断 API 仍保留供排障使用。
- 删除随上述旧数据路径存在的四个私有函数，以及全库无调用方的 `AccountService.first_account()` 别名包装器；保留账号提交、超时和进程身份校验边界。
- 进程存活检查复用已有 psutil，不再每次启动 `ps` 子进程；保留子进程回收并拒绝 0、负数等无效 PID。
- 日志摘要仅读取末尾最多 64 KiB、显示最近 20 行；超长日志行可能被截断，原日志文件不变。避免轮询耗时、内存占用随完整日志大小增长。
- `open_control_panel.sh` 复用唯一启动脚本，启动失败时不打开网页；合并重复 CLI 参数测试，同时补齐默认参数、轮询请求次数、日志读取上限、PID 和脚本失败路径测试。
- 隔离日志基准：16,200,000 字节合成日志，7 次采样中位数，旧算法 19.116 ms，新算法 0.076 ms；输出一致。该数值仅代表本机日志函数，不代表端到端 UI 延迟或 App 冷启动改善。
- 本地完整回归 219 项通过（包含 Chromium 行为测试），Bash 语法与差异检查通过；没有删减账号竞态、超时、接口权限等关键回归。

迁移：无数据迁移；控制台与后端应成套更新，内部状态接口删除上述旧字段。`Design/` 未变动。Serena、Sequential Thinking 与 Superpowers 不可用，使用本地引用检索、AST 候选分析及隔离测试留痕。

本地试用安装（2026-09-05，用户授权）：219 项回归再次通过，构建及安装后深度签名检查通过；已替换 `/Applications/Token BI.app`，版本号仍为 1.1.3，但包含本节未发布优化。控制台旧状态字段确认已移除，主服务启动和真实 OAuth 同步返回 ready。账号数据保留，旧版备份为 `dist/Token BI-v1.1.3-before-quality.noindex`；未推送 GitHub 或更新 Release，等待用户长期试用反馈。

本地控制台二进制 SHA-256：`fc8bff10ab6df872d2e62080947a837ee1e9cc320f13bac7c96b230cf215bf57`；本地测试 DMG SHA-256：`066a8ca3d735377681a63032f23e6351c0f073281a040c4637d2901a20f0cd59`，与下方正式发布包不同。

## v1.1.3 - 账号一致性、同步恢复与局域网稳定性

日期：2026-09-05

发布范围：包含 2026-08-10 局域网与单实例修复，以及 2026-09-05 评审问题 1–6 修复。支持 macOS Apple Silicon；DMG 使用 ad hoc 签名，未完成 Apple Developer ID 签名或公证，不提供自动更新签名。

### 局域网入口与单实例

- 确认 `v1.1.2` 主服务持续监听 `0.0.0.0`，本机通过当前 LAN IP 与 `.local` 地址均返回 `200`；当前副屏失败请求没有到达 Token BI，根因范围收敛到网络切换后的旧地址、mDNS 或 Wi-Fi 设备互访限制。
- iPhone 实机证明局域网 IPv4 入口可用、`.local` 固定入口不可用；进一步确认 mDNS 同时公布 IPv4 / IPv6，而主服务仅监听 IPv4，导致副屏优先连接 IPv6 时被拒绝。
- 主服务改为使用预绑定 IPv6 socket 并关闭 `IPV6_V6ONLY`，同一端口同时接收 IPv4 与 IPv6；系统不支持 IPv6 时回退到原 IPv4 启动链路。
- 局域网地址改为根据系统默认路由接口获取，并保留 `en0` / `en1` 回退；地址缓存缩短为 5 秒，手动刷新和端口变化会立即失效旧缓存。
- macOS App 增加 `NSLocalNetworkUsageDescription`，明确说明副屏看板所需的本地网络用途。
- 引入 Tauri 官方 single-instance 插件；从其他路径重复打开 Token BI 时只聚焦现有窗口，不再启动第二个控制台生命周期。
- 只有实际启动 control sidecar 的 App 实例才执行退出清理，避免非所有者窗口关闭共享主服务。
- Tauri 构建目录迁移到 `src-tauri/target.noindex`，防止 Spotlight 将仓库内构建包识别为第二个正式应用。

### 2026-09-05 - 评审问题 1–6 修复

本轮范围：用户确认的账号一致性、同步超时、状态反馈、局域网管理权限、退出语义、进程停止安全。沿用 OAuth > CLI > Web 的单账号读取优先级，不修改用户真实 Codex 凭据，不重新设计 UI。

1. 账号与有效额度一起提交；账号变化且新额度无法解析时不再复用旧指标。内存与磁盘均检查脱敏身份和身份键；CLI 在同一进程内读取并复核账号，避免读取期间切换账号造成错配。
2. 增加 45 秒整体采集上限、并发等待上限、OAuth 整体响应超时、CLI 非阻塞分帧和 Web 请求中止；看板轮询超时后自动恢复，并忽略旧请求迟到的结果。
3. 同步 HTTP 200 不再等于额度同步成功。控制台区分进程、服务健康和额度状态；保留旧数据时明确标注待更新，不宣称副屏已可达。
4. 账号与运维 API 仅允许本机回环访问，包含 IPv4-mapped IPv6；校验管理请求 Host/Origin。局域网仍可读取与手动同步看板，但不能登录、退出、访问 session 路径或触发浏览器最小化。
5. 退出后持久化暂停 Token BI 接入，重启或手动刷新也不会自动重新绑定。用户点击登录账号后优先复用本机 OAuth / CLI，缺少登录态时才打开 Web 登录；在途旧结果不得恢复账号或快照。
6. 使用锁定版本 `psutil==7.2.2` 统一停止服务，验证进程身份及项目路径；移除端口批量终止和浏览器进程模糊匹配。开发脚本统一数据目录，默认不使用已安装 App 的数据与 PID 文件。

追溯与验证：新增账号切换、退出/恢复竞态、悬挂请求、真实管道半行、慢速 HTTP 响应、IPv4/IPv6 管理限制、浏览器反馈和误指向 PID 回归。对应技术约束见 `docs/TECH_ARCHITECTURE_V1.0.0.md` 第 7、9、10 节；行为测试位于 `tests/test_ui_recovery.py` 与各服务测试文件。

本地验证结果（2026-09-05）：

- Python 完整回归：`env TOKEN_BI_APP_DATA_DIR=/tmp/token-bi-fix-regression PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider`，210 passed，22.05 秒；包含 13 项真实 Chromium 页面行为测试。
- Rust/Tauri：在 `src-tauri` 执行 `env CARGO_TARGET_DIR=target.noindex cargo test --locked --offline --lib`，5 passed。
- 看板 JavaScript 语法、六个启停脚本 Bash 语法、`pip check` 及 `git diff --check` 均通过。
- 额外验证账号未变化时保留用户别名；测试使用隔离数据与模拟账号，不写入真实 Codex 凭据。未运行远端流水线，未进行 iPhone/Safari 实机或覆盖率验收。

迁移与发布：无手工迁移，直接替换 App；旧账号文件缺省接入开启，新增状态首次写入补齐。保留应用运行数据及本机 Codex 登录态。用户已授权本地打包、覆盖安装、推送仓库并发布 v1.1.3；远端流水线保持停用。

发布验证（2026-09-05）：

- v1.1.3 版本一致性与完整回归再次通过：Python 210 项（24.66 秒）、Rust 5 项。
- `npm run app:build` 成功生成 App 与 DMG；App 深度签名、DMG 校验、只读挂载和复制后的签名验证通过。
- 从同一 DMG 替换 `/Applications/Token BI.app`，安装版本确认为 1.1.3；旧版保留在忽略目录 `dist/Token BI-v1.1.2-before-v1.1.3.noindex` 以便回滚，不改动运行数据。
- 安装后的控制台启动、主服务停止与重启通过；真实 OAuth 同步返回 `ready`。本机 IPv4、IPv6、局域网 IP、`.local` 的 `/dashboard` 均返回 200，不代表其他设备的网络路径已验收。
- DMG SHA-256：`ad4a818e8e5552c23ceb2f03a729e9750c8175ca718d30707525c60650c0397d`。完整用户更新说明见 `docs/RELEASE_NOTES_v1.1.3.md`。
- GitHub Release 已发布：`https://github.com/gbs00/Token_BI/releases/tag/v1.1.3`。GitHub 将附件文件名中的空格转换为点号，发布用 SHA-256 文件按 `Token.BI_1.1.3_aarch64.dmg` 下载名称生成；代码标签保持对应已验证的构建提交。

已知限制：`.local` 入口仍依赖路由器和副屏支持 Bonjour/mDNS，同名 Wi-Fi 不保证允许设备互访；不支持时使用局域网 IP 入口。底层浏览器驱动完全阻塞时，同步会超时返回且不会堆积采集线程，但可能仍需重启主服务。iPhone/Safari 实机效果需用户验收。

工具说明：本轮 Serena、Sequential Thinking、Superpowers 不可用，使用本地工具与隔离测试，并在现有文档留痕；通过 Context7 查询 psutil 官方进程身份与 PID 复用保护说明。

## v1.1.2 - 副屏同步稳定性修复

日期：2026-08-09

- 新增 Mac 端 `UsageSyncCoordinator`：主服务启动后异步同步，成功后每 180 秒同步一次；副屏每 15 秒只读取本地状态。
- 自动同步、看板手动同步、控制台刷新与多副屏请求使用 single-flight，同一时刻只执行一次上游请求。
- 账号状态从 connector 执行条件中解耦，`pending`、`invalid`、`expired` 账号仍会优先尝试 OAuth 与 CLI RPC，成功后自动恢复为 `active`。
- connector 失败统一为结构化类别；OAuth / CLI RPC 的网络、超时、限流或授权错误不再被 `No live browser` 覆盖。
- 新增单一 `latest_dashboard.json` 成功快照，使用原子替换和当前用户读写权限；重启后立即展示上次数据，不保存 usage 历史、token、cookie、原始窗口、账号明文或浏览器 profile 路径。
- 实现 15/60 秒网络退避、429 至少 20 秒并尊重 `Retry-After`、5xx/超时 2 秒单次重试；失败期间保留最后成功额度。
- `GET /api/v1/dashboard` 改为纯本地读取，`POST /api/v1/dashboard/refresh` 保留为显式强制同步入口；看板倒计时改为后端真实 `next_sync_at`。
- 无数据迁移，直接替换旧的进程内 usage 缓存；退出账号时同步删除最后成功快照。

验证：

- Python 完整回归：137 passed；Rust/Tauri 单元测试：5 passed。
- Python 编译、JavaScript 语法、Rust 格式与 Git 差异检查通过。
- `npm run app:build` 通过，生成 `Token BI.app` 与 `Token BI_1.1.2_aarch64.dmg`。
- App 深度签名、DMG 校验与挂载检查通过；打包后的主服务健康检查返回 `1.1.2`，OAuth 后台同步及本地看板读取通过。
- 本次 Release 由本地构建和验证后手动发布，GitHub Actions 发布流水线保持停用。

当前限制：

- 发布包仅支持 macOS Apple Silicon（arm64），采用 ad hoc 签名且未完成 Apple 公证，首次打开可能出现 Gatekeeper 提示。
- 本版本未配置 Tauri updater 私钥，因此不提供自动更新签名和 `latest.json`，需通过 DMG 手动更新。

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
