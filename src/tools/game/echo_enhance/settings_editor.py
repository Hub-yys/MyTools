"""声骸强化的**设置区**（核心属性 / 双爆下限 / 满值保护 / 可选属性 / 有效词条数）。

抽出来是为了让**两处**用同一份 UI：

* ``tool.py`` 的声骸自动强化工具页
* 配置页里「角色声骸强化」配置的编辑弹框

⚠ 组件本身**不碰存盘**，也不知道 okww / 宿主的存在 —— 它只负责"把一套
:class:`EchoSettings` 显示出来、改完发个 ``changed`` 信号"。
存到哪（tool_settings 还是某条配置）由宿主决定。这样两边能用同一份界面而不耦合。

界面上的联动规则（核心 ↔ 可选互斥、有效词条数的合法范围、核心上限）全在这里，
**别在宿主机里再实现一遍** —— 那正是两边会走偏的地方。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    CheckBox,
    InfoBar,
    StrongBodyLabel,
    SwitchButton,
)

from ....core.registry import logger
from ....gui.widgets import CollapsibleCard, ConfigCard, NumberField, NumberStepper
from .settings import (
    DEFAULT_CORE,
    DEFAULT_CRIT_DMG_MIN,
    DEFAULT_CRIT_MIN,
    DEFAULT_VALID_COUNT,
    EchoSettings,
    valid_count_range,
)
from .stats import (
    ALL_STATS,
    CRIT,
    CRIT_DMG,
    MAX_CORE_STATS,
    MAX_CRIT,
    MAX_CRIT_DMG,
    MAX_VALID_COUNT,
    MIN_VALID_COUNT,
    OPTIONAL_CHOICES,
)


class EchoSettingsEditor(QWidget):
    """一套强化判定条件的编辑界面。

    用法::

        editor = EchoSettingsEditor()
        editor.set_settings(settings)      # 回填（不会触发 changed）
        editor.changed.connect(保存)
        settings = editor.settings()       # 取当前值
    """

    #: 任何一处被改动时发出（宿主接这个去存盘）
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._core_boxes: dict = {}
        self._optional_boxes: dict = {}
        #: 回填过程中不要发 changed（否则构造/回填会触发一串无意义的存盘）
        self._loading = True
        #: 正在同步「有效词条数」的范围（防 set_range → changed → 再绕回来）
        self._syncing_valid = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.addWidget(self._build_core_card(self))
        layout.addWidget(self._build_crit_card(self))
        layout.addWidget(self._build_maxroll_card(self))
        layout.addWidget(self._build_autostop_card(self))
        layout.addWidget(self._build_optional_card(self))
        layout.addWidget(self._build_valid_card(self))

        self._update_core_count()
        self._update_optional_count()
        self._sync_valid_count()
        self._loading = False

    # ------------------------------------------------------------------ 内部
    def _notify(self) -> None:
        """发 changed —— **回填期间不发**。

        ⚠ 这个判断必须在这里、而不是在调用处：set_settings 回填时会
        setChecked / set_value，那些控件**照样会发自己的信号** ——
        在调用处拦是拦不住的（第一版就是这么错的，构造页面时会触发一串存盘）。
        """
        if self._loading:
            return
        # ⚠ 收敛「有效词条数」的范围也必须在这儿 —— 原来这一步是宿主
        #   `_save_settings()` 干的（先收敛范围、再收集值）。搬到组件里之后
        #   只发信号不收敛的话，改「可选属性」就不会刷新「有效词条数」的范围
        #   （check_echo_page_gui 有三条断言当场就炸，原因就是它）。
        #   `_sync_valid_count` 内部用 emit=False，不会回调到这里，无递归风险。
        self._sync_valid_count()
        self.changed.emit()

    # ------------------------------------------------------------------ 对外
    def settings(self) -> EchoSettings:
        """当前界面上那一套。"""
        return self._collect_settings()

    def set_settings(self, settings: EchoSettings) -> None:
        """回填一套设置（期间不发 changed）。"""
        was = self._loading
        self._loading = True
        try:
            self._apply_settings(settings)
        finally:
            self._loading = was

    # ------------------------------------------------------------------ 兼容
    @property
    def core_boxes(self) -> dict:
        return self._core_boxes

    @property
    def optional_boxes(self) -> dict:
        return self._optional_boxes

    def checked_core(self) -> list:
        return self._checked_core()

    def checked_optional(self) -> list:
        return self._checked_optional()


    def _build_core_card(self, parent: QWidget) -> QWidget:
        # 默认收起：13 个复选框全摊开太占地方，摘要行照样能看到选了哪些
        card = CollapsibleCard(
            "核心属性",
            f"必须有，缺任意一条就弃置。{CRIT}、{CRIT_DMG}强制勾选且不可取消 —— "
            f"上限 {MAX_CORE_STATS} 条里它们已占 2 条，自选最多还能勾 "
            f"{MAX_CORE_STATS - 2} 条（勾满后其余自选框会置灰；已勾的随时可取消）。\n"
            "出厂默认只有暴击、暴击伤害两条；**每次进入本页都是这套默认值**，"
            "这里的勾选不会跨次保留（摘要若标「非默认」说明本次改过，点标题栏的"
            "「恢复默认」可立刻还原）。",
            parent=parent,
        )
        grid = QGridLayout()
        grid.setSpacing(6)
        columns = 4
        rows = (len(ALL_STATS) + columns - 1) // columns
        for index, stat in enumerate(ALL_STATS):
            box = CheckBox(stat, card)
            forced = stat in (CRIT, CRIT_DMG)
            if forced:
                box.setChecked(True)
                box.setEnabled(False)          # 不可取消
                box.setToolTip("必须保留，不可取消")
            else:
                box.stateChanged.connect(self._on_core_changed)
            # 竖排顺序按列填，读起来顺着走
            grid.addWidget(box, index % rows, index // rows)
            self._core_boxes[stat] = box

        holder = QWidget(card)
        holder.setLayout(grid)
        card.add(holder)

        self.core_count_label = card.summary_label
        self._update_core_count()
        return card

    def _build_crit_card(self, parent: QWidget) -> QWidget:
        """暴击 / 爆伤两项下限 + 右侧总开关，全排在一行里。"""
        card = CardWidget(parent)
        row = QHBoxLayout(card)
        row.setContentsMargins(20, 15, 20, 15)
        row.setSpacing(10)

        self.crit_field = NumberField(DEFAULT_CRIT_MIN, card)
        self.crit_dmg_field = NumberField(DEFAULT_CRIT_DMG_MIN, card)
        self.crit_field.changed.connect(lambda *_: self._notify())
        self.crit_dmg_field.changed.connect(lambda *_: self._notify())

        row.addWidget(StrongBodyLabel("暴击不低于", card))
        row.addWidget(self.crit_field)
        row.addSpacing(22)
        row.addWidget(StrongBodyLabel("爆伤不低于", card))
        row.addWidget(self.crit_dmg_field)
        row.addStretch(1)

        # 关掉后完全跳过双爆下限检查（两个数值框同时置灰）
        self.crit_switch = SwitchButton(card)
        self.crit_switch.setOnText("启用")
        self.crit_switch.setOffText("不启用")
        self.crit_switch.setChecked(True)
        self.crit_switch.checkedChanged.connect(self._on_crit_switch)
        row.addWidget(self.crit_switch)
        return card

    def _build_maxroll_card(self, parent: QWidget) -> QWidget:
        """满暴击 / 满爆伤自动保护：单个开关，独立成卡片。

        不跟「暴击不低于 / 爆伤不低于」挤同一行 —— 那行已经有 4 个控件，
        再塞一个开关会把整行拉爆。
        """
        card = CardWidget(parent)
        row = QHBoxLayout(card)
        row.setContentsMargins(20, 15, 20, 15)
        row.setSpacing(10)

        box = QWidget(card)
        col = QVBoxLayout(box)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(2)
        col.addWidget(StrongBodyLabel(f"满{CRIT} / 满爆伤 自动锁定", box))
        hint = CaptionLabel(
            f"出现满值词条（{CRIT} {MAX_CRIT:g} / 爆伤 {MAX_CRIT_DMG:g}）时："
            f"不看别的条件，一律强化到满级并上锁，不弃置。"
            f"判定排在双爆下限与有效词条之前 —— 出了满值就保住。",
            box,
        )
        hint.setTextColor("#8A8F98", "#7C7C7C")
        hint.setWordWrap(True)
        col.addWidget(hint)
        row.addWidget(box, 1)

        self.maxroll_switch = SwitchButton(card)
        self.maxroll_switch.setOnText("启用")
        self.maxroll_switch.setOffText("不启用")
        self.maxroll_switch.setChecked(True)      # 需求：默认就开着
        self.maxroll_switch.checkedChanged.connect(lambda *_: self._notify())
        row.addWidget(self.maxroll_switch, 0, Qt.AlignmentFlag.AlignTop)
        return card

    def _build_autostop_card(self, parent: QWidget) -> QWidget:
        """★ 出现符合条件的声骸 → 自动暂停任务并通知（用户 2026-10-10 要求）。

        ⚠ 文案里必须把**排除项**写清楚。用户原话::

            "出现符合条件声骸自动停止
             （不包括出现满爆击/满暴伤，但是词条数不符合的）"

        因为「满值保护」是最高优先且会短路，满暴击/满爆伤**一定会被上锁**，
        用户很容易以为"上锁 = 符合条件"。不说清楚的话，他会觉得这功能坏了
        （明明停下来的次数比想象中少）。
        """
        card = CardWidget(parent)
        row = QHBoxLayout(card)
        row.setContentsMargins(20, 15, 20, 15)
        row.setSpacing(10)

        box = QWidget(card)
        col = QVBoxLayout(box)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(2)
        col.addWidget(StrongBodyLabel("出现符合条件的声骸就自动停止", box))
        hint = CaptionLabel(
            "强化过程中一旦出现**真正符合条件**的声骸：立刻暂停任务（游戏停手，"
            "不会继续强化下一个），托盘弹通知叫你回来确认。\n"
            f"⚠ **不算**这一条：只因为出了满{CRIT}/满爆伤而被上锁、"
            f"但有效词条数其实不够的声骸 —— 那种是满值保护保下来的，"
            f"不触发自动停止。",
            box,
        )
        hint.setTextColor("#8A8F98", "#7C7C7C")
        hint.setWordWrap(True)
        col.addWidget(hint)
        row.addWidget(box, 1)

        self.autostop_switch = SwitchButton(card)
        self.autostop_switch.setOnText("启用")
        self.autostop_switch.setOffText("不启用")
        self.autostop_switch.setChecked(True)      # 需求：默认就开着
        self.autostop_switch.checkedChanged.connect(lambda *_: self._notify())
        row.addWidget(self.autostop_switch, 0, Qt.AlignmentFlag.AlignTop)
        return card

    def _build_optional_card(self, parent: QWidget) -> CardWidget:
        card = CollapsibleCard(
            "可选属性",
            f"这里列的是去掉{CRIT}、{CRIT_DMG}之后的属性，勾中的算作有效词条。\n"
            f"已在「核心属性」里勾选的会置灰且不可勾选 —— 同一条属性不重复勾。",
            parent=parent,
        )
        grid = QGridLayout()
        grid.setSpacing(6)
        columns = 4
        rows = (len(OPTIONAL_CHOICES) + columns - 1) // columns
        for index, stat in enumerate(OPTIONAL_CHOICES):
            box = CheckBox(stat, card)
            box.stateChanged.connect(self._update_optional_count)
            grid.addWidget(box, index % rows, index // rows)
            self._optional_boxes[stat] = box

        holder = QWidget(card)
        holder.setLayout(grid)
        card.add(holder)

        self.optional_count_label = card.summary_label
        self._update_optional_count()
        return card

    def _build_valid_card(self, parent: QWidget) -> QWidget:
        # 加减控件直接放标题行右侧，省掉一行。真实范围由 _sync_valid_count()
        # 随核心/可选属性联动调整（这里只是起步值）。
        stepper = NumberStepper(MIN_VALID_COUNT, MAX_VALID_COUNT, DEFAULT_VALID_COUNT, parent)
        stepper.changed.connect(lambda *_: self._notify())
        self.valid_stepper = stepper

        controls = QWidget(parent)
        row = QHBoxLayout(controls)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        row.addWidget(BodyLabel("至少", controls))
        row.addWidget(stepper)
        row.addWidget(BodyLabel("条", controls))

        card = ConfigCard(
            "有效词条",
            f"至少要有多少条有效词条（核心属性 + 可选属性都算）。"
            f"若「当前有效 + 剩余孔位」都达不到这个数，就弃置。"
            f"这个数**跟着核心属性条数走**：改核心属性时它会回到核心条数（之后仍可往上调）。",
            parent,
            header_widget=controls,
        )
        # 取值范围随核心/可选属性联动，这里放一行实时提示（见 _sync_valid_count）
        self.criterion_label = CaptionLabel("", card)
        self.criterion_label.setWordWrap(True)
        self.criterion_label.setTextColor("#8A8F98", "#7C7C7C")
        card.add(self.criterion_label)
        return card

    def _checked_core(self) -> list[str]:
        return [name for name, box in self._core_boxes.items() if box.isChecked()]

    def _checked_optional(self) -> list[str]:
        return [name for name, box in self._optional_boxes.items() if box.isChecked()]

    def _on_core_changed(self, *_) -> None:
        checked = self._checked_core()
        if len(checked) > MAX_CORE_STATS:
            # 超限：只撤销**刚被点击的那个**（sender），不要按字典序误伤别的已勾选项。
            target = self.sender()
            forced_boxes = (
                self._core_boxes.get(CRIT),
                self._core_boxes.get(CRIT_DMG),
            )
            if target in forced_boxes or not hasattr(target, "isChecked") or not target.isChecked():
                # 兜底（程序化 setChecked 等）：撤销最后一个非强制已勾选项
                target = None
                for name, box in reversed(list(self._core_boxes.items())):
                    if name not in (CRIT, CRIT_DMG) and box.isChecked():
                        target = box
                        break
            if target is not None and target.isChecked():
                target.blockSignals(True)
                target.setChecked(False)
                target.blockSignals(False)
            # 用户要求：红字 + 原文「核心属性最多只能勾选5条」
            InfoBar.error(
                f"核心属性最多只能勾选{MAX_CORE_STATS}条",
                f"{CRIT}、{CRIT_DMG}强制占 2 条，自选最多 {MAX_CORE_STATS - 2} 条"
                f"（已取消刚才的勾选）",
                parent=self.window(),
            )
        # 核心条数变了 → 有效词条数跟着回到核心条数；**先**跟随再存盘，
        # 存下来的就是跟随后的值（否则减少核心时界面降了、盘上还是旧值）
        #
        # 联动顺序有讲究：**先**同步可选的置灰状态，再收敛有效词条数、再存盘。
        # 反过来的话 `_collect_settings()` 会把"已经进了核心、却还勾在可选里"
        # 的脏状态写进盘。
        self._sync_optional_with_core()
        self._sync_valid_count(follow_core=True)
        self._notify()
        self._update_core_count()
        self._update_optional_count()

    def _update_core_count(self) -> None:
        checked = self._checked_core()
        names = "、".join(checked) if checked else "尚未勾选"
        # 偏离出厂默认时明说 —— 否则"上次勾的"很容易被当成"默认坏了"
        suffix = "" if tuple(checked) == tuple(DEFAULT_CORE) else "（非默认 · 可点「恢复默认」）"
        self.core_count_label.setText(
            f"已勾选 {len(checked)} / {MAX_CORE_STATS} 条：{names}{suffix}")
        self._sync_core_limits()

    def _sync_core_limits(self) -> None:
        """满员时的交互规则（2026-09-24 严重 BUG 修复）：

        * **已勾的保持可点** —— 用来取消。以前整片 `setEnabled(False)`，
          勾满 5 条后连取消都做不到，卡死；
        * **未勾的满员时置灰** —— 让"不能再勾了"一眼看得见。曾经改成"全部可点、
          点了才弹红字"，用户反馈『报错提示出现了，但为什么我还是可以勾选这么多』
          （2026-09-24）—— 点得动却没有反馈（内容不变），体感就是"上限没生效"。
        双爆强制项始终禁用，与是否满员无关。
        """
        full = len(self._checked_core()) >= MAX_CORE_STATS
        for name, box in self._core_boxes.items():
            if name in (CRIT, CRIT_DMG):
                continue
            box.setEnabled(box.isChecked() or not full)
            if full and box.isChecked():
                box.setToolTip(f"已勾选；点击可取消（核心属性最多 {MAX_CORE_STATS} 条）")
            elif full:
                box.setToolTip(f"核心属性已满 {MAX_CORE_STATS} 条 —— 再勾会红字报错")
            else:
                box.setToolTip("")

    def _on_crit_switch(self, enabled: bool) -> None:
        """总开关：关掉时两个数值框一起置灰，一眼能看出当前不生效。"""
        self.crit_field.setEnabled(enabled)
        self.crit_dmg_field.setEnabled(enabled)
        self._notify()

    def _update_optional_count(self, *_) -> None:
        checked = self._checked_optional()
        names = "、".join(checked) if checked else "尚未勾选"
        self.optional_count_label.setText(f"已勾选 {len(checked)} 条：{names}")
        self._notify()

    def _sync_optional_with_core(self) -> None:
        """核心 ↔ 可选联动：**进了核心的属性，在可选里置灰且不可勾选**。

        为什么需要：同一条属性出现在两边是自相矛盾的 —— 核心是"必须有"，
        可选是"另外也算有效词条"，勾重了只会让「有效词条数」的联动算糊涂。
        （暴击 / 暴击伤害本来就不在可选列表里，这里管的是自选进核心的那些。）

        两个细节：

        * 置灰的同时**清掉勾选**。留一个"灰着的已勾选项"最坑 ——
          用户会以为它还生效，实际已经不参与判定了。
        * 核心那边取消勾选后，这里**恢复可点但不会自动勾回来** ——
          不替用户做决定，避免"取消一下核心、可选的勾选却凭空多了"。
        """
        core = set(self._checked_core())
        for name, box in self._optional_boxes.items():
            if name in core:
                if box.isChecked():
                    box.blockSignals(True)
                    box.setChecked(False)
                    box.blockSignals(False)
                box.setEnabled(False)
                box.setToolTip(f"已在「核心属性」里勾选 —— 二者只能选一边")
            else:
                box.setEnabled(True)
                box.setToolTip("")

    def _collect_settings(self) -> EchoSettings:
        """界面上的当前选择 → 设置对象。"""
        return EchoSettings(
            core_stats=tuple(self._checked_core()),
            optional_stats=tuple(self._checked_optional()),
            crit_min=self.crit_field.value(),
            crit_dmg_min=self.crit_dmg_field.value(),
            enable_crit_check=self.crit_switch.isChecked(),
            enable_max_roll_lock=self.maxroll_switch.isChecked(),
            enable_auto_stop=self.autostop_switch.isChecked(),
            min_valid_count=self.valid_stepper.value(),
        )

    def _apply_settings(self, settings: EchoSettings) -> None:
        """把一份设置填回控件（回填期间屏蔽信号，别顺手触发保存）。

        ⚠ **加载路径也要校验上限**：盘上若存着超过 ``MAX_CORE_STATS`` 条核心属性
        （老版本或手改留下的脏数据），原样填进去就会显示成「8 / 5 条」——
        2026-09-24 用户就是因此认为"上限根本没生效"。超出部分截掉并记日志。
        ``from_dict`` 已保证双爆排在最前，所以截断不会丢掉强制项。
        """
        core = tuple(settings.core_stats)[:MAX_CORE_STATS]
        if len(settings.core_stats) > MAX_CORE_STATS:
            logger.warning("核心属性 %d 条超出上限 %d，界面只填前 %d 条：%s",
                           len(settings.core_stats), MAX_CORE_STATS, MAX_CORE_STATS, core)
        for name, box in self._core_boxes.items():
            box.blockSignals(True)
            box.setChecked(name in core or name in (CRIT, CRIT_DMG))
            box.blockSignals(False)
        for name, box in self._optional_boxes.items():
            box.blockSignals(True)
            box.setChecked(name in settings.optional_stats)
            box.blockSignals(False)

        self.crit_field.set_value(settings.crit_min)
        self.crit_dmg_field.set_value(settings.crit_dmg_min)
        self.crit_switch.setChecked(settings.enable_crit_check)
        self.maxroll_switch.setChecked(settings.enable_max_roll_lock)
        self.autostop_switch.setChecked(settings.enable_auto_stop)

        self._on_crit_switch(settings.enable_crit_check)   # 双爆框的灰/亮跟着开关走
        # 核心 ↔ 可选联动：盘上若存着"两边都勾了"的脏数据（老版本写过），
        # 这里顺手收敛掉 —— 可选那边置灰并取消勾选。
        self._sync_optional_with_core()
        self._update_core_count()
        self._update_optional_count()
        # ★ 顺序要紧：**先把范围收敛好，再填「有效词条数」**。
        #   反过来的话 `set_value` 会被**旧范围**钳住 —— 编辑器构造时可选属性还空着，
        #   范围是 (2,2)，于是别处存着 3 的配置载进来会变成 2
        #   （2026-09-26 实测：新建的配置显示 2、而源配置是 3，保存下去还会把它改掉）。
        self._sync_valid_count()
        self.valid_stepper.set_value(settings.min_valid_count)

    def _sync_valid_count(self, *_, follow_core: bool = False) -> None:
        """把「有效词条数」与核心/可选属性**联动**（用户要求）。

        * **不可小于核心属性条数** —— 核心属性是"必须有"，全都到齐就天然有
          ``len(core)`` 条有效词条，要求更低是自相矛盾的；
        * **不可大于有效词条集合总条数** —— 声骸每种词条只会出现一次，集合里没有的
          种类永远凑不出来（2026-09-24「要求 ≥3 而集合只有 2 条」那类事故的根源）。

        两头夹住之后，"配出一个不可能满足的条件"在界面上就做不到了。
        """
        if self._syncing_valid:
            return                     # set_range 会发 changed → 别递归
        stepper = getattr(self, "valid_stepper", None)
        label = getattr(self, "criterion_label", None)
        if stepper is None or label is None:
            return                     # 卡片还没建好（构造过程中）

        self._syncing_valid = True
        try:
            core = self._checked_core()
            optional = self._checked_optional()
            low, high = valid_count_range(core, optional)
            stepper.set_range(low, high, emit=False)
            if follow_core:
                # 核心属性变了 → 有效词条数**跟着回到核心条数**（用户要求：
                # "核心 2 条时有效词条就该是 2 条"，减少核心也要跟着降）。
                # 静默设值就够了 —— _notify 在回填期间不会发信号，不会漏存也不会多存。
                stepper.set_value(low, emit=False)

            total = len(set(core) | set(optional))
            text = f"有效词条数不可小于核心词条数（{len(core)} 条）"
            if low == high:
                text += (f" —— 当前只能设 {low} 条：声骸每种词条只出现一次，"
                         f"在「可选属性」里多勾几条才能提高上限")
            else:
                text += f"，也不可大于有效词条总数（{total} 条）—— 可设 {low}~{high} 条"
            label.setText(text)
        finally:
            self._syncing_valid = False
