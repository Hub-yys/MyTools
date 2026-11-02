# -*- coding: utf-8 -*-
"""★ 把 Web 外壳接进 main.py 的**最小改动片段**（参考用，勿直接执行）。

## 为什么是「参考片段」而不是直接改 main.py

``main.py`` 不在本任务的写作用域里（Web 团队只负责
``src/core/web_bridge.py`` / ``src/gui/web_shell.py`` / ``src/gui/web/``）。
所以这里给出**逐行可抄**的补丁，由负责 ``main.py`` 的同学落地。

## 改动点只有 3 处

.. code:: text

    main.py
      ├─ import 区           +1 行
      ├─ 建窗口那段         替换成 if/else
      └─ 收尾（tray/watchdog）看情况

## 完整 diff（对着 main.py 现在的 234 行附近）

### ① import 区（第 190~193 行那段附近）

.. code:: diff

     from src.core.registry import ToolRegistry
     from src.gui.compat import app_icon
     from src.gui.main_window import MainWindow
    +from src.gui import web_shell
     from src.tools import discover_tools

### ② 建窗口（第 234 行 ``window = MainWindow()`` 那一行）

.. code:: diff

    -window = MainWindow()
    -window.show()
    +
    +#: ★ 新架构：整个窗口 = 一个 HTML 页面（见 src/gui/web_shell.py）
    +#: 开关：环境变量 MYTOOLS_WEB_SHELL=1 或 config.json 的 UI.WebShell
    +if web_shell.is_enabled():
    +    shell = web_shell.create_shell()
    +    if shell is not None:
    +        shell.show()
    +        #: 新外壳只管窗口；托盘/最小化等仍在 Qt 侧做（见下面 ③）
    +        window = shell
    +    else:
    +        logging.getLogger(__name__).warning(
    +            "Web 外壳起不来，退回旧界面")
    +        window = MainWindow()
    +        window.show()
    +else:
    +    window = MainWindow()
    +    window.show()

### ③ 收尾那几行要兼容两种 window

``main.py`` 后面还有三处用了 ``window``：

.. code:: python

    watchdog = StallWatchdog(dump_dir=paths.user_data_dir())
    watchdog.start()
    _heartbeat = QTimer(window)      # ← 要求 window 是 QObject
    _heartbeat.timeout.connect(watchdog.beat)
    _heartbeat.start()

    app.aboutToQuit.connect(_shutdown_okww_host)
    return app.exec()

``QTimer(window)`` 要求 ``window`` 是 ``QObject`` ——
:class:`src.gui.web_shell.WebShell` **是** ``QObject`` 的子类，
所以这行**不用改**。✅

## 仍然保留在 Qt 侧的（不在 P1 范围）

* **托盘图标** ``src/gui/tray.py`` —— 依赖 ``MainWindow`` 的方法
  （``restore_from_tray`` / ``quit_app`` / ``close_without_prompt``）。
  Web 外壳没实现这些，所以**开 Web 外壳时先不挂托盘**，
  或者给 ``WebShell`` 补上同名方法（下面给了个最小版）。

* **「任务启动就最小化」** —— ``main_window.task_started`` 信号驱动。
  Web 外壳要接的话：把 ``bridge.taskStarted`` 连到
  ``shell.showMinimized()`` 即可（已留信号）。

* **启动看门狗 / ok-ww 自启** —— 和窗口无关，照旧。

## 给 WebShell 补托盘要用到的最小接口

``src/gui/tray.py`` 里对 window 的调用（照着补就能复用托盘）：

.. code:: python

    class WebShell:
        def restore_from_tray(self):     self.showNormal(); self.show()
        def quit_app(self):              self.close()          # 主程序收到 closed 再退
        def close_without_prompt(self):  self.close()
        def set_update_badge(self, v=""): ...   # 侧栏黄字，P2 接
        def refresh_notice_badge(self):   ...
        def minimize_on_task_start(self): self.showMinimized()
        def minimize_after_task(self):    self.showMinimized()
        def windowIcon(self):             return self._window_icon
        def objectName(self):             return "WebShellWindow"

⚠ 这些**故意没写进** :mod:`src.gui.web_shell` —— P1 的目标是先证明
「整窗 HTML + 无平铺」成立，托盘是锦上添花，等功能迁完再加。

## 想立刻看新外壳（不改 main.py）

.. code:: powershell

    cd "D:\\AI Work\\workbuddy\\MyTools"
    $env:MYTOOLS_WEB_SHELL = "1"
    .venv\\Scripts\\python.exe main.py      # ← 但 main.py 还没接，看不到

    # 或者直接跑验证/截图脚本（这两个已经接好，推荐）：
    .venv\\Scripts\\python.exe src\\gui\\web_shell_verify.py
    .venv\\Scripts\\python.exe src\\gui\\web_shell_shots.py
"""

from __future__ import annotations


def _patch_notes() -> dict:
    """机器可读的改动摘要（给 lead 的落地清单用）。"""
    return {
        "file": "main.py",
        "changes": [
            {
                "where": "import 区（约 190~193 行）",
                "add": ["from src.gui import web_shell"],
                "remove": [],
            },
            {
                "where": "约 234 行 `window = MainWindow()` / `window.show()`",
                "replace_with": (
                    "if web_shell.is_enabled():\n"
                    "    shell = web_shell.create_shell()\n"
                    "    if shell is not None:\n"
                    "        shell.show()\n"
                    "        window = shell\n"
                    "    else:\n"
                    "        window = MainWindow()\n"
                    "        window.show()\n"
                    "else:\n"
                    "    window = MainWindow()\n"
                    "    window.show()"
                ),
                "remove": ["window = MainWindow()", "window.show()"],
            },
        ],
        #: 后面几行**不用改**（WebShell 是 QObject，QTimer(window) 能用）
        "unchanged": [
            "_heartbeat = QTimer(window)",
            "app.aboutToQuit.connect(_shutdown_okww_host)",
            "return app.exec()",
        ],
        #: 开新外壳时这些要显式关掉/跳过（P1 不迁移）
        "skip_when_web_shell": ["_setup_tray()（托盘，依赖 MainWindow 方法）"],
        "enable": [
            "环境变量: $env:MYTOOLS_WEB_SHELL = '1'",
            "或 config.json: {\"UI\": {\"WebShell\": true}}",
        ],
    }


if __name__ == "__main__":
    import json

    print(json.dumps(_patch_notes(), ensure_ascii=False, indent=2))
