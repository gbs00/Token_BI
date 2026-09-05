# Token BI V1.0.0 技术架构文档

日期：2026-05-23  
状态：设计草案  
输入来源：`Token BI 需求澄清分析` V1.0 PRD 草案、`V0.9.1 优化点整理`

## 1. 文档目的

本文用于指导 `Token_BI` 从 v0.9.1 可信测试版演进到 v1.0.0。

v1.0.0 的核心变化是：

- 从“浏览器 CDP 抓取主链路”调整为“无感后端数据源优先，浏览器兜底”。
- 从固定解释 `5h` / `weekly` 指标调整为官方 usage / rate limit 窗口透传。
- 常规刷新不应弹出、切换或唤起 Chrome tab。
- 保留现有 Mac 本地服务、副屏 H5 看板、Tauri App 壳层和局域网访问形态。

本文不是发布说明，也不是 UI 设计稿。它回答：

- v1.0.0 的系统边界是什么。
- 数据源如何选择与降级。
- 官方 usage 指标如何进入看板。
- 敏感数据和日志边界是什么。
- 哪些模块需要新增或替换。
- 本地验证应覆盖哪些路径。

## 2. 设计原则

### 2.1 无感优先

- 常规刷新不打开 Chrome，也不切换用户当前桌面焦点。
- Web Session / Chrome worker 只作为兜底，不再作为常规刷新主路径。
- 用户不应为了看额度反复处理登录窗口、usage 页面或 Chrome tab。

### 2.2 官方指标透传与 BI 展示边界

- Token BI 不自建固定指标库。
- Token BI 不把 `primary_window` / `secondary_window` 固定解释为 `session` / `weekly`。
- 后端连接器仍按官方 usage / rate limit 窗口归一化，避免补 0 或伪造指标。
- BI 看板只展示用户明确关心的额度窗口：`5h 额度` 与 `周额度`。
- 官方返回未知窗口时，不进入 BI 看板；后续如需展示，必须先补充需求纪要和展示语义。
- 官方删除窗口时，不展示该窗口，不报错、不补 0。
- `0%` 只代表官方明确返回剩余额度为 0。

### 2.3 标准生态优先

- 优先复用 Codex CLI / Codex App 已有本机登录态。
- 优先通过官方或本机标准能力读取 usage。
- 不新增自研鉴权系统，不存储账号密码。

### 2.4 安全克制

- 不存储 usage 历史。
- 不保存账号密码。
- 不把 token、cookie、邮箱明文、账户标识明文或官方原始响应写入普通日志。
- `raw_window` 只用于内存态排障和适配。

## 3. V1.0.0 范围

### 3.1 P0 必须完成

- 新增 `CodexOAuthConnector` 作为首选数据源。
- 新增 `CodexCliRpcConnector` 作为本机 Codex 能力 fallback。
- 调整 `UsageConnectorManager` 数据源顺序。
- 调整 usage 数据模型为官方窗口透传。
- 调整看板按官方窗口列表渲染指标卡。
- 常规刷新不依赖 Chrome worker。
- 增加 token 过期、未登录、权限不足、官方结构变化的错误态。
- 增加敏感数据与日志边界。

### 3.2 P1 应该完成

- 保留 `WebSessionConnector` 作为主链路不可用时的兜底。
- 控制台展示当前数据源与降级原因。
- 看板失败时保留上次成功数据和错误原因。
- 同步更新 `README.md`、`TECH_ARCHITECTURE.md`、`CHANGELOG.md`。

### 3.3 P2 暂缓

- 多账号复杂切换体验。
- usage 历史分析、趋势图、skills 统计。
- 正式公开分发、签名、公证、自动更新链路。
- 更多副屏设备 UI 深度优化。

## 4. 总体架构

```mermaid
flowchart LR
    T["Token BI.app (Tauri Shell)"] --> H["Local Console Shell"]
    T --> L["Rust Control Launcher"]
    L --> C["token-bi-control Runtime"]
    C --> D["token-bi-backend Runtime"]
    P["Sidecar Device Browser"] --> D

    D --> A["Account Service"]
    D --> U["Usage Service"]
    D --> K["Cache Service"]

    U --> M["Usage Connector Manager"]
    M --> O["CodexOAuthConnector"]
    M --> R["CodexCliRpcConnector"]
    M --> W["WebSessionConnector"]
    W --> B["Browser Worker Service"]
    B --> G["Token BI Chrome Worker"]

    O --> OA["~/.codex/auth.json / $CODEX_HOME/auth.json"]
    O --> OU["Codex Usage Backend"]
    R --> CR["codex app-server"]
    G --> CW["Codex Web Usage Page"]
```

### 4.1 v1.0.2 桌面端启动边界

- Tauri 窗口与 Python 健康检查解耦：窗口先显示本地控制台壳层，轻量控制服务就绪后在同一 WebView 内导航到完整控制台。
- `token-bi-control` 只承担控制台 HTML/API、健康检查和主服务生命周期管理，不导入 FastAPI、Playwright 或 usage connector 重依赖。
- `token-bi-backend` 承担账号、usage connector、Web Session 兜底和副屏看板 API，只在用户开启服务时按需启动。
- Rust launcher 只负责定位 App Resources 中的 onedir 运行时、注入主服务路径并用 `exec` 替换自身，避免额外常驻父进程。
- 两套 Python 运行时均使用 PyInstaller onedir，用包体积换取日常启动时不重复解包的稳定时延。
- 用户产品概念仍然是单一“Token BI 控制台”；该拆分是内部进程职责优化，不将控制台与运维服务拆成两个用户界面。

## 5. 数据源策略

### 5.1 数据源优先级

固定顺序：

1. `CodexOAuthConnector`
2. `CodexCliRpcConnector`
3. `WebSessionConnector`
4. `DOM fallback`

说明：

- OAuth usage 后端来自 ChatGPT/Codex 登录态，是当前优先数据源，但不是公开承诺稳定的 OpenAPI。
- `codex app-server` 当前带实验语义，需要封装失败、超时和降级。
- Web Session 仍保留，但只在前两条主链路不可用时触发。
- DOM fallback 只作为最后诊断手段，不作为常规刷新主路径。

### 5.2 CodexOAuthConnector

职责：

- 读取本机 Codex 登录态。
- 自动判断是否存在可用 ChatGPT auth token。
- 请求 Codex usage 后端接口。
- 将官方返回窗口转换为 Token BI 的展示模型。

输入：

- `~/.codex/auth.json`
- `$CODEX_HOME/auth.json`

输出：

- 当前账号标识，优先脱敏。
- 官方 usage / rate limit 窗口列表。
- 数据源元信息。

失败场景：

- auth 文件不存在。
- auth 结构不匹配。
- access token 过期且无法刷新。
- usage 后端返回 401 / 403 / 429 / 5xx。
- usage 返回结构无法解析。

处理规则：

- 不把 token 写入日志。
- 401 / 403：返回 `reauth_required`。
- 429：退避后保留上次成功结果。
- 5xx / 网络错误：退避后降级下一 connector。
- 结构无法解析：返回 `source_changed`，保留上次成功结果。

### 5.3 CodexCliRpcConnector

职责：

- 调用本机 `codex app-server`。
- 读取账号信息和 rate limit 数据。
- 将返回窗口转换为 Token BI 展示模型。

候选能力：

- `account/read`
- `account/rateLimits/read`

约束：

- app-server 属于本机能力 fallback，不要求用户理解 RPC 细节。
- 调用必须有超时，避免看板刷新被阻塞。
- 失败后应继续降级到 `WebSessionConnector`。

失败场景：

- 未安装 `codex`。
- `codex app-server` 不支持目标命令。
- 本机未登录。
- RPC 超时。
- 返回结构变化。

### 5.4 WebSessionConnector

职责：

- 保留现有 Chrome/CDP worker。
- 在 OAuth / CLI 不可用时作为兜底读取路径。
- 帮助无本机登录态用户完成一次 Web 登录。

变化：

- 不再作为常规刷新主路径。
- 触发时控制台必须解释原因。
- 成功后仍可尝试最小化 Token BI 管理的 worker。

### 5.5 DOM fallback

职责：

- 仅在 network / script / API 路径均不可用时尝试解析页面文本。
- 仅用于诊断或短期兼容。

约束：

- 不作为常规刷新主路径。
- 不新增复杂 DOM 语义推断。

## 6. 核心数据模型

### 6.1 OfficialUsageWindow

用于在后端内部承载官方返回窗口。

```json
{
  "raw_window": {},
  "display_name": "Weekly",
  "remaining_pct": 92,
  "reset_at": "2026-05-30T16:00:00+08:00",
  "window_seconds": 604800,
  "window_minutes": 10080,
  "source_type": "oauth",
  "source_detail": "oauth_usage_api"
}
```

字段说明：

- `raw_window`：官方返回的原始窗口数据，只允许在内存态用于排障和适配。
- `display_name`：展示名称，优先使用官方名称；官方未提供时才根据窗口时长生成保守名称。
- `remaining_pct`：剩余百分比，来自官方剩余值，或由官方 `used_percent` 换算。
- `reset_at`：官方返回的重置时间，只做时区转换和倒计时展示。
- `window_seconds` / `window_minutes`：官方返回的窗口时长，仅用于排序和兜底命名，不用于固化业务枚举。
- `source_type`：数据源，如 `oauth` / `cli_rpc` / `web_session` / `dom_fallback`。
- `source_detail`：具体读取路径，如 `oauth_usage_api` / `cli_rate_limits` / `network_response`。

### 6.2 DashboardPayload

建议 v1.0.0 API 返回结构：

```json
{
  "account": {
    "account_id": "acc_current",
    "masked_email": "user****@example.com",
    "status": "active"
  },
  "state": "ready",
  "message": null,
  "summary": {
    "updated_at": "2026-05-23T16:00:00+08:00",
    "source_type": "oauth",
    "source_detail": "oauth_usage_api",
    "connector_name": "codex_oauth",
    "is_estimated": false
  },
  "metrics": [
    {
      "display_name": "Weekly",
      "remaining_pct": 92,
      "reset_at": "2026-05-30T16:00:00+08:00",
      "window_seconds": 604800,
      "source_type": "oauth",
      "source_detail": "oauth_usage_api"
    }
  ],
  "detail_links": [
    {
      "label": "Usage 入口",
      "url": "https://chatgpt.com/codex/cloud/settings/analytics#usage",
      "requires_same_account_login": true
    }
  ]
}
```

兼容策略：

- `metrics` 改为窗口列表，不再要求同时存在 `session_*` 和 `weekly_*`。
- 前端不得依赖固定 `metric_type` 决定展示是否存在。
- 如需兼容旧前端，可短期保留 `metric_type`，但只能作为展示辅助，不作为业务真相。

## 7. 核心模块设计

### 7.1 UsageConnectorManager

职责：

- 统一调度 usage connector。
- 统一输出 `not_applicable`、`auth_required`、`network_error`、`timeout`、`rate_limited`、`source_changed`、`web_session_inactive`、`internal_error`。
- 按优先级依次尝试 connector。
- 记录最终成功的数据源和失败降级原因。
- 最终错误以 OAuth / CLI RPC 的真实语义为准，Web Session 未运行不能覆盖主链路的网络、超时或限流错误。

建议接口：

```python
class UsageConnector:
    name: str
    source_type: str

    def fetch_usage(self, account: AccountRecord) -> UsageConnectorResult:
        ...
```

`UsageConnectorResult` 建议包含：

- `connector_name`
- `source_type`
- `source_detail`
- `account_identity`
- `windows`
- `raw_debug_summary`

### 7.2 UsageService

职责：

- 选择当前账号。
- 调用 `UsageConnectorManager`。
- 将官方窗口转换为 `DashboardPayload`。
- 一次调用只执行一次上游同步，不承担缓存、定时调度或退避。
- 账号 `pending` / `invalid` / `expired` 只用于界面状态，不阻断 OAuth / CLI RPC 尝试；但用户主动退出后的 `access_enabled=false` 必须阻断自动读取。
- 采集与提交分离：`prepare_dashboard` 只返回候选账号和已解析额度；有效额度通过校验后，`commit_dashboard` 才提交账号身份和 `active` 状态。无有效指标时不得创建或激活账号。
- 能取得邮箱时，保存邮箱归一化后的 SHA-256 身份键，避免不同账号脱敏后显示相同名称。身份键不是登录凭据，不向副屏 API 暴露。

变化：

- 不再在这里构造固定 `5h Session` / `Weekly` 两张卡。
- 不再把缺少 session 视为异常。
- 不再按 `primary_window` / `secondary_window` 推断业务枚举。

### 7.3 UsageSyncCoordinator 与 LatestDashboardStore

职责：

- 接入开启时，主服务启动后在后台立即同步，成功后每 180 秒同步一次；主动退出后不安排下一次同步。
- 自动同步、手动同步、控制台刷新与多个副屏共用 single-flight，同一时刻只允许一次上游请求。
- `GET /api/v1/dashboard` 只读内存中的最新状态，不调用 connector。
- 失败时仅保留同一账号身份的最后成功额度，并按错误类型调度重试。已确认身份变化但新额度无法解析时，清除旧内存指标、成功时间和磁盘快照。
- 一次同步包含重试的总时间上限为 45 秒；并发调用最多等待 45.5 秒。采集线程不能写账号或快照，超时、退出、恢复接入都会使旧结果失去提交资格。
- 同一时刻最多保留一个采集工作线程；若底层尚未结束，不再启动额外采集。正常网络/RPC 超时会释放资源；若底层浏览器驱动发生不可取消的阻塞，返回失败并避免线程堆积，必要时由控制台重新启动主服务。
- GET 返回的最近成功数据超过一个同步周期加总时间预算后降级为 `stale`，不能持续标记 `ready`。
- 将最后一次成功结果原子写入 `runtime/cache/latest_dashboard.json`，服务重启后可立即恢复 stale 展示。

持久化边界：

- 只保存一份当前快照，不追加、不形成 usage 历史。
- 只保存归一化指标、数据源、同步时间和脱敏账号标识。
- 禁止写入 token、cookie、`raw_window`、账号明文、浏览器 profile 或 session 路径。
- 退出账号或发现账号标识不匹配时删除快照。

### 7.4 AccountService

职责：

- 管理 Token BI 内部账号记录。
- 保存脱敏身份、身份键、状态和最后校验时间。
- `accounts.json` 顶层保存 `access_enabled` 与 `access_revision`，通过原子替换写入；退出与恢复都会增加接入代次，防止“退出后马上重新登录”期间的旧采集结果回写。
- 不保存账号密码。
- 不保存 token 明文。

v1.0.0 变化：

- 支持“本机 Codex 登录态可用，但 Token BI 尚无账号记录”的首次识别流程。
- OAuth / CLI 成功读取账号身份后，自动创建或更新当前账号记录。

### 7.5 Control Panel

职责：

- 展示主服务状态。
- 展示当前账号。
- 展示数据源状态。
- 展示主链路失败和降级原因。
- 提供登录授权、同步 usage、扫码连接副屏。

v1.0.0 新增状态：

- `oauth_ready`
- `cli_rpc_ready`
- `web_session_fallback`
- `reauth_required`
- `rate_limited`
- `source_changed`

### 7.6 BrowserWorkerService

职责：

- 继续管理 Web Session 兜底所需的 Chrome worker。
- 关闭账号时释放 Token BI 管理的 worker。

v1.0.0 变化：

- 启动主服务时不应默认拉起 Chrome worker。
- 只有进入 Web Session 兜底时才启动或恢复 worker。
- 成功读取后可尝试最小化 worker。

### 7.7 Dashboard Frontend

职责：

- 渲染账号信息。
- 渲染 `5h 额度` 与 `周额度`。
- 展示数据源和下次同步倒计时。
- 定时刷新和手动同步。

变化：

- 根据 `metrics[]` 动态渲染已识别额度卡片。
- 周额度与 5h 额度同等优先级，使用同规格卡片。
- 百分比只在圆环中心显示一次。
- 卡片底部只显示后端重置剩余时间。
- 未知指标、链路、日志、刷新间隔和服务状态不在 BI 看板展示。
- 官方删除窗口时自动消失，不展示空卡、不补 0。

## 8. 数据流

### 8.1 常规刷新

```mermaid
sequenceDiagram
    participant Sidecar as Sidecar Browser
    participant API as FastAPI Dashboard API
    participant Coordinator as UsageSyncCoordinator
    participant Usage as UsageService
    participant Manager as UsageConnectorManager
    participant OAuth as CodexOAuthConnector
    participant CLI as CodexCliRpcConnector
    participant Web as WebSessionConnector
    participant Store as LatestDashboardStore

    Sidecar->>API: GET /api/v1/dashboard
    API->>Coordinator: get_dashboard()
    Coordinator-->>API: 内存中的最新状态
    API-->>Sidecar: JSON / HTML

    loop Mac 后台调度（成功后 180 秒）
        Coordinator->>Usage: sync_dashboard()
        Usage->>Manager: fetch_usage(account)
        Manager->>OAuth: fetch_usage()
        alt OAuth success
            OAuth-->>Manager: official windows
        else OAuth unavailable
            Manager->>CLI: fetch_usage()
            alt CLI success
                CLI-->>Manager: official windows
            else CLI unavailable
                Manager->>Web: fetch_usage()
                Web-->>Manager: existing session result or typed failure
            end
        end
        Manager-->>Usage: connector result
        Usage-->>Coordinator: DashboardPayload
        Coordinator->>Store: 原子替换最后成功快照
    end
```

### 8.2 首次授权

```mermaid
sequenceDiagram
    participant User as User
    participant Control as Control Panel
    participant API as FastAPI API
    participant OAuth as CodexOAuthConnector
    participant CLI as CodexCliRpcConnector
    participant Web as WebSessionConnector

    User->>Control: 打开 Token BI
    Control->>API: GET diagnostics
    API->>OAuth: detect local auth
    API->>CLI: detect codex app-server
    alt local auth usable
        API-->>Control: 可直接同步
    else auth missing
        API-->>Control: 引导完成 Codex 登录授权
        User->>Control: 执行授权或 Web Session 登录
        Control->>Web: fallback login if needed
    end
```

## 9. 刷新与退避

### 9.1 成功刷新

- 默认刷新间隔：180 秒。
- 副屏本地状态轮询：15 秒，不触发官方接口。
- 手动同步：直接请求协调器执行一次上游同步，并与正在运行的同步任务合并。
- 成功后更新 `updated_at`、`last_attempt_at`、`last_success_at`、`next_sync_at`、`source_type`、`source_detail`。

### 9.2 失败退避

- 网络错误：保留上次成功结果，15 秒后重试一次；连续失败后回到 60 秒间隔。
- 429：保留上次成功结果，至少退避 20 秒。
- 5xx / 超时：退避 2 秒后最多重试一次，再降级或返回 stale。
- 401 / 403：进入 `reauth_required`。
- 官方结构变化：进入 `source_changed`，仅在账号身份一致时保留上次成功结果。

### 9.3 请求截止时间与反馈（2026-09-05）

- OAuth 使用现有 HTTPX 库，异步总超时覆盖连接、响应头和整个响应体；慢速连续返回字节不能无限延长请求。
- CLI 在一个 `app-server` 进程内完成初始化、账号读取、额度读取和账号复核，共用总截止时间。使用可读字节分帧，禁止 `readline()` 阻塞等待半行；结束后回收该次启动的进程及管道。
- Web CDP 连接最多等待 5 秒；页面内直接 fetch 最多等待 5 秒，包含读取响应体，并在结束或超时后中止。网络响应采集改在 `requestfinished` 之后读取，避免在响应体尚未结束时阻塞监听器。
- 看板本地 GET 上限 8 秒，手动同步 POST 上限 50 秒；超时后按 15 秒本地轮询周期恢复。支持无 AbortController 环境的 Promise 截止时间，忽略迟到响应；网络恢复、页面重新可见或从浏览器页面缓存恢复时主动读取状态。
- 只有 `state=ready` 且有指标时才显示“额度已同步”。`stale`、`reauth_required`、`rate_limited`、`source_changed` 等即使 HTTP 为 200 也必须显示相应失败或等待状态。
- 控制台分别展示进程是否存在、主服务状态接口是否健康、最近一次额度同步是否成功。本机入口可访问不代表副屏网络已验证。

## 10. API 设计

访问边界（2026-09-05）：

- 局域网保留 `GET /api/v1/dashboard`、`POST /api/v1/dashboard/refresh`、健康探测和看板静态资源。
- 账号、会话和诊断接口仅允许回环地址，包括 `127.0.0.1`、`::1` 和 IPv4-mapped IPv6 回环地址。不得通过伪造 Host 或跨站 Origin 绕过限制；控制台 HTTP 服务使用同样的本地管理规则。
- 副屏账号信息只含内部账号 ID、脱敏名称和状态，不返回 session 路径或身份键。公开同步接口不再触发浏览器最小化操作。
- `runtime-status` 始终提供同步 `state`、`message`、`has_data` 和成功时间，不能以 usage 对象是否存在作为“已同步”的判断。

### 10.1 `GET /api/v1/dashboard`

返回当前账号看板 payload。

参数：

- `account_id` 可选。

行为：

- 只读取 `UsageSyncCoordinator` 当前状态，禁止调用 OAuth、CLI RPC 或 Web Session。
- 服务重启后可先返回磁盘中的最后成功快照，并标记为 stale。
- 返回 `last_attempt_at`、`last_success_at` 与 `next_sync_at`，供副屏展示真实同步状态。

### 10.2 `POST /api/v1/dashboard/refresh`

手动同步 usage。

行为：

- 请求协调器立即读取主链路。
- 若已有同步正在运行，则等待并复用同一次结果，不重复请求官方接口。
- 失败时按退避和 stale 规则返回。

### 10.3 `GET /api/v1/diagnostics`

返回控制台诊断信息。

新增诊断项：

- `codex_auth_available`
- `codex_cli_available`
- `oauth_connector_ready`
- `cli_rpc_connector_ready`
- `web_session_available`
- `last_connector_error`

### 10.4 `POST /api/v1/account-session/login`

保留现有接口，但语义调整：

- 恢复 Token BI 接入后先尝试可用的 OAuth / CLI；成功时直接显示当前账号，无需打开 Chrome。
- 没有可用本机登录态或明确需要授权时才进入 Web Session 登录。网络错误或限流不应误导用户重新登录。

### 10.5 `POST /api/v1/account-session/logout`

行为：

- 删除 Token BI 内账号记录。
- 清理 Token BI 侧缓存。
- 关闭 Token BI 管理的 Web Session worker。
- 持久化暂停接入；主服务重启或副屏手动刷新均不得重新自动绑定账号。
- 不删除、改写或退出用户的 Codex App / CLI OAuth 凭据。仅本机显式登录操作恢复接入。

### 10.6 本地进程生命周期（2026-09-05）

- 停止服务统一使用 `app/process_lifecycle.py`；采用 `psutil==7.2.2` 的结构化进程信息与 PID 复用保护，不再按端口批量杀进程或使用 `pkill -f` 模糊匹配。
- 开发服务必须同时匹配进程所有者、Python 入口和项目路径；正式 App 的后端校验实际可执行文件路径。强制终止前再次核验身份；身份未知时保留进程及 PID 记录并提示失败。
- Chrome 清理只匹配 Google Chrome 主进程和完整 `--user-data-dir` 路径，不处理用户的普通浏览器 profile。
- 开发启动、停止脚本共用 `TOKEN_BI_APP_DATA_DIR`，默认使用项目目录的数据和 PID 文件；不与已安装 App 的 Application Support 数据目录混用。
- 无需手工迁移：旧账号文件默认接入开启，新字段首次写入时补齐；有身份键变化时旧快照自动失效。修复随 v1.1.3 发布，升级直接替换 App，保留现有运行数据。

## 11. 敏感数据与日志

### 11.1 禁止写入普通日志

- access token
- refresh token
- cookie
- 邮箱明文
- 账户 ID 明文
- 官方完整 usage 原始响应
- `raw_window` 完整内容

### 11.2 允许写入日志

- connector 名称。
- source_type / source_detail。
- 字段名摘要。
- HTTP 状态码。
- 错误类型。
- 脱敏账号标识。

### 11.3 raw_window 使用边界

- 仅用于内存态排障、解析适配和必要调试。
- 不长期落库。
- 不跨进程保存。
- 如需导出问题样本，必须先脱敏并由用户明确确认。

## 12. 本地验证计划

### 12.1 单元测试

- OAuth auth 文件不存在时跳过到下一 connector。
- OAuth token 过期时返回 `reauth_required`。
- OAuth 返回单窗口时只生成一个 metric。
- CLI RPC 不存在时跳过到 Web Session。
- Web Session 仅在主链路不可用时触发。
- 官方新增未知窗口时可渲染。
- 官方返回 0 时显示 0。
- 未返回窗口时不补 0。
- 日志脱敏测试。

### 12.2 API 测试

- `GET /api/v1/dashboard` 返回动态 `metrics[]`。
- `POST /api/v1/dashboard/refresh` 绕过缓存。
- `GET /api/v1/diagnostics` 返回 OAuth / CLI / Web Session 状态。
- 结构变化时返回 stale + 错误信息。

### 12.3 前端测试

- 单窗口指标卡渲染。
- 多窗口指标卡渲染。
- 未知窗口名称兜底展示。
- 数据源标签展示。
- 错误态和 stale 态展示。
- iPhone 5s 横屏布局不溢出。

### 12.4 本地集成验收

- 已登录 Codex CLI：不打开 Chrome 即可刷新。
- 未登录 Codex CLI：控制台展示授权引导。
- OAuth 失败但 Web Session 可用：自动降级并说明原因。
- 断网：保留上次成功结果。
- 429：退避，不连续猛刷。

## 13. 迁移策略

### 13.1 代码迁移

- 新增 OAuth / CLI connector，不删除 Web Session connector。
- 调整 connector 优先级。
- 调整 payload 模型和前端动态渲染。
- 删除对固定 `session_*` / `weekly_*` 的强依赖。

### 13.2 数据迁移

- 无 usage 历史数据迁移。
- 账号记录可沿用现有 `accounts.json`。
- Web Session profile 保留为兜底能力。

### 13.3 用户迁移

- 已有用户升级后优先尝试本机 Codex 登录态。
- 若未发现本机登录态，控制台引导完成一次 Codex 授权。
- 原有 Web Session 登录能力保留为 fallback。

结论：无历史 usage 迁移，直接替换刷新主链路。

## 14. 交付检查清单

- [x] 技术架构文档与 PRD 一致。
- [x] `README.md` 更新 1.0.0 数据源方向。
- [x] `TECH_ARCHITECTURE.md` 指向本版本文档。
- [x] `CHANGELOG.md` 增加 v1.0.0 设计项。
- [x] OAuth connector 单元测试通过。
- [x] OAuth connector 本机 auth usage endpoint 探测通过。
- [x] CLI RPC connector 单元测试通过。
- [x] CLI RPC connector 本机 app-server 字段探测通过。
- [x] Web Session fallback 测试通过。
- [x] Dashboard 动态窗口渲染测试通过。
- [x] 控制台展示数据源链路与刷新后 connector 来源。
- [x] `raw_window` / token 不进入 DashboardPayload 输出测试通过。
- [x] connector 降级诊断错误脱敏测试通过。
- [x] 本地临时集成验收不调用 BrowserWorker 完成 CLI RPC 常规刷新。
