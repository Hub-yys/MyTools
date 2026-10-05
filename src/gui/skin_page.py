# -*- coding: utf-8 -*-
"""皮肤页面 —— 左侧边栏点「皮肤」，**右侧以卡片形式**展示所有皮肤。

## 用户要求（2026-10-05）

    1. "皮肤加在左侧边栏，不是左下角"        ← 做成侧栏一个**导航项**
    2. "右边显示所有的皮肤，以卡片的形式展示"  ← 右侧页面 = 卡片网格
    3. "以DSH这个主题皮肤为例（液态玻璃主题）" ← 卡片本身也要玻璃感

## ⚠⚠ 上一版的 bug：预览条画不出来

预览条用 ``s['bg']`` 直接拼进 QSS —— 而 ``bg`` 现在是**渐变的
stop 列表** ``[(0.0, '#0B1026'), ...]``，拼出来是::

    stop:0 [(0.0, '#0B1026'), (0.45, '#141A38'), (1.0, '#0A0E1F')]

**整个 Python 列表被当字符串塞进去了** —— QSS 解析失败，
预览条和卡片背景**全画不出来**（实测截图：卡片区域是纯灰）。

→ 现在统一走 :func:`src.core.skins.gradient_qss` 拼。

## 一张卡片长什么样

::

    ┌───────────────────────────┐
    │  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓  │  ← 预览条（真的画该皮肤的渐变）
    │  深空玻璃          [使用中] │
    │  DSH 同款：深邃蓝黑渐变…    │
    │  ● #4A9EFF                │  ← 主色点
    │  ┌─────────────────────┐  │
    │  │      使用这款        │  │
    │  └─────────────────────┘  │
    └───────────────────────────┘
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .compat import ScrollArea
from ..core import skins

logger = logging.getLogger(__name__)

#: 卡片宽度
CARD_WIDTH = 268
#: 预览条高度
PREVIEW_H = 88
#: 一行几张
PER_ROW = 3


class SkinCard(QWidget):
    """一款皮肤的卡片（预览 + 名字 + 说明 + 主色 + 使用按钮）。"""

    chosen = Signal(str)                       #: 皮肤 id

    def __init__(self, skin: dict, *, active: bool = False, parent=None):
        super().__init__(parent)
        self._skin = skin
        self._is_active = bool(active)          #: 测试要看这个
        self.setObjectName("skinCard")
        self.setFixedWidth(CARD_WIDTH)
        self._build(active)

    def _build(self, active: bool) -> None:
        s = self._skin
        #: ★★★ 卡片上的**文字**用**当前生效皮肤**的颜色，不是被预览那个。
        #:
        #: ⚠⚠ 这里踩过坑：一开始用 ``s['text']``（被预览皮肤的文字色）——
        #: 深色皮肤的文字是**浅色**，画在**当前皮肤**（也许是浅色）的页面底上
        #: → **字几乎看不见**（用户截图里「深空玻璃」那几款就是这个）。
        #:
        #: 道理很简单：卡片坐落在**当前皮肤的页面**上，
        #: 文字对比度该跟**页面**算，不该跟预览条算。
        ui = skins.current_skin()
        box = QVBoxLayout(self)
        box.setContentsMargins(14, 14, 14, 14)
        box.setSpacing(9)

        #: ── ① 预览条：**真的画这个皮肤的渐变**
        #:
        #: ⚠ 必须用 ``gradient_qss`` 拼 —— 直接把 ``bg``（列表）
        #: 塞进 QSS 会解析失败、什么都画不出来（上一版的 bug）。
        preview = QWidget(self)
        preview.setObjectName("skinPreview")
        preview.setFixedHeight(PREVIEW_H)
        preview.setStyleSheet(
            f"#skinPreview {{"
            f" background: {skins.gradient_qss(s)};"
            f" border-radius: 8px;"
            f" border: 1px solid {s['border']}; }}")
        box.addWidget(preview)

        #: ── ② 名字 + 「使用中」
        row = QHBoxLayout()
        row.setSpacing(6)
        name = QLabel(s["name"], self)
        name.setStyleSheet(
            f"font-size: 15px; font-weight: bold; color: {ui['text']};")
        row.addWidget(name)
        row.addStretch(1)
        if active:
            badge = QLabel("使用中", self)
            badge.setObjectName("skinBadge")
            badge.setStyleSheet(
                f"#skinBadge {{ background: {s['primary']}; color: #ffffff;"
                f" font-size: 11px; font-weight: bold;"
                f" padding: 2px 9px; border-radius: 9px; }}")
            row.addWidget(badge)
        box.addLayout(row)

        #: ── ③ 说明（用**当前皮肤**的次要色 —— 见上面 ui 的说明）
        desc = QLabel(s.get("desc") or "", self)
        desc.setWordWrap(True)
        desc.setMinimumHeight(34)               #: 高度对齐，卡片不会参差
        desc.setStyleSheet(f"font-size: 12px; color: {ui['dim']};")
        box.addWidget(desc)

        #: ── ④ 主色点 + 色值
        color_row = QHBoxLayout()
        color_row.setSpacing(7)
        dot = QLabel(self)
        dot.setFixedSize(14, 14)
        dot.setStyleSheet(
            f"background: {s['primary']}; border-radius: 7px;")
        color_row.addWidget(dot)
        hexlab = QLabel(s["primary"].upper(), self)
        hexlab.setStyleSheet(
            f"font-size: 11px; color: {ui['dim']};"
            f" font-family: Consolas, monospace;")
        color_row.addWidget(hexlab)
        color_row.addStretch(1)
        box.addLayout(color_row)

        #: ── ⑤ 按钮
        btn = QPushButton("使用中" if active else "使用这款", self)
        btn.setObjectName("skinUseBtn")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setEnabled(not active)
        if active:
            #: ⚠ 边框/文字也要用**当前皮肤**的色（用被预览皮肤的会糊在一起）
            btn.setStyleSheet(
                f"#skinUseBtn {{ font-size: 12px; padding: 7px 0;"
                f" border-radius: 6px; background: transparent;"
                f" border: 1px solid {ui['border']}; color: {ui['dim']}; }}")
        else:
            btn.setStyleSheet(
                f"#skinUseBtn {{ font-size: 12px; padding: 7px 0;"
                f" border-radius: 6px; border: none;"
                f" background: {s['primary']}; color: #ffffff;"
                f" font-weight: bold; }}")
        btn.clicked.connect(lambda: self.chosen.emit(s["id"]))
        box.addWidget(btn)

        #: ── 卡片本身：半透明玻璃 + 浅色细边
        #: （选中的用主色描边，一眼看出是哪个）
        accent = s["primary"] if active else s["border"]
        self.setStyleSheet(
            f"#skinCard {{ border-radius: 12px;"
            f" border: 2px solid {accent};"
            f" background: {s['card']}; }}")


class SkinInterface(ScrollArea):
    """★ 皮肤页面（侧栏导航项 → 右边整页卡片）。

    ## ⚠ 必须继承 ``ScrollArea`` 并 ``setWidget(view)``

    我第一版做成裸 ``QWidget`` —— 结果**整页不显示**（实测
    ``100x30``、``isVisible()=False``，切过去了也是空白）。

    这是本项目的**固定写法**（HomeInterface / ConfigInterface /
    TasksInterface 都一样）::

        self.setWidget(view)          # 内层 view 交给滚动区托管
        self.setWidgetResizable(True) # 跟着窗口伸缩
        setAttribute(WA_StyledBackground, True)
        setStyleSheet("#XxxInterface { background: transparent; }")
        self.viewport().setStyleSheet("background: transparent;")

    ⚠ 少写 ``setWidget`` 的话，内层控件就"浮在滚动区上"，
    尺寸不受布局管理、整页被压扁。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SkinInterface")
        self.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._cards: list[SkinCard] = []

        view = QWidget(self)
        view.setObjectName("skinView")
        layout = QVBoxLayout(view)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(8)

        title = QLabel("皮肤", view)
        title.setStyleSheet("font-size: 22px; font-weight: bold;")
        layout.addWidget(title)

        s = skins.current_skin()
        hint = QLabel(
            "液态玻璃主题 —— 点「使用这款」立刻生效，下次打开还是它。",
            view)
        hint.setStyleSheet(f"font-size: 13px; color: {s['dim']};")
        layout.addWidget(hint)
        layout.addSpacing(10)

        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(16)
        layout.addLayout(grid)
        layout.addStretch(1)
        self._grid = grid

        #: ⚠ 跟其它页面一样 —— 不写这几行整页不显示（见类文档）
        self.setWidget(view)
        self.setWidgetResizable(True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("#SkinInterface { background: transparent; }")
        self.viewport().setStyleSheet("background: transparent;")

        self.refresh()

    def refresh(self) -> None:
        """按当前皮肤重画卡片（「使用中」标记要跟着变）。"""
        for c in self._cards:
            c.setParent(None)
            c.deleteLater()
        self._cards.clear()

        current = skins.current_skin()["id"]
        for i, s in enumerate(skins.all_skins()):
            card = SkinCard(s, active=(s["id"] == current), parent=self)
            card.chosen.connect(self._on_chosen)
            self._grid.addWidget(card, i // PER_ROW, i % PER_ROW)
            self._cards.append(card)

    def _on_chosen(self, skin_id: str) -> None:
        if skins.apply_skin(skin_id):
            self.refresh()
            #: ⚠ 换肤后 QSS 是新的 —— 让其它已开窗口也跟上
            skins.refresh_windows()


def build_skin_page(parent=None) -> SkinInterface:
    """给侧栏用的皮肤页面。"""
    return SkinInterface(parent)
