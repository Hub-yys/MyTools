"""鸣潮资源库：角色头像 + 声骸套装（图标 + 套装效果）+ 声骸图鉴（图标 + 技能说明）。

## 资料从哪来

页面上显示的东西**全部读自 `src/core/data/*.json`**，这个文件只管展示：

- **角色名 / 属性 / 武器**、**套装名 / 套装效果原文**、**每套有哪些声骸** ——
  整理自公开 wiki，数据文件里带 ``_source`` / ``_fetched`` 注明来源和抓取时间。
  跑 ``tools/refresh_wuwa_data.py`` 可以刷新。
- **声骸技能说明**（图鉴分区）—— 来自 bwiki 每个声骸页的「声骸技能」段落，
  跑 ``tools/fetch_wuwa_echo_skills.py`` 刷新。43 个新声骸 bwiki 还没建页，
  技能是空的（官方详情接口要登录令牌，见该脚本的说明）。
- **图标**（角色头像 / 套装图标 / 声骸图标）—— 是游戏美术素材，**单独用
  ``tools/fetch_wuwa_assets.py`` 从 wiki 拉到本地**，不随代码走。
  想换成自己的图也行：按 ``assets/game/<分类>/<名字>.png`` 覆盖即可。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLayout, QVBoxLayout, QWidget
from qfluentwidgets import CardWidget, IconWidget, ScrollArea

from ..core import game_data
from ..core.game_data import (
    CHARACTERS,
    COST_SECTIONS,
    DATA_META,
    ECHOES_BY_COST,
    ECHO_SETS,
    WEAPONS,
    icon_path,
)
from .compat import CaptionLabel, StrongBodyLabel, TitleLabel, resolve_icon
from .pickers import load_icon
from .widgets import CollapsibleCard

AVATAR_SIZE = 64
AVATAR_COLUMNS = 8
SET_ICON_SIZE = 56
#: 卡片固定宽度 —— 刻意的：QLabel 的自动换行高度靠 heightForWidth 算，
#: 而 Qt 的 QBoxLayout **不支持**把 heightForWidth 正确传上去（嵌套时必然算矮，
#: 效果文字会被裁掉半行）。给死宽度之后 label 的 sizeHint 就是准的，绕开这个坑。
SET_CARD_WIDTH = 640
#: 卡片里文字区能用的宽度 = 卡片宽 - 左右内边距 - 图标列 - 间距
SET_TEXT_WIDTH = SET_CARD_WIDTH - 16 * 2 - SET_ICON_SIZE - 14

#: 说明文字颜色（(浅色主题, 深色主题)）
MUTED = ("#8A8F98", "#7C7C7C")
#: 套装效果正文颜色 —— 比说明文字深一点，是"正文"不是"注解"
BODY = ("#3D4148", "#C6CBD3")


def circular_icon(relative: str, size: int) -> QIcon:
    """把头像裁成圆形 —— 游戏里的角色头像本身就是圆的，方形素材裁一下才对得上。"""
    if not relative:
        return QIcon()
    raw = Path(relative)
    source = raw if raw.is_absolute() else Path(icon_path(relative))
    if not source.exists():
        return QIcon()

    pixmap = QPixmap(str(source))
    if pixmap.isNull():
        return QIcon()

    scaled = pixmap.scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
    canvas = QPixmap(size, size)
    canvas.fill(Qt.GlobalColor.transparent)

    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    clip = QPainterPath()
    clip.addEllipse(0, 0, size, size)
    painter.setClipPath(clip)
    painter.drawPixmap(0, 0, scaled)
    painter.end()

    return QIcon(canvas)


class _AvatarTile(QWidget):
    """一个角色：圆形头像 + 名字 +（有数据的话）属性小字。"""

    def __init__(self, character, parent: QWidget | None = None):
        super().__init__(parent)
        self.character = character

        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(4)
        column.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        icon = circular_icon(character.avatar, AVATAR_SIZE)
        view: QWidget = IconWidget(icon, self) if not icon.isNull() else QWidget(self)
        view.setFixedSize(QSize(AVATAR_SIZE, AVATAR_SIZE))
        column.addWidget(view, 0, Qt.AlignmentFlag.AlignHCenter)

        name = CaptionLabel(character.name, self)
        name.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        column.addWidget(name, 0, Qt.AlignmentFlag.AlignHCenter)

        tagline = character.tagline
        if tagline:
            meta = CaptionLabel(tagline, self)
            meta.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            meta.setTextColor(*MUTED)
            column.addWidget(meta, 0, Qt.AlignmentFlag.AlignHCenter)


class _EchoSetCard(CardWidget):
    """一套声骸套装：图标 + 名称 + 逐条套装效果 + 声骸收录情况。"""

    def __init__(self, echo_set, parent: QWidget | None = None):
        super().__init__(parent)
        self.echo_set = echo_set
        self.setFixedWidth(SET_CARD_WIDTH)

        row = QHBoxLayout(self)
        row.setContentsMargins(16, 14, 16, 14)
        row.setSpacing(14)

        icon = load_icon(echo_set.icon)
        view: QWidget = IconWidget(icon, self) if not icon.isNull() else QWidget(self)
        view.setFixedSize(QSize(SET_ICON_SIZE, SET_ICON_SIZE))
        row.addWidget(view, 0, Qt.AlignmentFlag.AlignTop)

        text_box = QWidget(self)
        column = QVBoxLayout(text_box)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(3)
        column.addWidget(StrongBodyLabel(echo_set.name, text_box))

        if echo_set.effects:
            for line in echo_set.effect_lines:
                label = CaptionLabel(line, text_box)
                label.setWordWrap(True)
                # 必须给死宽度，见 SET_CARD_WIDTH 那里的说明
                label.setFixedWidth(SET_TEXT_WIDTH)
                label.setTextColor(*BODY)
                column.addWidget(label)
        else:
            missing = CaptionLabel("（这套的套装效果还没收录）", text_box)
            missing.setTextColor(*MUTED)
            column.addWidget(missing)

        column.addStretch(1)
        row.addWidget(text_box, 1)

        # ⚠ 把高度钉死。
        # QLabel 自动换行的高度靠 heightForWidth 算，而 Qt 的 QBoxLayout **不传**它，
        # 父布局会把卡片压掉几个像素 —— 表现是最后一行文字被裁掉一半。
        # 布局的 totalSizeHint() 是准的（内部按固定宽度算过），直接拿来当固定高度。
        self.setFixedHeight(self.layout().totalSizeHint().height())


class _EchoRow(CardWidget):
    """一条声骸：左边图标，右边名字 + 技能说明。图鉴区的最小单元。"""

    def __init__(self, echo, parent: QWidget | None = None):
        super().__init__(parent)
        self.echo = echo
        self.setFixedWidth(SET_CARD_WIDTH)

        row = QHBoxLayout(self)
        row.setContentsMargins(16, 14, 16, 14)
        row.setSpacing(14)

        icon = load_icon(echo.icon)
        view: QWidget = IconWidget(icon, self) if not icon.isNull() else QWidget(self)
        view.setFixedSize(QSize(SET_ICON_SIZE, SET_ICON_SIZE))
        row.addWidget(view, 0, Qt.AlignmentFlag.AlignTop)

        text_box = QWidget(self)
        column = QVBoxLayout(text_box)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(3)
        column.addWidget(StrongBodyLabel(echo.name, text_box))

        # 第二行：COST 徽标 + 冷却（有才显示），没有附加信息就跳过这行
        meta_bits = [f"{echo.cost}C"]
        if echo.cooldown:
            meta_bits.append(f"冷却 {echo.cooldown}")
        meta = CaptionLabel(" · ".join(meta_bits), text_box)
        meta.setTextColor(*MUTED)
        column.addWidget(meta)

        if echo.skill:
            skill = CaptionLabel(echo.skill, text_box)
            skill.setWordWrap(True)
            # 必须给死宽度，见 SET_CARD_WIDTH 那里的说明
            skill.setFixedWidth(SET_TEXT_WIDTH)
            skill.setTextColor(*BODY)
            column.addWidget(skill)
        else:
            missing = CaptionLabel("（这个声骸的技能还没收录）", text_box)
            missing.setTextColor(*MUTED)
            column.addWidget(missing)

        column.addStretch(1)
        row.addWidget(text_box, 1)

        # ⚠ 高度钉死 —— 同 _EchoSetCard：QBoxLayout 不传 heightForWidth，
        # 不钉死的话换行文字会被裁掉半行。
        self.setFixedHeight(self.layout().totalSizeHint().height())


class _WeaponRow(CardWidget):
    """一条武器：左边图标，右边名字 + 「星级 · 类型 · 主词条」。

    和 :class:`_EchoRow` 同一套排版（图鉴区的最小单元），
    只是第二行换成武器的属性。
    """

    def __init__(self, weapon, parent: QWidget | None = None):
        super().__init__(parent)
        self.weapon = weapon
        self.setFixedWidth(SET_CARD_WIDTH)

        row = QHBoxLayout(self)
        row.setContentsMargins(16, 14, 16, 14)
        row.setSpacing(14)

        icon = load_icon(weapon.icon)
        view: QWidget = IconWidget(icon, self) if not icon.isNull() else QWidget(self)
        view.setFixedSize(QSize(SET_ICON_SIZE, SET_ICON_SIZE))
        row.addWidget(view, 0, Qt.AlignmentFlag.AlignTop)

        text_box = QWidget(self)
        column = QVBoxLayout(text_box)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(3)
        column.addWidget(StrongBodyLabel(weapon.name, text_box))

        meta = CaptionLabel(weapon.tagline or "（属性未收录）", text_box)
        meta.setTextColor(*MUTED)
        column.addWidget(meta)
        column.addStretch(1)
        row.addWidget(text_box, 1)

        # ⚠ 高度钉死 —— 同 _EchoRow：QBoxLayout 不传 heightForWidth。
        self.setFixedHeight(self.layout().totalSizeHint().height())


class WuwaLibraryInterface(ScrollArea):
    """侧栏「资源库 → 鸣潮资源库」对应的页面。"""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("WuwaLibraryInterface")
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # 兜底：万一 game_data 是在种子数据落盘**之前**被导入的，内存里就是空的。
        # 这里再补读一次盘 —— 首启动"资源库一片空白"就是那个顺序问题造成的。
        game_data.ensure_loaded()

        view = QWidget(self)
        view.setObjectName("wuwaLibraryView")
        layout = QVBoxLayout(view)
        layout.setContentsMargins(36, 32, 36, 28)
        layout.setSpacing(12)
        # 让内容控件的**最小**尺寸等于布局算出来的尺寸 —— 否则 ScrollArea 会把
        # 里面的卡片压扁（QBoxLayout 不传 heightForWidth，换行文字高度算矮）。
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self._view = view
        self._layout = layout

        self._populate(view)
        self._built_version = game_data.DATA_VERSION

        self.setWidget(view)
        self.setWidgetResizable(True)
        # 和其它页面一样：ScrollArea 自己和 viewport 都会吃系统调色板底色
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("#WuwaLibraryInterface { background: transparent; }")
        self.viewport().setStyleSheet("background: transparent;")

    # ---------------------------------------------------------------- 内容
    def _populate(self, view: QWidget) -> None:
        """把全部内容塞进布局。单独一层是为了能**重建**（见 :meth:`rebuild`）。"""
        layout = self._layout
        layout.addWidget(TitleLabel("鸣潮资源库", view))
        layout.addWidget(self._build_source_note(view))

        layout.addSpacing(6)
        layout.addWidget(self._build_avatar_section(view))
        layout.addSpacing(6)
        layout.addWidget(self._build_echo_set_section(view))
        layout.addSpacing(6)
        layout.addWidget(self._build_echo_section(view))
        layout.addSpacing(6)
        layout.addWidget(self._build_weapon_section(view))
        layout.addStretch(1)

    def rebuild(self) -> None:
        """数据换过了（比如刚点完「获取最新数据」）→ 重建整页内容。

        不清空重来是不行的：卡片是**按当时的数据**逐个建出来的，
        光换内存里的列表，界面上还是旧的那些卡片。
        """
        layout = self._layout
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._populate(self._view)
        self._built_version = game_data.DATA_VERSION

    def showEvent(self, event):  # noqa: N802 - Qt 回调
        """每次显示时对一下数据版本，变了就重建 —— 不用重启程序。

        ⚠ 版本号必须读 ``game_data.DATA_VERSION``（模块属性）：
        ``from game_data import DATA_VERSION`` 会在导入时把**数字**抄走，
        之后别人重载多少次它都不会变。
        """
        super().showEvent(event)
        if game_data.DATA_VERSION != self._built_version:
            self.rebuild()

    # ---------------------------------------------------------------- 顶部说明
    def _build_source_note(self, parent: QWidget) -> QWidget:
        """资料出处 + 图标怎么替换，都说清楚（免得把占位图当成真素材）。"""
        holder = QWidget(parent)
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(3)

        fetched = DATA_META.get("fetched") or "未知"
        version = DATA_META.get("game_version") or "未知"
        source = CaptionLabel(
            f"角色 {len(CHARACTERS)} 个 · 声骸套装 {len(ECHO_SETS)} 套"
            f" · 武器 {len(WEAPONS)} 把"
            f"　|　资料整理自公开 wiki，抓取于 {fetched}（游戏版本 {version}）",
            holder,
        )
        source.setTextColor(*MUTED)
        source.setWordWrap(True)
        column.addWidget(source)

        icons = CaptionLabel(
            "图标是从公开 wiki 拉的游戏素材（tools/fetch_wuwa_assets.py 可刷新）。"
            "想换成自己的图，按 assets/game/<分类>/<名字>.png 覆盖即可，代码不用改。",
            holder,
        )
        icons.setTextColor(*MUTED)
        icons.setWordWrap(True)
        column.addWidget(icons)

        return holder

    # ---------------------------------------------------------------- 分区
    # 三个分区都用 CollapsibleCard 包起来：标题行右侧一个箭头按钮，点它展开/收起内容。
    # 默认展开 —— 和加按钮之前的观感一致，不想看再收。

    def _build_avatar_section(self, parent: QWidget) -> QWidget:
        card = CollapsibleCard(f"角色头像（{len(CHARACTERS)}）", expanded=True, parent=parent)

        grid_host = QWidget(card)
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(14)
        for index, character in enumerate(CHARACTERS):
            grid.addWidget(
                _AvatarTile(character, grid_host),
                index // AVATAR_COLUMNS,
                index % AVATAR_COLUMNS,
                Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter,
            )
        # 最后一列留个弹性，免得整行被拉散
        grid.setColumnStretch(AVATAR_COLUMNS, 1)
        card.add(grid_host)
        return card

    def _build_echo_set_section(self, parent: QWidget) -> QWidget:
        card = CollapsibleCard(f"声骸套装（{len(ECHO_SETS)}）", expanded=True, parent=parent)

        for echo_set in ECHO_SETS:
            # ⚠ 这里**不能**加 Qt.AlignmentFlag.AlignLeft：
            # 给布局项设置对齐标志会让 heightForWidth 失效，卡片里的换行文本
            # 高度就算不准 —— 效果文字会被裁掉半行。宽度交给卡片的 maximumWidth 控。
            card.add(_EchoSetCard(echo_set, card))
        return card

    def _build_echo_section(self, parent: QWidget) -> QWidget:
        """声骸图鉴：按 4C / 3C / 1C 分组，每行一条声骸（图标 + 技能说明）。"""
        total = sum(len(items) for items in ECHOES_BY_COST.values())
        card = CollapsibleCard(f"声骸图鉴（{total}）", expanded=True, parent=parent)

        for cost, label in COST_SECTIONS:
            items = ECHOES_BY_COST.get(cost, ())
            if not items:
                continue
            group_title = CaptionLabel(f"{label}（{len(items)}）", card)
            group_title.setTextColor(*MUTED)
            card.add(group_title)
            for echo in items:
                card.add(_EchoRow(echo, card))
        return card

    def _build_weapon_section(self, parent: QWidget) -> QWidget:
        """武器图鉴（2026-09-30 新增）：**按武器类型**分组，每行一把武器。

        用户要求："把武器图也放到资源库，资源库新增分类，武器图鉴"。

        分组跟着游戏里的武器类型来（长刃 / 迅刀 / 佩枪 / 臂铠 / 音感仪），
        组内按名字排 —— 和声骸图鉴按 4C/3C/1C 分组是同一个思路。
        """
        if not WEAPONS:
            return QWidget(parent)      # 没数据就不摆空卡片

        card = CollapsibleCard(f"武器图鉴（{len(WEAPONS)}）", expanded=True,
                               parent=parent)

        # 按类型分组；顺序用**固定表**，别用 set 的随机序
        order = ("长刃", "迅刀", "佩枪", "臂铠", "音感仪")
        by_type: dict[str, list] = {name: [] for name in order}
        for weapon in WEAPONS:
            by_type.setdefault(weapon.type or "其它", []).append(weapon)

        for type_name in (*order, "其它"):
            items = by_type.get(type_name) or []
            if not items:
                continue
            group_title = CaptionLabel(f"{type_name}（{len(items)}）", card)
            group_title.setTextColor(*MUTED)
            card.add(group_title)
            for weapon in sorted(items, key=lambda w: (-w.rarity, w.name)):
                card.add(_WeaponRow(weapon, card))
        return card

    # ---------------------------------------------------------------- 其它
    def icon(self):  # 供主窗口导航用
        return resolve_icon("LIBRARY")
