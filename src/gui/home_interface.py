"""主页：**平铺所有已注册的工具**（2026-09-24 起不再按分类分组）。

数据来源只有 ToolRegistry，所以工具的增改删在这里天然生效，不需要改这个文件。
分类信息仍留在 ToolMeta 里（工具页下拉框、占位页的"分类"一行还在用），
只是主页不再拿它分组 —— 工具不多时分组只会白占几行标题。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget
from qfluentwidgets import ScrollArea

from ..app_config import APP_DISPLAY_NAME, APP_VERSION
from ..core.registry import ToolRegistry
from .compat import CaptionLabel, TitleLabel, resolve_icon
from .widgets import ToolGrid


class HomeInterface(ScrollArea):
    """可滚动的主页容器。"""

    requestOpenTool = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("HomeInterface")
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setViewportMargins(0, 0, 0, 0)

        self.view = QWidget(self)
        self.view.setObjectName("homeView")
        self.root_layout = QVBoxLayout(self.view)
        self.root_layout.setContentsMargins(36, 32, 36, 28)
        self.root_layout.setSpacing(24)

        self.setWidget(self.view)
        self.setWidgetResizable(True)
        # ScrollArea 自身和它的 viewport 都会吃系统调色板底色（深色 Windows 上
        # 就是一片黑，和浅色 Fluent 窗口对不上），两处都要显式透明才行。
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("#HomeInterface { background: transparent; }")
        self.viewport().setStyleSheet("background: transparent;")

        self.build()

    # ------------------------------------------------------------------ 构建
    def build(self) -> None:
        self.root_layout.addWidget(TitleLabel(APP_DISPLAY_NAME, self.view))

        total = len(ToolRegistry.all_metas())
        subtitle = CaptionLabel(
            f"v{APP_VERSION} · 已收录 {total} 个工具，点击卡片直接打开", self.view
        )
        subtitle.setTextColor("#8A8F98", "#7C7C7C")
        self.root_layout.addWidget(subtitle)

        self.root_layout.addSpacing(8)

        # 所有工具平铺成一张网格，不分类
        self.grid = ToolGrid(ToolRegistry.all_metas(), self.view)
        self.grid.toolClicked.connect(self.requestOpenTool)
        self.root_layout.addWidget(self.grid)

        self.root_layout.addStretch(1)

    # ------------------------------------------------------------------ 其它
    def icon(self):  # 供主窗口导航用
        return resolve_icon("HOME")
