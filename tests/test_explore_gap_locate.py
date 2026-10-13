# -*- coding: utf-8 -*-
"""连续性约束 + 独特性门槛的单元测试（**不碰真视频**）。

## 这两条约束堵的是什么洞

实测（2026-10-11，192 个样本）只靠相位相关闸门**不够**::

    只用闸门    : 危险格 5   定位跑飞 23%
    连续性+余量 : 危险格 0   定位跑飞  0%

最恶劣的一例："一帧之内从视频 10 分钟处跳到 21 分钟处"（差 1272 个
参考帧），但 ``peak=0.057`` 越过了 0.05 的闸门 —— 因为**别处的画面
也能对得很齐**。于是它给出的 ``dx=+0.2``（真值 +60）会被采信，
机器朝完全错误的方向纠偏。

**闸门量的是"对齐质量"，连续性和余量量的是"位置合不合理"，
两个信号管两件事，缺一不可。**

## 这里怎么测（不依赖真视频）

用一个**人造的、位置特征明确**的库：每个参考帧是一张纯色小图，
颜色按帧号渐变。这样"正确的帧"是唯一确定的，能精确验证
"窗口有没有生效、余量对不对"。
"""

from __future__ import annotations

import pathlib
import sys
import unittest

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.core.explore_gap.descriptor import DW, DH  # noqa: E402
from src.core.explore_gap.library import ReferenceLibrary  # noqa: E402
from src.core.explore_gap.locate import (  # noqa: E402
    ALIGNED_MARGIN_MIN,
    DEFAULT_WINDOW,
    MARGIN_MIN,
    TOP_K,
    locate_aligned,
    locate_windowed,
    should_relax,
)


def unit(vec) -> np.ndarray:
    """把向量归一化（库和查询都必须是单位向量 —— 点积才是余弦）。"""
    v = np.asarray(vec, dtype=np.float32)
    n = float(np.linalg.norm(v))
    return v / n if n > 0 else v


#: 传给 ``margin_min`` 表示"不拒绝任何结果"。
#:
#: 余量可以**为负**（最佳匹配还不如远处的某帧像），所以"关闭门槛"
#: 得用一个比任何可能余量都小的数，而不是 0.0 —— 用 0.0 会把
#: 负余量的情况也拒掉，那正是这组边界用例被误伤的原因。
_NEVER_REJECT = -9.0


def ramp_library(count: int = 200) -> ReferenceLibrary:
    """人造库：第 i 帧的方向沿一条正交基渐变。

    任意两帧都不相同，且"距离越近越像" —— 正好能验窗口。
    """
    dim = DW * DH
    rng = np.random.default_rng(11)
    basis = rng.normal(size=(count, dim)).astype(np.float32)
    #: 让相邻帧相似（沿基缓慢走），远处帧几乎正交
    m = np.zeros((count, dim), dtype=np.float32)
    walk = np.zeros(dim, dtype=np.float32)
    for i in range(count):
        walk = 0.85 * walk + 0.15 * basis[i]
        m[i] = walk
    m = np.stack([unit(r) for r in m])
    return ReferenceLibrary(matrix=m,
                            frames=np.arange(count, dtype=np.int64) * 15,
                            fps=30.0)


class TestFarMargin(unittest.TestCase):
    """独特性余量 = 最佳 减 **远处**第二名。"""

    def test_identical_is_high_margin(self):
        """查询就是库里的某一帧 → 余量应该很大（同帧相似度 1.0）。"""
        lib = ramp_library(120)
        got = locate_windowed(lib, None, near=None) if False else None
        #: 直接查库向量本身（绕过图像），用矩阵点积验证余量逻辑
        from src.core.explore_gap.locate import _far_margin
        sims = lib.matrix @ lib.matrix[40]
        margin = _far_margin(sims, 40, exclude=20)
        self.assertGreater(margin, 0.0, "自己跟自己比，余量必须为正")

    def test_near_duplicates_excluded(self):
        """近处的相似帧**不参与**余量计算（相邻帧本来就该像）。"""
        from src.core.explore_gap.locate import _far_margin
        #: 造一个"第 0 帧和第 1 帧几乎一样，远处差很多"的相似度数组
        sims = np.array([0.99, 0.989, 0.30, 0.20, 0.10], dtype=np.float32)
        margin = _far_margin(sims, best=0, exclude=20)
        #: 排除半径比数组还长 → 没有"远处" → 退化成返回最佳值本身
        self.assertAlmostEqual(float(margin), 0.99)

    def test_all_near_falls_back_to_best(self):
        from src.core.explore_gap.locate import _far_margin
        sims = np.array([0.5, 0.4, 0.3], dtype=np.float32)
        self.assertAlmostEqual(float(_far_margin(sims, 1, exclude=20)), 0.4)


class TestWindowBounds(unittest.TestCase):
    """窗口的边界处理 —— 越界是最容易出错的地方。"""

    def setUp(self):
        self.lib = ramp_library(200)

    def test_none_frame_returns_none(self):
        self.assertIsNone(locate_windowed(self.lib, None, near=10))

    def test_empty_library_returns_none(self):
        empty = ReferenceLibrary(matrix=np.zeros((0, DW * DH), dtype=np.float32),
                                 frames=np.zeros((0,), dtype=np.int64))
        self.assertIsNone(locate_windowed(empty, None, near=0))

    def test_window_zero_means_full_search(self):
        """``window=0`` = 明确要求全库搜（关掉连续性约束）。

        验的是**不崩且给出结果**，不是匹配质量（合成图不保证质量，
        见 :func:`_img_for`）。
        """
        rows = locate_windowed(self.lib, _img_for(self.lib, 5), near=5,
                               window=0, margin_min=_NEVER_REJECT)
        self.assertIsNotNone(rows)

    def test_window_at_library_start(self):
        """``near`` 在库开头 → 窗口要夹在 [0, ...]，不能出负下标。"""
        rows = locate_windowed(self.lib, _img_for(self.lib, 3), near=3,
                               window=10, margin_min=_NEVER_REJECT)
        self.assertIsNotNone(rows)
        self.assertGreaterEqual(rows[0], 0)
        self.assertLess(rows[0], len(self.lib))

    def test_window_at_library_end(self):
        """``near`` 在库末尾 → 窗口要夹在 [..., len)，不能越界。"""
        last = len(self.lib) - 1
        rows = locate_windowed(self.lib, _img_for(self.lib, last), near=last,
                               window=10, margin_min=_NEVER_REJECT)
        self.assertIsNotNone(rows)
        self.assertLess(rows[0], len(self.lib))

    def test_near_out_of_range_falls_back(self):
        """``near`` 远超出库长 → 退回全库搜（而不是崩 / 空窗口）。"""
        rows = locate_windowed(self.lib, _img_for(self.lib, 5), near=99999,
                               window=10, margin_min=_NEVER_REJECT)
        self.assertIsNotNone(rows, "越界 near 应该退回全库搜")
        self.assertLess(rows[0], len(self.lib))


def _img_for(lib: ReferenceLibrary, index: int):
    """把库里的某一行向量"还原"成一张图，好走完整的定位路径。

    ⚠ 这只是为了让 locate_windowed 能跑完整条路（它要图像）。
    描述子里的 mask / resize / 灰度是不可逆的，所以造出来的图
    与库里的向量**不会**完全一致 —— 因此这些用例都传
    ``margin_min=0.0``，只验**窗口边界行为**，不验匹配质量。
    """
    import cv2                                       # noqa: PLC0415

    img = np.zeros((720, 1280, 3), dtype=np.uint8)
    #: 用与描述子一致的降采样尺寸铺一层可控的图案
    small = (lib.matrix[index] * 40 + 128).astype(np.uint8)
    small = small.reshape(DH, DW)
    big = cv2.resize(small, (1280, 720), interpolation=cv2.INTER_NEAREST)
    img[:, :, 0] = big
    img[:, :, 1] = big
    img[:, :, 2] = big
    return img


class TestMarginGate(unittest.TestCase):
    """独特性门槛：认不准就返回 None（当没测到）。"""

    def test_gate_constant_is_positive(self):
        self.assertGreater(MARGIN_MIN, 0.0)

    def test_impossible_margin_rejects(self):
        """门槛高到不可能达到 → 一律返回 None（而不是硬给一个答案）。"""
        lib = ramp_library(60)
        got = locate_windowed(lib, _img_for(lib, 10), near=10,
                              margin_min=2.0)      #: 余弦相似度差不可能到 2.0
        self.assertIsNone(got, "门槛没过必须返回 None，不能硬给结果")


class TestRelax(unittest.TestCase):
    """跟丢之后的放宽策略。"""

    def test_no_relax_at_zero(self):
        self.assertFalse(should_relax(0))

    def test_relax_periodic(self):
        self.assertTrue(should_relax(5))
        self.assertTrue(should_relax(10))
        self.assertFalse(should_relax(3))

    def test_custom_period(self):
        self.assertTrue(should_relax(3, after=3))
        self.assertFalse(should_relax(1, after=3))

    def test_default_window_is_reasonable(self):
        """窗口要小到能挡跳飞、大到容得下正常行走。"""
        self.assertGreaterEqual(DEFAULT_WINDOW, 10)
        self.assertLessEqual(DEFAULT_WINDOW, 100)


class TestLocatorState(unittest.TestCase):
    """``Locator`` 的连续性状态机（不喂图，只验状态迁移）。"""

    def setUp(self):
        self.lib = ramp_library(80)
        from src.core.explore_gap import Locator
        self.Locator = Locator

    def test_near_starts_none(self):
        loc = self.Locator(self.lib)
        self.assertIsNone(loc.near, "起点没有上一帧 —— 必须允许全库搜")

    def test_reseat_sets_near(self):
        loc = self.Locator(self.lib)
        loc.reseat(30)
        self.assertEqual(loc.near, 30)
        self.assertEqual(loc.unclear_streak, 0)

    def test_reseat_none_clears(self):
        loc = self.Locator(self.lib)
        loc.reseat(30)
        loc.reseat(None)
        self.assertIsNone(loc.near)

    def test_failed_measure_keeps_near(self):
        """★ 一次没认出来**不该**清空 near。

        清空会退化成全库搜、把之前积累的约束丢掉 —— 而偶发认不出
        是正常的（实测可用率 92%，约每 12 帧就有 1 帧认不出）。
        """
        loc = self.Locator(self.lib)
        loc.reseat(25)
        loc.measure(None)                            #: 必然失败
        self.assertEqual(loc.near, 25, "失败不该清空连续性锚点")
        self.assertEqual(loc.unclear_streak, 1, "失败要计数")

    def test_streak_grows_then_triggers_relax(self):
        loc = self.Locator(self.lib)
        loc.reseat(25)
        for _ in range(5):
            loc.measure(None)
        self.assertEqual(loc.unclear_streak, 5)
        self.assertTrue(should_relax(loc.unclear_streak),
                        "连续 5 次失败后该放宽一次")

    def test_window_and_margin_defaults_exposed(self):
        loc = self.Locator(self.lib)
        self.assertEqual(loc.window, DEFAULT_WINDOW)
        #: ★ ``Locator`` 用的是**对齐后**的余量门槛（``ALIGNED_MARGIN_MIN``），
        #: 不是原始相似度的那个（``MARGIN_MIN``）—— 两者量纲不同:
        #: 对齐后的分差普遍更大（实测中位 0.064 vs 0.015），
        #: 拿原始门槛去卡对齐后的分，会把好结果全拒掉。
        self.assertEqual(loc.margin_min, ALIGNED_MARGIN_MIN)


class TestLocateAligned(unittest.TestCase):
    """★ 「先对齐再打分」—— 大偏航下救回定位的那一招。

    ## 为什么它是必需的

    相关型描述子**不是平移不变的**。画面横移 80px 时，**真值那一帧**的
    相似度从 0.99 掉到 0.93，而别处的帧本来就在 0.92 —— 余量被压没，
    于是认不出地方。实测命中率：80px 偏航下只有 **18%**。

    把候选"搬回去"再打分就恢复平移不变了，同条件 **100%**。

    ## 这批测试怎么做到不碰真图

    ``locate_aligned`` 的两个外部依赖都**可注入**::

        phase_shift   相位相关（喂假的，直接给已知位移）
        library.frame_image / descriptor / cv2.warpAffine
                      —— 这几条用**真实的**（合成图就够，因为
                      这里验的是"选谁"，不是"匹配得多准"）

    为了让"搬回去之后分数变高"这件事可控，假 ``phase_shift``
    只需要返回"把查询搬回候选"的位移即可。
    """

    def setUp(self):
        self.lib = ramp_library(200)
        #: ★ 必须让库能**交出画面** —— ``locate_aligned`` 对每个候选都要
        #: ``library.frame_image(idx)`` 拿原图做对齐。这个合成库没有源视频
        #: （``src`` 为空），``frame_image`` 会返回 None，于是所有候选都被
        #: 跳过、函数返回 None。
        #:
        #: 这不只是测试问题：**生产环境同样如此** —— 参考库只存描述子
        #: （21.8MB），原图是回源视频 seek 取的。所以源视频**必须还在**，
        #: 否则定位根本跑不起来。已写进 ``locate_aligned`` 的文档。
        def fake_frame(idx: int):
            if idx < 0 or idx >= len(self.lib):
                return None
            return _img_for(self.lib, idx)

        self.lib.frame_image = fake_frame
        #: 用一个"完美的"相位相关：位移恒为 0（查询与参考完全对齐）。
        #: 这样搬回去 = 原样，打分退化成原始相似度 —— 便于验窗口/候选逻辑。
        self.zero_shift = lambda ref, frame: (0.0, 0.0, 0.9)

    def test_returns_aligned_dx(self):
        """返回值要带上对齐位移（决策层靠它纠偏）。

        ⚠ 假 ``phase_shift`` 给的位移会被**真的**用来搬画面
        （``cv2.warpAffine``），所以位移太大会把图搬糊，
        对齐后得分崩掉、连候选都过不了。
        这里用 1px 的小位移 —— 验的是"**返回值带上了 dx/dy**"，
        不是"大位移下的匹配质量"（那个由真视频的
        ``check_explore_gap_live.py`` 覆盖）。
        """
        lib = self.lib
        img = _img_for(lib, 40)
        got = locate_aligned(lib, img, near=40, window=10,
                             margin_min=_NEVER_REJECT,
                             phase_shift=lambda r, f: (1.0, 0.0, 0.5))
        self.assertIsNotNone(got)
        idx, score, margin, dx, dy = got
        self.assertAlmostEqual(dx, 1.0)
        self.assertAlmostEqual(dy, 0.0)

    def test_shift_beyond_limit_rejected(self):
        """对齐位移大得离谱（不是平移关系）→ 丢弃该候选。"""
        lib = self.lib
        img = _img_for(lib, 40)
        got = locate_aligned(lib, img, near=40, window=10,
                             margin_min=_NEVER_REJECT,
                             max_shift=50.0,
                             phase_shift=lambda r, f: (999.0, 0.0, 0.9))
        self.assertIsNone(got, "超界位移的候选该被丢掉")

    def test_phase_shift_failure_rejected(self):
        """相位相关失败（返回 None）→ 丢弃该候选，不该崩。"""
        lib = self.lib
        img = _img_for(lib, 40)
        got = locate_aligned(lib, img, near=40, window=10,
                             margin_min=_NEVER_REJECT,
                             phase_shift=lambda r, f: None)
        self.assertIsNone(got)

    def test_none_frame(self):
        self.assertIsNone(locate_aligned(self.lib, None, near=5,
                                         phase_shift=self.zero_shift))

    def test_empty_library(self):
        empty = ReferenceLibrary(matrix=np.zeros((0, DW * DH), dtype=np.float32),
                                 frames=np.zeros((0,), dtype=np.int64))
        self.assertIsNone(locate_aligned(empty, _img_for(self.lib, 3),
                                         near=0,
                                         phase_shift=self.zero_shift))

    def test_window_limits_candidates(self):
        """★ 连续性：窗口外的真值**不该**被选中。

        造两个"很像"的位置（一个在窗口内、一个在窗口外），
        查询指向窗口外那个 —— 结果必须是窗口内的（约束优先），
        或者干脆 None（认不准）—— **不能**跳到窗口外。
        """
        lib = self.lib
        target = 150                        #: 窗口外的真值
        img = _img_for(lib, target)
        got = locate_aligned(lib, img, near=10, window=5,     #: 窗口 [5,15]
                             margin_min=_NEVER_REJECT,
                             phase_shift=self.zero_shift)
        if got is not None:
            self.assertLessEqual(got[0], 15,
                                 f"跳出了窗口：选中 {got[0]}（窗口 [5,15]）")

    def test_margin_gate_uses_aligned_scores(self):
        """门槛卡的是**对齐后**的分差。"""
        lib = self.lib
        img = _img_for(lib, 40)
        #: 门槛高到不可能 → 必须 None
        self.assertIsNone(
            locate_aligned(lib, img, near=40, window=10, margin_min=9.0,
                           phase_shift=self.zero_shift))

    def test_constants_are_sane(self):
        self.assertGreater(TOP_K, 1, "至少要能比较两个候选")
        self.assertGreater(ALIGNED_MARGIN_MIN, 0.0)
        #: 对齐后的余量比原始更"干净"（对齐消掉了平移带来的假差异），
        #: 所以门槛也该更高 —— 但**不能高过合理范围**，
        #: 否则会大面积误伤（把对的判成没测到）。
        #:
        #: ⚠ 2026-10-11 重标：描述子减均值 + 修掉分辨率 bug 之后
        #: 实测「对」的余量中位 0.4596、5% 分位 0.1908，
        #: 「错」的中位 0.0678 —— 两组拉开了，门槛才能提到 0.15。
        #: 旧值 0.02 是旧度量下的数（那时两组几乎重叠）。
        self.assertGreaterEqual(
            ALIGNED_MARGIN_MIN, MARGIN_MIN,
            "对齐后的门槛不该低于原始门槛")
        self.assertLess(
            ALIGNED_MARGIN_MIN, 0.30,
            "对齐门槛高到 0.3 以上会大面积误伤 —— 重标过了吗？")


if __name__ == "__main__":
    unittest.main(verbosity=2)
