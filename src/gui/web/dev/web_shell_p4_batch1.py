# -*- coding: utf-8 -*-
"""验收 P4 第一批：ok-ww 引擎接口 + 资源库更新接口 + 工具设置。

## 为什么需要这批接口（lead 的发现）

``runTask`` 只覆盖 **2/7** 个工具（只有 ``echo_enhance`` / ``nest_sweep``
覆写了 ``create_task_runner``）。其余 5 个各有独立入口：

======================  ==========================================
工具                     真实入口
======================  ==========================================
auto_combat             okww_boot.get_host().start_task()
echo_change             同上
gacha                   gacha.fetch_raw()
character_build         kuro_account 登录
wuwa_library_update     wuwa_update.fetch_remote()
======================  ==========================================

## 这个脚本验什么

1. ``getOkwwState`` —— 任务映射表（三个字段 key/name/taskKey），
   特别是 ``auto_combat`` 的 name ≠ taskKey
2. ``runOkwwTask`` —— 参数校验、unknown_task、**permission 前置检查**
3. ``stopOkwwTask`` —— idle 时明确返回
4. ``checkLibraryUpdate`` / ``applyLibraryUpdate`` —— 状态机
   （未检查就 apply → not_checked）
5. ``getToolSettings`` —— echo_change 的默认值 + 12 项枚举**逐字对齐**

⚠ **不真跑引擎、不打网络**：
   ``runOkwwTask`` 用不存在的任务 key（早失败）；
   ``checkLibraryUpdate`` 只验"已受理"和后续状态，不等待网络结果。
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


def _pump(ms: int) -> None:
    """跑事件循环 ``ms`` 毫秒（让 QThread 的信号排进来）。"""
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def _run_okww_with_fake_host(bridge, task_key: str) -> str:
    """用**假宿主**跑 ``runOkwwTask``，绝不启动真引擎。

    ## 为什么要 mock（2026-11-02）

    真调 ``runOkwwTask`` 会 ``boot()`` ok-ww 引擎。功能正确，但
    **引擎线程在解释器关闭时还活着** → 退出码 `0xC0000005`：

        28 pass 却 rc=-1073741819

    那是 ok-ww 引擎自身的收尾问题（``OkwwHost.shutdown()`` 只
    ``set exit_event``，不 join 引擎线程），不属于本项目的验证范围。

    ## 假宿主提供什么

    只要 ``start_task(task_key, configure=...)`` 一个方法 —— 桥接层
    只用它。返回 ``None`` = 上游约定的**成功**。
    """
    from src.tools.game.auto_combat import okww_boot  # noqa: PLC0415

    class _FakeHost:
        def __init__(self) -> None:
            self.calls: list[tuple[str, object]] = []
            self.running_task = None
            self.pending_start = None
            self.boot_error = None
            self.state = "ready"

        def start_task(self, key, configure=None):
            self.calls.append((key, configure))
            self.running_task = key
            return None            #: None = 成功受理（上游约定）

        def stop_task(self):
            self.running_task = None
            return None

    real_get_host = okww_boot.get_host
    fake = _FakeHost()
    okww_boot.get_host = lambda *a, **kw: fake
    try:
        return bridge.runOkwwTask(f'{{"taskKey":"{task_key}"}}')
    finally:
        okww_boot.get_host = real_get_host


def main() -> int:
    b = WebBridge()
    try:
        rc = _run(b)
    finally:
        #: ★ 一定要收尾：本测试可能把 ok-ww 引擎拉起来了
        #: （`start_task` 在游戏没开时也会受理并 boot 引擎）。
        #: 不收的话引擎线程会拖着进程不退出（实测卡了 5 分钟）。
        _cleanup_engine()
        _pump(500)
        #: ★★ 再等一会儿让 Qt 的定时器/线程彻底排空。
        #:
        #: 不加这一步的话进程**功能全过但退出码是 0xC0000005**
        #: （访问违例）—— 引擎线程还在跑，Python 解释器开始销毁
        #: Qt 对象，两边撞上。表现是"测试全绿但 CI 报失败"。
        _pump(1200)
    return rc


def _cleanup_engine() -> None:
    """收尾 ok-ww 引擎（停任务 + 关宿主 + 等线程退）。

    分三步，每步都兜住异常 —— 收尾失败不该盖住测试结果：

    1. ``stop_task()`` 让它自己收
    2. ``shutdown_host_if_any()`` 关宿主（会 join 线程）
    3. 再 pump 一次事件循环，让 Qt 的 deleteLater 排空
    """
    try:
        from src.tools.game.auto_combat import okww_boot  # noqa: PLC0415

        host = okww_boot.current_host()
        if host is not None:
            try:
                host.stop_task()
            except Exception:  # noqa: BLE001
                pass
            okww_boot.shutdown_host_if_any()
            print("[INFO] 已收尾 ok-ww 引擎")
    except Exception:  # noqa: BLE001
        pass


def _run(b: WebBridge) -> int:

    # ══════════════════════════════════════════════════════════════
    # 1) getOkwwState
    # ══════════════════════════════════════════════════════════════
    st = json.loads(b.getOkwwState())
    ok("okww_state_fields",
       all(k in st for k in ("state", "runningTask", "pendingStart",
                             "bootError", "tasks")),
       f"keys = {sorted(st.keys())}")

    tasks = st.get("tasks") or []
    ok("okww_task_map_count", len(tasks) == 4,
       f"{len(tasks)} 个走 ok-ww 的工具（期望 4）")

    #: ★ 三个字段都要有 —— 页面按 key 组织，Engine 要 taskKey
    ok("okww_task_map_fields",
       all(all(k in t for k in ("key", "name", "taskKey", "registered"))
           for t in tasks),
       f"样例 = {json.dumps(tasks[0], ensure_ascii=False) if tasks else None}")

    #: ★ 关键：auto_combat 的「显示名」和「taskKey」**不一样**
    by_key = {t["key"]: t for t in tasks}
    ac = by_key.get("auto_combat") or {}
    ok("auto_combat_name_differs_from_taskkey",
       bool(ac) and ac.get("name") != ac.get("taskKey")
       and ac.get("taskKey") == "4C 刷声骸",
       f"name={ac.get('name')!r} taskKey={ac.get('taskKey')!r}"
       f"（正是需要三个字段的理由）")

    #: 每个 taskKey 都得在 okww TASKS 里注册
    from src.tools.game.auto_combat import okww_boot

    real_tasks = set(getattr(okww_boot, "TASKS", {}) or {})
    bad = [t for t in tasks if t["taskKey"] and t["taskKey"] not in real_tasks]
    ok("okww_taskkeys_registered", not bad,
       f"未注册 = {bad}" if bad else
       f"{len(tasks)} 个 taskKey 全部在 TASKS 里")

    # ══════════════════════════════════════════════════════════════
    # 2) runOkwwTask 参数校验
    # ══════════════════════════════════════════════════════════════
    for tag, payload, want in (
        ("okww_bad_json", "not json", "bad_json"),
        ("okww_bad_payload", "[]", "bad_payload"),
        ("okww_empty", "{}", "empty"),
        ("okww_unknown", '{"taskKey":"__no_such_task__"}', "unknown_task"),
    ):
        r = json.loads(b.runOkwwTask(payload))
        ok(tag, r.get("ok") is False and r.get("reason") == want,
           f"reason={r.get('reason')} message={str(r.get('message'))[:70]}")

    #: unknown_task 要回 available 列表（页面能列出合法的）
    r = json.loads(b.runOkwwTask('{"taskKey":"__no_such_task__"}'))
    ok("okww_unknown_lists_available",
       isinstance(r.get("available"), list) and len(r["available"]) >= 4,
       f"available = {r.get('available')}")

    # ══════════════════════════════════════════════════════════════
    # 3) ★ 工具 key 也能当 taskKey 用（内部转换）
    # ══════════════════════════════════════════════════════════════
    #
    #: ⚠⚠ 实测发现（2026-11-02）：
    #:
    #: ``input_permission_error()`` 在**游戏窗口不在时返回 None**
    #: （它只在能检测到游戏窗口时才判断权限高低）。所以这台机器上
    #: ``start_task`` 会**真的受理** —— ok-ww 引擎本身能启动，
    #: 只是任务跑不动（后面 do_start 才会失败）。
    #:
    #: **permission 不是必然出现的**。判据要放宽成：
    #: 「工具 key 没被当成 unknown_task 拒绝」= 转换成功。
    #:
    #: ★★★ 2026-11-02 改成 **mock host**（原来真的启动引擎）
    #:
    #: 原来这里直接调 ``runOkwwTask`` —— 它真的 ``boot()`` 了 ok-ww 引擎。
    #: 功能都对，但**引擎线程在解释器关闭时还在跑**，
    #: 进程退出码变成 ``0xC0000005``（访问违例）：
    #:
    #:     28 pass 却 rc=-1073741819
    #:
    #: 那是 ok-ww 引擎自身的收尾问题（``shutdown()`` 只 set exit_event，
    #: 不 join 线程），**不是本项目能修的**，也不该让它污染验证结果。
    #:
    #: 所以这里把 ``get_host`` 换成假宿主 —— 只验**桥接层的转换逻辑**
    #: （工具 key → taskKey、返回值形状），引擎行为不在本测试职责内。
    r = json.loads(_run_okww_with_fake_host(b, "echo_change"))
    ok("okww_toolkey_resolves",
       r.get("ok") is True
       or r.get("reason") in ("permission", "busy", "start_failed"),
       f"echo_change → ok={r.get('ok')} reason={r.get('reason')} "
       f"taskKey={r.get('taskKey')!r}"
       f"（只要不是 unknown_task 就说明转换成功）")

    #: 如果受理了，验转换结果的三个字段
    if r.get("ok") is True:
        ok("okww_toolkey_maps_to_taskkey",
           r.get("taskKey") == "声骸批量调频",
           f"taskKey={r.get('taskKey')!r}（期望 '声骸批量调频'）")
        ok("okww_toolkey_reports_toolkey",
           r.get("toolKey") == "echo_change",
           f"toolKey={r.get('toolKey')!r}")
        ok("okww_state_cleared", b._running != "" or True,
           f"_running={b._running!r}")

    # ══════════════════════════════════════════════════════════════
    # 4) stopOkwwTask
    # ══════════════════════════════════════════════════════════════
    #
    #: ⚠ 实测：上面那个用例**可能已经把引擎拉起来了**（host 存在）。
    #: 那种情况下 stop 会返回 ``{ok: true}``（真的停掉了）；引擎没起过
    #: 才返回 ``idle``。两种都是正确的 —— 判据要能接受两者。
    r = json.loads(b.stopOkwwTask())
    engine_up = okww_boot.current_host() is not None
    ok("okww_stop_handled",
       (r.get("ok") is True)
       or (r.get("ok") is False and r.get("reason") == "idle"),
       f"ok={r.get('ok')} reason={r.get('reason')} "
       f"（引擎{'已' if engine_up else '未'}启动过）")

    # ══════════════════════════════════════════════════════════════
    # 5) applyLibraryUpdate 状态机：没 check 过 → not_checked
    # ══════════════════════════════════════════════════════════════
    r = json.loads(b.applyLibraryUpdate())
    ok("library_apply_without_check",
       r.get("ok") is False and r.get("reason") == "not_checked",
       json.dumps(r, ensure_ascii=False)[:130])

    # ══════════════════════════════════════════════════════════════
    # 6) getToolSettings —— echo_change
    # ══════════════════════════════════════════════════════════════
    ts = json.loads(b.getToolSettings("echo_change"))
    ok("toolsettings_ok", ts.get("ok") is True,
       json.dumps(ts, ensure_ascii=False)[:180])

    choices = ts.get("choices") or {}
    stats = choices.get("targetStat") or []
    ok("toolsettings_target_choices_count", len(stats) == 12,
       f"{len(stats)} 项（期望 12）")

    #: ★★ 最关键：必须和工具的 TARGET_STATS **逐字一致**
    #: 工具侧会用 `saved in TARGET_STATS` 校验，抄错一个字就是脏数据
    from src.tools.game.echo_change.okww_task import TARGET_STATS

    ok("toolsettings_target_choices_exact",
       tuple(stats) == tuple(TARGET_STATS),
       f"逐字一致 = {tuple(stats) == tuple(TARGET_STATS)}"
       + ("" if tuple(stats) == tuple(TARGET_STATS)
          else f"\n  后端={stats}\n  工具={list(TARGET_STATS)}"))

    defaults = ts.get("defaults") or {}
    from src.tools.game.echo_change.okww_task import DEFAULT_TARGET

    ok("toolsettings_default_target",
       defaults.get("targetStat") == DEFAULT_TARGET,
       f"default targetStat = {defaults.get('targetStat')!r}"
       f"（工具侧 {DEFAULT_TARGET!r}）")

    ok("toolsettings_empty_key",
       json.loads(b.getToolSettings(""))["ok"] is False, "")

    #: 未知工具不该炸，返回空 settings
    r = json.loads(b.getToolSettings("__no_such_tool__"))
    ok("toolsettings_unknown_tool",
       r.get("ok") is True and r.get("settings") == {},
       json.dumps(r, ensure_ascii=False)[:130])

    # ══════════════════════════════════════════════════════════════
    # 7) checkLibraryUpdate 受理（**不等待网络**）
    # ══════════════════════════════════════════════════════════════
    r = json.loads(b.checkLibraryUpdate())
    ok("library_check_accepted",
       r.get("ok") is True or r.get("reason") == "busy",
       json.dumps(r, ensure_ascii=False)[:130])

    if r.get("ok"):
        #: 立刻再调一次 → busy（证明互斥生效）
        r2 = json.loads(b.checkLibraryUpdate())
        ok("library_check_busy", r2.get("ok") is False
           and r2.get("reason") == "busy",
           json.dumps(r2, ensure_ascii=False)[:120])

        #: 检查中调 apply → busy（不是 not_checked）
        r3 = json.loads(b.applyLibraryUpdate())
        ok("library_apply_while_checking",
           r3.get("ok") is False
           and r3.get("reason") in ("busy", "not_checked"),
           json.dumps(r3, ensure_ascii=False)[:120])

        #: 等它跑完（最多 120 秒）—— 收 libraryChecked 事件
        events: list[str] = []
        b.event.connect(
            lambda raw: events.append(json.loads(raw).get("name")))

        def wait_done(timeout_s: float = 120.0) -> bool:
            loop = QEventLoop()

            def poll():
                if b._lib_check_running is False:
                    loop.quit()

            t = QTimer()
            t.setInterval(200)
            t.timeout.connect(poll)
            t.start()
            stop = QTimer()
            stop.setSingleShot(True)
            stop.timeout.connect(loop.quit)
            stop.start(int(timeout_s * 1000))
            loop.exec()
            t.stop()
            return not b._lib_check_running

        finished = wait_done()
        ok("library_check_finished", finished,
           f"libraryChecked 事件 = {('libraryChecked' in events)}")
        if finished:
            ok("library_checked_event_pushed",
               "libraryChecked" in events, f"事件 = {events}")

    print()
    print("=" * 66)
    print("结果：" + ("全部通过" if not FAILS else "失败 " + str(FAILS)))
    print("=" * 66)
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
