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

import logging

from PySide6.QtCore import QSize, Qt, QThread, Signal
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
    MessageBox,
    PrimaryPushButton,
    PushButton,
    ScrollArea,
    StrongBodyLabel,
    SubtitleLabel,
    TitleLabel,
)

from ....core import gacha, paths
from ....core.categories import ToolCategory
from ....core.registry import registry
from ....core.tool_base import BaseTool

logger = logging.getLogger(__name__)


def _now() -> str:
    """当前时间（历史记录的时间点），和项目其它地方同一个格式。"""
    from datetime import datetime

    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

#: 说明文字颜色（(浅色, 深色)）—— 和其它页同一套灰
MUTED = ("#8A8F98", "#7C7C7C")
#: 强调色（大数字）
ACCENT = ("#1a1a1a", "#f0f0f0")

PAGE_MARGIN = (36, 32, 36, 28)

#: 抽数条的宽度（像素/抽）。60 抽的条 = 60*3.2 ≈ 192px，接近头像宽度
BAR_UNIT = 3.2
#: 条的最大 / 最小宽度。最短也给到 76px —— 否则「1抽」的条只有几个像素，
#: 数字都写不下（用户要求"调粗一些，跟角色头像宽度差不多宽"）
BAR_MAX = 300
BAR_MIN = 76
#: 条的高度 —— 接近头像（48），这样整行看着厚实（原来是 18，太细）
BAR_HEIGHT = 34


def bar_width(span: int) -> int:
    """抽数 → 条的像素宽度（夹在 :data:`BAR_MIN` ~ :data:`BAR_MAX` 之间）。"""
    return int(min(BAR_MAX, max(BAR_MIN, max(0, int(span)) * BAR_UNIT)))


#: 星级角标颜色
STAR_COLORS = {5: "#d4a017", 4: "#9b59b6", 3: "#5a8fd4"}

#: 列表里每行头像的边长 —— 和配置页/任务行同一个尺寸（48），观感统一
AVATAR_SIZE = 48

#: 卡片墙里每张图的边长（工坊那种方块卡）
CARD_SIZE = 64


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
    """后台拉取全部卡池，**并合并进本地历史**。

    ★ 合并这一步在这里（线程里）做，而不是主线程：
    写盘 + 合并上千条记录有开销，放主线程会把界面卡一下。

    信号带回 ``GachaReport`` —— 那是**合并后**的累计统计（不是这一次拉到的），
    因为接口只给最近一段，只有累计才代表账号的真实全貌。
    """

    message = Signal(str)
    succeeded = Signal(object, object)   # (GachaReport, 新增条数报告 dict)
    failed = Signal(str)

    def __init__(self, params: dict, store=None, parent=None):
        super().__init__(parent)
        self._params = params
        self._store = store

    def run(self) -> None:  # noqa: D102 - QThread 接口
        from ....core import gacha_store

        try:
            raw = gacha.fetch_raw(self._params,
                                  log=lambda m: self.message.emit(m))
        except gacha.GachaError as exc:
            # 这类消息是**写给用户看的**（"记录过期，请打开唤取记录页"），
            # 不加异常类名前缀
            self.failed.emit(str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - 线程里抛异常必须带出来
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return

        # 合并进历史（按身份去重），再落盘
        try:
            store = self._store or gacha_store.GachaHistoryStore()
            history = store.load()
            before = len(history)
            added = 0
            for pool_type, display in gacha.POOLS:
                added += history.merge(
                    raw.get(pool_type, []), pool_type=pool_type,
                    pool_name=display,
                    at=self._params.get("_fetched_at", ""))
            report = gacha.report_from_records(
                history.all_records(),
                player_id=self._params.get("playerId", ""))
            history.add_snapshot(gacha_store.PullSnapshot(
                at=self._params.get("_fetched_at", "") or "",
                total=report.total, five=report.five_count, added=added))
            store.save(history)
        except Exception as exc:  # noqa: BLE001 - 存历史失败不该让"分析"白跑
            logger.warning("抽卡历史合并/保存失败", exc_info=True)
            self.message.emit(f"⚠ 历史记录保存失败（{exc}），本次只显示接口返回的部分")
            report = gacha.report_from_raw(
                raw, player_id=self._params.get("playerId", ""))
            added, before = 0, 0

        self.succeeded.emit(report, {"added": added,
                                     "before": before,
                                     "stored": len(history)})


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

    ★ 2026-09-30 按用户要求调粗调高：
    "这种横条太细了，调粗一些，跟角色头像宽度差不多宽" ——
    所以高度接近头像（``BAR_HEIGHT``），最短也保证能看清数字。
    """

    def __init__(self, span: int, parent=None):
        super().__init__(parent)
        self._span = max(0, int(span))
        self.setFixedHeight(BAR_HEIGHT)
        self.setFixedWidth(bar_width(self._span))

    def paintEvent(self, event):  # noqa: N802 - Qt 回调
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        color = QColor(gacha.span_color(self._span))

        painter.setBrush(color)
        painter.setPen(Qt.PenStyle.NoPen)
        # 圆角跟着高度走，看起来是"胶囊条"（工坊那种）
        radius = max(4, (BAR_HEIGHT - 6) // 2)
        painter.drawRoundedRect(0, 3, bar_width(self._span), BAR_HEIGHT - 6,
                                radius, radius)

        painter.setPen(QColor("#ffffff"))
        font = painter.font()
        font.setPointSize(max(font.pointSize() + 1, 9))
        font.setBold(True)
        painter.setFont(font)
        text = f"{self._span}抽"
        metrics = painter.fontMetrics()
        painter.drawText(
            (bar_width(self._span) - metrics.horizontalAdvance(text)) // 2,
            (BAR_HEIGHT + metrics.ascent() - metrics.descent()) // 2,
            text)
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
        #: 历史存储（懒建 —— 测试可以换成临时目录）
        self._store = None

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

        # ---- 历史记录（拉取时间点）----
        # 用户 2026-09-30 要求"按时间保存为一个历史记录"。
        # 底层是**合并累积**（接口只给最近一段，不累积就永远看不全），
        # 这里列的是"每次拉取时累计到了多少"。
        history_row = QHBoxLayout()
        history_row.setContentsMargins(0, 0, 0, 0)
        self.history_title = StrongBodyLabel("历史记录", view)
        history_row.addWidget(self.history_title)
        history_row.addStretch(1)
        self.clear_history_button = PushButton("清空历史", view)
        self.clear_history_button.setFixedWidth(96)
        self.clear_history_button.setToolTip(
            "删掉本地累积的全部抽卡记录（不可撤销）")
        self.clear_history_button.clicked.connect(self.clear_history)
        history_row.addWidget(self.clear_history_button)
        self.root.addLayout(history_row)

        self.history_host = QWidget(view)
        self.history_box = QVBoxLayout(self.history_host)
        self.history_box.setContentsMargins(0, 0, 0, 0)
        self.history_box.setSpacing(4)
        self.root.addWidget(self.history_host)

        self.root.addStretch(1)
        self._show_empty_hint()
        self.reload_history()

    # ---------------------------------------------------------------- 历史
    def _get_store(self):
        from ....core.gacha_store import GachaHistoryStore

        if self._store is None:
            self._store = GachaHistoryStore()
        return self._store

    def reload_history(self) -> None:
        """把历史（拉取时间点）铺到界面上；没有就提示一句。

        ⚠ 历史是**每次拉取时累计到了多少**，不是"每次单独的结果" ——
        因为接口只返回最近一段，只有累计才代表账号全貌。
        """
        while self.history_box.count():
            item = self.history_box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

        try:
            history = self._get_store().load()
        except Exception:  # noqa: BLE001 - 历史坏了不该把页面带崩
            history = None

        if history is None or not history.snapshots:
            hint = CaptionLabel(
                "还没有历史 —— 点「分析」后会按时间记下来。", self.history_host)
            hint.setTextColor(*MUTED)
            self.history_box.addWidget(hint)
            return

        total = len(history)
        note = CaptionLabel(
            f"本地已累积 {total} 条记录（每分析一次就把新记录并进来，"
            "所以数字会随时间变多）。", self.history_host)
        note.setTextColor(*MUTED)
        note.setWordWrap(True)
        self.history_box.addWidget(note)

        for snapshot in history.snapshots[:20]:      # 只列最近 20 次，够看
            row = CaptionLabel("· " + snapshot.describe(), self.history_host)
            row.setTextColor(*MUTED)
            self.history_box.addWidget(row)

    def clear_history(self) -> None:
        """清空本地累积记录（用户要求能重置）。"""
        box = MessageBox(
            "清空抽卡历史",
            "删掉本地累积的全部抽卡记录？\n"
            "下次「分析」会重新从接口拉最近一段，之前的累积就没了。",
            self.window())
        box.yesButton.setText("清空")
        box.cancelButton.setText("取消")
        if not box.exec():
            return
        try:
            from ....core.gacha_store import GachaHistory

            self._get_store().save(GachaHistory())
        except Exception:  # noqa: BLE001
            logger.warning("清空抽卡历史失败", exc_info=True)
        self._report = None
        self._clear_results()
        self.status.setText("历史已清空。")
        self.reload_history()

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
        # 拉取时刻写进参数，线程合并历史时用它当时间点
        params = dict(params)
        params["_fetched_at"] = _now()
        self._thread = FetchThread(params, self._get_store(), self)
        self._thread.message.connect(self.status.setText)
        self._thread.succeeded.connect(self._on_ok)
        self._thread.failed.connect(self._on_fail)
        self._thread.start()

    def _on_ok(self, report, info) -> None:
        self._report = report
        self.fetch_button.setEnabled(True)
        self.reload_history()
        if not report.total:
            self.status.setText(
                "读取成功，但这个账号没有任何抽卡记录（或者记录已过期清空）。")
            return
        added = int((info or {}).get("added") or 0)
        stored = int((info or {}).get("stored") or report.total)
        if added:
            self.status.setText(
                f"读取完成：本地累计 {stored} 抽（本次新增 {added} 条）。")
        else:
            # 接口给的那一段和已有的完全重叠 —— 说明没出新记录，不是出错
            self.status.setText(
                f"读取完成：本地累计 {stored} 抽（本次没有新记录，"
                "和已有的完全重合）。")
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
        """五星卡片墙：**图片** + 右上角"抽到几次"角标（工坊那个视觉）。

        用户 2026-09-30："这些换成图片，这些素材街区也完全可以取到的，
        同样这些素材东西可以放到资源库"。

        图片来自：
        * 角色 → ``assets/game/avatars/<角色名>.png``（``game_data`` 查）
        * 武器 → ``assets/game/weapons/<武器名>.png``

        拿不到图就用**首字圆图**兜底（同一套 ``avatar_icon``），不留白 ——
        否则卡片墙会缺一块、看起来像坏了。
        """
        fives = report.all_fives_analysis()
        if not fives:
            return

        # 统计每个名字出现的次数（还要记住它的 kind，决定去哪查图）
        counts: dict[str, int] = {}
        kinds: dict[str, str] = {}
        for f in fives:
            if not f.name:
                continue
            counts[f.name] = counts.get(f.name, 0) + 1
            kinds.setdefault(f.name, f.kind)

        columns = max(1, (self.cards_host.width() or 900) // (CARD_SIZE + 8))
        columns = min(columns, 12)
        for index, (name, count) in enumerate(
                sorted(counts.items(), key=lambda kv: -kv[1])):
            self.cards_grid.addWidget(
                self._five_card(name, count, kinds.get(name, "")),
                index // columns, index % columns)

    def _five_card(self, name: str, count: int, kind: str) -> QWidget:
        """一张五星卡片：图片铺满 + 右上角 ×N 角标。

        ⚠ ``IconWidget(parent)`` **只有 parent 一个参数**（实测），
        尺寸靠 ``setFixedSize``；它自己会把图标缩放到控件大小，
        没有 ``setScaledContents`` / ``setBorderRadius`` 这些方法。
        """
        from qfluentwidgets import IconWidget

        card = QWidget(self.cards_host)
        card.setFixedSize(CARD_SIZE, CARD_SIZE)

        icon = self._icon_for(name, kind)
        view = IconWidget(card)
        view.setIcon(icon)
        view.setFixedSize(CARD_SIZE, CARD_SIZE)
        view.move(0, 0)

        # 名字：图片底下压一行小字，鼠标悬停也能看全名
        card.setToolTip(f"{name}　×{count}")

        if count > 1:
            badge = CaptionLabel(f"×{count}", card)
            badge.setTextColor("#ffffff", "#ffffff")
            badge.setStyleSheet(
                "background: rgba(0,0,0,0.6); border-radius: 7px;"
                " padding: 0 4px; font-weight: 700;")
            badge.adjustSize()
            badge.move(CARD_SIZE - badge.width() - 2, 2)
        return card

    @staticmethod
    def _icon_for(name: str, kind: str = ""):
        """名字 → QIcon（角色查头像、武器查武器图，都没有就首字兜底）。"""
        from ....core import game_data
        from ....gui.pickers import avatar_icon

        try:
            if kind == "武器":
                return avatar_icon(f"weapons/{name}.png", name)
            info = game_data.find_character(name)
            return avatar_icon(info.avatar if info else "", name)
        except Exception:  # noqa: BLE001 - 资料没加载好也不该让卡片建不出来
            return avatar_icon("", name)

    def _pool_block(self, pool) -> QWidget:
        """一个卡池一块：标题行 + **逐条五星**（头像 + 抽数条 + 歪标 + 时间）。

        ★ 这是工坊那条列表的核心视觉（用户 2026-09-30："差在逐条抽数条列表"）：

            [头像] ████████████ 68抽                    (歪)
            [头像] ██████ 33抽
            [头像] ███████████████ 81抽                 (歪)

        条的**长度**按抽数走、**颜色**按欧非分级（绿→黄→红）。
        """
        card = CardWidget(self.pools_host)
        box = QVBoxLayout(card)
        box.setContentsMargins(16, 12, 16, 12)
        box.setSpacing(4)

        # 标题行：池名 + 概要 + 当前垫抽
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

        # 分隔线（工坊那里也有一条）
        line = QWidget(card)
        line.setFixedHeight(1)
        line.setStyleSheet("background: rgba(128,128,128,0.25);")
        box.addWidget(line)

        # 每条五星：时间倒序（最新在最上）
        fives = list(reversed(pool.fives_analysis()))
        if not fives:
            empty = CaptionLabel("这个池还没出过五星。", card)
            empty.setTextColor(*MUTED)
            box.addWidget(empty)
            return card
        for five in fives:
            box.addWidget(self._five_row(five, card))
        return card

    def _five_row(self, five, parent) -> QWidget:
        """一条五星记录：**头像 + 抽数条 + 歪/欧/非**。

        ★ 2026-09-30 用户要求：
        "这种横条太细了，调粗一些，跟角色头像宽度差不多宽，
        **然后歪、欧、非就写在横条后，时间就不要了**"。

        所以这里：
        * 条在左边（宽度见 :func:`bar_width`，高度接近头像）；
        * 条**紧跟着**就是评价文字（歪 / 欧 / 非），不再用 stretch 顶到最右；
        * **不再显示时间**（用户明确不要）。
        """
        row_widget = QWidget(parent)
        row = QHBoxLayout(row_widget)
        row.setContentsMargins(0, 3, 0, 3)
        row.setSpacing(10)

        # 头像（拿不到就留一个等宽占位，保持左边对齐）
        avatar = self._five_avatar(five, row_widget)
        row.addWidget(avatar, 0, Qt.AlignmentFlag.AlignVCenter)

        # 抽数条：显示 **span**（这个金花了几抽），不是 cumulative
        # （cumulative 是大保底口径，见 gacha.FiveStar 的说明）
        row.addWidget(_SpanBar(five.span, row_widget), 0,
                      Qt.AlignmentFlag.AlignVCenter)

        # 评价文字：紧跟在条后面（歪 / 欧 / 非 三选一，常驻池不标歪）
        text, color = self._verdict(five)
        if text:
            verdict = BodyLabel(text, row_widget)
            verdict.setTextColor(color, color)
            row.addWidget(verdict, 0, Qt.AlignmentFlag.AlignVCenter)

        row.addStretch(1)
        return row_widget

    @staticmethod
    def _verdict(five) -> tuple[str, str]:
        """这条五星的评价：**歪 / 欧 / 非**（用户要写在条后面）。

        * **歪**：限定池里出了非 UP（最优先，用户最关心这个）
        * **欧 / 非**：按这次用了多少抽分级（和条的颜色同一套阈值）
        * 常驻池不判"歪"（没有 UP 概念），只按欧非分级

        阈值复用 :data:`src.core.gacha.SPAN_COLORS` 的思路：
        ≤60 抽算欧、≥74 抽算非，中间不标（正常出货不值得标）。
        """
        if five.is_lost:
            return "歪", "#c0392b"
        span = int(five.span or 0)
        if span <= 60:
            return "欧", "#2e8b57"
        if span >= 74:
            return "非", "#c0392b"
        return "", ""

    def _five_avatar(self, five, parent) -> QWidget:
        """五星的头像 —— 和卡片墙**共用** :meth:`_icon_for`，别各写一份。

        ⚠ 这里原来给武器传的是**空路径**（``avatar_icon("", name)``），
        于是武器永远显示首字兜底图 —— 用户截图里「云」「千」就是这么来的
        （"这里怎么不改掉"）。**卡片墙改了、列表行忘了改**，
        正是"两处各写一份"的典型后果；现在统一走 :meth:`_icon_for`。
        """
        from qfluentwidgets import IconWidget

        holder = IconWidget(self._icon_for(five.name, five.kind), parent)
        holder.setFixedSize(QSize(AVATAR_SIZE, AVATAR_SIZE))
        return holder


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
    #: 自带图标（2026-09-30 用户提供的一整套）
    icon_path = str(paths.resource_dir("assets", "icons", "gacha.png"))
    #: ⚠ BaseTool 默认 ``coming_soon = True``（显示"即将到来"占位页）——
    #: 这个工具是**真做完了的**，必须显式关掉，否则点进去还是占位页。
    coming_soon = False
    #: 不参与任务流程：它不操作游戏，是"查数据"的工具
    supports_task_run = False

    def create_widget(self, parent=None):
        return GachaWidget(self.meta(), parent)
