# Token BI 启动与迁移说明

本文件用于说明两类场景：

- `新电脑首次部署`
- `已有电脑的日常启动`

适用前提：

- 项目目录已经拿到本地
- 使用 `Google Chrome`
- `Mac` 作为本地服务端
- `iPhone` 只负责通过局域网访问看板

---

## 1. 项目结构中最重要的文件

- [README.md](/Users/gbs00/我的文件夹/Projects/Token_BI/README.md)：需求与产品约束
- [TECH_ARCHITECTURE.md](/Users/gbs00/我的文件夹/Projects/Token_BI/TECH_ARCHITECTURE.md)：技术架构说明
- [config/accounts.json](/Users/gbs00/我的文件夹/Projects/Token_BI/config/accounts.json)：账号配置
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

可检查版本：

```bash
python3 --version
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
```

说明：

- 虽然当前主链路是 `Chrome + CDP attach`
- 但项目仍然依赖 `playwright` Python 包来连接浏览器调试端口

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

### 3.1 启动命令

为了让手机能访问，服务必须监听 `0.0.0.0`，不能只监听 `127.0.0.1`。

```bash
./.venv/bin/uvicorn app.main:app \
  --app-dir /path/to/Token_BI \
  --host 0.0.0.0 \
  --port 8787
```

如果你已经在项目目录中：

```bash
./.venv/bin/uvicorn app.main:app --app-dir "$(pwd)" --host 0.0.0.0 --port 8787
```

---

### 3.2 验证服务是否启动成功

本机打开：

```text
http://127.0.0.1:8787
```

如果能看到页面，说明服务本机可用。

---

## 4. 新机器首次接入真实账号

### 4.1 创建账号记录

用脱敏邮箱创建账号：

```bash
curl -X POST http://127.0.0.1:8787/api/v1/accounts \
  -H 'Content-Type: application/json' \
  -d '{"masked_email":"8754****@qq.com"}'
```

返回里会有一个新的 `account_id`，后续都用它。

---

### 4.2 启动登录流程

```bash
curl -X POST http://127.0.0.1:8787/api/v1/accounts/<account_id>/reauth
```

这一步会：

- 打开一扇本机 `Google Chrome` 窗口
- 带上 `--remote-debugging-port`
- 使用该账号自己的浏览器 profile 目录

---

### 4.3 在 Chrome 中手动登录

用户需要在新开的 `Chrome` 窗口中完成：

- ChatGPT/Codex 登录

注意：

- 这扇窗口不要关闭
- 它就是当前账号的“活会话”
- 看板后端会通过 `CDP` 附着这扇窗口读取额度

---

### 4.4 验证额度读取

登录完成后执行：

```bash
curl -X POST http://127.0.0.1:8787/api/v1/accounts/<account_id>/validate
```

如果成功，返回里通常会看到：

- `validated: true`
- `dashboard_state: ready`

同时服务会：

- 强制切到 `https://chatgpt.com/codex/cloud/settings/analytics#usage`
- 再显式刷新一次
- 然后读取最新额度

---

### 4.5 打开真实看板

本机打开：

```text
http://127.0.0.1:8787/dashboard?account_id=<account_id>
```

---

## 5. 手机如何访问

### 5.1 不能使用 `127.0.0.1`

这是最容易踩的坑。

`127.0.0.1` 永远只代表“当前设备自己”：

- Mac 上的 `127.0.0.1` 是 Mac
- iPhone 上的 `127.0.0.1` 是 iPhone

所以手机不能访问：

```text
http://127.0.0.1:8787/...
```

---

### 5.2 要使用 Mac 的局域网 IP

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

那么手机应访问：

```text
http://10.124.4.70:8787/dashboard?account_id=<account_id>
```

---

### 5.3 手机热点场景也属于“小局域网”

如果是：

- 手机开热点
- Mac 连接手机热点

那么手机和 Mac 通常仍然处于同一个小型局域网络里。

前提是：

- 服务监听的是 `0.0.0.0`
- Mac 防火墙没有拦截 `8787`
- 手机浏览器访问的是 `Mac IP`，不是 `127.0.0.1`

---

## 6. 日常启动流程

如果已经在当前这台电脑完成过登录，日常使用建议按这个顺序：

### 6.1 启动服务

```bash
cd /path/to/Token_BI
./.venv/bin/uvicorn app.main:app --app-dir "$(pwd)" --host 0.0.0.0 --port 8787
```

### 6.2 启动账号浏览器窗口

如果浏览器窗口不在了，需要重新拉起：

```bash
curl -X POST http://127.0.0.1:8787/api/v1/accounts/<account_id>/reauth
```

### 6.3 如果窗口已经存在

系统会优先尝试“认领”这扇已存在的浏览器窗口，而不是重复启动一份。

但前提是：

- 这扇窗口使用的是该账号对应的 profile
- 仍保留着可用登录态
- 调试端口还在

---

### 6.4 每次刷新前都会自动做什么

当前真实链路下，每次读取前都会：

1. 附着当前 `Chrome` 会话
2. 强制跳到 `analytics#usage`
3. 显式 `reload`
4. 优先读取 `network response`
5. 读取失败再降级到 `DOM fallback`

这也是为了避免停留在 `chatgpt.com/#usage` 首页时拿到旧数据或非数据页。

---

## 7. 服务重启后的影响

### 7.1 服务重启不一定等于重新登录

如果满足这些条件：

- 账号浏览器窗口还活着
- `Chrome` 仍保持同一 `CDP` 端口
- 对应账号 profile 目录一致

那么服务重启后，重新调用一次：

```bash
curl -X POST http://127.0.0.1:8787/api/v1/accounts/<account_id>/reauth
```

系统通常可以重新接管现有窗口。

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

### 8.4 手机能访问 Mac 吗

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
- 手机和 Mac 是否在同一网络

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
