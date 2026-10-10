# -*- coding: utf-8 -*-
"""托盘菜单：**真机（Windows 平台插件）**下的可见性检查。

    .\\.venv\\Scripts\\python.exe tests\\check_tray_menu_gui.py

## 为什么必须单独一个脚本（而不是塞进 unittest）

用户 2026-10-09："托盘退出怎么都看不见"。

根因：深色皮肤下托盘右键菜单是**深字压深底**。实测两个平台差得天壤之别::

    QT_QPA_PLATFORM=offscreen   反差 224  ← 看着完全正常（**假象**）
    QT_QPA_PLATFORM=windows     反差  19  ← 用户实际看到的

也就是说：**默认测试环境（offscreen）根本复现不了这个 bug**，
``tests/test_tray_menu.py`` 里那条渲染断言在 CI 上只是个冒烟。
真正能抓住它的是这个脚本 —— 它跟 ``check_echo_page_gui.py`` 等一样，
明确要求用 ``QT_QPA_PLATFORM=windows`` 跑。

退出码：0 = 全部可见；1 = 有皮肤下菜单看不清。
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SHOTS = ROOT / "tests" / "_shots"
SHOTS.mkdir(parents=True, exist_ok=True)

#: 反差低于这个值就算"看不见"（修之前深色皮肤是 19/255，修完 200+）
MIN_SPAN = 100.0

CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append((name, ok, detail))


def main() -> int:
    import os

    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)

    platform = os.environ.get("QT_QPA_PLATFORM", "(默认)")
    print(f"QT_QPA_PLATFORM = {platform}")
    if platform != "windows":
        print("⚠ 建议用 QT_QPA_PLATFORM=windows 跑 —— offscreen 下这个 bug 复现不了")

    from src.core import skins
    from src.gui import tray

    def span_of(menu) -> tuple[float, float, float]:
        """菜单渲染出来的 (最暗, 最亮, 反差)。"""
        menu.show()
        app.processEvents()
        app.processEvents()
        img = menu.grab().toImage()
        vals = []
        for y in range(img.height()):
            for x in range(img.width()):
                c = img.pixelColor(x, y)
                vals.append((c.red() + c.green() + c.blue()) / 3)
        menu.hide()
        return min(vals), max(vals), max(vals) - min(vals)

    print()
    print("%-12s %-10s %-10s %s" % ("皮肤", "最暗", "最亮", "反差"))
    worst = 1e9
    for skin in skins.all_skins():
        sid = skin["id"]
        skins.apply_skin(sid, save=False)
        menu = tray.build_menu(None, on_show=lambda: None, on_quit=lambda: None)
        dark, light, span = span_of(menu)
        worst = min(worst, span)
        menu.grab().save(str(SHOTS / f"tray_menu_{sid}.png"))
        flag = "" if span >= MIN_SPAN else "   ← 看不清！"
        print("%-12s %-10.0f %-10.0f %.1f%s" % (sid, dark, light, span, flag))
        check(f"{sid} 菜单可见（反差 {span:.0f}）", span >= MIN_SPAN)

    print()
    print(f"最差反差 = {worst:.1f}（阈值 {MIN_SPAN:.0f}）")
    print(f"截图：{SHOTS}\\tray_menu_*.png")
    print()

    bad = [c for c in CHECKS if not c[1]]
    for name, ok, det in CHECKS:
        print(f"  {'OK  ' if ok else 'BAD '} {name}" + (f"   {det}" if det else ""))
    print()
    print("★", "全部可见" if not bad else f"⚠ {len(bad)} 款皮肤下菜单看不清")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
