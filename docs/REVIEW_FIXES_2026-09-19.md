# 2026-09-19 代码审计修复纪要

状态：纳入 v1.2.3 发布。基线为 v1.2.2（`f306e0543e087ed17d049d53e757a8bf202fa55d`），用户确认修复此前审计的 7 项问题。保留菜单栏、副屏看板和单账号数据源优先级。初轮仅修复及测试；2026-09-19 用户追加授权正式发布 v1.2.3，发布验证见 [版本说明](RELEASE_NOTES_v1.2.3.md)。本机安装不自动替换。

## v1.2.3 发布验证

2026-09-19：`scripts/release_local.sh` 完整通过。Python/浏览器 394 项（127.65 秒）、Rust 19 项、JS 9 项及真实签名归档隔离安装测试 1 项全部通过；Clippy、格式和依赖检查通过。成套 App 构建、control/backend 健康与停止、App 深度签名、DMG 挂载及包内签名通过。更新安装测试仅替换临时副本，拒绝篡改包，不操作本机已安装 App。包体及升级边界见 [发布说明](RELEASE_NOTES_v1.2.3.md)。

## 修复与边界

| 审计项 | 原因 | 本轮处理 |
| --- | --- | --- |
| 1. 更新未确认后台停止 | Rust 忽略停止结果，失败时直接杀控制进程；Python 即使主服务停止失败也退出控制服务 | 更新安装以成功停止为前提，同时等待拥有的 control 子进程退出及端口释放。失败保留句柄和运行记录，取消文件替换，允许恢复后重试；不停止复用的外部控制实例。 |
| 2. mock 会触及真实账号 | 旧脚本先覆写账号配置再启动真实 connector 链路，旧 mock 标志只作用于已失效分支 | `start_mock_preview.sh` 转向现有独立示例服务，默认仅监听 `127.0.0.1:8899`；不导入生产服务、不初始化账号、不请求上游。删除种子脚本、旧独立浏览器抓取及其配置项。 |
| 3. OAuth 账号切换后旧额度残留 | 身份只在成功获取 usage 后才提交；请求失败时无法发现本地身份已变 | 每轮采集前读取本地 OAuth 身份指纹，在协调器状态锁与账号接入代次保护下清除旧内存/磁盘额度，提交 pending 身份。只有成功额度可将账号标记为 active。同账号短暂断网仍保留成功缓存。 |
| 4. GUI 无法找到已安装 CLI | Finder 的 PATH 不包含交互 Shell 的安装路径 | 统一 CLI 定位函数，优先配置/PATH，再检查 Homebrew、`~/.local/bin` 和 Codex.app 内置路径。启动使用解析后的可执行路径，子进程补充相应 PATH；显式配置失效不擅自改用其他 CLI。诊断与采集复用同一规则。 |
| 5. 回环请求被代理 | Python `urlopen` 隐式读取系统/环境代理 | 控制服务到主服务、浏览器调试端口探测共用仅允许回环 HTTP 的直连 transport，并拒绝重定向；不改变外部 OAuth 请求使用代理的能力。 |
| 6. Web 错误被未安装本地源掩盖 | 缺失 OAuth/CLI 的 `not_applicable` 被当作高优故障 | 选择根因时排除未适用源；已尝试的 OAuth/CLI 真实故障仍保持优先。只有本地源不存在时，Web 的网络、限流、结构变化和授权错误才能正确成为主要错误。 |
| 7. 失联进程无法通过重试恢复 | 仅凭 PID 存活判定服务已运行，UI 重试调用普通刷新 | 复用进程前验证健康标识及 PID；失联时在启动锁内停止确认归本项目管理的旧进程，再启动新进程。无法确认所有权或停止失败时不另起实例；菜单栏根据健康状态选择重启而非刷新。 |

停止流程还增加控制实例 PID 请求校验，避免旧句柄向已替换实例发送退出指令；收到退出请求后不再接受新启动。启动超时且清理失败时保留 PID/runtime 信息，不把未停止的后台变成无记录进程。

账号预检只读取本地元数据，不新增远程请求、不修改 Codex 凭据。身份不可读取时仍允许原有 fallback；这不是多账号管理或凭据监控功能，变更在下一轮同步预检时识别。

## 开发兼容

- `scripts/start_mock_preview.sh [端口]` 是隔离样例入口。示例额度不是官方实时报表。
- 旧 `TOKEN_BI_USE_MOCK_SCRAPER=true` 明确报错，防止把真实生产采集误当 mock；改用上述脚本。已删除的 Playwright channel/headless 配置仅属于旧独立浏览器抓取分支，不影响专用 Chrome 的 CDP 兜底。
- 无账号数据迁移，无新增依赖。升级时 Rust shell、control 和 backend 必须成套打包。
- 更新失败保留用户数据；未拥有的后台不会被强制结束，需要先退出其来源应用。控制进程已异常退出时先恢复服务，不能把端口空闲当作整个后台已停止。
- 同账号断网不清空额度，已确认切换账号则不展示旧额度。JWT 身份仅作本地缓存归属判断，不代表远程授权成功。

## 验证记录

- 专项后端回归：163 项通过；覆盖停止失败、所有权拒绝、代理干扰、降级归因、OAuth 切换/脱敏碰撞和独立 mock 脚本。
- 真实开发进程故障注入：使用临时数据目录、空账号且禁用接入、随机回环端口；挂起自建主服务后重试恢复，再退出检查进程和端口，已通过。
- Rust：19 项通过，覆盖停止 ACK、子进程退出、端口关闭三项缺一不可，以及不向替换的监听实例发送关闭请求。
- 在临时目录单独构建 control sidecar 并执行打包态握手：错误 PID 被拒绝、真实子进程 PID 被接受、控制进程正常退出且端口释放。发布用 `verify_bundle.py` 同步加入 PID 头校验；未覆盖安装或构建完整 App/DMG。
- JS：9 项通过；Clippy（警告视为错误）、Rust 格式、Python 依赖一致性和差异空白检查通过。
- 最终全量 Python 回归：394 项通过（包含 Chromium/WebKit 布局与交互），耗时 227.18 秒；相较审计基线增加 34 项 Python 回归，Rust 增加 2 项。JS 模块与 mock 启动脚本语法检查通过。

上述为修复阶段验证：当时未对真实安装执行文件替换或签名更新，也未验证真实 GitHub 下载、macOS 原生退出/升级提示、iPhone 实机及长期睡眠恢复。后续发布制品验证单独记录，不将源码测试等同于打包验收。

复验命令（`TOKEN_BI_APP_DATA_DIR` 应指向独立临时目录）：

```sh
PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/pytest -q -p no:cacheprovider
npm run desktop:test
cargo test --manifest-path src-tauri/Cargo.toml --target-dir src-tauri/target.noindex --lib --locked
cargo clippy --manifest-path src-tauri/Cargo.toml --target-dir src-tauri/target.noindex --all-targets --locked -- -D warnings
cargo fmt --manifest-path src-tauri/Cargo.toml --check
./.venv/bin/python -m pip check
git diff --check
```
