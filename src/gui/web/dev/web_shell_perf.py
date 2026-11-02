# -*- coding: utf-8 -*-
"""性能测量：**真实的事件往返吞吐**（给 lead 的问题一个可信数字）。

## 第一版为什么是错的

我用 ``QTimer(0)`` 数空转 —— 得到 172622 次/秒。那个数字毫无意义：
0ms 定时器是「有空就一直转」，测的是**事件循环空转速度**，
和「推一条消息要多久」没关系。

lead 问的「旧界面 ~300 次/秒」指的是**任务进度上报频率**。
所以这里测真正重要的三件事：

1. **推送吞吐** —— Python ``push_log`` → JS 收到并处理，端到端每秒多少条
2. **DOM 渲染** —— 日志行 DOM 增长（有 500 行上限）
3. **往返延迟** —— Python→JS、JS→Python 各自多久

## 关键：必须测「页面侧收齐了多少」

只数「Python emit 了多少次」是错的 —— 那是往队列塞消息的速度，
页面可能还在慢慢消化。所以页面里装计数器 ``window.__PERF__``，
推完之后读**页面实际处理完的条数**。

## 跑法

.. code:: powershell

    .venv\\Scripts\\python.exe src\\gui\\web\\dev\\web_shell_perf.py
"""

from __future__ import annotations

import json
import os
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
os.chdir(_ROOT)
os.environ.setdefault("QT_LOGGING_RULES", "qt.multimedia.*=false")

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

OUT: dict = {}


class Bench:
    """把整条测量流程封装起来 —— 避免模块级函数互相覆盖（第一版踩过）。"""

    def __init__(self, app, shell):
        self.app = app
        self.shell = shell
        self.state: dict = {}

    # ---------------------------------------------------------------- 调度
    def start(self) -> None:
        self.shell.view.loadFinished.connect(
            lambda ok: self.later(3200, self.step_setup))

    def later(self, ms: int, fn) -> None:
        QTimer.singleShot(ms, fn)

    # ---------------------------------------------------------------- 步骤
    def step_setup(self) -> None:
        #: 进任务页（日志区在那里）
        self.shell.request_page("tasks")
        self.later(900, self.step_install)

    def step_install(self) -> None:
        #: 装计数器 + 通配订阅
        self.shell.debug_js(
            "window.__PERF__={events:0,logs:0,t0:0,t1:0};"
            "Bridge.subscribe(function(n,d){"
            "  window.__PERF__.events++;"
            "  if(n==='logLine') window.__PERF__.logs++;"
            "});'ok'")
        self.later(300, lambda: self.step_flood(1000))

    def step_flood(self, n: int) -> None:
        self.shell.debug_js("window.__PERF__.t0=performance.now();'ok'")
        t0 = time.perf_counter()
        for i in range(n):
            self.shell.push_log(f"perf line {i}", "info")
        emit_secs = time.perf_counter() - t0

        self.state["emit"] = emit_secs
        self.state["n"] = n
        #: 给页面足够时间消化。
        #:
        #: 实测：1000 条约 1s，10000 条要 **约 6s**（每条约 0.6ms）。
        #: 余量按 1.2ms/条 给，别让 debug_js 的超时假象污染结论。
        wait = max(900, int(n * 1.2))
        self.later(wait, lambda: self.step_measure(n))

    def step_measure(self, n: int) -> None:
        raw = self.shell.debug_js(
            "window.__PERF__.t1=performance.now();"
            "JSON.stringify({events:window.__PERF__.events,"
            "logs:window.__PERF__.logs,"
            "span_ms:window.__PERF__.t1-window.__PERF__.t0,"
            "dom_lines:document.querySelectorAll('.log-line').length})")
        try:
            data = json.loads(raw or "{}")
        except ValueError:
            data = {}

        emit_secs = self.state.get("emit") or 1e-9
        if data is None:
            #: ⚠ debug_js 超时了 —— 说明这批太大，页面还在消化。
            #: 不能当"丢消息"报，要明确标成"未测完"。
            block = {
                "pushed": n,
                "page_received": None,
                "emit_seconds": round(emit_secs, 4),
                "emit_per_second": round(n / emit_secs, 1),
                "note": "读取超时：页面仍在消化这批事件（不是丢消息）",
            }
            OUT[f"flood_{n}"] = block
            print(f"FLOOD_{n} " + json.dumps(block, ensure_ascii=False))
        else:
            span_ms = float(data.get("span_ms") or 0)
            recv = int(data.get("events") or 0)
            e2e = span_ms / 1000.0 if span_ms > 0 else None

            block = {
                "pushed": n,
                "page_received": recv,
                "emit_seconds": round(emit_secs, 4),
                "emit_per_second": round(n / emit_secs, 1),
                "page_span_ms": round(span_ms, 1),
                "end_to_end_per_second": round(recv / e2e, 1) if e2e else None,
                "dom_log_lines_capped": data.get("dom_lines"),
            }
            OUT[f"flood_{n}"] = block
            print(f"FLOOD_{n} " + json.dumps(block, ensure_ascii=False))

        #: 清计数器
        self.shell.debug_js(
            "window.__PERF__&&(window.__PERF__.events=0,"
            "window.__PERF__.logs=0);'ok'")

        if n == 1000:
            self.later(300, lambda: self.step_flood(10000))
        else:
            self.later(300, self.step_roundtrip)

    def step_roundtrip(self) -> None:
        # ── Python → JS ──
        n = 200
        t0 = time.perf_counter()
        for _ in range(n):
            self.shell.debug_js("1")
        per = (time.perf_counter() - t0) / n
        OUT["python_to_js"] = {
            "samples": n,
            "avg_ms": round(per * 1000, 3),
            "per_second": round(1 / per, 1) if per else None,
        }
        print("PY2JS " + json.dumps(OUT["python_to_js"], ensure_ascii=False))

        # ── JS → Python（页面里循环 100 次 ping）──
        self.shell.debug_js(
            "window.__RT__={start:performance.now(),done:0,total:100};"
            "(function L(){"
            "  if(window.__RT__.done>=window.__RT__.total){"
            "    window.__RT__.end=performance.now();return;}"
            "  Bridge.call('ping').then(function(){"
            "    window.__RT__.done++;L();});"
            "})();'started'")
        self.later(5000, self.step_read_rt)

    def step_read_rt(self) -> None:
        raw = self.shell.debug_js(
            "JSON.stringify({done:window.__RT__.done,"
            "span:(window.__RT__.end||performance.now())-window.__RT__.start})")
        try:
            data = json.loads(raw or "{}")
        except ValueError:
            data = {}
        done = int(data.get("done") or 0)
        span = float(data.get("span") or 0)
        OUT["js_to_python"] = {
            "samples": done,
            "total_ms": round(span, 1),
            "avg_ms": round(span / done, 3) if done else None,
            "per_second": round(done / (span / 1000), 1) if span > 0 else None,
        }
        print("JS2PY " + json.dumps(OUT["js_to_python"], ensure_ascii=False))
        self.later(300, self.step_done)

    def step_done(self) -> None:
        layout = self.shell.debug_layout() or {}
        vp = layout.get("viewport") or {}
        wl = layout.get("wallpaperLayer") or {}
        OUT["tiling_after_all"] = {
            "viewport": vp, "wallpaper": wl,
            "ok": wl.get("w") == vp.get("w") and wl.get("h") == vp.get("h"),
        }
        OUT["title"] = self.shell.windowTitle()
        OUT["objectName"] = self.shell.objectName()

        #: hover 规则（lead 问的第二件事）
        hover = self.shell.debug_js(r"""
        (function () {
          var out = {found:false, dimsOnHover:false, liftsOnHover:false};
          for (var sheet of document.styleSheets) {
            var rules; try { rules = sheet.cssRules; } catch (e) { continue; }
            for (var rule of rules) {
              if (rule.selectorText === '.card-glass:hover') {
                out.found = true;
                out.dimsOnHover = !!rule.style.backgroundImage;
                out.liftsOnHover = !!rule.style.transform;
                out.shadow = (rule.style.boxShadow || '').length > 0;
              }
            }
          }
          return JSON.stringify(out);
        })()
        """)
        try:
            OUT["hover"] = json.loads(hover or "{}")
        except ValueError:
            OUT["hover"] = {}
        print("HOVER " + json.dumps(OUT["hover"], ensure_ascii=False))
        print("TILING_AFTER_ALL " + json.dumps(OUT["tiling_after_all"],
                                               ensure_ascii=False))

        path = os.path.join(_ROOT, "data", "_web_shell_perf.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(OUT, fh, ensure_ascii=False, indent=2)
        print("SAVED", path)

        self.shell.close()
        self.later(300, self.app.quit)


def main() -> int:
    app = QApplication.instance() or QApplication([])
    import src.tools as tools_pkg  # noqa: PLC0415

    tools_pkg.discover_tools()
    from src.gui.web_shell import WebShell, web_base_url  # noqa: PLC0415

    shell = WebShell(base_url=web_base_url())
    if not shell.build():
        print("BUILD_FAIL")
        return 1
    shell.view.resize(1200, 760)
    shell.view.show()

    Bench(app, shell).start()
    QTimer.singleShot(90000, app.quit)
    app.exec()
    print("DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
