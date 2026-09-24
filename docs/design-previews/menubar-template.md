# 菜单栏单色模板图标

以下保留图标迭代与本机试用的历史记录，其中“未提交、推送或发布”描述对应当时操作。用户已授权将最终左上开口版本纳入 v1.2.5 正式发布，发布范围与验证见 [更新说明](../RELEASE_NOTES_v1.2.5.md)。

日期：2026-09-24。用户选定第 2 版「双层额度环」，依次调整描边、整体大小和开口方向。当前本机为约 1.4pt 稿整体放大约 8%，再逆时针旋转 90° 的左上开口版本，与原应用图标方向一致；未提交、推送或发布。

## 设计与接入

- 完整外环、左上开口内环，空心中心；无文字、底座、渐变或动画，不用环形比例表达实时额度。
- 原素材由内置 ImageGen 根据选定设计生成，保存在 [透明源图](menubar-template-source.png)。生成要求为同心等粗双环、内环右上开口、黑色轮廓和透明负空间；加粗稿的黑白素材在导出时转换为纯黑加透明度，去掉白底。
- 生产资源：[menubar-template.png](../../src-tauri/icons/menubar-template.png)，36 × 36px，1,644 字节。当前先裁减源图透明留白，缩小为 36px 后再逆时针旋转 90°，命令见末节。
- 当前锁定的 `tray-icon 0.21.3` 将图像显示为 18pt 高，使用 36px 素材覆盖 Retina 2×。显示尺寸属于该依赖的实现，不是 Apple 强制尺寸标准。
- `menubar.rs` 仅在 macOS 使用独立资源及 `icon_as_template(true)`，由 AppKit 处理状态着色。其他平台继续使用原彩色图标；应用包、面板品牌图标保持原样。
- 保留 macOS 27 左键面板、右键快捷菜单兼容逻辑，不修改额度数据、服务启动或更新功能。不引入依赖，不在运行时生成或处理图像。

依据：[Apple 模板图像](https://developer.apple.com/documentation/appkit/nsimage/istemplate)。

## 预览与验证

- [HTML 预览](menubar-template.html)：浅色、深色与高对比背景，18pt 实际布局及放大观察。参考系统图标取自项目已有的 `lucide-static`，不进入生产包。
- [1× 离屏预览](menubar-template-native-1x.png)、[2× 离屏预览](menubar-template-native-2x.png)：使用生产 PNG 的透明度和 AppKit 深浅色 `labelColor` 绘制；每行从左到右为 18pt、2×、4× 观察。放大观察会显露低分辨率插值，不是大尺寸素材。
- 两种倍率下可辨认外环、内环与左上开口；无实心底座。离屏图用于检查资源与对比度，**不是运行中的 NSStatusItem 截图**。
- Rust 20 项测试通过，包含资源尺寸、像素占比、透明边界/中心和单色检查；`cargo fmt --check`、`cargo clippy --all-targets -- -D warnings` 通过。
- 内置浏览器拒绝本地文件 URL，未绕过策略，因此 HTML 浏览器视觉验收受阻；未宣称该预览已通过浏览器验收。
- 已重打包并覆盖本机 App，安装后账号面板与服务检查通过；实际菜单栏深浅色、选中状态、多屏与左右键行为仍待实机验收。未重跑后端完整套件，本次未修改后端。

源图与预览均只留在 `docs/design-previews`，生产构建仅嵌入小尺寸模板资源。

## 描边微加粗

用户要求稍微加粗。原版在 18pt 显示框中的有效线宽约 1pt；微调后约 1.1–1.2pt，Retina 2× 对应约 2.2–2.4 个物理像素。线宽是对抗锯齿 alpha 覆盖量的测量近似，不是 SVG 的固定 `stroke-width`。

- 保持 36px 资源和 18pt 显示框，只微调素材；双环仍分离，保留右上开口。
- [前后对比](menubar-template-weight-comparison.png) 同时展示浅色、深色和放大观察；源图、生产素材与 1×/2× 离屏预览已同步。
- 微加粗仅调整资源，没有改变 Rust 交互和数据逻辑；随后按用户确认进行下述本机替换。

## 1.2pt 本机替换与回归

- 使用 `app:sidecar` 和 Tauri release 构建，仅生成 App，不生成或上传更新制品。安装于 `/Applications/Token BI.app`，版本仍为 1.2.4，属于未发布的本地新构建。
- 构建包与安装包均通过 `codesign --verify --deep --strict`；使用现有 ad-hoc 签名，未做 Apple 公证。主程序、控制服务和后端的 SHA-256 分别核对一致。主程序 SHA-256：`ad380de2637f5d3eee282b372e8c34ecf1276463c183636fa3b13fb1ed093d0e`。
- 旧安装备份保留在 `dist/Token BI-before-menubar-template-20260924-204116.noindex`，未更改账号凭据、配置或应用数据目录。
- 替换前通过系统退出命令关闭 App，另对确认属于旧安装的孤立后端进程发送 SIGTERM。替换后仅一套应用/控制/后端进程，控制服务 8790、主服务 8787 健康检查通过。
- Rust 20 项和桌面模型 13 项测试通过；`verify_bundle.py` 在临时数据目录验证控制服务、后端、暂停访问、看板、静态资源、二维码和退出通过，包体 184,505,970 字节（不重复计算符号链接）。
- 已用原生应用工具查看安装后的 311px 额度面板：OAuth 账号、额度、存储重置倒计时与操作按钮正常。自动化未取得系统菜单栏图标截图，因此不将面板截图或离屏预览等同于真实菜单栏视觉验收；深浅色、选中状态及多屏效果仍需用户实机确认。
- 不变更版本号，不提交、推送或创建 Release；应用内更新配置保持原样。

## 1.4pt 本机试用

- 在原双环方向上增加线条视觉重量，仍使用 18pt 显示框、36px 透明模板、完整外环与右上开口内环。源图横向四处描边的 alpha 覆盖量折算约 1.33–1.38pt，标称约 1.4pt；这不是精确矢量描边值，缩小后的抗锯齿和屏幕倍率会影响观感。
- 使用内置 ImageGen 编辑。首个请求被工具拒绝，后续透明稿和首版白底稿的线宽不足，均未进入生产包；采用最后的白底加粗稿，导出时去掉白底并将深色归一化为纯黑透明度模板。没有增加生产依赖或运行时图像处理。
- [1.2pt / 1.4pt 对比](menubar-template-weight-14-comparison.png) 展示浅深色背景中的实际布局和放大观察；1×/2× 离屏预览已同步。小尺寸下仍能辨认双环与开口，但图像生成不保证与旧版几何形状逐像素相同。
- 最终编辑提示：`Make a BOLDER line-weight variant of this exact two-circle symbol. BOTH circular black bands must be visibly about 50 percent thicker than in this reference, increasing their thickness from approximately 65 image pixels to approximately 100 image pixels. Keep the same square canvas, same circle centers, same radius of the center of each black band, same upper-right opening, and rounded inner endpoints. The white separation between the two circles should become narrower as the bands become bolder, but the bands must not touch. Render just the single icon centered on an absolutely plain white background, solid pure black lines, no gradients, shadows, texture, labels, or other elements.`
- 重新执行 Rust 20 项测试、打包隔离集成检查、构建与安装包签名检查，均通过。仅图标资源变化，复用本轮前面已构建的控制/后端运行库，未改 Rust 交互或取数代码。
- 安装仍为 `/Applications/Token BI.app`，版本 1.2.4；主程序构建/安装 SHA-256 一致：`c03b15988e0cc189e689d2f7988267f114daa999f1bded629bbd2ec1cd8466c0`。
- 1.2pt 旧包备份：`dist/Token BI-before-14pt-20260924-205523.noindex`。账号配置保持原样；重启后 8790 控制服务健康，原生账号面板显示 OAuth 额度与存储重置。
- 仍未自动化核验真实菜单栏的深浅色、选中状态或跨屏表现，等待本机观感验收；不推送、不发布。

## 整体等比例放大约 8%

- 按用户要求将两个圆作为整体放大：缩减透明画布留白，不重新生成或重画双环。原 1254px 方形源图保留，居中裁成 1162px 方形，再导出为 36px，整体倍率 `1254 / 1162 = 1.07917`。
- 两个圆的直径、描边和间距一起变化，开口角度不变；菜单栏占位仍为 18pt。源图横向 alpha 覆盖量折算描边约 1.44–1.48pt，标称约 1.5pt，而不是强行维持 1.4pt。
- 裁减前后可见像素数量均为 389,308（alpha > 127），未裁掉图形。生产资源保持纯黑 RGB、透明边界和中心；[放大前后对比](menubar-template-scale-comparison.png) 及 1×/2× 离屏预览已更新。
- 仅资源导出变化，不新增运行时处理、原生接口或依赖。
- Rust 20 项、打包隔离集成检查、构建和安装包签名检查通过。版本仍为 1.2.4，构建/安装主程序 SHA-256 一致：`75e9e44cd643d149366192372c67fc2bd1a5629ca5d4902d5b9240bfee1b5875`。
- 已替换 `/Applications/Token BI.app` 并重启，控制服务健康，原生面板中 OAuth 账号、额度和存储重置正常。放大前备份：`dist/Token BI-before-scale108-20260924-210019.noindex`；账号数据未更改。
- 离屏预览不替代实际菜单栏深浅色、选中和跨屏验收，仍待用户确认观感；未推送或发布。

复现当前导出（项目根目录执行，保留右上开口源图，最终旋转与原应用图标方向对齐）：

```sh
sips --cropToHeightWidth 1162 1162 docs/design-previews/menubar-template-source.png --out dist/menubar-icon-qa.noindex/source-scale-108.png
sips --resampleHeightWidth 36 36 dist/menubar-icon-qa.noindex/source-scale-108.png --out dist/menubar-icon-qa.noindex/candidate-scale-108.png
sips --rotate 270 dist/menubar-icon-qa.noindex/candidate-scale-108.png --out src-tauri/icons/menubar-template.png
```

## 与原应用图标对齐方向

- 核对 `src-tauri/icons/icon.png`：原应用图标的内环弱化段位于左上方，约 10 点钟方向。将当前模板整体逆时针旋转 90°，开口从右上转至左上；原彩色应用图标不变。
- 仅做整数直角旋转，不重画、不缩放。旋转前后均为 36px、可见像素均为 348（alpha > 127），保留当前大小、描边、间距与透明边界。[方向对比](menubar-template-direction-comparison.png) 和离屏预览已同步。
- Rust 20 项、隔离打包集成检查及构建/安装包签名检查通过。本机 App 已替换并重启，服务健康，OAuth 账号、额度及存储重置正常；仍未自动化验证系统菜单栏深浅色和跨屏表现。
- 版本仍为 1.2.4，构建/安装主程序 SHA-256 一致：`d2c74a060d176b58e99a2043887c8cc74e104b97e3f1116c988211798038a064`。旧包备份为 `dist/Token BI-before-upperleft-20260924-210606.noindex`。没有修改账号数据、提交、推送或发布。
