""""版本兼容层"：把对第三方组件库的不确定性关在这一个文件里。

PyQt/PySide-Fluent-Widgets 各版本导出的名字有出入（图标名、标签类名都变过）。
这里用 getattr 做安全取值，缺哪个就退回 Qt 原生控件——目标是"装完依赖就能跑"，
而不是在某个 getattr 上空指针崩掉。
"""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QLineEdit, QTreeWidget

import qfluentwidgets as qfw
from qfluentwidgets import FluentIcon as FIF

# --------------------------------------------------------------------- 控件类
TitleLabel = getattr(qfw, "TitleLabel", QLabel)
SubtitleLabel = getattr(qfw, "SubtitleLabel", QLabel)
StrongBodyLabel = getattr(qfw, "StrongBodyLabel", QLabel)
BodyLabel = getattr(qfw, "BodyLabel", QLabel)
CaptionLabel = getattr(qfw, "CaptionLabel", QLabel)
SearchLineEdit = getattr(qfw, "SearchLineEdit", QLineEdit)
# Fluent 版树控件：Qt 原生 QTreeWidget 会吃系统调色板，在深色系统上变黑底，
# 和浅色窗口对不上，所以优先用它。
TreeWidget = getattr(qfw, "TreeWidget", QTreeWidget)

__all__ = [
    "FIF",
    "TitleLabel",
    "SubtitleLabel",
    "StrongBodyLabel",
    "BodyLabel",
    "CaptionLabel",
    "SearchLineEdit",
    "TreeWidget",
    "resolve_icon",
]

# --------------------------------------------------------------------- 图标
# FluentIcon 在不同版本里增减过成员，同名图标不一定存在。
# 每个逻辑图标给一串候选名，按顺序取第一个存在的。
_ICON_CANDIDATES: dict[str, tuple[str, ...]] = {
    "HOME": ("HOME", "HOME_FILL", "APPLICATION"),
    "TOOLS": ("TOOLS", "WRENCH", "DEVELOPER_TOOLS", "APPLICATION"),
    "GAME": ("GAME", "GAMEPAD", "PLAY", "JOYSTICK", "APPLICATION"),
    "DOCUMENT": ("DOCUMENT", "FILE", "TEXT_COMPARE", "FOLDER"),
    "APPLICATION": ("APPLICATION",),
    "SEARCH": ("SEARCH", "SEARCH_MIRROR", "VIEW"),
    "INFO": ("INFO", "INFO_FILL", "QUESTION"),
    "TILES": ("TILES", "GRID", "VIEW"),
    "SETTING": ("SETTING", "SETTINGS", "APPLICATION"),
    "CHECK": ("CHECK", "ACCEPT", "COMPLETED"),
    "LIBRARY": ("LIBRARY", "BOOK_SHELF", "ALBUM", "DICTIONARY", "FOLDER"),
    "DATABASE": ("DATABASE", "CLOUD", "APPLICATION"),
    "UPDATE": ("UPDATE", "SYNC", "DOWNLOAD", "APPLICATION"),
    "TASK": ("BOOK_INDEX", "APPOINTMENT", "CALENDAR", "LIBRARY", "APPLICATION"),
    "PANEL_COLLAPSED": ("CHEVRON_DOWN_MED", "ARROW_DOWN", "DOWN", "APPLICATION"),
    "PANEL_EXPANDED": ("UP", "CARE_UP_SOLID", "CHEVRON_DOWN_MED", "APPLICATION"),
}

_LAST_RESORT = "APPLICATION"


def resolve_icon(name: str, default: str = _LAST_RESORT):
    """把图标"名字"解析成 FluentIcon 成员，缺了就降级，永不抛异常。"""
    for candidate in _ICON_CANDIDATES.get(name, (name, default)):
        icon = getattr(FIF, candidate, None)
        if icon is not None:
            return icon
    return getattr(FIF, _LAST_RESORT, None)
