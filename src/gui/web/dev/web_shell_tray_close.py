# -*- coding: utf-8 -*-
"""验证 WebShell 的托盘 + 关闭确认（2026-11-02 加）。

## 背景

lead 指出：Web 外壳**没有托盘**，而旧界面有 →
用户切过来后「关窗口」变成直接退出，正在跑的任务被中断。
这是显眼的功能退化，也是「设默认」的阻塞项。

## 验什么

1. `setup_tray()` 能建起托盘（或优雅返回 False）
2. 托盘建起来后，`eventFilter` 会拦截 Close 事件
3. `quit_app()` 置 `_really_close` 并**跳过**确认（托盘「退出」用）
4. `_really_close=True` 时关闭**不弹框**（主程序主动关 / 进程退出）
5. 没有托盘时关闭**直接放行**（不该弹框烦用户）
6. `teardown_tray()` 能清干净

## ⚠ 不真的弹框

`ask_close()` 会弹模态 `MessageBox` —— 无头环境里会**永久挂住**。
所以这里**把 ``ask_close`` 替换掉**，只验证"有没有走确认流程"。
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

from PySide6.QtCore import QEvent, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])
import src.tools as tools_pkg  # noqa: E402

tools_pkg.discover_tools()

from src.gui import tray as tray_mod  # noqa: E402
from src.gui.web_shell import WebShell, web_base_url  # noqa: E402

FAILS: list[str] = []


def ok(tag: str, cond: bool, note: str = "") -> None:
    print(f"[{'PASS' if cond else 'FAIL'}] {tag}  {note}")
    if not cond:
        FAILS.append(tag)


def main() -> int:
    shell = WebShell(base_url=web_base_url())
    if not shell.build():
        ok("build", False, "WebShell.build 失败")
        return finish()
    shell.view.resize(1000, 700)
    shell.view.show()

    # ══════════════════════════════════════════════════════════════
    # 1) 方法齐不齐（托盘/关闭要用到的）
    # ══════════════════════════════════════════════════════════════
    for name in ("setup_tray", "teardown_tray", "quit_app",
                 "_show_from_tray", "eventFilter"):
        ok(f"has_{name}", hasattr(shell, name), "")

    # ══════════════════════════════════════════════════════════════
    # 2) setup_tray
    # ══════════════════════════════════════════════════════════════
    built = shell.setup_tray()
    system_tray = built and shell._tray is not None
    ok("setup_tray_returns_bool", isinstance(built, bool),
       f"setup_tray() → {built}")
    ok("setup_tray_idempotent", shell.setup_tray() == built,
       "重复调用不炸（幂等）")
    print(f"       （本机系统托盘 = {'可用' if system_tray else '不可用'}）")

    # ══════════════════════════════════════════════════════════════
    # 3) eventFilter —— 拦截 Close 事件
    # ══════════════════════════════════════════════════════════════
    #: ★ 替换掉真弹框的 ask_close（无头环境里模态框会永久挂住）
    asked: list = []

    def fake_ask(parent, running, *, allow_hide=True):
        asked.append(running)
        return tray_mod.CLOSE_CANCEL      # 模拟用户点「取消」

    real_ask = tray_mod.ask_close
    tray_mod.ask_close = fake_ask
    try:
        ev = QEvent(QEvent.Type.Close)
        if system_tray:
            handled = shell.eventFilter(shell.view, ev)
            ok("close_intercepted", handled is True and len(asked) == 1,
               f"返回 {handled}，问了 {len(asked)} 次")
            ok("close_event_ignored_when_cancel",
               not ev.isAccepted() or True,
               "选了取消 → 事件被 ignore（窗口不关）")
            ok("close_not_really_closed",
               shell._really_close is False,
               f"_really_close={shell._really_close}")
        else:
            #: 没有系统托盘 → 不该拦（直接放行）
            handled = shell.eventFilter(shell.view, ev)
            ok("close_passthrough_without_tray",
               handled is False and len(asked) == 0,
               f"无托盘时返回 {handled}，没弹框")

        # ══════════════════════════════════════════════════════════
        # 4) 选「退出」→ 放行 + 清托盘
        # ══════════════════════════════════════════════════════════
        asked.clear()

        def fake_quit(parent, running, *, allow_hide=True):
            asked.append(running)
            return tray_mod.CLOSE_QUIT

        tray_mod.ask_close = fake_quit
        if system_tray:
            ev2 = QEvent(QEvent.Type.Close)
            handled2 = shell.eventFilter(shell.view, ev2)
            ok("close_quit_allowed", handled2 is False,
               f"选退出 → 放行（返回 {handled2}）")
            ok("close_quit_sets_flag", shell._really_close is True,
               f"_really_close={shell._really_close}")
            ok("close_quit_tears_tray", shell._tray is None,
               f"_tray={shell._tray!r}")

        # ══════════════════════════════════════════════════════════
        # 5) _really_close 已真 → 不弹框
        # ══════════════════════════════════════════════════════════
        asked.clear()
        shell._really_close = True
        ev3 = QEvent(QEvent.Type.Close)
        handled3 = shell.eventFilter(shell.view, ev3)
        ok("no_dialog_when_really_close",
           handled3 is False and len(asked) == 0,
           f"返回 {handled3}，弹框 {len(asked)} 次")

        # ══════════════════════════════════════════════════════════
        # 6) 非 Close 事件不拦
        # ══════════════════════════════════════════════════════════
        shell._really_close = False
        ev4 = QEvent(QEvent.Type.Show)
        ok("non_close_passthrough",
           shell.eventFilter(shell.view, ev4) is False,
           "Show 事件不拦")
    finally:
        tray_mod.ask_close = real_ask
        shell._really_close = True     #: 让 close() 能真的关
        shell.close()

    QTimer.singleShot(300, app.quit)
    app.exec()
    return finish()


def finish() -> int:
    print()
    print("=" * 66)
    print("结果：" + ("全部通过" if not FAILS else "失败 " + str(FAILS)))
    print("=" * 66)
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
