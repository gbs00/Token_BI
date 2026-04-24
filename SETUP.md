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
- [Token BI.app](</Users/gbs00/我的文件夹/Projects/Token_BI/src-tauri/target/release/bundle/macos/Token BI.app>)：Mac App 原型入口，双击后打开内嵌控制台
- [Token BI.app](</Users/gbs00/我的文件夹/Projects/Token_BI/Token BI.app>)：项目根目录中的便捷 App 副本
- [config/accounts.json](/Users/gbs00/我的文件夹/Projects/Token_BI/config/accounts.json)：账号配置
- [scripts/open_control_panel.command](</Users/gbs00/我的文件夹/Projects/Token_BI/scripts/open_control_panel.command>)：Mac 本地控制台入口，双击即可启动控制页
- [scripts/start_server.sh](</Users/gbs00/我的文件夹/Projects/Token_BI/scripts/start_server.sh>)：启动 Token BI 主服务
- [scripts/stop_server.sh](</Users/gbs00/我的文件夹/Projects/Token_BI/scripts/stop_server.sh>)：停止 Token BI 主服务
- `runtime/contexts/`：每个账号的浏览器 profile 目录
- `runtime/logs/`：运行日志

要特别注意：

- `config/accounts.json` 里会记录绝对路径
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
- App 构建产物位于 `src-tauri/target/release/bundle/macos/Token BI.app`
- 为了方便本机使用，可将构建产物复制到项目根目录 `Token BI.app`
- 当前 App 不是完全自包含安装包，仍依赖项目目录下的 Python 虚拟环境、脚本、后端代码和配置文件

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
src-tauri/target/release/bundle/macos/Token BI.app
```

App 会自动：

- 启动控制台服务 `127.0.0.1:8790`
- 在 App 窗口内显示控制台
- 让用户通过按钮启动或停止 `8787` 主看板服务

关闭 `Token BI.app` 时，系统会停止控制台、停止主看板服务，并关闭 Token BI 管理的 Chrome worker，避免后台长期占用端口和浏览器资源。

### 3.1.1 当前 App 分发边界

当前 `Token BI.app` 属于开发预览形态：

- 可以在本机或项目目录完整迁移的 Mac 上运行
- 可以进一步打成 `.dmg` 上传 GitHub Releases 作为开发预览版
- 但它仍依赖项目目录内的 `.venv`、`scripts`、`app`、`config` 与 `runtime`

如果希望其他普通 Mac 用户下载后开箱即用，后续需要升级为自包含 App：

- 将 Python 后端或后端二进制打进 `.app/Contents/Resources`
- 将运行数据迁移到 `~/Library/Application Support/Token BI/`
- 避免依赖项目目录绝对路径
- 增加签名和 notarization，降低 macOS Gatekeeper 拦截概率

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

- 启动 Token BI
- 停止 Token BI
- 添加账号
- 打开看板
- 扫码连接副屏
- 刷新状态并触发一次 usage 校验
- 查看运行状态、PID、账号、固定入口、局域网入口和日志尾部

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
http://127.0.0.1:8787
```

如果能看到页面，说明服务本机可用。

---

## 4. 新机器首次接入真实账号

### 4.1 推荐方式：使用控制台添加账号

打开控制台后点击：

```text
添加账号
```

控制台会自动：

- 确认 Token BI 主服务已启动
- 先检查已有账号 worker 是否已经能读取 usage
- 如果已有 worker 可用，直接复用该窗口并刷新 usage
- 如果没有可用 worker，创建一个待识别账号记录
- 拉起独立 `Chrome` 登录窗口

你只需要在新开的 `Chrome` 窗口里完成 ChatGPT/Codex 登录，并保持窗口不关闭。

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

### 4.2 备用方式：命令行创建账号记录

也可以不传 `masked_email`，让系统先创建待识别账号：

```bash
curl -X POST http://127.0.0.1:8787/api/v1/accounts \
  -H 'Content-Type: application/json' \
  -d '{}'
```

返回里会有一个新的 `account_id`，后续都用它。

---

### 4.3 启动登录流程

```bash
curl -X POST http://127.0.0.1:8787/api/v1/accounts/<account_id>/reauth
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
curl -X POST http://127.0.0.1:8787/api/v1/accounts/<account_id>/validate
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
http://127.0.0.1:8787/dashboard?account_id=<account_id>
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
http://127.0.0.1:8787/...
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
src-tauri/target/release/bundle/macos/Token BI.app
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

- `启动 Token BI`
- `停止 Token BI`
- `添加账号`
- `打开看板`
- `扫码连接副屏`
- `刷新状态`

### 6.4 扫码连接副屏

控制台中的 `扫码连接副屏` 会展示两个二维码：

- `固定入口`：`http://<MacLocalName>.local:8787/dashboard`，推荐长期使用
- `局域网入口`：`http://<Mac局域网IP>:8787/dashboard`，用于 `.local` 解析失败时备用

副屏设备需要和 Mac 处在同一 Wi-Fi / 同一局域网。扫码只负责打开看板地址，usage 数据仍然由 Mac 上的 Token BI 主服务读取。

如果主服务没有启动，二维码仍可展示和复制，但副屏设备打开时会显示无法连接。此时先回到控制台点击 `启动 Token BI`。

### 6.5 固定看板入口

副屏设备建议始终使用：

```text
http://gbs00MacBook-Air-M2.local:8787/dashboard
```

不建议再把 `192.168.x.x` 这种动态 IP 地址添加到主屏幕或浏览器快捷方式。

### 6.6 启动账号浏览器窗口

如果浏览器窗口不在了，需要重新拉起：

```bash
curl -X POST http://127.0.0.1:8787/api/v1/accounts/<account_id>/reauth
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
curl -X POST http://127.0.0.1:8787/api/v1/accounts/<account_id>/reauth
```

或在控制台中重新启动 Token BI。

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

1. 调 `reauth`
2. 在新开的 Chrome 窗口里登录
3. 调 `validate`

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

### 8.3 看板上出现 demo 账号或伪造数据

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
