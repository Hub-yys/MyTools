# Web 界面框架 — 交接文档

> **给下一个会话的人看。** 这份文档记录：做了什么、当前状态、已知问题、
> 踩过的坑、以及下一步该干什么。
>
> 最后更新：2026-11-02 23:45

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
| `run_guarded.py` | — | **外部恢复包装器**（见下） |
| `backup_guard.py` | — | 进程内备份恢复 |
| `web_shell_p4_batch1~3.py` | 27+35+21 | 工具数据接口 |
| `web_shell_p5~p13.py` | 41+23+34+34+30+25+36+9+37 | 各阶段增量 |
| 其他 | — | 托盘 / 冷启动 / 数据审计 等 |

**共 30+ 个套件，680 项断言。**

---

## 四、🔴 已知问题（按严重程度）

### 1. 拖拽可能仍然无效（**最高优先级，未验证**）

用户两轮反馈「不能拖拽」。查了 5 轮，找到并修复了两个根因：

**① `nativeEventFilter` 里两个 Python 错误**（被 `except` 静默吞掉）
```python
message.__int__()   → 'c_void_p' object has no attribute '__int__'
msg.hwnd            → 'MSG' object has no attribute 'hwnd'（应为 hWnd）
```
→ 过滤器每次抛异常、永远返回 `(False, 0)` → 标题栏的 `WM_NCHITTEST` 落到 `0x0000`
→ Windows 丢弃鼠标事件 → 页面收不到 mousedown。
**已修**：现在返回 `(True, 1)` = `HTCLIENT`。

**② `FramelessWindowHint` 清掉了 `WS_THICKFRAME`**
```
GWL_STYLE = 0x-69F50000    WS_THICKFRAME = False
```
窗口管理器认为「没标题栏也不能缩放」→ 拒绝拖动。
**已修**：`show()` 后补回 `WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX`
+ `SetWindowPos(SWP_FRAMECHANGED)`。

**⚠ 但「真实鼠标拖拽」在自动化测试里仍然显示「没动」。**
原因：`mouse_event` / `SendInput` 在无头环境模拟不出「按住拖动」的完整交互。

**下一步**：让用户在真实环境试。如果还不行，可能原因：
- 页面 `mousedown` → `Bridge.call('startWindowDrag')` 这条链路没走通
- 或者系统级拖动被别的因素拦住

**调试方法**（已验证有效）：在页面里埋点
```javascript
window.__d = {md: 0, drag: 0};
document.getElementById('titlebar').addEventListener('mousedown',
    () => window.__d.md++, true);
const oc = Bridge.call;
Bridge.call = function (m) { if (m === 'startWindowDrag') window.__d.drag++; return oc.apply(Bridge, arguments); };
```
然后用 `PostMessage(hwnd, WM_LBUTTONDOWN, ...)` 触发（**注意不能用 SendMessage，
那个绕过消息队列，过滤器拦不到**）。正常应该看到 `md: 1, drag: 1`。

### 2. 窗口放大后不能缩小回来（**未验证**）

用户反馈。实测 `showMaximized()` → `showNormal()` 是正常的。

**需要确认**：是点 □ 最大化后还原不了，还是**拖边缘拉大**后拖不回来？
- 前者：`_on_window_action('restore')` 正常，问题在别处
- 后者：可能是 `WM_NCHITTEST` 的边缘判定 + `WS_THICKFRAME` 的交互

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

### 最优先

**让用户验证拖拽是否修好了。** 这是唯一未验证的关键功能。

如果还没修好，按第四节的调试方法埋点查。

### 其次

1. 「窗口放大后不能缩小回来」—— 先确认具体现象
2. 「角色战斗配置」编辑表单（可选，影响面小）
3. `grabGachaLink()`（可选）

### 长期

- `docs/Web界面-架构与验证.md` 有完整的 20+ 条踩坑记录
- `docs/webshell-manual-verify.md` 是真机验证清单
- 前端代码里有大量 `#: ★ 2026-11-02 ...` 注释，记录了每个决定的来由

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
