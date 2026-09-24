# Token BI v1.2.5

## 本次更新

- **macOS 单色菜单栏图标**：使用独立双环模板，由系统处理图标着色，更贴合菜单栏的整体观感。原彩色应用图标和面板内品牌图标保持不变。
- **小尺寸辨识优化**：加粗描边并等比例放大双环，保留 18pt 菜单栏占位；将缺口统一到左上方，与原应用图标保持一致。
- **轻量实现**：36px Retina 模板仅 1,644 字节，编译时嵌入，不新增依赖、运行时图像处理或账号数据迁移；设计稿不进入安装包。

本次只优化菜单栏图标。左键展开额度、右键快捷菜单、失焦收起、扫码连接副屏、存储重置、OAuth > CLI > Web 优先级以及应用内更新方式均保持不变。

## 升级方式

1. v1.2.1 及以上用户：进入菜单栏面板「设置」，检查更新，下载后确认「重启完成更新」。
2. 手动安装：下载 Apple Silicon DMG，退出旧 App 后替换应用程序目录中的 Token BI.app。
3. 升级保留账号与设置；重启期间副屏连接会短暂中断。

## 验证结果

- Python/Chromium/WebKit 425 项、JavaScript 13 项、Rust 20 项及真实签名更新归档测试 1 项通过；格式、Clippy 与依赖检查通过。
- 模板尺寸、单色像素、透明边界与中心检查通过；1×/2× 离屏预览确认双环和左上开口可辨认。
- 完整重建 shell、control、backend；打包服务健康、暂停账号访问、看板、二维码和退出端口释放通过。
- App 深度签名、DMG 校验及只读挂载后的 App 签名通过；官方 Updater 有效签名下载、篡改拒绝和临时 App 安装通过，未改动真实账号数据。

## 分发与边界

- 提供 Apple Silicon DMG、沿用原密钥签名的 Updater 归档、`.sig`、`latest.json` 和 `SHA256SUMS`。
- App 仍使用 ad hoc 签名，未做 Apple Developer ID 签名或公证；Updater 签名不代替 Gatekeeper 信任。
- 已进行多轮本地图标试用和浅深色离屏对比；离屏预览不等同于真实系统菜单栏截图。物理多屏、所有系统外观、iPhone 真机和长期睡眠恢复仍需独立验收。
- [图标设计与导出记录](https://github.com/gbs00/Token_BI/blob/v1.2.5/docs/design-previews/menubar-template.md)。
- [Python 构建依赖快照](https://github.com/gbs00/Token_BI/blob/v1.2.5/docs/releases/v1.2.5-python.txt)与上版一致，Node/Rust 依赖保持不变。

App：184,506,082 字节（符号链接不重复计入）；DMG：62,854,710 字节，约 59.9 MiB。DMG SHA-256：

```text
7e6e37f7e482be410402181ec418451ccb39ec098b47aad7c141fa246f925a8d
```
