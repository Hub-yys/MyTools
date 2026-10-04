# -*- coding: utf-8 -*-
"""皮肤选择器 —— 左侧边栏底部的皮肤卡片。

## 为什么放侧栏

用户："左侧边栏，增加皮肤功能"。
侧栏底部的空间正好空着 —— 皮肤是**全局设置**，放最下面合理
（不像配置那样是工具，所以也不该混在「工具」分组里）。

## 设计

    ┌─────────────────────┐
    │  🎨 皮肤            │
    │  ┌───┐ ┌───┐ ┌───┐ │
    │  │ ● │ │ ● │ │ ● │ │   ← 每款一个小色块
    │  └───┘ └───┘ └───┘ │
    └─────────────────────┘

· 每个皮肤一个**圆点**（带它自己的主色）
· 点击 → 立刻应用（换主色 + 亮暗模式）
· 悬停 → 显示皮肤名
· 当前选中的 → 加一圈外框

## 与 ``core/skins.py`` 的关系

那边管**存哪个皮肤**和**怎么应用**；
这边只管**画出来 + 接收点击**。
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..core import skins

logger = logging.getLogger(__name__)

#: 色块直径
DOT_SIZE = 24
#: 色块间距
DOT_SPACING = 8


class SkinDot(QToolButton):
    """一个皮肤色块（圆点）。"""

    chosen = Signal(str)                       #: 皮肤 id（**别叫 clicked**）

    def __init__(self, skin: dict, parent=None):
        super().__init__(parent)
        self._skin = skin
        self.setObjectName("skinDot")
        self.setFixedSize(QSize(DOT_SIZE + 8, DOT_SIZE + 8))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(
            f"{skin['name']}　"
            f"{'（暗色）' if skin['mode'] == 'dark' else ''}")
        self.setCheckable(True)
        self.setChecked(skin["id"] == skins.current_skin()["id"])
        self._apply_style()
        #: ⚠ 我第一版把信号也叫 ``clicked`` —— 跟 ``QToolButton.clicked``
        #: **撞名**：测试里 ``emit`` 时**又触发一次**自带的鼠标处理，
        #: 实测**直接卡住**。改名 ``chosen`` 就干净了。
        super().clicked.connect(
            lambda _c=False: self.chosen.emit(self._skin["id"]))

    def _apply_style(self) -> None:
        s = self._skin
        primary = s["primary"]
        #: 圆点：主色 + 一个浅色内圈（像皮肤预览）
        self.setStyleSheet(f"""
            QToolButton#skinDot {{
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 {primary},
                    stop:1 {self._shift(primary, -0.25)});
                border-radius: {(DOT_SIZE + 8) // 2}px;
                border: 2px solid {primary};
            }}
            QToolButton#skinDot:hover {{
                border: 2px solid #ffffff;
            }}
            QToolButton#skinDot:checked {{
                border: 3px solid {self._shift(primary, 0.35)};
            }}
        """)

    @staticmethod
    def _shift(hex_color: str, amount: float) -> str:
        """把颜色往亮（amount>0）/暗（<0）方向调一点。"""
        c = QColor(hex_color)
        if amount >= 0:
            return c.lighter(int(100 + amount * 100)).name()
        return c.darker(int(100 - amount * 100)).name()


class SkinPickerCard(QWidget):
    """侧栏底部的皮肤选择卡片。"""

    skin_chosen = Signal(str)                  # 皮肤 id

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("skinPickerCard")
        self._dots: list[SkinDot] = []
        self._build()
        self.refresh()

    def _build(self) -> None:
        box = QVBoxLayout(self)
        box.setContentsMargins(10, 6, 10, 10)
        box.setSpacing(6)

        head = QLabel("🎨 皮肤", self)
        head.setStyleSheet("font-size: 12px; font-weight: bold;")
        box.addWidget(head)

        grid = QHBoxLayout()
        grid.setSpacing(DOT_SPACING)
        for skin in skins.all_skins():
            dot = SkinDot(skin, self)
            dot.chosen.connect(self._on_dot)
            grid.addWidget(dot)
            self._dots.append(dot)
        grid.addStretch(1)
        box.addLayout(grid)

    def _on_dot(self, skin_id: str) -> None:
        if skins.apply_skin(skin_id):
            self.refresh()
            self.skin_chosen.emit(skin_id)

    def refresh(self) -> None:
        """把"当前选中"那圈外框标到正确的圆点上。"""
        current = skins.current_skin()["id"]
        for dot in self._dots:
            dot.setChecked(dot._skin["id"] == current)


def build_skin_card(parent=None) -> SkinPickerCard:
    """侧栏底部加一张皮肤卡（main_window 用它）。"""
    return SkinPickerCard(parent)
