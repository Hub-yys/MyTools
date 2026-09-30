"""「角色战斗」配置的界面：编辑弹框 + 列表行。

用户 2026-09-30 要求：

    角色（下拉列表选择）；角色头像（与角色联动）；
    有角色技能快捷键，技能快捷键分为声骸技能（默认 Q）、共鸣技能（默认 E）、
    共鸣解放（默认 R）；角色链路 +− 按钮 加 1 减 1，最大为 6 最小为 0；
    角色战斗脚本

## 和另外两类配置的界面保持一致

角色下拉、头像、"一个角色只能有一条"、校验规则都复用现成的那套
（``pickers.FilterComboBox`` / ``game_data.character_choice_error``），
不另写一份 —— 否则"角色只能从下拉选"这类规则会在两处慢慢分叉。

## ★ 现在**只存不跑**

快捷键和战斗脚本都只是存下来（用户明确："先只存不跑"）。
**别在这里接按键执行** —— 那是以后的事，要显式从配置读、注入任务。
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    CaptionLabel,
    IconWidget,
    LineEdit,
    MessageBoxBase,
    PushButton,
    SimpleCardWidget,
    StrongBodyLabel,
    SubtitleLabel,
    ToolButton,
)

from ..core.battle_profile import (
    DEFAULT_SKILL_KEYS,
    MAX_CHAIN,
    MAX_SCRIPT_LENGTH,
    MIN_CHAIN,
    SKILL_KEY_LABELS,
    BattleProfile,
    clamp_chain,
)
from ..core.battle_profile import MAX_NAME_LENGTH as MAX_NAME_LENGTH  # noqa: PLC0415
from .compat import ElidedLabel
from .config_names import TYPE_BATTLE_PROFILE, config_display_name
from .pickers import (
    CHARACTER_BOX_HINT,
    CHARACTER_BOX_WIDTH,
    avatar_icon,
)

MUTED = ("#8A8F98", "#7C7C7C")

#: 列表行的尺寸 —— 和另两类**用同一套值**，三行看起来才齐
ROW_MIN_HEIGHT = 96
ROW_PADDING = 16
ROW_SPACING = 18
ROW_BUTTON_WIDTH = 76
ROW_AVATAR_SIZE = 48
ROW_LEFT_WIDTH = 110
#: 行自己的固定占用（头像列 + 3 个按钮 + 间距）—— 摘要宽度 = 可用宽 - 它
ROW_CHROME = 430

#: 头像预览的边长（弹框里那一个）
PREVIEW_SIZE = 64

#: 快捷键输入框的宽度
KEY_BOX_WIDTH = 64

#: 战斗脚本输入框的高度
SCRIPT_HEIGHT = 150


class BattleProfileDialog(MessageBoxBase):
    """新建 / 编辑 / 查看一条「角色战斗」配置。"""

    def __init__(self, parent=None, *, profile=None, taken_chars=(),
                 read_only=False):
        super().__init__(parent)
        self.widget.setFixedWidth(720)
        self.read_only = bool(read_only)
        self._original = profile.name if profile is not None else ""
        #: 已被**别的**配置占用的角色（编辑时不含自己）
        self._taken = {str(n) for n in taken_chars if str(n) != self._original}

        from ..core import game_data  # noqa: PLC0415 - 懒导入，见另两类的说明
        from .pickers import FilterComboBox, load_icon  # noqa: PLC0415

        game_data.ensure_loaded()
        self._characters = list(game_data.CHARACTERS)
        self._game_data = game_data
        self._load_icon = load_icon

        creating = profile is None
        if self.read_only:
            title = f"查看「{config_display_name(TYPE_BATTLE_PROFILE, profile.name)}」"
        elif creating:
            title = "新建角色战斗配置"
        else:
            title = f"编辑「{config_display_name(TYPE_BATTLE_PROFILE, profile.name)}」"
        self.viewLayout.addWidget(SubtitleLabel(title, self))

        hint = CaptionLabel(
            "一个角色一条配置。" + ("（查看模式：只能看，不能改）"
                                if self.read_only else ""), self)
        hint.setTextColor(*MUTED)
        hint.setWordWrap(True)
        self.viewLayout.addWidget(hint)

        # ---- 角色（＝配置名）+ 头像（**与角色联动**）----
        self.viewLayout.addLayout(self._build_identity(FilterComboBox))

        # ---- 技能快捷键 ----
        self.viewLayout.addWidget(self._section_label("技能快捷键"))
        self.key_edits: dict[str, LineEdit] = {}
        keys_row = QHBoxLayout()
        keys_row.setSpacing(18)
        for skill, label in SKILL_KEY_LABELS:
            cell = QVBoxLayout()
            cell.setSpacing(3)
            caption = CaptionLabel(label, self)
            caption.setTextColor(*MUTED)
            cell.addWidget(caption)

            edit = LineEdit(self)
            edit.setFixedWidth(KEY_BOX_WIDTH)
            edit.setMaxLength(2)          # 只支持单键
            edit.setText(self._initial_key(profile, skill))
            edit.setPlaceholderText(DEFAULT_SKILL_KEYS[skill])
            edit.setEnabled(not self.read_only)
            self.key_edits[skill] = edit
            cell.addWidget(edit)
            keys_row.addLayout(cell)
        keys_row.addStretch(1)
        self.viewLayout.addLayout(keys_row)

        # ---- 角色链路（+/− 按钮，范围 0~6）----
        self.viewLayout.addWidget(self._section_label("角色链路"))
        self.viewLayout.addLayout(self._build_chain_row(profile))

        # ---- 战斗脚本 ----
        self.viewLayout.addWidget(self._section_label("角色战斗脚本"))
        self.script_edit = QPlainTextEdit(self)
        self.script_edit.setFixedHeight(SCRIPT_HEIGHT)
        self.script_edit.setPlaceholderText(
            "每个角色自己的战斗脚本（现在只是存着，还没接执行）")
        if profile is not None:
            self.script_edit.setPlainText(profile.script)
        self.script_edit.setEnabled(not self.read_only)
        self.viewLayout.addWidget(self.script_edit)

        self.errorLabel = CaptionLabel("", self)
        self.errorLabel.setTextColor("#C9514C", "#E6B4AC")
        self.errorLabel.setWordWrap(True)
        self.errorLabel.setVisible(False)
        self.viewLayout.addWidget(self.errorLabel)

        if self.read_only:
            self.yesButton.setText("关闭")
            self.cancelButton.hide()
        else:
            self.yesButton.setText("创建" if creating else "保存")
            self.cancelButton.setText("取消")

        self._sync_avatar()

    # ---------------------------------------------------------------- 构建
    def _section_label(self, text: str) -> QWidget:
        holder = QWidget(self)
        box = QVBoxLayout(holder)
        box.setContentsMargins(0, 6, 0, 0)
        box.addWidget(StrongBodyLabel(text, holder))
        return holder

    def _initial_key(self, profile, skill: str) -> str:
        if profile is None:
            return DEFAULT_SKILL_KEYS[skill]
        return profile.key_of(skill)

    def _build_identity(self, combo_cls) -> QHBoxLayout:
        """角色下拉 + 头像预览，并让**头像跟着下拉走**。"""
        row = QHBoxLayout()
        row.setSpacing(14)

        # 左：头像预览
        self.avatar_holder = QWidget(self)
        self.avatar_holder.setFixedSize(QSize(PREVIEW_SIZE, PREVIEW_SIZE))
        avatar_box = QVBoxLayout(self.avatar_holder)
        avatar_box.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.avatar_holder, 0)

        # 右：角色下拉
        right = QVBoxLayout()
        right.setSpacing(4)
        label = CaptionLabel("角色", self)
        label.setTextColor(*MUTED)
        right.addWidget(label)

        self.characterBox = combo_cls(self)
        self.characterBox.setFixedWidth(CHARACTER_BOX_WIDTH)
        self.characterBox.setPlaceholderText(CHARACTER_BOX_HINT)
        self.characterBox.set_choices([
            (c.name, avatar_icon(c.avatar, c.name))
            for c in self._characters if c.name not in self._taken
        ])
        if self._original:
            self.characterBox.setText(self._original)
        self.characterBox.setEnabled(not self.read_only)
        # ★ 与角色联动：文字一变就刷新头像
        self.characterBox.textChanged.connect(self._sync_avatar)
        right.addWidget(self.characterBox)
        right.addStretch(1)
        row.addLayout(right, 1)
        return row

    def _build_chain_row(self, profile) -> QHBoxLayout:
        """角色链路：``[−] 3 [+]``，范围 0~6。"""
        row = QHBoxLayout()
        row.setSpacing(8)

        self.chain_value = 0 if profile is None else profile.chain
        self.chain_minus = ToolButton(self)
        self.chain_minus.setText("−")
        self.chain_minus.setFixedSize(QSize(32, 32))
        self.chain_minus.clicked.connect(lambda: self._step_chain(-1))
        row.addWidget(self.chain_minus)

        self.chain_label = StrongBodyLabel(str(self.chain_value), self)
        self.chain_label.setFixedWidth(42)
        self.chain_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(self.chain_label)

        self.chain_plus = ToolButton(self)
        self.chain_plus.setText("+")
        self.chain_plus.setFixedSize(QSize(32, 32))
        self.chain_plus.clicked.connect(lambda: self._step_chain(1))
        row.addWidget(self.chain_plus)

        range_hint = CaptionLabel(f"（{MIN_CHAIN}~{MAX_CHAIN}）", self)
        range_hint.setTextColor(*MUTED)
        row.addWidget(range_hint)
        row.addStretch(1)

        if self.read_only:
            for button in (self.chain_minus, self.chain_plus):
                button.setEnabled(False)
        self._sync_chain_buttons()
        return row

    # ---------------------------------------------------------------- 交互
    def _step_chain(self, delta: int) -> None:
        """点 +/− —— **夹边界**用 core 的 :func:`clamp_chain`（只此一份）。"""
        self.chain_value = clamp_chain(self.chain_value + delta)
        self.chain_label.setText(str(self.chain_value))
        self._sync_chain_buttons()

    def _sync_chain_buttons(self) -> None:
        """到边界就把对应按钮**灰掉** —— 点了没反应会让人以为坏了。"""
        if self.read_only:
            return
        self.chain_minus.setEnabled(self.chain_value > MIN_CHAIN)
        self.chain_plus.setEnabled(self.chain_value < MAX_CHAIN)

    def _sync_avatar(self, *_args) -> None:
        """头像与角色联动 —— 下拉里选谁就显示谁的头像。

        拿不到图就用**首字圆图**兜底（和列表行同一套 ``avatar_icon``），
        不留空洞：新角色刚被资源库拉进来时本地还没有头像图。
        """
        name = self.characterBox.text().strip()
        box = self.avatar_holder.layout()
        while box.count():
            item = box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

        icon = QIcon()
        try:
            info = self._game_data.find_character(name) if name else None
            icon = avatar_icon(info.avatar if info is not None else "", name)
        except Exception:  # noqa: BLE001 - 资料没加载好也不该让弹框打不开
            icon = avatar_icon("", name)

        if icon.isNull():
            placeholder = QLabel("？", self.avatar_holder)
            placeholder.setFixedSize(QSize(PREVIEW_SIZE, PREVIEW_SIZE))
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            placeholder.setStyleSheet(
                "color: #8A8F98; background: rgba(128,128,128,0.16);"
                f" border-radius: {PREVIEW_SIZE // 2}px;")
            box.addWidget(placeholder)
        else:
            view = IconWidget(icon, self.avatar_holder)
            view.setFixedSize(QSize(PREVIEW_SIZE, PREVIEW_SIZE))
            box.addWidget(view)

    # ---------------------------------------------------------------- 结果
    def validate(self) -> bool:
        """角色必须是角色、且没被别的配置占用（和另两类**共用一份规则**）。"""
        from ..core.game_data import character_choice_error  # noqa: PLC0415

        error = character_choice_error(
            self.profile_name(), self._taken, MAX_NAME_LENGTH)
        return self._reject(error) if error else True

    def _reject(self, message: str) -> bool:
        self.errorLabel.setText(message)
        self.errorLabel.setVisible(True)
        return False

    def profile_name(self) -> str:
        return self.characterBox.text().strip()

    def result_profile(self) -> BattleProfile:
        """界面上那一套（写回配置用）。"""
        return BattleProfile(
            name=self.profile_name(),
            skill_keys={
                skill: edit.text().strip() or DEFAULT_SKILL_KEYS[skill]
                for skill, edit in self.key_edits.items()
            },
            chain=self.chain_value,
            script=self.script_edit.toPlainText()[:MAX_SCRIPT_LENGTH],
        )


class BattleProfileRow(SimpleCardWidget):
    """列表里的一条「角色战斗」配置。

    排版和 ``EchoProfileRow`` / ``LoadoutRow`` **完全一致**（头像+名字在左、
    摘要居中、右侧三个按钮），三行摆在一起才齐。
    """

    editRequested = Signal(str)
    viewRequested = Signal(str)
    deleteRequested = Signal(str)

    def __init__(self, profile: BattleProfile, parent: QWidget | None = None):
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
        self.summary.setTextColor(*MUTED)
        layout.addWidget(self.summary, 1)

        for text, signal, tip in (
            ("编辑", self.editRequested, "改快捷键 / 链路 / 战斗脚本"),
            ("查看", self.viewRequested, "只读地看一眼这套配置"),
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
        """左列：头像在上、名字在下面（和其它两类一致）。"""
        from ..core import game_data  # noqa: PLC0415

        box = QWidget(self)
        box.setFixedWidth(ROW_LEFT_WIDTH)
        column = QVBoxLayout(box)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(4)

        avatar = None
        try:
            info = game_data.find_character(self.profile.name)
            avatar = avatar_icon(info.avatar if info is not None else "",
                                 self.profile.name)
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

        name = ElidedLabel(config_display_name(TYPE_BATTLE_PROFILE,
                                               self.profile.name),
                           box, width=ROW_LEFT_WIDTH,
                           align=Qt.AlignmentFlag.AlignHCenter)
        self.nameLabel = name
        column.addWidget(name, 0, Qt.AlignmentFlag.AlignHCenter)
        column.addStretch(1)
        return box

    def set_summary_width(self, avail: int) -> None:
        """``avail`` = 这一行能用的总宽（页面已扣掉页边距和滚动条）。"""
        self.summary.setFixedWidth(max(160, int(avail) - ROW_CHROME))
        self.setFixedHeight(
            max(ROW_MIN_HEIGHT, self.layout().totalSizeHint().height()))
