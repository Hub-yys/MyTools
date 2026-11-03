# -*- coding: utf-8 -*-
"""生成「扫荡残像聚落」的工具图标。

## 为什么用程序画，而不是生成一张图

项目有硬规则（``tests/test_character_build.py::test_all_game_tools_have_icons``）：
**每个工具都要有自定义图标**，风格要统一。实测现有图标的共同规格::

    尺寸   512x512 RGBA
    底     深藏青 #1A1F2B
    边框   圆角方形 + 金色 #DBB96B
    图形   紫色 #8E74F5 线条画

取的是**实测色值**（和其它工具图标同一套），
所以和现有图标放一起不突兀 —— 生成式图片做不到这么稳。

## 图形含义

一张**清单**（三行，右侧各一个勾选框）+ 一条从上往下的**推进箭头** ——
对应工具在做的事：**勾选若干目标，按顺序一个一个刷下去**。

    .venv\\Scripts\\python tools\\make_nest_sweep_icon.py
"""

from __future__ import annotations

import pathlib
import sys

from PIL import Image, ImageDraw

sys.stdout.reconfigure(encoding="utf-8")

#: 实测自 assets/icons/ 现有图标的色值
BG = (26, 31, 43, 255)          # #1A1F2B
GOLD = (219, 185, 107, 255)     # #DBB96B
VIOLET = (142, 116, 245, 255)   # #8E74F5

SIZE = 512
SS = 4                          #: 超采样，缩回来边缘才平滑
S = SIZE * SS

#: 输出落点
OUT = pathlib.Path(__file__).resolve().parents[1] / "assets" / "icons" / "nest_sweep.png"


def main() -> int:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # ── 圆角方底 + 金边（与现有图标同款）
    margin = 8 * SS
    d.rounded_rectangle([margin, margin, S - margin, S - margin],
                        radius=96 * SS, fill=BG, outline=GOLD,
                        width=6 * SS)

    stroke = 20 * SS

    # ── 清单：三行横条（长度递减，像一份清单）
    #    左端起 x=118，右侧留出勾选框的位置
    rows_y = [176, 256, 336]
    widths = [196, 196, 150]
    for y, w in zip(rows_y, widths):
        d.rounded_rectangle([118 * SS, y * SS, (118 + w) * SS, (y + 26) * SS],
                            radius=13 * SS, fill=VIOLET)

    # ── 勾选框：右侧三个小方框 + 前两个打勾
    box_x = 350
    box_size = 48
    #: ⚠ 打勾的线要**比外框细**。第一版用了 ``stroke // 2``（=10px 实际宽度），
    #:   而勾本身只有 25px 宽 —— 粗细一比就糊成一坨，看着像个实心菱形。
    #:   勾的笔画取外框的一半再一半，才看得出是"✓"。
    tick_w = max(1, stroke // 4)
    for index, y in enumerate(rows_y):
        d.rounded_rectangle(
            [box_x * SS, y * SS, (box_x + box_size) * SS, (y + box_size) * SS],
            radius=11 * SS, outline=GOLD, width=stroke // 2)
        if index < 2:
            #: 打勾（两笔）—— 收在框内，四周留出边距
            cx, cy = box_x + box_size // 2, y + box_size // 2
            d.line([(cx - 10) * SS, (cy + 1) * SS, (cx - 3) * SS, (cy + 8) * SS],
                   fill=GOLD, width=tick_w)
            d.line([(cx - 3) * SS, (cy + 8) * SS, (cx + 11) * SS, (cy - 8) * SS],
                   fill=GOLD, width=tick_w)

    # ── ★ 推进箭头：一条向下的竖线 + 箭头，表示"按顺序一个一个刷下去"
    ax = 96
    d.line([ax * SS, 150 * SS, ax * SS, 372 * SS], fill=GOLD, width=stroke)
    d.polygon([(ax * SS, 410 * SS),
               ((ax - 26) * SS, 362 * SS),
               ((ax + 26) * SS, 362 * SS)], fill=GOLD)

    # ── 缩回目标尺寸（超采样降采样）
    out = img.resize((SIZE, SIZE), Image.Resampling.LANCZOS)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.save(OUT)
    print(f"已写出 {OUT} ({out.size[0]}x{out.size[1]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
