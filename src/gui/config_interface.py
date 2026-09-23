"""配置页：一条一条列出已保存的配置，每条可查看详情 / 修改 / 删除，左上角新增。

数据全在 :class:`~src.core.loadout.LoadoutStore` 里（本地 JSON），
所以"改完刷新列表"就是重新读一遍存储，没有别的状态要同步。
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget
from qfluentwidgets import (
    FluentIcon,
    IconWidget,
    MessageBox,
    PrimaryPushButton,
    PushButton,
    ScrollArea,
    SimpleCardWidget,
    StrongBodyLabel,
)

from ..core.loadout import Loadout, LoadoutStore
from .compat import CaptionLabel, TitleLabel, resolve_icon
from .loadout_dialog import LoadoutDetailDialog, LoadoutDialog
from .pickers import load_icon

#: 行内边距 / 元素间距
ROW_PADDING = 16
ROW_SPACING = 16
#: 左侧「头像 + 名字」那一列的宽度（名字在头像**下面**）
ROW_LEFT_WIDTH = 88
ROW_AVATAR_SIZE = 48
#: 右边三个按钮
ROW_BUTTON_WIDTH = 72
#: 行高下限 —— 左侧身份列本身就有这么高（头像 48 + 名字一行 + 内边距）
ROW_MIN_HEIGHT = 92

#: 整行里除摘要之外占掉的宽度（行内边距 + 左列 + 三个按钮 + 它们之间的间距）
_ROW_CHROME = (
    ROW_PADDING * 2
    + ROW_LEFT_WIDTH
    + ROW_BUTTON_WIDTH * 3
    + ROW_SPACING * 4          # 一行 5 个子项之间正好 4 个间距
)
#: 页面左右边距 + 给竖向滚动条留的余量
_PAGE_CHROME = 36 * 2 + 16


class LoadoutRow(SimpleCardWidget):
    """列表里的一条：左边「头像 + 名字（名字在下面）」，中间摘要，右边三个操作。

    摘要**居中显示、超长自动换行**。行高跟着摘要行数走，所以宽度要先定下来 ——
    见 :meth:`set_summary_width` 里的说明。
    """

    viewRequested = Signal(str)
    editRequested = Signal(str)
    deleteRequested = Signal(str)

    def __init__(self, loadout: Loadout, parent: QWidget | None = None):
        super().__init__(parent)
        self.loadout = loadout
        self.setMinimumHeight(ROW_MIN_HEIGHT)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(ROW_PADDING, 12, ROW_PADDING, 12)
        layout.setSpacing(ROW_SPACING)

        layout.addWidget(self._build_identity(), 0)

        self.summary = CaptionLabel(loadout.summary(), self)
        self.summary.setWordWrap(True)
        self.summary.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.summary.setTextColor("#8A8F98", "#7C7C7C")
        layout.addWidget(self.summary, 1)

        for text, signal in (
            ("查看", self.viewRequested),
            ("修改", self.editRequested),
            ("删除", self.deleteRequested),
        ):
            button = PushButton(text, self)
            button.setFixedWidth(ROW_BUTTON_WIDTH)
            button.clicked.connect(lambda _checked=False, sig=signal: sig.emit(self.loadout.id))
            layout.addWidget(button, 0)

        # 先给个兜底宽度，列表页随后会按真实视口重新调一次
        self.set_summary_width(420)

    # ---------------------------------------------------------------- 部件
    def _build_identity(self) -> QWidget:
        """左列：头像在上，角色名在**下面**。"""
        box = QWidget(self)
        box.setFixedWidth(ROW_LEFT_WIDTH)
        column = QVBoxLayout(box)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(4)

        avatar = load_icon(self.loadout.display_avatar)
        holder: QWidget = IconWidget(avatar, box) if not avatar.isNull() else QLabel(box)
        holder.setFixedSize(QSize(ROW_AVATAR_SIZE, ROW_AVATAR_SIZE))
        column.addWidget(holder, 0, Qt.AlignmentFlag.AlignHCenter)

        name = StrongBodyLabel(self.loadout.character or "（未填角色）", box)
        name.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        column.addWidget(name, 0, Qt.AlignmentFlag.AlignHCenter)
        column.addStretch(1)
        return box

    # ---------------------------------------------------------------- 尺寸
    def set_summary_width(self, width: int) -> None:
        """定死摘要宽度，再据此定死整行高度。

        为什么必须这么干：QLabel 自动换行的高度是靠 ``heightForWidth`` 算的，
        而 Qt 的 ``QBoxLayout`` **不传播**这个值 —— 父布局会按"一行"给高度，
        摘要最后一行就被裁掉了（本项目在资源库卡片上踩过同一个坑）。
        给死宽度之后 label 的 sizeHint 就是准的，行高自然也对。
        """
        self.summary.setFixedWidth(max(160, int(width)))
        self.setFixedHeight(
            max(ROW_MIN_HEIGHT, self.layout().totalSizeHint().height())
        )


class ConfigInterface(ScrollArea):
    """侧栏「配置」对应的页面。"""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("ConfigInterface")
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.store = LoadoutStore()

        self.view = QWidget(self)
        self.view.setObjectName("configView")
        self.root_layout = QVBoxLayout(self.view)
        self.root_layout.setContentsMargins(36, 32, 36, 28)
        self.root_layout.setSpacing(14)

        self.setWidget(self.view)
        self.setWidgetResizable(True)
        # 和其它页面一样：ScrollArea 自己和 viewport 都会吃系统调色板底色
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("#ConfigInterface { background: transparent; }")
        self.viewport().setStyleSheet("background: transparent;")

        #: 上一次算行宽用的视口宽度 —— 避免 resizeEvent 里反复重排
        self._last_row_width = -1

        self._build()

    # ---------------------------------------------------------------- 构建
    def _build(self) -> None:
        header = QWidget(self.view)
        row = QHBoxLayout(header)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)

        row.addWidget(TitleLabel("配置", header))

        add_button = PrimaryPushButton(FluentIcon.ADD, "新增", header)
        add_button.clicked.connect(self.open_add_dialog)
        row.addWidget(add_button)
        row.addStretch(1)
        self.root_layout.addWidget(header)

        self.subtitle = CaptionLabel("", self.view)
        self.subtitle.setTextColor("#8A8F98", "#7C7C7C")
        self.root_layout.addWidget(self.subtitle)

        self.list_host = QWidget(self.view)
        self.list_layout = QVBoxLayout(self.list_host)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(10)
        self.root_layout.addWidget(self.list_host)

        self.root_layout.addStretch(1)
        self.reload()

    # ---------------------------------------------------------------- 列表
    def _clear_list(self) -> None:
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def reload(self) -> None:
        """按存储里的内容重建列表（增删改之后都调它）。"""
        self._clear_list()

        items = self.store.all()
        self.subtitle.setText(f"共 {len(items)} 条配置 · 每条对应一个角色的声骸搭配")

        if not items:
            empty = CaptionLabel("还没有配置，点上面的「新增」建一条。", self.list_host)
            empty.setTextColor("#8A8F98", "#7C7C7C")
            self.list_layout.addWidget(empty)
            return

        for loadout in items:
            row = LoadoutRow(loadout, self.list_host)
            row.viewRequested.connect(self.open_view_dialog)
            row.editRequested.connect(self.open_edit_dialog)
            row.deleteRequested.connect(self.delete_loadout)
            self.list_layout.addWidget(row)

        # 新行都是默认宽度建的，这里按当前视口重算一次（顺带定好行高）
        self._last_row_width = -1
        self._apply_row_width()

    # ---------------------------------------------------------------- 尺寸
    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt 回调
        super().resizeEvent(event)
        self._apply_row_width()

    def _apply_row_width(self) -> None:
        """按当前视口宽度重算每行的摘要宽度 —— 行高跟着摘要行数走。

        不做这件事的话：窗口一变宽/变窄，摘要的换行位置就错了，
        行高还是按旧宽度算的，文字会被裁掉。
        """
        width = self.viewport().width() - _ROW_CHROME - _PAGE_CHROME
        if width == self._last_row_width:
            return
        self._last_row_width = width
        for row in self.findChildren(LoadoutRow):
            row.set_summary_width(width)

    # ---------------------------------------------------------------- 动作
    def open_add_dialog(self) -> None:
        dialog = LoadoutDialog(self.window())
        if dialog.exec():
            self.store.add(dialog.result_loadout())
            self.reload()

    def open_view_dialog(self, loadout_id: str) -> None:
        loadout = self.store.get(loadout_id)
        if loadout is None:
            return
        LoadoutDetailDialog(self.window(), loadout).exec()

    def open_edit_dialog(self, loadout_id: str) -> None:
        loadout = self.store.get(loadout_id)
        if loadout is None:
            return
        dialog = LoadoutDialog(self.window(), loadout)
        if dialog.exec():
            self.store.update(dialog.result_loadout())
            self.reload()

    def delete_loadout(self, loadout_id: str) -> None:
        loadout = self.store.get(loadout_id)
        if loadout is None:
            return

        box = MessageBox(
            "删除配置",
            f"确定删除「{loadout.character or '未填角色'}」的这条配置吗？删掉就找不回来了。",
            self.window(),
        )
        box.yesButton.setText("删除")
        box.cancelButton.setText("取消")
        if box.exec():
            self.store.remove(loadout_id)
            self.reload()

    # ---------------------------------------------------------------- 其它
    def icon(self):  # 供主窗口导航用
        return resolve_icon("SETTING")
