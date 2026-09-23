"""4C 自动战斗 —— ok-ww 引擎宿主面板。

**战斗本体全部来自 ok-ww**（``vendor/okww``，AGPL-3.0，见 README「开源许可」）：
MyTools 只负责把它的运行时（ok-script）以无 GUI 方式跑起来。模板匹配 / OCR /
后台按键（PostMessage）都走 ok-ww 自己的体系，**不经过** MyTools 的
``GameWindow``/``EchoController``。

页面**只保留「启动 / 停止」两个按钮**。打开本页**不会**加载引擎；
点「启动」才在后台 boot ok-ww，就绪后自动开 4C 刷声骸任务（``FarmEchoTask``）。
「停止」= 停掉当前任务（或取消尚未执行的排队启动）。
日志不进界面：ok-ww 按日期写到 ``%LOCALAPPDATA%\\MyTools\\okww\\logs\\``
（每天一个文件），宿主每次启动引擎时自动清理超过 31 天的旧日志。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    CaptionLabel,
    FluentIcon,
    InfoBar,
    PrimaryPushButton,
    PushButton,
    ScrollArea,
)

from ....core.categories import ToolCategory
from ....core import paths
from ....core.registry import registry
from ....core.tool_base import BaseTool
from ....gui.widgets import ConfigCard
from .okww_boot import DEFAULT_TASK_KEY, get_host


class AutoCombatWidget(ScrollArea):
    """ok-ww 宿主面板：启动 / 停止 + 状态。"""

    POLL_MS = 300

    def __init__(self, meta, parent=None):
        super().__init__(parent)
        self._meta = meta
        self._host = get_host()

        self.setObjectName("auto_combat_scroll")
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        page = QWidget(self)
        page.setObjectName("auto_combat_page")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        # ---------------------------------------------------------- 运行卡
        run_card = ConfigCard("4C 自动战斗",
                              "战斗本体是 ok-ww 引擎（AGPL-3.0）：模板匹配 + OCR + 后台按键；"
                              "点「启动」才会在后台加载引擎并开跑", page)
        row = QHBoxLayout()
        row.setSpacing(12)
        self.start_btn = PrimaryPushButton("启动", run_card)
        self.start_btn.clicked.connect(self._on_start)
        self.stop_btn = PushButton("停止", run_card)
        self.stop_btn.clicked.connect(self._on_stop)
        row.addWidget(self.start_btn, 1)
        row.addWidget(self.stop_btn, 1)
        run_card.body.addLayout(row)

        self.state_label = CaptionLabel("引擎：未启动 · 点「启动」在后台加载 ok-ww 并开跑", run_card)
        self.state_label.setTextColor("#C9514C", "#E6B4AC")
        run_card.add(self.state_label)
        layout.addWidget(run_card)

        # ---------------------------------------------------------- 说明卡
        note_card = ConfigCard("使用说明", None, page)
        notes = (
            "① 点「启动」= 后台加载 ok-ww 引擎 → 就绪后自动跑「4C 刷声骸」"
            "（打 Boss → 拾取 → 重开循环）；\n"
            "② 鸣潮需以窗口模式运行（不支持独占全屏），推荐 16:9 分辨率；\n"
            "③ 按键走 PostMessage 后台消息，游戏不必切到前台；\n"
            "④ 运行日志在后台按日期落盘：%LOCALAPPDATA%\\MyTools\\okww\\logs\\"
            "（每天一个文件，超过 31 天自动清理）；出问题把这个目录里当天的文件发过来即可；\n"
            "⑤ 分发 MyTools 安装包时需按 AGPL-3.0 一并提供源码（见 README「开源许可」）。"
        )
        note_card.add(CaptionLabel(notes, note_card))
        layout.addWidget(note_card)

        layout.addStretch(1)
        self.setWidget(page)

        # ⚠ 打开本页**不** boot 引擎：只有点「启动」才加载（见 _on_start）
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(self.POLL_MS)
        self._poll()

    # ------------------------------------------------------------------ 槽
    def _on_start(self) -> None:
        # 引擎未就绪 / 失败态 / 就绪：统一走 start_task —— 内部会 boot 或直接开任务，
        # 引擎就绪后自动 flush 排队任务。
        err = self._host.start_task(DEFAULT_TASK_KEY)
        if err:
            InfoBar.error("启动失败", err, duration=8000, parent=self)

    def _on_stop(self) -> None:
        err = self._host.stop_task()
        if err:
            InfoBar.warning("停止失败", err, duration=8000, parent=self)

    # ------------------------------------------------------------------ 轮询
    def _poll(self) -> None:
        state = self._host.state
        running = self._host.running_task
        pending = self._host.pending_start
        err = self._host.boot_error

        if err and state == "error":
            self.state_label.setText("引擎：启动失败 —— %s（点「启动」可重试）" % err)
        elif state == "booting":
            if pending:
                self.state_label.setText(
                    "引擎：正在后台启动 ok-ww…就绪后自动开始「%s」（首次加载 OCR 会慢一些）"
                    % pending)
            else:
                self.state_label.setText(
                    "引擎：正在后台启动 ok-ww 运行时…（首次加载 OCR 模型会慢一些）")
        elif state == "running":
            self.state_label.setText("引擎：运行中 —— %s（点「停止」结束）" % running)
        elif state == "ready":
            self.state_label.setText("引擎：就绪 · 点「启动」开始 4C 刷声骸")
        else:
            self.state_label.setText("引擎：未启动 · 点「启动」会在后台加载 ok-ww 引擎")

        # 启动：空闲 / 就绪 / 失败重试 / 启动中（可改排队）；运行中禁用
        self.start_btn.setEnabled(not running)
        self.stop_btn.setEnabled(bool(running) or bool(pending))

        # 一次性任务跑完把状态拉回 ready
        self._host.poll_done()


@registry.register(
    category=ToolCategory.GAME,
    name="4C 自动战斗",
    description="ok-ww 引擎（AGPL-3.0）：4C 声骸刷取，后台按键不抢前台",
    icon_name="GAME",
    coming_soon=False,
)
class AutoCombatTool(BaseTool):
    key = "auto_combat"
    name = "4C 自动战斗"
    version = "0.3.1"
    icon_path = str(paths.resource_dir("assets", "icons", "auto_combat.png"))

    def create_widget(self, parent=None):
        return AutoCombatWidget(self.meta(), parent)
