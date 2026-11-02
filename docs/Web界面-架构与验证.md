# Web UI 外壳（DSH 架构）

> **整个窗口就是一个 HTML 页面** —— 壁纸、玻璃、UI 全在 Chromium 里画。
> Qt 只负责开一个浏览器窗口，画面里一个 Qt 控件都没有。

---

## 一句话：怎么开

```powershell
cd "D:\AI Work\workbuddy\MyTools"

# 环境变量方式（推荐，不改用户配置）
$env:MYTOOLS_WEB_SHELL = "1"
.venv\Scripts\python.exe main.py
```

或者写进 `config/config.json`：

```json
{
  "UI": {
    "WebShell": true
  }
}
```

**默认是关闭的**（走旧的 `MainWindow`）。开关优先级：

1. 环境变量 `MYTOOLS_WEB_SHELL`（`1`/`true`/`yes`/`on`）
2. `config.json` 的 `UI.WebShell`
3. 都没有 → **`false`**（旧界面）

> ⚠ 为什么默认关：新外壳是 P1 骨架，部分页面还是占位。等功能迁完再翻默认值。
> 新外壳**起不来时会自动退回旧界面**，不会让程序开不了。

---

## 为什么要换架构

用户原话：**「完全按 DSH 那样做」**。

DSH 是 Electron 应用 —— 整个窗口就是一个 Chromium 页面。

MyTools 原来把 `QWebEngineView` 当**子控件**塞进 Qt 主窗口：

```text
QMainWindow（Qt 渲染）
  ├── 侧栏 / 标题栏 / 卡片  ← Qt 画的
  └── QWebEngineView        ← Chromium 画的，当壁纸层
```

两个渲染器、两套合成。用户报的「窗口放大后 Chromium 纹理被平铺」
就是这个架构的症状。

现在的架构：

```text
QWebEngineView（顶层窗口，无任何 Qt 界面元素）
  └── index.html
        ├── <video>      壁纸（position:fixed; inset:0）
        ├── .glass       玻璃面板（backdrop-filter）
        └── #sidebar / #titlebar / #content   全部 HTML
```

和 DSH 完全一致 —— **只有一个渲染器**。

### ⚠ 关于平铺根因的实测更正

早期结论是「**view 作为子控件必然平铺**」。**这个结论经实测不成立。**

我在同一进程、同一份真实页面（带玻璃 + 视频壁纸）里对照了 4 种宿主：

| 方式 | 结果 |
|---|---|
| A 顶层 `QWebEngineView()` | 无平铺 |
| B `QMainWindow.setCentralWidget(view)` | 无平铺 |
| C 无边框 Tool 窗口 | 无平铺 |
| D **完全照旧代码**（子控件 + 手动 `setGeometry` + `lower()` + 400ms 同步定时器） | 无平铺 |

5 个尺寸（放大 → 更大 → 缩小 → 再放大）全部通过，断言是
`#wallpaper-layer` 的 `getBoundingClientRect()` **严格等于** viewport。

所以旧 bug 的根因**不在「子控件」这个属性**上。剩下的候选：
「两套渲染器合成同一块画面」、旧页面是 `setHtml()` 单视频页、
特定 GPU 驱动路径。

**架构不变** —— 整窗 HTML 本来就该这么做（壁纸和 UI 同一渲染器），
只是「为什么换架构就好了」这个解释不依赖平铺是否复现。

---

## 目录结构

```text
src/
├── core/
│   ├── web_bridge.py       ★ Python ↔ JS 桥（QWebChannel）
│   └── media_server.py       本地 HTTP（页面 + 视频 + 素材同源）
└── gui/
    ├── web_shell.py         ★ Qt 宿主（QWebEngineView 顶层窗口）
    └── web/                 ★ 前端资源
        ├── index.html         主骨架
        ├── css/
        │   ├── base.css       变量 + 重置
        │   ├── glass.css      ★ 液态玻璃（DSH 配方）
        │   └── layout.css     侧栏 + 标题栏 + 内容区
        ├── js/
        │   ├── bridge.js      QWebChannel 封装（Promise + 事件总线）
        │   ├── app.js         路由 / 皮肤 / 壁纸 / 状态
        │   └── pages/
        │       ├── _shared.js   页面公共层
        │       ├── home.js      主页（工具卡片）
        │       ├── tasks.js     任务页
        │       ├── config.js    配置页
        │       ├── library.js   资源库
        │       ├── skin.js      主题皮肤
        │       └── simple.js    检查更新 / 消息通知
        ├── assets/icons/      工具图标（从 assets/icons 镜像）
        └── dev/               ★ 验证脚本（见下）
```

---

## 玻璃配方（照 DSH）

全部逆向自 `dsh-plugin-wallpaper-engine/lib/client.js`。

DSH 的玻璃不是「一张模糊图」，是 **4 层**叠出来的：

```css
.glass {
  /* ① 顶部白高光：让平面变成「湿玻璃」 */
  background-image: linear-gradient(180deg,
    rgba(255,255,255,0.10) 0%,
    rgba(255,255,255,0.045) 42%,
    rgba(255,255,255,0.02) 100%);

  /* ② 主题底色 @ 可读性下限 + 玻璃色 @ (1-floor) */
  background-color: rgba(13, 21, 36,
    calc(var(--we-readability-floor) + var(--we-glass-alpha) * (1 - var(--we-readability-floor))));

  /* ③ ★ GPU 实时模糊面板背后的壁纸 */
  backdrop-filter: blur(16px) saturate(1.8) brightness(1.04) contrast(1.01);

  /* ④ 玻璃厚度：内高光 + 内暗边 + 0.5px 描边 + 外投影 */
  box-shadow:
    inset 0 1px 0 rgba(255,255,255,0.32),
    inset 0 -1px 0 rgba(255,255,255,0.08),
    inset 0 0 0 0.5px rgba(255,255,255,0.08),
    0 12px 40px rgba(0,0,0,0.12);
}
```

### ★ 可读性下限（readability floor）—— DSH 最精妙的一处

纯透明的玻璃压在亮壁纸上，文字就看不清。DSH 的解法**不是**提高
面板不透明度（那样玻璃就没了），而是用 `color-mix` 把主题底色
按权重压在玻璃色下面：

```text
effective alpha = floor + a_glass × (1 − floor) ≥ floor
```

滑杆只改 `a_glass`，**floor 那项固定不动** → 下限不可能被削弱。

本项目用 rgba 直接算好（不需要可调滑杆）：

| 主题 | `--we-readability-floor-base` | `--we-glass-alpha` | 最终不透明度 |
|---|---|---|---|
| 深色 | 0.59 | 0.40 | **0.754** |
| 浅色 | 0.45 | 0.40 | 0.670 |

侧栏用 `rgba(10, 9, 19, 0.92)`（实测 DSH 是 `#0a0913`）——
侧栏是「骨架」不是「内容」，压得更实，内容区的玻璃才显得透。

---

## 桥接接口（`src/core/web_bridge.py`）

### 读

| 方法 | 返回 |
|---|---|
| `getTools()` | 7 个工具的元信息（含 `iconUrl`） |
| `getNav()` | 侧栏导航（**顺序对齐旧界面** + 工具分组，见下） |
| `getAppInfo()` | 名称 / 版本 / 作者 |
| `getSkin()` | 当前配色 `{primary, dim, text, bg, css, card, border, mode}` |
| `getSkinList()` | 全部皮肤（含 `bg` / `css` 供预览条） |
| `getWallpaper()` | 当前壁纸 + 可用列表 |
| `getStatus()` | 运行状态 |
| `getFlowList()` | 任务流程（1 条） |
| `getConfigList()` | `{loadouts, echoProfiles}`（**带头像兜底 + 拼音索引**） |
| `getGachaHistory()` | 抽卡历史（按**账号 × 年月**聚合，复用旧模块） |
| `getGachaOverview()` | 欧皇卡 6 个数字（本地缓存统计，**复用 `GachaReport`**） |
| `getGachaPoolDetail()` | 逐条出金列表（`span` 条长 + `barColor` + `verdict`，**最新在前**） |
| `getLibraryData()` | 61 角色 / 37 套装 / 187 声骸 / 123 武器（**150 KB**） |
| `getOkwwState()` | ok-ww 宿主状态 + 任务映射表（见下） |
| `getToolSettings(toolKey)` | 工具设置 + `defaults` + `choices`（**没有 `prerequisites`**，见坑 #15） |
| `getCombatHistory()` | 4C 自动战斗历史（5 列 + 汇总，复用 `auto_combat.history`） |
| `getEchoEnhanceHistory()` | 声骸强化历史（复用 `tool_history`） |
| `getShutdownTimer()` | 定时关机设置（1~1440 分钟） |
| `getEchoSetList()` | 声骸套装**轻量清单**（37 套，约 5 KB，含 `isConfigurable`） |
| `getEchoSetDetail(setName)` | 单套明细（4C/3C/1C 各档声骸 + 主属性 + 技能） |
| `getNestSweepData()` | 扫荡清单 + 当前勾选 |
| `getCharacterBuildCache()` | 角色练度缓存（**只读**，21 角色 + `base` 账号概览 + 立绘 + 登录卡） |
| `getCharacterBuildDetail(roleId)` | 单角色详情 |
| `getCharacterOptions(kind)` | 配置页弹框的角色下拉（61 个 + **`taken` 占用标记**） |
| `ping()` | 握手 |

### 写

| 方法 | 说明 |
|---|---|
| `setSkin(id)` | 切皮肤（走 `skins.apply_skin`，会存盘 + 广播 `skinChanged`） |
| `setWallpaper(id)` | 切壁纸 |
| `setConfig(payload)` | 新增/修改配置（`loadout` / `echo_profile`） |
| `deleteConfig(kind, id)` | 删配置 |
| `saveFlow(payload)` | 新增/修改任务流程 |
| `setToolSettings(payload)` | 保存工具设置（和 Qt 版同一个 `tool_settings.json`） |
| `setShutdownTimer(payload)` | 定时关机设置（1~1440 分钟，**合并存盘**） |
| `setNestSweepSelection(payload)` | 保存扫荡勾选（**会清洗失效 key 并回报**） |
| `clearGachaHistory()` | 清空抽卡历史（**破坏性** —— 页面必须加确认框） |
| `runTask(toolKey)` | 跑**工具**：走 `FlowRunThread`（见下） |
| `runFlow(flowId)` | 跑**流程**：走 `FlowRunThread`（见下） |
| `runOkwwTask(payload)` | 跑 ok-ww 任务：`auto_combat` / `echo_change` 等 |
| `stopTask()` | 停 `FlowRunThread` 那一路 |
| `stopOkwwTask()` | 停 ok-ww 那一路 |
| `checkLibraryUpdate()` | 检查资源库更新（异步，推 `libraryChecked`） |
| `applyLibraryUpdate()` | 应用更新（异步，推 `libraryApplied`） |
| `analyzeGacha(link)` | 抽卡分析（异步，推 `gachaAnalyzed`） |
| `switchPage(key)` | 记录当前页 |
| `windowAction(action)` | `minimize` / `maximize` / `toggleMaximize` / `close` |

### ★ `runTask` 只覆盖 2/7 个工具（2026-11-02 发现）

```
echo_enhance     覆写 create_task_runner=True   → runTask 可用
nest_sweep       覆写=True                      → runTask 可用
auto_combat      覆写=False  → runOkwwTask（okww_boot.start_task）
echo_change      覆写=False  → runOkwwTask
gacha            覆写=False  → analyzeGacha
character_build  覆写=False  → getCharacterBuildCache（只读）
wuwa_library_update 覆写=False → checkLibraryUpdate / applyLibraryUpdate
```

**所以 Web 面板必须按工具选对应接口**，不能一律用 `runTask`。
对不支持的调用，`runTask` 会返回 `{ok: false, reason: "not_runnable"}`
并提示"请到工具页手动操作" —— 但 **Web 版没有"工具页"**，所以这 5 个
独立入口是必需的。

### ★ `getOkwwState` 的三个字段

`TASKS` 的 key **本身就是中文名**（`"声骸批量调频"`），而页面按
**工具 key**（`echo_change`）组织代码。而且 `auto_combat` 的显示名
（"4C 自动战斗"）和它的 taskKey（"4C 刷声骸"）**并不一样** ——
只给中文名的话页面反查会错。

所以 `tasks` 每条给全：

```jsonc
{"key": "echo_change",        // 工具 key（页面用）
 "name": "声骸批量调频",       // 显示名（不是 taskKey！）
 "taskKey": "声骸批量调频",    // 真正传给 runOkwwTask 的
 "registered": true}
```

`state` 枚举固定 5 个：`idle` / `booting` / `ready` / `running` / `error`。

### ★ `runOkwwTask` 的「受理 ≠ 真的在跑」

`input_permission_error()` 在**游戏没开时返回 `None`**
（它只在能检测到游戏窗口时才判断权限）。于是 `start_task` 放行、
引擎真的 boot 起来 —— 但 `do_start` 找不到游戏窗口就静默失败，
`running_task` 永远不会被设置。

页面看到的是 `ok: true` + `state=ready` + `runningTask` 空 ——
**和"任务刚跑完"一模一样**。

所以 `runOkwwTask` 返回体里多给三个字段（起任务后等 1.2 秒探测）：

```jsonc
{"engineStarted": true, "engineState": "ready",
 "mayNotRun": true,
 "warning": "引擎已就绪，但任务没有进入运行状态 —— 多半是游戏没开着…"}
```

`engineState == "booting"` 时**不报 `mayNotRun`**（首次启动慢是正常的）。

### ★★ P5：对齐旧界面（用户：「请不要擅自修改原先的布局内容」）

2026-11-02 用户反馈 7 条，核心是「新界面把旧界面精心设计的东西弄丢了」。
**这是恢复原样，不是重新设计。**

#### ① `getNav()` 顺序 + 工具分组

顺序**严格对齐** `main_window.py` 的 `addSubInterface`（L298–L346）：

```text
主页 → 配置 → 任务 → 主题皮肤 → 检查更新 → 消息通知 → [工具分组] → 资源库
                                                          ↑ 分组在资源库**之前**
```

⚠ 两处容易错：**配置在任务前**、**工具分组在资源库前**。

分组项带 `kind:"group"` / `group:true` / `selectable:false` / `children`，
对应 qfluentwidgets 的 `addItem(selectable=False)` —— 点它只展开，不切页面。

#### ③ 头像**两级**兜底（用户：「配置页头像全是灰圈」）

旧界面 `pickers.avatar_icon` 是两级的，新界面只做了第一级：

```python
icon = load_icon(relative)
if not icon.isNull():
    return icon
return _initial_icon(name)      # ← 第二级：散列色相圆 + 白色首字
```

所以 `getConfigList()` 每一行都给：

| 字段 | 含义 |
|---|---|
| `avatarUrl` | 第一级；**文件真在才给**（否则空串，页面据此走第二级） |
| `initial` | 第二级全套：`{initial, hue, color, textColor}` |
| `avatarHue` | 色相 0~359 |
| `pinyin` | 搜索索引 `[全拼, 首字母]` |

**色相必须和旧界面逐位一致** —— 照抄 `zlib.crc32(name) % 360`（不是 `hash()`，
后者带随机种子）。有断言 `hue_matches_old_*` 逐个比对。
同一个角色新旧界面**同一个颜色**，截图对照才不会「像换了个角色」。

⚠ `EchoProfile` **没有** avatar 字段（只有 `name`，名字就是角色名）——
按旧界面约定推导 `avatars/<角色名>.png`。

#### ④ 拼音搜索 —— 函数搬到 `core/text_match.py`

`pinyin_keys` / `matches_keyword` 原来在 `gui/pickers.py`，但
`core/web_bridge.py` 也要用 —— **core 不该 import gui**（依赖方向反了）。

搬到 `core/text_match.py`，`pickers.py` 改成 re-export（**老调用方一行没改**）。

拼音依赖 `pypinyin`（Python 包），**JS 侧算不出来**，所以必须后端给
`pinyin: [全拼, 首字母]`。

#### ⑤ 抽卡历史 —— 复用旧模块，不要重写

```python
#: 直接调，别重新实现
from .gacha_store import GachaHistoryStore
from .gacha_history_view import group_by_account_month
```

`group_by_account_month` 里有一堆**用户亲自定的规则**：
「同一账号不同时间，数据一样就用最新时间的，不一样就合并」、
**数字取 max 不是 sum**（累计值相加会变天文数字）……

有断言 `history_matches_old_module` 直接和旧模块的输出对比。

⚠ 读历史用 `load()` **不用** `load_and_repair()` —— 后者会写盘，
而「读历史列表」不该改用户数据（那个 Store 的 `load` 文档里记着
一次「读的时候偷偷写盘」的事故）。

### ⚠ 声骸强化**没有**「选哪条配置」—— 这是刻意设计

2026-11-02 P4 时曾加过 `setEchoEnhanceProfile` / `getEchoEnhanceProfile`
（工具页选「用哪条强化配置」），**P5 已删**（见坑 #15）。

`echo_enhance/tool.py` L531 写着：

```python
#: ⚠ 这里**故意没有**「用哪套配置」的选择器。
#:   —— 用户 2026-09-26 明确："角色声骸强化类型配置与声骸自动强化工具的
#:   配置是无关的"。
```

两套数据是**不同的东西**，不该绑在一起：

* `getToolSettings('echo_enhance').settings` —— 工具自己的判定阈值
  （`crit_min` / `core_stats`，用户在工具页手调的）
* `getConfigList().echoProfiles` —— 配置页的 5 条具名预设（心 / 赞妮 / …）

工具运行时用的是**前者**（`EchoSettings.load()`）。

真要「按配置跑」应该走**任务流程** —— 在编排里显式挂一条 `config` 步骤，
而不是让工具页和配置页共享存储。`runTask('echo_enhance')` 合成的流程
**不插 config 步骤**（有断言 `single_tool_flow_no_config_step` 钉着）。

### ★ `getToolSettings` 的两个要点

**① `settingsKey` 不等于工具 key**

```python
工具 key          = "auto_combat"
存盘键            = "auto_combat_style"   # okww_farm.COMBAT_STYLE_KEY
```

直接拿工具 key 读会读到空，**而且不报错** —— 表现为"用户在旧界面选的
战斗风格，新界面读不到、回落到默认"。映射表在 `_TOOL_SETTINGS_SPEC`。

**② `choices` 从工具模块直读**

声骸调频 12 项目标属性、战斗风格 3 种，都从工具常量读
（`TARGET_STATS` / `rotation.STYLES`）。页面**不要自己抄一份** ——
工具改了会漂移，而校验是 `saved in TARGET_STATS`，抄错一个字就变脏数据。

三元组常量会展开成 `{value, label, desc}`，不把工具私有结构丢给页面。

**③ ~~`prerequisites`~~ —— 已删除**

曾经这里有一张 `_TOOL_PREREQUISITES` 表，给每个工具配「运行前提」文案
（"手动把游戏挪到声骸列表界面" / "需要管理员权限"…）。

**2026-11-02 删掉了** —— 用户发的旧界面截图证明**旧界面根本没有这个区块**，
他们把 web 版那块圈出来写了「干掉」。见坑 #15。

`getToolSettings()` 现在只返回
`{ok, key, settingsKey, settings, defaults, choices}`。


> ⚠ **`runTask` 和 `runFlow` 是分开的**，别混用。
> `runTask` 只认工具 key（`echo_enhance`），传流程 id（`16a74fd2b097`）
> 会明确返回 `{ok: false, reason: "unknown_tool", hint: "..."}` ——
> 这是刻意做的早失败，不然会「拿 flow id 去 `ToolRegistry.make()` 查不到」
> 那种静默失败。

### ★ 真实执行（2026-11-02 接上引擎）

`runTask` / `runFlow` **不再模拟**，走和 Qt 版任务页**同一个执行器**
`FlowRunThread`：

```text
runTask(toolKey) → 合成 [开始, 工具] 流程
runFlow(flowId)  → TaskStore.get(flowId)
        ↓
FlowRunThread.run()
  → _run_start_step()  前置检查 + 准备动作
  → tool.create_task_runner(...).run()
        ↓
信号 → 桥接事件：message→logLine, step_started→progress,
              succeeded/failed→taskFinished, report_ready→RunReportStore
```

**行为一致性**：从主页点「运行」和从任务页跑流程，走的是同一套代码
（权限闸门、准备动作、报告统计全继承），行为不会分叉。

#### 前置检查是**同步**的（返回给 JS）

`runTask` / `runFlow` 在起线程**之前**先跑
`core.task_start.check_start()`。游戏没开时：

```json
{"ok": false, "reason": "precheck",
 "message": "鸣潮客户端没在运行。\n（没找到标题含「鸣潮/…」的窗口…）\n先把游戏打开…"}
```

实测 **8.9 ms 同步返回**，不起线程、不发假事件。
`FlowRunThread` 内部**还会再查一次**作为兜底（幂等，只读进程状态）。

#### 其他拒绝情形

| `reason` | 含义 |
|---|---|
| `unknown_tool` | 工具 key 不存在（或误传了流程 id） |
| `not_runnable` | 工具没实现 `create_task_runner()`（如抽卡/图鉴） |
| `invalid` | 流程 `validate()` 不过（缺名字/缺步骤） |
| `precheck` | 前置检查不过（游戏没开） |
| `busy` | 已有任务在跑 |

#### 写接口的通用规则

- **校验不过不存** —— `saveFlow` 返回 `reason: "invalid"` + `errors: [...]`
- **有任务在跑时禁止写** —— `reason: "busy"`（运行中的流程握着旧配置引用）
- 失败一律带 `message` 字段，**页面直接显示**，不要自己编文案

### 推送（Python → JS）

```js
Bridge.subscribe(function (name, data) { ... });   // 全部事件
Bridge.on('logLine', function (data) { ... });     // 按名字
```

事件：`logLine` / `progress` / `taskStarted` / `taskFinished` /
`skinChanged` / `wallpaperChanged` / `pageRequested`

`taskStarted` 的 payload 带 `kind`（`"tool"` | `"flow"`）和 `name`。

### ★ 调用方式：`call` vs `callWith`

**`QWebChannel` 按 JS 实参个数精确匹配 `@Slot` 签名。个数不对不会报错，
只会静默失败。** 所以两个入口：

```js
// 0 或 1 个参数
await Bridge.call('getTools');
await Bridge.call('runTask', 'echo_enhance');

// 2 个以上参数（必须用这个）
await Bridge.callWith('deleteConfig', ['loadout', 'abc123']);
```

对照表：

| Python 签名 | JS 调法 |
|---|---|
| `@Slot(result=str)` | `Bridge.call('m')` |
| `@Slot(str, result=str)` | `Bridge.call('m', arg)` 或 `callWith('m', [arg])` |
| `@Slot(str, str, result=str)` | **`Bridge.callWith('m', [a, b])`** |

⚠ 参数个数不对时的真实表现（实测）：回调**会被调用**，但给的是
**空数组 `[]`**，不抛异常、不 reject：

```js
Bridge.call('deleteConfig', 'loadout').then(r => console.log(r))  // → []
```

页面侧 `JSON.parse('[]')` → `[]`，于是 `r.ok` 是 `undefined` ——
看起来像"调用成功但没有结果"。建议在公共封装里加一条：

```js
if (Array.isArray(data) && data.length === 0) {
  console.warn('[bridge] 可能是参数个数不匹配:', method);
}
```

---

## ⚠ 踩过的坑（都修了，记下来免得重踩）

### 1. 脚本加载顺序：`app.js` 必须在 `pages/*.js` **之前**

反过来的话页面模块一句 `if (!window.App) return;` **静默退出** ——
表现是「侧栏正常但主页一片空白」，而且**不报错**。

### 2. QWebChannel 的 Slot 签名必须精确匹配 JS 实参个数

`frontendReady()` 无参，却传了一个参数 →
`No candidates found for 'frontendReady' with 1 arguments`，
**静默不执行**。

### 3. `qrc:///qtwebchannel/qwebchannel.js` 三种组合都能加载

实测 `file+file` / `file+http` / `http+http` **视频都能播**。
`setHtml()` 才是 `MEDIA_ERR_SRC_NOT_SUPPORTED`（ERR4）的真正原因，
不是「file vs http」。

### 4. `media_server` 必须 percent-decode URL 路径

`BaseHTTPRequestHandler.path` 是**原始请求行**，不解码 `%E8%8E%89`。
角色头像全是中文名 → 整片破图。

⚠ 顺序是「**先解码、后查 `..`**」——反过来的话 `%2e%2e%2f` 能穿
路径检查。实测两种穿越都返回 403。

### 5. 日志追加不能每行都强制 reflow

```js
// ❌ 每行都读 childElementCount + 写 scrollTop = 每次强制布局
while (box.childElementCount > 500) box.removeChild(box.firstElementChild);
box.scrollTop = box.scrollHeight;
```

一万条日志时页面主线程**彻底卡死**（外层 `runJavaScript` 连回调都拿不到）。
改成局部计数 + `requestAnimationFrame` 批量滚动。

### 6. 首次启动竞态：`start()` 之后要等 HTTP 真的能响应

`serve_forever()` 在别的线程，Chromium 的请求抢先发出没人应答 →
**首次白屏、第二次正常**。

修法：`media_server.wait_until_ready()` 主动探活 + `WebShell`
加载失败重试 2 次。

### 7. `debug_js` 超时默认 15 秒（原 3 秒）

推 10000 条事件后页面要 **5.7 秒**消化；3 秒超时会返回 `None`，
看起来像「页面崩了/丢消息」，实际**一条没丢**（25 秒超时读到 10000）。

### 8. `EchoProfileStore` 曾经**不自动读盘** → 清空了用户 5 条配置

```python
EchoProfileStore.__init__   # 原来只有 self._items = []，不调 load()
LoadoutStore.__init__       # 结尾有 self.load()
TaskStore.__init__          # 结尾有 self.load()
```

**这不是"可能"，是真实发生过**（2026-11-02）：用户的 5 条
「角色声骸强化配置」（绯雪 / 爱弥斯 / 卡提希娅 / 赞妮 / 心，
创建于 9/26–9/30）被整个文件覆盖成 `{"profiles": []}`。

触发路径：

```python
store = EchoProfileStore()   # _items 是空的（没读盘）
store.add(new)               # 往空列表里加 1 条
    → save()                 # 把「只有 1 条」写回文件
                             # → 用户原有 5 条全部消失
# add() 还返回 True，调用方以为成功
```

**由我自己的测试 `web_shell_config_write.py` 触发**（做「新建→验证→删除」
时底座是空的），而且我还在报告里写「测试垃圾已清」——
清掉的不是垃圾，是用户真实数据。从打包备份恢复的。

#### 修了两层

**① 根治** —— `__init__` 补 `self.load()`，和另外两个 Store 一致。

**② 兜底护栏** —— `save()` 拒绝「磁盘有数据、内存为空」的写入：

```python
if not self._items and not self._allow_empty_save:
    # 文件里有 N 条 → 拒绝覆盖，只记 ERROR 日志
```

真要清空调 `store.clear()`（显式放行）。

#### 测试层再加一道

`src/gui/web/dev/backup_guard.py` —— 所有破坏性测试用
`UserDataGuard` 包起来：

```python
guard = UserDataGuard()
guard.start()          # 快照 echo_profiles / loadouts / tasks / ...
try:
    ... 随意增删改 ...
finally:
    guard.restore()    # 原样恢复（含异常路径）
    #: 还要比对 snapshot() 前后一致
```

**两道防线都要有**：根因修了不代表以后不会再有别的路径写坏数据，
而测试**永远**不该成为毁数据的途径。

`web_shell_data_guard.py` 专门验证这两层（含「掏空 `_items` 后强
`save()` 必须被拦住」）。

### 9. 类方法写成模块级调用（`NameError`，编译期抓不到）

`_single_tool_flow` 写成类方法却按 `_single_tool_flow(key)` 调用 →
`runTask` **100% 崩**。`py_compile` 完全抓不到（语法是对的）。

修法有两层：

1. 改成**模块级函数**（没歧义）
2. `web_shell_smoke.py` 做 **AST 扫描**（找「类方法体内裸调用类方法名」）
   + **23 个 `@Slot` 逐个冒烟调用**

这个冒烟测试立刻就又逮到一个：`currentPage()` 返回裸字符串而不是 JSON。

### 10. `Bridge.call` 传不了 2 个参数（多参 Slot 永远调不通）

`QWebChannel` 按**实参个数**匹配 Slot 签名。`deleteConfig` 是
`@Slot(str, str, result=str)`，而第一版 `Bridge.call(method, arg)`
只能传 1 个：

```js
Bridge.call('deleteConfig', 'loadout')   // → []（静默失败，无异常）
```

**不报错、不 reject**，回调给的是空数组 `[]`。

修法：`bridge.js` 加 `Bridge.callWith(method, argsArray)`，
内部 `fn.apply(_bridge, args.concat([cb]))`。
`web_shell_multicall.py` 8 项验证，含一条**反向断言**
（故意用单参调，确认它确实失败 —— 证明测试不是假通过）。

### 11. 游戏窗口必须是 16:9 才跑得动 `echo_enhance`

同事实测报的：

```
RuntimeError: 游戏画面比例是 1800:1055（1.71），不是 16:9（1.78）
```

来自 `tools/game/echo_enhance/prepare.py` 的真实校验。
**这不是 bug** —— 反而证明准备动作真的执行到了。
跑真任务前先把游戏窗口设成 1920x1080 / 2560x1440 等标准 16:9。

### 12. `precheck` 只拦**游戏类**流程（2026-11-02，我和 lead 都判断错过一次）

`core/task_start.py` 的 `check_start()`：

```python
type_key, _ = flow.derived_type()
if type_key != ToolCategory.GAME.key:
    say("任务类型…不需要检查游戏客户端，跳过")
    return          # ← 直接放行
```

**后果**：纯数据流程（`nest_sweep` 的某些用法、资源库更新）**不受前置检查保护**。

这坑的杀伤力在于它制造了**不确定的测试**：

```
runFlow(nest_sweep流程) → 有时 ok=True 真的起线程
                        → 有时 ok=False (precheck)
```

`_running` 被占住的时长取决于线程活多久 —— 后续 `setConfig` 时通时不通。

> **不确定的测试比没有更糟**，它会让人怀疑的是代码还是测试。

**规矩**：测试里只要可能启动执行器，就必须显式 `stop_and_settle()`
等它停干净；不要假设「游戏没开就一定会被拦」。

### 13. 测试对用户数据的处置规则（**两次数据事故的教训**）

2026-11-02 **同一天两次**毁掉用户数据：

| # | 被清空的 | 怎么清的 | 怎么找回的 |
|---|---|---|---|
| 一 | `echo_profiles.json`（5 条配置） | `EchoProfileStore` 不 auto-load，测试的新建→删除把整文件覆盖成空 | 从 `build/stage/` 打包备份 |
| 二 | `gacha_history.json`（549 KB 抽卡历史） | 测试验「传对令牌能清空」**真的清了** | 从 `build/stage/` 打包备份（但只找回 1 条 snapshot，丢失前是 2 条） |

**事故二的根因不是"忘了备份 `gacha_history.json`"，而是
「备份清单靠人工维护」** —— 新加数据文件时很容易漏，漏了不报错，
只在某次测试时静默毁数据。

修法是**结构性的**：`backup_guard._collect_targets()` 扫 `data/*.json`
**全部**，清单只做兜底（5 个 → 23 个文件）。「默认安全」。

#### 分类规则

```
读方法                      → 冒烟调用（安全）
写方法（幂等 / 只动自己建的）  → 冒烟调用 + backup_guard
写方法（可能覆盖用户数据）      → SMOKE_SKIP + 专项测试 + backup_guard
```

#### ★ 破坏性路径最好用**临时文件**测，别动真数据

事故二里的一段可以完全避免：

```python
# 危险：动的是用户真实的 gacha_history.json
store = gacha_store.GachaHistoryStore()

# 安全：用临时文件测同一条代码路径
store = gacha_store.GachaHistoryStore(path=tmpdir / "test.json")
```

`GachaHistoryStore` / `LoadoutStore` / `TaskStore` 都接受 `path=` 参数。
`WebBridge` 也有 `_gacha_store_path` 可覆盖（见 :meth:`WebBridge._gacha_store`）。

#### ★★ 真的启动引擎会让进程退出码变成 0xC0000005

`web_shell_p4_batch1.py` 里原来直接调 `runOkwwTask` → 真的 `boot()` 了
ok-ww 引擎。功能全过，但**退出码是 `-1073741819`（0xC0000005 访问违例）**：

```
28 pass 却 rc=-1073741819
```

根因：`OkwwHost.shutdown()` 只 `set exit_event`，**不 join 引擎线程** ——
解释器关闭时引擎线程还活着，和 Qt 对象析构撞上。

**这是 ok-ww 引擎自身的收尾问题，不该由测试承担**。修法是在测试里
**mock `get_host`**（只验桥接层的转换逻辑，引擎行为不在测试职责内）。

> 判据：**测试的退出码也要检查**。只看 `[PASS]` 计数会漏掉这类
> 「功能对但进程崩了」的情况 —— CI 里就是红色的。

### 14. ★★★ 用户态数据会覆盖代码默认值（2026-11-02，侧栏顺序错了两次）

**源码里的值 ≠ 运行时实际值。**

`data/*.json` 里的用户设置优先于源码常数。典型：

| 数据文件 | 覆盖了什么 |
|---|---|
| `ui_state.json` 的 `nav_order` | 侧栏顺序（用户拖动过） |
| `tool_settings.json` | 各工具上次选的参数 |
| `wallpaper_settings.json` | 壁纸选择 |
| `echo_profiles.json` / `loadouts.json` | 用户配置 |

#### 实例：侧栏顺序错了两次

**第一次** —— 把「工具」平铺在末尾（以为侧栏只有 7 个固定项）。

**第二次** —— 照抄 `main_window.py` 的 `addSubInterface` 调用顺序
（主页→配置→任务→…→工具→资源库）。**那也是错的。**

真实链路：

```text
addSubInterface(...)      ← 只是首次启动的默认值
      ↓ 用户可以按住拖动（只有部分项可拖：
        movable_keys=[CONFIG, TASKS, TOOL_GROUP, LIBRARY]，fixed_keys=[HOME]）
ui_state.json["nav_order"]  ← 拖完存这里
      ↓ 下次启动
nav_reorder.apply_order()   ← 按它重排
```

用户实际的 `nav_order`：

```json
["HomeInterface", "tool_group", "ConfigInterface", "TasksInterface",
 "SkinInterface", "UpdateInterface", "WuwaLibraryInterface"]
```

→ **「工具」被拖到了第 2 位。**

#### `apply_order()` 的真实算法（`nav_reorder.py` L91-98）

```python
ordered = [by_key[k] for k in order if k in by_key]
ordered += [w for w in widgets if w not in ordered]   # ← 没提到的追加到末尾
```

所以 `nav_order` **只有 7 项**（缺 `NoticeInterface`）→
**「消息通知」永远排在最后**。

#### 教训

**布局对齐必须「代码默认值 + 用户数据」两边都看。**
只读源码 = 照抄一个用户根本没在用的默认值。

> page-converter 的原话：
> **源码里的值 ≠ 运行时实际值**
> 因为有 `ui_state.json` / `tool_settings.json` 这些用户态数据会覆盖默认值

**凡是"照抄代码常数"的地方都要检查一遍**有没有被用户数据覆盖。

### 15. ★★★ P4 加错的两样东西（「旧界面没有的」和「被否掉的」都不能加）

**用户要的是「复刻旧界面」，不是「改进旧界面」。**

P4 时 lead 提了两个需求，两个都是错的：

| # | 加的东西 | 为什么错 | 处理 |
|---|---|---|---|
| 1 | `setEchoEnhanceProfile` / `getEchoEnhanceProfile`（工具页选「用哪条强化配置」） | 旧代码注释写着「**故意没有**」，用户 2026-09-26 明确否掉过 | **已删**（238 行） |
| 2 | `getToolSettings().prerequisites`（「运行前提」区块） | **旧界面根本没有这块** | **已删**（4 个符号 + 字段） |

#### 错误 1：被用户否掉的设计又加回来

`echo_enhance/tool.py` L531：

```python
#: ⚠ 这里**故意没有**「用哪套配置」的选择器。
#:   —— 用户 2026-09-26 明确："角色声骸强化类型配置与声骸自动强化工具的
#:   配置是无关的"。
#:   曾经加过一条下拉 + "改动写回当前那套"，属于把两者绑在一起的错误设计，已拆掉。
```

**旧代码里那些「故意没有」「已拆掉」的注释，记录着用户过去明确要求过什么。**

#### 错误 2：旧界面从来没有的功能，也不该加

`prerequisites` 是 lead 在 P4 提的，理由是
「7 个工具的前提文案散在 7 处会漂移，统一放后端更工程化」。

**听起来合理，但用户的 7 张旧界面截图证明：旧界面没有这个区块。**
用户把 web 版那块圈出来写了「干掉」。

#### ★ 通用规则

```text
不要加「被用户否掉过」的东西  → 读旧代码里「故意没有 / 已拆掉」的注释
不要加「旧界面从来没有」的东西 → 对着旧界面截图逐块核对
```

**"更好的设计"在「复刻」这个任务里不是加分项，是减分项。**
用户这轮的原话正是「**请不要擅自修改原先的布局内容**」。

#### 判断流程（改任何 UI 之前）

1. **旧界面有没有这块？** —— 没有 → 不要加，除非用户明确要求
2. **旧代码有没有说「故意没有」？** —— 有 → 一定不要加
3. **旧界面确实有 → 照抄它的布局、字段、存盘形状**

### 16. 无边框窗口（2026-11-02 用户："那个白色的方块区域去掉"）

不设 `FramelessWindowHint` 会出现**两个标题栏**：

```text
┌──────────────────────────────┐
│ 鸣潮工具箱          ─  □  ✕  │  ← Windows 原生（白色）
├──────────────────────────────┤
│ 主页                ─  □  ✕  │  ← 页面自绘 #titlebar（深色）
└──────────────────────────────┘
```

```python
view.setWindowFlags(
    Qt.WindowType.Window                    # ★ 不是 Tool（Tool 不进任务栏）
    | Qt.WindowType.FramelessWindowHint
    | Qt.WindowType.WindowMinMaxButtonsHint)
```

#### ⚠ 判断「有没有变成 Tool」不能用 `flags & Qt.Tool`

`Qt.Tool` 是**枚举值 0xb**，不是位标志 —— 位运算会和其他 flag 撞：

```python
flags & Qt.WindowType.Tool          # 实测是 True，但窗口根本不是 Tool！
view.windowType() == Qt.WindowType.Tool   # ✅ 唯一可靠的判断
```

#### 设了 Frameless 之后失去 3 个原生能力

| 能力 | 补法 |
|---|---|
| 拖拽移动 | 页面 `mousedown` → `startWindowDrag()` → Win32 `ReleaseCapture` + `SendMessage(WM_NCLBUTTONDOWN, HTCAPTION)` |
| 双击最大化 | `windowAction('toggleMaximize')` |
| 边缘缩放 | `WM_NCHITTEST` 返回 `HTLEFT`/`HTTOP`…（见下） |

**拖拽为什么用 Win32 而不是自己算位移**：让系统接管后自带
贴边分屏（Aero Snap），自己算的版本拖快了掉帧、贴边不分屏。

#### ★★ PySide6 的 native event filter 必须继承 `QAbstractNativeEventFilter`

第一版写成 `class _ResizeFilter(QObject)` —— 装不上去：

```text
TypeError: called with wrong argument types:
  installNativeEventFilter(F)
  installNativeEventFilter(filterObj: QAbstractNativeEventFilter, /)
```

**PySide6 要求参数类型就是 `QAbstractNativeEventFilter`**，
光有 `nativeEventFilter` 同名方法不够。（PyQt 接受鸭子类型，别照 PyQt 抄。）

另外 `nativeEventFilter` **每个分支都必须返回二元组** `(bool, int)`。

#### 验证「真的没有原生边框」的硬指标

```python
view.geometry() == view.frameGeometry()   # 有原生标题栏时前者会矮 ~30px
```

比看截图可靠 —— 截图只能说明"看起来没有"，这个能证明**真的没有**。

### 17. ★★★ 设置类 API 必须**回读验证**

**调用成功 ≠ 生效。** 这是本项目最常见、最难查的一类坑 ——
因为 API **不报错**，没有任何可观测的失败信号。

#### 已知的三处（2026-11-02 同一轮里遇到两个）

| # | API | 表面现象 | 真相 |
|---|---|---|---|
| 1 | `DwmSetWindowAttribute(33, ROUND)` | `hr == 0`（S_OK） | 在 `build()` 里设，`show()` 时被 Qt **重置** → 必须放 `show()` 里 |
| 2 | `QWebChannel @Slot(str)` 少传参 | 调用不抛，callback 收到 `[]` | Python 侧报 `No candidates found ... with N arguments`，JS 侧**完全静默** |
| 3 | 窗口 flags 用 `flags & Qt.Tool` | 返回 `True` | `Qt.Tool = 0xb` 是**枚举值不是位标志** → 必须用 `windowType()` |

#### 规则

```text
凡是有"设置/配置"语义的 API：

1. 调用
2. ★ 回读实际值（DwmGetWindowAttribute / getStatus / 读 DOM / windowType）
3. 断言 回读值 == 期望值
```

**只做第 1 步的代码看起来是对的，但可能是空操作。**

#### 具体例子

```python
# ❌ 不够 —— hr=0 只说明"调用被接受"
hr = dwm.DwmSetWindowAttribute(hwnd, 33, byref(corner), sizeof(corner))
return hr == 0

# ✅ 回读确认
hr = dwm.DwmSetWindowAttribute(hwnd, 33, byref(corner), sizeof(corner))
if hr != 0:
    return False
actual = self.get_window_corner_preference()      #: DwmGetWindowAttribute
if actual != 2:                                    #: 期望 ROUND
    logger.warning("设了但回读是 %s", actual)
    return False
```

#### ★ 为什么这条特别重要

这三类坑的**共同点**是：

> API 不报错，但没有可观测的效果。**没有回读就永远发现不了。**

第一条就是靠回读才发现的 —— `hr=0` 看起来完美，
`DwmGetWindowAttribute` 一查是 `0`（DEFAULT）而不是 `2`（ROUND）。

### 18. 系统圆角会**裁掉窗口四角**，标题栏要留安全边距

Win11 `DWMWCP_ROUND` 的圆角由 **DWM 画**，会裁掉窗口内容的四个角。

#### 实测半径 = **8 逻辑像素**

量法（抓**屏幕**不是 `grab()`，因为 grab 不含 DWM 遮罩）：

```python
dpr = app.primaryScreen().devicePixelRatio()      #: 本机 1.25
shot = screen.grabWindow(0, geo.x(), geo.y(), geo.width(), geo.height())
#: 逐行找白色（=窗口内容）的最右像素 → 内缩量 / dpr
```

量出来：`y=1 → 8.0px / y=2 → 4.8px / y=3 → 4.0px / y=4 → 3.2px` —
圆弧形，半径 **8px**。

#### ★★ 只加 `padding-right` 是**不够**的

**圆角是圆不是方角**，判定要用点到圆心距离：

```text
圆心       = (W - R, R)
按钮右上角 = (W - gapRight, gapTop)
安全条件   = hypot(gapRight - R, gapTop - R) >= R
```

实测（R=8）：

| 方案 | gapRight | gapTop | 距圆心 | 结论 |
|---|---|---|---|---|
| 原来 | 6 | 7 | 2.24 | 被裁 |
| **只改右侧** | 12 | 7 | 4.12 | **还是被裁** |
| 右侧 16 | 16 | 7 | 8.06 | ✓ 安全 |

**我第一版就只改了 `padding-right: 12px` —— 数学一算还是不够。**

#### 现在的取值

```css
.titlebar { padding: 0 16px 0 18px; }   /* 右 16px，> R=8 有余量 */

/* 圆角半径随 DPI 放大：100%→8 125%→10 150%→12 200%→16 */
@media (min-resolution: 1.75dppx) { .titlebar { padding-right: 26px; } }
@media (min-resolution: 2.25dppx) { .titlebar { padding-right: 34px; } }
```

#### 其他三个角

| 角 | 状态 | 为什么 |
|---|---|---|
| 左上 | ✓ 安全 | 侧栏品牌区 `padding: 16px 16px 14px`，最靠左上的 `.brand-mark` 在 `(16,21)`，距圆心 14.8 |
| 左下 / 右下 | ✓ 安全 | 页面主体有内边距，卡片不贴边 |
| 右上 | ⚠ **原来被裁** | 关闭按钮 `gapRight=6 < R=8` → 已改 16 |

### 19. ★★★ 写操作要验「**往返一致**」，不能只验「返回 ok」

**这是本轮最严重的一类 bug** —— 用户数据被静默破坏。

#### 已知案例：`setConfig` 写 loadout 丢掉声骸套装

.. code:: text

    getConfigList() 输出（驼峰）           from_dict() 认（下划线）
    ─────────────────────────             ────────────────────────
    "echoSet": "羽落空尘之歌"       ✗     echo_set = data.get("echo_set")
    "updatedAt": "2026-11-02 …"     ✗     updated_at = data.get("updated_at")

**读出的结构原样写回 → 套装变成空串**，而且返回 ``ok: true``：

.. code:: text

    setConfig({"kind":"loadout","id":…,"data":{…"echoSet":"羽落空尘之歌"…}})
    → {"ok": true, "warnings": ["请先选择声骸套装"]}    ← 居然还是 ok!

再读一次 → ``"echoSet": ""``

**用户只要编辑任何一条配置、点保存，套装就没了** —— 而前端当成功处理，
要等下次跑任务才发现。

#### 为什么之前的测试没抓到

之前所有「配置 CRUD 通过」的测试只验了：

* ✅ 写入返回 ``ok``
* ✅ 读出的**条数**对

**没验「读出来的内容 == 写进去的内容」。**

> 这和「测试过 ≠ 校验对」是同一类：测试覆盖了**操作成功**，
> 没覆盖**数据正确**。

#### 规则

.. code:: text

    凡是有写入的接口，都要验：

    读 → 原样写回 → 再读 → 完全一致

⚠ 两条要用**读出的结构直接写回**，**不许做任何字段名转换** ——
否则「字段名对称」这个承诺就是假的。

#### 排查结果（2026-11-02）

| 层 | Store | 对称？ |
|---|---|---|
| **core** | `Loadout` | ✅ `to_dict` / `from_dict` 都是 snake_case |
| **core** | `EchoProfile` | ✅ 对称 |
| **core** | `TaskFlow` | ✅ 对称 |
| **bridge** | `getConfigList` → `setConfig` | ❌ **驼峰 vs 下划线** |

→ **问题只出在桥接层**（它是唯一产出 camelCase 的地方）。
修法是在 ``_save_loadout`` 里做 ``_normalize_loadout_payload()``
（谁弄乱了谁收拾，`core` 不用动）。

#### 配套：半截数据要 `ok: false`

``echo_set`` 为空 + ``picks`` 非空 = 真矛盾（声骸挂在套装下），
必须拒绝并**撤回已写入的那条**。

⚠ 判定条件**不能**是「``echo_set`` 为空就报错」——
``validate()`` 说「各档一个都不选也合法」（用户 2026-09-28），
完全空的配置是允许的。

### 20. 抽卡页的「逐条出金条」配色与评价（**两套阈值，别合并**）

用户 2026-09-30：「**差在逐条抽数条列表**」—— 每个卡池下面的那一串：

```text
[头像] ████████████ 68抽          (歪)
[头像] ██████ 33抽
[头像] ███████████████ 81抽        (歪)
```

#### 条长按 `span`（不是 `cumulative`）

| 字段 | 含义 | 什么时候重置 |
|---|---|---|
| `span` | 距上一个**五星**的抽数（界面「这个金花了几抽」） | 每个五星 |
| `cumulative` | 距上一次 **UP** 的抽数（大保底口径） | 只有出 UP 才重置，歪了继续累加 |

> ⚠ 这两个混用是旧代码踩过的坑 —— 界面会显示「124 抽」这种累计值。

#### 两套阈值（**故意分开**，不要合并）

**① 条的颜色** —— `gacha.SPAN_COLORS`（5 档）

| span | 颜色 | 含义 |
|---|---|---|
| ≤ 40 | `#4aa96c` 绿 | 很欧 |
| ≤ 60 | `#7fae72` 浅绿 | 欧 |
| ≤ 73 | `#c8a86a` 黄 | 正常 |
| ≤ 80 | `#d9705a` 橙红 | 接近/吃到保底 |
| > 80 | `#c0392b` 红 | 超过保底（异常） |

**② 条后的评价文字** —— 旧界面 `_verdict`（3 个区间）

| 条件 | 文字 | 颜色 |
|---|---|---|
| `is_lost`（歪了） | **歪** | `#c0392b` |
| span ≤ 60 | 欧 | `#2e8b57` |
| span ≥ 74 | 非 | `#c0392b` |
| 61 ~ 73 | **不标** | — |

**为什么分开**：条的颜色是连续渐变（5 档更细），
评价是**只在两端标**（正常出货不值得标，标了反而噪音）。

#### 后端已经把展示值算好了

`getGachaPoolDetail()` 每条自带：

```jsonc
{"span": 68, "barColor": "#c8a86a",       // ← 直接用，别再算
 "verdict": "", "verdictColor": ""}       // ← 中间档是空串
```

**前端不用自己实现这两套阈值** —— 抄一遍必然和旧界面对不上。

#### 顺序

**最新的在最上面**（旧界面 `reversed(pool.fives_analysis())`）。
后端已排好，前端直接用。

#### 附：数值显示规则 `_fmt_number`

`src/gui/widgets.py` L389 —— **去掉末尾 0，整数保留一位小数**：

```text
6.90  → 6.9        15.00 → 15.0     0.22 → 0.22
7.50  → 7.5        100.0 → 100.0
```

⚠ 它只是**格式化**，不四舍五入到 decimals 以上
（`_fmt_number(0.015, 2)` → `"0.01"`，第三位被截）。

#### ★ 破坏性接口要**后端**也拦一道

```python
def clearGachaHistory(self, confirm_token: str = "") -> str:
    if confirm_token != "DELETE":
        return {"ok": False, "reason": "needs_confirm", "pending": N}
    # 才真清
```

前端弹窗可以被绕过（脚本出错、控制台直接调、别的前端接这套桥）。
验证方式最硬的是**逐字节比对**文件没被改（`bytes_unchanged_*` 断言）。

#### 具体到本项目的对应关系

| 类别 | 例子 | 冒烟里怎么处理 |
|---|---|---|
| 只读 | `getTools` / `getOkwwState` / `getNestSweepData` / `getCharacterBuildCache` | 直接调 |
| 写但幂等 | `setSkin`（切到当前皮肤）/ `setWallpaper` | 直接调 + `backup_guard` |
| 写**会覆盖用户数据** | `setNestSweepSelection`（覆盖 10 个勾选）/ `setConfig` / `saveFlow` | **`SMOKE_SKIP`** + 专项测试 + `backup_guard` |
| 会打网络 / 拉引擎 | `checkLibraryUpdate` / `runOkwwTask` | **`SMOKE_SKIP`**（冒烟不该打人家服务器、不该拉引擎） |

**三条硬规矩：**

1. **冒烟测试只负责"方法能调通、返回值是合法 JSON"** ——
   不要让它承担功能验证，那需要准备数据、会碰用户数据。
2. **任何写用户数据的测试，必须 `UserDataGuard` 包住并在 `finally` 恢复**，
   还要比对 `snapshot()` 前后条目数（不一致直接 FAIL）。
3. **`SMOKE_SKIP` 的项要在报告里明确列出来**，不是静默跳过 ——
   否则"33 个方法全部无异常"会让人误以为 35 个都测了。

> 上一轮事故的教训不止"要备份"，还有一条：
> **「清理测试数据」这个动作本身就可能删掉真数据。**
> 说"已清理"之前先 `git diff` 或对比备份。

---

## 验证脚本

全在 `src/gui/web/dev/`（**不是产品代码，不影响打包**）：

```powershell
$py = ".venv\Scripts\python.exe"

# ★ 冒烟：AST 查漏 self + **35 个** @Slot 逐个调用 + JSON 契约 —— 5 项
#   加了新的 bridge 方法**必须**先跑这个（新方法没登记会 FAIL）
& $py src\gui\web\dev\web_shell_smoke.py

# ★ 用户数据护栏：验证 Store 不再清空用户配置 —— 6 项
& $py src\gui\web\dev\web_shell_data_guard.py

# ★ P4 托盘 + 关闭确认（关窗口不再直接退出）—— 12 项
& $py src\gui\web\dev\web_shell_tray.py
& $py src\gui\web\dev\web_shell_tray_close.py

# ★ P4 第一批：ok-ww 引擎 + 资源库更新 —— 27 项
& $py src\gui\web\dev\web_shell_p4_batch1.py

# ★ P4 第二批：扫荡清单 + 战斗风格 + 前置条件 —— 34 项（含用户勾选恢复）
& $py src\gui\web\dev\web_shell_p4_batch2.py

# ★ P4 第三批：抽卡分析 + 练度缓存 —— 21 项
& $py src\gui\web\dev\web_shell_p4_batch3.py

# ★ P5：侧栏顺序+分组 / 头像兜底 / 抽卡历史 / 拼音 —— 40 项
& $py src\gui\web\dev\web_shell_p5.py

# ★ P5 第二批：继续 / 跳过 / 强化历史 + 已删接口的回归 —— 23 项
& $py src\gui\web\dev\web_shell_p5_batch2.py

# ★ P6：4C 历史 / 定时关机 / prerequisites 已删 —— 35 项
& $py src\gui\web\dev\web_shell_p6.py

# ★ P7：抽卡总览 6 个数字 + prerequisites 死代码清理 —— 34 项
& $py src\gui\web\dev\web_shell_p7.py

# ★ P8：角色练度 base / 立绘 / 登录卡 —— 31 项
& $py src\gui\web\dev\web_shell_p8.py

# ★ P9：配置页弹框角色下拉 + 后端角色占用校验 —— 25 项
& $py src\gui\web\dev\web_shell_p9.py

# ★ P10：无边框窗口（去掉 Windows 原生白标题栏）—— 36 项
& $py src\gui\web\dev\web_shell_p10.py

# ★ P11：系统圆角下的标题栏安全边距 —— 9 项
& $py src\gui\web\dev\web_shell_p11.py

# ★ P12：声骸套装接口 + 读写往返一致性 —— 37 项
& $py src\gui\web\dev\web_shell_p12.py

# ★ P13：抽卡页逐条出金列表 —— 20 项
& $py src\gui\web\dev\web_shell_p13.py

# ★ 破坏性接口的后端确认防护（clearGachaHistory）—— 34 项
& $py src\gui\web\dev\web_shell_gacha_clear.py

# ★ 数据审计：data/*.json vs 打包备份（随时可跑，查"有没有东西被动过"）
& $py src\gui\web\dev\web_shell_data_audit.py

# ★ 多参调用 callWith（含反向断言：单参调 2 参 Slot 必须失败）—— 8 项
& $py src\gui\web\dev\web_shell_multicall.py

# 核心：无平铺 / 桥接 / 玻璃 / 切页 / 推送  —— 13 项
& $py src\gui\web\dev\web_shell_verify.py

# runTask/runFlow 真引擎 + 前置检查 —— 9 项
& $py src\gui\web\dev\web_shell_real_engine.py

# 写接口 setConfig/deleteConfig/saveFlow —— 22 项（自动清理，不污染数据）
& $py src\gui\web\dev\web_shell_config_write.py

# 写接口语义 + runTask/runFlow 拆分 —— 17 项
& $py src\gui\web\dev\web_shell_write_api.py

# 三个数据接口 + 素材挂载 + 图标真实加载 —— 19 项
& $py src\gui\web\dev\web_shell_bridge_data.py

# main.py 开关两条路 + 优雅回退 —— 4 项
& $py src\gui\web\dev\web_shell_main_switch.py

# 冷启动竞态 / 服务不可用时优雅失败 —— 3 项
& $py src\gui\web\dev\web_shell_coldstart.py

# 压力：800 事件洪泛 + 7 页循环切换 + 干净退出
& $py src\gui\web\dev\web_shell_stress.py

# 性能：推送吞吐 / 往返延迟 / hover 规则
& $py src\gui\web\dev\web_shell_perf.py

# 截图（人工复核）→ data/_shots/
& $py src\gui\web\dev\web_shell_shots.py
```

> ⚠ **加 bridge 方法后一定要跑 `web_shell_smoke.py`。**
> 它会：① AST 扫描漏 `self.`；② 对每个 `@Slot` 用假参数真调一次；
> ③ 验证返回值都是合法 JSON。新方法没在 `SMOKE_ARGS` 登记会直接 FAIL，
> 逼你补一行 —— 这是为了不再重犯「编译过了但运行时 `NameError`」。

> ⚠⚠ **任何会写用户数据的测试，必须用 `backup_guard.UserDataGuard`
> 包起来。** 2026-11-02 我的 `web_shell_config_write.py` 清空了用户
> 5 条真实配置（见坑 #8）。现在它开头快照、`finally` 恢复，
> 还会比对恢复前后条目数是否一致。

### 「无平铺」到底怎么验的

判据是**几何**而不是像素比对 —— 平铺的本质是「viewport 变大了，
但内部盒子还是旧尺寸然后被重复」。

所以走一遍完整尺寸序列（放大 → 更大 → 缩小 → 再放大），每一步断言：

1. `#wallpaper-layer` 的 `getBoundingClientRect()` **严格等于** viewport
2. 视频 `clientWidth` ≈ viewport 宽
3. 内容区宽 == viewport 宽 − 侧栏宽
4. 截图尺寸 ≈ viewport × dpr
5. 截图**不是纯色**（防白屏「凑巧通过」几何断言）
6. 请求放大时 viewport 必须真的变大（防「几次 resize 压成同一尺寸」假通过）

---

## 和旧界面的能力差异（P1 现状）

| 能力 | 旧 Qt 界面 | Web 外壳 |
|---|---|---|
| 主页 7 个工具卡片 | ✅ | ✅ |
| 侧栏导航 + 切页 | ✅ | ✅ |
| 壁纸播放 | ✅ | ✅ |
| 液态玻璃 | ⚠️ CPU 模糊 | ✅ **GPU backdrop-filter** |
| 放大无平铺 | ❌ | ✅ |
| 任务页（流程 / 日志 / 进度） | ✅ | ✅ |
| 配置页 | ✅ | ✅ **可读可写可删** |
| 资源库（61/37/187/123） | ✅ | ✅ |
| 主题皮肤 | ✅ | ✅ 可切 |
| **运行真实任务** | ✅ | ✅ **同一个 `FlowRunThread`** |
| 前置检查（游戏没开就拒绝） | ✅ | ✅ 同步 + 兜底 |
| 启动看门狗 / ok-ww 自启 | ✅ | ✅（`main.py` 里照旧） |
| **工具真实面板**（7 个工具各自的界面） | ✅ | ❌ **占位** |
| 托盘图标 | ✅ | ✅（2026-11-02 补齐） |
| 检查更新 | ✅ | ❌ 占位 |
| 消息通知 | ✅ | ❌ 占位 |

**剩下的缺口只有「7 个工具各自的面板界面」** —— 每个都是几千行 Qt 代码，
要逐个迁到 HTML。任务执行链路、配置读写、皮肤、资源库都已经对齐。

### 能不能设成默认？

**还不行。** 阻碍不是技术，是**功能覆盖**：主页点 7 个工具进去目前是
占位面板（"P1 骨架阶段"），而旧界面那里每个工具都有完整操作界面。

功能迁完之后把 `is_enabled()` 的兜底值从 `False` 改成 `True` 即可
（一个 `return` 的事，开关机制不用动）。

---

## 设计决策记录

### 为什么 `WebShell` 继承 `QObject` 而不是 `QWebEngineView`

窗口对象需要能被主程序持有、有信号、能单独销毁 —— 组合比继承干净。
而且 `QWebEngineView` 的 Python 子类化在退出时容易踩
「C++ 对象已析构」的坑（Qt 的 parent / Python GC 打架）。

### 为什么桥接层要「只序列化，不重写业务逻辑」

`getFlowList` / `getConfigList` / `getLibraryData` 全部直接调
`src/core/` 里现成的 Store / 常量，**不做任何加工**。

理由：Qt 版界面和 Web 版页面拿到的是**同一份数据**，
行为不会分叉。哪天 core 里改了字段，两边一起变。

唯一的"加工"是：文件路径 → HTTP URL、Python 对象 → JSON。

### 为什么所有桥接返回值都是 JSON 字符串

`QWebChannel` 支持的返回类型里 `QVariantMap` 转过去会变成 JS 的
奇怪代理对象，嵌套 dict/list 尤其容易丢类型。统一走 JSON 字符串 +
JS 侧 `JSON.parse` —— 简单、可预测、debug 时打日志直接看得到内容。

### 为什么页面也走 HTTP

`setHtml()` 的同源策略会让 `<video>` 加载 `http://` 源直接失败。
页面和视频**同端口**（同一个 `media_server`）= 同源，最稳。

### 为什么只挂 `assets/game` 的 4 个子目录

```text
avatars      8.9 MB      挂 ✅
echoes      18.8 MB      挂 ✅
echo_sets    0.2 MB      挂 ✅
weapons      6.4 MB      挂 ✅
kuro_icons  48.0 MB      不挂
splash     773.0 MB      绝对不挂
```

白名单常量：`web_shell.GAME_ASSET_SUBDIRS`。
