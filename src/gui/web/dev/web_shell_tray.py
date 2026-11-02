# -*- coding: utf-8 -*-
"""确认：WebShell 模式下**托盘不报错**、程序能正常退出。

lead 要求：「托盘 P1 先不挂，但要保留托盘代码并在 WebShell 模式下优雅跳过」。

## 检查什么

1. WebShell 上没有 `restore_from_tray` / `quit_app` 等方法时，
   **没有任何代码去调它们**（否则 AttributeError）
2. `main.py` 的窗口创建分支：WebShell 模式走 create_shell。
   **不经过 MainWindow.__init__ → _setup_tray()**
3. WebShell 提供了托盘会用到的**最小接口**
   （`windowTitle` / `windowIcon` / `objectName` / `close` /
   `show` / `hide` / `showMinimized` / `isVisible`），
   将来接托盘不需要改托盘代码
4. `main.py` 里 WebShell 分支**没有**引用 `_setup_tray` / 托盘相关

## 跑法

.. code:: powershell

    .venv\\Scripts\\python.exe src\\gui\\web\\dev\\web_shell_tray.py
"""

from __future__ import annotations

import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", "..", ".."))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)
os.environ.setdefault("QT_LOGGING_RULES", "qt.multimedia.*=false")

FAILS: list[str] = []


def ok(tag: str, cond: bool, note: str = "") -> None:
    print(f"[{'PASS' if cond else 'FAIL'}] {tag}  {note}")
    if not cond:
        FAILS.append(tag)


def main() -> int:
    # ── 1. 静态检查：main.py 的 WebShell 分支不碰托盘 ──────────────
    main_src = open(os.path.join(_ROOT, "main.py"), encoding="utf-8").read()
    #: 截出「use_web_shell」到「if window is None」之间那段
    start = main_src.find("use_web_shell = False")
    end = main_src.find("window = MainWindow()", start)
    web_branch = main_src[start:end] if start > 0 and end > start else ""

    ok("main_has_web_branch", bool(web_branch), f"{len(web_branch)} 字符")
    #: ★ 2026-11-02 改：Web 外壳**现在也有托盘了**（lead 指出的功能退化 ——
    #: 没有托盘时「关窗口」变成直接退出，正在跑的任务被中断）。
    #: 所以断言从「不该有托盘」反过来：「必须挂托盘」。
    ok("main_branch_sets_up_tray",
       "setup_tray" in web_branch,
       "Web 外壳分支里**要有** setup_tray()"
       "（缺了 = 关窗口直接退出，任务被中断）")
    ok("main_branch_calls_create_shell",
       "create_shell" in web_branch, "")

    # ── 2. 托盘代码仍然存在（没被删）──────────────────────────────
    ok("tray_module_kept",
       os.path.isfile(os.path.join(_ROOT, "src", "gui", "tray.py")),
       "src/gui/tray.py 还在")
    mw = open(os.path.join(_ROOT, "src", "gui", "main_window.py"),
              encoding="utf-8").read()
    ok("mainwindow_tray_kept", "_setup_tray" in mw,
       "MainWindow 仍会挂托盘（旧界面路径不变）")

    # ── 3. WebShell 提供托盘需要的最小接口 ───────────────────────
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    import src.tools as tools_pkg

    tools_pkg.discover_tools()
    from src.gui.web_shell import WebShell, web_base_url

    shell = WebShell(base_url=web_base_url())
    ok("built", shell.build(), "")
    shell.view.resize(900, 620)
    shell.view.show()
    app.processEvents()

    #: tray.py 里实际会调到的那些
    wanted = [
        ("windowTitle", "str"),
        ("windowIcon", "icon"),
        ("objectName", "str"),
        ("close", "call"),
        ("hide", "call"),
        ("show", "call"),
        ("showMinimized", "call"),
        ("showNormal", "call"),
        ("isVisible", "call"),
        ("resize", "call"),
        ("raise_", "call"),
        ("activateWindow", "call"),
    ]
    missing = [n for n, _kind in wanted
               if not hasattr(WebShell, n) and not hasattr(shell, n)]
    ok("tray_min_interface", not missing,
       f"缺失 = {missing}" if missing else f"{len(wanted)} 个方法都在")

    #: windowTitle 必须有内容（空串会让任务栏显示 "(无标题)"）
    ok("windowTitle_nonempty", bool(shell.windowTitle()),
       f"title={shell.windowTitle()!r}")
    ok("objectName_stable", shell.objectName() == "WebShellWindow",
       f"objectName={shell.objectName()!r}")

    # ── 4. 托盘那套方法**故意**不实现（P1 不迁移）────────────────
    #: 如果哪天真接了，这条会变成 FAIL —— 提醒去看 tray.py
    # ── 4. 托盘要用到的方法**现在必须有**（2026-11-02 实现）──
    still_missing = [n for n in ("restore_from_tray", "close_without_prompt",
                                 "set_update_badge", "refresh_notice_badge")
                     if hasattr(shell, n)]
    ok("tray_optional_methods_absent", not still_missing,
       f"实现了 = {still_missing}（这几个 P1 用不到）" if still_missing
       else "restore_from_tray / set_update_badge 等仍未实现（P1 不需要）")

    #: ★ 真正必须有的两个（托盘菜单 + 关闭确认要用）
    required = [n for n in ("setup_tray", "teardown_tray", "quit_app",
                            "_show_from_tray", "eventFilter")
                if not hasattr(shell, n)]
    ok("tray_required_methods_present", not required,
       f"缺失 = {required}" if required
       else "setup_tray / teardown_tray / quit_app / _show_from_tray / "
            "eventFilter 全部实现")

    # ── 5. force_quit 兼容性（托盘/退出逻辑会读）─────────────────
    ok("force_quit_property", shell.force_quit is False,
       f"force_quit={shell.force_quit}")

    shell.close()

    print()
    print("=" * 62)
    print("结果：" + ("全部通过" if not FAILS else "失败 " + str(FAILS)))
    print("=" * 62)
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
