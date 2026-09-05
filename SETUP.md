# Token BI 启动与迁移说明

本文件用于说明两类场景：

- `新电脑首次部署`
- `已有电脑的日常启动`

适用前提：

- 项目目录已经拿到本地
- 使用 `Google Chrome`
- `Mac` 作为本地服务端
- 副屏设备只负责通过局域网访问看板，可包括 iPhone、Android 手机、小米手机、平板、旧手机、旧电脑等

---

## 1. 项目结构中最重要的文件

- [README.md](/Users/gbs00/我的文件夹/Projects/Token_BI/README.md)：需求与产品约束
- [TECH_ARCHITECTURE.md](/Users/gbs00/我的文件夹/Projects/Token_BI/TECH_ARCHITECTURE.md)：技术架构说明
- [CHANGELOG.md](/Users/gbs00/我的文件夹/Projects/Token_BI/CHANGELOG.md)：版本记录与关键决策演进
- [Token BI.app](</Users/gbs00/我的文件夹/Projects/Token_BI/src-tauri/target.noindex/release/bundle/macos/Token BI.app>)：Mac App 原型入口，双击后打开内嵌控制台
- [docs/RELEASE.md](/Users/gbs00/我的文件夹/Projects/Token_BI/docs/RELEASE.md)：DMG、本地 release、签名、公证和 GitHub updater 发布说明
- [config/accounts.json](/Users/gbs00/我的文件夹/Projects/Token_BI/config/accounts.json)：账号配置
- [scripts/open_control_panel.command](</Users/gbs00/我的文件夹/Projects/Token_BI/scripts/open_control_panel.command>)：Mac 本地控制台入口，双击即可启动控制页
- [scripts/start_server.sh](</Users/gbs00/我的文件夹/Projects/Token_BI/scripts/start_server.sh>)：启动 Token BI 主服务
- [scripts/stop_server.sh](</Users/gbs00/我的文件夹/Projects/Token_BI/scripts/stop_server.sh>)：停止 Token BI 主服务
- `runtime/contexts/`：每个账号的浏览器 profile 目录
- `runtime/logs/`：运行日志
- `~/Library/Application Support/Token BI/`：产品化 App 默认用户数据目录

源码项目目录统一为：

```bash
/Users/gbs00/我的文件夹/Projects/Token_BI
```

`.config/superpowers/worktrees/Token_BI` 只用于阶段性开发 worktree，不作为长期项目目录。完成合并、推送与验收后，应清理该临时目录，避免后续误从临时目录继续开发。

要特别注意：

- 开发目录中的 `config/accounts.json` 里会记录绝对路径
- 产品化 App 会优先使用 `~/Library/Application Support/Token BI/config/accounts.json`
- `runtime/contexts/` 里的浏览器数据和机器环境强相关
- 换电脑后，不建议直接复用旧机器的 `runtime/contexts/`

更稳妥的做法是：

- 新电脑重新登录账号
- 新电脑重新生成本地浏览器会话

---

## 2. 新电脑首次部署

### 2.1 安装基础环境

需要先安装：

- `Python 3.9+`
- `Google Chrome`
- `Node.js + npm`
- `Rust/Cargo`，用于构建 `Token BI.app`

可检查版本：

```bash
python3 --version
node --version
npm --version
rustc --version
cargo --version
```

---

### 2.2 进入项目目录

```bash
cd /path/to/Token_BI
```

---

### 2.3 创建虚拟环境并安装依赖

```bash
python3 -m venv .venv
./.venv/bin/pip install --upgrade pip
./.venv/bin/pip install -r requirements.txt
./.venv/bin/playwright install chromium
npm install
npm run app:build
```

说明：

- 虽然当前主链路是 `Chrome + CDP attach`
- 但项目仍然依赖 `playwright` Python 包来连接浏览器调试端口
- `npm run app:build` 会生成 `Token BI.app`
- App 构建产物位于 `src-tauri/target.noindex/release/bundle/macos/Token BI.app`
- 本机日常使用建议通过 DMG 安装到 `/Applications`，不要长期依赖项目根目录中的 App 副本
- 当前产品化基础版已将 Python 后端打包为 sidecar；开发构建仍需要本机具备 Python/Node/Rust，最终用户运行 DMG 不应再理解这些开发依赖

---

### 2.4 清理旧机器残留配置

如果项目目录是从旧电脑直接复制过来的，建议先清理旧的账号与运行态。

推荐做法：

1. 备份旧文件
2. 清空账号配置
3. 清空旧的浏览器上下文

示例：

```bash
cp config/accounts.json config/accounts.backup.json
rm -rf runtime/contexts/*
cat > config/accounts.json <<'EOF'
{
  "accounts": []
}
EOF
```

说明：

- 这是“新电脑重新接管”的推荐方式
- 如果保留旧 `accounts.json`，其中绝对路径仍然会指向旧电脑目录
- 即使路径刚好一致，旧浏览器登录态也未必可复用

---

## 3. 启动本地服务

### 3.1 推荐方式：打开 Token BI.app

日常建议优先双击：

```text
src-tauri/target.noindex/release/bundle/macos/Token BI.app
```

App 会自动：

- 启动控制台服务 `127.0.0.1:8790`
- 在 App 窗口内显示控制台
- 让用户通过 `开启服务` / `关闭服务` 单按钮管理主看板服务，默认优先使用 `8787`
- 如果 `8787` 被占用，自动切换到 `8788-8877` 中第一个可用端口，并在控制台、二维码和看板入口中显示实际端口

关闭 `Token BI.app` 时，系统会停止控制台、停止主看板服务，并关闭 Token BI 管理的 Chrome worker，避免后台长期占用端口和浏览器资源。

### 3.1.1 v0.9.1 可信测试版使用路径

首次打开 App 后，建议按控制台顶部 checklist 操作：

1. 检查 Google Chrome 是否可用。
2. 点击 `开启服务`。
3. 点击账号主按钮 `登录账号`，在弹出的 Token BI 专用 Chrome 窗口完成 Codex 登录和真人验证。
4. 回到控制台点击 `刷新状态`。
5. 确认账号按钮变为 `退出账号`，当前账号显示脱敏邮箱。
6. 点击 `扫码连接副屏`，用副屏设备扫码打开看板。

账号按钮规则：

- 显示 `登录账号`：当前没有可用账号、登录未完成、登录中断或 worker 丢失。
- 显示 `退出账号`：当前账号已读取到 usage，Token BI 认为该账号处于可用状态。
- 点击 `退出账号`：关闭该账号 worker，删除 Token BI 专用账号记录和 Chrome profile，并刷新为 `登录账号`。
- 该删除动作只影响 Token BI 专用 profile，不影响用户日常 Chrome 登录态。

刷新行为：

- 主服务会在后台统一读取 Codex usage，成功后默认每 180 秒再次同步。
- 副屏每 15 秒读取一次 Mac 本地最新状态，不会因设备数量增加而重复请求官方接口。
- `刷新状态` 会显式触发一次最新 Codex usage 同步，并与正在进行的同步任务合并。
- 副屏看板中的 `同步额度` 也会触发一次最新 usage 同步，用于手动校准看板。
- 成功读取 usage 后，Token BI 会尝试最小化自己管理的 Chrome worker，降低桌面打扰。
- 如果刷新失败，控制台会展示“发生了什么 + 下一步怎么做”的提示；副屏看板会保留最后成功快照并按后端计划自动重试。
- 最后成功快照位于 `runtime/cache/latest_dashboard.json`，只保留一份当前状态；退出账号时删除。

首次启动引导行为：

- checklist 未完成时，控制台会展示完整步骤条。
- checklist 全部完成后，引导会收缩为与上下内容齐平的通栏小卡片。
- 收起状态下，`查看引导` 按钮位于卡片右侧。
- 点击 `查看引导` 可重新展开完整步骤，再点击 `收起引导` 可恢复小卡片。

扫码连接行为：

- `扫码连接副屏` 默认只显示按钮。
- 点击按钮后才弹出二维码卡片。
- 点击二维码弹窗右上角 `x`、背景遮罩或按 `Esc` 可以关闭弹窗。
- 二维码中的地址会跟随当前实际端口变化；如果 `8787` fallback 到 `8788-8877`，二维码会同步使用新端口。

开发预览说明：

- 如果本机已安装旧版 DMG，开发调试时应先退出旧的 `Token BI.app`。
- 从源码预览控制台时，启动 `127.0.0.1:8790` 控制台后，通过页面里的 `开启服务` 启动主服务，避免手动启动的 `8787` 进程与控制台 runtime 状态不一致。
- iPhone Safari 或旧设备浏览器如果长时间保留旧样式，可关闭页面后重新扫码打开，避免浏览器缓存旧 CSS。

### 3.1.2 当前 App 分发边界

当前 `Token BI.app` 已具备产品化基础能力：

- 可以生成 `.app` 和 `.dmg`
- Python 后端被打包为 `token-bi-backend` sidecar
- 控制台和主服务由 App/sidecar 管理，不要求用户手动运行项目脚本
- 用户数据默认保存到 `~/Library/Application Support/Token BI/`

如果希望其他普通 Mac 用户下载后开箱即用，后续需要升级为自包含 App：

- 配置 Developer ID 签名和 notarization，降低 macOS Gatekeeper 拦截概率
- 生成正式 GitHub Releases updater manifest
- 用真实干净机器验证从 DMG 拖拽安装到 `/Applications`

### 3.2 备用方式：打开 Mac 本地控制台

如果暂时不使用 App，也可以打开控制台脚本：

```bash
/Users/gbs00/我的文件夹/Projects/Token_BI/scripts/open_control_panel.sh
```

也可以在 Finder 中双击：

```text
scripts/open_control_panel.command
```

控制台会打开：

```text
http://127.0.0.1:8790/
```

控制台能力：

- 通过一个按钮开启或关闭 Token BI 主服务
- 登录账号 / 退出账号，统一由一个账号主按钮按状态切换
- 打开看板
- 点击后弹窗显示 `扫码连接副屏` 二维码
- 刷新状态并触发一次 usage 校验
- 查看运行状态、PID、账号、固定入口、局域网入口和日志尾部
- 查看首次启动 checklist 和可执行异常提示

控制台仅监听 `127.0.0.1`，只用于 Mac 本机操作。

### 3.3 备用方式：命令行启动

为了让副屏设备能访问，服务必须监听 `0.0.0.0`，不能只监听 `127.0.0.1`。

```bash
/path/to/Token_BI/scripts/start_server.sh
```

如果你已经在项目目录中：

```bash
./scripts/start_server.sh
```

---

### 3.4 验证服务是否启动成功

本机打开：

```text
http://127.0.0.1:<实际端口>
```

如果能看到页面，说明服务本机可用。实际端口以控制台显示为准，默认是 `8787`，被占用时可能是 `8788-8877` 中的其他端口。

---

## 4. 新机器首次接入真实账号

### 4.1 推荐方式：使用控制台登录账号

打开控制台后点击：

```text
登录账号
```

控制台会自动：

- 确认 Token BI 主服务已启动
- 创建或复用待识别账号记录
- 拉起独立 `Chrome` 登录窗口

你只需要在新开的 `Chrome` 窗口里完成 ChatGPT/Codex 登录，然后回到控制台点击 `刷新状态`。成功读取 usage 后，控制台账号按钮会切换为 `退出账号`。

登录完成后，回到控制台点击：

```text
刷新状态
```

如果 usage 校验成功，系统会自动：

- 读取当前账号的 usage
- 识别账号标识
- 脱敏后写入账号配置
- 将账号状态更新为 `active`

---

### 4.2 备用方式：命令行启动登录流程

v0.9+ 推荐直接调用统一登录入口，让系统自动创建或复用待识别账号：

```bash
curl -X POST http://127.0.0.1:<实际端口>/api/v1/account-session/login
```

返回里会包含账号记录和 worker session。若控制台显示 fallback 到 `8788` 等端口，请把命令中的 `<实际端口>` 替换为控制台显示的端口。

---

### 4.3 兼容旧方式：指定账号重新登录

```bash
curl -X POST http://127.0.0.1:<实际端口>/api/v1/accounts/<account_id>/reauth
```

这一步会：

- 打开一扇本机 `Google Chrome` 窗口
- 带上 `--remote-debugging-port`
- 使用该账号自己的浏览器 profile 目录

---

### 4.4 在 Chrome 中手动登录

用户需要在新开的 `Chrome` 窗口中完成：

- ChatGPT/Codex 登录

注意：

- 这扇窗口不要关闭
- 它就是当前账号的“活会话”
- 看板后端会通过 `CDP` 附着这扇窗口读取额度

---

### 4.5 验证额度读取

登录完成后执行：

```bash
curl -X POST http://127.0.0.1:<实际端口>/api/v1/dashboard/refresh?account_id=<account_id>
```

如果成功，返回里通常会看到：

- `validated: true`
- `dashboard_state: ready`

同时服务会：

- 强制切到 `https://chatgpt.com/codex/cloud/settings/analytics#usage`
- 从已登录会话中提取账号标识，并脱敏写回账号配置
- 再显式刷新一次
- 然后读取最新额度

---

### 4.5 打开真实看板

本机打开：

```text
http://127.0.0.1:<实际端口>/dashboard?account_id=<account_id>
```

---

## 5. 副屏设备如何访问

### 5.1 不能使用 `127.0.0.1`

这是最容易踩的坑。

`127.0.0.1` 永远只代表“当前设备自己”：

- Mac 上的 `127.0.0.1` 是 Mac
- iPhone / Android / 平板上的 `127.0.0.1` 是它自己

所以副屏设备不能访问：

```text
http://127.0.0.1:<实际端口>/...
```

---

### 5.2 要使用 Mac 的局域网 IP 或 `.local` 地址

先在 Mac 上查 IP：

```bash
ifconfig | grep "inet "
```

或更直接一点：

```bash
ipconfig getifaddr en0
```

如果返回的是例如：

```text
10.124.4.70
```

那么副屏设备应访问：

```text
http://10.124.4.70:8787/dashboard
```

---

### 5.3 手机热点场景也属于“小局域网”

如果是：

- 手机开热点
- Mac 连接手机热点

那么开热点的手机和 Mac 通常仍然处于同一个小型局域网络里，其他连接该热点的设备也是同理。

前提是：

- 服务监听的是 `0.0.0.0`
- Mac 防火墙没有拦截 `8787`
- 副屏设备浏览器访问的是 `Mac IP` 或 `.local` 地址，不是 `127.0.0.1`

---

## 6. 日常启动流程

如果已经在当前这台电脑完成过登录，日常使用建议按这个顺序：

### 6.1 打开 Token BI.app

优先双击：

```text
src-tauri/target.noindex/release/bundle/macos/Token BI.app
```

如果只是临时调试，也可以继续使用控制台脚本。

### 6.2 打开控制台备用入口

双击：

```text
scripts/open_control_panel.command
```

或命令行：

```bash
/Users/gbs00/我的文件夹/Projects/Token_BI/scripts/open_control_panel.sh
```

### 6.3 启动或停止主服务

在控制台点击：

- `开启服务` / `关闭服务`
- `登录账号` / `退出账号`
- `打开看板`
- `扫码连接副屏`
- `刷新状态`

### 6.4 扫码连接副屏

控制台中的 `扫码连接副屏` 默认只显示按钮。点击后会弹出二维码卡片，卡片中可切换两个二维码：

- `固定入口`：`http://<MacLocalName>.local:8787/dashboard`，推荐长期使用
- `局域网入口`：`http://<Mac局域网IP>:8787/dashboard`，用于 `.local` 解析失败时备用

如果 `8787` 被占用，控制台会在二维码中自动改成实际端口，例如 `8788`。

副屏设备需要和 Mac 处在同一 Wi-Fi / 同一局域网。扫码只负责打开看板地址，usage 数据仍然由 Mac 上的 Token BI 主服务读取。

如果主服务没有启动，二维码仍可展示和复制，但副屏设备打开时会显示无法连接。此时先回到控制台点击 `开启服务`。

### 6.5 固定看板入口

副屏设备建议始终使用：

```text
http://gbs00MacBook-Air-M2.local:<实际端口>/dashboard
```

不建议再把 `192.168.x.x` 这种动态 IP 地址添加到主屏幕或浏览器快捷方式。

### 6.6 启动账号浏览器窗口

如果浏览器窗口不在了，需要重新拉起：

```bash
curl -X POST http://127.0.0.1:<实际端口>/api/v1/account-session/login
```

正常情况下，主服务启动时会自动尝试恢复或拉起 `active` 账号的 worker。

### 6.7 如果窗口已经存在

系统会优先尝试“认领”这扇已存在的浏览器窗口，而不是重复启动一份。

但前提是：

- 这扇窗口使用的是该账号对应的 profile
- 仍保留着可用登录态
- 调试端口还在

---

### 6.8 每次刷新前都会自动做什么

当前真实链路下，每次读取前都会：

1. 附着当前 `Chrome` 会话
2. 强制跳到 `analytics#usage`
3. 显式 `reload`
4. 优先读取 `network response`
5. 读取失败再降级到 `DOM fallback`

这也是为了避免停留在 `chatgpt.com/#usage` 首页时拿到旧数据或非数据页。

### 6.9 副屏页面刷新策略

副屏页面不会再每 `3 分钟` 整页刷新。

现在采用：

- 后台请求 `/api/v1/dashboard`
- 原地更新账号、状态、更新时间、来源、百分比、进度条和重置时间
- 服务短暂重启时保留当前内容
- 请求失败后显示 `Connection interrupted. Retrying automatically...`
- 失败后每 `15 秒` 自动重试

这样可以避免副屏设备页面在服务重启瞬间卡进系统级“服务器无响应”页。

---

## 7. 服务重启后的影响

### 7.1 服务重启不一定等于重新登录

如果满足这些条件：

- 账号浏览器窗口还活着
- `Chrome` 仍保持同一 `CDP` 端口
- 对应账号 profile 目录一致

那么服务重启后通常会自动接回现有窗口。

如果没有接回，再手动调用：

```bash
curl -X POST http://127.0.0.1:<实际端口>/api/v1/account-session/login
```

或在控制台中点击 `关闭服务` 后再点击 `开启服务`。

---

### 7.2 哪些情况需要重新登录

这些情况下建议重新登录：

- Chrome 窗口被关闭
- 登录态失效
- 机器重启后浏览器会话没恢复
- 换了新电脑
- 清理了 `runtime/contexts/`

---

## 8. 常见问题

### 8.1 看板显示 `reauth_required`

通常表示：

- 服务没有接管到有效浏览器会话
- 或当前浏览器窗口未登录

处理方式：

1. 点击控制台 `登录账号`
2. 在新开的 Chrome 窗口里登录
3. 回到控制台点击 `刷新状态`

---

### 8.2 页面显示的不是最新额度

当前项目已经修正这点。

现在会在抓取前：

- 进入 `analytics#usage`
- 再显式刷新一次

如果仍然不对，先重新执行一次：

```bash
curl -X POST http://127.0.0.1:8787/api/v1/accounts/<account_id>/validate
```

---

### 8.3 看板显示 `Analytics page may have changed`

这通常表示 Codex 官方 analytics 页面结构变化，或某个额度窗口被官方下线。

当前版本已兼容官方删除 `5h` / `5 小时额度` 的情况：

- 如果只读取到周额度，看板会只显示 `Weekly` / `周额度` 卡片。
- 如果页面已处于错误态，点击看板 `同步额度` 或控制台 `刷新状态` 后，读取成功会原地恢复显示。
- 如果仍然报错，请点击 `Open Usage` 打开官方页面，确认当前账号是否能在官方页面看到周额度。

---

### 8.4 看板上出现 demo 账号或伪造数据

正常真实环境下，不应再显示 demo 账号。

如果再次出现，先检查：

- [config/accounts.json](/Users/gbs00/我的文件夹/Projects/Token_BI/config/accounts.json) 中是否残留 `acc_demo_*`

如果有，可以清掉后重启服务。

---

### 8.4 副屏设备能访问 Mac 吗

先在 Mac 上自检：

```bash
curl http://127.0.0.1:8787/api/v1/accounts
```

再用 Mac 局域网 IP 自检：

```bash
curl http://<mac-lan-ip>:8787/api/v1/accounts
```

如果本机能通、局域网 IP 不通，优先排查：

- 服务是否监听 `0.0.0.0`
- macOS 防火墙
- 副屏设备和 Mac 是否在同一网络

### 8.5 主屏幕或快捷方式打开后提示服务器无响应

优先确认：

- Token BI 主服务是否在控制台中显示为 `运行中`
- 副屏设备打开的是固定入口 `http://gbs00MacBook-Air-M2.local:8787/dashboard`
- 不要使用旧的 `127.0.0.1` 或旧 IP 主屏幕图标

如果旧图标或快捷方式是用 `192.168.x.x` 添加的，建议删掉后用 `.local` 地址重新添加。

如果服务正在重启中，页面会保留当前内容并自动重试；但如果是在服务完全未启动时冷打开主屏幕图标或快捷方式，设备浏览器仍可能先显示系统级无响应页。

---

## 9. 建议的交接方式

如果以后要迁移给另一台电脑或另一位维护者，建议只迁移：

- 项目源码
- 文档

不建议把旧机器的这些内容直接当作正式迁移方案：

- `runtime/contexts/`
- 旧浏览器登录态
- 旧 `accounts.json`

更稳的交接方式是：

1. 新机器重新部署依赖
2. 新机器重新创建账号
3. 新机器重新登录
4. 新机器重新 `validate`

这样可重复性最好，故障也最少。
