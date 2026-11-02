# -*- coding: utf-8 -*-
"""验收 P7：`getGachaOverview()`（欧皇卡 6 个数字）+ `prerequisites` 死代码清理。

## 背景

lead 的截图 `p6-gacha.png` 里，欧皇卡 6 个格子**全是横线 `—`**：

```text
—          —          —
总抽卡数    平均出金     小保底不歪
—          —          —
五星数      每UP角色需   每UP武器需
```

但旧界面截图里是真实数据：`1131 / 47 / 66.7% / 24 / 71.8 / 63.3`。

**根因**：`getGachaHistory()` 只给历史快照（每月多少抽），
欧皇卡要的 6 个统计字段它一个都没有。

## 验什么

1. **6 个数字和旧界面截图逐个对上**（这是最硬的判据）
2. 算法来自 `GachaReport`，不是自己算的
3. `null` 和 `0` 区分（没抽过限定池 ≠ 每次都歪）
4. `prerequisites` 在前端彻底没了（`_panels.js` 函数 + 导出 + DOM）

## ⚠ 只读，不写用户数据

`getGachaOverview` 是纯读（`store.load()`），不调 `load_and_repair`。
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


#: ★ 旧界面截图里的真值（lead 提供）
#:
#: 这是**唯一**能证明"算法对齐"的判据 —— 自己算完和旧界面对不上就没意义。
_OLD_UI_TRUTH = {
    "total": 1131,        # 总抽卡数
    "avgFive": 47,        # 平均出金（旧界面 .0f 显示 47）
    "noLoseRate": 66.7,   # 小保底不歪
    "five": 24,           # 五星数
    "perChar": 71.8,      # 每UP角色需
    "perWeapon": 63.3,    # 每UP武器需
    "rank": "欧皇",
}


def main() -> int:
    b = WebBridge()

    # ══════════════════════════════════════════════════════════════
    # 1) ★★★ 6 个数字必须和旧界面截图对上
    # ══════════════════════════════════════════════════════════════
    r = json.loads(b.getGachaOverview())
    print(f"[INFO] recordCount={r.get('recordCount')} "
          f"playerId={r.get('playerId')!r} "
          f"accountLabel={r.get('accountLabel')!r}")

    if not r.get("ok"):
        ok("overview_ok", False,
           f"reason={r.get('reason')} message={r.get('message')}")
        return finish()

    ok("overview_ok", True,
       f"total={r.get('total')} five={r.get('five')}")

    #: 整数类字段
    for field in ("total", "five"):
        want = _OLD_UI_TRUTH[field]
        ok(f"overview_{field}_matches_old_ui", r.get(field) == want,
           f"{field} = {r.get(field)!r}（旧界面截图 = {want}）")

    #: 小数类字段（容差 0.1）
    for field in ("avgFive", "noLoseRate", "perChar", "perWeapon"):
        want = _OLD_UI_TRUTH[field]
        got = r.get(field)
        near = got is not None and abs(float(got) - want) <= 0.15
        ok(f"overview_{field}_matches_old_ui", near,
           f"{field} = {got!r}（旧界面截图 = {want}）")

    ok("overview_rank_matches_old_ui",
       r.get("rank") == _OLD_UI_TRUTH["rank"],
       f"rank = {r.get('rank')!r}（旧界面截图 = {_OLD_UI_TRUTH['rank']!r}）")

    # ══════════════════════════════════════════════════════════════
    # 2) 算法必须来自 GachaReport（不是自己算的）
    # ══════════════════════════════════════════════════════════════
    from src.core import gacha

    report, who, rows = b._gacha_report()

    ok("overview_uses_report_total",
       r["total"] == report.total,
       f"{r['total']} == report.total {report.total}")
    ok("overview_uses_report_five",
       r["five"] == report.five_count,
       f"{r['five']} == report.five_count {report.five_count}")

    #: avgFive 的口径：旧界面是 f"{average:.0f}"（取整显示），
    #: 我们给的是 round(average,1)（页面自己取整）
    ok("overview_avg_matches_report_average",
       abs(float(r["avgFive"]) - report.average()) <= 0.1,
       f"{r['avgFive']} ≈ report.average() {report.average():.2f}"
       f"（旧界面显示 f'{report.average():.0f}'）")

    ok("overview_nolose_matches_report",
       abs(float(r["noLoseRate"]) - report.not_up_rate()) <= 0.1,
       f"{r['noLoseRate']} ≈ report.not_up_rate() "
       f"{report.not_up_rate():.2f}")

    ok("overview_perchar_matches_report",
       abs(float(r["perChar"])
           - report.average_per_up("角色")) <= 0.1,
       f"{r['perChar']} ≈ report.average_per_up('角色') "
       f"{report.average_per_up('角色'):.2f}")

    ok("overview_perweapon_matches_report",
       abs(float(r["perWeapon"])
           - report.average_per_up("武器")) <= 0.1,
       f"{r['perWeapon']} ≈ report.average_per_up('武器') "
       f"{report.average_per_up('武器'):.2f}")

    ok("overview_rank_matches_report_luck",
       r["rank"] == report.luck()[0],
       f"{r['rank']!r} == report.luck()[0] {report.luck()[0]!r}")

    # ══════════════════════════════════════════════════════════════
    # 3) ★ null vs 0 —— 没抽过限定池 ≠ 每次都歪
    # ══════════════════════════════════════════════════════════════
    #: 旧界面：not_up_rate() 返回 None 时显示 "—"，不是 "0.0%"
    #: 我们给的 noLoseRate 也必须是 None 而不是 0
    if report.not_up_rate() is None:
        ok("overview_nolose_is_none_not_zero",
           r["noLoseRate"] is None,
           "没抽过限定池 → null（旧界面显示 —）")
    else:
        ok("overview_nolose_is_float",
           isinstance(r["noLoseRate"], (int, float)),
           f"有数据 → {r['noLoseRate']}（数字）")

    #: 同理 perChar / perWeapon
    for field, kind in (("perChar", "角色"), ("perWeapon", "武器")):
        want_none = report.average_per_up(kind) is None
        got_none = r[field] is None
        ok(f"overview_{field}_null_semantics", want_none == got_none,
           f"report 是 None={want_none} / 接口是 None={got_none}")

    # ══════════════════════════════════════════════════════════════
    # 4) summary（旧界面那句「共获得限定五星 N 个，常驻五星 M 个」）
    # ══════════════════════════════════════════════════════════════
    summary = r.get("summary") or {}
    ok("overview_summary_limited",
       summary.get("limited") == len(report.limited_fives()),
       f"limited={summary.get('limited')}"
       f"（report.limited_fives()={len(report.limited_fives())}）")
    ok("overview_summary_standard",
       summary.get("standard") == len(report.permanent_fives()),
       f"standard={summary.get('standard')}")
    ok("overview_summary_names_is_list",
       isinstance(summary.get("standardNames"), list),
       f"standardNames={summary.get('standardNames')}")
    ok("overview_summary_note",
       "限定五星" in str(summary.get("note"))
       and "常驻五星" in str(summary.get("note")),
       f"note={str(summary.get('note'))[:70]!r}（旧界面原句）")

    #: ★ 限定 + 常驻 **不**等于五星数 —— 口径是「只算角色，不算武器」。
    #:
    #: 旧代码 ``limited_fives`` 的文档写得很清楚：
    #:
    #:     只算角色，不算武器。反推验证（用户截图）：44 + 19 = 63 = 五星数
    #:
    #: 那个等式成立是因为**用户那个号全是角色**。本机 12 张卡里含武器，
    #: 所以 4 + 5 = 9 ≠ 24 是**正确**的（24 - 9 = 15 是武器 + 重复角色）。
    #:
    #: ⚠ 所以我第一版这条断言写错了 —— 不是代码错，是我把特例当成了通则。
    role_cards = [c for c in (r.get("cards") or []) if c.get("kind") == "角色"]
    role_five_count = sum(c["count"] for c in role_cards)
    ok("overview_summary_counts_roles_only",
       summary.get("limited", 0) + summary.get("standard", 0)
       <= r.get("five"),
       f"限定 {summary.get('limited')} + 常驻 {summary.get('standard')} "
       f"= {summary.get('limited', 0) + summary.get('standard', 0)}"
       f" ≤ 五星 {r.get('five')}（只算角色，武器不算 —— 旧代码口径）")
    ok("overview_summary_matches_role_cards",
       summary.get("limited", 0) + summary.get("standard", 0)
       == len({c["name"] for c in role_cards}),
       f"限定+常驻 = "
       f"{summary.get('limited', 0) + summary.get('standard', 0)}"
       f" 个**不同角色名**，卡片墙里角色名去重 = "
       f"{len({c['name'] for c in role_cards})}"
       f"（{role_five_count} 抽都是角色）")

    # ══════════════════════════════════════════════════════════════
    # 5) 卡片墙（旧界面 _render_cards）
    # ══════════════════════════════════════════════════════════════
    cards = r.get("cards") or []
    ok("overview_cards_nonempty", len(cards) > 0,
       f"{len(cards)} 张五星卡片")
    if cards:
        c0 = cards[0]
        ok("overview_card_fields",
           all(k in c0 for k in ("name", "count", "kind", "avatarUrl",
                                 "isLimited")),
           f"字段 = {sorted(c0.keys())}")
        #: 卡片必须按次数倒序（旧界面 sorted(counts.items(), key=-count)）
        counts = [c["count"] for c in cards]
        ok("overview_cards_sorted_desc", counts == sorted(counts, reverse=True),
           f"counts = {counts}")
        #: 可点击的有限定标记
        ok("overview_cards_have_limited_flag",
           all(isinstance(c.get("isLimited"), bool) for c in cards),
           "每张卡都有 isLimited（旧界面区分限定/常驻）")

    # ══════════════════════════════════════════════════════════════
    # 6) 分卡池（旧界面 _build_pool_tabs）
    # ══════════════════════════════════════════════════════════════
    pools = r.get("pools") or []
    active = report.active_pools()
    ok("overview_pools_count", len(pools) == len(active),
       f"{len(pools)} 个池（旧界面只显示抽过的 = {len(active)}）")
    if pools:
        p0 = pools[0]
        ok("overview_pool_fields",
           all(k in p0 for k in ("poolType", "name", "pulls", "five",
                                 "rate", "avgFive", "rank")),
           f"字段 = {sorted(p0.keys())}")
        #: 所有池的抽数加起来 == 总抽数
        ok("overview_pools_sum_to_total",
           sum(p["pulls"] for p in pools) == r["total"],
           f"sum(pulls)={sum(p['pulls'] for p in pools)} == total {r['total']}")
        ok("overview_pools_sum_fives",
           sum(p["five"] for p in pools) == r["five"],
           f"sum(five)={sum(p['five'] for p in pools)} == five {r['five']}")

    # ══════════════════════════════════════════════════════════════
    # 7) ★ prerequisites 死代码清理
    # ══════════════════════════════════════════════════════════════
    js_dir = os.path.join(_ROOT, "src", "gui", "web", "js")
    hits: list[str] = []
    for dirpath, _dirs, files in os.walk(js_dir):
        for name in files:
            if not name.endswith(".js"):
                continue
            path = os.path.join(dirpath, name)
            try:
                text = open(path, encoding="utf-8").read()
            except OSError:
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                if "prerequisites" in line:
                    hits.append(f"{name}:{lineno}  {line.strip()[:70]}")
    ok("js_no_prerequisites_reference", not hits,
       "残留：\n    " + "\n    ".join(hits) if hits
       else "所有 .js 里 0 处引用")

    #: 后端也不该再有
    import src.core.web_bridge as WB

    ok("backend_no_prerequisites_symbols",
       not [n for n in ("_TOOL_PREREQUISITES", "_prerequisites_for",
                        "_COMMON_GAME_PREREQUISITES")
            if hasattr(WB, n)],
       "后端 3 个符号已删")

    return finish()


def finish() -> int:
    print()
    print("=" * 70)
    print("结果：" + ("全部通过" if not FAILS else "失败 " + str(FAILS)))
    print("=" * 70)
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
