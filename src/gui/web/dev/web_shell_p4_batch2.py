# -*- coding: utf-8 -*-
"""验收 P4 第二批：扫荡清单接口 + 前置条件后端化 + auto_combat 战斗风格。

## 覆盖

* ``getNestSweepData()`` —— 清单 + 勾选（**含 sets 空/非空语义**）
* ``setNestSweepSelection()`` —— 保存 + **清洗失效 key 并回报**
* ``getToolSettings('auto_combat')`` —— 战斗风格三元组展开
* ``prerequisites`` —— 前置条件从后端给（lead 提的）

## ⚠ 用户数据保护

``setNestSweepSelection`` 会**真的写** ``tool_settings.json``。
本机有 10 个真实勾选 —— 所以：

1. 开头快照原勾选
2. 测完**原样写回**
3. `finally` 兜底

用 ``backup_guard.UserDataGuard`` 做整文件备份更稳（双重保险）。
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

from backup_guard import UserDataGuard  # noqa: E402
from src.core.web_bridge import WebBridge  # noqa: E402

FAILS: list[str] = []


def ok(tag: str, cond: bool, note: str = "") -> None:
    print(f"[{'PASS' if cond else 'FAIL'}] {tag}  {note}")
    if not cond:
        FAILS.append(tag)


def main() -> int:
    guard = UserDataGuard()
    guard.start()
    before = guard.snapshot()
    print(f"[INFO] 用户数据已备份：{before}")
    try:
        rc = _run()
    finally:
        guard.restore()
        print(f"[INFO] 已恢复 → {guard.snapshot()}")
    return rc


def _run() -> int:
    b = WebBridge()

    # ══════════════════════════════════════════════════════════════
    # 1) getNestSweepData
    # ══════════════════════════════════════════════════════════════
    data = json.loads(b.getNestSweepData())
    ok("nest_data_ok", data.get("ok") is True,
       f"count={data.get('count')} selected={len(data.get('selected') or [])} "
       f"summary={data.get('summary')!r}")

    targets = data.get("targets") or []
    ok("nest_targets_nonempty", len(targets) > 0, f"{len(targets)} 个可选目标")
    ok("nest_selected_nonempty", len(data.get("selected") or []) > 0,
       f"{len(data.get('selected') or [])} 个已勾选（用户的真实勾选）")

    if targets:
        t0 = targets[0]
        ok("nest_target_fields",
           all(k in t0 for k in ("key", "name", "kind", "kindName", "region",
                                 "count", "version", "sets", "verified",
                                 "order")),
           f"字段 = {sorted(t0.keys())}")

        #: ★ kindName 要能给人看
        ok("nest_kindname_readable",
           t0.get("kindName") in ("残像聚落", "梦魇残像"),
           f"kind={t0.get('kind')!r} kindName={t0.get('kindName')!r}")

        #: ★★ 关键：sets 空/非空语义必须如实传
        with_sets = [t for t in targets if t.get("sets")]
        without_sets = [t for t in targets if not t.get("sets")]
        ok("nest_sets_语义_has_both",
           len(with_sets) > 0,
           f"有套装 {len(with_sets)} 个，无套装 {len(without_sets)} 个"
           f"（空 = 不知道，页面不画这一行）")
        if with_sets:
            ok("nest_sets_are_strings",
               all(isinstance(s, str) for s in with_sets[0]["sets"]),
               f"样例 = {with_sets[0]['name']} → {with_sets[0]['sets']}")

        #: 一个勾选都没丢（load_selection 已过滤失效 key）
        selected = set(data.get("selected") or [])
        keys = {t["key"] for t in targets}
        orphan = selected - keys
        ok("nest_selected_all_valid", not orphan,
           f"失效 key = {orphan}" if orphan
           else f"{len(selected)} 个勾选全部有效")

    # ══════════════════════════════════════════════════════════════
    # 2) setNestSweepSelection
    # ══════════════════════════════════════════════════════════════
    original = list(data.get("selected") or [])
    keys = [t["key"] for t in targets]

    #: ① 存一个子集
    subset = keys[:3]
    r = json.loads(b.setNestSweepSelection(
        json.dumps({"selected": subset})))
    ok("nest_save_ok", r.get("ok") is True,
       f"selected={r.get('selected')} summary={r.get('summary')!r}")
    ok("nest_save_roundtrip",
       list(r.get("selected") or []) == subset,
       f"存进去的 = {r.get('selected')}，期望 {subset}")

    #: ② 回读确认真的写盘了
    again = json.loads(b.getNestSweepData())
    ok("nest_save_persisted",
       list(again.get("selected") or []) == subset,
       f"回读 = {again.get('selected')}")

    #: ③ ★ 塞一个失效 key —— 必须被清洗掉并**回报**
    bogus = subset + ["__no_such_key__"]
    r = json.loads(b.setNestSweepSelection(
        json.dumps({"selected": bogus})))
    ok("nest_bogus_dropped",
       "__no_such_key__" not in (r.get("selected") or []),
       f"selected={r.get('selected')}")
    ok("nest_bogus_reported",
       r.get("dropped") == ["__no_such_key__"],
       f"dropped={r.get('dropped')}（页面据此纠正 UI）")
    ok("nest_bogus_message",
       bool(r.get("message")),
       f"message={r.get('message')!r}")

    #: ④ 接受裸数组形式
    r = json.loads(b.setNestSweepSelection(json.dumps(keys[:2])))
    ok("nest_accepts_bare_array",
       r.get("ok") is True and len(r.get("selected") or []) == 2,
       f"selected={r.get('selected')}")

    #: ⑤ 参数校验
    for tag, payload, want in (
        ("nest_set_bad_json", "not json", "bad_json"),
        ("nest_set_bad_data", '{"selected":"notarray"}', "bad_data"),
    ):
        r = json.loads(b.setNestSweepSelection(payload))
        ok(tag, r.get("ok") is False and r.get("reason") == want,
           f"reason={r.get('reason')}")

    #: ⑥ ★ 恢复用户原来的勾选
    r = json.loads(b.setNestSweepSelection(json.dumps({"selected": original})))
    ok("nest_restore_user_selection",
       r.get("ok") is True and sorted(r.get("selected") or []) == sorted(original),
       f"恢复到 {len(r.get('selected') or [])} 个（原 {len(original)} 个）")

    # ══════════════════════════════════════════════════════════════
    # 3) getToolSettings('auto_combat') —— 战斗风格三元组展开
    # ══════════════════════════════════════════════════════════════
    ac = json.loads(b.getToolSettings("auto_combat"))
    ok("ac_settings_ok", ac.get("ok") is True,
       f"settingsKey={ac.get('settingsKey')!r}")

    #: ★ settingsKey 必须映射到 COMBAT_STYLE_KEY，不是工具 key
    ok("ac_settings_key_mapped",
       ac.get("settingsKey") == "auto_combat_style",
       f"settingsKey={ac.get('settingsKey')!r}"
       f"（工具 key 是 auto_combat，存盘键是 auto_combat_style）")

    choices = ac.get("choices") or {}
    styles = choices.get("style") or []
    ok("ac_style_choices_count", len(styles) == 3,
       f"{len(styles)} 种战斗风格（期望 3）")

    #: ★ 三元组必须展开成 {value,label,desc}，不能把工具私有结构丢给页面
    if styles:
        s0 = styles[0]
        ok("ac_style_expanded",
           isinstance(s0, dict) and all(k in s0 for k in ("value", "label")),
           f"样例 = {json.dumps(s0, ensure_ascii=False)[:130]}")

        #: 逐字对齐 rotation.STYLES
        from src.tools.game.auto_combat.rotation import STYLES

        got_values = [s["value"] for s in styles]
        want_values = [t[0] for t in STYLES]
        ok("ac_style_values_exact", got_values == want_values,
           f"后端={got_values}\n  工具={want_values}")

    ok("ac_style_default",
       (ac.get("defaults") or {}).get("style") == "smart",
       f"defaults.style={(ac.get('defaults') or {}).get('style')!r}")

    # ══════════════════════════════════════════════════════════════
    # 4) ★ prerequisites **已删**（2026-11-02，旧界面没有这块）
    # ══════════════════════════════════════════════════════════════
    #
    #: 原来这里有 11 条断言在验「每个工具的前置条件文案」——
    #: 那套东西是 P4 时 lead 让我加的，**用户截图证明旧界面根本没有**，
    #: 已整块删除（见 docs 坑 #15）。
    #:
    #: 所以现在反过来断言「字段不存在」—— 防止哪天又被加回来。
    for tool_key in ("echo_change", "nest_sweep", "auto_combat",
                     "wuwa_library_update", "gacha"):
        ts = json.loads(b.getToolSettings(tool_key))
        ok(f"no_prereq_{tool_key}",
           "prerequisites" not in ts,
           f"字段 = {sorted(ts.keys())}"
           f"（旧界面没有「运行前提」区块，用户要求去掉）")

    #: 未知工具也不该有那个字段
    r = json.loads(b.getToolSettings("__no_such_tool__"))
    ok("no_prereq_unknown_tool",
       "prerequisites" not in r,
       f"字段 = {sorted(r.keys())}")

    #: 模块级符号也该彻底没了
    import src.core.web_bridge as _WB

    leftovers = [n for n in ("_TOOL_PREREQUISITES",
                             "_COMMON_GAME_PREREQUISITES",
                             "_prerequisites_for", "_OKWW_TOOL_KEYS")
                 if hasattr(_WB, n)]
    ok("prereq_module_symbols_gone", not leftovers,
       f"残留 = {leftovers}" if leftovers else "4 个符号全部删除")

    print()
    print("=" * 66)
    print("结果：" + ("全部通过" if not FAILS else "失败 " + str(FAILS)))
    print("=" * 66)
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
