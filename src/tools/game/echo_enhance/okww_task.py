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
        """返回 ``True`` = 继续强化，``False`` = 交给 ok-ww 去弃置。"""
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
        element = super().find_add_mat()
        if element:
            # 「阶段放入」还在 → 材料是空的，正常放入。复位哨兵供本轮再报告。
            self._materials_ready_sent = False
            return element

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
        self._auto_stop_if_needed(hit)
        self._aim_at_next_unenhanced()

    def trash_and_esc(self):
        super().trash_and_esc()
        self._finalize_echo(kept=False)
        self._aim_at_next_unenhanced()

    def _auto_stop_if_needed(self, qualifying: bool) -> bool:
        """★ 出了符合条件的声骸 → **暂停任务 + 通知**（用户 2026-10-10 要求）。

        :param qualifying: 刚处理完那个声骸是不是**真正符合条件**
            （由 :meth:`_finalize_echo` 判定并传来 —— 不在这个方法里自己读字段，
            免得再踩"谁先清谁后读"的顺序坑）
        :return: 是否真的暂停了

        ## 为什么暂停而不是停止

        用户选了「暂停任务（可续跑）」：暂停后游戏停手、但任务还在，
        他回来点继续就能接着强化。**停止**会把任务整个结束掉，想接着跑得重开。

        ok-ww 的 ``pause()`` 正是干这个的（原版那句
        ``if self.config.get('Pause after Success'): self.pause()``
        就是这个机制）—— 我们只是把触发条件从"成功即暂停"换成
        "**真正符合条件**才暂停"，并且**由开关控制**。

        ⚠ 只在 ``enable_auto_stop`` 打开时做。关掉时**完全不动**
        （连日志都不打，免得刷屏）。
        """
        if not getattr(self.judge_config, "enable_auto_stop", False):
            return False
        if not qualifying:
            return False

        self.auto_stop_count += 1
        stats_text = "、".join(str(s) for s in self._last_present) or "无"
        summary = f"出现符合条件的声骸（第 {self.info_get('成功声骸数量', 0)} 个）：{stats_text}"
        self.info_set("自动停止原因", summary)
        #: notify=True → 走 ok 的通知链路，宿主那边接出来弹托盘气泡（见 tool.py）
        self.log_info(f"★ {summary} —— 已暂停任务，请回来确认", notify=True)
        try:
            self.pause()
            self.info_set("已自动停止", True)
        except Exception as exc:  # noqa: BLE001 - 暂停失败不该把任务搞崩
            self.log_error(f"自动暂停失败：{type(exc).__name__}: {exc}")
            return False
        return True

    # ------------------------------------------------- 3.7 声骸堆叠的修正
    def _aim_at_next_unenhanced(self) -> bool:
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

        :return: 是否成功把光标移到了一个未强化的声骸上
        """
        try:
            found = echo_grid.find_next_unenhanced(self)
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
        self.sleep(0.3)
        return True

    # ------------------------------------------------------------------ 运行
    def run(self) -> None:
        """ok-ww 的 ``run()`` 原样跑，只是屏蔽它结尾弹截图文件夹那一下。"""
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
        with _no_startfile():
            try:
                return super().run()
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
