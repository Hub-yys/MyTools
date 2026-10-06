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
    _set_theme_color(setThemeColor, skin["primary"])

    #: ★★★ 记住"**当前真正在用的**皮肤"—— 见 :func:`active_skin` 的说明。
    #: 必须在 ``_paint`` 之前设，否则 QSS 和明暗模式会对不上。
    global _ACTIVE_SKIN
    _ACTIVE_SKIN = skin["id"]

    _paint(skin)

    if save:
        from qfluentwidgets import qconfig

        qconfig.set(_skin_item(), skin["id"])
    return True


def _set_theme_color(set_theme_color, color, *, tries: int = 3) -> None:
    """调 ``setThemeColor``，**容忍 qfluentwidgets 的 GC 竞态**。

    ## ⚠⚠ 这个 ``RuntimeError`` 是它的 bug，不是我们的

    它内部是::

        for widget, file in list(styleSheetManager.items()):
            #  styleSheetManager 是 WeakKeyDictionary

    遍历**弱引用字典**时，如果正好有窗口被 GC 回收，字典大小就变了::

        RuntimeError: dictionary changed size during iteration

    **实测**：测试里连着建/销毁一堆 ``MainWindow`` 时，
    ``tests/test_updater.py`` 里一条用例**稳定复现**
    （每个测试都会 ``apply_skin``，而前面的窗口正好在那时候被回收）。

    这是纯粹的时间竞态 —— 生产环境窗口少、几乎撞不上，
    但**测试里必现**，而且报错信息完全指不到"皮肤"这件事上，
    非常难查。

    → 重试几次。字典遍历是**幂等**的：重来一遍就好了。
    真的一直失败也不该把界面弄崩 —— 记个日志、继续往下走。
    """
    for attempt in range(max(1, tries)):
        try:
            set_theme_color(color, save=False)
            return
        except RuntimeError as exc:
            if "changed size" not in str(exc):
                raise                          #: 别的 RuntimeError 照抛
            logger.debug("setThemeColor 撞上 GC 竞态（第 %d 次）",
                         attempt + 1)
    logger.warning("setThemeColor 重试 %d 次仍失败（GC 竞态）", tries)


#: ★★★ **当前真正在用的皮肤 id**（不是"存的那个"）
#:
#: ## ⚠⚠ 为什么需要这个（用户 2026-10-05 截图报的"字看不清"）
#:
#: 症状：界面上**背景是浅色、字也是浅色** → 看不清。
#:
#: 根因是两个"当前皮肤"**对不上**：
#:
#: * ``setTheme(DARK)`` 真的把 **明暗模式**切成了暗色
#:   （qfluentwidgets 于是把文字画成浅色）
#: * 但 ``current_skin()`` 读的是**存盘的那个**（还是浅色的 mist）
#:   → ``refresh_windows()`` 拿 mist 的 QSS 去刷 → 背景画成浅色
#:
#: 实测::
#:
#:     apply_skin("deepglass", save=False)
#:     current_skin()["id"]  →  "mist"      ← 存盘没变（预览的语义）
#:     isDarkTheme()         →  True        ← 但主题真的切了
#:     → 浅色背景 + 浅色文字 = 看不清
#:
#: → 用 ``_ACTIVE_SKIN`` 记住**实际刷上去的那个**；
#: ``refresh_windows()`` / 建新窗口时都用它，两边就永远一致。
_ACTIVE_SKIN: str = ""


def active_skin() -> dict:
    """**当前真正在用的**皮肤（新窗口 / 重刷 QSS 都该用它）。

    ⚠ 跟 :func:`current_skin` 的区别：
    ``current_skin()`` 是**存盘的选择**（用户点"使用这款"才会变），
    ``active_skin()`` 是**此刻界面上真正生效的**（预览也会让它变）。

    没有过任何 apply 时回落到 ``current_skin()``。
    """
    if _ACTIVE_SKIN:
        skin = skin_by_id(_ACTIVE_SKIN)
        if skin is not None:
            return skin
    return current_skin()


def _paint(skin: dict) -> None:
    """把皮肤的配色刷到**所有窗口 + Qt 调色板**上。

    ## ⚠⚠ 这里是"改一下要等好久"的元凶（2026-10-05 实测查出来）

    现象：**点一下皮肤卡片，界面卡 4.9 秒**；整套测试从 12 分钟涨到 42 分钟。

    根因：``app.setStyleSheet()`` 会**递归套用到所有 widget**，
    开销是 **O(总 widget 数)**::

        窗口 1 个, widget  2572 → 1.67s
        窗口 2 个, widget  5144 → 3.26s
        窗口 4 个, widget 10288 → 6.15s

    一个 ``MainWindow`` 就有 **2570 个 widget**（工具页 + 卡片 + 列表）。
    测试里建几十个窗口不关 → 累积上万 widget → 越跑越慢。

    ## ⚠⚠⚠ window 级 QSS **不能省**（我为了提速删过一次，白缝就回来了）

    2026-10-05 我为提速把 ``w.setStyleSheet(qss)`` 删了，理由写的是
    "app 级的会继承下来" —— **那个理由是错的**。

    项目里原本就写着（我删的时候没看）::

        ⚠ 还要**逐个顶层窗口再设一遍** —— 主窗口有自己的调色板，
        只设 app 级会被它**盖掉**（实测 app 级 74.4%，window 级 99.1%）

    删掉之后的实测后果：``MainWindow.styleSheet()`` **长度 37**
    （只剩我自己设的 navResizer 那条）、**没有渐变** →
    主窗口用回自己的调色板 → **顶部和侧栏出现白缝**
    （用户 2026-10-06 截图又圈出来了："这个白缝怎么又出现了"）。

    ## ✓ 正确做法：window 级保留，用别的方式省时间

    **① app 级 QSS 只在"皮肤真的变了"时设**

    实测 ``app.setStyleSheet`` **1.39s** vs ``window.setStyleSheet``
    **0.34s**（快 4 倍）—— 但 app 级是**必须**的：
    只设 window 级的话，新弹的**对话框**拿不到配色
    （实测裸 ``QDialog`` 里的 label ``styleSheet()`` 是空的）。

    → **两个都设**（先 app 后 window，window 的优先级更高、正好覆盖），
    但同一个皮肤重复 apply 时**整体跳过** —— 用户连点两次不该卡两次。

    **② 自带 styleSheet 的控件仍然单独设** —— 那是**必须**的：
    ``NavigationPanel``（584 字符）/ ``FluentTitleBar``（1990 字符）
    优先级高于继承，不单独设就会"右边玻璃左边白板"。
    """
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        return

    global _PAINTED_QSS, _PAINTED_WINDOWS
    qss = build_qss(skin)

    #: ⚠ 只处理**看得见**的窗口（测试里建了没显示的不用管）
    targets: list = []
    for w in app.topLevelWidgets():
        try:
            if w.isVisible():
                targets.append(w)
        except (RuntimeError, AttributeError):
            continue

    #: ★★ 缓存判断要**连窗口一起看**（2026-10-06 修）
    #:
    #: ## ⚠⚠ 只比 QSS 是不够的 —— 会漏掉"后来才建的窗口"
    #:
    #: 实测的坑：``MainWindow.__init__`` 里就调了 ``apply_current_skin()``，
    #: **那时新窗口还没 show()**、不在 ``targets`` 里。于是::
    #:
    #:     apply #1（建窗口过程中）→ 刷了 app 级，targets 是**空的**
    #:                              → 记下 _PAINTED_QSS
    #:     apply #2（窗口显示后）  → qss 相同 → **直接 return**
    #:                              → 新窗口从来没被刷过 → 白缝
    #:
    #: 所以缓存要记"**刷过哪些窗口**"，有新窗口就补刷。
    if qss == _PAINTED_QSS and set(map(id, targets)) <= _PAINTED_WINDOWS:
        return

    app.setStyleSheet(qss)
    _paint_palette(app, skin)

    for w in targets:
        #: ★★★ **必须**再给窗口设一遍 —— 主窗口有自己的调色板，
        #: 只设 app 级会被它**盖掉**（实测 app 级 74.4%，window 级 99.1%）。
        #:
        #: ⚠⚠ 我为了提速删过这一行，结果**顶部和侧栏的白缝就回来了**
        #: （用户 2026-10-06："这个白缝怎么又出现了"）。
        #: 见函数文档里的"window 级 QSS 不能省"。
        try:
            w.setStyleSheet(qss)
        except (RuntimeError, AttributeError):   #: 已销毁的窗口
            continue
        _paint_nav_panel(w, skin)       #: 自带 styleSheet，必须单独设
        _paint_title_bar(w, skin)       #: 同上
        _paint_pages(w)                 #: 页面那几层要显式透明

    #: ★ 记下"已经刷过这份 QSS + 这些窗口"—— 下次同一个皮肤 + 同样窗口才跳过
    _PAINTED_QSS = qss
    _PAINTED_WINDOWS = set(map(id, targets))


#: ★ 上一次**真正刷上去**的 QSS（用来跳过重复刷）
#:
#: 用户连点两次同一款皮肤、或者测试里反复 apply 默认皮肤时，
#: 那 1.4 秒的 ``app.setStyleSheet`` 完全可以省掉。
_PAINTED_QSS: str = ""

#: ★ 上一次刷过的**窗口 id 集合**（``_PAINTED_QSS`` 的配套）。
#:
#: ## ⚠⚠ 为什么光有 QSS 缓存不够（2026-10-06 的"白缝又回来了"）
#:
#: ``MainWindow.__init__`` 里就调了 ``apply_current_skin()`` ——
#: **那时新窗口还没 show()**，不在可见窗口列表里。于是::
#:
#:     apply #1（建窗口过程中）→ target 是**空的**，只刷了 app 级
#:                              → 记下 _PAINTED_QSS
#:     apply #2（窗口 show 之后）→ QSS 相同 → **直接 return**
#:                              → 新窗口永远没被刷过 → 顶部/侧栏白缝
#:
#: 所以缓存必须**连窗口一起比**：有新窗口就补刷。
_PAINTED_WINDOWS: set[int] = set()


def _paint_palette(app, skin: dict) -> None:
    """★ 同步 **Qt 系统调色板** —— 让**裸 Qt 控件**也跟着换色。

    ## ⚠⚠ 为什么必须做（用户 2026-10-05 截图："不然看不清字了"）

    有些控件是**裸 Qt 控件**，不认 qfluentwidgets 的主题：

    * ``QTextEdit``（「资源库更新」那个日志框）
    * 原生 ``QLabel`` / ``QLineEdit`` / ``QTreeWidget`` …

    它们用**系统调色板**取色。实测::

        深空玻璃（暗色）:  QTextEdit 底色=#ffffff  字色=#000000

    也就是说切到暗色皮肤后，**它还是白底黑字**；
    而玻璃 QSS 又把它的底压暗了 → **深底 + 深字 = 看不见**
    （用户截图里圈的就是这个）。

    → 把皮肤的颜色**同步写进 Qt 调色板**，裸控件就跟着变了。
    """
    from PySide6.QtGui import QColor, QPalette

    dark = skin["mode"] == "dark"
    bg = QColor(skin["bg"][0][1])              #: 渐变第一个 stop 当底色
    card = _solid_card(skin, bg, dark)
    text = QColor(skin["text"])
    dim = QColor(skin["dim"])

    pal = app.palette()
    for role, color in (
        (QPalette.ColorRole.Window, bg),
        (QPalette.ColorRole.WindowText, text),
        (QPalette.ColorRole.Base, card),
        (QPalette.ColorRole.AlternateBase, bg),
        (QPalette.ColorRole.Text, text),
        (QPalette.ColorRole.Button, bg),
        (QPalette.ColorRole.ButtonText, text),
        (QPalette.ColorRole.ToolTipBase, card),
        (QPalette.ColorRole.ToolTipText, text),
        (QPalette.ColorRole.PlaceholderText, dim),
        (QPalette.ColorRole.Highlight, QColor(skin["primary"])),
        (QPalette.ColorRole.HighlightedText,
         QColor("#ffffff" if dark else "#ffffff")),
    ):
        pal.setColor(role, color)
    #: 禁用态也给它一套（不然"未启用"的控件会刺眼）
    pal.setColor(QPalette.ColorGroup.Disabled,
                 QPalette.ColorRole.Text, dim)
    pal.setColor(QPalette.ColorGroup.Disabled,
                 QPalette.ColorRole.WindowText, dim)
    app.setPalette(pal)


def _rgba(text: str) -> tuple[int, int, int, float]:
    """解析 ``"rgba(255, 255, 255, 0.055)"`` → ``(r, g, b, alpha 0~1)``。

    ⚠⚠ **不能直接 ``QColor("rgba(...)")``** —— 实测它解析不出来，
    返回的是**黑色**（alpha 也丢了）。我的第一版就是这么写的，
    结果 ``Base`` 被设成 ``#000000``（暗色皮肤下日志框还是黑底）。

    解析不了就回落到 ``(255, 255, 255, 1.0)``。
    """
    import re

    m = re.match(
        r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)"
        r"(?:\s*,\s*([\d.]+)\s*)?\)",
        str(text or "").strip(), re.I)
    if not m:
        return 255, 255, 255, 1.0
    r, g, b = int(m.group(1)), int(m.group(2)), int(m.group(3))
    alpha = float(m.group(4)) if m.group(4) is not None else 1.0
    return r, g, b, max(0.0, min(1.0, alpha))


def _solid_card(skin: dict, bg, dark: bool):
    """把**半透明的卡片色**算成一个**实色**（Qt 调色板不吃 alpha）。

    ``rgba(255,255,255,0.055)`` 直接当颜色用是不行的 ——
    得**垫在底色上**混一下，才是它实际看起来的颜色。

    ⚠ 第一版拿 ``QColor(skin["card"])`` 去读 rgba，读出**黑色**，
    于是 ``Base`` 成了黑的（实测 ``#000000``）。见 :func:`_rgba`。
    """
    from PySide6.QtGui import QColor

    if not str(skin["card"]).lower().startswith("rgba"):
        return QColor(skin["card"])
    r, g, b, a = _rgba(skin["card"])
    return _blend(bg, QColor(r, g, b), a)


def _blend(base, top, alpha: float):
    """把 ``top`` 按 ``alpha`` 混到 ``base`` 上（算个实色）。"""
    from PySide6.QtGui import QColor

    a = max(0.0, min(1.0, alpha))
    return QColor(
        int(base.red() * (1 - a) + top.red() * a),
        int(base.green() * (1 - a) + top.green() * a),
        int(base.blue() * (1 - a) + top.blue() * a),
    )


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

    ⚠⚠ 用 :func:`active_skin`（**真正在用的**），不是 ``current_skin()``
    （存盘的那个）—— 两者在"预览"时会不一致，
    拿错的去刷就会出现**浅色背景 + 浅色字**（用户截图报过）。
    """
    _paint(active_skin())
