# -*- coding: utf-8 -*-
"""给 Web 外壳截几个页面的图（人工复核用，不进产品）。

跑法::

    .venv\\Scripts\\python.exe src\\gui\\web_shell_shots.py

输出到 ``data/_shots/``。
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

OUT = os.path.join(_ROOT, "data", "_shots")

#: 要截的页面：(页面 key, 文件名)
PAGES = [
    ("home", "01-home"),
    ("tasks", "02-tasks"),
    ("config", "03-config"),
    ("skin", "04-skin"),
    ("library", "05-library"),
    ("tool:echo_enhance", "06-tool"),
]


def main() -> int:
    app = QApplication.instance() or QApplication([])
    import src.tools as tools_pkg  # noqa: PLC0415

    tools_pkg.discover_tools()

    from src.gui.web_shell import WebShell, web_base_url  # noqa: PLC0415

    os.makedirs(OUT, exist_ok=True)
    shell = WebShell(base_url=web_base_url())
    if not shell.build():
        print("build failed")
        return 1
    shell.view.resize(1400, 880)
    shell.view.show()

    index = {"i": 0}

    def step() -> None:
        i = index["i"]
        if i >= len(PAGES):
            print("done →", OUT)
            app.quit()
            return
        key, name = PAGES[i]
        shell.debug_js("window.App && App.go(%r); 'ok'" % key)
        #: 页面有淡入动画，等它跑完再抓
        QTimer.singleShot(1100, lambda: grab_and_advance(key, name))

    def grab_and_advance(key: str, name: str) -> None:
        path = os.path.join(OUT, name + ".png")
        img = shell.debug_screenshot(path)
        print(f"  {key:20s} → {name}.png  "
              f"({img.width()}x{img.height()})" if img else f"  {key} 截图失败")
        index["i"] += 1
        QTimer.singleShot(120, step)

    def on_load(ok: bool) -> None:
        if not ok:
            print("load failed")
            app.quit()
            return
        QTimer.singleShot(2800, step)

    shell.view.loadFinished.connect(on_load)
    QTimer.singleShot(45000, app.quit)
    app.exec()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
