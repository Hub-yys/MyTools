"""配置页：一条一条列出已保存的配置，每条可查看详情 / 修改 / 删除，左上角新增。

页面上有**两类**配置（点「新增」时先选类型）：

* **角色声骸筛选配置** —— 数据在 :class:`~src.core.loadout.LoadoutStore`（`loadouts.json`）
* **角色声骸强化配置** —— 数据在 :class:`~src.core.echo_profile.EchoProfileStore`
  （`echo_profiles.json`）。存的是**判定条件**（核心属性 / 双爆下限 / 有效词条数…）。

两类都是**一个角色一条**（用户 2026-09-26 要求），角色只能从下拉里选、不能自由输入。

两类都是本地 JSON，所以"改完刷新列表"就是重新读一遍存储，没有别的状态要同步。
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

from ..core.battle_profile import BattleProfile, BattleProfileStore
from ..core.echo_profile import EchoProfileStore
from ..core.loadout import Loadout, LoadoutStore
from ..core.registry import logger
from .compat import CaptionLabel, ElidedLabel, SearchLineEdit, TitleLabel, resolve_icon
from .config_names import KIND_BATTLE_PROFILE, KIND_ECHO_PROFILE, KIND_LOADOUT
from .pickers import matches_keyword, pinyin_keys
from .battle_profile_ui import BattleProfileDialog, BattleProfileRow
from .echo_profile_ui import (
    TYPE_BATTLE_PROFILE,
    TYPE_ECHO_PROFILE,
    TYPE_LOADOUT,
    ConfigTypeDialog,
    EchoProfileDialog,
    EchoProfileRow,
    config_display_name,
)
from .loadout_dialog import LoadoutDetailDialog, LoadoutDialog
from .pickers import avatar_icon, load_icon

#: 行内边距 / 元素间距
ROW_PADDING = 16
ROW_SPACING = 16
#: 左侧「头像 + 名字」那一列的宽度（名字在头像**下面**）。
#: ⚠ 2026-09-26 从 88 加宽到 160：名字现在带类型后缀（「绯雪-声骸筛选」），
#: 最长的组合「漂泊者·衍射-声骸筛选」实测 **154px**，88 会被省略号截掉。
#: 这个数要跟 ``echo_profile_ui.ROW_LEFT_WIDTH`` 保持一致。
ROW_LEFT_WIDTH = 160
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


def _type_count(count: int, type_name: str) -> str:
    """「N 条<类型名>配置」—— 类型名一律来自 :data:`TYPE_*` 常量，别写死。

    ⚠ 常量是**类型名**（「角色声骸筛选」），这里补的「配置」是个量词性的后缀；
    常量本身要是已经以「配置」结尾就不重复补 —— 免得出现"筛选配置配置"。
    """
    suffix = "" if type_name.endswith("配置") else "配置"
    return f"{count} 条{type_name}{suffix}"


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
        """左列：头像在上，角色名在**下面**。

        角色名用 :class:`~src.gui.compat.ElidedLabel`：**单行 + 超宽省略号**。
        这里原来是个既没限宽、也没开换行的 ``StrongBodyLabel`` ——
        左列宽度是钉死的 88，长名会横向溢出、把摘要挤变形（和
        「角色声骸强化」那行同一个毛病，2026-09-26 一起修）。
        """
        box = QWidget(self)
        box.setFixedWidth(ROW_LEFT_WIDTH)
        column = QVBoxLayout(box)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(4)

        # 图没拿到就用角色名首字现画一个（用户 2026-09-28 要求）
        avatar = avatar_icon(self.loadout.display_avatar, self.loadout.character)
        holder: QWidget = IconWidget(avatar, box) if not avatar.isNull() else QLabel(box)
        holder.setFixedSize(QSize(ROW_AVATAR_SIZE, ROW_AVATAR_SIZE))
        column.addWidget(holder, 0, Qt.AlignmentFlag.AlignHCenter)

        name = ElidedLabel(config_display_name(TYPE_LOADOUT, self.loadout.character),
                           box, width=ROW_LEFT_WIDTH,
                           align=Qt.AlignmentFlag.AlignHCenter)
        self.nameLabel = name
        column.addWidget(name, 0, Qt.AlignmentFlag.AlignHCenter)
        column.addStretch(1)
        return box

    # ---------------------------------------------------------------- 尺寸
    def set_summary_width(self, avail: int) -> None:
        """``avail`` = 这一行**能用的总宽**（页面已扣掉页边距和滚动条）。

        扣掉**本行自己的** ``_ROW_CHROME`` 才是摘要宽度。页面不再统一扣一个常量 ——
        否则按钮多的那类行（「角色声骸强化」有 4 个按钮）必然超出、最右边的按钮被切掉。

        为什么必须把宽度钉死再量高度：QLabel 自动换行的高度是靠 ``heightForWidth``
        算的，而 Qt 的 ``QBoxLayout`` **不传播**这个值 —— 父布局会按"一行"给高度，
        摘要最后一行就被裁掉了（本项目在资源库卡片上踩过同一个坑）。
        """
        self.summary.setFixedWidth(max(160, int(avail) - _ROW_CHROME))
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
        #: 声骸自动强化的多套配置
        self.profiles = EchoProfileStore()
        #: ★ 角色战斗配置（2026-09-30 新增，用户要求）
        self.battles = BattleProfileStore()
        self._migrate_profiles()

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
    def _migrate_profiles(self) -> None:
        """清掉老版本**自动种出来**的那条「默认」。

        老版本第一次运行会种一条叫「默认」的配置（它不是角色 → 没有头像），
        新增时还从它复制。用户 2026-09-26 明确要求：
        **"去掉种子并删掉已有的「默认」"**。

        → 所以这里**不再种子**，只做一次清理。
        新建配置的起点见 :meth:`add_echo_profile`（＝出厂默认）。
        """
        self.profiles.load()
        self.profiles.purge_legacy_default()

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

        # ---- 搜索框（用户 2026-09-30："加上搜索，和前面下拉列表搜索一样的"）----
        # "和下拉列表一样" = 复用 FilterComboBox 那套匹配：中文子串 +
        # **拼音全拼/首字母**都认（见 pickers.pinyin_keys / matches_keyword）。
        # ⚠ 这里不用 FilterComboBox（那是下拉框），只用它的匹配函数。
        self.search_edit = SearchLineEdit(self.view)
        self.search_edit.setPlaceholderText(
            "搜索角色名（支持拼音，如 feixue / fx）")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setFixedWidth(280)
        self.search_edit.textChanged.connect(self._on_search_changed)
        search_row = QHBoxLayout()
        search_row.setContentsMargins(0, 0, 0, 0)
        search_row.addWidget(self.search_edit)
        search_row.addStretch(1)
        self.root_layout.addLayout(search_row)

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

    def _on_search_changed(self, _text: str) -> None:
        """搜索词变了 → 只重建列表（不动存储）。

        ⚠ 走 ``reload()`` 而不是"就地隐藏行"：列表本来就是**按数据重建**的
        （增删改之后也走同一条路），保持一致、少一处状态要同步。
        """
        self.reload()

    def _keyword(self) -> str:
        return (self.search_edit.text() or "").strip()

    def _matches_search(self, name: str) -> bool:
        """这一条的角色名是否命中搜索词（空搜索词 = 全命中）。"""
        key = self._keyword()
        if not key:
            return True
        return matches_keyword(pinyin_keys(name), name, key)

    # ---------------------------------------------------------------- 列表
    def _clear_list(self) -> None:
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def reload(self) -> None:
        """按存储里的内容重建列表（增删改之后都调它）。

        ★ 搜索也在这一步生效（2026-09-30）：**过滤只影响显示，不动存储** ——
        行还是照常从存储里读出来的，只是不命中的不摆上来。
        """
        self._clear_list()

        all_loadouts = self.store.all()
        all_profiles = self.profiles.all()
        all_battles = self.battles.all()
        keyword = self._keyword()
        loadouts = [x for x in all_loadouts if self._matches_search(x.character)]
        profiles = [x for x in all_profiles if self._matches_search(x.name)]
        battles = [x for x in all_battles if self._matches_search(x.name)]

        self.subtitle.setText(self._subtitle_text(
            loadouts, profiles, battles,
            all_loadouts, all_profiles, all_battles, keyword))
        self.subtitle.setVisible(True)

        if not loadouts and not profiles and not battles:
            self.list_layout.addWidget(self._empty_hint(keyword))
            return

        # ---- 角色声骸强化（判定条件，和强化工具自己的设置互不影响）----
        # 标题一律用 TYPE_* 常量，别再写一遍字面量 —— 改显示名时只改一处
        if profiles:
            self.list_layout.addWidget(self._section(TYPE_ECHO_PROFILE))
            for profile in profiles:
                row = EchoProfileRow(profile, parent=self.list_host)
                row.editRequested.connect(self.edit_profile)
                row.viewRequested.connect(self.view_profile)
                row.deleteRequested.connect(self.delete_profile)
                self.list_layout.addWidget(row)

        # ---- 角色战斗配置（★ 2026-09-30 新增）----
        if battles:
            self.list_layout.addWidget(self._section(TYPE_BATTLE_PROFILE))
            for battle in battles:
                row = BattleProfileRow(battle, parent=self.list_host)
                row.editRequested.connect(self.edit_battle)
                row.viewRequested.connect(self.view_battle)
                row.deleteRequested.connect(self.delete_battle)
                self.list_layout.addWidget(row)

        # ---- 角色声骸筛选配置 ----
        if loadouts:
            self.list_layout.addWidget(self._section(TYPE_LOADOUT))
            for loadout in loadouts:
                row = LoadoutRow(loadout, self.list_host)
                row.viewRequested.connect(self.open_view_dialog)
                row.editRequested.connect(self.open_edit_dialog)
                row.deleteRequested.connect(self.delete_loadout)
                self.list_layout.addWidget(row)

        # 新行都是默认宽度建的，这里按当前视口重算一次（顺带定好行高）
        self._last_row_width = -1
        self._apply_row_width()

    def _subtitle_text(self, loadouts, profiles, battles,
                       all_loadouts, all_profiles, all_battles,
                       keyword: str) -> str:
        """副标题：搜索时显示"命中多少 / 共多少"，没搜索就显示总数。

        ⚠ 搜索时**必须带上总数** —— 否则用户看到"共 1 条"会以为配置被删了。
        """
        if not keyword:
            return "共 " + " · ".join((
                _type_count(len(all_profiles), TYPE_ECHO_PROFILE),
                _type_count(len(all_battles), TYPE_BATTLE_PROFILE),
                _type_count(len(all_loadouts), TYPE_LOADOUT),
            ))
        hit = len(profiles) + len(loadouts) + len(battles)
        total = len(all_profiles) + len(all_loadouts) + len(all_battles)
        return f"搜索「{keyword}」：命中 {hit} / 共 {total} 条"

    def _empty_hint(self, keyword: str) -> QWidget:
        """空列表提示 —— 分"一条都没有"和"搜不到"两种情况。

        两者原因完全不同（一个是没建、一个是搜索词不对），
        提示混在一起会让用户白找半天。
        """
        if keyword:
            text = f"没有匹配「{keyword}」的配置。换个词试试（支持拼音）。"
        else:
            text = "还没有配置，点上面的「新增」建一条。"
        empty = CaptionLabel(text, self.list_host)
        empty.setTextColor("#8A8F98", "#7C7C7C")
        return empty

    def _section(self, text: str) -> QWidget:
        """两类配置之间的小标题。"""
        holder = QWidget(self.list_host)
        box = QVBoxLayout(holder)
        box.setContentsMargins(2, 6, 2, 0)
        box.addWidget(StrongBodyLabel(text, holder))
        return holder

    # ---------------------------------------------------------------- 尺寸
    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt 回调
        super().resizeEvent(event)
        self._apply_row_width()

    def _apply_row_width(self) -> None:
        """按当前视口宽度重算每行的摘要宽度 —— 行高跟着摘要行数走。

        页面只负责算出**每行能用的总宽**（视口减页边距/滚动条）；
        扣掉"本行自己的固定部分"由各行自己做 —— 两类行的按钮个数不同，
        不能共用一个常量（共用会让按钮多的那类超出、最右边按钮被切）。
        """
        avail = self.viewport().width() - _PAGE_CHROME
        if avail == self._last_row_width:
            return
        self._last_row_width = avail
        # ⚠ findChildren 只接单个类型（给元组会 TypeError），三类各查一次
        for cls in (LoadoutRow, EchoProfileRow, BattleProfileRow):
            for row in self.findChildren(cls):
                row.set_summary_width(avail)

    # ---------------------------------------------------------------- 动作
    def open_add_dialog(self) -> None:
        """新增 —— 先问建哪一类（现在有三类配置）。"""
        chooser = ConfigTypeDialog(self.window())
        if not chooser.exec():
            return
        chosen = chooser.chosen_type()
        if chosen == TYPE_ECHO_PROFILE:
            self.add_echo_profile()
        elif chosen == TYPE_BATTLE_PROFILE:
            self.add_battle()
        else:
            # 已被占用的角色传进去 —— 新增时"一个角色只能有一条"
            dialog = LoadoutDialog(
                self.window(), taken_chars=self.store.occupied_characters())
            if dialog.exec():
                self.store.add(dialog.result_loadout())
                self.reload()

    # ---------------------------------------------------- 角色声骸强化配置
    def add_echo_profile(self) -> None:
        """新增一条「角色声骸强化」。

        * **角色只能从下拉里选**（已被占用的角色选不到）；
        * 规则起点是**出厂默认** —— 也就是你打开「声骸自动强化」页**每次看到的那套**。

        ## ★ 为什么是出厂默认，而不是 ``tool_settings`` 里存的那套

        用户 2026-09-26 的批注是"这里应该跟声骸自动强化一样"，
        三条具体抱怨：双爆下限**不该默认不启用**、可选**不该默认勾着**、
        有效词条**不该默认 3 条**。

        一开始这里读的是 ``tool_settings.load("echo_enhance")``
        （＝磁盘上存的那套，用户上次改过），于是弹框一打开就是
        `不启用 / 勾了 2 条 / 3 条` —— 和他看到的工具页**不一样**：

        ==================  ==========  =========  ========  ==========
        起点                 可选        双爆启用    有效词条
        ==================  ==========  =========  ========  ==========
        工具页（每次进去）     空          启用        2
        弹框（读存盘）         勾了 2 条    不启用      3
        出厂默认              空          启用        2
        ==================  ==========  =========  ========  ==========

        关键：**「声骸自动强化」页每次进入都显示出厂默认**（用户早先定的
        "每次进入都是出厂默认"），它**不显示** ``tool_settings`` 里存的值。
        所以"跟工具页一样"＝出厂默认，不是存盘值。

        → ``initial_settings=None`` 时 ``EchoSettings.from_dict({})``
        给出的就是出厂默认（见 :meth:`EchoProfileDialog`）。
        """
        dialog = self._new_profile_dialog()
        if not dialog.exec():
            return

        from ..core.echo_profile import EchoProfile  # noqa: PLC0415 - 只在新建时用

        self.profiles.add(EchoProfile(name=dialog.profile_name(),
                                      settings=dialog.result_settings()))
        self.reload()

    def _new_profile_dialog(self) -> EchoProfileDialog:
        """构造"新增配置"用的弹框 —— 起点是**出厂默认**。

        ⚠ 单独抽出来是为了能被检查脚本**直接构造**：``add_echo_profile`` 里有
        ``exec()``，测试里弹不出来。**这个 bug 恰恰出在传参上**
        （曾经传了 ``initial_settings=tool_settings.load("echo_enhance")``），
        所以护栏必须走这条真实路径，不能自己 new 一个弹框来测 ——
        那样测的只是"弹框的默认行为"，拦不住"调用方传错了起点"。
        """
        return EchoProfileDialog(self.window(), profile=None,
                                 taken_chars=self.profiles.occupied_characters())

    def edit_profile(self, name: str) -> None:
        """编这套判定条件 —— 用的**就是**强化工具页那份设置界面。

        角色也能换（下拉里选），但不能换成已经被别的配置占用的角色。
        """
        profile = self.profiles.get(name)
        if profile is None:
            return
        dialog = EchoProfileDialog(
            self.window(), profile=profile,
            taken_chars=self.profiles.occupied_characters())
        if not dialog.exec():
            return
        new_name = dialog.profile_name()
        if new_name and new_name != profile.name:
            self.profiles.rename(profile.name, new_name)      # 换角色
            profile = self.profiles.get(new_name) or profile
        profile.settings = dialog.result_settings()
        self.profiles.update(profile)
        self.reload()

    def view_profile(self, name: str) -> None:
        """只读地看一眼这套规则 —— 同一个界面的只读版（改不了）。"""
        profile = self.profiles.get(name)
        if profile is None:
            return
        EchoProfileDialog(self.window(), profile=profile, read_only=True).exec()

    # ------------------------------------------------ 角色战斗（★ 2026-09-30）
    def _new_battle_dialog(self) -> BattleProfileDialog:
        """构造"新增"用的弹框（单独抽出来便于检查脚本直接构造）。"""
        return BattleProfileDialog(
            self.window(), profile=None,
            taken_chars=self.battles.occupied_characters())

    def add_battle(self) -> None:
        """新增一条「角色战斗」配置。

        * **角色只能从下拉里选**（已被占用的选不到）；
        * 起点：快捷键 Q/E/R、链路 0、脚本空（见 ``DEFAULT_SKILL_KEYS``）。
        """
        dialog = self._new_battle_dialog()
        if not dialog.exec():
            return
        self.battles.add(dialog.result_profile())
        self.reload()

    def edit_battle(self, name: str) -> None:
        """改快捷键 / 链路 / 战斗脚本。角色也能换（但不能换成已被占用的）。"""
        profile = self.battles.get(name)
        if profile is None:
            return
        dialog = BattleProfileDialog(
            self.window(), profile=profile,
            taken_chars=self.battles.occupied_characters())
        if not dialog.exec():
            return
        new_name = dialog.profile_name()
        if new_name and new_name != profile.name:
            self.battles.rename(profile.name, new_name)      # 换角色
            profile = self.battles.get(new_name) or profile
        updated = dialog.result_profile()
        profile.skill_keys = updated.skill_keys
        profile.chain = updated.chain
        profile.script = updated.script
        self.battles.update(profile)
        self.reload()

    def view_battle(self, name: str) -> None:
        """只读地看一眼这套配置。"""
        profile = self.battles.get(name)
        if profile is None:
            return
        BattleProfileDialog(self.window(), profile=profile,
                            read_only=True).exec()

    def delete_battle(self, name: str) -> None:
        profile = self.battles.get(name)
        keys = [k for k in ((profile.id if profile else ""), name) if k]
        if self._blocked_by_flows(
                KIND_BATTLE_PROFILE,
                f"「{config_display_name(TYPE_BATTLE_PROFILE, name)}」", *keys):
            return

        box = MessageBox("删除配置",
                         f"确定删除「{config_display_name(TYPE_BATTLE_PROFILE, name)}」"
                         "这条配置吗？删掉就找不回来了。", self.window())
        box.yesButton.setText("删除")
        box.cancelButton.setText("取消")
        if box.exec():
            self.battles.remove(name)
            self.reload()

    def _used_by_flows(self, kind: str, *keys) -> list[str]:
        """这条配置正被哪些任务流程引用？读不到任务存储时返回空（不拦）。"""
        try:
            from ..core.tasks import TaskStore, flows_using_config

            return flows_using_config(TaskStore().all(), kind, *keys)
        except Exception:  # noqa: BLE001 - 读任务出错不该把"删除配置"整个卡死
            logger.warning("检查配置引用失败（kind=%s, keys=%s）", kind, keys,
                           exc_info=True)
            return []

    def _blocked_by_flows(self, kind: str, display: str, *keys) -> bool:
        """配置被任务流程引用 → 弹提示并**拒绝删除**，返回 True。

        用户 2026-09-28 要求："已完成任务流程里使用的配置，不能直接删除配置，
        需要先删除任务，才能删除配置"。

        ⚠ 这里用的是 ``MessageBox`` 而不是 ``InfoBar``：``InfoBar`` 只是浮一条
        提示，用户很容易看漏，然后一脸茫然"为什么点了删除没反应"。
        弹框能明确告诉他**是哪几条流程**在占用、以及该怎么办。
        """
        users = self._used_by_flows(kind, *keys)
        if not users:
            return False

        shown = "、".join(f"「{name}」" for name in users[:5])
        if len(users) > 5:
            shown += f" 等 {len(users)} 条"
        box = MessageBox(
            "配置正在被使用",
            f"{display} 正被 {shown} 任务流程使用，不能删除。\n\n"
            "请先到「任务」页删除这些流程，再回来删除配置 —— "
            "否则那些流程里的一步会失效（工具拿不到配置）。",
            self.window(),
        )
        box.yesButton.setText("知道了")
        box.cancelButton.hide()          # 只读提示，没有可取消的操作
        box.exec()
        return True

    def delete_profile(self, name: str) -> None:
        profile = self.profiles.get(name)
        # 引用它的键：稳定 id + 名字（老流程存的是角色名，见 flows_using_config）
        keys = [k for k in ((profile.id if profile else ""), name) if k]
        if self._blocked_by_flows(
                KIND_ECHO_PROFILE,
                f"「{config_display_name(TYPE_ECHO_PROFILE, name)}」", *keys):
            return

        box = MessageBox("删除配置",
                         f"确定删除「{config_display_name(TYPE_ECHO_PROFILE, name)}」"
                         "这条配置吗？删掉就找不回来了。", self.window())
        box.yesButton.setText("删除")
        box.cancelButton.setText("取消")
        if box.exec():
            self.profiles.remove(name)
            # ⚠ 这里**故意不碰 tool_settings** —— 这类配置和强化工具自己的设置
            #   互不影响，删一条不该把工具正在用的规则改掉。
            #   删到一条不剩也可以（用户明确要求能删掉自动生成的「默认」）。
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
        dialog = LoadoutDialog(self.window(), loadout,
                               taken_chars=self.store.occupied_characters())
        if dialog.exec():
            self.store.update(dialog.result_loadout())
            self.reload()

    def delete_loadout(self, loadout_id: str) -> None:
        loadout = self.store.get(loadout_id)
        if loadout is None:
            return

        # ★ 被任务流程引用的配置不能删（用户 2026-09-28 要求）——
        #   筛选配置的步骤 key 就是 Loadout.id，另外带上角色名兜底。
        keys = [k for k in (loadout_id, getattr(loadout, "character", "")) if k]
        if self._blocked_by_flows(
                KIND_LOADOUT,
                f"「{config_display_name(TYPE_LOADOUT, loadout.character)}」", *keys):
            return

        box = MessageBox(
            "删除配置",
            f"确定删除「{config_display_name(TYPE_LOADOUT, loadout.character)}」"
            "的这条配置吗？删掉就找不回来了。",
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
