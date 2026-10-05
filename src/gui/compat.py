""""版本兼容层"：把对第三方组件库的不确定性关在这一个文件里。

PyQt/PySide-Fluent-Widgets 各版本导出的名字有出入（图标名、标签类名都变过）。
这里用 getattr 做安全取值，缺哪个就退回 Qt 原生控件——目标是"装完依赖就能跑"，
而不是在某个 getattr 上空指针崩掉。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QLabel, QLineEdit, QSizePolicy, QTreeWidget

import qfluentwidgets as qfw
from qfluentwidgets import FluentIcon as FIF

# --------------------------------------------------------------------- 控件类
TitleLabel = getattr(qfw, "TitleLabel", QLabel)
SubtitleLabel = getattr(qfw, "SubtitleLabel", QLabel)
StrongBodyLabel = getattr(qfw, "StrongBodyLabel", QLabel)
BodyLabel = getattr(qfw, "BodyLabel", QLabel)
CaptionLabel = getattr(qfw, "CaptionLabel", QLabel)
SearchLineEdit = getattr(qfw, "SearchLineEdit", QLineEdit)
#: ★ 页面基类（ScrollArea）—— 侧栏页面都要用它 + ``setWidget(view)``，
#: 用裸 ``QWidget`` 整页不显示（皮肤页第一版踩过）
ScrollArea = getattr(qfw, "ScrollArea", __import__(
    "PySide6.QtWidgets", fromlist=["QScrollArea"]).QScrollArea)
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
    "ScrollArea",
    "TreeWidget",
    "ElidedLabel",
    "resolve_icon",
    "app_icon",
]


class ElidedLabel(QLabel):
    """**单行 + 超宽省略号**的标签，鼠标悬停能看到全名。

    给「头像 + 名字」那类行用：名字一旦比左列宽，Qt 的默认行为要么把控件撑大
    （把摘要/按钮挤变形），要么自动换行到第 2、3 行（**把行高撑破**）。
    2026-09-26 用户截图就是这个：名字长了之后三行字把行撑高、头像位置被挤掉。

    两个关键点，少一个都会失效：

    1. ``setFixedWidth`` —— 宽度由调用方钉死，标签**不许**按文字长度自我膨胀；
    2. 水平 sizePolicy 设成 ``Ignored`` —— 否则布局仍会拿 ``sizeHint``（＝整串文字的
       宽度）去分配空间，钉死的宽度在父布局里照样被撑开。
    """

    def __init__(self, text: str = "", parent=None, *, width: int | None = None,
                 align=None):
        super().__init__(parent)
        self._full = ""
        self.setWordWrap(False)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        if width is not None:
            self.setFixedWidth(int(width))
        if align is not None:
            self.setAlignment(align)
        self.setText(text)

    # ------------------------------------------------------------------ 文本
    def setText(self, text: str) -> None:  # noqa: N802 - Qt 命名
        self._full = str(text or "")
        # 省略号之后看不全，悬停给全名
        self.setToolTip(self._full)
        self._apply_elide()

    def fullText(self) -> str:
        """未被省略的原文（测试与 tooltip 用）。"""
        return self._full

    def text(self) -> str:  # noqa: N802 - Qt 命名
        """⚠ 返回的是**省略后**的字面文本（和基类语义一致）。要原文用 fullText()。"""
        return super().text()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt 回调
        super().resizeEvent(event)
        self._apply_elide()

    def _apply_elide(self) -> None:
        metrics = QFontMetrics(self.font())
        avail = max(0, self.width())
        # 宽度还没定下来（布局前是 100）时先按原样放，resizeEvent 会再纠正一次
        super().setText(metrics.elidedText(
            self._full, Qt.TextElideMode.ElideRight, avail))


def app_icon():
    """应用图标（``assets/app.ico``），拿不到就返回空 QIcon。

    ⚠ 2026-09-25 之前**没有任何地方调用它** —— 项目里明明生成了 app.ico
    （``tools/make_app_icon.py``，蓝底圆角 + 工具字形），但 ``QApplication``
    和主窗口都没设图标，于是**任务栏显示的是 python.exe 的默认图标**。
    这个函数就是让"设应用图标"只有一处实现，别各处再各写一遍路径拼接。

    不抛异常：图标是锦上添花，拿不到不该挡住启动。空 QIcon 的 ``isNull()``
    为真，调用方（如 ``tray.make_tray``）会退回 fluent 自带图标。
    """
    from PySide6.QtGui import QIcon

    from ..core import paths

    try:
        path = paths.resource_dir("assets", "app.ico")
        if path.is_file():
            return QIcon(str(path))
    except Exception:  # noqa: BLE001 - 取不到就当没有
        pass
    return QIcon()

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
    #: ★ 皮肤（用户 2026-10-05："皮肤加在左侧边栏"）
    "SKIN": ("PALETTE", "BRUSH", "CONSTRACT", "COLOR", "APPLICATION"),
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
