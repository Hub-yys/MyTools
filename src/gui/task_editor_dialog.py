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
  见 ``core/tasks.py`` 的绑定规则），悬空的配置（**前面没有工具**）
  运行时不会生效，保存时会弹一条提示说清楚（但它们仍留在流程里）。
- 任务名称**不可重复**（和 store 里其它流程比对，编辑模式排除自己）。
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget, QSizePolicy
from qfluentwidgets import (
    CaptionLabel,
    InfoBar,
    MessageBoxBase,
    PushButton,
    SearchLineEdit,
    StrongBodyLabel,
    SubtitleLabel,
)

from ..core import game_data
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
from .compat import resolve_icon
from .config_names import (
    FLOW_NAME_SUFFIX,
    KIND_ECHO_PROFILE,
    KIND_LOADOUT,
    TYPE_ECHO_PROFILE,
    TYPE_LOADOUT,
    config_display_name,
    flow_character_of,
    flow_name_for,
    is_flow_name_of_character,
    live_config_avatar,
    live_config_name,
)
from .pickers import (
    CHARACTER_BOX_HINT,
    CHARACTER_BOX_WIDTH,
    FilterComboBox,
    avatar_icon,
    pinyin_keys,
)
from .widgets import tool_icon_of

logger = logging.getLogger(__name__)

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


def _make_item(list_widget, text: str, data: dict, icon=None, tip: str = "") -> None:
    # 用 Qt 原生的 QListWidgetItem：qfluentwidgets 顶层不导出 ListWidgetItem，
    # 而且我们只往 item 里存数据、不改样式，原生的完全够用
    from PySide6.QtWidgets import QListWidgetItem

    item = QListWidgetItem(text)
    if icon is not None:
        item.setIcon(icon)
    # 文字被格子截断时，悬浮能看全名；给了 tip 就用 tip（比如"这个还不能当步骤跑"）
    item.setToolTip(tip or text)
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

    # ------------------------------------------------------------ 拖放插入
    #: 拖动过程中算出来的插入下标（``None`` = 没在拖）—— 用来画那条插入指示线
    _drop_index: int | None = None

    def insert_index_at(self, pos) -> int:
        """落点 → 插入下标（用户 2026-09-26："可在中间自由插入"）。

        规则跟大多数列表一致：**落在某一项的左半边就插到它前面、右半边插到后面**；
        不在任何项上时按 x 跟每项中心比，都没有就排到最后。
        """
        count = self.count()
        if count == 0:
            return 0
        item = self.itemAt(pos)
        if item is not None:
            rect = self.visualItemRect(item)
            index = self.row(item)
            return index if pos.x() < rect.center().x() else index + 1
        for i in range(count):
            if pos.x() < self.visualItemRect(self.item(i)).center().x():
                return i
        return count

    def dragMoveEvent(self, event) -> None:  # noqa: N802 - Qt 回调
        index = self.insert_index_at(event.position().toPoint())
        if index != self._drop_index:
            self._drop_index = index
            self.viewport().update()
        event.accept()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802 - Qt 回调
        self._drop_index = None
        self.viewport().update()
        super().dragLeaveEvent(event)

    def move_selected_to(self, index: int) -> bool:
        """把**选中的条目**搬到 ``index`` 位置（编排区内部拖动排序）。

        抽成独立方法是为了**能单测** —— 它是这段逻辑里最容易出错的地方
        （下标要减去"原本排在它前面、已经被拿走"的那几项，不然会错位）。

        ``index`` 是"搬之前"的目标下标（也就是落点在**当前**列表里的插入位置）。
        返回是否真的动了。
        """
        rows = sorted((i.row() for i in self.selectedIndexes()), reverse=True)
        if not rows:
            return False
        taken = [self.takeItem(r) for r in rows]      # 从后往前拿，顺序天然是对的
        taken.reverse()                               # 还原成"从上到下"
        target = index - sum(1 for r in rows if r < index)
        target = max(0, min(target, self.count()))
        for offset, item in enumerate(taken):
            self.insertItem(target + offset, item)
        return True

    def dropEvent(self, event) -> None:  # noqa: N802 - Qt 回调
        """★ 自己算插入位置，**别用 Qt 默认行为**。

        Qt 在 IconMode 下不按落点插 —— 从组件区拖到第 1、2 项之间，结果照样
        **追加到末尾**（实测过）。所以这里接管：

        * **组件区拖进来的**（source 不是自己）→ 在落点处插入一份新的；
        * **编排区内部拖动**（source 是自己）→ 先把选中的那几项拿走、再插到落点，
          也就是"拖到哪儿就排到哪儿"。

        ⚠ 两个分支都**不能用 MoveAction 收尾**：Qt 的 ``startDrag`` 看到
        ``drag->exec() == MoveAction`` 会再调一次 ``clearOrRemove()`` 去删源行，
        而搬移是我们自己做的 —— 会被**删第二次**（数据丢失）。
        外部拖进来的本来就是复制（组件区那份要留着），用 CopyAction 正好。
        """
        index = self.insert_index_at(event.position().toPoint())
        self._drop_index = None

        if event.source() is self:
            if not self.move_selected_to(index):
                event.ignore()
                return
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            self.viewport().update()
            return

        index = max(0, min(index, self.count()))
        # ⚠ **必须先自己开一个空行**再灌数据 —— 直接 `dropMimeData(row)` 在
        #   `row < count` 时是**覆盖那一行**而不是插入（Qt 的 decodeData 先 setData、
        #   只有超出末尾才 insertRows）。实测：2 项时往 1 号位插，会把原来 1 号那项
        #   **顶掉**（编辑了一轮才发现）。
        #   开空行之后再灌，role 数据（含 UserRole 里那个 dict）会原样写进去。
        #   （组件区是单选，一次拖 1 项，所以开 1 行就够。）
        from PySide6.QtCore import QModelIndex

        self.insertItem(index, "")
        self.model().dropMimeData(event.mimeData(), Qt.DropAction.CopyAction,
                                  index, 0, QModelIndex())
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
        self.viewport().update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt 回调
        super().paintEvent(event)
        self._paint_drop_indicator()
        self._paint_arrows(event)

    def _paint_drop_indicator(self) -> None:
        """拖动时在**将要插入的位置**画一条竖线。

        没有它的话"能插在中间"这件事用户看不出来 —— 只看到拖过去松手，
        顺序变了却不知道为什么。线画在两项之间的空隙里。
        """
        index = self._drop_index
        if index is None:
            return
        count = self.count()
        from PySide6.QtCore import QRect
        from PySide6.QtGui import QColor, QPainter

        from qfluentwidgets import isDarkTheme

        if count == 0:
            x = self.viewport().width() // 2
        elif index <= 0:
            x = self.visualItemRect(self.item(0)).left() - 8
        elif index >= count:
            x = self.visualItemRect(self.item(count - 1)).right() + 8
        else:
            left = self.visualItemRect(self.item(index - 1))
            right = self.visualItemRect(self.item(index))
            x = (left.right() + right.left()) // 2

        top = 12
        height = max(24, self.viewport().height() - 24)
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#6FB2F0") if isDarkTheme() else QColor("#2B7CD3"))
        painter.drawRoundedRect(QRect(x - 1, top, 3, height), 1.5, 1.5)
        painter.end()

    def _paint_arrows(self, event) -> None:
        """相邻步骤之间画箭头（原来就叫 paintEvent，拆出来是为了再加一条插入指示线）。"""
        count = self.count()
        if count < 2:
            return
        from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
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


# ---------------------------------------------------------------------- 共用件
# 下面这几个是"编排区"和"详情里的流程图"**共用**的 —— 抽出来是为了让两处
# 长同一个样（用户 2026-09-26："详情应该显示任务的流程图"）。

def step_tile_text(step) -> str:
    """步骤在瓦片上的文字。

    ⚠ 配置步骤**必须**走 :func:`live_config_name` —— 去配置里读当前名字。
    存的是 id，名字只在配置里有一份真身；存快照的话配置一改名，
    这里（以及流程列表、详情）就永远是旧名字。
    """
    if step.type in (STEP_START, STEP_END):
        return f"[{'开始' if step.type == STEP_START else '结束'}] " \
               f"{'开始' if step.type == STEP_START else '结束'}"
    if step.is_tool:
        return f"[工具] {step.name or step.key}"
    return f"[配置] {live_config_name(step)}"


def step_icon(step):
    """步骤的图标：标记用播放/暂停、工具用工具图标、配置用**当前**角色头像。"""
    from PySide6.QtGui import QIcon

    if step.type == STEP_START:
        return resolve_icon("PLAY").icon()
    if step.type == STEP_END:
        return resolve_icon("PAUSE").icon()
    if step.is_tool:
        meta = ToolRegistry.get_meta(step.key)
        return tool_icon_of(meta) if meta else QIcon()
    avatar = live_config_avatar(step)
    # 图没拿到就用配置名首字现画一个（用户 2026-09-28 要求）
    if avatar:
        return avatar_icon(avatar, live_config_name(step))
    return QIcon()


def step_row_data(step) -> dict:
    """塞进瓦片 ``UserRole`` 的那份数据（编排区收集步骤时要用）。"""
    return {"type": step.type, "key": step.key, "name": step.name,
            "config_kind": step.config_kind}


def make_flow_list(parent, *, read_only: bool = False) -> "FlowListWidget":
    """造一个「横向链条」列表：图标 + 名字 + 相邻之间的箭头。

    编排区和详情里的**流程图**都用它 —— 一处改、两处一起变。

    ``read_only=True``（详情用）会禁掉拖放与选中：只读地看，不能拖。
    """
    from qfluentwidgets import isDarkTheme

    widget = FlowListWidget(parent)
    widget.setViewMode(QListWidget.ViewMode.IconMode)
    widget.setFlow(QListWidget.Flow.LeftToRight)
    widget.setWrapping(False)
    widget.setMovement(QListWidget.Movement.Snap)
    widget.setResizeMode(QListWidget.ResizeMode.Adjust)
    widget.setIconSize(TILE_ICON_SIZE)
    # gridSize 比 sizeHint 宽 —— 横向空隙专门用来画步骤间箭头；
    # 运行中 _adjust_grid 会按条目数动态铺满
    widget.setWordWrap(True)
    widget.setUniformItemSizes(True)
    widget.setItemDelegate(
        TileDelegate(widget, lambda: widget.gridSize().height()))
    widget.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    widget.setFixedHeight(FLOW_HEIGHT)
    # ⚠ IconMode 下 QListWidget 的 sizeHint 只有 ~100px（实测），布局会按它给宽度
    #   导致塌缩；显式 minimumWidth 锁死下限，Expanding 负责拉满。
    widget.setMinimumWidth(FLOW_MIN_WIDTH)
    widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    text_color = "#DEE0E3" if isDarkTheme() else "#3D4148"
    widget.setStyleSheet(
        "QListWidget { background: rgba(255, 255, 255, 0.04);"
        " border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 8px;"
        f" color: {text_color}; padding: 8px; }}"
        "QListWidget::item { background: transparent; outline: none; }"
    )
    if read_only:
        widget.setAcceptDrops(False)
        widget.setDragDropMode(QListWidget.DragDropMode.NoDragDrop)
        widget.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    else:
        widget.setAcceptDrops(True)
        # DragDrop（不是 InternalMove）：要能接收组件区拖进来的条目
        widget.setDragDropMode(QListWidget.DragDropMode.DragDrop)
        widget.setDefaultDropAction(Qt.DropAction.MoveAction)
    return widget


#: 详情弹框的宽度上限 —— 步骤再多也别超过它（超了就横向滚）
PREVIEW_MAX_WIDTH = 980


def preview_width_for(step_count: int) -> int:
    """按步骤数算「详情」弹框该多宽。

    瓦片宽度是固定的，而 ``FLOW_MIN_WIDTH`` 是按 4~5 个瓦片估的 ——
    步骤更多时**最后一项会被切掉**（实测 5 个就切了：「[结束」只剩一半）。
    所以这里按实际个数算，只有超过上限才允许横向滚。
    """
    needed = max(FLOW_MIN_WIDTH, int(step_count) * TILE_SIZE.width() + 24)
    return min(needed, PREVIEW_MAX_WIDTH) + 24 * 2


class FlowPreview(QWidget):
    """一条任务的**流程图**（只读）。

    "详情"里用它 —— 用户 2026-09-26："详情应该显示任务的流程图"。
    直接复用编排区那套瓦片 + 箭头，所以详情里看到的就是编排界面里的样子。

    ⚠ 配置那几步的名字是**实时**去配置里读的（见 :func:`step_tile_text`）。
    """

    def __init__(self, flow: TaskFlow, parent: QWidget | None = None):
        super().__init__(parent)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(6)

        self.list = make_flow_list(self, read_only=True)
        box.addWidget(self.list)

        self.empty_hint = CaptionLabel("（这条流程里还没有步骤）", self)
        self.empty_hint.setTextColor("#8A8F98", "#7C7C7C")
        self.empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_hint.setVisible(False)
        box.addWidget(self.empty_hint)

        self.set_flow(flow)

    def set_flow(self, flow: TaskFlow) -> None:
        self.list.clear()
        for step in flow.steps:
            _make_item(self.list, step_tile_text(step), step_row_data(step),
                       icon=step_icon(step))
        empty = not flow.steps
        self.empty_hint.setVisible(empty)
        # 没步骤时把空链条收起来，只留一行提示（别摆个大空框）
        self.list.setVisible(not empty)
        self.list._adjust_grid()


class TaskEditorDialog(MessageBoxBase):
    """新增 / 修改一条任务流程。传 ``flow`` 就是修改模式（会回填）。"""

    def __init__(self, parent: QWidget | None = None, flow: TaskFlow | None = None,
                 store=None, loadout_store=None):
        super().__init__(parent)
        self.editing = flow is not None
        self.flow: TaskFlow = TaskFlow(
            id=flow.id if flow else "",
            name=flow.name if flow else "",
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

        # --- 名称行（★ 2026-09-28：从自由输入改成**选角色**）---
        # 用户批注："任务这里也是选角色，保存时自动加后缀声骸自动强化"。
        #
        # 以前是个自由输入的 LineEdit，用户得自己敲名字；现在和配置页那两个
        # 弹框一样用 **FilterComboBox**（可打拼音筛），名字 = 角色 + 固定后缀
        # （见 config_names.flow_name_for）。这样行上的头像 / 名字和配置那边
        # 一套规矩，也避免手打出错别字。
        #
        # ⚠ 角色下拉是**可输入**的，所以"候选里没有"拦不住手打的字 ——
        #   真正的把关在 validate() 里（角色必须精确命中数据集）。
        name_row = QWidget(self)
        row = QHBoxLayout(name_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        label = StrongBodyLabel("角色", name_row)
        label.setFixedWidth(76)
        row.addWidget(label)

        game_data.ensure_loaded()          # 保证 CHARACTERS 有内容
        self.character_box = FilterComboBox(name_row)
        self.character_box.setFixedWidth(CHARACTER_BOX_WIDTH)
        self.character_box.setPlaceholderText(CHARACTER_BOX_HINT)
        self.character_box.set_choices(
            [(c.name, avatar_icon(c.avatar, c.name)) for c in game_data.CHARACTERS])
        # 回填：老流程名不是"角色+后缀"格式时（「日常清声骸」）填不进下拉，
        # 这时留空 + 给一句提示，让用户重新选一个角色（见下面那行 stale 提示）。
        self.character_box.setText(flow_character_of(self.flow.name))
        row.addWidget(self.character_box)
        row.addStretch(1)

        # 名字是自动拼的，就顺手把结果给用户看一眼（"保存时自动加后缀"）
        suffix_note = CaptionLabel(f"保存时自动加后缀「{FLOW_NAME_SUFFIX}」",
                                   name_row)
        suffix_note.setTextColor("#8A8F98", "#7C7C7C")
        row.addWidget(suffix_note)
        self.viewLayout.addWidget(name_row)

        # 老流程名不是「角色 + 后缀」那种格式 → 下拉里填不出来，
        # 说清楚要重新选（不静默丢掉原来的名字，用户自己决定）。
        # ⚠ 判断要认**两种**后缀（新式带连字符 / 老式手打不带），
        #   否则存量流程「绯雪声骸自动强化」一打开就误报。
        if self.flow.name and not is_flow_name_of_character(self.flow.name):
            stale = CaptionLabel(
                f"⚠ 原来叫「{self.flow.name}」，它不是「角色{FLOW_NAME_SUFFIX}」"
                "这种格式（旧版可以自由起名）。请在左边重新选一个角色 —— "
                "名字就是角色名加后缀（保存后旧名字会被替换）。", self)
            stale.setTextColor("#C9514C", "#E6B4AC")
            stale.setWordWrap(True)
            self.viewLayout.addWidget(stale)

        # --- 任务类型：**已经去掉**（2026-09-26 用户要求）---
        # 原来这里有一对两级下拉（一级 = 工具分类，二级 = 具体产品）。
        # 用户要求去掉：类型本来就是"这条流程属于哪一类"，看它放了什么工具就知道，
        # 不该再让人手填一遍。现在改成**从步骤推导** —— 见
        # `TaskFlow.derived_type()`（core/tasks.py），「开始」步的前置检查用它。
        # 存盘里也不再写 type_key / sub_key。

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
        # 横向链条列表（图标 + 名字 + 箭头）—— 和「详情」里的流程图共用同一个工厂
        self.flow_list = make_flow_list(self)
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
        #   悬空配置保存时本来就会弹 InfoBar 说清楚，不必在这儿再占一行）

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

    # ------------------------------------------------------------ 数据
    def _available_tools(self) -> list:
        """**全部**工具（用户 2026-09-26："可以搜索所有的配置、工具"）。

        ⚠ 这里原来按 ``supports_task_run`` 过滤，只有「声骸自动强化」一个能出现，
        另外三个（4C 自动战斗 / 声骸批量调频 / 资源库更新）**根本列不出来**，
        自然也搜不到。

        现在全部列出来。**能不能真跑**是另一回事：真跑起来时
        `FlowRunThread` 会调工具的 ``create_task_runner``，没实现的话
        会明确记一条「工具「X」不支持自动运行，跳过」——**不静默**。
        所以这里给不能跑的那些挂一条 tooltip 说清楚，免得拖进去才发现。
        """
        return list(ToolRegistry.all_metas())

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
        # ⚠ 循环变量别再叫 type_key —— 「任务类型」已经删了，这名字会让人误会
        for marker_type, marker_name, icon_name in (
            (STEP_START, "开始", "PLAY"),
            (STEP_END, "结束", "PAUSE"),
        ):
            text = f"[{marker_name}] {marker_name}"
            if matches(text) or matches(f"[标记] {marker_name}"):
                _make_item(
                    self.palette_list,
                    text,
                    {"type": marker_type, "key": marker_type, "name": marker_name},
                    icon=resolve_icon(icon_name).icon(),
                )
        for meta in self._available_tools():
            text = f"[工具] {meta.name}"
            if matches(text):
                # 能列出 ≠ 能真跑：没实现任务运行接口的挂一句 tooltip 说清楚，
                # 免得拖进去、跑到那一步才发现被跳过（运行时也会明确记一条）。
                tip = "" if meta.supports_task_run else (
                    f"{meta.name}：还不能当任务步骤跑（拖进流程后运行到它会跳过）")
                _make_item(
                    self.palette_list,
                    text,
                    {"type": STEP_TOOL, "key": meta.key, "name": meta.name,
                     "config_kind": ""},
                    icon=tool_icon_of(meta),
                    tip=tip,
                )
        # 配置：**两类都列**（用户 2026-09-26："可以搜索所有的配置、工具"）。
        # 名字用配置页那套（带类型后缀），所以搜「筛选」「强化」都能搜到。
        #
        # ⚠ 循环变量**千万别叫 key** —— `matches()` 是闭包，用的是上面那个
        #   搜索关键词 `key`。叫 key 会把它覆盖成"每一条自己的 key"，
        #   于是匹配退化成"自己的 key 是不是自己的文字的子串" → **永远命中**，
        #   搜什么都把配置全列出来（实测踩过）。
        for kind, item_key, item_name, item_avatar in self._config_entries():
            text = f"[配置] {item_name}"
            if matches(text):
                _make_item(
                    self.palette_list,
                    text,
                    {"type": STEP_CONFIG, "key": item_key, "name": item_name,
                     "config_kind": kind},
                    icon=self._config_icon(item_avatar, item_name),
                )

    def _config_entries(self) -> list[tuple[str, str, str, str]]:
        """可用组件里的配置项：``[(kind, key, 显示名, 头像相对路径), ...]``。

        **两类都收**：
        * 「角色声骸筛选配置」→ ``LoadoutStore``，key 是 **id**；
        * 「角色声骸强化配置」→ ``EchoProfileStore``，key 是 ``EchoProfile.id``
          （**稳定 id**，不是角色名 —— 名字会变、id 不会）。

        显示名一律走 :func:`~src.gui.config_names.config_display_name`
        （``绯雪-声骸筛选`` / ``绯雪-声骸强化``）——**和配置页同名**，
        这样在搜索框里按配置页看到的名字也能搜到。
        """
        entries: list[tuple[str, str, str, str]] = []
        try:
            if self._loadout_store is not None:
                loadouts = self._loadout_store.all()
            else:
                from ..core.loadout import LoadoutStore

                loadouts = LoadoutStore().all()
            for item in loadouts:
                entries.append((
                    KIND_LOADOUT, item.id,
                    config_display_name(TYPE_LOADOUT, item.character),
                    item.display_avatar or "",
                ))
        except Exception:  # noqa: BLE001 - 配置文件坏了不该把编排界面带崩
            logger.warning("读角色声骸筛选配置失败（可用组件里会缺这一类）", exc_info=True)

        try:
            from ..core.echo_profile import EchoProfileStore

            store = EchoProfileStore()
            store.load()
            for profile in store.all():
                entries.append((
                    KIND_ECHO_PROFILE, profile.id,
                    config_display_name(TYPE_ECHO_PROFILE, profile.name),
                    self._avatar_of(profile.name),
                ))
        except Exception:  # noqa: BLE001
            logger.warning("读角色声骸强化配置失败（可用组件里会缺这一类）", exc_info=True)
        return entries

    @staticmethod
    def _avatar_of(character: str) -> str:
        from ..core import game_data

        info = game_data.find_character(character)
        return info.avatar if info is not None else ""

    @staticmethod
    def _config_icon(avatar: str, name: str = ""):
        """头像相对路径 → QIcon；**图没拿到就用首字现画一个**（用户 2026-09-28 要求）。"""
        return avatar_icon(avatar or "", name)

    _MARKER_TEXTS = {STEP_START: "[开始] 开始", STEP_END: "[结束] 结束"}

    def _icon_for_step(self, step: TaskStep):
        """编排区瓦片的图标 —— 走共用的 :func:`step_icon`（详情用同一个）。"""
        return step_icon(step)

    @staticmethod
    def _step_text(step: TaskStep) -> str:
        """编排区瓦片的文字 —— 走共用的 :func:`step_tile_text`（详情用同一个）。"""
        return step_tile_text(step)

    def _restore_steps(self) -> None:
        for step in self.flow.steps:
            _make_item(
                self.flow_list,
                self._step_text(step),
                step_row_data(step),
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
                        config_kind=str(data.get("config_kind", "")),
                    )
                )
        return steps

    def _collect(self) -> None:
        # 名字 = 角色 + 固定后缀（用户 2026-09-28："保存时自动加后缀声骸自动强化"）。
        # flow_name_for 对"已经带后缀"的输入是幂等的 —— 编辑时不会补出两个后缀。
        self.flow.name = flow_name_for(self.character_box.text())
        # ⚠ 任务类型**不再收集** —— 已经改成从步骤推导（`TaskFlow.derived_type()`）。
        #   原来这里是 `self.flow.type_key = self._current_type_key()`。
        self.flow.steps = self._collect_steps()

    # ------------------------------------------------------------ 校验
    def _duplicate_name(self) -> bool:
        """任务名称是否和 store 里**其它**流程重名（编辑模式排除自己）。"""
        store = self._store
        if store is None:
            return False
        # ⚠ 比的是 **_collect 之后的最终名**（带后缀那个），不是下拉里显示的
        #   角色名 —— 存进 store 的是最终名，比错了就拦不住重名。
        name = self.flow.name.strip()
        if not name:
            return False
        for other in store.all():
            if other.id != self.flow.id and other.name.strip() == name:
                return True
        return False

    def validate(self) -> bool:  # noqa: D102 - MessageBoxBase 钩子
        self._collect()
        errors = self.flow.validate()
        # 角色必须**精确命中**数据集里的一个角色 —— 下拉是可输入的，
        # "候选里没有"拦不住手打的字（和配置页两个弹框同一条规则）。
        #
        # ⚠ 这里**不复用** ``game_data.character_choice_error``：那条规则还带
        #   "一个角色只能有一条"（配置页的规矩）。任务流程**同一个角色可以有多条**
        #   （比如「绯雪-声骸自动强化」和以后别的流程），重名靠下面的 _duplicate_name
        #   按**最终流程名**拦。复用了会把合法的第二条流程误杀掉。
        raw = self.character_box.text().strip()
        if not raw:
            errors.append("请先选一个角色")
        elif game_data.find_character(raw) is None:
            errors.append(f"「{raw}」不是一个角色 —— 请从列表里选一个（可以打拼音筛）")
        if self._duplicate_name():
            errors.append(f"任务名称「{self.flow.name}」已经存在，换一个角色")
        if errors:
            InfoBar.error(
                "还有问题没解决",
                "；".join(errors),
                duration=5000,
                parent=self,
            )
            return False
        # 悬空配置：**只有"流程里一个工具都没有"**才可能出现
        # （配置往上、往下都找不到工具）。
        #
        # ⚠ 2026-09-27 起绑定规则改了：**上面**没有工具的配置会**改绑给下面的工具**
        #   —— 用户那条「开始 → 配置 → 配置 → 工具 → 结束」现在能正常生效了
        #   （以前会被静默丢掉，用户报「配置挂着却不筛选」）。
        #   所以文案不能再写"配置要放在工具**后面**"：那是旧规则的说法，
        #   而旧规则本身就是这次修掉的 bug。剩下真能触发的情形 validate() 已先拦。
        #
        # ⚠ 也不能说"已从流程里去掉" —— 保存的是**原始步骤**，它们照样留在流程里
        #   （`to_dict` 存的就是 self.flow.steps）。
        raw = self._collect_steps()
        kept = {id(s) for binding in bind_configs_to_tools(raw) for s in (binding["step"], *binding["configs"])}
        dangling = [step for step in raw if id(step) not in kept]
        if dangling:
            InfoBar.warning(
                "有步骤不会生效",
                f"有 {len(dangling)} 步没能绑到任何工具上（流程里是不是没有工具步骤？）。"
                "它们仍会留在流程里。",
                duration=6000,
                parent=self,
            )
        return True

    # ------------------------------------------------------------ 给外部用
    def result_flow(self) -> TaskFlow:
        """保存后调用：拿到填好的流程（不含 id / updated_at，由 store 负责）。"""
        self._collect()
        return self.flow
