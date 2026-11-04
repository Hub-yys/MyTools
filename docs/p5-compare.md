# P5 新旧界面对照（用户反馈 7 条）

> **这份文档是证据，不是总结。** 每条都给出：旧界面的依据（源码行号 / 用户数据文件）、
> 旧截图、新截图、判定。
>
> **为什么需要它**：用户已经两次说「请不要擅自修改原先的布局内容」。
> 不能再靠「我觉得改好了」——要能指着截图说「这里一致」。

---

## ⚠ 先记住这一条：源码默认值 ≠ 用户实际看到的

本轮最大的教训（做 ① 时踩到的）：

```
main_window.py 的 addSubInterface 顺序   ← 只是**首次启动的默认值**
data/ui_state.json 的 nav_order          ← ★ 用户拖过的真实顺序
```

旧界面允许**按住拖动**侧栏项（`src/gui/nav_reorder.py`，182 行），
拖完存进 `ui_state.json`，下次启动按它重排。

同类「用户态数据覆盖默认值」的文件还有：

| 文件 | 覆盖什么 |
|---|---|
| `data/ui_state.json` | 侧栏顺序 |
| `data/tool_settings.json` | 各工具页保存的设置（目标属性 / 数量 / 判定条件） |
| `data/wallpaper_settings.json` | 壁纸外观参数 |
| `data/wallpaper.json` | 当前壁纸 |
| `data/loadouts.json` / `echo_profiles.json` | 配置 |

**所以做布局对齐时必须两边都看**：源码默认值 + 用户数据文件里的实际值。

---

## ① 侧栏顺序与工具分组 ✅

### 旧界面依据

**实测截图**（`p5-old-home.png`，真跑 `MainWindow()` 抓的）：

```
主页
工具        ← ★ 第 2 位
配置
任务
主题皮肤
检查更新
资源库
消息
```

**数据依据** —— `data/ui_state.json`：
```json
"nav_order": [
  "HomeInterface", "tool_group", "ConfigInterface", "TasksInterface",
  "SkinInterface", "UpdateInterface", "WuwaLibraryInterface"
]
```

**为什么不是代码顺序** —— `main_window.py` L298-346 的 `addSubInterface` 顺序是
`主页→配置→任务→皮肤→更新→通知→工具→资源库`，那只是**默认值**；
`nav_reorder.py` 允许拖动，真实顺序存在 `nav_order` 里。

### 旧截图

![旧侧栏](_shots/p5-old-home.png)

侧栏顺序：`主页 / 工具 / 配置 / 任务 / 主题皮肤 / 检查更新 / 资源库 / 消息`

### 新界面

![新侧栏](_shots/p5-new-home.png)

### 判定：✅ 一致

```
主页 → 工具(可展开,7子项) → 配置 → 任务 → 主题皮肤 → 检查更新 → 资源库 → 消息通知
```

**逐项核对**：
| 位置 | 旧 | 新 | |
|---|---|---|---|
| 1 | 主页 | 主页 | ✅ |
| 2 | 工具（分组） | 工具（分组，7 子项） | ✅ |
| 3 | 配置 | 配置 | ✅ |
| 4 | 任务 | 任务 | ✅ |
| 5 | 主题皮肤 | 主题皮肤 | ✅ |
| 6 | 检查更新 | 检查更新 | ✅ |
| 7 | 资源库 | 资源库 | ✅ |
| 8 | 消息 | 消息通知 | ✅（旧界面侧栏显示"消息"，页面标题"消息通知"） |

**分组交互**：旧界面 `selectable=False`（点它只展开/收起，不切页面）——新界面一致。

**回归断言**：`pages_verify.py` 的 **P3b**，逐项比对上面 8 个位置。

### 已知限制

**Web 版不支持拖动侧栏重排**（旧界面支持）。
要改顺序请用旧界面拖一次，Web 版会跟随 `nav_order`。
（用户没提这个需求，不做是刻意的取舍。）

---

## ② 主题皮肤页 ✅

### 旧界面依据

`src/gui/skin_page.py`：

- L465-477：标题 + **两行**说明
  ```
  配色主题：点一下立刻生效，所有选择都会记住。
  壁纸：从本机 Wallpaper Engine 创意工坊读取（视频型可播放，Scene 型需要 WebGL 渲染，暂不支持）。
  ```
- L480-544 注释：用户要求删掉了「角色主题」「配色主题」「当前主题卡」「玻璃滑块」4 块
  ```python
  #: ★★★ 2026-10-31 用户：「删掉配色主题，只留壁纸」
  #: ★★★ 2026-11-01 用户：「把标记的干掉，只把壁纸留着」
  ```
- L536-539：分区标题「Wallpaper Engine 壁纸」（15px 加粗）
- L905-906：说明行带**真实计数**
  ```
  扫到 {N} 个壁纸（可播放 {M} 个视频型；Scene / Web 型需要 WebGL 渲染，暂不支持）。
  ```
- L391：类型标签 `("▶ 视频" if wp_type == "video" else f"{wp_type}")`
- L328 / L399：按钮「使用这个壁纸」/「取消使用」
- `CARD_WIDTH = 268`

**用户问「我怎么自己选择皮肤呢」的答案**：
皮肤（配色）**根本没得选** —— 旧界面就一款液态玻璃，而且选择 UI 是用户自己要求删的。
**能选的是壁纸。**

### 旧截图

![旧皮肤页](_shots/p5-old-skin.png)

### 新界面

![新皮肤页](_shots/p5-new-skin.png)

### 判定：✅ 一致（逐字核对）

| 元素 | 旧 | 新 | |
|---|---|---|---|
| 标题 | 主题皮肤 | 主题皮肤 | ✅ |
| 说明 | 两行（配色主题 / 壁纸） | 两行，**逐字相同** | ✅ |
| 分区标题 | Wallpaper Engine 壁纸 | **逐字相同** | ✅ |
| 说明行 | 扫到 2 个壁纸（可播放 2 个视频型…） | **逐字相同**（含真实计数） | ✅ |
| 卡片宽度 | 268 | 268 | ✅ |
| 缩略图 | 满宽、圆角 8px、无卡片外框 | 一致 | ✅ |
| 类型标签 | ▶ 视频 | ▶ 视频 | ✅ |
| 使用中角标 | 绿色 | 绿色，正好 1 个 | ✅ |
| 按钮 | 取消使用 / 使用这个壁纸（整宽） | 一致 | ✅ |

**⚠ P4 的错误已清除**：那段技术说明
（「切换皮肤需要 `setSkin(id)` 接口…`skins.apply_skin()`…」）**已删除**。
`pages_verify.py` 的 **S5** 断言页面里不能出现 `setSkin` / `apply_skin` / `skinChanged` 字样。

---

## ③ 配置页头像 ✅

### 旧界面依据

`src/gui/pickers.py` L113 `avatar_icon`：
```python
"""角色头像：**文件不在就用名字首字现画一个**
   （用户 2026-09-28："如果角色头像没拿到，先用第一个字填充"）。"""
icon = load_icon(relative)
if not icon.isNull():
    return icon
return _initial_icon(name)   # 圆底 + 首字，色相 = crc32(name) % 360
```

**两级兜底**：① `assets/game/avatars/<角色名>.png` ② 散列色相圆底 + 白色首字。

### 判定：✅ 一致

实测（`pages_verify` + 专项探测）：
```
imgCount: 13    imgLoaded: 13    initialCount: 0    total: 13
```
13 条配置的头像**全部真实加载**（本机 `assets/game/avatars/` 完整，没触发首字兜底）。

首字兜底也接好了（后端给 `initial.color` / `initial.textColor`，和旧界面
`crc32(name) % 360` 的色相**逐位一致**，有断言 `hue_matches_old_心 = 284`）。

---

## ④ 配置页搜索框 + 拼音 ✅

### 旧界面依据

`src/gui/config_interface.py` L231-243：
```python
# ---- 搜索框（用户 2026-09-30："加上搜索，和前面下拉列表搜索一样的"）----
self.search_edit = SearchLineEdit(self.view)
self.search_edit.setPlaceholderText("搜索角色名（支持拼音，如 feixue / fx）")
self.search_edit.setClearButtonEnabled(True)
self.search_edit.setFixedWidth(280)
```

`src/gui/pickers.py` L64-93 `matches_keyword` 的规则：
```
空关键词 → 全命中
中文子串 → 命中
纯字母 → additionally 试拼音（全拼 or 首字母）
```

### 旧截图

![旧配置页](_shots/p5-old-config.png)

### 新界面

![新配置页](_shots/p5-new-config.png)

### 判定：✅ 功能一致，位置一致

| 项 | 旧 | 新 | |
|---|---|---|---|
| 位置 | 列表上方 | 列表上方 | ✅ |
| 宽度 | 固定 280 | 固定 280 | ✅ |
| placeholder | 搜索角色名（支持拼音，如 feixue / fx） | **逐字相同** | ✅ |
| 清除按钮 | `setClearButtonEnabled(True)` | 有 | ✅ |
| 拼音 | feixue / fx | **实测全通** | ✅ |

拼音实测：
```
绯雪    → 2 条      feixue → 2 条      fx  → 2 条
fei     → 2 条      心      → 2 条      xin → 2 条
赞妮    → 2 条      zanni  → 2 条      zzz → 0 条
```

### ⚠ 但有 6 处布局差异 —— **已全部修正**（P5 第二轮）

对照旧截图 `p5-old-config.png`，我最初漏掉了这些，现已按旧界面改好：

| # | 旧界面 | 我最初的实现 | 现状 |
|---|---|---|---|
| a | 标题旁有 **「+ 新增」按钮** | 没有 | ✅ 已加 |
| b | **计数说明行**：「共 5 条角色声骸强化配置 · 0 条角色战斗配置 · 8 条角色声骸筛选配置」 | 没有 | ✅ 已加（逐字一致） |
| c | **按类型分组**（声骸强化 → 战斗配置 → 声骸筛选，空组不画标题） | 页签切换 | ✅ 已改 |
| d | 行按钮：**编辑 / 查看 / 删除** | 查看 / 修改 / 删除 | ✅ 已改 |
| e | 身份列**竖排**（头像在上、名字在下），摘要**居中换行** | 头像+名字横排，摘要左对齐 | ✅ 已改 |
| f | 左列宽 160（旧界面 `ROW_LEFT_WIDTH`） | 118 | ✅ 已改 |

实测证据：
```json
{"registered": true, "title": "配置", "addBtn": "新增",
 "subtitle": "共 5 条角色声骸强化配置 · 0 条角色战斗配置 · 8 条角色声骸筛选配置",
 "sections": ["角色声骸强化", "角色声骸筛选"],
 "rows": 13, "btns": ["编辑","查看","删除"], "imgs": 13}
```

**新增断言钉住结构**：`C3`（分组标题）、`C3c`（+ 新增按钮）、`C3d`（计数行）。

---

## ⑤ 抽卡历史记录 ✅

### 旧界面依据

`src/core/gacha_history_view.py`（151 行）—— 按 **(账号, 年月)** 聚合：
```
同一账号同一个月只留一条（数字取该月最大，时间取最晚一次）
```

`src/tools/game/gacha/tool.py` L432-481 `HistoryCard`：
```python
"""抽卡历史卡片：一个账号的一个月。
   用户 2026-10-28：「以卡片的形式展示，另外我要能够切换」"""
WIDTH = 168
HEIGHT = 92
#:
#:  ┌────────────────┐
#:  │ …856011        │   ← 账号（后 6 位）
#:  │ 2026年10月     │   ← 年月
#:  │ 960 抽 / 21 金 │   ← 数字
#:  └────────────────┘
```
点一下整张卡 = 选中（**黄色边框高亮**）。

### 判定：✅ 一致

| 项 | 旧 | 新 | |
|---|---|---|---|
| 卡片尺寸 | 168×92 | 168×92 | ✅ |
| 三行内容 | 账号后6位 / 年月 / 抽数·金数 | 一致 | ✅ |
| 选中态 | 黄色边框 | 黄色边框 | ✅ |
| 位置 | 链接输入 与 结果 之间 | 一致 | ✅ |
| 聚合 | (账号, 年月) 去重 | 用后端 `getGachaHistory()`（同一份逻辑） | ✅ |

**清空历史双保险**：前端二次确认（点一次变「确认清空？」，3 秒内再点）
+ 后端 `confirm_token: "YES"`。旧界面直接 `store.save(GachaHistory())` 覆盖，**不可逆**。

---

## ⑥ 查询角色练度 ✅

### 旧界面依据

`src/tools/game/character_build/tool.py` L668-686 `_build()`：
```python
root.addWidget(TitleLabel("查询角色练度", view))
root.addWidget(BodyLabel("登录库街区后拉取你账号里的角色与声骸数据，…", view))
root.addWidget(self._build_login_card(view))     # ① 登录
root.addWidget(self._build_overview_card(view))  # ② 概览
root.addWidget(self._build_roles_card(view))     # ③ 共鸣者
root.addWidget(self._build_detail_card(view))    # ④ 详情
root.addWidget(self._build_log_card(view))       # 日志
```

**关键细节**（L792-815 注释）：
```python
#: ★★ 共鸣者列表：**单独一横行，放不下就横向滚动**
#: 用户："一个就展示所有共鸣者，展示不全，可以滑动"
#: ⚠ 之前用 QGridLayout 换行 → 43 个角色铺了 6 行，
#:   把下面的详情区挤到屏幕外。现在改成 QScrollArea(横向) + QHBoxLayout
#:   —— **永远只占一行**。
self._roles_scroll.setFixedHeight(TILE_H + 22)     # 132 + 22 = 154
```

**尺寸常量**：`TILE_W = 96`、`TILE_H = 132`
**筛选**：`FILTER_CHOICES = ("全部", "未达标", "达标", "未练")`
**筛选规则**（L1107-1136）：
```
unleveled = is_unleveled(role, has_data)   # 没声骸数据 或 未满90级

「未练」   → 只留 unleveled
「未达标」 → unleveled 或 没 issues 的都排除
「达标」   → unleveled 或 有 issues 的都排除
```
**排序**（L1095-1101）：`ordered = list(reversed(role_list))` —— 游戏原始顺序反转＝最新获得在前。

### 新界面

![新练度页](_shots/p5-new-build.png)

### 判定：✅ 结构一致

| 项 | 旧 | 新 | |
|---|---|---|---|
| 卡片数 | 5（登录/概览/共鸣者/详情/日志） | **5，顺序一致** | ✅ |
| 标题行 | 标题 + BodyLabel 说明 | 一致 | ✅ |
| ① 登录卡 | 手机号+验证码+登录按钮 | **改成「只读缓存」说明卡** | ⚠ 刻意不同 |
| ② 概览 | UID/等级/角色数 | 一致 | ✅ |
| ③ 共鸣者 | **单行横向滚动** + 搜索200 + 筛选120 | 一致，实测 `scrollW 2136 > clientW 1128` | ✅ |
| ④ 详情 | `EchoDetailView`（1400 行图文） | 数据摘要 + 缺口说明 | ⚠ 刻意不同 |
| ⑤ 日志 | 默认折叠 + 展开按钮 | 一致 | ✅ |

**两处「刻意不同」的原因**（已在页面内明确告知用户）：

1. **① 登录卡** → Web 版不做「手机号 + 短信验证码」多步交互。
   卡片位置和编号保留，内容改成：「这里显示的是上次同步的缓存，最后更新：2026-10-14 21:03:58。
   要刷新请用旧界面启动 `MYTOOLS_WEB_SHELL=0 python main.py`」
2. **④ 详情** → `EchoDetailView` 1400 行（属性雷达 / 武器立绘 / 声骸套装图 / 图标）。
   照抄等于重写一个新项目。页面内明确写：
   「完整图文详情（属性雷达 / 武器立绘 / 声骸套装图 / 技能说明）请在旧界面查看」

---

## ⑦ 声骸自动强化 ✅

### 旧界面依据

`src/tools/game/echo_enhance/tool.py` L487-528 `_build()`：
```python
layout.addWidget(self._build_title_row(view))   # 标题 + 5 个按钮
layout.addWidget(intro)                          # 说明
layout.addWidget(self.editor)                    # 设置编辑器（6 张卡）
layout.addWidget(self._build_report_card(view))  # 结果报告
layout.addWidget(self._build_history_card(view)) # 历史记录
```

**标题行 5 个按钮**（L862-928）：`运行 / 继续 / 停止 / 跳过 / 重置`

**设置编辑器 6 张卡**（`settings_editor.py` L79-84）：
```python
layout.addWidget(self._build_core_card(self))       # 核心属性 13 复选
layout.addWidget(self._build_crit_card(self))       # 暴击/爆伤下限 + 启用开关
layout.addWidget(self._build_maxroll_card(self))    # 满值自动锁定
layout.addWidget(self._build_autostop_card(self))   # 自动停止
layout.addWidget(self._build_optional_card(self))   # 可选属性
layout.addWidget(self._build_valid_card(self))      # 有效词条 至少 N 条
```

**常量**（`settings.py`）：
```python
ALL_STATS = ('暴击','暴击伤害','攻击','攻击百分比','生命','生命百分比',
             '防御','防御百分比','共鸣效率','普攻伤害加成','重击伤害加成',
             '共鸣技能伤害加成','共鸣解放伤害加成')
MAX_CORE_STATS = 5          # 暴击/爆伤占 2，自选最多 3
DEFAULT_CRIT_MIN = 7.5    DEFAULT_CRIT_DMG_MIN = 15.0
MIN_VALID_COUNT = 2   MAX_VALID_COUNT = 5   DEFAULT_VALID_COUNT = 2
```

### ⚠⚠ P4 我犯的实质性错误（已修正）

`tool.py` L530-535 的注释：
```python
#: ⚠ 这里**故意没有**「用哪套配置」的选择器。
#:   「角色声骸强化」那些配置和本页的设置是**两回事**
#:   —— 用户 2026-09-26 明确："角色声骸强化类型配置与声骸自动强化工具的配置是无关的"。
#:   曾经加过一条下拉 + "改动写回当前那套"，属于把两者绑在一起的错误设计，已拆掉。
```

**我 P4 加的那个「使用哪条配置」下拉，正是用户早否掉过的错误设计。已删除。**

### 新界面

![新强化页](_shots/p5-new-enhance.png)

### 判定：✅ 一致

| 项 | 旧 | 新 | |
|---|---|---|---|
| 标题行按钮 | 运行/继续/停止/跳过/重置 | **5 个，顺序一致** | ✅ |
| 说明 | 「在背包 → 声骸界面用过滤器筛好…」 | 逐字照抄 | ✅ |
| 设置卡数 | 6 | **6，顺序一致** | ✅ |
| 核心属性 | 13 复选，4 列，暴击/爆伤强制 | 一致（实测 13 个 checkbox） | ✅ |
| 双爆下限 | 暴击不低于 / 爆伤不低于 + 启用 | 一致（回填 6.9 / 13.8） | ✅ |
| 有效词条 | 至少 N 条（2~5） | 一致（回填 3） | ✅ |
| 结果报告 | 有 | 有 | ✅ |
| 历史记录 | 有 | 有 | ✅ |
| 「使用哪条配置」下拉 | **没有**（刻意） | **没有**（已删） | ✅ |

**实测证据**：
```json
{"titleRow": true,
 "btns": ["运行","继续","停止","跳过","重置"],
 "settingCards": 6, "coreChecks": 13,
 "hasProfileSelect": false,     ← ★ P4 那个错误下拉已不存在
 "report": true, "history": true}
```

### 已知缺口（接口未就绪）

| 按钮 | 接口 | 现状 |
|---|---|---|
| 运行 / 停止 | `runTask` / `stopTask` | ✅ 可用 |
| **继续** | `okwwResumeTask` | ⏳ 缺（点了提示"桥接缺少 okwwResumeTask"） |
| **跳过** | `okwwSkipEcho` | ⏳ 缺 |
| 历史记录 | `getEchoEnhanceHistory` | ⏳ 缺（显示"历史记录接口未就绪"） |

**不静默失败** —— 每个都给了明确提示。

---

## 汇总

| # | 项目 | 判定 |
|---|---|---|
| ① | 侧栏顺序 + 工具分组 | ✅ 一致（**返工过一次**：从代码默认顺序改成 `nav_order`） |
| ② | 主题皮肤页 | ✅ 一致（技术说明已删，逐字核对） |
| ③ | 配置页头像 | ✅ 13/13 真实加载 |
| ④ | 配置页整体（搜索框 + 拼音 + 布局） | ✅ 一致（6 处布局差异已修，见 ④） |
| ⑤ | 抽卡历史 | ✅ 一致 |
| ⑥ | 练度 5 卡布局 | ✅ 结构一致（2 处刻意不同，已告知用户） |
| ⑦ | 强化布局 | ✅ 一致（**P4 的错误下拉已删**） |

### 自动化验证

```
pages_verify.py         50/50   （P3b 侧栏顺序 / C3/C3c/C3d 配置页结构 / S5 无技术说明）
tool_panels_verify.py   63/63
```

---

## 未完成 / 待办

### A. ~~配置页 5 处布局差异~~ —— **已全部修正**（见 ④）

### B. 三个接口未就绪（见 ⑦）

`okwwResumeTask` / `okwwSkipEcho` / `getEchoEnhanceHistory`
（web-shell-dev 已实现，见它最新一轮汇报）

### C. 托盘缺失

WebShell 没有系统托盘（旧界面有关窗口进托盘）。关窗口 = 直接退出。

### D. 刻意不做

| 项 | 原因 |
|---|---|
| 拖动侧栏重排 | 用户没提需求；`nav_order` 已能跟随 |
| 库街区登录（手机号+验证码） | Web 端多步交互体验差；只读缓存 |
| `EchoDetailView` 1400 行图文详情 | 等于重写新项目；旧界面还在 |
| 配置的新增/编辑表单 | 独立工作量；`setConfig` 接口已就绪 |

---

## 截图索引

| 文件 | 内容 |
|---|---|
| `p5-old-home.png` | 旧界面主页（真实运行 `MainWindow()`） |
| `p5-old-config.png` | 旧界面配置页 |
| `p5-old-skin.png` | 旧界面主题皮肤页 |
| `p5-new-home.png` | 新界面主页 |
| `p5-new-config.png` | 新界面配置页 |
| `p5-new-skin.png` | 新界面主题皮肤页 |
| `p5-new-build.png` | 新界面练度页 |
| `p5-new-enhance.png` | 新界面强化页 |
| `p5-new-gacha.png` | 新界面抽卡页 |
