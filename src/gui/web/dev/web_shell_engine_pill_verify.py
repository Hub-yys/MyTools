# -*- coding: utf-8 -*-
"""侧栏底部状态药丸 —— ok-ww 引擎状态验证（无头）。

## 为什么需要（2026-11-04 用户圈图）

用户圈住侧栏那颗「● 就绪」，批注：

    如果okww引擎启动成功，原点就变绿色，文字变成引擎就绪，
    如果失败，原点变成红色，文字变成引擎启动失败，
    而且各种任务，工具无法运行

修复前药丸**完全不看引擎** —— 它只反映桥接层自己的 ``_running``
（``taskStarted`` / ``taskFinished`` 两个事件）。引擎挂了照样显示
绿色的「就绪」，用户点了运行才发现跑不起来。

## 这个脚本验什么

``WebBridge.getEngineStatus()`` 后端给的 ``state`` / ``ready``
要能被前端 ``App.applyEngineStatus()`` 正确翻译成药丸的
``data-state``（决定颜色）+ 文字。所以：

1. **后端**：五种宿主状态各调一次 ``getEngineStatus``，
   断言 ``state`` / ``ready`` / ``available`` 对得上；
2. **前端**：把每种状态喂给 ``App.applyEngineStatus``，
   读真实 DOM 的 ``#status-pill[data-state]`` + ``#status-text``，
   断言颜色态和文案对得上；
3. **优先��**：桥接层有任务在跑时，药丸必须是「运行中」，
   不能被引擎状态盖掉。

## ⚠ 用假宿主，不启动真引擎

真 ``boot()`` 会让进程退出码变成 ``0xC0000005``（引擎线程不 join，
见 ``web_shell_p4_batch1.py`` 的注释）。这里只替换
``okww_boot.current_host``，``getEngineStatus`` 的逻辑照常跑。

## 跑法

.. code:: powershell

    .venv\\Scripts\\python.exe src\\gui\\web\\dev\\web_shell_engine_pill_verify.py
"""

from __future__ import annotations

import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

os.environ.setdefault(
    "QT_LOGGING_RULES", "qt.multimedia.*=false;qt.webenginecontext.debug=false"
)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []
DETAIL: dict = {}


def check(case_id: str, ok: bool, note: str = "") -> None:
    RESULTS.append((case_id, bool(ok), note))
    print(f"[{'PASS' if ok else 'FAIL'}] {case_id}  {note}", flush=True)


class FakeHost:
    """假宿主 —— 只提供 ``getEngineStatus`` 读的四个 property。"""

    def __init__(self, state: str, *, running: str = "",
                 pending: str = "", boot_error: str = "") -> None:
        self.state = state
        self.running_task = running
        self.pending_start = pending
        self.boot_error = boot_error


def main() -> int:
    app = QApplication.instance() or QApplication([])

    import src.tools as tools_pkg  # noqa: PLC0415

    tools_pkg.discover_tools()

    from src.core.web_bridge import WebBridge  # noqa: PLC0415
    from src.tools.game.auto_combat import okww_boot  # noqa: PLC0415

    bridge = WebBridge()
    real_current = okww_boot.current_host
    #: 假宿主暂存（``call`` 里换，``finally`` 恢复真实实现）
    holder: dict = {"host": None}

    def call(state: dict) -> dict:
        """装好假宿主，调一次 getEngineStatus。"""
        holder["host"] = FakeHost(**state)
        okww_boot.current_host = lambda: holder["host"]
        try:
            return json.loads(bridge.getEngineStatus())
        finally:
            okww_boot.current_host = real_current

    # ══════════════════════════════════════════════════════════════════
    #  1) 后端：五种状态
    # ══════════════════════════════════════════════════════════════════
    print("\n--- 后端 getEngineStatus ---\n", flush=True)

    cases = [
        # (说明, 假宿主参数, 期望 state, 期望 ready)
        ("就绪", dict(state="ready"), "ready", True),
        ("运行中", dict(state="running", running="声骸自动强化"),
         "running", True),
        ("启动中", dict(state="booting", pending="声骸自动强化"),
         "booting", False),
        ("启动失败", dict(state="error", boot_error="引擎 20 秒没起来"),
         "error", False),
        ("空转", dict(state="idle"), "idle", False),
    ]
    for label, kwargs, want_state, want_ready in cases:
        got = call(kwargs)
        check(
            f"B-{want_state}",
            got.get("state") == want_state and got.get("ready") is want_ready,
            f"{label}：state={got.get('state')} ready={got.get('ready')} "
            f"runningTask={got.get('runningTask')!r} "
            f"bootError={got.get('bootError')!r}",
        )

    #: 宿主从没建过（current_host() → None）→ idle，不能崩
    okww_boot.current_host = lambda: None
    try:
        got = json.loads(bridge.getEngineStatus())
    finally:
        okww_boot.current_host = real_current
    check("B-no-host", got.get("state") == "idle"
          and got.get("ready") is False and got.get("available") is True,
          f"宿主没建过：{got}")

    #: ⚠ 别用真的 current_host() —— 这个进程里引擎没 boot
    check("B-no-tasks-field", "tasks" not in got,
          "轻量版不带 tasks 表（1.5 秒轮询扛不住 importlib）")

    # ══════════════════════════════════════════════════════════════════
    #  2) 前端：喂状态看药丸
    # ══════════════════════════════════════════════════════════════════
    from src.gui.web_shell import WebShell, web_base_url  # noqa: PLC0415

    base = web_base_url()
    check("P0", bool(base), "HTTP 服务起得来")
    if not base:
        return finish()

    shell = WebShell(base_url=base)
    if not shell.build():
        check("P0b", False, "WebShell.build() 失败")
        return finish()

    view = shell.view
    view.resize(1280, 800)
    view.show()

    js = shell.debug_js
    state = {"stage": "loading"}

    def bundle(code: str, label: str):
        #: ⚠⚠ debug_js 返回 JS **对象**时拿到的是空串，
        #: 必须自己 JSON.stringify 包一层（2026-11-04 踩过半小时）
        raw = js("JSON.stringify(" + code + ")")
        if raw is None or raw == "":
            DETAIL[label] = None
            return None
        try:
            value = json.loads(raw)
        except (TypeError, ValueError):
            DETAIL[label] = raw
            return value if isinstance(value, str) else None  # noqa: PLW2901
        DETAIL[label] = value
        return value

    def pill_state(label: str):
        """喂一条状态给 applyEngineStatus，读回真实 DOM。"""
        return bundle(
            "(function(){"
            "App.applyEngineStatus(" + json.dumps(DETAIL["feed"]) + ");"
            "var p=document.getElementById('status-pill');"
            "var t=document.getElementById('status-text');"
            "var d=p?p.querySelector('.status-dot'):null;"
            #: ⚠⚠ ``.status-dot`` 带 ``transition: background`` —— 读完立刻
            #: ``getComputedStyle`` 拿到的还是**上一帧**的颜色（过渡还没开始），
            #: 于是「就绪」读出来是灰的、「失败」读出来是上一次的绿。
            #: 先把过渡掐掉再读，ComputedStyle 就直接是目标值。
            "if(d){d.style.setProperty('transition','none','important');"
            "void d.offsetWidth;}"
            "return {state:p?p.dataset.state:'',"
            " text:t?t.textContent:'',"
            " dot:d?getComputedStyle(d).backgroundColor:''};"
            "})()",
            label,
        )

    def on_load(_ok: bool) -> None:
        QTimer.singleShot(2600, stage_backend_ready)

    def stage_backend_ready() -> None:
        """等前端 boot 完（App 存在 + Bridge 连上）。"""
        state["stage"] = "backend-ready"
        got = bundle(
            "(function(){return {"
            "hasApp: typeof App !== 'undefined',"
            "hasEngine: !!(window.App && 'engine' in App),"
            "hasApply: !!(window.App && typeof App.applyEngineStatus==='function'),"
            "hasPoll: !!(window.App && typeof App.pollEngineStatus==='function'),"
            #: 轮询真的开起来了吗（boot 末尾调 startEnginePoll）
            "timerOn: !!(window.App && window.App._engineTimer)"
            "};})()",
            "front_api",
        )
        check("F-api", bool(got) and got.get("hasApp")
              and got.get("hasApply") and got.get("hasPoll")
              and got.get("timerOn"),
              f"前端 API：{got}")
        QTimer.singleShot(200, stage_states)

    def stage_states() -> None:
        state["stage"] = "states"
        #: 桥接层「没有任务在跑」——否则 applyEngineStatus 会被
        #: 「运行中」优先级短路，测不到引擎那几条分支
        js("window.App.status.running = '';")

        feed_cases = [
            # (说明, 喂进去的状态, 期望 data-state, 期望文字片段)
            ("就绪", dict(state="ready", ready=True, available=True),
             "ready", "引擎就绪"),
            ("运行中", dict(state="running", ready=True, available=True,
                          runningTask="声骸自动强化"),
             "running", "引擎运行中"),
            ("启动中", dict(state="booting", ready=False, available=True,
                          pendingStart="声骸自动强化"),
             "idle", "引擎启动中"),
            ("启动失败", dict(state="error", ready=False, available=True,
                           bootError="引擎 20 秒没起来"),
             "error", "引擎启动失败"),
            ("模块不可用", dict(state="error", ready=False, available=False),
             "error", "引擎不可用"),
            ("空转", dict(state="idle", ready=False, available=True),
             "idle", "就绪"),
        ]
        for label, feed, want_state, want_text in feed_cases:
            DETAIL["feed"] = feed
            got = pill_state("pill_" + want_state + "_" + str(len(RESULTS)))
            good = bool(got) and got.get("state") == want_state \
                and want_text in str(got.get("text") or "")
            check(
                f"F-{want_state}-{len(RESULTS)}",
                good,
                f"{label}：data-state={got.get('state') if got else None} "
                f"text={got.get('text') if got else None!r} "
                f"dot={got.get('dot') if got else None}",
            )

        #: 绿点 / 红点真的上色了吗（不是只改了 dataset）
        DETAIL["feed"] = dict(state="ready", ready=True, available=True)
        green = pill_state("pill_green")
        DETAIL["feed"] = dict(state="error", ready=False, available=True,
                              bootError="x")
        red = pill_state("pill_red")
        check("F-dot-green",
              bool(green) and "74, 222, 128" in str(green.get("dot")),
              f"就绪点色 = {green.get('dot') if green else None}（要 #4ade80）")
        check("F-dot-red",
              bool(red) and "239, 68, 68" in str(red.get("dot")),
              f"失败点色 = {red.get('dot') if red else None}（要 #ef4444）")

        QTimer.singleShot(150, stage_priority)

    def stage_priority() -> None:
        """桥接层有任务在跑时，「运行中」优先于引擎状态。"""
        state["stage"] = "priority"
        js("window.App.status.running = 'echo_enhance';")
        DETAIL["feed"] = dict(state="ready", ready=True, available=True)
        got = pill_state("pill_priority")
        check("F-priority",
              bool(got) and got.get("state") == "running"
              and "运行中" in str(got.get("text")),
              f"桥接层有任务时压过引擎：{got}")

        #: 清掉，别影响后面的截图
        js("window.App.status.running = '';")
        QTimer.singleShot(600, stage_shot)

    def stage_shot() -> None:
        state["stage"] = "shot"
        #: ⚠ 必须先把轮询停掉 —— 否则 1.5 秒后 ``pollEngineStatus``
        #: 会拿这个测试进程里的**真实**状态（引擎没 boot → idle）
        #: 把药丸改回灰色「就绪」，截图就拍不到了。
        js(
            "clearInterval(window.App._engineTimer);"
            "window.App._engineTimer = null;"
        )
        DETAIL["feed"] = dict(state="ready", ready=True, available=True)
        js(
            "App.applyEngineStatus(" + json.dumps(DETAIL["feed"]) + ");"
        )
        QTimer.singleShot(700, take_shot)

    def take_shot() -> None:
        #: ⚠ 截图要等重绘 —— debug_js 同步返回时 DOM 改了但还没画
        try:
            shot = os.path.join(_ROOT, "data", "_shots")
            os.makedirs(shot, exist_ok=True)
            shell.debug_screenshot(
                os.path.join(shot, "99-engine-pill-ready.png"))
            print(f"  [shot] data/_shots/99-engine-pill-ready.png", flush=True)
        except Exception:  # noqa: BLE001 - 截图失败不影响结论
            pass
        QTimer.singleShot(150, lambda: finish_and_quit(shell))

    def finish_and_quit(shell_) -> None:
        state["stage"] = "done"
        try:
            shell_.view.page().deleteLater()
        except Exception:  # noqa: BLE001
            pass
        app.exit(finish())

    view.page().loadFinished.connect(on_load)

    def watchdog() -> None:
        if state.get("stage") != "done":
            check("TIMEOUT", False,
                  f"超时，卡在阶段 {state.get('stage')} —— 已收 {len(RESULTS)} 项")

    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(watchdog)
    timer.start(60000)

    return app.exec()


def finish() -> int:
    print("\n" + "=" * 62, flush=True)
    total = len(RESULTS)
    passed = sum(1 for _cid, ok_, _note in RESULTS if ok_)
    for cid, ok_, note in RESULTS:
        if not ok_:
            print(f"  FAIL {cid}: {note}", flush=True)
    print(f"结果：{passed}/{total} 通过", flush=True)
    if passed == total and total:
        print("✓ 引擎状态药丸全部通过", flush=True)
    else:
        print("✗ 有未通过项，见上面的 FAIL 行", flush=True)
    print("=" * 62, flush=True)
    try:
        out = os.path.join(_ROOT, "data", "_engine_pill_verify.json")
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(
                {"results": [{"id": c, "ok": o, "note": n} for c, o, n in RESULTS],
                 "detail": DETAIL},
                fh, ensure_ascii=False, indent=2,
            )
    except Exception:  # noqa: BLE001
        pass
    return 0 if passed == total and total else 1


if __name__ == "__main__":
    sys.exit(main())
