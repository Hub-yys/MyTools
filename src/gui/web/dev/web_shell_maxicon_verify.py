# -*- coding: utf-8 -*-
"""验证 —— 标题栏 □ 按钮图标随窗口状态切换（真实鼠标点击）。

## 用户报的问题

    放大后，这个缩小框不对把，应该右图那样

窗口最大化后，□ 按钮还是显示「单个方框」（最大化图标 ``E922``），
但这时候点它是「还原」，应该显示「两个叠起来的方框」（``E923``）。

## 这个脚本验什么

  W1 页面加载时 □ 按钮是 ``E922``（未最大化）
  W2 点 □ 最大化 → 图标变 ``E923``
  W3 tooltip / aria-label 也变成「还原」
  W4 再点 □ 还原 → 图标变回 ``E922``
  W5 双击标题栏最大化 → 图标也变 ``E923``（不只按钮那条路）
  W6 最大化时 ``getWindowState()`` 返回 maximized=True
  W7 最大化时图标**真的渲染出来了**（不是空白 —— 字体缺字时会是豆腐块）

跑法::

    .venv\\Scripts\\python.exe src\\gui\\web\\dev\\web_shell_maxicon_verify.py
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import json
import os
import sys
import threading
import time

ROOT = r"D:\AI Work\workbuddy\MyTools"
sys.path.insert(0, ROOT)
os.chdir(ROOT)
os.environ.setdefault("QT_LOGGING_RULES", "qt.multimedia.*=false")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

user32 = ctypes.windll.user32
user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]

#: ChromeMaximize / ChromeRestore
GLYPH_MAX = "\uE922"
GLYPH_RESTORE = "\uE923"

RESULTS: list[tuple[str, bool, str]] = []


def log(m=""):
    print(m, flush=True)


def ok(case, passed, note=""):
    RESULTS.append((case, bool(passed), note))
    log(f"[{'PASS' if passed else 'FAIL'}] {case}  {note}")


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD),
                ("dwFlags", wt.DWORD), ("time", wt.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


class INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT), ("pad", ctypes.c_byte * 32)]
    _anonymous_ = ("u",)
    _fields_ = [("type", wt.DWORD), ("u", _U)]


def _send(flags):
    inp = INPUT()
    inp.type = 0
    inp.mi.dwFlags = flags
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def click_at(x, y):
    """真鼠标单击一次。"""
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.25)
    _send(0x0002)
    time.sleep(0.12)
    _send(0x0004)
    time.sleep(0.40)


def wrect(hwnd):
    r = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


#: 读 □ 按钮当前状态的 JS
JS_READ = """
(function () {
  var el = document.getElementById('btn-max');
  if (!el) return JSON.stringify({error: 'no #btn-max'});
  var cs = getComputedStyle(el);
  //: 用 canvas 量一下这个字形到底画不画得出来（缺字会量成 0 宽或者方块）
  var cv = document.createElement('canvas');
  var ctx = cv.getContext('2d');
  ctx.font = cs.fontSize + ' ' + cs.fontFamily;
  var w = ctx.measureText(el.textContent || '').width;
  return JSON.stringify({
    text: el.textContent,
    codePoint: (el.textContent || '').codePointAt(0),
    hex: '0x' + ((el.textContent || '').codePointAt(0) || 0).toString(16).toUpperCase(),
    title: el.title,
    ariaLabel: el.getAttribute('aria-label'),
    dataState: el.getAttribute('data-state'),
    fontFamily: cs.fontFamily,
    fontSize: cs.fontSize,
    glyphWidth: w,
    w: el.offsetWidth, h: el.offsetHeight
  });
})()
"""


def main():
    app = QApplication.instance() or QApplication([])
    import src.tools as tools_pkg

    tools_pkg.discover_tools()
    from src.gui.web_shell import WebShell, web_base_url

    shell = WebShell(base_url=web_base_url())
    if not shell.build():
        log("build failed")
        return 1
    view = shell.view
    view.resize(1100, 720)
    shell.show()
    h = {"hwnd": None}

    def read_btn():
        raw = shell.debug_js(JS_READ)
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except ValueError:
            return {}

    def btn_screen_pos():
        """□ 按钮中心的**物理屏幕坐标**。"""
        raw = shell.debug_js("""
        (function(){
          var el = document.getElementById('btn-max');
          if (!el) return null;
          var rc = el.getBoundingClientRect();
          return JSON.stringify({x: Math.round(rc.left + rc.width/2),
                                 y: Math.round(rc.top + rc.height/2)});
        })()
        """)
        if not raw:
            return None
        info = json.loads(raw)
        l, t, r, b = wrect(h["hwnd"])
        dpr = view.devicePixelRatioF()
        return int(l + info["x"] * dpr), int(t + info["y"] * dpr)

    def on_load(loaded):
        log(f"页面加载 ok={loaded}")
        QTimer.singleShot(3000, w1)

    # ── W1 初始状态 ───────────────────────────────────────────────────
    def w1():
        h["hwnd"] = int(view.winId())
        log(f"hwnd={h['hwnd']}  DPR={view.devicePixelRatioF()}")
        st = read_btn()
        log(f"    按钮状态 = {st}")
        ok("W1 初始图标 = E922（最大化）",
           st.get("codePoint") == 0xE922,
           f"当前 {st.get('hex')} title={st.get('title')!r}")
        ok("W1b 初始 tooltip = 最大化",
           st.get("title") == "最大化",
           f"title={st.get('title')!r} aria={st.get('ariaLabel')!r}")
        QTimer.singleShot(400, w2)

    # ── W2 点 □ → 最大化，图标应变 E923 ──────────────────────────────
    def w2():
        pos = btn_screen_pos()
        if not pos:
            ok("W2 最大化后图标变 E923", False, "找不到 #btn-max")
            return finish()
        h["btnpos"] = pos
        log(f"\n[W2] 点 □  物理坐标={pos}  点前 isMax={view.isMaximized()}")
        threading.Thread(target=click_at, args=pos, daemon=True).start()
        QTimer.singleShot(2200, after_w2)

    def after_w2():
        st = read_btn()
        log(f"    isMaximized={view.isMaximized()}  按钮 = {st}")
        ok("W2 最大化后图标 = E923（还原）",
           st.get("codePoint") == 0xE923,
           f"当前 {st.get('hex')}  text={st.get('text')!r}")
        ok("W3 最大化后 tooltip = 还原",
           st.get("title") == "还原" and st.get("ariaLabel") == "还原",
           f"title={st.get('title')!r} aria={st.get('ariaLabel')!r}"
           f" data-state={st.get('dataState')!r}")
        ok("W7 图标真的渲染出来（不是豆腐块）",
           float(st.get("glyphWidth") or 0) > 0,
           f"字形宽度={st.get('glyphWidth')}px "
           f"字体={st.get('fontFamily')!r} 字号={st.get('fontSize')}")
        QTimer.singleShot(500, w6)

    # ── W6 getWindowState ─────────────────────────────────────────────
    def w6():
        log("\n[W6] getWindowState() 回读")
        raw = shell.debug_js(
            "(function(){ if (typeof Bridge === 'undefined' || !Bridge) return null;"
            " return JSON.stringify({maximized: Bridge._lastState}); })()")
        #: 直接问 Python 侧（比绕 JS 稳）
        try:
            state = json.loads(shell.bridge.getWindowState())
        except Exception as exc:  # noqa: BLE001
            state = {"error": str(exc)}
        ok("W6 getWindowState() 返回最大化",
           state.get("maximized") is True,
           f"{state}  (JS 上下文 {raw})")
        QTimer.singleShot(400, w4)

    # ── W4 再点 □ → 还原，图标应回 E922 ──────────────────────────────
    def w4():
        pos = btn_screen_pos()
        if not pos:
            ok("W4 还原后图标回 E922", False, "找不到 #btn-max")
            return finish()
        log(f"\n[W4] 再点 □  物理坐标={pos}  点前 isMax={view.isMaximized()}")
        threading.Thread(target=click_at, args=pos, daemon=True).start()
        QTimer.singleShot(2200, after_w4)

    def after_w4():
        st = read_btn()
        log(f"    isMaximized={view.isMaximized()}  按钮 = {st}")
        ok("W4 ★ 还原后图标回 E922",
           st.get("codePoint") == 0xE922 and not view.isMaximized(),
           f"isMax={view.isMaximized()} 图标={st.get('hex')}")
        ok("W4b 还原后 tooltip = 最大化",
           st.get("title") == "最大化",
           f"title={st.get('title')!r}")
        QTimer.singleShot(500, w5)

    # ── W5 双击标题栏也要换图标 ───────────────────────────────────────
    def w5():
        l, t, r, b = wrect(h["hwnd"])
        x, y = (l + r) // 2, t + 22      # 标题栏中段（不在按钮上）
        log(f"\n[W5] 双击标题栏 ({x},{y})  双击前 isMax={view.isMaximized()}")

        def worker():
            user32.SetCursorPos(int(x), int(y))
            time.sleep(0.25)
            for _ in range(2):
                _send(0x0002)
                time.sleep(0.04)
                _send(0x0004)
                time.sleep(0.06)
            time.sleep(0.40)

        threading.Thread(target=worker, daemon=True).start()
        QTimer.singleShot(2600, after_w5)

    def after_w5():
        st = read_btn()
        log(f"    isMaximized={view.isMaximized()}  按钮 = {st}")
        ok("W5 ★ 双击标题栏最大化后图标 = E923",
           view.isMaximized() and st.get("codePoint") == 0xE923,
           f"isMax={view.isMaximized()} 图标={st.get('hex')} "
           f"tooltip={st.get('title')!r}")
        QTimer.singleShot(400, finish)

    def finish():
        log("\n" + "=" * 74)
        passed = sum(1 for _, p, _ in RESULTS if p)
        log(f"结果：{passed}/{len(RESULTS)} 通过")
        for case, p, note in RESULTS:
            log(f"  {'PASS' if p else 'FAIL'}  {case}")
        QTimer.singleShot(250, app.quit)

    view.loadFinished.connect(on_load)
    QTimer.singleShot(120000, app.quit)
    app.exec()
    return 0 if all(p for _, p, _ in RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
