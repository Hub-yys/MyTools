"""鸣潮「唤取记录」分析 —— 工具页。

用户从游戏里复制「唤取记录」链接 → 粘进来 → 点「读取」→ 看统计。
数据来源是库洛官方接口（见 :mod:`src.core.gacha`），**本页不做 UI 自动化**。

## 为什么它不是 ok-ww 那条路

本项目其它游戏工具都是"UI 自动化"（模拟点击/读屏）。这个不一样：
它**联网请求官方接口**，拿的是**账号的抽卡数据**。所以：

* 不需要管理员权限、不需要游戏开着、不需要 ok-ww 引擎；
* 但要**联网**，并且会把链接里的玩家参数发给库洛服务器。

界面上把这件事说清楚（顶部那句说明），别让用户以为它偷偷干了什么。

## 拉取放在后台线程

7 个卡池 = 7 次请求，串行下来要几秒；直接在 UI 线程里跑会**卡住界面**。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QThread, Signal
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
    FluentIcon,
    InfoBar,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    ScrollArea,
    StrongBodyLabel,
    TitleLabel,
)

from ....core import gacha
from ....core.categories import ToolCategory
from ....core.registry import registry
from ....core.tool_base import BaseTool

#: 说明文字颜色（(浅色, 深色)）—— 和其它页同一套灰
MUTED = ("#8A8F98", "#7C7C7C")

PAGE_MARGIN = (36, 32, 36, 28)


class FetchThread(QThread):
    """后台拉取全部卡池。"""

    message = Signal(str)
    succeeded = Signal(object)      # GachaReport
    failed = Signal(str)

    def __init__(self, params: dict, parent=None):
        super().__init__(parent)
        self._params = params

    def run(self) -> None:  # noqa: D102 - QThread 接口
        try:
            report = gacha.fetch_report(
                self._params, log=lambda m: self.message.emit(m))
        except gacha.GachaError as exc:
            # 这类消息是**写给用户看的**（"记录过期，请打开唤取记录页"），
            # 不加异常类名前缀
            self.failed.emit(str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - 线程里抛异常必须带出来
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        self.succeeded.emit(report)


class _StatTile(CardWidget):
    """一个统计小块：大字数值 + 下面一行说明。"""

    def __init__(self, title: str, value: str = "—", note: str = "",
                 parent=None):
        super().__init__(parent)
        box = QVBoxLayout(self)
        box.setContentsMargins(16, 12, 16, 12)
        box.setSpacing(2)

        self.value_label = StrongBodyLabel(value, self)
        box.addWidget(self.value_label)

        name = CaptionLabel(title, self)
        name.setTextColor(*MUTED)
        box.addWidget(name)

        self.note_label = CaptionLabel(note, self)
        self.note_label.setTextColor(*MUTED)
        self.note_label.setWordWrap(True)
        box.addWidget(self.note_label)

    def set_value(self, value: str, note: str = "") -> None:
        self.value_label.setText(value)
        self.note_label.setText(note)


class GachaWidget(ScrollArea):
    """唤取记录分析页面。"""

    def __init__(self, meta=None, parent=None):
        super().__init__(parent)
        self.meta = meta
        self.setObjectName("GachaWidget")
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._thread: FetchThread | None = None
        self._report: gacha.GachaReport | None = None

        view = QWidget(self)
        view.setObjectName("gachaView")
        self.root = QVBoxLayout(view)
        self.root.setContentsMargins(*PAGE_MARGIN)
        self.root.setSpacing(12)

        self._build(view)

        self.setWidget(view)
        self.setWidgetResizable(True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("#GachaWidget { background: transparent; }")
        self.viewport().setStyleSheet("background: transparent;")

    # ---------------------------------------------------------------- 构建
    def _build(self, view: QWidget) -> None:
        self.root.addWidget(TitleLabel("唤取记录分析", view))

        note = CaptionLabel(
            "从游戏里复制「唤取记录」链接粘到下面，点「读取」即可统计。\n"
            "数据来自库洛官方接口 —— **需要联网**，会把链接里的玩家参数"
            "发给库洛服务器（不读游戏、不模拟操作、不需要管理员权限）。",
            view,
        )
        note.setTextColor(*MUTED)
        note.setWordWrap(True)
        self.root.addWidget(note)

        # ---- 链接行 ----
        link_row = QWidget(view)
        row = QHBoxLayout(link_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        self.link_edit = LineEdit(link_row)
        self.link_edit.setPlaceholderText(
            "粘贴唤取记录链接（游戏 → 唤取 → 唤取记录 → 复制链接）")
        self.link_edit.setClearButtonEnabled(True)
        row.addWidget(self.link_edit, 1)

        self.fetch_button = PrimaryPushButton(FluentIcon.SYNC, "读取", link_row)
        self.fetch_button.clicked.connect(self.start_fetch)
        row.addWidget(self.fetch_button)
        self.root.addWidget(link_row)

        # ---- 状态 / 日志 ----
        self.status = CaptionLabel("", view)
        self.status.setTextColor(*MUTED)
        self.status.setWordWrap(True)
        self.root.addWidget(self.status)

        # ---- 总览 ----
        self.summary_title = StrongBodyLabel("总览", view)
        self.root.addWidget(self.summary_title)
        self.summary_host = QWidget(view)
        self.summary_grid = QGridLayout(self.summary_host)
        self.summary_grid.setContentsMargins(0, 0, 0, 0)
        self.summary_grid.setSpacing(10)
        self.root.addWidget(self.summary_host)

        self.tiles: dict[str, _StatTile] = {}
        for index, (key, title) in enumerate((
            ("total", "总抽数"),
            ("five", "五星数量"),
            ("rate", "五星出货率"),
            ("average", "平均出货抽数"),
            ("four", "四星数量"),
            ("luck", "欧非评价"),
        )):
            tile = _StatTile(title, parent=self.summary_host)
            self.tiles[key] = tile
            self.summary_grid.addWidget(tile, index // 3, index % 3)

        # ---- 分池 ----
        self.pools_title = StrongBodyLabel("分卡池统计", view)
        self.root.addWidget(self.pools_title)
        self.pools_host = QWidget(view)
        self.pools_box = QVBoxLayout(self.pools_host)
        self.pools_box.setContentsMargins(0, 0, 0, 0)
        self.pools_box.setSpacing(8)
        self.root.addWidget(self.pools_host)

        # ---- 五星记录 ----
        self.fives_title = StrongBodyLabel("五星记录", view)
        self.root.addWidget(self.fives_title)
        self.fives_host = QWidget(view)
        self.fives_box = QVBoxLayout(self.fives_host)
        self.fives_box.setContentsMargins(0, 0, 0, 0)
        self.fives_box.setSpacing(6)
        self.root.addWidget(self.fives_host)

        self.root.addStretch(1)
        self._show_empty_hint()

    # ---------------------------------------------------------------- 动作
    def start_fetch(self) -> None:
        if self._thread is not None and self._thread.isRunning():
            return
        try:
            params = gacha.parse_link(self.link_edit.text())
        except gacha.GachaError as exc:
            self.status.setText(str(exc))
            InfoBar.warning("链接有问题", str(exc).splitlines()[0],
                            duration=5000, parent=self.window())
            return

        self.fetch_button.setEnabled(False)
        self.status.setText("正在读取…")
        self._clear_results()
        self._thread = FetchThread(params, self)
        self._thread.message.connect(self.status.setText)
        self._thread.succeeded.connect(self._on_ok)
        self._thread.failed.connect(self._on_fail)
        self._thread.start()

    def _on_ok(self, report) -> None:
        self._report = report
        self.fetch_button.setEnabled(True)
        if not report.total:
            self.status.setText(
                "读取成功，但这个账号没有任何唤取记录（或者记录已过期清空）。")
            return
        self.status.setText(f"读取完成：共 {report.total} 抽。")
        self.render(report)

    def _on_fail(self, message: str) -> None:
        self.fetch_button.setEnabled(True)
        self.status.setText(message.splitlines()[0])
        InfoBar.error("读取失败", message, duration=8000, parent=self.window())

    # ---------------------------------------------------------------- 渲染
    def _clear_layout(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def _clear_results(self) -> None:
        self._clear_layout(self.pools_box)
        self._clear_layout(self.fives_box)

    def _show_empty_hint(self) -> None:
        hint = CaptionLabel(
            "还没有数据 —— 粘贴链接后点「读取」。", self.pools_host)
        hint.setTextColor(*MUTED)
        self.pools_box.addWidget(hint)

    def render(self, report) -> None:
        """把报告铺到界面上。"""
        self._clear_results()

        # ---- 总览 ----
        self.tiles["total"].set_value(str(report.total))
        self.tiles["five"].set_value(str(report.five_count))
        self.tiles["four"].set_value(str(report.four_count))
        self.tiles["rate"].set_value(f"{report.rate():.2f}%")
        average = report.average()
        self.tiles["average"].set_value(
            f"{average:.1f}" if average else "—")
        luck = report.luck()
        self.tiles["luck"].set_value(luck[0] if luck else "—")
        if luck:
            self.tiles["luck"].value_label.setTextColor(luck[1], luck[1])

        # ---- 分池 ----
        for pool in report.active_pools():
            self.pools_box.addWidget(self._pool_row(pool))
        if not report.active_pools():
            self._show_empty_hint()

        # ---- 五星记录 ----
        fives = report.all_five_stars()
        if not fives:
            empty = CaptionLabel("这个账号还没有出过五星。", self.fives_host)
            empty.setTextColor(*MUTED)
            self.fives_box.addWidget(empty)
            return

        # 每个五星标注"第几抽出" —— 用模型给的映射，**别在界面里重算**
        # （重算一遍就等于把"方向"这套逻辑抄了两份，抄错会静默显示错的数字）
        span_by_pull: dict[int, int] = {}
        for pool in report.pools:
            for pull, span in pool.five_star_spans():
                span_by_pull[id(pull)] = span

        for pull in fives[:200]:
            self.fives_box.addWidget(self._five_row(pull, span_by_pull))

    def _pool_row(self, pool) -> QWidget:
        card = CardWidget(self.pools_host)
        row = QHBoxLayout(card)
        row.setContentsMargins(16, 10, 16, 10)
        row.setSpacing(16)

        name = BodyLabel(pool.name, card)
        name.setFixedWidth(200)
        row.addWidget(name)

        for text in (
            f"{pool.total} 抽",
            f"五星 {pool.five_count}",
            f"出货率 {pool.rate():.2f}%",
            f"平均 {pool.average():.1f}" if pool.average() else "平均 —",
            f"已垫 {pool.current_pity()} 抽",
        ):
            row.addWidget(CaptionLabel(text, card))
        row.addStretch(1)
        luck = pool.luck()
        if luck:
            tag = CaptionLabel(luck[0], card)
            tag.setTextColor(luck[1], luck[1])
            row.addWidget(tag)
        return card

    def _five_row(self, pull, span_by_pull) -> QWidget:
        card = CardWidget(self.fives_host)
        row = QHBoxLayout(card)
        row.setContentsMargins(16, 8, 16, 8)
        row.setSpacing(12)

        name = BodyLabel(pull.name or "（未收录）", card)
        name.setFixedWidth(180)
        row.addWidget(name)

        row.addWidget(CaptionLabel(pull.pool, card))
        span = span_by_pull.get(id(pull))
        row.addWidget(CaptionLabel(
            f"第 {span} 抽" if span else "—", card))
        row.addStretch(1)
        row.addWidget(CaptionLabel(pull.time, card))
        return card


@registry.register(
    category=ToolCategory.GAME,
    name="唤取记录分析",
    description="粘贴唤取记录链接，统计抽卡出货率 / 保底进度 / 五星记录",
    icon_name="HISTORY",
    coming_soon=False,
)
class GachaTool(BaseTool):
    """抽卡记录分析工具。"""

    key = "gacha"
    #: ⚠ BaseTool 默认 ``coming_soon = True``（显示"即将到来"占位页）——
    #: 这个工具是**真做完了的**，必须显式关掉，否则点进去还是占位页。
    coming_soon = False
    #: 不参与任务流程：它不操作游戏，是"查数据"的工具
    supports_task_run = False

    def create_widget(self, parent=None):
        return GachaWidget(self.meta(), parent)
