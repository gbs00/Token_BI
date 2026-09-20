# 包体与工作区精简

日期：2026-09-21。初次精简使用本地 1.2.3 候选构建完成验证，未覆盖已安装 App。用户随后授权随 v1.2.4 发布，以下尺寸、清理和验证为初次实施记录；正式发布结果见 [v1.2.4 发布回执](releases/v1.2.4-verification.md)。

## 运行库打包

原 App 实测约 200.4MB。两个 Python sidecar 中的 framework 链接经 `bundle.resources` 逐文件复制后变成重复实体文件，每个 runtime 多出两份约 2.9MB 的 Python 库。

改为 `bundle.macOS.files`，目标仍是原有 `Contents/Resources/*-runtime`，不改变 launcher 路径或进程拆分。此路径在 Tauri CLI 2.10.1 中使用保留符号链接的目录复制，且发生在签名前；不需要签名后修包或新增解压启动流程。[Tauri 目录复制实现](https://github.com/tauri-apps/tauri/blob/tauri-cli-v2.10.1/crates/tauri-bundler/src/utils/fs_utils.rs#L95)

新构建实测：

| 部分 | 字节数 |
| --- | ---: |
| App 合计 | 188,708,466 |
| 原生可执行文件 | 24,411,360 |
| control runtime | 11,245,074 |
| backend runtime | 152,052,184 |

合计约 188.7MB，减少约 11.7MB。体积统计不重复计算符号链接；不同于 APFS 实际独占磁盘空间。

`scripts/verify_bundle.py` 新增链接完整性、路径边界、退役页面及 195MB 体积上限检查。两个 runtime 仍各有一套必要运行库，本轮不合并进程，不为减少几 MB 重新耦合启动链路。

## 退役代码

- 删除旧 `scripts/control_panel.html` 与两个打开该页面的脚本，control sidecar 不再打包或读取 HTML。
- 删除旧根页面、SVG 二维码旧接口、状态驱动的账号/服务切换、重复打开看板、独立停止服务和清空日志接口。原生端继续使用显式登录/退出、`/api/pairing`、`/api/open-url`、启动与退出握手。
- 删除仅剩测试引用的 `SessionService.context_has_material`。
- 删除上述退役行为的测试；保留并更新管理接口权限、账号优先级、故障恢复、菜单栏和副屏测试，新增退役路由 404 检查。
- 历史 PRD 和迭代档案不删除；当前入口文档更新，历史架构加退役提示。

## 本地清理结果

`scripts/clean_workspace.py` 默认预览，只有 `--apply` 才执行。核对工作区与已安装 App 的账号引用、当前进程路径及目录修改时间后，本轮清理：

- 12 份超过 30 天未修改、无账号引用、无进程占用的开发浏览器配置。
- 已退役的 `src-tauri/target`；保留当前使用的 `target.noindex`。
- 7 份旧 App 备份；保留最新两份。
- `release-v1.2.0`、`release-v1.2.1` 本地发布暂存；保留 1.2.2 / 1.2.3，GitHub 附件未变。

删除文件合计 **93,829,374,501 字节，约 93.8GB 逻辑体积**。APFS 克隆、稀疏文件和快照可能使实际可用空间增量不同，不将此数冒充物理释放量。

本地清单与结果：`dist/cleanup-reports/20260920T160905724728Z.json`（UTC 文件名；已被 dist 规则排除出 Git）。已安装 App、Application Support 数据、仍被引用的开发 profile、源码、Design 和当前构建缓存未删除。

## 保留规则与使用

```sh
npm run workspace:clean
npm run workspace:clean -- --apply
```

- 默认保留最近两个版本暂存与最新两份 App 备份；只匹配明确命名且标识为 Token BI 的备份。
- 浏览器配置必须同时满足：不被任一已检查账号配置引用、无进程路径占用、内部文件至少 30 天未修改。
- 账号配置不可读或损坏时终止，不把未知当空列表；缺少开发账号配置时不清理 profile。
- 拒绝目标或父级符号链接跳转；删除前重新规划并比对目录身份，避免按过时清单删除。
- 保留当前 `target.noindex`、Python/Node 开发依赖和最新运行库产物，避免每次开发全量重建。
- 不在用户 App 启动、更新或同步时自动清理。macOS 可能限制部分进程的文件句柄枚举；进程可执行路径、工作目录、Chrome profile 参数及可读取的句柄用于占用保护，不宣称系统级文件锁。

## 浏览器依赖后续

本轮仍保留 Playwright，确保网页登录兜底不变。用户已明确 CDP 评估选型与重构放入后续版本；初步结论、风险、60–80MB 目标估算与验收门槛见 [轻量 CDP 评估](TECH_LIGHTWEIGHT_CDP.md)，该估算不代表本次交付体积。

## 验证结果

- Python / 浏览器全量 421 项通过；最后调整测试隔离与路径规范后，相关 49 项再次通过。
- JavaScript 13 项、Rust 19 项通过；Rust 格式、Clippy、`pip check` 与 `git diff --check` 通过。
- App 深度签名、隔离 control/backend 启动与关闭、暂停账号接入、看板资源、二维码以及旧控制台 404 均通过；未读取真实账号额度。
- DMG 校验和有效，已只读挂载确认包内 App 也是 188,708,466 字节，运行库链接完整、深度签名通过，验证后已卸载镜像。
- 沿用原 Updater 密钥生成本地更新归档，在临时发布目录中完成官方 Updater 下载、有效签名安装、篡改拒绝，以及安装后 symlink / codesign 检查。没有覆盖 `dist/release-v1.2.3` 正式发布暂存。
- 清理后再次预览候选为空；原账号关联的 8 个开发 profile 保留，`runtime/contexts` 从约 81.5GB 的目录磁盘统计降至约 450MB。

初次本地候选制品生成于 `src-tauri/target.noindex/release/bundle`。该阶段没有覆盖 `/Applications/Token BI.app`，没有更改版本号、签名公钥或 GitHub Release；后续 v1.2.4 正式制品不覆盖历史正式 v1.2.3 附件。真实账号网页登录与副屏真机仍由后续验收覆盖。
