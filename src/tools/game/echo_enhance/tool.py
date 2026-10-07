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
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    CaptionLabel,
    CardWidget,
    FluentIcon,
    InfoBar,
    PrimaryPushButton,
    PushButton,
    ScrollArea,
    StrongBodyLabel,
)

from ....core import paths
from ....core.categories import ToolCategory
from ....core.echo_profile import KIND as ECHO_PROFILE_KIND
from ....core.loadout import KIND as LOADOUT_KIND
from ....core.registry import logger, registry
from ....core.tool_base import BaseTool
from ..auto_combat.okww_boot import get_host
from .settings_editor import EchoSettingsEditor
from .settings import (
    DEFAULT_VALID_COUNT,
    TASK_KEY,
    EchoSettings,
)
from .stats import (
    format_result_report,
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
        # 任务异常中断的原因（okww_task.run 捕获异常时写进去的）。
        # 有它时报告优先显示它 —— 真实原因都在这里，不显示的话用户会去
        # 看默认那句「请确认停在 背包 → 声骸 界面」，完全对不上。
        "failed_reason": (str(info.get("失败原因") or "").strip() or None),
    }


# --------------------------------------------------------------------- 主界面

def _find_echo_profile(key: str):
    """按 key 取一条「角色声骸强化配置」。取不到返回 ``None``。

    key 是 ``EchoProfile.id``（**稳定 id**，改名不变）；``by_id`` 找不到
    再按**角色名**试一次 —— 兼容 2026-09-26 之前存的、按名字指的老流程。
    读配置出任何问题都不该把任务带崩，所以这里兜住。
    """
    key = str(key or "").strip()
    if not key:
        return None
    try:
        from ....core.echo_profile import EchoProfileStore

        store = EchoProfileStore()
        store.load()
        return store.by_id(key) or store.get(key)
    except Exception:  # noqa: BLE001 - 配置文件坏了就当作没有
        logger.warning("读「角色声骸强化配置」失败（key=%s）", key, exc_info=True)
        return None


def _bound_loadout(options: dict):
    """按 key 取编排里挂的「角色声骸筛选配置」（``Loadout``）。取不到返回 ``None``。

    key 是 ``Loadout.id``。找不到（配置被删了）就返回 None —— 调用方会退化成
    "让用户自己筛"，不会因此把任务打断。
    """
    keys = list(options.get("config_keys") or [])
    kinds = list(options.get("config_kinds") or [])
    for index, key in enumerate(keys):
        kind = kinds[index] if index < len(kinds) else ""
        if kind != LOADOUT_KIND:
            continue
        try:
            from ....core.loadout import LoadoutStore

            return LoadoutStore().get(str(key))
        except Exception:  # noqa: BLE001 - 配置坏了不该把任务带崩
            logger.warning("读「角色声骸筛选配置」失败（key=%s）", key, exc_info=True)
            return None
    return None


def _loadout_picks(loadout) -> dict:
    """``{档位: [声骸名, ...]}`` —— 给日志用（每档勾了几个什么）。"""
    result: dict = {}
    for cost in (4, 3, 1):
        try:
            picks = loadout.picks_of(cost)
        except Exception:  # noqa: BLE001
            picks = []
        if picks:
            result[cost] = [
                getattr(getattr(pick, "echo", None), "name", str(getattr(pick, "echo", "")))
                for pick in picks
            ]
    return result


class EchoEnhanceWidget(ScrollArea):
    def __init__(self, meta, parent=None):
        super().__init__(parent)
        self.meta = meta
        self.setObjectName("EchoEnhanceWidget")
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
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
        #: 不用 ``EchoSettings.load()``。改动仍然存盘，任务流程读的就是存下来那份。
        #:
        #: ⚠ 本页**不碰**「角色声骸强化」那些配置（配置页里的第二类）——
        #: 用户 2026-09-26 明确："角色声骸强化类型配置与声骸自动强化工具的配置是无关的"。
        #: 那条种子（第一次升级时补一条「默认」）由配置页负责，本页不掺和。
        self._settings = EchoSettings()

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

        # ★ 设置区是**独立组件** —— 配置页里编辑「角色声骸强化」配置用的是同一份，
        #   两边界面永远一致（改一处两边都变）。见 settings_editor.py。
        self.editor = EchoSettingsEditor(view)
        self.editor.changed.connect(self._save_settings)
        layout.addWidget(self.editor)

        layout.addWidget(self._build_report_card(view))

        layout.addStretch(1)

        # 回填上次的选择 —— 界面上看到的值 = 任务流程会用的值，必须是同一份
        self.editor.set_settings(self._settings)

        self.setWidget(view)
        self.setWidgetResizable(True)

        # 状态靠轮询宿主（和 4C 工具页一致），页面不自己维护线程
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(300)
        self._poll()

    # ---------------------------------------------------------------- 配置卡片
    #: ⚠ 这里**故意没有**「用哪套配置」的选择器。
    #:   「角色声骸强化」那些配置（配置页里的第二类）和本页的设置是**两回事**
    #:   —— 用户 2026-09-26 明确："角色声骸强化类型配置与声骸自动强化工具的配置是无关的"。
    #:   曾经加过一条下拉 + "改动写回当前那套"，属于把两者绑在一起的错误设计，已拆掉。
    #:   将来要做"按配置跑"的话，应该是**显式选择并注入任务**，而不是让两者共享存储。






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








    # ---------------------------------------------------------------- 配置读写
    def _save_settings(self, *_) -> None:
        """配置一变就存盘 —— **任务流程运行时读的就是这一份**。

        设置控件本体在 :class:`~.settings_editor.EchoSettingsEditor` 里
        （那边改完发 ``changed`` 信号，这里接住落盘）。
        """
        self._settings = self.editor.settings()
        try:
            self._settings.save()
        except Exception as exc:  # noqa: BLE001 - 存不下来不该影响使用
            logger.warning("声骸强化设置存不下来：%s", exc)

    # ------------------------------------------------- 兼容：设置控件的直接访问
    # 检查脚本（check_echo_page_gui / check_settings_gui）会直接摸这些控件来断言，
    # 而它们现在住在 editor 里。转发一层，脚本不用改，改起来也只有这一处。
    @property
    def _core_boxes(self):
        return self.editor.core_boxes

    @property
    def _optional_boxes(self):
        return self.editor.optional_boxes

    @property
    def core_count_label(self):
        return self.editor.core_count_label

    @property
    def criterion_label(self):
        return self.editor.criterion_label

    @property
    def crit_field(self):
        return self.editor.crit_field

    @property
    def crit_dmg_field(self):
        return self.editor.crit_dmg_field

    @property
    def crit_switch(self):
        return self.editor.crit_switch

    @property
    def maxroll_switch(self):
        return self.editor.maxroll_switch

    @property
    def valid_stepper(self):
        return self.editor.valid_stepper

    def _checked_core(self) -> list:
        return self.editor.checked_core()

    def _checked_optional(self) -> list:
        return self.editor.checked_optional()

    def _update_core_count(self) -> None:
        self.editor._update_core_count()          # noqa: SLF001 - 见上面的说明

    def _update_optional_count(self, *_) -> None:
        self.editor._update_optional_count(*_)    # noqa: SLF001 - 见上面的说明

    def _sync_valid_count(self, *_, follow_core: bool = False) -> None:
        self.editor._sync_valid_count(follow_core=follow_core)  # noqa: SLF001

    def _apply_settings(self, settings: EchoSettings) -> None:
        self.editor.set_settings(settings)
        self._settings = self.editor.settings()

    def build_judge_config(self) -> JudgeConfig:
        """界面当前的值 → 判定配置（双爆由 JudgeConfig 强制进核心属性）。"""
        return self.editor.settings().to_judge_config()

    # ---------------------------------------------------------------- 日志
    def _append(self, text: str) -> None:
        """界面上不再显示日志区，运行日志走标准 logging
        （PyCharm 的运行/调试窗口里能看到；出错时另有 InfoBar 弹窗）。"""
        logger.info("[声骸强化] %s", text)

    # ---------------------------------------------------------------- 动作
    def _on_run(self) -> None:
        self._save_settings()          # 顺手存盘：任务流程跑的时候读的就是这一份
        settings = self.editor.settings()
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
        # set_settings 内部有自己的回填保护，不会把"正要写进去的值"当成用户改动
        self._apply_settings(EchoSettings())
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

    #: 「交给引擎后多久还没开始跑」的上限（秒）。
    #:
    #: ★ 2026-09-27 用户报「应用卡死」就是栽在这里。引擎把任务排进队列之后
    #: （ok 日志里的 ``queued onetime_task``），紧接着本该出现
    #: ``get queued onetime_task`` —— 那是 executor 线程真把它取走了。
    #: 那天 ``get queued`` 一直没出现：任务排了队，但引擎的 executor 线程没起来，
    #: 于是下面这个 while **永远转下去**，界面上永远「运行中」、停止也没用 ——
    #: 用户看到的就是"卡死"。
    #:
    #: 与其无限等，不如到点认账并说清楚。
    START_TIMEOUT = 60.0

    #: 心跳日志间隔（秒）：长任务期间让日志里能看到"还活着、在等什么"。
    HEARTBEAT = 10.0

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
        #: 引擎真的开始跑了吗（``task.running`` 变 True 过）。
        #: 用它区分"还在等引擎"和"已经在强化中"—— 后者再久也不该超时。
        started = False
        queued_at = time.monotonic()
        last_beat = queued_at
        try:
            while True:
                task = host.find_task(TASK_KEY)
                if task is not None:
                    info = getattr(task, "info", None)
                    if isinstance(info, dict) and info:
                        last_info = dict(info)
                    last_stats = _snapshot_task_stats(task)
                    if getattr(task, "running", False):
                        started = True
                host.poll_done()
                if self._should_stop():
                    host.stop_task()
                    self._log("声骸自动强化：已请求停止")
                    break
                if host.running_task != TASK_KEY and host.pending_start != TASK_KEY:
                    break

                now = time.monotonic()
                if not started and now - queued_at > self.START_TIMEOUT:
                    host.stop_task()
                    raise RuntimeError(
                        "已把任务交给 ok-ww 引擎，但 %.0f 秒过去它还没开始跑"
                        "（任务排在队列里，引擎的执行线程没把它取走）—— "
                        "本次没有真正强化任何声骸，已中止等待。"
                        "引擎侧日志见 data/okww/logs/ok-ww.log"
                        % self.START_TIMEOUT)
                if now - last_beat >= self.HEARTBEAT:
                    last_beat = now
                    self._log("… 等待引擎：已 %.0f 秒（%s）"
                              % (now - queued_at,
                                 "任务已在跑" if started else "任务还没被引擎取走"))
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

        ## ★ 判定条件从哪来（用户 2026-09-26）

        用户要求："**声骸自动工具会启用声骸强化配置的条件进行强化**"。

        * 编排里挂了「角色声骸强化配置」→ **用它的条件**（见 :meth:`_settings_for_run`）；
        * 没挂 → 退回工具页保存的那份（"从任务页跑"和"从工具页点运行"仍然一致）。
        """
        settings, source = self._settings_for_run(options, log)
        log(f"判定配置（{source}）：{settings.describe()}")
        return OkwwTaskRunner(settings.to_judge_config(), log=log, should_stop=should_stop)

    def _settings_for_run(self, options: dict, log):
        """本次运行用哪套判定条件 → ``(EchoSettings, 来源说明)``。

        **优先用编排里挂的「角色声骸强化配置」** —— 一条流程可以按角色不同挂不同条件
        （比如"绯雪这条严格、清宵那条宽松"）。找不到配置（被删了）就打一声、退回工具页那份。

        配置的 key 是 ``EchoProfile.id``（**稳定 id**，改名也不变）；
        兼容 09-26 之前存的、按角色名指的老流程（``by_id`` 找不到再按名字试）。
        """
        keys = list(options.get("config_keys") or [])
        kinds = list(options.get("config_kinds") or [])
        names = list(options.get("configs") or [])
        for index, key in enumerate(keys):
            kind = kinds[index] if index < len(kinds) else ""
            if kind != ECHO_PROFILE_KIND:
                continue
            profile = _find_echo_profile(key)
            if profile is None:
                shown = names[index] if index < len(names) else key
                log(f"⚠ 编排里挂的强化配置「{shown}」已经找不到了 —— 改用工具页保存的设置")
                continue
            try:
                return EchoSettings.from_dict(profile.settings), f"编排里挂的「{profile.name}」"
            except Exception:  # noqa: BLE001 - 配置坏了不该把任务带崩
                logger.warning("强化配置读不出来：%s", key, exc_info=True)
                log(f"⚠ 编排里挂的强化配置「{profile.name}」读不出来 —— 改用工具页保存的设置")
        return EchoSettings.load(), "工具页保存的设置"

    def create_task_prep(self, options: dict, log, should_stop):
        """「开始」步的准备动作（用户 2026-09-26 第 (1) 条）：

        > **可以按照声骸筛选配置，按 B 打开背包筛选指定的声骸**

        做三件事：

        1. 读**编排里挂的「角色声骸筛选配置」**（``Loadout``），把这次要筛的目标
           （套装 / 各档声骸）打进日志 —— 让用户看到"这次要筛什么"；
        2. **按 B 打开背包**（这一步是**已验证**的）；
        3. 剩下的「切声骸页签 / 开过滤器 / 筛未调谐 / 按等级排序」**还没校准**，
           默认**跳过不去点**（见 ``prepare.py`` 顶部：猜坐标可能触发分解、弃置这类
           破坏性操作），改为跑一次**探测**：把当前画面 + OCR 出来的每行文字/坐标
           落到 ``data/probe/``，拿那张图就能把待校准的步骤填成真的。
        """
        settings, source = self._settings_for_run(options, log)
        log(f"判定配置（{source}）：" + settings.describe())

        target = _bound_loadout(options)
        if target is not None:
            # ⚠ 别写成 f"{len(picks)}{cost}C" —— 拼出来是「14C」，看着像 14C 档
            want = "、".join(
                f"{cost}C×{len(picks)}" for cost, picks in _loadout_picks(target).items()
            )
            log(f"筛选目标（来自「{target.character}-声骸筛选」）："
                f"套装「{target.echo_set}」" + (f"；各档 {want}" if want else ""))
        else:
            # ⚠ 这句话必须说清楚**后果**和**怎么办**。
            #   用户 2026-09-27 报「没有按流程 筛选声骸→强化声骸，而是直接强化声骸」
            #   —— 就是这条：没挂配置 → 只按 B → 没筛 → 直接把界面交给 ok-ww。
            #   原来的文案「请自己筛好」太轻，看不出"工具根本不会筛"。
            log("⚠ 编排里没挂「角色声骸筛选配置」→ 本次**不会自动筛选**"
                "（只会按 B 打开背包）。ok-ww 会以「必须在背包声骸界面过滤后开始!」"
                "拒绝执行。要让工具自动筛，请在编排里挂上「角色声骸筛选配置」。")

        from .prepare import EchoPrep, build_filter_steps  # noqa: PLC0415

        # 挂了筛选配置 → 按它生成"切声骸页 / 开筛选 / 选状态·品质·合鸣 / 排序"那一串；
        # 没挂 → 用默认步骤（只按 B 开背包 + 未校准的跳过），不猜。
        steps = build_filter_steps(target) if target is not None else None
        if steps is not None:
            log(f"准备动作共 {len(steps)} 步（切页签 / 开筛选 / 选条件 / 关面板 / 排序）")
        return EchoPrep(log=log, should_stop=should_stop, steps=steps)
