"""资源库更新 —— 面板 + 后台线程。

流程对应需求：
    ① 工具启动（面板第一次显示）→ 后台线程自动拉远端、对比本地
    ② 有更新 → 界面提示 + 列出变更 + 「获取最新数据」按钮点亮
    ③ 用户点按钮 → 后台线程把更新写进本地 JSON → 提示重启生效

线程模型和声骸强化一样用 QThread：网络请求阻塞，绝不能在主线程跑。
数据逻辑全在 :mod:`src.core.wuwa_update`（core 层、无 Qt），这里只管界面。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import QHBoxLayout, QTextEdit, QVBoxLayout, QWidget
from qfluentwidgets import (
    CaptionLabel,
    InfoBar,
    PrimaryPushButton,
    PushButton,
    StrongBodyLabel,
    SubtitleLabel,
    TitleLabel,
)

from ...core.categories import ToolCategory
from ...core.registry import registry
from ...core.tool_base import BaseTool
from ...core.wuwa_update import (
    UpdateReport,
    apply_updates,
    check_updates,
    fetch_remote,
)


# --------------------------------------------------------------------- 线程

class CheckThread(QThread):
    """后台检查更新：拉远端 + 对比本地。"""

    message = Signal(str)
    succeeded = Signal(object)   # UpdateReport
    failed = Signal(str)

    def run(self) -> None:  # noqa: D102 - QThread 接口
        try:
            snapshot = fetch_remote(log=lambda msg: self.message.emit(msg))
            report = check_updates(snapshot)
        except Exception as exc:  # noqa: BLE001 - 异常必须带回主线程，否则界面无感
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        self.succeeded.emit(report)


class ApplyThread(QThread):
    """后台应用更新：写本地 JSON + 补新声骸的技能说明（逐页抓，慢）。"""

    message = Signal(str)
    succeeded = Signal(list)     # list[str]：做了什么
    failed = Signal(str)

    def __init__(self, snapshot, report: UpdateReport, parent=None):
        super().__init__(parent)
        self._snapshot = snapshot
        self._report = report

    def run(self) -> None:  # noqa: D102 - QThread 接口
        try:
            done = apply_updates(self._snapshot, self._report,
                                 log=lambda msg: self.message.emit(msg))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        self.succeeded.emit(done)


# --------------------------------------------------------------------- 面板

class WuwaLibraryUpdatePanel(QWidget):
    """状态行 + 变更摘要 + 两个按钮 + 日志区。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._snapshot = None
        self._report: UpdateReport | None = None
        self._check_thread: CheckThread | None = None
        self._apply_thread: ApplyThread | None = None
        self._auto_checked = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        root.addWidget(TitleLabel("资源库更新", self))
        note = CaptionLabel(
            "数据来源：bwiki（套装效果 / 声骸掉落池 / 技能说明）+ 库街区官方 wiki"
            "（声骸掉落池 / 图标）。检查只发 3~4 个轻量请求，不会写任何本地文件。",
            self,
        )
        note.setTextColor("#8A8F98", "#7C7C7C")
        note.setWordWrap(True)
        root.addWidget(note)

        # --- 状态卡 ---
        status_card = QWidget(self)
        status_layout = QVBoxLayout(status_card)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(6)

        title_row = QHBoxLayout()
        self._status_label = StrongBodyLabel("尚未检查", status_card)
        title_row.addWidget(self._status_label)
        title_row.addStretch(1)

        self._recheck_button = PushButton("重新检查", status_card)
        self._recheck_button.clicked.connect(self.start_check)
        title_row.addWidget(self._recheck_button)

        self._apply_button = PrimaryPushButton("获取最新数据", status_card)
        self._apply_button.setEnabled(False)
        self._apply_button.clicked.connect(self.start_apply)
        title_row.addWidget(self._apply_button)
        status_layout.addLayout(title_row)

        self._summary = QTextEdit(status_card)
        self._summary.setReadOnly(True)
        self._summary.setMinimumHeight(180)
        self._summary.setPlaceholderText(
            "打开本工具会自动在后台检查更新；发现更新后点「获取最新数据」应用。"
        )
        status_layout.addWidget(self._summary)
        root.addWidget(status_card, 1)

    # ---------------------------------------------------------------- 生命周期
    def showEvent(self, event):  # noqa: N802 - Qt 回调
        """面板第一次显示时自动检查（需求②：工具启动时后台自动拉取）。"""
        super().showEvent(event)
        if not self._auto_checked:
            self._auto_checked = True
            self.start_check()

    # ---------------------------------------------------------------- 动作
    def start_check(self) -> None:
        if self._check_thread is not None and self._check_thread.isRunning():
            return
        self._status_label.setText("正在检查更新…")
        self._summary.setPlainText("")
        self._apply_button.setEnabled(False)
        self._recheck_button.setEnabled(False)

        self._check_thread = CheckThread(self)
        self._check_thread.message.connect(self._append_log)
        self._check_thread.succeeded.connect(self._on_checked)
        self._check_thread.failed.connect(self._on_failed)
        self._check_thread.start()

    def start_apply(self) -> None:
        if self._report is None or not self._report.has_updates:
            return
        if self._apply_thread is not None and self._apply_thread.isRunning():
            return
        self._status_label.setText("正在获取最新数据…")
        self._apply_button.setEnabled(False)
        self._recheck_button.setEnabled(False)

        self._apply_thread = ApplyThread(self._snapshot, self._report, self)
        self._apply_thread.message.connect(self._append_log)
        self._apply_thread.succeeded.connect(self._on_applied)
        self._apply_thread.failed.connect(self._on_failed)
        self._apply_thread.start()

    # ---------------------------------------------------------------- 回调
    def _on_checked(self, report) -> None:
        self._report = report
        self._recheck_button.setEnabled(True)
        if report.remote_empty:
            # 远端没返回数据：这**不是**"已是最新"，是这次检查不成立
            self._status_label.setText("没能取到远端数据")
            self._summary.setPlainText(report.summary())
            self._apply_button.setEnabled(False)
        elif report.has_updates:
            self._status_label.setText("发现数据更新")
            self._summary.setPlainText(report.summary())
            self._apply_button.setEnabled(True)
        else:
            self._status_label.setText("数据已是最新")
            self._summary.setPlainText("远端数据和本地一致，无需更新。")

    def _on_applied(self, done: list) -> None:
        self._status_label.setText("更新完成")
        self._summary.setPlainText("\n".join(done))
        self._recheck_button.setEnabled(True)
        self._report = None
        self._notify("更新完成", "本地数据已写入并即时生效，打开资源库页即可看到。")

    def _on_failed(self, message: str) -> None:
        self._status_label.setText("检查 / 更新失败")
        self._summary.setPlainText(message)
        self._recheck_button.setEnabled(True)
        self._notify("失败了", message, error=True)

    def _append_log(self, message: str) -> None:
        self._summary.append(message)

    def _notify(self, title: str, message: str, error: bool = False) -> None:
        """右下角气泡通知。窗口还没显示出来时 InfoBar 发不出去，兜住。"""
        try:
            window = self.window()
            if error:
                InfoBar.error(title, message, duration=5000, parent=window)
            else:
                InfoBar.success(title, message, duration=5000, parent=window)
        except Exception:  # noqa: BLE001 - 通知发不出去不影响主流程
            pass


# --------------------------------------------------------------------- 注册

@registry.register(
    category=ToolCategory.DATA,
    name="资源库更新",
    icon_name="UPDATE",
    coming_soon=False,
)
class WuwaLibraryUpdateTool(BaseTool):
    key = "wuwa_library_update"
    name = "资源库更新"
    description = "自动检查鸣潮资源库数据更新，一键获取最新数据"

    def create_widget(self, parent=None):
        return WuwaLibraryUpdatePanel(parent)
