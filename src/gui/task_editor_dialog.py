"""任务流程的编排弹框（新增 / 修改）。

布局（上下结构，都是横向）：

    任务名称 *  [____________]          ← 不可与已有流程重名
    任务类型    [游戏 ▾] [鸣潮 ▾]        ← 两级下拉，只是流程的标签
    可用组件（拖到下方编排区 →）  [搜索工具/配置…]
    ┌ [图标]  [图标]  [图标] …（一排横铺，超出横向滚动） ┐
    └──────────────────────────────────────────────┘
    ┌ 编排区（卡片围出，无标题）──────────────────────┐
    │  [步骤1] [步骤2] [步骤3] …（横向，拖动排序）      │
    └──────────────────────────────────────────────┘
                        [移除选中]   [保存] [取消]

- 可用组件是**块状卡片**（上面图标、下面 ``[类型] 名称``）——
  用 ``QListWidget`` 的 IconMode + LeftToRight 实现，不是手搓网格，
  这样**拖拽语义原封不动**：组件 → 编排区添加、编排区内拖动排序。
- 搜索框过滤可用组件（中文子串 + 拼音全拼/首字母）。
- 配置属于它**左边最近的工具步骤**（横向布局下的说法，本质是列表顺序，
  见 ``core/tasks.py`` 的绑定规则），悬空的配置保存时会被丢掉并提示。
- 任务名称**不可重复**（和 store 里其它流程比对，编辑模式排除自己）。
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QVBoxLayout, QWidget, QSizePolicy
from qfluentwidgets import (
    CaptionLabel,
    ComboBox,
    InfoBar,
    LineEdit,
    MessageBoxBase,
    PushButton,
    SearchLineEdit,
    StrongBodyLabel,
    SubtitleLabel,
)

from ..core.loadout import LoadoutStore
from ..core.registry import ToolRegistry
from ..core.tasks import (
    STEP_CONFIG,
    STEP_END,
    STEP_START,
    STEP_TOOL,
    TaskFlow,
    TaskStep,
    bind_configs_to_tools,
)
from ..core.task_types import sub_options, type_options
from .compat import resolve_icon
from .pickers import load_icon, pinyin_keys
from .widgets import tool_icon_of

#: 条目自定义数据存哪些 key（Qt.UserRole 里存一个 dict）
_ROLE_DATA = Qt.ItemDataRole.UserRole

DIALOG_WIDTH = 830
#: 组件区高度（横向一排，超出横向滚动）
PALETTE_HEIGHT = 118
#: 编排区高度（内容高：条目 100 + 上下 padding/边框）。
#: 不再撑满固定大区域 —— 弹框里上下留弹性空间，编排条目**全局垂直居中**。
FLOW_HEIGHT = 124
#: 编排区最小宽度 = 弹框宽 830 - viewLayout 左右 margins 24*2
FLOW_MIN_WIDTH = 780
#: 块状组件的图标尺寸
TILE_ICON_SIZE = QSize(40, 40)
#: 块状条目的格子尺寸。
#: 宽 170 刚好放得下最长的显示文本（"[工具] 声骸自动强化"）；
#: 高 78 = 图标 40 + 间距 6 + 一行文字 ~17 + 上下留白，**贴着内容**——
#: 原来 100 高时内容吊在上半部分，选中框也空荡荡一大圈（用户标注过两次）
TILE_SIZE = QSize(170, 78)


def _make_item(list_widget, text: str, data: dict, icon=None) -> None:
    # 用 Qt 原生的 QListWidgetItem：qfluentwidgets 顶层不导出 ListWidgetItem，
    # 而且我们只往 item 里存数据、不改样式，原生的完全够用
    from PySide6.QtWidgets import QListWidgetItem

    item = QListWidgetItem(text)
    if icon is not None:
        item.setIcon(icon)
    item.setToolTip(text)   # 文字被格子截断时，悬浮能看全名
    # 尺寸交给 TileDelegate 的 sizeHint（它会跟着格子高度走）。
    # ⚠ 这里**不要**再设 item.setSizeHint —— item 自己的 sizeHint 会盖掉 delegate 的，
    #   条目就会比格子矮一截并贴在格子顶边（实测偏上 14px）
    item.setData(_ROLE_DATA, data)
    list_widget.addItem(item)


def _item_data(item) -> dict:
    data = item.data(_ROLE_DATA)
    return data if isinstance(data, dict) else {}


from PySide6.QtWidgets import (  # noqa: E402  # 延迟到能拿到它的位置
    QListWidget,
    QStyle,
    QStyledItemDelegate,
)


class TileDelegate(QStyledItemDelegate):
    """IconMode 下块状条目的绘制：图标在上、文字在下，**整块落在格子正中**。

    为什么要自己画：Qt 默认的 IconMode 布局把"图标 + 文字"贴着格子**上沿**排，
    格子一高内容就明显偏上（下半截空着）；而选中/焦点框又是**沿整个格子矩形**画的，
    两件事凑在一起就是用户看到的那只"空荡荡的大白框"。
    这里改成：整块垂直居中、图标与文字各自水平居中，选中/悬停时画一个**贴合内容**的
    圆角底色，同时用 ``outline: none`` 关掉 Qt 那个沿整格画的大框。
    """
    ICON = QSize(40, 40)     # 图标区
    GAP = 6                  # 图标与文字的间距

    def __init__(self, view, height_provider=None):
        super().__init__(view)
        #: 取"当前格子高度"的回调 —— 条目矩形要铺满格子，内容才有居中的余地
        self._height_provider = height_provider or (lambda: TILE_SIZE.height())
    PAD_X = 8                # 选中底色左右各外扩多少
    PAD_Y = 6                # 选中底色上下各外扩多少

    @classmethod
    def block_height(cls, font) -> int:
        """图标 + 间距 + 一行文字的总高（整块就按这个高度垂直居中）。"""
        from PySide6.QtGui import QFontMetrics

        return cls.ICON.height() + cls.GAP + QFontMetrics(font).height()

    @classmethod
    def icon_center_y(cls, rect, font) -> float:
        """图标中心在条目矩形里的 y —— 编排区的箭头要对准它。"""
        return rect.center().y() - (cls.block_height(font) - cls.ICON.height()) / 2

    def sizeHint(self, option, index):  # noqa: N802 - Qt 回调
        # ⚠ IconMode 下 item 的矩形是按 sizeHint 给的（不是 gridSize），而且**贴格子顶边**。
        #   只设 gridSize 的话矩形仍然矮一截、整体偏上（实测 rect 高 78 而格子 106）。
        #   所以高度直接跟着格子走，绘制时再在这块矩形里居中。
        height = max(TILE_SIZE.height(), int(self._height_provider() or 0))
        return QSize(TILE_SIZE.width(), height)

    def paint(self, painter, option, index):  # noqa: N802 - Qt 回调
        from PySide6.QtCore import QPoint, QRect
        from PySide6.QtGui import QColor, QFontMetrics, QIcon

        from qfluentwidgets import isDarkTheme

        rect = option.rect
        fm = QFontMetrics(option.font)
        dark = isDarkTheme()
        total = self.block_height(option.font)

        painter.save()

        # 选中 / 悬停：画一个**贴合内容**的圆角底色，代替 Qt 那个沿整格画的大框
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if selected or hovered:
            alpha = 48 if selected else 26
            fill = QColor(255, 255, 255, alpha) if dark else QColor(0, 0, 0, alpha // 2)
            box = QRect(0, 0, rect.width() - 2 * self.PAD_X, total + 2 * self.PAD_Y)
            box.moveCenter(rect.center())
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(fill)
            painter.drawRoundedRect(box, 8, 8)

        # 图标：水平居中，纵向位置由"整块居中"反推
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        icon_rect = QRect(0, 0, self.ICON.width(), self.ICON.height())
        icon_rect.moveCenter(QPoint(rect.center().x(), int(self.icon_center_y(rect, option.font))))
        if isinstance(icon, QIcon) and not icon.isNull():
            icon.paint(painter, icon_rect, Qt.AlignmentFlag.AlignCenter)

        # 文字：图标正下方一行居中，超宽省略号
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        text_rect = QRect(rect.left(), icon_rect.bottom() + self.GAP, rect.width(), fm.height())
        painter.setPen(QColor("#DEE0E3") if dark else QColor("#3D4148"))
        painter.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            fm.elidedText(text, Qt.TextElideMode.ElideRight, text_rect.width()),
        )

        painter.restore()



class FlowListWidget(QListWidget):
    """编排区的横向列表：相邻步骤之间**自动画箭头**（执行顺序的方向感）。

    箭头画在 viewport 上（paintEvent 追加绘制），只在两个相邻条目都可见时画，
    滚动/增删后 Qt 会自动重 paint，不需要手动刷新。

    条目少时**均匀铺满**编排区（视觉上就是居中）：动态把 gridSize 宽度调成
    ``viewport宽 / 条目数``（不小于标准格宽）；条目多到放不下就恢复标准宽度、
    靠横向滚动。箭头基于 visualItemRect 画，格子拉开后箭头自动跟着走。
    ⚠ 别用 setViewportMargins 做居中——文档要求它只能在构造函数里调用，
    运行中调用会把 QListWidget 的布局搞塌（实测整个列表缩成 100px 宽）。
    """

    _last_grid_w = 0
    _last_grid_h = 0

    def _adjust_grid(self) -> None:
        count = self.count()
        available = self.viewport().width()
        if count == 0 or available <= 0:
            return
        # 均匀铺满，但不小于标准格宽；箭头需要空隙，标准宽已含 45px 余量
        grid_w = max(TILE_SIZE.width(), available // count)
        # 高度用 viewport 的实际高度：条目在编排区里垂直居中（内容再由 delegate 居中）
        grid_h = max(TILE_SIZE.height(), self.viewport().height())
        if (grid_w, grid_h) != (self._last_grid_w, self._last_grid_h):
            self._last_grid_w, self._last_grid_h = grid_w, grid_h
            self.setGridSize(QSize(grid_w, grid_h))
            # 格子高度变了 → sizeHint 跟着变 → 得让 Qt 重排条目矩形
            self.scheduleDelayedItemsLayout()

    def updateGeometries(self) -> None:  # noqa: N802 - Qt 回调
        super().updateGeometries()
        self._adjust_grid()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt 回调
        super().paintEvent(event)
        count = self.count()
        if count < 2:
            return
        from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF, QFont
        from PySide6.QtCore import QPointF, Qt as _Qt

        from qfluentwidgets import isDarkTheme

        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor("#6E7480") if isDarkTheme() else QColor("#9AA0A8")
        pen = QPen(color, 2)
        painter.setPen(pen)
        painter.setBrush(color)

        for index in range(count - 1):
            rect_a = self.visualItemRect(self.item(index))
            rect_b = self.visualItemRect(self.item(index + 1))
            viewport = self.viewport().rect()
            # 两端都不可见就跳过（横向滚动时省事）
            if rect_a.right() < 0 or rect_b.left() > viewport.width():
                continue
            if rect_b.right() < 0 or rect_a.left() > viewport.width():
                continue
            # 对准图标中心：TileDelegate 把"图标 + 文字"整块垂直居中了，
            # 所以图标中心不再是"矩形顶边 + 半个图标高"
            y = TileDelegate.icon_center_y(rect_a, self.font())
            # 箭头画在两格间隙的正中，宽窄随间隙自适应；
            # 间隙太窄时允许向两侧条目边缘各借 3px（条目边缘是空白，压住不碍事）
            cx = (rect_a.right() + rect_b.left()) / 2
            half = min(10.0, (rect_b.left() - rect_a.right()) / 2 + 3)
            start = QPointF(cx - half, y)
            end = QPointF(cx + half, y)
            painter.drawLine(start, end)
            head_size = min(6.0, half)
            head = QPolygonF([
                end,
                QPointF(end.x() - head_size, y - head_size * 0.8),
                QPointF(end.x() - head_size, y + head_size * 0.8),
            ])
            painter.setPen(_Qt.PenStyle.NoPen)
            painter.drawPolygon(head)
            painter.setPen(pen)
        painter.end()


class TaskEditorDialog(MessageBoxBase):
    """新增 / 修改一条任务流程。传 ``flow`` 就是修改模式（会回填）。"""

    def __init__(self, parent: QWidget | None = None, flow: TaskFlow | None = None,
                 store=None, loadout_store=None):
        super().__init__(parent)
        self.editing = flow is not None
        self.flow: TaskFlow = TaskFlow(
            id=flow.id if flow else "",
            name=flow.name if flow else "",
            type_key=flow.type_key if flow else "",
            sub_key=flow.sub_key if flow else "",
            steps=[TaskStep.from_dict(s.to_dict()) for s in (flow.steps if flow else [])],
            updated_at=flow.updated_at if flow else "",
        )
        #: 注入点：测试可以传临时目录的 store
        self._store = store
        self._loadout_store = loadout_store

        self.widget.setFixedWidth(DIALOG_WIDTH)
        self.yesButton.setText("保存")
        self.cancelButton.setText("取消")

        self.viewLayout.addWidget(SubtitleLabel("修改任务流程" if self.editing else "新增任务流程"))

        # --- 名称行 ---
        name_row = QWidget(self)
        row = QHBoxLayout(name_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        label = StrongBodyLabel("任务名称", name_row)
        label.setFixedWidth(76)
        row.addWidget(label)
        self.name_edit = LineEdit(name_row)
        self.name_edit.setPlaceholderText("给这条流程起个名字，比如「日常清声骸」")
        self.name_edit.setText(self.flow.name)
        row.addWidget(self.name_edit, 1)
        self.viewLayout.addWidget(name_row)

        # --- 任务类型行（一级分类 + 二级产品，两级都是下拉） ---
        # 按需求：任务类型**只是流程的标签**，不过滤下面的可用组件。
        # 一级复用工具分类（游戏 / 数据 / 办公…），二级是具体产品（游戏 → 鸣潮）；
        # 候选表在 core/task_types.py，加一个游戏就加一行。
        type_row = QWidget(self)
        t_row = QHBoxLayout(type_row)
        t_row.setContentsMargins(0, 0, 0, 0)
        t_row.setSpacing(10)
        type_label = StrongBodyLabel("任务类型", type_row)
        type_label.setFixedWidth(76)                 # 和「任务名称」那行对齐
        t_row.addWidget(type_label)
        self.type_combo = ComboBox(type_row)
        self._type_options = type_options()          # [(key, 显示名), ...]
        self.type_combo.addItems([name for _, name in self._type_options])
        t_row.addWidget(self.type_combo, 1)
        self.sub_combo = ComboBox(type_row)
        self._sub_options: list[tuple[str, str]] = []
        t_row.addWidget(self.sub_combo, 1)
        self.viewLayout.addWidget(type_row)

        # 一级变了重建二级；回填时也要按存下来的 key 定位（不能直接 setText）
        self.type_combo.currentIndexChanged.connect(self._on_type_changed)
        type_keys = [key for key, _ in self._type_options]
        self.type_combo.setCurrentIndex(
            type_keys.index(self.flow.type_key) if self.flow.type_key in type_keys else 0
        )
        self._fill_sub_combo(self.flow.type_key, self.flow.sub_key)

        # --- 可用组件区（横向一排 + 上方搜索框） ---
        palette_title_row = QWidget(self)
        pt_row = QHBoxLayout(palette_title_row)
        pt_row.setContentsMargins(0, 0, 0, 0)
        pt_row.setSpacing(12)
        pt_row.addWidget(StrongBodyLabel("可用组件（拖到下方编排区 →）", palette_title_row))
        pt_row.addStretch(1)
        # 搜索框：过滤可用组件（中文子串 + 拼音）
        self.search_edit = SearchLineEdit(palette_title_row)
        self.search_edit.setPlaceholderText("搜索工具 / 配置（支持拼音）")
        self.search_edit.setFixedWidth(300)
        self.search_edit.setFixedHeight(34)
        self.search_edit.textChanged.connect(self._fill_palette)
        pt_row.addWidget(self.search_edit)
        self.viewLayout.addWidget(palette_title_row)

        # 块状组件：IconMode 让每个条目"上面图标、下面 [类型] 名称"。
        # ⚠ 必须用 **Qt 原生** QListWidget：实测 qfluentwidgets 的 ListWidget
        # 代理在 IconMode 下**不渲染条目文字**（图标能画，"[工具] xxx"没有）。
        # Movement 必须是 Static（否则拖动会变成移动格子而不是拖去编排区）。
        # LeftToRight + 不换行 = 所有组件**横向一排**，超出横向滚动。
        from PySide6.QtWidgets import QListWidget

        self.palette_list = QListWidget(self)
        self.palette_list.setViewMode(QListWidget.ViewMode.IconMode)
        self.palette_list.setFlow(QListWidget.Flow.LeftToRight)
        self.palette_list.setWrapping(False)
        self.palette_list.setMovement(QListWidget.Movement.Static)
        self.palette_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.palette_list.setIconSize(TILE_ICON_SIZE)
        # 格子高度按"区域高度 - 上下 padding"给：条目才会落在区域正中，
        # 而不是贴着顶边、下面空一截（内容由 TileDelegate 在格子里居中）
        self.palette_list.setGridSize(QSize(TILE_SIZE.width(), PALETTE_HEIGHT - 16))
        self.palette_list.setWordWrap(True)
        self.palette_list.setUniformItemSizes(True)
        self.palette_list.setItemDelegate(
            TileDelegate(self.palette_list, lambda: self.palette_list.gridSize().height()))
        self.palette_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.palette_list.setDragEnabled(True)
        self.palette_list.setDragDropMode(QListWidget.DragDropMode.DragOnly)
        self.palette_list.setFixedHeight(PALETTE_HEIGHT)
        # 原生控件会吃系统调色板底色（深色系统上一片黑，坑位表老朋友），
        # 这里拍平：背景透明、文字/选中色跟主题走
        from qfluentwidgets import isDarkTheme

        text_color = "#DEE0E3" if isDarkTheme() else "#3D4148"
        self.palette_list.setStyleSheet(
            "QListWidget { background: transparent; border: none;"
            f" color: {text_color}; }}"
            "QListWidget::item { background: transparent; outline: none; }"
        )
        self.viewLayout.addWidget(self.palette_list)

        # --- 编排区（横向，在组件区下方；标题按需求删掉，用卡片围出边界） ---
        # ⚠ 编排区的列表**直接放进 viewLayout**，不要套容器（CardWidget/QFrame 都试过）：
        # 实测无论哪种容器，套上之后列表宽度会塌缩到 100px 且容器的布局
        # geometry 停在 0x0（布局引擎没跑，原因未深究）；
        # 直接同级放置宽度正常，"卡片边界"的视觉用列表自己的样式表画。
        self.flow_list = FlowListWidget(self)
        self.flow_list.setViewMode(QListWidget.ViewMode.IconMode)
        self.flow_list.setFlow(QListWidget.Flow.LeftToRight)
        self.flow_list.setWrapping(False)
        self.flow_list.setMovement(QListWidget.Movement.Snap)
        self.flow_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.flow_list.setIconSize(TILE_ICON_SIZE)
        # gridSize 比 sizeHint 宽 —— 横向空隙专门用来画步骤间箭头；
        # 运行中 _adjust_grid 会按条目数动态铺满
        self.flow_list.setWordWrap(True)
        self.flow_list.setUniformItemSizes(True)
        self.flow_list.setItemDelegate(
            TileDelegate(self.flow_list, lambda: self.flow_list.gridSize().height()))
        self.flow_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.flow_list.setAcceptDrops(True)
        # DragDrop（不是 InternalMove）：要能接收组件区拖进来的条目
        self.flow_list.setDragDropMode(QListWidget.DragDropMode.DragDrop)
        self.flow_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.flow_list.setFixedHeight(FLOW_HEIGHT)
        # 弹框宽 830 是固定的，viewLayout 左右 margins 各 24、上下留白 ——
        # 编排区可用宽是个常数。IconMode 下 QListWidget 的 sizeHint 只有 ~100px
        # （实测，原因未深究），布局会按 sizeHint 给宽度导致塌缩；
        # 显式 minimumWidth 直接锁死下限，Expanding 负责拉满。
        self.flow_list.setMinimumWidth(FLOW_MIN_WIDTH)
        self.flow_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.flow_list.setStyleSheet(
            "QListWidget { background: rgba(255, 255, 255, 0.04);"
            " border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 8px;"
            f" color: {text_color}; padding: 8px; }}"
            "QListWidget::item { background: transparent; outline: none; }"
        )
        self.viewLayout.addStretch(1)
        self.viewLayout.addWidget(self.flow_list)
        self.viewLayout.addStretch(1)
        self.flow_placeholder = CaptionLabel(
            "把上面的工具 / 配置拖到这里，按从左到右的顺序执行", self
        )
        self.flow_placeholder.setTextColor("#8A8F98", "#7C7C7C")
        self.flow_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.viewLayout.addWidget(self.flow_placeholder)

        # （原来这里有一行「配置会挂到左边最近的工具下…」的说明，按需求去掉了：
        #   悬空配置保存时本来就会弹 InfoBar 兜住，不必在这儿再占一行）

        remove_row = QWidget(self)
        remove_layout = QHBoxLayout(remove_row)
        remove_layout.setContentsMargins(0, 0, 0, 0)
        remove_layout.addStretch(1)
        self.remove_button = PushButton("移除选中条目", remove_row)
        self.remove_button.clicked.connect(self._remove_selected)
        remove_layout.addWidget(self.remove_button)
        remove_layout.addStretch(1)
        self.viewLayout.addWidget(remove_row)

        # 编排区空/非空时切换占位提示
        self.flow_list.model().rowsInserted.connect(self._sync_placeholder)
        self.flow_list.model().rowsRemoved.connect(self._sync_placeholder)
        # 增删条目后重算铺满（rowsInserted 不会自动触发 updateGeometries，
        # 用 singleShot(0) 排到本轮布局结束之后）
        self.flow_list.model().rowsInserted.connect(
            lambda *_: QTimer.singleShot(0, self.flow_list._adjust_grid))
        self.flow_list.model().rowsRemoved.connect(
            lambda *_: QTimer.singleShot(0, self.flow_list._adjust_grid))

        self._fill_palette()
        self._restore_steps()
        self._sync_placeholder()

    # ------------------------------------------------------------ 任务类型
    def _current_type_key(self) -> str:
        index = self.type_combo.currentIndex()
        if index < 0 or index >= len(self._type_options):
            return ""
        return self._type_options[index][0]

    def _current_sub_key(self) -> str:
        index = self.sub_combo.currentIndex()
        if index < 0 or index >= len(self._sub_options):
            return ""
        return self._sub_options[index][0]

    def _on_type_changed(self, *_args) -> None:
        """一级变了就重建二级候选（默认落在第一项）。"""
        self._fill_sub_combo(self._current_type_key(), "")

    def _fill_sub_combo(self, type_key: str, sub_key: str) -> None:
        """按一级重建二级下拉。

        未分类时没有二级候选 —— 置灰 + 一句占位提示（空下拉比禁用更容易让人以为坏了）。
        """
        self._sub_options = sub_options(type_key)
        self.sub_combo.blockSignals(True)
        self.sub_combo.clear()
        self.sub_combo.addItems([name for _, name in self._sub_options])
        self.sub_combo.blockSignals(False)
        if not self._sub_options:
            self.sub_combo.setPlaceholderText("先选任务类型")
            self.sub_combo.setCurrentIndex(-1)
            self.sub_combo.setEnabled(False)
            return
        self.sub_combo.setEnabled(True)
        keys = [key for key, _ in self._sub_options]
        self.sub_combo.setCurrentIndex(keys.index(sub_key) if sub_key in keys else 0)

    # ------------------------------------------------------------ 数据
    def _available_tools(self) -> list:
        """支持任务运行的工具元数据。"""
        return [m for m in ToolRegistry.all_metas() if m.supports_task_run]

    def _fill_palette(self, keyword: str = "") -> None:
        """按关键词重建可用组件（中文子串 + 拼音全拼/首字母）。"""
        self.palette_list.clear()
        key = (keyword or "").strip()

        def matches(text: str) -> bool:
            if not key:
                return True
            if key in text:
                return True
            if not (key.isascii() and key.isalpha()):
                return False
            lowered = key.lower()
            full, initial = pinyin_keys(text)
            return lowered in full or lowered in initial

        # 开始 / 结束标记：拖进流程做首尾（不执行任何东西）
        for type_key, type_name, icon_name in (
            (STEP_START, "开始", "PLAY"),
            (STEP_END, "结束", "PAUSE"),
        ):
            text = f"[{type_name}] {type_name}"
            if matches(text) or matches(f"[标记] {type_name}"):
                _make_item(
                    self.palette_list,
                    f"[{type_name}] {type_name}",
                    {"type": type_key, "key": type_key, "name": type_name},
                    icon=resolve_icon(icon_name).icon(),
                )
        for meta in self._available_tools():
            text = f"[工具] {meta.name}"
            if matches(text):
                _make_item(
                    self.palette_list,
                    text,
                    {"type": STEP_TOOL, "key": meta.key, "name": meta.name},
                    icon=tool_icon_of(meta),
                )
        for loadout in self._loadouts():
            name = loadout.character or "（未命名）"
            text = f"[配置] {name}"
            if matches(text):
                _make_item(
                    self.palette_list,
                    text,
                    {"type": STEP_CONFIG, "key": loadout.id, "name": name},
                    icon=load_icon(loadout.display_avatar),
                )

    def _loadouts(self):
        if self._loadout_store is not None:
            return self._loadout_store.all()
        try:
            from ..core.loadout import LoadoutStore

            return LoadoutStore().all()
        except Exception:  # noqa: BLE001 - 配置文件坏了不该把编排界面带崩
            return []

    _MARKER_TEXTS = {STEP_START: "[开始] 开始", STEP_END: "[结束] 结束"}

    def _icon_for_step(self, step: TaskStep):
        """按步骤类型找图标：标记用播放/暂停、工具用工具图标、配置用角色头像。"""
        from PySide6.QtGui import QIcon

        if step.type == STEP_START:
            return resolve_icon("PLAY").icon()
        if step.type == STEP_END:
            return resolve_icon("PAUSE").icon()
        if step.is_tool:
            meta = ToolRegistry.get_meta(step.key)
            return tool_icon_of(meta) if meta else QIcon()
        for loadout in self._loadouts():
            if loadout.id == step.key:
                return load_icon(loadout.display_avatar)
        return QIcon()

    @staticmethod
    def _step_text(step: TaskStep) -> str:
        if step.type in TaskEditorDialog._MARKER_TEXTS:
            return TaskEditorDialog._MARKER_TEXTS[step.type]
        kind = "工具" if step.is_tool else "配置"
        return f"[{kind}] {step.name or step.key}"

    def _restore_steps(self) -> None:
        for step in self.flow.steps:
            _make_item(
                self.flow_list,
                self._step_text(step),
                {"type": step.type, "key": step.key, "name": step.name},
                icon=self._icon_for_step(step),
            )

    # ------------------------------------------------------------ 交互
    def _sync_placeholder(self, *_args) -> None:
        """编排区为空时显示引导文字，有条目就藏起来。"""
        self.flow_placeholder.setVisible(self.flow_list.count() == 0)

    def _remove_selected(self) -> None:
        for item in self.flow_list.selectedItems():
            self.flow_list.takeItem(self.flow_list.row(item))

    # ------------------------------------------------------------ 收集
    def _collect_steps(self) -> list[TaskStep]:
        steps: list[TaskStep] = []
        for index in range(self.flow_list.count()):
            data = _item_data(self.flow_list.item(index))
            if data.get("type") in (STEP_TOOL, STEP_CONFIG, STEP_START, STEP_END) and data.get("key"):
                steps.append(
                    TaskStep(
                        type=str(data["type"]),
                        key=str(data["key"]),
                        name=str(data.get("name", "")),
                    )
                )
        return steps

    def _collect(self) -> None:
        self.flow.name = self.name_edit.text().strip()
        self.flow.type_key = self._current_type_key()
        self.flow.sub_key = self._current_sub_key()
        self.flow.steps = self._collect_steps()

    # ------------------------------------------------------------ 校验
    def _duplicate_name(self) -> bool:
        """任务名称是否和 store 里**其它**流程重名（编辑模式排除自己）。"""
        store = self._store
        if store is None:
            return False
        name = self.name_edit.text().strip()
        if not name:
            return False
        for other in store.all():
            if other.id != self.flow.id and other.name.strip() == name:
                return True
        return False

    def validate(self) -> bool:  # noqa: D102 - MessageBoxBase 钩子
        self._collect()
        errors = self.flow.validate()
        if self._duplicate_name():
            errors.append(f"任务名称「{self.flow.name}」已经存在，换一个名字")
        if errors:
            InfoBar.error(
                "还有问题没解决",
                "；".join(errors),
                duration=5000,
                parent=self,
            )
            return False
        # 悬空配置：前面没有工具的配置会被静默丢弃 —— 先告诉用户一声
        raw = self._collect_steps()
        kept = {id(s) for binding in bind_configs_to_tools(raw) for s in (binding["step"], *binding["configs"])}
        dropped = sum(1 for step in raw if id(step) not in kept)
        if dropped:
            InfoBar.warning(
                "有配置被丢弃",
                f"{dropped} 个配置前面没有工具，已从流程里去掉。",
                duration=5000,
                parent=self,
            )
        return True

    # ------------------------------------------------------------ 给外部用
    def result_flow(self) -> TaskFlow:
        """保存后调用：拿到填好的流程（不含 id / updated_at，由 store 负责）。"""
        self._collect()
        return self.flow
