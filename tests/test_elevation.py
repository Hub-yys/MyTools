"""权限检测（``src/core/elevation.py``）单测。

**关键**：查询类函数必须有一条"一定能查到已知存在的目标"的用例（肯定分支），
否则实现整个坏掉、测试照样全绿 —— 本机 pywin32 缺函数那次就是这么漏过去的。
这里用**当前自己的进程**当那个"已知存在的目标"。
"""

from __future__ import annotations

import os
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.core import elevation  # noqa: E402


class TestLevelName(unittest.TestCase):
    def test_names(self):
        self.assertEqual(elevation.level_name(elevation.LEVEL_MEDIUM), "普通级")
        self.assertEqual(elevation.level_name(elevation.LEVEL_HIGH), "管理员级")
        self.assertEqual(elevation.level_name(elevation.LEVEL_LOW), "低")
        self.assertEqual(elevation.level_name(elevation.LEVEL_SYSTEM), "系统级")

    def test_unknown(self):
        self.assertEqual(elevation.level_name(None), "未知")
        # 夹在中间的值按"够到哪一档"算
        self.assertEqual(elevation.level_name(elevation.LEVEL_HIGH + 1), "管理员级")
        self.assertEqual(elevation.level_name(elevation.LEVEL_SYSTEM + 1), "系统级")


class TestIntegrityQuery(unittest.TestCase):
    """肯定分支：自己的进程一定查得到。"""

    def test_own_process_is_queryable(self):
        if not elevation.is_windows():
            self.skipTest("只在 Windows 上跑")
        level = elevation.integrity_level(os.getpid())
        self.assertIsNotNone(level, "自己的进程都查不到，说明查询实现坏了")
        # 普通跑 / 管理员跑分别在 Medium / High
        self.assertIn(
            level,
            (elevation.LEVEL_LOW, elevation.LEVEL_MEDIUM, elevation.LEVEL_HIGH,
             elevation.LEVEL_SYSTEM),
        )

    def test_own_level_matches_own_pid(self):
        if not elevation.is_windows():
            self.skipTest("只在 Windows 上跑")
        self.assertEqual(elevation.own_integrity_level(), elevation.integrity_level(os.getpid()))

    def test_elevation_is_bool(self):
        self.assertIsInstance(elevation.is_elevated(), bool)

    def test_bad_pid_is_none(self):
        """打不开的进程要返回 None，而不是抛异常。"""
        if not elevation.is_windows():
            self.skipTest("只在 Windows 上跑")
        self.assertIsNone(elevation.integrity_level(0))
        self.assertIsNone(elevation.integrity_level(999999))


class TestAdminHint(unittest.TestCase):
    def test_hint_is_actionable(self):
        hint = elevation.admin_hint(elevation.LEVEL_MEDIUM, elevation.LEVEL_HIGH)
        self.assertIn("管理员", hint)
        self.assertIn("普通级", hint)
        self.assertIn("管理员级", hint)
        # 不能只把 API 名字甩给用户
        self.assertNotIn("SetCursorPos", hint)

    def test_hint_without_target(self):
        hint = elevation.admin_hint(elevation.LEVEL_MEDIUM, None)
        self.assertIn("管理员", hint)

    def test_relaunch_target_uses_python_in_dev(self):
        exe, params = elevation._relaunch_target(["--debug"])
        self.assertTrue(exe)
        self.assertIn("--debug", params)


if __name__ == "__main__":
    unittest.main(verbosity=2)
