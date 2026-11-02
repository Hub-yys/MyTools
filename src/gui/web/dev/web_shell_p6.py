# -*- coding: utf-8 -*-
"""验收 P6：`getCombatHistory` / `setShutdownTimer` + **prerequisites 已删**。

## 背景（2026-11-02 用户发了 7 张旧界面截图）

用户要求：「**对着旧界面的代码复刻**」。

lead 在 P4 让我加的两样东西是错的，用户圈出来要求「干掉」：

1. `getToolSettings().prerequisites`（「运行前提」区块）
   —— **旧界面根本没有这块**
2. `setEchoEnhanceProfile`（工具页选配置的下拉）
   —— 旧代码注释写着「**故意没有**」，用户 2026-09-26 明确否掉过

而这两样是旧界面**真实存在**、但 Web 版缺的：

3. `getCombatHistory()` —— 4C 自动战斗的历史记录卡
4. `setShutdownTimer()` —— 定时关机设置

## 验什么

* `prerequisites` 真的从返回里没了
* `getCombatHistory` 的 5 列数据（时间/时长/战斗/声骸/锁定）+ 汇总行
* `getShutdownTimer` / `setShutdownTimer` 存盘形状和旧界面一致

## ⚠ 用户数据保护

`setShutdownTimer` 会写 ``tool_settings.json`` 的 ``auto_combat`` 键 ——
用 ``backup_guard`` 包住。

## ⚠ 不启动引擎

两个接口都是纯数据读写，不碰 ok-ww。
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


def _run() -> int:
    b = WebBridge()

    # ══════════════════════════════════════════════════════════════
    # 1) ★ prerequisites 必须**没了**（lead P4 的错误决定）
    # ══════════════════════════════════════════════════════════════
    checked = 0
    for key in ("echo_change", "echo_enhance", "nest_sweep", "auto_combat",
                "gacha", "character_build", "wuwa_library_update"):
        ts = json.loads(b.getToolSettings(key))
        if not ts.get("ok"):
            continue
        checked += 1
        ok(f"no_prerequisites_{key}",
           "prerequisites" not in ts,
           f"字段 = {sorted(ts.keys())}")
    ok("prerequisites_checked_all", checked >= 5,
       f"{checked} 个工具都检查了")

    #: 模块级符号也该没了
    import src.core.web_bridge as WB

    gone = [
        name for name in ("_TOOL_PREREQUISITES", "_COMMON_GAME_PREREQUISITES",
                          "_prerequisites_for", "_OKWW_TOOL_KEYS")
        if hasattr(WB, name)
    ]
    ok("prerequisites_symbols_gone", not gone,
       f"还残留 = {gone}" if gone else "4 个符号全部删除")

    # ══════════════════════════════════════════════════════════════
    # 2) getCombatHistory —— 5 列 + 汇总
    # ══════════════════════════════════════════════════════════════
    h = json.loads(b.getCombatHistory())
    ok("combat_history_ok", h.get("ok") is True,
       f"count={h.get('count')} total={h.get('total')}")
    ok("combat_history_default_limit", h.get("limit") == 5,
       f"limit={h.get('limit')}（旧界面 HistoryCard.MAX_ROWS = 5）")

    items = h.get("items") or []
    if items:
        it = items[0]
        #: ★ 旧界面 5 列：时间 / 时长 / 战斗 / 声骸 / 锁定
        ok("combat_history_five_columns",
           all(k in it for k in ("when", "duration", "battles",
                                 "echoes", "locked")),
           f"字段 = {sorted(it.keys())}")
        ok("combat_history_when_format",
           "-" in str(it.get("when")) or ":" in str(it.get("when")),
           f"when={it.get('when')!r}")
        ok("combat_history_duration_format",
           ":" in str(it.get("duration")),
           f"duration={it.get('duration')!r}")
        ok("combat_history_counts_are_int",
           all(isinstance(it.get(k), int)
               for k in ("battles", "echoes", "locked")),
           f"battles={it.get('battles')} echoes={it.get('echoes')} "
           f"locked={it.get('locked')}")
        #: 旧界面还有队伍 / 声骸名
        ok("combat_history_has_team_echo",
           "team" in it and "echo" in it,
           f"team={it.get('team')} echo={it.get('echo')!r}")
        ok("combat_history_team_is_list",
           isinstance(it.get("team"), list),
           f"team 类型 = {type(it.get('team')).__name__}")
    else:
        ok("combat_history_empty_ok", True, "本机没有 4C 历史（接口正确返回空）")

    #: ★ 汇总行（旧界面底部那行）
    ok("combat_history_total_text",
       isinstance(h.get("totalText"), str) and bool(h.get("totalText")),
       f"totalText = {h.get('totalText')!r}")

    #: limit 生效
    h1 = json.loads(b.getCombatHistory("1"))
    ok("combat_history_limit_respected",
       len(h1.get("items") or []) <= 1,
       f"limit=1 → {len(h1.get('items') or [])} 条")

    # ══════════════════════════════════════════════════════════════
    # 3) getShutdownTimer / setShutdownTimer
    # ══════════════════════════════════════════════════════════════
    g = json.loads(b.getShutdownTimer())
    ok("shutdown_get_ok", g.get("ok") is True,
       json.dumps(g, ensure_ascii=False)[:130])
    ok("shutdown_get_fields",
       all(k in g for k in ("enabled", "minutes", "minMinutes",
                            "maxMinutes", "defaultMinutes")),
       f"字段 = {sorted(g.keys())}")
    ok("shutdown_bounds",
       g.get("minMinutes") == 1 and g.get("maxMinutes") == 1440,
       f"{g.get('minMinutes')}~{g.get('maxMinutes')} 分钟（用户要求 1~1440）")
    ok("shutdown_minutes_in_range",
       g["minMinutes"] <= g["minutes"] <= g["maxMinutes"],
       f"minutes={g.get('minutes')}")

    #: 存一个新值
    r = json.loads(b.setShutdownTimer(
        json.dumps({"enabled": True, "minutes": 90})))
    ok("shutdown_set_ok", r.get("ok") is True,
       json.dumps(r, ensure_ascii=False))

    g2 = json.loads(b.getShutdownTimer())
    ok("shutdown_persisted",
       g2.get("enabled") is True and g2.get("minutes") == 90,
       f"回读 enabled={g2.get('enabled')} minutes={g2.get('minutes')}")

    #: ★ 存盘形状必须和旧界面一致（shutdown_enabled / shutdown_minutes）
    from src.core import tool_settings
    from src.tools.game.auto_combat.tool import SHUTDOWN_SETTINGS_KEY

    raw = tool_settings.load(SHUTDOWN_SETTINGS_KEY) or {}
    ok("shutdown_stored_shape",
       "shutdown_enabled" in raw and "shutdown_minutes" in raw,
       f"存盘 key = {sorted(raw.keys())}"
       f"（旧界面就是 shutdown_enabled / shutdown_minutes）")
    ok("shutdown_stored_values",
       raw.get("shutdown_enabled") is True
       and raw.get("shutdown_minutes") == 90,
       f"存盘 = {json.dumps(raw, ensure_ascii=False)[:100]}")

    #: ★ clamp：超范围要夹住
    r = json.loads(b.setShutdownTimer(
        json.dumps({"enabled": True, "minutes": 99999})))
    ok("shutdown_clamped_max", r.get("minutes") == 1440,
       f"99999 → {r.get('minutes')}（夹到 MAX_MINUTES=1440）")

    r = json.loads(b.setShutdownTimer(
        json.dumps({"enabled": True, "minutes": -5})))
    ok("shutdown_clamped_min",
       r.get("minutes") == 60,
       f"-5 → {r.get('minutes')}（clamp 后为 0 → 回落默认 60）")

    r = json.loads(b.setShutdownTimer(
        json.dumps({"enabled": True, "minutes": "abc"})))
    ok("shutdown_bad_minutes_fallback",
       r.get("ok") is True and r.get("minutes") == 60,
       f"'abc' → {r.get('minutes')}（回落默认 60）")

    #: ★ 非法 payload
    r = json.loads(b.setShutdownTimer("not json"))
    ok("shutdown_bad_json",
       r.get("ok") is False and r.get("reason") == "bad_json",
       f"reason={r.get('reason')}")

    r = json.loads(b.setShutdownTimer("[]"))
    ok("shutdown_bad_data",
       r.get("ok") is False and r.get("reason") == "bad_data",
       f"reason={r.get('reason')}")

    #: ★ 合并而不是覆盖 —— 同 key 下的其他字段要保留
    tool_settings.save(SHUTDOWN_SETTINGS_KEY, {
        **dict(tool_settings.load(SHUTDOWN_SETTINGS_KEY) or {}),
        "__sentinel": "keep-me",
    })
    json.loads(b.setShutdownTimer(json.dumps(
        {"enabled": False, "minutes": 30})))
    after = tool_settings.load(SHUTDOWN_SETTINGS_KEY) or {}
    ok("shutdown_merges_not_overwrites",
       after.get("__sentinel") == "keep-me",
       f"同 key 下其他字段保住了 = {after.get('__sentinel')!r}"
       f"（旧界面也是 **合并** 存盘）")

    #: disabled 时 minutes 仍保留（旧界面行为）
    g3 = json.loads(b.getShutdownTimer())
    ok("shutdown_disabled_keeps_minutes",
       g3.get("enabled") is False and g3.get("minutes") == 30,
       f"enabled=False 时 minutes 仍 = {g3.get('minutes')}"
       f"（旧界面取消勾选不清掉分钟数）")

    print()
    print("=" * 70)
    print("结果：" + ("全部通过" if not FAILS else "失败 " + str(FAILS)))
    print("=" * 70)
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
