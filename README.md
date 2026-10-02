# pi-magpie-ops

**实测沉淀的 magpie × pi 运维手册** —— 把「本地模型网关 + coding agent」这一栈的诊断经验固化成
一个可直接安装的 skill、两个只读诊断脚本，和一本踩坑案例集。

> 全部内容来自真实排障现场：每一条结论都有真实请求的返回体和耗时作证据，不含推测性建议。

---

## 它解决什么问题

当代 agent 工作流通常是这样的：一堆客户端（pi / Claude Code / Codex / Gemini CLI / OpenCode /
Cursor / Crush …）**都不直连各家 API**，而是连一个本地网关（magpie），由网关决定「这次请求发给谁」。

好处是随处都能换模型、多订阅自动 failover、统一算额度。代价是——
**出问题时故障点不在你面前那个 agent 上，而在这条链的某一层：**

```
agent (pi / claude / codex …)
   ↓  ①  接线：agent 被指向哪个 provider / model
magpie 网关 (127.0.0.1:3425)
   ↓  ②  路由决策：provider / 路由组选谁，怎么 failover
上游 provider (anyrouter / ark717 / chatgpt / antigravity …)
   ↓  ③  上游可用性、额度、网络
```

**本仓库的核心主张：先分层定位，再动手改。不要一上来就删 provider 或改 agent 配置。**

因为三层的症状高度相似（都是「慢」或「不生效」），但修法完全不同。

---

## 招牌案例：343s → 2.4s

| | |
|---|---|
| **症状** | agent 每轮回话卡几十秒到几分钟，但 `magpie healthcheck` exit 0，网关「看着完全正常」 |
| **层级** | 第 ② 层（路由） |
| **根因** | 路由组用 `routing=order`，**严格按列表顺序发第一个成员**。列表第一位是个「TCP 能连上、实际极慢」的 provider，于是每次都在死等它 |
| **关键认知** | `order` 模式下 **failover 只在请求真的失败时触发，没有「先探测再选」**。所以顺序就是优先级；半死的 provider 比彻底死掉的更坑 |
| **修复** | 逐个成员实测延迟 → 快的排前面（`magpie group set … routing=order models=<fast>,<slow>`） |
| **结果** | **343s → 2.4~3.8s** |

这是「不看真实请求耗时就会被误导」的典型：日志正常、健康检查正常、配置看着也对，
唯一的线索是**真发一次请求并看返回体里的 `"model"` 字段**——那是判断路由是否按预期工作的唯一硬证据。

---

## 仓库结构

```
pi-magpie-ops/
├── skill/                       # 可直接安装的 skill（skill-creator 校验通过）
│   ├── SKILL.md                 # 30 秒分层定位 + 命令索引 + 文件地图 + 铁律
│   ├── references/
│   │   ├── 01-magpie-cli-cheatsheet.md    # 完整 CLI 速查（真实 help 文案）
│   │   ├── 02-routing-groups.md           # 路由组语义：routing / stays / effort
│   │   ├── 03-file-map.md                 # 全部配置文件与日志路径
│   │   ├── 04-desktop-collision.md        # pi / PI-Desktop / PiDeck 目录撞车辨析
│   │   └── 05-troubleshooting.md          # 六个已归档排障案例
│   └── scripts/
│       ├── magpie_doctor.py               # 一键只读体检
│       └── gateway_probe.py               # 网关端点探测（含真实调用与计时）
└── docs/
    └── why-layered.md         # 方法论：为什么必须先分层、证据从哪来
```

---

## 快速开始

### 1. 装 skill（可选，给 agent 用）

```bash
# Windows
Copy-Item -Recurse skill "$env:USERPROFILE\.agents\skills\pi-magpie-ops"
# macOS / Linux
cp -r skill ~/.agents/skills/pi-magpie-ops
```

装好后，agent 遇到「响应慢 / 换模型不生效 / provider 死了 / 网关不通」会自动加载本技能。

### 2. 跑脚本（不装 skill 也能用，纯标准库，无第三方依赖）

```bash
python skill/scripts/magpie_doctor.py            # 一键体检：二进制定位→配置→provider→路由组→网关→接线
python skill/scripts/magpie_doctor.py --json     # 机器可读，退出码非 0 表示有 FAIL

python skill/scripts/gateway_probe.py            # 端点探测 + 一次真实 completion（带计时）
python skill/scripts/gateway_probe.py --no-call  # 只探只读端点
```

**两个脚本都是只读的**：只报告，不改任何配置，也不会执行任何有副作用的 magpie 子命令。

### 3. 手动 30 秒分层定位

```bash
magpie healthcheck                    # exit 0 = 网关在答（注意 /health 这个 HTTP 端点不存在，是 404）
magpie ls                             # 各 agent 的接线一览
magpie providers                      # provider 总览（● 可用 / ○ 已关）
magpie groups                         # 路由组总览
magpie provider test <id>             # 单 provider 冒烟测试 —— 唯一可信的存活证据
```

### 4. 复现「路由慢」的检测

```bash
curl -s -w "\nHTTP %{http_code}  %{time_total}s\n" \
  -X POST http://127.0.0.1:3425/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"group/auto-xxx","messages":[{"role":"user","content":"say OK"}],"max_tokens":16}'
```

看两个东西：**耗时**，和返回体里的 **`"model"`**（最终真正服务的模型）。

---

## 六条铁律

1. **改前先备份** —— `magpie backup`，或至少 `Copy-Item providers.json providers.json.bak`。
2. **优先用 CLI，不手改 `providers.json`** —— 手改容易与网关内存状态不一致。
3. **删 provider 前必须真调验证** —— 并把「暂时不用」（`off`）和「已经死了」（`rm`）区分开。
4. **用户点名要留的 provider，无论健康与否都不删。**
5. **改完必须自己复测** —— healthcheck + 真请求 + 接线复核，不要把验证丢给人。
6. **桌面端 sqlite 有锁** —— 先做快照副本，再设 `busy_timeout`，改完 `integrity_check`。

---

## 容易踩的坑（摘要）

| 坑 | 真相 |
|---|---|
| `magpie` 命令敲不出来 | 它是便携版 exe，常**不在 PATH** 上。用 `Get-Process magpie* \| Select Path` 反查真实路径 |
| `%APPDATA%\magpie-windows-amd64.exe` 是个 exe？ | **是 WebView2 数据目录**，不是可执行文件 |
| `settings.json` 里的 `favoriteModels` 改了没反应 | 它在 `%APPDATA%\pi-desktop\`，是**另一个软件（PiDeck）**的配置，不是 PI-Desktop 的 |
| `/v1/models` 里有这个模型 = provider 健康 | **错**。它只反映本地登记了什么，**不校验上游可用性** |
| 网关有个 `/health` 端点？ | **不存在**，HTTP 404。用 CLI `magpie healthcheck` |
| 本地网关要 API key | 回环地址**不校验**。`models.json` 里的 `apiKey: "magpie"` 只是占位字面量 |

细节见 `skill/references/`。

---

## 适用版本

本手册的实测环境：

- `magpie` 0.1.632（Windows amd64）
- `pi` CLI 1.0.0
- PI-Desktop 0.16.0

CLI 子命令与文件布局在这些版本上逐一核对过。其他版本可能有多寡，
但**分层模型和排查方法本身与版本无关**。

---

## License

MIT — 见 [LICENSE](LICENSE)。
