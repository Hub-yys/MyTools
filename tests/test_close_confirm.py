"""关闭确认 + 托盘文案的单测。

## 为什么不直接弹真框

真弹框要人点、还得分"点按钮"和"按 X"两种情况，人工覆盖不住。
这里把 ``qfluentwidgets.MessageBox`` 换成假的，精确模拟三种出口：

* 点主按钮   → exec() 真
* 点次按钮   → exec() 假 **且** ``cancelButton.clicked`` 被触发
* X / Esc    → exec() 假，但那个 clicked 信号**没**发过

第三种和第二种必须分开 —— 这是本文件最核心的断言。
（qfluentwidgets 的 MessageBox 没有 ``clickedButton()``，只能自己挂标记。）
"""

from __future__ import annotations

import pathlib
import sys
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.gui import tray  # noqa: E402


class _FakeSignal:
    def __init__(self) -> None:
        self._slots: list = []

    def connect(self, slot) -> None:
        self._slots.append(slot)

    def emit(self) -> None:
        for slot in list(self._slots):
            slot()


class _FakeButton:
    def __init__(self) -> None:
        self.text = ""
        self.clicked = _FakeSignal()

    def setText(self, text: str) -> None:  # noqa: N802 - 模仿 Qt 命名
        self.text = text


class _FakeMessageBox:
    """替身：按 ``outcome`` 决定 exec() 怎么返回、cancel 信号发不发。"""

    last: "_FakeMessageBox | None" = None

    def __init__(self, title, text, parent=None) -> None:
        self.title = title
        self.text = text
        self.yesButton = _FakeButton()
        self.cancelButton = _FakeButton()
        self.outcome = "yes"            # yes / cancel / x
        _FakeMessageBox.last = self

    def exec(self) -> int:              # noqa: A003 - 模仿 Qt 命名
        if self.outcome == "yes":
            return 1
        if self.outcome == "cancel":
            self.cancelButton.clicked.emit()
        # "x"：什么都不发，只返回假
        return 0


def _install_fake_messagebox(outcome: str):
    """把 qfluentwidgets.MessageBox 换成替身，并设定本次的出口。"""

    class _Box(_FakeMessageBox):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self.outcome = outcome

    fake_module = types.ModuleType("qfluentwidgets")
    fake_module.MessageBox = _Box
    sys.modules["qfluentwidgets"] = fake_module
    return _Box


class TestCloseQuestion(unittest.TestCase):
    """文案是纯函数，直接断言 —— 这段最容易写错又最难人工覆盖。"""

    def test_idle_mentions_both_choices(self):
        title, text, yes_text, cancel_text = tray.close_question(None)
        self.assertIn("托盘", yes_text)
        self.assertIn("退出", cancel_text)
        self.assertIn("托盘", text)
        self.assertIn("退出", text)

    def test_running_names_the_task(self):
        """需求 3：必须**点明是哪个**工具/任务在跑。"""
        title, text, yes_text, cancel_text = tray.close_question("声骸自动强化")
        self.assertIn("声骸自动强化", text)
        self.assertIn("正在执行", title)
        self.assertIn("停止", yes_text)
        self.assertIn("托盘", cancel_text)

    def test_running_warns_about_stopping(self):
        _t, text, _y, _c = tray.close_question("4C 刷声骸")
        self.assertIn("停止", text)


class TestRunningTaskName(unittest.TestCase):
    class _Host:
        def __init__(self, running):
            self.running_task = running

    def test_none_host(self):
        self.assertIsNone(tray.running_task_name(None))

    def test_idle(self):
        self.assertIsNone(tray.running_task_name(self._Host(None)))

    def test_running(self):
        self.assertEqual(tray.running_task_name(self._Host("声骸自动强化")),
                         "声骸自动强化")

    def test_broken_host_does_not_raise(self):
        class _Broken:
            @property
            def running_task(self):
                raise RuntimeError("宿主炸了")

        # 宿主状态异常不该挡住关闭流程
        self.assertIsNone(tray.running_task_name(_Broken()))


class TestAskClose(unittest.TestCase):
    def setUp(self):
        self._orig = sys.modules.get("qfluentwidgets")

    def tearDown(self):
        if self._orig is not None:
            sys.modules["qfluentwidgets"] = self._orig
        else:
            sys.modules.pop("qfluentwidgets", None)

    # ---- 无任务 ----
    def test_idle_primary_hides(self):
        _install_fake_messagebox("yes")
        self.assertEqual(tray.ask_close(None, None), tray.CLOSE_HIDE)

    def test_idle_secondary_quits(self):
        _install_fake_messagebox("cancel")
        self.assertEqual(tray.ask_close(None, None), tray.CLOSE_QUIT)

    def test_idle_x_cancels(self):
        """★ 按 X / Esc 必须**什么都不做**，不能顺手退出。"""
        _install_fake_messagebox("x")
        self.assertEqual(tray.ask_close(None, None), tray.CLOSE_CANCEL)

    # ---- 有任务 ----
    def test_running_primary_quits(self):
        _install_fake_messagebox("yes")
        self.assertEqual(tray.ask_close(None, "声骸自动强化"), tray.CLOSE_QUIT)

    def test_running_secondary_hides(self):
        _install_fake_messagebox("cancel")
        self.assertEqual(tray.ask_close(None, "声骸自动强化"), tray.CLOSE_HIDE)

    def test_running_x_cancels(self):
        _install_fake_messagebox("x")
        self.assertEqual(tray.ask_close(None, "声骸自动强化"), tray.CLOSE_CANCEL)

    # ---- 按钮文案 ----
    def test_button_texts_match_question(self):
        _install_fake_messagebox("yes")
        tray.ask_close(None, None)
        box = _FakeMessageBox.last
        self.assertEqual(box.yesButton.text, "隐藏到托盘")
        self.assertEqual(box.cancelButton.text, "直接退出")

        _install_fake_messagebox("yes")
        tray.ask_close(None, "4C 刷声骸")
        box = _FakeMessageBox.last
        self.assertEqual(box.yesButton.text, "停止并退出")
        self.assertEqual(box.cancelButton.text, "隐藏到托盘")

    # ---- 没有托盘时 ----
    def test_no_tray_never_offers_tray(self):
        """拿不到系统托盘时不该再劝用户"隐藏到托盘"（那是死路）。"""
        _install_fake_messagebox("yes")
        tray.ask_close(None, None, allow_hide=False)
        box = _FakeMessageBox.last
        self.assertNotIn("托盘", box.yesButton.text)
        self.assertNotIn("托盘", box.cancelButton.text)
        self.assertIn("最小化", box.yesButton.text)

    def test_no_tray_primary_still_goes_background(self):
        """没托盘时点主按钮仍然是「别退出、去后台」——只是缩成最小化。

        ``CLOSE_HIDE`` 的含义是"别退出"，**不是**"一定有托盘"。
        """
        _install_fake_messagebox("yes")
        self.assertEqual(
            tray.ask_close(None, None, allow_hide=False), tray.CLOSE_HIDE)


class TestMakeTrayFailureIsVisible(unittest.TestCase):
    """托盘建不起来时**必须留下痕迹** —— 这条是本文件最贵的教训。

    2026-09-25 的真实事故：``tray.py`` 里用了 ``QMenu`` 却漏了 import，
    `NameError` 被 ``except Exception: return None`` 吞掉。后果是
    **托盘永远建不出来、界面永远最小化到任务栏**，而日志里一个字都没有 ——
    用户只看到"图标不对、最小化后还会弹回来"，我从代码上一眼看不出问题，
    最后靠逐步手工复现才逼出来。

    "不该拖垮程序"不等于"不该留下痕迹"。
    """

    def setUp(self):
        self._avail = tray.tray_available
        self._cls = tray.QSystemTrayIcon
        tray.tray_available = lambda: True      # 假装托盘可用，逼它走进 try

    def tearDown(self):
        tray.tray_available = self._avail
        tray.QSystemTrayIcon = self._cls

    def test_failure_logs_warning(self):
        class _Boom:
            def __init__(self, *a, **kw):
                raise RuntimeError("故意炸")

        tray.QSystemTrayIcon = _Boom
        with self.assertLogs("src.gui.tray", level="WARNING") as cm:
            got = tray.make_tray(None, lambda: None, lambda: None)
        self.assertIsNone(got)
        self.assertTrue(any("托盘图标创建失败" in m for m in cm.output),
                        cm.output)

    def test_unavailable_logs_info(self):
        """托盘不可用（无头环境）也要说一声，别让人以为"忘了建"。"""
        tray.tray_available = lambda: False
        with self.assertLogs("src.gui.tray", level="INFO") as cm:
            got = tray.make_tray(None, lambda: None, lambda: None)
        self.assertIsNone(got)
        self.assertTrue(any("托盘不可用" in m or "跳过" in m for m in cm.output),
                        cm.output)


class TestAppIcon(unittest.TestCase):
    def test_returns_icon_object(self):
        """``app_icon()`` 必须**永远**返回 QIcon（哪怕文件不存在），不能抛。

        ⚠ 需要 QGuiApplication：``QIcon`` 从文件构造时内部会建 ``QPixmap``，
        没有 app 会直接崩（"Must construct a QGuiApplication before a QPixmap"）。
        单测默认不起 Qt，所以这里跳过而不是硬造一个 app —— 造了会污染其它用例。
        """
        from PySide6.QtGui import QGuiApplication

        if QGuiApplication.instance() is None:
            self.skipTest("需要 QGuiApplication（跑 tests/smoke_gui.py 覆盖这条）")

        from src.gui.compat import app_icon

        icon = app_icon()
        self.assertIsNotNone(icon)
        self.assertTrue(hasattr(icon, "isNull"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
