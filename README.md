# MyTools

一个 Python + Qt 的桌面工具箱骨架。左边侧栏「主页 / 工具」，主页按分类平铺所有工具，
点一下卡片直接跳到那个工具。

界面用 PySide6 + [PySide6-Fluent-Widgets](https://github.com/zhiyiYo/PyQt-Fluent-Widgets)，
工具组织方式参考了 [ok-ww](https://github.com/ok-oldking/ok-wuthering-waves) 的「注册表 + 自动发现」思路：
**加一个工具 = 加一个文件**，不用在任何地方手动登记。

## 跑起来

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt --no-deps
.venv\Scripts\python main.py
```

`--no-deps` 不是可选项：`PySide6-Fluent-Widgets` 的元数据声明依赖**完整版 PySide6（245MB）**，
但它运行时只用到 QtWidgets / QtGui / QtCore / QtSvg / QtNetwork，全在 **PySide6-Essentials（77MB）** 里。
依赖已在 `requirements.txt` 里全部显式列出，跳过解析就不会去拉那个大包。

### PyCharm

用 File → Open 打开项目目录即可。`.idea/runConfigurations/MyTools.xml` 里已经放好
**MyTools** 和 **Smoke Core** 两个运行项；解释器指向 `.venv\Scripts\python.exe`。
如果 PyCharm 没自动认出 `.venv`，手动在 Settings → Python Interpreter 里指过去。

### 离线安装（网络慢的时候）

单连接 pip 在某些网络下只有 18KB/s，装 77MB 要一个小时。`tools/fetch_wheels.py` 用
16 连接分段下载 + 断点续传，实测 **313 KB/s**（快 17 倍），中途断了重跑即可接着下：

```powershell
.venv\Scripts\python tools\fetch_wheels.py          # 下载到 wheels/
.venv\Scripts\python -m pip install --no-index --find-links wheels --no-deps `
    PySide6-Essentials shiboken6 PySideSix-Frameless-Window darkdetect pywin32 PySide6-Fluent-Widgets pypinyin
```

## 配置（角色声骸搭配）

侧栏「配置」页。一条配置 = 一个角色 + 一套声骸套装 + 4C/3C/1C 各一个声骸（各带一条属性）。
**同一个角色可以有多条配置**（比如两套不同思路的搭配）。数据存在 `data/loadouts.json`。

### 数据从哪来

### 数据从哪来

角色名单和套装资料放在 `src/core/data/` 下的三个 JSON 里，都带
`_source` / `_fetched` 字段，注明**整理自哪里、什么时候抓的**：

- `wuwa_characters.json` —— 58 个角色：名字 + 稀有度 / 属性 / 武器
- `wuwa_echo_sets.json` —— 34 套套装：名称 + 2/5 件套效果原文 + **每套有哪些声骸**
- `wuwa_set_versions.json` —— 34 套各自的**出场版本**（如 `3.5`）

**版本表是人工整理的**，因为它没法从 wiki 抓：wiki 那张套装表是按
`sort=名称` 排的，压根没有版本栏。所以照库洛官方各版本「内容说明 / 更新预告」
里的『新增【合鸣套装】』逐条核对，再和巴哈姆特《声骸套装&图鉴》的版本分组交叉验证。
**界面按版本倒序排**（最新的在最前面）—— 资源库列表和配置页下拉都走这个顺序。

更新：跑 `python tools/refresh_wuwa_data.py`（刷效果 / 声骸明细，**不会动版本表**），
或直接改那几个 JSON。

**图标不随代码走**（它们是游戏美术素材）—— 用
`python tools/fetch_wuwa_assets.py` 从公开 wiki 拉到本地：角色头像 58 +
套装图标 34 + 声骸图标 125 = **217 张**。详见下面「资源库」一节。


### 新增 / 修改表单

| 项 | 说明 |
|---|---|
| 角色 * | **点输入框就摊开全部候选**（当前选中的名字不会被清掉），一打字就切回过滤；**中文、全拼、首字母都能搜**（`爱弥斯` / `aimisi` / `ams` 都行，一条都不匹配就收起，不留空框）。也能直接输入任意内容。头像显示在角色下方，跟着角色自动联动 |
| 角色头像 | 头像框**默认空白**，选到角色会自动补上该角色的头像；点「更换」可以挑一张自己的图（之后不再跟角色联动 —— 再换角色会把自定义头像清掉，回归联动） |
| 声骸套装 * | 下拉里带**套装图标 + 名称**，列出**全部 34 套**，顺序为**出场版本倒序**（最新的在最前面）—— 和资源库那份完全一致。明细还没收录的套装也能选，只是对应档位会空着并提示（见下） |
| 4C / 3C / 1C * | 只列该套装对应档位的声骸。一行 = 图标+名称（左）／属性（中，**每行单选**：勾第二个会自动取消第一个）／勾选该声骸（右）。**同一档位可以勾多个声骸**，每个声骸各带一条属性 |

**每档的候选属性 = 该档真实的主词条池**（在 `src/core/game_data.py` 的 `STATS_BY_COST`）：

| 档位 | 主词条池 |
|---|---|
| 4C | 暴击 / 暴击伤害 / 治疗加成 / 攻击百分比 / 防御百分比 / 生命百分比（6 条）|
| 3C | 攻击百分比 / 防御百分比 / 生命百分比 / 共鸣效率 / **六种属性伤害加成**（冷凝·热熔·气动·导电·衍射·湮灭，共 10 条）|
| 1C | 攻击百分比 / 防御百分比 / 生命百分比（**只有百分比，没有固定值**，3 条）|

三档的"固定攻击 / 固定生命"是声骸**自带的固定词条**，不是可刷的主词条，所以都不列。
属性框按**固定 5 列**排布，超出自动换行（3C 10 条会占两行）。

> 老配置里若存着已不在池里的属性（比如 3C 早先那个笼统的「属性伤害加成」），
> 打开「修改」时会**把那条单独列出来并勾上**，而不是默默丢掉 —— 改选具体属性即可。

必填项没填时点「保存」**不会关窗**，会弹提示说明缺什么。套装没选时只提示"请先选择声骸套装"，
不会再刷三条"声骸必填"。

### 列表

每条一行：左边**头像 + 名字（名字在头像下面）**，中间**摘要居中显示、超长自动换行**，
右侧 **查看 / 修改 / 删除**。「查看」是只读详情；「删除」有二次确认。

行高跟着摘要行数走（窗口宽度变了会重算）。实现上要注意：QLabel 自动换行的高度靠
`heightForWidth`，而 Qt 的 `QBoxLayout` **不传播**它 —— 所以摘要的宽度是先算好再定死的，
见 `config_interface.py` 的 `LoadoutRow.set_summary_width()`。

存储格式：每个档位的 `picks` 存的是**列表**（支持多选）；老版本存的单条对象也能正常读出来。


## 资源库

侧栏「资源库」分组，下面挂各个游戏的资料页；目前只有 **鸣潮资源库**，分两块：

- **角色头像**：圆形头像 + 角色名，网格铺开（游戏里的角色头像本身就是圆的，
  所以方形素材会自动裁圆）。
- **声骸套装**：每套一张卡片 —— 套装图标 + 名称 + **套装效果说明** +
  该套装下 4C/3C/1C 各有几个声骸。

### 资料从哪来

页面不写死任何一条资料，全部读 `src/core/data/*.json`。**资料整理自公开 wiki**
（bwiki 鸣潮 Wiki），页面上会写明「抓取于 X（游戏版本 Y）」——
**这是第三方 wiki 的数据，游戏更新后可能过期**。

### 怎么更新

```powershell
.venv\Scripts\python tools\refresh_wuwa_data.py            # 只刷套装效果（快，1 个页面）
.venv\Scripts\python tools\refresh_wuwa_data.py --echoes   # 顺带刷声骸明细（34 个页面）
.venv\Scripts\python tools\refresh_wuwa_data.py --all --write
```

默认只预览，加 `--write` 才写盘。按套装名 merge，不会动其它字段。

> 抓的是第三方页面、不是官方接口，页面改版了正则要跟着改。
> 角色页会被 wiki 限流，所以角色名单只打印出来供人工比对，不自动写盘。

### 图标（游戏素材）

**图标不随代码走** —— 它们是库洛的美术素材，用脚本从公开 wiki 拉到本地：

```powershell
.venv\Scripts\python tools\fetch_wuwa_assets.py                 # 三类都下
.venv\Scripts\python tools\fetch_wuwa_assets.py --list          # 只看有什么，不下载
.venv\Scripts\python tools\fetch_wuwa_assets.py --only avatars  # 只下角色头像
```

| 类别 | 存到哪 | 张数 | 备注 |
|---|---|---|---|
| 角色头像 | `assets/game/avatars/<角色名>.png` | 58 | 方形图会自动裁圆 |
| 套装图标 | `assets/game/echo_sets/<套装名>.png` | 34 | |
| 声骸图标 | `assets/game/echoes/<声骸名>.png` | 125 | |

**换成自己的图**：直接覆盖同名文件，代码不用改。

> **版权**：这些是库洛游戏的美术素材，版权归库洛。脚本只是把公开 wiki 上的图
> 拉到你自己机器上，供本地这个工具显示用 —— **别二次分发**。
> 也正因如此 `assets/game/` 在 `.gitignore` 里。
>
> 不跑这个脚本也没关系：`python tools/make_placeholders.py` 会生成自绘占位图，
> 界面照常能用（就是不好看）。
>
> ⚠ **`make_placeholders.py` 默认只补缺失的图，不会覆盖已有文件**（要重画得加 `--force`）。
> 这是刻意的：它和下载回来的真图标**同目录同名**，无脑重写会把头像全冲成色块
> （2026-09-21 真的踩了两次，第二次把 58 个头像 + 34 个套装图标全盖掉了）。

### 声骸明细（数据来源与已知缺口）

数据来自**声骸自己的 wiki 页面**：每页都写了 `所属套装`（英文逗号分隔）和 `COST花费`。
这个 wiki 开了 SemanticMediaWiki，所以用 `action=ask` **一次就能把 139 条声骸全查下来**，
再反过来拼出「套装 → 声骸」。同一条声骸经常属于多个套装（例如「重工铁蹄」同时属于
逆光跃彩之约 / 雪落无声之愿 / 剪心辑梦之影），所以必须走反向索引，不能只看套装详情页。

> ⚠ 早期版本是抓 `声骸合鸣/<套装名>` 详情页的，**那样会漏**——详情页上是编辑手工挑的一小撮。
> 换成反向索引后补上了 13 套（例如「流金溯真之式」「荣斗铸锋之冠」原来一个声骸都没有）。

**但即便如此，wiki 本身仍有缺口**，这不是程序问题：

| 版本 | 情况 |
|---|---|
| 1.0 / 2.0 | ✅ 完整（编辑填过完整的掉落池）|
| 2.2 ~ 2.8 | ⚠️ 只登记了「该版本新增的专属声骸」，3C/1C 基本为空 |
| 3.0 ~ 3.3 | ⚠️ 4C/3C 有，**1C 为空** |
| 3.4 | 1 件套联动套，只有一个 4C（**本来就该只有一个**）|
| 3.5 | ✅ 完整 |

根因：`所属套装` 这个字段只被认真填过老套装和当版本新增的小怪；
3.0 起新地区的 1C 小怪在 bwiki 上**连词条都还没建**（`噼啪啪`、`颤栗战士` 这些页面不存在）。
公开渠道里也没有更全的：hakush 走不通、encore.moe 的数据靠客户端 JS 拉、
gamekee 那份《声骸产出一览》停在 1.0。

所以：**34 套里 18 套能填完整，16 套缺档**（缺的那一档会明确提示"还没收录"）。
想补齐只有两条路：等 bwiki 更新后重跑 `refresh_wuwa_data.py --echoes`，
或者你知道某套的 1C 是哪些，直接写进 `wuwa_echo_sets.json` 对应那一套的 `echoes` 数组。

**1 件套是例外**：3.4 联动套「碎梦亡鬼之魇」装一个声骸就生效，所以配置页只要求 4C，
不会拿 3C/1C 来卡你（`EchoSetInfo.required_costs` 会按件套数算）。

> 资源库的套装卡片**只显示套装名 + 2/5 件套效果**，不再列声骸条数统计。
> 卡片顺序是**出场版本倒序**（最新的在最前面），和配置页的套装下拉一致。


## 声骸自动强化

**流程整段用 ok-ww 的 [`EnhanceEchoTask`](https://github.com/ok-oldking/ok-wuthering-waves)**，
MyTools 只提供两样东西：界面上的筛选条件，以及"把条件注入任务再启动"的接线
（实现在 `src/tools/game/echo_enhance/okww_task.py`）。

强化动作全在 ok-ww 那边：点「培养」进强化界面 → 「阶段放入」→「强化并调谐」→
关掉「调谐成功 / 不再提示」弹窗 → OCR 读词条 → 判定 → 按 `Z` 弃置或按 `C` 上锁，
直到列表里没有 0 级声骸。

> ⚠ 2026-09-23 改版：原来 MyTools 自己写了一套点击/OCR（`controller.py` / `runner.py` /
> `reader.py`），**在别的机器上完全没用**。而同期的「4C 自动战斗」走 ok-ww 引擎是通的 ——
> 同一件事有两套实现，那就只留跑得通的那套：流程搬 ok-ww 的，判定条件用界面上的。
> 旧的四个模块保留着（还有测试覆盖），但已不是主路径，文件顶部有 LEGACY 标记。

### 前置条件（很关键）

1. 游戏用**窗口模式**（无边框窗口最稳）。独占全屏时截图不可靠。
2. 游戏内「强化设置」里勾上 **阶段放入** 和 **同步调谐**，否则流程会中断并提示你。
3. 自己先走到：**背包(B) → 声骸 → 用过滤器筛出要强化的 → 按等级升序排序**，
   停在这个列表界面上。
4. 按键走 ok-ww 的 **PostMessage 后台消息**（和「4C 自动战斗」同一条通路），
   游戏**不必切到前台**，运行期间可以照常用电脑 —— 但别把游戏窗口关掉或最小化。
5. **本工具要以管理员身份运行**。鸣潮带 ACE 反外挂，游戏跑在 **High 完整性级别**；
   Windows 的 UIPI 会拦掉低权限进程发往高权限窗口的**全部输入**（`PostMessage` 也一样），
   表现是"点了游戏没反应"，而且不报错。打包版已带 `requireAdministrator` 清单
   （双击弹 UAC 就是以管理员启动）；开发态请用管理员的命令行跑。

### 配置项

| 界面 | 说明 |
|---|---|
| 核心属性 | 必须有，缺任意一条就弃置。最多勾 5 条；**暴击/暴击伤害是强制的，勾选后不可取消**。列表**默认收起**（收起时摘要行会显示已选了哪些），点标题右侧的箭头展开 |
| 暴击/爆伤不低于 | 两项下限**排在同一行**，各带 `− 数值 +`（步长 1，也可直接在框里敲数字）。**默认 7.5 / 15.0**。两项都出来后，**任意一项不达标就弃置**（任一项没出时不判，还有孔位可以博）。最右侧的**启用 / 不启用**开关能整体关掉这项检查 —— 关掉时两个数值框会置灰，判定直接跳过（双爆值仍会读出来写进日志） |
| 可选属性 | 列表是去掉双爆之后的属性，勾中的也算有效词条，**勾选数量不限**。同样**默认收起** |
| 有效词条 | 至少要有多少条有效词条（加减按钮就在标题行右侧，2~5） |

> 这些配置**会存盘**（`%LOCALAPPDATA%\MyTools\tool_settings.json`，开发态在 `data/tool_settings.json`），
> 关掉程序再打开还是上次那套。
> **任务流程运行时用的也是这一份** —— 在工具页配好规则，从「任务」页跑流程会按同一套规则判定
> （早先任务流程用的是代码里的默认值，等于"没按你配的筛选"，2026-09-23 已修）。

### 运行时行为（注意，会真的操作游戏）

点「运行」后：**不合格的直接弃置（按 `Z`）**，合格的强化到满级后上锁（按 `C`）。
没有演练开关 —— 运行即弃置。

引擎**只在点「运行」时**才在后台加载 ok-ww（首次会慢一些，要初始化 OCR 模型），
就绪后自动开跑；再点就是直接开始。页面标题旁实时显示状态
（引擎加载中 / 运行中 / 结束，结束时给出「符合条件 N 个、弃置 M 个」）。

> 运行日志按日期落盘：`%LOCALAPPDATA%\MyTools\okww\logs\`
> （每天一个文件，超过 31 天自动清理）。出问题把这个目录里当天的文件发过来即可。

判定逻辑在 `stats.py`（纯逻辑，不依赖 Qt / OCR，`tests/test_echo_stats.py` 覆盖）；
「OCR 读出的词条 → 判定」这层适配在 `okww_task.py`，
由 `tests/test_echo_okww_task.py` 覆盖。

### 判定顺序（每调谐出一批词条就跑一次）

按下面顺序逐条查，任一条命中就**直接弃置**，都不命中才是继续强化 / 上锁：

| 顺序 | 规则 | 触发条件 |
|---|---|---|
| 1 | 核心属性凑不齐 | `缺失的核心条数 > 剩余孔位` —— 剩下几个孔已经不够把缺的核心补出来了 |
| 2 | 双爆不达标 | 暴击、爆伤**都出现后**，任一项低于各自下限（右侧开关可整体关掉） |
| 3 | 有效词条数不够 | `当前有效条数 + 剩余孔位 < 要求的条数` |
| 4 | 上锁 | 上面都通过、且已出满 5 条 → 按 C 保留 |

第 1 条**不是**"缺核心就弃置"。逐级强化时刚进界面一条词条都没出，那时永远是"缺全部核心"，
一刀切弃置会导致一件都强化不了。它的真实语义是 **"剩下几个孔 < 还缺几个核心"才弃置**；
缺核心但孔位还够，就继续调谐去博（这跟"最终不留缺核心的声骸"是等价的，只是弃得更早、更省时间）。

**触发时机跟核心勾了几条直接相关**：默认核心只有双爆 2 条，所以第 1 条规则实际要到
**已出 4 条词条（剩 1 孔）**才会生效；已出 3 条、一条核心都没有时，是第 3 条（有效词条数）先拦下来。
如果核心勾到 4~5 条，这条规则会明显提前触发。

## 4C 自动战斗（ok-ww 引擎宿主）

「4C」= **4-Cost（Boss）声骸**。本工具的战斗本体**整体来自开源项目
[ok-ww](https://github.com/ok-oldking/ok-wuthering-waves)**（AGPL-3.0）：
把它的运行时（ok-script）以无 GUI 方式嵌进 MyTools。页面**只保留「启动 / 停止」**；
**打开本页不加载引擎**，点「启动」才在后台 boot，就绪后自动开
`FarmEchoTask`。**MyTools 不实现任何战斗逻辑**，模板匹配、OCR、
后台按键（PostMessage）全部走 ok-ww 自己的体系，53 份角色脚本原生可用。

| 点「启动」跑的任务 | ok-ww 侧实现 | 说明 |
|---|---|---|
| 4C 刷声骸 | `FarmEchoTask`（🌀 Farm 4C Echo in Dungeon/World） | 打 Boss → 拾取 4C 声骸 → 重开，循环 |

ok-ww 配置里还注册了触发式的 `AutoCombatTask`（进战斗自动输出），
当前页面未暴露入口。

### 使用前提

1. **以管理员运行 MyTools**（本程序清单已要求；ok-ww 对 PC 游戏同样要求管理员）；
2. 鸣潮**窗口模式**（不支持独占全屏），推荐 16:9；
3. 首次启动引擎要加载 OCR 模型，慢一些属正常；
4. 运行日志按日期写在 `%LOCALAPPDATA%\MyTools\okww\logs\`（每天一个文件，
   超 31 天自动清理）；出问题把当天的文件发过来即可；
5. 运行期间不要同时运行 ok-ww 官方程序本体（两套自动化会互相打架）。

### 验证

- `tests/test_okww_vendor.py`：vendor 完整性（模块可导入、无 src 残留、
  配置无 gui/自动更新、任务全部走 okww.*）
- `tests/check_okww_boot.py`：真机冒烟（点启动才 boot → 无游戏时
  优雅失败 → 页面只有 启动/停止 → 日志按日期落盘）

## 开源许可

「4C 自动战斗」内置了 [ok-ww](https://github.com/ok-oldking/ok-wuthering-waves)
的源码与素材（`vendor/okww/`，AGPL-3.0）。**把 MyTools 安装包分发给他人时，
必须按 AGPL-3.0 一并提供对应源码** —— 最简单的做法：发安装包时把整个源码目录
（或对应 commit 的 zip）一起发。详见 `licenses/NOTICES.md`；ok-ww 与 ok-script
的许可全文在 `licenses/` 下。

> ⚠ **克隆本仓库后缺一部分 vendored 素材，属正常**：`vendor/okww/assets/images/`
> （48 张逐帧模板图）与 `vendor/okww/assets/echo_model/echo.onnx`（38MB 的 YOLO
> 声骸模型）是库洛画面衍生物，按本仓库对游戏素材的一贯处理**没有入库**
> （`.gitignore` 里有说明）。要跑 4C / 声骸工具，需要自己从 ok-ww 上游把这两个
> 目录取回来（放到同名路径即可）；只跑资源库 / 配置管理 / 任务流程不受影响。
> 注意 `packaging/check_build.py` 会检查它们，所以**未补齐时打包自检会不通过**。

## 打包成安装包

```
package.bat               # 双击即可。版本号自动取 src/app_config.py 里的 APP_VERSION
                          # （想临时指定别的：package.bat 0.4.0）
```

它做两件事：PyInstaller 出绿色目录 → Inno Setup 出安装包。

**产物**

- `dist\MyTools\` —— 绿色版，整个目录拷到别的机器就能跑；
- `dist\MyToolsSetup-<版本>.exe` —— 安装包，装到 `%LOCALAPPDATA%\Programs\MyTools`
  （安装本身免 UAC），带开始菜单 / 桌面快捷方式和卸载项。

**主程序要求管理员权限**（`packaging/mytools.spec` 里的 `uac_admin=True`）——
这是必须的，不是图省事：鸣潮带 ACE 反外挂，游戏自身以管理员运行，
低权限的 MyTools 连一次点击都发不出去（见上面「前置条件」第 5 条）。
代价是**每次启动都会弹一次 UAC 确认**；如果账号不是管理员，程序会起不来
（那就得用管理员账号，或改回"普通启动 + 界面里一键提权重启"）。
安装包自身仍是按用户安装、不弹 UAC，只有启动程序时才会提权。

**用户数据不在安装目录里**：配置、任务流程、界面状态、探测产物都在
`%LOCALAPPDATA%\MyTools\`（落点由 `src/core/paths.py` 决定），所以装到 `Program Files`
也能正常保存，卸载不会删用户配置，重装 / 升级也不会覆盖。开发态这些路径没变
（仍是项目根下的 `data/`）。

### 打包时的两个坑（都已处理，改配置时别踩回去）

1. **工具是靠 `pkgutil.walk_packages` 扫文件系统发现的**，而打包后代码在压缩归档里、
   磁盘上没有 `.py` —— 不处理会**一个工具都发现不到**：界面显示「工具（暂无）」、
   「已收录 0 个工具」，而且**不报错**。所以 `packaging/mytools.spec` 把
   `src/tools/**/*.py` 既收进归档（`collect_submodules`）**又当数据放一份**到 `_internal/`。
   （`registry.discover()` 里留了一条 warning 当报警器。）
2. **无控制台**（`console=False`）时 `sys.stderr` 是 `None`，日志等于直接丢掉。
   所以打包版会把日志写到 `%LOCALAPPDATA%\MyTools\mytools.log` —— 装机版出问题先看它。

**体积上的两个实测结论**（改依赖前先看这条，省得白折腾）：

- `opencv-python-headless` **并不比完整版小** —— OpenCV 5.x 两者 wheel 解压都是 112MB、
  `cv2.pyd` 都是 82MB（4.x 时代 headless 才明显更小）。试过一轮没收益，已还原。
- 打包后 344MB 里的大头：`cv2` 112MB、`PySide6` 74MB、`onnxruntime` 36MB、
  `assets` 30MB、`numpy`+`numpy.libs` 27MB、`onnxocr` 模型 21MB。

## 目录结构

```
MyTools/
├── main.py                     入口（参数、日志、启动 Qt）
├── requirements.txt
├── package.ps1 / package.bat   一键打包（PyInstaller → Inno Setup 安装包）
├── packaging/mytools.spec      PyInstaller 打包配置（onedir）
├── installer/mytools.iss       Inno Setup 安装脚本
├── docs/阶段性总结.md           阶段进度：已完成 / 待办 / 风险 / 关键技术决策
├── assets/
│   ├── icons/                  工具图标（自定义图标放这里）
│   └── game/                   游戏素材（头像 / 套装 / 声骸图标，脚本下载，不进仓库）
├── data/                       运行时数据（不进仓库）
│   ├── loadouts.json           配置数据（第一次保存时自动建）
│   └── ui_state.json           界面状态（目前只存侧栏顺序）
├── src/
│   ├── app_config.py           常量集中在这里
│   ├── core/                   ★ 不依赖 Qt，可单独测试
│   │   ├── categories.py       工具分类（改这里加分类）
│   │   ├── tool_base.py        BaseTool + ToolMeta
│   │   ├── registry.py         注册表 + pkgutil 自动发现
│   │   ├── game_data.py        数据集加载 + 查询（角色 / 套装 / 声骸）
│   │   ├── data/               ★ 资料数据（JSON，带来源与抓取时间）
│   │   │   ├── wuwa_characters.json   58 个角色：名字 / 稀有度 / 属性 / 武器
│   │   │   ├── wuwa_echo_sets.json    34 套套装：名称 + 效果原文 + 每套的声骸明细
│   │   │   └── wuwa_set_versions.json 34 套的出场版本（人工整理，界面按它倒序排）
│   │   ├── loadout.py          配置模型 + 本地 JSON 存储
│   │   ├── ui_state.py         界面状态持久化（侧栏顺序等）
│   │   └── paths.py            路径解析：只读资源 / 可写用户数据分离（打包用）
│   ├── gui/                    ★ 只依赖 Qt
│   │   ├── compat.py           图标名/控件名的降级兼容层
│   │   ├── nav_reorder.py      侧栏顶级项的自由排序（主页固定）
│   │   ├── widgets.py          工具卡片、分类分组、可折叠卡片
│   │   ├── pickers.py          可输入过滤的下拉 / 带图标的下拉 / 属性单选 / 声骸选择行
│   │   ├── home_interface.py   主页
│   │   ├── config_interface.py 配置页（列表 + 查看/修改/删除）
│   │   ├── library_interface.py 资源库页（角色头像网格 + 声骸套装卡片）
│   │   ├── loadout_dialog.py   新增 / 修改 / 详情弹框
│   │   └── main_window.py      侧栏 + 内容区 + 工具懒加载宿主
│   └── tools/                  ★ 具体工具，加文件就行
│       ├── game/
│       │   ├── echo_enhance/   ★ 声骸自动强化
│       │   │   ├── stats.py        词条定义 + 判定引擎（纯逻辑，可单测）
│       │   │   ├── reader.py       截图 → OCR → 词条（配对属性名与数值）
│       │   │   ├── controller.py   游戏窗口定位 / 截图 / 键鼠（两个游戏工具共用）
│       │   │   ├── runner.py       强化流程状态机
│       │   │   └── tool.py         配置界面 + 运行
│       │   └── auto_combat/    ★ 4C 自动战斗（ok-ww 宿主）
│       │       ├── okww_boot.py     无 GUI 启动 ok-script + 启停任务 + 日志
│       │       └── tool.py          注册入口 + 启动/停止面板
│       └── office/             办公分类（暂时是空的）
├── tests/
│   ├── smoke_core.py           核心层冒烟（不需要 Qt）
│   ├── smoke_gui.py            GUI 冒烟 + 可选截图
│   ├── test_echo_stats.py      判定引擎单测（39 个用例）
│   ├── test_loadout.py         配置模型 + 存储单测（25 个用例）
│   ├── test_ui_state.py        界面状态持久化单测（7 个用例）
│   ├── test_game_data.py       数据集单测（25 个用例）
│   ├── test_okww_vendor.py     vendored ok-ww 完整性 + 宿主配置
│   ├── check_okww_boot.py      4C 页真机冒烟（点启动才 boot）
│   ├── smoke_echo_reader.py    合成图 → OCR → 判定 端到端
│   └── smoke_echo_runner.py    流程状态机（假窗口，不碰真游戏）
└── tools/
    ├── fetch_wheels.py         多连接下载依赖 wheel（网络慢时用）
    ├── refresh_wuwa_data.py    从 bwiki 刷新套装效果 / 声骸明细
    ├── fetch_wuwa_assets.py    从 bwiki 下载游戏素材（头像 / 套装 / 声骸图标）
    ├── make_placeholders.py    生成自绘占位图（不下载素材时的兜底）
    └── make_app_icon.py        生成应用图标 assets/app.ico（安装包 / exe 用）
```

## 界面与图标

- **侧栏**：`主页` + `配置` + `工具` + `资源库`。**「工具」「资源库」都是可展开的分组**，
  展开后列出来的是各自的子项（工具名 / 各游戏的资源页），
  点工具名切到对应面板（框架的层级导航：分组项 `selectable=False`，工具项挂在它的 `parentRouteKey` 下）。
  分组**启动时是收起的**，只有从主页点卡片跳转时才自动展开、并把对应项高亮。
  **`配置` 和 `工具` 可以按住上下拖动换位置，「主页」固定在最上面**（框架不支持，自己实现的）；
  顺序存在 `data/ui_state.json`，下次启动照旧。
  左上角的菜单(☰)按钮已隐藏、折叠功能关闭；鼠标移到侧栏**右边缘**按住左右拖动即可调宽度
  （框架自带导航栏不支持拖拽，那条分隔条是自己加的）。
- **主页**：按分类铺**块状卡片**——上面图标、下面名称。说明文字**不常驻卡片**，
  鼠标悬浮时以小字提示弹出（走 `ToolTipFilter` 把延迟压到 120ms，Qt 默认 700ms 太慢）。
  点卡片会跳到对应工具，并**自动展开侧栏分组、把那一项选中高亮**。
- **工具面板**：懒加载。侧栏项挂的是 `ToolInterfaceHost` 空壳，第一次真正显示时才
  `create_widget()`（见 `main_window.py`），所以工具再多也不拖慢启动。
- **图标**：工具类里设 `icon_path` 指向一张图片即可（见 `EchoEnhanceTool`）。
  默认读 `assets/icons/<key>.png`，放一张 256×256 的 png 覆盖它就能换成自己的图标。

## 加一个新工具（三步）

1. 在 `src/tools/game/` 或 `src/tools/office/` 下新建 `xxx_tool.py`
2. 继承 `BaseTool`，用 `@registry.register` 装饰
3. 想有界面就重写 `create_widget()` 返回自己的 QWidget

```python
from ...core.categories import ToolCategory
from ...core.registry import registry
from ...core.tool_base import BaseTool


@registry.register(
    category=ToolCategory.GAME,
    name="骰子助手",
    description="自定义面数的随机数生成器",
    icon_name="GAME",
)
class DiceTool(BaseTool):
    key = "dice"

    def create_widget(self, parent=None):
        # 不重写的话，默认给一张「功能建设中」占位面板
        return MyOwnWidget(parent)
```

保存后重启程序，主页和侧栏「工具」分组里都会自动出现这个工具。

## 加一个新分类

改 `src/core/categories.py`，加一个 `ToolCategory` 枚举成员即可（含显示名、图标名、排序），
主页自动多出一组卡片。

## 测试

```powershell
.venv\Scripts\python tests\smoke_core.py            # 核心层（注册表/分类）
.venv\Scripts\python tests\smoke_gui.py             # GUI 能不能构造
.venv\Scripts\python tests\test_echo_stats.py       # 判定引擎，39 个用例
.venv\Scripts\python tests\smoke_echo_reader.py     # 合成图 → OCR → 判定
.venv\Scripts\python tests\smoke_echo_runner.py     # 强化流程状态机（假窗口）
.venv\Scripts\python tests\check_settings_gui.py    # 工具页配置存盘/回填 + 资源库页重建（带截图）
.venv\Scripts\python tests\check_frozen_fixes.py    # 打包版：提权清单 + 首启动播种顺序
.venv\Scripts\python tests\check_okww_boot.py       # 4C 自动战斗（点启动才 boot 引擎）
.venv\Scripts\python tests\test_okww_vendor.py      # vendored ok-ww 完整性 + 宿主配置

# 全量单测（252 个）
.venv\Scripts\python -m unittest discover -s tests -p "test_*.py"

# 想要界面截图：
$env:QT_QPA_PLATFORM="windows"; .venv\Scripts\python tests\smoke_gui.py --shot
```

截图模式会短暂显示窗口再抓图，输出到 `tests/_shots/`。

> 三个坑记在这里：
> 1. 默认的 `offscreen` 平台插件在 Windows 上**加载不到任何系统字体**
>    （`QFontDatabase.families()` 返回 0），截图里的中文会变成方框——那是测试环境限制，不是 bug。
>    要正常中文截图就设 `QT_QPA_PLATFORM=windows`。
> 2. Mica/亚克力是 DWM 合成的，Qt 自己 render 抓不到，截图里会变成一片死色；脚本里已临时关掉。
> 3. `QWidget.render()` 在 PySide6 里必须传 `(painter, QPoint(0,0))`。

## 已知情况

- **声骸强化里"真实游戏"这一段没有实机验证过**：判定规则、OCR 解析、流程状态机都有测试兜底，
  但「截图坐标对不对、游戏认不认这些点击」只有接上真游戏才知道。
  先勾上**演练模式**联调（只识别判定、不点游戏），确认没问题再正式跑。
- 相对坐标沿用 ok-ww 的 16:9 基准（`runner.py` 顶部的 `REGION_*` 常量），
  如果你的分辨率/UI 缩放导致对不上，改这几个常量即可。
- 图标名走 `compat.resolve_icon()` 多级降级：Fluent 新版改名了也不会崩，只是形状可能不同。
- 主题走 `Theme.AUTO`（跟随系统）。`main.py` 里改一行就能固定成浅色/深色。

## 踩过的坑（改界面时别重蹈）

这两个都是**深色 Windows 系统 + Fluent 组件**才会暴露的，写在这里省得再调一遍：

1. **别给 Fluent 窗口里的 `QTreeWidget` 套自定义 `setStyleSheet`。**
   自定义 QSS 会接管 item 的绘制流程，和 Fluent 的全局样式表打架，
   现象非常迷惑：数据和选中态都在（选中条能看见），**但一个字都不画**。
   树一律用 `compat.TreeWidget`（内部优先取 `qfluentwidgets.TreeWidget`）。
2. **`QScrollArea` / `QTreeWidget` 这类 Qt 原生容器会吃系统调色板底色。**
   深色系统上它们是黑底，套在浅色 Fluent 窗口里就是一块黑。
   解决：`self.setAttribute(WA_StyledBackground, True)` + `setStyleSheet("#某某 { background: transparent; }")`
   再补一句 `self.viewport().setStyleSheet("background: transparent;")`。
