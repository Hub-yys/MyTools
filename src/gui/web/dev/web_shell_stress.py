# -*- coding: utf-8 -*-
"""压力测试：Web 外壳的生命周期 / 事件洪泛 / 反复切页。

回答三个问题：
1. 反复 ``request_page`` + 大量 ``push_log`` 会不会让页面卡死或内存暴涨？
2. 日志 DOM 有 500 行上限，真的生效吗？
3. ``close()`` 之后进程能不能干净退出（不挂住）？
"""

from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", "..", ".."))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)
os.environ.setdefault("QT_LOGGING_RULES", "qt.multimedia.*=false")

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

PAGES = ["home", "tasks", "config", "skin", "library", "notice", "update"]
PUSHES = 800


def main() -> int:
    app = QApplication.instance() or QApplication([])
    import src.tools as tools_pkg  # noqa: PLC0415

    tools_pkg.discover_tools()
    from src.gui.web_shell import WebShell, web_base_url  # noqa: PLC0415

    shell = WebShell(base_url=web_base_url())
    if not shell.build():
        print("BUILD_FAIL")
        return 1
    print("BUILD OK")
    shell.view.resize(1100, 720)
    shell.view.show()

    def phase1() -> None:
        print("READY", shell.is_ready)
        layout = shell.debug_layout() or {}
        print("LAYOUT_KEYS", sorted(layout.keys()))

        #: 先进任务页，让 #task-log 存在
        shell.request_page("tasks")

        QTimer.singleShot(900, phase2)

    def phase2() -> None:
        #: 事件洪泛：800 条日志 + 进度
        for i in range(PUSHES):
            shell.push_log(f"flood line {i}", "info")
            shell.push_progress((i * 7) % 100, f"p{i}")
        print("PUSHED", PUSHES)
        QTimer.singleShot(1600, phase3)

    def phase3() -> None:
        n = shell.debug_js("document.querySelectorAll('.log-line').length")
        print("LOG_LINES_AFTER_FLOOD", n)
        #: 反复切页 7 个页面各 3 轮
        for _ in range(3):
            for p in PAGES:
                shell.request_page(p)
        QTimer.singleShot(1600, phase4)

    def phase4() -> None:
        print("PAGE_AFTER_CYCLING", shell.debug_js("window.App && App.page"))
        print(
            "ACTIVE_PAGES",
            shell.debug_js("document.querySelectorAll('.page.is-active').length"),
        )
        print(
            "RENDERED_SECTIONS",
            shell.debug_js("document.querySelectorAll('.page[data-rendered]').length"),
        )
        layout = shell.debug_layout() or {}
        vp = layout.get("viewport") or {}
        wl = layout.get("wallpaperLayer") or {}
        print("STILL_NO_TILING",
              wl.get("w") == vp.get("w") and wl.get("h") == vp.get("h"))
        print("CLOSING")
        shell.close()
        QTimer.singleShot(500, phase5)

    def phase5() -> None:
        print("NO_CRASH")
        app.quit()

    shell.view.loadFinished.connect(lambda ok: QTimer.singleShot(3000, phase1))
    QTimer.singleShot(45000, app.quit)
    app.exec()
    print("EXITED_CLEAN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
