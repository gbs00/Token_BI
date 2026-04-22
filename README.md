# Token BI 解决方案

补充文档：

- [SETUP.md](/Users/gbs00/我的文件夹/Projects/Token_BI/SETUP.md)：新电脑部署、日常启动、账号登录、手机访问与排障说明

## 1. 项目目标

建设一个面向 `iPhone 5s` 的轻量级移动看板，用于实时查看 `Codex` 订阅账号的额度情况，并具备多账号切换查看能力。

核心要求：

- 终端设备：`iPhone 5s`
- 展示形态：手机网页看板，支持添加到主屏幕
- 使用定位：`iPhone 5s` 作为 `Mac` 的额度副屏看板
- 刷新频率：每 `3 分钟`
- 首期重点：`Codex 订阅账号`
- 首期访问范围：仅支持 `同一 WiFi / 同一局域网`
- 多账号能力：支持多个 `Codex` 订阅账号的独立额度查看与切换

## 2. 输入模块梳理

基于幕布文档 [token bi](https://share.mubu.com/doc/3DGaWroDAp-) ，当前显示模块可归纳为：

1. `agents 切换栏（预留）`
2. `Codex 账号切换栏与当前账号脱敏信息栏`
3. `Codex 账号Usage统计`
4. `Usage 详情入口（外链跳转）`
5. `最近3条活跃session名称（建议不纳入 MVP）`

建议将上述模块正式定义为以下信息架构：

### 2.1 一级导航

- `Codex`

说明：

- `Codex` 为首期唯一页面
- 其他 agent 扩展能力不进入当前 MVP

### 2.2 二级切换

- 当前 agent 下的账号列表
- 支持单击切换账号
- 当前账号高亮显示
- 账号名称统一采用脱敏邮箱

### 2.3 主内容区

- 当前账号信息卡
- `5 小时额度`与 `剩余重置时间`
- `周额度`与 `剩余重置时间`
- `Usage 详情入口`

## 3. 核心产品判断

## 3.1 最稳妥的技术路线

`服务端实时采集 + 移动端轻量 H5 看板`


## 3.2 对“token 统计”的定义要收敛

展示口径聚焦为：

1. `订阅额度口径`
   - `5 小时额度`
   - `周额度`
   - `剩余百分比`
   - `下次重置时间`

前端应在界面上明确标记数据来源：

- `Scraped`
- `Estimated`

## 3.3 MVP 取舍建议

建议首期只突出“当前最关键状态”，不做历史分析能力。

MVP 保留：

- 多账号切换
- `5 小时额度`
- `周额度`
- `剩余百分比`
- `下次重置时间`
- `最近更新时间`
- `Usage 详情入口`

MVP 不做：

- `7 日用量柱状图`
- `7 日 skills 用量统计`
- `最近 3 条活跃 session 名称`
- 任意 usage 历史落库

## 3.4 设备关系定义

本项目中，`iPhone 5s` 的角色应定义为：

`Mac 上 Codex 账号额度的副屏看板`

这意味着：

- 手机展示的不是“Mac 屏幕截图”
- 手机读取的也不是“iPhone 本地额度”
- 手机看到的是 `Mac` 侧服务实时拉取到的同一账号额度数据

因此，本方案关注的是“账号级额度”，不是“Mac 本机某个进程的内部瞬时状态”。

如果目标是展示：

- `5 小时额度`
- `周额度`
- `重置时间`

那么手机完全可以准确展示，只要它读取的是 `Mac` 侧服务产出的同一账号数据。

## 3.5 同 WiFi 准确展示的前提

`iPhone 5s` 与 `Mac` 处于同一 WiFi 下，可以不通过数据线直接访问看板，但需要满足以下前提：

- `Mac` 上运行一个本地服务，负责读取 Codex 当前账号额度
- 该服务监听的是局域网可访问地址，而不是仅 `127.0.0.1`
- `iPhone` 通过 Safari 访问 `Mac` 的局域网地址或本地域名
- `Mac` 防火墙允许该端口访问
- 路由器没有开启客户端隔离
- `Mac` 在看板使用期间保持在线且不休眠

要特别说明：

- “同一 WiFi” 只代表手机可以访问 `Mac`
- 不代表手机会自动知道 `Mac` 上的 Codex 额度
- 真正让数据准确的前提，是 `Mac` 侧服务拿到的就是你正在使用的那个 Codex 账号数据

## 3.6 准确性验收标准

首期建议把“准确展示”定义为：

- 手机展示的是 `Codex 账号级当前额度`
- 允许 `0-3 分钟` 的刷新延迟
- 不承诺任务级、秒级、进程级实时状态
- 当采集失败时，允许展示“上次成功结果 + 过期标记”

## 4. 无历史存储原则

本方案中的“不存储数据”，建议明确定义为：

- 不存储 usage 历史快照
- 不存储 7 日趋势数据
- 不做 skills 历史统计
- 不保存分析报表

但以下最小信息仍需要保留，否则无法实现多账号切换：

- 账号别名
- 最小鉴权配置
- 加密后的 API Key 或登录态 session

如果连这些都不持久化保存，那么服务重启后需要重新逐个账号登录，MVP 可用性会明显下降。


## 5. 推荐系统架构

```mermaid
flowchart TD
    A["iPhone 5s H5 Dashboard"] --> B["Dashboard API (Run on Mac or Remote Host)"]
    B --> C["Long-Lived Browser Workers"]
    B --> D["In-Memory Cache (Optional, 30-180s)"]
    B --> E["Usage Connector Manager"]
    E --> F["Local Codex Connector (Optional)"]
    E --> G["Live Browser Connector"]
    G --> H["Codex Analytics Web"]
```

### 5.1 架构分层

#### A. 移动端展示层

职责：

- 渲染单账号和多账号看板
- 提供 agent 切换与账号切换
- 展示最近刷新时间
- 自动轮询刷新
- 作为 `Mac` 的副屏展示终端

建议：

- `SSR + 少量原生 JavaScript`
- 避免重前端框架依赖
- 优先兼容 `Safari iOS 12`

#### B. Dashboard API 层

职责：

- 向移动端输出极简 JSON
- 做账户鉴权
- 聚合实时读取到的当前指标
- 屏蔽底层采集差异
- 提供详情页跳转链接

建议技术：

- `FastAPI`
- 或 `Node.js + Express/NestJS`

默认部署建议：

- MVP 默认部署在 `Mac` 本机
- `iPhone 5s` 通过局域网访问该服务
- 不需要数据线连接
- 访问形式可为 `http://<mac-lan-ip>:<port>` 或本地域名
- 启动方式先采用手动启动
- 只要用户不主动关闭服务，服务就持续运行

#### C. Long-Lived Browser Workers

职责：

- 为每个账号维护一个长驻浏览器会话
- 由用户在该会话中手动登录 `Codex`
- 保持浏览器窗口和上下文存活，供后台定时读取 usage
- 不依赖“浏览器关闭后仍可复用 cookie”作为主前提

建议：

- 采用 `Playwright persistent context + headful browser`
- 一个账号一个独立 context 和独立窗口
- 服务运行期间不主动关闭该 worker
- 服务重启后允许重新登录，不把“跨重启复用登录态”视为 MVP 必须能力

#### D. In-Memory Cache

职责：

- 为最近一次读取结果提供 `30-180 秒` 短时缓存
- 避免同一时刻重复抓取
- 服务重启后可直接丢失，不做持久化

建议：

- 可选，不是必需
- 可以直接使用进程内缓存
- 只保留内存态结果，不跨重启持久化

#### E. 实时连接器层

职责：

- 实时读取 `Codex` 订阅账号当前额度数据
- 统一调度多个 usage connector
- 只读取当前看板需要的字段，不做全量抓取

## 6. 数据源策略

参考 `CodexBar` 的启发，MVP 不应把“网页抓取”写死为唯一数据源，而应采用：

`Usage Connector Manager + 多源 fallback`

建议固定顺序为：

1. `Local Codex Connector`
2. `Web Session Connector`
3. `Web DOM fallback`

其中：

- `Local Codex Connector` 是增强型入口，用于未来接入本机 Codex/CLI 侧快照
- `Web Session Connector` 是当前 MVP 的主路径
- `Web DOM fallback` 是 `Web Session Connector` 内部的最后一级降级，而不是独立主连接器

### 6.1 Local Codex Connector

适用对象：

- 未来需要接入本机 Codex/CLI usage 快照的场景

来源：

- 读取本机标准化 usage snapshot
- 如果当前账号没有本地 snapshot，则直接跳过

当前定位：

- 作为增强型 connector 预留
- 当前 MVP 不依赖它才能工作
- 主要作用是给后续接入更稳定的数据源留接口

### 6.2 Web Session Connector

适用对象：

- `Codex` 订阅账号

来源：

- 维护独立登录态
- 按请求实时访问 analytics 页面
- 优先读取页面请求接口
- 接口不可见时降级抓 DOM

建议技术：

- `Playwright`

关键策略：

- 每个账号一个独立 session 容器
- 不混用 cookies
- 单次只抓当前看板需要的字段
- 必要时对同一账号做短时缓存

### 6.3 页面抓取的优点

- 实现门槛低，最符合当前 `Codex 订阅账号` 的 MVP 范围
- 不需要自建 usage 历史库
- 可以直接围绕你关心的字段抓取，如 `5 小时额度`、`周额度`、`重置时间`
- 手机端不需要接触账号凭证，所有敏感登录态都只留在 `Mac` 侧
- 适合做“Mac 副屏额度看板”这种轻量场景

### 6.4 页面抓取的缺点

- 对页面结构和接口变化敏感，页面改版后可能失效
- 必须维护长期有效的登录态
- 稳定性弱于官方 API
- 抓取失败时需要良好的降级策略，否则看板会空白
- 多账号越多，抓取和鉴权管理越复杂

结论：

对于当前已确认的 MVP 范围，页面抓取是可接受且最现实的方案，但应被定义为：

`可落地的工程方案，不是长期最优的数据接口方案`

### 6.5 为什么要做 connector 架构

这样设计的主要原因是：

- 与 `CodexBar` 的多源 fallback 思路一致
- 不把 `Playwright + 页面抓取` 固化成唯一实现
- 后续如果发现更稳定的本机接口、CLI 输出或 OAuth 通道，可以直接新增 connector
- 多账号主链路仍保持 `一个账号一个独立 session context`

因此，当前代码实现应遵循：

- `Usage Service` 不直接依赖单一 `Scraper Service`
- 统一由 `Usage Connector Manager` 选择可用 connector
- `Scraper Service` 只负责 `Web Session Connector` 的底层抓取

### 6.6 关于 Usage 详情跳转

MVP 可以提供 `Open Usage` 按钮，但需要明确边界：

- 对 `Codex` 订阅账号，如果手机本地没有登录同一账号，外链不一定能直接打开到目标数据
- 因此外链只能作为辅助入口，不能替代看板主数据
- 看板主数据仍应来自服务端实时采集结果

## 7. 标准化数据模型

建议统一为“当前态模型”，只用于接口返回或短时内存对象：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `account_id` | string | 平台内唯一账号 ID |
| `account_alias` | string | 内部兼容字段，默认等于 `masked_email` |
| `provider` | string | 固定为 `codex` |
| `source_type` | string | 如 `scraped / local_snapshot` |
| `source_detail` | string | 如 `network_response / script_json / dom_fallback / local_snapshot_json` |
| `connector_name` | string | 如 `web_session / local_codex` |
| `is_estimated` | boolean | 是否为估算值 |
| `updated_at` | datetime | 最近更新时间 |
| `session_remaining_pct` | number | `5 小时额度`剩余百分比 |
| `session_reset_at` | datetime | `5 小时额度`重置时间 |
| `weekly_remaining_pct` | number | `周额度`剩余百分比 |
| `weekly_reset_at` | datetime | `周额度`重置时间 |
| `usage_detail_url` | string | Usage/Analytics 详情页入口 |

## 8. 前端展示方案

## 8.1 页面结构

### 顶部标题栏

- 显示 `Codex`
- 保持单标题布局
- 不在 MVP 中引入多 agent tab

### 账号切换栏

- 横向滚动胶囊按钮
- 每个按钮宽度固定
- 支持显示脱敏邮箱，如 `guo****@gmail.com`

### 当前账号信息卡

建议字段：

- `Codex`
- 当前账号脱敏信息
- `Updated just now`
- 数据来源标记，如 `Scraped`

### 额度卡片

首期只保留两条主进度：

- `5 小时额度`
- `周额度`

每条包含：

- 左侧标题
- 主进度条
- 左下角剩余百分比
- 右下角重置时间，如 `Resets in 5h`

### Usage 详情入口

- 提供单个按钮或轻量链接
- 文案建议：`Open Usage`
- 用于打开对应 usage / analytics 页面
- 需在界面上提示“可能需要同账号登录”

## 8.2 iPhone 5s 适配约束

`iPhone 5s` 重点约束：

- 屏宽按 `320px` 设计
- 触控区域需足够大
- 文本层级要少
- 不宜使用复杂动画
- 不宜加载大型 JS 包

推荐设计规范：

- 页面宽度：`320px` 基准
- 主内容左右留白：`12px`
- 主标题字号：`18px`
- 次级文字字号：`11px - 12px`
- 卡片圆角：`8px`
- 进度条高度：`6px`

## 8.3 兼容性建议

- 不依赖最新 PWA 能力
- 不依赖 Service Worker 作为核心能力
- 默认以 Safari 直接访问为主
- 支持“添加到主屏幕”，但不把离线缓存作为首期能力

## 8.4 推荐访问方式

推荐把看板作为 `Mac` 的局域网副屏页面使用：

- `Mac` 上启动本地 Dashboard 服务
- `iPhone 5s` 在同一 WiFi 下用 Safari 打开对应地址
- 首次打开后添加到主屏幕
- 后续作为常驻额度副屏查看

推荐访问地址示例：

- `http://192.168.1.23:8787`
- `http://codex-bi.local:8787`

说明：

- 不需要数据线连接
- 不要求手机安装额外 App
- 如果 `Mac` 休眠或离线，手机侧页面将无法获取最新数据

## 8.5 什么叫 Mac 本地部署

这里的 `Mac 本地部署`，不是指把网页文件复制到 `iPhone 5s` 本地运行，而是指：

- 在 `Mac` 上启动一个本地 Web 服务
- 这个服务负责抓取 `Codex` 账号 usage 数据
- 同时对外提供一个局域网可访问的网页地址
- `iPhone 5s` 通过同一 WiFi 访问这个地址来显示看板

因此更准确的理解是：

`网页运行在 Mac 上，iPhone 只是远程打开它`

这不是以下几种方式：

- 不是把网页安装到手机本地
- 不是把 Mac 浏览器页面镜像到手机
- 不是通过数据线同步页面

而是：

- `Mac = 数据采集器 + 本地网页服务`
- `iPhone 5s = 局域网中的显示终端`

举例：

- `Mac` 上启动服务后地址为 `http://192.168.1.23:8787`
- `Mac` 自己浏览器打开这个地址，可以看到看板
- `iPhone 5s` 在同一 WiFi 下打开同一个地址，也可以看到同一个看板

所以从使用体验上看，像是“把页面放到了手机上”，但技术上其实是：

`iPhone 正在访问 Mac 本地运行的网页服务`

## 9. 页面接口草案

### 9.1 获取 Agent 列表

`GET /api/v1/agents`

返回示例：

```json
{
  "items": [
    { "key": "codex", "label": "Codex", "enabled": true }
  ]
}
```

### 9.2 获取某 Agent 下账号列表

`GET /api/v1/accounts?provider=codex`

返回示例：

```json
{
  "items": [
    {
      "account_id": "acc_001",
      "account_alias": "guo****@gmail.com",
      "is_default": true
    },
    {
      "account_id": "acc_002",
      "account_alias": "dev****@outlook.com",
      "is_default": false
    }
  ]
}
```

### 9.3 获取单账号看板

`GET /api/v1/dashboard?provider=codex&account_id=acc_001`

返回示例：

```json
{
  "provider": "codex",
  "account": {
    "account_id": "acc_001",
    "account_alias": "guo****@gmail.com"
  },
  "summary": {
    "updated_at": "2026-04-21T22:12:00+08:00",
    "source_type": "scraped",
    "is_estimated": false
  },
  "metrics": [
    {
      "metric_type": "session",
      "label": "5小时额度",
      "remaining_pct": 100,
      "reset_at": "2026-04-22T03:00:00+08:00"
    },
    {
      "metric_type": "weekly",
      "label": "周额度",
      "remaining_pct": 92,
      "reset_at": "2026-04-28T00:00:00+08:00"
    }
  ],
  "detail_links": [
    {
      "label": "Open Usage",
      "url": "https://chatgpt.com/codex/cloud/settings/analytics#usage",
      "requires_same_account_login": true
    }
  ]
}
```

## 10. 刷新策略

目标刷新频率为每 `3 分钟`。

建议采用“客户端定时刷新 + 服务端短时缓存”：

### 10.1 服务端刷新

- 不做固定后台轮询任务
- 按页面请求实时读取当前数据
- 可选增加 `30-180 秒` 内存缓存
- 失败时直接返回最近一次成功结果或错误状态

### 10.2 客户端刷新

- 页面打开后每 `180 秒` 轮询 dashboard API
- 页面切到后台后暂停轮询
- 页面重新激活时立即刷新一次
- 提供手动刷新按钮

这样可以兼顾：

- 手机端省电
- 数据基本实时
- 实现复杂度低
- 无需历史数据存储

## 11. 安全设计

### 11.1 账号安全

- 不在前端保存平台登录态
- 所有第三方登录态仅保存在服务端
- 每个账号独立 session 仓
- cookies 和 token 加密存储
- 不落库 usage 历史快照

### 11.2 访问控制

- MVP 先不增加额外访问口令
- 管理后台与移动看板分离
- 首期只支持同一局域网访问，不开放公网入口

待办：

- 后续版本再评估是否增加轻口令或单用户登录保护

### 11.3 风险提示

对于 `Scraped` 数据源，应在后台标注：

- 抓取来源
- 最近一次成功时间
- 最近一次失败原因

## 11.4 账号配置与 Session 管理方案

本方案中的多账号切换，核心不是“重新登录不同账号”，而是：

`为每个 Codex 账号建立独立的长驻浏览器 worker -> 切换账号时切换到对应 worker 抓取 usage`

### 11.4.1 配置原则

- 用户只在 `Mac` 上手动登录
- 系统不保存账号密码
- 系统只保存账号元信息与 worker 对应的 context 目录
- 每个账号必须有独立的浏览器 worker
- 账号切换本质上是“切换抓取上下文”
- MVP 不再把“浏览器关闭后仍能离线复用登录态”作为主假设

### 11.4.2 推荐配置流程

#### 第一步：添加账号

- 用户在 `Mac` 上点击 `Add Account`
- 系统拉起一个受控浏览器窗口和独立浏览器上下文
- 用户手动登录对应 `Codex` 账号
- 登录成功后，系统不关闭该浏览器 worker
- 后台直接在这个活着的会话里校验 analytics 页面是否可访问
- 校验通过后，将该 worker 视为可用数据源

#### 第二步：保存账号配置

建议保存以下信息：

- `account_id`
- `account_alias`
- `masked_email`
- `session_storage_path`
- `created_at`
- `last_validated_at`
- `status`

其中：

- `status` 建议取值为 `active / expired / invalid`
- `session_storage_path` 指向本地浏览器上下文目录，但该目录主要用于 worker 运行，不再承诺可在浏览器关闭后稳定复用
- `account_alias` 在 MVP 中不单独暴露为自定义命名，默认等于 `masked_email`

本地存储建议：

- 在项目目录下新建专用文件夹保存 session 上下文
- 建议路径：`/Users/gbs00/我的文件夹/Projects/Token_BI/runtime/contexts/`
- 每个账号单独一个子目录，避免登录态互相污染
- 目录本身不纳入版本管理

### 11.4.3 切换账号时的行为

当用户在看板上切换账号时，系统应执行：

1. 定位该账号对应的长驻浏览器 worker
2. 在该 worker 中访问 `Codex analytics / usage` 页面
3. 读取当前账号下的 `5 小时额度`、`周额度`、`重置时间`
4. 将结果返回给 `iPhone 5s` 页面

因此：

- 切换账号不是重新登录
- 切换账号也不是切换手机本地状态
- 而是切换 `Mac` 侧用于抓取的登录态上下文

### 11.4.4 建议的技术实现

建议采用：

- 每个账号一个独立浏览器 profile 或 context
- 使用普通 `Chrome/Edge` 窗口承载登录态
- 服务端通过 `CDP attach` 附着到该浏览器读取 usage
- 用户在该 worker 中手动登录
- 抓取时直接复用这个仍然活着的浏览器会话
- 不再把“关闭浏览器后复用 cookie”作为主方案
- 不再把“Playwright 直接拉起登录浏览器”作为主方案

抓取优先级建议固定为：

1. 先尝试 `Local Codex Connector`
2. 若无可用本机快照，则进入 `Web Session Connector`
3. 在 `Web Session Connector` 内部，先读取页面请求返回
4. 若不可用，再读取页面内脚本对象
5. 仍不可用，再降级读取 DOM 文本
6. 若页面请求返回与 DOM 冲突，以页面请求返回为准

原因：

- 与 `CodexBar` 的多源思路一致，但更适合当前多账号需求
- 能绕开关闭浏览器后 session 落盘不稳定的问题
- 与真实登录环境更接近
- 对前端态依赖更稳
- 更适合处理页面脚本、重定向和鉴权校验

### 11.4.5 不应保存的内容

MVP 不建议保存：

- 用户明文密码
- 可逆明文 token
- 与看板无关的浏览历史
- usage 历史数据

### 11.4.6 登录态失效后的处理

当某个账号的 session 失效时：

- 将该账号状态标记为 `expired`
- 停止继续使用该 session 自动抓取
- 页面提示用户在 `Mac` 上重新登录该账号
- 重新登录成功后，覆盖原 session 数据

## 11.5 异常处理流程

建议 MVP 统一采用：

`优先展示当前成功结果 -> 失败时回退到上次成功结果 -> 无可用结果时展示明确错误提示`

具体流程如下：

### 场景 A：正常抓取成功

- 更新当前看板数据
- 更新 `updated_at`
- 清除异常状态

### 场景 B：本次抓取失败，但存在上次成功结果

- 继续展示上次成功结果
- 页面增加 `stale` 提示
- 显示最近一次成功时间
- 后台记录失败原因
- 该“上次成功结果”只保存在内存中，不跨重启保留

### 场景 C：抓取失败，且没有任何成功结果

- 不展示伪造数据
- 直接进入错误态
- 页面提示用户检查 `Mac 服务状态 / 登录态 / WiFi`

### 场景 D：账号登录态失效

- 标记该账号为 `需要重新登录`
- 停止继续使用该账号自动抓取
- 页面在该账号卡片上显示登录失效提示

### 场景 E：手机不在同一局域网或无法访问 Mac

- 页面请求失败
- 提示用户确认是否与 `Mac` 连接到同一 WiFi
- 不将此类错误误报为账号额度异常

### 场景 F：页面结构变化导致抓取字段缺失

- 将错误归类为 `页面结构变更`
- 保留上次成功结果
- 后台提示需要调整抓取逻辑

## 11.6 推荐提示文案

建议前端预置以下提示文案：

### 正常状态

- `Updated just now`
- `Updated 2 min ago`

### 数据过期但仍可展示

- `Showing last successful update`
- `Data may be delayed`

### 登录态失效

- `Session expired on Mac`
- `Please sign in again on Mac`

### Mac 服务不可达

- `Cannot reach Mac dashboard service`
- `Check Wi-Fi and make sure Mac is online`

### 首次无数据

- `No usage data yet`
- `Open Codex on Mac and complete first sync`

### 页面抓取失败

- `Unable to read Codex usage right now`
- `Analytics page may have changed`

## 11.7 实施前确认项

以下事项已确认，可作为 MVP 实施约束：

1. 账号接入方式：`Playwright 长驻 browser worker + 用户手动登录`
2. Session 存储位置：项目目录下专用文件夹
3. Usage 获取架构：`Usage Connector Manager + 多源 fallback`
4. 抓取优先级：本机 connector 优先，Web 内部先页面请求结果，再脚本对象，最后 DOM 降级
5. 回退数据策略：只保留内存，不跨重启持久化
6. 服务启动方式：手动启动，服务不关闭则持续运行
7. 访问控制：MVP 不加额外口令，先仅限同一局域网访问

## 12. 分阶段实施建议

### P0：验证阶段

目标：

- 验证 `Codex` analytics 页面可否在长驻 worker 中稳定抓取
- 验证 3 分钟间隔重复读取时长驻 worker 是否稳定

交付：

- 单账号抓取脚本
- 原始数据样例
- 字段映射说明

### P1：MVP

目标：

- 支持 `Codex` 订阅账号
- 支持 `2-5` 个账号
- 支持以下页面模块：
  - 账号切换栏
  - 5 小时额度
  - 周额度
  - Usage 详情入口

不做：

- `7 日用量统计`
- `最近 3 条活跃 session`
- 复杂筛选

### P2：增强版

目标：

- 优化详情页跳转体验
- 增加异常提醒

### P3：进阶版

目标：

- 如果后续确实需要趋势分析，再单独评估是否引入历史存储
- 完善后台账号管理
- 增加账号状态检测
- 增加采集监控

## 13. 工期建议

如果由 1 名前后端全栈开发推进，建议节奏如下：

- `1-2 天`：数据源验证
- `1-2 天`：后端长驻 worker 与账号配置
- `1-2 天`：移动端页面
- `1 天`：联调与兼容性测试

MVP 总周期预计：

`4-6 天`

## 14. 最终推荐版本

首期推荐落地版本：

- 终端：`iPhone 5s H5 看板`
- 范围：`Codex 订阅账号`
- 功能：
  - 多账号切换
  - 当前账号脱敏信息
  - `5 小时额度`
  - `周额度`
  - `Usage 详情入口`
- 刷新：`3 分钟`
- 数据策略：
  - 基于页面抓取
  - `Mac` 侧维护最小登录态
  - `iPhone` 仅作为局域网副屏读取结果

`7 日用量统计` 与 `skills 用量统计` 都不建议进入首期版本。

## 15. 参考资料

- 幕布原始文档：[token bi](https://share.mubu.com/doc/3DGaWroDAp-)
- OpenAI 官方帮助：[Using Codex with your ChatGPT plan](https://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan)
- Apple 安全更新说明：[Apple security releases](https://support.apple.com/en-mo/100100)
- WebKit 说明：[Web Push for Web Apps on iOS and iPadOS](https://webkit.org/blog/13878/web-push-for-web-apps-on-ios-and-ipados/)

## 16. 当前输出说明

本文件默认按以下假设编写：

- 输出文档格式为 `Markdown`
- 首期目标仅为 `Codex 订阅账号`
- 不落库 usage 历史
- `Usage 详情入口` 作为辅助能力存在
- 终端形态默认是手机网页，而非原生 iOS App
- 默认部署形态为 `Mac 本地服务 + iPhone 局域网访问`
- 仅保存实现多账号所需的最小鉴权信息

如果后续要继续推进，下一步最值得补的是：

1. `PRD 详细版`
2. `Mac 本地部署说明`
3. `后台管理页原型`
4. `iPhone 5s 低保真线框图`
