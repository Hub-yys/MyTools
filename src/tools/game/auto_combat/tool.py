"""4C 自动战斗 —— ok-ww 引擎宿主面板。

**战斗本体全部来自 ok-ww**（``vendor/okww``，AGPL-3.0，见 README「开源许可」）：
MyTools 只负责把它的运行时（ok-script）以无 GUI 方式跑起来。模板匹配 / OCR /
后台按键（PostMessage）都走 ok-ww 自己的体系，**不经过** MyTools 的
``GameWindow``/``EchoController``。

页面**只保留「启动 / 停止」两个按钮**。**引擎在程序启动时就默认拉起来了**
（``okww_boot.autostart_engine``，见 ``main.py``）：本页点「启动」只是开跑
4C 刷声骸任务（``FarmEchoTask``）；引擎万一没起来，这里会兜底再 boot 一次。
「停止」= 停掉当前任务（或取消尚未执行的排队启动）。
日志不进界面：ok-ww 按日期写到 ``%LOCALAPPDATA%\\WutheringWavesTools\\okww\\logs\\``
（每天一个文件），宿主每次启动引擎时自动清理超过 31 天的旧日志。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget
from qfluentwidgets import (
    CaptionLabel,
    FluentIcon,
    IconWidget,
    InfoBar,
    PrimaryPushButton,
    PushButton,
    ScrollArea,
    StrongBodyLabel,
)

from ....core.categories import ToolCategory
from ....core import paths
from ....core.registry import registry
from ....core.tool_base import BaseTool
from ....gui.library_interface import circular_icon
from ....gui.pickers import load_icon
from ....gui.widgets import ConfigCard
from .okww_boot import DEFAULT_TASK_KEY, get_host


#: 说明文字颜色（(浅色主题, 深色主题)）—— 与资源库页保持同一套灰
MUTED = ("#8A8F98", "#7C7C7C")


def _clear_layout(layout) -> None:
    """清空一个 layout 里的控件（报告刷新时用）。子 layout 也递归清。"""
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()
        elif item.layout() is not None:
            _clear_layout(item.layout())


class TeamMemberChip(QWidget):
    """一个队员：圆形头像 + 名字。头像取不到就画个占位圆，不留空洞。"""

    AVATAR_SIZE = 34

    def __init__(self, member, parent=None):
        super().__init__(parent)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(2)

        icon = circular_icon(member.avatar, self.AVATAR_SIZE) if member.avatar else QIcon()
        if icon.isNull():
            placeholder = QLabel("？", self)
            placeholder.setFixedSize(self.AVATAR_SIZE, self.AVATAR_SIZE)
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            placeholder.setStyleSheet(
                "color: #8A8F98; background: rgba(128,128,128,0.16); border-radius: %dpx;"
                % (self.AVATAR_SIZE // 2))
            box.addWidget(placeholder, 0, Qt.AlignmentFlag.AlignHCenter)
        else:
            view = IconWidget(icon, self)
            view.setFixedSize(self.AVATAR_SIZE, self.AVATAR_SIZE)
            box.addWidget(view, 0, Qt.AlignmentFlag.AlignHCenter)

        name = CaptionLabel(member.name, self)
        name.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        name.setTextColor("#3D4148", "#C6CBD3")
        box.addWidget(name)


class BattleReportCard(ConfigCard):
    """4C 自动战斗的「战斗报告」。

    五项：使用队伍 / 战斗声骸 / 战斗次数 / 声骸数量 / 时长。

    ★ 这些数字**不是 MyTools 统计的** —— 全部来自 ok-ww 自己的计数器
    （``info['Combat Count']`` / ``info['Echo Count']`` / ``task.chars`` /
    ``task.aim_boss``，见 :mod:`.report` 的模块文档），这里只负责画出来。

    ⚠ 本卡每 300ms 被刷一次：**只在内容变化时才重建控件**，否则头像会一直闪。
    """

    ECHO_ICON_SIZE = 34

    def __init__(self, parent=None):
        super().__init__("战斗报告", "本次运行（点「启动」到「停止」）的统计", parent)

        self._team_key: tuple[str, ...] | None = None
        self._echo_key: str | None = None

        self.team_area = QHBoxLayout()
        self.team_area.setSpacing(12)
        self.body.addLayout(self._labeled_row("使用队伍", self.team_area))

        self.echo_area = QHBoxLayout()
        self.echo_area.setSpacing(10)
        self.body.addLayout(self._labeled_row("战斗声骸", self.echo_area))

        self.stats: dict[str, StrongBodyLabel] = {}
        stats_row = QHBoxLayout()
        stats_row.setSpacing(34)
        for title in ("战斗次数", "声骸数量", "锁定声骸", "时长"):
            cell = QVBoxLayout()
            cell.setSpacing(2)
            head = CaptionLabel(title, self)
            head.setTextColor(*MUTED)
            value = StrongBodyLabel("—", self)
            self.stats[title] = value
            cell.addWidget(head)
            cell.addWidget(value)
            stats_row.addLayout(cell)
        stats_row.addStretch(1)
        self.body.addLayout(stats_row)

        self.hint = CaptionLabel("还没跑过 —— 点「启动」后这里会边跑边刷新", self)
        self.hint.setTextColor(*MUTED)
        self.body.addWidget(self.hint)

        #: 拾取分类的诊断行（锁定/弃置/都没）—— 只在有数据时出现
        self.pickup_hint = CaptionLabel("", self)
        self.pickup_hint.setTextColor(*MUTED)
        self.body.addWidget(self.pickup_hint)

        self.update_report(None)

    # ------------------------------------------------------------------ 构建
    def _labeled_row(self, title: str, area: QHBoxLayout) -> QHBoxLayout:
        """左侧固定宽度标签 + 右侧内容区。"""
        row = QHBoxLayout()
        row.setSpacing(12)
        label = CaptionLabel(title, self)
        label.setTextColor(*MUTED)
        label.setFixedWidth(60)
        row.addWidget(label, 0, Qt.AlignmentFlag.AlignTop)
        row.addLayout(area, 1)
        return row

    # ------------------------------------------------------------------ 刷新
    def update_report(self, report) -> None:
        """``None`` = 还没跑过，显示占位。"""
        if report is None:
            self._set_team(())
            self._set_echo(None)
            for value in self.stats.values():
                value.setText("—")
            self.hint.setVisible(True)
            self.pickup_hint.setVisible(False)
            return

        self.hint.setVisible(False)
        self._set_team(report.team)
        self._set_echo(report.echo)
        self.stats["战斗次数"].setText(str(report.battles))
        self.stats["声骸数量"].setText(str(report.echo_count))
        self.stats["锁定声骸"].setText(str(report.pickups.locked))
        self.stats["时长"].setText(report.duration_text)

        # 诊断用：把拾取到的声骸按角标分的三类都摆出来。
        # 判定区域万一不对，会表现为「锁定/弃置恒为 0、都没 = 全部」—— 一眼能看出来。
        pickups = report.pickups
        self.pickup_hint.setText("拾取分类：锁定 %d · 弃置 %d · 都没 %d"
                                 % (pickups.locked, pickups.dropped, pickups.none))
        self.pickup_hint.setVisible(pickups.total > 0)

    def _set_team(self, members) -> None:
        key = tuple(m.name for m in members)
        if key == self._team_key:
            return                       # 队伍没变就别重建
        self._team_key = key
        _clear_layout(self.team_area)
        if not members:
            self.team_area.addWidget(self._muted("还没识别到（进战斗后会自动读队伍）"))
        else:
            for member in members:
                self.team_area.addWidget(TeamMemberChip(member, self))
        self.team_area.addStretch(1)

    def _set_echo(self, target) -> None:
        key = "" if target is None else "%s|%s" % (target.name, target.identified)
        if key == self._echo_key:
            return
        self._echo_key = key
        _clear_layout(self.echo_area)

        if target is None:
            self.echo_area.addWidget(self._muted("—"))
            self.echo_area.addStretch(1)
            return

        icon = load_icon(target.icon) if target.icon else QIcon()
        if not icon.isNull():
            view = IconWidget(icon, self)
            view.setFixedSize(self.ECHO_ICON_SIZE, self.ECHO_ICON_SIZE)
            self.echo_area.addWidget(view)
        self.echo_area.addWidget(StrongBodyLabel(target.name, self))

        if not target.identified:
            # ok-ww 只认 4 个 Boss；其余情况照实显示配置档位名 + 这个角标
            badge = QLabel("未识别", self)
            badge.setFixedSize(48, 18)
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setStyleSheet(
                "color: #8A5A0F; background: rgba(224, 168, 60, 0.22);"
                "border-radius: 4px; font-size: 11px;")
            self.echo_area.addWidget(badge)
        self.echo_area.addStretch(1)

    def _muted(self, text: str) -> CaptionLabel:
        label = CaptionLabel(text, self)
        label.setTextColor(*MUTED)
        return label


class AutoCombatWidget(ScrollArea):
    """ok-ww 宿主面板：启动 / 停止 + 战斗报告 + 状态。"""

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
                              "引擎随程序启动已在后台加载，点「启动」直接开跑", page)
        row = QHBoxLayout()
        row.setSpacing(12)
        self.start_btn = PrimaryPushButton("启动", run_card)
        self.start_btn.clicked.connect(self._on_start)
        self.stop_btn = PushButton("停止", run_card)
        self.stop_btn.clicked.connect(self._on_stop)
        row.addWidget(self.start_btn, 1)
        row.addWidget(self.stop_btn, 1)
        run_card.body.addLayout(row)

        self.state_label = CaptionLabel("引擎：后台加载中 · 就绪后点「启动」开跑", run_card)
        self.state_label.setTextColor("#C9514C", "#E6B4AC")
        run_card.add(self.state_label)
        layout.addWidget(run_card)

        # ------------------------------------------------------ 战斗报告
        self.report_card = BattleReportCard(page)
        layout.addWidget(self.report_card)

        # ---------------------------------------------------------- 说明卡
        note_card = ConfigCard("使用说明", None, page)
        log_dir = paths.user_data_dir() / "okww" / "logs"
        notes = (
            "① 引擎随程序启动就在后台加载；点「启动」= 开跑「4C 刷声骸」"
            "（打 Boss → 拾取 → 重开循环）；\n"
            "② 鸣潮需以窗口模式运行（不支持独占全屏），推荐 16:9 分辨率；\n"
            "③ 按键走 PostMessage 后台消息，游戏不必切到前台；\n"
            f"④ 运行日志在后台按日期落盘：{log_dir}"
            "（每天一个文件，超过 31 天自动清理）；出问题把这个目录里当天的文件发过来即可；\n"
            "⑤ 分发本工具的安装包时需按 AGPL-3.0 一并提供源码（见 README「开源许可」）。"
        )
        note_card.add(CaptionLabel(notes, note_card))
        layout.addWidget(note_card)

        layout.addStretch(1)
        self.setWidget(page)

        # 本页不主动 boot：引擎由 main.py 在程序启动时拉起（autostart_engine）。
        # 这里只管轮询状态；点「启动」是兜底重试路径（见 _on_start）
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
            self.state_label.setText("引擎：就绪（随程序启动已加载）· 点「启动」开始 4C 刷声骸")
        else:
            self.state_label.setText("引擎：未启动 · 点「启动」会先加载引擎再开跑")

        # 启动：空闲 / 就绪 / 失败重试 / 启动中（可改排队）；运行中禁用
        self.start_btn.setEnabled(not running)
        self.stop_btn.setEnabled(bool(running) or bool(pending))

        # 一次性任务跑完把状态拉回 ready
        self._host.poll_done()

        # 战斗报告：边跑边刷新（数字取自 ok-ww 自己的计数器；
        # 放在 poll_done 之后，这样停止那一刻就能读到冻结的时长）
        self.report_card.update_report(self._host.battle_report())


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
