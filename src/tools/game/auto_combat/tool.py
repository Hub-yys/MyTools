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

import logging
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget
from qfluentwidgets import (
    CaptionLabel,
    CheckBox,
    ComboBox,
    FluentIcon,
    HyperlinkButton,
    IconWidget,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    MessageBox,
    PrimaryPushButton,
    PushButton,
    ScrollArea,
    StrongBodyLabel,
)

from ....core import paths, shutdown_timer, tool_settings
from ....core.categories import ToolCategory
from ....core.registry import registry
from ....core.tool_base import BaseTool
from ....gui.library_interface import circular_icon
from ....gui.pickers import load_icon
from ....gui.widgets import ConfigCard
from .okww_boot import DEFAULT_TASK_KEY, get_host
from . import history, okww_farm, rotation

#: 定时关机设置的存放节（和别处一样存 tool_settings）
SHUTDOWN_SETTINGS_KEY = "auto_combat"

#: 默认的关机分钟数（勾上就用它）
DEFAULT_SHUTDOWN_MINUTES = 60


#: 说明文字颜色（(浅色主题, 深色主题)）—— 与资源库页保持同一套灰
MUTED = ("#8A8F98", "#7C7C7C")

logger = logging.getLogger(__name__)


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


class HistoryCard(ConfigCard):
    """4C 自动战斗的「历史记录」—— 每次「启动 → 停止」记一条。

    ## 为什么要它（用户 2026-10-28）

    > 这里的使用说明删掉，改成历史记录

    「使用说明」那几条是给**第一次用**的人看的，看完就没用了，白占一屏。
    历史记录则是每次跑完都想看一眼的东西：跑了多久、打了多少、拿了几只锁定。

    ## 什么时候落一条

    宿主在**停止时**落一条（见 :meth:`AutoCombatWidget._on_stop` 和
    ``OkwwHost`` 的 ``_notify_task_done``）。**运行中不落** ——
    否则每 3 秒一条，历史会被刷爆。

    ## 显示几条

    只显示最近 :attr:`MAX_ROWS` 条，多了在底部显示「共 N 次」汇总。
    **不滚动**：这里的卡片是主界面的一部分，做成内嵌滚动区很丑。
    想看全部还有历史文件本身（用户数据目录）。
    """

    MAX_ROWS = 5
    #: 各列宽度（像素）。**要够宽**，否则数字会挤在一起看不清
    #: （实测 84/74/68 时「时间」和「时长」几乎贴上了）
    COLS = (100, 80, 62, 62, 58)

    def __init__(self, parent=None):
        super().__init__("历史记录", "每次「启动 → 停止」跑完记一条，最近 5 次",
                         parent)

        self._store = history.HistoryStore()
        self._signature: tuple | None = None

        #: 表头
        head = QHBoxLayout()
        head.setSpacing(14)
        for title, width in zip(("时间", "时长", "战斗", "声骸", "锁定"), self.COLS):
            label = CaptionLabel(title, self)
            label.setTextColor(*MUTED)
            label.setFixedWidth(width)
            head.addWidget(label)
        head.addStretch(1)
        self.body.addLayout(head)

        #: 记录行容器（每次刷新重建里面的控件）
        self.rows = QVBoxLayout()
        self.rows.setSpacing(6)
        self.body.addLayout(self.rows)

        #: 空态 / 汇总
        self.hint = CaptionLabel("还没跑过 —— 点「启动」跑一次，停后会记在这里",
                                 self)
        self.hint.setTextColor(*MUTED)
        self.body.addWidget(self.hint)

        self.total = CaptionLabel("", self)
        self.total.setTextColor(*MUTED)
        self.total.setWordWrap(True)
        self.body.addWidget(self.total)

        self.refresh()

    # ------------------------------------------------------------------ 刷新
    def refresh(self) -> None:
        """重新读盘并重画。**只在内容真变了才重建**，否则控件会闪。"""
        records = self._store.records(self.MAX_ROWS)
        sig = tuple(
            (r.started_at, r.duration, r.battles, r.echoes, r.locked)
            for r in records
        )
        if sig == self._signature:
            return
        self._signature = sig

        #: 清空旧行
        while self.rows.count():
            item = self.rows.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        if not records:
            self.hint.setVisible(True)
            self.total.setVisible(False)
            self.total.setText("")
            return

        self.hint.setVisible(False)
        for record in records:
            self.rows.addLayout(self._build_row(record))
        self.total.setText(self._store.total_text())
        self.total.setVisible(True)

    def _build_row(self, record) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(14)
        values = (
            record.when_text,
            record.duration_text,
            str(record.battles),
            str(record.echoes),
            str(record.locked),
        )
        for index, (value, width) in enumerate(zip(values, self.COLS)):
            label = StrongBodyLabel(value, self) if index else CaptionLabel(value, self)
            if index == 0:
                #: 时间列用弱色，数据列用强色 —— 扫一眼先看到数字
                label.setTextColor(*MUTED)
            label.setFixedWidth(width)
            row.addWidget(label)
        #: 队伍塞在右边，太长会省略（不换行，避免每行高度不一致）
        team = CaptionLabel(record.team_text, self)
        team.setTextColor(*MUTED)
        team.setToolTip(record.team_text)
        row.addWidget(team, 1)
        return row

    # ------------------------------------------------------------------ 落盘
    def record_run(self, report, *, started_at: float,
                   ended_at: float) -> None:
        """跑完调这个 —— 拍平一条历史并刷新界面。"""
        record = history.record_from_report(report, started_at=started_at,
                                            ended_at=ended_at)
        if record is None:
            return
        #: 时长为 0 且什么都没打的，不记（避免误点「启动」留下垃圾行）
        if record.duration < 5 and not record.battles and not record.echoes:
            return
        self._store.add(record)
        self._signature = None      #: 强制重画
        self.refresh()


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

    #: 空闲时轮询间隔（毫秒）—— 界面要跟手，300ms 合适。
    POLL_MS = 300

    #: ★★★ 任务运行中的轮询间隔（毫秒）—— **故意降到 3 秒**。
    #:
    #: ## 为什么（2026-10-26 用户实测「老是停顿」）
    #:
    #: MyTools 的 GUI 和 ok 引擎跑在**同一个 Python 进程**里
    #: （引擎在 ``okww-boot`` 后台线程，见 ``okww_boot.OkwwHost.boot``），
    #: 两者共享一把 **GIL**。
    #:
    #: ``_poll`` 每 300ms 要做：6 处 QLabel/QPushButton 重绘 +
    #: 战斗报告卡片刷新 + ``poll_done()`` + 定时关机检查。
    #: 这些都是**主线程拿 GIL** 干的活，而引擎线程正在做
    #: ``cv2.matchTemplate``（战斗里每秒 5~6 次，每次 180ms）——
    #: 两边抢同一把 GIL，引擎的匹配就被拖慢。
    #:
    #: 实测：同一份代码，ok-ww 单次匹配 80ms，我们 188ms（慢 2.3 倍）。
    #: 慢下来的匹配 → 主循环被占满 → 角色站着不动 → **被打死**。
    #:
    #: 运行中界面只需要偶尔更新个数字，3 秒完全够看；
    #: 空闲时才用 300ms 保证按钮状态跟手。
    POLL_MS_RUNNING = 3000

    def __init__(self, meta, parent=None):
        super().__init__(parent)
        self._meta = meta
        self._host = get_host()
        #: 定时关机（None = 还没启动过；由 _on_start 建）
        self._shutdown: shutdown_timer.ShutdownTimer | None = None

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

        # ------------------------------------------------------ 战斗方式
        layout.addWidget(self._build_style_card(page))

        # ------------------------------------------------------ 定时关机
        layout.addWidget(self._build_shutdown_card(page))

        # ------------------------------------------------------ 战斗报告
        self.report_card = BattleReportCard(page)
        layout.addWidget(self.report_card)

        # ---------------------------------------------------------- 历史记录
        #: ★ 2026-10-28 用户：「这里的使用说明删掉，改成历史记录」
        #:
        #: 「使用说明」那五条是**首次使用**才需要看的（引擎加载方式、窗口模式、
        #: 日志位置、AGPL 义务）—— 看完就没用了，白占一屏。
        #: 换成每次跑完都想看一眼的历史记录。
        #:
        #: 那些说明文字没扔：引擎/窗口/日志这三条在 ``README.md`` 和本工具的
        #: docstring 里都有，日志目录也会在「消息」页的出问题引导里提到。
        self.history_card = HistoryCard(page)
        layout.addWidget(self.history_card)

        layout.addStretch(1)
        self.setWidget(page)

        # 本页不主动 boot：引擎由 main.py 在程序启动时拉起（autostart_engine）。
        # 这里只管轮询状态；点「启动」是兜底重试路径（见 _on_start）
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(self.POLL_MS)
        self._poll()

    # ------------------------------------------------------------ 战斗方式
    def _build_style_card(self, page) -> ConfigCard:
        """「战斗方式」下拉框（用户 2026-10-25 要求加回来）。

        三种：智能切换（= ok-ww 原版）/ 轮切（固定轴 3→2→1）/ 合轴（待定）。

        ## ⚠ 默认必须是「智能切换」

        用户实测过固定轴不如 ok-ww。而且「智能切换」在我们这边的实现是
        **完全不覆盖任何方法** —— 等价于用 ok-ww 官方程序。

        ## ⚠ 改了要**下次启动**才生效

        任务实例在 ``__init__`` 里读一次 ``combat_style``。运行中改下拉框
        只会存盘、当前这局不变 —— 所以运行期间**锁住**并说明原因。
        """
        card = ConfigCard(
            "战斗方式",
            "**智能切换** = ok-ww 原生调度（默认，推荐）。"
            "**轮切** = 固定轴 3→2→1，协奏满就换。"
            "**合轴** = 待定，当前等同智能切换。"
            "⚠ 改动**下次启动生效**；运行中会锁定。",
            page)

        row = QHBoxLayout()
        row.setSpacing(10)

        self.style_box = ComboBox(card)
        self.style_box.setMinimumWidth(160)
        for style, label, _desc in rotation.STYLES:
            self.style_box.addItem(label, userData=style)
        row.addWidget(self.style_box)

        self.style_hint = self._muted_label("", card)
        self.style_hint.setWordWrap(True)
        row.addWidget(self.style_hint, 1)
        card.body.addLayout(row)

        #: 读回上次选择（默认 smart）
        current = rotation.normalize_style(
            (tool_settings.load(okww_farm.COMBAT_STYLE_KEY) or {}).get("style"))
        for idx in range(self.style_box.count()):
            if self.style_box.itemData(idx) == current:
                self.style_box.setCurrentIndex(idx)
                break
        self._update_style_hint(current)
        self.style_box.currentIndexChanged.connect(self._on_style_changed)
        return card

    def _update_style_hint(self, style: str) -> None:
        """说明当前选项的行为。"""
        for value, _label, desc in rotation.STYLES:
            if value == style:
                extra = ""
                if value == rotation.STYLE_COMBO:
                    extra = "（当前不接管切人，等同智能切换）"
                self.style_hint.setText(desc + extra)
                return

    def _apply_style_enabled(self, running: bool, pending: bool = False) -> None:
        """运行中**禁用**战斗方式下拉框，并说明原因。

        :param running: 有没有任务在跑
        :param pending: 有没有排队等待启动的任务（引擎还在 boot）—— 也要锁
        """
        box = getattr(self, "style_box", None)
        if box is None:
            return
        busy = bool(running) or bool(pending)
        box.setEnabled(not busy)
        if not busy:
            #: 恢复成正常说明（可能上一轮被改成了"运行中"的提示）
            self._update_style_hint(
                rotation.normalize_style(box.currentData()))
            return
        self.style_hint.setText(
            "⚠ 任务运行中，战斗方式已锁定 —— 停止后再改"
            "（改动要到下一次启动才生效）")

    def _on_style_changed(self, _index: int) -> None:
        """用户换了战斗方式 → 存盘 + 更新说明；**运行中还原、不写盘**。

        第一道是 :meth:`_apply_style_enabled` 把下拉框禁用掉；
        这里是第二道 —— 万一被绕过（键盘/程序），还原成"当前真正生效"的值。
        """
        style = rotation.normalize_style(self.style_box.currentData())

        if self._is_busy():
            saved = rotation.normalize_style(okww_farm.read_combat_style())
            self._sync_style_box(saved)
            self._apply_style_enabled(running=True)
            logger.info("任务运行中，忽略切换战斗方式的请求（%s）", style)
            return

        self._update_style_hint(style)
        try:
            tool_settings.save(okww_farm.COMBAT_STYLE_KEY, {"style": style})
        except Exception:  # noqa: BLE001 - 存不下来也只是下次要重选
            logger.warning("保存战斗方式失败", exc_info=True)

    def _is_busy(self) -> bool:
        """现在有没有任务在跑（或马上要跑）。"""
        try:
            return bool(self._host.running_task or self._host.pending_start)
        except Exception:  # noqa: BLE001 - 宿主状态异常按"空闲"处理
            return False

    def _sync_style_box(self, style: str) -> None:
        """把下拉框切到指定方式，**不触发** ``currentIndexChanged``。"""
        box = getattr(self, "style_box", None)
        if box is None:
            return
        for idx in range(box.count()):
            if box.itemData(idx) == style:
                box.blockSignals(True)
                try:
                    box.setCurrentIndex(idx)
                finally:
                    box.blockSignals(False)
                return

    # ------------------------------------------------------------ 定时关机
    def _build_shutdown_card(self, page) -> ConfigCard:
        """定时关机设置卡（2026-10-01 用户要求）。

        * **跑 N 分钟后关**（从点「启动」开始计时）；
        * 关机前**提前通知**（不挡路），**到点直接关、不再确认**。

        ⚠ 用户 2026-10-05："这里改为不用确认，到时间就自动关机"
        （截图圈的就是这张卡）—— 原来那句"关机前会弹提醒，随时可以取消"
        是**模态确认框**的说明，已经不准了。
        """
        card = ConfigCard(
            "定时关机",
            "跑够指定分钟数后自动关机（从点「启动」开始计时）；"
            f"关机前 {shutdown_timer.WARN_SECONDS} 秒会弹通知，"
            "到点直接关机（想反悔就点通知里的「取消」）。",
            page)

        row = QHBoxLayout()
        row.setSpacing(10)

        self.shutdown_check = CheckBox("启用", card)
        row.addWidget(self.shutdown_check)

        self.shutdown_edit = LineEdit(card)
        self.shutdown_edit.setFixedWidth(90)
        self.shutdown_edit.setPlaceholderText(str(DEFAULT_SHUTDOWN_MINUTES))
        row.addWidget(self.shutdown_edit)

        row.addWidget(self._muted_label("分钟后关机", card))
        row.addStretch(1)
        row.addWidget(self._muted_label(
            f"（{shutdown_timer.MIN_MINUTES}~{shutdown_timer.MAX_MINUTES} 分钟）",
            card))
        card.body.addLayout(row)

        self.shutdown_state = CaptionLabel("", card)
        self.shutdown_state.setTextColor(*MUTED)
        self.shutdown_state.setWordWrap(True)
        card.add(self.shutdown_state)

        # 读回上次的设置
        saved = tool_settings.load(SHUTDOWN_SETTINGS_KEY) or {}
        self.shutdown_check.setChecked(bool(saved.get("shutdown_enabled")))
        minutes = shutdown_timer.clamp_minutes(
            saved.get("shutdown_minutes") or DEFAULT_SHUTDOWN_MINUTES)
        self.shutdown_edit.setText(str(minutes or DEFAULT_SHUTDOWN_MINUTES))

        self.shutdown_check.toggled.connect(lambda _c: self._save_shutdown())
        self.shutdown_edit.textChanged.connect(lambda _t: self._save_shutdown())
        self._refresh_shutdown_state()
        return card

    def _muted_label(self, text: str, parent) -> CaptionLabel:
        label = CaptionLabel(text, parent)
        label.setTextColor(*MUTED)
        return label

    def _shutdown_minutes(self) -> int:
        """界面上填的分钟数（夹过范围）。不启用时返回 0。"""
        if not self.shutdown_check.isChecked():
            return 0
        return shutdown_timer.clamp_minutes(self.shutdown_edit.text())

    def _save_shutdown(self) -> None:
        """存设置 —— ⚠ 用 ``clamp_minutes`` 夹过再存，别把脏数据写进盘。"""
        tool_settings.save(SHUTDOWN_SETTINGS_KEY, {
            **dict(tool_settings.load(SHUTDOWN_SETTINGS_KEY) or {}),
            "shutdown_enabled": self.shutdown_check.isChecked(),
            "shutdown_minutes": shutdown_timer.clamp_minutes(
                self.shutdown_edit.text()) or DEFAULT_SHUTDOWN_MINUTES,
        })
        self._refresh_shutdown_state()

    def _refresh_shutdown_state(self) -> None:
        """状态行：没启用就说明一下，启用了就显示倒计时。"""
        if self._shutdown is not None and self._shutdown.active:
            self.shutdown_state.setText(
                f"将在 {self._shutdown.remaining_text()} 后关机"
                "（关机前会弹通知，到点直接关）")
            self.shutdown_state.setTextColor("#C9514C", "#E6B4AC")
            return

        minutes = self._shutdown_minutes()
        self.shutdown_state.setTextColor(*MUTED)
        if minutes:
            self.shutdown_state.setText(
                f"已设为运行 {minutes} 分钟后关机 —— 点「启动」开始计时。")
        else:
            self.shutdown_state.setText("未启用（不勾选就不会关机）。")

    def _tick_shutdown(self) -> None:
        """轮询里调 —— 检查该通知 / 该关机了。"""
        timer = self._shutdown
        if timer is None or not timer.active:
            return

        if timer.should_warn():
            self._notify_before_shutdown()
            return
        if timer.should_fire():
            self._do_shutdown()
            return
        self._refresh_shutdown_state()

    def _notify_before_shutdown(self) -> None:
        """关机前的**通知** —— 不挡路、也不等用户点。

        ## 用户 2026-10-05

            "这里改为不用确认，到时间就自动关机"

        ⚠⚠ 原来是弹**模态** ``MessageBox``（"立即关机 / 取消关机"）——
        那不但烦，而且**逻辑上是坏的**：

        模态框只挡得住**调用方的代码**，``QTimer`` 轮询照跑 ——
        提醒窗口一过（60 秒），``should_fire()`` 就是 True，
        **框还开着电脑也照关**。也就是说「取消关机」按钮
        **只有 60 秒有效期**，超时就点不动了。

        → 改成非模态 InfoBar：不阻塞、到点直接关，
        想反悔就点通知里的「取消」。
        """
        seconds = shutdown_timer.WARN_SECONDS
        #: ⚠ ``InfoBar`` 的按钮得自己挂 —— 默认没有 action 按钮
        bar = InfoBar.new(
            icon=FluentIcon.HISTORY,
            title="即将自动关机",
            content=f"电脑将在 {seconds} 秒后关机。想反悔就点右边的「取消」。",
            orient=Qt.Orientation.Horizontal,
            isClosable=False,
            position=InfoBarPosition.TOP_RIGHT,
            duration=-1,                       #: 一直显示到关机
            parent=self,
        )
        bar.addWidget(self._make_cancel_button(bar))
        bar.show()

    def _make_cancel_button(self, bar):
        """InfoBar 里的「取消」按钮 —— 点了就撤掉本次自动关机。"""
        button = HyperlinkButton("", "取消", self)
        button.clicked.connect(lambda: self._cancel_shutdown("已取消自动关机。"))
        button.clicked.connect(bar.close)
        return button

    def _do_shutdown(self) -> None:
        ok, message = shutdown_timer.shutdown()
        if ok:
            self.shutdown_state.setText("已发出关机命令，电脑即将关闭。")
            self.shutdown_state.setTextColor("#C9514C", "#E6B4AC")
        else:
            InfoBar.error("关机失败", message, duration=10000, parent=self)
            self.shutdown_state.setText(f"关机失败：{message}")

    def _cancel_shutdown(self, note: str = "") -> None:
        if self._shutdown is not None:
            self._shutdown.cancel()
        self.shutdown_state.setText(note or "已取消定时关机。")
        self.shutdown_state.setTextColor(*MUTED)

    # ------------------------------------------------------------------ 槽
    def _on_start(self) -> None:
        # ★ 启动前把下拉框当前值落盘 —— 任务 ``__init__`` 会读它。
        #   不落盘的话，用户刚改的值可能还在 UI 里没写进设置。
        self._persist_style()
        # 引擎未就绪 / 失败态 / 就绪：统一走 start_task —— 内部会 boot 或直接开任务，
        # 引擎就绪后自动 flush 排队任务。
        err = self._host.start_task(DEFAULT_TASK_KEY)
        if err:
            InfoBar.error("启动失败", err, duration=8000, parent=self)
            return
        # ★ 计时**从点启动开始**（用户选的"跑多少分钟后关"）
        self._shutdown = shutdown_timer.ShutdownTimer(self._shutdown_minutes())
        self._shutdown.start()
        self._refresh_shutdown_state()
        # ★ 立刻锁一次战斗方式，不用等下一轮 poll 才灰掉
        self._apply_style_enabled(running=True)

    def _persist_style(self) -> None:
        """把下拉框当前值写进设置（失败只记日志，不挡启动）。"""
        box = getattr(self, "style_box", None)
        if box is None:
            return
        style = rotation.normalize_style(box.currentData())
        try:
            tool_settings.save(okww_farm.COMBAT_STYLE_KEY, {"style": style})
        except Exception:  # noqa: BLE001 - 存不下来也要能开跑
            logger.warning("保存战斗方式失败", exc_info=True)

    def _on_stop(self) -> None:
        err = self._host.stop_task()
        if err:
            InfoBar.warning("停止失败", err, duration=8000, parent=self)
        # 手动停止了 → 定时关机也一并取消。
        # ⚠ 不取消的话，用户以为"停了就没事了"，结果到点电脑还是关了。
        if self._shutdown is not None and self._shutdown.active:
            self._cancel_shutdown("已停止任务，定时关机一并取消。")

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

        # ★ 战斗方式：运行中（或正在启动）不许改 —— 见 _apply_style_enabled
        self._apply_style_enabled(bool(running), bool(pending))

        # 一次性任务跑完把状态拉回 ready
        self._host.poll_done()

        # 战斗报告：边跑边刷新（数字取自 ok-ww 自己的计数器；
        # 放在 poll_done 之后，这样停止那一刻就能读到冻结的时长）
        report = self._host.battle_report()
        self.report_card.update_report(report)

        #: ★★★ 历史记录：检测「运行中 → 停止」这个下降沿，落一条。
        #:
        #: ## 为什么在 _poll 里做，不在 _on_stop 里做
        #:
        #: 结束有 **三种** 途径：
        #:   ① 用户点「停止」
        #:   ② 任务自己跑完（``Repeat Farm Count`` 到了 / 异常退出）
        #:   ③ 定时关机
        #: 只在 ``_on_stop`` 里落会漏掉 ②③。这里用「上一次是 running、
        #: 这一次不是」来判定，三种都能覆盖。
        #:
        #: ## 为什么运行中不落
        #:
        #: 运行中每轮都 running=True，这个分支根本不会进 —— 天然安全。
        was_running = getattr(self, "_was_running", False)
        if was_running and not running:
            started = self._host.report_started_at()
            if started:
                self.history_card.record_run(
                    report, started_at=started, ended_at=time.time())
        self._was_running = bool(running)

        # 定时关机：提醒 / 到点执行（轮询里顺带做，不用额外的线程）
        self._tick_shutdown()

        #: ★ 动态调整轮询频率 —— 运行中放慢，把 GIL 让给引擎线程。
        #: 见 POLL_MS_RUNNING 的注释（用户实测「老是停顿」的根因之一）。
        busy = bool(running) or bool(pending)
        want = self.POLL_MS_RUNNING if busy else self.POLL_MS
        if self._timer.interval() != want:
            self._timer.setInterval(want)


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
