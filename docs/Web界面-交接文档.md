# Web 界面框架 — 交接文档

> **给下一个会话的人看。** 这份文档记录：做了什么、当前状态、已知问题、
> 踩过的坑、以及下一步该干什么。
>
> 最后更新：2026-11-03 02:10

---

## 一、这是什么

MyTools（鸣潮工具箱）原本是 **PySide6 + qfluentwidgets** 的 Qt 桌面应用。

用户要求：**把界面换成和 DSH（Electron 应用）一样的整窗 HTML** —— 壁纸、UI、玻璃效果全在一个
Chromium 页面里，而不是「Qt 控件 + 嵌一个 QWebEngineView 子控件，两套渲染器合成」。

**动机**：Qt 应用里嵌 `QWebEngineView` 会有各种合成问题（窗口放大后壁纸平铺等）。
整窗 HTML 只有**一个渲染器**，和 DSH 架构一致。

---

## 二、当前状态（重要）

### Git 分支

```
main  → 纯旧 Qt 框架（没有 web_bridge / web_shell / gui/web）
dev   → 新 Web 框架（当前分支，所有提交都在这里）
```

⚠ **两边不是同一个代码库的两套文件，而是 dev 包含 main 的全部 + 新增 web 层。**
旧 Qt 界面代码**完整保留在 dev 里**，用环境变量切换。

### 怎么跑

```powershell
cd "D:\AI Work\workbuddy\MyTools"

# 新界面（默认）
python main.py

# 旧界面
$env:MYTOOLS_WEB_SHELL = "0"
python main.py
```

也可以改 `config.json`：`{"UI": {"WebShell": false}}`

### 验证状态

```
编译       148/148
自动化     680 项，0 失败
数据       8 条 loadout / 5 条 profile 完好
```

跑验证：
```powershell
# 全部套件（用 run_guarded 保护用户数据）
.venv\Scripts\python.exe src\gui\web\dev\run_guarded.py src\gui\web\dev\pages_verify.py

# 前端静态检查（符号缺失 / 静默失败 / 调用签名）
.venv\Scripts\python.exe src\gui\web\dev\js_sanity.py
```

---

## 三、代码结构

### Python 侧

| 文件 | 作用 |
|---|---|
| `src/core/web_bridge.py` | QWebChannel 双向桥，60+ 个 `@Slot` 接口 |
| `src/gui/web_shell.py` | 无边框窗口 + 托盘 + 边缘缩放 + 拖拽 |
| `src/core/media_server.py` | 本地 HTTP 服务（页面和视频都走它） |
| `src/core/text_match.py` | 拼音匹配（从 `gui/pickers.py` 提到 core） |
| `src/core/webm_transcode.py` | mp4 → WebM（QtWebEngine 无 H.264） |
| `src/core/color_extract.py` | 从壁纸抽主色 |
| `src/core/wallpaper_engine.py` | 扫 Steam 创意工坊 + 用户自备视频 |

### 前端（`src/gui/web/`）

```
index.html                    骨架（侧栏 / 标题栏 / 内容区）
css/base.css                  变量、重置
css/glass.css                 ★ 液态玻璃配方（照 DSH）
css/layout.css                侧栏 + 标题栏 + 内容区布局
css/pages/pages.css           各页面样式（4300 行）
js/bridge.js                  QWebChannel 封装
js/app.js                     应用逻辑、路由、导航、窗口控制
js/pages/_shared.js           公共工具
js/pages/_panels.js           面板公共组件（卡片、开关、数字输入…）
js/pages/tool-panels.js       7 个工具面板（4100 行）
js/pages/{home,tasks,config,library,skin,simple}.js   五个页面
assets/icons/                 工具图标（从 src/assets/icons 复制）
dev/                          验证脚本（不参与运行）
```

### 验证脚本（`src/gui/web/dev/`）

| 脚本 | 项数 | 作用 |
|---|---|---|
| `web_shell_verify.py` | 13 | P1 骨架：壁纸 / 玻璃 / 无平铺 / 桥接 |
| `pages_verify.py` | 53 | 主页 / 任务 / 配置 / 资源库 / 皮肤 |
| `tool_panels_verify.py` | 67 | 7 个工具面板 |
| `js_sanity.py` | 15 | 静态检查（符号 / 静默失败 / 调用签名） |
| `web_shell_drag_resize_verify.py` | **10** | **★ 真鼠标**验证拖拽 / 缩放 / 放大后缩小 |
| `web_shell_maxicon_verify.py` | **9** | **★ 真鼠标**验证 □ 按钮图标随窗口状态切换 |
| `run_guarded.py` | — | **外部恢复包装器**（见下） |
| `backup_guard.py` | — | 进程内备份恢复 |
| `web_shell_p4_batch1~3.py` | 27+35+21 | 工具数据接口 |
| `web_shell_p5~p13.py` | 41+23+34+34+30+25+36+9+37 | 各阶段增量 |
| 其他 | — | 托盘 / 冷启动 / 数据审计 等 |

**共 30+ 个套件，690 项断言。**

---

## 四、🔴 已知问题（按严重程度）

### 1. ✅ 拖拽 / 缩放 / 放大后不能缩小 —— **已修复（2026-11-03）**

用户三轮反馈：

> 程序启动后，窗口不能拖拽，放大窗口后，还不能缩小

**这次是真的修好了**，而且是**用真鼠标输入（SendInput）验证过的**，
不是靠「代码看起来对」。日志/证据见下。

跑验证：

```powershell
.venv\Scripts\python.exe src\gui\web\dev\web_shell_drag_resize_verify.py
# 结果：10/10 通过
```

#### 根因 ①：``nativeEventFilter`` 拿不到消息地址 → 过滤器等于不存在

PySide6 **6.11.2** 里 ``message`` 是 ``PySide6.QtCore.VoidPtr``，
不是 sip.voidptr，也不是 int。原来的写法：

```python
addr = ctypes.cast(message, ctypes.c_void_p).value   # ← 抛异常
```

实测抛 ``ArgumentError: argument 1: TypeError: wrong type``，
被外层 ``except`` 静默吞掉 → **每条消息都返回 (False, 0)**。

**证据**（探针在真鼠标划一圈时统计）：

```
nativeEventFilter 被调用 36 次
其中成功解析出 message 的次数 = 0
每次都是 ArgumentError: wrong type
```

**修法**：``addr = int(message)``（``VoidPtr`` 实现了 ``__int__``，36/36 成功）。

> 上一版注释里写的「``int(message)`` 会 ValueError」是**错的** ——
> 那是 PySide6 早期版本的行为，6.11 上 ``int()`` 才是唯一可用的写法。

#### 根因 ②：拖动消息号写成 ``0x00A2``（= **UP**）

```python
SendMessageW(hwnd, 0x00A2, ...)   # ← WM_NCLBUTTONUP，"松开"
```

拖动要用 **``0x00A1`` = WM_NCLBUTTONDOWN**。发"松开"却没有"按下"配对，
窗口管理器直接忽略。

实测（真 SendInput，DPR=1.25）：

```
发 0x00A2（旧）→ 窗口 (1250,875) 位置尺寸 完全没变
发 0x00A1（新）→ 窗口 (300,200) 拖到 (444,260) ✅
```

同时还修了两个同源问题：

* ``lParam`` 必须传**真实光标坐标**（旧代码传 0 → 从屏幕左上角起算 → 拖动瞬间乱跳）
* ``SendMessageW`` 必须声明 ``argtypes``，否则 64 位下 ``hwnd`` 被截断成
  32 位，消息发给了随机句柄（**不报错**，窗口就是不动）

#### 根因 ③：命中测试把**物理像素**和**逻辑像素**混着比

``WM_NCHITTEST`` 的 ``lParam`` 是**物理**像素；
``QWidget.frameGeometry()`` 返回**逻辑**像素。125% 缩放下差 1.25 倍：

```
frameGeometry  = (150,140)-(1149,839)   逻辑，1000x700
GetWindowRect  = (188,175)-(1438,1050)  物理，1250x875
```

→ 改用 ``GetWindowRect``（物理），标题栏高度判定也要 × DPR。
不修的话表现是「**有时候能拉、有时候拉不动**」。

#### 根因 ④：``#btn-max`` 发的是 ``maximize`` 不是 ``toggleMaximize``

``app.js`` 里 ``hook('btn-max', 'maximize')`` —— Python 侧 ``maximize`` 是
**单向**的 ``showMaximized()``，窗口已经最大化再调还是最大化。

```
第 1 次点 □ → isMaximized = True   ✅
第 2 次点 □ → isMaximized = True   ❌ 永远回不去
换成 toggleMaximize → False        ✅
```

**这就是用户说的「放大窗口后，还不能缩小」。**
已改成 ``toggleMaximize``（和双击标题栏的行为统一了）。

#### 修复后实测（真实鼠标注入）

```
V1  标题栏拖动              (1250,875,150,120) → (1250,875,282,174)  ✅
V2  最大化后拖标题栏能还原    isMaximized=False                       ✅
V3  拉右边界放大             宽 1250 → 1375                          ✅
V4  拉右边界缩小             宽 1375 → 1250   ← 用户报的核心         ✅
V5  拉下边界放大             高 875 → 1020                           ✅
V6  拉右下角                 1200x800 → 1260x860                     ✅
V7  内容区点击仍到页面        页面 mousedown = 1                      ✅
V8  最大化时边缘 = HTCLIENT   [右/下/左上/右下] 全部 0x1              ✅
V9  □ 第一次点击 → 最大化     isMaximized=True                       ✅
V10 □ 第二次点击 → 还原       isMaximized=False  ← 用户报的核心      ✅
```

#### ⚠ 验证这类问题**必须用真鼠标**

``PostMessage`` / ``SendMessage`` **绕过输入队列**，验证不出这些问题
（返回 0x0000 时页面照样收得到消息，看起来"正常"）。要注入真事件：

```python
# SendInput + SetCursorPos + 中间插 sleep，模拟"按住拖动"
user32.SetCursorPos(x, y); time.sleep(0.25)
_send(0x0002)              # LEFTDOWN
for ...: SetCursorPos(...); time.sleep(0.08)
_send(0x0004)              # LEFTUP
```

完整实现见 ``src/gui/web/dev/web_shell_drag_resize_verify.py``。

#### 根因 ⑤：□ 按钮图标不随最大化状态切换（同日修复）

用户圈图：「放大后，这个缩小框不对把，应该右图那样」——

窗口最大化后，□ 还是**单框**（``E922`` ChromeMaximize），
但这时候点它是「还原」，应该显示**两个叠起来的方框**
（``E923`` ChromeRestore）。

**修法**：

| 位置 | 改了什么 |
|---|---|
| `web_bridge.py` | 新增 `windowStateChanged` 信号 + `pushWindowState()` + `getWindowState()` 槽 |
| `web_shell.py` | `eventFilter` 拦 `QEvent.WindowStateChange` → `_push_window_state()`（去重后推） |
| `app.js` | 新增 `setMaxButtonIcon()` / `bindMaxButtonIcon()`，处理 `windowStateChanged` |
| `index.html` | 初始图标加 `data-state` 标记 |

**为什么必须由 Python 推**：页面判不出来 —— 用户可能双击标题栏、
Aero Snap、Win+↑、任务栏菜单，全都不经过 JS。只有 Qt 的
``WindowStateChange`` 能全覆盖。

**为什么还要 ``getWindowState()``**：``show()`` 里推的那次页面可能还没连上
Bridge（QWebChannel 握手在 ``onload`` 之后），会丢 —— 页面加载完主动问一次。

⚠ **光换图标不够** —— 点它必须真的还原，所以 ``btn-max`` 发的是
``toggleMaximize``（根因 ④），否则图标换了但点了没反应，比原来更困惑。

实测（真鼠标点页面里的按钮）：

```
W1  初始图标 = E922（最大化）      ✅
W2  点 □ 最大化 → E923（还原）     ✅
W3  tooltip / aria-label = 还原    ✅
W4  再点 □ 还原 → E922             ✅
W5  双击标题栏 → 图标也变 E923     ✅
W6  getWindowState() → maximized   ✅
W7  字形渲染宽度 11px（不是豆腐块） ✅
```

跑验证：

```powershell
.venv\Scripts\python.exe src\gui\web\dev\web_shell_maxicon_verify.py
# 结果：9/9 通过
```

### 2. ✅ UI 细节第二批（2026-11-03）—— 6 张圈图，已全部修完

用户一次性圈了 6 张截图。逐条对应：

| # | 用户原话 | 改了什么 |
|---|---|---|
| 1 | 「标记处都干掉」 | 主页删掉 标题栏页面名 / 副标题 / 统计芯片条 / 右上角「换壁纸」「任务中心」按钮 |
| 2 | 「按钮太大了，比文字长度大一点就行」 | 运行·停止按钮从 `flex:1 1 0`（撑满）改成内容宽度 + `padding: 0 28px`，`min-width:88px` |
| 3 | 「这个下拉列表矩形怎么是个直角的，要圆角的」 | `select.input` 用 `appearance: base-select` + `::picker(select)` 圆角弹层 |
| 4 | 「这个卡片怎么没了，而且这个启用要对齐」 | 双爆下限行补玻璃卡底；开关 `margin-left:auto` 右对齐 |
| 5 | 「这里也是」 | 有效词条行同样补玻璃卡底 |
| 6 | 「另外文字说明也去掉，再检查其他地方有没有类似情况」 | 删掉 调频数量说明段 / 强化页整段 intro / 「未启用…」提示；全站扫了一遍 |

#### 关键踩坑记录

**① `appearance: base-select` 才是下拉圆角的唯一解法**

原生 `<select>` 的弹层由**操作系统**画（Windows 上是 Win32 菜单），
CSS 完全够不到 —— `option { border-radius }` 算得出值但**画的时候被忽略**。

Chromium 135+ 的 `appearance: base-select` 把 select 降级成页面内元素，
弹层变成 `::picker(select)` 伪元素，圆角/阴影/hover 才能生效。
本机 QtWebEngine 6.11.2 = **Chromium 140**，实测支持。

⚠ 三个必须一起处理的副作用（实测踩到）：

```
① 双箭头 —— base-select 自带 ::picker-icon，和我们 background-image 画的重复
② 多一个 ✓ —— 选中项前面有 ::checkmark，旧界面观感里没有
③ option 变 display:flex —— padding 才生效，不写会贴边
```

**② `setStateLabel` 用 `.hidden` 类，不是 `hidden` 属性**

HTML 的 `hidden` 属性只是 `display:none` 的**弱默认值**，
页面里任何 `.cfg-muted { display: flex }` 都能盖掉它。
实测：给 `.cfg-muted` 设 `el.hidden = true` 之后**照样显示**。
本项目统一用 `.hidden` 类（`base.css` 里是 `display:none !important`）。

**③ 「说明文字」和「状态反馈」必须分开对待**

用户要求删说明文字，但状态行里混着两种东西：

```
静态说明（删）    「引擎：就绪 · 点「启动」开始 4C 刷声骸」
动态反馈（留）    「引擎：启动失败 —— …」「引擎：正在启动…」
```

判据：**状态会自己变回去的 = 反馈（留）；一直挂着不动的 = 说明（删）**。

⚠ 一开始把「正在启动…」也删了 —— 结果是**引擎冷启动 20 秒里点完毫无反应**，
用户会以为按钮坏了反复点。已改回保留。

**④ 反馈要写在第一个 `await` 之前**

`sweepAction` 原来先 `await sweepSaveSelection()` 再写状态行。
QWebChannel 调用是排队异步的，前一个面板还在等 `runOkwwTask` 时这里会卡住
→ 点完几秒毫无反应（`tool_panels_verify` 的 nest_sweep.P5 因此一直假失败）。

**⑤ `pendingUntil` 有效期取 120 秒（不是 30）**

引擎冷启动期间 `getOkwwState()` 还报 `state:"idle"`，轮询会把
「正在启动…」擦掉。加了 `pendingUntil` 截止时间，值对齐 ok-ww 自己的
`start_timeout: 120`。30 秒实测不够。

### 3. 「角色战斗配置」编辑表单未做
配置页「新增」→ 选「角色战斗配置」会显示「下一轮做」的提示（不静默失败）。

**影响面小**：用户 0 条战斗配置。要建得用旧界面。

### 4. `grabGachaLink()` 未做

抽卡页「获取抽卡记录」按钮会提示「接口未就绪，请手动粘贴」。

旧界面能自动从本机游戏日志读链接（`GrabLinkThread`，可能全盘扫、几十秒）。

---

## 五、踩过的坑（按类型，共 20+ 条）

完整版在 `docs/Web界面-架构与验证.md`。这里列最要紧的：

### A. 静默失败（5 种形态，最容易浪费时间）

| # | 形态 | 表现 |
|---|---|---|
| ① | async 弹框抛异常 | 不进 `window.onerror`，控制台安静，页面「没反应」 |
| ② | 提示容器失效 | `if (!host) return` 静默吞掉 |
| ③ | STATE 字段恒 null | `XXX_STATE.field` 被引用但从未赋值，分支永不执行 |
| ④ | `@Slot` 少传参 | QWebChannel 静默返回 `[]` |
| ⑤ | 接口不存在 | 返回 `{ok: true, data: {}}`，**看起来像成功** |

**共同点：失败时用户看不到任何东西。**

**对策**：
- `js_sanity.py` 能机器检查 ①②③⑤
- `@Slot(str)` 有默认值 ≠ JS 可以不传（`player_id=""` 只在 Python 侧生效）

### B. 设置类 API「看起来成功但没生效」

| 场景 | 教训 |
|---|---|
| `DwmSetWindowAttribute` | `hr=0` 只说明调用被接受；必须在 `show()` 之后调，**并回读验证** |
| QWebChannel 调用 | 少传参静默返回 `[]`，要回读 |
| `flags & Qt.Tool` | `Qt.Tool = 0xb` 是枚举值不是位标志，位运算会误报；用 `windowType()` |

**规则：调用 → 回读实际值 → 断言回读值 == 期望值。**

### C. 写操作要验「往返一致」

`getConfigList()` 输出驼峰 `echoSet`，`Loadout.from_dict` 只认下划线 `echo_set`
→ **读出来原样写回，套装被静默清空，还返回 `ok: true`。**

**用户编辑任何一条配置就会丢数据。**

**已修**：桥接层加 `_normalize_loadout_payload` 做别名映射。

**为什么之前的测试没抓到**：所有测试只验「返回 ok」和「条数」，唯一验持久化的只看了
`character` 一个字段 —— 恰好是唯一没问题的那个。

**规则**：读 → 原样写回（**不做任何字段名转换**）→ 再读 → 完全一致。

### D. 用户态数据会覆盖代码默认值

侧栏顺序不在 `main_window.py` 的 `addSubInterface` 里，在
`data/ui_state.json` 的 `nav_order`（**用户拖动过**）。

而且 `nav_order` 只有 7 项 —— 它是「**可拖动项**的顺序」，不是完整顺序。
正确算法见 `src/gui/nav_reorder.py` 的 `apply_order()`。

### E. 不要加「旧界面从来没有的」和「被用户否掉过的」

- `prerequisites`（运行前提卡）—— 旧界面根本没这块，用户圈出「干掉」
- `setEchoEnhanceProfile`（配置选择器）—— 旧代码注释写着「**故意没有**，用户 2026-09-26
  说两者无关，曾经加过已拆掉」

**旧代码里的注释记录着用户过去明确要求过什么。加功能前先读。**

### F. 测试会毁用户数据（三次事故）

- `echo_profiles.json` 被清空（5 条配置）
- `gacha_history.json` 被清空（536KB）
- `loadouts.json` 写坏一条

**根因都是「备份清单靠人工维护」**，漏一个文件就是一次数据丢失。

**现在的机制**：
```powershell
# 所有会写 data/*.json 的测试都用这个包装
.venv\Scripts\python.exe src\gui\web\dev\run_guarded.py <测试脚本>
```
父进程备份 → 跑子进程 → **必定恢复** + 条目数自检。
不维护白名单，直接扫 `data/*.json`。

⚠ **`os._exit()` 会跳过所有 `finally`** —— 测试脚本别用它。

---

## 六、页面实现约定（照着做，别重新设计）

### 侧栏

```
主页 → 工具(可展开分组) → 配置 → 任务 → 主题皮肤 → 检查更新 → 资源库 → 消息通知
```
顺序来自 `ui_state.json` 的 `nav_order`，不是代码默认顺序。

### 7 个工具面板的结构（和旧界面一致）

| 工具 | 结构 |
|---|---|
| 4C 自动战斗 | 5 张卡：运行 / 战斗方式 / 定时关机 / 战斗报告 / 历史记录 |
| 声骸批量调频 | **1 张卡**，所有内容都在里面 |
| 扫荡残像聚落 | 2 张卡：运行 / 残像聚落（3 列网格） |
| 声骸自动强化 | 标题行(5按钮) + 2 张折叠卡 + 2 张普通卡 + 2 个裸行 + 报告 + 历史 |
| 抽卡记录分析 | 12 块（标题/说明/怎么获取/链接行/状态/欧皇卡/总结/头像墙/分卡池/页签/详情/历史） |
| 查询角色练度 | 5 张卡（①登录 ②概览 ③共鸣者 ④详情 日志） |
| 资源库更新 | 标题 + 说明 + 1 张状态卡 |

**⚠ 用户明确要求过「这些说明都要删掉」** —— 7 个工具页的说明文字已全删，
只剩卡片标题、摘要行、下拉选项描述、错误提示。

### 玻璃配方（照 DSH）

```css
background-image: linear-gradient(180deg,
  rgba(255,255,255,0.10), rgba(255,255,255,0.02));
background-color: rgba(13,21,36,0.59);
backdrop-filter: blur(16px) saturate(1.8);
box-shadow:
  inset 0  1px 0 rgba(255,255,255,0.32),
  inset 0 -1px 0 rgba(255,255,255,0.08),
  inset 0 0 0 0.5px rgba(255,255,255,0.08),
  0 12px 40px rgba(0,0,0,0.12);
```

侧栏：`rgba(10, 9, 19, 0.92)`

### 尺寸常数（照旧界面，别自己定）

```
卡片宽 158  高 128  图标 46  间距 12       ← app_config.py
数字输入 [−30px][76px 居中][+30px] 间距 6px
开关 40×22  滑块 16×16  位移 20px
标题栏高 44px  右内边距 16px（避系统圆角）
窗口圆角半径 8px（Win11 系统值）
```

---

## 七、工具链

### 写代码时

```powershell
# 改完前端先跑静态检查
.venv\Scripts\python.exe src\gui\web\dev\js_sanity.py

# 再跑对应页面的验证
.venv\Scripts\python.exe src\gui\web\dev\tool_panels_verify.py --only echo_enhance
```

### 改完提交前

```powershell
# 全量编译
.venv\Scripts\python.exe -c "
import py_compile, tempfile, os, sys, glob
bad = 0; n = 0
for f in set(glob.glob('src/**/*.py', recursive=True) + ['main.py']):
    n += 1
    try: py_compile.compile(f, cfile=os.path.join(tempfile.gettempdir(), 'c.pyc'), doraise=True)
    except Exception: bad += 1
print('%d/%d' % (n - bad, n))
"
```

### 数据安全

```powershell
# 任何会写 data/*.json 的测试，用这个包装
.venv\Scripts\python.exe src\gui\web\dev\run_guarded.py <测试脚本>

# 不确定数据有没有被改坏
.venv\Scripts\python.exe src\gui\web\dev\web_shell_data_audit.py
```

---

## 八、用户偏好（很重要的上下文）

1. **不要擅自改布局** —— 用户说过三次「请不要擅自修改原先的布局内容」
   「按照以前那个布局做」「再对着旧界面的代码复刻」
   → **新框架的定位是「用 HTML 重新实现旧界面」，不是「重新设计界面」**

2. **改动前先看旧界面** —— 读旧代码不够，要真的跑旧界面看截图
   （`MYTOOLS_WEB_SHELL=0 python main.py`）

3. **说明文字要少** —— 用户要求删掉所有工具页的说明

4. **不要分工** —— 用户明确说「切换到标准模式，不要分工了，速度太慢了」

5. **用中文回复**

---

## 九、下一步建议

### ✅ 已完成（2026-11-03）

**① 拖拽 / 缩放 / 放大后不能缩小 —— 已修复并验证（10/10）。**
**② □ 按钮图标不随最大化切换 —— 已修复并验证（9/9）。**
**③ UI 细节第二批（6 张圈图） —— 已全部修完。**

详见第四节第 1、2 条。

改动文件：

| 文件 | 改了什么 |
|---|---|
| `src/gui/web_shell.py` | `int(message)` 解析、`0x00A1` 拖动、`GetWindowRect` 物理坐标、标题栏判定 ×DPR、`WindowStateChange` → 推窗口状态 |
| `src/core/web_bridge.py` | 新增 `windowStateChanged` 信号 / `pushWindowState()` / `getWindowState()` |
| `src/gui/web/js/app.js` | `btn-max` 的 `maximize` → `toggleMaximize`；`setMaxButtonIcon()` 换图标 |
| `src/gui/web/index.html` | □ 按钮加 `data-state`；去掉标题栏页面名 |
| `src/gui/web/js/pages/home.js` | 删副标题 / 统计芯片条 / 换壁纸 / 任务中心 |
| `src/gui/web/js/pages/_panels.js` | 新增 `setStateLabel()`（用 `.hidden` 类） |
| `src/gui/web/js/pages/tool-panels.js` | 按钮尺寸、下拉圆角配套、6 张卡的玻璃底、删说明文字、`pendingUntil` 冷启动反馈 |
| `src/gui/web/css/pages/pages.css` | `.cfg-btn` 不自撑满、`select.input` base-select 圆角、`.enh-crit-card` |
| `src/gui/web/dev/web_shell_drag_resize_verify.py` | **新增**：真鼠标验证套件（10 项） |
| `src/gui/web/dev/web_shell_maxicon_verify.py` | **新增**：□ 图标验证套件（9 项） |

### 验证结果（2026-11-03 02:10 终跑）

```
web_shell_drag_resize_verify.py   10/10   ✅
web_shell_maxicon_verify.py        9/9    ✅
tool_panels_verify.py             67/67   ✅
pages_verify.py                   55/55   ✅
web_shell_verify.py               13/13   ✅
web_shell_p10.py                  全部通过 ✅
js_sanity.py                      15/15   ✅
全量编译                          150/150 ✅
```

⚠ 三个测试脚本本身也改了（它们原来断言的是**被删掉的 UI**）：
`pages_verify` 的 H6 从「统计条 >= 2 个」反转成「必须是 0 个」；
`tool_panels_verify` 的 P5 增加「反应历史」采样（引擎冷启动会阻塞主线程，
单点快照读不到反馈）。

### 其次

1. 「角色战斗配置」编辑表单（可选，影响面小）
2. `grabGachaLink()`（可选）

### 长期

- `docs/Web界面-架构与验证.md` 有完整的 20+ 条踩坑记录
- `docs/webshell-manual-verify.md` 是真机验证清单
- 前端代码里有大量 `#: ★ 2026-11-02 ...` 注释，记录了每个决定的来由

### ⚠ 排查这类「Windows 原生交互」问题的经验

1. **别信「代码看起来对」** —— 要用真 ``SendInput`` 验证
2. **别信 ``SendMessage``/``PostMessage`` 的测试结果** —— 它们绕过输入队列，
   和真实鼠标走的不是同一条路（本次 3 个 bug 全靠真输入才暴露）
3. **``except: return 默认值`` 是排查地狱** —— 至少要打一条 ``logger.debug``
4. **64 位下所有 Win32 调用都要声明 ``argtypes``**，否则句柄被截断成 32 位，
   **不报错**，就是静默不生效
5. **物理像素 vs 逻辑像素** —— ``WM_*`` 的 ``lParam`` 是物理，
   Qt 的 ``geometry()`` 是逻辑，混用只在缩放不是 100% 时出问题
   （用户机器正好 125%，所以必现）
6. **无边框窗口的 UI 状态要由 Python 推给页面** ——
   双击标题栏 / Aero Snap / Win+↑ 都不经过 JS，页面自己判不出来。
   监听 ``QEvent.WindowStateChange``，别指望 ``outerHeight`` 之类的哈希。

---

## 十、清理清单

切换会话前该删的临时文件：

```powershell
cd "D:\AI Work\workbuddy"
Remove-Item "_fix","_dt","_rz","_cw","_p1" -Recurse -Force -EA SilentlyContinue
Remove-Item "$env:TEMP\*.txt","$env:TEMP\*.png" -EA SilentlyContinue
cd MyTools
Get-ChildItem -Filter "__pycache__" -Recurse -Directory | Remove-Item -Recurse -Force
```
