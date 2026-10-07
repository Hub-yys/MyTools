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


def text_color() -> str:
    """★ **当前皮肤的正文色** —— 所有文字都该用它。

    ## ⚠⚠ 为什么要有这个函数（用户 2026-10-06 连报两次）

        "这里又出现了深色皮肤 深色字体 看不见"
        "这里字压根看不见" / "这里也是很丑"

    根因反复是同一个：**``setStyleSheet`` 里没写 ``color``** ——
    于是文字继承到一个在深色玻璃底上几乎看不见的色。

    另外还有个更隐蔽的写法错误::

        color: inherit      ← **QSS 不支持 `inherit`**！
                              会被当成无效值**整条丢掉**，
                              结果和"没写"一样

    → 统一走这个函数取色，别再各写各的。

    ⚠ 读不到皮肤时兜底 ``#3d4148``（深灰）—— 保证**至少不是隐形**。
    """
    from ....core import skins

    try:
        return skins.active_skin()["text"]
    except (KeyError, TypeError, AttributeError):
        return "#3d4148"


def dim_color() -> str:
    """次要文字色（说明行、单位那种）。"""
    from ....core import skins

    try:
        return skins.active_skin()["dim"]
    except (KeyError, TypeError, AttributeError):
        return "#8a8f98"


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

#: ★★ 选中的角色格子 —— **下方一条黄色粗线**（用户 2026-10-05）
#:
#: 用户（截图圈出格子**下方**那条横线）：
#: "点到那个，哪个下方加一个黄色高亮的粗线"
#:
#: ⚠ 改过两次：先是蓝色边框 → 用户要黄的；我又做成整卡黄底 →
#: 用户要的是**下方一条粗线**（卡片本身不变色）。
SELECT_BORDER = "#f5b301"      # 粗线颜色（黄）
SELECT_BAR_H = 4               # 粗线高度（px）

#: 选中格子时**黄底**（共鸣链"已激活"用这个）——
#: ⚠ 角色格子**不用**它了（改成下方粗线），但共鸣链还在用。
SELECT_BG = "#ffe9a8"

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

    #: ★★ 属性名 / 数值都要**显式给颜色**（用户 2026-10-06："这里也是很丑"）
    #:
    #: ⚠⚠ 原来两处都有问题：
    #:   · ``name`` 只设了 ``font-size`` —— **没颜色**，深色底上几乎看不见
    #:   · ``val`` 用了 ``color: inherit`` —— **QSS 不支持 `inherit`**，
    #:     会被当成无效值丢掉，于是也继承到一个看不见的色
    #:
    #: → 名字用皮肤正文色；数值**加粗 + 也用正文色**（比名字亮一点靠字重）。
    from ....core import skins

    try:
        text_fg = skins.active_skin()["text"]
    except (KeyError, TypeError):
        text_fg = "#3d4148"

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
        name.setStyleSheet(f"font-size: 12px; color: {text_fg};")
        row.addWidget(name)
        row.addStretch(1)

        val = QLabel(str(p.get("attributeValue") or ""), cell)
        #: ⚠ 高亮格用 ``MAIN_FG``（官方那种金棕），否则用皮肤正文色 ——
        #: **不能写 ``inherit``**（QSS 不认，会被丢掉）
        val.setStyleSheet(
            f"font-size: 12px; font-weight: bold;"
            f"color: {MAIN_FG if highlight else text_fg};")
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
    #: ★★ 词条名用**皮肤正文色**（用户 2026-10-06："这里字压根看不见"）
    #:
    #: ⚠ 原来这行只设了 ``font-size`` —— **没设颜色**，于是继承到一个
    #: 在深色底上几乎看不见的色。跟我前面犯的错是同一类：
    #: **文字色必须显式给，而且要从皮肤取**。
    from ....core import skins

    try:
        name_fg = skins.active_skin()["text"]
    except (KeyError, TypeError):
        name_fg = "#3d4148"
    for i, (name, n) in enumerate(items):
        cell = QWidget(grid_host)
        line = QHBoxLayout(cell)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(4)
        lab = QLabel(f"{name}", cell)
        lab.setStyleSheet(f"font-size: 12px; color: {name_fg};")
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
    name.setStyleSheet(f"font-size: 12px; font-weight: bold;"
                        f"color: {text_color()};")
    info.addWidget(name)

    cost = QLabel(f"COST {item.get('cost')}　"
                  f"+{item.get('level')}　[{fet.get('name') or '?'}]", card)
    cost.setStyleSheet(f"font-size: 11px; color: {dim_color()};")
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
            nm.setStyleSheet(f"font-size: 11px;"
                             f"color: {text_color()};")
            row.addWidget(nm)
            row.addStretch(1)
            vv = QLabel(str(s.get("attributeValue") or ""), line)
            vv.setStyleSheet(
                f"font-size: 11px; font-weight: bold;"
                f"color: {MAIN_FG if hit else text_color()};")
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
    line.setStyleSheet(f"font-size: 12px; color: {dim_color()};")
    info.addWidget(line)
    head.addLayout(info, 1)
    box.addLayout(head)

    props = wd.get("mainPropList") or []
    if props:
        box.addWidget(_prop_grid(props, host, cols=2))
    return host


def _expand_area(parent, title: str, text: str) -> QWidget:
    """★ 一块**初始隐藏**的说明区（点了才展开）。

    ⚠ 现在技能/共鸣链用的是 :func:`_expand_panel`（**共用一块**）——
    这个函数留给"每条一个框"的场景（暂时没用到，但测试在用）。
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
    head.setStyleSheet(f"font-size: 12px; font-weight: bold;"
                       f"color: {text_color()};")
    box.addWidget(head)

    body = QLabel(text, area)
    body.setWordWrap(True)
    body.setTextInteractionFlags(
        Qt.TextInteractionFlag.TextSelectableByMouse)
    body.setStyleSheet(f"font-size: 12px; color: {text_color()};")
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


def _expand_panel(parent) -> tuple[QWidget, QLabel, QLabel]:
    """★★ **一块共用的说明面板**（占满整宽），初始隐藏。

    用户 2026-10-05::

        "这里点到哪个技能，展示哪个，占满整个红框，
         再次点击该技能就是关闭展开"
        "共鸣链这里也是跟上面一样"

    → 不是每条一个框，而是**共用一块**：
    点谁就把内容换上去；**再点同一个就关掉**（互斥展开）。

    :return: ``(面板, 标题 QLabel, 正文 QLabel)``
    """
    panel = QWidget(parent)
    panel.setObjectName("expandPanel")
    #: ⚠ 样式必须带选择器（不带会级联到子控件 —— 之前踩过）
    panel.setStyleSheet(
        "#expandPanel { background: #f5f6f8; border-radius: 4px;"
        " border-left: 3px solid #3d4148; }")
    box = QVBoxLayout(panel)
    box.setContentsMargins(12, 8, 10, 8)
    box.setSpacing(4)

    title = QLabel(panel)
    title.setWordWrap(True)
    title.setStyleSheet(f"font-size: 13px; font-weight: bold;"
                        f"color: {text_color()};")
    box.addWidget(title)

    body = QLabel(panel)
    body.setWordWrap(True)
    body.setTextInteractionFlags(
        Qt.TextInteractionFlag.TextSelectableByMouse)
    body.setStyleSheet(f"font-size: 12px; color: {text_color()};")
    box.addWidget(body)

    panel.setVisible(False)                    # ★ 初始不展示
    return panel, title, body


def _bind_exclusive(clickable, panel, title: str, text: str) -> None:
    """点 ``clickable`` → 在**共用面板**里显示这条例；再点同一条 → 关闭。

    互斥：点别的会自动换成别的（同一时刻只显示一条）。

    ⚠ 展开状态记在面板的 ``expandShown`` 属性上（**不是**看
    ``isVisible()``）—— 父窗口没 ``show()`` 时 Qt 的 ``isVisible()``
    永远是 False，测试里判不出来（我第一版就栽在这）。
    """
    if clickable is None:
        return
    clickable.setProperty("expandKey", title)
    clickable.setProperty("expandText", text)

    def _toggle(_event, _c=clickable, _p=panel):
        from PySide6.QtWidgets import QLabel as _L

        key = str(_c.property("expandKey") or "")
        same = str(_p.property("expandShown") or "") == key
        if same:                               #: 再点同一条 → 关闭
            _p.setVisible(False)
            _p.setProperty("expandShown", "")
            return
        labels = _p.findChildren(_L)
        if len(labels) >= 2:
            labels[0].setText(key)
            labels[1].setText(str(_c.property("expandText") or ""))
        _p.setVisible(True)
        _p.setProperty("expandShown", key)

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
        head.setStyleSheet(f"font-size: 12px; font-weight: bold;"
                           f"color: {dim_color()};")
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
        #: ⚠ 达标时也要给颜色（原来是"红字 or 啥都不设"）——
        #: 不设的话深色皮肤上正常项的文字会隐形（我的静态扫描抓到的）
        nm.setStyleSheet(
            f"font-size: 12px; color: "
            + (f"{BAD_FG}; font-weight: bold;" if not ok
               else f"{text_color()};"))
        row.addWidget(nm)
        row.addStretch(1)

        #: ── 当前值
        cur = QLabel(f"{have:g}{unit}" if not missing else "—", cell)
        #: ⚠ 达标时也要给颜色（同 nm —— 不然深色皮肤上隐形）
        cur.setStyleSheet(
            f"font-size: 12px; font-weight: bold; color: "
            + (f"{BAD_FG};" if not ok else f"{text_color()};"))
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

    #: ⚠ 外层竖排：**图标行** + **共用说明面板**（面板要占满整宽）
    outer = QVBoxLayout(host)
    outer.setContentsMargins(12, 10, 12, 10)
    outer.setSpacing(6)

    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(10)

    #: ★ 共用说明面板（**一块**，占满整宽）—— 初始不显示。
    #: 用户："点到哪个技能，展示哪个，占满整个红框，
    #:       再次点击该技能就是关闭展开"
    panel, _pt, _pb = _expand_panel(host)

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

        #: ★ 点图标 → **在下面那块共用面板里**显示这条例的说明
        #: （用户："这里点到哪个技能，展示哪个，占满整个红框，
        #:   再次点击该技能就是关闭展开"）
        if desc:
            _bind_exclusive(holder, panel, title, desc)

        row.addLayout(col)
    row.addStretch(1)

    outer.addLayout(row)
    outer.addWidget(panel)
    return host


def _chains_block(chains, parent) -> QWidget:
    """「共鸣链」块：图标排（可点展开说明）+ **已激活的黄底高亮**。

    用户 2026-10-05（截图圈出图标行和标题列表）::

        "已激活这里黄色高亮"      ← 图标
        "删掉"                    ← 那一列标题文字（1 雨洗千山皆入画 未激活 …）

    ## 所以这一块现在只有

    **一排图标**（每条一个），已激活的**黄底高亮**，未激活的灰掉。
    点任意图标 → 下面共用面板展开那条的说明。

    ⚠ 我原来还列了一串标题（`1 雨洗千山皆入画 未激活` …）——
    用户明确说"删掉"：图标本身就是"哪条"的表示，文字是多余的。
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
    plate_row.setContentsMargins(12, 10, 12, 10)
    plate_row.setSpacing(8)

    #: ★ 共用说明面板（和技能那边一样）
    panel, _pt, _pb = _expand_panel(host)

    for it in chains or []:
        label = f"共鸣链 {it.get('order')}　{it.get('name') or ''}"
        desc = str(it.get("description") or "").strip()
        unlocked = bool(it.get("unlocked"))

        #: ★★ 已激活 → **黄底高亮**（用户："已激活这里黄色高亮"）
        #:
        #: ⚠ 原来只是"未解锁的灰掉" —— 在深色底上差别不明显，
        #: 用户要求把**已激活的**标出来（点亮而不是压暗）。
        cell = QWidget(plate)
        cell.setObjectName("chainCell")
        cell.setStyleSheet(
            f"#chainCell {{ background: "
            f"{SELECT_BG if unlocked else 'transparent'};"
            f" border-radius: 6px; }}")
        cell_box = QVBoxLayout(cell)
        cell_box.setContentsMargins(4, 4, 4, 4)
        cell_box.setSpacing(0)

        holder = _icon_label(it.get("iconUrl"), SKILL_ICON, cell)
        #: ★ 没图就不摆空方块
        if holder is None:
            continue
        if not unlocked:
            holder.setStyleSheet("opacity: 0.35;")
        if desc:
            holder.setCursor(Qt.CursorShape.PointingHandCursor)
            _bind_exclusive(holder, panel, label, desc)
        cell_box.addWidget(holder)
        plate_row.addWidget(cell)
    plate_row.addStretch(1)
    box.addWidget(plate)
    box.addWidget(panel)
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
        #: 未达标 → 名字标红（和"选中"无关 —— 选中靠下方那条黄线表示）
        #:
        #: ⚠ 达标时也要给颜色（同前面几处 —— 不然深色皮肤上名字隐形）
        nm.setStyleSheet(
            f"font-size: 12px; color: "
            + (f"{BAD_FG}; font-weight: bold;" if flagged
               else f"{text_color()};"))
        box.addWidget(nm)

        lv = QLabel(f"Lv.{role.get('level', '?')}", self)
        lv.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        lv.setStyleSheet(f"font-size: 11px; color: {dim_color()};")
        box.addWidget(lv)

        # ★★ 选中的格子 → **黄色高亮**（用户 2026-10-05：
        #    "这里点到哪个，哪个黄色高亮"）
        #
        # ⚠ 原来是蓝色边框（``#0a84ff``）—— 用户要的是**黄**的。
        # 黄底 + 金色边框，未达标仍然是红框（红优先，因为那是"有问题"）。
        # ★★★ 选中的格子 → **下方一条黄色粗线**（下划线指示器）
        #
        # 用户 2026-10-05（截图圈出格子**下方**那条横线）::
        #
        #     "点到那个，哪个下方加一个黄色高亮的粗线"
        #
        # ⚠ 改过两次：
        #   1. 原来蓝色**边框** → 用户说"黄色高亮"
        #   2. 我做成整卡黄底 → 用户要的是**下方一条粗线**（不是整卡变色）
        #
        # ⚠⚠ 用 ``border-bottom`` 有个坑：格子高度是固定的，
        # 那条线会被挤到**最底下、贴着边缘**，几乎看不见（实测截图里就是）。
        # 所以改成**单独一个横条控件**放在最下面 —— 高度可控、颜色明确。
        self._bar = QWidget(self)
        self._bar.setObjectName("selectBar")
        self._bar.setFixedHeight(SELECT_BAR_H)
        #: ⚠ 样式带选择器 —— 这是**统一规则**（不带会级联到子控件，
        #: 之前图标被涂成空方块就是这原因）。横条自己没子控件，
        #: 但保持一致免得以后往里塞东西踩坑。
        if selected:
            self._bar.setStyleSheet(
                f"#selectBar {{ background: {SELECT_BORDER};"
                f" border-radius: 2px; }}")
        else:
            self._bar.setStyleSheet(
                "#selectBar { background: transparent; }")
        box.addWidget(self._bar)

        self.setStyleSheet("CharacterTile { border: none; }")

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
