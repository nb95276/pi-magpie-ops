# 04 · pi / PI-Desktop / PiDeck 三方目录撞车辨析

> 这份文档来自一次真实误判：花了大半天在 PI-Desktop 里找 `favoriteModels`，最后发现
> **那个配置根本不是 PI-Desktop 的，是另一个软件的**。

## 三个东西，别当成一个

| 名字 | 是什么 | 程序位置 | 配置位置 |
|---|---|---|---|
| **pi** (CLI) | 命令行 coding agent，npm 包 `@earendil-works/pi-coding-agent` | npm global `dist/bundle/cli.js` | `~/.pi/agent/` |
| **PI-Desktop** | 桌面版 GUI（Electron），作者 vastsa | `%LOCALAPPDATA%\Programs\PI-Desktop\` | `%APPDATA%\pi-desktop\pi-desktop.json` + `~/.pi-desktop\pi.sqlite` |
| **PiDeck** | **另一个**桌面 GUI，作者 ayuayue，package name 也叫 `pi-desktop` | `%LOCALAPPDATA%\Programs\PiDeck\PiDeck.exe` | `%APPDATA%\pi-desktop\settings.json` |

三者版本号**互相独立**，不要拿一个的版本去推断另一个：

- CLI：`pi --version` → 例如 `1.0.0`
- PI-Desktop：`0.16.0`
- PiDeck：自己一套

**PI-Desktop 无法指向全局 CLI。** 它把 agent runtime 打包在自己的 `resources/agent-runtime/` 里
（`sidecar.js`），二进制扫描确认它**不读**任何 `cliPath` / `PI_CLI_PATH` 之类的环境变量覆盖点。
所以「升级 PI-Desktop 里的 pi」= 升级 PI-Desktop 本身。

## 撞车点：`%APPDATA%\pi-desktop`

Windows 文件系统**大小写不敏感**，所以：

- PI-Desktop 的 Electron `userData` = `C:\Users\<你>\AppData\Roaming\pi-desktop`
- PiDeck 的 userData 也是 `C:\Users\<你>\AppData\Roaming\pi-desktop`

两者**落在同一个目录里**。于是同一个目录下同时躺着：

```
%APPDATA%\pi-desktop\
├── pi-desktop.json     ← PI-Desktop 的（Electron 主配置）
├── settings.json       ← PiDeck 的（不是 PI-Desktop 的！）
├── Local Storage\      ← 浏览器的
├── Preferences         ← Electron 通用
└── ...
```

**`settings.json` 里的这些键属于 PiDeck，改它们不影响 PI-Desktop：**

`favoriteModels`、`customPiPath`、`petEnabled`、`sendShortcut`、`piRpcOffline`、
`telemetryEnabled`、`rpcTimeout`、`webServicePort`、`piProxyUrl`、`desktopProxyUrl`、
`enableGitManagement`、`externalEditors` …

辨别特征：
- 出现 `customPiPath` / `petEnabled` / `favoriteModels` → **PiDeck**
- 出现 `agent-runtime` / sidecar 相关、`app-update.yml` owner 对上 → **PI-Desktop**

## 怎么确认某个键属于哪个软件（不用猜）

反向验证：**把程序的 asar 解包做字节扫描**，看它到底认不认识这个键。

```powershell
# 1) 找到程序的 app.asar
Get-ChildItem "$env:LOCALAPPDATA\Programs" -Recurse -Filter app.asar -ErrorAction SilentlyContinue |
  Select-Object FullName, Length

# 2) 在 asar 里搜关键词（asar 头是 JSON，字符串原文都在里面）
Select-String -Path <path>\app.asar -Pattern 'favoriteModels' -SimpleMatch -Encoding Default

# 3) 顺便把 ASCII 字符串全捞出来数一数（确认文件里有几千个条目、扫描确实生效）
#    命中 0 次 ≠ 扫描失败，要先用一个必然存在的词（如 'userData'）做阳性对照
```

**实例（本仓库的方法论来源）：**

| 程序 | asar 条目数 | `favoriteModels` 命中 | 结论 |
|---|---|---|---|
| PI-Desktop 0.16.0 | 571 | **0** | 没有收藏功能，settings.json 里那条不是它的 |
| PiDeck | 1804 | **8** | `favoriteModels` 默认值、`customPiPath` ×39 全都在 |

再补一条佐证：PiDeck 的 `debug.log` 修改时间 == `settings.json` 修改时间 → 就是它写的。

> ⚠️ 扫描前一定先做**阳性对照**：如果连 `userData` 都 0 命中，是扫描姿势错了，不是程序没这个键。

## 相关扩展：桌面端的会话/模型缓存

PI-Desktop 的 `~/.pi-desktop/pi.sqlite` 里存会话、项目、**模型缓存**。

- `models` 表里残留的模型，是**历史上被写进去的**，删掉 provider 后它自己不会消失
- 清缓存 = 直接操作 sqlite 表，**必须**：
  1. 先复制一份快照再动手（桌面端可能锁着库）
  2. 设 `busy_timeout`（例：`PRAGMA busy_timeout=20000;`）
  3. 改完 `PRAGMA integrity_check;` + 行数对账

实测：清理 194 → 180 行，仅删掉指向已删 provider 的模型记录。

## 排查顺序（撞车场景）

```
1. 用户说的"配置没生效"，先问：哪个软件？
2. 找不到那个键？
   a. 该程序目录 asar 字节扫描（阳性对照 + 目标键）
   b. 若无 → 换程序扫描（本地同类桌面端全扫一遍）
   c. 找到后 → 看 debug.log / 文件 mtime 与该程序最后运行时间是否吻合
3. 确认归属再改，改前备份 + diff 验证只动了一个键
```

**教训**：不要假设"同一个目录名 = 同一个软件"。也不要在自己程序里找不到某个键时，
就去手改那个键——先证明它属于谁。
