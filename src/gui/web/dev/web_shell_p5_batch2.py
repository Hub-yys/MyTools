# -*- coding: utf-8 -*-
"""验收 P5 第二批：`getEchoEnhanceHistory` / `okwwResumeTask` / `okwwSkipEcho`。

## 为什么需要（用户 P5 反馈）

旧界面「声骸自动强化」页有 **5 个按钮**：
**运行 / 继续 / 停止 / 跳过 / 重置**

新界面只有「运行 / 停止」—— 缺「继续」和「跳过」，而且没有「历史记录」卡。

用户要求的「请不要擅自修改原先的布局内容」= **这些都得有**。

## 三条的语义（照抄旧界面）

**`getEchoEnhanceHistory`** —— 旧界面 ``_build_history_card``（tool.py L577）：
每次「运行 → 停止」记一条，**最多展示最近 10 轮**。
数据在 ``<用户数据>/echo_enhance_history.json``，由
:class:`src.core.tool_history.ToolHistoryStore` 读写。

**`okwwResumeTask`** —— 旧界面 ``_on_resume``：``task.unpause()``。
旧代码注释原话：「少了它，'可续跑'就只是个说法（只能停止再重跑，前面强化的白费）」

**`okwwSkipEcho`** —— 旧界面 ``OkwwHost.request_skip_current()``。
用户 2026-10-30：「跳过相当于他已经强化好了，需要跳过同类型同名声号」

## ⚠ 本测试用 mock，不启动真引擎

真 `boot()` ok-ww 引擎会让进程退出码变成 `0xC0000005`
（引擎线程不 join，见 web_shell_p4_batch1 的注释）。
所以 ``okwwResumeTask`` / ``okwwSkipEcho`` 都用**假宿主**验桥接层逻辑。
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


class _FakeTask:
    """假的任务实例 —— 只提供 ``unpause()`` 和 ``paused``。"""

    def __init__(self, paused: bool = True) -> None:
        self.paused = paused
        self.unpaused = 0

    def unpause(self) -> None:
        self.paused = False
        self.unpaused += 1


class _FakeHost:
    """假的 ok-ww 宿主。"""

    def __init__(self, *, task=None, run_key="声骸自动强化",
                 skip_result=True) -> None:
        self._task = task
        self.running_task = run_key
        self.pending_start = None
        self.boot_error = None
        self.state = "running"
        self.skip_calls = 0
        self._skip_result = skip_result
        self.tasks_seen: list[str] = []

    def find_task(self, key):
        self.tasks_seen.append(key)
        return self._task

    def request_skip_current(self) -> bool:
        self.skip_calls += 1
        return self._skip_result

    def stop_task(self):
        return None


def _with_fake_host(bridge, host):
    """临时替换 ``okww_boot.get_host`` / ``current_host``。"""
    from src.tools.game.auto_combat import okww_boot

    real_get = okww_boot.get_host
    real_cur = okww_boot.current_host
    okww_boot.get_host = lambda *a, **kw: host
    okww_boot.current_host = lambda: host
    try:
        yield
    finally:
        okww_boot.get_host = real_get
        okww_boot.current_host = real_cur


import contextlib  # noqa: E402


@contextlib.contextmanager
def fake_host(host):
    from src.tools.game.auto_combat import okww_boot

    real_get = okww_boot.get_host
    real_cur = okww_boot.current_host
    okww_boot.get_host = lambda *a, **kw: host
    okww_boot.current_host = lambda: host
    try:
        yield host
    finally:
        okww_boot.get_host = real_get
        okww_boot.current_host = real_cur


def main() -> int:
    b = WebBridge()

    # ══════════════════════════════════════════════════════════════
    # 1) getEchoEnhanceHistory —— 读真实历史文件（709 B，2 条）
    # ══════════════════════════════════════════════════════════════
    h = json.loads(b.getEchoEnhanceHistory())
    ok("history_ok", h.get("ok") is True,
       f"count={h.get('count')} total={h.get('total')}")

    items = h.get("items") or []
    ok("history_has_items", len(items) > 0,
       f"{len(items)} 条（本机实测历史文件里有 2 条）")
    ok("history_default_limit", h.get("limit") == 10,
       f"limit={h.get('limit')}（旧界面就是最近 10 轮）")

    if items:
        it = items[0]
        ok("history_item_fields",
           all(k in it for k in ("when", "duration", "startedAt",
                                 "endedAt", "stats")),
           f"字段 = {sorted(it.keys())}")
        ok("history_when_format",
           ":" in str(it.get("when")) or "-" in str(it.get("when")),
           f"when={it.get('when')!r}（旧界面是 10-28 14:30 这种）")
        ok("history_duration_format",
           ":" in str(it.get("duration")),
           f"duration={it.get('duration')!r}（旧界面是 mm:ss / h:mm:ss）")
        ok("history_stats_is_dict",
           isinstance(it.get("stats"), dict),
           f"stats keys = {sorted((it.get('stats') or {}).keys())[:6]}")

        #: ★ stats 里是工具自定义字段 —— 本机历史有 checked/kept/dropped
        stats = it.get("stats") or {}
        ok("history_stats_has_counts",
           any(k in stats for k in ("checked", "kept", "dropped",
                                    "judged", "qualified")),
           f"统计字段 = {sorted(stats.keys())}")

    #: limit 参数生效
    h1 = json.loads(b.getEchoEnhanceHistory("1"))
    ok("history_limit_respected", len(h1.get("items") or []) <= 1,
       f"limit=1 → {len(h1.get('items') or [])} 条")

    #: 非法 limit 回落默认
    h_bad = json.loads(b.getEchoEnhanceHistory("abc"))
    ok("history_bad_limit_fallback", h_bad.get("ok") is True,
       f"limit='abc' → limit={h_bad.get('limit')}（回落默认）")

    # ══════════════════════════════════════════════════════════════
    # 2) okwwResumeTask
    # ══════════════════════════════════════════════════════════════
    #: 无引擎
    from src.tools.game.auto_combat import okww_boot

    real_cur = okww_boot.current_host
    okww_boot.current_host = lambda: None
    try:
        r = json.loads(b.okwwResumeTask())
    finally:
        okww_boot.current_host = real_cur
    ok("resume_no_engine",
       r.get("ok") is False and r.get("reason") == "idle",
       json.dumps(r, ensure_ascii=False)[:100])

    #: 有任务且 paused → 调 unpause()
    task = _FakeTask(paused=True)
    host = _FakeHost(task=task)
    with fake_host(host):
        r = json.loads(b.okwwResumeTask())
    ok("resume_calls_unpause",
       r.get("ok") is True and task.unpaused == 1,
       f"unpause 被调了 {task.unpaused} 次，paused={task.paused}")
    ok("resume_returns_message", bool(r.get("message")),
       f"message={r.get('message')!r}")

    #: 有宿主但没有任务 → no_task
    host2 = _FakeHost(task=None, run_key="")
    with fake_host(host2):
        r = json.loads(b.okwwResumeTask())
    ok("resume_no_task",
       r.get("ok") is False and r.get("reason") == "no_task",
       json.dumps(r, ensure_ascii=False)[:110])

    #: unpause 抛异常 → resume_failed（不静默）
    class _BadTask:
        paused = True

        def unpause(self):
            raise RuntimeError("executor 已经没了")

    with fake_host(_FakeHost(task=_BadTask())):
        r = json.loads(b.okwwResumeTask())
    ok("resume_failure_reported",
       r.get("ok") is False and r.get("reason") == "resume_failed",
       f"reason={r.get('reason')} message={str(r.get('message'))[:60]!r}")

    # ══════════════════════════════════════════════════════════════
    # 3) okwwSkipEcho
    # ══════════════════════════════════════════════════════════════
    okww_boot.current_host = lambda: None
    try:
        r = json.loads(b.okwwSkipEcho())
    finally:
        okww_boot.current_host = real_cur
    ok("skip_no_engine",
       r.get("ok") is False and r.get("reason") == "idle",
       json.dumps(r, ensure_ascii=False)[:100])

    #: 宿主接受请求
    host3 = _FakeHost(skip_result=True)
    with fake_host(host3):
        r = json.loads(b.okwwSkipEcho())
    ok("skip_calls_host",
       r.get("ok") is True and host3.skip_calls == 1,
       f"request_skip_current 被调了 {host3.skip_calls} 次")
    ok("skip_returns_message", bool(r.get("message")),
       f"message={r.get('message')!r}")

    #: 宿主拒绝（没有在跑的强化任务）→ no_task
    host4 = _FakeHost(skip_result=False)
    with fake_host(host4):
        r = json.loads(b.okwwSkipEcho())
    ok("skip_rejected_when_no_task",
       r.get("ok") is False and r.get("reason") == "no_task",
       json.dumps(r, ensure_ascii=False)[:110])

    # ══════════════════════════════════════════════════════════════
    # 4) 两个接口都已从桥接层移除（lead P4 的错误决定）
    # ══════════════════════════════════════════════════════════════
    ok("removed_setEchoEnhanceProfile",
       not hasattr(b, "setEchoEnhanceProfile"),
       "setEchoEnhanceProfile 已删（用户 2026-09-26 否掉过的错误设计）")
    ok("removed_getEchoEnhanceProfile",
       not hasattr(b, "getEchoEnhanceProfile"),
       "getEchoEnhanceProfile 已删")
    ok("removed_echo_profile_pick",
       not hasattr(b, "_ECHO_PROFILE_PICK_KEY"),
       "_ECHO_PROFILE_PICK_KEY 已删")

    #: _single_tool_flow 不再插 config 步骤
    import src.core.web_bridge as WB

    flow = WB._single_tool_flow("echo_enhance")
    ok("single_tool_flow_no_config_step",
       "config" not in [s.type for s in flow.steps],
       f"步骤 = {[s.type for s in flow.steps]}"
       f"（曾经会插 config，那是错误设计）")

    print()
    print("=" * 70)
    print("结果：" + ("全部通过" if not FAILS else "失败 " + str(FAILS)))
    print("=" * 70)
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
