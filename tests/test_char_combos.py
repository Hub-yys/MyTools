"""角色连招：守岸人「平A攒能 → 重击 → E+Q → 循环到协奏满」。

    python tests/test_char_combos.py

用户 2026-10-01 指定的流程（ok-ww 自带的**不是**这个顺序）：
    平A攒能量条 → 攒满 → 长按普攻释放重击 → E+Q
    → 协奏没满就继续上面的循环，满了就切换到二号位

⚠ 这里测的是**逻辑和接线**。实际按键效果要实机验证。
"""

from __future__ import annotations

import logging
import os
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor" / "okww"
for p in (str(ROOT), str(VENDOR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from src.tools.game.auto_combat.char_combos import (  # noqa: E402
    ShoreKeeperCombo,
)


class TestComboSequence(unittest.TestCase):
    """用户的流程：攒能 → 满 → 重击 → E+Q → 再攒能。"""

    def test_gather_until_full(self):
        c = ShoreKeeperCombo()
        for _ in range(5):
            self.assertEqual(c.next_action(False, False), "gather")

    def test_full_triggers_heavy(self):
        c = ShoreKeeperCombo()
        self.assertEqual(c.next_action(True, False), "heavy")

    def test_heavy_then_skills(self):
        """重击放完就该 E+Q（不是又回攒能）。"""
        c = ShoreKeeperCombo()
        c.next_action(True, False)                 # → heavy
        self.assertEqual(c.next_action(True, False), "skills")

    def test_skills_then_back_to_gather(self):
        """E+Q 放完 → 回攒能（下一轮）。"""
        c = ShoreKeeperCombo()
        c.next_action(True, False)                 # heavy
        c.next_action(True, False)                 # skills
        self.assertEqual(c.next_action(False, False), "gather")

    def test_full_cycle(self):
        """完整一轮：gather → heavy → skills → gather。"""
        c = ShoreKeeperCombo()
        seq = [
            c.next_action(False, False),   # gather
            c.next_action(True, False),    # heavy
            c.next_action(True, False),    # skills
            c.next_action(False, False),   # gather
        ]
        self.assertEqual(seq, ["gather", "heavy", "skills", "gather"])

    def test_rounds_counter(self):
        c = ShoreKeeperCombo()
        c.next_action(True, False)     # heavy
        c.next_action(True, False)     # skills
        c.next_action(False, False)    # gather → 一轮结束
        self.assertEqual(c.rounds, 1)


class TestHandOff(unittest.TestCase):
    """★ 协奏满了就交人 —— 不管当前在哪一步。"""

    def test_hand_off_from_any_step(self):
        for step in ("gather", "heavy", "skills"):
            with self.subTest(step=step):
                c = ShoreKeeperCombo()
                c.step = step
                self.assertEqual(c.next_action(False, True), "hand_off")

    def test_con_full_beats_forte_full(self):
        """两个都满时**先换人** —— 用户流程里协奏满是这一棒的终点。"""
        c = ShoreKeeperCombo()
        self.assertEqual(c.next_action(True, True), "hand_off")

    def test_not_con_full_keeps_going(self):
        """协奏没满就继续循环（这是用户强调的）。"""
        c = ShoreKeeperCombo()
        self.assertNotEqual(c.next_action(False, False), "hand_off")


class TestReset(unittest.TestCase):
    def test_reset_returns_to_gather(self):
        c = ShoreKeeperCombo()
        c.next_action(True, False)
        c.reset()
        self.assertEqual(c.step, "gather")

    def test_reset_after_handoff(self):
        c = ShoreKeeperCombo()
        c.next_action(False, True)
        self.assertEqual(c.step, "gather", "交人后该回到起点")


class TestWiring(unittest.TestCase):
    """★ 接线：真的把守岸人换成了带连招的子类。"""

    @classmethod
    def setUpClass(cls):
        # ⚠ 关掉 ok-ww 的日志噪音 —— 但**必须记下原值并在 tearDownClass 还原**。
        #   不还原的话会把「全局」日志级别改掉，污染后面的用例
        #   （实测：test_close_confirm 的两个 logger 断言会因此失败）。
        cls._old_disable = logging.root.manager.disable
        logging.disable(logging.CRITICAL)
        cls._old_cwd = os.getcwd()
        os.chdir(VENDOR)
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))

    @classmethod
    def tearDownClass(cls):
        os.chdir(cls._old_cwd)
        logging.disable(cls._old_disable)      # ★ 还原全局状态

    def _task(self):
        class _T:
            pass

        return _T()

    def test_wraps_shorekeeper(self):
        from okww.char.ShoreKeeper import ShoreKeeper
        from src.tools.game.auto_combat.char_combos import wrap_char

        real = ShoreKeeper(self._task(), 2, char_name="char_shorekeeper")
        wrapped = wrap_char(self._task(), real, 2)
        self.assertIsNotNone(wrapped, "守岸人没被换掉 —— 连招不生效")
        self.assertIsNot(wrapped, real)
        self.assertIsInstance(wrapped, ShoreKeeper,
                              "必须是子类，否则 ok-ww 的 isinstance 判断会崩")
        self.assertNotEqual(type(wrapped).__name__, "ShoreKeeper",
                            "还是原来的类 —— 没覆盖")

    def test_overrides_do_perform(self):
        from okww.char.ShoreKeeper import ShoreKeeper
        from src.tools.game.auto_combat.char_combos import wrap_char

        real = ShoreKeeper(self._task(), 2, char_name="char_shorekeeper")
        wrapped = wrap_char(self._task(), real, 2)
        self.assertIn("do_perform", type(wrapped).__dict__,
                      "没覆盖 do_perform —— 还是 ok-ww 原来的顺序")

    def test_combo_state_present(self):
        """⚠ 用 ``__new__`` 造实例会跳过 ``__init__`` —— combo 要补上，
        否则 ``do_perform`` 一跑就 AttributeError。"""
        from okww.char.ShoreKeeper import ShoreKeeper
        from src.tools.game.auto_combat.char_combos import wrap_char

        real = ShoreKeeper(self._task(), 2, char_name="char_shorekeeper")
        wrapped = wrap_char(self._task(), real, 2)
        self.assertTrue(hasattr(wrapped, "combo"), "没建 combo 状态")
        self.assertIsInstance(wrapped.combo, ShoreKeeperCombo)

    def test_state_is_carried_over(self):
        """★ 换对象不能丢状态 —— 那些是切人调度要用的。"""
        from okww.char.ShoreKeeper import ShoreKeeper
        from src.tools.game.auto_combat.char_combos import wrap_char

        real = ShoreKeeper(self._task(), 2, char_name="char_shorekeeper")
        real.current_con = 0.75
        real.has_intro = True
        real.last_switch_time = 12345.0
        wrapped = wrap_char(self._task(), real, 2)
        self.assertEqual(wrapped.current_con, 0.75)
        self.assertTrue(wrapped.has_intro)
        self.assertEqual(wrapped.last_switch_time, 12345.0)

    def test_unrelated_char_untouched(self):
        """没有连招的角色**不该**被换。"""
        from okww.char.Jinhsi import Jinhsi
        from src.tools.game.auto_combat.char_combos import wrap_char

        other = Jinhsi(self._task(), 0, char_name="char_jinhsi")
        self.assertIsNone(wrap_char(self._task(), other, 0))

    def test_none_safe(self):
        from src.tools.game.auto_combat.char_combos import wrap_char

        self.assertIsNone(wrap_char(self._task(), None, 0))
        self.assertIsNone(wrap_char(None, object(), 0))

    def test_task_hooks_load_chars(self):
        """★ MyToolsFarmEchoTask 必须覆盖 load_chars —— 否则换不上。"""
        from src.tools.game.auto_combat.okww_farm import MyToolsFarmEchoTask

        self.assertIn("load_chars", MyToolsFarmEchoTask.__dict__,
                      "任务没覆盖 load_chars —— 连招永远不会生效")


class TestNoVendorEdits(unittest.TestCase):
    """★ 连招必须走 MyTools 自己的代码，**不改 vendor**。

    改了 vendor 的话，上游一更新就被冲掉（这个坑在「心」的模板上踩过）。
    """

    def test_shorekeeper_source_untouched(self):
        text = (VENDOR / "okww" / "char" / "ShoreKeeper.py").read_text(
            encoding="utf-8")
        self.assertNotIn("平A攒能", text, "守岸人的连招被写进 vendor 了")
        self.assertNotIn("ShoreKeeperCombo", text, "vendor 里引用了我们的连招")

    def test_combo_lives_in_mytools(self):
        path = ROOT / "src" / "tools" / "game" / "auto_combat" / "char_combos.py"
        self.assertTrue(path.exists(), "连招模块不在 MyTools 里")


if __name__ == "__main__":
    unittest.main(verbosity=2)
