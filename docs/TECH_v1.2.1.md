# 1.2.1 技术实施与验证

日期：2026-09-14。依据 [PRD](PRD_v1.2.1.md) 与用户通过的 HTML 原型。

## 架构与范围

- `menubar.rs` 继续负责托盘、主窗口与服务生命周期，不把下载实现塞入前端或 Python 控制服务。
- `menubar/onboarding.rs` 独立创建 284 × 214 逻辑点引导窗口；复用 AppKit 定位和裁剪。页面就绪才展示，不等待服务健康或账号同步。不申请通知中心权限。
- 引导完成标记为 Tauri app-data 下的 `menubar-onboarding-v1`。测试时可用既有 `TOKEN_BI_APP_DATA_DIR` 隔离。显式关闭/确认/打开主面板才持久化；不按版本重复提示。
- `menubar/updates.rs` 是唯一更新状态持有者。进程启动 10 秒后检查，此后正常 6 小时一次；失败按 60 秒起指数退避，上限 1 小时。只检查，不自动下载、安装或唤起面板。
- 设置通过受限本地 IPC 发起 check/download/install，既有轻量轮询读取更新快照；更新独立于 backend 就绪状态。
- 官网签名检查由 Tauri Updater 执行。通过校验的大包存放在私有临时文件中，稍后安装前核验摘要，避免长期驻留内存和文件被替换。
- 下载期间服务继续运行；安装需二次明确点击“重启完成更新”。安装前检查 App 安装目录可写并停止本实例拥有的服务。安装中禁止普通退出及账号/服务操作，成功后由 Tauri 重启；失败显示原因并尝试恢复已停止的服务。
- 无管理员提权或静默强制安装。DMG/只读目录不能原位升级，须先复制 App 到可写目录。安装失败不承诺所有系统/磁盘故障均能自动回滚，应保留手动 DMG 恢复路径。
- `model.mjs` 将状态映射为文案/操作，版本说明使用 textContent，不执行 Release 内的 HTML。已知更新不因一次检查失败而消失。
- 原 `pinned` 状态、命令、设置和图钉资源全部删除。主面板失焦即隐藏，未加入鼠标离开即关闭的干扰行为。

## 精简依据

| 项目 | 判断与处理 |
| --- | --- |
| `@tauri-apps/api` / JS `plugin-updater` | 未被静态模块导入；已有全局 Tauri IPC，更新使用 Rust 插件。删除 npm 依赖，不删除实际启用的 Rust Updater。 |
| 图钉与冗余图标 | 删除图钉文件；前端输出明确逐项复制资源，不复制整个 assets 目录。 |
| uvloop / watchfiles | 主服务明确使用 asyncio，生产不启用 reload。仅从 PyInstaller 包排除，不更改开发依赖。 |
| Playwright / Node 驱动 | 浏览器登录与 Web 兜底仍依赖，保留；不以破坏兜底换取包体数字。 |
| 测试、原型与文档 | 原本不进入 App；保留有效回归及追溯材料，不声称删文档能缩小安装包。 |

## 发布与密钥

- 仓库仅包含公钥。首次更新私钥保存在本机仓库外，权限 0600，不写入 Git、Obsidian 或 Release。发布者需自行安全备份；丢失后不能给旧客户端签发可信更新。
- 本地执行 `TAURI_SIGNING_PRIVATE_KEY=/path/to/key TAURI_SIGNING_PRIVATE_KEY_PASSWORD= npm run app:release:local`，先全量回归再构建、签名及隔离验证。
- `scripts/prepare_release.py` 统一制备版本化 DMG、app.tar.gz、.sig、latest.json 和 SHA256SUMS；manifest 的平台键为 `darwin-aarch64`，签名字段使用签名内容，不是文件 URL。
- `updater_artifact.rs` 使用官方 Updater、MockRuntime 和本机 HTTP fixture，下载真实签名归档、拒绝篡改，然后显式安装到临时 App 路径并运行 codesign 校验。HTTP 仅在 debug 测试中使用；生产端点/下载白名单保持 HTTPS。
- GitHub Release 应先创建 draft，上传全部资源并校验，再设为 published/latest。源码 push 本身不会触发客户端更新。
- Actions 工作流改为 arm64 验证构建并创建完整草稿，当前远端保持 `disabled_manually`；未上传私钥至 GitHub，也未擅自启用 CI。将来启用需要配置同一私钥的 Secrets。
- Runner 标签依据 [GitHub 官方列表](https://docs.github.com/en/actions/reference/runners/github-hosted-runners) 选择 macos-15，并额外断言 `uname -m=arm64`。

## 验证边界

- 浏览器测试使用拦截式 fixture 和 IPC 替身，覆盖 Chromium、WebKit；不操作真实账号或安装 App。
- 签名归档测试验证真实下载、校验、显式替换及包签名；不等同于真实运行 App 的 N → N+1 完整重启验证。
- 包内 control/backend 使用临时目录和暂停账号接入进行启停、版本、资源和二维码验证。
- 本机已安装 Token BI 正在运行，本轮不停止或替换。菜单栏跨屏/隐藏场景、用户数据保持、真实重启及副屏恢复需要实机验收。
- 不宣称启动时间、常驻内存或耗电已经改善；本轮只测量实际包体变化与功能回归。

## 本机验证记录

- Python 全量 360 项、JS 9 项、Rust 单元测试 17 项通过；Clippy `-D warnings`、rustfmt、pip check 和 diff check 通过。
- 新增更新/引导界面 46 项 Chromium/WebKit 测试；生产截图见 `design-previews/v121-qa/production/`。截图使用模拟 1.2.2 元数据，不是已发布版本或真实账户。
- 更新归档隔离测试 1 项通过：官方插件识别高版本、真实签名下载、篡改字节拒绝、确认前不替换、临时 App 显式安装及 codesign 检查。
- 正式包的 control/backend 在临时账号目录和随机端口完成启停、版本、网页、资产、二维码验证。App 深度签名和 DMG 镜像校验通过；没有停止已安装的 Token BI。
- 发布前修正临时更新包生命周期：正常退出显式丢弃，安装后在不返回的 restart 调用之前释放，退出时迟到下载不再写回状态。强制终止/系统崩溃仍可能留下系统临时文件，未增加周期性扫描进程。

| 同机测量 | 1.2.0 基线 | 1.2.1 |
| --- | ---: | ---: |
| DMG 字节 | 68,186,865 | 67,462,279 |
| control 磁盘占用 KiB | 11,132 | 11,132 |
| backend 磁盘占用 KiB | 152,352 | 149,476 |
| App 磁盘占用 KiB | 198,884 | 196,872 |

App/运行时数据由 `du -sk` 测量，受文件系统影响，不是下载大小。更新归档为 68,505,920 字节；全量更新与 DMG 压缩格式不同。

发布授权：用户于本轮明确选择“同时正式发布 v1.2.1”。先完整上传草稿并回读，再正式公开；无需启用 Actions 或上传私钥。

## 发布结果

- 2026-09-14 15:22:41 UTC 正式发布 [v1.2.1](https://github.com/gbs00/Token_BI/releases/tag/v1.2.1)，非草稿、非预发布，并已设为 latest。
- 代码提交 `fc056811eeae3c6715f246a162170819ff0062f1`，标签 `v1.2.1`。发布后的纪要补录提交不改变此构建标签。
- 5 个附件均处于 uploaded 状态，GitHub 返回的大小和 SHA-256 与本地一致；公开 updater endpoint 下载得到的 SHA-256 为 `25be055d237cb96bad5b7e4a0c06dec507d975c06b34b22fb300702fd08b23a4`，与已发布 latest.json 匹配。
- App 未覆盖本地安装。Obsidian `Token BI Roadmap.md` 已保留旧记录，补录 v1.1.3、v1.2.0、本次实现、验收边界及后续 Roadmap。
