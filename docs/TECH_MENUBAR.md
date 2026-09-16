# Token BI 菜单栏版实施纪要

首次实施日期：2026-09-12。下方保留各轮试用包记录；当前已纳入 1.2.0 发布范围，最新复查见 [1.2.0 复查](REVIEW_v1.2.0.md)。

## 已确认范围

- 用户选择方案 1「静谧列表」，以菜单栏弹层取代 App 的大控制台窗口。
- 局域网服务随 App 自动启动，不再要求用户点击服务开关。
- 保留 OAuth 优先、CLI 与 Web 登录兜底的单账号逻辑，以及登录/退出、额度、重置剩余时间、刷新和扫码连接副屏。
- 副屏 Web 看板不改版，不引入多账号、历史消费或趋势图。

设计原图：[方案 1](design-previews/menubar-choice-1.png)。视觉核验：[design-qa.md](../design-qa.md)。

## 桌面生命周期

`src-tauri/src/menubar.rs` 管理菜单栏图标、原生窗口及桥接；`menubar/macos.rs` 负责 macOS 逻辑坐标定位与原生圆角；`lib.rs` 保留已有 sidecar 身份校验、健康检查和进程所有权清理。

- `LSUIElement` 与 Accessory 激活策略使 App 常驻菜单栏。单个本地 WebView，311 × 600 逻辑尺寸，依菜单栏图标与显示器工作区定位，限制边界和可用高度。
- 左键切换面板；右键提供查看额度、扫码、退出。失焦收起，固定后保持展开；Escape 返回上一级，首页 Escape 收起。
- CloseRequested 隐藏但不销毁、不停止后台；显式退出才清理本实例启动的进程。
- 异步启动 control sidecar，身份校验通过后调用现有 `/api/start`。启动与停止共享锁，避免自动启动/登录同时创建进程，或启动尚未写入 PID 即退出而遗留服务。退出清理超时 60 秒，覆盖最长 30 秒在途启动；通常就绪后立即停止，极端慢启动期间退出可能等待。
- 启动状态保存在 Rust 中，由页面读取，避免一次性错误事件因页面尚未就绪而丢失。不再导航到 HTTP 大控制台。
- 隐藏时不读取后台额度，仅保留每 2 秒轻量窗口状态查询；可见时每 15 秒读取一次缓存，重新聚焦立即检查。

没有使用私有 NSPanel 接口或透明材质。本轮是 Tauri 原生窗口承载紧凑页面，不宣称与 AppKit 系统弹出菜单完全相同。

## 数据与权限

- `GET /api/v1/runtime-status` 新增 `dashboard`，与 `account`、`usage` 来自同一次 coordinator 缓存读取，沿用公开看板序列化脱敏。`GET /api/status` 直接透传，不额外调用采集器或诊断接口。
- 只呈现返回的有效窗口，缺失窗口不补 0%。阈值沿用 `>75 / >50 / >25 / <=25`，两个窗口同一规则。倒计时继续根据后台 `reset_at` 计算，分钟取整与 Web 看板一致。
- 新增显式 `/api/logout`，调用原退出实现，避免按瞬时状态切换登录/退出动作。暂停接入不删除本机 Codex CLI 凭据。
- 新增 `/api/pairing?kind=lan|fixed`，一次返回 URL 与对应 SVG，避免网络切换时二维码和复制地址不一致。默认 LAN，固定 `.local` 依赖名称解析；无有效入口时不生成二维码、不假报成功。
- 管理 API 仍仅接受回环 Host/Origin；IPC 采用固定动作白名单，不接受任意 URL、命令或文件路径。桌面页面保持打包资源来源，导航与 CSP 受限，动态业务文本用 `textContent` 渲染，SVG 作为图片显示。
- 复用已有 reqwest 0.13，显式初始化已有 ring TLS provider，覆盖 updater 的 `rustls-no-provider` 特性组合，防止客户端初始化崩溃。

## 页面与兼容

正式页面：`desktop/index.html`、`panel.css`、`panel.mjs`；独立展示规则：`model.mjs`。

1.2.0 打包时由 `scripts/prepare_desktop.mjs` 将上述文件和离线素材复制到 `dist/desktop`；预览页面和示例模块不随 App 分发。右键扫码意图由 Rust 保存，在页面可见后通过 `panel_state` 消费。Python 启动不预热 CDP，Web 降级按需恢复会话；control 手动刷新只调用一次当前账号协调器。

- 正常、未登录、同步失败主状态；扫码、设置、诊断次级视图。退出账号/App 二次确认，失败保留上次数据，不把 HTTP 200 当同步成功。
- 设置只提供当前运行期间保持面板展开与诊断入口，没有无后端支持的开关。
- 使用现有蓝色图标、离线 Lucide 图标和系统字体，不引入前端框架、远程字体或图标 CDN。
- `scripts/control_panel.html` 暂保留供原开发 CLI/本机排障兼容，不再是 App 入口，也不暴露给局域网。正式用户入口只有菜单栏与副屏看板。

## 验证

Python 全量回归 229 项、JavaScript 展示规则 7 项、Rust 7 项通过。覆盖单窗口、0/99/100%、阈值、退出缓存清理、旧身份不回填、失败反馈、隐藏轮询、启动重试、QR URL 一致性、管理权限及并发启停。

Chromium 布局覆盖 366 × 706、320 × 480、366 × 400，与方案 1 同尺寸并排比对。独立标识 `com.gbs00.tokenbi.menubar-preview` 的 debug App 使用示例 HTTP fixture，验证真实 Tauri IPC、额度渲染、QR、入口切换、固定按钮、复制、失败反馈及显式退出进程。

以上开发阶段未读取真实 OAuth 凭据或联网同步额度，未覆盖 `/Applications/Token BI.app`；后续本地安装验证记录见下节。物理多屏、缩放、全屏 Space、长时间睡眠唤醒、真实 iPhone 扫码与持续更新仍需用户验收。内存/CPU/冷启动时延未实测，不给出改善百分比。

发布时需成套重建 shell、control、backend。开发阶段 debug App 的 sidecar 资源不是发布验收包，不应直接覆盖安装。

## 本地安装验证（2026-09-12）

- 用户授权本地更新，执行 `npm run app:build` 完整生成 release App 和 DMG；未使用独立预览 App 或示例服务进行安装。
- 安装前无旧 App、control、backend 运行进程，8787/8790 无监听。替换 `/Applications/Token BI.app`，旧包保留为 `dist/Token BI-v1.1.3-before-menubar-20260912-142152.noindex`；不修改账号数据目录和本机 Codex 凭据。
- 安装标识 `com.gbs00.tokenbi`、版本 1.1.3、`LSUIElement=true`。构建包与已安装包的 shell、control、backend 校验值一致；App 深度签名验证及 DMG 校验通过，仍为 ad hoc 签名，未公证。
- 再次通过 Python 229 项、JS 7 项、Rust 7 项测试。真实 App 自动启动 control 与主服务，健康标记正确，OAuth 同步 `ready`、账号 `active`；原生页面通过 IPC 展示真实单一周额度，不补造 5h 窗口。
- 原生扫码页生成 LAN 二维码；LAN 与固定入口 API 均返回有效 SVG，二维码 URL 与状态入口一致。本机回环、LAN IP、`.local` 的 `/dashboard` 均返回 200；主服务监听 IPv6 双栈，control 仅监听 IPv4 回环。不以本机检查替代 iPhone 网络验收。
- 首次 UI 自动化读取超时，但随后检查 App 和两个服务进程均正常，健康检查成功，第二次原生读取成功；该工具超时不能作为 App 启动耗时或失败证据。未进行新的冷启动性能基准。
- App 保留运行供用户验收；未推送 GitHub、未创建 Release、未递增版本号。

SHA-256：

| 产物 | 校验值 |
| --- | --- |
| App shell `Contents/MacOS/token-bi` | `bd9e4a9720eba291e86cc099bd6cf1008c6cd493bf1f1d0084006a42b5a92e8a` |
| control runtime | `09dc06ea89b1f30ca52c9b7484f15bc2fb9c2d23fa5b5deb03e110308c94f24d` |
| backend runtime | `ebf94efcca0bd1c31d24c7e671ec7e12f85e8d1ef781bfa1c2724b7d30ba88f8` |
| `Token BI_1.1.3_aarch64.dmg` | `e0d071a8b8c86f0bfd38b0f869c4ca07170ea6748b68b8721236ef8b6f08b1ec` |

## 首次展开尺寸与圆角修复（2026-09-12）

用户反馈：首次展开变窄，标题、指标名称与底部操作换行，再次展开恢复；圆角处露出矩形背景。当前设备连接 Retina 内屏及 1920 × 1080 外接屏。

原因：原 `show_panel` 把 tray 的物理坐标传入 macOS 使用逻辑坐标的屏幕查询，再按查询屏幕的倍率计算物理尺寸；底层 `set_inner_size` 却按窗口移动前的倍率转换。在 1×/2× 屏幕组合中可能选错屏幕或把宽度缩成一半。尺寸、位置分别提交也使首次显示与后续显示结果不一致。网页 `border-radius` 只裁剪 HTML，原生窗口背景不透明且未裁剪，圆角外仍有底色。

处理：

- 所有展开路径派发至主线程；从实际状态栏按钮的 NSWindow 读取所属 NSScreen 与 `visibleFrame`，全程使用 AppKit 逻辑坐标，原生 `setFrame:display:` 一次应用位置和尺寸后才显示。
- 正常尺寸保持 366 × 706 逻辑点，按当前工作区缩短高度，保留 6 点边距；覆盖负坐标、Dock 占位、短屏和状态栏位置暂不可用时的回退。不改变用户的显示器设置。
- 使用公开 `NSWindow` 与 `CALayer` API：透明窗口背景、内容层 12 点圆角和 `masksToBounds` 裁切，保留原生阴影。未启用 Tauri `macos-private-api`，未使用私有 WKWebView 属性或磨砂材质。网页根节点同步裁剪，移除圆角外底色，并禁止品牌标题和底栏按钮拆行。
- 新增 macOS 专用模块及窄范围 objc2/AppKit/QuartzCore 依赖；由于使用 Tauri 内部 tray 访问器，将 Tauri 约束为 `~2.10.3`。额度采集、账号优先级、缓存、Web 看板和服务生命周期未修改。

验证：15 项桌面浏览器行为测试通过（含 1×/2×、366 × 706、366 × 404、308 × 388 布局），11 项 Rust 测试、7 项 JS 测试通过；Clippy `-D warnings`、差异检查通过。本轮未重跑完整 Python 后端套件。完整重建 App/DMG，安装后截图确认展开、收起再展开及扫码页正常；收起后主服务仍 healthy、OAuth 为 ready，LAN 看板本机请求返回 200。跨屏菜单栏实际点击、外接屏拔插与首帧连续录像仍待用户验收，不以浏览器 DPR 测试替代原生跨屏测试。

已覆盖 `/Applications/Token BI.app`，旧菜单栏包备份：`dist/Token BI-before-window-fix-20260912-144432.noindex`。账号数据保留，版本保持 1.1.3，未推送或发布。安装及构建 App 深度签名检查通过；shell SHA-256：`6aec3eb486939e70fd7c0d9b41263d9fcfd1eec9f7d777ba7e85b9d9b6d2be81`，本次 DMG SHA-256：`08ba40998727e2115fb16e99adf1cb9020164b7635d0f4bd62397d3be3330bcf`。

依据：本机锁定版本 `tray-icon 0.21.3` 的 `get_tray_rect`、`tao 0.34.8` 的 `monitor::from_point`/`set_inner_size` 源码；[Apple CALayer 裁切说明](https://developer.apple.com/documentation/quartzcore/calayer/maskstobounds)、[Apple NSWindow 内容视图](https://developer.apple.com/documentation/appkit/nswindow/contentview)。

## 311px 紧凑布局（2026-09-12）

用户反馈原弹层占屏过大，明确要求宽度收紧至 311px。本轮将默认窗口从 366 × 706 改为 311 × 600 逻辑点，保留上一轮跨屏定位、可用工作区边界和原生圆角修复，不用物理像素推算逻辑宽度。

- 同步收紧品牌区、账号区、指标间距、按钮及底栏；标题和操作不拆行，重置剩余时间仍使用 14px 字号。
- 主按钮最小高度 44px，二维码尺寸 200 × 200px；单额度、双额度及 LAN/固定入口扫码页在默认尺寸下无需额外滚动即可看到主要操作。矮屏继续限制窗口高度并允许内容滚动。
- 更新浏览器预览及原设计对照页，保留原图尺寸作历史参照。截图位于 `docs/design-previews/menubar-qa/`。
- 未修改账号读取优先级、额度计算、服务生命周期或副屏 Web 看板。

验证：19 项桌面浏览器行为测试、11 项 Rust 测试、7 项 JS 测试通过，共 37 项针对性测试；覆盖 1×/2×、311 × 600、311 × 404、308 × 388 等尺寸，以及单/双额度、100% 数值、长账号和两种扫码入口。截图测试关闭过渡动画以避免捕获入口切换中间帧。本轮未重跑完整 Python 后端套件。

执行 `npm run app:build` 成套重建并替换 `/Applications/Token BI.app`，旧包备份为 `dist/Token BI-before-compact-311-20260912-150455.noindex`，账号数据保留。原生额度页与扫码页截图检查通过，真实 OAuth 状态为 `ready`，control 与主服务健康，本机请求 LAN 看板返回 200。安装前后深度签名及 DMG 校验通过，安装 shell 与构建包校验值一致；未新增 iPhone 或原生跨屏验收。

当前 shell SHA-256：`224123aa8f8f8717b947ec179c1d32440b66e80f3f29d6317db39868ae06c7b1`；DMG SHA-256：`107c81fa34a7c2722a3c4f6ea94f668aef74a73a5a62f52349e21cdb2844514d`。版本保持 1.1.3，App 保留运行供用户验收，未推送 GitHub 或创建 Release。

## 额度数字排版修正（2026-09-12）

用户确认问题属于数字显示样式，而非额度取值。此前整段 `100%` 使用相同的 25px/650 字重，百分号视觉权重过高，与“剩余”的排版层级不清。

- 拆分数字、百分号与说明：数字 24px/600，百分号 14px/500，“剩余”14px/400 次级灰色，通过 inline-flex 统一基线。
- 数字采用等宽数字字形，数值组不收缩、不拆行；保持 311 × 600 窗口、阶梯颜色、重置时间、后端数值与进度条比例不变。
- 27 项桌面行为测试、7 项 JS 展示规则测试通过。新增 0/9/99/100 在 1×/2× 下的字级、元素边界和数据一致性检查，单/双额度截图复核通过；未重跑完整后端与 Rust 测试。截图：`menubar-qa/quota-100-dpr1.png`、`menubar-qa/quota-100-dpr2.png`（位于 `docs/design-previews/`）。

已完整重建 App/DMG 并覆盖 `/Applications/Token BI.app`，旧包备份为 `dist/Token BI-before-quota-typography-20260912-162112.noindex`。安装前后深度签名验证通过，安装 shell 与构建包一致；原生窗口截图确认新字级及基线，后台健康、OAuth 为 `ready`，真实数值与面板一致。账号数据保留，版本仍为 1.1.3，未推送或发布。

Shell SHA-256：`f3812c0174b4c8f2212f54a18b69f78626956059211dcae1b924235404a9876e`；DMG SHA-256：`84f50639f65266490612199623a0b930f95ec2880093b3fd9f79fd3b4b7d924b`。

## macOS 27 菜单栏点击兼容（2026-09-16）

### 问题与依据

用户升级至 macOS 27.0（本机 build 26A428）后，单击菜单栏图标只出现「查看额度 / 扫码连接副屏 / 退出 Token BI」菜单。安装版为 1.2.1，额度面板仍能显示真实数据，问题位于原生点击分发，而非 OAuth、局域网或网页渲染。

项目使用 Tauri 2.10.3 / tray-icon 0.21.3。旧代码同时配置 `.menu(&menu)` 和 `.show_menu_on_left_click(false)`；依赖内部始终将菜单设置到 `NSStatusItem`，关闭左键菜单的标志只在覆盖子视图收到点击后判断。macOS 27 在菜单常驻绑定时先处理原生菜单，子视图无法收到预期左键事件，因此该标志不能阻止系统菜单。

依据：[tray-icon #355](https://github.com/tauri-apps/tray-icon/issues/355) 描述相同复现；[上游修复 #365](https://github.com/tauri-apps/tray-icon/pull/365) 于 2026-09-16 合并。当前锁定依赖不含该修复，不为本次问题进行整套 Tauri 升级或维护私有依赖分支。

### 实施范围

- `menubar.rs` 在 macOS 不调用托盘 `.menu()`，菜单对象由事件闭包持有；其他平台仍使用原绑定方式。
- macOS 右键按下时先收起额度面板，再通过 Tauri `popup_menu` 显式显示菜单。底层 AppKit 按光标位置弹出，不设置 `NSStatusItem.menu`，菜单关闭后也不会重新绑定。
- `menubar/macos.rs` 封装主线程检查与弹出后的高亮清理。旧 tray-icon 在无绑定菜单的右键路径会设置高亮但不在释放时清除，因此主动恢复；不跨菜单嵌套事件循环持有内部托盘借用。
- 左键释放展开/收起、失焦隐藏、311px 尺寸、扫码菜单动作、Updater、OAuth 优先级及 LAN 服务均保持不变。不增加轮询、进程、私有 API 或新依赖。
- 后续升级 Tauri/tray-icon 时重新核验此兼容处理；只有在新版本通过下列真机验收后才能删除，不并行保留两套菜单触发逻辑。

### 验证与本机安装

- Rust 单元测试 17 项、桌面浏览器交互 31 项、JS 展示规则 9 项通过；`cargo clippy --all-targets -- -D warnings` 通过。本轮未重跑完整 Python 后端套件。
- 构建 App（未生成或上传新的 DMG/Updater 归档），构建与安装路径均通过 `codesign --verify --deep --strict`。`verify_bundle.py` 隔离验证 control、backend、暂停账号访问、看板静态资源、二维码和退出清理通过。
- 已替换 `/Applications/Token BI.app` 并启动，control 健康接口确认打包服务运行；旧实例及其后台进程退出后再替换，无重复实例。未修改账号数据与设置。
- 旧包备份：`dist/Token BI-before-macos27-fix-20260916-224631.noindex`。本机兼容包仍显示 1.2.1，与 GitHub 已发布的 1.2.1 不同；未推送、未覆盖 Release 产物。
- 安装与构建 shell SHA-256 均为 `b9f05d21522441656bfd6a5d76e510efa357e184250484ec19ff515731cfc48b`。
- 自动化工具无法可靠访问隐藏状态下的系统菜单栏图标，以上测试不能证明真实鼠标事件分发。替换后用户于本次会话明确反馈「左键面板、右键菜单均正常」，核心点击行为已通过本机真机验收；其余未明确确认的细项仍待复验。

真机验收清单：

1. 已确认：左键单击直接展开额度面板；右键显示快捷菜单。
2. 待复验：再次单击收起；单击桌面或其他窗口后隐藏，再单击图标可重新展开。
3. 待复验：取消右键菜单后图标不持续高亮，左键仍可展开面板。
4. 待复验：右键菜单的「查看额度」和「扫码连接副屏」打开对应页面，关闭后再次右键仍正常。
5. 待复验：「退出 Token BI」正常退出并清理本实例服务；重新启动后左右键仍按各自规则响应。
6. 待复验：旧 macOS、多显示器/混合 DPI 与睡眠唤醒，不以本机 27.0 的结果覆盖。

### v1.2.2 发布回归

用户在上述本机验收后授权将修复发布为 v1.2.2。版本元数据统一后执行 `scripts/release_local.sh`，重新构建 shell、control 和 backend，而非复用 1.2.1 后端。

- Python 360 项、JS 9 项、Rust 单元 17 项、签名归档集成 1 项通过；格式、Clippy `-D warnings`、依赖检查通过。
- App 深度签名、DMG 校验通过；打包服务在临时数据目录验证版本、健康、暂停账号、看板资源、二维码与退出清理。
- 使用既有 Updater 密钥签名，隔离验证官方下载/安装接口与篡改拒绝。正式端点仍为 HTTPS，未为测试修改生产安全配置。
- DMG 为 67,491,777 字节，SHA-256：`3f845df4e5bbf13c98e1e8dfa03e1c7e3815755866f8cc6ef3064da113bc0606`。
- 更新归档 SHA-256：`8134b6a9a2ed4df294e353ebafafa71798779b4f20f600ee4eda66724b0d3ad7`。签名、版本清单及 SHA256SUMS 一并制备；发布说明修改后重新生成清单，确保内容一致。
- 本轮发布构建未再次覆盖已验收的本机兼容包；正式 1.2.2 可通过设置检查更新后手动安装。跨版本真实重启与副屏恢复的验收边界不变。

## 本地复验

```sh
npm run desktop:assets
npm run desktop:preview
npm run desktop:test
./.venv/bin/pytest -q
cargo test --manifest-path src-tauri/Cargo.toml --target-dir src-tauri/target.noindex --lib
```

预览：`http://127.0.0.1:8898/preview.html`，只使用示例数据，不启动生产服务。

按需生成视觉截图：`TOKEN_BI_VISUAL_QA=1 ./.venv/bin/pytest -q tests/test_desktop_shell.py -k visual_evidence`。

`tests/native_menubar_stub.py` 仅供原生隔离验证：只能在 8790 空闲、正式 App 未运行时手动启动，验证后必须停止，不得作为后台服务或发布内容。
