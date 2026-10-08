"""可复用的界面组件：工具卡片网格、配置卡片、占位面板。

这些组件只认数据是 ToolMeta，不认具体工具实现——这样工具坏了也不会波及主页。
卡片是"块状"的：上面图标、下面名称，鼠标悬浮时补一行小字说明。
"""

from __future__ import annotations

import os

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QDoubleValidator, QIcon
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


def tool_icon_of(meta: ToolMeta) -> QIcon:
    """工具图标 → **QIcon**（统一类型，别混着给）。

    ⚠ 以前两种返回类型混着：有 ``icon_path`` 时给 ``QIcon``，否则给
    ``FluentIcon``。调用方只要把它塞进**只认 QIcon** 的地方
    （``QListWidgetItem.setIcon()`` / ``QIcon(path)`` 之类）就会 TypeError。

    以前任务编排里只列**一个**工具，恰好它有 ``icon_path``，所以一直没暴露；
    2026-09-26 改成列出全部工具之后当场就炸了（``setIcon(FluentIcon)``）。
    """
    path = (getattr(meta, "icon_path", "") or "").strip()
    if path and os.path.exists(path):
        return QIcon(path)
    return resolve_icon(meta.icon_name, "APPLICATION").icon()


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
    """主页里的一张工具卡片：上面图标、下面名称，说明只在鼠标悬浮时以小字提示弹出。

    ## ⚠⚠⚠ 底色**必须自己管**（用户 2026-10-08 截图）

        用户（截图圈出整片卡片区）："我怎么鼠标已过去他才变色？"

    截图里**同一排卡片一半灰白、一半深紫** —— 划过的才变深。

    ## 根因：``SimpleCardWidget`` 的底色看的是 **qfluentwidgets 的主题**，
    ## 不是我们的皮肤

    ::

        def _normalBackgroundColor(self):
            return QColor(255, 255, 255, 13 if isDarkTheme() else 170)
                                          ↑ 深色        ↑ 浅色（几乎不透明白 = 灰）

    而 ``isDarkTheme()`` **只在两个时刻被读**：

      · **创建时** —— 但 ``main.py`` 那时是 ``setTheme(Theme.AUTO)``
        （按**系统**明暗；用户系统是浅色 → 取到 170 → **灰白**）
      · **鼠标进出时**（``enterEvent`` → ``_updateBackgroundColor``）

    ``apply_current_skin()`` 之后才切深色主题 —— 但**卡片不会重画**。

    实测::

        建卡片时 alpha = 170（灰白，叠在紫底上 ≈ #b1afb9）
        切深色后    alpha 仍是 170   ← 没跟着变
        鼠标划过    alpha 才变 13（≈ #211a39，深紫）

    ## 修法：底色**从皮肤取**，并在换肤时重取

    ``skin["card"]``（半透明）+ ``skin["border"]`` 就是为这个准备的。
    换肤时由 ``refresh_skin_colors()`` 回收（``skins._notify_custom_widgets``
    会自动调它，不用注册）。
    """

    #: 悬浮提示的延迟（毫秒）。Qt 默认要等 700ms 才弹，太慢，这里压到 120。
    TOOLTIP_DELAY = 120

    def __init__(self, meta: ToolMeta, parent=None):
        super().__init__(parent)
        self.meta = meta
        self.setClickEnabled(True)
        self.setFixedSize(CARD_WIDTH, CARD_HEIGHT)
        #: ★ 底色跟皮肤（覆盖基类那两个方法，见类文档）
        self._refresh_card_colors()

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

    #: ── ★ 底色跟**皮肤**，不跟 qfluentwidgets 的全局主题 ─────────────
    def _refresh_card_colors(self) -> None:
        """从当前皮肤取底色（``skins`` 换了之后由回调再调一次）。"""
        try:
            from ..core import skins

            skin = skins.active_skin()
            self._card_color = QColor(255, 255, 255, 0)   #: 占位，下面覆盖
            self._bg_rgba = skin["card"]
            self._border_rgba = skin["border"]
        except Exception:  # noqa: BLE001 - 皮肤读不到就别拦着建卡片
            self._bg_rgba = "rgba(255, 255, 255, 0.06)"
            self._border_rgba = "rgba(255, 255, 255, 0.16)"
        self._updateBackgroundColor()

    @staticmethod
    def _to_qcolor(text: str) -> QColor:
        """解析 ``rgba(...)`` / ``#rrggbb`` → ``QColor``（**带 alpha**）。

        ⚠ 不能用 ``QColor("rgba(...)")`` —— 实测它解析不出来、返回**黑色**。
        """
        from ..core import skins

        parsed = skins.parse_color(text)
        if parsed is None:
            return QColor(255, 255, 255, 16)
        r, g, b, a = parsed
        return QColor(r, g, b, round(a * 255))

    def _normalBackgroundColor(self) -> QColor:
        """正常态底色 —— 皮肤的卡片色。"""
        return self._to_qcolor(getattr(self, "_bg_rgba", ""))

    def _hoverBackgroundColor(self) -> QColor:
        """悬浮态 —— **比正常态亮一点**（让鼠标划过去有反馈）。

        ⚠ 基类这里返回的是**和正常态一样**的值（``return self._normalBackgroundColor()``）
        —— 所以我们自己做一点区分，否则"划过去没反应"。
        """
        base = self._normalBackgroundColor()
        return QColor(min(255, base.red() + 18),
                      min(255, base.green() + 18),
                      min(255, base.blue() + 22),
                      min(255, base.alpha() + 26))

    def _pressedBackgroundColor(self) -> QColor:
        """按下态 —— 再亮一点。"""
        base = self._normalBackgroundColor()
        return QColor(min(255, base.red() + 30),
                      min(255, base.green() + 30),
                      min(255, base.blue() + 36),
                      min(255, base.alpha() + 44))

    def refresh_skin_colors(self) -> None:
        """★ 换肤后重取底色 —— ``skins._notify_custom_widgets`` 会自动调。"""
        self._refresh_card_colors()
        self.update()

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
