# -*- coding: utf-8 -*-
"""侧栏「消息」页 —— 最近的通知，**卡片形式**列出来。

用户 2026-10-10 要求::

    "左侧边栏增加消息通知功能，用来储存最近发的通知，最多储存10条，
     每天自动清理，也可手动清理，每个任务完成/失败都要进行通知，
     声骸批量调频、声骸自动强化等工具完成/失败时也要通知"

## 页面长什么样

::

    ┌──────────────────────────────────────────────┐
    │ 消息                        [清空全部 (3)]     │
    │ 最近的通知，最多留 10 条，每天自动清理。        │
    │ ┌──────────────────────────────────────────┐ │
    │ │ ✔ 声骸自动强化 · 完成            14:23    │ │
    │ │   判定 42 个 · 符合条件 3 · 弃置 39       │ │
    │ └──────────────────────────────────────────┘ │
    │ ┌──────────────────────────────────────────┐ │
    │ │ ✖ 声骸批量调频 · 失败            13:02    │ │
    │ │   找不到 强化并调谐                        │ │
    │ └──────────────────────────────────────────┘ │
    └──────────────────────────────────────────────┘

## ⚠ 三条本仓的固定写法（都踩过）

1. **必须继承 ``ScrollArea`` 并 ``setWidget(view)``** —— 用裸 ``QWidget``
   整页不显示（``100x30``、切过去空白）。皮肤页第一版就栽在这。
2. **颜色跟皮肤算**，不写死 —— 本仓有 ``TestNoHardcodedLightBackground``
   按亮度扫全仓的 ``background:``（深色皮肤下发白）。
3. **提供 ``refresh_skin_colors()``** —— 换肤时 ``skins`` 会沿控件树调它
   （见 ``skins.SKIN_REFRESH_METHOD``），页面里的自绘控件要自己重取色。
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    MessageBox,
    PushButton,
    StrongBodyLabel,
)

from ..core import notifications as N
from ..core import skins
from .compat import ScrollArea

logger = logging.getLogger(__name__)

#: 三种级别 → (圆点字符, 颜色)
#:
#: ⚠ 颜色**不写死**在这里 —— 深色皮肤下要换一档（见 :func:`level_color`）。
_LEVEL_MARK = {
    N.LEVEL_SUCCESS: "✔",
    N.LEVEL_ERROR: "✖",
    N.LEVEL_INFO: "•",
}

#: (浅色皮肤用的色, 深色皮肤用的色)
_LEVEL_COLORS = {
    N.LEVEL_SUCCESS: ("#1a7f37", "#5fd07a"),
    N.LEVEL_ERROR: ("#c42b1c", "#ff8a80"),
    N.LEVEL_INFO: ("#4a5568", "#a9b4c8"),
}


def level_color(level: str) -> str:
    """级别 → 当前皮肤下合适的颜色（深色皮肤用亮一档，否则看不见）。"""
    light, dark = _LEVEL_COLORS.get(level, _LEVEL_COLORS[N.LEVEL_INFO])
    try:
        return dark if skins.active_skin()["mode"] == "dark" else light
    except (KeyError, TypeError, AttributeError):
        return light


def main_text_color() -> str:
    """正文色（跟皮肤）。"""
    try:
        return skins.active_skin()["text"]
    except (KeyError, TypeError, AttributeError):
        return "#1f2937"


def dim_text_color() -> str:
    """次要文字色（跟皮肤）。"""
    try:
        return skins.active_skin()["dim"]
    except (KeyError, TypeError, AttributeError):
        return "#8a8f98"


def card_bg_color() -> str:
    """卡片底色 —— **实心**（半透明的玻璃色铺在列表里会糊成一片）。

    ⚠ 跟练度详情页的 ``solid_card_color`` 同一个做法、同一个理由。
    """
    try:
        skin = skins.active_skin()
        return skins.solid_card_on(skin["card"], skin["bg"][0][1],
                                   skin["mode"] == "dark")
    except (KeyError, TypeError, AttributeError):
        return "#f7f7f7"


class NoticeCard(CardWidget):
    """一条消息的卡片：级别标记 + 标题 + 时间 + 正文。"""

    def __init__(self, notice: N.Notice, parent=None):
        super().__init__(parent)
        self.notice = notice
        self.setObjectName("noticeCard")

        box = QVBoxLayout(self)
        box.setContentsMargins(16, 12, 16, 12)
        box.setSpacing(4)

        # ── 第一行：✔ 标题 ……… 时间
        head = QHBoxLayout()
        head.setSpacing(8)

        mark = QLabel(_LEVEL_MARK.get(notice.level, "•"), self)
        mark.setObjectName("noticeMark")
        mark.setFixedWidth(16)
        head.addWidget(mark)

        title = StrongBodyLabel(notice.title, self)
        title.setObjectName("noticeTitle")
        title.setWordWrap(True)
        head.addWidget(title, 1)

        when = QLabel(notice.time_text(), self)
        when.setObjectName("noticeTime")
        when.setAlignment(Qt.AlignmentFlag.AlignRight
                          | Qt.AlignmentFlag.AlignTop)
        head.addWidget(when, 0)
        box.addLayout(head)

        # ── 正文（可能多行；空就不摆，别留一块空白）
        if notice.body.strip():
            body = BodyLabel(notice.body.strip(), self)
            body.setObjectName("noticeBody")
            body.setWordWrap(True)
            box.addWidget(body)

        self.refresh_skin_colors()

    def refresh_skin_colors(self) -> None:
        """换肤时被 ``skins`` 自动调用（见 ``SKIN_REFRESH_METHOD``）。

        ⚠ 这些颜色是建控件时**算出来塞进 setStyleSheet** 的，
        换肤不会自动更新 —— 不重取就会留着上一个皮肤的颜色。
        """
        for child in self.findChildren(QWidget):
            name = child.objectName()
            sheet = ""
            if name == "noticeMark":
                sheet = (f"color: {level_color(self.notice.level)};"
                         f" font-size: 15px; font-weight: bold;")
            elif name == "noticeTitle":
                sheet = f"color: {main_text_color()}; font-size: 14px;"
            elif name == "noticeTime":
                sheet = f"color: {dim_text_color()}; font-size: 12px;"
            elif name == "noticeBody":
                sheet = f"color: {dim_text_color()}; font-size: 13px;"
            if sheet:
                try:
                    child.setStyleSheet(sheet)
                except RuntimeError:      #: 已经销毁了
                    continue


class NoticeInterface(ScrollArea):
    """侧栏「消息」页。

    :param store: 存储；测试传临时路径就不碰用户真实的消息历史。
    """

    #: 通知数变了（主窗口接它去更新侧栏未读角标）
    changed = Signal()

    def __init__(self, parent=None, store: N.NotificationStore | None = None):
        super().__init__(parent)
        self.setObjectName("NoticeInterface")
        self.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        #: 注入点：测试用临时 store
        #:
        #: ⚠⚠ 默认**必须**取 ``notify.store()`` 那个进程级单例，不能自己
        #: ``NotificationStore()`` —— 那会新建一个指向**用户真实
        #: notifications.json** 的 store，于是:
        #:
        #:   * 测试里建 ``MainWindow`` 就会往用户真实文件里写消息
        #:     （本仓踩过同类的坑：测试改掉了用户本地的皮肤设置、
        #:      写坏了 ``gacha_history.json``）；
        #:   * 工具/任务那边（``core.notify``）和界面这边会是**两份 store**，
        #:      各写各的 —— 消息记了但页面上看不见。
        #:
        #: 走单例的好处：``notify.set_store(临时路径)`` 一处生效，界面和
        #: 记录方**永远看同一份**。
        from ..core import notify as _notify

        self.store = (store if store is not None
                      else _notify.store())
        self._cards: list[NoticeCard] = []

        view = QWidget(self)
        view.setObjectName("noticeView")
        layout = QVBoxLayout(view)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(8)

        self.title = QLabel("消息", view)
        self.title.setObjectName("noticePageTitle")
        layout.addWidget(self.title)

        hint = QLabel(
            f"最近的通知，最多留 {N.MAX_ITEMS} 条，每天自动清理。", view)
        hint.setObjectName("noticePageHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addSpacing(6)

        # ── 操作行：清空全部
        tools = QHBoxLayout()
        tools.setSpacing(10)
        self.clear_button = PushButton("清空全部", view)
        self.clear_button.clicked.connect(self._on_clear)
        tools.addWidget(self.clear_button)
        tools.addStretch(1)
        layout.addLayout(tools)
        layout.addSpacing(6)

        #: 卡片都塞进这个容器（刷新时整块重建）
        self.list_host = QWidget(view)
        self.list_box = QVBoxLayout(self.list_host)
        self.list_box.setContentsMargins(0, 0, 0, 0)
        self.list_box.setSpacing(10)
        layout.addWidget(self.list_host)

        #: 空态（没有消息时显示一句，而不是一片空白）
        self.empty = QLabel("还没有消息。任务跑完 / 失败时会记在这里。", view)
        self.empty.setObjectName("noticeEmpty")
        self.empty.setWordWrap(True)
        layout.addWidget(self.empty)

        layout.addStretch(1)

        #: ⚠ 跟其它页面一样 —— 不写这几行整页不显示（见类文档）
        self.setWidget(view)
        self.setWidgetResizable(True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("#NoticeInterface { background: transparent; }")
        self.viewport().setStyleSheet("background: transparent;")

        self.refresh()

    # -------------------------------------------------------------- 刷新
    def refresh(self) -> None:
        """重画列表（**读一遍 store** —— 顺便触发每日清理）。"""
        #: 先清空旧卡片
        while self.list_box.count():
            item = self.list_box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._cards.clear()

        items = self.store.items()
        for notice in items:
            card = NoticeCard(notice, self.list_host)
            self.list_box.addWidget(card)
            self._cards.append(card)

        has_any = bool(items)
        self.list_host.setVisible(has_any)
        self.empty.setVisible(not has_any)
        self.clear_button.setEnabled(has_any)
        self.clear_button.setText(
            f"清空全部（{len(items)}）" if has_any else "清空全部")

        self.refresh_skin_colors()

    def refresh_skin_colors(self) -> None:
        """换肤时被 ``skins`` 自动调用 —— 页面自己的几个 QLabel 要重取色。"""
        for widget, sheet in (
            (self.title, f"font-size: 22px; font-weight: bold;"
                         f" color: {main_text_color()};"),
            (self.empty, f"font-size: 13px; color: {dim_text_color()};"),
        ):
            try:
                widget.setStyleSheet(sheet)
            except RuntimeError:
                continue
        #: ⚠ hint 当初用的是 QLabel，得一起刷
        for child in self.findChildren(QLabel):
            if child.objectName() == "noticePageHint":
                child.setStyleSheet(
                    f"font-size: 13px; color: {dim_text_color()};")
        #: 卡片自己也会被 ``skins`` 调到（它在控件树里），这里不用管

    # -------------------------------------------------------------- 动作
    def note(self, title: str, body: str = "", *,
             level: str = N.LEVEL_INFO) -> N.Notice:
        """★ **记一条消息**（各工具/任务完成时调的就是它）。

        ⚠ 记完**顺手刷一下界面**：用户可能正开着消息页，
        不刷的话新消息要切走再回来才看得到。
        """
        notice = self.store.add(title, body, level=level)
        self.refresh()
        self.changed.emit()
        return notice

    def mark_read(self) -> None:
        """标记全部已读（**切到本页时**由主窗口调）→ 未读角标清掉。"""
        self.store.mark_all_read()
        self.changed.emit()

    def unread_count(self) -> int:
        return self.store.unread_count()

    def _on_clear(self) -> None:
        """手动清理 —— 先问一句（这个动作不可撤销）。"""
        if not len(self.store):
            return
        box = MessageBox(
            "清空全部消息？",
            f"将删掉当前 {len(self.store)} 条通知，**不可恢复**。\n"
            f"（每天也会自动清掉非当天的消息）",
            self.window())
        if not box.exec():
            return
        n = self.store.clear()
        self.refresh()
        self.changed.emit()
        logger.info("消息：已手动清空 %d 条", n)


def build_notice_page(parent=None, store=None) -> NoticeInterface:
    """给侧栏用的消息页面。"""
    return NoticeInterface(parent, store=store)
