# -*- coding: utf-8 -*-
"""系统托盘通知：不创建 + 退出时清理。

用户反馈（2026-09-24）：每次跑工具，任务栏托盘区会多出一排默认「小窗口」图标。

根因：
* ``HeadlessApp`` 在 ``do_init`` 里就会 ``NotificationManager()`` →
  ``WindowsSystemNotifier``（隐藏 Win32 窗口 + ``Shell_NotifyIconW(NIM_ADD)``）；
* MyTools 退出只 ``exit_event.set()``，从不 ``NIM_DELETE`` → 图标残留叠加。

这个文件断言的是两条修复都还在：
1. 构造参数补丁：``system_notifier=None``，图标根本不注册；
2. ``shutdown()`` 走 ``headless.quit()``（会 ``notification_manager.stop()`` 删托盘），
   而不是只 set 事件。
"""
from __future__ import annotations

import inspect
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.tools.game.auto_combat import okww_boot  # noqa: E402


class TestNoSystemNotifierPatch(unittest.TestCase):
    def test_patch_forces_system_notifier_none(self):
        """补丁装上后，NotificationManager 构造必须收到 system_notifier=None。"""
        okww_boot._notification_patched = False
        # 重置类上的标记，保证本次真的走 patch 分支
        try:
            from ok.notification import NotificationManager
        except ImportError:
            self.skipTest("ok 包不可用")

        if getattr(NotificationManager, "_mytools_no_tray", False):
            # 已 patch 过：确认仍是补丁后的 __init__
            src = inspect.getsource(NotificationManager.__init__)
            self.assertIn("system_notifier", src)

        okww_boot._install_no_system_notifier()
        self.assertTrue(okww_boot._notification_patched)

        # 用假依赖构造：不应该去 import WindowsSystemNotifier / 建窗口
        created = {}

        class FakeConfig(dict):
            def get(self, k, default=None):
                return super().get(k, default)

        class FakeGC:
            def get_config(self, name):
                return FakeConfig()

        class FakeExecutor:
            class ocr_lib:
                pass

        # NotificationManager 还会建 NotificationPipeline / OCR —— 用 monkeypatch 躲开
        import ok.notification.manager as mgr_mod

        orig_pipeline = mgr_mod.NotificationPipeline
        orig_ocr = mgr_mod.NotificationPPOCR

        class _NoopPipeline:
            def __init__(self, *a, **k):
                self.queue = None
                self.thread = None

            def stop(self, wait=True):
                return True

            def submit(self, *a, **k):
                return False

        class _NoopOCR:
            def __init__(self, *a, **k):
                pass

        mgr_mod.NotificationPipeline = _NoopPipeline
        mgr_mod.NotificationPPOCR = _NoopOCR
        try:
            nm = mgr_mod.NotificationManager(FakeGC(), FakeExecutor())
            created["system_notifier"] = nm.system_notifier
        finally:
            mgr_mod.NotificationPipeline = orig_pipeline
            mgr_mod.NotificationPPOCR = orig_ocr

        self.assertIsNone(
            created["system_notifier"],
            "补丁后 system_notifier 必须是 None（否则会注册托盘图标）",
        )
        # notify_system 在 notifier 为 None 时应直接短路
        self.assertFalse(nm.notify_system("t", "m"))


class TestShutdownCleansTray(unittest.TestCase):
    def test_shutdown_calls_headless_quit(self):
        """shutdown 必须走 HeadlessApp.quit()（它会 stop 通知、删托盘）。"""
        src = inspect.getsource(okww_boot.OkwwHost.shutdown)
        self.assertIn("headless.quit()", src,
                      "shutdown 只 set exit_event 会漏删托盘图标")
        self.assertNotIn("ok.quit()", src,
                         "不要调 OK.quit() —— 它可能碰 Qt QMetaObject")

    def test_shutdown_still_sets_exit_event_on_failure(self):
        src = inspect.getsource(okww_boot.OkwwHost.shutdown)
        # headless.quit 失败时要有 exit_event 兜底
        self.assertIn("exit_event.set", src)

    def test_module_has_shutdown_host_helper(self):
        self.assertTrue(callable(okww_boot.shutdown_host_if_any))


class TestBootInstallsPatch(unittest.TestCase):
    def test_boot_calls_install_before_ok(self):
        src = inspect.getsource(okww_boot.OkwwHost._boot_in_thread)
        self.assertIn("_install_no_system_notifier()", src)
        self.assertIn("_force_disable_system_notification", src)
        self.assertLess(
            src.index("_install_no_system_notifier()"),
            src.index("OK(config)"),
            "补丁必须在 OK() 之前 —— HeadlessApp 在 do_init 里就建通知",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
