# -*- coding: utf-8 -*-
"""生成「查缺补漏」的工具图标。

## 为什么用程序画，而不是生成一张图

项目有硬规则（``tests/test_character_build.py::test_all_game_tools_have_icons``）：
**每个工具都要有自定义图标**，风格要统一。实测现有图标的共同规格::

    尺寸   512x512 RGBA
    底     深藏青 #1A1F2B
    边框   圆角方形 + 金色 #DBB96B
    图形   紫色 #8E74F5 线条画

取的是**实测色值**，所以和现有图标放一起不突兀 —— 生成式图片做不到这么稳。

## 图形含义

一个"取景框"套着一个**播放三角**，旁边一条**对齐刻度线** ——
对应工具在做的事：把当前画面**对到**视频的某一帧上。

    .venv\\Scripts\\python tools\\make_explore_gap_icon.py
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


def main() -> int:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # ── 圆角方底 + 金边（与现有图标同款）
    margin = 8 * SS
    d.rounded_rectangle([margin, margin, S - margin, S - margin],
                        radius=96 * SS, fill=BG, outline=GOLD,
                        width=6 * SS)

    stroke = 20 * SS

    # ── 取景框（四角括号，比整框更像"取景/对齐"）
    fx0, fy0 = int(S * 0.20), int(S * 0.24)
    fx1, fy1 = int(S * 0.80), int(S * 0.68)
    arm = int(S * 0.10)
    #: 左上
    d.line([fx0, fy0, fx0 + arm, fy0], fill=VIOLET, width=stroke)
    d.line([fx0, fy0, fx0, fy0 + arm], fill=VIOLET, width=stroke)
    #: 右上
    d.line([fx1 - arm, fy0, fx1, fy0], fill=VIOLET, width=stroke)
    d.line([fx1, fy0, fx1, fy0 + arm], fill=VIOLET, width=stroke)
    #: 左下
    d.line([fx0, fy1, fx0 + arm, fy1], fill=VIOLET, width=stroke)
    d.line([fx0, fy1 - arm, fx0, fy1], fill=VIOLET, width=stroke)
    #: 右下
    d.line([fx1 - arm, fy1, fx1, fy1], fill=VIOLET, width=stroke)
    d.line([fx1, fy1 - arm, fx1, fy1], fill=VIOLET, width=stroke)

    # ── 播放三角（"视频"）
    cx, cy = int(S * 0.475), int(S * 0.46)
    r = int(S * 0.115)
    d.polygon([(cx - r * 0.75, cy - r),
               (cx - r * 0.75, cy + r),
               (cx + r * 0.95, cy)], fill=VIOLET)

    # ── 底部对齐刻度（"对齐/纠偏"）
    ty = int(S * 0.795)
    d.line([int(S * 0.26), ty, int(S * 0.74), ty],
           fill=VIOLET, width=14 * SS)
    #: 中间那个刻度和"当前偏移"标记
    d.line([int(S * 0.50), ty - int(S * 0.045),
            int(S * 0.50), ty + int(S * 0.045)],
           fill=VIOLET, width=18 * SS)
    #: 偏右的标记（画面偏了，要纠回来）
    mx = int(S * 0.635)
    d.ellipse([mx - 15 * SS, ty - 15 * SS, mx + 15 * SS, ty + 15 * SS],
              fill=VIOLET)

    img = img.resize((SIZE, SIZE), Image.LANCZOS)
    out = (pathlib.Path(__file__).resolve().parents[1]
           / "assets" / "icons" / "explore_gap.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    print(f"已写出 {out}  ({out.stat().st_size} 字节)")
    print(f"尺寸 {img.size}  模式 {img.mode}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
