"""GUI 层冒烟测试：不需要人看窗口就能验证界面代码。

    python tests/smoke_gui.py                 # 只验证不崩
    python tests/smoke_gui.py --shot          # 截图到 tests/_shots/

关于渲染平台：
- 默认走 offscreen（无显示器也能跑）。**offscreen 插件在 Windows 上加载不到任何系统字体**
  （QFontDatabase.families() 返回 0），所以截图里的中文会是方框——那是测试环境限制，不是 bug。
- 想拿到正常中文截图，强制用真实平台插件（不会弹窗，只做离屏 render）：

      QT_QPA_PLATFORM=windows python tests/smoke_gui.py --shot
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SHOT_DIR = ROOT / "tests" / "_shots"

_failures: list[str] = []


def check(condition: bool, message: str) -> bool:
    print(f"  [{'PASS' if condition else 'FAIL'}] {message}")
    if not condition:
        _failures.append(message)
    return bool(condition)


def save_shot(widget, filename: str) -> None:
    """整窗渲染到预填背景的 QImage。

    直接 widget.grab() 会把透明区域抓成黑色，所以这里先按主题填底色再 render。
    """
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QColor, QImage, QPainter
    from qfluentwidgets import isDarkTheme

    SHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SHOT_DIR / filename

    image = QImage(widget.size(), QImage.Format.Format_ARGB32)
    image.fill(QColor("#202020") if isDarkTheme() else QColor("#F3F3F3"))

    painter = QPainter(image)
    widget.render(painter, QPoint(0, 0))
    painter.end()
    image.save(str(path))
    print(f"  -> 截图 {path.relative_to(ROOT)}  ({widget.width()}x{widget.height()})")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shot", action="store_true", help="输出界面截图")
    args = parser.parse_args()

    from PySide6.QtGui import QFontDatabase
    from PySide6.QtWidgets import QApplication

    from src.core.registry import ToolRegistry
    from src.gui.main_window import MainWindow
    from src.tools import discover_tools

    print("=== MyTools GUI 冒烟测试 ===")

    discover_tools()
    app = QApplication(sys.argv)

    if not QFontDatabase.families():
        print("  [WARN] 当前平台没有任何系统字体，截图里的中文会是方框")
        print("         想要正常截图：QT_QPA_PLATFORM=windows python tests/smoke_gui.py --shot")

    window = MainWindow()
    check(window is not None, "主窗口可构造")
    check(window.home_interface is not None, "主页已挂载")

    # 每个滚动页都必须把内层 view 交给滚动区托管：只 new 一个 QWidget 而不 setWidget，
    # 它就是个"浮在滚动区上的裸控件"，尺寸不受布局管理 —— 整页会被压扁
    # （2026-09-22 任务页就是这么漏的：标题和说明叠在一起、卡片里的字挤成横条）
    for page in (window.home_interface, window.config_interface,
                 window.tasks_interface, window.wuwa_library):
        name = type(page).__name__
        check(page.widget() is not None, f"{name} 已 setWidget（漏了会让整页压扁）")
        check(page.widgetResizable(), f"{name} 已开启 widgetResizable")

    check(
        len(window._tool_hosts) == len(ToolRegistry.all_metas()),
        f"侧栏「工具」分组下挂了 {len(window._tool_hosts)} 个工具项",
    )

    metas = ToolRegistry.all_metas()
    check(len(metas) > 0, f"{len(metas)} 个工具可渲染")

    # 逐个打开工具面板；create_widget 抛异常会被宿主兜住，不该波及主程序
    for meta in metas:
        try:
            window.open_tool(meta.key)
            panel = window.tool_panel(meta.key)
            check(panel is not None, f"{meta.name}: 面板创建成功")
        except Exception as exc:  # noqa: BLE001
            check(False, f"{meta.name}: 面板创建异常 {exc}")

    # 主页每个"有工具的"分类各渲染一组（空分类按设计不显示）
    from src.core.categories import ALL_CATEGORIES
    from src.gui.widgets import CategorySection

    sections = window.home_interface.findChildren(CategorySection)
    expected = len([c for c in ALL_CATEGORIES if ToolRegistry.by_category(c)])
    check(
        len(sections) == expected,
        f"主页分类分组 {len(sections)} 组 / 应有 {expected} 组",
    )

    if args.shot:
        # 截图统一走浅色主题：AUTO 在命令行环境下会跟着系统/终端跑偏，
        # 导致背景与文字配色对不上（纯属截图观感问题，不影响真实运行）。
        from qfluentwidgets import Theme, setTheme

        setTheme(Theme.LIGHT)

        # 未 show 的窗口 resize 不生效（要等窗口真正映射），截出来只有 500x500，
        # 所以截图模式会短暂把窗口显示出来再抓图。
        window.show()
        app.processEvents()

        def settle(times: int = 4) -> None:
            """多跑几轮事件循环，等布局/绘制稳定下来再抓图。"""
            for _ in range(times):
                app.processEvents()

        settle()
        # 截图辅助：Mica/亚克力是 DWM 合成的，Qt 抓不到，留下会是一片死色
        if hasattr(window, "setMicaEffectEnabled"):
            window.setMicaEffectEnabled(False)
        # 让侧栏展开，导航项文字才看得见
        expand = getattr(window.navigationInterface, "expand", None)
        if callable(expand):
            try:
                expand(useAni=False)
            except TypeError:
                expand()
        settle()
        window.resize(1180, 780)
        settle()

        window.switchTo(window.home_interface)
        settle()
        save_shot(window, "home.png")

        # 展开侧栏的「工具」分组，让工具名（子项）显示出来
        nav = window.navigationInterface
        for method_name in ("widget", "item", "findItem"):
            getter = getattr(nav, method_name, None)
            if not callable(getter):
                continue
            try:
                node = getter("tool_group")
            except Exception:  # noqa: BLE001
                continue
            if node is not None and hasattr(node, "setExpanded"):
                node.setExpanded(True)
                print(f"  [info] 已展开工具分组（nav.{method_name}）")
                break
        settle()
        print(f"  [info] 侧栏子项：{list(window._tool_hosts.keys())}")

        window.open_tool(metas[0].key)
        settle()
        save_shot(window, "tools.png")
        window.close()

    print(f"\n=== 结果：{'全部通过' if not _failures else f'{len(_failures)} 项失败'} ===")
    for item in _failures:
        print(f"  - {item}")
    return 1 if _failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
