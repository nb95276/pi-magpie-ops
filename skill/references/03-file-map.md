# 文件地图

## magpie —— `~/.config/magpie/`

Windows：`C:\Users\<you>\.config\magpie\`

| 文件 | 作用 | 能不能手改 |
|---|---|---|
| `providers.json` | provider + 路由组定义（含 `hidden` 标记） | ⚠️ 尽量用 CLI，手改后要能对上网关内存态 |
| `settings.json` | theme / lang / tray / lan / lanKey / redact / updateEvery / textSize / window | 可以 |
| `profiles.json` | `magpie save/use` 的档案 | 用 CLI |
| `quotas.json` | 各订阅额度快照（key 形如 `codex/<email> · team`） | 只读 |
| `usage.jsonl` | 逐请求用量流水（**注意体积，会持续增长**） | 只读 |
| `logins.json` | 各订阅登录态 | 别动 |
| `plugin-providers.json` | OpenCode 插件型 provider | 别动 |
| `plugin-auth.json` / `plugin-updates.json` / `plugins.json` | 插件 | 用 `magpie plugin` |
| `library.json` | 写进各 agent 的共享指令/MCP/skill | 用 `magpie library` |
| `affinity.json` | 路由粘性状态 | 别动 |
| `applied.json` / `migrations.json` | 已应用状态与迁移记录 | 别动 |
| `caller-keys.json` / `cli-identity.json` | 客户端标识 | 别动 |
| `stash.json` / `backups/` | 暂存与备份 | 只读 |
| `routing/YYYY-MM-DD.jsonl[.gz]` | **每日路由决策日志，排障金矿** | 只读 |
| `redact.key` | 脱敏密钥 | 别动 |
| `install-id` / `last-version` / `stats-sent` | 遥测相关 | 别动 |
| `wsl.json` | WSL 集成 | 别动 |
| `rtk.exe` | 内置的 RTK 工具 | 别动 |
| `market/` | 商店元数据（在 `%LOCALAPPDATA%\magpie`） | 别动 |

### 脱敏说明

`providers.json` 里看到的 key 可能是 `{{API_KEY_xxxx}}` 形式 —— 这是 magpie 的**脱敏占位符**，
不是真实 key，真实值在加密存储里。所以这类文件可以安全地贴出来讨论。

## pi（CLI）

Windows：`C:\Users\<you>\.pi\agent\`

| 文件 | 作用 |
|---|---|
| `models.json` | pi 自己的 provider 定义（接 magpie 后应只剩 `magpie` 一个） |
| `settings.json` | `defaultProvider` / `defaultModel` / `defaultThinkingLevel` / `retry` / `packages` / `theme` / `defaultProjectTrust` |
| `auth.json` | 直连 provider 的凭据（走 magpie 时应为 `{}`） |
| `sessions/` | 会话记录 |
| `pi-switch.json` | ⚠️ 旧版切换器残留，新版 pi 不读它 —— 见到可直接忽略，别改 |

pi 的执行文件（npm 全局）：
`%APPDATA%\npm\node_modules\@earendil-works\pi-coding-agent\dist\bundle\cli.js`

## PI-Desktop（桌面端）

| 路径 | 作用 |
|---|---|
| `%LOCALAPPDATA%\Programs\PI-Desktop\` | 安装目录；`resources\app.asar`（~90MB）是主体，`resources\agent-runtime\sidecar.js` 是内置内核 |
| `%LOCALAPPDATA%\Programs\PI-Desktop\resources\bin\pi-desktop-host-core.exe` | 宿主进程 |
| `%APPDATA%\pi-desktop\settings.json` | ⚠️ 看 `04-desktop-collision.md` |
| `%APPDATA%\pi-desktop\pi-desktop.json` | 桌面端自身设置 |
| `%APPDATA%\pi-desktop\pi-desktop-index.db` | 索引用 SQLite |
| `%APPDATA%\pi-desktop\session-summary-cache.json` | 会话摘要缓存 |
| `~/.pi-desktop/pi.sqlite` | 会话/项目/模型缓存（**有锁，操作前先快照**） |
| `~/.pi-desktop/logs/` | 日志 |
| `~/.pi-desktop/scratch/` | 各 agent 的临时工作目录 |

## 版本线

- pi CLI：`pi --version`（例：1.0.0），由 npm 全局包提供，可独立升级
- PI-Desktop：`0.16.0`（vastsa/PI-Desktop），**自带内核，无法指向全局 CLI**
- magpie：`magpie --version`（例：0.1.632）

三者版本互相独立，排查时要分别确认。

## 快速清点脚本

```powershell
# magpie 二进制定位
Get-Process magpie-windows-amd64 -ErrorAction SilentlyContinue | Select-Object Path

# 网关端口归属
Get-NetTCPConnection -State Listen | Where-Object LocalPort -eq 3425

# pi 接线
Get-Content "$env:USERPROFILE\.pi\agent\settings.json" -Raw
```
