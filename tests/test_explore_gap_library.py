# -*- coding: utf-8 -*-
"""参考库 + 描述子的单元测试（**不碰真视频**，用合成数据）。

## 为什么合成数据够用

这里要验的是**结构**：维度对不对、存读往返一不一致、坏文件会不会
被拒绝、时间换算对不对。这些跟"画面长什么样"无关。

真视频那条路径（建库 → 定位 → 纠偏）在
``tests/check_explore_gap_live.py`` 里，那个要几十秒、还需要视频文件，
不适合放进快速单测。

## ★ 为什么维度检查值得单独一条

``REF @ q`` 在维度不符时**会抛异常**，但如果"长度一样、含义不一样"
（比如描述子算法变了但库是旧的），它**不会报错** —— 直接算出错误位置。
这种静默错误比崩溃危险得多，所以 :func:`library_shape_ok` 和
版本号检查都要钉住。
"""

from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402

from src.core.explore_gap.descriptor import (  # noqa: E402
    DH,
    DW,
    MASK,
    descriptor,
)
from src.core.explore_gap.library import (  # noqa: E402
    FORMAT_VERSION,
    REF_STEP,
    ReferenceLibrary,
    library_shape_ok,
    load_library,
    save_library,
)


def fake_library(count: int = 5, *, dim: int | None = None) -> ReferenceLibrary:
    """造一个结构合法的小参考库。"""
    dim = dim or DW * DH
    rng = np.random.default_rng(7)
    m = rng.random((count, dim)).astype(np.float32)
    m /= np.linalg.norm(m, axis=1, keepdims=True)
    return ReferenceLibrary(
        matrix=m,
        frames=np.arange(count, dtype=np.int64) * REF_STEP,
        fps=30.0,
        step=REF_STEP,
        src="F:/fake/video.mp4",
    )


def textured(seed: int = 1, *, lo: int = 0, hi: int = 255):
    """造一张**有纹理**的假画面（灰度落在 ``[lo, hi]``）。

    ⚠ 不能用纯色 / 纯随机噪声：
    * 纯色帧现在**正确地**返回 ``None``（没有任何明暗结构可定位）
    * 纯随机噪声的相邻像素完全不相关，缩放后几乎趋同，
      两张不同种子的噪声图相似度会很高 —— 测不出"分不分得开"

    所以这里造**块状**纹理：先生成小块随机值再放大。
    这样缩放后仍保留大尺度结构，不同种子之间才有区分度，
    也更像真实画面的"地形/建筑"。

    :param lo/hi: 灰度范围。测"调亮不改变描述子"时要留出余量，
        否则 ``convertScaleAbs`` 会截断（那是真的改了内容）。
    """
    rng = np.random.default_rng(seed)
    small = rng.integers(lo, hi + 1, (24, 40), dtype=np.uint8)
    big = cv2.resize(small, (1280, 720), interpolation=cv2.INTER_NEAREST)
    return cv2.cvtColor(big, cv2.COLOR_GRAY2BGR)


class TestMask(unittest.TestCase):
    """遮罩本身要跟实测一致（改了就白测了）。"""

    def test_shape(self):
        self.assertEqual(MASK.shape, (DH, DW))

    def test_keeps_measured_fraction(self):
        """实测保留 59% 像素（5468 个）。"""
        self.assertEqual(int(MASK.sum()), 5468)

    def test_ui_regions_excluded(self):
        """UI 区域必须被挖掉 —— 它们每帧都在变，当特征用等于用噪声。"""
        self.assertFalse(MASK[0:6, :].any(), "顶部图标条没挖掉")
        self.assertFalse(MASK[58:, :].any(), "底部 HUD 没挖掉")
        self.assertFalse(MASK[:, 119:].any(), "右侧队伍图标没挖掉")
        self.assertFalse(MASK[0:30, 0:30].any(), "左上小地图/水印没挖掉")

    def test_world_area_kept(self):
        self.assertTrue(MASK[30, 60], "中间大世界画面应该保留")


class TestDescriptor(unittest.TestCase):
    def test_returns_normalized(self):
        v = descriptor(textured(1))
        self.assertIsNotNone(v)
        self.assertAlmostEqual(float(np.linalg.norm(v)), 1.0, places=5)

    def test_none_frame(self):
        self.assertIsNone(descriptor(None))

    def test_black_frame_returns_none(self):
        """全黑帧归一化是 0/0 —— 必须返回 None，不能返回 NaN 向量。

        NaN 进到 ``REF @ q`` 会让**所有**相似度变 NaN，
        然后 ``argmax`` 返回 0（静默给出错误位置）。
        """
        v = descriptor(np.zeros((720, 1280, 3), dtype=np.uint8))
        self.assertIsNone(v)

    def test_flat_frame_returns_none(self):
        """★ 纯色帧也要返回 None —— 它**没有任何可用于定位的信息**。

        减均值之后纯色帧恒等于全 0，范数为 0。这是**对的行为**：
        一张没有任何明暗结构的图，跟哪个地方都"像"，也跟哪个地方都
        不像 —— 硬要给个向量，它就会在所有候选上拿一样的分，
        等于往定位里灌噪声。
        """
        for level in (0, 77, 128, 255):
            self.assertIsNone(
                descriptor(np.full((720, 1280, 3), level, dtype=np.uint8)),
                f"纯色 {level} 不该给出描述子")

    # ---------------------------------------------------------------- ZNCC
    def test_brightness_change_alone_does_not_change_descriptor(self):
        """★★ 整体调亮/调暗**不该**改变描述子（减均值要消掉的就是它）。

        这是修 bug 之后新获得的性质：原来只做 L2 归一化，
        L2 消得掉乘性差异、消不掉**加性**直流偏移。

        ⚠ 基准图要留在**中间调**（40~200）：``convertScaleAbs`` 会
        在 255 截断，若基准图本来就顶到 255，"调亮"会把高光压平
        —— 那是**真的改变了内容**，不该期望描述子不变。
        （第一版就是这么假失败的：0.9943。）
        """
        a = textured(3, lo=40, hi=200)
        for delta in (15, 55):
            b = cv2.convertScaleAbs(a, alpha=1.0, beta=delta)
            self.assertLessEqual(int(b.max()), 255)
            va, vb = descriptor(a), descriptor(b)
            self.assertIsNotNone(va)
            self.assertIsNotNone(vb)
            self.assertGreater(
                float(va @ vb), 0.999,
                f"亮度 +{delta} 就改变了描述子 —— 直流分量没消干净")

    def test_different_scenes_stay_apart(self):
        """★★ 反证：**内容不同**的画面，分数必须分得开。

        ⚠ 这条就是那个真机 bug 的回归 —— 修之前
        "无关帧"也能拿 0.5~0.8，最高分和中位挤在一起，根本选不出位置。
        """
        a, b = textured(4), textured(5)
        #: 两张都是自然画风的噪声图，内容无关
        self.assertLess(float(descriptor(a) @ descriptor(b)), 0.9,
                        "两张无关画面的相似度太高 —— 度量又退化了")

    def test_ui_only_change_does_not_change_descriptor(self):
        """★ 只改 UI 区域 → 描述子**不该变**（这正是遮罩的用处）。"""
        a = textured(1)
        b = a.copy()
        #: 改血条（底部）和小地图（左上）
        b[690:720, 400:900] = 255
        b[0:200, 0:260] = 0
        va, vb = descriptor(a), descriptor(b)
        self.assertIsNotNone(va)
        self.assertIsNotNone(vb)
        self.assertGreater(float(va @ vb), 0.9999,
                           "UI 变化影响了描述子 —— 遮罩没生效")

    def test_world_change_does_change_descriptor(self):
        """反证：大世界画面变了，描述子**必须**变（否则根本没法定位）。"""
        a = textured(2)
        b = a.copy()
        b[200:600, 300:1000] = 0                 #: 改大世界区域
        va, vb = descriptor(a), descriptor(b)
        self.assertLess(float(va @ vb), 0.999,
                        "大世界画面变了描述子却没变 —— 遮罩挖多了")

    def test_dimension(self):
        v = descriptor(textured(6))
        self.assertEqual(v.shape, (DW * DH,))

    def test_mask_outside_is_zero(self):
        """★ 遮罩外必须是 0 —— 均值只在遮罩内求、也只在遮罩内减。

        ⚠ 若对整个向量求均值，遮罩外那 41% 的 0 会稀释均值、
        减完在遮罩外留下一个非零常数 —— 那块本来不该有任何贡献。
        """
        v = descriptor(textured(7))
        self.assertEqual(float(np.abs(v[~MASK.ravel()]).max()), 0.0,
                         "遮罩外出现非零值 —— 均值减错了范围")


class TestLibraryStructure(unittest.TestCase):
    def test_len_and_time(self):
        lib = fake_library(5)
        self.assertEqual(len(lib), 5)
        self.assertAlmostEqual(lib.time_of(0), 0.0)
        self.assertAlmostEqual(lib.time_of(2), 1.0)      #: 2*15/30
        self.assertTrue(np.isnan(lib.time_of(99)))
        self.assertTrue(np.isnan(lib.time_of(-1)))

    def test_shape_ok(self):
        self.assertTrue(library_shape_ok(fake_library(3)))

    def test_shape_rejects_wrong_dim(self):
        """维度不对要能查出来 —— 否则匹配会静默给出错误位置。"""
        bad = fake_library(3, dim=DW * DH - 1)
        self.assertFalse(library_shape_ok(bad))

    def test_shape_rejects_length_mismatch(self):
        lib = fake_library(3)
        lib.frames = np.asarray([1, 2], dtype=np.int64)   #: 帧数对不上
        self.assertFalse(library_shape_ok(lib))

    def test_custom_fps_time(self):
        lib = fake_library(2)
        lib.fps = 60.0
        self.assertAlmostEqual(lib.time_of(1), 15 / 60.0)


class TestLibraryPersistence(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_round_trip(self):
        lib = fake_library(6)
        path = self.dir / "ref.npz"
        save_library(lib, path)
        self.assertTrue(path.is_file())

        got = load_library(path)
        np.testing.assert_allclose(got.matrix, lib.matrix)
        np.testing.assert_array_equal(got.frames, lib.frames)
        self.assertAlmostEqual(got.fps, lib.fps)
        self.assertEqual(got.step, lib.step)
        self.assertEqual(got.src, lib.src)
        self.assertTrue(library_shape_ok(got))

    def test_creates_parent_dir(self):
        lib = fake_library(2)
        path = self.dir / "sub" / "deep" / "ref.npz"
        save_library(lib, path)
        self.assertTrue(path.is_file())

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            load_library(self.dir / "nope.npz")

    def test_corrupt_file_raises(self):
        path = self.dir / "bad.npz"
        path.write_bytes(b"this is not an npz file at all")
        with self.assertRaises(RuntimeError) as ctx:
            load_library(path)
        self.assertIn("读不出来", str(ctx.exception))

    def test_wrong_version_rejected(self):
        """★ 版本不认识时**必须报错**，不能"尽力而为"。

        描述子算法改过之后，旧库去匹配会**静默给出错误位置** ——
        比读不出来危险得多（机器会照着错位置走）。
        """
        path = self.dir / "old.npz"
        np.savez_compressed(
            path,
            version=np.asarray(FORMAT_VERSION + 1),
            matrix=fake_library(2).matrix,
            frames=np.asarray([0, 15], dtype=np.int64),
            fps=np.asarray(30.0),
            step=np.asarray(15, dtype=np.int64),
            src=np.asarray("x"),
        )
        with self.assertRaises(RuntimeError) as ctx:
            load_library(path)
        self.assertIn("版本", str(ctx.exception))

    def test_no_temp_file_left_behind(self):
        """存盘用"先写临时再 replace" —— 不该留下 .tmp。"""
        lib = fake_library(2)
        path = self.dir / "ref.npz"
        save_library(lib, path)
        leftovers = [p.name for p in self.dir.iterdir() if ".tmp" in p.name]
        self.assertEqual(leftovers, [], f"留下了临时文件：{leftovers}")

    def test_frame_image_on_missing_video(self):
        """源视频不在 → 取原图返回 None（不该抛）。"""
        lib = fake_library(2)
        lib.src = str(self.dir / "no-such-video.mp4")
        self.assertIsNone(lib.frame_image(0))

    def test_frame_image_out_of_range(self):
        lib = fake_library(2)
        self.assertIsNone(lib.frame_image(99))
        self.assertIsNone(lib.frame_image(-1))

    def test_close_is_idempotent(self):
        lib = fake_library(2)
        lib.close()
        lib.close()                               #: 再关一次不该炸


if __name__ == "__main__":
    unittest.main(verbosity=2)
