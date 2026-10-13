# -*- coding: utf-8 -*-
"""★★ 分辨率无关性 —— 真机首测抓到的第二个 bug 的回归测试。

## 这个 bug 是什么（2026-10-11）

``world_region()`` 原来**按比例裁原图**，裁出来的尺寸跟着分辨率变::

    视频 1280x720   → (510, 1180)
    真机 1536x864   → (612, 1416)

而 ``Locator.phase_shift()`` 里有::

    if a.shape != b.shape:
        return None

→ **游戏分辨率 ≠ 视频分辨率时，相位相关每次必返回 None**，
所有候选被跳过，**定位必定失败**。

⚠ 这个 bug 的恶劣之处在于它**跟内容无关**：就算人站在视频里
一模一样的位置、朝向也一模一样，只要分辨率不同就必然失败。
用户的实际情形正是如此（游戏 1536x864，视频 1280x720）。

## 这里怎么钉

不碰真视频、不依赖 cv2 的相位相关质量 —— 只钉**形状与换算**：

1. ``world_region`` 对任何分辨率都必须给出**同一个形状**
2. ``phase_scale`` 必须把规范尺寸正确换算回本帧像素
3. ``phase_shift`` 对不同分辨率的输入**不能**因为它俩不同就返回 None
4. 裁剪区的宽高比必须恒定（否则缩放会引入形变）
"""

from __future__ import annotations

import pathlib
import sys
import unittest

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.core.explore_gap.descriptor import (  # noqa: E402
    PHASE_CANON,
    crop_box,
    phase_scale,
    world_region,
)
from src.core.explore_gap.locator import Locator  # noqa: E402

#: 真实碰到的几种分辨率（视频源 + 用户真机 + 常见档位）
RESOLUTIONS = [
    (1280, 720),      #: 视频
    (1536, 864),      #: ★ 用户真机 —— 就是它暴露的 bug
    (1920, 1080),
    (2560, 1440),
    (3840, 2160),
]


def blank(w: int, h: int, seed: int = 0):
    """造一张有纹理的假帧（纯色会让描述子返回 None）。"""
    rng = np.random.default_rng(seed)
    small = rng.integers(0, 255, (max(2, h // 40), max(2, w // 40)),
                         dtype=np.uint8)
    import cv2  # noqa: PLC0415

    big = cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)
    return cv2.cvtColor(big, cv2.COLOR_GRAY2BGR)


class TestWorldRegionShape(unittest.TestCase):
    """★ 核心：形状必须与输入分辨率**无关**。"""

    def test_same_shape_for_every_resolution(self):
        shapes = {}
        for w, h in RESOLUTIONS:
            shapes[(w, h)] = world_region(blank(w, h)).shape
        uniq = set(shapes.values())
        self.assertEqual(
            len(uniq), 1,
            f"world_region 的形状跟着分辨率变了：{shapes}\n"
            f"→ phase_shift 会因为它俩 shape 不同而永远返回 None")

    def test_shape_is_the_canonical_one(self):
        for w, h in RESOLUTIONS:
            g = world_region(blank(w, h))
            self.assertEqual((g.shape[1], g.shape[0]), PHASE_CANON,
                             f"{w}x{h} 没缩放到规范尺寸")

    def test_aspect_ratio_is_stable(self):
        """★ 各分辨率的裁剪区宽高比必须一致 —— 否则缩放会引入形变。

        形变会让相位相关量出错误的位移（而且不报错）。
        """
        ratios = []
        for w, h in RESOLUTIONS:
            x0, y0, x1, y1 = crop_box(blank(w, h))
            ratios.append((x1 - x0) / (y1 - y0))
        spread = max(ratios) - min(ratios)
        self.assertLess(spread, 0.01,
                        f"裁剪区宽高比不一致（{ratios}）—— 缩放会形变")

    def test_is_float32_gray(self):
        g = world_region(blank(1280, 720))
        self.assertEqual(g.dtype, np.float32)
        self.assertEqual(g.ndim, 2, "应该是单通道灰度")


class TestPhaseScale(unittest.TestCase):
    """换算：规范尺寸 → 本帧像素。"""

    def test_scale_matches_crop_size(self):
        for w, h in RESOLUTIONS:
            frame = blank(w, h)
            x0, y0, x1, y1 = crop_box(frame)
            sx, sy = phase_scale(frame)
            self.assertAlmostEqual(sx, (x1 - x0) / PHASE_CANON[0], places=6)
            self.assertAlmostEqual(sy, (y1 - y0) / PHASE_CANON[1], places=6)

    def test_bigger_resolution_has_bigger_scale(self):
        """分辨率越高，同样的规范位移对应的真像素越多。"""
        _, s720 = phase_scale(blank(1280, 720))
        _, s1080 = phase_scale(blank(1920, 1080))
        self.assertGreater(s1080, s720)

    def test_720p_scale_is_one(self):
        """1280x720 的裁剪区正好是规范尺寸 —— 换算系数应为 1。"""
        sx, sy = phase_scale(blank(1280, 720))
        self.assertAlmostEqual(sx, 1.0, places=6)
        self.assertAlmostEqual(sy, 1.0, places=6)


class TestPhaseShiftCrossResolution(unittest.TestCase):
    """★ 最直接的回归：不同分辨率**不能**再直接返回 None。

    ⚠ 判据要挑**内容对齐**的图对。
    随机纹理的假图在跨分辨率时可能量出一个很大的位移
    （实测 408px），那会撞上 ``MAX_SHIFT=400`` 而返回 None ——
    那是**位移超界**的正常拒绝，不是分辨率 bug。
    所以这里让被比较的两张图**内容一致**（同一张图缩放而来），
    这样"形状/换算"是唯一的变量。
    """

    @staticmethod
    def _pair(w: int, h: int, seed: int = 5):
        """同一画面，渲染成两种分辨率（都是 BGR 三通道）。"""
        import cv2  # noqa: PLC0415

        rng = np.random.default_rng(seed)
        small = rng.integers(0, 255, (18, 32), dtype=np.uint8)
        gray = cv2.resize(small, (1280, 720), interpolation=cv2.INTER_NEAREST)
        base = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

        def render(width, height):
            return cv2.resize(base, (width, height),
                              interpolation=cv2.INTER_LINEAR)

        return render(w, h), render(1280, 720)

    def test_different_resolutions_still_correlate(self):
        """修 bug 之前这里必然 None（形状不同）。"""
        higher, video = self._pair(1536, 864)
        loc = Locator(library=None)
        out = loc.phase_shift(video, higher)
        self.assertIsNotNone(
            out, "不同分辨率又返回 None 了 —— 分辨率 bug 回归")

    def test_same_content_cross_resolution_shift_is_small(self):
        """★ 同一画面的两种分辨率 → 位移应该接近 0。"""
        higher, video = self._pair(1536, 864)
        loc = Locator(library=None)
        out = loc.phase_shift(video, higher)
        self.assertIsNotNone(out)
        dx, dy, _peak = out
        self.assertLess(abs(dx), 30.0,
                        f"同一画面跨分辨率的位移不该这么大：dx={dx}")
        self.assertLess(abs(dy), 30.0,
                        f"同一画面跨分辨率的位移不该这么大：dy={dy}")

    def test_returns_finite_numbers(self):
        higher, video = self._pair(1920, 1080)
        loc = Locator(library=None)
        out = loc.phase_shift(video, higher)
        self.assertIsNotNone(out, "跨分辨率返回 None")
        dx, dy, peak = out
        self.assertTrue(np.isfinite(dx) and np.isfinite(dy))
        self.assertTrue(np.isfinite(peak))

    def test_same_resolution_still_works(self):
        """别为了修跨分辨率把同分辨率弄坏了。"""
        a = blank(1280, 720, seed=3)
        b = blank(1280, 720, seed=3)
        loc = Locator(library=None)
        out = loc.phase_shift(a, b)
        self.assertIsNotNone(out, "同分辨率的相位相关坏了")
        dx, dy, _ = out
        #: 同内容同分辨率 → 位移应该接近 0
        self.assertLess(abs(dx), 5.0, f"同图位移不该这么大：dx={dx}")
        self.assertLess(abs(dy), 5.0, f"同图位移不该这么大：dy={dy}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
