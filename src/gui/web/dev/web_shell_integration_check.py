# -*- coding: utf-8 -*-
"""验证 page-converter 报的两个 bug 已修 + 新挂载点可用。

## 检查项

1. ``_parse_gradient`` 的字符串分支不再 NameError（``import ast`` 补上了）
2. ``getSkinList()`` 返回 ``bg`` / ``css``
3. ``/game/avatars/`` 等 4 个白名单目录能取到 png
4. ``/game/splash/`` **取不到**（773MB 那个必须挡住）
5. ``_shared.js`` 被页面加载了（``window.Pages`` 存在）
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from urllib.parse import quote

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", "..", ".."))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)
os.environ.setdefault("QT_LOGGING_RULES", "qt.multimedia.*=false")

RESULTS: list[tuple[str, bool, str]] = []


def check(tag: str, ok: bool, note: str = "") -> None:
    RESULTS.append((tag, bool(ok), note))
    print(f"[{'PASS' if ok else 'FAIL'}] {tag}  {note}")


def http(url: str) -> tuple[int, int]:
    """返回 (status, 字节数)；失败返回 (0, 0)。"""
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            return resp.status, len(resp.read())
    except Exception:  # noqa: BLE001
        return 0, 0


def main() -> int:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    import src.tools as tools_pkg  # noqa: PLC0415

    tools_pkg.discover_tools()

    # ── 1 / 2：桥接层 ──────────────────────────────────────────────
    from src.core.web_bridge import WebBridge, _parse_gradient  # noqa: PLC0415

    bridge = WebBridge()

    try:
        parsed = _parse_gradient("[(0.0, '#0C0A18'), (1.0, '#090713')]")
        check("B1", len(parsed) == 2,
              f"字符串渐变解析 = {parsed}（不再 NameError）")
    except Exception as exc:  # noqa: BLE001
        check("B1", False, f"字符串渐变解析崩了：{type(exc).__name__}: {exc}")

    skins = json.loads(bridge.getSkinList())
    if skins:
        first = skins[0]
        has_bg = bool(first.get("bg"))
        has_css = bool(first.get("css"))
        check("B2", has_bg and has_css,
              f"getSkinList[0] bg={first.get('bg')!r} css={first.get('css')!r}")
    else:
        check("B2", False, "getSkinList 返回空")

    # ── 3 / 4：挂载点 ─────────────────────────────────────────────
    from src.gui import web_shell as WS  # noqa: PLC0415

    base = WS.web_base_url()
    check("M0", bool(base), f"base = {base}")

    #: 白名单里的每个子目录至少能取到一张图
    for sub in WS.GAME_ASSET_SUBDIRS:
        src_dir = os.path.join(_ROOT, "assets", "game", sub)
        if not os.path.isdir(src_dir):
            check(f"M_{sub}", True, "（本地没有这个目录，跳过）")
            continue
        names = [f for f in sorted(os.listdir(src_dir))
                 if f.lower().endswith(".png")]
        if not names:
            check(f"M_{sub}", True, "（目录里没 png，跳过）")
            continue
        #: ⚠ 必须 percent-encode —— 文件名全是中文（丹瑾.png），
        #: urllib 遇到未编码的 UTF-8 会直接抛（表现为 status=0）。
        #: 这正是本脚本 2026-11-02 误报 4 个 M_* 失败的原因。
        url = (f"{base.rsplit('/web/', 1)[0]}/game/{sub}/"
               f"{quote(names[0], safe='')}")
        status, size = http(url)
        check(f"M_{sub}", status == 200 and size > 0,
              f"{names[0]} → {status}, {size} bytes")

    #: splash 必须取不到
    splash = os.path.join(_ROOT, "assets", "game", "splash")
    if os.path.isdir(splash):
        files = [f for f in sorted(os.listdir(splash))
                 if f.lower().endswith((".jpg", ".png"))]
        if files:
            url = (f"{base.rsplit('/web/', 1)[0]}/game/splash/"
                   f"{quote(files[0], safe='')}")
            status, _ = http(url)
            check("M_splash_blocked", status != 200,
                  f"/game/splash/{files[0]} → {status}（应为 403/404）")

    # ── 5：_shared.js 真的加载了 ──────────────────────────────────
    from src.gui.web_shell import WebShell  # noqa: PLC0415

    shell = WebShell(base_url=base)
    if not shell.build():
        check("S1", False, "WebShell.build 失败")
        return finish()

    shell.view.resize(1100, 720)
    shell.view.show()

    def probe() -> None:
        raw = shell.debug_js(
            "JSON.stringify({"
            "pages: typeof window.Pages,"
            "app: typeof window.App,"
            "scripts: Array.from(document.scripts)"
            "  .map(function(s){return s.src.split('/').pop()})"
            "})")
        try:
            data = json.loads(raw or "{}")
        except ValueError:
            data = {}
        pages = data.get("pages")
        check("S1", pages not in (None, "undefined"),
              f"window.Pages = {pages}")
        scripts = data.get("scripts") or []
        has_shared = any("_shared.js" in str(s) for s in scripts)
        check("S2", has_shared, f"已加载脚本 {scripts}")
        #: 顺序：_shared 必须在 home.js 之前
        idx_shared = next((i for i, s in enumerate(scripts)
                           if "_shared" in str(s)), -1)
        idx_home = next((i for i, s in enumerate(scripts)
                         if str(s) == "home.js"), -1)
        check("S3", 0 <= idx_shared < idx_home,
              f"_shared.js 位置 {idx_shared} < home.js 位置 {idx_home}")
        QTimer.singleShot(200, finish_and_quit)

    def finish_and_quit() -> None:
        shell.close()
        QTimer.singleShot(200, app.quit)

    shell.view.loadFinished.connect(lambda ok: QTimer.singleShot(3000, probe))
    QTimer.singleShot(30000, app.quit)
    app.exec()
    return finish()


def finish() -> int:
    failed = [r for r in RESULTS if not r[1]]
    print("\n" + "=" * 60)
    print(f"结果：{len(RESULTS) - len(failed)}/{len(RESULTS)} 通过")
    if failed:
        for tag, _ok, note in failed:
            print(f"  NG {tag}  {note}")
    print("=" * 60)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
