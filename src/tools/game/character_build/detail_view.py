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

#: 主属性文字色
MAIN_FG = "#8a6d1a"
#: ★ 声骸**主属性**的底色 —— 用户 2026-10-04："主属性就不用高亮了"
#:
#: ⚠ 原来主属性也铺淡黄底，结果和"命中的副词条"撞色，分不清哪个是哪个。
#: 现在只有命中的副词条才黄底。
MAIN_BG = "transparent"
#: 副词条底色（未命中）
SUB_BG = "#f7f7f7"
#: ★ 副词条底色（**命中** —— 用户："命中的词条黄色高亮就行"）
SUB_HIT_BG = "#fdf3d0"
#: 命中 / 未命中的标记色
HIT_FG = "#c8a02c"
MISS_FG = "#9aa0a6"
#: 未达标红
BAD_FG = "#c42b1c"

#: ★★ 技能 / 共鸣链图标区的底色（**深色**）
#:
#: ## 为什么要深色底（2026-10-04 查了很久）
#
#: 用户报"技能/共鸣链是空白"，但逐层查下来：
#:   · 图标**都在缓存里**（技能 217、共鸣链 186，一个不缺）
#:   · ``pixmap()`` 也**不空**（``isNull()=False``），控件 ``visible=True``
#:   · 可界面上就是看不到
#:
#: **真正原因**：这些图是**纯白线条**（实测平均色 ``(255,255,255)``）——
#: 画在**白卡片**上等于隐形。官方的技能区是**深色底**，白图标才显眼。
#:
#: 属性图标（平均色 173）在白底上勉强可见，所以只有技能/共鸣链两块出问题。
ICON_PLATE_BG = "#3d4148"
#: 深色底上的文字色
ICON_PLATE_FG = "#e8e9ea"


def _icon_label(url: str, size: int, parent=None,
                fallback: str = "") -> QLabel | None:
    """画一个小图标；**没图就返回 ``None``**（调用方不摆控件）。

    ## ★ 为什么不能留空白占位（用户 2026-10-04）

    用户（截图圈出副词条前面那排**空方块**）："这个方框去掉"

    根因：**``subProps`` 里根本没有 ``iconUrl`` 字段**（接口不给）::

        mainProps: {"attributeName": "治疗效果加成", "iconUrl": "https://..."}
        subProps:  {"attributeName": "防御", "key": "10010-2"}   ← 没有 iconUrl

    而我原来不管有没有图都摆一个 ``size×size`` 的空 QLabel 想"保持对齐" ——
    结果就是一排空方块。

    现在**拿不到图就返回 ``None``**，调用方看到 ``None`` 就不加控件。

    ⚠ 别用 ``lab.size().isEmpty()`` 判断"有没有图" —— 刚建出来的 QLabel
    尺寸是 ``(100, 30)``，**永远不 empty**，判断会失效（我踩过）。
    """
    url = str(url or "").strip() or str(fallback or "").strip()
    if not url:
        return None
    pix = icon_cache.pixmap(url, size)
    if pix.isNull():
        return None
    lab = QLabel(parent)
    lab.setFixedSize(QSize(size, size))
    lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lab.setPixmap(pix)
    return lab


def _add_icon(row, url: str, size: int, parent, fallback: str = "") -> bool:
    """往一行里加图标 —— **没图就什么都不加**（不留空方块）。

    :return: 加进去了没有
    """
    lab = _icon_label(url, size, parent, fallback)
    if lab is None:
        return False
    row.addWidget(lab)
    return True


def _build_icon_index(detail: dict) -> dict[str, str]:
    """``属性名 → iconUrl`` 的索引。

    ## 为什么要它

    ``subProps``（副词条）**没有 iconUrl**，但同一个属性名（"暴击""攻击"…）
    在 ``mainProps`` / ``roleAttributeList`` / ``equipPhantomAddPropList``
    里**有**。所以建个索引，副词条按名字去查同一个图标。
    """
    index: dict[str, str] = {}
    detail = detail or {}

    def take(node):
        if isinstance(node, dict):
            name = str(node.get("attributeName") or "").strip()
            url = str(node.get("iconUrl") or "").strip()
            if name and url.startswith("http"):
                index.setdefault(name, url)

    for key in ("roleAttributeList", "equipPhantomAddPropList"):
        for item in detail.get(key) or []:
            take(item)

    ph = detail.get("phantomData") or {}
    for item in ph.get("equipPhantomList") or []:
        for prop in item.get("mainProps") or []:
            take(prop)
        for prop in item.get("subProps") or []:
            take(prop)
    return index


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
    # ⚠⚠ **样式必须带 objectName 选择器**！
    #
    # 用户 2026-10-04（截图圈出技能/共鸣链那一排**空方框**）：
    # "这个怎么是空白，能拿到数据吗，不能的话就干掉吧"
    #
    # 数据是好的（图标全在缓存里、pixmap 也不空），问题是**样式级联**：
    # Qt 的样式表如果**不写选择器**，会套到**所有子控件**上 ——
    # 于是每个图标 QLabel 都被画上了「白底 + 1px 边框 + 圆角」，
    # 看着就是一排空方框（其实 pixmap 在底下被盖住了）。
    #
    # 写成 ``#sectionCard { ... }`` 就只作用于这个卡片本身。
    card.setObjectName("sectionCard")
    card.setStyleSheet(
        f"#sectionCard {{"
        f" background: {SECTION_BG};"
        f" border: 1px solid {SECTION_BORDER};"
        f" border-radius: {SECTION_RADIUS}px; }}")
    outer = QVBoxLayout(card)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(0)

    #: ── 深色标题栏
    if title:
        head = QLabel(title, card)
        #: ⚠ 同样写选择器 —— 标题栏自己没子控件，但**统一规则**更安全：
        #: 以后往标题栏里塞图标就不会踩坑（见 ``_section`` 顶部说明）
        head.setObjectName("sectionHead")
        head.setStyleSheet(
            f"#sectionHead {{"
            f" background: {SECTION_HEAD_BG};"
            f" color: {SECTION_HEAD_FG};"
            f" font-size: 13px; font-weight: bold;"
            f" padding: 6px 10px;"
            f" border-top-left-radius: {SECTION_RADIUS}px;"
            f" border-top-right-radius: {SECTION_RADIUS}px; }}")
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
        #: ⚠ 带选择器（否则会套到格子里的图标 / 文字上）
        cell.setObjectName("propCell")
        cell.setStyleSheet(f"#propCell {{ background: {bg};"
                           f" border-radius: 4px; }}")
        row = QHBoxLayout(cell)
        row.setContentsMargins(4, 2, 4, 2)
        row.setSpacing(4)

        _add_icon(row, p.get("iconUrl"), PROP_ICON, cell)

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
    #: ⚠ 带选择器
    badge.setObjectName("hitBadge")
    badge.setStyleSheet(
        f"#hitBadge {{ background: {MAIN_BG}; color: {MAIN_FG};"
        f" border: 2px solid {HIT_FG}; border-radius: {HIT_BADGE // 2}px;"
        f" font-size: 24px; font-weight: bold; }}")
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


def _phantom_card(item, parent, icon_index=None) -> QWidget:
    """一个声骸卡片（官方那种：图 + 名字 + COST + 主属性 + 副词条）。

    :param icon_index: ``属性名 → iconUrl``（副词条没图标时按名字查 ——
        见 :func:`_build_icon_index`）
    """
    icon_index = icon_index or {}
    card = QWidget(parent)
    # ⚠⚠ 同样必须带 objectName 选择器（见 ``_section`` 的说明）——
    # 不写选择器的话，这个「白底 + 边框」会套到卡片里**每个子控件**上，
    # 图标就被涂成空方框（用户 2026-10-04 报的那个问题）。
    card.setObjectName("phantomCard")
    card.setStyleSheet(
        "#phantomCard { background: white;"
        " border: 1px solid rgba(0,0,0,0.10); border-radius: 6px; }")
    box = QVBoxLayout(card)
    box.setContentsMargins(8, 6, 8, 6)
    box.setSpacing(4)

    prop = item.get("phantomProp") or {}
    fet = item.get("fetterDetail") or {}

    # ── 头：图 + 名字 + COST
    head = QHBoxLayout()
    head.setSpacing(6)
    _add_icon(head, prop.get("iconUrl"), ITEM_ICON, card)

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

    # ── 主属性
    #: ★ 用户 2026-10-04："主属性就不用高亮了"
    #: → 不再铺黄底（否则和"命中的副词条"撞色，分不清）
    mains = item.get("mainProps") or []
    if mains:
        box.addWidget(_prop_grid(mains, card, cols=1, highlight=False))

    # ── 副词条
    #:
    #: ★ 用户 2026-10-04："（前面的勾）是什么？去掉，命中的词条黄色高亮就行"
    #: → **不画 ✓/·**，改成**命中的整行淡黄底**。
    #:
    #: ★ 同一天："这个方框去掉"（截图圈出那排空方块）——
    #: ``subProps`` 没有 ``iconUrl``，之前硬摆空占位就是一排方框。
    #: 现在按**属性名**去 ``icon_index`` 查同名图标，查不到就**不摆**。
    subs = item.get("subProps") or []
    if subs:
        sub_host = QWidget(card)
        sub_box = QVBoxLayout(sub_host)
        sub_box.setContentsMargins(0, 0, 0, 0)
        sub_box.setSpacing(1)
        for s in subs:
            hit = bool(s.get("valid"))
            line = QWidget(sub_host)
            #: ⚠ 带选择器（否则会套到图标上）
            line.setObjectName("subLine")
            line.setStyleSheet(
                f"#subLine {{ background: "
                f"{SUB_HIT_BG if hit else SUB_BG};"
                f" border-radius: 3px; }}")
            row = QHBoxLayout(line)
            row.setContentsMargins(4, 1, 4, 1)
            row.setSpacing(4)

            #: ★ 按名字复用主属性 / 角色属性里的同名图标（没有就不摆）
            _add_icon(row, s.get("iconUrl"), 14, line,
                      fallback=icon_index.get(
                          str(s.get("attributeName") or ""), ""))
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


def _echoes_block(ph: dict, parent, icon_index=None) -> QWidget:
    """「声骸 COST 12/12」整块（含命中统计 + 两列卡片）。"""
    icon_index = icon_index or {}
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
        grid.addWidget(_phantom_card(it, grid_host, icon_index),
                       i // 2, i % 2)
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
    _add_icon(head, w.get("weaponIcon"), ITEM_ICON, host)

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


def _expand_area(parent, title: str, text: str) -> QWidget:
    """★ 一块**初始隐藏**的说明区（点了才展开）。

    用户 2026-10-05::

        "技能、共鸣链，点击的时候，往下展开说明，不是弹出说明，
         初始不点击的时候，不展示任何说明"

    → 不用弹窗，改成**就地往下展开**；初始 ``setVisible(False)``。
    """
    area = QWidget(parent)
    area.setObjectName("expandArea")
    #: ⚠ 样式带选择器（否则会套到里面的子控件上，图标会变空方块）
    area.setStyleSheet(
        "#expandArea { background: #f5f6f8; border-radius: 4px;"
        " border-left: 3px solid #3d4148; }")
    box = QVBoxLayout(area)
    box.setContentsMargins(10, 6, 8, 6)
    box.setSpacing(3)

    head = QLabel(title, area)
    head.setWordWrap(True)
    head.setStyleSheet("font-size: 12px; font-weight: bold;")
    box.addWidget(head)

    body = QLabel(text, area)
    body.setWordWrap(True)
    body.setTextInteractionFlags(
        Qt.TextInteractionFlag.TextSelectableByMouse)
    body.setStyleSheet("font-size: 12px;")
    box.addWidget(body)

    area.setVisible(False)                     # ★ 初始不展示
    return area


def _bind_toggle(clickable, area) -> None:
    """点 ``clickable`` → 切换 ``area`` 的显示（往下展开 / 收起）。"""
    if clickable is None:
        return

    def _toggle(_event, _area=area):
        _area.setVisible(not _area.isVisible())

    clickable.mousePressEvent = _toggle       # noqa: B010 - 简易点击


def _num(text) -> float | None:
    """``"70.0%"`` → ``70.0``（本地版，不依赖 core 模块）。"""
    s = str(text or "").strip().replace("%", "").replace(",", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _meets(have: float, need: float, symbol: str) -> bool:
    """按官方给的比较符判断达标。

    ⚠ 这张符号表是**从官方 JS 挖出来的**（``4`` 是 ``>`` 不是 ``<=``）——
    别在这儿再写一份，统一走 :mod:`src.core.wuwa_guide`。
    """
    from ....core import wuwa_guide

    return wuwa_guide.meets(have, need, symbol)


def _standard_block(standard, current: dict, parent) -> QWidget:
    """★★ 「属性推荐」块 —— **当前值 vs 官方推荐值**（用户要的达标标准）。

    用户 2026-10-05 给了官方攻略站的截图::

        属性        当前数值    推荐数值
        暴击        78.4%       ≥70.0%  ✓
        暴击伤害    281.0%      ≥260.0% ✓
        共鸣效率    128.4%      ≥120.0% ✓

    ★ 用户之后又要求（2026-10-05）::

        "哪条属性不足的，红色高亮显示，并加个括号说明差多少"

    → 不足的那一行：**数值标红** + 后面跟 `（差 37.4%）`。

    数据来自 :mod:`src.core.wuwa_guide`（官方攻略站）。
    """
    host = QWidget(parent)
    grid = QGridLayout(host)
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setHorizontalSpacing(12)
    grid.setVerticalSpacing(3)

    #: 表头
    for col, text in enumerate(("属性", "当前数值", "推荐数值")):
        head = QLabel(text, host)
        head.setStyleSheet("font-size: 12px; font-weight: bold; color: #666;")
        if col:
            head.setAlignment(Qt.AlignmentFlag.AlignRight
                              | Qt.AlignmentFlag.AlignVCenter)
        grid.addWidget(head, 0, col)

    for i, a in enumerate((standard or {}).get("attrs") or [], start=1):
        name = str(a.get("name") or "?")
        have = current.get(name)
        need = a.get("value")
        need_raw = str(a.get("recommend") or "")
        unit = a.get("unit") or ""
        symbol = str(a.get("symbol") or "≥")
        #: ⚠ 面板里没这个属性 → 灰色显示"—"，**不标红**（不是"不达标"）
        missing = have is None or need is None
        ok = missing or _meets(have, need, symbol)

        cell = QWidget(host)
        cell.setObjectName("stdRow")
        cell.setStyleSheet(
            f"#stdRow {{ background: {SUB_HIT_BG if not ok else ''};"
            f" border-radius: 3px; }}")
        row = QHBoxLayout(cell)
        row.setContentsMargins(4, 2, 4, 2)
        row.setSpacing(6)

        _add_icon(row, a.get("icon_url"), PROP_ICON, cell)

        nm = QLabel(name, cell)
        nm.setStyleSheet(
            f"font-size: 12px;"
            f"{f' color: {BAD_FG}; font-weight: bold;' if not ok else ''}")
        row.addWidget(nm)
        row.addStretch(1)

        #: ── 当前值
        cur = QLabel(f"{have:g}{unit}" if not missing else "—", cell)
        cur.setStyleSheet(
            f"font-size: 12px; font-weight: bold;"
            f"{f' color: {BAD_FG};' if not ok else ''}")
        row.addWidget(cur)

        #: ── 推荐值
        want = QLabel(f"{symbol}{need_raw}", cell)
        want.setStyleSheet(
            f"font-size: 12px; font-weight: bold;"
            f"color: {BAD_FG if not ok else MAIN_FG};")
        row.addWidget(want)

        #: ── ★ 差多少（用户要求："加个括号说明差多少"）
        if not ok and not missing:
            row.addWidget(_gap_label(have, need, unit, symbol, cell))

        mark = QLabel("✓" if ok else "✗", cell)
        mark.setStyleSheet(
            f"font-size: 12px; font-weight: bold;"
            f"color: {'#9aa0a6' if missing else
                      ('#2e7d32' if ok else BAD_FG)};")
        row.addWidget(mark)

        grid.addWidget(cell, i, 0, 1, 3)
    grid.setColumnStretch(0, 1)
    return host


def _gap_label(have: float, need: float, unit: str, symbol: str,
               parent) -> QLabel:
    """★ 差多少 —— ``（差 37.4%）``。

    ⚠ 符号可能是 ``>`` / ``≤`` 等**非** ``≥`` 的方向，
    所以用 ``abs`` 取差额（"差"就是两者的距离，和方向无关）。
    """
    gap = abs(need - have)
    lab = QLabel(f"（差 {gap:g}{unit}）", parent)
    lab.setStyleSheet(f"font-size: 11px; color: {BAD_FG};")
    return lab


def _skills_block(skills, parent) -> QWidget:
    """「技能」块：一排图标 + 名称 + 等级。

    ★ **图标区用深色底** —— 这些图是**纯白线条**，画在白底上等于隐形
    （详见 ``ICON_PLATE_BG`` 的说明）。
    """
    host = QWidget(parent)
    host.setObjectName("skillsBlock")
    host.setStyleSheet(
        f"#skillsBlock {{ background: {ICON_PLATE_BG};"
        f" border-radius: 6px; }}")
    row = QHBoxLayout(host)
    row.setContentsMargins(12, 10, 12, 10)
    row.setSpacing(10)

    for it in skills or []:
        sk = it.get("skill") or {}
        col = QVBoxLayout()
        col.setSpacing(2)

        desc = str(sk.get("description") or "").strip()
        title = f"{sk.get('name') or ''}（{sk.get('type') or ''}）"

        #: ★ 图标可点 → **在下面展开说明**（不是弹窗）
        holder = _icon_label(sk.get("iconUrl"), SKILL_ICON, host)
        if holder is not None:
            if desc:
                holder.setCursor(Qt.CursorShape.PointingHandCursor)
            col.addWidget(holder, 0, Qt.AlignmentFlag.AlignHCenter)

        nm = QLabel(str(sk.get("name") or "?"), host)
        nm.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        #: ⚠ 深色底 → 文字要浅色（否则黑字也看不见）
        nm.setStyleSheet(f"font-size: 11px; color: {ICON_PLATE_FG};")
        col.addWidget(nm)
        lv = QLabel(f"Lv.{it.get('level', '?')}/10", host)
        lv.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        lv.setStyleSheet(f"font-size: 11px; color: {MAIN_FG};")
        col.addWidget(lv)

        #: ★ 说明区：**初始隐藏**，点了图标才往下展开
        #: （用户："技能、共鸣链，点击的时候，往下展开说明，
        #:   不是弹出说明，初始不点击的时候，不展示任何说明"）
        if desc:
            area = _expand_area(host, title, desc)
            col.addWidget(area)
            _bind_toggle(holder, area)

        row.addLayout(col)
    row.addStretch(1)
    return host


def _chains_block(chains, parent) -> QWidget:
    """「共鸣链」块：图标排（可点展开）+ 每条链的标题。

    用户 2026-10-05::

        "共鸣链数据能拿到吗"                       ← 数据有
        "点击的时候，往下展开说明，不是弹出说明，
         初始不点击的时候，不展示任何说明"          ← 交互要求

    → 图标 + 标题常驻；**说明文字初始隐藏**，点图标或标题才展开。
    """
    host = QWidget(parent)
    box = QVBoxLayout(host)
    box.setContentsMargins(0, 0, 0, 0)
    box.setSpacing(6)

    #: ★ 图标区用**深色底** —— 共鸣链图标也是纯白线条（见 ICON_PLATE_BG）
    plate = QWidget(host)
    plate.setObjectName("chainPlate")
    plate.setStyleSheet(
        f"#chainPlate {{ background: {ICON_PLATE_BG};"
        f" border-radius: 6px; }}")
    plate_row = QHBoxLayout(plate)
    plate_row.setContentsMargins(12, 8, 12, 8)
    plate_row.setSpacing(6)
    for it in chains or []:
        holder = _icon_label(it.get("iconUrl"), SKILL_ICON, plate)
        #: ★ 没图就不摆空方块
        if holder is None:
            continue
        if not it.get("unlocked"):
            holder.setStyleSheet("opacity: 0.35;")
        label = f"共鸣链 {it.get('order')}　{it.get('name') or ''}"
        desc = str(it.get("description") or "").strip()
        if desc:
            holder.setCursor(Qt.CursorShape.PointingHandCursor)
            holder.setToolTip(label)
        plate_row.addWidget(holder)
    plate_row.addStretch(1)
    box.addWidget(plate)

    #: ★ 每条链：标题常驻 + **说明初始隐藏**（点了才展开）
    for it in chains or []:
        unlocked = bool(it.get("unlocked"))
        desc = str(it.get("description") or "").strip()
        line = QWidget(host)
        line.setObjectName("chainLine")
        line.setStyleSheet(
            "#chainLine { border-bottom: 1px solid rgba(0,0,0,0.06); }")
        lay = QVBoxLayout(line)
        lay.setContentsMargins(2, 4, 2, 6)
        lay.setSpacing(2)

        title = QLabel(
            f"<b>{it.get('order')}　{it.get('name') or ''}</b>"
            + ("" if unlocked
               else "　<span style='color:#9aa0a6'>未激活</span>"),
            line)
        title.setStyleSheet("font-size: 12px;")
        if desc:
            title.setCursor(Qt.CursorShape.PointingHandCursor)
        lay.addWidget(title)

        if desc:
            area = _expand_area(
                line, f"共鸣链 {it.get('order')}　{it.get('name') or ''}",
                desc)
            lay.addWidget(area)
            _bind_toggle(title, area)
        box.addWidget(line)
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

    def show_detail(self, detail: dict, issues=None,
                    standard=None) -> None:
        """把 ``detail``（``getRoleDetail`` 的返回）画出来。

        :param issues: 待优化项（红字提示）
        :param standard: ★ 官方推荐标准（:mod:`src.core.wuwa_guide`），
            有就多画一块「属性推荐：当前 vs 推荐」
        """
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

        # ★★ 属性推荐（当前 vs 官方推荐）—— 放在最前面，这是核心判据
        current = {}
        for item in detail.get("roleAttributeList") or []:
            if isinstance(item, dict):
                nm = str(item.get("attributeName") or "").strip()
                val = _num(item.get("attributeValue"))
                if nm and val is not None:
                    current[nm] = val
        if (standard or {}).get("attrs"):
            host, inner = _section("✦ 属性推荐", self._body)
            inner.addWidget(_standard_block(standard, current, host))
            self._body_box.addWidget(host)

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
            inner.addWidget(_echoes_block(ph, host,
                                          _build_icon_index(detail)))
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
