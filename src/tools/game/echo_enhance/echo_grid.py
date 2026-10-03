# -*- coding: utf-8 -*-
"""声骸列表的**网格几何** + 「下一个未强化声骸在哪」的定位。

## 为什么需要它（3.7 声骸堆叠导致的 bug）

用户 2026-10-02 报："3.7 更新后，更新了声骸堆叠，导致强化好了一个声骸后，
会自动跳到强化好的声骸位置，从而不能继续强化到其他声骸了"。

**根因**（读 ``vendor/okww/okww/task/EnhanceEchoTask.py`` 得出）：

ok-ww 的循环**从不主动选下一个声骸** —— 它假设
"强化完 → ESC 回列表 → 光标还在原位"，于是"下一个"自然就是旁边那个：

    while True:
        enhance = self.find_echo_enhance()   # 右边"培养"按钮在不在
        current_level = self.is_0_level()    # 当前声骸是不是 0 级
        if not current_level:
            return                            # ← 认为干完了，收工
        self.click(enhance)                   # 强化**当前光标**那个

**堆叠打破了这个假设**：强化好的被归类重排，光标被带过去 →
``is_0_level()`` 读到"不是 0 级" → **直接收工**。

**所以不是"不能继续强化"，是它以为干完了。**

## 用户确认的约束

> 滚动不能移动光标，上下左右也不能，**只能通过鼠标选择移动光标**

→ **唯一的办法就是算出格子坐标，点它。**

## 判据：卡片左下的**层叠图标**

卡片底部只有两种形态：

* **层叠图标 + 数字** → 数字是**持有数量**（未强化）
* **只有 ``+N``** → 是**强化等级**（已强化）

实测（两张截图 × 18 格，走 ok-ww 的 ``find_one`` 路径）：

========================  ==========================
未强化（有图标）           已强化（无图标）
========================  ==========================
**0.887 ~ 1.000**         **0.047 ~ 0.085**
========================  ==========================

完全不重叠 —— 比 OCR 判 ``+N`` 可靠得多。

## ⚠⚠ 踩过的坑：搜索框必须比模板大（``SEARCH_PAD``）

实测（18 格逐格）：

======================  ==========  ==========
配置                     漏检格数    未强化最低分
======================  ==========  ==========
放大模板 + pad0          **7 格**     0.321
原尺寸 + pad0            **7 格**     0.321
原尺寸 + **pad6**        **0 格**     **0.887**
======================  ==========  ==========

**元凶是 pad**：每张卡的图标位置有 1~2 像素偏差，而
``cv2.matchTemplate`` 在"搜索图尺寸 == 模板尺寸"时**只产出一个值**，
没有滑动余地 → 偏一点就崩。

## ★ 坐标系：**统一用 1280x720（基准）**

所有几何常量都是在这个分辨率下从截图量的。
需要换算时**只做一件事**：

* 点格子 → 用**相对坐标**（0~1）—— 天然与分辨率无关
* 找图标 → 把基准坐标交给 ``box_of_screen_scaled``，**它自己会缩放**

⚠ 我第一版自己在 :class:`Grid` 里乘了一个 scale，又交给
``box_of_screen_scaled`` —— **双重缩放**。现在去掉，交给 ok-ww 一个地方做。

本模块是**纯几何**，不碰 UI，方便单测（见 ``tests/test_echo_grid.py``）。
"""

from __future__ import annotations

#: ★ 网格参数 —— 全部在 **1280x720** 下从用户截图量出，并画框验证过对齐。
CARD_W = 102.5          # 卡片宽度
CARD_H = 130.0          # 卡片高度
COL_PITCH = 117.5       # 列间距
ROW_PITCH = 139.0       # 行间距
GRID_X0 = 115.0         # 第一列卡片的左沿
GRID_Y0 = 87.5          # 第一排卡片的顶沿

COLS = 6                # 一屏 6 列
ROWS = 3                # 一屏 3 排（用户第二张截图确认）

#: 量这些参数时用的基准分辨率。**所有坐标都在这个尺度下。**
BASE_W, BASE_H = 1280, 720

#: 层叠图标相对**卡片左上角**的偏移 + 尺寸（1280x720 下量的）。
ICON_DX = 9
ICON_DY = 105.5
ICON_W = 22
ICON_H = 18

#: ★★ 搜索框每边多留的像素 —— **必需，不是保险**（见模块说明的实测表）。
SEARCH_PAD = 6

#: 判定阈值。实测未强化 0.887~1.000 / 已强化 0.047~0.085，
#: 0.7 落在中间的空档里，两边都留足余量。
THRESHOLD = 0.7

#: ok-ww 那边注册的模板名（见 ``tools/make_echo_stack_template.py``）。
LABEL = "echo_stack_icon"


def card_center_relative(row: int, col: int) -> tuple[float, float]:
    """第 ``row`` 排第 ``col`` 列卡片的**中心**，返回**相对坐标**（0~1）。

    给 ``click_relative`` 用 —— 相对坐标天然与分辨率无关。

    ⚠ 索引都从 0 起。跟用户报位置时要 +1（"第 5 个"= ``col=4``）。
    """
    x = GRID_X0 + col * COL_PITCH + CARD_W / 2
    y = GRID_Y0 + row * ROW_PITCH + CARD_H / 2
    return x / BASE_W, y / BASE_H


def icon_box_base(row: int, col: int) -> tuple[int, int, int, int]:
    """层叠图标的搜索框 ``(x1, y1, x2, y2)`` —— **基准分辨率坐标**。

    含 :data:`SEARCH_PAD`（必需，见模块说明）。

    ⚠ 返回的是 1280x720 尺度的坐标，交给 ``box_of_screen_scaled`` 时
    要把 ``BASE_W`` / ``BASE_H`` 传成它的"原始分辨率"。
    """
    x1 = GRID_X0 + col * COL_PITCH + ICON_DX - SEARCH_PAD
    y1 = GRID_Y0 + row * ROW_PITCH + ICON_DY - SEARCH_PAD
    x2 = x1 + ICON_W + 2 * SEARCH_PAD
    y2 = y1 + ICON_H + 2 * SEARCH_PAD
    return round(x1), round(y1), round(x2), round(y2)


def slots():
    """按**扫描顺序**（从上到下、从左到右）产出 ``(row, col)``。"""
    for row in range(ROWS):
        for col in range(COLS):
            yield row, col


def find_next_unenhanced(task):
    """★ 找出**下一个未强化**的声骸格子。返回 ``(row, col)``，找不到返回 None。

    :param task: ok-ww 的 task（要能用 ``find_one`` / ``box_of_screen_scaled``）

    ## 判定

    用 ok-ww 现成的 ``find_one`` 找**层叠图标**（``echo_stack_icon``）：

    * 找到 → 这张卡**未强化**（底部显示持有数量）
    * 找不到 → 这张卡**已强化**（底部显示 ``+N``）

    ## 为什么不用 OCR 判 ``+N``

    OCR 慢、且 ``+25`` 那种小字带斜纹底很容易读错。
    图标判据实测区分度 0.887~1.000 vs 0.047~0.085，**完全不重叠**。

    ## 坐标系

    几何常量是 1280x720 下量的；``box_of_screen_scaled(BASE_W, BASE_H, ...)``
    会把它换算到当前屏幕 —— **只在这一处做缩放**，别自己再乘一遍。
    """
    for row, col in slots():
        x1, y1, x2, y2 = icon_box_base(row, col)
        box = task.box_of_screen_scaled(BASE_W, BASE_H, x1, y1, x2, y2,
                                        name="echo_stack_slot")
        if task.find_one(LABEL, box=box, threshold=THRESHOLD):
            return row, col
    return None
