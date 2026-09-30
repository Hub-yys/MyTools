"""抽卡记录分析 —— 工具页。

用户从游戏里复制「唤取记录」链接 → 粘进来 → 点「读取」→ 看统计。
数据来自库洛官方接口（见 :mod:`src.core.gacha`），**本页不做 UI 自动化**。

界面参照鸣潮工坊的抽卡分析（用户 2026-09-30 要求"直接做成工坊那样"）：

    ┌ 总览大字 ────────────────────────────────┐
    │  欧非评价（大标题）                        │
    │  总抽数 / 平均出金                         │
    │  不歪率 · 五星数 · 每UP角色 · 每UP武器      │
    ├ 抽卡总结 ─────────────────────────────────┤
    │  共获得限定五星 N 个，常驻五星 M 个         │
    │  [五星卡片墙，每张带"抽了几次"角标]         │
    ├ 分卡池 ───────────────────────────────────┤
    │  每个五星一行：名字 + 抽数条（带颜色）+ 歪标 │
    └───────────────────────────────────────────┘

## 为什么它不是 ok-ww 那条路

本项目其它游戏工具都是"UI 自动化"（模拟点击/读屏）。这个不一样：
它**联网请求官方接口**，拿的是**账号的抽卡数据**。所以不需要管理员权限、
不需要游戏开着、不需要 ok-ww 引擎；但要联网。

## 拉取放在后台线程

7 个卡池 = 7 次请求，串行下来要几秒；直接在 UI 线程里跑会**卡住界面**。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
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
    SubtitleLabel,
    TitleLabel,
)

from ....core import gacha
from ....core.categories import ToolCategory
from ....core.registry import registry
from ....core.tool_base import BaseTool

#: 说明文字颜色（(浅色, 深色)）—— 和其它页同一套灰
MUTED = ("#8A8F98", "#7C7C7C")
#: 强调色（大数字）
ACCENT = ("#1a1a1a", "#f0f0f0")

PAGE_MARGIN = (36, 32, 36, 28)

#: 抽数条的宽度（像素/抽）—— 条太长会撑爆一行，太长就截断
BAR_UNIT = 4
BAR_MAX = 260
BAR_HEIGHT = 18
#: 星级角标颜色
STAR_COLORS = {5: "#d4a017", 4: "#9b59b6", 3: "#5a8fd4"}


class GrabLinkThread(QThread):
    """后台从游戏日志里读抽卡链接。

    ⚠ 必须后台跑：找不到游戏目录时会**全盘扫**（实测几十秒），
    在 UI 线程里跑界面会整个冻住。
    """

    succeeded = Signal(str)
    failed = Signal(str)

    def run(self) -> None:  # noqa: D102 - QThread 接口
        try:
            from ....core.gacha_link import GrabError, grab_link

            url = grab_link()
        except GrabError as exc:
            self.failed.emit(str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - 线程里抛异常必须带出来
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        self.succeeded.emit(url)


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


class _BigStat(QWidget):
    """一个大数字 + 下面一行小字（工坊顶部那排）。

    ⚠ 两个实机踩过的坑（第一版显示成一堆小横杠就是这两个）：

    1. **``setFont() 之后又 setTextColor() 会把字体覆盖回去** ——
       qfluentwidgets 的 ``setTextColor`` 内部重设了样式表/字体，
       所以大字号要在**最后**设，或者改用 ``setStyleSheet``。
       这里干脆用 QLabel + 显式 stylesheet，不跟它的字体机制打架。
    2. **必须设最小宽度**：放进 QHBoxLayout 时控件会被压到最小尺寸，
       大数字挤不下就只剩一条横杠。
    """

    #: 每个统计块的最小宽度（够放「总抽卡数」这种标签 + 4 位数字）
    MIN_WIDTH = 110

    def __init__(self, value: str = "—", caption: str = "", parent=None,
                 color: str | None = None):
        super().__init__(parent)
        self.setMinimumWidth(self.MIN_WIDTH)

        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(2)

        # 用 QLabel + stylesheet：字号/颜色一次写清，不会被别的方法覆盖
        self.value_label = QLabel(value, self)
        self._apply_value_style(color)
        box.addWidget(self.value_label)

        self.caption_label = CaptionLabel(caption, self)
        self.caption_label.setTextColor(*MUTED)
        box.addWidget(self.caption_label)

    def _apply_value_style(self, color: str | None) -> None:
        """大数字的样式。字号走 stylesheet（比 setFont 稳）。"""
        tint = color or "#1a1a1a"
        self.value_label.setStyleSheet(
            f"color: {tint}; font-size: 30px; font-weight: 700;"
            " background: transparent;")

    def set(self, value: str, caption: str = "", color: str | None = None):
        self.value_label.setText(value)
        self.caption_label.setText(caption)
        self._apply_value_style(color)


class _SpanBar(QWidget):
    """一条抽数条（带颜色 + 数值）。

    工坊那条列表的核心视觉：绿=欧、黄=正常、红=非。
    """

    def __init__(self, span: int, parent=None):
        super().__init__(parent)
        self._span = max(0, int(span))
        self.setFixedHeight(BAR_HEIGHT)
        width = min(BAR_MAX, max(28, self._span * BAR_UNIT))
        self.setFixedWidth(width + 44)      # bar + 文字

    def paintEvent(self, event):  # noqa: N802 - Qt 回调
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        color = QColor(gacha.span_color(self._span))
        width = min(BAR_MAX, max(28, self._span * BAR_UNIT))

        painter.setBrush(color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(0, 0, width, BAR_HEIGHT - 4, 4, 4)

        painter.setPen(QColor("#ffffff"))
        font = painter.font()
        font.setPointSize(max(font.pointSize() - 1, 7))
        painter.setFont(font)
        painter.drawText(6, BAR_HEIGHT - 9, f"{self._span}抽")
        painter.end()


class GachaWidget(ScrollArea):
    """抽卡记录分析页面。"""

    def __init__(self, meta=None, parent=None):
        super().__init__(parent)
        self.meta = meta
        self.setObjectName("GachaWidget")
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._thread: FetchThread | None = None
        self._grab_thread: GrabLinkThread | None = None
        self._report: gacha.GachaReport | None = None

        view = QWidget(self)
        view.setObjectName("gachaView")
        self.root = QVBoxLayout(view)
        self.root.setContentsMargins(*PAGE_MARGIN)
        self.root.setSpacing(14)

        self._build(view)

        self.setWidget(view)
        self.setWidgetResizable(True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("#GachaWidget { background: transparent; }")
        self.viewport().setStyleSheet("background: transparent;")

    # ---------------------------------------------------------------- 构建
    def _build(self, view: QWidget) -> None:
        self.root.addWidget(TitleLabel("抽卡记录分析", view))

        note = CaptionLabel(
            "点「获取抽卡记录」自动读取本机游戏记录的链接，也可以自己粘贴。\n"
            "拿到链接后发给库洛官方接口做分析（需要联网）。",
            view,
        )
        note.setTextColor(*MUTED)
        note.setWordWrap(True)
        self.root.addWidget(note)

        # ---- 取链接行：自动获取（主）+ 手动粘贴（兜底）----
        # ⚠ 这里**不能写 Markdown 星号** —— Qt 的 QLabel 不解析 markdown，
        #   写了会原样显示成「**xxx**」（实测踩过）。
        link_row = QWidget(view)
        row = QHBoxLayout(link_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)

        self.grab_button = PrimaryPushButton(
            FluentIcon.SEARCH, "获取抽卡记录", link_row)
        self.grab_button.setToolTip(
            "从本机游戏的日志里读出抽卡记录链接（需要先在本机登录过游戏）")
        self.grab_button.clicked.connect(self.grab_link)
        row.addWidget(self.grab_button)

        self.link_edit = LineEdit(link_row)
        self.link_edit.setPlaceholderText(
            "抽卡记录链接（点左边按钮自动获取，也可手动粘贴）")
        self.link_edit.setClearButtonEnabled(True)
        row.addWidget(self.link_edit, 1)

        self.fetch_button = PushButton(FluentIcon.SYNC, "分析", link_row)
        self.fetch_button.clicked.connect(self.start_fetch)
        row.addWidget(self.fetch_button)
        self.root.addWidget(link_row)

        self.status = CaptionLabel("", view)
        self.status.setTextColor(*MUTED)
        self.status.setWordWrap(True)
        self.root.addWidget(self.status)

        # ---- 总览卡（工坊顶部那块）----
        self.overview_card = CardWidget(view)
        ov = QVBoxLayout(self.overview_card)
        ov.setContentsMargins(20, 16, 20, 16)
        ov.setSpacing(10)

        self.luck_label = SubtitleLabel("—", self.overview_card)
        ov.addWidget(self.luck_label)

        # 第一排：总抽数 / 平均出金
        row1 = QHBoxLayout()
        row1.setSpacing(40)
        self.stat_total = _BigStat("—", "总抽卡数", self.overview_card)
        self.stat_avg = _BigStat("—", "平均出金", self.overview_card)
        row1.addWidget(self.stat_total)
        row1.addWidget(self.stat_avg)
        row1.addStretch(1)
        ov.addLayout(row1)

        # 第二排：不歪率 / 五星数 / 每UP角色 / 每UP武器（工坊那排小字）
        row2 = QHBoxLayout()
        row2.setSpacing(28)
        self.stat_not_up = _BigStat("—", "小保底不歪", self.overview_card)
        self.stat_fives = _BigStat("—", "五星数", self.overview_card)
        self.stat_up_char = _BigStat("—", "每UP角色需", self.overview_card)
        self.stat_up_weapon = _BigStat("—", "每UP武器需", self.overview_card)
        for w in (self.stat_not_up, self.stat_fives,
                  self.stat_up_char, self.stat_up_weapon):
            row2.addWidget(w)
        row2.addStretch(1)
        ov.addLayout(row2)
        self.root.addWidget(self.overview_card)

        # ---- 抽卡总结（卡片墙）----
        self.summary_title = StrongBodyLabel("抽卡总结", view)
        self.root.addWidget(self.summary_title)
        self.summary_note = CaptionLabel("", view)
        self.summary_note.setTextColor(*MUTED)
        self.summary_note.setWordWrap(True)
        self.root.addWidget(self.summary_note)
        self.cards_host = QWidget(view)
        self.cards_grid = QGridLayout(self.cards_host)
        self.cards_grid.setContentsMargins(0, 0, 0, 0)
        self.cards_grid.setSpacing(6)
        self.root.addWidget(self.cards_host)

        # ---- 分卡池明细 ----
        self.pools_title = StrongBodyLabel("分卡池记录", view)
        self.root.addWidget(self.pools_title)
        self.pools_host = QWidget(view)
        self.pools_box = QVBoxLayout(self.pools_host)
        self.pools_box.setContentsMargins(0, 0, 0, 0)
        self.pools_box.setSpacing(8)
        self.root.addWidget(self.pools_host)

        self.root.addStretch(1)
        self._show_empty_hint()

    # ---------------------------------------------------------------- 动作
    def grab_link(self) -> None:
        """点「获取抽卡记录」：从本机日志里读出链接并**自动填充**。

        用户 2026-09-30 要求："上面加个获取抽卡记录按钮，获取到后自动填充"。

        ⚠ 读文件 + 可能全盘扫，**放在后台线程**里跑（全盘扫要几十秒，
        在 UI 线程里跑会把界面冻住）。
        """
        if self._grab_thread is not None and self._grab_thread.isRunning():
            return
        self.grab_button.setEnabled(False)
        self.status.setText("正在从游戏日志里读取抽卡记录链接…")
        self._grab_thread = GrabLinkThread(self)
        self._grab_thread.succeeded.connect(self._on_grabbed)
        self._grab_thread.failed.connect(self._on_grab_failed)
        self._grab_thread.start()

    def _on_grabbed(self, url: str) -> None:
        self.grab_button.setEnabled(True)
        self.link_edit.setText(url)
        self.status.setText("已获取链接 —— 点「分析」开始统计。")

    def _on_grab_failed(self, message: str) -> None:
        self.grab_button.setEnabled(True)
        self.status.setText(message.splitlines()[0])
        InfoBar.warning("没能自动获取", message, duration=8000,
                        parent=self.window())

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
                "读取成功，但这个账号没有任何抽卡记录（或者记录已过期清空）。")
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
        self._clear_layout(self.cards_grid)

    def _show_empty_hint(self) -> None:
        hint = CaptionLabel("还没有数据 —— 粘贴链接后点「读取」。", self.pools_host)
        hint.setTextColor(*MUTED)
        self.pools_box.addWidget(hint)

    def render(self, report) -> None:
        """把报告铺到界面上。"""
        self._clear_results()

        # ---- 总览 ----
        self.stat_total.set(str(report.total), "总抽卡数")
        average = report.average()
        self.stat_avg.set(f"{average:.0f}" if average else "—", "平均出金")
        self.stat_fives.set(str(report.five_count), "五星数")

        not_up = report.not_up_rate()
        self.stat_not_up.set(
            f"{not_up:.1f}%" if not_up is not None else "—", "小保底不歪")

        up_char = report.average_per_up("角色")
        up_weapon = report.average_per_up("武器")
        self.stat_up_char.set(
            f"{up_char:.1f}" if up_char else "—", "每UP角色需")
        self.stat_up_weapon.set(
            f"{up_weapon:.1f}" if up_weapon else "—", "每UP武器需")

        luck = report.luck()
        if luck:
            self.luck_label.setText(luck[0])
            self.luck_label.setTextColor(luck[1], luck[1])
        else:
            self.luck_label.setText("—")

        # ---- 抽卡总结（卡片墙）----
        limited = report.limited_fives()
        permanent = report.permanent_fives()
        self.summary_note.setText(
            f"共获得限定五星 {len(limited)} 个，常驻五星 {len(permanent)} 个。"
            + (f"（常驻：{'、'.join(permanent)}）" if permanent else "")
        )
        self._render_cards(report)

        # ---- 分卡池 ----
        for pool in report.active_pools():
            self.pools_box.addWidget(self._pool_block(pool))
        if not report.active_pools():
            self._show_empty_hint()

    def _render_cards(self, report) -> None:
        """五星卡片墙：每张显示名字 + "抽了几次"角标。

        ⚠ 工坊那里是**头像图**；我们没有干员的抽卡头像素材（那是游戏素材，
        不入库），所以这里用**名字卡片**代替 —— 信息量一样（谁、抽到几次、
        是不是歪出来的），只是没图。
        """
        fives = report.all_fives_analysis()
        if not fives:
            return
        # 统计每个名字出现的次数
        counts: dict[str, int] = {}
        for f in fives:
            if f.name:
                counts[f.name] = counts.get(f.name, 0) + 1

        columns = 10
        for index, (name, count) in enumerate(
                sorted(counts.items(), key=lambda kv: -kv[1])):
            card = CardWidget(self.cards_host)
            card.setFixedSize(64, 64)
            box = QVBoxLayout(card)
            box.setContentsMargins(2, 4, 2, 4)
            box.setSpacing(0)

            label = BodyLabel(name[:4], card)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setWordWrap(True)
            box.addWidget(label, 1)

            if count > 1:
                badge = CaptionLabel(f"×{count}", card)
                badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
                badge.setTextColor("#d4a017", "#d4a017")
                box.addWidget(badge)

            self.cards_grid.addWidget(card, index // columns, index % columns)

    def _pool_block(self, pool) -> QWidget:
        """一个卡池一块：标题 + 每行一个五星（名字 + 抽数条 + 歪标）。"""
        card = CardWidget(self.pools_host)
        box = QVBoxLayout(card)
        box.setContentsMargins(16, 12, 16, 12)
        box.setSpacing(6)

        # 标题行：池名 + 概要
        head = QHBoxLayout()
        head.setSpacing(14)
        title = BodyLabel(pool.name, card)
        title.setFixedWidth(170)
        head.addWidget(title)

        parts = [f"{pool.total} 抽", f"五星 {pool.five_count}",
                 f"出货率 {pool.rate():.1f}%"]
        if pool.total:
            parts.append(f"已垫 {pool.current_pity()} 抽")
        for text in parts:
            head.addWidget(CaptionLabel(text, card))
        head.addStretch(1)

        luck = pool.luck()
        if luck:
            tag = CaptionLabel(luck[0], card)
            tag.setTextColor(luck[1], luck[1])
            head.addWidget(tag)
        box.addLayout(head)

        # 每条五星：时间倒序（最新在最上）
        for five in reversed(pool.fives_analysis()):
            box.addWidget(self._five_row(five, card))
        return card

    def _five_row(self, five, parent) -> QWidget:
        row_widget = QWidget(parent)
        row = QHBoxLayout(row_widget)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)

        name = BodyLabel(five.name or "（未收录）", row_widget)
        name.setFixedWidth(150)
        row.addWidget(name)

        # 抽数条（带颜色）。列表里显示的是 **span**（这个金花了几抽），
        # 不是 cumulative（那是大保底口径，见 gacha.FiveStar 的说明）
        row.addWidget(_SpanBar(five.span, row_widget))

        row.addStretch(1)
        if five.is_lost:
            lost = CaptionLabel("歪", row_widget)
            lost.setTextColor("#c0392b", "#e07070")
            row.addWidget(lost)
        row.addWidget(CaptionLabel(five.time, row_widget))
        return row_widget


@registry.register(
    category=ToolCategory.GAME,
    name="抽卡记录分析",
    description="粘贴抽卡记录链接，统计出货率 / 保底进度 / 歪没歪 / 五星记录",
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
