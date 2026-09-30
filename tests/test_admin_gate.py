"""启动权限闸门：**不是管理员就必须启动失败**。

    python tests/test_admin_gate.py

用户 2026-09-30 要求："增加应用启动时，如果不是管理员权限，启动失败，
并提示需要以管理模式启动"。

改动前是"提醒 + 可以点『仍然继续』"：用户选了继续，进去之后每个游戏工具
都点不动（UIPI 静默丢掉输入），还会去查"坐标是不是错了"。
这组用例把"拒绝启动"这个行为钉住。

Qt 部分用 offscreen 跑（弹框被 mock 掉，不真弹）。
"""

from __future__ import annotations

import os
import pathlib
import sys
import unittest
import unittest.mock as mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


class TestAdminGate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def _check(self, *, windows=True, elevated=False, restart=False,
               relaunch_ok=False):
        """跑一次 ``main._check_admin()``，各环节都 mock 掉。"""
        import main as main_module
        from src.core import elevation

        with mock.patch.object(elevation, "is_windows", return_value=windows), \
             mock.patch.object(elevation, "is_elevated", return_value=elevated), \
             mock.patch.object(elevation, "own_integrity_level",
                               return_value=0x3000 if elevated else 0x2000), \
             mock.patch.object(elevation, "level_name",
                               return_value="High" if elevated else "Medium"), \
             mock.patch.object(main_module, "_ask_restart_as_admin",
                               return_value=restart), \
             mock.patch.object(elevation, "relaunch_as_admin",
                               return_value=relaunch_ok):
            return main_module._check_admin()

    # ---------------------------------------------------------------- 放行
    def test_elevated_passes(self):
        """★ 已经是管理员 → 放行。"""
        self.assertTrue(self._check(elevated=True))

    def test_non_windows_passes(self):
        """非 Windows 放行（本项目只支持 Windows，但别让别的平台起不来）。"""
        self.assertTrue(self._check(windows=False))

    # ---------------------------------------------------------------- 拦下
    def test_not_elevated_is_blocked(self):
        """★ 非管理员 + 用户选『退出』→ **不放行**（这就是"启动失败"）。"""
        self.assertFalse(self._check(elevated=False, restart=False))

    def test_restart_success_still_blocks_this_process(self):
        """★ 选提权重启且发起成功 → **本进程仍不放行**。

        新实例已经在 UAC 之后接管了，本进程必须退场；
        放行的话会**同时跑两个实例**。
        """
        self.assertFalse(self._check(elevated=False, restart=True,
                                     relaunch_ok=True))

    def test_uac_cancelled_is_blocked(self):
        """★ 选提权但用户把 UAC 点了『否』→ 不放行（不能偷偷继续）。"""
        self.assertFalse(self._check(elevated=False, restart=True,
                                     relaunch_ok=False))

    def test_never_returns_none(self):
        """返回值必须能当布尔用 —— ``main()`` 拿它决定退出码。"""
        for kwargs in ({"elevated": True}, {"elevated": False},
                       {"windows": False}):
            with self.subTest(**kwargs):
                result = self._check(**kwargs)
                self.assertIn(result, (True, False))


class TestDialogHasNoContinueOption(unittest.TestCase):
    """弹框**不该再有「仍然继续」** —— 用户要求启动失败。"""

    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def test_dialog_buttons(self):
        import main as main_module
        from qfluentwidgets import MessageBoxBase  # noqa: F401 - 只是确保 Qt 可用

        from PySide6.QtWidgets import QMessageBox

        captured: dict = {}
        original_exec = QMessageBox.exec

        def fake_exec(self):
            captured["buttons"] = [b.text() for b in self.buttons()]
            captured["title"] = self.windowTitle()
            captured["text"] = self.text()
            captured["info"] = self.informativeText()
            return 0                      # 不真弹

        with mock.patch.object(QMessageBox, "exec", fake_exec):
            main_module._ask_restart_as_admin()

        labels = captured.get("buttons", [])
        self.assertTrue(any("管理员" in b for b in labels),
                        f"应提供「以管理员身份重启」：{labels}")
        self.assertFalse(any("继续" in b for b in labels),
                         f"不该再提供「仍然继续」：{labels}")
        # 标题/正文都要说清"需要管理员权限"（用户要求"提示需要以管理模式启动"）
        self.assertIn("权限", captured.get("title", ""))
        self.assertIn("管理员", captured.get("info", ""))

    def test_dialog_returns_false_when_not_restart(self):
        """用户点了非重启按钮 → 返回 False。"""
        import main as main_module

        from PySide6.QtWidgets import QMessageBox

        with mock.patch.object(QMessageBox, "exec", lambda self: 0), \
             mock.patch.object(QMessageBox, "clickedButton",
                               return_value=None):
            self.assertFalse(main_module._ask_restart_as_admin())


class TestMainExitsNonZero(unittest.TestCase):
    """``main()`` 在闸门不放行时必须以非 0 退出。"""

    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def test_main_returns_one_when_blocked(self):
        """★ 关键：拦下之后 ``main()`` 要返回 1。

        ``main.py`` 末尾是 ``raise SystemExit(main())``，所以返回 1
        才能让**进程以失败码结束**（这正是"启动失败"的体现）。

        ⚠ ``main()`` 内部会 ``QApplication(sys.argv)``；测试进程里已经有一个
        实例了，再建一个会抛 "destroy the QApplication singleton"。
        所以这里把 ``QApplication`` 换成"返回现有实例"的假构造器。
        """
        import main as main_module

        from PySide6.QtWidgets import QApplication

        existing = QApplication.instance()

        with mock.patch.object(main_module, "_check_admin",
                               return_value=False), \
             mock.patch("PySide6.QtWidgets.QApplication",
                        return_value=existing):
            code = main_module.main([])

        self.assertEqual(code, 1, "闸门不放行时 main() 必须返回非 0")
        self.assertNotEqual(code, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
