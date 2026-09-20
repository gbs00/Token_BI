# 轻量 CDP 替换评估

日期：2026-09-21。状态：初步评估存档，用户明确选型确认与重构留待后续版本；v1.2.4 不替换生产 Playwright，也不新增运行依赖。

## 结论

建议使用已有 `websockets` 的同步客户端承载有限 CDP 命令，替换生产环境的 Playwright 驱动；Playwright 保留在开发依赖，继续做 Chromium / WebKit 页面回归。

这是代码与依赖层面的可行性判断，不代表已通过真实 ChatGPT 登录、挑战页面及失效恢复的等效验收。不得在实现前直接排除 Playwright 或删除 Node。

## 当前调用范围

- `BrowserWorkerService._launch_browser` 使用系统 Chrome 和 Token BI 专用 profile；没有内置 Chromium，不需要新装另一套浏览器。
- `_probe_current_url` 目前启动 Playwright 驱动只为读取 URL，可改为回环 `/json/list` 查询。
- `_scrape_via_cdp` 连接当前窗口并交给 `ScraperService`；不是浏览器自动化测试平台，不需要录制器、追踪查看器、Firefox 或 WebKit 驱动。
- `_minimize_debug_port` 只使用 `Browser.getWindowForTarget`、`Browser.setWindowBounds`。
- `ScraperService` 使用导航、重新加载、页面 JavaScript、JSON 响应监听与超时；其后的身份与额度解析逻辑可继续复用。

## 方案比较

| 方案 | 收益 | 代价与结论 |
| --- | --- | --- |
| 保留 Playwright，仅裁剪附属资源 | 改动少 | 117.7MB Node 仍在，不能解决主要体积问题；裁剪仍需处理上游模块引用 |
| 引入 pychrome 等完整 Python CDP 包 | 不需要 Node，有命令与事件分发 | 仍需适配导航等待、异常、目标身份和线程生命周期；引入另一层依赖，不能直接替换 Page API |
| 复用 websockets，增加小范围 CDP 适配 | 不需要 Node，传输协议由成熟库处理 | 需要自行明确命令应答、事件、超时和页面生命周期；推荐严格限制到当前所需能力，不复刻 Playwright |

本机已有 `websockets 15.0.1`。其同步连接支持接收超时、连接超时和消息大小限制；默认可能使用系统代理，本机 CDP 应显式设 `proxy=None`，不能依赖用户代理设置。[官方客户端文档](https://websockets.readthedocs.io/en/15.0.1/reference/sync/client.html)

候选 `pychrome` 提供事件回调和命令调用，但现有业务还需要上述适配，不能仅凭库名认定生命周期和错误行为等价。[项目文档](https://github.com/fate0/pychrome)

## 建议实现边界

1. 只增加一个小型 CDP 传输/会话模块：使用同步 WebSocket、递增请求 ID、同一连接内串行命令、事件分发、有限缓冲和全局 deadline。事件处理不得递归阻塞命令应答。
2. 目标发现用回环 HTTP；确认专用 Chrome 进程和 profile 所有权后，只附着目标页面。过滤扩展、DevTools 等页面；不对日常浏览器发命令。只有明确需要时才在专用实例新建页面。
3. 使用 `Page` / `Runtime` / `Network` 域完成导航、页面内容与响应采集；窗口操作使用 `Browser` 域。优先使用稳定命令，开发版协议可能变化，需限定测试过的 Chrome 版本并保留清晰错误。[CDP 官方协议](https://chromedevtools.github.io/devtools-protocol/)
4. 页面内同源只读请求继续使用浏览器登录态，不导出 Cookie / Token；现有 usage、身份解析、DOM 降级和账号隔离规则保持不变。响应体在 `loadingFinished` 后读取，处理重定向、失败和 base64 编码，并限制匹配 URL、条数与累计字节。[Network 协议](https://chromedevtools.github.io/devtools-protocol/tot/Network/)
5. 页面导航必须区分主框架和旧 loader 的事件，处理 hash 路由刷新、执行上下文销毁、挑战页面与登录跳转；不能用固定 sleep 代替状态等待。
6. 临时连接退出只断开 WebSocket，不发送 `Browser.close`。真正关闭浏览器仍由现有、经过所有权验证的进程管理负责。
7. 保持 OAuth > CLI > Web 的协调器逻辑。OAuth 暂时网络失败不能被新 CDP 重试循环覆盖，不提高官方请求频率，不阻塞控制台启动。

## 依赖与体积

- 将 Playwright / pytest / PyInstaller 移到开发依赖清单，生产显式声明实际使用的 websockets 版本范围；不依赖 uvicorn 的间接依赖关系。
- 清除生产代码对 Playwright 异常类型的引用，以项目的超时/断线异常承接；不保留一个“隐藏启动 Playwright”的包装器。
- 验证 PyInstaller 输出不包含 `playwright/driver/node`，保留包体清单检查。
- 本轮重复打包修复后 App 实测 188.7MB，其中驱动约 130.1MB。若完整去掉该驱动，算术基线约 58.6MB；含新适配及依赖的目标可先定为 **60–80MB**，这是预估，不是已构建结果。
- 可能减少 Web 兜底时的 Node 启动和连接开销，但不能据此承诺整体 App 启动变快：OAuth 主路径本来就不预热 Playwright。

## 实施与验收门槛

用户确认后先在隔离 profile 和本地测试服务上验证，再做生产接入，最后用真实网页登录验收。至少覆盖：

- 无 OAuth/CLI 时仍能打开专用 Chrome，手动登录并读取身份、额度及重置时间。
- 同一路由反复刷新、请求中断、Chrome 被关闭、过期登录、挑战页面、403/429、页面结构变化的错误归因。
- 网络 JSON、脚本 JSON、DOM 降级结果与现有解析器一致；不能把缺失额度当成 0%，不能返回另一个账号的数据。
- 进程/profile 所有权、回环代理隔离、页面目标筛选、断开不关闭用户浏览器。
- 事件乱序、断线、超时、超大响应、重连后旧事件，以及退出时的资源释放。
- 冻结包运行，菜单栏与副屏恢复，App/DMG/Updater 完整验收；认证信息不进入日志、快照或安装包。

验收完成后再从生产依赖彻底移除 Playwright；不保留两套常驻抓取链路。真实网页登录验证需要用户手动完成认证，本轮未操作任何真实账号。
