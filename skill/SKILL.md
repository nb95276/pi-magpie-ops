---
name: pi-magpie-ops
description: >
  管理 magpie（本地模型网关 + 路由中枢）与 pi（coding agent CLI / PI-Desktop 桌面端）的运维技能。
  用于：诊断"响应慢/卡住"、增删 Provider、配置路由组（routing group）、探测网关 127.0.0.1:3425、
  把 pi 接到 magpie、清理失效模型与桌面端历史缓存、区分 pi 与 PI-Desktop 与 PiDeck 的配置归属。
  触发词：magpie、麦格派、路由组、group/auto-、网关、3425、pi 卡、响应慢、provider 死了、
  换模型不生效、PI-Desktop、PiDeck、pi.sqlite、favoriteModels、接线、pi 管理、模型不切换。
---

# pi-magpie-ops — magpie × pi 运维手册

## 这个技能解决什么问题

`magpie` 是你所有 AI agent（Claude Code / Codex / Gemini CLI / OpenCode / **pi** / …）背后的
**统一模型网关**：所有 agent 不直接连各家 API，而是连 magpie，由 magpie 决定"这次请求发给谁"。

所以 agent 出问题时，故障点通常**不在 agent 本身**，而在这三层中的某一层：

```
agent (pi / claude / codex …)
   ↓  ①  agent 的接线：它被指向哪个 provider/model
magpie 网关 (127.0.0.1:3425)
   ↓  ②  路由决策：provider / 路由组 选谁，怎么 failover
上游 provider (anyrouter / ark717 / chatgpt / antigravity …)
   ↓  ③  上游可用性、额度、网络
```

**核心原则：先分层定位，再动手改。** 不要一上来就删 provider 或改 agent 配置。

## 30 秒分层定位

```bash
# 第 0 步：网关活着吗
magpie healthcheck ; echo "exit=$?"          # exit 0 = 网关在答

# 第 1 步：agent 接到哪了（看 Pi 那一行）
magpie ls
magpie pi                                     # 只看 pi 一行

# 第 2 步：这条路线上有哪些 provider / 路由组
magpie providers                              # ● 可用 / ○ 已关
magpie groups                                 # 含 magpie 自动发现的 group/auto-*

# 第 3 步：真发一次请求，看耗时和实际用了谁
magpie provider test <id>                     # 单 provider 冒烟
curl -s -w "\nHTTP %{http_code} %{time_total}s\n" \
  -X POST http://127.0.0.1:3425/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"group/auto-gemini-3-8-flash","messages":[{"role":"user","content":"say OK"}],"max_tokens":16}'
```

请求返回体里的 `"model"` 字段 = **最终真正服务的模型**，这是判断路由是否按预期工作的唯一硬证据。

## 「响应慢」的头号原因：路由组顺序

**症状**：agent 每次回话都卡几十秒到几分钟（实测 343s），但 `magpie healthcheck` 正常。

**根因**：路由组的 `routing=order` 严格按列表顺序发，**第一个成员慢/半死就会一直等**，不会
提前探测下一个。列表第一个恰好接到了一个能连上但极慢的 provider。

**修复**（先验证每个成员，再定序，不要盲删）：

```bash
# 1) 逐个成员测，拿到真实延迟
magpie provider test 717
magpie provider test antigravity

# 2) 把快的放第一位
magpie group set auto-gemini-3-8-flash routing=order models=antigravity/gemini-3.8-flash,717/gemini-3.8-flash

# 3) 复测
```

实测效果：343s → 2.4~3.8s。

**注意**：failover 只在**请求真的失败**时触发，没有"先探测再选"的机制。所以顺序 = 优先级，
第一位必须是你实测最快最稳的那个。

细节见 `references/02-routing-groups.md`。

## 命令索引（高频）

| 目的 | 命令 |
|---|---|
| 列出所有 agent 的接线 | `magpie ls` |
| 看/改某个 agent | `magpie <agent>` / `magpie <agent> <model>` / `magpie <agent> <field> <value>` |
| 把 agent 还原成默认 | `magpie <agent> [field] default` |
| 列 provider | `magpie providers` |
| 加 provider（预设） | `magpie provider add deepseek sk-…` |
| 加 provider（自定义） | `magpie provider add relay url=https://…/v1 key=sk-…` |
| 改 provider | `magpie provider set <id> k=v…` |
| 测 provider | `magpie provider test <id> [model…]` |
| 开关 provider | `magpie provider off|on <id>` |
| 删除 provider | `magpie provider rm <id>` |
| 列路由组 | `magpie groups` |
| 建路由组 | `magpie group add <name> models=<m1>,<m2> routing=order` |
| 改路由组 | `magpie group set <id> k=v…`（`models+=`/`models-=` 单项增删） |
| 手动指定路由 | `magpie group pick <id> <model>` |
| 剩余额度 | `magpie quota [<provider>] [--json]` |
| 用量/成本 | `magpie usage [today|7d|30d|all]` |
| 会话与花费 | `magpie sessions --days 7` |
| 备份/恢复 | `magpie backup` / `magpie restore <file>` |
| 网关密钥 | `magpie gateway-key list|add|rotate|remove` |

完整 CLI 速查（含所有子命令的真实 help 文案）：`references/01-magpie-cli-cheatsheet.md`

## 文件地图（改之前先知道文件在哪）

| 归属 | 路径 | 内容 |
|---|---|---|
| magpie | `~/.config/magpie/providers.json` | provider 与路由组定义 |
| magpie | `~/.config/magpie/settings.json` | 主题、语言、LAN、脱敏 |
| magpie | `~/.config/magpie/quotas.json` | 各订阅额度快照 |
| magpie | `~/.config/magpie/usage.jsonl` | 逐请求用量流水 |
| magpie | `~/.config/magpie/library.json` | 写进各 agent 的指令/MCP/skill |
| magpie | `~/.config/magpie/routing/*.jsonl[.gz]` | 路由决策日志（排障金矿） |
| pi CLI | `~/.pi/agent/models.json` | pi 自己的 provider（**接 magpie 后应只剩 magpie 一个**） |
| pi CLI | `~/.pi/agent/settings.json` | `defaultProvider` / `defaultModel` / retry |
| PI-Desktop | `~/.pi-desktop/pi.sqlite` | 桌面端会话/项目/模型缓存 |
| PI-Desktop | `%APPDATA%\pi-desktop\pi-desktop.json` | 桌面端自己的配置 |
| PiDeck | `%APPDATA%\pi-desktop\settings.json` | **另一个软件**，配置与 PI-Desktop 同目录 |

⚠️ `%APPDATA%\pi-desktop` 同时被 PI-Desktop(Electron userData) 和 PiDeck 占用，
`settings.json` 里的 `favoriteModels` / `customPiPath` / `petEnabled` 属于 **PiDeck 不是 PI-Desktop**。
详见 `references/04-desktop-collision.md`。

## pi 接 magpie 的标准姿势

**不要手写 `models.json`：**

```bash
magpie pi group/auto-gpt-6-1-sol     # magpie 自己把接线写进 ~/.pi/agent/
magpie pi                            # 复核
```

magpie 生成的是这样的结构（`~/.pi/agent/models.json`）：

```json
{
  "providers": {
    "magpie": {
      "api": "openai-completions",
      "apiKey": "magpie",
      "baseUrl": "http://127.0.0.1:3425/v1",
      "models": [
        { "id": "group/auto-gpt-6-1-sol", "name": "GPT-6.1-Sol · routing group",
          "contextWindow": 272000, "maxTokens": 128000, "reasoning": true,
          "thinkingLevelMap": { "low": "low", "medium": "medium", "high": "high", "xhigh": "xhigh" } }
      ]
    }
  }
}
```

要点：
- `apiKey` 就是字面量 `"magpie"`（本地网关不校验），baseUrl 必须是 `http://127.0.0.1:3425/v1`
- 走 OpenAI 协议的模型用 `openai-completions`；magpie 也会为 `anthropic-messages` 的模型
  写 `baseUrl: http://127.0.0.1:3425`（无 `/v1`）
- 端到端验证：
  ```bash
  pi -p --provider magpie --model group/auto-gpt-6-1-sol "print the token PI_WIRING_OK"
  ```

**反模式**：在 `~/.pi/agent/models.json` 里同时保留一堆直连 provider。
实测：直连 provider 全死时，pi 启动会逐个探测，单次调用 34s → 清理后 7~8s。
清理前务必**逐个真调验证**再删，别盲删。

## 铁律

1. **改前先备份**：`magpie backup`，或至少 `Copy-Item providers.json providers.json.bak`。
2. **优先用 magpie CLI**，不手改 `providers.json` —— 手改容易与网关内存状态不一致。
3. **删 provider 前必须真调验证**（`magpie provider test <id>`），并把"暂时不用"和"已经死了"
   区分开：前者用 `magpie provider off <id>`，后者才 `rm`。
4. **用户点名要留的 provider，无论健康与否都不删。**
5. **改完必须自己复测**（healthcheck + 真请求 + `magpie ls`），不要把验证丢给人。
6. **桌面端 `pi.sqlite` 有锁**：直接打开会被占用，先快照副本再操作，并设 `busy_timeout`。

## 参考文档

- `references/01-magpie-cli-cheatsheet.md` — 完整 CLI 速查
- `references/02-routing-groups.md` — 路由组语义、routing/stays/effort、实测数字
- `references/03-file-map.md` — 全部配置文件与日志路径地图
- `references/04-desktop-collision.md` — pi / PI-Desktop / PiDeck 三方目录撞车辨析
- `references/05-troubleshooting.md` — 排障清单与已归档案例

## 脚本

```bash
python scripts/magpie_doctor.py      # 一键体检：二进制定位→配置→provider→路由组→网关→pi 接线
python scripts/gateway_probe.py      # 网关端点探测（含 /v1/chat/completions 真实调用与计时）
python scripts/gateway_probe.py --json
```

两个脚本都是**只读**的：只报告，不改任何配置。
