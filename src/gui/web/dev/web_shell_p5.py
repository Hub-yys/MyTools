# -*- coding: utf-8 -*-
"""验收 P5：① 侧栏顺序+分组 / ③ 头像兜底 / ⑤ 抽卡历史。

## 用户反馈（原话）

> 1. 图1 工具与原来不一样
> 3. 图三的角色图片呢（配置页头像全是灰圈）
> 5. 图5 我的抽卡分析记录呢

**核心诉求：「请不要擅自修改原先的布局内容」** —— 这是**恢复原样**，
不是重新设计。

## 验什么

**① getNav()** —— 顺序必须和 `main_window.py` 的 `addSubInterface` 逐项一致，
且带「工具」分组（`group:true` / `selectable:false` / `children`）

**③ 头像** —— 两级兜底：
1. `avatarUrl`（文件真在才给）
2. `initial` / `avatarHue`（照抄 `pickers._initial_icon` 的 crc32 散列）

**⑤ 抽卡历史** —— 用旧界面的 `group_by_account_month()` 聚合

## ⚠ 不破坏用户数据

`clearGachaHistory` 会清空历史 —— **本脚本只读，不调它**。
（它的验证用「清空后恢复」的方式，见单独的 data_guard 思路）
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

#: ★ 起 HTTP 服务 —— 否则 avatarUrl 全是空串（那是环境问题不是 bug）
from src.gui.web_shell import web_base_url  # noqa: E402

web_base_url()

from src.core.web_bridge import (  # noqa: E402
    WebBridge, _hsv_to_hex, _initial_avatar, _initial_avatar_hue,
)

FAILS: list[str] = []


def ok(tag: str, cond: bool, note: str = "") -> None:
    print(f"[{'PASS' if cond else 'FAIL'}] {tag}  {note}")
    if not cond:
        FAILS.append(tag)


#: 复现 ``nav_reorder.apply_order`` + ``main_window`` 的真实算法 ——
#: **独立实现一遍**，不调被测函数（否则就是自己验证自己）。
#:
#: 算法（源码实证）：
#:   1. ``movable_keys=[CONFIG,TASKS,TOOL_GROUP,LIBRARY]``、``fixed_keys=[HOME]``
#:   2. ``apply_order(saved)`` 把**顶级项**按 saved 重排，
#:      **没提到的项保持原相对顺序、追加到最后**（L91-98）
#:   3. ``nav_order`` 实测只有 7 项（缺 ``NoticeInterface``）→ 消息在末尾
_ROUTE_TO_KEY = {
    "HomeInterface": "home",
    "ConfigInterface": "config",
    "TasksInterface": "tasks",
    "SkinInterface": "skin",
    "UpdateInterface": "update",
    "NoticeInterface": "notice",
    "WuwaLibraryInterface": "library",
    "tool_group": "tool_group",
}
_DEFAULT_ORDER = ["home", "config", "tasks", "skin", "update",
                  "notice", "tool_group", "library"]


def _expected_nav_keys() -> list[str]:
    """按旧界面的真实链路算出侧栏顺序。

    ★ 数据源是 ``ui_state.json`` 的 ``nav_order``（用户拖过的结果），
    **不是**代码里的 ``addSubInterface`` 默认顺序。
    """
    from src.core.ui_state import UiState

    saved = [s for s in UiState().get_list("nav_order")]
    keys = [_ROUTE_TO_KEY[r] for r in saved if r in _ROUTE_TO_KEY]
    #: apply_order：没提到的项追加到末尾
    keys += [k for k in _DEFAULT_ORDER if k not in keys]
    #: 主页固定最上
    keys.sort(key=lambda k: 0 if k == "home" else 1)
    return keys


def main() -> int:
    b = WebBridge()

    # ══════════════════════════════════════════════════════════════
    # ① 侧栏顺序 + 分组
    # ══════════════════════════════════════════════════════════════
    nav = json.loads(b.getNav())
    keys = [n["key"] for n in nav]

    #: ★★★ 顺序必须来自**用户自己的拖拽结果**（``ui_state.json`` 的
    #: ``nav_order``），**不是**代码里的 ``addSubInterface`` 默认顺序。
    #:
    #: 2026-11-02 第二次修正：第一版照抄了 ``main_window.py`` 的代码默认
    #: 顺序（主页→配置→任务→…→工具→资源库），但用户把「工具」拖到了
    #: **第 2 位** —— 那才是他实际看到的。
    expected = _expected_nav_keys()
    ok("nav_order_matches_ui_state", keys == expected,
       f"实际 = {keys}\n      期望（读 ui_state）= {expected}")

    #: 用户第一张图指的就是「工具」的位置
    ok("nav_tool_group_second",
       keys.index("tool_group") == 1,
       f"工具分组在第 {keys.index('tool_group') + 1} 位"
       f"（用户拖到了第 2 位）")

    ok("nav_config_before_tasks",
       keys.index("config") < keys.index("tasks"),
       f"配置在第 {keys.index('config') + 1} 位、任务在第 "
       f"{keys.index('tasks') + 1} 位")

    #: ★ ``NoticeInterface`` 不在 ``nav_order`` 里，而 ``apply_order`` 的
    #: 规则是「没提到的项保持原相对顺序、追加到最后」→ 消息通知永远在末尾
    ok("nav_notice_last",
       keys[-1] == "notice",
       f"最后一项 = {keys[-1]!r}"
       f"（NoticeInterface 不在 nav_order 里 → 追加到末尾）")

    #: 每项都要有 kind / selectable
    missing_fields = [
        n["key"] for n in nav
        if "kind" not in n or "selectable" not in n
    ]
    ok("nav_all_have_kind", not missing_fields,
       f"缺字段 = {missing_fields}" if missing_fields
       else f"{len(nav)} 项都有 kind / selectable")

    #: ★ 分组项的四个语义
    group = next((n for n in nav if n.get("group")), None)
    ok("nav_has_group", group is not None,
       f"分组 = {group.get('name') if group else None}")
    if group:
        ok("nav_group_key", group["key"] == "tool_group",
           f"key={group['key']!r}（旧界面 TOOL_GROUP_KEY 就是 tool_group）")
        ok("nav_group_not_selectable", group["selectable"] is False,
           f"selectable={group['selectable']}（点它只展开，不切页面）")
        ok("nav_group_has_tooltip", bool(group.get("tooltip")),
           f"tooltip={group.get('tooltip')!r}")
        children = group.get("children") or []
        ok("nav_group_children_count", len(children) == 7,
           f"{len(children)} 个子项（7 个工具）")
        if children:
            ok("nav_child_key_format",
               all(c["key"].startswith("tool:") for c in children),
               f"子项 key 样例 = {children[0]['key']!r}"
               f"（必须 tool:<工具key>，和 App.go 路由一致）")
            ok("nav_child_has_name",
               all(c.get("name") for c in children),
               f"样例 = {children[0]['name']!r}")

        #: 子项顺序要和 ToolRegistry 一致
        from src.core.registry import ToolRegistry

        want = [f"tool:{m.key}" for m in ToolRegistry.all_metas()]
        got = [c["key"] for c in children]
        ok("nav_children_match_registry", got == want,
           f"子项顺序 = {got}")

    #: 普通页面项的 selectable 都是 True
    pages = [n for n in nav if n.get("kind") == "page"]
    ok("nav_pages_selectable",
       all(n["selectable"] is True for n in pages),
       f"{len(pages)} 个页面项全部可选")

    # ══════════════════════════════════════════════════════════════
    # ③ 头像两级兜底
    # ══════════════════════════════════════════════════════════════
    #: ① 散列稳定：同名两次必须同色
    ok("hue_deterministic",
       _initial_avatar_hue("绯雪") == _initial_avatar_hue("绯雪"),
       f"绯雪 → {_initial_avatar_hue('绯雪')}（两次一致）")

    #: ② 不同名尽量不同色
    hues = {_initial_avatar_hue(n) for n in
            ("心", "绯雪", "赞妮", "卡提希娅", "爱弥斯")}
    ok("hue_distinct", len(hues) == 5,
       f"5 个角色 {len(hues)} 种色相：{sorted(hues)}")

    #: ③ 和旧界面 **逐位一致**：crc32 % 360
    import zlib

    for name in ("心", "绯雪", "秧秧·玄翎"):
        want = zlib.crc32(name.encode("utf-8")) % 360
        ok(f"hue_matches_old_{name[:2]}",
           _initial_avatar_hue(name) == want,
           f"{name} → {_initial_avatar_hue(name)}（旧界面 crc32%360 = {want}）")

    #: ④ 首字数据完整
    init = _initial_avatar("绯雪")
    ok("initial_fields",
       all(k in init for k in ("name", "initial", "hue", "color", "textColor")),
       f"keys = {sorted(init.keys())}")
    ok("initial_is_first_char", init.get("initial") == "绯",
       f"首字 = {init.get('initial')!r}（旧界面 text[0]）")

    #: ⑤ 颜色是合法 hex
    color = init.get("color") or ""
    ok("initial_color_hex",
       len(color) == 7 and color.startswith("#"),
       f"color = {color!r}")

    #: ⑥ HSV 换算正确（hue=0,s=90,v=200 → 偏红）
    red = _hsv_to_hex(0, 90, 200)
    ok("hsv_hue0_is_reddish",
       red.startswith("#C8") or int(red[1:3], 16) > 150,
       f"hue=0 → {red}（旧界面 QColor.fromHsv(0,90,200)）")

    # ══════════════════════════════════════════════════════════════
    # ③ getConfigList 两组都要有头像字段
    # ══════════════════════════════════════════════════════════════
    cfg = json.loads(b.getConfigList())
    loads = cfg.get("loadouts") or []
    profiles = cfg.get("echoProfiles") or []

    ok("config_has_both_groups", bool(loads) and bool(profiles),
       f"{len(loads)} 条声骸配置 / {len(profiles)} 条战斗配置")

    for group_name, items in (("loadout", loads), ("echoProfile", profiles)):
        if not items:
            continue
        first = items[0]
        ok(f"{group_name}_has_initial",
           isinstance(first.get("initial"), dict)
           and bool(first["initial"].get("initial")),
           f"initial = {json.dumps(first.get('initial'), ensure_ascii=False)[:90]}")
        ok(f"{group_name}_has_hue",
           isinstance(first.get("avatarHue"), int),
           f"avatarHue = {first.get('avatarHue')}")
        ok(f"{group_name}_has_avatarUrl_field",
           "avatarUrl" in first,
           f"avatarUrl = {str(first.get('avatarUrl'))[:70]!r}")

    #: ★★ 关键：echoProfiles 之前**完全没有**头像字段（用户看到灰圈）
    if profiles:
        all_have = all(isinstance(p.get("initial"), dict)
                       and p["initial"].get("initial") for p in profiles)
        ok("echoProfiles_all_have_initial", all_have,
           f"{len(profiles)} 条全部有首字兜底（这就是灰圈的修复）")

        #: avatar 相对路径按约定推导（EchoProfile 本身没有 avatar 字段）
        p0 = profiles[0]
        ok("echoProfile_avatar_path_convention",
           p0.get("avatar", "") == f"avatars/{p0['name']}.png",
           f"avatar = {p0.get('avatar')!r}"
           f"（EchoProfile 没 avatar 字段，按约定推导）")

        #: 真实头像文件在 → 必须有 URL
        from src.core import paths

        name = p0["name"]
        exists = (paths.resource_dir("assets", "game", "avatars")
                  / f"{name}.png").is_file()
        url = p0.get("avatarUrl") or ""
        ok("echoProfile_url_matches_file_existence",
           (bool(url) == exists),
           f"{name}.png 存在={exists}，avatarUrl {'有' if url else '空'}"
           f"（**一致**才对：有文件才给 URL）")

    # ══════════════════════════════════════════════════════════════
    # ⑤ 抽卡历史
    # ══════════════════════════════════════════════════════════════
    hist = json.loads(b.getGachaHistory())
    ok("history_ok", hist.get("ok") is True,
       f"count={hist.get('count')} snapshots={hist.get('snapshotCount')}")

    items = hist.get("items") or []
    if items:
        it = items[0]
        ok("history_item_fields",
           all(k in it for k in ("playerId", "yearMonth", "monthText",
                                 "total", "five", "latestAt")),
           f"字段 = {sorted(it.keys())}")

        #: ★ 月份格式必须是「xxxx年xx月」（用户 2026-10-28 明确要求）
        ok("history_month_format",
           "年" in it["monthText"] and "月" in it["monthText"],
           f"monthText = {it['monthText']!r}（用户要 xxxx年xx月）")

        #: 累计值必须是 max 而不是 sum（同一账号同月多条快照时）
        ok("history_total_is_int", isinstance(it["total"], int),
           f"total = {it['total']}")

        #: 按账号分组：同账号的月份要挨着
        players_seq = []
        for x in items:
            if not players_seq or players_seq[-1] != x["playerId"]:
                players_seq.append(x["playerId"])
        ok("history_grouped_by_account",
           len(players_seq) == len(set(players_seq)),
           f"账号出现顺序 = {players_seq}（同一账号不该被打断）")

        #: 账号列表去重
        ok("history_players_deduped",
           len(hist.get("players") or []) == len(set(hist.get("players") or [])),
           f"players = {hist.get('players')}")

        #: ★ 和旧界面 module 直接对比（证明是复用不是重写）
        from src.core import gacha_store
        from src.core.gacha_history_view import group_by_account_month

        want = group_by_account_month(
            gacha_store.GachaHistoryStore().load().snapshots)
        ok("history_matches_old_module",
           len(want) == len(items)
           and [m.month_text for m in want] == [x["monthText"] for x in items],
           f"旧模块 {len(want)} 组 / 接口 {len(items)} 组，月份序列一致")
    else:
        ok("history_empty_ok", True, "本机没有抽卡历史（接口正确返回空）")

    #: 破坏性方法存在但**不调**
    ok("clear_history_exists", hasattr(b, "clearGachaHistory"),
       "clearGachaHistory 已实现（本脚本不调用 —— 会清用户数据）")

    print()
    print("=" * 70)
    print("结果：" + ("全部通过" if not FAILS else "失败 " + str(FAILS)))
    print("=" * 70)
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
