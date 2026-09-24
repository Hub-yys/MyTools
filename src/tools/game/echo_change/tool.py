"""声骸批量调频 —— 工具页。

页面只做三件事：选**目标属性** → 点「运行」 → 看报告。
流程本体和容错全在 :mod:`.okww_task` / ok-ww 那边；
引擎启停、托盘、后台运行、关闭确认都由共用宿主负责，**本页不用管**。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    CaptionLabel,
    ComboBox,
    FluentIcon,
    InfoBar,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    ScrollArea,
    StrongBodyLabel,
    ToolButton,
)

from ....core import paths, tool_settings
from ....core.categories import ToolCategory
from ....core.registry import registry
from ....core.tool_base import BaseTool
from ....gui.widgets import ConfigCard
from ..auto_combat.okww_boot import get_host
from . import DEFAULT_TARGET, SETTINGS_KEY, TARGET_STATS

#: 页面在引擎里的任务名（要和 ``okww_boot.TASKS`` 的键一致）
TASK_KEY = "声骸批量调频"

#: 说明文字颜色（(浅色主题, 深色主题)）—— 与其他页保持同一套灰
MUTED = ("#8A8F98", "#7C7C7C")

#: 数量框能设到多大。**这是输入框的上限**，不是"会调这么多" ——
#: 实际能调多少取决于过滤器里有多少个声骸，调完就自然结束。
MAX_COUNT = 999

#: 「目标属性」下拉的宽度。**固定住，别跟着窗口拉伸** ——
#: 属性名最长也就 8 个字，占满整行（实测 945px）又长又空。
TARGET_BOX_WIDTH = 320
#: 「数量」框的宽度（够放下 4 位数字 + 左减右加两个按钮）
COUNT_BOX_WIDTH = 160


class EchoChangeWidget(ScrollArea):
    """声骸批量调频面板：目标属性 + 运行/停止 + 结果报告 + 说明。"""

    POLL_MS = 300

    def __init__(self, meta, parent=None):
        super().__init__(parent)
        self._meta = meta
        self._host = get_host()
        self._settings = self._load_settings()

        self.setObjectName("echo_change_scroll")
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        page = QWidget(self)
        page.setObjectName("echo_change_page")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        layout.addWidget(self._build_run_card(page))
        layout.addWidget(self._build_report_card(page))
        layout.addWidget(self._build_note_card(page))
        layout.addStretch(1)
        self.setWidget(page)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(self.POLL_MS)
        self._poll()

    # ------------------------------------------------------------------ 存盘
    def _load_settings(self) -> dict:
        try:
            got = tool_settings.load(SETTINGS_KEY)
            return got if isinstance(got, dict) else {}
        except Exception:  # noqa: BLE001 - 存不出来不该挡住页面
            return {}

    def _save_settings(self, *_) -> None:
        try:
            tool_settings.save(SETTINGS_KEY, {
                "target_stat": self.target_box.currentText(),
                "max_count": self.count(),
            })
        except Exception as exc:  # noqa: BLE001
            self._append(f"设置存不下来：{exc}")

    # ------------------------------------------------------------ 数量控制
    def count(self) -> int:
        """当前数量；``0`` = 不限。

        容错都收在这儿：输入框空着 / 敲了空格 / 超出范围，一律夹回 0~MAX，
        别让它一路传到任务里再炸（那边也有一层 ``max(0, ...)``，两道保险）。
        """
        try:
            return max(0, min(MAX_COUNT, int(self.count_edit.text() or 0)))
        except (TypeError, ValueError):
            return 0

    def _step_count(self, delta: int) -> None:
        """数量 ±1 —— 左减号按钮传 ``-1``、右加号按钮传 ``+1``。

        ⚠ 夹边界的活必须在这做：`LineEdit` 自己不会拦，点几下就成负数了。
        """
        self.count_edit.setText(str(max(0, min(MAX_COUNT, self.count() + delta))))
        self._save_settings()

    # ------------------------------------------------------------------ 构建
    def _build_run_card(self, parent) -> ConfigCard:
        card = ConfigCard(
            "声骸批量调频",
            "把过滤器筛出的声骸，主属性批量改成下面选的那一个。"
            "流程由 ok-ww 引擎执行（后台按键，不抢前台）。",
            parent,
        )

        row = QHBoxLayout()
        row.setSpacing(12)
        label = CaptionLabel("目标属性", card)
        label.setTextColor(*MUTED)
        label.setFixedWidth(60)
        row.addWidget(label)

        self.target_box = ComboBox(card)
        self.target_box.addItems(list(TARGET_STATS))
        saved = str(self._settings.get("target_stat") or DEFAULT_TARGET)
        if saved not in TARGET_STATS:
            saved = DEFAULT_TARGET
        self.target_box.setCurrentText(saved)
        self.target_box.currentTextChanged.connect(self._save_settings)
        # ★ **变短**（用户 2026-09-27）：原来 stretch=1 占满整行，太长了。
        #   属性名最长也就 8 个字，320px 足够；给 0 让它别跟着窗口拉伸。
        self.target_box.setFixedWidth(TARGET_BOX_WIDTH)
        row.addWidget(self.target_box, 0)
        row.addStretch(1)
        card.body.addLayout(row)

        # ★ 数量控制**单独一行**（用户 2026-09-27："数量挪到下面去"）。
        #   左边 60px 的标签，右边是〔−〕〔数字〕〔+〕。
        count_row = QHBoxLayout()
        count_row.setSpacing(8)
        count_label = CaptionLabel("数量", card)
        count_label.setTextColor(*MUTED)
        count_label.setFixedWidth(60)
        count_row.addWidget(count_label)

        # ★ 数量 = 〔−〕〔数字〕〔+〕，**左减右加**。
        #   用户 2026-09-27 批注原文："左边-号按钮控制-1，右边+号按钮控制数量+1"。
        #   ⚠ **不能用 qfluentwidgets 的 `SpinBox`**：它自带的是**上下箭头**（^ v），
        #     和"左右加减"不是一回事（第一版就是拿它做的，截图里一眼看出不对）。
        #   所以这里自己拼：两个按钮夹一个只收数字的输入框。
        self.minus_button = ToolButton(FluentIcon.REMOVE, card)
        self.minus_button.setFixedSize(32, 32)
        self.minus_button.setToolTip("减 1")
        self.minus_button.clicked.connect(lambda: self._step_count(-1))
        count_row.addWidget(self.minus_button, 0)

        self.count_edit = LineEdit(card)
        self.count_edit.setFixedWidth(COUNT_BOX_WIDTH)
        self.count_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # 只收 0~MAX 的整数：别让用户敲进 "abc" 或负数
        self.count_edit.setValidator(QIntValidator(0, MAX_COUNT, self.count_edit))
        try:
            self.count_edit.setText(
                str(max(0, min(MAX_COUNT, int(self._settings.get("max_count") or 0)))))
        except (TypeError, ValueError):
            self.count_edit.setText("0")
        self.count_edit.setToolTip("最多成功调频多少个；0 = 不限")
        self.count_edit.editingFinished.connect(self._save_settings)
        count_row.addWidget(self.count_edit, 0)

        self.plus_button = ToolButton(FluentIcon.ADD, card)
        self.plus_button.setFixedSize(32, 32)
        self.plus_button.setToolTip("加 1")
        self.plus_button.clicked.connect(lambda: self._step_count(1))
        count_row.addWidget(self.plus_button, 0)

        count_row.addStretch(1)
        card.body.addLayout(count_row)

        hint = CaptionLabel(
            "数量最多**成功调频**多少个（点 −/+ 每次 1 个；填 0 = 不限）。"
            "已经是目标属性的声骸会被**跳过**（不会中断任务），跳过的**不计入**数量；"
            "但如果过滤器里一直有它，工具会停下来提醒你收紧过滤条件。",
            card,
        )
        hint.setTextColor(*MUTED)
        hint.setWordWrap(True)
        card.body.addWidget(hint)

        buttons = QHBoxLayout()
        buttons.setSpacing(12)
        self.run_button = PrimaryPushButton("运行", card)
        self.run_button.clicked.connect(self._on_run)
        self.stop_button = PushButton("停止", card)
        self.stop_button.clicked.connect(self._on_stop)
        buttons.addWidget(self.run_button, 1)
        buttons.addWidget(self.stop_button, 1)
        card.body.addLayout(buttons)

        self.state_label = CaptionLabel("引擎：后台加载中…", card)
        self.state_label.setTextColor("#C9514C", "#E6B4AC")
        card.add(self.state_label)
        return card

    def _build_report_card(self, parent) -> ConfigCard:
        card = ConfigCard("结果", "本次运行（点「运行」到「停止」）的统计", parent)

        row = QHBoxLayout()
        row.setSpacing(34)
        self.stats: dict[str, StrongBodyLabel] = {}
        for title in ("成功", "跳过", "失败"):
            cell = QVBoxLayout()
            cell.setSpacing(2)
            head = CaptionLabel(title, card)
            head.setTextColor(*MUTED)
            value = StrongBodyLabel("—", card)
            self.stats[title] = value
            cell.addWidget(head)
            cell.addWidget(value)
            row.addLayout(cell)
        row.addStretch(1)
        card.body.addLayout(row)

        self.report_line = CaptionLabel("还没跑过 —— 点「运行」后这里会刷新", card)
        self.report_line.setTextColor(*MUTED)
        self.report_line.setWordWrap(True)
        card.body.addWidget(self.report_line)

        self.log_line = CaptionLabel("", card)
        self.log_line.setTextColor(*MUTED)
        self.log_line.setWordWrap(True)
        card.body.addWidget(self.log_line)
        return card

    def _build_note_card(self, parent) -> ConfigCard:
        card = ConfigCard("前置条件（很关键）", None, parent)
        log_dir = paths.user_data_dir() / "okww" / "logs"
        notes = (
            "① **以管理员身份运行**本程序 —— 鸣潮带 ACE 反外挂，游戏跑在管理员权限下；"
            "低权限的话点击会被系统丢掉，而且不报错；\n"
            "② 游戏用**窗口模式**（无边框窗口最稳），独占全屏时截图不可靠；\n"
            "③ 自己先走到：**背包(B) → 声骸 → 用过滤器筛出要调频的 → 按等级升序排序**，"
            "停在这个列表界面上；\n"
            "④ 过滤器**别把目标属性包含进来** —— 否则筛出的第一个就是目标属性，"
            "工具会停下来提醒你；\n"
            "⑤ 运行日志按日期落盘：" + str(log_dir) + "（出问题把当天那个文件发过来即可）。"
        )
        label = CaptionLabel(notes, card)
        label.setWordWrap(True)
        card.add(label)
        return card

    # ------------------------------------------------------------------ 槽
    def _on_run(self) -> None:
        target = self.target_box.currentText()
        limit = self.count()

        def configure(task) -> None:
            # ★ 把页面上选的注入任务实例 —— 引擎跑的时候读的就是它
            task.config["目标属性"] = target
            # ★ 数量上限（0 = 不限）。任务侧读 `max_count`（见 okww_task）。
            task.config["数量上限"] = limit

        err = self._host.start_task(TASK_KEY, configure=configure)
        if err:
            self._append("启动失败：" + err)
            InfoBar.error("启动失败", err, duration=10000, parent=self.window())

    def _on_stop(self) -> None:
        err = self._host.stop_task()
        if err:
            InfoBar.warning("停止失败", err, duration=8000, parent=self.window())

    def _append(self, text: str) -> None:
        self.log_line.setText(text)

    # ------------------------------------------------------------------ 轮询
    def _poll(self) -> None:
        state = self._host.state
        running = self._host.running_task
        pending = self._host.pending_start
        err = self._host.boot_error

        if err and state == "error":
            self.state_label.setText(f"引擎：启动失败 —— {err}（点「运行」可重试）")
        elif state == "booting":
            self.state_label.setText(
                "引擎：正在后台启动 ok-ww…就绪后自动开始（首次加载 OCR 会慢一些）")
        elif state == "running":
            self.state_label.setText(f"引擎：运行中 —— {running}（点「停止」结束）")
        elif state == "ready":
            self.state_label.setText("引擎：就绪 · 点「运行」开始调频")
        else:
            self.state_label.setText("引擎：未启动 · 点「运行」会先加载引擎再开跑")

        self.run_button.setEnabled(not running)
        self.stop_button.setEnabled(bool(running) or bool(pending))
        self.target_box.setEnabled(not running)

        self._host.poll_done()
        self._refresh_report()

    def _refresh_report(self) -> None:
        """从宿主抄一份本次运行的统计（跑完那一刻是冻住的）。"""
        info = self._host.finished_info(TASK_KEY)
        if not info:
            task = self._host.find_task(TASK_KEY)
            info = getattr(task, "info", None) if task is not None else None
        if not isinstance(info, dict) or not info:
            return

        for key, title in (("成功声骸数量", "成功"), ("跳过声骸数量", "跳过"),
                           ("失败声骸数量", "失败")):
            value = info.get(key)
            self.stats[title].setText("—" if value is None else str(value))

        tally = info.get("调频统计")
        if tally:
            self.report_line.setText(str(tally))


@registry.register(
    category=ToolCategory.GAME,
    name="声骸批量调频",
    description="批量把声骸主属性改成指定属性（ok-ww 引擎，后台按键不抢前台）",
    icon_name="GAME",
    coming_soon=False,
)
class EchoChangeTool(BaseTool):
    key = "echo_change"
    name = "声骸批量调频"
    version = "0.1.0"

    def create_widget(self, parent=None):
        return EchoChangeWidget(self.meta(), parent)
