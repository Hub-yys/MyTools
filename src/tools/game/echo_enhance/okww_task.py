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
"""

from __future__ import annotations

import contextlib
import os
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

from .stats import (  # noqa: E402
    EchoStat,
    JudgeConfig,
    judge,
    normalize_stat_name,
    parse_value,
)

#: 任务在宿主里的注册名（``okww_boot.TASKS`` 与页面上用的是同一个 key）
TASK_KEY = "声骸自动强化"

#: ok-ww 侧看到的类名
TASK_CLASS_NAME = "MyToolsEnhanceEchoTask"


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


class MyToolsEnhanceEchoTask(EnhanceEchoTask):
    """ok-ww 的强化流程 + MyTools 的筛选条件。

    除了 :meth:`check_echo_stats` 与几处与判定直接相关的配置，其余全部继承。
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.name = "⬆️ 声骸自动强化（MyTools 筛选条件）"
        self.description = (
            "点 B 进背包 → 声骸 → 用过滤器筛出要强化的 → 按等级升序排序后开始。"
            "流程与 ok-ww 一致，判定用 MyTools 里配的那套条件。"
        )

        # ok-ww 默认「成功即暂停」，那是给"边看边强化"准备的；
        # MyTools 是批量工具，暂停会表现得像"只跑一个就停了" —— 关掉。
        # （after_init → load_config 会拿 default_config 生成 self.config，
        #   所以在这里改默认值是生效的。见 ok/task/task.py: load_config）
        self.default_config["Pause after Success"] = False

        #: 判定配置。由宿主在启动任务前注入（见 ``okww_boot.OkwwHost.start_task``）
        #: —— 也就是工具页上用户配的那套筛选条件。
        self.judge_config = JudgeConfig()

        #: 最近一次的判定结果（日志/排查用）
        self.last_judgement = ""

    # ------------------------------------------------------------------ 判定
    def check_echo_stats(self, properties, values) -> bool:
        """返回 ``True`` = 继续强化，``False`` = 交给 ok-ww 去弃置。"""
        stats = to_echo_stats(properties, values)
        result = judge(stats, self.judge_config)

        self.last_judgement = str(result)
        # ok-ww 会把 fail_reason 拼进失败截图的文件名，所以给个安全的短串
        self.fail_reason = result.reason or result.action
        self.info_set("MyTools 判定", str(result))
        self.log_info(
            "MyTools 判定：%s（读到词条 %s）"
            % (result, "、".join(str(s) for s in stats) or "无")
        )
        return result.action != "discard"

    # ------------------------------------------------------------------ 运行
    def run(self) -> None:
        """ok-ww 的 ``run()`` 原样跑，只是屏蔽它结尾弹截图文件夹那一下。"""
        with _no_startfile():
            return super().run()
