"""主线程卡死看门狗的单测（``src/core/watchdog.py``）。

## 为什么要它

2026-09-27 用户报「应用卡死」，我们能拿到的只有日志的**最后一行**：

    ... start_controller:enabled task <MyToolsEnhanceEchoTask ...>

日志停在某一行**只说明"卡在这之后"**，说明不了卡在**哪个线程的哪一行**。
于是我猜了七八轮（跨线程碰 Qt、锁被占着、对象复用……）**全是错的**。

这里的护栏守两件事：
1. 转储必须**带线程名**（``faulthandler`` 只给 ``Thread 0x00042834``，对不上人）；
2. 主线程**不打点就自动**转储，**正常打点绝不转储**（否则运行时刷一堆假转储）。
"""

from __future__ import annotations

import pathlib
import sys
import tempfile
import threading
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.core.watchdog import (  # noqa: E402
    DEFAULT_TIMEOUT,
    HEARTBEAT_MS,
    StallWatchdog,
    format_all_threads,
)


class TestFormatAllThreads(unittest.TestCase):
    """转储内容。"""

    def test_contains_main_thread_and_frames(self):
        """★ 必须有 **MainThread** 这个名字，且是**我们自己的格式**。

        ⚠ 断言不能只查 ``"MainThread" in txt`` + ``"File" in txt`` ——
        ``faulthandler.dump_traceback`` 的输出里恰好也有 ``File "..."``/``line``，
        能侥幸通过（2026-09-27 反证时发现：把实现换成 faulthandler，这条照样绿）。
        所以要锁**格式**：我们写的是 ``--- MainThread ---``，faulthandler 写的是
        ``Thread 0x00042834 (most recent call first)``。
        """
        txt = format_all_threads()
        self.assertIn("--- MainThread ---", txt)
        self.assertIn('File "', txt)
        self.assertIn("line ", txt)
        # 反证性质：faulthandler 那种"只有 id 没有名字"的格式不该出现
        self.assertNotIn("(most recent call first)", txt)

    def test_named_thread_appears(self):
        """别的线程也要列出来 —— TaskExecutor / FlowRunThread 才是常见嫌疑。"""
        threading.Thread(target=lambda: time.sleep(5), name="TaskExecutorProbe",
                         daemon=True).start()
        self.assertIn("TaskExecutorProbe", format_all_threads())

    def test_main_thread_comes_first(self):
        """主线程排最前：它才是"界面卡住"的本体，不该让人去一堆栈里翻。"""
        threading.Thread(target=lambda: time.sleep(5), name="AaaProbe",
                         daemon=True).start()
        txt = format_all_threads()
        main_at = txt.index("MainThread")
        for name in ("AaaProbe", "TaskExecutorProbe"):
            if f"--- {name} ---" in txt:
                self.assertLess(main_at, txt.index(f"--- {name} ---"),
                                f"{name} 不该排在 MainThread 前面")


class TestStallWatchdog(unittest.TestCase):

    def test_beat_resets_silence(self):
        wd = StallWatchdog(timeout=5.0)
        time.sleep(0.05)
        wd.beat()
        self.assertLess(wd.silence(), 0.05, "beat() 之后安静时间该归零")

    def test_dump_writes_stack_to_file(self):
        with tempfile.TemporaryDirectory() as d:
            wd = StallWatchdog(timeout=0.1, dump_dir=pathlib.Path(d))
            path = wd.dump(0.5)
            self.assertTrue(path.is_file())
            self.assertEqual(wd.dumps, 1)
            self.assertIn("MainThread", path.read_text(encoding="utf-8"))

    def test_auto_dump_when_silent(self):
        """★ 核心行为：主线程不打点 → 超时后**自动**转储，不用人去点。"""
        with tempfile.TemporaryDirectory() as d:
            wd = StallWatchdog(timeout=0.3, dump_dir=pathlib.Path(d))
            wd.start()
            try:
                deadline = time.time() + 6
                while wd.dumps == 0 and time.time() < deadline:
                    time.sleep(0.05)
                self.assertGreater(wd.dumps, 0, "超时了却没自动转储")
                self.assertTrue(list(pathlib.Path(d).glob("stall-*.txt")))
            finally:
                wd.stop()

    def test_beating_prevents_dump(self):
        """★ 反向：正常打点**不该**转储 —— 否则程序健康时也刷假转储，没人会看。"""
        with tempfile.TemporaryDirectory() as d:
            wd = StallWatchdog(timeout=0.3, dump_dir=pathlib.Path(d))
            wd.start()
            try:
                for _ in range(16):
                    wd.beat()
                    time.sleep(0.05)
                self.assertEqual(wd.dumps, 0)
            finally:
                wd.stop()

    def test_creates_missing_directory(self):
        """用户数据目录可能还没建 —— 转储不能因此失败。"""
        with tempfile.TemporaryDirectory() as d:
            target = pathlib.Path(d) / "nested" / "deeper"
            wd = StallWatchdog(dump_dir=target)
            self.assertTrue(wd.dump(1.0).is_file())

    def test_timeouts_are_sane(self):
        """超时别定得太短（正常慢操作会误报），打点也够密。"""
        self.assertGreaterEqual(DEFAULT_TIMEOUT, 5.0)
        self.assertLess(HEARTBEAT_MS / 1000.0, DEFAULT_TIMEOUT / 4)


if __name__ == "__main__":
    unittest.main(verbosity=2)
