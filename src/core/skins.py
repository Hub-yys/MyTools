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
)

#: 默认皮肤 id（启动时回落到它）
DEFAULT_SKIN = "deepglass"

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
        f" CardWidget {{ {card_qss(skin)} }}"
    )


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
