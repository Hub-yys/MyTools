"""声骸自动强化 —— 配置界面 + 运行。

界面结构对应需求：
    ① 核心属性（必输有，缺则弃置；最多 5 条；暴击/爆伤强制勾选且不可取消）
    ② 暴击 / 爆伤各自的下限（左右 -/+ 按钮，也可直接输入）
    ③ 可选属性（列表去掉双爆，勾选数量不限）
    ④ 有效词条数（加减按钮，2~5）
    ⑤ 运行 / 停止

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
from .settings import TASK_KEY, EchoSettings
from .stats import (
    ALL_STATS,
    CRIT,
    CRIT_DMG,
    DEFAULT_CRIT_DMG_MIN,
    DEFAULT_CRIT_MIN,
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
        #: 任务跑起来后持续记录它的统计 —— 结束时框架会把任务 disable 掉，就读不到了
        self._last_info: dict = {}
        #: 上次存下来的设置。**任务流程运行读的就是这一份**（见 settings.py）
        self._settings = EchoSettings.load()
        #: 回填过程中不要存盘（否则构造/回填会触发一串无意义的写文件）
        self._loading_settings = True

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
            "运行日志按日期落盘：%LOCALAPPDATA%\\MyTools\\okww\\logs\\"
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
            f"必须有，缺任意一条就弃置；最多勾 {MAX_CORE_STATS} 条。"
            f"{CRIT}、{CRIT_DMG}强制勾选且不可取消。",
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
        # 加减控件直接放标题行右侧，省掉一行
        stepper = NumberStepper(MIN_VALID_COUNT, MAX_VALID_COUNT, 3, parent)
        stepper.changed.connect(self._save_settings)
        self.valid_stepper = stepper

        controls = QWidget(parent)
        row = QHBoxLayout(controls)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        row.addWidget(BodyLabel("至少", controls))
        row.addWidget(stepper)
        row.addWidget(BodyLabel("条", controls))

        return ConfigCard(
            "有效词条",
            f"至少要有多少条有效词条（核心属性 + 可选属性都算）。"
            f"若「当前有效 + 剩余孔位」都达不到这个数，就弃置。范围 {MIN_VALID_COUNT}~{MAX_VALID_COUNT}。",
            parent,
            header_widget=controls,
        )

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

        # 按钮紧跟在标题右边，不推到最右
        row.addWidget(self.run_button)
        row.addWidget(self.stop_button)
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
            # 超了就撤销这次勾选（双爆是禁用状态，不会出现在这里）
            for name, box in self._core_boxes.items():
                if box.isChecked() and name not in (CRIT, CRIT_DMG) and len(checked) > MAX_CORE_STATS:
                    box.blockSignals(True)
                    box.setChecked(False)
                    box.blockSignals(False)
                    checked = self._checked_core()
                    if len(checked) <= MAX_CORE_STATS:
                        break
            InfoBar.warning("核心属性最多 5 条", "已撤销这次勾选", parent=self.window())
        self._save_settings()
        self._update_core_count()

    def _update_core_count(self) -> None:
        checked = self._checked_core()
        names = "、".join(checked) if checked else "尚未勾选"
        self.core_count_label.setText(f"已勾选 {len(checked)} / {MAX_CORE_STATS} 条：{names}")

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
        """把一份设置填回控件（回填期间屏蔽信号，别顺手触发保存）。"""
        for name, box in self._core_boxes.items():
            box.blockSignals(True)
            box.setChecked(name in settings.core_stats or name in (CRIT, CRIT_DMG))
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

    def _save_settings(self, *_) -> None:
        """配置一变就存盘 —— **任务流程运行时读的就是这一份**。"""
        if self._loading_settings:
            return                     # 构造 / 回填期间不写盘
        self._settings = self._collect_settings()
        try:
            self._settings.save()
        except Exception as exc:  # noqa: BLE001 - 存不下来不该影响使用
            logger.warning("声骸强化设置存不下来：%s", exc)

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

    def _on_stop(self) -> None:
        err = self._host.stop_task()
        if err:
            self._append("停止失败：" + err)
            InfoBar.warning("停止失败", err, duration=8000, parent=self.window())
        else:
            self._append(">>> 已请求停止")

    # ---------------------------------------------------------------- 轮询
    def _task_summary(self) -> str:
        """用任务自己记的统计凑一行结果（ok-ww 的 EnhanceEchoTask 会写这两个键）。"""
        info = self._last_info
        kept = info.get("成功声骸数量")
        dropped = info.get("失败声骸数量")
        if kept is None and dropped is None:
            return ""
        return f"符合条件 {kept or 0} 个，弃置 {dropped or 0} 个"

    def _poll(self) -> None:
        """照「4C 自动战斗」那套：状态从宿主读，页面不自己维护线程。"""
        state = self._host.state
        running = self._host.running_task
        pending = self._host.pending_start
        err = self._host.boot_error
        key = TASK_KEY if (running == TASK_KEY or pending == TASK_KEY) else None

        # 跑起来之后持续记统计（结束时就取不到了）
        if key:
            task = self._host.find_task(key)
            if task is not None:
                info = getattr(task, "info", None)
                if isinstance(info, dict) and info:
                    self._last_info = dict(info)

        if state != self._last_state:
            if err and state == "error":
                self._append("引擎启动失败：" + err)
                InfoBar.error("引擎启动失败", err, duration=8000, parent=self.window())
            elif state == "booting" and (pending == TASK_KEY or not pending):
                self._append("引擎：后台加载 ok-ww 运行时…（首次加载 OCR 模型会慢一些）")
            elif state == "running":
                self._append("引擎：运行中 —— 声骸自动强化")
            elif state == "ready" and self._last_state in ("running", "booting"):
                summary = self._task_summary()
                self._append("任务结束" + ("：" + summary if summary else ""))
                InfoBar.success("任务结束", summary or "声骸自动强化已结束",
                                parent=self.window())
                self._last_info = {}
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
        try:
            while True:
                task = host.find_task(TASK_KEY)
                if task is not None:
                    info = getattr(task, "info", None)
                    if isinstance(info, dict) and info:
                        last_info = dict(info)
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
        return RunnerSummary(kept=kept, dropped=dropped)

    def _configure(self, task) -> None:
        task.judge_config = self.judge_config


class RunnerSummary:
    """任务流程要的 ``.summary()`` 接口。"""

    def __init__(self, *, kept: int, dropped: int):
        self.kept = kept
        self.dropped = dropped

    def summary(self) -> str:
        return f"符合条件 {self.kept} 个，弃置 {self.dropped} 个"


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
