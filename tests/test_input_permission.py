"""启动前权限预检（``okww_boot.input_permission_error``）单测。

## 为什么要单测这个

2026-09-25 的事故：游戏以管理员运行、工具不是，
于是**每一次点击都被 UIPI 静默丢掉**（ok-script 的 ``post()`` 只记日志就继续），
任务照跑，最后报的却是毫不相干的「强化设置需要开启阶段放入!」。
用户完全看不出真正原因。

所以这里重点覆盖**判定逻辑本身**，尤其是"什么情况下不该拦"——
预检误拦会把明明能用的场景挡死，比漏拦更糟。
"""

from __future__ import annotations

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.core import elevation  # noqa: E402
from src.tools.game.auto_combat import okww_boot  # noqa: E402


class TestPermissionReason(unittest.TestCase):
    """纯判定逻辑（不碰真实进程，可在任何环境跑）。"""

    def test_game_higher_blocks(self):
        """游戏级别更高 → 必须拦，且提示要说人话。"""
        msg = okww_boot._permission_reason(
            elevation.LEVEL_MEDIUM, elevation.LEVEL_HIGH)
        self.assertIsNotNone(msg)
        self.assertIn("管理员", msg)
        # 不能把 API 名字甩给用户
        self.assertNotIn("PostMessage", msg)
        self.assertNotIn("SetCursorPos", msg)

    def test_same_level_allows(self):
        """两边同级 → 不拦（UIPI 不会拦同级进程）。"""
        self.assertIsNone(okww_boot._permission_reason(
            elevation.LEVEL_HIGH, elevation.LEVEL_HIGH))
        self.assertIsNone(okww_boot._permission_reason(
            elevation.LEVEL_MEDIUM, elevation.LEVEL_MEDIUM))

    def test_self_higher_allows(self):
        """自身比游戏高 → 不拦。"""
        self.assertIsNone(okww_boot._permission_reason(
            elevation.LEVEL_HIGH, elevation.LEVEL_MEDIUM))

    def test_unknown_level_does_not_block(self):
        """取不到级别（None）→ **不拦**。

        查不到就阻断用户是最糟的选择：宁可让引擎跑起来、
        报它自己的错，也不要因为拿不到级别就把功能锁死。
        """
        self.assertIsNone(okww_boot._permission_reason(None, elevation.LEVEL_HIGH))
        self.assertIsNone(okww_boot._permission_reason(elevation.LEVEL_MEDIUM, None))
        self.assertIsNone(okww_boot._permission_reason(None, None))


class TestFindGameProcessId(unittest.TestCase):
    def test_returns_int_or_none(self):
        """找不到游戏是正常情况（游戏没开），必须返回 None 而不是抛异常。"""
        pid = okww_boot.find_game_process_id()
        self.assertTrue(pid is None or isinstance(pid, int))

    def test_live_probe_returns_none_when_no_pid(self):
        """游戏没开时 input_permission_error 不能报「权限不足」。"""
        if okww_boot.find_game_process_id() is not None:
            self.skipTest("本机正开着游戏，跳过「无游戏」分支")
        self.assertIsNone(okww_boot.input_permission_error())


class TestElevateInstructions(unittest.TestCase):
    """提权指引必须区分开发态/打包态 —— 说错了用户照做也没用。"""

    def test_mentions_both_launch_paths(self):
        text = elevation._elevate_instructions()
        self.assertIn("管理员", text)
        if not elevation.is_windows():
            self.skipTest("只在 Windows 上跑")
        # 开发态下必须提醒「父程序也要提权」，否则用户只会去右键 main.py
        # ⚠ 不能写 sys.frozen —— 那个属性只有 PyInstaller 打包后才存在，
        #   源码态直接 AttributeError（这条测试自己踩过）。
        if not getattr(sys, "frozen", False):
            self.assertIn("PyCharm", text)
            self.assertIn("父程序", text)

    def test_hint_still_actionable(self):
        """原有断言不能退化（admin_hint 的对外契约）。"""
        hint = elevation.admin_hint(elevation.LEVEL_MEDIUM, elevation.LEVEL_HIGH)
        self.assertIn("普通级", hint)
        self.assertIn("管理员级", hint)


if __name__ == "__main__":
    unittest.main(verbosity=2)
