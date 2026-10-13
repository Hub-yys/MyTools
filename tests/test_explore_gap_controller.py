# -*- coding: utf-8 -*-
"""「查缺补漏」决策层的单元测试。

## 为什么要测得这么细

决策层是"会不会把路线毁掉"的那一层，而它**没法在离线环境验证**
（真要跑得开游戏）。所以只能在这里把各种情况穷举掉：

* 测不准 → **绝不能**产生 CORRECT 动作（这条是命门）
* 连续测不准 → 判跟丢（而不是无限等下去）
* 符号方向：``CORRECT.dx`` 必须是**原样**的 ``fix.dx``
  （执行方按 ``-dx`` 撤销；决策层要是先取负，就变成正反馈了）

## ⚠ 参数默认值全部是实测的

见 :mod:`src.core.explore_gap` 的模块文档。这里只钉**行为**，
不重复钉子（阈值改了这组测试仍应通过，只要行为没变）。
"""

from __future__ import annotations

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.core.explore_gap.controller import (  # noqa: E402
    ActionKind,
    ExploreGapConfig,
    ExploreGapState,
    at_end,
    decide,
)
from src.core.explore_gap.locator import Fix, peak_gate_ok  # noqa: E402


def fix(*, dx: float = 0.0, dy: float = 0.0, peak: float = 0.9,
        index: int = 10, sim: float = 0.95, margin: float = 0.07) -> Fix:
    """造一个测量结果。默认是"测得很准、已对齐"。"""
    return Fix(index=index, frame=index * 15, time_s=index * 0.5,
               similarity=sim, margin=margin, dx=dx, dy=dy, peak=peak)


class TestGate(unittest.TestCase):
    """闸门本身。"""

    def test_threshold_boundary(self):
        self.assertTrue(peak_gate_ok(0.05))
        self.assertTrue(peak_gate_ok(0.0501))
        self.assertFalse(peak_gate_ok(0.0499))

    def test_fix_trusted_flag(self):
        self.assertTrue(fix(peak=0.9).trusted)
        self.assertFalse(fix(peak=0.01).trusted)

    def test_shift_is_euclidean(self):
        self.assertAlmostEqual(fix(dx=3.0, dy=4.0).shift, 5.0)


class TestNoMeasurement(unittest.TestCase):
    def test_none_waits_then_lost(self):
        cfg = ExploreGapConfig(miss_after=3)
        st = ExploreGapState()
        for i in range(3):
            act = decide(None, st, cfg, library_len=100)
            if i < 2:
                self.assertEqual(act.kind, ActionKind.WAIT, f"第{i+1}次不该放弃")
            else:
                self.assertEqual(act.kind, ActionKind.LOST)
                self.assertTrue(act.is_terminal)
        self.assertIn("定位", act.reason)

    def test_success_clears_miss_counter(self):
        cfg = ExploreGapConfig(miss_after=2)
        st = ExploreGapState()
        decide(None, st, cfg, library_len=100)
        self.assertEqual(st.miss, 1)
        decide(fix(dx=1.0), st, cfg, library_len=100)      # 测到一次
        self.assertEqual(st.miss, 0, "测到之后定位失败计数要清零")
        decide(None, st, cfg, library_len=100)
        self.assertEqual(st.miss, 1)


class TestUntrustedMeasurement(unittest.TestCase):
    """★★★ 命门：测不准时**绝不能**输出 CORRECT。"""

    def test_untrusted_never_corrects(self):
        """即使偏离巨大，只要过不了闸门就**不许**纠偏。

        实测依据：大偏离下相位相关会返回垃圾值（见过 1201.9px、743px）。
        照着它转 = 把路线走废。
        """
        cfg = ExploreGapConfig()
        st = ExploreGapState()
        for peak in (0.0, 0.01, 0.02, 0.049):
            with self.subTest(peak=peak):
                act = decide(fix(dx=9999.0, peak=peak), st, cfg,
                             library_len=100)
                self.assertEqual(act.kind, ActionKind.WAIT,
                                 f"peak={peak} 竟然产生了 {act.kind}")
                self.assertEqual(act.dx, 0.0, "测不准时不能带任何纠偏量")

    def test_untrusted_is_counted_and_cleared(self):
        cfg = ExploreGapConfig(lost_after=5)
        st = ExploreGapState()
        decide(fix(dx=1.0, peak=0.01), st, cfg, library_len=100)
        self.assertEqual(st.unclear, 1)
        decide(fix(dx=1.0, peak=0.9), st, cfg, library_len=100)
        self.assertEqual(st.unclear, 0, "测准之后要清零")

    def test_too_many_unclear_is_lost(self):
        cfg = ExploreGapConfig(lost_after=3)
        st = ExploreGapState()
        kinds = [decide(fix(dx=5.0, peak=0.001), st, cfg,
                        library_len=100).kind for _ in range(3)]
        self.assertEqual(kinds[:2], [ActionKind.WAIT, ActionKind.WAIT])
        self.assertEqual(kinds[2], ActionKind.LOST)
        act = decide(fix(dx=5.0, peak=0.001), st, cfg, library_len=100)
        self.assertIn("测不准", act.reason)

    def test_lost_reason_says_why_it_stopped(self):
        """跟丢的理由要说清"停下比硬纠安全" —— 否则用户以为是坏了。"""
        cfg = ExploreGapConfig(lost_after=1)
        st = ExploreGapState()
        act = decide(fix(dx=5.0, peak=0.0), st, cfg, library_len=100)
        self.assertEqual(act.kind, ActionKind.LOST)
        self.assertIn("乱动", act.reason)


class TestCorrection(unittest.TestCase):
    def test_large_shift_corrects(self):
        cfg = ExploreGapConfig(align_px=40.0)
        st = ExploreGapState()
        act = decide(fix(dx=120.0), st, cfg, library_len=100)
        self.assertEqual(act.kind, ActionKind.CORRECT)

    def test_correction_sign_is_passed_through(self):
        """★ ``CORRECT.dx`` 必须是 ``fix.dx`` **原样**。

        实测约定（``_vid/diag_sign.py`` 量出来的）::

            注入 +S 右移  →  dx ≈ +S
            对当前画面施加 -dx  →  残差 0.00px
            对当前画面施加 +dx  →  残差 = 2S（正反馈）

        执行方按 ``-dx`` 撤销。决策层要是自己先取负，执行方再取负
        = 正反馈，越纠越偏 —— 这正是第一版残差 200% 的那个错。
        """
        cfg = ExploreGapConfig(align_px=40.0)
        for raw in (120.0, -120.0):
            with self.subTest(dx=raw):
                st = ExploreGapState()
                act = decide(fix(dx=raw), st, cfg, library_len=100)
                self.assertEqual(act.dx, raw, "符号被改过 —— 会变成正反馈")

    def test_no_deadzone_between_align_and_correct(self):
        """★★★ 回归：**不许再有死区**。

        曾经有 ``align=40 / correct=60`` 两个阈值，于是 40~60px 成了
        "谁也不管"的区间：不前进（超 align）、不纠偏（没超 correct）、
        只 WAIT，而 WAIT 不改变状态 → 下一帧还是 WAIT → **永久死锁**。

        闭环仿真实测：起始偏航 41px 时 **600 帧全 WAIT、0 次推进**。

        所以现在只有一个阈值：超了就纠、没超就前进。这条测试逐点扫过
        整个边界区间，任何一点 WAIT 都算失败。
        """
        cfg = ExploreGapConfig()
        for px in (cfg.align_px - 1, cfg.align_px, cfg.align_px + 0.1,
                   cfg.align_px + 5, cfg.align_px + 10, cfg.align_px + 19,
                   60.0, 80.0):
            with self.subTest(px=px):
                st = ExploreGapState()
                act = decide(fix(dx=px), st, cfg, library_len=100)
                self.assertIn(act.kind, (ActionKind.ADVANCE, ActionKind.CORRECT),
                              f"{px}px 处既没前进也没纠偏（{act.kind}）"
                              f"—— 死区又回来了")

    def test_vertical_only_never_corrects_by_itself(self):
        """★ 纵向偏移**不单独**触发纠偏（视角纠纵向会把画面转花）。"""
        cfg = ExploreGapConfig()
        st = ExploreGapState()
        act = decide(fix(dx=0.0, dy=30.0), st, cfg, library_len=100)
        self.assertEqual(act.kind, ActionKind.ADVANCE)


class TestAdvance(unittest.TestCase):
    def test_aligned_advances(self):
        cfg = ExploreGapConfig()
        st = ExploreGapState()
        act = decide(fix(dx=3.0), st, cfg, library_len=100)
        self.assertEqual(act.kind, ActionKind.ADVANCE)

    def test_exactly_at_align_boundary(self):
        cfg = ExploreGapConfig(align_px=40.0)
        st = ExploreGapState()
        self.assertEqual(decide(fix(dx=40.0), st, cfg,
                                library_len=100).kind, ActionKind.ADVANCE)

    def test_steps_counted(self):
        st = ExploreGapState()
        decide(fix(dx=1.0), st, ExploreGapConfig(), library_len=100)
        decide(fix(dx=1.0), st, ExploreGapConfig(), library_len=100)
        self.assertEqual(st.steps, 2)


class TestWorkPoint(unittest.TestCase):
    """★ 实测的工作点：3~40px 偏离必须全部能"前进"。

    这是回路的正常工作区间 —— 它靠高频小幅纠偏维持，
    所以这段必须畅通（否则每一步都在纠偏，走不动）。
    """

    def test_measured_working_range_advances(self):
        cfg = ExploreGapConfig()
        for px in (3, 5, 8, 10, 15, 20, 30, 40):
            with self.subTest(px=px):
                st = ExploreGapState()
                act = decide(fix(dx=float(px)), st, cfg, library_len=100)
                self.assertEqual(act.kind, ActionKind.ADVANCE,
                                 f"{px}px 在实测工作区间内，应该能前进")

    def test_measured_correction_range_corrects(self):
        """60px 以上该纠偏（实测通过率开始下降，但测出来的是准的）。"""
        cfg = ExploreGapConfig()
        for px in (70, 80, 120):
            with self.subTest(px=px):
                st = ExploreGapState()
                act = decide(fix(dx=float(px)), st, cfg, library_len=100)
                self.assertEqual(act.kind, ActionKind.CORRECT)


class TestTerminal(unittest.TestCase):
    def test_at_end(self):
        self.assertTrue(at_end(ExploreGapState(index=99), 100))
        self.assertTrue(at_end(ExploreGapState(index=98), 100))
        self.assertFalse(at_end(ExploreGapState(index=50), 100))

    def test_at_end_empty_library(self):
        self.assertTrue(at_end(ExploreGapState(index=0), 0))

    def test_terminal_flags(self):
        self.assertTrue(ActionKind.DONE)
        from src.core.explore_gap.controller import Action
        self.assertTrue(Action(ActionKind.DONE).is_terminal)
        self.assertTrue(Action(ActionKind.LOST).is_terminal)
        self.assertFalse(Action(ActionKind.WAIT).is_terminal)
        self.assertFalse(Action(ActionKind.CORRECT).is_terminal)
        self.assertFalse(Action(ActionKind.ADVANCE).is_terminal)


class TestHistory(unittest.TestCase):
    def test_history_records_and_caps(self):
        st = ExploreGapState()
        for _ in range(60):
            decide(fix(dx=1.0), st, ExploreGapConfig(), library_len=100)
        self.assertLessEqual(len(st.history), 40, "历史不能无限涨")

    def test_total_dx_accumulates(self):
        cfg = ExploreGapConfig()
        st = ExploreGapState()
        decide(fix(dx=100.0), st, cfg, library_len=100)
        decide(fix(dx=100.0), st, cfg, library_len=100)
        self.assertAlmostEqual(st.total_dx, 200.0)

    def test_working_range_still_covers_measured_values(self):
        """实测工作点 3~40px 仍然全部"前进"（改动没把工作点挪走）。"""
        cfg = ExploreGapConfig()
        for px in (3, 5, 8, 10, 15, 20, 30, 40):
            with self.subTest(px=px):
                st = ExploreGapState()
                self.assertEqual(
                    decide(fix(dx=float(px)), st, cfg,
                           library_len=100).kind,
                    ActionKind.ADVANCE)


if __name__ == "__main__":
    unittest.main(verbosity=2)
