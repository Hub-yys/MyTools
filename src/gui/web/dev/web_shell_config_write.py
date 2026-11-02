# -*- coding: utf-8 -*-
"""验收 3 个写接口：`setConfig` / `deleteConfig` / `saveFlow`。

## ⚠⚠ 用户数据保护（2026-11-02 事故后加的）

这个测试**真的会写盘**。2026-11-02 它把用户 5 条「角色声骸强化配置」
整个清空了 —— 底座是 ``EchoProfileStore`` 曾经 auto-load=False 的坑：
没 load 就 add，`save()` 把整个文件覆盖成只剩新加那 1 条。

**两道防线，都要有：**

1. **根因已修** —— ``EchoProfileStore.__init__`` 现在会 ``load()``，
   ``save()`` 还加了「拒绝把非空文件写成空」的护栏；
2. **本测试仍先备份** —— ``backup_guard.user_data_backup()`` 在开头
   快照所有用户数据，结束时（**含异常**）原样恢复。

第二道不能省：根因修了不代表以后不会再有别的路径写坏数据，
而测试**永远**不该成为毁数据的途径。
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", "..", ".."))
sys.path.insert(0, _ROOT)
sys.path.insert(0, _HERE)          #: 让 backup_guard 可导入
os.chdir(_ROOT)
os.environ.setdefault("QT_LOGGING_RULES", "qt.multimedia.*=false")

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])
import src.tools as tools_pkg  # noqa: E402

tools_pkg.discover_tools()

from backup_guard import UserDataGuard  # noqa: E402
from src.core.web_bridge import WebBridge  # noqa: E402

FAILS: list[str] = []
#: 需要在 finally 里清理的东西
CLEANUP: list[tuple[str, str]] = []      # [(kind, id)]
PREFIX = "__smoke_"


def ok(tag: str, cond: bool, note: str = "") -> None:
    print(f"[{'PASS' if cond else 'FAIL'}] {tag}  {note}")
    if not cond:
        FAILS.append(tag)


def pump(ms: int) -> None:
    """跑事件循环 ``ms`` 毫秒（让工作线程的信号排进来）。"""
    from PySide6.QtCore import QEventLoop, QTimer

    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def wait_idle(b: WebBridge, timeout_s: float = 15.0) -> bool:
    """等 ``_running`` 变空（执行器真的结束）。"""
    import time

    deadline = time.perf_counter() + timeout_s
    while time.perf_counter() < deadline:
        if not b._running:
            return True
        pump(50)
    return False


def stop_and_settle(b: WebBridge, timeout_s: float = 15.0) -> bool:
    """停止当前任务并等它真的停下。"""
    if not b._running:
        return True
    try:
        b.stopTask()
    except Exception:  # noqa: BLE001
        pass
    return wait_idle(b, timeout_s)


def cleanup_all(b: WebBridge) -> None:
    for kind, item_id in CLEANUP:
        try:
            b.deleteConfig(kind, item_id)
        except Exception:  # noqa: BLE001
            pass
    CLEANUP.clear()


def main() -> int:
    #: ★ 先快照用户数据 —— 不管下面做什么，退出时都会原样恢复
    guard = UserDataGuard()
    guard.start()
    before_counts = guard.snapshot()
    print(f"[INFO] 用户数据已备份：{before_counts}")
    try:
        rc = _run_tests()
    finally:
        #: ⚠ 一定要恢复（哪怕 _run_tests 抛异常）
        restored = guard.restore()
        after_counts = guard.snapshot()
        print(f"[INFO] 已恢复用户数据 → {after_counts}")
        if not restored:
            print("[ERROR] 恢复不完全，请检查 data/ 目录！")
        if before_counts != after_counts:
            print(f"[ERROR] 恢复前后不一致！{before_counts} vs {after_counts}")
            FAILS.append("data_restored")
    return rc


def _run_tests() -> int:
    b = WebBridge()

    # ══════════════════════════════════════════════════════════════
    #  setConfig / deleteConfig —— loadout
    #
    # ⚠⚠ 2026-11-02 改：角色名**必须是真实存在的角色**。
    #
    # 这里原来用 ``__smoke_loe`` 这种假名字，测试能过 —— 但那是**漏洞**：
    # 后端的角色校验（``character_choice_error``）当时还没接。
    # 接上之后这个测试立刻红了 —— 说明**校验真的生效了**。
    #
    # 现在的做法：从 ``getCharacterOptions`` 里挑**两个没被占用**的真实角色，
    # 一个用来新建/改名（改名前后的名字都得是真角色）。
    # ══════════════════════════════════════════════════════════════
    options = json.loads(b.getCharacterOptions("loadout"))
    free_names = [x["name"] for x in (options.get("items") or [])
                  if not x.get("taken")]
    if len(free_names) < 2:
        ok("need_two_free_characters", False,
           f"只有 {len(free_names)} 个空闲角色，无法测新建+改名")
        return finish()

    name = free_names[0]              #: 新建时用
    rename_to = free_names[1]         #: 改名成这个
    before = len(json.loads(b.getConfigList()).get("loadouts") or [])

    r = json.loads(b.setConfig(json.dumps({
        "kind": "loadout",
        "data": {
            "character": name,
            "avatar": f"avatars/{name}.png",
            "echo_set": "羽落空尘之歌",
        },
    }, ensure_ascii=False)))
    new_id = r.get("id") or ""
    if new_id:
        CLEANUP.append(("loadout", new_id))
    ok("setConfig_loadout_create",
       r.get("ok") is True and r.get("created") is True and bool(new_id),
       json.dumps(r, ensure_ascii=False)[:150])

    after = len(json.loads(b.getConfigList()).get("loadouts") or [])
    ok("setConfig_loadout_count_plus1", after == before + 1,
       f"{before} → {after}")

    #: 修改它（改名成另一个**真实**角色）
    r2 = json.loads(b.setConfig(json.dumps({
        "kind": "loadout", "id": new_id,
        "data": {"character": rename_to, "echo_set": "茜染怀想之花"},
    }, ensure_ascii=False)))
    ok("setConfig_loadout_update",
       r2.get("ok") is True and r2.get("created") is False,
       json.dumps(r2, ensure_ascii=False)[:150])

    #: 确认真的改了
    cfg = json.loads(b.getConfigList())
    hit = next((x for x in (cfg.get("loadouts") or [])
                if x.get("id") == new_id), None)
    ok("setConfig_loadout_persisted",
       hit is not None and hit.get("character") == rename_to,
       f"character={hit.get('character') if hit else None!r}"
       f"（期望 {rename_to!r}）")

    #: 改不存在的 → not_found（不偷偷新建）
    r3 = json.loads(b.setConfig(json.dumps({
        "kind": "loadout", "id": "__no_such__",
        "data": {"character": name},
    }, ensure_ascii=False)))
    ok("setConfig_loadout_missing_id",
       r3.get("ok") is False and r3.get("reason") == "not_found",
       json.dumps(r3, ensure_ascii=False)[:130])

    #: 删除
    r4 = json.loads(b.deleteConfig("loadout", new_id))
    ok("deleteConfig_loadout", r4.get("ok") is True,
       json.dumps(r4, ensure_ascii=False)[:130])
    if r4.get("ok"):
        CLEANUP.remove(("loadout", new_id))

    after2 = len(json.loads(b.getConfigList()).get("loadouts") or [])
    ok("deleteConfig_count_back", after2 == before, f"{after} → {after2}")

    #: 再删一次 → not_found
    r5 = json.loads(b.deleteConfig("loadout", new_id))
    ok("deleteConfig_missing",
       r5.get("ok") is False and r5.get("reason") == "not_found",
       json.dumps(r5, ensure_ascii=False)[:130])

    # ══════════════════════════════════════════════════════════════
    #  setConfig —— echo_profile
    #
    # ⚠ 同理：``name`` 必须是**真实角色名**（EchoProfile 的主键就是角色名，
    # 后端会拿它去 ``character_choice_error`` 校验）。
    # 从"没被 echo_profile 占用"的真实角色里挑。
    # ══════════════════════════════════════════════════════════════
    prof_options = json.loads(b.getCharacterOptions("echo_profile"))
    prof_free = [x["name"] for x in (prof_options.get("items") or [])
                 if not x.get("taken")]
    if not prof_free:
        ok("need_free_character_for_profile", False,
           "没有未被占用的角色，无法测战斗配置新建")
        return finish()

    prof_name = prof_free[0]
    r6 = json.loads(b.setConfig(json.dumps({
        "kind": "echo_profile",
        "data": {"name": prof_name, "character": prof_name},
    }, ensure_ascii=False)))
    ok("setConfig_echo_profile",
       r6.get("ok") is True and r6.get("kind") == "echo_profile",
       json.dumps(r6, ensure_ascii=False)[:150])
    if r6.get("ok"):
        CLEANUP.append(("echo_profile", r6.get("id") or prof_name))

    profs = json.loads(b.getConfigList()).get("echoProfiles") or []
    ok("echo_profile_persisted",
       any(x.get("name") == prof_name for x in profs),
       f"共 {len(profs)} 条，含 {prof_name} = "
       f"{any(x.get('name') == prof_name for x in profs)}")

    # ══════════════════════════════════════════════════════════════
    #  saveFlow
    # ══════════════════════════════════════════════════════════════
    flow_name = f"{PREFIX}flow"
    flows_before = len(json.loads(b.getFlowList()))

    r7 = json.loads(b.saveFlow(json.dumps({
        "name": flow_name,
        "steps": [
            {"type": "start", "name": "开始"},
            {"type": "tool", "key": "echo_enhance", "name": "声骸自动强化"},
            {"type": "end", "name": "结束"},
        ],
    }, ensure_ascii=False)))
    flow_id = r7.get("id") or ""
    ok("saveFlow_create",
       r7.get("ok") is True and r7.get("created") is True and bool(flow_id),
       json.dumps(r7, ensure_ascii=False)[:160])

    flows_after = len(json.loads(b.getFlowList()))
    ok("saveFlow_count_plus1", flows_after == flows_before + 1,
       f"{flows_before} → {flows_after}")

    #: 修改
    r8 = json.loads(b.saveFlow(json.dumps({
        "id": flow_id,
        "name": flow_name + "v2",
        "steps": [
            {"type": "start", "name": "开始"},
            {"type": "tool", "key": "nest_sweep", "name": "扫荡残像聚落"},
        ],
    }, ensure_ascii=False)))
    ok("saveFlow_update",
       r8.get("ok") is True and r8.get("created") is False,
       json.dumps(r8, ensure_ascii=False)[:160])

    #: 校验不过的不让存
    r9 = json.loads(b.saveFlow(json.dumps({
        "name": "", "steps": [],
    }, ensure_ascii=False)))
    ok("saveFlow_rejects_invalid",
       r9.get("ok") is False and r9.get("reason") == "invalid",
       json.dumps(r9, ensure_ascii=False)[:160])

    #: 那条流程现在能跑吗？
    #:
    #: ⚠⚠ 2026-11-02 修（偶发 6 项失败的真因）：
    #:
    #: 原来假设 ``runFlow`` **一定**被 precheck 拦下（游戏没开嘛）。
    #: 但 precheck 是按 ``flow.derived_type()`` 判断的 —— 这条测试流程只
    #: 放了 ``nest_sweep``，它推导出来是 **data 类**，
    #: ``check_start()`` 对非游戏类型直接放行（"不需要检查游戏客户端"）。
    #:
    #: 于是 ``runFlow`` **真的起了线程**，``_running`` 被占住 →
    #: 后面所有 ``setConfig`` / ``deleteConfig`` 全返回 ``busy``。
    #:
    #: 表现是**偶发**：线程活得久就跑；``QThread`` 结束得快时就不跑。
    #: 这种不确定的测试比没有更糟 —— 会让人怀疑的是代码还是测试。
    r10 = json.loads(b.runFlow(flow_id))
    ok("saveFlow_flow_runnable",
       r10.get("ok") is True or r10.get("reason") in ("precheck", "invalid"),
       f"ok={r10.get('ok')} reason={r10.get('reason')}")

    #: ★ 关键：不管真跑没跑起来，**必须把它停干净**再往下
    if r10.get("ok") is True:
        ok("saveFlow_stopped", stop_and_settle(b, timeout_s=30.0),
           f"_running={b._running!r}（真起了线程，必须等它退出）")
    else:
        wait_idle(b)

    #: 删掉（TaskStore.remove 没暴露给 JS，直接用 store）
    try:
        from src.core.tasks import TaskStore

        removed = TaskStore().remove(flow_id)
        ok("saveFlow_cleanup", removed is True, f"删除 {flow_id} = {removed}")
    except Exception as exc:  # noqa: BLE001
        ok("saveFlow_cleanup", False, f"{type(exc).__name__}: {exc}")

    # ══════════════════════════════════════════════════════════════
    #  参数校验
    # ══════════════════════════════════════════════════════════════
    for tag, raw, want in (
        ("setConfig_bad_json", "not json", "bad_json"),
        ("setConfig_bad_kind", json.dumps({"kind": "nope", "data": {}}),
         "bad_kind"),
        ("setConfig_bad_data", json.dumps({"kind": "loadout", "data": 1}),
         "bad_data"),
    ):
        got = json.loads(b.setConfig(raw))
        ok(tag, got.get("ok") is False and got.get("reason") == want,
           f"reason={got.get('reason')} message={str(got.get('message'))[:60]}")

    got = json.loads(b.deleteConfig("nope", "x"))
    ok("deleteConfig_bad_kind",
       got.get("ok") is False and got.get("reason") == "bad_kind",
       f"reason={got.get('reason')}")

    got = json.loads(b.deleteConfig("loadout", ""))
    ok("deleteConfig_empty_id",
       got.get("ok") is False and got.get("reason") == "empty_id",
       f"reason={got.get('reason')}")

    got = json.loads(b.saveFlow("not json"))
    ok("saveFlow_bad_json",
       got.get("ok") is False and got.get("reason") == "bad_json",
       f"reason={got.get('reason')}")

    cleanup_all(b)

    print()
    print("=" * 64)
    print("结果：" + ("全部通过" if not FAILS else "失败 " + str(FAILS)))
    print("=" * 64)
    return 1 if FAILS else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        import traceback

        traceback.print_exc()
        raise SystemExit(1)
