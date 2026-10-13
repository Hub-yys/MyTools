# -*- coding: utf-8 -*-
"""★ 取原图的 LRU 缓存 —— 性能修复的回归测试。

## 为什么加这个缓存（2026-10-11 真机实测）

回源视频 seek 取一帧**极慢**：实测 **3087 ms**（232MB 的 mp4，
顺序读只要 11.7 ms/帧）。而 ``locate_aligned`` 对 top_k(=5) 个候选
各取一次原图 → ``Locator.measure()`` **23 秒**。

闭环需要 ~10 次/秒（100ms）才能跟住走路 —— **慢 230 倍**。

加缓存后实测 **23487ms → 528ms**（冷启动那一次仍然慢，之后命中内存）。

## 这里钉什么

缓存是**容易写错**的东西（淘汰逻辑、命中后顺序、清空时机），
所以必须单测盖住 —— 它出错的后果是"拿到别的帧的原图"，
**不会报错**，只会让定位悄悄变差。
"""

from __future__ import annotations

import pathlib
import sys
import unittest

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.core.explore_gap.library import (  # noqa: E402
    DEFAULT_FRAME_CACHE,
    ReferenceLibrary,
    _FrameCache,
)


class TestFrameCacheUnit(unittest.TestCase):
    """``_FrameCache`` 本身（纯逻辑，不碰视频）。"""

    def test_put_and_get(self):
        c = _FrameCache(4)
        c.put(10, "a")
        self.assertEqual(c.get(10), "a")

    def test_miss_returns_none(self):
        c = _FrameCache(4)
        self.assertIsNone(c.get(999))

    def test_evicts_oldest_when_full(self):
        c = _FrameCache(3)
        for i in range(3):
            c.put(i, f"v{i}")
        c.put(3, "v3")                 #: 挤掉 0
        self.assertIsNone(c.get(0), "最旧的没被淘汰")
        self.assertEqual(c.get(3), "v3")

    def test_get_refreshes_recency(self):
        """★ 命中要刷新"最近使用" —— 否则 LRU 退化成 FIFO。"""
        c = _FrameCache(3)
        for i in range(3):
            c.put(i, f"v{i}")
        c.get(0)                       #: 0 变成最新
        c.put(3, "v3")                 #: 该挤掉 1（而不是 0）
        self.assertEqual(c.get(0), "v0", "命中没刷新最近使用顺序")
        self.assertIsNone(c.get(1))

    def test_overwrite_same_key(self):
        c = _FrameCache(3)
        c.put(5, "old")
        c.put(5, "new")
        self.assertEqual(c.get(5), "new")
        self.assertEqual(len(c._order), 1, "重复 put 把顺序写重复了")

    def test_clear(self):
        c = _FrameCache(4)
        c.put(1, "a")
        c.clear()
        self.assertIsNone(c.get(1))

    def test_capacity_at_least_one(self):
        c = _FrameCache(0)
        c.put(1, "a")
        self.assertEqual(c.get(1), "a")

    def test_never_exceeds_capacity(self):
        c = _FrameCache(5)
        for i in range(50):
            c.put(i, i)
        self.assertLessEqual(len(c._data), 5)
        self.assertLessEqual(len(c._order), 5)


class TestLibraryFrameCache(unittest.TestCase):
    """库这一层：缓存不能改变**取到的内容**。"""

    @staticmethod
    def _lib(tmpdir: str, count: int = 6, fps: float = 30.0):
        """造一个库，并记下"每个帧号应该长什么样"。

        ⚠ 视频里**只有 count 帧**，所以 ``frames`` 必须是
        ``0..count-1`` —— 不能照真实库那样乘 ``REF_STEP``，
        否则 ``frame_image_at`` 会 seek 到不存在的帧号，
        ``cap.read()`` 返回 False → ``frame_image`` 给 ``None``。
        （第一版就是这么假失败的。）
        """
        import cv2

        path = pathlib.Path(tmpdir) / "v.mp4"
        w, h = 320, 180
        vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"),
                             fps, (w, h))
        for i in range(count):
            #: 每帧一个独特的纯色块图案（确定性强，好断言）
            img = np.full((h, w, 3), i * 20 % 256, dtype=np.uint8)
            img[:, i * 20 % w:(i * 20 % w) + 20] = 255
            vw.write(img)
        vw.release()

        lib = ReferenceLibrary(
            matrix=np.zeros((count, 128 * 72), dtype=np.float32),
            #: ★ 帧号 0..count-1（视频真的只有这么多帧）
            frames=np.arange(count, dtype=np.int64),
            fps=fps, step=1, src=str(path),
        )
        return lib

    def test_cached_read_matches_first_read(self):
        """★ 命中的结果必须和第一次取到的一模一样。"""
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            lib = self._lib(td)
            try:
                a = lib.frame_image(2)
                b = lib.frame_image(2)          #: 这次应该是缓存命中
                self.assertIsNotNone(a)
                self.assertIsNotNone(b)
                self.assertTrue(np.array_equal(a, b),
                                "缓存命中的图和第一次取到的不一样")
            finally:
                lib.close()

    def test_different_indices_differ(self):
        """★ 缓存不能把**不同帧号**串味。"""
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            lib = self._lib(td)
            try:
                imgs = [lib.frame_image(i) for i in range(4)]
                for i in range(4):
                    self.assertIsNotNone(imgs[i], f"第 {i} 帧取不到")
                #: 再取一遍（全部命中缓存），结果必须一样
                again = [lib.frame_image(i) for i in range(4)]
                for i in range(4):
                    self.assertTrue(np.array_equal(imgs[i], again[i]),
                                    f"第 {i} 帧缓存命中后内容变了")
                #: 相邻两帧不该相同（造的数据每帧都不一样）
                self.assertFalse(np.array_equal(imgs[0], imgs[1]),
                                 "造的数据有问题：相邻帧一样")
            finally:
                lib.close()

    def test_eviction_does_not_corrupt(self):
        """★ 超过容量后仍要取到**正确**的图（淘汰不能串味）。"""
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            lib = self._lib(td, count=10)
            lib._frame_cache_size = 3        #: 逼它频繁淘汰
            try:
                want = {}
                for i in range(10):
                    want[i] = lib.frame_image(i)
                #: 再按乱序取一遍，全部要和第一次一致
                for i in (9, 0, 5, 2, 7, 1):
                    got = lib.frame_image(i)
                    self.assertTrue(np.array_equal(want[i], got),
                                    f"第 {i} 帧在淘汰后取到了错的内容")
            finally:
                lib.close()

    def test_close_clears_cache(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            lib = self._lib(td)
            lib.frame_image(1)
            self.assertIsNotNone(lib._cache)
            lib.close()
            self.assertIsNone(lib._cache.get(1), "close() 之后缓存没清")

    def test_default_capacity_is_sane(self):
        """容量要够用（>=5 个候选）又不能吃爆内存。"""
        self.assertGreaterEqual(DEFAULT_FRAME_CACHE, 16)
        #: 每帧 ~2.7MB（1280x720x3），别超过 ~500MB
        self.assertLessEqual(DEFAULT_FRAME_CACHE * 2.7, 500)


if __name__ == "__main__":
    unittest.main(verbosity=2)
