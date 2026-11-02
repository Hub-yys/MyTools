# -*- coding: utf-8 -*-
"""★ 验证 `runTask` / `runFlow` **真的**接了引擎（不再模拟）。

## 关键：怎么在不启动游戏的情况下验证"真跑"

游戏没开着 → ``FlowRunThread._run_start_step`` 里的
``check_start()`` 会抛 ``TaskStartError``（「客户端没在运行」）。
**这恰好就是"真的走了执行器"的证据** —— 模拟实现永远不会报这句话。

所以判据是：

1. 状态返回 `{ok: true, real: true}`
2. **收到执行器发的日志**（"检查鸣潮客户端是否在运行…"）
3. 最后收到 `taskFinished {ok: false, summary: "…客户端没在运行…"}`
4. （最重要）**summary 里出现只有真执行器才会产生的那句话**

如果还是模拟，第 2、4 条都不会出现。

## 额外检查

- 不支持自动运行的工具 → 明确 `not_runnable`（不假装跑）
- 忙的时候再 run → `busy`
- `stopTask` 走 `request_stop`（`pending: true`）
- 线程能干净收尾（不残留 QThread）

## 跑法

.. code:: powershell

    .venv\\Scripts\\python.exe src\\gui\\web\\dev\\web_shell_real_engine.py
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
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)
os.environ.setdefault("QT_LOGGING_RULES", "qt.multimedia.*=false")

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

FAILS: list[str] = []


def ok(tag: str, cond: bool, note: str = "") -> None:
    print(f"[{'PASS' if cond else 'FAIL'}] {tag}  {note}")
    if not cond:
        FAILS.append(tag)


def main() -> int:
    app = QApplication.instance() or QApplication([])
    import src.tools as tools_pkg

    tools_pkg.discover_tools()
    from src.core.web_bridge import WebBridge

    bridge = WebBridge()

    #: 收集所有推送事件
    events: list[dict] = []
    bridge.event.connect(lambda raw: events.append(json.loads(raw)))

    def wait_until(pred, timeout_ms: int = 12000) -> bool:
        """跑事件循环直到 pred() 为真或超时。"""
        loop = QEventLoop()
        box = {"done": False}

        def tick():
            if pred():
                box["done"] = True
                loop.quit()

        timer = QTimer()
        timer.setInterval(80)
        timer.timeout.connect(tick)
        timer.start()

        stop = QTimer()
        stop.setSingleShot(True)
        stop.timeout.connect(loop.quit)
        stop.start(timeout_ms)
        loop.exec()
        timer.stop()
        return box["done"]

    def names() -> list[str]:
        return [e.get("name") for e in events]

    def drain() -> None:
        events.clear()

    # ══════════════════════════════════════════════════════════════
    # 1) 不支持的工具有没有明确拒绝
    # ══════════════════════════════════════════════════════════════
    r = json.loads(bridge.runTask("gacha"))          # supports_task_run=False
    ok("not_runnable_rejected",
       r.get("ok") is False and r.get("reason") == "not_runnable",
       json.dumps(r, ensure_ascii=False)[:150])

    # ══════════════════════════════════════════════════════════════
    # 2) ★ 支持的工具 → 真引擎链路（前置检查通过才起线程）
    # ══════════════════════════════════════════════════════════════
    #
    #: ⚠ 2026-11-02 加了**同步前置检查**之后，这台机器（游戏没开）
    #: 会直接返回 ``{ok: false, reason: "precheck"}``，**不起线程**。
    #:
    #: 这恰恰证明"链路真的接上了" —— 因为 ``precheck`` 是
    #: ``core.task_start.check_start()`` 产生的，而它只在真实执行路径上被调。
    #: 模拟实现永远不会返回 ``precheck``。
    drain()
    r = json.loads(bridge.runTask("echo_enhance"))
    blocked_by_precheck = (r.get("ok") is False
                           and r.get("reason") == "precheck")

    ok("runTask_reaches_engine",
       blocked_by_precheck or r.get("real") is True,
       json.dumps(r, ensure_ascii=False)[:170])

    if blocked_by_precheck:
        #: 前置检查同步拦下 —— 消息必须给用户看得懂
        msg = str(r.get("message") or "")
        ok("engine_precheck_message",
           "客户端没在运行" in msg,
           f"message = {msg[:100]!r}")
        ok("engine_no_thread_on_precheck",
           bridge._thread is None and not bridge._running,
           f"_thread={bridge._thread!r} _running={bridge._running!r}")
        #: 没开始就别发 taskStarted（不假装）
        ok("engine_no_fake_events",
           "taskStarted" not in names(),
           f"事件 = {names()}")
    else:
        #: 游戏真开着 —— 走完整路径，等执行器结束
        ok("runTask_real_flag", r.get("real") is True,
           f"real={r.get('real')}")
        finished = wait_until(
            lambda: "taskFinished" in names(), timeout_ms=30000)
        ok("engine_finished", finished, f"事件 = {names()}")
        logs = [e["data"].get("text", "") for e in events
                if e.get("name") == "logLine"]
        ok("engine_emitted_logs", len(logs) >= 2, f"共 {len(logs)} 条")
        fin = next((e["data"] for e in events
                    if e.get("name") == "taskFinished"), {})
        ok("engine_finished_ok_false", fin.get("ok") is False,
           f"ok={fin.get('ok')} summary={str(fin.get('summary'))[:80]!r}")

    #: 无论走哪条路，线程/状态都得是干净的
    wait_until(lambda: bridge._running == "", timeout_ms=15000)
    ok("thread_cleaned", bridge._thread is None,
       f"_thread={bridge._thread!r}")
    ok("running_cleared", bridge._running == "",
       f"_running={bridge._running!r}")

    # ══════════════════════════════════════════════════════════════
    # 3) 忙的时候拒绝（只有真的起得来线程才测得到）
    # ══════════════════════════════════════════════════════════════
    drain()
    started = json.loads(bridge.runTask("echo_enhance"))
    if started.get("ok") is True:
        r = json.loads(bridge.runTask("nest_sweep"))
        ok("busy_rejected",
           r.get("ok") is False and r.get("reason") == "busy",
           json.dumps(r, ensure_ascii=False)[:120])
        r = json.loads(bridge.stopTask())
        ok("stop_accepted", r.get("ok") is True,
           json.dumps(r, ensure_ascii=False)[:120])
        wait_until(lambda: bridge._running == "", timeout_ms=30000)
        ok("stop_settled", bridge._running == "",
           f"_running={bridge._running!r}")
    else:
        ok("busy_skipped_precheck",
           started.get("reason") == "precheck",
           f"precheck 拦下，busy 无从测起（reason={started.get('reason')}）")

    # ══════════════════════════════════════════════════════════════
    # 4) runFlow 也走真引擎
    # ══════════════════════════════════════════════════════════════
    flows = json.loads(bridge.getFlowList())
    if flows:
        drain()
        r = json.loads(bridge.runFlow(flows[0]["id"]))
        ok("runFlow_reaches_engine",
           r.get("real") is True or r.get("reason") == "precheck",
           json.dumps(r, ensure_ascii=False)[:160])
        if r.get("real") is True:
            wait_until(lambda: "taskFinished" in names(), timeout_ms=30000)
        wait_until(lambda: bridge._running == "", timeout_ms=15000)
    else:
        ok("runFlow_reaches_engine", False, "没有流程可测")

    print()
    print("=" * 64)
    print("结果：" + ("全部通过" if not FAILS else "失败 " + str(FAILS)))
    print("=" * 64)
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
