# 路由组（Routing Group）语义

## Group 是什么

**把多个 provider 上的同一个模型（或一组模型）打包成一个逻辑模型**，agent 只看到一个名字，
用 `group/<id>` 表示：

```
group/auto-gpt-6-1-sol  →  717/gpt-6.1-sol  ·  codex/gpt-6.1-sol
```

好处：agent 侧零改动。上游哪个挂了、额度用完了、想换更便宜的路子，改 group 就行，agent 不用动。

## 两种来源

### 1. magpie 自动发现的组（`auto-<model>`）

当**两个或以上 provider 提供同一个模型**时，magpie 自动生成一个组，id 形如 `auto-<model>`。
这类组**从不落盘**，是实时算出来的。

- `magpie group auto off` → 停止自动发现（自己建的和改过的保留）
- 想让自动组的 id 短一点：`magpie group set auto-gpt-6-astra id=gpt-6-astra`
  （⚠️ 改了 id 后，已指向旧 id 的 agent 需要重新设置）

### 2. 自己建的组（存在 `providers.json` 的 `groups` 数组）

```json
{
  "id": "auto-gemini-3-8-flash",
  "name": "Gemini 3.8 Flash",
  "members": ["antigravity/gemini-3.8-flash", "717/gemini-3.8-flash"],
  "routing": "order"
}
```

**删除自动组**的做法很特别：不是真删，而是在 `providers.json` 里写一条
`{"id": "…", "hidden": true}` 记录（这就是"记住它被删了"的机制）。
把这条记录从文件里拿掉，组就回来了（等价于 `magpie group restore <id>`）。

## routing（选谁）—— 这是性能的关键

| routing | 行为 | 什么时候用 |
|---|---|---|
| `smart`（默认） | 在有额度的订阅里，**最先重置的那个优先** | 多个订阅轮换，想省钱 |
| `order` | **严格按 members 顺序**，第一个不行才下一个 | 有明确的"主力 + 备用" |
| `rotate` | 每次新回合换下一个成员 | 分散用量 |
| `usage` | 剩余额度最多的优先 | 多 key 均衡 |
| `manual` | 只用 `pick=` 指定的那个，**不 failover** | 锁定某条线路排障 |

### ⚠️ `order` 的性能陷阱

**这是"响应慢/卡住"的头号原因。**

`order` 只在**请求真的失败**时才切换到下一个。**没有事先探测**。
如果第一个成员处于"能连上但极慢"的状态（比如上游限流、被墙一半、排队），
每一次请求都会老老实实等它，卡到超时才算失败，然后再走下一个。

带 `smart` 的同理：`smart` 挑的是"最先重置的"，不代表快。

**正确做法**：
1. 先用 `magpie provider test <id>` 逐个测成员的真实延迟
2. 把最快最稳的放 `order` 列表第一位
3. 改完立即复测端到端耗时

实例：`auto-gemini-3-8-flash` 原本第一个成员很慢 → 343s；调整为
`models=antigravity/gemini-3.8-flash,717/gemini-3.8-flash routing=order` → 2.4~3.8s。

## stays（会话粘性）

| stays | 含义 |
|---|---|
| `auto`（默认） | 缓存还值得留时，继续用上次答话的账号/key |
| `session` | 整个会话都粘住 |
| `turn` | 只在一个回合内粘住，下次说话重新路由 |
| `off` | 每个请求都重新路由 |

调 `stays=off` 会让 prompt cache 频繁失效 → 更贵更慢。
只在明确需要打散时才用。

## effort（推理档位）

- `effort=agent`（默认）：agent 要多少就给多少，但受成员自带的 `:<effort>` 约束
- `effort=auto`：每回合开始时，用一个分类模型判断难度，自动给 low/medium/high/xhigh
  - 需要配 `classifier=<provider/model>` 或 `group/<id>`

## 成员写法（members 语法）

```
provider/model                      普通成员
provider/model:high                 固定推理档位（覆盖 agent 的请求）
provider/model:high:fast            再用厂商的 fast 模式
group/<其他组>                       嵌套组（最多 8 层，不能自嵌套）
```

- 同一个模型配两个不同 effort = 两个独立成员（规则可以分别指向）
- 模型 id 本身以 `:free` / `:7b` / `:0` 结尾时按原样保留，不会被当 effort 解析
- `:fast` 只有支持的模型能用（Codex 的 Fast、OpenAI key、Cursor 的 -fast、Anthropic key 上的 Opus 4.8/5）

## 组的其他可调字段

```bash
magpie group set <id> k=v…
```

| 字段 | 说明 |
|---|---|
| `name` | 显示名 |
| `models` | **整个**成员列表（按顺序） |
| `models+=<m>` / `models-=<m>` | 追加 / 删除单个成员 |
| `routing` | `smart|order|rotate|usage|manual` |
| `stays` | `auto|session|turn|off` |
| `context` | 告诉 agent 这个组"多长"（如 `272k`；空 = 取最短的成员） |
| `levels` | 向 agent 提供的推理档位（如 `levels=none,low,medium,high`） |
| `family` | 打标签，配合 `magpie visible` 批量控制可见性 |
| `id` | 改 id（指向旧 id 的 agent 需要重新设置） |
| `effort` / `classifier` | 见上 |
| `pick` | `routing=manual` 时用的固定成员 |
| `fast` | 哪些成员走厂商 fast 模式 |

## 组规则（rules）：按条件选成员

```bash
magpie group rule add|rm|mv <id> …      # 帮助见 magpie group rule help
```

可依据：请求长度、是否带图、要求的推理档位、是哪个 agent。

## 常用排障命令

```bash
magpie group <id>                    # 看一个组的完整定义
magpie groups                        # 所有组（自己的 + 自动发现的）
magpie group pick <id> <model>       # 临时锁定某条线路
magpie model efforts <provider/model>   # 某模型支持哪些推理档位
magpie models <agent>                 # 某 agent 能选哪些模型（含"为什么别的不可选"）
```
