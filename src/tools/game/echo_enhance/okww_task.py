# -*- coding: utf-8 -*-
"""声骸自动强化 = **ok-ww 的 ``EnhanceEchoTask`` 原样搬运** + MyTools 的筛选条件。

## 为什么搬

2026-09-23 用户实测（在另一台机器上）：「声骸自动强化」**完全没用**。
MyTools 原来自己手写了一套自动化（``controller.py`` / ``runner.py`` / ``reader.py``），
而同一时期做的「4C 自动战斗」走 ok-ww 引擎是跑通的 —— 同一件事没必要写两遍，
更没必要让一个跑不通的版本继续挂着。

## 搬了什么、没搬什么

**搬**：整个探索流程 —— 进培养界面、阶段放入、强化并调谐、关「不再提示/调谐成功」
弹窗、OCR 读词条、不合格按 ``Z`` 弃置、满意按 ``C`` 上锁、循环找下一个 0 级声骸。
坐标 / 模板 / OCR / 后台按键（PostMessage）**全是 ok-ww 原样**。

**没搬**：ok-ww 自己的筛选规则（``必须有双爆`` / ``双爆总计>=`` / ``首条双爆>=`` /
``第一条必须为有效词条`` …）。这些**换成 MyTools 界面上那套**（:func:`stats.judge`）：
核心属性 / 可选属性 / 暴击·爆伤各自下限 / 满值保护 / 有效词条数。
—— 用户明确要求「筛选条件保持我那样」。

## 判定怎么接上去

ok-ww 的判断点只有一个方法：

    check_echo_stats(properties, values) -> bool     # True=继续强化，False=弃置

它把 OCR 出来的「属性名一列 + 数值一列」两串文本当参数传进来。这里把它配对成
:class:`~.stats.EchoStat`，再交给 :func:`~.stats.judge`，最后把三态动作映射回布尔：

* ``discard``  → ``False``（ok-ww 会按 Z 弃置）
* ``continue`` → ``True``（继续强化）
* ``lock``     → ``True``

⚠ ``lock`` 映射成 ``True`` 不是偷懒：MyTools 的 ``lock`` 只在**词条已经满 5 条**时
才出现，而 ok-ww 的主循环里 ``if len(properties) >= 5: self.lock_and_esc()``
本来就会在这个时刻上锁 —— 两条路的落点一致。
「满值保护」那条规则（出了满分词条要留到最后）返回的是 ``continue``，
ok-ww 会继续强化到满级再上锁，语义也正好对得上。
**所以不需要改动 ok-ww 的主循环**，只改这一个方法就够。

## ⚠ 2026-09-24：两个会让本功能"完全没用"的坑（都已修）

**① 任务被静默跳过（头号原因）。** ok-ww 的 ``EnhanceEchoTask`` 声明了
``supported_languages = ["zh_CN", "zh_TW"]``，而 ok-script 的
``task_manager.init_tasks()`` 是这么写的::

    if len(task.supported_languages) == 0 or locale_name in task.supported_languages:
        tasks.append(task)

**不满足就静默不注册**。宿主是无 GUI 的，``init_app_config()`` 拿不到 ok-ww GUI
里那个「语言」设置，``app.locale`` 就是 qfluentwidgets 的默认值 **en_US**（实测）
→ 子类推承的门禁把它挡掉了 → ``find_task`` 返回 None → 点「运行」什么都不会发生。
子类里清了 ``supported_languages`` 即可（见 :meth:`__init__`）。

**② 判定规则自相矛盾。** 有效词条集合只有双爆（2 条）而界面默认要求 ≥3，
声骸每种词条只出现一次 → 永远达不到 → 每个声骸都在满级那一刻被弃置。
修法在 :mod:`stats`（``effective_min_valid_count``）。
"""

from __future__ import annotations

import contextlib
import os
import re
import sys


def _ensure_vendor_on_path() -> None:
    """把 vendored ok-ww 挂到 ``sys.path``。

    本模块要在**任何**上下文里都能被 import：ok 的 ``init_class_by_name``（boot 时，
    vendor 已在 path 上）、PyInstaller 的静态分析、以及单测。所以不假设调用方
    已经把 vendor 加进过 path。
    """
    from ....core import paths  # noqa: PLC0415 - 避免模块级循环导入

    vendor = str(paths.resource_dir("vendor", "okww"))
    if vendor not in sys.path:
        sys.path.insert(0, vendor)


_ensure_vendor_on_path()

from okww.task.EnhanceEchoTask import EnhanceEchoTask  # noqa: E402

from . import echo_grid  # noqa: E402
from .stats import (  # noqa: E402
    DISCARD_CODES,
    EchoStat,
    JudgeConfig,
    judge,
    normalize_stat_name,
    parse_value,
    qualifies,
)

#: 任务在宿主里的注册名（``okww_boot.TASKS`` 与页面上用的是同一个 key）
TASK_KEY = "声骸自动强化"

#: ok-ww 侧看到的类名
TASK_CLASS_NAME = "MyToolsEnhanceEchoTask"

#: 「符合条件的声骸」在 info 里存哪 —— 值是一个 list[dict]。
#:
#: 存 info 而不是普通属性，是因为**工具页要从任务实例上读回来**
#: （``_snapshot_task_stats`` 每 300ms 抄一次，任务跑完实例就被 disable 了）。
#: 结构见 :meth:`MyToolsEnhanceEchoTask._record_qualifying`。
QUALIFYING_INFO_KEY = "符合条件的声骸"

#: ★ 「跳过当前声骸」用的**控制流异常**（用户 2026-10-30 要求"立即中断"）。
#:
#: ## 为什么用异常
#:
#: 强化一个声骸的循环是 ok-ww 写的 ``while True``（在 ``EnhanceEchoTask.run``
#: 里），每一轮揭开一条词条、判一次、再决定继续/弃置/上锁。
#: 要**立即**（不等这一轮跑完）跳出来，只有抛异常能穿过它的控制流。
#:
#: ## 谁抛 / 谁接
#:
#: * 抛：:meth:`MyToolsEnhanceEchoTask.check_echo_stats` —— 那是每揭开
#:   一条词条就会调一次的地方，也是**唯一**能及时感知"用户按了跳过"的点。
#: * 接：:meth:`MyToolsEnhanceEchoTask.run` —— 捕获后重新筛选、重新开跑。
#:
#: ## 为什么不用 return / 标志位
#:
#: ``check_echo_stats`` 的返回值只表示"继续强化 or 弃置这个声骸"，
#: 没法表达"跳出整个 run 循环"。标志位更不行 —— 循环体里没有读标志的地方。
class SkipCurrentEcho(Exception):
    """内部信号：用户要求跳过当前声骸（不是错误，别当失败报给用户）。"""


#: ★ 标记「这个任务实例是任务流程起的，不是工具页单独跑的」。
#:
#: ## 为什么需要区分（用户 2026-10-28）
#:
#: > 声骸任务运行时，如果成功强化好了符合条件的时候，
#: > 此时如果配置暂停强化，任务也会被暂停……
#: > 但是任务里我要让他切换到强化另一种声骸
#:
#: 两条路径对「符合条件后怎么收尾」的要求正好相反：
#:
#: ============  =============================================
#: 工具页          ``pause()`` —— 可点「继续」接着强化
#: 任务流程        **停止当前步骤** —— 流程才能走下一步
#: ============  =============================================
#:
#: 任务流程的 ``OkwwTaskRunner.run()`` 是同步等任务结束的 while 循环，
#: 一旦 ``pause()`` 就永久卡死在那一步（见 ``_auto_stop_if_needed`` 的说明）。
#:
#: 实现方式：``OkwwTaskRunner._configure`` 往任务实例上写这个属性 = True。
#: 用 ``getattr(task, FLOW_MODE_FLAG, False)`` 读，工具页那条路读不到 → False。
FLOW_MODE_FLAG = "_mytools_flow_mode"


#: 「跳过已处理同种声骸」时，一轮最多连续跳几个。
#:
#: ## 用户 2026-10-28
#:
#: > 就是要做成一个集合记住这个声骸已处理，
#: > 然后下次遇到同名的未强化的，直接C解锁改为未标记
#:
#: > 这个集合的最大值是2才对，因为只有3C才会有多个，这个是正常情况
#:
#: 实现见 :meth:`MyToolsEnhanceEchoTask.select_0_level_echo` 的覆盖版：
#: 每轮选目标后读名字，在集合里 → 按 C 解锁并跳过，再选下一个。
#:
#: ## 为什么比"扫 18 格"好
#:
#: 扫 18 格要 11 秒/屏且每次强化成功都要扫；这个方法**零额外扫描**
#: （本来就是每轮必经的一步），而且**天然跨屏**（ok-ww 自己会滚动找
#: 0 级声骸，同名的不管在第几屏都会碰到）。
#:
#: ## 为什么上限是 2
#:
#: 3C 配置里每种声骸选 **2 个主属性**（攻击% + 属性伤害%），
#: 所以游戏里同种 3C **最多就是 2 个**。1C/4C 每种只有 1 个，
#: 不存在同名。
#:
#: 所以"一个已处理 + 最多跳过 1 个同名的"就是正常情况，
#: 上限给 2 留一点余量（万一用户有 3 个同种，第三个也会被处理，
#: 只是要等下一轮）。
#:
#: ⚠ 设太大没意义：真出现"20 个同名叠在一起"那是数据异常，
#: 硬跳 20 次会白花 8 秒以上，还可能撞上界面没刷新的坑。
SKIP_HANDLED_MAX = 2

#: :class:`MyToolsEnhanceEchoTask.run` 里"连着跳过多少次就放弃"的上限。
#:
#: ## 为什么需要（2026-10-30）
#:
#: 「读不到声骸名 → 也跳过（不强化）」这条兜底本身是对的
#: （读不到就无法核对配置，宁可不强化），但它有个天然风险：
#: 万一 OCR 一直读不到，就会
#:
#:     跳过 → Esc 回列表 → 重开 run() → 又读不到 → 又跳过 → …
#:
#: **无限循环**，而且每次都白点一次「培养」+ 按 Esc，
#: 把游戏界面折腾个没完，用户完全不知道发生了什么。
#:
#: 给个上限：连续跳过这么多次都没真正强化一个，就判定"OCR 坏了 / 配置空了"，
#: 停下任务并把原因写进「失败原因」（界面和托盘都能看到）。
#:
#: 为什么是 8：正常情况下强化成功一个就会把计数清零（见 ``run``），
#: 连着 8 个都只能跳过，已经不可能是"运气不好"了。
MAX_CONSECUTIVE_SKIPS = 8


@contextlib.contextmanager
def _no_startfile():
    """临时让 ``os.startfile`` 变成空操作。

    为什么需要：ok-ww 的 ``run()`` 在「强化结束且成功过至少 1 个」时会
    ``os.startfile('screenshots')`` —— 在它自己的 GUI 里那是"帮你打开截图文件夹"，
    但在 MyTools 里这是**后台工具**，无缘无故弹一个资源管理器窗口很突兀。
    屏蔽范围仅限本任务 ``run()`` 的存活期，且只是不弹文件夹，不影响截图落盘。
    """
    original = os.startfile
    os.startfile = lambda *a, **k: None       # type: ignore[assignment]
    try:
        yield
    finally:
        os.startfile = original               # type: ignore[assignment]


def format_tally(checked: int, tally: dict[str, int]) -> str:
    """把弃置原因统计拼成一行（纯函数，方便单测）。

    为什么要有这行：判定的结果只有"弃置/保留"两种，用户看到"刷了 40 个全丢掉了"
    时完全无法判断是**规则太严**还是**读错了词条**。把原因分布摆出来就一目了然。
    """
    dropped = sum(tally.values())
    if not dropped:
        return f"已判 {checked} 次，暂无弃置"
    parts = [
        "%s %d" % (DISCARD_CODES.get(code, code), count)
        for code, count in sorted(tally.items(), key=lambda kv: -kv[1])
    ]
    return "已判 %d 次，弃置 %d 个（原因：%s）" % (checked, dropped, "、".join(parts))


def to_echo_stats(properties, values) -> list[EchoStat]:
    """把 ok-ww 读出来的两串文本配对成 :class:`EchoStat` 列表。

    ``properties`` / ``values`` 是 ok-script 的 ``Box``（有 ``.name`` 与 ``.y``）。
    配对规则**照抄 ok-ww 的 ``check_echo_stats``**：属性名与数值分两列排，
    按 y 坐标最近的一一配对，每个数值只用一次。

    ⚠ 与 ok-ww 唯一的差别（有意为之）：**先把认不出的属性名剔掉再配对**。
    ok-ww 只过滤了「辅音」一个词，剩下任何 OCR 噪声（多认出的中文短语）都会
    "吃掉"一个数值，让它后面所有属性名整体错位一格 —— 数值配错了，判定自然是错的。
    :func:`judge` 本来就只认标准词条，所以提前剔掉这些噪声是纯收益。
    """
    known = [p for p in properties if normalize_stat_name(p.name, "") is not None]

    unmatched = list(values)
    stats: list[EchoStat] = []
    for prop in known:
        value_text = ""
        if unmatched:
            closest = min(unmatched, key=lambda v: abs(prop.y - v.y))
            value_text = closest.name
            unmatched.remove(closest)

        name = normalize_stat_name(prop.name, value_text)
        value = parse_value(value_text)
        if name is None or value is None:
            continue
        stats.append(EchoStat(name=name, value=value))
    return stats


class _MaterialsReady:
    """哨兵：**材料已经放进去了**，外层循环不该再点那个按钮。

    为什么需要它、以及它为什么不能真去点，见
    :meth:`MyToolsEnhanceEchoTask.find_add_mat` 的长注释。

    单例用 ``is`` 比较（``==`` 会被别的对象蒙混过关）。
    """


#: :class:`_MaterialsReady` 的唯一实例
_MATERIALS_READY = _MaterialsReady()


class MyToolsEnhanceEchoTask(EnhanceEchoTask):
    """ok-ww 的强化流程 + MyTools 的筛选条件。

    除了 :meth:`check_echo_stats` 与几处与判定直接相关的配置，其余全部继承。
    """

    #: 一轮最多连续跳过几个"同种已处理"的声骸。
    #:
    #: ⚠ 这里是**类属性**，和模块级 :data:`SKIP_HANDLED_MAX` 同值 ——
    #: 双保险。2026-10-28 曾经因为方法里写 ``self.SKIP_HANDLED_MAX``
    #: 但常量只在模块级定义，运行时抛 AttributeError 把整轮任务搞崩。
    SKIP_HANDLED_MAX = SKIP_HANDLED_MAX

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.name = "⬆️ 声骸自动强化（鸣潮工具箱筛选条件）"
        self.description = (
            "点 B 进背包 → 声骸 → 用过滤器筛出要强化的 → 按等级升序排序后开始。"
            "流程与 ok-ww 一致，判定用鸣潮工具箱里配的那套条件。"
        )

        # ok-ww 默认「成功即暂停」，那是给"边看边强化"准备的；
        # MyTools 是批量工具，暂停会表现得像"只跑一个就停了" —— 关掉。
        # （after_init → load_config 会拿 default_config 生成 self.config，
        #   所以在这里改默认值是生效的。见 ok/task/task.py: load_config）
        self.default_config["Pause after Success"] = False

        # ★★ 语言门禁：**必须清空**，否则这个任务会凭空消失。
        #   ok-ww 的 EnhanceEchoTask 声明了 supported_languages = ["zh_CN", "zh_TW"]，
        #   而 ok-script 的 task_manager.init_tasks() 不满足就**静默不注册**。
        #   宿主无 GUI → app.locale 是 qfluentwidgets 的默认值 en_US（实测）→
        #   任务根本进不了引擎，点「运行」只得到「找不到任务」。
        #   宿主场景里"引擎语言"这个代理量毫无意义：本工具就是给中文游戏用的，
        #   ok-ww 的 OCR 匹配串（'培养' / '阶段放入' …）本来就是中文字面量。
        #   清空 = 永远注册；run() 里另有一道语言检查，不匹配会明确告警。
        self.supported_languages = []

        #: 判定配置。由宿主在启动任务前注入（见 ``okww_boot.OkwwHost.start_task``）
        #: —— 也就是工具页上用户配的那套筛选条件。
        self.judge_config = JudgeConfig()

        #: 最近一次的判定结果（日志/排查用）
        self.last_judgement = ""
        #: 弃置原因统计（键是 :data:`DISCARD_CODES` 的分类码）
        self.discard_tally: dict[str, int] = {}
        #: 一共判过多少次
        self.checked_echoes = 0
        #: 「满属性」声骸数（出现过满暴击/满爆伤词条并被上锁的声骸）
        self.perfect_echoes = 0
        #: ★ 「真正符合条件」的声骸清单（用户要求：报告里以卡片完整展示声骸图）。
        #: 每项形如 ``{"index": 成功序号, "stats": ["暴击 7.5", …], "image": 文件名}``。
        self.qualifying_echoes: list[dict] = []
        #: 当前这个声骸有没有出现过满分词条（逐声骸结算用，见 ``_finalize_echo``）
        self._perfect_seen = False
        #: 「材料已在里面」这个哨兵本轮是否已经报告过（见 ``find_add_mat``）。
        #: 只报告一次，好让 ok-ww 那个内层 while 能正常 break 出去、不白等满 5 秒。
        self._materials_ready_sent = False

        #: ★ 当前这个声骸**最后一条词条**读出来时，是不是「真正符合条件」的。
        #:
        #: 为什么掐"最后一条"那一刻：``check_echo_stats`` 一个声骸会被调 5 次，
        #: 前面几条时"能不能达标"还是未知的（还有孔位），只有**满 5 条**那一刻
        #: 结论才定。所以逐条记录、以最后一条为准。
        self._qualifying_now = False
        #: 已经自动暂停过几次（防止"暂停后又被恢复→立刻再暂停"来回弹）
        self.auto_stop_count = 0
        #: 当前这个声骸**最后一次**读到的词条（结算时拿去记录，见 _finalize_echo）
        self._last_present: list[EchoStat] = []

        #: ★ 2026-10-30 「进强化界面后的最后一道核验」相关状态。
        #:
        #: ``_entry_checked``：这个声骸在强化界面里核过了没有
        #: （``find_add_mat`` 一进界面就核一次，之后不再重复 OCR）。
        #: 每选中新声骸（``select_0_level_echo``）和每轮重开（``run``）都重置。
        #:
        #: ``_cursor_name``：光标所在格读到的名字。用来核对
        #: "右侧面板的读数是不是滞后于光标"。
        #:
        #: ``_cursor_slot``：光标当前在哪个格子 ``(row, col)``。
        self._entry_checked = False
        self._cursor_name = ""
        self._cursor_slot: tuple[int, int] | None = None
        #: 连续跳过了几次（真强化完一个就清零，见 ``run`` 里的死循环保护）
        self._consecutive_skips = 0
        #: 「进强化界面后核验」打过几次日志（前几次打，之后静默，避免刷屏）
        self._entry_gate_logged = 0
        self._fm_logged = 0

        #: ★★★ 2026-10-30 **外部注入的配置字段：只在这里给默认值**。
        #:
        #: 它们由 ``OkwwTaskRunner._configure`` 通过 ``setattr`` 覆盖
        #: （在 ``__init__`` 之后、``run()`` 之前）。
        #:
        #: ⚠⚠⚠ **绝对不能在 `run()` 里重置它们**！这是困扰一整天的
        #: 两个 bug 的总根因 —— 原来 `run()` 里有::
        #:
        #:     self._allowed_echoes: set[str] = set()   ← 把注入的 6 个清了
        #:     self._set_plan: dict[int, int] = {}      ← 把 43311 清了
        #:     self._echo_cost: dict[str, int] = {}     ← 把 Cost 索引清了
        #:
        #: 实机日志（2026-10-30 15:11，同一个 task#）::
        #:
        #:     15:11:19 【run 启动】task#… 白名单=6个 成套={4:1,3:2,1:2}
        #:     15:11:21 [fm#1] 白名单=0个 成套=False
        #:
        #: 现在只在 `__init__` 建默认值，`run()` 一律不碰。
        self._allowed_echoes: set[str] = set()
        self._set_plan: dict[int, int] = {}
        self._set_done: set[int] = set()
        self._echo_cost: dict[str, int] = {}

    # ------------------------------------------------------ 符合条件的判定
    def _remember_judgement(self, stats: list[EchoStat], full: bool) -> None:
        """记住"当前这个声骸算不算真正符合条件"。

        :param full: 是不是已经读满 5 条（= 结论定的那一刻）

        ⚠ 判据用 :func:`stats.qualifies` 而**不是** ``result.action == "lock"``：
        「满值保护」是最高优先且**会短路** —— 出了满暴击/满爆伤就直接返回
        ``lock``，双爆下限 / 核心属性 / 有效词条数**根本没跑**。
        于是"满暴击但有效词条只有 1 条"也会被上锁（有意保护），
        但那**不算符合条件**（用户 2026-10-10 明确要求排除）。

        ⚠ 只在 ``full`` 时把结论**当真**：没读满之前 `qualifies` 为真
        只表示"还没被淘汰"（还剩孔位可以凑），不能拿去触发自动停止。
        """
        if full:
            self._qualifying_now = qualifies(stats, self.judge_config)
        elif not qualifies(stats, self.judge_config):
            #: 中途就已经废了（双爆低于下限 / 核心凑不齐）→ 提前钉死为"否"，
            #: 免得靠后面把它翻回来
            self._qualifying_now = False

    def _record_qualifying(self, stats: list[EchoStat]) -> None:
        """把一个「符合条件的声骸」记进 info（含截图文件名，给报告卡用）。

        ## 为什么要记截图名

        用户 2026-10-10 要求："结果报告符合条件的要完整展示声骸图，以卡片形式展示"。
        而 ok-ww 在 ``lock_and_esc`` 里**已经**把那个声骸截好图了::

            self.screenshot_echo(f'success/{成功声骸数量}')

        落在 ``<用户数据>/okww/screenshots/success/`` 下，文件名形如
        ``16-38-56.014_1_original.png``（``时间_序号_original``）。
        → 直接复用这些图，**不重建截图链路**（那要碰 ok-ww 的坐标和时序）。

        ⚠ 用 ``success/`` 目录 + ``序号`` 前缀找：ok-ww 的序号 = 成功声骸数量，
        正好能对上。找不到就只记词条（卡片那边退化成纯文字，不留空洞）。
        """
        self.qualifying_echoes.append({
            "index": self.info_get("成功声骸数量", 0),
            "stats": [str(s) for s in stats],
            "image": self._find_echo_screenshot(),
            #: ★ 这个声骸是不是**因为出了满值词条**才被保下来的。
            #:
            #: 逐声骸记，不用"整体满属性计数"近似 —— 用户要求卡片上标出满属性，
            #: 而"全局有几个满属性"根本推不出"**这一个**是不是满属性"
            #: （我第一版就是这么近似的，纯属糊弄）。
            "perfect": bool(self._perfect_seen),
        })
        try:
            self.info_set(QUALIFYING_INFO_KEY, list(self.qualifying_echoes))
        except Exception:  # noqa: BLE001 - info 写不进去不该打断任务
            pass

    def _find_echo_screenshot(self) -> str:
        """找刚上锁那个声骸的截图**文件名**（找不到返回空串）。

        ⚠ 只返回**文件名**，不返回绝对路径：图片目录在用户数据目录下，
        而工具页那边自己知道根目录（``paths.user_data_dir()``）——
        存绝对路径的话，用户搬了数据目录、或者打包版路径不同，就会全失效。
        """
        try:
            from ....core import paths

            folder = (paths.user_data_dir() / "okww" / "screenshots" / "success")
            if not folder.is_dir():
                return ""
            want = int(self.info_get("成功声骸数量", 0) or 0)
            #: 文件名里的序号是 ``..._<n>_original.png`` 那一段
            pattern = re.compile(r"_%d_original\.png$" % want)
            hits = [p.name for p in folder.iterdir()
                    if p.is_file() and pattern.search(p.name)]
            #: 同一个序号理论上只有一个；多个就取最新改的（改名/重跑都不怕）
            if not hits:
                return ""
            hits.sort(key=lambda n: (folder / n).stat().st_mtime, reverse=True)
            return hits[0]
        except Exception as exc:  # noqa: BLE001 - 找不到图不该打断任务
            self.log_debug(f"找声骸截图失败：{type(exc).__name__}: {exc}")
            return ""

    # ------------------------------------------------------------------ 判定
    def check_echo_stats(self, properties, values) -> bool:
        """返回 ``True`` = 继续强化，``False`` = 交给 ok-ww 去弃置。

        ## ★ 这里是「跳过」的**立即**检查点（2026-10-30 用户要求）

        > 另外跳过要立即中断当前强化，回到声骸完成筛选那一步

        这个方法**每揭开一条词条就被调一次**（一个声骸最多 5 次），
        是强化循环里唯一能"及时"感知用户操作的钩子。

        所以放在最前面：一进来就看有没有跳过请求，有就抛
        :class:`SkipCurrentEcho` 直接冲出 ok-ww 的 ``while True``
        强化循环，由 :meth:`run` 捕获后重新筛选。

        ⚠ 抛在 ``judge()`` **之前**：跳过的意思就是"这个声骸不判了"，
        没必要为了一个要被丢弃的声骸多算一遍判定。
        """
        #: ★★ 2026-10-30 工具页「跳过」按钮的**第一个检查点**。
        #:
        #: 这个方法**每揭开一条词条就被调一次**（一个声骸最多 5 次），
        #: 是强化循环里能"尽早"感知用户操作的地方。
        #:
        #: 按一下跳过 = 把这个声骸当成已强化好：
        #: ① 记进 ``_handled_echoes``（之后同名的都跳过）
        #: ② ``_mark_cost_progress`` / ``_force_satisfy_cost``
        #:    （成套时计入该 Cost 档种类数）
        #: ③ 抛异常冲出 ok-ww 的强化循环，由 ``run()`` 捕获后重新开跑
        if self._consume_skip_request():
            name = ""
            try:
                from . import same_echo  # noqa: PLC0415

                name = same_echo.read_echo_name(
                    self, known_names=getattr(self, "_allowed_echoes", None))
            except Exception:  # noqa: BLE001 - 读不到也别挡着跳过
                name = ""
            if name:
                self._note_handled_echo(name)
                self._mark_cost_progress(name)
                self._force_satisfy_cost(name)
                self.log_info(
                    f"【跳过】「{name}」记为**已处理**"
                    f"（之后同类型同名的都会跳过）", notify=True)
            else:
                self.log_info(
                    "【跳过】⚠ 读不到声骸名 —— 只跳过这一个", notify=True)
            raise SkipCurrentEcho("用户跳过当前声骸")

        stats = to_echo_stats(properties, values)
        result = judge(stats, self.judge_config)

        self.last_judgement = str(result)
        #: ★ 记住"这个声骸算不算真正符合条件"（判据见 :meth:`_remember_judgement`）。
        #: 一个声骸会被调 5 次，只有读满 5 条那一刻结论才定。
        self._last_present = list(result.stats)
        self._remember_judgement(list(result.stats),
                                 full=len(result.stats) >= self.judge_config.max_sub_stats)
        # 统计"为什么弃置"——不然用户只看到"全都丢掉了"，无从下手
        self.checked_echoes += 1
        if result.action == "discard":
            code = result.code or "other"
            self.discard_tally[code] = self.discard_tally.get(code, 0) + 1
            self.info_set("判定统计", self.tally_text())
        elif result.code == "max_roll":
            # 出了满分词条 → 先记在"当前这个声骸"头上；**真正计数**等它处理完再做
            # （见 _finalize_echo）—— 同一个声骸会被判 5 次，按次数算会重复计数
            self._perfect_seen = True
        # ok-ww 会把 fail_reason 拼进失败截图的文件名，所以给个安全的短串
        self.fail_reason = result.reason or result.action
        self.info_set("鸣潮工具箱判定", str(result))
        self.log_info(
            "鸣潮工具箱判定：%s（读到词条 %s）"
            % (result, "、".join(str(s) for s in stats) or "无")
        )
        return result.action != "discard"

    def tally_text(self) -> str:
        """一行统计（给 InfoBar / 日志用）。"""
        return format_tally(self.checked_echoes, self.discard_tally)

    # ------------------------------------------------ 材料插入（补 ok-ww 的致命缺口）
    def find_add_mat(self):
        """「阶段放入」按钮；材料**已经在里面**时返回一个不会被点的哨兵。

        ## ok-ww 原实现的缺口（2026-09-26 实测：跑完 42 次判定后整个任务中断）

        ``EnhanceEchoTask.run()`` 里那段是：

            while ... < 5:
                add_mat = self.find_add_mat()      # 只认「阶段放入」
                if add_mat: have_add_mat = True; click(add_mat)
                else: ... if have_add_mat: break
            if not have_add_mat:
                raise Exception('强化设置需要开启阶段放入!')

        而那个按钮的**文案是随状态变的**：

        * 材料槽空着     → 「阶段放入」（点它按阶段放入材料）
        * 材料已在里面   → 「清 除」  （点它是把材料撤掉）

        于是只要有一轮「强化并调谐」没把材料消耗掉（点击被界面过渡吞掉，
        或那一刻刚好没生效），材料就留在里面；下一轮 ``find_add_mat`` 找不到
        「阶段放入」→ 空等 5 秒 → **抛异常，整个任务当场结束**，
        而报的错还是「强化设置需要开启阶段放入!」—— 跟真实状态正好相反，
        用户只会去反复检查那个设置。

        ## 这里的处理

        认出「清 除」＝**材料已就绪**，让外层把 ``have_add_mat`` 置真、直接往下走
        「强化并调谐」，而不是判它死刑。哨兵**只报告一次**（下一次返回 None），
        这样外层的 ``if have_add_mat: break`` 能正常生效，不会白等满 5 秒。
        """
        #: ★★★ 2026-10-30 无条件诊断（前 5 次）：证明 find_add_mat 到底有没有被调。
        #:
        #: 之前加了 `[闸]` 日志却一次都没出现，无法判断是
        #: "闸没执行" 还是 "执行了但没进 if"。这里在**方法最开头**打一条，
        #: 一定能看出这个方法被调过、以及当时的关键状态。
        #:
        #: ⚠ 用**独立计数器** ``_fm_logged``（不能和闸的 ``_entry_gate_logged``
        #: 共用，否则先跑的这个会把对方的额度吃光）。
        self._fm_logged = getattr(self, "_fm_logged", 0)
        if self._fm_logged < 5:
            self._fm_logged += 1
            self.log_info(
                f"[fm#{self._fm_logged}] find_add_mat 被调用："
                f"entry_checked={getattr(self, '_entry_checked', '未定义')}  "
                f"白名单={len(getattr(self, '_allowed_echoes', ()))}个  "
                f"成套={bool(getattr(self, '_set_plan', None))}")

        #: ★★ 2026-10-30 工具页「跳过」按钮的**第二个检查点**（更频繁）。
        #:
        #: ``check_echo_stats`` 只在揭开词条时被调（间隔好几秒），
        #: 而 ``find_add_mat`` 是强化循环里**每一轮都会调**的方法 ——
        #: 在这里查，用户按跳过最多等一个循环（约 1~2 秒）就生效。
        if self._consume_skip_request():
            name = ""
            try:
                from . import same_echo  # noqa: PLC0415

                name = same_echo.read_echo_name(
                    self, known_names=getattr(self, "_allowed_echoes", None))
            except Exception:  # noqa: BLE001
                name = ""
            if name:
                self._note_handled_echo(name)
                self._mark_cost_progress(name)
                self._force_satisfy_cost(name)
                self.log_info(
                    f"【跳过】「{name}」记为**已处理**"
                    f"（之后同类型同名的都会跳过）", notify=True)
            else:
                self.log_info(
                    "【跳过】⚠ 读不到声骸名 —— 只跳过这一个", notify=True)
            raise SkipCurrentEcho("用户跳过当前声骸")

        #: ★★★ 2026-10-30 **最后一道闸**：进入强化界面后，再核一次
        #: 「这个声骸到底该不该强化」。
        #:
        #: ## 为什么需要（用户实测的两个 bug）
        #:
        #: 1. **配置里已删掉的声骸还在被强化**
        #:    （"我配置里明明已经去掉了融躯战士，怎么任务里还是要强化他"）
        #: 2. **成套的档已达标还在强化**
        #:    （"连续跳过2个1C后，怎么还是强化1C了"）
        #:
        #: ## 根因：`select_0_level_echo` 那关漏掉了
        #:
        #: 那一关靠 `_read_current_name()` 读**列表页右侧**的名字。
        #: 但 `super().select_0_level_echo()` 刚点完第 0 格，
        #: 右侧详情面板**可能还没刷新完** → 读到上一个声骸的名字 /
        #: 读到空 → `_skip_reason` 判"该强化" → 就这么点进强化界面了。
        #:
        #: 而**这里**（`find_add_mat`，已经进了强化界面）名字显示在
        #: 左上角标题，是最稳的时刻 —— 在这里再核一次，
        #: 该跳过就立刻抛异常退出去，一个词条都不揭。
        #:
        #: ⚠ 只在**有白名单或有成套结构**时才核（否则每次多一次 OCR）。
        #: ⚠⚠ 还要**一次性**（``_entry_checked``）—— ``find_add_mat``
        #: 在一个声骸的强化过程中会被调好几次，每次都 OCR 太浪费。
        #: 而且入口处这一次核过就够了（名字不会变）。
        if not getattr(self, "_entry_checked", False) \
                and (getattr(self, "_allowed_echoes", None)
                     or getattr(self, "_set_plan", None)):
            self._entry_checked = True
            name = ""
            #: ★★★ 2026-10-30 **多读几次**（实机发现问题就在这）。
            #:
            #: ## 为什么不能只读一次
            #:
            #: 强化界面刚打开的一瞬间，**游戏还在切界面动画**，
            #: WGC 捕获到的是**黑帧**（实测截图整张全黑，
            #: ``data/okww/screenshots/15-35-56.639_…_original.png``），
            #: OCR 什么都读不到 → 返回空串。
            #:
            #: 于是形成死循环::
            #:
            #:     点「培养」→ 界面还没渲染好 → 读不到名字 → 跳过（Esc 退出）
            #:       → 又点「培养」→ 又没渲染好 → 又读不到 → 又跳过 → …
            #:
            #: 实机表现为"在第一个和第二个声骸之间来回弹"，
            #: 8 次后被 ``MAX_CONSECUTIVE_SKIPS`` 停掉。
            #:
            #: ## 现在怎么做
            #:
            #: 最多读 5 次、每次间隔 0.4 秒（共约 2 秒），
            #: 读到名字就立刻用；5 次都读不到才判定"真的读不到"。
            #: 2 秒对一个已经打开的界面绰绰有余。
            for _try in range(5):
                try:
                    from . import same_echo  # noqa: PLC0415

                    name = same_echo.read_echo_name(
                        self, known_names=getattr(self, "_allowed_echoes", None))
                except Exception:  # noqa: BLE001
                    name = ""
                if name:
                    break
                if _try < 4:
                    self.sleep(0.4)
            #: ★★★ 2026-10-30 **读不到名字时先判"是不是黑屏"**。
            #:
            #: 实测（2026-10-30 15:35）失败截图整张全黑 —— 强化界面刚打开
            #: 的一瞬间 WGC 抓到的是黑帧，OCR 必然读不到。
            #:
            #: 如果这时按"读不到 → 跳过"处理，就会
            #: **点培养 → 黑 → 跳过 → 点培养 → 黑 → 跳过** 无限弹，
            #: 用户看到的正是"在第一个和第二个声骸之间徘徊"。
            #:
            #: 黑屏是**环境问题**（游戏没渲染），不是"这个声骸该跳过"，
            #: 所以这时候应该**等它画出来**，绝不能判跳过。
            if not name:
                try:
                    from . import same_echo  # noqa: PLC0415

                    if same_echo.screen_looks_blank(self):
                        #: 等 2.5 秒再读一次（给它时间渲染）
                        self.log_info(
                            "⚠ 强化界面是黑屏（游戏没渲染）→ 等 2.5 秒再看，"
                            "**不判跳过**")
                        self.sleep(2.5)
                        try:
                            from . import same_echo as _se  # noqa: PLC0415

                            name = _se.read_echo_name(
                                self, known_names=getattr(
                                    self, "_allowed_echoes", None))
                        except Exception:  # noqa: BLE001
                            name = ""
                except Exception:  # noqa: BLE001 - 探测失败不影响主流程
                    pass
            #: ★★ 2026-10-30 诊断：前 3 次核验**必定打日志**。
            #:
            #: 用户反复报"还是没实现"，而我加的所有日志一次都没出现
            #: —— 没法判断是"闸没执行"还是"执行了但判定通过"。
            #: 打这行就能区分：有这行 = 闸执行了；没有 = 闸压根没跑到。
            if self._entry_gate_logged < 3:
                self._entry_gate_logged += 1
                _why = self._skip_reason(name) if name else "（读不到名字）"
                self.log_info(
                    f"[闸] 进强化界面核验#{self._entry_gate_logged}："
                    f"读到={name!r}  白名单{len(getattr(self, '_allowed_echoes', ()))}个  "
                    f"达标档={sorted(getattr(self, '_set_done', ()))}  "
                    f"判定={_why or '可强化'}")
            if name:
                reason = self._skip_reason(name)
                if reason:
                    self._note_handled_echo(name)
                    self._mark_cost_progress(name)
                    self._force_satisfy_cost(name)
                    self.log_info(
                        f"【跳过】进强化界面后发现「{name}」{reason}"
                        f" —— 立即退出，不强化它", notify=True)
                    raise SkipCurrentEcho(f"进界面后判定该跳过：{reason}")
            else:
                #: ★★★ 2026-10-30 读不到名字时**不再一律跳过**（重要修正）。
                #:
                #: ## 原来的做法及其后果
                #:
                #: "读不到名字 → 跳过"看起来安全（宁可不强化），但实机上
                #: 造成了**死循环**：强化界面刚打开的瞬间画面是黑的，
                #: 读不到 → 跳过（Esc）→ 又点培养 → 又黑 → 又跳过 …
                #: 用户看到的就是"在第一个和第二个声骸之间来回弹"，
                #: 8 次后被 ``MAX_CONSECUTIVE_SKIPS`` 停掉，一个都没强化。
                #:
                #: ## 现在怎么处理
                #:
                #: * **黑屏** → 已经在上面的 ``screen_looks_blank`` 分支
                #:   等过 2.5 秒了；还读不到说明游戏真的没画面，
                #:   **照常往下走**（让 ok-ww 去点材料/强化），
                #:   真不行它自己会报错停下。绝不在这里 Esc 循环。
                #: * **不黑但读不到** → 说明区域/OCR 有问题，
                #:   这时跳过是对的（防止强化不该强化的），
                #:   但要打足够显眼的日志。
                _blank = False
                try:
                    from . import same_echo as _se2  # noqa: PLC0415

                    _blank = _se2.screen_looks_blank(self)
                except Exception:  # noqa: BLE001
                    pass
                if _blank:
                    self.log_info(
                        "⚠ 强化界面读不到名字，且画面是黑的 → "
                        "**不判跳过**，照常继续（避免死循环）", notify=True)
                else:
                    self.log_info(
                        "⚠ 进强化界面后读不到声骸名（无法核对配置）"
                        "→ 立即退出，不强化它", notify=True)
                    raise SkipCurrentEcho("进界面后读不到声骸名")

        element = super().find_add_mat()
        if element:
            # 「阶段放入」还在 → 材料是空的，正常放入。复位哨兵供本轮再报告。
            self._materials_ready_sent = False
            return element

        #: ★★★ 2026-10-28 「自动切换阶段放入」挂在这里（不在 run() 开头）。
        #:
        #: ## 为什么选这个位置
        #:
        #: ``find_add_mat()`` 是 ok-ww 在**强化界面里**反复调的方法::
        #:
        #:     while True:                       # EnhanceEchoTask.run()
        #:         while ... < 5:
        #:             add_mat = self.find_add_mat()      # ← 就是这里
        #:
        #: 走到这里说明：界面已经是强化界面、材料面板已经渲染出来。
        #: **这时候点齿轮 ⚙ 才是安全的**。
        #:
        #: ## 为什么不能放 run() 开头（实机翻车记录）
        #:
        #: 那时还停在背包列表页，盲点 (639,673) 会点到别的东西 → 界面乱
        #: → ``select_0_level_echo()`` 找不到 0 级声骸 → 收工 →
        #: 报「本次没有判定任何声骸」（19:24:57 实际发生过）。
        #:
        #: ## 试一次就够，不反复试
        #:
        #: 用 ``_stage_insert_checked`` 做一次性开关：切过（不管成功失败）
        #: 就不再试。否则每个声骸、每轮循环都会点一次齿轮，界面全乱。
        if not getattr(self, "_stage_insert_checked", False):
            self._stage_insert_checked = True
            try:
                self._ensure_stage_insert_mode()
            except Exception as exc:  # noqa: BLE001 - 切换失败不该把任务搞崩
                self.log_debug(f"自动切换阶段放入失败：{type(exc).__name__}: {exc}")

        #: ⚠⚠ 2026-10-28 我在这里加过一个「找不到阶段放入就点快捷放入」的
        #: fallback —— **已经撤掉，别再加回来**。
        #:
        #: ## 为什么是错的
        #:
        #: 用户截图（齿轮 ⚙ 点开的「自动放入设置」）说明了游戏的真实语义::
        #:
        #:     放入模式
        #:       ○ 快捷放入   放入所有符合筛选规则的材料，直到达到声骸等级上限
        #:       ● 阶段放入   放入将声骸提升至最近可调谐等级(5/10/15/20/25)的材料
        #:
        #: 也就是说：**材料区那个按钮显示的是「当前模式」的名字**。
        #:
        #:     模式=阶段放入 → 按钮写「阶段放入」
        #:     模式=快捷放入 → 按钮写「快捷放入」
        #:
        #: ok-ww 找「阶段放入」按钮，**前提就是模式已经设成阶段放入**。
        #:
        #: 所以「找不到阶段放入」只可能有两种原因：
        #:   ① 模式是快捷放入（用户在游戏里设错了 —— 该让用户去改）
        #:   ② 材料已经放进去了，按钮变成「清 除」（下面那个分支处理）
        #:
        #: 如果点「快捷放入」：材料会**一次性填满到等级上限**，
        #: +5/+10/+15/+20 这些阶段判定全部跳过 → 强化逻辑直接废掉，
        #: 而且花掉的材料是**不可撤销**的。
        #:
        #: → 找不到就老老实实报错，让用户去齿轮里把模式切成「阶段放入」。
        #:   报错文案也在下面改清楚（不要只说「需要开启」，要说怎么开）。

        if getattr(self, "_materials_ready_sent", False):
            # 已经报告过就绪 → 返回 None，让外层 break（不然要白等满 5 秒）
            self._materials_ready_sent = False
            return None

        if self._has_material_reset_button():
            self._materials_ready_sent = True
            # 记一笔：否则"这次为什么没报错"在日志里看不出来，
            # 下次排查又会以为工具什么都没做。
            self.log_info(
                "材料还留在槽里（按钮已是「清 除」）→ 直接继续强化，"
                "不再空等「阶段放入」"
            )
            return _MATERIALS_READY
        return None

    def _has_material_reset_button(self) -> bool:
        """材料区那个按钮现在是不是「清 除」＝ 材料已经放进去了。

        用**单帧** ``ocr`` 而不是 ``wait_ocr``：这是个"看一眼就好"的探针，
        每次都等满 time_out 会把每个声骸都拖慢 1 秒。
        """
        try:
            return bool(self.ocr(0.09, 0.6, 0.38, 0.86,
                                 match=[re.compile(r"清\s*除")]))
        except Exception:  # noqa: BLE001 - 探不到就当没有，退回 ok-ww 原来的行为
            return False

    def click(self, *args, **kwargs):
        """哨兵不该被点 —— 它代表「清 除」，真点下去会把材料**撤掉**。"""
        if args and args[0] is _MATERIALS_READY:
            return None
        return super().click(*args, **kwargs)

    def _finalize_echo(self, *, kept: bool) -> None:
        """一个声骸处理完了（上锁 / 弃置）—— 结算它的「满属性」身份。

        为什么要按**声骸**结算而不是按判定次数：``check_echo_stats`` 每揭开一条词条
        就被调一次（一个声骸最多 5 次），满分词条一旦出现，之后每轮都会再命中那条规则。
        按次数算会把一个声骸数成好几个。

        只在**启用满值保护**时统计（用户要求）—— 关掉保护时满分词条不会被特殊对待，
        那个数就失去意义了。

        ★ 2026-10-10 起这里还负责记「符合条件的声骸」（见 :meth:`_record_qualifying`），
        用的是同一个"按声骸结算"的时机 —— 理由完全一样。
        """
        if kept and self._perfect_seen and self.judge_config.enable_max_roll_lock:
            self.perfect_echoes += 1
            self.info_set("满属性声骸数量", self.perfect_echoes)
        #: ★ 「符合条件的声骸」—— 上锁的那一刻结算（弃置的不算）
        #:
        #: ⚠⚠ ``_qualifying_now`` 要**先记下来再清**：清完再交给
        #: :meth:`_auto_stop_if_needed` 的话它永远读到 False（自动停止彻底失效）。
        #: 我第一版就是这个顺序 bug —— 靠"两个方法各自读一个字段"很难看出来，
        #: 所以这里改成**显式传参**，让依赖关系写在调用处。
        hit = bool(kept and self._qualifying_now)
        if hit:
            self._record_qualifying(self._last_present)
        self._perfect_seen = False
        self._qualifying_now = False
        return hit

    # ok-ww 的两个收尾动作各对应"一个声骸处理完" → 在这两处结算
    def lock_and_esc(self):
        super().lock_and_esc()
        #: ★ 顺序要紧：先结算（拿到"是不是符合条件"），再决定要不要自动暂停
        hit = self._finalize_echo(kept=True)
        #: ★★★ 强化成功后：**只记名字**进已处理集合，不碰游戏界面。
        #:
        #: ## 为什么要记（用户 2026-10-28）
        #:
        #: > 就是要做成一个集合记住这个声骸已处理，
        #: > 然后下次遇到同名的未强化的，就跳过
        #:
        #: 用户的声骸**全是锁定的**（他手动锁的"要强化的"那批），
        #: 而 ok-ww 的 ``lock_and_esc`` 语义是「确保锁定」（已锁就什么都不做）
        #: → 强化完**还是已锁定** → 下一轮筛「已锁定」又筛出它。
        #:
        #: 所以要靠这个集合记住"这个名字处理过了"，
        #: 下次 ``select_0_level_echo`` 遇到同名的就**鼠标点下一个跳过**。
        #:
        #: ## ⚠⚠ 绝不按 C 解锁（2026-10-29 用户制止）
        #:
        #:     > 不要再按C解锁，这个操作很危险，我说的跳过实现是鼠标点到下一个声骸
        #:
        #: 按 C 是**切换**键 —— 万一那一刻光标已经不在这个声骸上
        #: （界面刷新、列表重排、堆叠重分类），解锁的就会是**别的声骸**：
        #: 一个已经锁好的好声骸被变成「未标记」，用户根本发现不了。
        #:
        #: 所以整套「解锁 → 全部跑完再锁回」（原 relock.py）**已彻底删除**。
        #: 现在只做纯内存记录，**零风险、不碰锁定状态**。
        #:
        #: ⚠ 代价：这些声骸会**留在「已锁定」列表里**，每次跑都会重新
        #: 遇到一次、再跳过一次（多花一次 OCR + 一次点击，约 1 秒）。
        #: 但比"锁错声骸"安全得多 —— 用户明确选了这个权衡。
        if hit:
            name = self._read_current_name()
            self._note_handled_echo(name)
            #: ★ 2026-10-29 成套声骸（43311 / 44111）：
            #: 强化成功一个就更新该 Cost 档的"凑够了几种"，
            #: 够了后续同档的声骸会被 ``_skip_reason`` 跳过。
            self._mark_cost_progress(name)
        #: ★ 2026-10-30 真强化完一个 → 把"连续跳过"计数清零。
        #: 见 ``run`` 里的 ``MAX_CONSECUTIVE_SKIPS``（防 OCR 坏掉时死循环）。
        self._consecutive_skips = 0
        self._auto_stop_if_needed(hit)
        self._aim_at_next_unenhanced()

    def _auto_stop_if_needed(self, qualifying: bool) -> bool:
        """★ 出了符合条件的声骸 → 按模式收尾。

        :param qualifying: 刚处理完那个声骸是不是**真正符合条件**
            （由 :meth:_finalize_echo 判定并传来）
        :return: 是否真的做了收尾动作

        ## ⚠⚠ 任务流程里**不结束整个步骤**（用户 2026-10-29 澄清）

        用户原话：

        > 在任务里不成套时自动停止的效果就是跳过同名同类型声骸，
        > 然后成套里也是跳过同名同类型声骸，
        > 但是还要判断同类型声骸数量是否足够，足够了就跳过同类型声骸

        也就是说**「自动停止」在任务里的语义 = 跳过同名同类型声骸**，
        而那个跳过动作本来就由 `_handled_echoes` 集合在做
        （见 `lock_and_esc` 里那个 `_note_handled_echo`）——
        **跟这个开关无关，一直在跑**。

        所以任务流程里这个方法**什么都不做**：
          * 不 `pause()` —— 会卡死流程（`FlowRunThread` 同步等 run 返回）
          * 不 `stop_task()` —— 那是结束整个步骤，用户说从来没这个意思

        强化好一个之后继续强化下一个，直到没有可强化的为止。

        ## 工具页单独跑时保留 `pause()`

        工具页那个「出现符合条件的声骸就自动停止」复选框是**给人盯屏幕
        用**的：猜着看强化、出了好东西想马上停下来验货。
        那条路没有流程等它，`pause()` 正好。

        ## 历史（踩过的坑，别再犯）

        2026-10-29 我一度把任务里的行为改成 `stop_task()`
        （结束本步骤，流程走下一步）—— 那是我自己臆想的语义，
        用户从没这么要求过。现在改回什么都不做。
        """
        if not getattr(self.judge_config, "enable_auto_stop", False):
            return False
        if not qualifying:
            return False

        #: 记一笔统计（报告和历史看得到有几个符合条件的）
        self.auto_stop_count += 1
        stats_text = "、".join(str(s) for s in self._last_present) or "无"
        summary = (f"出现符合条件的声骸（第 {self.info_get('成功声骸数量', 0)} 个）："
                   f"{stats_text}")
        self.info_set("自动停止原因", summary)

        #: ★ 任务流程里：**只记录，不做任何收尾动作**
        if getattr(self, FLOW_MODE_FLAG, False):
            self.log_info(
                f"★ {summary} —— 继续强化下一个（任务流程里不中断）",
                notify=False)
            return False

        #: 工具页单独跑：暂停（原行为，可点「继续」）
        self.log_info(f"★ {summary} —— 已暂停任务，请回来确认", notify=True)
        try:
            self.pause()
            self.info_set("已自动停止", True)
        except Exception as exc:  # noqa: BLE001 - 暂停失败不该把任务搞崩
            self.log_error(f"自动暂停失败：{type(exc).__name__}: {exc}")
            return False
        return True

    def select_0_level_echo(self):
        """★ 覆盖 ok-ww 的"选下一个未强化声骸"，顺手跳过**已处理过的名字**。

        ## 用户 2026-10-28

        > 就是要做成一个集合记住这个声骸已处理，
        > 然后下次遇到同名的未强化的，直接C解锁改为未标记

        ## 为什么改这里

        ok-ww 的 ``run()`` 每轮开头就调这个方法选目标::

            while True:
                if not self.select_0_level_echo():    # ← 这里
                    return                            # 没得强化了 → 收工
                ...强化...

        所以在**选中目标之后、开始强化之前**插一刀：
        如果这个名字在 ``_handled_echoes`` 里 → 说明同种已经处理过了
        → **不强化，按 C 解锁**（变「未标记」，下一轮它就不在「已锁定」列表里）
        → 然后继续选下一个。

        ## 为什么比"扫 18 格"好

        扫 18 格要 11 秒/屏，而且每次强化成功都要扫。这个方法：
          * **零额外扫描** —— 本来就是每轮必经的一步
          * **天然跨屏** —— ok-ww 自己会滚动列表找 0 级声骸，
            不管同名的在第几屏都能碰到

        ## ⚠ 唯一代价

        ``_read_current_name()`` 每次多一次 OCR（约 0.1~0.3 秒）。
        只在 ``_handled_echoes`` 非空时才做 —— 第一次强化前完全零开销。
        """
        found = super().select_0_level_echo()
        #: ★ ``super()`` 一定把光标点回**第 0 格**（它开头就是
        #: ``self.click(0.13, 0.21)``），所以此刻"当前格"= (0, 0)。
        self._cursor_slot = (0, 0)
        self._last_aimed_slot = None
        #: ★ 2026-10-30：光标所在格读到的名字（由 `_aim_at_next_unenhanced`
        #: 在等面板刷新后写入）。用来核对读数是否滞后于光标。
        #:
        #: ⚠⚠ **不能在这里清成空串** —— 清了之后 `select` 里那个
        #: 「cursor_name != name → 面板滞后」检测永远拿不到基准值，
        #: 等于那道检查不存在（2026-10-30 排查时发现：
        #: 加了检测却一次都没触发，就是因为这里把它清空了）。
        #: 现在改成**读一次真实名字**作为基准。
        self._entry_checked = False
        #: ★★ 2026-10-30 诊断：这一轮到底读到了什么名字。
        #:
        #: 加这行是因为用户反馈"跳过还是强化那个声骸"——
        #: 必须有日志能看出：**跳过之后重开时，读到的名字对不对**。
        #: 只在有已处理记录时打，避免刷屏。
        _handled = getattr(self, "_handled_echoes", None) or set()
        if _handled:
            try:
                _probe = self._read_current_name()
                #: ★ 记下第 0 格读到什么，作为后续"面板是否滞后"的基准
                if _probe:
                    self._cursor_name = _probe
                self.log_info(
                    f"[跳过诊断] 第0格读到={_probe!r}  "
                    f"已处理={sorted(_handled)[:6]}")
            except Exception:  # noqa: BLE001 - 诊断失败不该影响主流程
                pass
        else:
            #: 没有已处理记录时不打日志，但也要个基准值
            try:
                self._cursor_name = self._read_current_name() or ""
            except Exception:  # noqa: BLE001
                self._cursor_name = ""
        if not found:
            return found
        #: ★★ 2026-10-30 **核心修复**：`super()` 会点**列表第一格**，
        #: 而那个格子可能正是"刚被跳过的声骸"（它还在列表里、还是 0 级）。
        #:
        #: 于是变成这样：
        #:     run() 重开 → select → 点第一格 → 是它
        #:       → 判到该跳过 → 点下一个（还是从第一格扫）→ 又点回它
        #:       → **死循环，永远强化不了新声骸**
        #:
        #: 用户的直觉（"跳过还是强化第一个声骸"）完全正确。
        #:
        #: 修法：``super()`` 点完之后**再判一次**，该跳就往下挪，
        #: 直到挪到一个**真正可以强化**的声骸为止。
        #: 这段逻辑和下面的 "循环跳过不该强化的" 是同一件事，
        #: 所以不用单独写 —— 但要把"已跳过"记进排除集，
        #: 免得在同一轮里反复点同一个格子。
        #: 既没有"已处理"记录、也没有白名单
        #: → 不用判，直接走原逻辑（零开销）
        if not getattr(self, "_handled_echoes", None) \
                and not getattr(self, "_allowed_echoes", None):
            return found

        #: 循环跳过"不该强化"的声骸。两种跳过理由：
        #:
        #:   ① **同种已处理过**（``_handled_echoes``）—— 3C 那种一个名字 2 个副本
        #:   ② **不在配置勾选清单里**（``_allowed_echoes``）—— 如「融躯战士」
        #:
        #: 用户 2026-10-29 的截图原话：::
        #:
        #:     这个强化好了，下次强化右边那个，
        #:     右边那个不是同名的就强化「配置里没勾选的声骸，遇到就跳过」
        #:
        #: ## ⚠⚠ 跳过 = **鼠标点下一个**，绝不按 C 解锁
        #:
        #: 用户 2026-10-29 明确制止了按 C 的做法：
        #:
        #:     > 不要再按C解锁，这个操作很危险，我说的跳过实现是鼠标点到下一个声骸
        #:
        #: 按 C 是**切换**键：万一那一刻光标已经不在这个声骸上（界面刷新、
        #: 列表重排），解锁的就会是**别的声骸** —— 把一个已经锁好的
        #: 好声骸变成「未标记」，用户根本发现不了，下次筛选还会漏掉它。
        #:
        #: 所以现在改成：``_aim_at_next_unenhanced()`` —— 用的是用户
        #: 自己在 2026-10-02 确认过的做法（"滚动和方向键都不能移动光标，
        #: **只能鼠标点击**"）：扫一遍 18 格、点第一个未强化的。
        #:
        #: ## 为什么不担心"死循环"
        #:
        #: ``_aim_at_next_unenhanced`` 找的是**层叠图标**（= 0 级未强化），
        #: 它不关心锁没锁。如果跳过的那个声骸还是 0 级，下次扫描
        #: **可能又点回它** → 用 ``_skip_seen`` 记下本轮已经跳过的
        #: (row, col)，避免来回点同一个。
        #:
        #: ⚠ ``SKIP_HANDLED_MAX`` 是**模块级常量**，不是类属性 ——
        #: 写成 ``self.SKIP_HANDLED_MAX`` 会在运行时抛
        #: ``AttributeError: 'MyToolsEnhanceEchoTask' object has no attribute``
        #: （2026-10-28 实机就是这么崩的：强化成功后想跳过同种声骸，
        #: 结果整轮任务直接异常结束）。
        #:
        #: ★ ``skipped`` 必须**累加**：只排"当前光标"会来回打转 —— 见
        #: ``_aim_at_next_unenhanced`` 开头那段 2026-10-30 的说明。
        skipped: set[tuple[int, int]] = set()
        for _attempt in range(SKIP_HANDLED_MAX * 4):
            name = self._read_current_name()
            #: ★★★ 2026-10-30 工具页「跳过」按钮 —— 在**选目标**这关也查一次。
            #:
            #: 覆盖"按跳过时正好在两轮之间"的情况：那时强化循环里的
            #: 两个检查点（``check_echo_stats`` / ``find_add_mat``）
            #: 都还没被调到，请求会一直躺着没人处理。
            if self._consume_skip_request():
                self.log_info("【跳过】请求在手 → 跳过当前，点下一个",
                              notify=True)
                cursor = getattr(self, "_cursor_slot", None)
                if cursor is not None:
                    skipped.add(cursor)
                if not self._aim_at_next_unenhanced(exclude=skipped):
                    self.log_info("【跳过】找不到下一个未强化声骸 → 收工")
                    return False
                found = True
                continue
            #: ★★ 2026-10-30 **核对光标与名字是否对得上**。
            #:
            #: ``_aim_at_next_unenhanced`` 点完新格子后会重读名字等面板刷新，
            #: 并把结果存进 ``_cursor_name``。如果这里读到的名字和它不一样，
            #: 说明右侧面板**还在滞后**（读数跟不上光标）——这种情况下
            #: 判定结果不可信，不能拿它决定"能不能强化"。
            #:
            #: 实机症状（用户 2026-10-30）：名字永远落后一格，
            #: 于是跳过判在错的格子上 → 该跳的没跳、不该强的强了。
            cursor_name = getattr(self, "_cursor_name", "")
            if cursor_name and name and cursor_name != name:
                self.log_info(
                    f"⚠ 光标在第 {getattr(self, '_cursor_slot', ('?', '?'))} 格"
                    f"（{cursor_name!r}），但读到 {name!r} —— 面板滞后，重读一次")
                self.sleep(0.4)
                name = self._read_current_name()
            #: ★★★ 2026-10-30 **关键**：配了白名单 / 成套结构却**读不到名字**时，
            #: 绝不能当成"该强化"直接返回 —— 那正是用户报的两个 bug 的直接成因：
            #:
            #:     配置里删了「融躯战士」
            #:       → read_echo_name 读到套装名/空 → 带白名单后返回 ""
            #:       → _skip_reason("") 返回 ""（= 不跳过）
            #:       → **直接强化它**（用户："怎么还是要强化他"）
            #:
            #: 读不到名字 = 无法确认它是否该强化 → **宁可不强化，跳过它**。
            if not name:
                if getattr(self, "_allowed_echoes", None) \
                        or getattr(self, "_set_plan", None):
                    #: ★★★ 2026-10-30 **先判黑屏**（这是死循环的真凶）。
                    #:
                    #: 实机失败截图 ``15-35-56.639_…_original.png``
                    #: **整张全黑** —— 游戏没渲染时 OCR 必然读不到。
                    #: 这时如果判"跳过"，就会
                    #: 点培养 → 黑 → 跳过 → 点培养 → 黑 → 跳过，
                    #: 用户看到的就是"在第一个和第二个声骸之间徘徊"。
                    #:
                    #: 黑屏是环境问题，应该**等**，不是跳。
                    _blank = False
                    try:
                        from . import same_echo as _se3  # noqa: PLC0415

                        _blank = _se3.screen_looks_blank(self)
                    except Exception:  # noqa: BLE001
                        pass
                    if _blank:
                        self.log_info(
                            "⚠ 画面黑屏且读不到声骸名 → 等 2.5 秒再看，"
                            "**不往下点下一个**（避免死循环）")
                        self.sleep(2.5)
                        name = self._read_current_name()
                        if not name:
                            #: 还是读不到 → 照常继续（让 ok-ww 自己去试），
                            #: 绝不在这里 Esc/点下一个打转。
                            self.log_info(
                                "⚠ 仍然读不到（画面依然黑）→ 不再跳过，"
                                "交给 ok-ww 继续")
                            return found
                    else:
                        self.log_info(
                            "⚠ 读不到当前声骸名（无法核对是否在配置里）"
                            "→ 跳过它，不强化")
                        cursor = getattr(self, "_cursor_slot", None)
                        if cursor is not None:
                            skipped.add(cursor)
                        if not self._aim_at_next_unenhanced(exclude=skipped):
                            self.log_info("读不到名字且没有下一个未强化声骸 → 收工")
                            return False
                        found = True
                        continue
                return found
            reason = self._skip_reason(name)
            if not reason:
                return found
            #: 不该强化 → **点下一个未强化的声骸**（不按 C！）
            self.log_info(
                f"「{name or '（读不到名字）'}」{reason} → 点下一个声骸，跳过它")
            #: ★★ 2026-10-30 用户要的「成套时的跳过」：
            #:
            #:     > 这个跳过应该加上成套（这里默认测试43311）的时候的跳过功能，
            #:     > 比如我跳过了2个1C，下一步应该找3C了
            #:
            #: 也就是：**手动跳过的声骸也算"这一档凑够了"**——
            #: 用户跳过一个 1C，等于告诉他"这个 1C 我不想要了"，
            #: 那 43311 要的 1C×2 就该往前推进一格。
            #: 所以这里也调 ``_mark_cost_progress``（和强化成功一样的记账）。
            if name:
                self._note_handled_echo(name)
                self._mark_cost_progress(name)
                self._force_satisfy_cost(name)
            #: 记下"这个格子本轮已经跳过了"，别再来回点它
            cursor = getattr(self, "_cursor_slot", None)
            if cursor is not None:
                skipped.add(cursor)
            if not self._aim_at_next_unenhanced(exclude=skipped):
                self.log_info("跳过后找不到下一个未强化声骸 → 交给 ok-ww 收工")
                return False
            found = True
        return found

    def _force_satisfy_cost(self, name: str) -> None:
        """★ 手动跳过的声骸 → 把它所在的 Cost 档**也算凑够一种**。

        ## 用户 2026-10-30

        > 这个跳过应该加上成套（这里默认测试43311）的时候的跳过功能，
        > 比如我跳过了2个1C，下一步应该找3C了

        ## 为什么单独一个方法

        ``_mark_cost_progress`` 是按 ``_handled_echoes`` 里"属于这一档的
        名字数"来算的，跳过一个就自动算了 —— 但它**只在 count >= need
        时才把该档标记为 done**。

        手动跳过时用户是明确说"不要这个"，所以**只要这一档已经
        跳过/处理了 need 个，就该立刻标记 done**，后面同档的全跳过。

        这里补的就是"跳过的也算数"这一步（和 ``_mark_cost_progress``
        配合，不重复记账）。
        """
        if not getattr(self, "_set_plan", None):
            return
        cost = self._cost_of_echo(name)
        need = int((self._set_plan or {}).get(cost) or 0)
        if not cost or not need:
            return
        done = 0
        for handled in (getattr(self, "_handled_echoes", None) or set()):
            if int((getattr(self, "_echo_cost", None) or {}).get(handled, 0)) == cost:
                done += 1
        if done >= need:
            self._set_done.add(cost)
            self.log_info(
                f"★ [{cost}C] 跳过/处理后已凑够 {done}/{need} 种"
                f"（套装结构 {self._set_plan_text()}）→ 该档剩余的声骸全部跳过，"
                f"接下来只强化其他档", notify=True)

    def _consume_skip_request(self) -> bool:
        """工具页「跳过」按钮的请求 → 取走并返回是否要跳过。

        ## 用户 2026-10-30

        > 这个跳过可以加到声骸自动强化工具这里

        语义（同一轮确认）：

        > 跳过相当与他已经强化好了，需要跳过同类型同名声骸

        ## 通路

        工具页按钮 → ``OkwwHost.request_skip_current()`` 置一次性标志
        → 任务在检查点（``check_echo_stats`` / ``find_add_mat``）取走
        → 记进 ``_handled_echoes``（之后同名的都跳过）
          + ``_mark_cost_progress`` / ``_force_satisfy_cost``
          （成套时计入该档种类数）。

        ## 为什么用"取走"（一次性）

        标志取走即清，所以按一次只跳一个声骸。
        不清的话会一直跳，等于把整个任务废掉。

        ## 失败要吞掉

        宿主没起 / 没这个方法 → 当成"没有请求"。
        绝不能因为按钮通路出问题把强化任务搞崩。
        """
        try:
            from ..auto_combat import okww_boot  # noqa: PLC0415

            host = okww_boot.get_host()
            if not getattr(host, "_skip_current_requested", False):
                return False
            #: 取走（在宿主的锁里改）
            with host._lock:  # noqa: SLF001 - 同一进程内的协调，只能碰这把锁
                if not host._skip_current_requested:
                    return False
                host._skip_current_requested = False
            return True
        except Exception:  # noqa: BLE001 - 按钮通路坏了不该影响强化
            return False

    def _skip_reason(self, name: str) -> str:
        """这个名字**为什么该跳过**？返回给日志看的原因；空串 = 不该跳过。

        ## 两种跳过理由（用户 2026-10-29）

        ============  =====================================================
        同种已处理过   3C 一个名字有 2 个副本（攻击%/属性伤害% 各一个），
                      强化好一个 → 另一个也不用强化了
        不在配置清单   配置里没勾这个声骸（比如「融躯战士」）→ 整类跳过
        ============  =====================================================

        ## ⚠ 满属性除外

        用户特别说明「（就是符合条件的，只是满属性的除外）」。

        满属性声骸**一律保留**（``enable_max_roll_lock`` 打开时，
        出了满值词条就强化到满级并上锁，见 ``check_echo_stats``）——
        那种是**宝贝**，不能因为"同种已处理过"就解锁丢掉。

        所以这里先判满属性：如果当前这个声骸**已经出过满值词条**
        （``_perfect_seen``），就不跳过，让它走完正常流程被上锁。
        """
        #: 满属性 → 永远不跳过（用户要求："满属性的除外"）
        if getattr(self, "_perfect_seen", False):
            return ""

        #: ① 不在配置勾选清单里
        allowed = getattr(self, "_allowed_echoes", None)
        if allowed:
            try:
                from . import same_echo  # noqa: PLC0415

                key = same_echo.normalize_echo_name(name)
            except Exception:  # noqa: BLE001
                key = ""
            if key and key not in allowed:
                return "配置里没勾选这个声骸"

        #: ② 该 Cost 档已经凑够种类了（成套模式）
        #:
        #: 用户 2026-10-29：43311 的 1C 要 2 种不同名字，凑齐后
        #: **剩下的 1C 全部跳过**（哪怕还有别的 1C 声骸）。
        if self._is_cost_satisfied(name):
            cost = self._cost_of_echo(name)
            return f"{cost}C 已凑够种类（套装结构 {self._set_plan_text()}）"

        #: ③ 同种已处理过
        if self._is_handled_echo(name):
            return "同种已处理过"
        return ""

    # --------------------------------------------------- 成套声骸（43311 等）
    def _build_cost_index(self, picks_by_cost: dict) -> None:
        """从配置的 ``{Cost: [声骸名, ...]}`` 建「名字 → Cost」反查表。

        :param picks_by_cost: ``{4: ['共鸣回响…'], 3: ['解形煞', ...], 1: [...]}``

        ⚠ 只建索引，**不动白名单** —— 白名单是 ``_allowed_echoes``
        （扁平的名字集合），两者职责不同。
        """
        try:
            from . import same_echo  # noqa: PLC0415

            normalize = same_echo.normalize_echo_name
        except Exception:  # noqa: BLE001
            normalize = lambda s: str(s or "").strip()  # noqa: E731

        index: dict[str, int] = {}
        for cost, names in (picks_by_cost or {}).items():
            try:
                c = int(cost)
            except (TypeError, ValueError):
                continue
            for name in names or ():
                key = normalize(str(name or ""))
                if key:
                    index[key] = c
        self._echo_cost = index
        if index:
            self.log_info(
                "声骸 Cost 索引：" + "、".join(
                    f"{c}C×{sum(1 for v in index.values() if v == c)}"
                    for c in sorted(set(index.values()), reverse=True)))

    def _cost_of_echo(self, name: str) -> int:
        """这个名字是几 C？查不到返回 0（= 不确定）。"""
        try:
            from . import same_echo  # noqa: PLC0415

            key = same_echo.normalize_echo_name(name)
        except Exception:  # noqa: BLE001
            key = str(name or "").strip()
        return int((getattr(self, "_echo_cost", None) or {}).get(key, 0) or 0)

    def _set_plan_text(self) -> str:
        """套装结构的可读文本（给日志）。"""
        plan = getattr(self, "_set_plan", None) or {}
        if not plan:
            return "不成套"
        return " ".join(f"{c}C×{n}" for c, n in sorted(plan.items(), reverse=True))

    def _is_cost_satisfied(self, name: str) -> bool:
        """这个声骸所在的 Cost 档**已经凑够种类**了吗。

        不成套模式 → 永远 ``False``（不做这套判断）。

        ``_set_done`` 里记的是"哪几档已达标"，由 :meth:`_mark_cost_progress`
        在每次强化成功后更新。
        """
        plan = getattr(self, "_set_plan", None) or {}
        if not plan:
            return False
        cost = self._cost_of_echo(name)
        if not cost:
            return False
        return cost in (getattr(self, "_set_done", None) or set())

    def _mark_cost_progress(self, name: str) -> None:
        """强化成功一个声骸 → 更新该 Cost 档的种类计数，够了就标记达标。

        :param name: 刚强化成功那个声骸的名字

        ## 计数规则

        **按种类算**（用户 2026-10-29 确认 B）：同一名字的多个副本只算 1 种
        —— 名字本来就在 ``_handled_echoes`` 里，所以直接用那个集合去重。
        """
        plan = getattr(self, "_set_plan", None) or {}
        if not plan:
            return
        cost = self._cost_of_echo(name)
        need = int(plan.get(cost) or 0)
        if not cost or not need:
            return
        #: 已处理的名字里，属于这一档的有几个（= 凑了几种）
        done = 0
        for handled in (getattr(self, "_handled_echoes", None) or set()):
            if int((getattr(self, "_echo_cost", None) or {}).get(handled, 0)) == cost:
                done += 1
        self.log_info(f"[{cost}C] 已凑 {done}/{need} 种")
        if done >= need:
            done_set = getattr(self, "_set_done", None)
            if done_set is None:
                done_set = self._set_done = set()
            if cost not in done_set:
                done_set.add(cost)
                self.log_info(
                    f"★ {cost}C 已凑够 {need} 种（套装结构 {self._set_plan_text()}）"
                    f"→ 该档剩余的声骸全部跳过")

    def _read_current_name(self) -> str:
        """读当前选中声骸的名字（右侧详情面板）。"""
        try:
            from . import same_echo  # noqa: PLC0415

            return same_echo.read_echo_name(
                    self, known_names=getattr(self, "_allowed_echoes", None))
        except Exception:  # noqa: BLE001 - 读不到当没有
            return ""

    def _is_handled_echo(self, name: str) -> bool:
        """这个名字是不是**已经处理过**（强化成功过同种）。"""
        try:
            from . import same_echo  # noqa: PLC0415

            key = same_echo.normalize_echo_name(name)
        except Exception:  # noqa: BLE001
            return False
        return bool(key) and key in self._handled_echoes

    def _note_handled_echo(self, name: str) -> None:
        """记下"这个名字处理过了"（强化成功后调）。"""
        try:
            from . import same_echo  # noqa: PLC0415

            key = same_echo.normalize_echo_name(name)
        except Exception:  # noqa: BLE001
            return
        if key:
            self._handled_echoes.add(key)



    # ------------------------------------------------- 3.7 声骸堆叠的修正
    def _aim_at_next_unenhanced(self, exclude=None) -> bool:
        """★ 把光标**移回一个未强化的声骸** —— 修 3.7 声骸堆叠导致的卡死。

        ## 问题（用户 2026-10-02 报）

        "3.7 更新后，更新了声骸堆叠，导致强化好了一个声骸后，会自动跳到
        强化好的声骸位置，从而不能继续强化到其他声骸了"

        ## 根因

        ok-ww 的 ``run()`` **从不主动选下一个声骸** —— 它假设
        "强化完 ESC 回列表，光标还在原位"。**堆叠打破了这个假设**：
        强化好的被归类重排、光标被带过去 → 下一次循环 ``is_0_level()``
        读到"不是 0 级" → **直接收工**（不是"不能强化"，是它以为干完了）。

        ## 修法

        用户实测"滚动和方向键都不能移动光标，**只能鼠标点击**"
        → 所以在两个收尾动作之后，**扫一遍 18 格、点第一个未强化的**。

        判定用 :func:`echo_grid.find_next_unenhanced`（找层叠图标）。
        找不到（一屏都没有 0 级了）就什么都不做，让 ok-ww 正常收工。

        :param exclude: 要**跳过**的格子 ``{(row, col), ...}``。
            2026-10-29 加：「跳过不该强化的声骸」时用，避免
            点回刚才那个（它还是 0 级，不排除就会来回点同一个）。

            2026-10-30 修：**当前光标所在的那个格子会自动并进来**。
            原来只靠调用方传，而 ``super().select_0_level_echo()``
            会先把光标点回**第 0 格** —— 于是这里又从第 0 格扫，
            返回的还是它 → **"跳过"跳到自己身上，永远前进不了**
            （用户："跳过还是强化第一个声骸"）。

        :return: 是否成功把光标移到了一个未强化的声骸上
        """
        #: ★ 把"当前光标所在格"也排除掉 —— 见上面 2026-10-30 那条注释。
        #:
        #: ⚠⚠ **调用方还要累积传 ``exclude``**（本次已跳过的所有格子）。
        #: 只排"当前光标"是不够的 —— 点下一个之后光标变成新格子，
        #: 再找时上一个又满足"未强化"了，来回打转：
        #:
        #:     点 A → 排除 A → 找到 B
        #:     点 B → 排除 B（但 A 又可选了）→ 找到 A
        #:     → **循环，永远前进不了**（2026-10-30 实测：跳 4 次回到原点）
        skip = set(exclude or ())
        cursor = getattr(self, "_cursor_slot", None)
        if cursor is not None:
            skip.add(cursor)
        try:
            found = echo_grid.find_next_unenhanced(self, exclude=skip)
        except TypeError:
            #: 兼容老签名（没 exclude 参数）—— 只是少一层保护，不该崩
            try:
                found = echo_grid.find_next_unenhanced(self)
            except Exception as exc:          # noqa: BLE001
                self.log_debug(f"扫描未强化声骸失败：{type(exc).__name__}: {exc}")
                return False
        except Exception as exc:              # noqa: BLE001 - 定位失败不该中断任务
            self.log_debug(f"扫描未强化声骸失败：{type(exc).__name__}: {exc}")
            return False
        if not found:
            self.log_info("一屏内没有未强化的声骸了 —— 交给 ok-ww 收工")
            return False

        row, col = found
        rx, ry = echo_grid.card_center_relative(row, col)
        # ⚠ 索引从 0 起、序数从 1 起 —— 报给用户时要 +1
        self.log_info(f"声骸堆叠修正：点第 {row + 1} 排第 {col + 1} 个"
                      f"（未强化）→ 把光标移过去")
        self.click_relative(rx, ry)
        #: ★ 光标移到新格子了 —— 更新"当前格"记录。
        #: 下一次调用时它会自动被排除，否则"跳过"会一直点回同一格
        #: （见方法开头 2026-10-30 的说明）。
        self._cursor_slot = (row, col)
        #: ★★ 2026-10-30 **必须等右侧详情面板刷新完**（这是跳转失效的真因）。
        #:
        #: ## 实机日志（用户 2026-10-30 13:59:45）
        #:
        #:     13:59:45 「融躯战士」同种已处理过 → 点下一个
        #:     13:59:45 点第 1 排第 2 个（未强化）→ 把光标移过去
        #:     13:59:46 left_click 培养 (1683, 988)      ← 直接进强化界面了！
        #:
        #: 表面上"点完第 2 个就退出了循环、以为它可以强化"。但真相是：
        #:
        #:     点完第 2 个 → sleep(0.3) → 循环下一轮读名字
        #:     → **右侧面板还没刷新，读到的还是第 1 个「融躯战士」**
        #:     → `_skip_reason('融躯战士')` = 已处理 → 又跳一次
        #:     → 但 `_aim_at_next_unenhanced` 排除了第 1 格，点第 3 个…
        #:
        #: 也就是说名字读数**永远滞后一格** —— 判定和光标对不上，
        #: 这一整类 bug（跳过无效 / 强化了不该强化的 / 成套凑不齐）
        #: 都是从这来的。
        #:
        #: ## 怎么等
        #:
        #: 拿点击前读到的名字当基准：点完等 0.35 秒，然后重读；
        #: 只要还等于旧名字就再等（最多 6 次 ≈ 2 秒）。
        #: 读到不同的名字 = 面板刷新好了，循环下一轮拿到的就是准的。
        #:
        #: ⚠ 读不到名字（空串）不算"变了"—— 空串说明面板正在重绘，
        #: 继续等；等满 6 次还没变化就放弃（不能无限等，那会卡死任务）。
        prev_name = getattr(self, "_cursor_name", "")
        for _wait in range(6):
            self.sleep(0.35)
            now_name = self._read_current_name()
            if now_name and now_name != prev_name:
                self._cursor_name = now_name
                return True
        #: 等满还没变 → 用最后一次读到的（可能是空串），交给上层兜底
        self._cursor_name = self._read_current_name() or ""
        return True

    # --------------------------------------------------- 自动放入设置（阶段放入）
    def _ensure_stage_insert_mode(self) -> bool:
        """确保「自动放入设置 → 放入模式」是**阶段放入**。

        ## 用户 2026-10-28

        > 齿轮是阶段放入和快捷放入，其实现在没有问题，只是不能自动切换成阶段放入

        ## 这两者的区别（用户截图上的官方说明）

        ==========  ==========================================================
        快捷放入     放入所有符合筛选规则的材料，直到达到声骸等级上限
        阶段放入     放入将声骸提升至最近可调谐等级(5/10/15/20/25)的材料
        ==========  ==========================================================

        ok-ww 的强化流程是**按阶段**走的（放入 → 强化并调谐 → 判词条），
        所以必须用「阶段放入」。用「快捷放入」会一次性把材料填到上限，
        +5/+10/+15 那些判定点全被跳过，而且材料花掉不可撤销。

        ## 怎么切

        1. 点材料区那个**齿轮 ⚙** → 弹出「自动放入设置」
        2. 点「阶段放入」那一格
        3. 点「确认」

        ## ⚠ 全部靠 OCR 定位，不写死坐标

        「快捷放入」和「阶段放入」在同一行、只差 x 方向约 500 像素，
        点偏了会选成快捷放入 —— 那比不切还糟。所以：
          * 用 ``ocr()`` 拿到「阶段放入」文字的**实际框**再点，不是盲点
          * 点完**验证**：重新读材料区按钮文字，确认变成「阶段放入」
          * 任何一步失败都**不抛异常**（让 ok-ww 原来的报错去说），
            只记日志 —— 免得把「设置没切成」变成「任务炸了」

        ## 返回

        成功切到（或本来就是）阶段放入 → ``True``；
        没切成功 → ``False``（调用方不处理，继续跑，让 ok-ww 报错）。
        """
        #: ⚠⚠ 2026-10-28 实机翻车：这里原来只判 ``find_echo_enhance()``，
        #: 而它找的是**「培养」按钮** —— 背包**列表页**上也有那个按钮！
        #:
        #: 于是任务刚启动（还停在列表页、强化界面根本没打开）时，
        #: 这个检查**通过了** → 去点 (639,673) 那片区域的"齿轮" →
        #: 实际点到了别的东西 → 界面被弄乱 → ok-ww 的
        #: ``select_0_level_echo()`` 找不到 0 级声骸 → 收工 →
        #: 最终报「本次没有判定任何声骸」（截图里那句）。
        #:
        #: 日志证据::
        #:
        #:     19:24:56 当前不是「阶段放入」模式 → 尝试自动切换
        #:     19:24:57 left_click 0.315 0.6 (639, 673)
        #:     19:24:58 TaskDisabledException
        #:
        #: ## 现在的三重确认
        #:
        #: 只用**强化界面独有**的标志，缺一不可：
        #:   1. 「培养」按钮在（``find_echo_enhance``）
        #:   2. **「强化并调谐」在** ← 这个只有强化界面有，列表页没有
        #:   3. 材料区那一片能 OCR 到东西（说明材料面板已经渲染出来）
        #:
        #: 任何一条不满足 → 直接放弃，**绝不点任何坐标**。
        try:
            if not self.find_echo_enhance():
                self.log_debug("不在强化界面，跳过「阶段放入」检查")
                return False
            #: ★ 关键：列表页没有「强化并调谐」，有它才是真·强化界面
            if not self.ocr(0.10, 0.86, 0.35, 0.98, match=['强化并调谐']):
                self.log_debug("看不到「强化并调谐」→ 还没进强化界面，"
                               "跳过「阶段放入」检查（不乱点）")
                return False
        except Exception:  # noqa: BLE001 - 探测失败就当不在
            return False

        #: 已经是阶段放入 → 什么都不做（大多数情况走这条）
        #:
        #: ⚠⚠ **必须调 super()，不能调 self.find_add_mat()** ——
        #: 后者被我覆盖了，里面会反过来调这个方法 → **无限递归**。
        #: 而且那样 `_stage_insert_checked` 刚置 True 就被这里打断，
        #: 逻辑也乱。
        try:
            if super().find_add_mat():
                return True
        except Exception:  # noqa: BLE001 - 探不到就往下走
            pass

        #: 材料已放进去了（按钮变成「清 除」）→ 那也不是模式问题，别乱动
        try:
            if self._has_material_reset_button():
                self.log_info("材料槽里有材料，不动「自动放入设置」")
                return False
        except Exception:  # noqa: BLE001
            pass

        self.log_info("当前不是「阶段放入」模式 → 尝试自动切换")

        #: 1. 点齿轮。用 OCR 在材料区找那个齿轮 —— 它是图标不是文字，
        #:    OCR 读不到，所以用一个**很窄的区域**（按钮右侧那一小条）。
        #:
        #:    材料区按钮（截图实测）: x 0.19~0.34, y 0.60~0.64
        #:    齿轮紧跟在它右边      : x 0.315~0.345, y 0.600~0.640
        try:
            self.click_box(self.box_of_screen(0.315, 0.600, 0.350, 0.645),
                           after_sleep=0.8)
        except Exception as exc:  # noqa: BLE001
            self.log_info(f"点齿轮失败（{type(exc).__name__}）→ 放弃自动切换")
            return False

        #: 2. 对话框开了吗？验证方式：找「自动放入设置」标题
        opened = self.wait_ocr(0.05, 0.05, 0.95, 0.20,
                               match=['自动放入设置'], time_out=2)
        if not opened:
            self.log_info("没弹出「自动放入设置」对话框 → 放弃自动切换")
            return False

        #: 3. 点「阶段放入」。**必须用 OCR 拿到的实际框**，不能盲点 ——
        #:    隔壁就是「快捷放入」，点错一次材料就废了。
        stage = self.wait_ocr(0.50, 0.20, 0.92, 0.45,
                              match=['阶段放入'], time_out=2)
        if not stage:
            self.log_info("对话框里找不到「阶段放入」→ 放弃自动切换")
            self._close_auto_insert_dialog()
            return False
        self.log_info("找到「阶段放入」→ 点击")
        self.click(stage, after_sleep=0.5)

        #: 4. 点「确认」保存
        confirm = self.wait_ocr(0.68, 0.82, 0.92, 0.96,
                                match=['确认'], time_out=2)
        if confirm:
            self.click(confirm, after_sleep=0.8)
        else:
            self.log_info("找不到「确认」按钮 → 试着按 Esc 关掉对话框")
            self.send_key('esc', after_sleep=0.5)

        #: 5. 验证：材料区按钮文字应该变成「阶段放入」
        #:
        #: ⚠ 同样必须调 ``super()`` —— ``self.find_add_mat()`` 会回到
        #: 本方法的调用者，无限递归。
        self.sleep(0.5)
        try:
            if super().find_add_mat():
                self.log_info("✔ 已切换到「阶段放入」模式")
                return True
        except Exception:  # noqa: BLE001 - 验不出来就当失败
            pass
        self.log_info(
            "★ 切换后仍读不到「阶段放入」—— 可能点偏了或对话框没保存。"
            "请在游戏里手动打开齿轮 ⚙ → 放入模式选「阶段放入」→ 确认")
        return False

    def _close_auto_insert_dialog(self) -> None:
        """关掉「自动放入设置」对话框（不保存）。"""
        try:
            self.send_key('esc', after_sleep=0.4)
        except Exception:  # noqa: BLE001 - 关不掉也不该抛
            pass

    # ------------------------------------------------------------------ 运行
    def run(self) -> None:
        """ok-ww 的 ``run()`` 原样跑，只是屏蔽它结尾弹截图文件夹那一下。"""
        #: ★★★ 2026-10-30 **铁证日志**：`run()` 一开始就把注入状态打出来。
        #:
        #: 为什么一定要在这里打：`_configure`（tool 侧）**先**把白名单/成套
        #: 注入到任务实例上，然后 ok-ww 才调 `run()`。所以这两行日志的
        #: 先后和内容能直接判定注入有没有生效、有没有被中途清掉：
        #:
        #:     【注入】白名单 6 个 → task#140234…   ← tool.py 打的
        #:     【run 启动】task#140234… 白名单 6 个 / 成套 {4:1,3:2,1:2}
        #:
        #: 如果两个 task# 不一样，说明 ok-ww 重建了实例；
        #: 如果 `run` 这里读到 0 个，说明注入之后被清掉了（那就是真 bug）。
        try:
            self.log_info(
                f"【run 启动】task#{id(self)}  "
                f"白名单={len(getattr(self, '_allowed_echoes', ()))}个  "
                f"成套={dict(getattr(self, '_set_plan', None) or {})}  "
                f"Cost 索引={len(getattr(self, '_echo_cost', None) or {})} 条")
        except Exception:  # noqa: BLE001 - 日志打不出来不该挡住启动
            pass
        # 不指望 default_config 单点生效：configs/<类名>.json 里可能留着旧值，
        # 开着"成功即暂停"会让批量强化表现得像"只跑一个就停"。
        try:
            self.config["Pause after Success"] = False
        except Exception:                     # noqa: BLE001 - 配置只读也不该挡住主流程
            pass
        # 本轮统计清零 —— info 在同一进程内跨次累加，这几个键必须自己重置
        self.checked_echoes = 0
        self.discard_tally = {}
        self.perfect_echoes = 0
        self._perfect_seen = False
        #: ★ 符合条件清单 / 自动停止状态也要清（见各自字段的说明）
        self.qualifying_echoes = []
        self.auto_stop_count = 0
        self._qualifying_now = False
        self._last_present = []
        #: ★★★ 2026-10-28 用户：
        #: > 就是要做成一个集合记住这个声骸已处理，
        #: > 然后下次遇到同名的未强化的，就跳过
        #:
        #: **已处理过的声骸名集合**。一旦某个声骸名强化成功过，
        #: 之后遇到同名的（还是 0 级没强化的）就不用再强化了 ——
        #: 直接按 C 解锁。这样：
        #:   1. 不用反复扫 18 格（扫一次就够，名字记进集合）
        #:   2. 同种声骸**无论在哪一屏**都能处理（每轮选目标时顺手判）
        #:
        #: 存的是 ``same_echo.normalize_echo_name()`` 归一化后的名字。
        self._handled_echoes: set[str] = set()
        #: ★★★ 2026-10-29 用户：
        #: > 配置哪里我不是勾选了声骸吗，可以准确识别出声骸名和声骸类型
        #: > （4C、3C、1C），我想要实现比如强化好了一个 融躯战士 1C
        #: > （就是符合条件的，只是满属性的除外），那么就跳过他
        #:
        #: **允许强化的声骸白名单**（来自「角色声骸筛选配置」里勾选的那些）。
        #:
        #: 空集合 = 不做白名单过滤（工具页单独跑时没有配置，走这条）。
        #: 非空 = 只强化名单里的；名单外的（如「融躯战士」没在配置里勾）
        #: 直接按 C 解锁跳过，**一个判定都不做**。
        #:
        #: 这就是用户图里那句话的意思：::
        #:
        #:     这个强化好了，下次强化右边那个，
        #:     右边那个不是同名的就强化「配置里没勾选的声骸，遇到就跳过」
        #:
        #: 存的是 ``same_echo.normalize_echo_name()`` 归一化后的名字
        #: （和 ``_handled_echoes`` 同一套归一化，比对才一致）。
        #:
        #: ## ⚠⚠⚠ 2026-10-30 **这个字段绝不能在 `run()` 里重置！**
        #:
        #: 这是困扰了一整天的两个 bug（配置里删掉的声骸还被强化、
        #: 跳过 2 个 1C 后还强化 1C）的**总根因**。
        #:
        #: 注入顺序是这样的::
        #:
        #:     OkwwTaskRunner.run()
        #:       └─ host.start_task(configure=self._configure)
        #:            └─ _configure(task) → setattr(task, "_allowed_echoes", 6 个)
        #:     ok-ww 随后调 task.run()
        #:       └─ 原来这里写了 self._allowed_echoes = set()  ← **清零！**
        #:
        #: 于是 `run()` 一开始明明有 6 个，进到 `find_add_mat` 就变成 0 个。
        #: 实机日志铁证（2026-10-30 15:11）::
        #:
        #:     15:11:19 【run 启动】task#… 白名单=6个 成套={4:1,3:2,1:2}
        #:     15:11:21 [fm#1] find_add_mat 被调用：白名单=0个 成套=False
        #:
        #: 这两个方法在**同一个实例**上（task# 一致），2 秒内值全没了，
        #: 只可能是 `run()` 自己清的。
        #:
        #: ## 正确做法
        #:
        #: 这几个字段属于「**由外部注入的配置**」，只该在 `__init__` 里
        #: 给个默认值，之后**由 `_configure` 覆盖**。`run()` 每次重开
        #: （跳过之后会 `continue` 重跑）都**不能**动它们，
        #: 否则第二圈开始就全丢了。
        #:
        #: 默认值已经在 `__init__` 里建好了（见那个「外部注入的配置字段」
        #: 那段注释）。这里**一行都不写** —— 写了就会覆盖注入值。
        #: ★★★ 2026-10-29 用户：
        #: > 任务再增加一个是否成套声骸，如果是再让用户选择是43311,还是44111，
        #: > 根据这个判断，如果强化好了声骸类型，就不再强化该类型，
        #: > 比如强化好了2个1C的，如果还有别的1C那也不再强化了，也就是跳过
        #:
        #: ## 两个字段
        #:
        #: ``_set_plan``       套装结构 → ``{Cost: 需要几种不同名字}``。
        #:                     空 dict = 不成套（不做这套判断）。
        #: ``_set_done``       已经凑够种类的档位（``{4, 3}`` 这种）。
        #:
        #: ## 计数规则（用户 2026-10-29 确认）
        #:
        #: **按种类算，不按件数**：43311 的 ``1C×2`` = 凑齐 2 种
        #: **不同名字**的 1C。强化好「冰盈舞者」的 3 个副本只算 1 种。
        #:
        #: **不指定具体哪几种**：强化好任意 N 种就算该档达标，
        #: 该档剩余的同类声骸全部跳过。
        #:
        #: ## 怎么判断"这个声骸是几 C"
        #:
        #: 不用 OCR 读「COST 3」那行 —— 配置的 ``picks`` 本来就是
        #: ``{Cost: [声骸名, ...]}``，用名字反查即可（零开销，
        #: 见 ``_cost_of_echo``）。
        #:
        #: ⚠⚠ 同上：`_set_plan` / `_echo_cost` 都**不能**在这里重置，
        #: 它们由 `_configure` 注入。只有 `_set_done`（"已达标档位"）
        #: 属于**本轮运行状态**，重开时清空才对（跳过之后要重新累计）。
        #: ★ 注意：`_set_done` 清空是**对的**，但它是"跨重开保留进度"更合适 ——
        #: 因为跳过之后 `run()` 重开，前面凑够的档位不该丢。
        #: 所以这里也不动它（保持 `__init__` 里那份，由 `_force_satisfy_cost`
        #: / `_mark_cost_progress` 累加）。
        #: 名字 → Cost 的反查表（从配置的 picks 建，见 ``_build_cost_index``）
        #: ★ 「阶段放入」自动切换试过了没有（**一次就够，不反复试**）。
        #:
        #: 见 ``find_add_mat`` 里的调用点：每次强化循环都会调 find_add_mat，
        #: 不加这个开关就会每轮都点一次齿轮 ⚙ → 界面全乱。
        self._stage_insert_checked = False
        #: ★ ★ 2026-10-30 「进强化界面后的最后一道核验」做过没有。
        #:
        #: 每进一个**新声骸**都要重新核一次（名字变了），所以这个开关
        #: 在 ``run()`` 每次重开时重置（跳过后会 continue 重跑 run）。
        #: 见 ``find_add_mat`` 里那段「最后一道闸」。
        self._entry_checked = False
        try:
            self.info_set(QUALIFYING_INFO_KEY, [])
            self.info_set("自动停止原因", "")
            self.info_set("已自动停止", False)
        except Exception:                     # noqa: BLE001 - info 写不进去不该挡启动
            pass
        if self.judge_config.enable_max_roll_lock:
            # 先播一个 0：报告卡靠"这个键在不在"判断要不要统计满属性
            self.info_set("满属性声骸数量", 0)
        self._check_environment()
        # 上一轮的失败原因先清掉 —— info 在同一进程内跨次累加，
        # 不清的话这次跑成功也还会挂着上次的「任务中断：…」。
        try:
            self.info_set("失败原因", "")
        except Exception:                     # noqa: BLE001
            pass
        #: ★★★ 2026-10-28 「自动切换阶段放入」**不在 run() 开头做**。
        #:
        #: ## 打过一次实机翻车（19:24:57）
        #:
        #: 我原来在这里调 ``_ensure_stage_insert_mode()``，但此时**强化界面
        #: 还没打开**（ok-ww 要等它自己点「培养」才进去）。于是那个方法
        #: 盲点 (639,673) 想点"齿轮"，实际点到别处 → 界面被弄乱 →
        #: ok-ww 的 ``select_0_level_echo()`` 找不到 0 级声骸 → 直接收工 →
        #: 最终报「本次没有判定任何声骸」。
        #:
        #: ## 现在挂在哪
        #:
        #: ``find_add_mat()`` 里 —— 那是 ok-ww 在**强化界面里**反复调的
        #: 方法（``run()`` 的 ``while True: add_mat = self.find_add_mat()``）。
        #: 在那里做「检查 + 自动切换」，界面一定是对的。
        with _no_startfile():
            #: ★ 2026-10-30 用户：
            #: > 另外跳过要立即中断当前强化，回到声骸完成筛选那一步
            #:
            #: 所以 ``super().run()`` 包在一个**可重启的循环**里：
            #:   * 正常结束 → 返回
            #:   * 抛 :class:`SkipCurrentEcho`（用户按了跳过）→
            #:     按 Esc 退出强化界面 → 重新筛一遍 → 再开跑
            #:   * 其他异常 → 照旧记「失败原因」并抛出
            #:
            #: ## ⚠ 必须防死循环（2026-10-30）
            #:
            #: 「读不到名字 → 也跳过」这条兜底有个天然风险：如果 OCR 一直
            #: 读不到，就会一直跳过 → 重开 → 又读不到 → 无限循环，
            #: 而且每次都白点一次「培养」，把游戏界面折腾个没完。
            #:
            #: 所以连续跳过次数超过上限（``MAX_CONSECUTIVE_SKIPS``）就
            #: **结束任务**并报出来 —— 那种情况下 OCR 是真的坏了，
            #: 继续跑只会坏事，停在原地让人看到原因才有意义。
            #:
            #: ⚠ 计数存在**实例字段** ``_consecutive_skips`` 上，
            #: 由 ``lock_and_esc``（真强化完一个）清零 —— 不能放局部变量，
            #: 那样跨不过 ``continue``。
            self._consecutive_skips = 0
            while True:
                #: ★ 每轮重开都重置"入口核验"开关 —— 下一个声骸要重新核。
                #: 不重置的话，第一次核过之后再也不核了（等同于没有这道闸）。
                self._entry_checked = False
                try:
                    return super().run()
                except SkipCurrentEcho:
                    self._consecutive_skips += 1
                    if self._consecutive_skips >= MAX_CONSECUTIVE_SKIPS:
                        #: 连着跳过太多次 → OCR 大概率坏了，停下来报原因。
                        #: 继续跑只会无限点「培养」+ 退出，把游戏界面折腾乱。
                        msg = (f"连续跳过 {self._consecutive_skips} 个声骸仍未"
                               f"强化任何一个（多半是读不到声骸名 / 配置为空）"
                               f"→ 已停止任务，请检查日志里的「读不到声骸名」")
                        try:
                            self.info_set("失败原因", msg)
                        except Exception:  # noqa: BLE001
                            pass
                        self.log_info("✗ " + msg, notify=True)
                        raise RuntimeError(msg) from None
                    self._on_skip_requested()
                    #: 回到"筛选好的声骸列表"，再让 ok-ww 重新开始
                    continue
                except Exception as exc:
                    # ★ 把中断原因记进 info。
                    #   它会被 okww_boot.poll_done 在任务消失前摘走，
                    #   再由工具页喂给 format_result_report —— 不然界面只会显示
                    #   「请确认停在 背包 → 声骸 界面」，跟真实原因完全对不上
                    #   （实测 2026-09-25：真因是游戏内「阶段放入」没开）。
                    try:
                        self.info_set("失败原因", str(exc))
                    except Exception:             # noqa: BLE001
                        pass
                    raise
                finally:
                    self.log_info(
                        "本轮报告：判定 %d 次，符合条件 %s 个，弃置 %s 个，满属性 %s 个"
                        % (self.checked_echoes, self.info_get("成功声骸数量", 0),
                           self.info_get("失败声骸数量", 0),
                           self.info_get("满属性声骸数量", "未统计")),
                        notify=True,
                    )

    def _on_skip_requested(self) -> None:
        """用户按了「跳过」→ 退回筛选好的声骸列表，准备重新开跑。

        ## 用户 2026-10-30

        > 另外跳过要立即中断当前强化，回到声骸完成筛选那一步

        ## 怎么退

        ok-ww 的 ``esc()`` 会连按 Esc 直到看到「培养」按钮
        （= 回到声骸列表），这正是"筛选完之后停在的那个界面"。

        列表本身**没变**（筛选条件还在），所以不需要重新筛选 ——
        直接让 ``run()`` 再跑一遍就会从列表第一个未强化声骸重新开始。

        ⚠ 那个**刚被跳过的声骸**还在列表里（它没被强化也没被弃置）。
        靠 ``_skip_recent`` 记住它，下一轮 ``select_0_level_echo``
        会把它再跳过一次（见那里的处理）。

        ⚠ 那个**刚被跳过的声骸**还在列表里（它没被强化也没被弃置）。
        它的名字在**抛出异常之前**就已经记进 ``_handled_echoes`` 了
        （见 ``check_echo_stats`` 里那段）—— 那里才有准确的界面状态。
        所以下一轮 ``select_0_level_echo`` 会自动跳过它，
        以及**所有同类型同名的**声骸（用户 2026-10-30 的语义：
        "跳过相当于他已经强化好了"）。

        ## 为什么不清统计

        用户中途跳过只是"这一个不想要"，之前强化好的东西还算数，
        所以 ``checked_echoes`` / ``discard_tally`` 都保留。
        """
        #: 退回声骸列表（= 筛选完成后的界面）
        try:
            self.esc()
            self.sleep(0.5)
        except Exception as exc:  # noqa: BLE001 - 退不回去也别卡死
            self.log_error(f"【跳过】退回列表失败：{type(exc).__name__}: {exc}")
        self.log_info("【跳过】已回到声骸列表，重新开始强化"
                      "（刚跳过的那个及其同名同类型都会跳过）",
                      notify=True)

    def _check_environment(self) -> None:
        """开跑前把"会让结果看起来完全不对"的环境/配置问题喊出来。"""
        warning = self.judge_config.criterion_warning()
        if warning:
            self.log_info("⚠ 判定规则自相矛盾，已自动收窄：" + warning, notify=True)
        locale = getattr(self.executor, "locale", None)
        name = locale.name() if hasattr(locale, "name") else str(locale or "")
        if name and not name.startswith("zh"):
            self.log_info(
                "⚠ 引擎语言是 %s，本任务按**中文游戏界面**做 OCR 匹配"
                "（'培养'「阶段放入」「强化并调谐」…）；"
                "游戏界面不是简体/繁体中文就会识别失败。" % name,
                notify=True,
            )
