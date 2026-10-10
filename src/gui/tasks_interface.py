"""侧栏「任务」页：任务流程列表 + 运行控制。

界面自上而下：

    任务流程                      [＋ 新增任务流程]
    ┌────────────────────────────────────────────┐
    │ 名称            步骤摘要                    │
    │ [详情][修改][删除][运行/停止]                │
    └────────────────────────────────────────────┘

运行模型：一条流程一个 QThread，按顺序跑各步骤。工具步骤调工具的
``create_task_runner``（不支持的工具记一条跳过）；步骤之间可以停
（当前动作结束后退出）。同一时刻只允许跑一条流程 —— 强化要抢游戏窗口，
两条流程并行只会互相干扰。
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QThread, Signal
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    CaptionLabel,
    InfoBar,
    MessageBox,
    PrimaryPushButton,
    PushButton,
    ScrollArea,
    StrongBodyLabel,
    SubtitleLabel,
    TitleLabel,
)

from ..core import notifications as N
from ..core import notify
from ..core.registry import ToolRegistry, logger
from ..core.run_report import (
    RoundReport,
    RunReportStore,
    flow_result_from_summary,
)
from ..core.task_start import TaskStartError, check_start
from ..core.tasks import STEP_START, TaskFlow, TaskStore
from .config_names import live_config_name, live_flow_avatar, live_flow_summary
from .task_editor_dialog import TaskEditorDialog

PAGE_MARGIN = (36, 32, 36, 28)

#: 任务行上角色头像的边长 —— 和配置页那些行（48）保持一致，
#: 三处行看起来才是一套规矩。
AVATAR_SIZE = 48


def _now() -> str:
    """时间戳（报告里给人看的），和 ``core/tasks.py`` 用同一种格式。"""
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class FlowRunThread(QThread):
    """按顺序跑一条流程。"""

    message = Signal(str)
    step_started = Signal(int, str)      # 步骤序号(0起), 描述
    succeeded = Signal(str)              # 汇总
    failed = Signal(str)
    #: ★ 本轮报告（用户 2026-09-28 要求）—— 不管成功 / 失败 / 被停止，
    #: **每条出口都发一次**，界面才知道这一轮到底统计到多少。
    #: 参数是 :class:`~src.core.run_report.RoundReport`（对象，不是字符串）。
    report_ready = Signal(object)

    def __init__(self, flow: TaskFlow, parent=None):
        super().__init__(parent)
        self._flow = flow
        self._stop = False
        #: 本轮报告 —— 一路往里记，出口处统一发出去
        self.report = RoundReport(flow_name=flow.name or "",
                                  started_at=_now())

    def request_stop(self) -> None:
        self._stop = True

    def _finish(self, ok: bool, note: str = "") -> None:
        """收尾：盖时间戳、发本轮报告。**每条出口都要走它**（别再漏）。"""
        self.report.ok = ok
        self.report.note = note
        self.report.finished_at = _now()
        self.report_ready.emit(self.report)

    def run(self) -> None:  # noqa: D102 - QThread 接口
        bindings = self._flow.tool_bindings()
        summaries: list[str] = []
        try:
            blocked = self._permission_block()
            if blocked:
                # ⚠ 这里**必须**在跑任何准备动作之前拦下：
                #   权限不足时点击会被 UIPI **静默丢掉**（不报错），
                #   接着我的"点完验证"会失败，报出来是「坐标可能不对」——
                #   把真正的原因（没提权）盖掉了。工具页那条路早就查了（见
                #   okww_boot.start_task），任务流程这条路一直漏着。
                logger.warning("任务流程启动被拦下：%s", blocked)
                self._finish(False, blocked)
                self.failed.emit(blocked)
                return
            self._run_start_step(bindings)
            for index, binding in enumerate(bindings, 1):
                if self._stop:
                    break
                step = binding["step"]
                meta = ToolRegistry.get_meta(step.key)
                if meta is None:
                    self._emit(f"[{index}/{len(bindings)}] 工具「{step.name}」已不存在，跳过")
                    continue
                self.step_started.emit(index - 1, step.name)
                self._emit(f"[{index}/{len(bindings)}] 开始：{step.name}")

                tool = ToolRegistry.make(step.key)
                if tool is None:
                    self._emit(f"  工具「{step.name}」实例化失败，跳过")
                    self._report_step(step.name, ok=False, note="工具实例化失败")
                    continue
                runner = tool.create_task_runner(
                    {"configs": [live_config_name(c) for c in binding["configs"]],
                     "config_keys": [c.key for c in binding["configs"]],
                     # 工具靠它判断"挂的是不是我这类配置"（见 core 里的 KIND）
                     "config_kinds": [c.config_kind for c in binding["configs"]]},
                    log=lambda msg: self._emit(f"  {msg}"),
                    should_stop=lambda: self._stop,
                )
                if runner is None:
                    self._emit(f"  工具「{step.name}」不支持自动运行，跳过")
                    self._report_step(step.name, ok=False, note="不支持自动运行")
                    continue

                result = runner.run()
                summary = getattr(result, "summary", lambda: "完成")()
                summaries.append(f"{step.name}：{summary}")
                self._report_step(step.name, summary=summary)
        except TaskStartError as exc:
            # 「开始」步的前置检查没过。这条消息是**写给用户看的**，
            # 不加异常类名前缀，界面上直接弹出来。
            logger.warning("任务前置检查未通过: %s", exc)
            self._finish(False, str(exc))
            self.failed.emit(str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - 线程里抛异常必须带出来
            logger.exception("任务流程运行失败")
            text = f"{type(exc).__name__}: {exc}"
            self._finish(False, text)
            self.failed.emit(text)
            return
        if self._stop:
            note = "已停止" + ("；之前完成：" + "；".join(summaries) if summaries else "")
            self._finish(False, note)
            self.failed.emit(note)
            return
        if any(step.type == "end" for step in self._flow.steps):
            self._emit("✔ 流程结束")
        self._finish(True)
        self.succeeded.emit("；".join(summaries) if summaries else "没有可运行的步骤")

    def _report_step(self, name: str, summary: str = "",
                     ok: bool = True, note: str = "") -> None:
        """把一个工具步骤的结果记进本轮报告。

        ★ 锁定 / 弃置的数字从工具 ``.summary()`` 那行文本里读回来
        （见 :func:`~src.core.run_report.flow_result_from_summary`）——
        ``create_task_runner`` 的契约只给得到文本，这是唯一的取数路径。
        """
        self.report.items.append(
            flow_result_from_summary(name, summary, ok=ok, note=note))

    def _emit(self, text: str) -> None:
        """流程日志：**同时**发到界面和日志文件。

        ⚠ 以前只发界面 —— 用户在界面上看到的那句"某步骤失败"**不会进日志文件**，
        出问题只能靠截图口述，排查时手上什么证据都没有（2026-09-27 就卡在这儿）。
        准备动作那 18 步的逐条日志尤其重要：它记着"点到哪一步、期望看到什么"。
        """
        logger.info("[流程] %s", text)
        self.message.emit(text)

    def _permission_block(self) -> str | None:
        """本进程能不能把点击送进游戏？不能则返回给用户看的原因。

        只在**流程里确实有游戏类工具**时查 —— 纯数据流程（比如只跑资源库更新）
        不该因为"游戏开着但没提权"而被拦。

        连带保证：`input_permission_error()` 在"游戏没开"时返回 None，
        那种情况交给后面的「开始」步前置检查去报（那句更贴切）。
        """
        from ..tools.game.auto_combat.okww_boot import input_permission_error

        if self._flow.derived_type()[0] != "game":
            return None
        return input_permission_error()

    # ------------------------------------------------------------ 开始步
    def _run_start_step(self, bindings) -> None:
        """「开始」步真正做的事（以前它只是个视觉标记）。

        ① **前置检查**：任务类型是游戏 → 查客户端在不在跑，不在就抛
           TaskStartError（任务直接停）；非游戏类型跳过。
        ② **准备动作**：问每个工具步骤要不要先把环境摆好（比如强化工具要把
           游戏停到声骸列表），第一个声明了的执行掉 —— 准备一次就够。
        """
        if not any(step.type == STEP_START for step in self._flow.steps):
            return
        self._emit("▶ 流程开始")

        check_start(self._flow, self.message.emit)

        for binding in bindings:
            tool = ToolRegistry.make(binding["step"].key)
            if tool is None:
                continue
            prep = tool.create_task_prep(
                {"configs": [live_config_name(c) for c in binding["configs"]],
                     "config_keys": [c.key for c in binding["configs"]],
                     # 工具靠它判断"挂的是不是我这类配置"（见 core 里的 KIND）
                     "config_kinds": [c.config_kind for c in binding["configs"]]},
                # ⚠ 必须走 self._emit（不用 self.message.emit）：准备动作那 18 步
                #   的逐条日志是排查的主力证据，只发界面就进不了日志文件。
                log=self._emit,
                should_stop=lambda: self._stop,
            )
            if prep is None:
                continue
            result = prep.run()
            summary = getattr(result, "summary", None)
            if callable(summary):
                self._emit(summary())
            return


class TaskRowCard(QWidget):
    """一行任务流程：名字 + 摘要 + 操作按钮。"""

    def __init__(self, flow: TaskFlow, page: "TasksInterface", parent=None):
        super().__init__(parent)
        self.flow = flow
        self._page = page
        self._thread: FlowRunThread | None = None

        from qfluentwidgets import CardWidget

        card = CardWidget(self)
        row = QHBoxLayout(card)
        row.setContentsMargins(20, 14, 20, 14)
        row.setSpacing(10)

        # ★ 角色头像（2026-09-28 用户要求）—— 流程名 = 角色 + 后缀，
        #   所以拿名字剥掉后缀去查头像，和配置页两类配置的行是**同一条**查法。
        #   查不到就留空（不画占位图），见 config_names.live_flow_avatar。
        from .pickers import load_icon

        self.avatar_view = self._build_avatar(card, load_icon)
        row.addWidget(self.avatar_view, 0, Qt.AlignmentFlag.AlignVCenter)

        text_box = QWidget(card)
        col = QVBoxLayout(text_box)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(3)
        # ★ 「任务类型」这个标签**去掉了**（2026-09-27 用户："这个标签怎么还有啊，
        #   任务类型我已经删了"）。
        #   之前只删了**录入**（那个两级下拉），推导出来的类型还照旧显示在名字后面 ——
        #   用户看到的是"删了怎么还在"。
        #   ⚠ `TaskFlow.derived_type()` **方法保留**：它是**运行时逻辑**
        #     （「开始」步要不要检查游戏客户端、任务流程要不要查权限），不是给人看的。
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)
        title_row.addWidget(StrongBodyLabel(flow.name or "（未命名）", text_box))
        title_row.addStretch(1)
        col.addLayout(title_row)
        # ⚠ 摘要走 live_flow_summary：配置那几步用**当前**名字。
        #   用 flow.summary() 的话配置一改名，这里永远是旧名字。
        stamp = CaptionLabel(live_flow_summary(flow), text_box)
        stamp.setTextColor("#8A8F98", "#7C7C7C")
        stamp.setWordWrap(True)
        col.addWidget(stamp)
        self.status_label = CaptionLabel("空闲", text_box)
        self.status_label.setTextColor("#8A8F98", "#7C7C7C")
        col.addWidget(self.status_label)
        row.addWidget(text_box, 1)

        self.detail_button = PushButton("详情", card)
        self.detail_button.clicked.connect(self._show_detail)
        row.addWidget(self.detail_button)

        self.edit_button = PushButton("修改", card)
        self.edit_button.clicked.connect(self._edit)
        row.addWidget(self.edit_button)

        self.delete_button = PushButton("删除", card)
        self.delete_button.clicked.connect(self._delete)
        row.addWidget(self.delete_button)

        self.run_button = PrimaryPushButton("运行", card)
        self.run_button.clicked.connect(self._run)
        row.addWidget(self.run_button)

        self.stop_button = PushButton("停止", card)
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self._stop)
        row.addWidget(self.stop_button)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(card)

    # ------------------------------------------------------------ 头像
    def _build_avatar(self, parent: QWidget, load_icon) -> QWidget:
        """行首的角色头像 —— 大小和配置页那些行保持一致（48px）。

        ⚠ 查不到头像时**占一个等大的空位**（而不是不建控件）：否则有头像和
        没头像的行左边缘对不齐，整列名字参差不齐。和
        ``EchoProfileRow._build_identity`` 同一个做法。
        """
        from PySide6.QtWidgets import QLabel

        from qfluentwidgets import IconWidget

        box = QWidget(parent)
        box.setFixedSize(QSize(AVATAR_SIZE, AVATAR_SIZE))

        icon = None
        path = live_flow_avatar(self.flow)
        if path:
            try:
                candidate = load_icon(path)
                if candidate is not None and not candidate.isNull():
                    icon = candidate
            except Exception:  # noqa: BLE001 - 图标坏了不该让行建不出来
                icon = None

        if icon is not None:
            view = IconWidget(icon, box)
            view.setFixedSize(QSize(AVATAR_SIZE, AVATAR_SIZE))
            view.setParent(box)
            view.move(0, 0)
        else:
            # 空位：撑住宽度，保持左右对齐（不画占位图）
            QLabel(box).setFixedSize(QSize(AVATAR_SIZE, AVATAR_SIZE))
        return box

    # ------------------------------------------------------------ 操作
    def _thread_running(self) -> bool:
        return self._thread is not None and self._thread.isRunning()
    def _show_detail(self) -> None:
        """任务详情 —— **显示这条任务的流程图**（用户 2026-09-26）。

        流程图直接复用编排区那套瓦片 + 箭头（``FlowPreview``），
        所以"详情里看到的"和"点「修改」进去看到的"是同一个样子。

        ⚠ 以前这里是几行纯文字（`1. 工具：…  └ 配置：…`）——
        用户要的是**图**，不是文字清单。
        后来我还在图下面加过一段"工具 ← 它挂的配置"的文字，**去掉了**：
        ``tool_bindings()`` 会丢掉"前面没有工具"的悬空配置，于是那段文字
        会把流程里明明有的配置**藏起来**（用户那条流程正是 配置→配置→工具），
        看着像配置凭空没了。图里按顺序列了每一步，信息已经足够。
        """
        from qfluentwidgets import BodyLabel, MessageBoxBase, SubtitleLabel

        from .task_editor_dialog import FlowPreview, preview_width_for

        dialog = MessageBoxBase(self.window())
        # 宽度跟着步骤数走 —— 步骤多的时候才横向滚，别一上来就把最后一项切掉
        dialog.widget.setFixedWidth(preview_width_for(len(self.flow.steps)))
        dialog.yesButton.setText("关闭")
        dialog.cancelButton.hide()
        dialog.viewLayout.addWidget(SubtitleLabel(f"任务详情：{self.flow.name}", dialog))
        # ★ 「任务类型：…」那行也去掉了（2026-09-27）。
        #   用户已经把这个概念删了，列表行和详情里都不该再冒出来 ——
        #   只删录入、留下显示，用户看到的还是"删了怎么还在"。
        dialog.viewLayout.addWidget(FlowPreview(self.flow, dialog))
        dialog.exec()

    def _edit(self) -> None:
        self._page.edit_flow(self.flow)

    def _delete(self) -> None:
        if self._thread is not None and self._thread.isRunning():
            InfoBar.warning("正在运行", "先停止再删除这条流程。", duration=3000, parent=self.window())
            return
        self._page.delete_flow(self.flow)

    def _run(self) -> None:
        if self._thread is not None and self._thread.isRunning():
            return
        if self._page.has_running_flow():
            InfoBar.warning("已有流程在跑", "同一时刻只能运行一条流程（会抢游戏窗口）。", duration=4000, parent=self.window())
            return
        self._thread = FlowRunThread(self.flow, self)
        self._thread.message.connect(lambda msg: self.status_label.setText(msg[-60:]))
        self._thread.succeeded.connect(self._on_finished)
        self._thread.failed.connect(self._on_stopped_or_failed)
        # ★ 本轮报告：每条出口都会发一次（成功 / 失败 / 停止），页面负责展示 + 累计
        self._thread.report_ready.connect(self._page.note_report)
        self._set_running(True)
        self._page.note_running(self, True)
        self._thread.start()

    def _stop(self) -> None:
        if self._thread is not None:
            self._thread.request_stop()
            self.status_label.setText(">>> 已请求停止，等当前动作结束…")

    def _on_finished(self, summary: str) -> None:
        self.status_label.setText("完成")
        self._set_running(False)
        self._page.note_running(self, False)
        InfoBar.success("任务完成", summary, duration=5000, parent=self.window())
        #: ★ 记一条消息（用户 2026-10-10："每个任务完成/失败都要进行通知"）
        notify.report_task_result(self.flow.name or "任务", ok=True,
                                  detail=summary)

    def _on_stopped_or_failed(self, message: str) -> None:
        self.status_label.setText(message[-60:] if message else "已停止")
        self._set_running(False)
        self._page.note_running(self, False)
        #: ★ 「已停止」是**用户自己按的**，不是失败 —— 单独记成一种，
        #: 别在消息列表里报"失败"吓人（用户会以为出了故障）。
        #: 这跟 okww_boot 里「自动暂停」的处理是同一个口径。
        stopped = not message or message.startswith("已停止")
        if not stopped:
            InfoBar.error("运行出错", message, duration=5000, parent=self.window())
        name = self.flow.name or "任务"
        if stopped:
            notify.report(f"{name} · 已停止",
                          (message or "").strip() or "已停止（用户主动停止）",
                          level=N.LEVEL_INFO)
        else:
            notify.report_task_result(name, ok=False, detail=message)

    def _set_running(self, running: bool) -> None:
        self.run_button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        self.edit_button.setEnabled(not running)
        self.delete_button.setEnabled(not running)


class TasksInterface(ScrollArea):
    """侧栏「任务」页。"""

    def __init__(self, parent: QWidget | None = None, store: TaskStore | None = None):
        super().__init__(parent)
        self.setObjectName("TasksInterface")
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        #: 注入点：测试可以传临时目录的 store
        self._store = store
        #: 累计统计的存储（懒建 —— 测试可以换成临时目录）
        self._report_store: RunReportStore | None = None
        #: 本轮报告（内存里，跑完一轮就换掉）
        self._last_report: RoundReport | None = None

        view = QWidget(self)
        view.setObjectName("tasksView")
        layout = QVBoxLayout(view)
        layout.setContentsMargins(*PAGE_MARGIN)
        layout.setSpacing(12)

        header = QWidget(view)
        header_row = QHBoxLayout(header)
        header_row.setContentsMargins(0, 0, 0, 0)
        title_box = QVBoxLayout()
        title_box.addWidget(TitleLabel("任务流程"))
        note = CaptionLabel(
            "把工具和配置编成一条流程，按顺序自动跑。点「新增任务流程」拖拽编排。", header
        )
        note.setTextColor("#8A8F98", "#7C7C7C")
        note.setWordWrap(True)
        title_box.addWidget(note)
        header_row.addLayout(title_box, 1)

        self.add_button = PrimaryPushButton("＋ 新增任务流程", header)
        self.add_button.clicked.connect(self._add_flow)
        header_row.addWidget(self.add_button, 0, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(header)

        self.rows_host = QWidget(view)
        self.rows_layout = QVBoxLayout(self.rows_host)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(10)
        layout.addWidget(self.rows_host)
        layout.addStretch(1)

        # ★ 运行报告（用户 2026-09-28 要求）—— 上图红框那块区域。
        #   两块：「本轮报告」= 刚跑完这一轮每条流程的锁定/弃置；
        #        「累计统计」= 所有任务所有轮次加起来的总数（持久化）。
        layout.addWidget(self._build_report_section(view))

        # ⚠ 必须把内层 view 交给滚动区托管（跟 HomeInterface / ConfigInterface 一样）。
        #   只写 QWidget(self) 而不 setWidget，它就只是个"浮在滚动区上的裸控件"：
        #   尺寸不受滚动区布局管理，整页会被压扁 —— 标题和说明文字叠在一起、
        #   卡片里的文字挤成一根根横条（用户截图报的就是这个）。
        self.setWidget(view)
        self.setWidgetResizable(True)

        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("#TasksInterface { background: transparent; }")
        self.viewport().setStyleSheet("background: transparent;")

        self.reload()
        self._refresh_report()

    # ------------------------------------------------------------ 运行报告
    def _build_report_section(self, parent: QWidget) -> QWidget:
        """「本轮报告」+「所有任务累计统计」两块卡片。

        统计口径（用户已确认）：**锁定 = 引擎的成功声骸数量，
        弃置 = 引擎的失败声骸数量** —— 直接用引擎跑出来的真结果，不自己重算。
        """
        from qfluentwidgets import BodyLabel, CardWidget, StrongBodyLabel

        holder = QWidget(parent)
        box = QVBoxLayout(holder)
        box.setContentsMargins(0, 8, 0, 0)
        box.setSpacing(10)

        box.addWidget(StrongBodyLabel("运行报告", holder))

        # ---- 本轮报告 ----
        self.round_card = CardWidget(holder)
        round_box = QVBoxLayout(self.round_card)
        round_box.setContentsMargins(20, 14, 20, 14)
        round_box.setSpacing(6)
        round_box.addWidget(StrongBodyLabel("本轮报告", self.round_card))
        self.round_body = BodyLabel("", self.round_card)
        self.round_body.setWordWrap(True)
        round_box.addWidget(self.round_body)
        box.addWidget(self.round_card)

        # ---- 累计统计 ----
        self.total_card = CardWidget(holder)
        total_box = QVBoxLayout(self.total_card)
        total_box.setContentsMargins(20, 14, 20, 14)
        total_box.setSpacing(6)
        total_title_row = QHBoxLayout()
        total_title_row.setContentsMargins(0, 0, 0, 0)
        total_title_row.addWidget(StrongBodyLabel("所有任务累计", self.total_card))
        total_title_row.addStretch(1)
        self.reset_button = PushButton("清零", self.total_card)
        self.reset_button.setFixedWidth(72)
        self.reset_button.setToolTip("把所有任务的累计统计归零（本轮报告不受影响）")
        self.reset_button.clicked.connect(self._reset_total)
        total_title_row.addWidget(self.reset_button)
        total_box.addLayout(total_title_row)
        self.total_body = BodyLabel("", self.total_card)
        self.total_body.setWordWrap(True)
        total_box.addWidget(self.total_body)
        box.addWidget(self.total_card)

        return holder

    def _get_report_store(self) -> RunReportStore:
        if self._report_store is None:
            self._report_store = RunReportStore()
        return self._report_store

    def _refresh_report(self) -> None:
        """按当前内存里的本轮报告 + 磁盘上的累计统计重画两块卡片。"""
        # ---- 本轮 ----
        report = self._last_report
        if report is None or report.is_empty():
            self.round_body.setText("还没有跑过。点某条流程的「运行」后，这里显示本轮结果。")
        else:
            head = f"{report.flow_name or '（未命名）'}：{report.summary()}"
            details = report.lines()
            text = head + ("\n" + "\n".join(details) if details else "")
            if not report.ok and report.note:
                text += f"\n（{report.note}）"
            self.round_body.setText(text)

        # ---- 累计（每次从盘上读，别缓存 —— 别的入口也可能改它）----
        stats = self._get_report_store().load()
        if stats.rounds <= 0 and stats.locked == 0 and stats.dropped == 0:
            self.total_body.setText("还没有累计数据。")
        else:
            text = f"{stats.summary()} · 共 {stats.rounds} 轮"
            if stats.updated_at:
                text += f" · 最后一次 {stats.updated_at}"
            self.total_body.setText(text)

    def note_report(self, report: RoundReport) -> None:
        """一轮跑完：记下本轮、累加进持久化的总数、刷新显示。

        ⚠ 只统计**真有强化结果**的那一轮 —— 被"没提权 / 前置检查没过"拦下的
        那一轮 ``items`` 是空的，累加它只会在总数里多记一轮 ``rounds``，
        数字却一动不动（用户会以为统计坏了）。空轮次只更新"本轮报告"。
        """
        self._last_report = report
        if not report.is_empty():
            self._get_report_store().add_round(report)
        self._refresh_report()

    def _reset_total(self) -> None:
        """把所有任务的累计统计清零（用户要求能重置）。"""
        box = MessageBox("清零累计统计",
                         "把所有任务的累计锁定 / 弃置数量归零？"
                         "这一步不可撤销。", self.window())
        box.yesButton.setText("清零")
        box.cancelButton.setText("取消")
        if box.exec():
            self._get_report_store().reset()
            self._refresh_report()

    # ------------------------------------------------------------ 数据
    def _get_store(self) -> TaskStore:
        if self._store is None:
            self._store = TaskStore()
        return self._store

    def reload(self) -> None:
        """清掉行，按 store 重建。"""
        while self.rows_layout.count():
            item = self.rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        flows = self._get_store().all()
        if not flows:
            empty = CaptionLabel(
                "还没有任务流程。点右上角「＋ 新增任务流程」创建一条。", self.rows_host
            )
            empty.setTextColor("#8A8F98", "#7C7C7C")
            self.rows_layout.addWidget(empty)
            return
        for flow in flows:
            self.rows_layout.addWidget(TaskRowCard(flow, self, self.rows_host))

    # ------------------------------------------------------------ 运行互斥
    def has_running_flow(self) -> bool:
        for index in range(self.rows_layout.count()):
            widget = self.rows_layout.itemAt(index).widget()
            if isinstance(widget, TaskRowCard) and widget._thread is not None and widget._thread.isRunning():
                return True
        return False

    def note_running(self, card: TaskRowCard, running: bool) -> None:
        """某条流程开始/结束运行：其它行的运行按钮跟着禁用/解禁。"""
        for index in range(self.rows_layout.count()):
            widget = self.rows_layout.itemAt(index).widget()
            if isinstance(widget, TaskRowCard) and widget is not card:
                widget.run_button.setEnabled(not running and not widget._thread_running())

    # ------------------------------------------------------------ 增删改
    def _add_flow(self) -> None:
        dialog = TaskEditorDialog(self.window(), store=self._get_store())
        if dialog.exec():
            flow = dialog.result_flow()
            self._get_store().add(flow)
            self.reload()

    def edit_flow(self, flow: TaskFlow) -> None:
        dialog = TaskEditorDialog(self.window(), flow=flow, store=self._get_store())
        if dialog.exec():
            updated = dialog.result_flow()
            updated.id = flow.id
            self._get_store().update(updated)
            self.reload()

    def delete_flow(self, flow: TaskFlow) -> None:
        self._get_store().remove(flow.id)
        self.reload()
