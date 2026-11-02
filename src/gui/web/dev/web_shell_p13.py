# -*- coding: utf-8 -*-
"""验收 P13：`getGachaPoolDetail()` —— 抽卡页的逐条出金列表。

## 背景（用户 2026-09-30 原话）

> **差在逐条抽数条列表**

旧界面每个卡池下面是：

```text
[头像] ████████████ 68抽          (歪)
[头像] ██████ 33抽
[头像] ███████████████ 81抽        (歪)
```

条长按 ``span`` 走、颜色按欧非分级（绿→黄→红）。

## 验什么

1. **顺序：最新在最上面**（旧界面 ``reversed(fives_analysis())``）
2. ``span`` 是"这一金花了几抽"，**不是** ``cumulative``
3. 条颜色 = ``gacha.span_color`` 的分档（40/60/73/80）
4. 评价 = 旧界面 ``_verdict`` 的规则（歪 / ≤60欧 / ≥74非 / 中间空）
5. 4 个池、条数加起来 == 总五星数

## 顺带验两件 lead 问的事

* ``_fmt_number`` 的行为（去掉末尾 0，整数保留一位小数）
* 分级分界点（SPAN_COLORS + _verdict 两套阈值）
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

from src.gui.web_shell import web_base_url  # noqa: E402

web_base_url()

from src.core.web_bridge import WebBridge  # noqa: E402

FAILS: list[str] = []


def ok(tag: str, cond: bool, note: str = "") -> None:
    print(f"[{'PASS' if cond else 'FAIL'}] {tag}  {note}")
    if not cond:
        FAILS.append(tag)


def main() -> int:
    b = WebBridge()

    # ══════════════════════════════════════════════════════════════
    # 1) 基本结构
    # ══════════════════════════════════════════════════════════════
    r = json.loads(b.getGachaPoolDetail())

    if not r.get("ok"):
        ok("pool_detail_ok", False,
           f"reason={r.get('reason')} message={r.get('message')}")
        return finish()

    pools = r.get("pools") or []
    ok("pool_detail_ok", True,
       f"{len(pools)} 个池 / {r.get('fiveTotal')} 条五星")

    ok("has_all_fields",
       all(k in r for k in ("ok", "pools", "fiveTotal", "playerId")),
       f"顶层字段 = {sorted(r.keys())}")

    # ══════════════════════════════════════════════════════════════
    # 2) 和 GachaReport 对账（证明没另算）
    # ══════════════════════════════════════════════════════════════
    report, who, rows = b._gacha_report()

    ok("five_total_matches_report",
       r["fiveTotal"] == report.five_count,
       f"{r['fiveTotal']} == report.five_count {report.five_count}")

    ok("pool_count_matches_active",
       len(pools) == len(report.active_pools()),
       f"{len(pools)} == report.active_pools() {len(report.active_pools())}"
       f"（只列抽过的池）")

    #: 每个池的 fives 条数 == 该池 five_count
    mismatched = []
    for p in pools:
        if len(p["fives"]) != p["five"]:
            mismatched.append(
                (p["name"], len(p["fives"]), p["five"]))
    ok("per_pool_fives_count", not mismatched,
       "每池条数 == 该池五星数" if not mismatched
       else f"不一致 = {mismatched}")

    # ══════════════════════════════════════════════════════════════
    # 3) ★★ 顺序：最新在最上面
    # ══════════════════════════════════════════════════════════════
    bad_order = []
    for p in pools:
        times = [f["at"] for f in p["fives"] if f.get("at")]
        if times != sorted(times, reverse=True):
            bad_order.append(p["name"])
    ok("fives_newest_first", not bad_order,
       "每个池都是最新在最上面" if not bad_order
       else f"⚠ 顺序不对 = {bad_order}")

    #: 和旧界面显式对照（reversed(fives_analysis())）
    for pool in report.active_pools():
        want = [f.name for f in reversed(pool.fives_analysis())]
        got = next((p["fives"] for p in pools
                    if p["poolType"] == str(pool.pool_type)), [])
        if [x["name"] for x in got] != want:
            ok(f"order_matches_old_{pool.pool_type}", False,
               f"{pool.name}: 后端={[x['name'] for x in got][:5]} "
               f"旧界面={want[:5]}")
        else:
            ok(f"order_matches_old_{pool.pool_type}", True,
               f"{pool.name}: {len(got)} 条，顺序和 "
               f"reversed(fives_analysis()) 一致")

    # ══════════════════════════════════════════════════════════════
    # 4) ★ span vs cumulative —— 两个不同口径
    # ══════════════════════════════════════════════════════════════
    all_fives = [f for p in pools for f in p["fives"]]
    ok("span_is_not_cumulative_field",
       all(isinstance(f.get("span"), int)
           and isinstance(f.get("cumulative"), int) for f in all_fives),
       "两个字段都是 int，且分开给")

    #: 同一池里"歪了之后"那条的 cumulative 应该 > span
    limited = [p for p in pools if p["isLimitedPool"]]
    if limited:
        has_diff = any(f["cumulative"] != f["span"]
                       for p in limited for f in p["fives"])
        ok("span_and_cumulative_differ",
           has_diff,
           "限定池里有 span != cumulative 的条目"
           "（歪了会累积 —— 证明没混成一个）" if has_diff
           else "（本机恰好都相等）")

    # ══════════════════════════════════════════════════════════════
    # 5) ★ 条颜色 = gacha.span_color 的分档
    # ══════════════════════════════════════════════════════════════
    from src.core import gacha

    bad_color = []
    for f in all_fives:
        want = gacha.span_color(f["span"])
        if f["barColor"] != want:
            bad_color.append((f["name"], f["span"], f["barColor"], want))
    ok("bar_color_matches_span_color", not bad_color,
       f"{len(all_fives)} 条全部符合 span_color 分档" if not bad_color
       else f"不符 = {bad_color[:3]}")

    #: 分档边界（40 / 60 / 73 / 80）
    print("       （span_color 分档：" +
          " ".join(f"≤{lim}={col}" for lim, col in gacha.SPAN_COLORS[:4]) +
          " >80=红）")
    cases = [(40, "#4aa96c"), (41, "#7fae72"), (60, "#7fae72"),
             (61, "#c8a86a"), (73, "#c8a86a"), (74, "#d9705a"),
             (80, "#d9705a"), (81, "#c0392b")]
    bad_case = [(s, got, want) for s, want in cases
                for got in [gacha.span_color(s)] if got != want]
    ok("span_color_boundaries", not bad_case,
       "40/60/73/80 四个分界点都对" if not bad_case
       else f"边界不符 = {bad_case}")

    # ══════════════════════════════════════════════════════════════
    # 6) ★ 评价 = 旧界面 _verdict 规则
    # ══════════════════════════════════════════════════════════════
    from src.core.web_bridge import _gacha_verdict

    class _F:
        def __init__(self, span, lost=False):
            self.span = span
            self.is_lost = lost

    verdict_cases = [
        #: 歪了最优先（哪怕抽数少）
        (60, True, "歪", "#c0392b"),
        (10, True, "歪", "#c0392b"),
        #: ≤60 = 欧
        (60, False, "欧", "#2e8b57"),
        (1, False, "欧", "#2e8b57"),
        #: 61~73 中间不标
        (61, False, "", ""),
        (73, False, "", ""),
        #: ≥74 = 非
        (74, False, "非", "#c0392b"),
        (90, False, "非", "#c0392b"),
    ]
    bad_verdict = []
    for span, lost, want_text, want_color in verdict_cases:
        got_text, got_color = _gacha_verdict(_F(span, lost))
        if got_text != want_text or got_color != want_color:
            bad_verdict.append(
                (span, lost, (got_text, got_color),
                 (want_text, want_color)))
    ok("verdict_matches_old_rule", not bad_verdict,
       "歪优先 / ≤60欧 / ≥74非 / 中间空" if not bad_verdict
       else f"不符 = {bad_verdict}")

    #: 接口返回的 verdict 也要符合同一规则
    bad_api = []
    for f in all_fives:
        want_text, _ = _gacha_verdict(
            type("F", (), {"span": f["span"], "is_lost": f["isLost"]})())
        if f["verdict"] != want_text:
            bad_api.append((f["name"], f["span"], f["isLost"],
                            f["verdict"], want_text))
    ok("api_verdict_consistent", not bad_api,
       "接口里的 verdict 全部合规" if not bad_api
       else f"不符 = {bad_api[:3]}")

    # ══════════════════════════════════════════════════════════════
    # 7) 头像两级兜底（和别的列表一致）
    # ══════════════════════════════════════════════════════════════
    if all_fives:
        f0 = all_fives[0]
        ok("five_has_avatar_fields",
           all(k in f0 for k in ("iconUrl", "avatarHue", "initial")),
           f"字段 = {sorted(f0.keys())}")
        ok("five_has_initial_fallback",
           isinstance(f0.get("initial"), dict)
           and bool(f0["initial"].get("initial")),
           f"initial = "
           f"{json.dumps(f0.get('initial'), ensure_ascii=False)[:60]}")

    # ══════════════════════════════════════════════════════════════
    # 8) ★ lead 问的：_fmt_number 规则
    # ══════════════════════════════════════════════════════════════
    from src.gui.widgets import _fmt_number

    fmt_cases = [
        (6.9, 2, "6.9"),        #: 6.90 → 6.9（去末尾 0）
        (13.8, 2, "13.8"),
        (15.0, 2, "15.0"),      #: 整数**保留一位**小数
        (0.22, 2, "0.22"),
        (0.015, 2, "0.01"),     #: decimals=2 会截掉第三位（旧代码的已知限制）
        (7.5, 1, "7.5"),
        (100.0, 2, "100.0"),
    ]
    bad_fmt = []
    for value, dec, want in fmt_cases:
        got = _fmt_number(value, dec)
        if got != want:
            bad_fmt.append((value, dec, got, want))
    ok("fmt_number_strips_trailing_zeros", not bad_fmt,
       "6.90→6.9、15.00→15.0（整数保留一位）" if not bad_fmt
       else f"不符 = {bad_fmt}")

    print()
    print("=" * 70)
    print("结果：" + ("全部通过" if not FAILS else "失败 " + str(FAILS)))
    print("=" * 70)
    return 1 if FAILS else 0


def finish() -> int:
    print()
    print("=" * 70)
    print("结果：" + ("全部通过" if not FAILS else "失败 " + str(FAILS)))
    print("=" * 70)
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
