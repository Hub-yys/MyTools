"""固定循环轴（轮椅轴）：3 → 2 → 1 → 3 …

    python tests/test_rotation.py

用户 2026-10-01 报"还是在乱切人"，要求改成固定轴：
    3号位打完一套满协奏 → 2号位打完一套慢卸载 → 1号位打完一套满协奏 → 回 3号位

队伍固定：1=心、2=坎特蕾拉、3=守岸人。

⚠ 这里测的是**状态机**（纯逻辑，不碰游戏）。真正的"切人动作"要实机验证。
"""

from __future__ import annotations

import pathlib
import sys
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.tools.game.auto_combat import rotation  # noqa: E402


class _Char:
    """假的 ok-ww 角色对象（只需要 ``index``）。"""

    def __init__(self, index: int, name: str = "") -> None:
        self.index = index
        self.char_name = name or f"char_{index}"

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<Char {self.index}>"


class TestRotationOrder(unittest.TestCase):
    """轴的**顺序**必须是用户要的 3 → 2 → 1。"""

    def test_order_is_three_two_one(self):
        st = rotation.RotationState()
        seq = [st.current]
        for _ in range(5):
            seq.append(st.advance())
        self.assertEqual(seq, [3, 2, 1, 3, 2, 1])

    def test_custom_rotation(self):
        st = rotation.RotationState((1, 2, 3))
        self.assertEqual([st.current, st.advance(), st.advance()], [1, 2, 3])

    def test_empty_rotation_rejected(self):
        with self.assertRaises(ValueError):
            rotation.RotationState(())

    def test_full_cycle_returns_to_start(self):
        st = rotation.RotationState()
        start = st.current
        for _ in range(len(rotation.ROTATION)):
            st.advance()
        self.assertEqual(st.current, start)


class TestHandOff(unittest.TestCase):
    """什么时候换人。"""

    def _at(self, slot: int) -> rotation.RotationState:
        st = rotation.RotationState()
        st.resync(slot)
        return st

    def test_con_full_hands_off(self):
        st = self._at(1)
        go, why = st.should_hand_off(con_full=True, slot=1)
        self.assertTrue(go, f"1 号位协奏满了却不换（{why}）")

    def test_not_full_stays(self):
        st = self._at(1)
        go, _why = st.should_hand_off(con_full=False, slot=1)
        self.assertFalse(go, "协奏没满就换人了")

    def test_slow_unload_waits(self):
        """★ 2 号位（坎特蕾拉）是"慢卸载"—— 协奏满了还要再打一会儿。"""
        st = self._at(2)
        st._since = time.monotonic()          # 刚上场
        go, _why = st.should_hand_off(con_full=True, slot=2)
        self.assertFalse(go, "慢卸载位协奏一满就走，没打完整套")

    def test_slow_unload_eventually_goes(self):
        st = self._at(2)
        st._since = time.monotonic() - (rotation.SLOW_UNLOAD_SECONDS + 0.1)
        go, _why = st.should_hand_off(con_full=True, slot=2)
        self.assertTrue(go, "慢卸载等够了还不换人")

    def test_slow_unload_slot_is_two(self):
        """慢卸载位必须是 2 号位（坎特蕾拉）—— 用户点名的。"""
        self.assertIn(2, rotation.SLOW_UNLOAD_SLOTS)

    def test_non_slow_slot_leaves_immediately(self):
        """1 号位（心）不是慢卸载位：协奏一满就走。"""
        st = self._at(1)
        st._since = time.monotonic()
        go, _why = st.should_hand_off(con_full=True, slot=1)
        self.assertTrue(go)

    def test_timeout_fallback(self):
        """★ 协奏一直不满也要有兜底 —— 否则原地卡死。"""
        st = self._at(3)
        st._since = time.monotonic()
        go, _why = st.should_hand_off(con_full=False, slot=3)
        self.assertFalse(go)
        st._since = time.monotonic() - (rotation.MAX_FIELD_SECONDS + 0.1)
        go, why = st.should_hand_off(con_full=False, slot=3)
        self.assertTrue(go, "超时了还不换人 —— 会卡死")
        self.assertIn("超时", why)

    def test_timeout_is_bounded(self):
        """★ 超时值必须是**有限且够短**的。

        ⚠ 这条是补的漏洞：把 ``MAX_FIELD_SECONDS`` 改成 99999
        （等于没有兜底）时，上面那条用例**照样通过**（因为它用的是
        改后的值去算时间），抓不住。
        所以这里直接给这个常量划个上界。
        """
        self.assertGreater(rotation.MAX_FIELD_SECONDS, 0)
        self.assertLessEqual(
            rotation.MAX_FIELD_SECONDS, 30.0,
            f"单棒站场上限 {rotation.MAX_FIELD_SECONDS}s 太长了 —— "
            f"信号失灵时会干等这么久（等于卡死）")

    def test_slow_unload_is_bounded(self):
        """慢卸载的额外等待也要有上界。"""
        self.assertGreaterEqual(rotation.SLOW_UNLOAD_SECONDS, 0)
        self.assertLess(
            rotation.SLOW_UNLOAD_SECONDS, rotation.MAX_FIELD_SECONDS,
            "慢卸载等待不能超过单棒上限 —— 否则永远不会触发超时兜底")

    def test_elapsed_tracks_time(self):
        st = self._at(1)
        st._since = time.monotonic() - 2.0
        self.assertGreater(st.elapsed(), 1.9)


class TestResync(unittest.TestCase):
    """★ 漂移容错：轴要跟着**实际**在场的人走。"""

    def test_resync_moves_pointer(self):
        st = rotation.RotationState()
        self.assertEqual(st.current, 3)
        st.resync(1)
        self.assertEqual(st.current, 1)
        # 从 1 往后走应该是 3（因为轴是 3→2→1）
        self.assertEqual(st.advance(), 3)

    def test_resync_ignores_unknown_slot(self):
        st = rotation.RotationState()
        st.resync(1)
        st.resync(99)
        self.assertEqual(st.current, 1, "不认识的位置不该改变轴")

    def test_resync_resets_elapsed(self):
        st = rotation.RotationState()
        st._since = time.monotonic() - 5.0
        st.resync(2)
        self.assertLess(st.elapsed(), 0.5, "resync 后计时该重置")

    def test_advance_resets_elapsed(self):
        st = rotation.RotationState()
        st._since = time.monotonic() - 5.0
        st.advance()
        self.assertLess(st.elapsed(), 0.5)


class TestSlotOf(unittest.TestCase):
    """ok-ww 的 ``index`` 是 0 起，我们要 1 起的"号位"。"""

    def test_index_is_zero_based(self):
        for i in range(3):
            with self.subTest(index=i):
                self.assertEqual(rotation.slot_of(_Char(i)), i + 1)

    def test_none_is_none(self):
        self.assertIsNone(rotation.slot_of(None))

    def test_missing_index_is_none(self):
        class _NoIndex:
            pass

        self.assertIsNone(rotation.slot_of(_NoIndex()))

    def test_bad_index_is_none(self):
        class _Bad:
            index = -1

        self.assertIsNone(rotation.slot_of(_Bad()))


class TestNextSlotTarget(unittest.TestCase):
    """按轴找**在场**的人。"""

    def test_picks_first_of_rotation(self):
        chars = [_Char(0), _Char(1), _Char(2)]
        target = rotation.next_slot_target(chars)
        self.assertIsNotNone(target)
        self.assertEqual(rotation.slot_of(target), 3, "轴首位是 3 号位")

    def test_skips_missing_slot(self):
        """3 号位不在（比如两人队）→ 应该退到 2 号位。"""
        chars = [_Char(0), _Char(1)]
        target = rotation.next_slot_target(chars)
        self.assertIsNotNone(target)
        self.assertEqual(rotation.slot_of(target), 2)

    def test_empty_returns_none(self):
        self.assertIsNone(rotation.next_slot_target([]))
        self.assertIsNone(rotation.next_slot_target([None, None]))

    def test_no_usable_slot_returns_none(self):
        class _NoIndex:
            pass

        self.assertIsNone(rotation.next_slot_target([_NoIndex()]))


class TestTaskWiring(unittest.TestCase):
    """★ 接线：任务类真的覆盖了 ok-ww 的切人决策。"""

    def _load(self):
        import logging
        import os

        logging.disable(logging.CRITICAL)
        vendor = str(ROOT / "vendor" / "okww")
        if vendor not in sys.path:
            sys.path.insert(0, vendor)
        old = os.getcwd()
        os.chdir(vendor)
        try:
            from okww.task.BaseCombatTask import BaseCombatTask
            from src.tools.game.auto_combat.okww_farm import (
                MyToolsFarmEchoTask,
            )
        finally:
            os.chdir(old)
        return BaseCombatTask, MyToolsFarmEchoTask

    def test_task_overrides_switch_target(self):
        """⚠ 没覆盖的话就还是 ok-ww 的乱切 —— 这条防的就是"接线断了"。"""
        _base, task = self._load()
        self.assertIn(
            "_choose_switch_target", task.__dict__,
            "MyToolsFarmEchoTask 没覆盖 _choose_switch_target —— 还是乱切人")

    def test_signature_matches_parent(self):
        """签名必须和父类一致，否则 ok-ww 调用时会 TypeError。"""
        import inspect

        base, task = self._load()
        self.assertEqual(
            inspect.signature(task._choose_switch_target),
            inspect.signature(base._choose_switch_target))

    def test_has_rotation_state(self):
        """⚠ ``rotation_state`` 是**实例**属性（在 ``__init__`` 里建的），
        所以查 ``dir(类)`` 是查不到的 —— 要查 ``__init__`` 的源码。"""
        _base, task = self._load()
        import inspect

        src = inspect.getsource(task.__init__)
        self.assertIn("rotation_state", src,
                      "任务里没建 rotation_state —— 固定轴没接上")
        self.assertIn("rotation.RotationState", src)

    def test_falls_back_when_team_incomplete(self):
        """★ 队伍不足 3 人时**不该**接管 —— 交回 ok-ww 的原逻辑。

        否则一个两人队会被硬切来切去。
        """
        base, task = self._load()
        calls = []

        class _Probe(task):
            def __init__(self):          # noqa: D107 - 故意不调 super
                self.chars = [_Char(0), _Char(1)]
                self.rotation_state = rotation.RotationState()

            def log_info(self, *a, **k):
                pass

            def log_debug(self, *a, **k):
                pass

        def fake_super(self, current_char, has_intro, target_low_con=False):
            calls.append(True)
            return "SUPER"

        original = base._choose_switch_target
        base._choose_switch_target = fake_super
        try:
            got = _Probe()._choose_switch_target(_Char(0), False)
        finally:
            base._choose_switch_target = original

        self.assertEqual(got, "SUPER", "队伍不全时没交回 ok-ww")
        self.assertTrue(calls, "父类逻辑根本没被调用")


if __name__ == "__main__":
    unittest.main(verbosity=2)
