# -*- coding: utf-8 -*-
"""回归测试：**首次启动不应白屏**（lead 实测踩到的竞态）。

## 复现的问题

lead 第一次跑 ``create_shell()``：

    web_shell：加载 http://127.0.0.1:xxxxx/web/index.html?t=...
    web_shell：页面加载失败 http://127.0.0.1:xxxxx/web/index.html?t=...

第二次就正常。典型启动竞态：``media_server.start()`` 里
``serve_forever()`` 在别的线程，Chromium 的请求抢先发出没人应答。

## 这个脚本怎么测

**每个场景都在全新进程里跑**，这样 `media_server` 是真正的冷启动
（模块级单例为空）—— 同进程反复 `stop()`/`start()` 测不出竞态。

场景：
  A. 冷启动 → build() → 断言加载成功
  B. 冷启动 + 故意把 ``wait_until_ready`` 改成恒 False
     → 断言 build() 返回 False（**优雅失败**，不白屏）
  C. 冷启动 → 第一次故意让服务不可用、第二次正常
     → 断言重试后成功

## 跑法

.. code:: powershell

    .venv\\Scripts\\python.exe src\\gui\\web\\dev\\web_shell_coldstart.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", "..", ".."))

PROBE = r'''
import os, sys, json, time
sys.path.insert(0, %r)
os.chdir(%r)
os.environ.setdefault("QT_LOGGING_RULES", "qt.multimedia.*=false")
sys.stderr = open(os.devnull, "w")

SCENARIO = os.environ.get("PROBE_SCENARIO", "A")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
app = QApplication([])

import src.tools
src.tools.discover_tools()

result = {"scenario": SCENARIO}

if SCENARIO == "B":
    #: 让「等服务就绪」永远失败 → build() 应优雅返回 False
    from src.core import media_server
    media_server.wait_until_ready = lambda timeout=3.0: False

if SCENARIO == "C":
    #: 前两次探测失败、第三次成功 —— 验「外层重试」真的起作用
    #:
    #: ⚠ 这里模拟的是**探测函数本身**偶发失败（比如服务线程刚起来又抖了一下），
    #: 不是服务永久挂掉。永久挂掉是场景 B。
    from src.core import media_server
    _real = media_server.wait_until_ready
    _calls = {"n": 0}
    def flaky(timeout=3.0):
        _calls["n"] += 1
        if _calls["n"] <= 2:
            return False
        return _real(timeout)
    media_server.wait_until_ready = flaky

from src.gui.web_shell import create_shell

t0 = time.time()
shell = create_shell()
build_secs = time.time() - t0
result["build_returned_shell"] = shell is not None
result["build_seconds"] = round(build_secs, 3)

if shell is None:
    result["loaded"] = False
    result["ready"] = False
    print("RESULT " + json.dumps(result, ensure_ascii=False), flush=True)
    QTimer.singleShot(200, app.quit)
    app.exec()
    print("EXITED", flush=True)
    sys.exit(0)

result["url"] = shell.view.url().toString()
shell.view.resize(1100, 720)
shell.view.show()

def check():
    result["loaded"] = True
    result["ready"] = bool(shell.is_ready)
    layout = shell.debug_layout() or {}
    result["viewport"] = layout.get("viewport")
    result["tools"] = layout.get("tools")
    result["has_app"] = shell.debug_js("typeof window.App") or "?"
    cards = shell.debug_js("document.querySelectorAll('.tool-card').length")
    result["cards"] = cards
    print("RESULT " + json.dumps(result, ensure_ascii=False), flush=True)
    shell.close()
    QTimer.singleShot(300, app.quit)

shell.view.loadFinished.connect(lambda ok: QTimer.singleShot(3200, check))
QTimer.singleShot(40000, check)
app.exec()
print("EXITED", flush=True)
'''


def run(scenario: str) -> dict:
    env = dict(os.environ)
    env["PROBE_SCENARIO"] = scenario
    env.pop("MYTOOLS_WEB_SHELL", None)
    code = PROBE % (_ROOT, _ROOT)
    try:
        proc = subprocess.run(
            [sys.executable, "-X", "utf8", "-c", code],
            cwd=_ROOT, env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=120)
    except subprocess.TimeoutExpired:
        return {"error": "timeout"}
    for line in (proc.stdout or "").splitlines():
        if line.startswith("RESULT "):
            try:
                return json.loads(line[len("RESULT "):])
            except ValueError:
                pass
    return {"error": "no RESULT", "tail": (proc.stdout or "")[-600:]}


def main() -> int:
    fails: list[str] = []

    # ── A：冷启动应该成功 ─────────────────────────────────────────
    a = run("A")
    ok_a = (a.get("build_returned_shell") is True
            and a.get("ready") is True
            and a.get("tools") == 7
            and str(a.get("cards")) in ("7", "7.0"))
    print(f"[{'PASS' if ok_a else 'FAIL'}] A 冷启动" 
          f"  ready={a.get('ready')} tools={a.get('tools')} "
          f"cards={a.get('cards')} build={a.get('build_seconds')}s")
    if not ok_a:
        fails.append("A")
        print("       detail:", json.dumps(a, ensure_ascii=False)[:400])

    # ── B：服务永远不就绪 → 优雅失败（不白屏、不崩）──────────────
    b = run("B")
    ok_b = b.get("build_returned_shell") is False
    print(f"[{'PASS' if ok_b else 'FAIL'}] B 服务不可用 → 优雅返回 None"
          f"  build_returned_shell={b.get('build_returned_shell')}")
    if not ok_b:
        fails.append("B")
        print("       detail:", json.dumps(b, ensure_ascii=False)[:400])

    # ── C：第一次探测失败，重试成功 ───────────────────────────────
    c = run("C")
    ok_c = (c.get("build_returned_shell") is True
            and c.get("ready") is True)
    print(f"[{'PASS' if ok_c else 'FAIL'}] C 探测抖动后仍成功"
          f"  ready={c.get('ready')} tools={c.get('tools')}")
    if not ok_c:
        fails.append("C")
        print("       detail:", json.dumps(c, ensure_ascii=False)[:400])

    print()
    print("=" * 62)
    print("结果：" + ("全部通过" if not fails else "失败 " + str(fails)))
    print("=" * 62)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
