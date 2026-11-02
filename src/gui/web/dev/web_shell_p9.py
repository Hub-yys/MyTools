# -*- coding: utf-8 -*-
"""验收 P9：配置页「新增/编辑」弹框的角色下拉。

## 背景

用户点配置页「新增」**没反应**（lead 实测 `modal: 0`）。

旧界面弹框（``src/gui/loadout_dialog.py``）的核心是 ``FilterComboBox`` ——
**可输入、按内容过滤的角色下拉**，外加头像联动。

## 数据源（照抄，不发明）

``loadout_dialog.py`` L205-206：

.. code:: python

    self.character_combo.set_choices(
        [(c.name, avatar_icon(c.avatar, c.name)) for c in CHARACTERS])

``CHARACTERS`` = :mod:`src.core.game_data` 的模块级清单（61 个，已按
「实装版本倒序」排好 —— 用户 2026-10-24 要求「新角色降序，不算复刻」）。

## 「一个角色只能一条配置」（用户 2026-09-26）

旧界面**两层**校验：
1. UI 层：从下拉剔掉已占用的
2. 校验层：``character_choice_error`` 再校一次

为什么两层：下拉**可输入**，用户能直接打字。

⚠ Web 版**必须**有后端那层 —— 前端可以被绕过。

## 验什么

1. `getCharacterOptions()` 61 个角色、顺序 = `CHARACTERS`、带头像/拼音
2. `taken` 标记正确，且 `kind` 决定从哪类配置算（两类独立）
3. `getConfigList().takenCharacters` 和 `getCharacterOptions` 的 taken **一致**
4. ★ **后端真的拦住**重复角色 / 不存在的角色 / 空角色
5. 编辑自己**不被**误判成占用

## ⚠ 用户数据保护

会写 ``loadouts.json``（测正常新增），用 ``backup_guard``。
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

#: ★ 起 HTTP 服务 —— 否则 avatarUrl 全是空串（环境问题，不是 bug）
from src.gui.web_shell import web_base_url  # noqa: E402

web_base_url()

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


def _run() -> int:
    b = WebBridge()

    # ══════════════════════════════════════════════════════════════
    # 1) 数据源 = game_data.CHARACTERS（照抄旧界面）
    # ══════════════════════════════════════════════════════════════
    from src.core import game_data

    game_data.ensure_loaded()
    real = list(game_data.CHARACTERS)

    r = json.loads(b.getCharacterOptions("loadout"))
    ok("char_options_ok", r.get("ok") is True,
       f"total={r.get('total')} taken={r.get('takenCount')} "
       f"avail={r.get('availableCount')}")

    items = r.get("items") or []
    ok("char_options_count_matches_CHARACTERS",
       len(items) == len(real),
       f"{len(items)} 个 == game_data.CHARACTERS 的 {len(real)} 个")

    #: ★ 顺序必须和 CHARACTERS 一致（那里已按实装版本倒序排好，
    #:   用户 2026-10-24 明确要求过 —— 不要自己重排）
    ok("char_options_order_matches",
       [x["name"] for x in items] == [c.name for c in real],
       f"前 3 个 = {[x['name'] for x in items[:3]]}"
       f"（和 CHARACTERS 同序 = "
       f"{[x['name'] for x in items] == [c.name for c in real]}）")

    # ══════════════════════════════════════════════════════════════
    # 2) 每项字段
    # ══════════════════════════════════════════════════════════════
    if items:
        it = items[0]
        ok("char_item_fields",
           all(k in it for k in ("name", "avatarUrl", "avatarHue",
                                 "initial", "taken", "pinyin")),
           f"字段 = {sorted(it.keys())}")

        #: 头像两级兜底（和配置页一致）
        ok("char_item_has_initial",
           isinstance(it.get("initial"), dict)
           and bool(it["initial"].get("initial")),
           f"initial = {json.dumps(it.get('initial'), ensure_ascii=False)[:70]}")

        #: 拼音索引（下拉可输入过滤用 —— 和配置页搜索同一套规则）
        ok("char_item_has_pinyin",
           isinstance(it.get("pinyin"), list) and len(it["pinyin"]) == 2,
           f"pinyin = {it.get('pinyin')}")

        #: taken 必须是 bool
        ok("char_item_taken_is_bool",
           all(isinstance(x.get("taken"), bool) for x in items),
           "每项 taken 都是 bool")

        #: 库街区属性（页面分组/筛选可能用）
        ok("char_item_has_element_weapon",
           "element" in it and "weapon" in it,
           f"element={it.get('element')!r} weapon={it.get('weapon')!r}")

    # ══════════════════════════════════════════════════════════════
    # 3) ★ taken 的语义：kind 决定从哪类配置算
    # ══════════════════════════════════════════════════════════════
    cfg = json.loads(b.getConfigList())
    loadouts = cfg.get("loadouts") or []
    profiles = cfg.get("echoProfiles") or []

    loadout_chars = {x["character"] for x in loadouts if x.get("character")}
    profile_chars = {x["name"] for x in profiles if x.get("name")}

    opt_loadout = json.loads(b.getCharacterOptions("loadout"))
    taken_loadout = {x["name"] for x in (opt_loadout["items"] or [])
                     if x["taken"]}
    ok("taken_loadout_matches_loadout_store",
       taken_loadout == loadout_chars,
       f"loadout taken = {sorted(taken_loadout)}"
       f"（现有 {len(loadout_chars)} 条声骸配置）")

    opt_profile = json.loads(b.getCharacterOptions("echo_profile"))
    taken_profile = {x["name"] for x in (opt_profile["items"] or [])
                     if x["taken"]}
    ok("taken_profile_matches_profile_store",
       taken_profile == profile_chars,
       f"echo_profile taken = {sorted(taken_profile)}"
       f"（现有 {len(profile_chars)} 条战斗配置）")

    #: ★★ 两类**各自独立** —— 一个角色可以同时有两种配置
    #: （用户 2026-09-26 明确："两类配置是无关的"）
    opt_all = json.loads(b.getCharacterOptions(""))
    taken_all = {x["name"] for x in (opt_all["items"] or []) if x["taken"]}
    ok("taken_empty_kind_unions_both",
       taken_all == (loadout_chars | profile_chars),
       f"不给 kind → 两类并集 = {sorted(taken_all)}")

    # ══════════════════════════════════════════════════════════════
    # 4) getConfigList().takenCharacters 必须和 getCharacterOptions 一致
    # ══════════════════════════════════════════════════════════════
    tc = cfg.get("takenCharacters") or {}
    ok("configlist_has_takenCharacters",
       isinstance(tc, dict) and "loadout" in tc and "echo_profile" in tc,
       f"keys = {sorted(tc.keys())}")
    ok("takenCharacters_loadout_consistent",
       sorted(tc.get("loadout") or []) == sorted(taken_loadout),
       f"getConfigList={sorted(tc.get('loadout') or [])}")
    ok("takenCharacters_profile_consistent",
       sorted(tc.get("echo_profile") or []) == sorted(taken_profile),
       f"getConfigList={sorted(tc.get('echo_profile') or [])}")

    # ══════════════════════════════════════════════════════════════
    # 5) ★★★ 后端真的拦住（这是 Web 版必须自己有的那层）
    # ══════════════════════════════════════════════════════════════
    existing = sorted(loadout_chars)[0] if loadout_chars else ""

    #: ① 重复角色
    r = json.loads(b.setConfig(json.dumps({
        "kind": "loadout",
        "data": {"character": existing, "echo_set": "轻云出月"},
    })))
    ok("backend_rejects_duplicate_character",
       r.get("ok") is False and r.get("reason") == "bad_character",
       f"「{existing}」→ {r.get('reason')}: {str(r.get('message'))[:50]}")
    ok("backend_duplicate_message_is_readable",
       "已经有一条配置" in str(r.get("message")),
       f"message = {str(r.get('message'))[:70]!r}"
       f"（旧界面原话「一个角色只能有一条」）")

    #: ② 不存在的角色（自由输入 —— 下拉是可输入的，用户真会这么干）
    r = json.loads(b.setConfig(json.dumps({
        "kind": "loadout",
        "data": {"character": "绯雪声骸强化配置", "echo_set": "轻云出月"},
    })))
    ok("backend_rejects_unknown_character",
       r.get("ok") is False and r.get("reason") == "bad_character",
       f"→ {str(r.get('message'))[:70]}")
    ok("backend_unknown_message_mentions_list",
       "不是一个角色" in str(r.get("message")),
       "message 告诉用户「请从列表里选」")

    #: ③ 空角色
    r = json.loads(b.setConfig(json.dumps({
        "kind": "loadout",
        "data": {"character": "", "echo_set": "轻云出月"},
    })))
    ok("backend_rejects_empty_character",
       r.get("ok") is False and r.get("reason") == "bad_character",
       f"→ {str(r.get('message'))[:50]}")

    #: ④ 正常新角色 → 放行
    free = next((x["name"] for x in (opt_loadout["items"] or [])
                 if not x["taken"]), "")
    if free:
        r = json.loads(b.setConfig(json.dumps({
            "kind": "loadout",
            "data": {"character": free, "echo_set": "轻云出月"},
        })))
        ok("backend_allows_free_character", r.get("ok") is True,
           f"「{free}」→ ok={r.get('ok')} id={r.get('id')}")
        if r.get("ok"):
            d = json.loads(b.deleteConfig("loadout", r["id"]))
            ok("backend_cleanup_new_loadout", d.get("ok") is True,
               f"已删 {r.get('id')}")

    #: ⑤ ★ 编辑自己**不该**被判成"已占用"
    if loadouts:
        target = loadouts[0]
        r = json.loads(b.setConfig(json.dumps({
            "kind": "loadout",
            "id": target["id"],
            "data": {
                "character": target["character"],
                "echo_set": target.get("echoSet") or "轻云出月",
                "status": target.get("status") or "",
                "qualities": target.get("qualities") or [],
                "picks": target.get("picks") or {},
            },
        })))
        ok("backend_allows_editing_self", r.get("ok") is True,
           f"编辑「{target['character']}」自己 → ok={r.get('ok')}"
           f"（exclude_id 生效）")

    #: ⑥ echo_profile 编辑自己也要放行
    if profiles:
        p = profiles[0]
        r = json.loads(b.setConfig(json.dumps({
            "kind": "echo_profile", "id": p["name"],
            "data": {"name": p["name"], "settings": p.get("settings") or {}},
        })))
        ok("backend_allows_editing_self_echo_profile",
           r.get("ok") is True,
           f"编辑战斗配置「{p['name']}」自己 → ok={r.get('ok')}")

    # ══════════════════════════════════════════════════════════════
    # 6) excludeId 的透传（页面修改模式要知道"除了我之外谁被占了"）
    # ══════════════════════════════════════════════════════════════
    if loadouts:
        target = loadouts[0]
        r2 = json.loads(b.getCharacterOptions(
            f"loadout|{target['id']}"))
        taken2 = {x["name"] for x in (r2["items"] or []) if x["taken"]}
        ok("excludeId_frees_that_character",
           target["character"] not in taken2,
           f"排除 {target['id']} 后，「{target['character']}」"
           f"不在 taken 里 = {target['character'] not in taken2}")
        ok("excludeId_keeps_others_taken",
           len(taken2) == len(taken_loadout) - 1,
           f"taken 从 {len(taken_loadout)} 减到 {len(taken2)}")

    print()
    print("=" * 70)
    print("结果：" + ("全部通过" if not FAILS else "失败 " + str(FAILS)))
    print("=" * 70)
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
