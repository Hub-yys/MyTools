# -*- coding: utf-8 -*-
"""验收 page-converter 要的写接口 + runTask/runFlow 语义拆分。"""

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

app = QApplication.instance() or QApplication([])
import src.tools as tools_pkg  # noqa: E402

tools_pkg.discover_tools()

from src.core.web_bridge import WebBridge  # noqa: E402

FAILS: list[str] = []


def ok(tag: str, cond: bool, note: str = "") -> None:
    print(f"[{'PASS' if cond else 'FAIL'}] {tag}  {note}")
    if not cond:
        FAILS.append(tag)


def pump(ms: int) -> None:
    """跑事件循环 ``ms`` 毫秒（让工作线程的信号能排进来）。"""
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def wait_idle(bridge: WebBridge, timeout_s: float = 10.0) -> bool:
    """★ 等执行器**真的**结束（不再有任务在跑）。

    ## 为什么必须有这个（2026-11-02）

    ``runTask`` 接真引擎之后不再是同步的 —— 它会起一个
    ``FlowRunThread``。第一版测试没等它就调下一个方法，
    于是后面全部返回 ``busy``，6 项假失败。

    实测：游戏没开时执行器 **0.07 秒**就被 ``check_start`` 拒掉，
    所以这里 10 秒上限非常宽松（真挂住会明确 FAIL）。
    """
    deadline = time.perf_counter() + timeout_s
    while time.perf_counter() < deadline:
        if not bridge._running:
            return True
        pump(40)
    return False


def stop_and_settle(bridge: WebBridge) -> bool:
    """停止当前任务并等它真的停下。"""
    if not bridge._running:
        return True
    bridge.stopTask()
    return wait_idle(bridge, 10.0)


def main() -> int:
    b = WebBridge()

    # ── runTask 只认工具 key ──────────────────────────────────────
    #
    #: ⚠ 这台机器**游戏没开着** → ``_precheck`` 会同步返回
    #: ``{ok: false, reason: "precheck"}``，不会起线程。
    #: 这正是想要的行为（见 _precheck 的说明），测试要按它设计。
    r = json.loads(b.runTask("echo_enhance"))
    precheck_blocked = (r.get("ok") is False
                        and r.get("reason") == "precheck")
    ok("runTask_precheck",
       precheck_blocked or (r.get("ok") is True and r.get("real") is True),
       json.dumps(r, ensure_ascii=False)[:170])
    if precheck_blocked:
        ok("precheck_message_is_readable",
           "客户端没在运行" in str(r.get("message", "")),
           f"message = {str(r.get('message'))[:90]!r}")
        ok("precheck_no_thread_started",
           b._thread is None and not b._running,
           f"_thread={b._thread!r} _running={b._running!r}")
    #: 保险：如果真跑起来了（游戏开着），等它结束
    wait_idle(b)

    #: 拿流程 id 去 runTask → 必须明确报 unknown_tool，**不能**静默成功
    flows = json.loads(b.getFlowList())
    if flows:
        fid = flows[0]["id"]
        r = json.loads(b.runTask(fid))
        ok("runTask_flowid_rejected",
           r.get("ok") is False and r.get("reason") == "unknown_tool",
           f"key={fid} → {json.dumps(r, ensure_ascii=False)[:130]}")
        ok("runTask_flowid_hint",
           "runFlow" in str(r.get("hint", "")),
           f"hint={r.get('hint')!r}")

    # ── 不存在的工具 ─────────────────────────────────────────────
    r = json.loads(b.runTask("no_such_tool"))
    ok("runTask_unknown", r.get("ok") is False,
       f"reason={r.get('reason')}")

    # ── 不支持自动运行的工具 → 明确拒绝，不假装跑 ─────────────────
    r = json.loads(b.runTask("gacha"))
    ok("runTask_not_runnable",
       r.get("ok") is False and r.get("reason") == "not_runnable",
       json.dumps(r, ensure_ascii=False)[:130])

    # ── runFlow ──────────────────────────────────────────────────
    if flows:
        fid = flows[0]["id"]
        r = json.loads(b.runFlow(fid))
        ok("runFlow_handled",
           r.get("ok") is True
           or r.get("reason") in ("invalid", "precheck", "busy"),
           f"ok={r.get('ok')} reason={r.get('reason')} "
           f"name={r.get('name')} errors={r.get('errors')}")
        wait_idle(b)

    r = json.loads(b.runFlow("deadbeef0000"))
    ok("runFlow_missing", r.get("ok") is False and r.get("reason") == "not_found",
       json.dumps(r, ensure_ascii=False))

    # ── busy 互斥 ────────────────────────────────────────────────
    #
    #: 游戏没开时 precheck 会拦下，起不了线程 —— 那种情况下
    #: 没法测 busy。所以先看 runTask 到底能不能真的启动。
    started = json.loads(b.runTask("echo_enhance"))
    if started.get("ok") is True:
        r = json.loads(b.runTask("nest_sweep"))
        ok("runTask_busy", r.get("ok") is False and r.get("reason") == "busy",
           json.dumps(r, ensure_ascii=False))
        stop_and_settle(b)
    else:
        #: 起不了线程（precheck 拦下）→ busy 无从谈起，跳过而非假通过
        ok("runTask_busy_skipped",
           started.get("reason") == "precheck",
           f"precheck 拦下，跳过 busy 测试（reason={started.get('reason')}）")

    r = json.loads(b.stopTask())
    ok("stopTask_idle", r.get("ok") is False and r.get("reason") == "idle",
       json.dumps(r, ensure_ascii=False))

    # ── setSkin ──────────────────────────────────────────────────
    skins = json.loads(b.getSkinList())
    sid = skins[0]["id"] if skins else "glass"
    r = json.loads(b.setSkin(sid))
    ok("setSkin_ok", r.get("ok") is True,
       f"id={sid} skin.primary={((r.get('skin') or {}).get('primary'))}")
    ok("setSkin_returns_skin",
       isinstance(r.get("skin"), dict) and bool(r["skin"].get("primary")),
       f"keys={sorted((r.get('skin') or {}).keys())}")

    r = json.loads(b.setSkin("no_such_skin"))
    ok("setSkin_missing", r.get("ok") is False and r.get("reason") == "not_found",
       json.dumps(r, ensure_ascii=False))
    r = json.loads(b.setSkin(""))
    ok("setSkin_empty", r.get("ok") is False, f"reason={r.get('reason')}")

    # ── 事件里带 kind + 用 JS 传进来的 key ───────────────────────
    seen: list[dict] = []
    b.event.connect(lambda raw: seen.append(json.loads(raw)))
    started_r = json.loads(b.runTask("echo_enhance"))
    wait_idle(b)
    started = [e for e in seen if e.get("name") == "taskStarted"]
    if started_r.get("ok") is True:
        ok("event_kind_present",
           bool(started) and started[0]["data"].get("kind") == "tool",
           f"taskStarted data={started[0]['data'] if started else None}")
        #: ★ taskStarted 的 key 必须是 echo_enhance（不是中文显示名）
        ok("event_key_is_tool_key",
           bool(started) and started[0]["data"].get("key") == "echo_enhance",
           f"key={started[0]['data'].get('key') if started else None!r}")
    else:
        #: precheck 拦下 → 不该发 taskStarted（没开始就别假装开始）
        ok("event_no_fake_start",
           not started and started_r.get("reason") == "precheck",
           f"precheck 拦下且没发 taskStarted（{len(started)} 个）")

    # ── currentPage 是 JSON（契约一致性）──────────────────────────
    r = json.loads(b.currentPage())
    ok("currentPage_is_json", isinstance(r, dict) and "page" in r,
       json.dumps(r, ensure_ascii=False))

    print()
    print("=" * 62)
    print("结果：" + ("全部通过" if not FAILS else "失败 " + str(FAILS)))
    print("=" * 62)
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())

