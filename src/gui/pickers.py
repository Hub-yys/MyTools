"""配置界面用的选择控件。

三个可复用件：

- :class:`FilterComboBox` —— 能自由输入、并**按输入内容过滤候选**的下拉框；
- :class:`StatChooser`    —— 属性多选器（一组复选框，可同时勾多条）；
- :class:`EchoPickRow`    —— 一行声骸：左图标+名称 / 中属性多选 / 右勾选。
"""

from __future__ import annotations

import zlib
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CheckBox,
    EditableComboBox,
    IconWidget,
    PushButton,
    RoundMenu,
)

from ..core.game_data import EchoInfo, icon_path

try:  # 拼音搜索是可选增强：没装 pypinyin 就退化成只有中文子串匹配
    from pypinyin import Style as _PinyinStyle
    from pypinyin import lazy_pinyin as _lazy_pinyin
except ImportError:  # pragma: no cover
    _lazy_pinyin = None
    _PinyinStyle = None


def pinyin_keys(text: str) -> tuple[str, str]:
    """算出搜索用的拼音索引 → ``(全拼, 首字母)``，都小写、只留字母数字。

    ``"穗穗"`` → ``("suisui", "ss")``；
    ``"漂泊者·衍射"`` → ``("piaobozheyanshe", "pbzys")`` —— 中间的 ``·`` 被滤掉，
    所以敲 ``pbz`` 也能搜到。

    没装 pypinyin 时返回空串：拼音搜索失效，中文子串搜索照常。
    """
    if _lazy_pinyin is None:
        return "", ""

    def keep_alnum(value: str) -> str:
        return "".join(ch for ch in value if ch.isalnum())

    full = "".join(_lazy_pinyin(text)).lower()
    initial = "".join(_lazy_pinyin(text, style=_PinyinStyle.FIRST_LETTER)).lower()
    return keep_alnum(full), keep_alnum(initial)


def matches_keyword(keys: tuple[str, str], text: str, keyword: str) -> bool:
    """``text`` 是否命中 ``keyword`` —— **全项目共用的搜索匹配规则**。

    * 空关键词（含**纯空白**）= 全命中；
    * 中文走**子串**；
    * **纯字母** additionally 走拼音（全拼或首字母都行）。

    只在纯字母输入时试拼音：打中文时子串匹配已经够用，而且中文 key 跟
    拼音串不可能互相包含 —— 加进去只会白算。

    ⚠ 抽成模块级函数是为了**别处也能用同一套规则**（2026-09-30：
    配置页要"和下拉列表搜索一样的"搜索框）。逻辑只有这一份，
    改规则时下拉框和搜索框一起变，不会两边不一致。

    ⚠ **自己 ``strip()``**：调用方忘了去空格时，"   " 会被当成关键词，
    结果一条都搜不到（看起来像"搜索坏了"）。下拉框那边是在
    ``_fill_items`` 里先 strip 的，这里再兜一次，两边都不会踩。

    ``keys`` 是 :func:`pinyin_keys` 的返回值 ``(全拼, 首字母)``。
    """
    keyword = (keyword or "").strip()
    if not keyword:
        return True
    if keyword in text:
        return True
    if not (keyword.isascii() and keyword.isalpha()):
        return False
    lowered = keyword.lower()
    full, initial = keys
    return lowered in full or lowered in initial


def load_icon(relative: str) -> QIcon:
    """加载图标：数据集里的相对路径、或用户自选的绝对路径都吃。

    文件不在就返回空图标（界面自己会留白）。
    """
    if not relative:
        return QIcon()
    raw = Path(relative)
    path = raw if raw.is_absolute() else Path(icon_path(relative))
    return QIcon(str(path)) if path.exists() else QIcon()


#: 首字占位图的配色（和 ``tools/make_placeholders.py`` 画的那套同源思路：
#: 由名字散列出色相，所以同一个人每次都是同一个颜色）
_FALLBACK_HUES = 360


def avatar_icon(relative: str, name: str = "") -> QIcon:
    """角色头像：**文件不在就用名字首字现画一个**（用户 2026-09-28 要求）。

    "如果角色头像没拿到，先用第一个字填充"。

    ## 为什么要在**运行时**画，而不是只提前生成好文件

    新角色是「资源库更新」拉进来的 —— 那一刻 `assets/game/avatars/` 里
    **不会有**对应的图（游戏素材按项目一贯处理不入库，要用户自己截）。
    如果只是留白，用户看到的就是"名字有了、图是空的"，以为没生效。
    这里兜一个首字圆图，至少一眼能认出是谁。

    ## 和 ``make_placeholders.py`` 的关系

    那个脚本是**离线**给全量角色铺占位图的；这个是**运行时**的兜底，
    两者视觉一致（都是散列色相的圆 + 白色首字），所以看不出接缝。
    """
    icon = load_icon(relative)
    if not icon.isNull():
        return icon
    return _initial_icon(name)


def _initial_icon(name: str) -> QIcon:
    """画一个"圆底 + 首字"的头像。

    ⚠ 必须**先有 QApplication** 才能建 QPixmap/QPainter ——
    调用点都在界面里，正常满足；万一没有就返回空图标（不抛）。
    """
    text = str(name or "").strip()
    if not text:
        return QIcon()
    try:
        from PySide6.QtCore import QRectF, Qt as _Qt
        from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPixmap
    except Exception:  # noqa: BLE001 - Qt 没装好时不该把界面拖崩
        return QIcon()

    size = 64
    pix = QPixmap(size, size)
    pix.fill(_Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        # 色相由名字散列决定 —— 同一个人永远同一个颜色，不同人尽量错开
        hue = (zlib.crc32(text.encode("utf-8")) % _FALLBACK_HUES)
        base = QColor.fromHsv(hue, 90, 200)
        painter.setBrush(QBrush(base))
        painter.setPen(QPen(base.darker(115), 1))
        painter.drawEllipse(QRectF(0, 0, size, size))

        font = QFont()
        font.setPixelSize(int(size * 0.52))
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(255, 255, 255, 245))
        painter.drawText(QRectF(0, 0, size, size),
                         int(_Qt.AlignmentFlag.AlignCenter), text[0])
    finally:
        painter.end()
    return QIcon(pix)


def _make_item(text: str, icon: QIcon | None):
    """构造下拉项。

    框架的 ``ComboItem`` 不在顶层导出，这里不去依赖它的内部路径 —— 只要对象有
    ``text`` / ``icon`` / ``isEnabled`` 三个属性，框架的菜单构建逻辑就能用。
    """
    try:
        from qfluentwidgets.components.widgets.combo_box import ComboItem

        return ComboItem(text, icon, None)
    except Exception:  # noqa: BLE001 - 内部路径变了也不影响功能
        return SimpleNamespace(text=text, icon=icon, isEnabled=True, userData=None)


#: 选**角色**那个下拉框的宽度 —— 配置页两个弹框共用，别各写一个数。
#: 用户 2026-09-26：以前「角色声骸强化」那个填满整行（650px），"太长了，缩短"；
#: 现在和「角色声骸筛选」对齐成同一个宽度。
CHARACTER_BOX_WIDTH = 230

#: 它的提示文字。⚠ 别写长 —— 230px 里只放得下约 190px 的字，
#: "打名字或拼音筛选，再从列表里选"（210px）会被截成带省略号的半句。
CHARACTER_BOX_HINT = "选角色（可打拼音筛）"


class FilterComboBox(EditableComboBox):
    """可自由输入的下拉框：输入什么，候选就按"包含"过滤成什么；匹配不到 → 没有候选。

    行为对齐"点一下输入框就把候选摊开，边打字边筛"：

    - **点输入框本身就展开**（不用非得去够右边那个小箭头）；
    - 菜单开着的时候**输入即过滤**，候选列表就地变。

    能这么做的前提是框架的下拉菜单**不是模态的** —— ``RoundMenu.exec()`` 内部只调
    ``show()``，没有起模态事件循环，所以菜单挂在上面的同时输入框照样收键盘。

    另外框架自带的 ``EditableComboBox`` 有两个毛病，这里也绕开了：

    1. 输入时**不筛候选**（这里改成输入即重建候选列表）；
    2. 回车时会把匹配不到的内容**塞进候选列表**（越用越脏）—— 这里直接不塞。

    注意不能调 ``addItem()``：它有个副作用，往空列表加第一项时会顺手 ``setText()``，
    把用户正在输入的内容改掉。所以过滤时是直接改 ``items`` 的。
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._all: list[tuple[str, QIcon | None]] = []
        #: 预计算的拼音索引 ``{文本: (全拼, 首字母)}`` —— 每次按键现算会卡
        self._pinyin: dict[str, tuple[str, str]] = {}
        self.textChanged.connect(self._apply_filter)
        self.textChanged.connect(self._refresh_open_menu)

    # ------------------------------------------------------------ 数据
    def set_choices(self, choices: list[tuple[str, QIcon | None]]) -> None:
        """设定全部候选，并按当前输入立刻过滤一次。"""
        self._all = list(choices)
        self._pinyin = {text: pinyin_keys(text) for text, _icon in self._all}
        self._apply_filter(self.text())

    def matched_texts(self) -> list[str]:
        """当前候选里的文本 —— 测试和调试用。"""
        return [item.text for item in self.items]

    def menu_texts(self) -> list[str]:
        """下拉菜单里此刻真正显示着的条目文本（没打开就是空表）。"""
        menu = self.dropMenu
        if menu is None or not menu.isVisible():
            return []
        return [action.text() for action in menu.actions()]

    def is_menu_open(self) -> bool:
        return self.dropMenu is not None and self.dropMenu.isVisible()

    def _apply_filter(self, keyword: str) -> None:
        self._fill_items(keyword)

    def _fill_items(self, keyword: str) -> None:
        """按关键词重建候选。空关键词 = 全部。"""
        self.items.clear()
        key = (keyword or "").strip()
        for text, icon in self._all:
            if self._matches(text, key):
                self.items.append(_make_item(text, icon))

    def _matches(self, text: str, key: str) -> bool:
        """匹配规则见模块级 :func:`matches_keyword`（全项目共用一份）。"""
        return matches_keyword(self._pinyin.get(text, ("", "")), text, key)

    # ------------------------------------------------------------ 交互
    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt 回调
        """点输入框本身也能把候选摊开。"""
        super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.LeftButton and not self.is_menu_open():
            # 延到这次点击处理完再弹，免得跟 LineEdit 自己的按下处理打架
            QTimer.singleShot(0, self._open_menu)

    def _open_menu(self) -> None:
        # 点开时先把候选摊全：点输入框多半是想换一个，只留当前那一条等于没法换
        # （还得先手动把字删掉）。一开始打字就会切回"按内容过滤"。
        self._fill_items("")
        self._clamp_current_index()
        self._showComboMenu()
        # 菜单浮层不该把焦点从输入框上抢走，否则打字就断了
        self.setFocus()

    def _clamp_current_index(self) -> None:
        """把 currentIndex 钳进候选范围里。

        ⭐ 这是补框架的越界 bug：``_showComboMenu`` 里有这么一句

            menu.setDefaultAction(menu.actions()[self.currentIndex()])

        它只判断了"候选非空"，**没判断 index 有没有超出过滤后的条数**。
        场景：选中「穗穗」→ currentIndex 是它在全表里的位置（三十几）
        → 再点输入框 → 候选被按文本过滤成 1 条 → ``actions()[三十几]``
        → IndexError，菜单直接弹不出来。

        用户看到的就是「选了一个角色，想改却报错」。

        ⚠ 这里**必须直接改 `_currentIndex`，不能调 `setCurrentIndex(-1)`** ——
        那条路会连带触发 `setPlaceholderText` / `_updateTextState`，实测效果是
        用户选好的角色名被清空（点一下输入框，名字就没了）。
        直接赋值只动索引，输入框里的文字原封不动。
        """
        if self.items and not (0 <= self.currentIndex() < len(self.items)):
            self._currentIndex = -1

    def _refresh_open_menu(self, _text: str) -> None:
        """菜单开着时，把候选换成新的过滤结果。

        做法是**关掉重开**，不是去改已显示菜单的条目 —— 因为 ``QMenu.clear()`` 会把
        框架设的 ``defaultAction`` 一起删掉，菜单会跟着消失（试过，会直接关掉）。
        重开一次位置也会重新算，两步都在同一个事件循环里，视觉上看不出来。
        """
        if not self.is_menu_open():
            return

        self._closeComboMenu()
        if not self.items:
            # 一条都不匹配就别留个空框
            return

        self._clamp_current_index()
        self._showComboMenu()
        # 菜单浮层不该把焦点从输入框上抢走，否则打字就断了
        self.setFocus()

    # ------------------------------------------------------------ 菜单形态
    def _createComboMenu(self):  # noqa: N802 - 覆盖框架钩子
        """把菜单做成**不抢键盘**的浮层。

        框架的菜单是 ``Qt.Popup`` 窗口，而 Popup 会 ``grabKeyboard()`` ——
        菜单一显示，输入框就一个字符都收不到了（表现是"能点开候选，但打不了字"）。
        这里摘掉 Popup 标志、改成 Tool + 不激活，键盘才会继续送到输入框。

        代价是失去 Popup 自带的"点外面自动关"，那个由 :meth:`focusOutEvent` 兜底。
        """
        menu = super()._createComboMenu()
        menu.setWindowFlags(
            (menu.windowFlags() & ~Qt.WindowType.Popup)
            | Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            # 关键的一条：菜单连焦点都不接受。否则用户去点菜单项时，菜单会先激活、
            # 输入框跟着失焦，而"失焦就收菜单"会抢在点击生效之前把菜单关掉 ——
            # 表现就是"选了一个角色，什么都没发生"。
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        menu.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        return menu

    def _onItemClicked(self, index: int) -> None:  # noqa: N802 - 覆盖框架行为
        super()._onItemClicked(index)
        # 不是 Popup 了，选中之后得自己把菜单收起来；
        # 顺手把焦点拿回输入框，用户能接着改。
        self._closeComboMenu()
        self.setFocus()

    def focusOutEvent(self, event) -> None:  # noqa: N802 - Qt 回调
        super().focusOutEvent(event)
        # 焦点一离开输入框就收起候选（非 Popup 的菜单不会自己关）
        QTimer.singleShot(0, self._close_menu_if_blurred)

    def _close_menu_if_blurred(self) -> None:
        if not self.is_menu_open():
            return
        # 焦点落在菜单自己身上时不能关（用户正要点某一项）
        menu = self.dropMenu
        focused = QApplication.focusWidget()
        if focused is not None and menu is not None:
            if focused is menu or menu.isAncestorOf(focused):
                return
        if not self.hasFocus():
            self._closeComboMenu()

    def _onReturnPressed(self) -> None:  # noqa: N802 - 覆盖框架行为
        """回车只接受"完全等于某个候选"的输入，绝不往候选里加新内容。"""
        key = self.text().strip()
        for index, item in enumerate(self.items):
            if item.text == key:
                self.setCurrentIndex(index)
                self._closeComboMenu()
                return


class IconComboBox(QWidget):
    """带图标的下拉选择：按钮显示当前项（图标 + 文本），点开是带图标的菜单。

    为什么不用框架的 ``ComboBox``：它继承的是 ``QPushButton``、当前项是自绘的，
    实测**不画 item 的图标**（``addItem(icon=...)`` 的图标在界面上看不到）。
    需求明确要"套装图标 + 名称"，所以这里用 ``PushButton`` + ``RoundMenu`` 自己拼一个。
    """

    changed = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._items: list[tuple[str, QIcon]] = []
        self._current = ""

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.button = PushButton(self)
        self.button.setIconSize(QSize(22, 22))
        self.button.clicked.connect(self._show_menu)
        layout.addWidget(self.button)

    # ------------------------------------------------------------ 数据
    def set_items(self, items: list[tuple[str, QIcon]]) -> None:
        self._items = list(items)
        if self._items:
            self.set_current(self._items[0][0])

    def count(self) -> int:
        return len(self._items)

    def current_text(self) -> str:
        return self._current

    def set_current(self, text: str, *, emit: bool = False) -> None:
        self._current = text
        icon = next((ic for name, ic in self._items if name == text), None)
        self.button.setText(text)
        self.button.setIcon(icon if icon is not None else QIcon())
        if emit:
            self.changed.emit(text)

    # ------------------------------------------------------------ 菜单
    def _show_menu(self) -> None:
        if not self._items:
            return
        menu = RoundMenu(parent=self)
        for text, icon in self._items:
            action = QAction(icon, text, menu)
            action.setCheckable(True)
            action.setChecked(text == self._current)
            action.triggered.connect(
                lambda _checked=False, t=text: self.set_current(t, emit=True)
            )
            menu.addAction(action)
        menu.exec(self.button.mapToGlobal(self.button.rect().bottomLeft()), ani=True)


#: 属性复选框每行放几个。
#:
#: 3C 的主词条有 **10 条**（六种属性伤害加成 + 攻击% / 防御% / 生命% / 共鸣效率），
#: 单行放不下会横向溢出（把右边的勾选框挤出可视区），所以改成**固定列数的网格**。
#:
#: 为什么不用 FlowLayout（自动换行那种）：它靠 ``heightForWidth`` 算高度，
#: 而 Qt 的 QBoxLayout **不传播**这个值，外层滚动区会把内容压扁 ——
#: 这个坑本项目为资源库卡片返工过两次，不再踩第三次。
STAT_COLUMNS = 5


class StatChooser(QWidget):
    """一个声骸的候选属性：**多选** —— 想勾几条勾几条。

    2026-09-22 起 从"复选框外观、单选语义"改成了真多选：
    一条声骸可以同时要「暴击 + 暴击伤害」等多条主词条。
    """

    changed = Signal(tuple)   # 当前勾中的全部属性

    def __init__(self, stats: tuple[str, ...], parent: QWidget | None = None):
        super().__init__(parent)
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(14)
        self._grid.setVerticalSpacing(4)

        self._boxes: dict[str, CheckBox] = {}
        for stat in stats:
            self._add_box(stat)

    # ------------------------------------------------------------ 内部
    def _add_box(self, stat: str) -> CheckBox:
        """加一个属性框，按已有个数自动算行列。"""
        box = CheckBox(stat, self)
        box.stateChanged.connect(self._emit_changed)
        index = len(self._boxes)
        self._grid.addWidget(box, index // STAT_COLUMNS, index % STAT_COLUMNS)
        self._boxes[stat] = box
        return box

    def _emit_changed(self, _state: int) -> None:
        self.changed.emit(self.values())

    def values(self) -> tuple[str, ...]:
        """当前勾中的全部属性（按摆放顺序）。"""
        return tuple(name for name, box in self._boxes.items() if box.isChecked())

    def set_values(self, stats) -> None:
        """勾上给定的属性（str 视作单条）；列表外的全部取消。"""
        wanted = {stats} if isinstance(stats, str) else set(stats)
        # 老配置里可能存着已经不在词条池里的属性（比如 3C 早先那个笼统的
        # "属性伤害加成" —— 现在拆成了六种具体属性）。这种情况**补一个框把它显示出来**，
        # 而不是默默丢掉：否则打开"修改"看到的是一圈没勾的空框，
        # 用户根本不知道原来选的是什么，保存时还会被"还没选属性"拦住。
        for stat in wanted:
            if stat and stat not in self._boxes:
                self._add_box(stat)

        for name, box in self._boxes.items():
            checked = name in wanted
            if box.isChecked() != checked:
                box.blockSignals(True)
                box.setChecked(checked)
                box.blockSignals(False)

    # ------------------------------------------------------------ 兼容旧调用
    def value(self) -> str:
        """兼容读取：勾中的第一条（没有就是空串）。"""
        checked = self.values()
        return checked[0] if checked else ""

    def set_value(self, stat: str) -> None:
        self.set_values(stat)


class EchoPickRow(QWidget):
    """一行声骸：左「图标 + 名称」/ 中「属性多选」/ 右「勾选该声骸」。"""

    changed = Signal()

    def __init__(self, echo: EchoInfo, parent: QWidget | None = None):
        super().__init__(parent)
        self.echo = echo

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(12)

        icon = load_icon(echo.icon)
        if icon.isNull():
            # 缺图时留一块同尺寸的空白，别让整行错位
            holder: QWidget = QLabel(self)
        else:
            holder = IconWidget(icon, self)
        holder.setFixedSize(QSize(34, 34))
        layout.addWidget(holder)

        name = BodyLabel(echo.name, self)
        name.setFixedWidth(92)
        layout.addWidget(name)

        self.stats_widget = StatChooser(echo.stats, self)
        self.stats_widget.changed.connect(lambda _stats: self.changed.emit())
        layout.addWidget(self.stats_widget)

        self.check = CheckBox("", self)
        self.check.setFixedWidth(28)
        self.check.stateChanged.connect(self._on_check)
        layout.addWidget(self.check)

        self._sync_enabled()

    # ------------------------------------------------------------ 状态
    def is_selected(self) -> bool:
        return self.check.isChecked()

    def set_selected(self, selected: bool, *, silent: bool = False) -> None:
        if silent:
            self.check.blockSignals(True)
        self.check.setChecked(selected)
        if silent:
            self.check.blockSignals(False)
        self._sync_enabled()

    def stats(self) -> tuple[str, ...]:
        return self.stats_widget.values()

    def set_stats(self, stats) -> None:
        self.stats_widget.set_values(stats)

    # ------------------------------------------------------------ 兼容旧调用
    def stat(self) -> str:
        """兼容读取：勾中的第一条。"""
        return self.stats_widget.value()

    def set_stat(self, stat: str) -> None:
        self.stats_widget.set_value(stat)

    def _on_check(self, _state: int) -> None:
        self._sync_enabled()
        self.changed.emit()

    def _sync_enabled(self) -> None:
        # 没勾这个声骸时，属性框置灰 —— 一眼能看出"先勾左边那个框"
        self.stats_widget.setEnabled(self.check.isChecked())
