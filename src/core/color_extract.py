# -*- coding: utf-8 -*-
"""★ 壁纸主色提取 —— 让主题配色跟随壁纸。

## 用户 2026-10-31

    > 比如守岸人是偏蓝色的主题，这里却出现了紫色的按钮
    > 按钮变了，但是怎么还是这么亮啊

## 要解决的两件事

**① 配色和壁纸不搭**

主题的 ``primary`` 硬编码成紫色 ``#8B7CFF``，而守岸人壁纸是蓝色 ——
按钮、选中条、徽章全是紫色，看着突兀。

**② 整体偏亮**

DSH 的界面明显比壁纸原色**暗一大截**（它默认有一层 scrim）。
我们压得不够。

## 主色提取算法

1. 缩到 64x64（快）
2. 转 HSV（色相和亮度分离，比 RGB 更符合人眼）
3. **过滤低饱和度和过暗/过亮的像素**（那些是背景/高光，不是主色）
4. 剩余像素按**色相直方图**投票（36 个桶，每 10° 一个）
5. 取最高票的桶，用那些像素的平均饱和度/亮度合成主色
6. 保证足够的亮度/饱和度（否则按钮太暗/太灰）

### 为什么按色相投票

直接平均所有像素 → 得到一片灰（不同颜色混在一起会互相抵消）。
按色相分组投票 → 能挑出"占比最大的那个颜色"，这才是人眼感知的主色。

## 暗化（tint）

``suggest_tint`` 按壁纸平均亮度算暗化不透明度。**下限 0.42** ——
这是照着 DSH 的观感调的（用户拿截图对比过，DSH 明显暗得多）。
"""

from __future__ import annotations

import colorsys
import logging

logger = logging.getLogger(__name__)

#: 提取时缩到多大（越小越快，64 足够统计主色）
SAMPLE = 64

#: 色相直方图的桶数（36 = 每 10°）
HUE_BINS = 36

#: 最低饱和度（低于这个的像素是"灰白"，不算主色）
MIN_SAT = 0.18

#: 最低/最高明度（过滤纯黑和纯白）
MIN_VAL = 0.12
MAX_VAL = 0.96

#: 主色最低亮度（太暗的按钮在暗背景上看不见）
#:
#: 实测守岸人抽到 #2045AA（明度 0.67），当按钮偏暗；
#: 提到 0.75 后是 #3D6BFF 那种亮蓝，看着舒服。
MIN_OUT_VAL = 0.75

#: 主色最低饱和度（太灰的按钮没"品牌感"）
MIN_OUT_SAT = 0.52


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{r:02X}{g:02X}{b:02X}"


def extract_primary(img, *, fallback: str = "#4A9EFF") -> str:
    """从一张 QImage 里提取主色调（返回 ``#RRGGBB``）。

    :param img: ``QImage``（壁纸的一帧）
    :param fallback: 提取失败时用的颜色
    :return: 主色 hex
    """
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QImage

        q = img
        if q is None or q.isNull():
            return fallback
        #: ① 缩小（64x64 足够统计）
        small = q.scaled(
            SAMPLE, SAMPLE,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.FastTransformation)
        small = small.convertToFormat(QImage.Format.Format_RGB32)

        #: ② 按色相投票
        bins = [0] * HUE_BINS
        sums = [(0.0, 0.0, 0.0)] * HUE_BINS
        for y in range(small.height()):
            for x in range(small.width()):
                c = small.pixelColor(x, y)
                r, g, b = c.red(), c.green(), c.blue()
                h, s, v = colorsys.rgb_to_hsv(
                    r / 255.0, g / 255.0, b / 255.0)
                #: 过滤灰白和纯黑纯白
                if s < MIN_SAT or v < MIN_VAL or v > MAX_VAL:
                    continue
                idx = int(h * HUE_BINS) % HUE_BINS
                bins[idx] += 1
                pr, pg, pb = sums[idx]
                sums[idx] = (pr + r, pg + g, pb + b)

        #: ③ 取票最多的桶
        #:
        #: ★★★ 2026-11-01 **加权：让紫色更容易胜出**
        #:
        #: 用户：「坎特蕾拉那个是以紫色为主题，按钮颜色要随之变化」。
        #:
        #: 实测坎特蕾拉抽出 `#5058DB`（H=237°，是**蓝**不是紫）——
        #: 因为画面里蓝色像素（头发/星空）比紫色（衣服/背景）多。
        #:
        #: 但人眼感知上它是紫调的。所以给**紫/品红区间**
        #: （H 250~320°）加权 1.6 倍，让它更容易成为主题色。
        #:
        #: ⚠ 只加 1.6 不是无限 —— 纯蓝壁纸（H~210°）不会被强行拉紫。
        #: ★★★ **按色族竞争**（不是单桶）
        #:
        #: 单独给紫色桶加权重是不够的 —— 紫色的票被**拆散在多个桶**里::
        #:
        #:     坎特蕾拉实测::
        #:       230° 蓝   2053 票
        #:       250° 紫    145 票
        #:       260° 紫    403 票   ← 单桶最多
        #:       270° 紫    183 票
        #:       280° 紫     55 票
        #:
        #: 紫色总票数 786，全给 4.2 倍也只有 403×4.2=1692 < 2053。
        #:
        #: → 改成**色族**：紫族 = 250~320° 加起来（786），
        #:   蓝族 = 200~250°（3192）。
        #:
        #:   ⚠ 实际算：紫 786 × w > 蓝 3192 → **w 必须 > 4.06**。
        #:   （第一版写 2.8 是算错了，蓝仍然赢，所以按钮没变紫。）
        #:
        #: 这样纯蓝壁纸（守岸人 H=224°，紫族票数很少）不会被误判成紫。
        families = {
            "purple": (250, 320),
            "magenta": (320, 345),
            "blue": (200, 250),
            "cyan": (160, 200),
            "green": (70, 160),
            "yellow": (40, 70),
            "orange": (20, 40),
            "red": (345, 360),
        }
        #: 各族权重（人眼对紫/品红更敏感，且用户明确要求紫主题要紫按钮）
        fam_weight = {
            "purple": 4.5,
            "magenta": 2.6,
            "blue": 1.0,
            "cyan": 1.0,
            "green": 1.0,
            "yellow": 1.2,
            "orange": 1.2,
            "red": 1.2,
        }
        fam_votes = {k: 0 for k in families}
        for i in range(HUE_BINS):
            deg = i * (360.0 / HUE_BINS)
            for fam, (lo, hi) in families.items():
                if lo <= deg < hi:
                    fam_votes[fam] += bins[i]
                    break
        #: 选票数×权重最高的族
        best_fam = max(fam_votes,
                       key=lambda k: fam_votes[k] * fam_weight.get(k, 1.0))
        lo, hi = families[best_fam]
        #: 在该族内取票最多的桶
        best = max((i for i in range(HUE_BINS)
                    if lo <= i * (360.0 / HUE_BINS) < hi),
                   key=lambda i: bins[i])
        n = bins[best]
        if n <= 0:
            return fallback
        ar, ag, ab = sums[best]
        r, g, b = ar / n, ag / n, ab / n

        #: ④ 保证亮度和饱和度（否则按钮太暗/太灰）
        h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
        s = max(s, MIN_OUT_SAT)
        v = max(v, MIN_OUT_VAL)
        #: 稍微提亮（按钮要跳出来）
        v = min(0.95, v * 1.15)
        r2, g2, b2 = colorsys.hsv_to_rgb(h, s, v)
        return _rgb_to_hex(int(r2 * 255), int(g2 * 255), int(b2 * 255))
    except Exception:  # noqa: BLE001
        logger.warning("主色提取：失败", exc_info=True)
        return fallback


def average_luma(img) -> float:
    """算一张图的平均亮度（0~1）。用来决定要暗化多少。"""
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QImage

        q = img
        if q is None or q.isNull():
            return 0.5
        small = q.scaled(
            32, 32,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.FastTransformation)
        small = small.convertToFormat(QImage.Format.Format_RGB32)
        total = 0.0
        cnt = 0
        for y in range(small.height()):
            for x in range(small.width()):
                c = small.pixelColor(x, y)
                #: Rec.709 亮度权重
                total += (0.2126 * c.red() + 0.7152 * c.green()
                          + 0.0722 * c.blue()) / 255.0
                cnt += 1
        return total / cnt if cnt else 0.5
    except Exception:  # noqa: BLE001
        return 0.5


def suggest_tint(img, *, base: float = 0.45) -> float:
    """按壁纸亮度建议**暗化层**的不透明度（0.42~0.72）。

    ## ★★★ 2026-10-31 两次调整的历史

    **第一版** ``0.06 + (luma - 0.35) * 0.55`` —— 用户说"没变化"。
    守岸人亮度 0.28，算出 0.02，等于没压。

    **第二版** ``0.28 + (luma - 0.30) * 0.55``、下限 0.26 —— 用户说
    「按钮变了，但是怎么还是这么亮啊」。0.26 视觉上还是偏亮。

    **第三版（现在）** 下限 **0.42**，跟着 DSH 的观感走::

        亮度 0.18 → 0.42
        亮度 0.28 → 0.44      ← 守岸人
        亮度 0.35 → 0.48
        亮度 0.51 → 0.58      ← 爱弥斯
        亮度 0.70 → 0.69

    ## 为什么下限这么高

    DSH 的界面明显比壁纸原色暗一大截 —— 那是它默认的
    "壁纸暗化层"（插件里叫 scrim）。用户拿两张截图对比过，
    DSH 暗得多。**完全不压的话亮壁纸上的文字难读，观感也"太跳"**。
    """
    luma = average_luma(img)
    val = base + (luma - 0.30) * 0.6
    return max(0.42, min(0.72, val))


def derive_dark_bg(primary: str) -> list:
    """按主色生成一组**更暗的**背景渐变 stop（和主色同色相）。

    :param primary: 主色 hex
    :return: ``[(0.0, "#..."), (0.5, "#..."), (1.0, "#...")]``
    """
    try:
        h = primary.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        hh, ss, _vv = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
        #: 背景用**低饱和 + 低亮度**的同色相
        s_bg = min(0.34, max(0.16, ss * 0.42))
        stops = []
        for pos, v in ((0.0, 0.080), (0.5, 0.105), (1.0, 0.058)):
            rr, gg, bb = colorsys.hsv_to_rgb(hh, s_bg, v)
            stops.append((pos, _rgb_to_hex(int(rr * 255), int(gg * 255),
                                           int(bb * 255))))
        return stops
    except Exception:  # noqa: BLE001
        return [(0.0, "#0C0A18"), (0.5, "#141026"), (1.0, "#090713")]
