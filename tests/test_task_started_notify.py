"""「任务已启动」通知**绝不能阻塞调用方**（2026-09-27 卡死根因）。

## 事故

用户报「应用卡死」。日志最后两条是：

    [宿主] … do_start 返回：True
    [宿主] ▶ 已启动任务：声骸自动强化
    ← 之后 12 分钟零输出

而 ``OkwwTaskRunner.run()`` 的第一条日志（"已交给 ok-ww 引擎"）**没出现**。
``start_task`` 里 ``▶ 已启动任务`` 之后**只剩一句** ``_notify_task_started()``
→ 必然卡在它（或它调的回调）上。

那个回调是 ``MainWindow.go_background_to_game()`` —— 里面要 ``hide()`` /
``QTimer.singleShot()`` / ``processEvents()``，**只能在 Qt 主线程做**，
可它是被 ``FlowRunThread``（工作线程）调用的。

**实测反证**：注册一个"卡 5 秒"的监听者 —— 同步调用时 ``start_task`` 被拖 5 秒；
改成走独立线程后 0.00s。界面回调真卡住时任务就永远起不来 ⇒ 用户看到的「卡死」。

这里守两层：
1. 宿主侧：通知走独立线程，**任何监听者卡住都不拖住任务启动**；
2. 界面侧：回调只 ``emit`` 信号（槽在主线程跑），不直接碰 Qt。
"""

from __future__ import annotations

import pathlib
import sys
import threading
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.tools.game.auto_combat import okww_boot  # noqa: E402


def _bare_host() -> okww_boot.OkwwHost:
    """不 boot 引擎的宿主 —— ``_notify_task_started`` 用不到引擎。"""
    return okww_boot.OkwwHost()


class TestNotifyNeverBlocks(unittest.TestCase):

    def test_slow_listener_does_not_block_caller(self):
        """★ 核心：监听者卡住，调用方也必须**立刻**返回。"""
        host = _bare_host()
        release = threading.Event()

        def slow(_key):
            release.wait(5.0)        # 模拟卡住/很慢的界面回调

        host.add_task_started_listener(slow)
        t0 = time.monotonic()
        try:
            host._notify_task_started("echo_enhance")
            elapsed = time.monotonic() - t0
            self.assertLess(elapsed, 1.0,
                            f"通知把调用方拖了 {elapsed:.2f}s —— 这正是「卡死」")
        finally:
            release.set()

    def test_listener_is_actually_called(self):
        """★ 前置：别在"空集合"上验 —— 监听者必须真被调到。

        没有这条，上面那条即使把 ``_notify_task_started`` 改成空函数也照样绿。
        """
        host = _bare_host()
        seen = []
        done = threading.Event()

        def listener(key):
            seen.append(key)
            done.set()

        host.add_task_started_listener(listener)
        host._notify_task_started("echo_enhance")
        self.assertTrue(done.wait(3.0), "监听者没被调到")
        self.assertEqual(seen, ["echo_enhance"])

    def test_no_listeners_is_harmless(self):
        """没人监听时不该炸（工具页那条路也会调它）。"""
        _bare_host()._notify_task_started("echo_enhance")

    def test_duplicate_listener_registered_once(self):
        """同一个监听者重复注册只留一份（否则会被调多次）。"""
        host = _bare_host()
        count = []
        fn = lambda _key: count.append(1)      # noqa: E731
        host.add_task_started_listener(fn)
        host.add_task_started_listener(fn)
        self.assertEqual(len(host._task_started_listeners), 1)


class TestMainWindowCallbackGoesThroughSignal(unittest.TestCase):
    """界面侧：回调必须是 ``emit``，不能直接调 ``go_background_to_game``。

    直接调 = 从工作线程碰 Qt（``hide()`` / ``QTimer`` / ``processEvents()``）。
    """

    SRC = ROOT / "src/gui/main_window.py"

    def test_listener_emits_signal_not_direct_call(self):
        src = self.SRC.read_text(encoding="utf-8")
        self.assertIn("self.task_started.emit()", src)
        # 被禁的写法：回调里直接调那个碰 Qt 的函数
        self.assertNotIn("lambda _key: self.go_background_to_game()", src)

    def test_signal_connected_to_slot(self):
        """信号要真的连到槽 —— 否则界面永远不缩到后台了（功能静默丢失）。"""
        src = self.SRC.read_text(encoding="utf-8")
        self.assertIn("self.task_started.connect(self.go_background_to_game)", src)

    def test_signal_is_declared(self):
        src = self.SRC.read_text(encoding="utf-8")
        self.assertIn("task_started = Signal()", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
