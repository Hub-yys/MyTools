# -*- coding: utf-8 -*-
"""验证脚本 —— 拖拽 / 缩放 / 放大后缩小（真实鼠标输入）。

跑的是 **src/gui/web_shell.py 里的真实实现**（不复制粘贴任何逻辑），
只把「鼠标」换成 SendInput 注入的真事件、把「点按钮」换成页面里真的
DOM 点击。

断言：
  V1  标题栏真鼠标拖动 → 窗口移动
  V2  最大化后拖标题栏 → 还原
  V3  拉右边界往外 → 变宽
  V4  拉右边界往里 → 变窄     ← 用户报的「放大后不能缩小」
  V5  拉下边界 → 变高
  V6  拉右下角 → 同时变宽变高
  V7  内容区点击仍能到页面（没被边缘判定误伤）
  V8  最大化时边缘不是拉伸游标（返回 HTCLIENT）
  V9  □ 按钮第一次点击 → 最大化
  V10 □ 按钮第二次点击 → **还原**   ← 用户报的核心 bug
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
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
user32.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, wt.UINT]

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


def real_drag(pts, hold=0.08):
    user32.SetCursorPos(int(pts[0][0]), int(pts[0][1]))
    time.sleep(0.25)
    _send(0x0002)
    time.sleep(0.20)
    for x, y in pts[1:]:
        user32.SetCursorPos(int(x), int(y))
        time.sleep(hold)
    time.sleep(0.12)
    _send(0x0004)
    time.sleep(0.30)


def wrect(hwnd):
    r = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def size(hwnd):
    l, t, r, b = wrect(hwnd)
    return (r - l, b - t, l, t)


def nchittest(hwnd, sx, sy):
    lp = ((int(sy) & 0xFFFF) << 16) | (int(sx) & 0xFFFF)
    user32.SendMessageW.restype = ctypes.c_ssize_t
    user32.SendMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
    return user32.SendMessageW(hwnd, 0x0084, 0, lp)


def place(hwnd, x, y, w, h):
    user32.SetWindowPos(hwnd, wt.HWND(0), x, y, w, h, 0x0004)


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

    def on_load(loaded):
        log(f"页面加载 ok={loaded}")
        QTimer.singleShot(2800, v1)

    # ── V1 标题栏拖动 ──────────────────────────────────────────────────
    def v1():
        hwnd = int(view.winId())
        h["hwnd"] = hwnd
        place(hwnd, 150, 120, 1250, 875)
        h["d0"] = size(hwnd)
        l, t, r, b = wrect(hwnd)
        sx, sy = (l + r) // 2, t + 22
        log(f"\n[V1] 标题栏真鼠标拖动  起点({sx},{sy})  前 {h['d0']}")
        pts = [(sx, sy)] + [(sx + 22 * i, sy + 9 * i) for i in range(1, 7)]
        threading.Thread(target=real_drag, args=(pts,), daemon=True).start()
        QTimer.singleShot(3200, lambda: after_v1(h["d0"]))

    def after_v1(base):
        after = size(h["hwnd"])
        #: 窗口应该移动（位置变），尺寸不变
        ok("V1 标题栏拖动", after != base,
           f"{base} → {after}")
        #: 归位
        place(h["hwnd"], 150, 120, 1250, 875)
        QTimer.singleShot(500, v2)

    # ── V2 最大化后拖标题栏还原 ────────────────────────────────────────
    def v2():
        log("\n[V2] 最大化后拖标题栏")
        view.showMaximized()
        QTimer.singleShot(800, do_v2)

    def do_v2():
        l, t, r, b = wrect(h["hwnd"])
        sx, sy = (l + r) // 2, t + 26
        log(f"    最大化 rect={wrect(h['hwnd'])}  isMax={view.isMaximized()}")
        pts = [(sx, sy)] + [(sx - 15 * i, sy + 30 * i) for i in range(1, 9)]
        threading.Thread(target=real_drag, args=(pts,), daemon=True).start()
        QTimer.singleShot(3400, after_v2)

    def after_v2():
        was = view.isMaximized()
        ok("V2 最大化后拖标题栏能还原", not was,
           f"isMaximized={was}  rect={wrect(h['hwnd'])}")
        view.showNormal()
        QTimer.singleShot(700, v3)

    # ── V3 拉右边界放大 ────────────────────────────────────────────────
    def v3():
        place(h["hwnd"], 150, 120, 1250, 875)
        QTimer.singleShot(400, do_v3)

    def do_v3():
        h["r"] = size(h["hwnd"])
        l, t, r, b = wrect(h["hwnd"])
        sx, sy = r - 3, t + 300
        log(f"\n[V3] 拉右边界往外  前 {h['r']}  起点({sx},{sy})")
        pts = [(sx, sy)] + [(sx + 25 * i, sy) for i in range(1, 6)]
        threading.Thread(target=real_drag, args=(pts,), daemon=True).start()
        QTimer.singleShot(3000, after_v3)

    def after_v3():
        after = size(h["hwnd"])
        ok("V3 拉右边界放大", after[0] > h["r"][0],
           f"宽 {h['r'][0]} → {after[0]}")

    # ── V4 ★ 拉右边界缩小 ──────────────────────────────────────────────
        h["r2"] = after
        l, t, r, b = wrect(h["hwnd"])
        sx, sy = r - 3, t + 300
        log(f"\n[V4] ★ 拉右边界往里（缩小）  前 {h['r2']}  起点({sx},{sy})")
        pts = [(sx, sy)] + [(sx - 25 * i, sy) for i in range(1, 6)]
        threading.Thread(target=real_drag, args=[pts], daemon=True).start()
        QTimer.singleShot(3000, after_v4)

    def after_v4():
        after = size(h["hwnd"])
        ok("V4 ★ 拉右边界缩小", after[0] < h["r2"][0],
           f"宽 {h['r2'][0]} → {after[0]}")
        QTimer.singleShot(400, v5)

    # ── V5 拉下边界 ────────────────────────────────────────────────────
    def v5():
        h["h"] = size(h["hwnd"])
        l, t, r, b = wrect(h["hwnd"])
        sx, sy = (l + r) // 2, b - 3
        log(f"\n[V5] 拉下边界往下  前 {h['h']}  起点({sx},{sy})")
        pts = [(sx, sy)] + [(sx, sy + 20 * i) for i in range(1, 6)]
        threading.Thread(target=real_drag, args=[pts], daemon=True).start()
        QTimer.singleShot(3000, after_v5)

    def after_v5():
        after = size(h["hwnd"])
        ok("V5 拉下边界放大", after[1] > h["h"][1],
           f"高 {h['h'][1]} → {after[1]}")
        QTimer.singleShot(400, v6)

    # ── V6 右下角 ──────────────────────────────────────────────────────
    def v6():
        #: ⚠ 先把窗口缩回小尺寸 —— V5 可能已经把高度拉到工作区上限
        #: （屏 1080 - 任务栏 = 1020），那时"往下拉高"物理上不可能，
        #: 断言会假失败（实测踩到：前 = 1250x1020 已经顶满）。
        place(h["hwnd"], 150, 100, 1000, 700)
        QTimer.singleShot(500, do_v6)

    def do_v6():
        h["c"] = size(h["hwnd"])
        l, t, r, b = wrect(h["hwnd"])
        log(f"\n[V6] 拉右下角  前 {h['c']}")
        pts = ([(r - 3, b - 3)] +
               [(r - 3 + 15 * i, b - 3 + 15 * i) for i in range(1, 5)])
        threading.Thread(target=real_drag, args=[pts], daemon=True).start()
        QTimer.singleShot(3000, after_v6)

    def after_v6():
        after = size(h["hwnd"])
        ok("V6 拉右下角", after[0] > h["c"][0] and after[1] > h["c"][1],
           f"{h['c'][0]}x{h['c'][1]} → {after[0]}x{after[1]}")
        QTimer.singleShot(400, v7)

    # ── V7 内容区点击 ──────────────────────────────────────────────────
    def v7():
        log("\n[V7] 内容区点击是否仍能到页面")
        shell.debug_js("""
        (function(){ window.__c = 0;
          document.addEventListener('mousedown', function(){ window.__c++; }, true);
          return 1; })()
        """)
        l, t, r, b = wrect(h["hwnd"])
        x, y = (l + r) // 2, t + 420
        threading.Thread(target=real_drag,
                         args=([(x, y), (x, y)],), daemon=True).start()
        QTimer.singleShot(1800, after_v7)

    def after_v7():
        n = shell.debug_js("window.__c")
        ok("V7 内容区点击到达页面", bool(n), f"页面 mousedown = {n}")
        QTimer.singleShot(400, v8)

    # ── V8 最大化时边缘 ────────────────────────────────────────────────
    def v8():
        log("\n[V8] 最大化时边缘命中测试")
        view.showMaximized()
        QTimer.singleShot(800, do_v8)

    def do_v8():
        hwnd = h["hwnd"]
        l, t, r, b = wrect(hwnd)
        vals = []
        for name, x, y in [("右边缘", r - 3, t + 300),
                           ("下边缘", (l + r) // 2, b - 3),
                           ("左上角", l + 3, t + 3),
                           ("右下角", r - 3, b - 3)]:
            vals.append((name, nchittest(hwnd, x, y)))
        good = all(v == 1 for _, v in vals)
        ok("V8 最大化时边缘返回 HTCLIENT", good,
           str([(n, hex(v)) for n, v in vals]))
        view.showNormal()
        QTimer.singleShot(800, v9)

    # ── V9/V10 ★ □ 按钮两次点击 ───────────────────────────────────────
    def v9():
        log("\n[V9/V10] 真鼠标点页面里的 □ 按钮两次")
        place(h["hwnd"], 150, 120, 1250, 875)
        QTimer.singleShot(600, click_max_btn_1)

    def _btn_pos():
        import json
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

    def click_max_btn_1():
        pos = _btn_pos()
        if not pos:
            ok("V9 □ 按钮第一次点击最大化", False, "找不到 #btn-max")
            return app.quit()
        log(f"    □ 物理坐标 = {pos}  当前 isMax={view.isMaximized()}")
        threading.Thread(target=real_drag,
                         args=([pos, pos],), daemon=True).start()
        QTimer.singleShot(2000, after_btn1)

    def after_btn1(self_=None):
        ok("V9 □ 第一次点击 → 最大化", view.isMaximized(),
           f"isMaximized={view.isMaximized()}")
        QTimer.singleShot(600, click_max_btn_2)

    def click_max_btn_2():
        pos = _btn_pos()
        if not pos:
            ok("V10 □ 第二次点击还原", False, "找不到 #btn-max")
            return finish()
        log(f"    再点一次同一个位置 {pos}")
        threading.Thread(target=real_drag,
                         args=([pos, pos],), daemon=True).start()
        QTimer.singleShot(2200, after_btn2)

    def after_btn2():
        ok("V10 ★ □ 第二次点击 → 还原", not view.isMaximized(),
           f"isMaximized={view.isMaximized()}")
        QTimer.singleShot(400, finish)

    def finish():
        log("\n" + "=" * 74)
        passed = sum(1 for _, p, _ in RESULTS if p)
        log(f"结果：{passed}/{len(RESULTS)} 通过")
        for case, p, note in RESULTS:
            log(f"  {'PASS' if p else 'FAIL'}  {case}")
        QTimer.singleShot(250, app.quit)

    view.loadFinished.connect(on_load)
    QTimer.singleShot(150000, app.quit)
    app.exec()
    return 0 if all(p for _, p, _ in RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
