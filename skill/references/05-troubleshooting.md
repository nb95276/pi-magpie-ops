# 05 · 排障清单与案例库

排障的通用姿势：**先分层定位（agent 接线 → magpie 路由 → 上游），拿真实请求计时，再动手。**

---

## 案例 1 ·「响应怎么这么慢，卡在哪了」— 343s

**症状**：pi 每轮回话卡几十秒到几分钟，但 `magpie healthcheck` exit 0，网关看着完全正常。

**定位过程**：

```bash
magpie healthcheck                 # exit=0        → 网关没问题（第 0 层排除）
magpie ls                          # Pi 那行接线正常 → 第 1 层排除
magpie groups                      # 看到 group/auto-gemini-3-8-flash
# 关键一步：真发请求，看耗时 + 返回体里的 "model"
curl -s -w "\nHTTP %{http_code} %{time_total}s\n" -X POST \
  http://127.0.0.1:3425/v1/chat/completions -H "Content-Type: application/json" \
  -d '{"model":"group/auto-gemini-3-8-flash","messages":[{"role":"user","content":"say OK"}],"max_tokens":16}'
```

**根因**：路由组 `routing=order`，**严格按列表顺序发第一个成员**。列表第一位是
一个「TCP 能连上、但实际极慢」的 provider，于是每次都在死等它。

**修复**：

```bash
magpie provider test 717            # 逐个成员实测，拿到真实延迟
magpie provider test antigravity
magpie group set auto-gemini-3-8-flash routing=order \
  models=antigravity/gemini-3.8-flash,717/gemini-3.8-flash   # 快的放前面
```

**结果**：343s → **2.4~3.8s**。

**关键认知**：
- `order` 模式下 **failover 只在请求真的失败时触发，没有「先探测再选」**。所以顺序就是优先级。
- 半死（能连上、极慢）的 provider **不会被自动跳过**，比彻底死掉的更坑。
- 所以：`order` 的第一个成员必须是你**实测过**最快最稳的那个。

---

## 案例 2 ·「provider 死了吗，能删吗」— 死/关/留三分类

**问题**：一堆 provider，哪些删、哪些留、哪些只是暂时不用？

**原则：先把「暂时不用」和「已经死了」分开。**

```bash
magpie providers                       # ● 可用 / ○ 已关，先看总览
magpie provider test <id>              # 逐个真调，这是唯一证据
magpie provider test <id> <model…>     # 针对具体模型再测
```

| 判定 | 动作 |
|---|---|
| `provider test` 真实报错（401/404/超时/连不上） | `magpie provider rm <id>` |
| 能用但当前不想用 | `magpie provider off <id>`（保留配置，随时 `on`） |
| **用户点名要留** | **什么都不做**，无论健康与否 |

**反例（血的教训）**：只看 `/v1/models` 列表里有它还活着就以为健康 —— 错。
`/v1/models` **不校验上游可用性**，只反映本地配置里登记了什么。
必须真发一次 completions 请求才算证据。

**另一个坑**：删 provider **不会自动清理引用它的路由组成员**。删完要复查：

```bash
magpie groups                          # 看有没有组还挂着已删的 <provider>/<model>
magpie group set <组id> models-=<provider>/<model>
```

---

## 案例 3 ·「收藏的模型还在，但 provider 早删了」— 幽灵配置

见 `04-desktop-collision.md`。简版：

1. 在 PI-Desktop 里死活找不到 `favoriteModels` → **正常，它不属于 PI-Desktop**
2. 字节扫描 asar：PI-Desktop 0 命中，**PiDeck** 8 命中 → 归属确认
3. 备份 → 改成 `[]` → diff 验证只动了这一个键 → JSON 合法性校验

**通用教训**：本程序里找不到的键，不要盲改；先**证明它属于谁**。

---

## 案例 4 ·`pi.sqlite` 被占用，打不开

**症状**：直接打开桌面端的 `~/.pi-desktop/pi.sqlite` → database is locked。

**做法**：

```powershell
# 不要在活库上操作。先做快照副本
Copy-Item "$env:USERPROFILE\.pi-desktop\pi.sqlite" "$env:PI_SCRATCH_DIR\pi.sqlite" -Force
```

```python
# 打开快照时仍设 busy_timeout，容忍残余锁
con = sqlite3.connect(snapshot_path, timeout=20)
con.execute("PRAGMA busy_timeout=20000;")
# …改完…
con.execute("PRAGMA integrity_check;")   # 必须做
# 再和改前对账行数（例：194 → 180，只少了预期的那批）
```

改前先备份原库（`$env:PI_SCRATCH_DIR\pidb-backup-<时间戳>\`）。

---

## 案例 5 · magpie 不在 PATH 上

`magpie` 命令敲不出来，但网关明明在跑。

**真相**：它是便携版 exe，装在下载目录里，**从没进 PATH**。

```powershell
# 通过正在运行的进程反查 exe 全路径 —— 最可靠的方法
Get-Process magpie* | Select-Object Id, Path, StartTime
```

**易踩的假路径**：

| 路径 | 实际是什么 |
|---|---|
| `%APPDATA%\magpie-windows-amd64.exe` | 是 **WebView2 数据目录**，不是 exe！ |
| `%LOCALAPPDATA%\magpie\market\` | 商店图标/关于/skill 缓存 |
| `~/.config/magpie/` | 真正的配置目录 |

拿到全路径后直接用绝对路径调用，或自己加进 PATH。

---

## 案例 6 · agent 启动/首字慢 — 残留的死 provider

**症状**：pi 单次调用 34s，删掉死 provider 后 7~8s。

**根因**：`~/.pi/agent/models.json` 里同时挂着一堆**直连** provider，全死时启动会逐个探测。

**正确姿势**：pi 应该只留 magpie 一个 provider，由 magpie 去做多路复用：

```bash
magpie pi group/auto-gpt-6-1-sol     # 官方接线，别手写 models.json
magpie pi                            # 复核
pi -p --provider magpie --model group/auto-gpt-6-1-sol "print PI_WIRING_OK"
```

清理前**必须逐个真调验证**，别盲删。文件备份到 `$env:PI_SCRATCH_DIR\pi-cleanup-<时间戳>\`。

---

## 附：通用排障命令集合

```bash
magpie healthcheck                     # 网关活着吗（exit 0 = 正常；注意没有 /health 这个 HTTP 端点，是 404）
magpie ls                              # 各 agent 接线总览
magpie providers                       # provider 总览（●/○）
magpie groups                          # 路由组总览
magpie provider test <id>              # 单 provider 冒烟
magpie quota                           # 各订阅额度与重置时间
magpie usage today                     # 今日用量/成本
magpie backup                          # 改前备份
```

网关端点探测（本仓库脚本）：

```bash
python scripts/gateway_probe.py            # 带真实 completions 调用与计时
python scripts/gateway_probe.py --json
python scripts/magpie_doctor.py            # 一键只读体检
```

**注意**：网关的 `/health` **不存在**（HTTP 404）。健康检查用 CLI `magpie healthcheck`，
或 GET `/v1/models`（200 即网关在答）。

---

## 改任何东西之前，先问自己三个问题

1. **证据是什么？** —— 有没有真实请求的返回体和耗时，还是只看了列表？
2. **备份在哪？** —— `magpie backup` 或 `Copy-Item`，路径写下来。
3. **怎么复测？** —— 改完用什么命令证明修好了？现在就写出来。

三个都答不上来，就还没到动手的时候。
