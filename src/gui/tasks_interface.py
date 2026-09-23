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

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    CaptionLabel,
    InfoBar,
    PrimaryPushButton,
    PushButton,
    ScrollArea,
    StrongBodyLabel,
    SubtitleLabel,
    TitleLabel,
)

from ..core.registry import ToolRegistry, logger
from ..core.task_start import TaskStartError, check_start
from ..core.tasks import STEP_START, TaskFlow, TaskStore
from .task_editor_dialog import TaskEditorDialog

PAGE_MARGIN = (36, 32, 36, 28)


class FlowRunThread(QThread):
    """按顺序跑一条流程。"""

    message = Signal(str)
    step_started = Signal(int, str)      # 步骤序号(0起), 描述
    succeeded = Signal(str)              # 汇总
    failed = Signal(str)

    def __init__(self, flow: TaskFlow, parent=None):
        super().__init__(parent)
        self._flow = flow
        self._stop = False

    def request_stop(self) -> None:
        self._stop = True

    def run(self) -> None:  # noqa: D102 - QThread 接口
        bindings = self._flow.tool_bindings()
        summaries: list[str] = []
        try:
            self._run_start_step(bindings)
            for index, binding in enumerate(bindings, 1):
                if self._stop:
                    break
                step = binding["step"]
                meta = ToolRegistry.get_meta(step.key)
                if meta is None:
                    self.message.emit(f"[{index}/{len(bindings)}] 工具「{step.name}」已不存在，跳过")
                    continue
                self.step_started.emit(index - 1, step.name)
                self.message.emit(f"[{index}/{len(bindings)}] 开始：{step.name}")

                tool = ToolRegistry.make(step.key)
                if tool is None:
                    self.message.emit(f"  工具「{step.name}」实例化失败，跳过")
                    continue
                runner = tool.create_task_runner(
                    {"configs": [c.name for c in binding["configs"]]},
                    log=lambda msg: self.message.emit(f"  {msg}"),
                    should_stop=lambda: self._stop,
                )
                if runner is None:
                    self.message.emit(f"  工具「{step.name}」不支持自动运行，跳过")
                    continue

                result = runner.run()
                summaries.append(f"{step.name}：{getattr(result, 'summary', lambda: '完成')()}")
        except TaskStartError as exc:
            # 「开始」步的前置检查没过。这条消息是**写给用户看的**，
            # 不加异常类名前缀，界面上直接弹出来。
            logger.warning("任务前置检查未通过: %s", exc)
            self.failed.emit(str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - 线程里抛异常必须带出来
            logger.exception("任务流程运行失败")
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        if self._stop:
            self.failed.emit("已停止" + ("；之前完成：" + "；".join(summaries) if summaries else ""))
            return
        if any(step.type == "end" for step in self._flow.steps):
            self.message.emit("✔ 流程结束")
        self.succeeded.emit("；".join(summaries) if summaries else "没有可运行的步骤")

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
        self.message.emit("▶ 流程开始")

        check_start(self._flow, self.message.emit)

        for binding in bindings:
            tool = ToolRegistry.make(binding["step"].key)
            if tool is None:
                continue
            prep = tool.create_task_prep(
                {"configs": [c.name for c in binding["configs"]]},
                log=self.message.emit,
                should_stop=lambda: self._stop,
            )
            if prep is None:
                continue
            result = prep.run()
            summary = getattr(result, "summary", None)
            if callable(summary):
                self.message.emit(summary())
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

        text_box = QWidget(card)
        col = QVBoxLayout(text_box)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(3)
        # 名字 + 任务类型标签同一行（类型是标签，放名字后面最省地方，也不占额外高度）
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)
        title_row.addWidget(StrongBodyLabel(flow.name or "（未命名）", text_box))
        type_text = flow.type_text()
        if type_text:
            type_tag = CaptionLabel(type_text, text_box)
            type_tag.setTextColor("#3B6EA5", "#6FB2F0")
            title_row.addWidget(type_tag, 0, Qt.AlignmentFlag.AlignVCenter)
        title_row.addStretch(1)
        col.addLayout(title_row)
        stamp = CaptionLabel(flow.summary(), text_box)
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

    # ------------------------------------------------------------ 操作
    def _thread_running(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def _show_detail(self) -> None:
        from qfluentwidgets import BodyLabel, MessageBoxBase, SubtitleLabel

        dialog = MessageBoxBase(self.window())
        dialog.widget.setFixedWidth(560)
        dialog.yesButton.setText("关闭")
        dialog.cancelButton.hide()
        dialog.viewLayout.addWidget(SubtitleLabel(f"任务详情：{self.flow.name}", dialog))
        dialog.viewLayout.addWidget(
            BodyLabel(f"任务类型：{self.flow.type_text() or '未分类'}", dialog)
        )
        if not self.flow.steps:
            dialog.viewLayout.addWidget(BodyLabel("（空流程）", dialog))
        for index, binding in enumerate(self.flow.tool_bindings(), 1):
            dialog.viewLayout.addWidget(BodyLabel(f"{index}. 工具：{binding['step'].name}", dialog))
            for config in binding["configs"]:
                dialog.viewLayout.addWidget(
                    BodyLabel(f"    └ 配置：{config.name}", dialog)
                )
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

    def _on_stopped_or_failed(self, message: str) -> None:
        self.status_label.setText(message[-60:] if message else "已停止")
        self._set_running(False)
        self._page.note_running(self, False)
        if message not in ("已停止",) and not message.startswith("已停止"):
            InfoBar.error("运行出错", message, duration=5000, parent=self.window())

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
