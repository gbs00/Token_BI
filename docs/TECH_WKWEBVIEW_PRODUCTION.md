# v1.2.6 原生网页登录接入

## 结构

Tauri 菜单栏 → Python control → Python backend → OAuth / CLI / WKWebView。

`WebSessionService` 延迟启动包内 `Token BI Web Session.app`，使用匿名 stdin/stdout NDJSON 管道，没有 TCP 调试端口。远程页面不接入 Tauri IPC，不加载验证工具的网络诊断 hook。进程随后端管道 EOF 退出；关闭 App、断开账号和更新安装都通过现有生命周期结束它。

- `native/web-session/Session.swift`：AppKit 窗口、独立 WebKit 存储、白名单导航、单次读取与超时、弹窗、唤醒及 Web 内容进程终止处理。
- `native/web-session/collect.js`：与探针共用的隔离内容世界采集器，限同源固定只读路径、禁止重定向、限制响应大小；Token 仅用于网页上下文内的请求。
- `native/web-session/NavigationPolicy.swift`：精确认证域名白名单，Sentinel 仅允许可信来源的 HTTPS 子框架。未经允许的跳转拒绝，不绕过网站认证限制。
- `app/services/web_session_service.py`：组件发现、进程所有权、管道截止时间、关闭保护和可用状态；只把事件交给现有同步协调器。
- `UsageConnectorManager`：原有来源优先级、身份一致性及按账号限流冷却。

macOS 14+ 使用专用 UUID 的持久数据存储，11–13 使用组件独立 Bundle ID 的默认持久存储。运行目录 `web-session.json` 只存 UUID（0600），无令牌副本。探针与正式组件独立，不导入旧 Chrome、Safari 或 Probe Cookie。

## 数据与交互约束

1. 用规范化邮箱的 SHA-256 核验现有单账号身份，不能以脱敏邮箱匹配。已绑定 A 时，B 的 OAuth/CLI/Web 结果不能覆盖 A；网页还需采集前后身份一致。当前身份模型不支持同一邮箱下多个组织/工作区独立额度，不能视为多租户支持。
2. 额度接口 401 时重新读取现有网页会话，最多重试一次；会话明确失效才提示登录。用户主动唤醒唯一登录窗口，读取成功后隐藏；后台读取不弹窗。导航变化和关闭会使旧结果失效。
3. 同账号失败保留成功快照及时间，不推算到期后的额度为 100%。明确断网停止降级；429 停止来源链并冷却，不以其他来源绕过限流。
4. 正常同步 180 秒，副屏 15 秒只读本机状态。Web 唤醒事件仅唤醒已有调度循环；无组件时同一循环最长 5 秒核对墙钟，错过多个周期只执行一次。
5. JSON 优先；DOM 仅在指定额度页、同一已确认账号、明确剩余百分比及重置时间下采用。无法识别时失败，不猜测。存储重置详情部分失败保留已知次数，明细未知，不补 0。
6. 断开账号先持久化暂停并使在途结果失效，再关闭组件、清除 Token BI 绑定；保留网站 Cookie 和外部凭据。服务关闭后迟到的降级不得再拉起组件。
7. Web 内容进程连续终止有 60 秒重建保护；Python 子进程失败也按 60 秒冷却。手动登录可重新唤醒；不无限后台创建窗口。

## 测试与边界

真实 WKWebView 测试用本机 HTTP fixture，不使用 Playwright 模拟引擎；验证 Cookie/Bearer、401 单次恢复、账号切换、失效会话、断网/超时/限流、部分明细、DOM、隐藏读取、持久会话重启与管道关闭。协调器用受控时钟验证唤醒，不对用户整机断网或强制睡眠。

```sh
./.venv/bin/python scripts/build_web_session.py
./.venv/bin/python scripts/build_wkwebview_probe.py
TOKEN_BI_NATIVE_WK_TEST=1 ./.venv/bin/python -m pytest -q
./.venv/bin/python scripts/verify_web_session.py --login --output dist/web-session-check.json
```

最后一条为显式真人登录验收，使用本机正式 WebKit profile，但不改写账号绑定或导出凭据；结果留本机，不进 Git。全量发布脚本还检查体积预算、无 Playwright/Node、真实签名更新归档和服务退出。

性能脚本 `scripts/benchmark_bundle.py` 仅测打包 control/backend 的隔离就绪时间，账号暂停，不能代表 UI 全启动、认证或网络延迟。WebKit 是系统运行库，不占安装包，但网页进程仍占内存；不把包体下降等同于运行内存下降。

系统最低要求经用户确认调整为 macOS 11。当前实机为 macOS 27 Apple Silicon；11–13、其他 SSO、长期会话过期、长时间常驻和真实手机网络切换仍需扩大验收。网页接口不是第三方稳定公开契约。
