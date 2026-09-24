"""任务流程「交给引擎后引擎一直不取任务」的超时单测（2026-09-27）。

## 这次事故

用户报「应用卡死」。日志停在 ok 引擎的 ``enabled task``，ok-ww 自己的日志
（``data/okww/logs/ok-ww.log``）也是如此。**关键证据**：ok 的
``TaskExecutor.next_task()`` 在真把任务取走时会打一条
``get queued onetime_task`` —— 日志里**从来没有这一条**，只有 ``queued``。
也就是说：任务排进队列了，但引擎的执行线程没把它取走。

而 ``OkwwTaskRunner.run()`` 的退出条件只有

    host.running_task != TASK_KEY and host.pending_start != TASK_KEY

任务既然"已排队"，这个条件永远不成立 → **这个 while 无限空转**，
界面上永远「运行中」、停止也未必灵 —— 用户看到的就是"卡死"。

所以这里守：**引擎一直不取任务时必须认账退出**，而不是无限等下去。
"""

from __future__ import annotations

import pathlib
import sys
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.tools.game.echo_enhance import tool as echo_tool  # noqa: E402

TASK_KEY = echo_tool.TASK_KEY


class _FakeTask:
    """引擎里那个任务。

    对应事故现场的状态：**已 enable、但从没 running 过**
    （``_mark_task_enabled`` 把 ``_enabled`` 置了 True，executor 却没取走它）。
    """

    def __init__(self, *, running=False):
        self.enabled = True
        self.running = running
        self.info = {}


class _FakeHost:
    """只实现 runner 用到的那几个口子。"""

    def __init__(self, running_task=TASK_KEY, *, finish_after=None):
        self._running_task = running_task
        self.pending_start = None
        self.stopped = False
        self._finish_after = finish_after
        self._t0 = time.time()

    def start_task(self, key, configure=None):
        return None                 # None = 已受理

    def find_task(self, key):
        return _FakeTask(running=bool(self._finish_after))

    def poll_done(self):
        # 模拟"任务跑完自己收尾"：到点就把 running_task 清掉
        if self._finish_after is not None and time.time() - self._t0 > self._finish_after:
            self._running_task = None

    @property
    def running_task(self):
        return self._running_task

    def stop_task(self):
        self.stopped = True
        self._running_task = None
        return None


class TestStartTimeout(unittest.TestCase):
    """★ 引擎排了队却不执行 —— 不能无限空转。"""

    def _run(self, host, *, timeout):
        """跑一次 runner，返回异常（没有异常就返回 None）。

        ⚠ ``START_TIMEOUT`` 是**类属性**，改它等于改全局 —— 必须在 finally 里
        恢复，否则会影响这个文件里后续的用例（乃至其它模块）。
        """
        orig_host = echo_tool.get_host
        orig_timeout = echo_tool.OkwwTaskRunner.START_TIMEOUT
        echo_tool.get_host = lambda: host
        echo_tool.OkwwTaskRunner.START_TIMEOUT = timeout
        try:
            echo_tool.OkwwTaskRunner(None).run()
            return None
        except BaseException as exc:      # noqa: BLE001 - 要把异常带回去断言
            return exc
        finally:
            echo_tool.OkwwTaskRunner.START_TIMEOUT = orig_timeout
            echo_tool.get_host = orig_host

    def test_times_out_instead_of_spinning_forever(self):
        """★ 事故现场：任务排了队、引擎不取 → 超时认账，并把原因说清楚。"""
        host = _FakeHost()
        started = time.monotonic()
        exc = self._run(host, timeout=0.5)
        elapsed = time.monotonic() - started

        self.assertIsInstance(exc, RuntimeError, f"应超时退出，实际 {exc!r}")
        self.assertIn("还没开始跑", str(exc))
        self.assertLess(elapsed, 20, "0.5 秒的超时不该拖这么久")
        self.assertTrue(host.stopped, "超时必须顺手把引擎那边停掉")

    def test_must_time_out_at_all(self):
        """★ 前置断言：把超时**关掉**（设成很大）时它确实会一直转。

        没有这条，上面的用例可能是"因为别的原因退出"而侥幸通过 ——
        那就成了同义反复。
        """
        host = _FakeHost()
        orig_host = echo_tool.get_host
        orig_timeout = echo_tool.OkwwTaskRunner.START_TIMEOUT
        echo_tool.get_host = lambda: host
        echo_tool.OkwwTaskRunner.START_TIMEOUT = 3600.0     # 等于不超时
        try:
            # 在自己这边掐时间：转 1 秒还没结束，就说明"不设超时它会一直转"
            import threading
            done = threading.Event()

            def run():
                try:
                    echo_tool.OkwwTaskRunner(None).run()
                except BaseException:                        # noqa: BLE001
                    pass
                finally:
                    done.set()

            threading.Thread(target=run, daemon=True).start()
            self.assertFalse(done.wait(1.0), "不设超时时它应该一直在转（这才说明超时有用）")
        finally:
            echo_tool.OkwwTaskRunner.START_TIMEOUT = orig_timeout
            echo_tool.get_host = orig_host

    def test_running_task_is_not_timed_out(self):
        """★ 反向：任务**已经在跑**就不该超时 —— 强化本来就要很久。"""
        host = _FakeHost(finish_after=0.2)      # 0.2 秒后"跑完"
        exc = self._run(host, timeout=5.0)      # 超时给得比"跑完"久
        self.assertIsNone(exc, f"任务正常跑完不该报错，实际 {exc!r}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
