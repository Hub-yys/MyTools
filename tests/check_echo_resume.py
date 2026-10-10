# -*- coding: utf-8 -*-
"""验证「继续」按钮的判据与行为（假宿主，不碰真引擎）。"""
import pathlib
import sys
import types

sys.stdout.reconfigure(encoding="utf-8")
ROOT = pathlib.Path(r"D:\AI Work\workbuddy\MyTools")
sys.path.insert(0, str(ROOT))

import os  # noqa: E402

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

from src.tools.game.echo_enhance import tool as T  # noqa: E402


class FakeTask:
    def __init__(self, paused=False, enabled=True, running=True):
        self.paused = paused
        self.enabled = enabled
        self.running = running
        self.unpause_calls = 0

    def unpause(self):
        self.unpause_calls += 1
        self.paused = False


class FakeHost:
    def __init__(self, task):
        self.task = task
        self.state = "running"
        self.running_task = None
        self.pending_start = None
        self.boot_error = None

    def find_task(self, key):
        return self.task

    def take_start_error(self):
        return None

    def poll_done(self):
        return None


def make_page(task):
    """造一个只带 _poll 所需字段的页面（绕过构造里的引擎依赖）。"""
    page = T.EchoEnhanceWidget.__new__(T.EchoEnhanceWidget)
    page._host = FakeHost(task)
    page._last_state = ""
    page._was_running = False
    page._was_paused = False
    page._task_seen = False
    page._last_stats = {}
    page._auto_stop_reported = ""
    page._echo_key = ()
    page._append = lambda msg: None

    from PySide6.QtWidgets import QPushButton, QVBoxLayout, QWidget

    from qfluentwidgets import CaptionLabel

    page.run_button = QPushButton()
    page.resume_button = QPushButton()
    page.stop_button = QPushButton()
    page.report_label = CaptionLabel()
    page.echo_area = QWidget()
    page.echo_box = QVBoxLayout(page.echo_area)
    #: ⚠ 用 ``__new__`` 绕过构造时 Qt 的基类没初始化，``self.window()`` 会抛
    #: ``libshiboken: '__init__' method of object's base class not called``。
    #: InfoBar 的 parent 参数要用它 → 这里顶一个假的。
    page.window = lambda: None
    return page


CHECKS = []


def check(name, ok, detail=""):
    CHECKS.append((name, bool(ok), detail))


#: ① 暂停中 → 「继续」可用
task = FakeTask(paused=True)
page = make_page(task)
page._poll()
check("任务暂停时「继续」可用", page.resume_button.isEnabled(),
      f"enabled={page.resume_button.isEnabled()}")

#: ② 没暂停 → 「继续」灰掉
task2 = FakeTask(paused=False)
page2 = make_page(task2)
page2._poll()
check("没暂停时「继续」是灰的", not page2.resume_button.isEnabled())

#: ③ 点「继续」→ 调 task.unpause()
page2b = make_page(task2)
page2b._poll()
page2b._on_resume()
check("点「继续」调了 unpause()", task2.unpause_calls == 1,
      f"调用 {task2.unpause_calls} 次")

#: ④ 没有任务时点「继续」→ 不炸
page3 = make_page(None)
page3._on_resume()
check("没有任务时点「继续」不抛异常", True)

#: ⑤ unpause 抛异常 → 不炸、有提示
class Boom(FakeTask):
    def unpause(self):
        raise RuntimeError("引擎没醒")


page4 = make_page(Boom(paused=True))
page4._poll()
page4._on_resume()
check("unpause 抛异常时被兜住", True)

print()
bad = [c for c in CHECKS if not c[1]]
for name, ok, det in CHECKS:
    print("  [%s] %s%s" % ("PASS" if ok else "FAIL", name,
                           ("   " + det) if det else ""))
print()
print("★", "全部通过" if not bad else "⚠ 见上面的 FAIL")
sys.exit(1 if bad else 0)
