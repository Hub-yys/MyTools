"""新增 / 修改角色配置的弹框。

界面自上而下：

    角色 *   [可输入、按内容过滤的下拉]  [头像]      头像跟着角色联动
    声骸套装 * [带图标的下拉]
    4C *     ┌ [图] 名称   ☐暴击 ☐暴伤…（属性可多选）   ☑ ┐   ← 中列多选、右列勾选声骸
    3C *     │  ...                                            │
    1C *     └  ...                                            ┘
                                        [保存] [取消]

``validate()`` 是 ``MessageBoxBase`` 的钩子：返回 False 就不关窗，正好用来做必填校验。
"""

from __future__ import annotations

import copy
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    IconWidget,
    InfoBar,
    InfoBarPosition,
    MessageBoxBase,
    PushButton,
    ScrollArea,
    StrongBodyLabel,
)

from ..core.game_data import (
    CHARACTERS,
    COST_SECTIONS,
    ECHO_SETS,
    EchoInfo,
    find_character,
    find_echo_set,
)
from ..core.loadout import EchoPick, Loadout
from .compat import TitleLabel
from .pickers import EchoPickRow, FilterComboBox, IconComboBox, load_icon

#: 套装下拉里那一项占位（选中它 = 还没选套装）
SET_PLACEHOLDER = "请选择"

DIALOG_WIDTH = 880
ECHO_AREA_HEIGHT = 380


class CostSection(QWidget):
    """一个费用档位（4C / 3C / 1C）下的一组声骸，**可以多选**。

    每行的属性也是多选 —— 一条声骸可以同时要「暴击 + 暴击伤害」等多条主词条
    （2026-09-22 起，属性框不再是单选）。
    """

    def __init__(self, cost: int, label: str, echoes, parent: QWidget | None = None):
        super().__init__(parent)
        self.cost = cost
        self.rows: list[EchoPickRow] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(StrongBodyLabel(f"{label}（可多选）", self))

        if not echoes:
            # 多数新版套装只收录了声骸明细的一部分；选到这种套装时把话说明白，
            # 免得用户以为界面坏了。
            empty = CaptionLabel(
                f"这套的 {label} 声骸明细还没收录，这一档暂时选不了 —— "
                f"换一套，或跑 tools/refresh_wuwa_data.py --echoes 刷一下",
                self,
            )
            empty.setTextColor("#8A8F98", "#7C7C7C")
            empty.setWordWrap(True)
            layout.addWidget(empty)
            return

        for echo in echoes:
            row = EchoPickRow(echo, self)
            layout.addWidget(row)
            self.rows.append(row)

    def selected_rows(self) -> list[EchoPickRow]:
        return [row for row in self.rows if row.is_selected()]

    def select_many(self, picks) -> None:
        """回填：按名字勾上对应行，并把属性也设回去。"""
        by_name = {p.echo: p for p in picks}
        for row in self.rows:
            hit = row.echo.name in by_name
            row.set_selected(hit, silent=True)
            if hit:
                row.set_stats(by_name[row.echo.name].stats)

    def clear(self) -> None:
        for row in self.rows:
            row.set_selected(False, silent=True)


class LoadoutDialog(MessageBoxBase):
    """新增 / 修改一条配置。传 ``loadout`` 就是修改模式（会回填）。"""

    def __init__(self, parent: QWidget | None = None, loadout: Loadout | None = None):
        super().__init__(parent)
        self.editing = loadout is not None
        self.loadout: Loadout = copy.deepcopy(loadout) if loadout is not None else Loadout()
        self._sections: dict[int, CostSection] = {}
        #: 用户自选的头像（点"更换"才有），优先于角色联动的头像
        self.custom_avatar: str = ""

        self.widget.setFixedWidth(DIALOG_WIDTH)
        self.yesButton.setText("保存")
        self.cancelButton.setText("取消")

        self.viewLayout.addWidget(
            TitleLabel("修改配置" if self.editing else "新增配置", self)
        )
        self.viewLayout.addWidget(self._build_character_row())
        self.viewLayout.addWidget(self._build_echo_set_row())
        self.viewLayout.addWidget(self._build_echo_area())

        self._restore()

    # ---------------------------------------------------------------- 上半部分
    def _required_label(self, text: str, parent: QWidget | None = None) -> QWidget:
        """必填项标签：文字后面跟一个红色星号。"""
        holder = QWidget(parent or self)
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(2)

        label = BodyLabel(text, holder)
        label.setFixedWidth(76)
        row.addWidget(label)

        star = BodyLabel("*", holder)
        star.setTextColor("#C42B1C", "#FF6B6B")
        row.addWidget(star)

        row.addStretch(1)
        return holder

    def _build_character_row(self) -> QWidget:
        """角色一行、头像独占下面一行（头像与"角色"标签左对齐）。"""
        holder = QWidget(self)
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(8)

        top = QWidget(holder)
        row = QHBoxLayout(top)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        row.addWidget(self._required_label("角色", top))

        self.character_combo = FilterComboBox(top)
        self.character_combo.setFixedWidth(230)
        self.character_combo.setPlaceholderText("可直接输入，按内容匹配")
        self.character_combo.set_choices(
            [(c.name, load_icon(c.avatar)) for c in CHARACTERS]
        )
        self.character_combo.textChanged.connect(self._on_character_changed)
        row.addWidget(self.character_combo)
        row.addStretch(1)
        column.addWidget(top)

        bottom = QWidget(holder)
        avatar_row = QHBoxLayout(bottom)
        avatar_row.setContentsMargins(0, 0, 0, 0)
        avatar_row.setSpacing(12)

        # 标签宽度和上面那个「角色」对齐（必填标签是 76 + 星号 ≈ 86）
        avatar_label = BodyLabel("角色头像", bottom)
        avatar_label.setFixedWidth(86)
        avatar_row.addWidget(avatar_label)

        self.avatar_view = IconWidget(QIcon(), bottom)
        self.avatar_view.setFixedSize(QSize(44, 44))
        avatar_row.addWidget(self.avatar_view)

        self.avatar_button = PushButton("更换", bottom)
        self.avatar_button.setFixedWidth(72)
        self.avatar_button.clicked.connect(self._on_change_avatar)
        avatar_row.addWidget(self.avatar_button)

        avatar_row.addStretch(1)
        column.addWidget(bottom)

        return holder


    def _build_echo_set_row(self) -> QWidget:
        holder = QWidget(self)
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)

        row.addWidget(self._required_label("声骸套装"))

        self.set_combo = IconComboBox(holder)
        self.set_combo.setFixedWidth(250)
        # 列**全部**套装（和资源库那份一致，按出场版本倒序，最新的在最前面）。
        # 明细还没收录的也能选，只是那一档会空着并提示 —— 见 CostSection。
        self.set_combo.set_items(
            [(SET_PLACEHOLDER, QIcon())]
            + [(item.name, load_icon(item.icon)) for item in ECHO_SETS]
        )
        self.set_combo.changed.connect(self._on_echo_set_changed)
        row.addWidget(self.set_combo)

        note = CaptionLabel(
            f"共 {len(ECHO_SETS)} 套 · 按出场版本排（最新的在最前面）", holder
        )
        note.setTextColor("#8A8F98", "#7C7C7C")
        row.addWidget(note)

        row.addStretch(1)
        return holder

    def _build_echo_area(self) -> QWidget:
        self.echo_scroll = ScrollArea(self)
        self.echo_scroll.setObjectName("echoPickArea")
        self.echo_scroll.setFixedHeight(ECHO_AREA_HEIGHT)
        self.echo_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.echo_scroll.setWidgetResizable(True)
        # ScrollArea 自己和 viewport 都会吃系统调色板底色（深色系统上就是一片黑）。
        # 光设 viewport 的样式不够，还得给 ScrollArea 打开 WA_StyledBackground，
        # 否则它照样按 palette 把 viewport 刷成深色。
        self.echo_scroll.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.echo_scroll.setStyleSheet(
            "#echoPickArea { background: transparent; border: none; }"
        )
        self.echo_scroll.viewport().setStyleSheet("background: transparent;")

        self.echo_host = QWidget(self.echo_scroll)
        self.echo_layout = QVBoxLayout(self.echo_host)
        self.echo_layout.setContentsMargins(0, 0, 8, 0)
        self.echo_layout.setSpacing(12)

        self.echo_scroll.setWidget(self.echo_host)
        self._rebuild_sections("")
        return self.echo_scroll

    # ---------------------------------------------------------------- 联动
    def _on_character_changed(self, _text: str) -> None:
        # 换了角色就回归联动的头像（之前自选的那张跟着作废）
        self.custom_avatar = ""
        self._refresh_avatar()

    def _refresh_avatar(self) -> None:
        """头像优先级：用户自选 > 角色联动 > 空。"""
        if self.custom_avatar:
            icon = load_icon(self.custom_avatar)
            if not icon.isNull():
                self.avatar_view.setIcon(icon)
                return

        info = find_character(self.character_combo.text())
        self.avatar_view.setIcon(load_icon(info.avatar) if info else QIcon())

    def _on_change_avatar(self) -> None:
        """手动挑一张头像图，之后就不再跟角色联动。"""
        path, _selected = QFileDialog.getOpenFileName(
            self,
            "选择头像图片",
            str(Path.home()),
            "图片 (*.png *.jpg *.jpeg *.webp *.bmp)",
        )
        if not path:
            return
        self.custom_avatar = path
        self._refresh_avatar()

    def _on_echo_set_changed(self, set_name: str) -> None:
        self._rebuild_sections(set_name)

    def _clear_echo_area(self) -> None:
        while self.echo_layout.count():
            item = self.echo_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._sections.clear()

    def _rebuild_sections(self, set_name: str) -> None:
        """套装变了两件事：换掉三档声骸的候选、清掉原来的选择。"""
        self._clear_echo_area()

        info = find_echo_set(set_name)
        if info is None:
            hint = CaptionLabel("请先在上方选择声骸套装", self.echo_host)
            hint.setTextColor("#C42B1C", "#FF6B6B")
            self.echo_layout.addWidget(hint)
            self.echo_layout.addStretch(1)
            return

        if info.is_single_piece:
            note = CaptionLabel(
                "这套是 1 件套 —— 装一个声骸就生效，所以只有 4C，不需要 3C/1C。",
                self.echo_host,
            )
            note.setTextColor("#8A8F98", "#7C7C7C")
            note.setWordWrap(True)
            self.echo_layout.addWidget(note)

        for cost, label in COST_SECTIONS:
            # 1 件套只有它那一档 —— 别的档位不是"缺数据"，是本来就不存在，别摆空框出来
            if cost not in info.required_costs:
                continue
            section = CostSection(cost, label, info.by_cost(cost), self.echo_host)
            self.echo_layout.addWidget(section)
            self._sections[cost] = section
        self.echo_layout.addStretch(1)

    # ---------------------------------------------------------------- 回填 / 收集
    def _restore(self) -> None:
        """把 loadout 里的选择填回界面。顺序要紧：套装先（会重建声骸区），声骸最后。"""
        item = self.loadout
        self.custom_avatar = item.custom_avatar

        if item.character:
            self.character_combo.setText(item.character)
            # setText 会触发 _on_character_changed 把自定义头像清掉，这里再放回去
            self.custom_avatar = item.custom_avatar
        self._refresh_avatar()

        if item.echo_set and find_echo_set(item.echo_set) is not None:
            self.set_combo.set_current(item.echo_set)
            self._rebuild_sections(item.echo_set)
            for cost, _label in COST_SECTIONS:
                section = self._sections.get(cost)
                if section is not None:
                    section.select_many(item.picks_of(cost))

    def _collect(self) -> None:
        """把界面上的选择收回 loadout 里。"""
        item = self.loadout
        item.character = self.character_combo.text().strip()
        item.custom_avatar = self.custom_avatar

        set_text = self.set_combo.current_text().strip()
        item.echo_set = "" if set_text == SET_PLACEHOLDER else set_text

        for cost, _label in COST_SECTIONS:
            section = self._sections.get(cost)
            rows = section.selected_rows() if section is not None else []
            item.set_picks(
                cost, [EchoPick(echo=r.echo.name, stats=r.stats()) for r in rows]
            )

    # ---------------------------------------------------------------- 校验
    def validate(self) -> bool:  # noqa: D102 - MessageBoxBase 钩子
        self._collect()
        errors = self.loadout.validate()
        if errors:
            InfoBar.error(
                "还有必填项没填",
                "；".join(errors),
                duration=5000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return False
        return True

    # ---------------------------------------------------------------- 给外部用
    def result_loadout(self) -> Loadout:
        """最终结果（保存后调用）。"""
        self._collect()
        return self.loadout


class LoadoutDetailDialog(MessageBoxBase):
    """只读的配置详情 —— 跟修改弹框长得像，但一个控件都点不动。"""

    def __init__(self, parent: QWidget | None = None, loadout: Loadout | None = None):
        super().__init__(parent)
        self.loadout = loadout or Loadout()

        self.widget.setFixedWidth(580)
        self.yesButton.setText("关闭")
        self.cancelButton.hide()

        self.viewLayout.addWidget(TitleLabel("配置详情", self))
        self.viewLayout.addWidget(self._character_block())

        info = find_echo_set(self.loadout.echo_set)
        self.viewLayout.addWidget(self._line("声骸套装", self.loadout.echo_set or "未选",
                                             load_icon(info.icon) if info else None))
        for cost, label in COST_SECTIONS:
            picks = self.loadout.picks_of(cost)
            if picks:
                text = "；".join(
                    f"{p.echo}　属性：{'、'.join(p.stats) if p.stats else '未选'}"
                    for p in picks
                )
                echo_info = self._find_echo(info, cost, picks[0].echo)
            else:
                text = "未选"
                echo_info = None
            self.viewLayout.addWidget(
                self._line(label, text, load_icon(echo_info.icon) if echo_info else None)
            )

    # ---------------------------------------------------------------- 小积木
    def _line(self, label: str, text: str, icon: QIcon | None = None) -> QWidget:
        holder = QWidget(self)
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)

        name = CaptionLabel(label, holder)
        name.setFixedWidth(64)
        name.setTextColor("#8A8F98", "#7C7C7C")
        row.addWidget(name)

        if icon is not None and not icon.isNull():
            widget = IconWidget(icon, holder)
            widget.setFixedSize(QSize(30, 30))
            row.addWidget(widget)

        row.addWidget(BodyLabel(text, holder))
        row.addStretch(1)
        return holder

    def _character_block(self) -> QWidget:
        holder = QWidget(self)
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)

        avatar = load_icon(self.loadout.display_avatar)
        view = IconWidget(avatar, holder) if not avatar.isNull() else QWidget(holder)
        view.setFixedSize(QSize(52, 52))
        row.addWidget(view)

        text_box = QWidget(holder)
        col = QVBoxLayout(text_box)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(2)
        col.addWidget(StrongBodyLabel(self.loadout.character or "（未填角色）", text_box))

        stamp = CaptionLabel(f"更新于 {self.loadout.updated_at or '—'}", text_box)
        stamp.setTextColor("#8A8F98", "#7C7C7C")
        col.addWidget(stamp)

        row.addWidget(text_box)
        row.addStretch(1)
        return holder

    @staticmethod
    def _find_echo(echo_set, cost: int, echo_name: str):
        """在套装里按名字找那个声骸，找得到就拿它的图标。"""
        if echo_set is None or not echo_name:
            return None
        for item in echo_set.by_cost(cost):
            if item.name == echo_name:
                return item
        return None
