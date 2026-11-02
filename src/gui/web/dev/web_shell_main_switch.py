# -*- coding: utf-8 -*-
"""验证 main.py 的**开关两条路**都能起来。

## 测什么

1. 默认（无环境变量）→ 走 ``WebShell`` ★ 2026-11-02 翻转
2. ``MYTOOLS_WEB_SHELL=0`` → 走旧 ``MainWindow``（回退路径）
3. ``MYTOOLS_WEB_SHELL=1`` 但把 ``src.gui.web_shell.create_shell`` 弄坏
   → **必须退回旧界面**，不能白屏/崩溃

## 为什么不在同一进程里测三个

``main()`` 会建 ``QApplication`` 并进 ``app.exec()``，跑完就退出了。
所以每个场景**单独起一个子进程**，各自跑一段带超时的 ``exec``。

⚠ 不能真的调 ``main.main()`` —— 它有管理员权限闸门、
会自启 ok-ww 引擎、还有看门狗。所以这里**复制**它那段的逻辑，
只测「开关 → 建哪种窗口」这一段。

## 跑法

.. code:: powershell

    .venv\\Scripts\\python.exe src\\gui\\web\\dev\\web_shell_main_switch.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", "..", ".."))

#: 子进程里跑的探针 —— 只测「该建哪个窗口」
PROBE = r'''
import os, sys, json
sys.path.insert(0, %r)
os.chdir(%r)
os.environ.setdefault("QT_LOGGING_RULES", "qt.multimedia.*=false")
sys.stderr = open(os.devnull, "w")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
app = QApplication([])

import src.tools
src.tools.discover_tools()

MODE = os.environ.get("PROBE_MODE", "auto")
use_web = False
err = ""
try:
    if MODE == "broken":
        #: 模拟 QtWebEngine 缺失 / 前端资源丢失
        import src.gui.web_shell as WS
        WS.create_shell = lambda **kw: None      # ← 起不来
        use_web = True
    else:
        from src.gui.web_shell import is_enabled
        use_web = is_enabled()
except Exception as exc:
    err = type(exc).__name__ + ": " + str(exc)

window = None
kind = "none"
if use_web:
    try:
        from src.gui.web_shell import create_shell
        window = create_shell()
    except Exception as exc:
        err = err or (type(exc).__name__ + ": " + str(exc))
        window = None
    if window is not None:
        kind = "webshell"
        window.show()
    else:
        #: 外壳起不来 → 走下面的旧界面分支。
        #: ⚠ 最终 kind 会是 "mainwindow"（因为真的建了 MainWindow）——
        #:   这正是 main.py 里「兜底」的语义，不是 bug。
        kind = "mainwindow"

if window is None:
    from src.gui.main_window import MainWindow
    w = MainWindow()
    w._skip_auto_update = True
    #: ⚠ 探测脚本必须置 _force_quit，否则 app.quit() 会走
    #: MainWindow.closeEvent 弹「确定退出？」模态框 —— 没人点，
    #: 进程就**永久挂住**（我第一版就是这么超时的）。
    w._force_quit = True
    kind = "mainwindow"
    window = w
    w.show()

print("RESULT " + json.dumps({
    "mode": MODE,
    "use_web_shell": use_web,
    "kind": kind,
    "error": err,
    "title": window.windowTitle() if hasattr(window, "windowTitle") else "",
}, ensure_ascii=False), flush=True)

#: 建完就退，不等用户操作
def _bye():
    try:
        if kind == "mainwindow":
            window._force_quit = True
        window.close()
    except Exception:
        pass
    app.quit()

QTimer.singleShot(2500, _bye)
QTimer.singleShot(9000, app.quit)     #: 双保险：关窗口再卡住也强退
app.exec()
print("EXITED", flush=True)
'''

CASES = [
    #: (名称, 环境变量, 期望的窗口类型)
    #: ★ 2026-11-02 默认值翻转：用户要求「干脆把新界面设为默认」。
    #: 原来是 "mainwindow"，现在是 "webshell"。
    ("默认（无开关）", {}, "webshell"),
    ("MYTOOLS_WEB_SHELL=1", {"MYTOOLS_WEB_SHELL": "1"}, "webshell"),
    ("MYTOOLS_WEB_SHELL=0", {"MYTOOLS_WEB_SHELL": "0"}, "mainwindow"),
    #: 外壳起不来时要**退回旧界面**（kind 仍是 mainwindow，
    #: 但 use_web_shell=True 证明开关是开的、回退发生了）
    ("开关开但外壳起不来", {"MYTOOLS_WEB_SHELL": "1", "__BROKEN__": "1"},
     "mainwindow"),
]


def run_case(name: str, env_extra: dict, expect: str) -> tuple[bool, str]:
    env = dict(os.environ)
    env.pop("MYTOOLS_WEB_SHELL", None)
    mode = "auto"
    if env_extra.pop("__BROKEN__", None):
        mode = "broken"
    env.update(env_extra)
    env["PROBE_MODE"] = mode

    code = PROBE % (_ROOT, _ROOT)
    try:
        proc = subprocess.run(
            [sys.executable, "-X", "utf8", "-c", code],
            cwd=_ROOT, env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=90,
        )
    except subprocess.TimeoutExpired:
        return False, "超时（90s）"

    out = (proc.stdout or "") + "\n--stderr--\n" + (proc.stderr or "")[-800:]
    result = None
    for line in (proc.stdout or "").splitlines():
        if line.startswith("RESULT "):
            try:
                result = json.loads(line[len("RESULT "):])
            except ValueError:
                pass
    if result is None:
        return False, f"没有 RESULT 行\n{out[-1500:]}"

    got = result.get("kind")
    ok = (got == expect)
    note = (f"kind={got}（期望 {expect}）"
            f" use_web={result.get('use_web_shell')}"
            f" title={result.get('title')!r}")
    if result.get("error"):
        note += f" error={result['error']}"
    return ok, note


def main() -> int:
    print(f"root = {_ROOT}\n")
    fails = 0
    for name, env_extra, expect in CASES:
        ok, note = run_case(name, dict(env_extra), expect)
        print(f"[{'PASS' if ok else 'FAIL'}] {name}")
        print(f"        {note}")
        if not ok:
            fails += 1

    print("\n" + "=" * 60)
    print(f"结果：{len(CASES) - fails}/{len(CASES)} 通过")
    print("=" * 60)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
