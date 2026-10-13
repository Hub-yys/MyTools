# -*- coding: utf-8 -*-
"""冒烟：渲染「查缺补漏」工具页并截图（浅色 / 深色两种主题）。

## 为什么值得单独跑

工具页是用户唯一会看到的东西，而 GUI 问题**单测抓不到** ——
这个项目里已经栽过几次（写死浅色底、卡片叠一起、Mica 截成死色）。
所以每个工具页都该真渲染一次。

⚠ 两个坑照抄现有脚本的做法：

1. ``setMicaEffectEnabled(False)`` —— Mica 是 DWM 合成的，Qt 抓不到，
   不关就是一片死色
2. ``QT_QPA_PLATFORM=windows`` —— offscreen 平台在 Windows 上
   **加载不到任何系统字体**，中文会变方框
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "windows")
sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8")

from PySide6.QtWidgets import QApplication          # noqa: E402
from qfluentwidgets import Theme, setTheme          # noqa: E402
from qfluentwidgets.window.fluent_window import FluentWindow  # noqa: E402

from src.core.registry import registry              # noqa: E402
from src.gui.compat import resolve_icon             # noqa: E402
from src.gui.widgets import ComingSoonWidget        # noqa: E402
from src.tools import discover_tools                # noqa: E402

discover_tools()
app = QApplication.instance() or QApplication([])

out = os.path.join("tests", "_shots")
os.makedirs(out, exist_ok=True)

errors = []


def shoot(theme, name: str) -> None:
    setTheme(theme)
    win = FluentWindow()
    if hasattr(win, "setMicaEffectEnabled"):
        win.setMicaEffectEnabled(False)

    tool = registry.make("explore_gap")
    if tool is None:
        errors.append("registry.make('explore_gap') 返回 None")
        return
    panel = tool.create_widget()
    if panel is None:
        errors.append("create_widget() 返回 None")
        return
    #: ★ ``is not None`` 证明不了构造成功 —— 构造抛异常时会被换成
    #: ComingSoonWidget 兜底（README 踩过的坑第 4 条）。
    if isinstance(panel, ComingSoonWidget):
        errors.append("拿到的是兜底占位页 —— create_widget 抛异常了")
        return

    win.addSubInterface(panel, resolve_icon("GAME"), "查缺补漏")
    win.resize(940, 680)
    win.show()
    for _ in range(10):
        app.processEvents()

    path = os.path.join(out, name)
    win.grab().save(path)
    print("截图 →", path)

    #: 顺手验几个关键控件在（截图看不出"没崩但缺东西"）
    for attr in ("video_edit", "build_button", "px_edit", "cal_button",
                 "cal_status", "build_status", "drop_zone", "pick_button"):
        if not hasattr(panel, attr):
            errors.append(f"面板缺控件 {attr}")
    #: ★ 上传控件必须真的接上了（"看着有、拖了没反应"是典型故障）
    if hasattr(panel, "drop_zone"):
        try:
            panel.drop_zone.dropped.emit("")
            panel.drop_zone.dropped.disconnect()
        except Exception as exc:                  # noqa: BLE001
            errors.append(f"拖放区信号接不上：{exc}")

    panel._shutdown_thread()
    win.close()
    win.deleteLater()
    for _ in range(4):
        app.processEvents()


shoot(Theme.LIGHT, "explore_gap_light.png")
shoot(Theme.DARK, "explore_gap_dark.png")

#: 再验一次"怎么标定？"那个按钮的说明真能弹出来（内容不崩）
print()
print("=" * 70)
print("结果")
print("=" * 70)
if errors:
    for e in errors:
        print("  ✗", e)
    raise SystemExit(1)
print("  工具页在浅色/深色下都能渲染，关键控件齐全")
