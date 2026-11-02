# -*- coding: utf-8 -*-
"""验证 `setConfig` 写 loadout 的**读写对称**（lead 要求）。

## 为什么要验

``getConfigList()`` 读出来的字段和 ``setConfig()`` 写进去的字段
必须**能原地往返** —— 否则：

* 页面把读到的对象原样提交（"编辑后保存"）→ 悄悄丢掉字段
* 或者类型变了（``int`` ↔ ``str`` / ``tuple`` ↔ ``list``）→ 越改越乱

这类 bug **不报错**，只在用户编辑几次之后发现"我选的东西没了"。

## 做什么

.. code:: python

    before  = getConfigList().loadouts[0]
    setConfig({"kind":"loadout", "id": before["id"], "data": before})
    after   = getConfigList().loadouts[0]
    assert before == after

## ⚠ 用户数据保护

``loadouts.json`` 里有用户 **8 条真实配置** —— 全程 ``UserDataGuard`` 包住。
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
    try:
        return _run()
    finally:
        guard.restore()


def _diff_keys(before: dict, after: dict) -> list[str]:
    """找出不一样（或缺失）的顶层 key。"""
    out: list[str] = []
    for key in set(before) | set(after):
        if key not in before:
            out.append(f"+{key}")
        elif key not in after:
            out.append(f"-{key}")
        elif before[key] != after[key]:
            out.append(key)
    return out


def _run() -> int:
    b = WebBridge()

    cfg = json.loads(b.getConfigList())
    loadouts = cfg.get("loadouts") or []
    ok("has_loadouts", len(loadouts) > 0,
       f"{len(loadouts)} 条声骸配置（用户真实数据）")
    if not loadouts:
        return finish()

    # ══════════════════════════════════════════════════════════════
    # 1) ★ 单条：读 → 原样写回 → 再读 → 完全一致
    # ══════════════════════════════════════════════════════════════
    for idx, before in enumerate(loadouts):
        wid = before.get("id")
        #: 原样提交（页面"编辑后保存"就是这么做的）
        payload = {
            "kind": "loadout",
            "id": wid,
            "data": {k: v for k, v in before.items()
                     #: id 由 URL 传，别塞进 data（避免两处打架）
                     if k not in ("id", "errors", "taken")},
        }
        r = json.loads(b.setConfig(json.dumps(payload)))
        if not r.get("ok"):
            ok(f"roundtrip_write_{idx}", False,
               f"{before.get('character')}: {r.get('reason')} "
               f"{str(r.get('message'))[:60]}")
            continue

        after_cfg = json.loads(b.getConfigList())
        after = next((x for x in (after_cfg.get("loadouts") or [])
                      if x.get("id") == wid), None)
        if after is None:
            ok(f"roundtrip_found_{idx}", False, f"写回后找不到 id={wid}")
            continue

        diffs = _diff_keys(before, after)
        #: ``errors`` 是 validate() 现算的，可能因数据变化而变 —— 不参与比对。
        #:
        #: ``updatedAt`` 也排除 —— **保存时时间戳本来就该变**（那是它存在
        #: 的意义）。真正要验的是"内容字段有没有丢"。
        #: 但要注意：它必须**变成新值**而不是变成空串 —— 那个单独验。
        diffs = [d for d in diffs
                 if d.lstrip("+-") not in ("errors", "updatedAt")]
        ok(f"roundtrip_identical_{idx}", not diffs,
           f"{before.get('character', '?'):10s} "
           f"{'内容字段往返一致' if not diffs else '差异: ' + str(diffs)}")

        #: ★ updatedAt 应该被更新成"现在"，而不是被清空
        ok(f"roundtrip_timestamp_refreshed_{idx}",
           bool(str(after.get("updatedAt") or "").strip()),
           f"updatedAt = {after.get('updatedAt')!r}"
           f"（保存后应有新时间，不是空）")

    # ══════════════════════════════════════════════════════════════
    # 2) ★ 类型不能漂移（int / str / list / dict）
    # ══════════════════════════════════════════════════════════════
    sample = loadouts[0]
    types_before = {k: type(v).__name__ for k, v in sample.items()}
    payload = {
        "kind": "loadout", "id": sample["id"],
        "data": {k: v for k, v in sample.items()
                 if k not in ("id", "errors", "taken")},
    }
    json.loads(b.setConfig(json.dumps(payload)))
    after_cfg = json.loads(b.getConfigList())
    after = next((x for x in (after_cfg.get("loadouts") or [])
                  if x.get("id") == sample["id"]), None)
    if after:
        types_after = {k: type(v).__name__ for k, v in after.items()}
        drift = {k: (types_before.get(k), types_after.get(k))
                 for k in set(types_before) | set(types_after)
                 if types_before.get(k) != types_after.get(k)
                 and k not in ("errors", "taken")}
        ok("roundtrip_no_type_drift", not drift,
           f"类型全部一致" if not drift
           else f"⚠ 类型漂移 = {drift}")

    # ══════════════════════════════════════════════════════════════
    # 3) picks 的 key 是字符串（"4"/"3"/"1"）
    # ══════════════════════════════════════════════════════════════
    with_picks = [x for x in loadouts if x.get("picks")]
    if with_picks:
        p = with_picks[0]
        keys = list((p.get("picks") or {}).keys())
        ok("picks_keys_are_strings",
           all(isinstance(k, str) for k in keys),
           f"{p.get('character')} 的 picks keys = {keys}")
        #: 每档的值是 list[dict{echo, stats}]
        bad_struct = [
            k for k, v in (p.get("picks") or {}).items()
            if not isinstance(v, list)
            or any(not isinstance(x, dict) or "echo" not in x for x in v)
        ]
        ok("picks_structure_is_list_of_dict",
           not bad_struct,
           "每档是 [{echo, stats}]" if not bad_struct
           else f"结构不对 = {bad_struct}")
    else:
        ok("picks_keys_are_strings", True, "（本机 loadout 没有 picks）")

    # ══════════════════════════════════════════════════════════════
    # 4) ★★ 用户否掉的规则**没被加回来**
    # ══════════════════════════════════════════════════════════════
    free = json.loads(b.getCharacterOptions("loadout"))
    free_names = [x["name"] for x in (free.get("items") or [])
                  if not x.get("taken")]
    if free_names:
        #: 只填角色 + 套装，**各档一个都不选** —— 用户 2026-09-28 明确合法
        r = json.loads(b.setConfig(json.dumps({
            "kind": "loadout",
            "data": {"character": free_names[0],
                     "echo_set": "茜染怀想之花",
                     "picks": {}},
        }, ensure_ascii=False)))
        ok("empty_picks_is_valid", r.get("ok") is True,
           f"只填角色+套装、各档不选 → ok={r.get('ok')}"
           f"（用户 2026-09-28：『1C、3C、4C 都可以不填』）")
        ok("no_4c_required_warning",
           not any("4C" in str(w) for w in (r.get("warnings") or [])),
           f"warnings = {r.get('warnings')}"
           f"（以前会报「4C 声骸为必填项」，用户抱怨过）")
        if r.get("ok"):
            json.loads(b.deleteConfig("loadout", r["id"]))

    #: 角色必填 / 套装必填 仍然是要求
    r = json.loads(b.setConfig(json.dumps({
        "kind": "loadout", "data": {"character": "", "echo_set": "x"},
    })))
    ok("character_still_required",
       r.get("ok") is False and r.get("reason") == "bad_character",
       f"空角色 → {r.get('reason')}")

    # ══════════════════════════════════════════════════════════════
    # 5) ★ _save_loadout 用的是 Loadout.validate()，不是另写一套
    # ══════════════════════════════════════════════════════════════
    bridge_src = open(os.path.join(_ROOT, "src", "core", "web_bridge.py"),
                      encoding="utf-8").read()
    save_fn = bridge_src.split("def _save_loadout")[-1].split("def _character")[0]
    ok("uses_loadout_validate",
       "item.validate()" in save_fn,
       "_save_loadout 里调的是 item.validate()（不是自己另写校验）")
    ok("does_not_check_cost_required",
       "4C" not in save_fn and "required_costs" not in save_fn,
       "没有自己加「各档必填」的检查")

    # ══════════════════════════════════════════════════════════════
    # 6) ★★ 半截数据必须 ok:false（lead P0 ②）
    # ══════════════════════════════════════════════════════════════
    if free_names:
        #: 选了声骸但**没选套装** → 真矛盾，必须拦
        r = json.loads(b.setConfig(json.dumps({
            "kind": "loadout",
            "data": {
                "character": free_names[0],
                "echo_set": "",              #: 空套装
                "picks": {"4": [{"echo": "千傀重楼", "stats": ["暴击"]}]},
            },
        }, ensure_ascii=False)))
        ok("half_baked_rejected",
           r.get("ok") is False and r.get("reason") == "bad_echo_set",
           f"选了声骸没套装 → ok={r.get('ok')} reason={r.get('reason')}")
        #: ⚠ 必须**撤回**那条废配置（别留脏数据）
        after_cfg = json.loads(b.getConfigList())
        leftover = [x for x in (after_cfg.get("loadouts") or [])
                    if x.get("character") == free_names[0]]
        ok("half_baked_rolled_back", not leftover,
           f"被拒的新建没有留在 Store 里（残留 {len(leftover)} 条）")

        #: ★ 但「套装给了、各档不选」仍然合法（用户 2026-09-28）
        r = json.loads(b.setConfig(json.dumps({
            "kind": "loadout",
            "data": {"character": free_names[0],
                     "echo_set": "茜染怀想之花", "picks": {}},
        }, ensure_ascii=False)))
        ok("full_empty_picks_still_ok", r.get("ok") is True,
           f"有套装、各档不选 → ok={r.get('ok')}（合法）")
        if r.get("ok"):
            json.loads(b.deleteConfig("loadout", r["id"]))

    # ══════════════════════════════════════════════════════════════
    # 7) ★★★ 其他 Store 的往返（lead P0 ④）
    # ══════════════════════════════════════════════════════════════
    import inspect  # noqa: PLC0415

    from src.core import echo_profile as _echo  # noqa: PLC0415
    from src.core import loadout as _loadout  # noqa: PLC0415
    from src.core import tasks as _tasks  # noqa: PLC0415

    def _recognized_keys(cls) -> set[str]:
        """从 ``from_dict`` 源码里抠出 ``data.get("xxx")`` 的字段名。"""
        try:
            src = inspect.getsource(cls.from_dict)
        except (OSError, TypeError):
            return set()
        out: set[str] = set()
        idx = 0
        while True:
            i = src.find('data.get("', idx)
            if i < 0:
                break
            j = src.find('"', i + 10)
            out.add(src[i + 10:j])
            idx = j
        return out

    def _store_roundtrip(label: str, items, cls) -> tuple[bool, str]:
        if not items:
            return True, "（无数据，跳过）"
        before = items[0].to_dict()
        rebuilt = cls.from_dict(json.loads(
            json.dumps(before, ensure_ascii=False)))
        after = rebuilt.to_dict()
        diff = {k: (before.get(k), after.get(k))
                for k in set(before) | set(after)
                if before.get(k) != after.get(k)}
        return (not diff,
                f"{len(before)} 个字段" if not diff else f"差异 {diff}")

    #: Loadout
    good, note = _store_roundtrip(
        "Loadout", _loadout.LoadoutStore().all(), _loadout.Loadout)
    ok("core_loadout_roundtrip", good, note)

    #: EchoProfile（⚠ 必须 load()，它不自动读盘）
    _ps = _echo.EchoProfileStore()
    _ps.load()
    good, note = _store_roundtrip("EchoProfile", _ps.all(), _echo.EchoProfile)
    ok("core_echo_profile_roundtrip", good, note)

    #: TaskFlow
    good, note = _store_roundtrip(
        "TaskFlow", _tasks.TaskStore().all(), _tasks.TaskFlow)
    ok("core_task_roundtrip", good, note)

    #: ★ 字段名对称：to_dict 产出的 key 必须都被 from_dict 认
    for label, cls, items in (
        ("loadout", _loadout.Loadout, _loadout.LoadoutStore().all()),
        ("echo_profile", _echo.EchoProfile, _ps.all()),
        ("task", _tasks.TaskFlow, _tasks.TaskStore().all()),
    ):
        if not items:
            ok(f"core_{label}_field_symmetry", True, "（无数据）")
            continue
        recognized = _recognized_keys(cls)
        dumped = set(items[0].to_dict())
        lost = sorted(dumped - recognized - {"id"})
        ok(f"core_{label}_field_symmetry", not lost,
           "to_dict 的 key 全被 from_dict 认" if not lost
           else f"❌ 会丢: {lost}")

    # ══════════════════════════════════════════════════════════════
    # 8) ★ 桥接层已经做了 camelCase → snake_case 映射
    # ══════════════════════════════════════════════════════════════
    ok("bridge_normalizes_camelCase",
       "_normalize_loadout_payload" in bridge_src,
       "web_bridge 有 _normalize_loadout_payload（驼峰→下划线）")
    ok("normalize_covers_echoSet",
       '"echoSet"' in bridge_src and '"echo_set"' in bridge_src,
       "echoSet → echo_set 已覆盖")
    ok("normalize_covers_updatedAt",
       '"updatedAt"' in bridge_src,
       "updatedAt → updated_at 已覆盖")

    return finish()


def finish() -> int:
    print()
    print("=" * 70)
    print("结果：" + ("全部通过" if not FAILS else "失败 " + str(FAILS)))
    print("=" * 70)
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
