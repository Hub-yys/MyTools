"""配置页里「角色声骸强化」那几个控件。

单独放一个文件是因为 ``config_interface.py`` 已经管着「角色声骸筛选配置」那一套；
再多一类配置塞进同一个文件会两边都不好读。

    ConfigTypeDialog        点「新增」时先选类型
    EchoProfileDialog       新建 / 编辑 / 查看（查看 = 同一个界面的只读版）
    EchoProfileRow          列表里的一行（头像 + 名字 + 编辑/查看/删除）

⚠ 这一类配置和「声骸自动强化」工具页的设置**没有联动**（用户 2026-09-26 明确），
所以行上**没有**「设为当前」那种按钮 —— 只有增删改查。

样式跟着 ``LoadoutRow`` 走（同一套内边距 / 按钮宽 / 摘要居中换行）。
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget
from qfluentwidgets import (
    CaptionLabel,
    ComboBox,
    IconWidget,
    MessageBoxBase,
    PushButton,
    ScrollArea,
    SimpleCardWidget,
    SubtitleLabel,
)

from ..core.echo_profile import MAX_NAME_LENGTH, EchoProfile
from .compat import ElidedLabel
from .pickers import CHARACTER_BOX_HINT, CHARACTER_BOX_WIDTH, avatar_icon

#: 和 config_interface 里那套保持一致
ROW_PADDING = 16
ROW_SPACING = 16
#: 左列宽（头像 + 名字竖排，和 LoadoutRow 同宽）。
#: ⚠ 2026-09-26 从 88 加宽到 160：名字现在带类型后缀（「绯雪-声骸强化」），
#: 最长的组合「漂泊者·衍射-声骸强化」实测 **154px**，88 会被省略号截掉。
ROW_LEFT_WIDTH = 160
ROW_AVATAR_SIZE = 48         # 头像尺寸，和 LoadoutRow 一致
ROW_BUTTON_WIDTH = 72
ROW_MIN_HEIGHT = 92
#: 本行除摘要之外占掉的宽度（内边距 + 左列 + **三个**按钮 + 它们之间的间距）。
#: ⚠ 这个数每个行类**各算各的**：页面只告诉每一行"你能用多宽"，
#: 扣多少由行自己定 —— 以前页面统一扣一个常量，按钮多的那类行必然超出、
#: 最右边的按钮被切掉（2026-09-26 用户截图：删除显示不全）。
ROW_CHROME = (ROW_PADDING * 2 + ROW_LEFT_WIDTH + ROW_BUTTON_WIDTH * 3
              + ROW_SPACING * 4)

#: 「配置类型」的取值 —— 界面上的字面量，别散落到各处。
#: ⚠ 这几个已经搬到 :mod:`src.gui.config_names`（配置页 / 任务编排 / 任务列表都要用），
#:   这里**原样转出去**，免得老 import 全断。
#: 它们同时是**下拉框里显示的字**和**比较用的键**（``chosen_type()`` 取 `currentText()`），
#: 改字面量不会动到已存的数据 —— 两类配置分别存在 ``loadouts.json`` / ``echo_profiles.json``，
#: 里面**没有** type 字段，类型只是界面上的选择。
from .config_names import (  # noqa: E402 - 见上方说明
    CONFIG_TYPES,
    TYPE_BATTLE_PROFILE,
    TYPE_ECHO_PROFILE,
    TYPE_LOADOUT,
    config_display_name,
    type_suffix,
)

__all__ = [
    "CONFIG_TYPES",
    "TYPE_BATTLE_PROFILE",
    "TYPE_ECHO_PROFILE",
    "TYPE_LOADOUT",
    "ConfigTypeDialog",
    "EchoProfileDialog",
    "EchoProfileRow",
    "config_display_name",
    "type_suffix",
]


class ConfigTypeDialog(MessageBoxBase):
    """点「新增」时的第一步：要建哪一类配置。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.widget.setFixedWidth(460)
        self.titleLabel = SubtitleLabel("新增配置", self)
        self.viewLayout.addWidget(self.titleLabel)

        hint = CaptionLabel(
            f"「{TYPE_LOADOUT}」= 角色 + 声骸套装 + 各档声骸；\n"
            f"「{TYPE_ECHO_PROFILE}」= 一套强化判定条件（核心属性 / 双爆下限 / 有效词条数…）；\n"
            f"「{TYPE_BATTLE_PROFILE}」= 一个角色的技能快捷键 / 链路 / 战斗脚本。\n"
            "三者互不影响：后两类只是存着，不改变各自工具自己的设置。",
            self,
        )
        hint.setTextColor("#8A8F98", "#7C7C7C")
        hint.setWordWrap(True)
        self.viewLayout.addWidget(hint)

        self.typeBox = ComboBox(self)
        self.typeBox.addItems(list(CONFIG_TYPES))
        self.viewLayout.addWidget(self.typeBox)

        self.yesButton.setText("下一步")
        self.cancelButton.setText("取消")

    def chosen_type(self) -> str:
        return self.typeBox.currentText()


class EchoProfileDialog(MessageBoxBase):
    """新建 / 编辑 / 查看一条「角色声骸强化」配置。

    ★ 设置区就是**强化工具页那份**（``EchoSettingsEditor``）——
    用户要求："新增声骸强化配置跟声骸自动强化的配置界面是一样的"。
    两边的卡片、联动规则、文案永远一致，改一处两边都变。

    ⚠ **不含「结果报告」卡**（用户明确不要）—— 那是工具页跑任务才有的东西，
    配置本身没有"本次运行"可言。

    ## 名字就是**角色名**（2026-09-26 晚按要求改）

    名字不再是自由输入框，而是**角色下拉**（``FilterComboBox``，可打拼音筛）。
    原因：行上的头像是拿名字去 ``game_data.find_character()`` 查的，
    自由输入一旦不是角色名（用户实测把名字改成"绯雪声骸强化配置"）→ **头像直接消失**。

    配套两条规则，都在 :meth:`validate` 里把关（下拉里剔只是第一道）：

    * 名字**必须**精确命中数据集里的一个角色；
    * **一个角色只能有一条**配置 —— 已占用的角色从候选里剔掉，保存时再校一次
      （``FilterComboBox`` 是可输入的，光靠"候选里没有"拦不住手打的字）。

    * ``profile=None`` → 新建：规则起点是**出厂默认** —— 也就是打开
      「声骸自动强化」页**每次看到的那套**（那个页每次进入都显示出厂默认，
      **不显示** ``tool_settings`` 里存的旧值，所以"跟工具页一样"＝出厂默认）。
      传 ``initial_settings`` 可覆盖（测试用）；
    * ``profile=<某条>`` → 编辑：带上那条自己的规则；
    * ``read_only=True`` → 查看：整块只读，主按钮变「关闭」。

    ⚠ 组件是**懒导入**的：``src/gui`` 不该在启动时就把 ``src/tools`` 拉进来
    （那会拖慢启动）。这个弹框只在用户点时构造，属于按需。
    """

    #: 编辑区高度（5 张卡比较高，套滚动区）
    EDITOR_HEIGHT = 430

    def __init__(self, parent=None, *, profile=None, taken_chars=(),
                 initial_settings=None, read_only=False):
        super().__init__(parent)
        self.widget.setFixedWidth(760)
        self.read_only = bool(read_only)
        self._original = profile.name if profile is not None else ""
        #: 已被**别的**配置占用的角色（编辑时不含自己）——候选里剔掉 + 保存时再校
        self._taken = {str(n) for n in taken_chars if str(n) != self._original}

        from ..core import game_data  # noqa: PLC0415 - 见类文档（懒导入）
        from .pickers import FilterComboBox, load_icon  # noqa: PLC0415

        from ..tools.game.echo_enhance.settings import (
            EchoSettings,  # noqa: PLC0415 - 见类文档
        )
        from ..tools.game.echo_enhance.settings_editor import (
            EchoSettingsEditor,  # noqa: PLC0415 - 见类文档
        )

        game_data.ensure_loaded()          # 保证 CHARACTERS 有内容
        self._characters = list(game_data.CHARACTERS)

        creating = profile is None
        if self.read_only:
            title = f"查看「{config_display_name(TYPE_ECHO_PROFILE, profile.name)}」"
        elif creating:
            title = "新建角色声骸强化配置"
        else:
            title = f"编辑「{config_display_name(TYPE_ECHO_PROFILE, profile.name)}」"
        self.viewLayout.addWidget(SubtitleLabel(title, self))

        hint = CaptionLabel(
            "设置区 = **「声骸自动强化」工具页那一份**；"
            "**新增时的默认 = 它每次打开显示的那套（出厂默认）**。\n"
            "改这里**不会**动到工具页，反之亦然（两者互不影响）。",
            self,
        )
        hint.setTextColor("#8A8F98", "#7C7C7C")
        hint.setWordWrap(True)
        self.viewLayout.addWidget(hint)

        # ---- 角色（＝配置名）----
        name_row = QHBoxLayout()
        name_row.setSpacing(8)
        name_label = CaptionLabel("角色", self)
        name_label.setTextColor("#8A8F98", "#7C7C7C")
        name_label.setFixedWidth(52)
        name_row.addWidget(name_label)

        self.characterBox = FilterComboBox(self)
        # ⚠ 宽度钉死、**别用 stretch** —— 以前它填满整行（650px），
        #   用户 2026-09-26："太长了，缩短"。现在和「角色声骸筛选」那个弹框同宽。
        self.characterBox.setFixedWidth(CHARACTER_BOX_WIDTH)
        self.characterBox.setPlaceholderText(CHARACTER_BOX_HINT)
        # 已被占用的角色不放进来 —— "一个角色只能有一条"的第一道（第二道在 validate）
        self.characterBox.set_choices([
            (c.name, avatar_icon(c.avatar, c.name))
            for c in self._characters if c.name not in self._taken
        ])
        if self._original:
            self.characterBox.setText(self._original)
        self.characterBox.setEnabled(not self.read_only)     # 查看模式只读
        name_row.addWidget(self.characterBox)
        name_row.addStretch(1)                               # 留白在右边，不撑控件
        self.viewLayout.addLayout(name_row)

        if self._taken and not self.read_only:
            note = CaptionLabel(
                f"（{len(self._taken)} 个角色已经有配置了，不在候选里 —— "
                "一个角色只能有一条）", self)
            note.setTextColor("#8A8F98", "#7C7C7C")
            note.setWordWrap(True)
            self.viewLayout.addWidget(note)

        # 老数据里可能存着"不是角色"的名字（改名前自由输入留下的）。
        # 打开编辑时那个值会被回填进下拉，但保存会被拦 —— 先说清楚要重新选。
        if self._original and not read_only \
                and game_data.find_character(self._original) is None:
            stale = CaptionLabel(
                f"⚠ 原来叫「{self._original}」，它不是一个角色（旧版可以自由起名）。"
                "请在下拉里重新选一个角色 —— 名字就是角色名。", self)
            stale.setTextColor("#C9514C", "#E6B4AC")
            stale.setWordWrap(True)
            self.viewLayout.addWidget(stale)

        # ---- 设置区（和工具页同一份）----
        area = ScrollArea(self)
        area.setWidgetResizable(True)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        area.setFixedHeight(self.EDITOR_HEIGHT)
        self.editor = EchoSettingsEditor(area)
        area.setWidget(self.editor)
        area.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollArea > QWidget > QWidget { background: transparent; }")
        self.viewLayout.addWidget(area)

        # 新建 → **出厂默认**起手（＝工具页每次打开显示的那套）；
        # 编辑/查看 → 带上那条自己的。⚠ 别改成"读 tool_settings 里存的" ——
        # 工具页每次进入都显示出厂默认、不显示存盘值，读存盘就两边对不上了
        # （用户 2026-09-26 就是为此连问三句「为什么默认……」，见 :meth:`validate` 上方）。
        if profile is not None:
            initial = dict(profile.settings)
        else:
            initial = dict(initial_settings or {})
        self.editor.set_settings(EchoSettings.from_dict(initial))
        if self.read_only:
            self.editor.setEnabled(False)                # 查看模式不给改

        #: 校验不过时的提示（不关窗）
        self.errorLabel = CaptionLabel("", self)
        self.errorLabel.setTextColor("#C9514C", "#E6B4AC")
        self.errorLabel.setWordWrap(True)
        self.errorLabel.setVisible(False)
        self.viewLayout.addWidget(self.errorLabel)

        # ⚠ 这里**不能**再往下加提示行了：弹框内容本来就比卡片高
        #   （viewLayout 要 786px，卡片只有 682px），多一个可见控件就会
        #   竖直**重叠** —— 实测加一行"默认配置与工具页一样"的说明时，
        #   它直接叠在「可选属性」卡片上。
        #   所以"默认配置与工具页一样"这条并进了顶部那句提示（打开就能看到，
        #   还不额外占高度）。见 check_echo_page_gui 里的"不重叠"护栏。

        if self.read_only:
            self.yesButton.setText("关闭")
            self.cancelButton.hide()                     # 查看模式只要一个出口
        else:
            self.yesButton.setText("创建" if creating else "保存")
            self.cancelButton.setText("取消")

    # ``MessageBoxBase`` 的钩子：返回 False 就不关窗
    def validate(self) -> bool:
        """角色必须**是**一个角色、而且**没被别的配置占用**。

        两条都不能只靠"候选里没有"来拦 —— ``FilterComboBox`` 是可输入的，
        用户完全可以把候选筛空、直接敲一个词就点确定。

        真正的规则在 :func:`~src.core.game_data.character_choice_error`
        （和「角色声骸筛选」那边共用一份，改一处两边都变）。
        """
        from ..core.game_data import character_choice_error  # noqa: PLC0415 - 懒导入

        error = character_choice_error(
            self.profile_name(), self._taken, MAX_NAME_LENGTH)
        return self._reject(error) if error else True

    def _reject(self, message: str) -> bool:
        self.errorLabel.setText(message)
        self.errorLabel.setVisible(True)
        return False

    def profile_name(self) -> str:
        """配置名（＝角色名）。"""
        return self.characterBox.text().strip()

    def result_settings(self) -> dict:
        """界面上那一套（写回配置用）。"""
        return self.editor.settings().to_dict()


class EchoProfileRow(SimpleCardWidget):
    """列表里的一条「角色声骸强化」配置。

    左边「**头像 + 角色名**（名字在头像下面）」—— 和 ``LoadoutRow`` 一个样子：
    认出是谁的头像比读一行字快（用户 2026-09-26 要求）。

    * 头像由名字去 ``game_data.find_character()`` 查。名字现在**只能是角色名**
      （弹框里是下拉选的），所以正常情况下一定查得到；查不到时留空、不画占位图
      （老数据 / 手改过 JSON 时会出现）。
    * 名字用 :class:`~src.gui.compat.ElidedLabel`：**单行 + 超宽省略号**。
      以前是 ``setWordWrap(True)`` + 固定宽，名字一长就换 3 行、把行撑高、
      把头像是挤没 —— 2026-09-26 用户截图就是这个。

    右边三个操作：**编辑 / 查看 / 删除**（用户要求去掉「复制」「重命名」——
    换角色在「编辑」弹框的角色下拉里选）。
    删到一条不剩也可以。

    摘要**居中换行**，行高跟着摘要行数走 —— 和 ``LoadoutRow`` 同一套做法，
    所以宽度要由页面统一喂进来（见 :meth:`set_summary_width`）。
    """

    editRequested = Signal(str)
    viewRequested = Signal(str)
    deleteRequested = Signal(str)

    def __init__(self, profile: EchoProfile, parent: QWidget | None = None):
        super().__init__(parent)
        self.profile = profile
        self.setMinimumHeight(ROW_MIN_HEIGHT)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(ROW_PADDING, 12, ROW_PADDING, 12)
        layout.setSpacing(ROW_SPACING)

        layout.addWidget(self._build_identity(), 0)

        self.summary = CaptionLabel(profile.describe(), self)
        self.summary.setWordWrap(True)
        self.summary.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.summary.setTextColor("#8A8F98", "#7C7C7C")
        layout.addWidget(self.summary, 1)

        for text, signal, tip in (
            ("编辑", self.editRequested, "编这套判定条件（界面和强化工具页一样）"),
            ("查看", self.viewRequested, "只读地看一眼这套规则"),
            ("删除", self.deleteRequested, ""),
        ):
            button = PushButton(text, self)
            button.setFixedWidth(ROW_BUTTON_WIDTH)
            if tip:
                button.setToolTip(tip)
            button.clicked.connect(
                lambda _checked=False, sig=signal: sig.emit(self.profile.name))
            layout.addWidget(button, 0)

    def _build_identity(self) -> QWidget:
        """左列：头像在上，名字在**下面**（和 ``LoadoutRow`` 一致）。"""
        from ..core import game_data  # noqa: PLC0415 - 只在建行时用
        from .pickers import load_icon  # noqa: PLC0415

        box = QWidget(self)
        box.setFixedWidth(ROW_LEFT_WIDTH)
        column = QVBoxLayout(box)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(4)

        # 名字就是角色名 → 用那个角色的头像；**图没拿到就用首字现画一个**
        # （用户 2026-09-28："如果角色头像没拿到，先用第一个字填充"）——
        # 新角色是刚被资源库更新拉进来的，那一刻本地必然没有头像图。
        avatar = None
        try:
            info = game_data.find_character(self.profile.name)
            path = info.avatar if info is not None else ""
            avatar = avatar_icon(path or "", self.profile.name)
        except Exception:  # noqa: BLE001 - 资料没加载好也不该让行建不出来
            avatar = None

        holder: QWidget
        if avatar is not None and not avatar.isNull():
            view = IconWidget(avatar, box)
            view.setFixedSize(QSize(ROW_AVATAR_SIZE, ROW_AVATAR_SIZE))
            holder = view
        else:
            blank = QLabel(box)
            blank.setFixedSize(QSize(ROW_AVATAR_SIZE, ROW_AVATAR_SIZE))
            holder = blank
        column.addWidget(holder, 0, Qt.AlignmentFlag.AlignHCenter)

        name = ElidedLabel(config_display_name(TYPE_ECHO_PROFILE, self.profile.name),
                           box, width=ROW_LEFT_WIDTH,
                           align=Qt.AlignmentFlag.AlignHCenter)
        self.nameLabel = name
        column.addWidget(name, 0, Qt.AlignmentFlag.AlignHCenter)
        column.addStretch(1)
        return box

    def set_summary_width(self, avail: int) -> None:
        """``avail`` = 这一行**能用的总宽**（页面已扣掉页边距和滚动条）。

        扣掉**本行自己的** :data:`ROW_CHROME` 才是摘要宽度 ——
        和 ``LoadoutRow`` 的做法一致，两行的常量刚好一样（都是 3 个按钮）。

        （QLabel 自动换行的高度在嵌套布局里算不准，必须先把宽度钉死再量高度。）
        """
        self.summary.setFixedWidth(max(160, int(avail) - ROW_CHROME))
        self.setFixedHeight(
            max(ROW_MIN_HEIGHT, self.layout().totalSizeHint().height()))
