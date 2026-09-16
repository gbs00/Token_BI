# Token BI v1.2.2

## 本次修复

- 修复升级 macOS 27 后，单击菜单栏图标只弹出「查看额度 / 扫码连接副屏 / 退出 Token BI」菜单、无法直接展开额度面板的问题。
- 左键直接展开/收起额度面板，右键保留快捷菜单；切换到其他窗口仍自动收起。
- 右键菜单不再常驻绑定到系统状态栏图标，关闭菜单后恢复图标高亮状态，避免影响后续左键点击。
- 不更改账号读取优先级、额度计算、刷新频率、扫码入口或 Web 看板布局；不增加依赖、进程或轮询。

## 升级方式

1. v1.2.1 用户：打开额度面板，进入「设置」检查更新，下载后确认「重启完成更新」。旧版 macOS 27 用户可先从菜单的「查看额度」进入面板。
2. v1.2.0 及更早版本：下载本次 DMG，退出旧 App 后替换应用程序目录中的 Token BI.app。
3. 升级保留账号和设置；重启期间副屏连接会短暂中断。检查与下载需要能够访问 GitHub。

## 验证范围

- 同一菜单栏修复已在本机 macOS 27.0（26A428）验证，用户确认「左键面板、右键菜单均正常」。
- Python 360 项、JS 9 项、Rust 单元测试 17 项通过；额外通过真实签名归档的隔离下载、篡改拒绝和临时 App 安装测试，共 387 项。
- 格式、Clippy、依赖检查、App 深度签名与 DMG 校验通过；成套打包的 control/backend、版本、暂停账号接入、看板资源、二维码及退出清理检查通过。
- 旧 macOS、物理跨屏、长时间睡眠唤醒、真实运行 App 跨版本重启后的副屏恢复仍需独立验收，不以网页或临时安装测试代替。

## 分发范围

- macOS Apple Silicon DMG、签名的 Tauri 更新归档、签名文件、latest.json 与 SHA256SUMS。
- 沿用 v1.2.1 的 Updater 公钥与签名密钥，已有客户端无需手动更换更新配置。
- App 仍为 ad hoc 签名，未进行 Apple Developer ID 签名及公证；Updater 签名不代替 Gatekeeper 信任。
- 根因与实现记录：[菜单栏技术纪要](https://github.com/gbs00/Token_BI/blob/v1.2.2/docs/TECH_MENUBAR.md)。全部制品校验值见 Release 的 SHA256SUMS。
- DMG 为 67,491,777 字节（约 64.4 MiB），SHA-256：`3f845df4e5bbf13c98e1e8dfa03e1c7e3815755866f8cc6ef3064da113bc0606`。
- 构建环境：macOS 27 arm64、Python 3.9.6、Node 24.13.0、Rust 1.95.0；[Python 依赖快照](https://github.com/gbs00/Token_BI/blob/v1.2.2/docs/releases/v1.2.2-python.txt)，Node/Rust 依赖沿用 lockfile。
