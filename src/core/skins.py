# -*- coding: utf-8 -*-
"""皮肤系统 —— **液态玻璃主题**（照 DSH 那套做的）。

## 用户要求（2026-10-05）

    "这个皮肤设计太差，删掉重写，以DSH这个主题皮肤为例（液态玻璃主题），
     不用接入Wallpaper Engine"

## 液态玻璃 = 三件事

参照 DSH 界面（深蓝黑渐变 + 半透明面板 + 发光描边）::

    ① **渐变背景**     不是纯色 —— 两三个 stop 的斜向渐变，有纵深
    ② **半透明卡片**   卡片是 rgba 半透的，能"透"出背景 → 玻璃感
    ③ **发光描边**     1px 的浅色描边 + 圆角 → 玻璃边缘的高光

## ⚠ 为什么不用 qfluentwidgets 自带的 ``AcrylicBrush``

它**真的去抓屏幕背后的像素**做高斯模糊（``grabWindow``）——
需要窗口透明 + 系统合成，窗口一旦不透明就退回纯色，
而且 ``isAcrylicAvailable`` 在很多机器上是 False。

**渐变 + rgba 能稳定画出玻璃感，且完全可控** —— 就用这个。

## ⚠⚠ 上一版为什么被推翻

第一版只是"给纯色背景换个色"（``#f3f3f3`` → ``#eaf1ef``）——
用户看下来是"这个皮肤设计太差"。**换色 ≠ 皮肤**。
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt

logger = logging.getLogger(__name__)

#: 皮肤注册表（顺序 = 界面上显示的顺序）
#:
#: 字段说明::
#:
#:     id        皮肤 id（存盘用）
#:     name      显示名
#:     desc      一句话说明（卡片上显示）
#:     mode      "light" / "dark"（决定 qfluentwidgets 的明暗基调）
#:     primary   强调色（选中条、按钮、徽章）
#:     bg        背景渐变的 stop 列表 ``[(位置0~1, 颜色), ...]``
#:     card      卡片填充（**半透明**才有玻璃感）
#:     border    卡片描边（浅色细边 = 玻璃高光）
#:     text      正文色
#:     dim       次要文字色
SKINS: tuple[dict, ...] = (
    {
        "id": "mist",
        "name": "晨雾玻璃",
        "desc": "浅色玻璃，白天用清爽不刺眼",
        "mode": "light",
        "primary": "#3B82F6",
        "bg": [(0.0, "#F7F9FC"), (0.5, "#EDF2F9"), (1.0, "#E8EEF7")],
        "card": "rgba(255, 255, 255, 0.72)",
        "border": "rgba(255, 255, 255, 0.95)",
        "text": "#1F2937",
        "dim": "#6B7280",
    },
    {
        "id": "sakura",
        "name": "樱雾玻璃",
        "desc": "浅粉玻璃，柔和",
        "mode": "light",
        "primary": "#EC4899",
        "bg": [(0.0, "#FDF7FA"), (0.5, "#FAEFF5"), (1.0, "#F7E9F1")],
        "card": "rgba(255, 255, 255, 0.75)",
        "border": "rgba(255, 255, 255, 0.95)",
        "text": "#3F2A35",
        "dim": "#8B6B7A",
    },
    {
        "id": "deepglass",
        "name": "深空玻璃",
        "desc": "DSH 同款：深邃蓝黑渐变 + 冷调玻璃面板",
        "mode": "dark",
        "primary": "#4A9EFF",
        "bg": [(0.0, "#0B1026"), (0.45, "#141A38"), (1.0, "#0A0E1F")],
        "card": "rgba(255, 255, 255, 0.055)",
        "border": "rgba(255, 255, 255, 0.11)",
        "text": "#E8ECF5",
        "dim": "#8B93A7",
    },
    {
        "id": "nebula",
        "name": "星云玻璃",
        "desc": "紫蓝星云渐变，梦幻一点",
        "mode": "dark",
        "primary": "#A78BFA",
        "bg": [(0.0, "#150E2E"), (0.5, "#241A45"), (1.0, "#120C26")],
        "card": "rgba(255, 255, 255, 0.06)",
        "border": "rgba(200, 180, 255, 0.13)",
        "text": "#EDE9FE",
        "dim": "#9B92B8",
    },
    {
        "id": "abyss",
        "name": "幽海玻璃",
        "desc": "墨绿深海的静谧感",
        "mode": "dark",
        "primary": "#2DD4BF",
        "bg": [(0.0, "#06181C"), (0.5, "#0C2A2E"), (1.0, "#051417")],
        "card": "rgba(255, 255, 255, 0.055)",
        "border": "rgba(180, 255, 245, 0.12)",
        "text": "#DCF5F1",
        "dim": "#7FA39F",
    },
    {
        "id": "ember",
        "name": "熔火玻璃",
        "desc": "暗红余烬，够劲",
        "mode": "dark",
        "primary": "#F87171",
        "bg": [(0.0, "#1C0F0F"), (0.5, "#2E1616"), (1.0, "#170C0C")],
        "card": "rgba(255, 255, 255, 0.055)",
        "border": "rgba(255, 200, 200, 0.12)",
        "text": "#F5E4E4",
        "dim": "#A88B8B",
    },
)

#: 默认皮肤 id（启动时回落到它）
#:
#: ★ 用户 2026-10-05 定的：默认用**晨雾玻璃**（浅色那款）。
#: 之前默认是「深空玻璃」（暗色）。
DEFAULT_SKIN = "mist"

#: 持久化用的 ``ConfigItem`` —— qconfig 只认它（**不是**裸字符串）
#:
#: ⚠ 更早的一版写了 ``qconfig.get("skin", DEFAULT_SKIN)`` ——
#: ``qconfig.get()`` 只接**一个 ``ConfigItem``**，
#: 传字符串会炸 ``TypeError``（启动时就崩了）。
_SKIN_ITEM = None


def _skin_item():
    """皮肤配置的 ``ConfigItem``（懒建）。"""
    global _SKIN_ITEM
    if _SKIN_ITEM is None:
        from qfluentwidgets import OptionsConfigItem, OptionsValidator

        _SKIN_ITEM = OptionsConfigItem(
            "Skins", "CurrentSkin",
            DEFAULT_SKIN,
            OptionsValidator([s["id"] for s in SKINS]),
        )
    return _SKIN_ITEM


def all_skins() -> tuple[dict, ...]:
    """全部皮肤（顺序固定）。"""
    return SKINS


def skin_by_id(skin_id: str) -> dict | None:
    """按 id 找皮肤；找不到返回 ``None``。"""
    for s in SKINS:
        if s["id"] == skin_id:
            return s
    return None


def current_skin() -> dict:
    """当前皮肤（没存过就用默认）。"""
    from qfluentwidgets import qconfig

    skin_id = qconfig.get(_skin_item())
    return skin_by_id(str(skin_id)) or skin_by_id(DEFAULT_SKIN)


def gradient_qss(skin: dict) -> str:
    """把 ``bg`` 的 stop 列表拼成 QSS 的 ``qlineargradient``。

    斜向（左上 → 右下）比纯竖直更有纵深。
    """
    stops = ", ".join(
        f"stop:{pos:g} {color}" for pos, color in skin["bg"])
    return (f"qlineargradient(x1:0, y1:0, x2:1, y2:1, {stops})")


def card_qss(skin: dict) -> str:
    """把 ``card`` / ``border`` 拼成卡片样式。"""
    return (f"background: {skin['card']};"
            f" border: 1px solid {skin['border']};"
            f" border-radius: 10px;")


def build_qss(skin: dict) -> str:
    """★ 把皮肤**变成 QSS** —— 玻璃感全在这儿。

    ## 选择器为什么是这几个（实测出来的）

    ``QStackedWidget`` 是**页面容器** —— 给它渐变，整个内容区就有纵深
    （实测能改变 70%+ 的像素）。

    ``NavigationPanel`` 是**左侧栏** —— 它自己画背景，不给它渐变的话
    就会「右边深色玻璃、左边白板」，非常割裂（实测截图就是这个）。

    ``NavigationPanel ScrollArea`` 是侧栏里那块**滚动区** ——
    它有自己的 viewport，不一起设的话侧栏上下会分成两截颜色。

    ``FluentTitleBar`` 是**顶部标题栏** —— 实测它**自带 1990 字符的
    styleSheet** 且 ``WA_StyledBackground=False``，从窗口继承的渐变
    **根本到不了**它，顶部会留一条白/浅灰（用户截图圈的就是这个）。
    必须**单独设**（见 :func:`_paint_title_bar`）。

    ``CardWidget`` 是 qfluentwidgets 的卡片基类 —— 半透明填充 +
    浅色细边 = 玻璃面板。

    ⚠ 别用笼统的 ``QWidget { background: ... }`` —— 那会把**所有**
    子控件（图标、标签底）一起涂了，层次全糊（实测过）。
    """
    grad = gradient_qss(skin)
    return (
        f"QStackedWidget {{ background: {grad}; }}"
        f" NavigationPanel {{ background: {grad}; }}"
        f" NavigationPanel ScrollArea {{ background: transparent; }}"
        f" NavigationPanel ScrollArea > QWidget > QWidget"
        f" {{ background: transparent; }}"
        f" FluentTitleBar {{ background: {grad}; }}"
        f" CardWidget {{ {card_qss(skin)} }}"
    )


def page_transparent_qss() -> str:
    """★ 给**工具页 / 页面**用的透明样式。

    ## 为什么单独一份（用户截图："这里也是白色，跟现有配色完全不符"）

    工具页的宿主（``ToolInterfaceHost``）和工具面板本身都是**裸
    ``QWidget``** —— 它们不透明，于是在玻璃背景上盖了一块**纯白**。

    ⚠ 只在**页面这一层**设透明是安全的（它没有别的子控件要靠它取色）——
    这也是为什么不能用笼统的 ``QWidget { background: transparent }``
    （那会把卡片、图标底全弄没）。
    """
    return "background: transparent;"


def apply_skin(skin_id: str, *, save: bool = True) -> bool:
    """应用一个皮肤（立刻生效）。返回是否成功。

    ⚠ 顺序有讲究：**先 ``setTheme`` 再刷 QSS**。
    ``setTheme`` 会重建 qfluentwidgets 的全局样式表，
    先设的 QSS 会被它冲掉（实测过）。
    """
    skin = skin_by_id(skin_id)
    if skin is None:
        logger.warning("不认识的皮肤 id：%s", skin_id)
        return False

    from qfluentwidgets import setTheme, setThemeColor, Theme

    setTheme(Theme.DARK if skin["mode"] == "dark" else Theme.LIGHT,
             save=False)
    setThemeColor(skin["primary"], save=False)

    _paint(skin)

    if save:
        from qfluentwidgets import qconfig

        qconfig.set(_skin_item(), skin["id"])
    return True


def _paint(skin: dict) -> None:
    """把皮肤的 QSS 刷到**所有窗口**上。

    ⚠ 挂 **app 级**（不是 window 级）—— 这样**对话框 / 弹窗**也一起换，
    不然弹出的窗口还是旧配色（看着很割裂）。

    ⚠ 还要**逐个顶层窗口再设一遍** —— 主窗口有自己的调色板，
    只设 app 级会被它盖掉（实测 app 级 74.4%，window 级 99.1%）。

    ⚠⚠ ``NavigationPanel``（左侧栏）**自己带一份 styleSheet**
    （实测 584 字符，里面写死 ``background-color: rgb(32,32,32)``），
    优先级高于从窗口继承下来的 —— **必须单独给它设**，
    否则就是"右边深色玻璃、左边白板"（实测截图就是这个）。

    ⚠⚠ ``FluentTitleBar``（顶部标题栏）同理 —— 它自带 **1990 字符**的
    styleSheet 且 ``WA_StyledBackground=False``，渐变到不了它，
    顶部会留一条浅灰（用户第二个截图圈的就是这个）。
    """
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        return
    qss = build_qss(skin)
    app.setStyleSheet(qss)
    for w in app.topLevelWidgets():
        try:
            w.setStyleSheet(qss)
        except (RuntimeError, AttributeError):   #: 已销毁的窗口
            continue
        _paint_nav_panel(w, skin)
        _paint_title_bar(w, skin)
        _paint_pages(w)


def _paint_title_bar(window, skin: dict) -> None:
    """单独给顶部标题栏刷渐变（它自带 styleSheet，会盖掉继承的）。

    ⚠ 光设 ``setStyleSheet`` **不够** —— 它的
    ``WA_StyledBackground`` 默认是 ``False``，Qt 不会拿样式表画它的底，
    必须一起打开（实测：只设样式时顶部还是浅灰）。
    """
    bar = getattr(window, "titleBar", None)
    if bar is None:
        return
    try:
        bar.setStyleSheet(
            f"FluentTitleBar {{ background: {gradient_qss(skin)}; }}")
        bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    except (RuntimeError, AttributeError):
        return


def _paint_pages(window) -> None:
    """把**页面这一层**设成透明，露出玻璃背景。

    ## 用户报的（第二个截图）

        "这里也是白色，跟现有配色完全不符"

    ## 实测：工具页有**三层**白底

    ::

        ToolInterfaceHost        WA_StyledBackground=False  ← 裸 QWidget
        AutoCombatWidget         WA_StyledBackground=False  ← ScrollArea
        qt_scrollarea_viewport   WA_StyledBackground=False  ← 滚动区 viewport

    全部不透明 → 在玻璃背景上盖了一块**纯白**（实测取色 ``#efefef``）。

    ## 做法：从 ``stackedWidget`` 往下走一层，都设透明

    ⚠ 只对**页面这一层**设透明是安全的 ——
    它们没有"别的子控件要靠它取色"的情况。
    **不能**用全局 ``QWidget { background: transparent }``
    （那会把卡片、图标底全弄没）。
    """
    from PySide6.QtWidgets import QAbstractScrollArea, QStackedWidget

    stack = getattr(window, "stackedWidget", None)
    if not isinstance(stack, QStackedWidget):
        return

    for i in range(stack.count()):
        page = stack.widget(i)
        if page is None:
            continue
        _make_transparent(page)
        #: ★ ``ScrollArea`` 子类还要额外处理 viewport
        #: （它自己吃系统底色，光设控件本身不够）
        if isinstance(page, QAbstractScrollArea):
            vp = page.viewport()
            if vp is not None:
                _make_transparent(vp)


def paint_page_widget(page) -> None:
    """★ 给**单个页面**上透明 —— 工具页**懒创建**，建好之后要再调一次。

    ## 为什么需要这个

    ``ToolInterfaceHost`` 是**延迟宿主**：工具面板到第一次
    ``showEvent`` 才创建。所以 ``_paint`` 跑的时候它可能还不存在 ——
    等它建好了，又没人给它设透明，于是**还是白的**。

    → ``ToolInterfaceHost.ensure_panel()`` 建完面板后调这个。

    ## ⚠⚠ 实测有**四层**白底要处理

    ::

        ToolInterfaceHost        ← 懒创建的宿主
        AutoCombatWidget         ← ScrollArea 本身
        qt_scrollarea_viewport   ← 滚动区 viewport
        auto_combat_page         ← ★ **ScrollArea 的内层 view**（最容易漏）

    最后那层是 ``setWidget(view)`` 交进去的内层控件 ——
    它**不是** ``viewport()`` 返回的那个，得单独找出来。
    """
    from PySide6.QtWidgets import QAbstractScrollArea, QWidget

    if page is None:
        return
    _make_transparent(page)

    #: 页面自己就是滚动区 → 处理 viewport  +  内层 view
    if isinstance(page, QAbstractScrollArea):
        _transparent_scroll_area(page)
    #: 页面里**套着**的滚动区也要处理（工具面板常见）
    for child in page.findChildren(QAbstractScrollArea):
        _transparent_scroll_area(child)
    #: 兜底：页面首层子控件里那种"铺满的裸 QWidget"（内层 view 的常见形态）
    for child in page.findChildren(QWidget):
        if child.parent() is page and not child.objectName().startswith("qt_"):
            _make_transparent(child)


def _transparent_scroll_area(area) -> None:
    """把一个 ``QAbstractScrollArea`` 的 viewport + 内层 view 都设透明。"""
    from PySide6.QtWidgets import QAbstractScrollArea

    if not isinstance(area, QAbstractScrollArea):
        return
    vp = area.viewport()
    if vp is not None:
        _make_transparent(vp)
    #: ★ ``setWidget(view)`` 交进去的内层 view —— 不是 viewport
    inner = None
    if hasattr(area, "widget"):
        try:
            inner = area.widget()
        except (RuntimeError, AttributeError):
            inner = None
    if inner is not None and inner is not vp:
        _make_transparent(inner)


def _make_transparent(widget) -> None:
    """把一个控件设成"透明背景"（带 objectName 时用选择器，避免级联）。"""
    try:
        widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        name = widget.objectName()
        if name:
            widget.setStyleSheet(f"#{name} {{ background: transparent; }}")
        else:
            widget.setStyleSheet("background: transparent;")
    except (RuntimeError, AttributeError):
        return


def _paint_nav_panel(window, skin: dict) -> None:
    """单独给左侧栏刷渐变（它自带 styleSheet，会盖掉继承的）。"""
    panel = getattr(getattr(window, "navigationInterface", None),
                    "panel", None)
    if panel is None:
        return
    grad = gradient_qss(skin)
    try:
        panel.setStyleSheet(
            f"NavigationPanel {{ background: {grad}; }}")
        panel.setAttribute(
            Qt.WidgetAttribute.WA_StyledBackground, True)
        #: 侧栏里那块滚动区也要透明，否则上下分两截颜色
        scroll = getattr(panel, "scrollArea", None)
        if scroll is not None:
            scroll.setStyleSheet("background: transparent;")
            vp = scroll.viewport()
            if vp is not None:
                vp.setStyleSheet("background: transparent;")
    except (RuntimeError, AttributeError):
        return


def apply_current_skin() -> dict:
    """启动时：把存的皮肤应用上。"""
    skin = current_skin()
    apply_skin(skin["id"], save=False)
    return skin


def refresh_windows() -> None:
    """新窗口建好后调一次 —— 让它也带上当前皮肤。

    （``apply_skin`` 只刷**当时已存在**的窗口。）
    """
    _paint(current_skin())
