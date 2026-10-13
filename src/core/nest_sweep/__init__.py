# -*- coding: utf-8 -*-
"""扫荡残像聚落 —— **纯逻辑层**（不碰 Qt、不碰 ok-ww）。

======================================  ==================================
文件                                     职责
======================================  ==================================
``catalog.py``                          目标清单：有哪些能刷、什么顺序
``plan.py``                             勾选 → 有序执行计划 + 勾选存盘
``__init__.py``（本文件）                对外出口
======================================  ==================================

界面在 ``src/tools/game/nest_sweep/tool.py``，
游戏侧接线在 ``src/tools/game/nest_sweep/okww_task.py``。
"""

from __future__ import annotations

from .catalog import (
    CATALOG_FILE,
    KIND_NAMES,
    KIND_NEST,
    KIND_NIGHTMARE,
    KIND_ORDER,
    SweepTarget,
    catalog_by_kind,
    catalog_path,
    find_target,
    load_catalog,
    parse_catalog,
)
from .plan import (
    SETTINGS_KEY,
    SweepPlan,
    SweepStep,
    build_plan,
    clean_selection,
    load_selection,
    save_selection,
    selected_targets,
    selection_summary,
)

__all__ = [
    "CATALOG_FILE",
    "KIND_NAMES",
    "KIND_NEST",
    "KIND_NIGHTMARE",
    "KIND_ORDER",
    "SETTINGS_KEY",
    "SweepPlan",
    "SweepStep",
    "SweepTarget",
    "build_plan",
    "catalog_by_kind",
    "catalog_path",
    "clean_selection",
    "find_target",
    "load_catalog",
    "load_selection",
    "parse_catalog",
    "save_selection",
    "selected_targets",
    "selection_summary",
]
