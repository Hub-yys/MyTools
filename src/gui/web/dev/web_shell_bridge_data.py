# -*- coding: utf-8 -*-
"""验收 page-converter 要的 3 个数据接口 + 素材挂载点。"""

from __future__ import annotations

import json
import os
import sys
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", "..", ".."))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)
os.environ.setdefault("QT_LOGGING_RULES", "qt.multimedia.*=false")

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

import src.tools as tools_pkg  # noqa: E402

tools_pkg.discover_tools()

from src.core.web_bridge import WebBridge, _parse_gradient  # noqa: E402
from src.gui import web_shell as WS  # noqa: E402

FAILS: list[str] = []


def ok(tag: str, cond: bool, note: str = "") -> None:
    print(f"[{'PASS' if cond else 'FAIL'}] {tag}  {note}")
    if not cond:
        FAILS.append(tag)


def main() -> int:
    bridge = WebBridge()

    #: 先起 HTTP 服务（图标 URL 依赖它）
    base = WS.web_base_url()
    ok("BASE", bool(base), base)

    # ── bug 修复确认 ──────────────────────────────────────────────
    try:
        p = _parse_gradient("[(0.0, '#0C0A18'), (1.0, '#090713')]")
        ok("FIX_ast", len(p) == 2, f"字符串渐变 = {p}")
    except Exception as exc:  # noqa: BLE001
        ok("FIX_ast", False, f"{type(exc).__name__}: {exc}")

    skins = json.loads(bridge.getSkinList())
    ok("FIX_skin_bg", bool(skins and skins[0].get("bg")),
       f"bg={skins[0].get('bg') if skins else None!r}")

    # ── getFlowList ───────────────────────────────────────────────
    flows = json.loads(bridge.getFlowList())
    ok("getFlowList", isinstance(flows, list), f"{len(flows)} 条流程")
    if flows:
        f0 = flows[0]
        ok("flow_fields",
           all(k in f0 for k in ("id", "name", "steps", "stepCount",
                                 "toolCount", "errors")),
           f"字段 = {sorted(f0.keys())}")
        print("      样例:", json.dumps(
            {k: f0[k] for k in ("id", "name", "stepCount", "toolCount",
                                "typeText")},
            ensure_ascii=False))

    # ── getConfigList ─────────────────────────────────────────────
    cfg = json.loads(bridge.getConfigList())
    ok("getConfigList_keys",
       isinstance(cfg, dict) and "loadouts" in cfg and "echoProfiles" in cfg,
       f"keys={sorted(cfg.keys()) if isinstance(cfg, dict) else cfg}")
    loads = cfg.get("loadouts") or []
    profiles = cfg.get("echoProfiles") or []
    ok("getConfigList_counts", True,
       f"{len(loads)} 条声骸配置, {len(profiles)} 条战斗配置")
    if loads:
        L0 = loads[0]
        ok("loadout_fields",
           all(k in L0 for k in ("id", "character", "avatarUrl", "echoSet",
                                 "picks", "errors")),
           f"字段 = {sorted(L0.keys())}")
        print("      样例:", json.dumps(
            {k: L0[k] for k in ("character", "echoSet", "avatarUrl")},
            ensure_ascii=False)[:150])

    # ── getLibraryData ────────────────────────────────────────────
    lib = json.loads(bridge.getLibraryData())
    counts = lib.get("counts") or {}
    ok("lib_counts",
       counts.get("characters") == 61 and counts.get("echoSets") == 37
       and counts.get("echoes") == 187,
       f"counts={counts}")
    ok("lib_assets_available", lib.get("assetsAvailable") is True,
       f"assetsAvailable={lib.get('assetsAvailable')}")

    #: 图标 URL 抽查（中文文件名必须能取到）
    for group, key_name in (("characters", "avatarUrl"),
                            ("echoSets", "iconUrl")):
        items = lib.get(group) or []
        if not items:
            continue
        url = items[0].get(key_name) or ""
        got = http_size(url)
        ok(f"lib_icon_{group}", got > 0,
           f"{items[0].get('name')} → {url[:80]} → {got} bytes")

    echoes = lib.get("echoesByCost") or {}
    first_cost = next(iter(echoes), None)
    if first_cost:
        e = echoes[first_cost][0]
        got = http_size(e.get("iconUrl") or "")
        ok("lib_icon_echoes", got > 0,
           f"{e.get('name')} → {got} bytes")

    weapons = lib.get("weapons") or []
    ok("lib_weapons_count", len(weapons) > 0, f"{len(weapons)} 把武器")
    if weapons:
        got = http_size(weapons[0].get("iconUrl") or "")
        ok("lib_icon_weapons", got > 0,
           f"{weapons[0].get('name')} → {got} bytes")

    # ── splash 必须挡住 ───────────────────────────────────────────
    host = base.rsplit("/web/", 1)[0]
    splash_dir = os.path.join(_ROOT, "assets", "game", "splash")
    if os.path.isdir(splash_dir):
        files = [f for f in sorted(os.listdir(splash_dir))
                 if f.lower().endswith((".jpg", ".png"))]
        if files:
            from urllib.parse import quote
            st = http_status(f"{host}/game/splash/{quote(files[0])}")
            ok("splash_blocked", st != 200, f"/game/splash/ → {st}")

    # ── 体积检查（页面能接受吗）──────────────────────────────────
    for name, payload in (("getLibraryData", lib), ("getConfigList", cfg),
                          ("getFlowList", flows)):
        size = len(json.dumps(payload, ensure_ascii=False).encode())
        ok(f"size_{name}", size < 900_000, f"{size / 1024:.0f} KB")

    print()
    print("=" * 60)
    print(f"结果：{'全部通过' if not FAILS else '失败 ' + str(FAILS)}")
    print("=" * 60)
    return 1 if FAILS else 0


def http_status(url: str) -> int:
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status
    except Exception:  # noqa: BLE001
        return 0


def http_size(url: str) -> int:
    if not url:
        return 0
    try:
        with urllib.request.urlopen(url, timeout=8) as r:
            return len(r.read())
    except Exception:  # noqa: BLE001
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
