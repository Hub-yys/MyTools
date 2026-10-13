# -*- coding: utf-8 -*-
"""「查缺补漏」—— 让机器照视频自动跑路线的核心逻辑。

## 这套东西在做什么

用户 2026-10-11 的原话::

    "不，不需要什么坐标，我只需要你做一件事，查缺补漏"

也就是**视觉伺服**：不建立世界坐标，只持续回答一个可观测的问题::

    我现在屏幕上的画面  ≈  视频第几秒的画面？

对上就继续，没对上就纠回来。**误差不累积**（每帧重新对齐），
这正是它比"照着按键盲放"强的地方。

## 为什么要拆成四个模块

判定逻辑是**会算错**的部分，而算错的表现是"机器照着垃圾值乱走、
把整条路线毁掉"。所以每一层都拆开、都不依赖 Qt、都能单测：

============================  ==========================================
模块                           职责
============================  ==========================================
:mod:`.descriptor`            一帧 → 定长向量（含 UI 遮罩）
:mod:`.library`               参考库：建 / 存 / 读
:mod:`.locator`               ★ 定位 + 测偏离 + **可信度闸门**
:mod:`.controller`            ★ 闭环决策（纯函数：给状态，出动作）
============================  ==========================================

## ★★ 全部参数都是**实测**出来的（2026-10-11）

这些数不是拍脑袋定的，是在 ``_vid/p4.mp4``（27 分钟真实攻略视频）
上量出来的，改动前请先看 ``docs`` 里对应实验的结论：

============================  ==========  ==================================
参数                          实测值       含义
============================  ==========  ==================================
描述子尺寸                    128x72      UI 挖掉后还剩 59% 像素
参考帧间隔                    15 帧       0.5 秒一个；3280 个参考帧
定位命中（非循环）             ——          见下
**可信度闸门 peak**            **0.05**    ★ 低于它 = 测不准，必须放弃
闸门内残差                    中位 0.002px 一步就能纠回来
闸门内最大残差                1.814 px    ≤3px 判据
可用测量占比                  71%
============================  ==========  ==================================

## ⚠⚠ 三条血的教训（都写进代码了，别改回去）

**① 撤销偏离必须用 ``-dx``。**
   第一版写了 ``+dx``，残差**恰好是初始偏离的 200%** —— 2 倍就是
   符号反了的指纹。改对之后残差立刻掉到 0.00 px。

**② 定位对不对是"事后标签"，控制器运行时没有它。**
   所以判据**只能**用运行时拿得到的量（``peak``）。
   拿事后标签算出来的指标再漂亮也没用。

**③ ``peak`` 低的时候**必须**放弃这一帧，而不是照它乱动。**
   大偏离下相位相关会返回垃圾值（实测过 1201.9px 这种）。
   闸门拦住 = "这一帧我看不准"，等下一帧 —— 这是不毁路线的关键。
"""

from __future__ import annotations

from .catalog import (
    VideoEntry,
    build_for,
    forget,
    library_dir,
    library_path_for,
    list_entries,
    sanitize_stem,
    short_hash,
)
from .controller import (
    Action,
    ActionKind,
    ExploreGapConfig,
    ExploreGapState,
    at_end,
    decide,
)
from .descriptor import (
    DH,
    DW,
    MASK,
    PHASE_CANON,
    crop_box,
    descriptor,
    phase_scale,
    world_region,
)
from .keys import (
    KeyEvent,
    KeyPress,
    KeySchedule,
    build_schedule,
    parse_prompt,
)
from .library import ReferenceLibrary, build_library, load_library, save_library
from .locate import (
    ALIGNED_MARGIN_MIN,
    DEFAULT_WINDOW,
    MARGIN_MIN,
    TOP_K,
    locate_aligned,
    locate_windowed,
    should_relax,
)
from .locator import Fix, Locator, peak_gate_ok
from .reader import (
    OCR_SCALES,
    PROMPT_REGION,
    crop_prompt,
    learn_from_ocr,
    prompt_score,
    read_prompt_text,
    read_prompts,
)

__all__ = [
    "ALIGNED_MARGIN_MIN",
    "DH",
    "DW",
    "DEFAULT_WINDOW",
    "MARGIN_MIN",
    "MASK",
    "OCR_SCALES",
    "PHASE_CANON",
    "PROMPT_REGION",
    "TOP_K",
    "Action",
    "ActionKind",
    "ExploreGapConfig",
    "ExploreGapState",
    "Fix",
    "KeyEvent",
    "crop_box",
    "KeyPress",
    "KeySchedule",
    "Locator",
    "ReferenceLibrary",
    "VideoEntry",
    "at_end",
    "build_for",
    "build_library",
    "build_schedule",
    "crop_prompt",
    "decide",
    "descriptor",
    "forget",
    "library_dir",
    "library_path_for",
    "learn_from_ocr",
    "list_entries",
    "load_library",
    "locate_aligned",
    "locate_windowed",
    "parse_prompt",
    "peak_gate_ok",
    "phase_scale",
    "prompt_score",
    "read_prompt_text",
    "read_prompts",
    "sanitize_stem",
    "save_library",
    "short_hash",
    "should_relax",
    "world_region",
]

#: 相位相关闸门阈值（实测标定，见模块文档）
PEAK_MIN = 0.05
