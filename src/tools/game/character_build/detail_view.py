# -*- coding: utf-8 -*-
"""「共鸣者详情」面板 —— 按官方那个**图文并茂**的布局展示。

## 布局（用户给的参考图，逐块对应）

    ┌─ 共鸣者信息 ────────────────────────────────┐
    │  名字 Lv.90 ★★★★★                          │
    ├─ 共鸣者属性 ────────────────────────────────┤
    │  ♡生命 15465      ⚔攻击 2357                │  ← 双列，每项带图标
    │  🛡防御 1381       ✦暴击 68.6%              │
    │  …                                          │
    ├─ 武器 ──────────────────────────────────────┤
    │  [图] 裁春  Lv.90 谐振1阶                    │
    │       武器星级 ★★★★★                       │
    │  ⚔攻击 587        ✦暴击 24.3%               │
    ├─ 属性展示 ──────────────────────────────────┤  ← 声骸提供的属性
    │  ♡生命 5140       ⚔攻击 1071                │
    ├─ 声骸 COST 12/12 ───────────────────────────┤
    │  ✦ 推荐辅音词条命中                          │
    │   ┌────┐  ⚔攻击 2   ⚔攻击(百分比) 3         │
    │   │ 19 │  ✦暴击 5   ✦暴击伤害 5             │  ← 黄底大数字
    │   └────┘  总计命中  ◈共鸣效率 3 …           │
    │  ✦ 装配声骸详情                              │
    │   ┌──────────────┐ ┌──────────────┐         │
    │   │[图] 梦魇·无冠者│ │[图] 振铎乐师 │         │  ← 两列卡片
    │   │  COST4  👍4  │ │  COST3  👍4  │         │
    │   ├──────────────┤ ├──────────────┤         │
    │   │✦暴击伤害 44.0%│ │◈湮灭伤害 30.0%│         │  ← 主属性（黄底）
    │   │⚔攻击 150     │ │⚔攻击 100     │         │
    │   │·共鸣效率 10.8%│ │·攻击 40      │         │  ← 副词条
    │   └──────────────┘ └──────────────┘         │
    ├─ 技能 ──────────────────────────────────────┤
    │  [图][图][图][图][图]                        │
    │  常态攻击 共鸣技能 共鸣解放 变奏技能 共鸣回路 │
    │  Lv.10/10 …                                 │
    ├─ 共鸣链 ────────────────────────────────────┤
    │  ◆◆◆◆◆◆                                    │
    │  在无人知晓的秘密小径 已激活                  │
    │  施放变奏技能…                               │
    └─────────────────────────────────────────────┘

## 性能

图标**不在绘制时下载** —— 拉数据的时候后台线程已经
``icon_cache.ensure_many()`` 下好了，这里只读缓存。
拿不到图标就**不画图**（文字照常显示），不留白块。
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import BodyLabel, CaptionLabel, StrongBodyLabel

from ....core import icon_cache

logger = logging.getLogger(__name__)

#: 属性图标尺寸
PROP_ICON = 18
#: 技能 / 共鸣链图标尺寸
SKILL_ICON = 40
#: 声骸 / 武器图标尺寸
ITEM_ICON = 56
#: 命中大数字的直径
HIT_BADGE = 64

#: 主属性底色（官方那种淡黄）
MAIN_BG = "#fdf6e3"
#: 主属性文字色
MAIN_FG = "#8a6d1a"
#: 副词条底色（未命中）
SUB_BG = "#f7f7f7"
#: ★ 副词条底色（**命中** —— 用户："命中的词条黄色高亮就行"）
SUB_HIT_BG = "#fdf3d0"
#: 命中 / 未命中的标记色
HIT_FG = "#c8a02c"
MISS_FG = "#9aa0a6"
#: 未达标红
BAD_FG = "#c42b1c"


def _icon_label(url: str, size: int, parent=None) -> QLabel:
    """画一个小图标（拿不到就返回一个**等宽空占位**，保持对齐）。"""
    lab = QLabel(parent)
    lab.setFixedSize(QSize(size, size))
    lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
    pix = icon_cache.pixmap(url, size)
    if not pix.isNull():
        lab.setPixmap(pix)
    return lab


#: ★ 区块卡片的样式（用户："这些都分别做成一个卡片，别放在一起"）
#:
#: 官方参考图里每一块都是**独立的卡片**：
#: 深色标题栏 + 浅色内容区 + 圆角 + 细边框。
SECTION_BG = "#ffffff"
#: 标题栏底色（官方那种深灰）
SECTION_HEAD_BG = "#3d4148"
#: 标题栏文字色
SECTION_HEAD_FG = "#f2f3f5"
#: 卡片边框 / 圆角
SECTION_BORDER = "rgba(0,0,0,0.14)"
SECTION_RADIUS = 8


def _section(title: str, parent=None) -> tuple[QWidget, QVBoxLayout]:
    """一个**独立卡片**区块（深色标题栏 + 浅色内容区）。

    返回 ``(卡片, 内容布局)`` —— 往 ``内容布局`` 里塞东西即可。

    ## 为什么是卡片（用户 2026-10-04）

    用户（截图圈出「共鸣者属性」「武器」「属性展示」三个标题）：
    "这些都分别做成一个卡片，别放在一起，下面的也是"

    ⚠ 我原来只画了一个加粗小标题，所有区块直接堆在同一个白底上 ——
    视觉上糊成一片，用户要求**每块各自成卡片**。
    """
    card = QWidget(parent)
    card.setStyleSheet(
        f"background: {SECTION_BG};"
        f"border: 1px solid {SECTION_BORDER};"
        f"border-radius: {SECTION_RADIUS}px;")
    outer = QVBoxLayout(card)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(0)

    #: ── 深色标题栏
    if title:
        head = QLabel(title, card)
        head.setStyleSheet(
            f"background: {SECTION_HEAD_BG};"
            f"color: {SECTION_HEAD_FG};"
            f"font-size: 13px; font-weight: bold;"
            f"padding: 6px 10px;"
            f"border-top-left-radius: {SECTION_RADIUS}px;"
            f"border-top-right-radius: {SECTION_RADIUS}px;")
        outer.addWidget(head)

    #: ── 内容区
    body = QWidget(card)
    box = QVBoxLayout(body)
    box.setContentsMargins(10, 8, 10, 10)
    box.setSpacing(6)
    outer.addWidget(body)
    return card, box


def _prop_grid(props, parent, *, cols: int = 2,
               highlight: bool = False) -> QWidget:
    """属性双列表格（官方那种：图标 + 名称 + 数值）。

    :param props: ``[{"attributeName","attributeValue","iconUrl","valid"}]``
    :param highlight: 主属性用淡黄底（声音的"主属性"那种）
    """
    host = QWidget(parent)
    grid = QGridLayout(host)
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setHorizontalSpacing(12)
    grid.setVerticalSpacing(2)

    for i, p in enumerate(props or []):
        cell = QWidget(host)
        bg = MAIN_BG if highlight else "transparent"
        cell.setStyleSheet(f"background: {bg}; border-radius: 4px;")
        row = QHBoxLayout(cell)
        row.setContentsMargins(4, 2, 4, 2)
        row.setSpacing(4)

        row.addWidget(_icon_label(p.get("iconUrl"), PROP_ICON, cell))

        name = QLabel(str(p.get("attributeName") or "?"), cell)
        name.setStyleSheet("font-size: 12px;")
        row.addWidget(name)
        row.addStretch(1)

        val = QLabel(str(p.get("attributeValue") or ""), cell)
        val.setStyleSheet(
            f"font-size: 12px; font-weight: bold;"
            f"color: {MAIN_FG if highlight else 'inherit'};")
        row.addWidget(val)

        grid.addWidget(cell, i // cols, i % cols)
    return host


def _hit_badge(hits: dict, total: int, parent) -> QWidget:
    """★ 「推荐辅音词条命中」那块 —— 黄底大数字 + 各词条计数。

    官方那个 ``19`` 是**命中的副词条总数**。
    """
    host = QWidget(parent)
    row = QHBoxLayout(host)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(14)

    #: 大数字
    badge = QLabel(str(total), host)
    badge.setFixedSize(QSize(HIT_BADGE, HIT_BADGE))
    badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
    badge.setStyleSheet(
        f"background: {MAIN_BG}; color: {MAIN_FG};"
        f"border: 2px solid {HIT_FG}; border-radius: {HIT_BADGE // 2}px;"
        f"font-size: 24px; font-weight: bold;")
    row.addWidget(badge)

    #: 各词条命中数（两列）
    grid_host = QWidget(host)
    grid = QGridLayout(grid_host)
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setHorizontalSpacing(16)
    grid.setVerticalSpacing(2)
    items = sorted(hits.items(), key=lambda kv: -kv[1])
    for i, (name, n) in enumerate(items):
        cell = QWidget(grid_host)
        line = QHBoxLayout(cell)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(4)
        lab = QLabel(f"{name}", cell)
        lab.setStyleSheet("font-size: 12px;")
        line.addWidget(lab)
        num = QLabel(str(n), cell)
        num.setStyleSheet(
            f"font-size: 12px; font-weight: bold; color: {MAIN_FG};"
            f"background: {MAIN_BG}; border-radius: 3px; padding: 0 4px;")
        line.addWidget(num)
        grid.addWidget(cell, i // 2, i % 2)

    row.addWidget(grid_host, 1)
    return host


def _phantom_card(item, parent) -> QWidget:
    """一个声骸卡片（官方那种：图 + 名字 + COST + 主属性 + 副词条）。"""
    card = QWidget(parent)
    card.setStyleSheet(
        "background: white; border: 1px solid rgba(0,0,0,0.10);"
        "border-radius: 6px;")
    box = QVBoxLayout(card)
    box.setContentsMargins(8, 6, 8, 6)
    box.setSpacing(4)

    prop = item.get("phantomProp") or {}
    fet = item.get("fetterDetail") or {}

    # ── 头：图 + 名字 + COST
    head = QHBoxLayout()
    head.setSpacing(6)
    head.addWidget(_icon_label(prop.get("iconUrl"), ITEM_ICON, card))

    info = QVBoxLayout()
    info.setSpacing(0)
    name = QLabel(str(prop.get("name") or "?"), card)
    name.setWordWrap(True)
    name.setStyleSheet("font-size: 12px; font-weight: bold;")
    info.addWidget(name)

    cost = QLabel(f"COST {item.get('cost')}　"
                  f"+{item.get('level')}　[{fet.get('name') or '?'}]", card)
    cost.setStyleSheet("font-size: 11px; color: #666;")
    info.addWidget(cost)
    head.addLayout(info, 1)
    box.addLayout(head)

    # ── 主属性（黄底）
    mains = item.get("mainProps") or []
    if mains:
        box.addWidget(_prop_grid(mains, card, cols=1, highlight=True))

    # ── 副词条
    #:
    #: ★ 用户 2026-10-04："（前面的勾）是什么？去掉，命中的词条黄色高亮就行"
    #: → **不画 ✓/·**，改成**命中的整行淡黄底**。
    subs = item.get("subProps") or []
    if subs:
        sub_host = QWidget(card)
        sub_box = QVBoxLayout(sub_host)
        sub_box.setContentsMargins(0, 0, 0, 0)
        sub_box.setSpacing(1)
        for s in subs:
            hit = bool(s.get("valid"))
            line = QWidget(sub_host)
            line.setStyleSheet(
                f"background: {SUB_HIT_BG if hit else SUB_BG};"
                f"border-radius: 3px;")
            row = QHBoxLayout(line)
            row.setContentsMargins(4, 1, 4, 1)
            row.setSpacing(4)

            row.addWidget(_icon_label(s.get("iconUrl"), 14, line))
            nm = QLabel(str(s.get("attributeName") or "?"), line)
            nm.setStyleSheet("font-size: 11px;")
            row.addWidget(nm)
            row.addStretch(1)
            vv = QLabel(str(s.get("attributeValue") or ""), line)
            vv.setStyleSheet(
                f"font-size: 11px; font-weight: bold;"
                f"color: {MAIN_FG if hit else 'inherit'};")
            row.addWidget(vv)
            sub_box.addWidget(line)
        box.addWidget(sub_host)
    return card


def _echoes_block(ph: dict, parent) -> QWidget:
    """「声骸 COST 12/12」整块（含命中统计 + 两列卡片）。"""
    host = QWidget(parent)
    box = QVBoxLayout(host)
    box.setContentsMargins(0, 0, 0, 0)
    box.setSpacing(8)

    items = ph.get("equipPhantomList") or []
    hits: dict[str, int] = {}
    total = 0
    for it in items:
        for s in it.get("subProps") or []:
            if s.get("valid"):
                hits[str(s.get("attributeName") or "?")] = \
                    hits.get(str(s.get("attributeName") or "?"), 0) + 1
                total += 1

    # ── 推荐辅音词条命中
    sec, inner = _section("✦ 推荐辅音词条命中", host)
    inner.addWidget(_hit_badge(hits, total, host))
    box.addWidget(sec)

    # ── 装配声骸详情（两列）
    sec2, inner2 = _section("✦ 装配声骸详情", host)
    grid_host = QWidget(host)
    grid = QGridLayout(grid_host)
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setSpacing(8)
    for i, it in enumerate(items):
        grid.addWidget(_phantom_card(it, grid_host), i // 2, i % 2)
    inner2.addWidget(grid_host)
    box.addWidget(sec2)
    return host


def _weapon_block(wd: dict, parent) -> QWidget:
    """「武器」块：图标 + 名字 + 等级 + 谐振 + 星级 + 主属性。"""
    host = QWidget(parent)
    box = QVBoxLayout(host)
    box.setContentsMargins(0, 0, 0, 0)
    box.setSpacing(6)

    w = wd.get("weapon") or {}
    head = QHBoxLayout()
    head.setSpacing(8)
    head.addWidget(_icon_label(w.get("weaponIcon"), ITEM_ICON, host))

    info = QVBoxLayout()
    info.setSpacing(0)
    nm = StrongBodyLabel(str(w.get("weaponName") or "?"), host)
    info.addWidget(nm)
    line = QLabel(f"Lv.{wd.get('level', '?')}　"
                  f"谐振{wd.get('resonLevel', '?')}阶　"
                  f"★{w.get('weaponStarLevel', '?')}", host)
    line.setStyleSheet("font-size: 12px; color: #666;")
    info.addWidget(line)
    head.addLayout(info, 1)
    box.addLayout(head)

    props = wd.get("mainPropList") or []
    if props:
        box.addWidget(_prop_grid(props, host, cols=2))
    return host


def _skills_block(skills, parent) -> QWidget:
    """「技能」块：一排图标 + 名称 + 等级。"""
    host = QWidget(parent)
    row = QHBoxLayout(host)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(10)

    for it in skills or []:
        sk = it.get("skill") or {}
        col = QVBoxLayout()
        col.setSpacing(2)
        holder = _icon_label(sk.get("iconUrl"), SKILL_ICON, host)
        col.addWidget(holder, 0, Qt.AlignmentFlag.AlignHCenter)
        nm = QLabel(str(sk.get("name") or "?"), host)
        nm.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        nm.setStyleSheet("font-size: 11px;")
        col.addWidget(nm)
        lv = QLabel(f"Lv.{it.get('level', '?')}/10", host)
        lv.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        lv.setStyleSheet(f"font-size: 11px; color: {MAIN_FG};")
        col.addWidget(lv)
        row.addLayout(col)
    row.addStretch(1)
    return host


def _chains_block(chains, parent) -> QWidget:
    """「共鸣链」块：图标排 + 已激活的那条说明。"""
    host = QWidget(parent)
    box = QVBoxLayout(host)
    box.setContentsMargins(0, 0, 0, 0)
    box.setSpacing(6)

    row = QHBoxLayout()
    row.setSpacing(6)
    for it in chains or []:
        holder = _icon_label(it.get("iconUrl"), SKILL_ICON, host)
        if not it.get("unlocked"):
            holder.setStyleSheet("opacity: 0.35;")
        holder.setToolTip(f"{it.get('name')}\n{it.get('description')}")
        row.addWidget(holder)
    row.addStretch(1)
    box.addLayout(row)

    #: 已激活的（取最大的 order 那条，和官方"已激活"一致）
    active = [c for c in (chains or []) if c.get("unlocked")]
    if active:
        top = max(active, key=lambda c: c.get("order") or 0)
        title = QLabel(f"{top.get('name')}　"
                       f"<span style='color:{MAIN_FG}'>已激活</span>", host)
        title.setStyleSheet("font-size: 12px; font-weight: bold;")
        box.addWidget(title)
        desc = BodyLabel(str(top.get("description") or ""), host)
        desc.setWordWrap(True)
        box.addWidget(desc)
    return host


# --------------------------------------------------------------------- 主体

class CharacterTile(QWidget):
    """共鸣者列表里的**一个小格**：头像 + 名字（用户要求"图片+文字"）。

    ::

        ┌──────────┐
        │  ┌────┐  │
        │  │头像│  │
        │  └────┘  │
        │  今汐     │
        │  Lv.90   │
        └──────────┘

    点一下 → 右边/下面显示完整详情。

    :param selected: 当前选中的高亮
    :param flagged:  声骸未达标 → 名字标红
    """

    clicked = Signal(str)

    def __init__(self, role: dict, *, flagged: bool = False,
                 selected: bool = False, size: int = 72, parent=None):
        super().__init__(parent)
        self._cid = str(role.get("roleId"))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(
            f"{role.get('roleName')}　Lv{role.get('level')}\n"
            f"{role.get('attributeName', '')}　"
            f"{role.get('weaponTypeName', '')}\n"
            f"共鸣链 {role.get('chainUnlockNum', 0)}")
        if flagged:
            self.setToolTip(self.toolTip() + "\n⚠ 声骸未达标")

        box = QVBoxLayout(self)
        box.setContentsMargins(4, 4, 4, 4)
        box.setSpacing(2)

        holder = QLabel(self)
        holder.setFixedSize(QSize(size, size))
        holder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pix = _role_avatar(role, size)
        if not pix.isNull():
            holder.setPixmap(pix)
        else:
            holder.setText(str(role.get("roleName") or "?")[:1])
        box.addWidget(holder, 0, Qt.AlignmentFlag.AlignHCenter)

        nm = QLabel(str(role.get("roleName") or "?"), self)
        nm.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        nm.setStyleSheet(
            f"font-size: 12px;"
            f"color: {BAD_FG if flagged else 'inherit'};"
            f"{'font-weight: bold;' if selected else ''}")
        box.addWidget(nm)

        lv = QLabel(f"Lv.{role.get('level', '?')}", self)
        lv.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        lv.setStyleSheet("font-size: 11px; color: #888;")
        box.addWidget(lv)

        border = BAD_FG if flagged else (
            "#0a84ff" if selected else "transparent")
        width = 2 if (flagged or selected) else 1
        self.setStyleSheet(
            f"CharacterTile {{ border: {width}px solid {border};"
            f" border-radius: 6px; }}")

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt 接口
        self.clicked.emit(self._cid)
        super().mousePressEvent(event)


def _role_avatar(role: dict, size: int):
    """角色头像 —— 先试游戏内素材，再用接口给的 ``roleIconUrl``。"""
    from PySide6.QtGui import QPixmap

    name = str(role.get("roleName") or "")
    try:
        from ....core import game_data
        from ....gui.pickers import avatar_icon

        info = game_data.find_character(name)
        icon = avatar_icon(info.avatar if info else "", name)
        if not icon.isNull():
            return icon.pixmap(size, size)
    except Exception:                          # noqa: BLE001
        pass
    #: 退回接口给的图标 URL（拉数据时已经缓存过）
    url = role.get("roleIconUrl")
    if url:
        pix = icon_cache.pixmap(url, size)
        if not pix.isNull():
            return pix
    return QPixmap()


class EchoDetailView(QScrollArea):
    """一个角色的完整详情（图文并茂，可滚动）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self._host = QWidget(self)
        self.setWidget(self._host)
        self._box = QVBoxLayout(self._host)
        self._box.setContentsMargins(2, 2, 2, 2)
        self._box.setSpacing(12)
        self._title = StrongBodyLabel("（选一个共鸣者看详情）", self._host)
        self._box.addWidget(self._title)
        self._body = QWidget(self._host)
        self._body_box = QVBoxLayout(self._body)
        self._body_box.setContentsMargins(0, 0, 0, 0)
        self._body_box.setSpacing(14)
        self._box.addWidget(self._body)
        self._box.addStretch(1)

    def clear(self) -> None:
        while self._body_box.count():
            item = self._body_box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._title.setText("（选一个共鸣者看详情）")

    def show_detail(self, detail: dict, issues=None) -> None:
        """把 ``detail``（``getRoleDetail`` 的返回）画出来。"""
        self.clear()
        detail = detail or {}
        role = detail.get("role") or {}
        name = role.get("roleName") or "?"
        self._title.setText(
            f"{name}　Lv{role.get('level', '?')}　"
            f"{role.get('attributeName', '')}　"
            f"{role.get('weaponTypeName', '')}")

        if issues:
            warn = BodyLabel("⚠ " + "；".join(issues), self._body)
            warn.setWordWrap(True)
            warn.setStyleSheet(f"color: {BAD_FG};")
            self._body_box.addWidget(warn)

        # ── 共鸣者属性
        attrs = detail.get("roleAttributeList") or []
        if attrs:
            host, inner = _section("✦ 共鸣者属性", self._body)
            inner.addWidget(_prop_grid(attrs, host, cols=2))
            self._body_box.addWidget(host)

        # ── 武器
        wd = detail.get("weaponData") or {}
        if wd.get("weapon"):
            host, inner = _section("✦ 武器", self._body)
            inner.addWidget(_weapon_block(wd, host))
            self._body_box.addWidget(host)

        # ── 属性展示（声骸提供）
        adds = detail.get("equipPhantomAddPropList") or []
        if adds:
            host, inner = _section("✦ 属性展示", self._body)
            inner.addWidget(_prop_grid(adds, host, cols=2))
            self._body_box.addWidget(host)

        # ── 声骸
        ph = detail.get("phantomData") or {}
        if ph.get("equipPhantomList"):
            host, inner = _section(
                f"✦ 声骸　COST {ph.get('cost', '?')}/12", self._body)
            inner.addWidget(_echoes_block(ph, host))
            self._body_box.addWidget(host)

        # ── 技能
        skills = detail.get("skillList") or []
        if skills:
            host, inner = _section("✦ 技能", self._body)
            inner.addWidget(_skills_block(skills, host))
            self._body_box.addWidget(host)

        # ── 共鸣链
        chains = detail.get("chainList") or []
        if chains:
            host, inner = _section("✦ 共鸣链", self._body)
            inner.addWidget(_chains_block(chains, host))
            self._body_box.addWidget(host)
