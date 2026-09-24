"""声骸自动强化 —— 配置界面 + 运行。

界面结构对应需求：
    ① 核心属性（必输有，缺则弃置；最多 5 条；暴击/爆伤强制勾选且不可取消）
    ② 暴击 / 爆伤各自的下限（左右 -/+ 按钮，也可直接输入）
    ③ 可选属性（列表去掉双爆，勾选数量不限）
    ④ 有效词条数（加减按钮，范围随核心/可选属性联动）
    ⑤ 运行 / 停止
    ⑥ 结果报告（判定数 / 符合条件 / 弃置原因 / 满属性，跑的过程实时刷新）

运行模型：**强化流程整个交给 ok-ww 引擎**（与「4C 自动战斗」共用同一个宿主，
见 ``auto_combat/okww_boot.py``）。本页只负责两件事：
① 收集用户配的筛选条件；② 点「运行」时把它注入任务并启动。

为什么不再自己写一套点击/OCR：2026-09-23 实测那套（``controller`` / ``runner`` /
``reader``）在别的机器上**完全没用**，而同期 4C 走的 ok-ww 引擎是通的 ——
于是流程直接搬 ok-ww 的 ``EnhanceEchoTask``，见 ``okww_task.py``；
只有判定条件换成这里界面上的那套。

按钮状态靠定时器轮询宿主（不自己维护线程），界面不会被阻塞。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    CheckBox,
    FluentIcon,
    InfoBar,
    PrimaryPushButton,
    PushButton,
    ScrollArea,
    StrongBodyLabel,
    SwitchButton,
)

from ....core import paths
from ....core.categories import ToolCategory
from ....gui.widgets import CollapsibleCard, ConfigCard, NumberField, NumberStepper
from ....core.registry import logger, registry
from ....core.tool_base import BaseTool
from ..auto_combat.okww_boot import get_host
from .settings import DEFAULT_CORE, DEFAULT_VALID_COUNT, TASK_KEY, EchoSettings, valid_count_range
from .stats import (
    ALL_STATS,
    CRIT,
    CRIT_DMG,
    DEFAULT_CRIT_DMG_MIN,
    DEFAULT_CRIT_MIN,
    format_result_report,
    MAX_CORE_STATS,
    MAX_CRIT,
    MAX_CRIT_DMG,
    MAX_VALID_COUNT,
    MIN_VALID_COUNT,
    OPTIONAL_CHOICES,
    JudgeConfig,
)


# --------------------------------------------------------------------- 说明
# 这里原来有个 RunnerThread：在 QThread 里跑 MyTools 自己写的强化状态机。
# 2026-09-23 换成 ok-ww 引擎后就不需要了 —— 后台线程由 ok-script 的 TaskExecutor
# 负责，本页只用 QTimer 轮询宿主状态。

# --------------------------------------------------------------------- 小控件
# 数值加减框（NumberStepper / NumberField）和配置卡片（ConfigCard）都挪到了
# src/gui/widgets.py —— 新工具「4C 自动战斗」要用同一套，别在后头各写一份。


# ------------------------------------------------------------------ 统计快照


def _snapshot_task_stats(task) -> dict:
    """从任务实例抄一份本次运行的统计。

    为什么每 300ms 抄一次：任务跑完会被 ok-script disable，到时候
    ``checked_echoes`` / ``discard_tally`` 这些实例属性就读不到了。
    """
    info = getattr(task, "info", None)
    if not isinstance(info, dict):
        info = {}
    return {
        "checked": int(getattr(task, "checked_echoes", 0) or 0),
        "kept": int(info.get("成功声骸数量") or 0),
        "dropped": int(info.get("失败声骸数量") or 0),
        # 满属性只在「启用满暴击/满爆伤自动锁定」时才统计 ——
        # 键不存在就是没启用，报告里也不显示这项
        "perfect": info.get("满属性声骸数量"),
        "tally": dict(getattr(task, "discard_tally", None) or {}),
    }


# --------------------------------------------------------------------- 主界面

class EchoEnhanceWidget(ScrollArea):
    def __init__(self, meta, parent=None):
        super().__init__(parent)
        self.meta = meta
        self.setObjectName("EchoEnhanceWidget")
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._core_boxes: dict[str, CheckBox] = {}
        self._optional_boxes: dict[str, CheckBox] = {}
        #: ok-ww 宿主（进程内单例，与 4C 自动战斗共用一个 OK 实例）
        self._host = get_host()
        self._timer: QTimer | None = None
        #: 只在状态**变化**时写日志，别每 300ms 刷一次
        self._last_state = ""
        self._was_running = False
        #: 任务跑起来后持续抄统计 —— 结束时任务被 disable，就取不到了
        self._last_stats: dict = {}
        #: 本次轮询期间见过本页的任务（running/pending）——
        #: 引擎自启完成（booting→ready）不算「任务结束」，就靠它区分
        self._task_seen = False
        #: 本页当前的一套设置。**每次打开页面都是出厂默认**（用户 2026-09-24
        #: 明确要求："不要遗留上次的东西，每次进入都是默认配置"）—— 所以这里
        #: 不用 ``EchoSettings.load()``。改动仍然存盘，任务流程读的就是存下来那份
        #: （两个入口用同一套规则，见 settings.py 顶部说明）。
        self._settings = EchoSettings()
        #: 回填过程中不要存盘（否则构造/回填会触发一串无意义的写文件）
        self._loading_settings = True
        #: 正在同步「有效词条数」的范围（防 set_range → changed → 再绕回来）
        self._syncing_valid = False

        view = QWidget(self)
        view.setObjectName("echoView")
        layout = QVBoxLayout(view)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)

        layout.addWidget(self._build_title_row(view))
        intro = CaptionLabel(
            "在背包 → 声骸界面用过滤器筛好、按等级升序排序，再点运行。"
            "强化流程由 ok-ww 引擎执行（与「4C 自动战斗」同一个引擎，后台按键不抢前台）："
            "符合条件的上锁保留，不符合条件的自动弃置。\n"
            f"运行日志按日期落盘：{paths.user_data_dir() / 'okww' / 'logs'}"
            "（出问题把当天那个文件发过来即可）",
            view,
        )
        intro.setTextColor("#8A8F98", "#7C7C7C")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        layout.addWidget(self._build_core_card(view))
        layout.addWidget(self._build_crit_card(view))
        layout.addWidget(self._build_maxroll_card(view))
        layout.addWidget(self._build_optional_card(view))
        layout.addWidget(self._build_valid_card(view))
        layout.addWidget(self._build_report_card(view))

        layout.addStretch(1)

        # 回填上次的选择 —— 界面上看到的值 = 任务流程会用的值，必须是同一份
        self._apply_settings(self._settings)
        self._loading_settings = False

        self.setWidget(view)
        self.setWidgetResizable(True)

        # 状态靠轮询宿主（和 4C 工具页一致），页面不自己维护线程
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(300)
        self._poll()

    # ---------------------------------------------------------------- 配置卡片
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
        self.crit_field.changed.connect(self._save_settings)
        self.crit_dmg_field.changed.connect(self._save_settings)

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
            f"不看别的条件，一律强化到满级并上锁，不弃置。判定排在弃置之前，"
            f"优先于上面的双爆下限与有效词条规则。",
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
        self.maxroll_switch.checkedChanged.connect(self._save_settings)
        row.addWidget(self.maxroll_switch, 0, Qt.AlignmentFlag.AlignTop)
        return card

    def _build_optional_card(self, parent: QWidget) -> CardWidget:
        card = CollapsibleCard(
            "可选属性",
            f"这里列的是去掉{CRIT}、{CRIT_DMG}之后的属性，勾中的算作有效词条。",
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
        stepper.changed.connect(self._save_settings)
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

    def _build_report_card(self, parent: QWidget) -> QWidget:
        """本次运行的结果报告（判定数 / 符合条件 / 弃置原因 / 满属性）。

        跑的过程中就实时刷新（数据来自每 300ms 的统计快照），结束后定格。
        """
        card = CardWidget(parent)
        col = QVBoxLayout(card)
        col.setContentsMargins(20, 15, 20, 15)
        col.setSpacing(4)
        col.addWidget(StrongBodyLabel("结果报告", card))
        self.report_label = CaptionLabel(
            "还没跑过 —— 点「运行」后这里实时显示本次的统计", card)
        self.report_label.setTextColor("#8A8F98", "#7C7C7C")
        self.report_label.setWordWrap(True)
        # 老坑：QLabel 开 wordWrap 后 sizeHint 只算一行 → 第二行（弃置原因）被截掉。
        # 按两行钉最小高度；正文固定两行以内（首行统计 + 弃置原因），不会溢出。
        self.report_label.setMinimumHeight(46)
        col.addWidget(self.report_label)
        return card

    def _update_report_card(self, text: str) -> None:
        label = getattr(self, "report_label", None)
        if label is not None:
            label.setText(text)

    def _build_title_row(self, parent: QWidget) -> QWidget:
        """标题 + 紧随其后的操作按钮。"""
        holder = QWidget(parent)
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)

        row.addWidget(StrongBodyLabel("声骸自动强化", holder))

        self.run_button = PrimaryPushButton(FluentIcon.PLAY, "运行", holder)
        self.run_button.clicked.connect(self._on_run)

        self.stop_button = PushButton(FluentIcon.CANCEL, "停止", holder)
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self._on_stop)

        # 乱了一键拉回出厂默认：核心仅双爆 / 有效词条 = 2 / 可选清空
        self.reset_button = PushButton(FluentIcon.SYNC, "恢复默认", holder)
        self.reset_button.clicked.connect(self._on_reset_defaults)

        # 按钮紧跟在标题右边，不推到最右
        row.addWidget(self.run_button)
        row.addWidget(self.stop_button)
        row.addWidget(self.reset_button)
        row.addStretch(1)
        return holder

    # ---------------------------------------------------------------- 勾选约束
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
        self._sync_valid_count(follow_core=True)
        self._save_settings()
        self._update_core_count()

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
        self._save_settings()

    def _update_optional_count(self, *_) -> None:
        checked = self._checked_optional()
        names = "、".join(checked) if checked else "尚未勾选"
        self.optional_count_label.setText(f"已勾选 {len(checked)} 条：{names}")
        self._save_settings()

    # ---------------------------------------------------------------- 配置读写
    def _collect_settings(self) -> EchoSettings:
        """界面上的当前选择 → 设置对象。"""
        return EchoSettings(
            core_stats=tuple(self._checked_core()),
            optional_stats=tuple(self._checked_optional()),
            crit_min=self.crit_field.value(),
            crit_dmg_min=self.crit_dmg_field.value(),
            enable_crit_check=self.crit_switch.isChecked(),
            enable_max_roll_lock=self.maxroll_switch.isChecked(),
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
        self.valid_stepper.set_value(settings.min_valid_count)

        self._on_crit_switch(settings.enable_crit_check)   # 双爆框的灰/亮跟着开关走
        self._update_core_count()
        self._update_optional_count()
        self._sync_valid_count()       # 范围/提示跟着回填好的核心 + 可选属性走

    def _save_settings(self, *_) -> None:
        """配置一变就存盘 —— **任务流程运行时读的就是这一份**。"""
        if self._loading_settings:
            return                     # 构造 / 回填期间不写盘
        # 先把「有效词条数」的范围与当前值收敛好 —— 核心/可选属性刚可能变过，
        # 不收敛就会把一个越界的值存进去
        self._sync_valid_count()
        self._settings = self._collect_settings()
        try:
            self._settings.save()
        except Exception as exc:  # noqa: BLE001 - 存不下来不该影响使用
            logger.warning("声骸强化设置存不下来：%s", exc)

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
                # 静默设值就够了 —— _save_settings 是先同步再收集，不会漏存。
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

    def build_judge_config(self) -> JudgeConfig:
        """界面当前的值 → 判定配置（双爆由 JudgeConfig 强制进核心属性）。"""
        return self._collect_settings().to_judge_config()

    # ---------------------------------------------------------------- 日志
    def _append(self, text: str) -> None:
        """界面上不再显示日志区，运行日志走标准 logging
        （PyCharm 的运行/调试窗口里能看到；出错时另有 InfoBar 弹窗）。"""
        logger.info("[声骸强化] %s", text)

    # ---------------------------------------------------------------- 动作
    def _on_run(self) -> None:
        self._save_settings()          # 顺手存盘：任务流程跑的时候读的就是这一份
        settings = self._collect_settings()
        config = settings.to_judge_config()

        self._append("— 开始运行（ok-ww 引擎）—")
        self._append("判定配置：" + settings.describe())
        self._append("前置：请停在 背包 → 声骸 界面，用过滤器筛好、按等级升序排序")
        self._append("⚠ 不符合条件的自动弃置（按 Z），符合条件的上锁（按 C）")
        if self._host.state in ("idle", "error"):
            self._append("引擎未就绪：后台加载 ok-ww 中，就绪后自动开始（首次会慢一些）")

        # 把页面上的判定条件注入任务实例（ok-ww 的任务本身不知道这些）
        def configure(task):
            task.judge_config = config

        err = self._host.start_task(TASK_KEY, configure=configure)
        if err:
            self._append("启动失败：" + err)
            InfoBar.error("启动失败", err, duration=8000, parent=self.window())
            return
        self._poll()

    def _on_reset_defaults(self) -> None:
        """一键回到出厂默认：核心仅双爆、有效词条 = 2、可选属性清空。

        为什么有这个按钮：勾选是**自动存盘**的，测试/试用时随手勾的几条会一直
        留着，第二天打开看着就像"默认错了"（2026-09-24 用户反馈）。
        """
        from qfluentwidgets import MessageBox  # 局部导入：只有点了才需要
        box = MessageBox(
            "恢复默认设置？",
            "核心属性将回到「暴击 + 暴击伤害」，有效词条数回到 "
            f"{DEFAULT_VALID_COUNT}，可选属性清空；\n"
            "双爆下限、满值保护等开关也一并回到默认值。",
            self.window(),
        )
        if not box.exec():
            return
        self._loading_settings = True
        try:
            self._apply_settings(EchoSettings())
        finally:
            self._loading_settings = False
        self._save_settings()
        self._append("已恢复默认设置：" + self._settings.describe())
        InfoBar.success("已恢复默认", "核心属性：暴击、暴击伤害；有效词条 ≥"
                        f"{DEFAULT_VALID_COUNT}", duration=3000, parent=self.window())

    def _on_stop(self) -> None:
        err = self._host.stop_task()
        if err:
            self._append("停止失败：" + err)
            InfoBar.warning("停止失败", err, duration=8000, parent=self.window())
        else:
            self._append(">>> 已请求停止")

    # ---------------------------------------------------------------- 轮询
    def _poll(self) -> None:
        """照「4C 自动战斗」那套：状态从宿主读，页面不自己维护线程。"""
        # 「引擎就绪后才开任务」那条路以前只有日志，页面上看不到 ——
        # 用户会以为"点了运行没反应"。这里把它捞出来弹一次。
        start_error = self._host.take_start_error()
        if start_error:
            self._append("启动失败：" + start_error)
            InfoBar.error("启动失败", start_error, duration=12000, parent=self.window())

        state = self._host.state
        running = self._host.running_task
        pending = self._host.pending_start
        err = self._host.boot_error
        key = TASK_KEY if (running == TASK_KEY or pending == TASK_KEY) else None

        # 跑起来之后持续抄统计（结束/被 disable 之后就取不到了）
        if key:
            task = self._host.find_task(key)
            if task is not None:
                self._last_stats = _snapshot_task_stats(task)
            self._task_seen = True
            self._update_report_card(format_result_report(**self._last_stats))

        if state != self._last_state:
            if err and state == "error":
                self._append("引擎启动失败：" + err)
                InfoBar.error("引擎启动失败", err, duration=8000, parent=self.window())
            elif state == "booting" and (pending == TASK_KEY or not pending):
                self._append("引擎：后台加载 ok-ww 运行时…（首次加载 OCR 模型会慢一些）")
            elif state == "running" and key:
                self._append("引擎：运行中 —— 声骸自动强化")
            elif state == "ready" and self._last_state in ("running", "booting"):
                if self._task_seen:
                    # 只有真的跑过本页任务才算「结束」。引擎自启完成（booting→ready、
                    # 从没跑过任务）也走这条状态迁移 —— 之前在这里误弹了
                    # 「[声骸强化] 任务结束」，用户莫名其妙（2026-09-24）。
                    report = format_result_report(**self._last_stats)
                    first_line = report.splitlines()[0]
                    self._append("任务结束：" + report.replace("\n", "；"))
                    InfoBar.success("声骸强化结果", first_line, duration=10000,
                                    parent=self.window())
                    self._update_report_card(report)
                    self._task_seen = False
                    self._last_stats = {}
                elif self._last_state == "booting":
                    self._append("引擎就绪（本次没有跑任务）")
            self._last_state = state

        self._was_running = bool(running)
        self.run_button.setEnabled(not running)
        self.stop_button.setEnabled(bool(running) or bool(pending))

        # 一次性任务跑完把状态拉回 ready
        self._host.poll_done()



# --------------------------------------------------------------------- 任务流程适配

class OkwwTaskRunner:
    """把 ok-ww 宿主上的任务包装成「任务流程」能用的 runner。

    任务流程是**同步**调 ``runner.run()`` 的（它自己跑在 QThread 里），
    所以这里就阻塞轮询宿主，直到任务跑完或被要求停止。
    """

    #: 轮询间隔（秒）
    POLL = 0.3

    def __init__(self, judge_config: JudgeConfig, *, log=None, should_stop=None):
        #: 判定条件（工具页存下来的那份）。**公开字段**：任务流程的回归测试会读它，
        #: 确认"从任务页跑"和"从工具页点运行"用的是同一套规则。
        self.judge_config = judge_config
        self._log = log or (lambda msg: None)
        self._should_stop = should_stop or (lambda: False)

    def run(self) -> "RunnerSummary":
        import time

        host = get_host()
        err = host.start_task(TASK_KEY, configure=self._configure)
        if err:
            raise RuntimeError(err)
        self._log("声骸自动强化：已交给 ok-ww 引擎（按「停止」可中断）")

        last_info: dict = {}
        last_stats: dict = {}
        try:
            while True:
                task = host.find_task(TASK_KEY)
                if task is not None:
                    info = getattr(task, "info", None)
                    if isinstance(info, dict) and info:
                        last_info = dict(info)
                    last_stats = _snapshot_task_stats(task)
                host.poll_done()
                if self._should_stop():
                    host.stop_task()
                    self._log("声骸自动强化：已请求停止")
                    break
                if host.running_task != TASK_KEY and host.pending_start != TASK_KEY:
                    break
                time.sleep(self.POLL)
        except Exception:
            host.stop_task()
            raise

        kept = last_info.get("成功声骸数量") or 0
        dropped = last_info.get("失败声骸数量") or 0
        return RunnerSummary(
            kept=kept, dropped=dropped,
            checked=last_stats.get("checked", 0),
            perfect=last_stats.get("perfect"),
            tally=last_stats.get("tally") or {},
        )

    def _configure(self, task) -> None:
        task.judge_config = self.judge_config


class RunnerSummary:
    """任务流程要的 ``.summary()`` 接口。"""

    def __init__(self, *, kept: int, dropped: int, checked: int = 0,
                 perfect: int | None = None, tally: dict[str, int] | None = None):
        self.kept = kept
        self.dropped = dropped
        #: 判定的声骸总数 / 满属性数（未启用满值保护时为 None）/ 弃置原因分布
        self.checked = checked
        self.perfect = perfect
        self.tally = dict(tally or {})

    def summary(self) -> str:
        return format_result_report(
            checked=self.checked, kept=self.kept, dropped=self.dropped,
            perfect=self.perfect, tally=self.tally)


# --------------------------------------------------------------------- 注册

@registry.register(
    category=ToolCategory.GAME,
    name="声骸自动强化",
    description="按核心属性 / 双爆下限 / 可选属性 / 有效词条数，自动强化并筛选声骸",
    icon_name="GAME",
    coming_soon=False,
)
class EchoEnhanceTool(BaseTool):
    key = "echo_enhance"
    version = "0.1.0"
    supports_task_run = True
    #: 自定义图标。放一张鸣潮的图标覆盖这个文件（256x256 的 png 最好），界面会自动用它
    icon_path = str(paths.resource_dir("assets", "icons", "echo_enhance.png"))

    def create_widget(self, parent=None):
        return EchoEnhanceWidget(self.meta(), parent)

    # ---------------------------------------------------------------- 任务系统
    def create_task_runner(self, options: dict, log, should_stop):
        """给「任务流程」用：把 ok-ww 宿主上的声骸强化任务包装成同步 runner。

        判定条件照样取工具页保存的那份（``settings.py``）——
        "从任务页跑"和"从工具页点运行"必须是同一套规则。
        任务编排里挂的配置（角色配置）仍然只记日志 —— 强化判定不吃角色配置。
        """
        settings = EchoSettings.load()
        log(f"判定配置（取自工具页保存的设置）：{settings.describe()}")
        bound = options.get("configs") or []
        if bound:
            log(f"（编排里挂了配置：{'、'.join(bound)} —— 强化判定不使用角色配置，仅作记录）")
        return OkwwTaskRunner(settings.to_judge_config(), log=log, should_stop=should_stop)

    def create_task_prep(self, options: dict, log, should_stop):
        """准备步：ok-ww 的强化任务要求**人已经在声骸界面**，所以这里只做提示。

        以前这里会自己开背包、切页签、调过滤器（``prepare.py``）—— 那套跟自写的
        点击/OCR 是一体的，已经不作数了。ok-ww 的 ``EnhanceEchoTask`` 开头就会检查
        是否停在过滤器后的声骸列表，不在就报错退出，不需要我们先动界面。
        """
        log("判定配置（取自工具页保存的设置）：" + EchoSettings.load().describe())
        log("提示：请先停在 背包 → 声骸 界面，用过滤器筛好并按等级升序排序，再开始")
        bound = options.get("configs") or []
        if bound:
            log(f"（编排里挂了配置：{'、'.join(bound)} —— 准备阶段不使用角色配置，仅作记录）")
        return None
