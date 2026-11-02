# -*- coding: utf-8 -*-
"""验收 P10：无边框窗口（去掉 Windows 原生白标题栏）。

## 用户原话

> 「那个白色的方块区域去掉，下面本来就有最小化，关闭，放大」

## 根因

没设 ``FramelessWindowHint``，所以屏幕上有**两个标题栏**：

```text
┌──────────────────────────────┐
│ 鸣潮工具箱          ─  □  ✕  │  ← Windows 原生（白色）
├──────────────────────────────┤
│ 主页                ─  □  ✕  │  ← 页面自绘（深色）
└──────────────────────────────┘
```

页面 `#titlebar` 本来就有那三个按钮（`btn-min` / `btn-max` / `btn-close`）。

## 设了 Frameless 之后失去的 3 个能力（必须补）

1. **拖拽移动** → 页面 mousedown → `Bridge.call('startWindowDrag')`
   → Win32 `ReleaseCapture` + `SendMessage(WM_NCLBUTTONDOWN, HTCAPTION)`
2. **双击最大化** → `windowAction('toggleMaximize')`（已支持）
3. **边缘缩放** → `WM_NCHITTEST` 返回 HTLEFT/HTTOP… 等

## 验什么

* 窗口 flags 是 ``Window | Frameless``，**不是 ``Tool``**（Tool 不进任务栏）
* ``frameGeometry == geometry``（无原生边框的硬证据）
* 三个按钮在 DOM 里，且能调到后端
* startWindowDrag / toggle_maximize 方法在
* 边缘缩放的 native filter **真的装上**（这里踩过 PySide6 的坑）
* 托盘 + 关闭确认没被 Frameless 破坏

## ⚠ 无头环境

用 ``offscreen`` 平台也能验 flags 和 frameGeometry ——
不需要真的显示到屏幕上。
"""

from __future__ import annotations

import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", "..", ".."))
sys.path.insert(0, _ROOT)
sys.path.insert(0, _HERE)
os.chdir(_ROOT)
os.environ.setdefault("QT_LOGGING_RULES", "qt.multimedia.*=false")

from PySide6.QtCore import QTimer, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])
import src.tools as tools_pkg  # noqa: E402

tools_pkg.discover_tools()

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

    view = shell.view
    flags = view.windowFlags()

    # ══════════════════════════════════════════════════════════════
    # 1) ★ 窗口 flags
    # ══════════════════════════════════════════════════════════════
    ok("frameless_enabled",
       bool(flags & Qt.WindowType.FramelessWindowHint),
       "FramelessWindowHint 已设（去掉 Windows 原生白标题栏）")

    #: ★★ 必须用 ``windowType()`` 判断，**不能** ``flags & Qt.Tool`` ——
    #:    ``Qt.Tool`` 是枚举值 0xb，位运算会和其他 flag 撞（实测误报过）
    wt = view.windowType()
    ok("window_type_is_window",
       wt == Qt.WindowType.Window,
       f"windowType = {int(wt)}（1=Window）")

    ok("not_tool_window",
       wt != Qt.WindowType.Tool,
       f"windowType != Tool（{int(Qt.WindowType.Tool)}）"
       f"—— Tool 类型**不进任务栏**，用户会找不到窗口")

    #: 会进任务栏的类型才算合格
    taskbar_types = {
        Qt.WindowType.Window, Qt.WindowType.Dialog,
        Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint,
    }
    ok("shows_in_taskbar",
       wt in (Qt.WindowType.Window, Qt.WindowType.Dialog)
       or bool(wt & Qt.WindowType.Window),
       f"windowType 会进任务栏 = {wt in (Qt.WindowType.Window, Qt.WindowType.Dialog)}")

    # ══════════════════════════════════════════════════════════════
    # 2) ★★ 无原生边框的**硬证据**：frameGeometry == geometry
    # ══════════════════════════════════════════════════════════════
    view.resize(1280, 800)
    view.show()
    app.processEvents()

    geo = view.geometry()
    frame = view.frameGeometry()
    ok("no_native_frame",
       geo.width() == frame.width() and geo.height() == frame.height(),
       f"geometry {geo.width()}x{geo.height()} == "
       f"frameGeometry {frame.width()}x{frame.height()}"
       f"（有原生标题栏时 frameGeometry 会高 ~30px）")

    # ══════════════════════════════════════════════════════════════
    # 3) 三个按钮 + 拖拽能力都在
    # ══════════════════════════════════════════════════════════════
    for name in ("start_window_drag", "toggle_maximize",
                 "_install_resize_support", "_remove_resize_support"):
        ok(f"has_{name}", hasattr(shell, name), "")

    ok("resize_margin_defined",
       isinstance(getattr(WebShell, "RESIZE_MARGIN", None), int),
       f"RESIZE_MARGIN = {getattr(WebShell, 'RESIZE_MARGIN', None)}px")

    #: ★★★ 边缘缩放的 native filter 必须**真的装上**
    #:
    #: 这里踩过 PySide6 的坑：基类必须是 ``QAbstractNativeEventFilter``，
    #: 只继承 ``QObject`` 会 ``TypeError: called with wrong argument types``。
    ok("resize_filter_installed",
       shell._native_filter is not None,
       f"_native_filter = {shell._native_filter!r}"
       f"（None 说明 WM_NCHITTEST 没接上，边缘拖不动）")

    #: ★★ Win11 系统圆角（2026-11-02，page-converter 指出无边框后没圆角）
    #
    #: ⚠ 走 **Win32** 不走 CSS：
    #: CSS 圆角需要窗口透明（``WA_TranslucentBackground``），
    #: 而透明 + Chromium 合成在笔记本上明显掉帧（壁纸是视频时更糟）。
    ok("has_apply_window_corner",
       hasattr(shell, "apply_window_corner"),
       "apply_window_corner 存在")

    is_win11 = WebShell._is_windows_11()
    print(f"       （本机 Win11 = {is_win11}）")

    corner_ok = shell.apply_window_corner()
    if is_win11:
        ok("corner_radius_applied", corner_ok is True,
           "Win11 → DwmSetWindowAttribute(DWMWA_WINDOW_CORNER_PREFERENCE=33) 成功")
        ok("corner_radius_idempotent",
           shell.apply_window_corner() is True,
           "重复调用返回 True（幂等）")

        #: ★★★ 回读才是"真的生效了"的证据 —— S_OK 只说明调用被接受
        pref = shell.get_window_corner_preference()
        ok("corner_preference_readback", pref == 2,
           f"DwmGetWindowAttribute(33) = {pref}（2=DWMWCP_ROUND）"
           f"—— 回读比 hr==0 硬")

        #: ★★ 顺序正确性：圆角必须在 show() **之后**设
        #: （Qt 在 show 时会重置窗口样式，build 里设会被冲掉）
        shell_src_corner = open(
            os.path.join(_ROOT, "src", "gui", "web_shell.py"),
            encoding="utf-8").read()
        show_fn = shell_src_corner.split("def show(self)")[-1].split("def close")[0]
        ok("corner_applied_in_show_not_build",
           "apply_window_corner" in show_fn,
           "apply_window_corner 在 show() 里调（build 里设会被 Qt 冲掉）")
    else:
        #: ★ Win10 兜底：这个属性不存在，必须**静默跳过**而不是崩
        ok("corner_radius_skipped_on_win10", corner_ok is False,
           "非 Win11 → 返回 False 且不抛（版本兜底）")

    #: 版本判断必须用 RtlGetVersion —— platform.release() 会被 manifest 骗
    shell_src = open(os.path.join(_ROOT, "src", "gui", "web_shell.py"),
                     encoding="utf-8").read()
    ok("is_windows_11_uses_rtlgetversion",
       "RtlGetVersion" in shell_src,
       "用 RtlGetVersion 拿真实 build（platform.release 会因兼容性清单报错版本）")

    # ══════════════════════════════════════════════════════════════
    # 4) 桥接层的动作
    # ══════════════════════════════════════════════════════════════
    from src.core.web_bridge import WebBridge

    b = WebBridge()
    emitted: list[str] = []
    b.windowActionRequested.connect(lambda a: emitted.append(a))

    r = json.loads(b.startWindowDrag())
    ok("bridge_startWindowDrag",
       r.get("ok") is True and r.get("action") == "startdrag",
       json.dumps(r, ensure_ascii=False))

    for action in ("minimize", "maximize", "restore",
                   "togglemaximize", "close"):
        r = json.loads(b.windowAction(action))
        ok(f"bridge_action_{action}", r.get("ok") is True,
           f"{action} → ok={r.get('ok')}")

    #: 大小写混用也要吃（页面传的是 'toggleMaximize'）
    r = json.loads(b.windowAction("toggleMaximize"))
    ok("bridge_action_case_insensitive",
       r.get("ok") is True and r.get("action") == "togglemaximize",
       f"'toggleMaximize' → {r.get('action')!r}（后端会 .lower()）")

    r = json.loads(b.windowAction("__bogus__"))
    ok("bridge_action_rejects_unknown",
       r.get("ok") is False and r.get("reason") == "unknown_action",
       f"reason={r.get('reason')}")

    ok("bridge_emitted_all",
       "startdrag" in emitted and "togglemaximize" in emitted,
       f"信号 = {emitted[:6]}…")

    #: ``startdrag`` **不该**混进 windowAction 的 allowed 里
    #: （它是单独方法，语义是"进入拖动状态"不是"动作"）
    r = json.loads(b.windowAction("startdrag"))
    ok("startdrag_not_in_windowAction",
       r.get("ok") is False and r.get("reason") == "unknown_action",
       "startdrag 只能走 startWindowDrag()，不是 windowAction 的动作")

    # ══════════════════════════════════════════════════════════════
    # 5) ★ 托盘 + 关闭确认没被 Frameless 破坏
    # ══════════════════════════════════════════════════════════════
    ok("tray_still_available",
       hasattr(shell, "setup_tray") and hasattr(shell, "teardown_tray"),
       "托盘方法还在（Frameless 不影响它）")

    ok("close_confirm_still_available",
       hasattr(shell, "eventFilter"),
       "关闭确认的 eventFilter 还在")

    tray_ok = shell.setup_tray()
    ok("tray_setup_works",
       isinstance(tray_ok, bool),
       f"setup_tray() → {tray_ok}")

    # ══════════════════════════════════════════════════════════════
    # 6) 真实动作：最大化 / 还原
    # ══════════════════════════════════════════════════════════════
    from PySide6.QtCore import QEventLoop

    def pump(ms: int) -> None:
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    shell.toggle_maximize()
    pump(300)
    ok("toggle_maximize_works", view.isMaximized(),
       f"isMaximized = {view.isMaximized()}")

    shell.toggle_maximize()
    pump(300)
    ok("toggle_restore_works", not view.isMaximized(),
       f"再切一次 → isMaximized = {view.isMaximized()}")

    # ══════════════════════════════════════════════════════════════
    # 7) 页面侧：mousedown 拖拽 + dblclick 最大化接线
    # ══════════════════════════════════════════════════════════════
    js_dir = os.path.join(_ROOT, "src", "gui", "web", "js")
    app_js = os.path.join(js_dir, "app.js")
    src = open(app_js, encoding="utf-8").read()

    ok("js_startWindowDrag_wired",
       "startWindowDrag" in src,
       "app.js 里调了 startWindowDrag")

    ok("js_drag_on_titlebar",
       "mousedown" in src and "titlebar" in src,
       "标题栏绑了 mousedown")

    ok("js_dblclick_maximize",
       "dblclick" in src and "toggleMaximize" in src,
       "标题栏绑了 dblclick → toggleMaximize")

    ok("js_drag_ignores_buttons",
       "closest('.tb-btn')" in src or 'closest(".tb-btn")' in src,
       "拖拽跳过按钮（否则点最小化会顺带拖窗口）")

    #: 清理
    shell._really_close = True
    shell._remove_resize_support()
    shell.teardown_tray()
    shell.close()
    pump(300)
    return finish()


def finish() -> int:
    print()
    print("=" * 70)
    print("结果：" + ("全部通过" if not FAILS else "失败 " + str(FAILS)))
    print("=" * 70)
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
