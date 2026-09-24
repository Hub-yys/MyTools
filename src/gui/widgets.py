"""可复用的界面组件：工具卡片网格、配置卡片、占位面板。

这些组件只认数据是 ToolMeta，不认具体工具实现——这样工具坏了也不会波及主页。
卡片是"块状"的：上面图标、下面名称，鼠标悬浮时补一行小字说明。
"""

from __future__ import annotations

import os

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QDoubleValidator, QIcon
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    CardWidget,
    FluentIcon,
    IconWidget,
    LineEdit,
    SimpleCardWidget,
    StrongBodyLabel,
    SubtitleLabel,
    ToolButton,
    ToolTipFilter,
)

from ..app_config import (
    CARD_GRID_COLUMNS,
    CARD_GRID_SPACING,
    CARD_HEIGHT,
    CARD_ICON_SIZE,
    CARD_WIDTH,
)
from ..core.tool_base import ToolMeta
from .compat import BodyLabel, CaptionLabel, StrongBodyLabel, SubtitleLabel, TitleLabel, resolve_icon


def tool_icon_of(meta: ToolMeta):
    """把 meta 的图标解析成 icon 对象（导航栏 / 按钮用，不是控件）。"""
    path = (getattr(meta, "icon_path", "") or "").strip()
    if path and os.path.exists(path):
        return QIcon(path)
    return resolve_icon(meta.icon_name, "APPLICATION")


def build_tool_icon(meta: ToolMeta, size: int, parent: QWidget) -> QWidget:
    """工具的图标控件：优先用 ``meta.icon_path`` 指定的图片，否则用 Fluent 图标。"""
    path = (getattr(meta, "icon_path", "") or "").strip()
    if path and os.path.exists(path):
        widget = IconWidget(QIcon(path), parent)
    else:
        widget = IconWidget(resolve_icon(meta.icon_name, "APPLICATION"), parent)
    widget.setFixedSize(QSize(size, size))
    return widget


class ToolCard(SimpleCardWidget):
    """主页里的一张工具卡片：上面图标、下面名称，说明只在鼠标悬浮时以小字提示弹出。"""

    #: 悬浮提示的延迟（毫秒）。Qt 默认要等 700ms 才弹，太慢，这里压到 120。
    TOOLTIP_DELAY = 120

    def __init__(self, meta: ToolMeta, parent=None):
        super().__init__(parent)
        self.meta = meta
        self.setClickEnabled(True)
        self.setFixedSize(CARD_WIDTH, CARD_HEIGHT)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 16, 8, 14)
        root.setSpacing(8)

        root.addWidget(build_tool_icon(meta, CARD_ICON_SIZE, self), 0, Qt.AlignmentFlag.AlignHCenter)

        name = StrongBodyLabel(meta.name, self)
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name.setWordWrap(True)
        root.addWidget(name)

        root.addStretch(1)

        # 说明不常驻卡片，改成悬浮小字提示。ToolTipFilter 才能调延迟，
        # 光 setToolTip() 走的是系统默认延迟（很慢）。
        if meta.description:
            self.setToolTip(meta.description)
            self.installEventFilter(ToolTipFilter(self, self.TOOLTIP_DELAY))

        self._badge = ComingSoonBadge(self) if meta.coming_soon else None

    def resizeEvent(self, event):  # noqa: N802 - Qt 回调
        super().resizeEvent(event)
        if self._badge is not None:
            self._badge.move(self.width() - self._badge.width() - 8, 8)


class ComingSoonBadge(QLabel):
    """右上角的小角标。用 QLabel 手搓，省一个资源依赖。"""

    def __init__(self, parent=None):
        super().__init__("规划中", parent)
        self.setFixedSize(48, 18)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(
            "color: #0F6E56; background: rgba(29, 158, 117, 0.14);"
            "border-radius: 4px; font-size: 11px;"
        )


class ToolGrid(QWidget):
    """一组工具卡片（块状网格），**不带分类标题**。

    主页直接用它平铺所有工具（2026-09-24 起取消分类分组）。
    原来的 ``CategorySection`` / ``SectionHeader`` 一并删除 —— 留着容易被下一个
    人重新拿去按分类铺主页。
    """

    toolClicked = Signal(str)

    def __init__(self, metas: list[ToolMeta], parent=None):
        super().__init__(parent)

        grid = QGridLayout(self)
        grid.setSpacing(CARD_GRID_SPACING)
        grid.setContentsMargins(0, 0, 0, 0)

        columns = max(1, CARD_GRID_COLUMNS)
        for index, meta in enumerate(metas):
            card = ToolCard(meta, self)
            card.clicked.connect(lambda checked=False, key=meta.key: self.toolClicked.emit(key))
            grid.addWidget(card, index // columns, index % columns)

        # 卡片按左上角对齐，右侧多余空间留白，不做拉伸（否则卡片会变形）
        grid.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)


class ComingSoonWidget(QWidget):
    """工具的默认面板。工具没写界面时用它顶上，永远不会是白板。"""

    def __init__(self, meta: ToolMeta, parent=None):
        super().__init__(parent)
        container = CardWidget(self)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(40, 36, 40, 36)
        layout.setSpacing(14)

        layout.addWidget(build_tool_icon(meta, 48, container), 0, Qt.AlignmentFlag.AlignHCenter)

        title = TitleLabel(meta.name, container)
        title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(title)

        tip = BodyLabel("功能建设中，敬请期待", container)
        tip.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        tip.setTextColor("#8A8F98", "#7C7C7C")
        layout.addWidget(tip)

        line = QFrame(container)
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("background: rgba(255,255,255,0.08);")
        layout.addWidget(line)

        for key, value in (
            ("分类", meta.category.display_name),
            ("标识", meta.key),
            ("描述", meta.description or "—"),
        ):
            row = QHBoxLayout()
            row.addWidget(CaptionLabel(key, container))
            row.addStretch(1)
            value_label = CaptionLabel(value, container)
            value_label.setTextColor("#8A8F98", "#7C7C7C")
            row.addWidget(value_label)
            layout.addLayout(row)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(container)
        outer.addStretch(1)


def _fmt_number(value: float, decimals: int = 2) -> str:
    """按字段自己的精度显示，去掉多余的零。

    ⚠ 这里原来写死 ``f"{value:.1f}"`` —— 一位小数。对"暴击下限 7.5"够用，
    但检测区域（0.22）和阈值（0.015）会被**四舍五入吃掉**：
    ``0.22`` 显示成 ``0.2``、``0.015`` 显示成 ``0.0``，改完直接失真。
    现在按 ``decimals`` 格式化，再裁掉末尾多余的零（``0.100`` → ``0.1``），
    整数保留一位小数（``15.00`` → ``15.0``，和以前的观感一致）。
    """
    text = f"{value:.{decimals}f}"
    if "." in text:
        text = text.rstrip("0")
        if text.endswith("."):
            text += "0"
    return text


class NumberStepper(QWidget):
    """加减按钮 + 整数数值。``changed`` 用来把设置存盘。

    这几个控件原来住在 ``echo_enhance/tool.py``；新工具（4C 自动战斗）也要用
    同一套，2026-09-23 挪到这里，名字保持不变。
    """

    #: 值变了
    changed = Signal()

    def __init__(self, minimum: int, maximum: int, value: int, parent=None):
        super().__init__(parent)
        self.minimum = minimum
        self.maximum = maximum
        self._value = value

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.minus = ToolButton(FluentIcon.REMOVE, self)
        self.minus.setFixedSize(30, 30)
        self.minus.clicked.connect(lambda: self.set_value(self._value - 1))

        self.label = StrongBodyLabel(str(value), self)
        self.label.setFixedWidth(28)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.plus = ToolButton(FluentIcon.ADD, self)
        self.plus.setFixedSize(30, 30)
        self.plus.clicked.connect(lambda: self.set_value(self._value + 1))

        layout.addWidget(self.minus)
        layout.addWidget(self.label)
        layout.addWidget(self.plus)
        self._sync_buttons()

    def value(self) -> int:
        return self._value

    def set_value(self, value: int, *, emit: bool = True) -> None:
        """设值（越界夹回）。``emit=False`` 用于"外面正在同步、不想再触发一次存盘"。

        （``_save_settings`` 里是**先**同步**再**收集设置，所以静默设值同样会被存下来。）
        """
        before = self._value
        self._value = max(self.minimum, min(self.maximum, value))
        self.label.setText(str(self._value))
        self._sync_buttons()
        if emit and self._value != before:
            self.changed.emit()

    def set_range(self, minimum: int, maximum: int, *, emit: bool = True) -> None:
        """改可取值范围；当前值越界会被夹回范围里。

        ``emit=False`` 给"外面正在同步范围"的场合用 —— 否则
        ``set_range → changed → 存盘 → 再同步`` 会绕回来
        （见声骸强化页 ``_sync_valid_count``）。
        """
        self.minimum = minimum
        self.maximum = maximum
        clamped = max(minimum, min(maximum, self._value))
        if clamped != self._value:
            self._value = clamped
            self.label.setText(str(clamped))
            if emit:
                self.changed.emit()
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        self.minus.setEnabled(self._value > self.minimum)
        self.plus.setEnabled(self._value < self.maximum)


class NumberField(QWidget):
    """[−] [可编辑数值] [+]。

    两侧按钮按固定步长增减，也可以直接在框里敲数值。
    框里是空值/非法内容时，``value()`` 退回上一次的有效值，不会把判定搞崩。
    """

    #: 值变了（敲字或点加减）—— 用来存盘
    changed = Signal()

    def __init__(
        self,
        value: float,
        parent=None,
        *,
        step: float = 1.0,
        minimum: float = 0.0,
        maximum: float = 100.0,
        decimals: int = 2,
    ):
        super().__init__(parent)
        self.step = step
        self.minimum = minimum
        self.maximum = maximum
        self._decimals = decimals
        self._last = self._clamp(value)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.minus = ToolButton(FluentIcon.REMOVE, self)
        self.minus.setFixedSize(30, 30)
        self.minus.clicked.connect(lambda: self.set_value(self.value() - self.step))

        self.edit = LineEdit(self)
        self.edit.setFixedWidth(76)
        self.edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.edit.setValidator(QDoubleValidator(self.minimum, self.maximum, decimals, self))
        self.edit.setText(_fmt_number(self._last, decimals))
        self.edit.textEdited.connect(self._remember)

        self.plus = ToolButton(FluentIcon.ADD, self)
        self.plus.setFixedSize(30, 30)
        self.plus.clicked.connect(lambda: self.set_value(self.value() + self.step))

        layout.addWidget(self.minus)
        layout.addWidget(self.edit)
        layout.addWidget(self.plus)

    def value(self) -> float:
        """当前数值；框里不是数字时退回上一次的有效值。"""
        try:
            return round(self._clamp(float(self.edit.text().strip())), self._decimals)
        except ValueError:
            return self._last

    def set_value(self, value: float) -> None:
        self._last = self._clamp(value)
        self.edit.setText(_fmt_number(self._last, self._decimals))
        self.changed.emit()

    def _remember(self, text: str) -> None:
        try:
            before = self._last
            self._last = self._clamp(float(text.strip()))
            if self._last != before:
                self.changed.emit()
        except ValueError:
            pass

    def _clamp(self, value: float) -> float:
        return max(self.minimum, min(self.maximum, value))


class ConfigCard(CardWidget):
    """带标题和说明的配置卡片。``header_widget`` 会摆到标题行右侧（不占额外一行）。"""

    def __init__(
        self,
        title: str,
        hint: str = "",
        parent=None,
        header_widget: QWidget | None = None,
    ):
        super().__init__(parent)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(20, 16, 20, 18)
        self.body.setSpacing(8)

        header = QWidget(self)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(10)
        header_layout.addWidget(SubtitleLabel(title, self))
        if header_widget is not None:
            # 紧跟标题放（不推到最右边）
            header_layout.addWidget(header_widget)
        header_layout.addStretch(1)
        self.body.addWidget(header)

        if hint:
            label = CaptionLabel(hint, self)
            label.setTextColor("#8A8F98", "#7C7C7C")
            label.setWordWrap(True)
            self.body.addWidget(label)

    def add(self, widget: QWidget) -> None:
        self.body.addWidget(widget)


class CollapsibleCard(CardWidget):
    """可折叠的配置卡片：标题行右侧一个箭头，内容默认收起。

    ``add()`` 进去的东西放进内容区；``summary_label`` 是收起时也一直可见的摘要行，
    所以折叠状态下也能看到"当前选了什么"。
    """

    def __init__(
        self,
        title: str,
        hint: str = "",
        summary: str = "",
        expanded: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self._expanded = expanded

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 14, 20, 16)
        root.setSpacing(8)

        header = QWidget(self)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)
        header_layout.addWidget(SubtitleLabel(title, header))
        header_layout.addStretch(1)

        self.toggle_button = ToolButton(resolve_icon("PANEL_COLLAPSED"), header)
        self.toggle_button.setFixedSize(28, 28)
        self.toggle_button.setToolTip("展开 / 收起")
        self.toggle_button.clicked.connect(self.toggle)
        header_layout.addWidget(self.toggle_button)
        root.addWidget(header)

        if hint:
            hint_label = CaptionLabel(hint, self)
            hint_label.setTextColor("#8A8F98", "#7C7C7C")
            hint_label.setWordWrap(True)
            root.addWidget(hint_label)

        self.summary_label = CaptionLabel(summary, self)
        self.summary_label.setTextColor("#8A8F98", "#7C7C7C")
        self.summary_label.setWordWrap(True)
        root.addWidget(self.summary_label)

        self.content = QWidget(self)
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 6, 0, 0)
        self.content_layout.setSpacing(8)
        self.content.setVisible(expanded)
        root.addWidget(self.content)

        self._sync_button()

    # ------------------------------------------------------------------ 行为
    def add(self, widget: QWidget) -> None:
        """加到内容区（收起时一并隐藏）。"""
        self.content_layout.addWidget(widget)

    def set_summary(self, text: str) -> None:
        self.summary_label.setText(text)

    def toggle(self) -> None:
        self.set_expanded(not self._expanded)

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = expanded
        self.content.setVisible(expanded)
        self._sync_button()

    @property
    def is_expanded(self) -> bool:
        return self._expanded

    def _sync_button(self) -> None:
        icon = resolve_icon("PANEL_EXPANDED" if self._expanded else "PANEL_COLLAPSED")
        self.toggle_button.setIcon(icon)
