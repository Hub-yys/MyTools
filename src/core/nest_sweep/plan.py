# -*- coding: utf-8 -*-
"""勾选 → **按顺序一个一个刷**的执行计划。

## 用户要的是什么

原话（2026-10-13）::

    以卡片形式展示，可以一键勾选全部，勾选的运行后，根据顺序一个一个去刷

拆成三件事，本模块管前两件::

    ① 勾选集合  +  清单  →  一个**有序**的执行计划   ← 本模块（纯逻辑）
    ② 计划里的每一步去游戏里怎么点                    ← okww_task（宿主接线）
    ③ 卡片 / 全选按钮 / 进度                         ← tool.py

## 为什么"顺序"要单独讲

**清单的顺序 = 刷取顺序**，而清单的顺序由 :mod:`.catalog` 决定
（2026-10-13 起：**按聚落推出的版本从新到旧**，同一版本内看 ``order``）。

这里**只做过滤，不重排** —— 过滤时重排会让"清单里的排序"失效，
而用户调 ``order`` 的目的正是控制刷的先后。

## 勾选存盘：**只存 key，不存下标**

::

    {"nest_sweep": {"selected": ["nest:xxx", "nightmare:梦魇·无冠者"]}}

存下标的话，用户往清单里插一条，之前勾的就全错位了 ——
而且错得**悄无声息**（勾的东西变了，界面看起来却"还是勾着"）。
key 是稳定的（见 ``catalog.SweepTarget.key``），改名字都不影响。

## ★ 计划里带上了"这一条怎么在游戏里找到"

:class:`SweepStep` 里的 :attr:`~SweepStep.match_names` 和
:attr:`~SweepStep.fallback_row` 是给任务侧用的:

* ``match_names`` —— 先按名字在指南里认行（最稳，名称顺序变了也不怕）
* ``fallback_row`` —— 名字认不出来时，退回"点第 N 行"

两个都带着，任务侧就能**先精确后兜底**，而不是二选一赌一个。

**纯逻辑**：不依赖 Qt、不碰 ok-ww。见 ``tests/test_nest_sweep_plan.py``。
"""

from __future__ import annotations

from dataclasses import dataclass

from .catalog import (
    KIND_NAMES,
    SweepTarget,
    load_catalog,
)

#: 工具设置里存勾选的那一节的名字（``data/tool_settings.json``）
SETTINGS_KEY = "nest_sweep"


@dataclass(frozen=True)
class SweepStep:
    """计划里的一步 = 一个要刷的目标 + 它在游戏里怎么定位。"""

    #: 清单里的 key（进度回报 / 日志用它认人）
    key: str
    #: 界面和日志上显示的名字
    name: str
    kind: str
    #: 在**本次计划**里的序号（从 1 起）—— 日志里"第 2/5 个"就是它
    index: int
    #: 匹配时依次尝试的名字（长名优先，见 ``SweepTarget.match_names``）
    match_names: tuple[str, ...] = ()
    #: 名称匹配失败时的兜底行号（**同一分类内**从 1 起，对应该页签列表的第几行）
    fallback_row: int = 0
    #: 每日可刷数量（``0/24`` 的那个 24），0 表示清单里没写
    count: int = 0
    region: str = ""

    @property
    def kind_name(self) -> str:
        """:data:`~.catalog.KIND_NAMES` 里的中文分类名。"""
        return KIND_NAMES.get(self.kind, self.kind)

    def describe(self) -> str:
        """一行进度文字，例如 ``[2/5] 残像聚落 · 落渊南丘``。"""
        where = f" · {self.region}" if self.region else ""
        return f"[{self.index}] {self.kind_name}{where} · {self.name}"


@dataclass
class SweepPlan:
    """一次扫荡的全部步骤（**有序**，按清单顺序）。"""

    steps: tuple[SweepStep, ...] = ()

    def __bool__(self) -> bool:
        return bool(self.steps)

    def __len__(self) -> int:
        return len(self.steps)

    def __iter__(self):
        return iter(self.steps)

    @property
    def first(self) -> SweepStep | None:
        """第一步（没勾任何东西时是 ``None``）。"""
        return self.steps[0] if self.steps else None

    def of_kind(self, kind: str) -> tuple[SweepStep, ...]:
        """只看某一类（``nest`` / ``nightmare``）的步骤，**保持原顺序**。"""
        return tuple(step for step in self.steps if step.kind == kind)

    def kinds(self) -> tuple[str, ...]:
        """计划里出现过的分类（按 :data:`~.catalog.KIND_ORDER` 排）。"""
        seen: list[str] = []
        for step in self.steps:
            if step.kind not in seen:
                seen.append(step.kind)
        return tuple(seen)

    def describe(self) -> str:
        """一行摘要，例如 ``残像聚落 2 个 · 梦魇残像 1 个``。"""
        if not self.steps:
            return "没有勾选任何目标"
        parts = []
        for kind in self.kinds():
            parts.append(f"{KIND_NAMES.get(kind, kind)} {len(self.of_kind(kind))} 个")
        return " · ".join(parts)


def build_plan(
    selected_keys,
    targets: tuple[SweepTarget, ...] | None = None,
) -> SweepPlan:
    """★ 把勾选的 key 变成有序计划。

    :param selected_keys: 勾中的 key（``set`` / ``list`` 都行；``None`` = 空）
    :param targets: 清单；不给就读数据文件

    ## 两条规则

    1. **顺序完全按清单来**，不按勾选顺序、也不重排 ——
       清单本身按版本从新到旧排（见 :mod:`.catalog`），
       用户在数据文件里调 ``order`` 则控制**同一版本内**的先后。
    2. **认不出来的 key 直接丢掉**（返回的步骤里没有）。用户可能勾过一条
       后来从清单里删掉的目标；这时计划里没有它，但**存盘的勾选先留着**
       （见 :func:`clean_selection` 的说明），下次把清单改回来它就又生效了。
    """
    items = load_catalog() if targets is None else targets
    keys = {str(k) for k in (selected_keys or ()) if str(k)}
    if not items or not keys:
        return SweepPlan()

    steps: list[SweepStep] = []
    #: 每个分类各自数行号（指南里残像聚落和梦魇是**两个页签**，行号各从 1 起）
    row_in_kind: dict[str, int] = {}
    for target in items:
        row_in_kind[target.kind] = row_in_kind.get(target.kind, 0) + 1
        if target.key not in keys:
            continue
        steps.append(SweepStep(
            key=target.key,
            name=target.name,
            kind=target.kind,
            index=len(steps) + 1,
            match_names=target.match_names(),
            fallback_row=row_in_kind[target.kind],
            count=target.count,
            region=target.region,
        ))
    return SweepPlan(tuple(steps))


def clean_selection(
    selected_keys,
    targets: tuple[SweepTarget, ...] | None = None,
) -> list[str]:
    """把勾选集合里**已经不存在的 key** 去掉，返回干净的一份（按清单顺序）。

    ## ⚠ 这个函数是给「保存」用的，不是给「构建计划」用的

    两者刻意不同:

    * **保存**时清掉不存在的 key —— 否则清单改过之后，
      ``tool_settings.json`` 里会永远堆着一串死 key。
    * **构建计划**时**不清**（:func:`build_plan` 只是不认它们）——
      这样用户"手滑删了一条又加回来"，勾选还在，不用重新点一遍。

    区别很小但有用：加回来时勾选恢复，而盘上又不会积垃圾。
    """
    items = load_catalog() if targets is None else targets
    if items is None:
        return []
    wanted = {str(k) for k in (selected_keys or ()) if str(k)}
    # 按**清单顺序**输出，不是按勾选顺序 —— 存盘的内容也就稳定了，
    # 每次保存不会因为点选先后不同而让文件内容抖来抖去。
    return [t.key for t in items if t.key in wanted]


# --------------------------------------------------------------------- 设置

def load_selection(targets: tuple[SweepTarget, ...] | None = None) -> list[str]:
    """从工具设置里读勾选（**已经过滤掉不存在的 key**）。

    设置文件读不出来 / 没存过 → 空列表（= 一个都没勾），
    界面上的表现是"什么都没选"，而不是崩掉。
    """
    from .. import tool_settings  # noqa: PLC0415 - 避免 core 内部的循环 import

    saved = tool_settings.load(SETTINGS_KEY)
    raw = saved.get("selected")
    if not isinstance(raw, (list, tuple, set)):
        return []
    return clean_selection(raw, targets)


def save_selection(selected_keys, targets: tuple[SweepTarget, ...] | None = None) -> None:
    """把勾选写进工具设置（写之前先 :func:`clean_selection`）。"""
    from .. import tool_settings  # noqa: PLC0415

    tool_settings.save(SETTINGS_KEY, {
        "selected": clean_selection(selected_keys, targets),
    })


def selected_targets(
    selected_keys, targets: tuple[SweepTarget, ...] | None = None,
) -> tuple[SweepTarget, ...]:
    """勾选对应的目标对象（按清单顺序）—— 界面画"已选"时用。"""
    items = load_catalog() if targets is None else targets
    keys = {str(k) for k in (selected_keys or ()) if str(k)}
    return tuple(t for t in items if t.key in keys)


def selection_summary(
    selected_keys, targets: tuple[SweepTarget, ...] | None = None,
) -> str:
    """一行摘要，例如 ``已选 3 个``。

    ★ 2026-10-13 用户要求「不再区分残像聚落/梦魇聚落，统一叫残像聚落」，
    所以这里**不再按分类拆开数**（原先写``已选 3 个（残像聚落 2 · 梦魇残像 1）``）。
    用户看到的是一张统一的卡片墙，摘要再分两类只会让人以为界面还分两段。
    """
    chosen = selected_targets(selected_keys, targets)
    if not chosen:
        return "未勾选任何目标"
    return f"已选 {len(chosen)} 个"
