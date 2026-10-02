# magpie CLI 速查（v0.1.632 实测）

二进制名 `magpie`。Windows 上常见位置：`%USERPROFILE%\Downloads\Programs\magpie-windows-amd64.exe`。
配置根目录：`~/.config/magpie/`（即 `%USERPROFILE%\.config\magpie`）。

> 命令行里跑不到 `magpie` 时先定位二进制：`Get-Process magpie* | Select Path`，
> 记住路径后统一用完整路径调用。

## 顶层

```
magpie                         打开 app（窗口 + 菜单栏图标）
magpie tray                    只起菜单栏图标
magpie panel                   开关快捷面板
magpie autostart [on|off]      开机自启
magpie tui                     终端界面
magpie web [--addr host:port] [--lan] [--no-open]   浏览器版（可跑在 WSL/服务器）
magpie ls                      列出探测到的 agent 及其设置      ← 排障第一步
magpie <agent>                 看一个 agent
magpie <agent> <model>         给 agent 设模型
magpie <agent> <field> <value> 设其他字段（如 effort）
magpie <agent> [field] default 还原默认，摘掉 magpie 的接线
```

支持的 agent：`claude (cc)`、`codex`、`gemini`、`opencode (oc)`、`mimocode`、**`pi`**、
`goose`、`cursor`、`copilot`、`crush`。

## 配置档（profiles）

```
magpie save <name>      把当前所有 agent 的设置快照成档案
magpie use <name>       套用档案
magpie profiles         列出
magpie rm <name>        删除
```

## 备份 / 同步

```
magpie backup [--no-keys] [--no-library] [file]     providers+key+设置+档案+agent 模型+library，口令加密
magpie restore [--no-agents] [--no-library] <file>
magpie webdav [on <address>|set k=v…|now|off]       通过 WebDAV 跨机同步
magpie s3 [on s3://<bucket>[/<prefix>]|set k=v…|now|off]
```

## provider

```
magpie providers                        列 provider：host、key、模型数、谁在用
magpie presets                          magpie 内置知道的厂商
magpie provider <id>                    看一个 provider
magpie provider add <preset> <key>      用预设加
magpie provider add <name> k=v…         自定义加
magpie provider set <id> k=v…           改
magpie provider key <id> <key>          换 key
magpie provider icon <id> <file|name>   图标
magpie provider fallback <id> <p/m>…    额度耗尽/宕机时去哪
magpie provider models <id> [ids…]      拉取厂商模型表 / 选择暴露哪些
magpie provider account-models <id> [account|key [ids…|all]]
magpie provider listed <id> yes|no      no: 模型只通过路由组服务，不进列表
magpie provider off|on <id>             关/开（保留配置但停用）
magpie provider test <id> [model…]      发微小请求冒烟测试   ← 判断死活只用这个
magpie provider rm <id>                 删除
```

`add`/`set` 的 k=v 字段：`url`、`anthropic`、`responses`、`key`、`models`、`catalog`、
`icon`、`header.X-Foo`、`balance`、`balance.path`、`balance.token`、`models.url`、`search`、
`proxy`、`family`、`context`、`id`、`name`。

```bash
magpie provider add "My Relay" url=https://relay.example.com/v1 key=sk-…
magpie provider add "Own Claude" anthropic=https://gw.example.com key=sk-… catalog=anthropic
magpie provider set my-relay id=relay         # 重命名（组和 agent 的引用会跟着走）
magpie provider set opencode-go family=ocgo   # 打标签，配合 magpie visible
```

## 模型微调

```
magpie models [<agent>]                            所有可选模型（provider/model）
magpie model name <p/m> <name>|--reset             改显示名
magpie model efforts <p/m> <l>,<l>|--reset         该模型提供哪些推理档
magpie model price <p/m> <in>,<out>,<cacheR>,<cacheW>
magpie model price <model> <...>                   全局兜底价（'*/<model>'）
magpie model prices                                已定价的
magpie model context <p/m> [<n>|--reset]           上下文长度（200000 或 1m）
magpie model output <p/m> [<n>|--reset]            最大输出
magpie model wire <p/m> [<name>|--reset]           实际向厂商请求时用的模型名
magpie model wires / model names
magpie model suffix [on|own|off]                   模型列表里是否带厂商后缀
```

查找顺序：**该模型 → `<provider>/*` → 厂商自带列表 → models.dev**。

## 路由组

```
magpie groups
magpie group <id> | show <id>
magpie group add <name> models=<m1>[,m2…] [routing=…] [stays=…]
magpie group set <id> k=v…
magpie group pick <id> <model>
magpie group rm <id> / restore <id>
magpie group auto [on|off]
magpie group rule add|rm|mv <id> …
```

见 `02-routing-groups.md`。

## 账号与额度

```
magpie accounts [agent] [--json]                 已知订阅 + 额度用量 + 重置时间
magpie accounts add <agent>                      再登录一个 Claude/ChatGPT/Google 订阅
magpie accounts switch <agent> <email>
magpie accounts refresh
magpie accounts checkin                          WorkBuddy 每日签到
magpie accounts project <gemini|antigravity> <email> <project>
magpie quota [<provider>] [--json]               剩余额度
```

## 观测

```
magpie usage [today|7d|30d|all]                  按 agent / 模型统计 token 与成本（默认 30d）
magpie usage --csv [today|7d|30d|all]            每个请求一行 CSV（模型请求值/实际值、token、成本、耗时、状态）
magpie sessions [--model <m>] [--folder <f>] [--json]
magpie sessions --days N|today|all […]           每天各会话花了多少
```

## 插件与库

```
magpie plugin [list] [--json]
magpie plugin add <npm|git|path> / rm / update / on|off / login / logout
magpie plugin move|migrate <subscription>        改用社区插件跑某订阅
magpie plugin move-back|unmigrate <subscription>

magpie library [sync|instructions|mcp|skill]     写进每个 agent 的指令/MCP/skill
magpie library sync
magpie library mcp add <name> <url | command args…> [agents=a,b…]
magpie library skill rm --all [--yes]
magpie library rtk on|off <agent> / install / upgrade
```

## 网关

```
magpie serve                         单独跑网关
magpie healthcheck                   网关应答则 exit 0（容器 HEALTHCHECK 用）
magpie gateway-key list|add <name>|rotate <id>|remove <id>
magpie sync                          刷新模型目录与厂商模型表
magpie agents                        列出支持的所有 agent
magpie update [check]
magpie update auto [on|off] [30m|1h|6h|24h]
magpie search [add <api> <key>|rm <api>]         Tavily / Brave / Exa / Firecrawl / SearXNG
```

## 网关 HTTP 端点（本地实测）

| 端点 | 说明 |
|---|---|
| `GET /v1/models` | 模型列表，200，无需鉴权，~0.03–0.07s |
| `POST /v1/chat/completions` | OpenAI 协议，`Authorization: Bearer <key>`（本地不校验） |
| `POST /v1/messages` | Anthropic 协议，`x-api-key: <key>` + `anthropic-version: 2023-06-01` |
| `GET /v1/magpie/quotas` | 额度快照（JSON） |
| `GET /health` | **404，不存在**，别用它做探活（用 `magpie healthcheck`） |

请求体里的 `"model"` 可以是 `provider/model`、`group/<id>`；返回体里的 `"model"`
是**最终真正服务的模型**，用来验证路由是否按预期工作。
