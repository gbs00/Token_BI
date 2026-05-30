# Token BI V1.0.0 BI 看板样式优化技术纪要

日期：2026-05-24  
状态：已落地  
输入来源：`docs/design-previews/preview-b-focus-dashboard.html`、用户浏览器评论、`docs/TECH_ARCHITECTURE_V1.0.0.md`  

## 1. 目标

将 BI 看板端按夜间模式预览稿落地到生产页面，降低副屏多次观看的视觉负担，并确保用户快速读取当前额度。

本轮只处理 `/dashboard` 看板端，不调整 Tauri 控制台样式。

## 2. 需求结论

- 顶部必须存在：当前账号、数据源、下次同步、`同步额度`。
- 看板只展示 `5h 额度` 与 `周额度` 两类用户关心的额度窗口。
- 两类额度窗口为同等优先级，卡片尺寸、布局和视觉权重保持一致。
- 圆环中心为唯一额度百分比展示点。
- 卡片底部只显示后端语义的重置剩余时间。
- 未知指标、链路、日志、看板状态、刷新间隔等服务信息不属于 BI 看板职责，不展示。
- 重置时间计算逻辑不改，只调整 UI 文案与展示位置。

## 3. 技术变更

### 3.1 后端看板 payload 收敛

文件：`app/services/usage_service.py`

- 新增看板指标归一：`session -> 5h 额度`，`weekly -> 周额度`。
- 根据 `metric_type`、`display_name`、`window_minutes`、`window_seconds` 识别 5h 与周额度。
- 未识别窗口不进入 `DashboardPayload.metrics[]`，避免 BI 看板展示未知指标。

### 3.2 模板结构调整

文件：`app/templates/dashboard.html`

- 顶部状态栏改为账号、数据源、下次同步、同步按钮四元素。
- 额度卡改为圆环结构：`metric-radial` + `metric-radial-inner`。
- 删除外侧百分比、进度条、`Remaining usage window`、`Remaining` 等辅助标签。
- 删除可见的详情外链区域，避免看板出现非额度信息。

### 3.3 CSS 响应式重构

文件：`app/static/css/dashboard.css`

- 全局夜间模式，使用低亮度背景和高对比额度色。
- 桌面和横屏短屏保持双卡同屏。
- 窄屏和竖屏切换为同规格纵向卡片。
- 额度颜色由 `remaining_pct` 阶梯决定，不由 `5h 额度` / `周额度` 类型决定：`>75%`、`>50 且 <=75%`、`>25 且 <=50%`、`<=25%`。
- 使用 `100dvh`、`clamp()`、`min()` 和横屏断点降低多设备溢出风险。
- 针对 iPhone 5s / 旧版 iOS Safari 增加固定尺寸 fallback：环形图不依赖 `aspect-ratio`，568×320 横屏下使用紧凑顶部栏与 120px SVG 圆环，避免页面溢出。

### 3.4 JS 动态刷新同步

文件：`app/static/js/dashboard.js`

- 动态创建卡片时使用与模板一致的 SVG 圆环结构。
- 动态刷新时只保留可识别的 5h / 周额度指标。
- `formatRelativeDuration()` 改为中文 `重置剩余 ...` 文案。
- `同步额度` 仍然通过 `POST /api/v1/dashboard/refresh` 强制刷新。

### 3.5 iPhone 5s Safari 实测修复

输入来源：用户 2026-05-24 提供的 iPhone 5s Safari 横屏照片。

- 问题 1：旧 Safari 对 CSS `aspect-ratio`、`min()` / `clamp()` 及 CSS 饼图组合支持不足，原 `metric-radial` 容器被压成椭圆。
- 处理：改为 SVG `circle` + `stroke-dashoffset` 圆环，并保留固定宽高 fallback。
- 问题 2：568×320 横屏下顶部栏和卡片尺寸偏大。
- 处理：新增 `@media (orientation: landscape) and (max-height: 380px) and (max-width: 700px)`，压缩顶部栏、按钮、字号、卡片间距和圆环尺寸。
- 问题 3：周额度卡曾通过 `.metric-weekly` 固定为黄色，导致 99% / 100% 周额度仍显示低额度警示色。
- 处理：移除按指标类型固定颜色，服务端首屏与 JS 动态刷新均按 `remaining_pct` 写入 `tier-*` 档位类，圆环和中心百分比共用该档位色。
- 问题 4：旧版 iOS Safari 对 SVG `pathLength` 的 stroke dash 归一化支持不可靠，导致 `92%` / `99%` 等高额度在 iPhone 5s 上显示为接近固定比例的短弧。
- 处理：圆环不再依赖 `pathLength="100"`；统一使用 `r=42` 的真实圆周长 `263.89378290154264` 计算 `stroke-dasharray` 与 `stroke-dashoffset`，保证所有浏览器按同一比例渲染。
- 问题 5：圆环和中心百分比在 iPhone 5s 横屏下视觉权重偏低，用户第一眼不容易聚焦额度本身。
- 处理：按 `docs/design-previews/preview-d-emphasis-dashboard.html` 的“额度优先”方案放大圆环与中心百分比；短横屏下圆环提升到 `158px`，百分比提升到 `38px`，重置剩余时间保持当前比例与右下角样式。

## 4. 回归测试

文件：`tests/test_dashboard_page.py`、`tests/test_usage_service.py`

覆盖点：

- 顶部同步按钮仍存在，且不回退到 `Refresh`。
- 只输出 5h / 周额度，未知窗口不进入 API payload。
- 服务端初始 HTML 与 JS 动态卡片均不包含外侧百分比或进度条。
- CSS 存在 SVG 圆环图、旧 Safari fallback 和横竖屏响应式断点。
- SVG 圆环不包含 `pathLength`，`92%` / `99%` 的 dashoffset 按真实圆周长计算。
- 99% 的 5h / 周额度均进入 `tier-75-plus`，不会因周额度类型被固定为黄色。
- 周额度单卡场景仍可展示，不要求 5h 同时存在。
- 568×320 横屏模拟验证：页面尺寸为 568×320，两个圆环均为 158×158，页面无滚动溢出。

验证命令：

```bash
.venv/bin/python -m pytest tests/test_dashboard_page.py -q
.venv/bin/python -m pytest -q
```

最新结果：看板专项 `11 passed`；完整回归 `89 passed`。

## 5. 迁移与风险

无迁移，直接替换看板前端显示层。

风险：

- 若官方新增新的有效额度窗口，当前 BI 看板不会直接展示，需要先补充需求语义。
- 若后端返回窗口缺少 `reset_at`，卡片底部显示 `重置剩余未知`。

## 6. 后续事项

- Tauri 控制台样式待用户确认后单独适配。
- 控制台仍需保留“控制台 + 本地服务状态”一体化，不拆分为独立运维页。
