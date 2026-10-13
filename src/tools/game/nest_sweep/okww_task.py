# -*- coding: utf-8 -*-
"""「扫荡残像聚落」的 ok-ww 任务类（宿主接线）。

## 和 ok-ww 原版的关系：**复用流程，换掉"刷哪个"的决定权**

ok-ww 的 ``NightmareNestTask`` 已经实现了完整的一条龙::

    开索拉指南 → 切到「残像聚落」/「梦魇拔除」页签 → 找到**任意**没打完的
    → 传送 → 打 → 捡声骸 → 回到列表 → 再来一遍

但它的取舍是「**刷所有**」—— :meth:`~okww.task.NightmareNestTask.find_nest`
只认行尾的 ``0/24`` 计数器，**根本不看那行叫什么**。

本工具要的是「**只刷我勾的那几个，按我的顺序**」，所以继承它、
把"选哪个"这一段换掉，**传送 / 战斗 / 捡取全部沿用**（那些是最难调的部分，
一行都不重写）。

## ★ 三层定位：名称 → 别名 → 行号

识别"这一行是不是我要的那一处"只用计数器是不够的（所有没打的都是 ``0/24``），
所以按可靠性依次退让::

    ① 名称匹配     OCR 读行文字，和 match_names 比（最稳 —— 名称顺序变了也不怕）
    ② 别名匹配     同上，名字是简称 / 少字时兜底
    ③ 行号兜底     按清单里的顺序点第 N 行（前两级都认不出来时）

三个都在 :class:`~src.core.nest_sweep.SweepStep` 里带着（见 ``core/nest_sweep/plan``），
所以这里**不需要猜** —— 全是数据文件里定的。

## ⚠⚠ 别把判断写进这里

本模块跑在 ok-ww 引擎线程里，**离线测不了**。
"勾了什么 / 什么顺序 / 怎么匹配"全在 ``src/core/nest_sweep``（纯逻辑、有单测）。
这里只做: **把引擎的画面读出来 → 交给 core → 照结果点**。

## 接线（新增任务时最容易漏的一步）

ok-ww 侧要**两处**都登记才会跑：

1. ``src/tools/game/auto_combat/okww_boot.py`` 的 ``TASKS`` 字典
2. 同文件 ``build_config()`` 的 ``onetime_tasks`` 列表
3. 外加 ``tests/test_okww_vendor.py`` 的 ``OWN_TASKS`` 白名单

漏掉任何一处 → 界面显示"找不到任务"（而且**不报错**）。

## ★★ ``supported_languages`` 必须清空

宿主**无 GUI** → ``app.locale`` 是 ``en_US`` → ok-script 的 ``init_tasks()``
**不注册**声明了 ``supported_languages = ["zh_CN"]`` 的任务 → 任务被静默跳过。
这个坑在声骸调频 / 强化 / 查缺补漏那边都踩过。
"""

from __future__ import annotations

import os
import re
import sys

#: ★ ok-ww 配置里要引用的**模块级类名**。
#:
#: ``onetime_tasks`` 写 ``["src.tools.game.nest_sweep.okww_task",
#: "MyToolsNestSweepTask"]`` 时，ok-script 会对本模块做
#: ``getattr(..., "MyToolsNestSweepTask")`` —— 所以在模块尾用
#: ``__getattr__``（PEP 562）懒构造它。
TASK_CLASS_NAME = "MyToolsNestSweepTask"

#: 索拉指南里两个页签的坐标代号（对应 ``BaseWWTask.open_boss_book`` 的分支）
TAB_NEST = "canxiang"        #: 残像聚落
TAB_NIGHTMARE = "mengyan"    #: 梦魇拔除

#: 分类 → 页签代号
TAB_OF_KIND = {
    "nest": TAB_NEST,
    "nightmare": TAB_NIGHTMARE,
}

#: 指南列表里"``0/24``"这种计数器的形状
COUNT_RE = re.compile(r"(\d{1,2})\s*/\s*(\d{1,2})")

#: 列表区域（相对坐标）。和 ok-ww 原版 ``find_nest`` 用的是同一块 ——
#: 那是实测调出来的，别自己另量一套。
LIST_BOX = (0.35, 0.13, 1.0, 0.96)

#: 点行的横向位置（屏幕宽度的比例）。原版取 0.9 ——
#: 那是行尾「前往」按钮附近，点这里才会触发传送而不是选中。
ROW_CLICK_X = 0.9


def _ensure_okww_on_path() -> None:
    """把 vendored ok-ww 挂上 ``sys.path``（和别处同样的四层上溯）。"""
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.abspath(os.path.join(here, "..", "..", "..", ".."))
    vendor = os.path.join(root, "vendor", "okww")
    if os.path.isdir(vendor) and sys.path and vendor not in sys.path:
        sys.path.insert(0, vendor)


def _normalize(text: str) -> str:
    """比较用归一化：**去掉所有空白和分隔点**，只留下实义字符。

    ## 为什么必须归一化

    OCR 读出来的行文字和清单里的名字**不可能逐字相同**：

    * 名字里有 ``·``（``梦魇·无冠者``），OCR 常读成 ``.`` / 空格 / 干脆丢掉
    * 行里可能还混着别的字（数量、状态词）
    * 全角 / 半角、简繁差异

    所以这里把 ``梦魇·无冠者`` 和 ``梦魇 无冠者`` 都压成 ``梦魇无冠者``
    再去比 —— 比"要求一字不差"稳得多。
    """
    if not text:
        return ""
    #: 去掉一切非字母数字汉字的字符（含 ``·`` ``.`` 空格 全角空格）
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", str(text))


def _name_hit(row_text: str, candidates) -> str:
    """``row_text`` 命中 ``candidates`` 里的哪一个？返回命中的名字（没命中返回空串）。

    ## ★ 长的先比（这个顺序有讲究）

    ``梦魇·刺玫菇（稚形）`` 和 ``梦魇·刺玫菇`` 是**两个不同的目标**。
    如果拿短名先比，``...刺玫菇（稚形）`` 那一行会被判成 ``梦魇·刺玫菇``
    —— 于是"勾了稚形，跑去刷了普通那个"。

    :func:`~src.core.nest_sweep.SweepTarget.match_names` 已经按长度倒序排好，
    这里照着顺序比、命中就返回。

    ## 两个方向都算命中

    * ``候选 in 行文字`` —— 行里带了额外字符（常态）
    * ``行文字 in 候选`` —— OCR 只读到半截（也很常见）

    但**太短的不能反向算**：行文字只有两个字时，"它是我要找的那行的前缀"
    这种事纯属巧合。所以反向匹配要求至少 :data:`_MIN_REVERSE` 个字。
    """
    row = _normalize(row_text)
    if not row:
        return ""
    #: ⚠ **自己再排一遍**，不能只依赖调用方传进来的顺序。
    #:   实测过：候选按 ``['梦魇·刺玫菇', '梦魇·刺玫菇（稚形）']`` 传进来时，
    #:   短名是长名的子串 → 先命中短名 → **勾了稚形却刷了普通那个**。
    #:   ``match_names()`` 确实已经排过序，但这里排一次的代价是零，
    #:   而漏排的代价是"刷错目标且界面上看不出来"。
    ordered = sorted((str(c) for c in (candidates or ()) if str(c)),
                     key=len, reverse=True)
    for candidate in ordered:
        want = _normalize(candidate)
        if not want:
            continue
        if want in row:
            return candidate
        if len(row) >= _MIN_REVERSE and row in want:
            return candidate
    return ""


#: 反向匹配（行文字 ⊂ 候选名）要求的最少字数
_MIN_REVERSE = 3


def build_task_class():
    """构造任务类。拿不到 ok-ww 时返回 ``None``（**不抛异常**）。

    ## 为什么要在函数里建类，而不是模块级 ``class ... (WWOneTimeTask)``

    模块级基类会在 **import 本模块时**就要 ok-ww 在场。而
    ``registry.discover()`` 会 import 工具包下的所有模块 ——
    没装 ok-ww 的环境（CI / 只跑数据工具）会**整个发现流程失败**。

    所以真正的类在调用时才建，模块级只暴露一个 ``__getattr__``（PEP 562）。
    """
    _ensure_okww_on_path()
    try:
        from ok import Box  # noqa: PLC0415
        from okww.task.NightmareNestTask import (  # noqa: PLC0415
            NestTarget,
            NightmareNestTask,
        )
    except Exception:  # noqa: BLE001 - ok-ww 不在场
        return None

    #: ★ 双继承 ``(WWOneTimeTask, BaseCombatTask)`` 由 ``NightmareNestTask``
    #: 带过来 —— 直接继承它就够了，别自己写单继承基类
    #: （``WWOneTimeTask`` 没有 ``__init__``，ok-script 用
    #: ``class_(executor=..., app=...)`` 实例化时单继承会 ``TypeError``）。
    class MyToolsNestSweepTask(NightmareNestTask):
        """按**用户勾选的清单**、**按顺序一个一个**刷。

        ``NightmareNestTask`` 的「传送 / 战斗 / 捡声骸」全盘沿用，只换选择逻辑。
        """

        #: ★ 见模块说明 —— 不清空会被 ok-script 静默跳过
        supported_languages = []

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.name = "扫荡残像聚落"
            self.description = "按勾选的清单顺序，逐个扫荡残像聚落 / 梦魇残像"
            #: ★ 计划由工具页注入（``configure``）或从盘上读（:meth:`_resolve_plan`）。
            #: 工具页注入的那份是"用户当下看到的"，优先。
            self.sweep_plan = None
            #: 每个目标的结果，跑完写进 ``info`` 给界面做报告
            self.sweep_results: list[dict] = []
            self.default_config.update({"Which to Farm": ["Tacet Discord Nest",
                                                          "Nightmare Purification"]})

        # ------------------------------------------------------------ 计划
        def _resolve_plan(self):
            """拿这次要跑的**有序计划**。

            两条来源，优先级从高到低：

            1. 工具页注入的 ``self.sweep_plan`` —— 用户刚在界面上勾的那份
            2. 盘上的 ``tool_settings.json`` —— 任务流程冷启动时的唯一来源
               （用户可能开机就跑流程，根本没打开过工具页）

            都没勾 → 返回空计划，:meth:`run` 会**明确报错停下**，
            而不是"什么都没做就成功"（那会让人以为刷完了）。
            """
            if self.sweep_plan is not None:
                return self.sweep_plan
            try:
                from src.core.nest_sweep import build_plan, load_selection
            except Exception as exc:  # noqa: BLE001
                self.log_error(f"读扫荡清单失败：{type(exc).__name__}: {exc}")
                return None
            try:
                return build_plan(load_selection())
            except Exception as exc:  # noqa: BLE001
                self.log_error(f"构建扫荡计划失败：{type(exc).__name__}: {exc}")
                return None

        # ------------------------------------------------------------ 主循环
        def run(self):
            """★ **一个目标一个目标地刷**，顺序就是清单顺序。"""
            self._capture_mode = False
            self._capture_success = False
            self._unreachable_nests.clear()
            self.sweep_results = []

            plan = self._resolve_plan()
            if plan is None or not len(plan):
                self.log_error("没有勾选任何残像聚落 / 梦魇残像 —— 先去工具页勾选，"
                               "再运行本任务", notify=True)
                return
            self.plan = plan

            WWOneTimeTask.run(self)
            self.ensure_main(time_out=30)

            self.info_set("扫荡目标总数", len(plan))
            self.info_set("扫荡完成数", 0)
            self.log_info(f"扫荡开始：{plan.describe()}")

            done = 0
            for step in plan:
                if self._stop_requested():
                    self.log_info("收到停止请求，扫荡中断")
                    break
                ok = self._sweep_one(step)
                self.sweep_results.append({
                    "key": step.key, "name": step.name, "kind": step.kind,
                    "ok": bool(ok),
                })
                if ok:
                    done += 1
                    self.info_set("扫荡完成数", done)
                #: 记一条进度（界面上的"第 N/M 个"）
                self.info_set("当前进度", step.describe())

            self.ensure_main(time_out=30)
            self.info_set("扫荡结果", self._results_text())
            self.log_info(self._results_text(), notify=True)

        # ------------------------------------------------------------ 停止
        def _stop_requested(self) -> bool:
            """用户点了「停止」吗？

            ## ★★ 必须查 ``_enabled``，**没有别的信号**

            ok-ww 的停止不是"设一个标志让任务自己看"，而是:

            ::

                TaskExecutor.stop_current_task()
                    → task.disable()          # self._enabled = False
                    → task.unpause()

            真正的**中断**发生在下一次 ``sleep()`` / ``next_frame()`` 里 ——
            ``check_enabled()`` 发现 ``_enabled`` 是 False 就 ``raise
            TaskDisabledException``，把整条调用栈掀掉（见 ``TaskExecutor.py``）。

            ## 那这里为什么还要自己查一遍？

            因为本轮循环是**我加的**：每一步之间如果什么都不查，
            用户点了停止、当前这一步又恰好很快跑完，就会**接着开下一个**。
            自查一遍能让"停止"在这一步的边界上立刻生效，
            而不是等引擎那头掀栈。

            ⚠ ``_enabled`` 是 ok-ww 的**私有属性**（下划线开头）。
            加 ``getattr`` 兜底：将来它改了名，这里退化成"靠引擎自己的
            check_enabled 中断"（仍然能停，只是晚一个边界），
            **而不是 AttributeError 把任务搞崩**。
            """
            return not bool(getattr(self, "_enabled", True))

        # ------------------------------------------------------------ 单个目标
        def _sweep_one(self, step) -> bool:
            """刷**一个**目标。成功返回 True。

            流程（每一步都可能失败，失败只跳过一个、**不中断整轮**）::

                开指南 → 切页签 → 找到那一行 → 点它 → 传送 → 打 → 捡

            ⚠ "找不到那一行"是**正常情况**而不是异常：今天已经刷过的聚落
            计数会变成非 0，认不出来时应该记一条"跳过"继续下一个 ——
            整轮停在一个刷过的目标上，才是真的坏体验。
            """
            self.log_info(f"→ {step.describe()}")
            try:
                self._open_tab(step.kind)
            except Exception as exc:  # noqa: BLE001
                self.log_error(f"打开指南页签失败（{step.describe()}）："
                               f"{type(exc).__name__}: {exc}")
                return False

            box = self._find_row(step)
            if box is None:
                self.log_info(f"指南里找不到 / 今天已刷完，跳过：{step.name}")
                return False

            try:
                self.combat_nest(box)
            except Exception as exc:  # noqa: BLE001
                self.log_error(f"扫荡失败（{step.describe()}）："
                               f"{type(exc).__name__}: {exc}")
                #: 失败也要把书关上，否则下一个目标会从"书还开着"的状态开始
                self._safe_back_to_main()
                return False
            self._safe_back_to_main()
            self.log_info(f"✓ 完成：{step.name}")
            return True

        def _open_tab(self, kind: str) -> None:
            """开索拉指南并切到对应页签。"""
            tab = TAB_OF_KIND.get(kind, TAB_NEST)
            self.ensure_main(time_out=30)
            self.openF2Book("gray_book_boss")
            self.open_boss_book(tab)

        def _safe_back_to_main(self) -> None:
            """回大世界。失败**不抛** —— 收尾动作失败不该盖掉真正的结果。"""
            try:
                self.ensure_main(time_out=30)
            except Exception as exc:  # noqa: BLE001
                self.log_debug(f"回主界面失败（忽略）：{type(exc).__name__}: {exc}")

        # ------------------------------------------------------------ 找行
        def _find_row(self, step):
            """★ 三层定位：**名称 → 别名 → 行号**。

            返回一个可以直接点（会触发传送）的目标；找不到返回 ``None``。

            ## 为什么包成 ``NestTarget`` 而不是裸的 ``Box``

            ``NestTarget`` 带一个 ``cache_key``，ok-ww 的
            ``_travel_to_nest_or_skip`` 靠它把"传送不过去"的目标记进
            ``_unreachable_nests``，**本次运行不再重试**。

            裸 ``Box`` 也能跑（``combat_nest`` 两种都收），但那样就丢了这个记录 ——
            传不过去的目标会一次次重试，每一轮都要白等一次传送超时。

            ``cache_key`` 直接用清单里的 ``step.key``：它本来就是稳定唯一的，
            比我再编一个更靠谱（原版是按行号算的，行号会变）。
            """
            counts = self._ocr_counts()
            rows = self.ocr(*LIST_BOX)

            ordered = list(rows or [])
            #: 名称 / 别名匹配（长名优先已由 core 排好）
            for box in ordered:
                hit = _name_hit(getattr(box, "name", ""), step.match_names)
                if not hit:
                    continue
                #: 找到了 —— 顺手确认"今天还没刷完"。
                #: ⚠ 读不到计数器时**照样刷**：计数器认不出来是常事
                #: （数字带斜纹底、字号小），而"名字对上了"本身已经够确定。
                if not self._row_incomplete(box, counts):
                    self.log_info(f"{step.name}：今天已经刷过了（计数器已满）")
                    return None
                self.log_info(f"{step.name}：按名称命中「{hit}」")
                self._enter_tab_for(step)
                return NestTarget(self._clickable(box), step.key)

            #: 行号兜底 —— 名称完全认不出来时用清单里的顺序
            fallback = self._row_by_index(step, counts)
            if fallback is not None:
                self.log_info(f"{step.name}：名称没认出来，按清单第 "
                              f"{step.fallback_row} 行兜底")
                self._enter_tab_for(step)
                return NestTarget(fallback, step.key)
            return None

        def _enter_tab_for(self, step) -> None:
            """记下"当前这个目标在哪个页签"。

            ⚠ 原版 ``combat_nest`` 的兜底重传分支会用到
            ``self._nest_tab_of_current_nest``（没声骸时重开指南、回到当前页签）。
            不设它的话兜底会走错页签 —— 那会表现为"重传之后跑到别的地方去了"。
            """
            self._nest_tab_of_current_nest = (
                "go_nest" if step.kind == "nest" else "go_nightmare")

        def _ocr_counts(self):
            """OCR 出所有 ``0/24`` 形状的计数器。"""
            try:
                return self.ocr(*LIST_BOX, match=COUNT_RE) or []
            except Exception as exc:  # noqa: BLE001
                self.log_debug(f"读计数器失败（忽略）：{type(exc).__name__}: {exc}")
                return []

        def _clickable(self, box):
            """文字框 → **可以点的行尾框**。

            ## 为什么不能直接点文字框

            OCR 给的框住的是**行首的文字**（"落渊南丘"那几个字），
            而要点的是**行尾的「前往」按钮**。点文字那里多半只是选中这一行、
            不会触发传送 —— 表现为"任务在跑但一直不动"。

            原版 ``find_nest`` 就是这么处理的：把 ``x`` 挪到 ``0.9 * 屏宽``、
            ``y`` 保持在这一行上，那里才是按钮。这里照抄同一个落点。

            ⚠ 用 ``width_of_screen`` 换算，**不要自己乘分辨率比例** ——
            那个换算 ok-ww 只应该在一处做（``echo_grid`` 里踩过"双重缩放"）。
            """
            x = self.width_of_screen(ROW_CLICK_X)
            return Box(x, box.y, 1, max(box.height, 1),
                       name=f"sweep_row:{getattr(box, 'name', '') or ''}")

        def _row_incomplete(self, box, counts) -> bool:
            """这一行今天还没刷完吗？

            ## 判据（和 ok-ww 原版一致）

            计数器 ``分子/分母``：``分子 != 分母`` 且 ``分子 == 0`` 且分母在
            已知的每日上限里 → **还没打过**。

            ⚠ **读不到计数器时返回 True**（当作"还没刷"）：
            让任务去试一次，失败了只是白跑一趟；反过来判 False 的话，
            一次 OCR 抖动就会让**用户明确勾选的目标被静默跳过**。
            """
            row_y = getattr(box, "y", 0)
            row_h = max(getattr(box, "height", 0), 1)
            for count_box in counts:
                cy = getattr(count_box, "y", -10 ** 6)
                #: 同一行的判据：纵坐标落在这一行的带状范围里
                if not (row_y - row_h <= cy <= row_y + 2 * row_h):
                    continue
                for match in COUNT_RE.finditer(getattr(count_box, "name", "") or ""):
                    numerator, denominator = match.group(1), match.group(2)
                    if numerator == denominator:
                        return False
                    if numerator == "0":
                        return True
                    return False
            return True

        def _row_by_index(self, step, counts):
            """行号兜底：按清单顺序点第 ``fallback_row`` 行。

            ## 只在"没打过"的行里数，不是整列表数

            指南列表里**刷过的行也占位置**。如果按整表数第 N 行，
            用户刷掉第一处之后，第二处就变成第 1 行了 ——
            于是"按行号"会越点越偏。

            所以这里数的是 :meth:`_ocr_counts` 认出来的**未完成行**，
            第 ``fallback_row`` 个未完成行 —— 和"清单里第几个"语义一致
            （清单本身就是"今天要刷的"）。
            """
            target_row = int(getattr(step, "fallback_row", 0) or 0)
            if target_row <= 0:
                return None
            pending = self._pending_rows(counts)
            if len(pending) < target_row:
                return None
            return self._clickable(pending[target_row - 1])

        def _pending_rows(self, counts):
            """从计数器框推出"还没打完的行"（按从上到下的顺序）。"""
            boxes = []
            for count_box in counts:
                for match in COUNT_RE.finditer(getattr(count_box, "name", "") or ""):
                    numerator, denominator = match.group(1), match.group(2)
                    if numerator != denominator and numerator == "0":
                        boxes.append(count_box)
                        break
            boxes.sort(key=lambda b: getattr(b, "y", 0))
            return boxes

        # ------------------------------------------------------------ 报告
        def _results_text(self) -> str:
            """跑完的汇总文字（进 ``info``，界面和通知都用它）。"""
            total = len(self.plan) if getattr(self, "plan", None) else 0
            done = sum(1 for r in self.sweep_results if r.get("ok"))
            skipped = [r["name"] for r in self.sweep_results if not r.get("ok")]
            text = f"扫荡完成：{done}/{total}"
            if skipped:
                #: ⚠ 跳过的一定要点名 —— 否则用户只看到"5/8"，
                #: 完全不知道是哪 3 个没刷，也没法判断要不要手动补
                text += "；未完成：" + "、".join(skipped[:6])
                if len(skipped) > 6:
                    text += f" 等 {len(skipped)} 个"
            return text

    return MyToolsNestSweepTask


def _load_okww_class():
    """★ ok-ww 配置里 ``[模块, 类名]`` 走的是 ``getattr`` —— 得有个模块级名字。

    ok-script 解析 ``onetime_tasks`` 的方式是::

        getattr(importlib.import_module(module_name), attribute_name)

    也就是**普通属性查找**，不接受工厂函数的结果。所以本模块必须暴露
    一个模块级类名。但模块级 ``class ... (WWOneTimeTask)`` 会在 import 时
    就要 ok-ww 在场（见 :func:`build_task_class` 的说明）。

    解法：``__getattr__``（PEP 562）—— **模块级懒属性**。
    平时 import 本模块不碰 ok-ww；ok-script 真的 ``getattr`` 时才构造。
    """
    return build_task_class()


def __getattr__(name: str):
    """模块级懒属性（PEP 562）—— 只认任务类名。"""
    if name == TASK_CLASS_NAME:
        cls = _load_okww_class()
        if cls is None:
            raise AttributeError(
                f"{TASK_CLASS_NAME} 需要 ok-ww（vendor/okww 或已安装的 ok-script）")
        #: 缓存，避免每次 getattr 都重建一个类
        globals()[TASK_CLASS_NAME] = cls
        return cls
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
