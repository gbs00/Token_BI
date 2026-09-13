# 横屏优先的自适应看板

日期：2026-09-13。状态：源码与独立预览已完成，现纳入 1.2.0 发布范围；本文保留实现阶段的验证记录，发布结果见 [1.2.0 说明](RELEASE_NOTES_v1.2.0.md)。

## 需求与原因

用户反馈：5S 能完整显示，但其他手机需要向下滚动；闲置设备横屏常驻为主要使用场景。

原样式在宽度不超过 700px、高度不超过 380px 的小横屏取消卡片最小高度；其他矮横屏仍要求卡片至少 330px。加上顶部栏和页面内边距，较宽手机反而可能溢出。竖屏每张卡片至少 410–430px，双额度自然超过一屏。页面最小高度使用视口单位，但卡片没有分享扣除顶部栏后的剩余高度。

验收目标：正常字号下，常见横屏单/双额度一屏可读，竖屏兼容；不按手机型号分支。保留账号、来源、下次同步、同步按钮、额度和重置时间；不裁切异常说明或抵消用户放大操作。

## 实现

- `app/static/css/dashboard.css`：页面按可见高度分配顶部和主体；主体用弹性布局，额度区用等分 Grid。横屏双列、手机及平板竖屏单列，单额度独立居中。删除固定卡片最小高度和 5S 尺寸分支，保留图表区域 128px 的最低高度以保护可读性。
- `app/static/js/dashboard.js`：优先读取 `visualViewport.height`，无此接口时回退 `innerHeight`；CSS 提供 `dvh` / `vh` 初始值。旋转、resize、pageshow、字体就绪、内容更新和受支持的 ResizeObserver 触发同一个 requestAnimationFrame 合并调度，不增加网络请求或轮询。
- 圆环按额度卡片图表区域的实际宽高中较小者取整，最大 360px，宽高同步。SVG 继续使用实际周长 263.89378290154264，不更改额度比例算法或颜色阶梯。
- 数字使用 32/42/54/68px 离散字级，依据图表容器容纳能力选择，不按屏幕宽度线性缩放字体。重置时间保持 14px，手机同步按钮最低 44px。
- 安全区域留白作用于普通浏览器和主屏 Web App。空间不足、长错误消息或放大字体时保留文档滚动，不用 overflow 隐藏内容。
- `visualViewport.scale` 不为 1 时不重设页面高度，避免抵消双指缩放。减少动态效果时使用 `transition: none`，不再给所有元素添加极短的尺寸过渡。
- HTML 静态资源标识更新为 `20260913-fit-viewport`。后端采集、账号、同步频率、超时恢复、重置计算、菜单栏页面均不变。

## 验证与边界

新增 `tests/test_dashboard_layout.py`，58 项 Chromium/WebKit 行为测试通过：

- 568×320、667×375、844×390、844×320、896×414、932×430、1024×768、1920×1080，以及 320×568、390×844、430×932、768×1024；每组检查单/双额度、文档溢出、正圆、数字处于内圈、重置时间与图表互不遮挡。
- 连续旋转、双额度变单额度、旧视口接口缺失、模拟地址栏变化与双指缩放、长错误消息/极矮窗口滚动、暗色主题与额外安全区留白。
- 布局变动不触发额外获取额度请求；运行期间无页面脚本异常。保留原看板渲染和同步恢复测试。

截图位于 `docs/design-previews/dashboard-qa/`。WebKit 为当前 Playwright 版本，不等同于 iOS 12 Safari；隐藏新版 API 的测试仅验证回退分支，不代表已完成 5S 真机验收。真实刘海安全区、浏览器工具栏动画及手机设备互访仍需用户验证。

最终回归：使用隔离数据目录 `/tmp/token-bi-responsive-regression-20260913` 运行完整 Python 测试，305 项通过（83.16 秒）；菜单栏 JS 展示规则 7 项通过，`node --check` 及 `git diff --check` 通过。Rust 代码未修改，本轮未重跑 Rust 测试或打包。

## 独立预览

`scripts/preview_dashboard.py` 直接渲染正式模板和静态资源，仅提供示例 JSON，不导入生产容器、不读取账号凭据、不启动采集器；刷新按钮只返回示例数据。默认绑定回环，可显式指定 LAN 监听供手机验收：

```sh
./.venv/bin/python scripts/preview_dashboard.py --host 0.0.0.0 --port 8899
```

- 双额度：`/dashboard?theme=dark`。
- 单额度：`/dashboard?theme=dark&windows=1`。
- 浅色：将 `theme=dark` 改为 `theme=light`。

8899 是临时预览端口，已安装 App 仍使用 8787。预览请求返回 200 只证明本机可达，不保证其他设备穿过防火墙或 Wi-Fi 隔离。

```sh
TOKEN_BI_VISUAL_QA=1 ./.venv/bin/pytest -q tests/test_dashboard_layout.py
./.venv/bin/pytest -q tests/test_dashboard_page.py tests/test_ui_recovery.py
node --check app/static/js/dashboard.js
```
