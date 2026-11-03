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

from PySide6.QtCore import QEvent, QSize, Qt, QThread, Signal
from PySide6.QtGui import QColor, QPainter
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

from ....core import gacha, gacha_history_view, gacha_store, paths
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

#: 列表里每行头像的边长 —— 和配置页/任务行同一个尺寸（48），观感统一
AVATAR_SIZE = 48

#: 卡片墙里每张图的边长（工坊那种方块卡）
CARD_SIZE = 64

#: 卡片墙最多几列（再多一行就长得离谱了，没必要）
MAX_CARD_COLUMNS = 12

#: ★★ 卡池选项卡（用户 2026-10-06）
#:
#:     "这里切换选项卡，展示不同的卡池，选项卡并排展示如
#:      角色活动唤取，武器活动唤取卡池"
#:
#: ⚠ 选中样式**沿用「查询角色练度」那套** —— 用户 2026-10-05 对角色格子
#: 明确要求过"点到那个，哪个下方加一个黄色高亮的粗线"。
#: 这里用**同一个黄**，保持整套界面的视觉语言一致。
SELECT_BORDER = "#f5b301"      # 选中那条粗线的黄（跟练度页同一个色）
SELECT_BAR_H = 4               # 粗线高度（px）
#:
#: ⚠⚠⚠ **文字色不能写死**（用户 2026-10-06："深色皮肤 深色字体 看不见"）
#:
#: 我第一版把选中色写成 ``#1a1a1a``（深灰）—— 浅色皮肤上没问题，
#: **深色皮肤上就完全看不见了**。同一个错误我在皮肤系统里犯过好几次，
#: 教训就是：**文字色一律从当前皮肤取**，绝不写死。


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
            #: ⚠ 这里用 ``load_and_repair``（**会写**）而不是 ``load`` ——
            #: 用户点「分析」本来就是在改数据，顺便把历史遗留问题修掉
            #: 不突兀。**读界面**那条路（``_render_from_history``）
            #: 必须用纯 ``load``，否则打开页面就会偷偷改用户的文件。
            history = store.load_and_repair()
            before = len(history)
            #: ★ 这次拉的是**哪个账号** —— 多账号隔离靠它
            #: （用户 2026-10-06："我要是换个账户了呢"）
            who = str(self._params.get("playerId", "") or "").strip()
            added = 0
            for pool_type, display in gacha.POOLS:
                added += history.merge(
                    raw.get(pool_type, []), pool_type=pool_type,
                    pool_name=display,
                    at=self._params.get("_fetched_at", ""),
                    player_id=who)
            #: ★ 只统计**这个账号**的记录 —— 不给 player_id 会把
            #: 别的号的数据也算进来（那正是这次要修的 bug）
            report = gacha.report_from_records(
                history.all_records(who), player_id=who)
            history.add_snapshot(gacha_store.PullSnapshot(
                at=self._params.get("_fetched_at", "") or "",
                total=report.total, five=report.five_count, added=added,
                player_id=who))
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
        """大数字的样式。字号走 stylesheet（比 setFont 稳）。

        ## ⚠⚠ 兜底色**不能写死**（用户 2026-10-06 报的同类问题）

        原来兜底是 ``#1a1a1a``（深灰）—— 深色皮肤上那五个大数字
        （总抽卡数 / 平均出金 / …）就是**深字压深底**，看不见。

        → 兜底改成从**当前皮肤**取 ``text`` 色。
        """
        if not color:
            from ....core import skins

            try:
                color = skins.active_skin()["text"]
            except (KeyError, TypeError):
                color = "#1a1a1a"           #: 皮肤读不到时的最后兜底
        self.value_label.setStyleSheet(
            f"color: {color}; font-size: 30px; font-weight: 700;"
            " background: transparent;")

    def set(self, value: str, caption: str = "", color: str | None = None):
        self.value_label.setText(value)
        self.caption_label.setText(caption)
        self._apply_value_style(color)


class _PoolTab(QWidget):
    """一个卡池选项卡（**并排**的那一排，选中项下方一条黄粗线）。

    ## 用户 2026-10-06（截图圈出「角色活动唤取」那行）

        "这里切换选项卡，展示不同的卡池，选项卡并排展示如
         角色活动唤取，武器活动唤取卡池"

    原来是**每个池子一张卡片竖着堆**（4 个池就是 4 张大卡，要滚很久）。
    现在改成**一排选项卡**：点哪个，下面只显示那个池的逐条抽数。

    ## ⚠ 选中样式沿用「查询角色练度」那套（用户定过的）

    用户 2026-10-05 对角色格子明确要求过：

        "点到那个，哪个下方加一个黄色高亮的粗线"

    → 这里保持**同一个视觉语言**：选中 = 文字变亮 + 下方一条黄粗线，
    **不是**整块黄底（那是我第一版做错的）。
    """

    clicked = Signal(str)          #: 卡池编号

    def __init__(self, pool_type: str, text: str, parent=None):
        super().__init__(parent)
        self.setObjectName(f"poolTab_{pool_type}")
        self._type = pool_type
        self._selected = False
        self._text = text

        #: ⚠ 让样式表能作用在这个自定义控件上（QWidget 默认不画背景）
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        box = QVBoxLayout(self)
        box.setContentsMargins(12, 6, 12, 6)
        box.setSpacing(4)

        self.label = BodyLabel(text, self)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addWidget(self.label)

        #: ★ 下方那条粗线 —— 选中时**黄**，未选中时透明（占位保持高度一致）
        self.bar = QWidget(self)
        self.bar.setFixedHeight(SELECT_BAR_H)
        box.addWidget(self.bar)

        self._apply()

    def set_selected(self, on: bool) -> None:
        self._selected = bool(on)
        self._apply()

    def showEvent(self, event):  # noqa: N802 - Qt 回调
        """★ 每次显示时**重取一次皮肤色** —— 换肤后自动跟上。

        ## 为什么需要这个

        ``skins._paint`` 只负责"把 QSS 挂到窗口/页面"，
        **不会回调自定义控件**（它不知道有哪些）。所以换肤之后，
        这个选项卡还留着**上一个皮肤**的文字色 —— 表现就是
        用户 2026-10-06 看到的"深色皮肤 深色字体 看不见"。

        → 在 ``showEvent`` 里重取。窗口重建 / 页面切回来都会触发，
        成本只有两次 ``setStyleSheet``（可忽略）。

        ⚠ 光在 ``__init__`` 里取一次是不够的 —— 那时皮肤可能还没应用。
        """
        self._apply()
        super().showEvent(event)

    def _apply(self) -> None:
        """按**当前皮肤**取文字色 —— 深色皮肤用浅字、浅色皮肤用深字。

        ## ⚠⚠⚠ 这里犯过一个错误（用户 2026-10-06）

            "这里又出现了深色皮肤 深色字体 看不见"

        我第一版把选中色写成常量 ``#1a1a1a``（深灰）—— 浅色皮肤上没问题，
        **深色皮肤上就完全看不见**。

        → 改成从 :func:`skins.active_skin` 取（它有 ``text`` / ``dim``），
        这样六款皮肤都自动适配。

        ⚠ 那条**黄线**（``SELECT_BORDER``）是例外，写死没问题 ——
        它是"选中标记"不是文字，在深浅底上都看得见（用户指定的色）。
        """
        from ....core import skins

        try:
            skin = skins.active_skin()
            if self._selected:
                self.label.setStyleSheet(
                    f"color: {skin['text']}; font-weight: 700;")
                self.bar.setStyleSheet(f"background: {SELECT_BORDER};")
            else:
                self.label.setStyleSheet(f"color: {skin['dim']};")
                self.bar.setStyleSheet("background: transparent;")
        except (KeyError, TypeError):
            #: 皮肤字段缺失（理论上不会）→ 退回 Qt 默认色，别崩
            self.label.setStyleSheet("")

    def mouseReleaseEvent(self, event):  # noqa: N802 - Qt 回调
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._type)
        super().mouseReleaseEvent(event)


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


class HistoryCard(QWidget):
    """抽卡历史卡片：一个账号的一个月。

    ## 用户 2026-10-28

    > 以卡片的形式展示，另外我要能够切换

    ## 长什么样

    ::

        ┌────────────────┐
        │ …856011        │   ← 账号（后 6 位）
        │ 2026年10月     │   ← 年月
        │ 960 抽 / 21 金 │   ← 数字
        └────────────────┘

    点一下整张卡 = 选中（黄色边框高亮），并发出
    :attr:`clicked` 信号，页面据此把角色统计切换成这个快照的数据。

    ## 为什么自己做而不用 qfluentwidgets 的 CardWidget

    ``CardWidget`` 没有"选中态"和点击信号，套一层 QPushButton 又会
    让卡片里的多行文字排版变形。这里直接继承 ``QWidget``，
    - 用 ``mousePressEvent`` 收点击
    - 用 ``paintEvent`` 画圆角底 + 选中边框（跟练度页/抽卡页同一套观感）

    ⚠ **必须重写 ``paintEvent`` 而不是只靠 ``setStyleSheet``**：
    ``QWidget`` 的样式表背景默认不绘制，得手动 ``QStyle`` 画。
    """

    clicked = Signal(object)      #: 参数是 MonthlyHistory

    WIDTH = 168
    HEIGHT = 92

    def __init__(self, record, parent=None):
        super().__init__(parent)
        self._record = record
        self._selected = False
        self.setFixedSize(self.WIDTH, self.HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(
            f"{record.month_text}（该月 {record.snapshots} 次拉取）\n"
            f"共 {record.total} 抽 / {record.five} 金\n"
            "点一下：只看这个月的记录")
        #: 里面用 layout 放三行字 —— 比在 paintEvent 里手画文字好维护
        box = QVBoxLayout(self)
        box.setContentsMargins(12, 9, 12, 9)
        box.setSpacing(2)

        who = CaptionLabel(
            gacha_store.account_label(record.player_id), self)
        who.setTextColor(*MUTED)
        box.addWidget(who)

        month = StrongBodyLabel(record.month_text, self)
        box.addWidget(month)

        stats = CaptionLabel(f"{record.total} 抽 / {record.five} 金", self)
        stats.setTextColor(*MUTED)
        box.addWidget(stats)
        box.addStretch(1)

    # ------------------------------------------------------------ 状态
    def set_selected(self, selected: bool) -> None:
        if self._selected == selected:
            return
        self._selected = selected
        self.update()          #: 触发 paintEvent 重画边框

    @property
    def record(self):
        return self._record

    # ------------------------------------------------------------ 事件
    def mousePressEvent(self, event) -> None:      # noqa: N802 - Qt 命名
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._record)
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:           # noqa: N802 - Qt 命名
        """画圆角底 + 选中边框。

        颜色跟 ``GachaWidget`` 里那套皮肤常量保持一致（浅/深色都要能看）。
        """
        from PySide6.QtGui import QPainterPath, QPen

        skin = _skin()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        path = QPainterPath()
        path.addRoundedRect(self.rect().adjusted(1, 1, -1, -1), 8, 8)
        #: ``_skin()`` 已经把这些字段转成 QColor 了
        painter.fillPath(path, skin["card"])

        #: 选中 = 粗黄边；未选中 = 细淡边（保证深色主题下也能看出边界）
        if self._selected:
            pen = QPen(QColor(SELECT_BORDER))
            pen.setWidth(2)
        else:
            pen = QPen(skin["border"])
            pen.setWidth(1)
        painter.setPen(pen)
        painter.drawPath(path)
        painter.end()


def _skin() -> dict:
    """当前皮肤的颜色表（读不到就给浅色兜底）。

    六个皮肤里 ``card`` / ``border`` 有的是 ``rgba(255,255,255,0.72)``
    这种 CSS 写法 —— Qt 的 ``QColor`` 不认，必须走
    :func:`skins.parse_color` 转成 QColor。这里统一转好放在一个
    ``QColor`` 字段里，画的时候直接用。
    """
    from ....core import skins

    try:
        raw = dict(skins.active_skin())
    except Exception:  # noqa: BLE001 - 皮肤系统坏了也不能让历史卡片画不出来
        raw = {}

    def qc(value: str, fallback: str) -> QColor:
        try:
            color = skins.parse_color(value)
            return color if isinstance(color, QColor) else QColor(fallback)
        except Exception:  # noqa: BLE001
            return QColor(fallback)

    return {
        "card": qc(raw.get("card") or "", "#FFFFFF"),
        "border": qc(raw.get("border") or "", "#D8DEE9"),
    }


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
        #: 卡片墙的卡片（建好存着，位置由 _relayout_cards 算）
        self._card_widgets: list[QWidget] = []
        self._card_columns = 0
        #: ★ 历史记录卡片（2026-10-28 改成卡片 + 可切换）
        self._history_cards: list[HistoryCard] = []
        #: 当前选中的历史卡片（``MonthlyHistory`` 或 None）
        self._selected_history = None

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

        # ---- 怎么获取（用户 2026-09-30："上方加上怎么获取抽卡记录的说明"）----
        # ⚠ 这段要**先于按钮**出现：用户卡住的点就是"点按钮没反应怎么办"。
        # ⚠ 别写 Markdown 星号 —— Qt 的 QLabel 不解析 markdown（实测踩过）。
        howto = CaptionLabel(
            "怎么获取：\n"
            "① 点下面「获取抽卡记录」—— 自动从本机游戏日志里读出链接并填好；\n"
            "② 如果没读到，就手动取：游戏里　唤取 → 唤取记录 → "
            "打开页面后多翻几页 → 复制页面链接 → 粘到输入框。\n"
            "⚠ 链接有时效：取完尽快粘过来；放久了会提示「请求游戏获取日志异常」，"
            "那时回游戏重新打开一次唤取记录页再复制即可。",
            view,
        )
        howto.setTextColor(*MUTED)
        howto.setWordWrap(True)
        self.root.addWidget(howto)

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
        # ★ 卡片墙的重排钩在 **cards_host 自己**身上，不是整个页面。
        #
        # ⚠ 挂在页面上没用：页面在 ScrollArea 里，窗口变窄时它**不跟着缩**
        #   （实测：窗口 1300→600，cards_host 一直停在 1226）——
        #   所以宽度变化要直接监听真正承载卡片的那一层。
        self.cards_host.installEventFilter(self)
        self.root.addWidget(self.cards_host)

        # ---- 分卡池明细 ----
        self.pools_title = StrongBodyLabel("分卡池记录", view)
        self.root.addWidget(self.pools_title)

        #: ★★ 卡池**选项卡**（并排；点哪个显示哪个）
        #:
        #: 用户 2026-10-06："这里切换选项卡，展示不同的卡池，
        #: 选项卡并排展示如 角色活动唤取，武器活动唤取卡池"
        #:
        #: ⚠ 原来每个池一张大卡片**竖着堆**（4 个池要滚很久）。
        #: 现在改成这一排 + 下面只渲染选中的那个池。
        self.pool_tabs_host = QWidget(view)
        self.pool_tabs_row = QHBoxLayout(self.pool_tabs_host)
        self.pool_tabs_row.setContentsMargins(0, 0, 0, 0)
        self.pool_tabs_row.setSpacing(8)
        self.root.addWidget(self.pool_tabs_host)

        #: 选项卡 → 控件（切池子时只改选中态，不重建）
        self._pool_tabs: dict[str, _PoolTab] = {}
        #: 当前选中的卡池编号（空 = 还没选）
        self._selected_pool = ""
        #: 这次渲染的全部卡池（切选项卡时从这里取）
        self._pools: dict[str, object] = {}

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
        # ★ 打开页面就把**已累积的历史**显示出来（2026-09-30 修）。
        #   用户报："有数据，为什么没有展示" —— 历史里明明有 887 条，
        #   页面却是空的（统计全是「—」），因为原来**只有点「分析」成功
        #   才会渲染**；一旦这次没取到链接（链接过期 / 没打开唤取记录页），
        #   界面就一直是空的，而数据其实早就攒在本地了。
        self._render_from_history()

    # ---------------------------------------------------------------- 历史
    def _render_from_history(self) -> bool:
        """用本地累积的记录渲染界面。**返回是否渲染了**。

        没有历史 → 保持空状态（返回 False，让"点获取"的引导留在那）。

        ## ★ 多账号（用户 2026-10-06："我要是换个账户了呢"）

        只渲染**最近一次拉取的那个账号**的数据。用户的库里有几个号时，
        换号后再打开页面会**自动切到新号**，不会两个号混着显示。
        """
        try:
            history = self._get_store().load()
        except Exception:  # noqa: BLE001 - 历史坏了不该把页面带崩
            logger.warning("读抽卡历史失败", exc_info=True)
            return False
        if not len(history):
            return False

        #: ★★★ 取**最近一次"认得出账号"的**拉取 —— 用它来筛
        #:
        #: ## ⚠⚠ 这里修过一个真 bug（2026-10-06 自查发现）
        #:
        #: 原来写的是 ``history.snapshots[0].player_id`` —— 但列表**第一条
        #: 可能是"未知账号"**（升级前的旧快照没有 ``player_id``）::
        #:
        #:     snapshots[0].player_id == ""  →  all_records("") == 不过滤
        #:                                   →  **所有账号的数据混在一起**
        #:
        #: 而且 ``if not rows:`` 那个兜底**救不了**：不过滤时 rows 一定非空，
        #: 所以那个分支根本进不去（写了等于没写）。
        #:
        #: → 改成**跳过空账号**，取最近一个有账号的。
        who = ""
        for snap in history.snapshots:
            if snap.player_id:
                who = str(snap.player_id)
                break
        rows = history.all_records(who) if who else history.all_records()
        report = gacha.report_from_records(rows, player_id=who)
        if not report.total:
            return False

        self._report = report
        self.render(report)
        # ⚠ 状态栏要写清"这是**本地累计**，不是这次拉的" ——
        #   否则用户会以为刚点的那一下就拉到了这么多。
        scope = f"（{gacha_store.account_label(who)}）" if who else ""
        self.status.setText(
            f"显示的是本地累计的 {report.total} 抽"
            f"{scope}（{len(rows)} 条记录）。"
            "点「分析」可以把最新记录并进来。")
        return True

    def _get_store(self):
        from ....core.gacha_store import GachaHistoryStore

        if self._store is None:
            self._store = GachaHistoryStore()
        return self._store

    def reload_history(self) -> None:
        """把历史（拉取时间点）铺到界面上；没有就提示一句。

        ⚠ 历史是**每次拉取时累计到了多少**，不是"每次单独的结果" ——
        因为接口只返回最近一段，只有累计才代表账号全貌。

        ## ★ 多账号：每行标出是**哪个号**拉的

        用户 2026-10-06 选了"按账号分开存"，所以要能一眼看出
        每条历史属于哪个账号（切号之后尤其重要）。
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

        #: ★★ 只列**认得出账号**的快照（用户 2026-10-06："未知账号的干掉"）
        #:
        #: 那些是升级到多账号版本**之前**留下的 —— 那时还没有 ``player_id``
        #: 字段，读回来是空串。里面还夹着错误数据（``total=2018`` 那条是
        #: 我修"复制记录"bug 之前拍的）。
        #:
        #: ⚠ 这里**先过滤显示**（纯读，不写盘）—— 用户不用等"下次点分析"
        #: 才看不到它们；真正的删除在 ``repair()`` 里（写路径）做。
        known = ([s for s in history.snapshots if s.player_id]
                 if history is not None else [])
        if not known:
            hint = CaptionLabel(
                "还没有历史 —— 点「分析」后会按时间记下来。", self.history_host)
            hint.setTextColor(*MUTED)
            self.history_box.addWidget(hint)
            return

        total = len(history)
        #: ★ 多账号：说清**每个号各多少条** —— 只写一个总数用户会以为
        #: 都是当前号的（用户 2026-10-06 选了"按账号分开存"）
        players = history.players()
        if len(players) > 1:
            detail = "、".join(
                f"{gacha_store.account_label(w)} {history.player_count(w)} 条"
                for w in players[:4])
            note_text = (f"本地已累积 {total} 条记录，分属 {len(players)} 个账号："
                         f"{detail}。每分析一次就把新记录并进来。")
        else:
            note_text = (f"本地已累积 {total} 条记录（每分析一次就把新记录"
                         "并进来，所以数字会随时间变多）。")
        note = CaptionLabel(note_text, self.history_host)
        note.setTextColor(*MUTED)
        note.setWordWrap(True)
        self.history_box.addWidget(note)

        #: ★★★ 2026-10-28 用户：「历史记录按时间和账号维度统计，
        #: 同一账号不同时间内，数据一样就用最新时间，不一样就合并，
        #: 时间显示 xxxx年xx月」「以卡片的形式展示，另外我要能够切换」
        #:
        #: 按 **(账号, 年月)** 聚合（见 gacha_history_view 的模块文档），
        #: 每个组合渲染成**一张可点的卡片**：
        #:   * 点一下 → 下面的统计切到那个快照的账号
        #:   * 选中的卡片黄色粗边框（跟练度页/抽卡页同一套观感）
        #:   * 卡片横向排，超过宽度自动换行
        monthly = gacha_history_view.group_by_account_month(known)
        self._history_cards = []
        cards_host = QWidget(self.history_host)
        cards_box = QGridLayout(cards_host)
        cards_box.setContentsMargins(0, 6, 0, 0)
        cards_box.setHorizontalSpacing(10)
        cards_box.setVerticalSpacing(10)
        #: 一行放几张 —— 按页面可用宽度估（卡片 168 + 间距 10）
        per_row = 4
        for index, item in enumerate(monthly):
            card = HistoryCard(item, cards_host)
            card.clicked.connect(self._on_history_selected)
            #: ★ 默认选中**第一张**（最新那个月的账号）——
            #: 用户打开页面就想看最近的数据，不该让他先点一下。
            if index == 0:
                card.set_selected(True)
                self._selected_history = item
            self._history_cards.append(card)
            cards_box.addWidget(card, index // per_row, index % per_row)
        #: 最后补一个空列撑开，卡片不会被拉成平均宽度
        if monthly:
            cards_box.setColumnStretch(len(monthly) % per_row or per_row, 1)
        self.history_box.addWidget(cards_host)

        #: ⚠ 聚合后还有"被折叠掉了多少条"要说明白 ——
        #: 否则用户会以为"我拉过 20 次，怎么只剩 3 行"是丢了数据。
        folded = len(known) - sum(item.snapshots for item in monthly)
        if monthly and folded > 0:
            tip = CaptionLabel(
                f"（同一账号同一个月的 {folded + len(monthly)} 次拉取已按月份合并，"
                f"数字取该月最大，时间取最晚一次）", self.history_host)
            tip.setTextColor(*MUTED)
            tip.setWordWrap(True)
            self.history_box.addWidget(tip)

    # ------------------------------------------------------------ 历史切换
    def _on_history_selected(self, record) -> None:
        """点了某张历史卡片 → 把统计切到那个账号的数据。

        ## 用户 2026-10-28

        > 以卡片的形式展示，另外我要能够切换

        ## 切什么

        卡片代表「一个账号的一个月」。点它要做的：

        1. **高亮**这张卡（其余取消）
        2. 用那个账号的记录**重新渲染**统计区块
        3. 状态栏说清"你正在看哪个号的哪个月"

        ## ⚠ 为什么按账号取记录，而不是按月份筛

        ``gacha_store`` 只存**累计记录**（每条有 ``time`` 但没按月索引），
        按月筛要把 2000 多条记录逐条解析时间。而用户点卡片的动机是
        **「换个号看」** —— 账号维度才是他真正要切的。月份只是标签。

        所以这里按 ``player_id`` 取全部记录重画，月份仅用于**显示**
        （说明"你点的是 2026年10月 那张卡"）。
        """
        if record is None:
            return
        self._selected_history = record
        #: 1. 高亮切换
        for card in self._history_cards:
            card.set_selected(card.record is record)
        #: 2. 按账号重画
        who = str(record.player_id or "")
        try:
            history = self._get_store().load()
            rows = history.all_records(who) if who else history.all_records()
        except Exception:  # noqa: BLE001 - 读不到就维持现状
            logger.warning("切换历史账号时读取失败", exc_info=True)
            return
        if not rows:
            self.status.setText(
                f"{record.month_text} 没有可显示的单条记录。")
            return
        report = gacha.report_from_records(rows, player_id=who)
        self._report = report
        self.render(report)
        #: 3. 状态栏说明当前在看什么
        label = gacha_store.account_label(who) if who else "未知账号"
        self.status.setText(
            f"正在看 [{label}] {record.month_text} 的快照："
            f"共 {record.total} 抽 / {record.five} 金"
            f"（本地累计 {report.total} 抽 / {len(rows)} 条记录）。"
            "点别的卡片可以切换账号。")

    def clear_history(self) -> None:
        """清空本地累积记录（用户要求能重置）。

        ⚠ 多账号（2026-10-06）：这是**所有账号**的记录一起清掉 ——
        确认框里要说清楚，别让用户以为是只清当前号。
        """
        players = []
        try:
            players = self._get_store().load().players()
        except Exception:  # noqa: BLE001
            pass

        detail = ""
        if len(players) > 1:
            detail = ("\n\n⚠ 这会清掉**全部 %d 个账号**的记录：%s"
                      % (len(players),
                         "、".join(gacha_store.account_label(w)
                                   for w in players[:4])))
        box = MessageBox(
            "清空抽卡历史",
            "删掉本地累积的全部抽卡记录？\n"
            "下次「分析」会重新从接口拉最近一段，之前的累积就没了。"
            + detail,
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

        # ---- 分卡池（选项卡）----
        self._build_pool_tabs(report)

    def _build_pool_tabs(self, report) -> None:
        """建那一排卡池选项卡，然后渲染**选中的那个**池。

        ## 用户 2026-10-06

            "这里切换选项卡，展示不同的卡池，选项卡并排展示如
             角色活动唤取，武器活动唤取卡池"

        ## ⚠ 只显示**抽过的**池

        ``report.active_pools()`` 已经过滤掉了没记录的池（7 个池全列出来
        会有 4 个是空的，那一排按钮就显得很废）。
        """
        self._clear_layout(self.pool_tabs_row)
        self._pool_tabs = {}
        self._pools = {}

        pools = report.active_pools()
        for pool in pools:
            self._pools[str(pool.pool_type)] = pool

        if not pools:
            self._show_empty_hint()
            return

        for pool in pools:
            tab = _PoolTab(str(pool.pool_type), pool.name,
                           self.pool_tabs_host)
            tab.clicked.connect(self.select_pool)
            self.pool_tabs_row.addWidget(tab)
            self._pool_tabs[str(pool.pool_type)] = tab
        self.pool_tabs_row.addStretch(1)

        #: 保持用户之前选的池（重新分析后不要跳回第一个）；
        #: 那个池没了（比如这次没抽）就退回第一个。
        keep = self._selected_pool if self._selected_pool in self._pools else ""
        self.select_pool(keep or str(pools[0].pool_type))

    def select_pool(self, pool_type: str) -> None:
        """切到某个卡池：更新选项卡选中态 + 只渲染那个池的明细。"""
        if pool_type not in self._pools:
            return
        self._selected_pool = pool_type

        for ptype, tab in self._pool_tabs.items():
            tab.set_selected(ptype == pool_type)

        self._clear_layout(self.pools_box)
        self.pools_box.addWidget(self._pool_block(self._pools[pool_type]))

    def refresh_skin_colors(self) -> None:
        """★ 换肤后重取一次配色（选项卡文字 + 顶部大数字）。

        ## 为什么需要它

        ``skins._paint`` 只把 QSS 挂到**窗口 / 页面**那一层，
        **不会回调自定义控件** —— 它不知道有哪些。

        所以换肤之后，这个页面里那些"自己设 ``setStyleSheet`` 的控件"
        （选项卡标签、``_BigStat`` 的大数字）还留着**上一个皮肤**的色 ——
        表现就是用户 2026-10-06 看到的"深色皮肤 深色字体 看不见"。

        ⚠ 选项卡自己在 ``showEvent`` 里也会重取（页面切回来时能自愈），
        但大数字没有那个时机，所以这里统一刷一遍。
        """
        for tab in self._pool_tabs.values():
            tab._apply()                     # noqa: SLF001 - 同模块内的刷新
        for stat in (self.stat_total, self.stat_avg, self.stat_fives,
                     self.stat_not_up, self.stat_up_char, self.stat_up_weapon):
            stat._apply_value_style(None)    # noqa: SLF001 - 重取皮肤色

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

        # ★ 卡片**先建好存起来**，位置由 _relayout_cards() 单独算。
        #
        # ⚠ 不在这里算列数 —— 构造页面时控件还没被布局过，
        #   ``cards_host.width()`` 拿到的是**默认尺寸**（实测 624px，
        #   而窗口实际是 1226px），于是列数算成 1，
        #   卡片全被竖着排成一列（用户 2026-10-01 截图：
        #   "这个怎么竖着展示了，这个横着展示就行"）。
        #   而且 Qt 的 QGridLayout **不会**在窗口变宽后自己重排 ——
        #   算错了就一直是错的。
        self._card_widgets = [
            self._five_card(name, count, kinds.get(name, ""))
            for name, count in sorted(counts.items(), key=lambda kv: -kv[1])
        ]
        self._relayout_cards()

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 - Qt 回调
        """``cards_host`` 尺寸一变就重排卡片墙。

        ⚠ 用事件过滤器而不是重写 ``resizeEvent``：``cards_host`` 是个**普通
        QWidget**，为了重排单独给它派生子类不值得；而且页面的 resizeEvent
        拿不到它的宽度变化（见 ``_build`` 里的说明）。
        """
        # ⚠ 过滤器是**在 _build 之前**就装上的，那时 cards_host 还不存在 ——
        #   直接访问会 AttributeError（实测：Python override 里抛异常会打断 Qt）。
        host = getattr(self, "cards_host", None)
        if host is not None and obj is host \
                and event.type() == QEvent.Type.Resize:
            self._relayout_cards()
        return super().eventFilter(obj, event)

    def _relayout_cards(self) -> None:
        """按**当前**容器宽度把卡片摆成网格（容器宽度变了就重排）。"""
        cards = getattr(self, "_card_widgets", None)
        if not cards:
            return

        spacing = self.cards_grid.spacing()
        avail = self.cards_host.width()
        columns = max(1, (avail + spacing) // (CARD_SIZE + spacing))
        columns = min(columns, MAX_CARD_COLUMNS)
        if columns == getattr(self, "_card_columns", None) \
                and self.cards_grid.count() == len(cards):
            return                       # 列数没变就不折腾

        self._card_columns = columns
        while self.cards_grid.count():
            self.cards_grid.takeAt(0)    # 只摘布局项，卡片本身留着复用
        for index, card in enumerate(cards):
            self.cards_grid.addWidget(card, index // columns, index % columns)

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

        ## ⚠ 池名不再重复显示（2026-10-06 改成选项卡之后）

        上面那排选项卡已经写着池名了，这里再来一个就是重复。
        概要那几个数字（总抽/五星/出货率/垫抽）留着 —— 那是选项卡上没有的。
        """
        card = CardWidget(self.pools_host)
        box = QVBoxLayout(card)
        box.setContentsMargins(16, 12, 16, 12)
        box.setSpacing(4)

        # 标题行：概要 + 当前垫抽
        head = QHBoxLayout()
        head.setSpacing(14)

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
