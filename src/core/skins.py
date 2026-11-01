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
    # ══════════════════════════════════════════════════════════════════
    #  ★★★ 2026-10-31 用户：「删掉配色主题，只留壁纸」
    #
    #  之前有 7 款配色主题（晨雾/樱雾/深空/星云/幽海/熔火/星轨紫）。
    #  它们的问题：**背景是不透明渐变，把壁纸整个盖住了**。
    #
    #  用户截图：选了配色主题 → 壁纸还在播但看不见，界面变回素色板。
    #  所以干脆删掉，只留**一款基础主题** —— 它只提供：
    #
    #    * 文字/强调色/卡片边框 这些**配色令牌**
    #    * 深色底（壁纸没铺时 / 加载中时的兜底）
    #
    #  界面背景由**壁纸**负责（见 `gui/wallpaper_layer.py`）。
    # ══════════════════════════════════════════════════════════════════
    {
        "id": "glass",
        "name": "液态玻璃",
        "desc": "深色底 + 玻璃面板，背景交给壁纸",
        "mode": "dark",
        "primary": "#8B7CFF",
        "bg": [(0.0, "#0C0A18"), (0.5, "#141026"), (1.0, "#090713")],
        "card": "rgba(255, 255, 255, 0.06)",
        "border": "rgba(170, 160, 255, 0.14)",
        "text": "#ECE9FF",
        "dim": "#9A93C4",
    },
)

#: 默认皮肤 id（启动时回落到它）
#:
#: ★ 用户 2026-10-05 定的：默认用**晨雾玻璃**（浅色那款）。
#: 之前默认是「深空玻璃」（暗色）。
DEFAULT_SKIN = "glass"

#: 持久化用的 ``ConfigItem`` —— qconfig 只认它（**不是**裸字符串）
#:
#: ## ⚠⚠⚠ 这里修过一个**"皮肤选了不生效、重开又变回去"**的 bug
#: （用户 2026-10-08 装完包才发现："皮肤应用之后，再次重新打开，还是之前的皮肤"）
#:
#: ### bug ①：item 挂在**模块级**，qconfig 根本存不了它
#:
#: ``QConfig.toDict()`` 的实现是::
#:
#:     for name in dir(self._cfg.__class__):        # ← 扫**类属性**
#:         item = getattr(self._cfg.__class__, name)
#:         if not isinstance(item, ConfigItem):
#:             continue
#:         ...
#:
#: **它只认识挂在 ``QConfig`` 子类上的类属性。** 而原来这个 item 是
#: 模块级普通变量 —— ``qconfig.set()`` 改得了内存，``save()`` 时**扫不到它**，
#: 于是**永远不落盘**。实测::
#:
#:     模块级 item  → 落盘 ['QFluentWidgets']                ← 没有 Skins ✗
#:     类属性 item  → 落盘 ['QFluentWidgets', 'ProbeTest']   ← 存上了 ✓
#:
#: ### bug ②：配置文件写在**相对路径**（跟着当前工作目录跑）
#:
#: ``qconfig.file`` 默认是 ``WindowsPath('config/config.json')`` ——
#: **相对路径**。开发时 CWD 是项目目录（看着正常），
#: **打包后 CWD 是安装目录** → 配置写进安装目录（甚至写不进去）。
#:
#: → 修法：见 :func:`_ensure_config_file` —— 把 qconfig 的落盘位置
#: 指到 :func:`src.core.paths.user_data_dir`（和别的用户数据放一起）。
_SKIN_ITEM = None


def _ensure_config_file() -> None:
    """★ 把 ``qconfig`` 的落盘位置指到**用户数据目录**（只做一次）。

    ## ⚠ 为什么必须做

    ``qconfig.file`` 默认是**相对路径** ``config/config.json`` ——
    落在**当前工作目录**下。开发时是项目目录（看着没事），
    **打包后是安装目录**：重装/卸载会清掉，装到 ``Program Files``
    还可能根本没权限写。

    → 指到 ``<用户数据>/config.json``，跟 ``ui_state.json`` /
    ``gacha_history.json`` 那些放一起。

    ⚠ 用 ``Path`` 不是 ``str`` —— qfluentwidgets 内部会 ``.parent``，
    给字符串会炸 ``AttributeError``（这个坑踩过）。

    ## ⚠⚠⚠ 改路径的**正确姿势是 ``load(file=...)``**

    ## ⚠ 改路径用带参数的 ``load()``（两种写法其实都行，但这个更直白）

    ``QConfig.load(file=...)`` 内部会 ``self._cfg.file = Path(file)``
    再读盘 —— **一步到位**，不用操心 ``qconfig`` 和 ``qconfig._cfg``
    那两个对象的关系::

        qconfig.load(file=target)   # 设路径 + 读盘

    ⚠⚠ 我一度断言"手动 ``qconfig.file = x`` 不生效"，**那是误判**。
    实测（脚本对比过）**两种写法都能让 ``save()`` 写到新路径**。

    之所以看着"不生效"，是因为**这个函数每次都把路径纠正回**
    ``target``（那正是它的职责）—— 盖掉了测试里临时改的值。

    ⚠ 因此**测试没法靠改 ``qconfig.file`` 来隔离配置** ——
    得备份真实文件、测完还原（见 ``TestSkinPersists``）。
    """
    from qfluentwidgets import qconfig

    from . import paths

    target = paths.user_data_dir() / "config.json"
    try:
        if str(qconfig.file) == str(target):
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        #: ★ 带参数的 load —— 设路径 + 读盘一步到位
        qconfig.load(file=target)
    except Exception:  # noqa: BLE001 - 配置存不下也不该让程序起不来
        logger.warning("设置 qconfig 落盘位置失败", exc_info=True)


def _skin_item():
    """皮肤配置的 ``ConfigItem``（懒建）。

    ## ⚠⚠⚠ 必须挂在 **``QConfig`` 类本身**上

    ``qconfig.save()`` → ``self._cfg.toDict()`` → 遍历的正是::

        for name in dir(self._cfg.__class__):     # ← QConfig 这个类
            item = getattr(self._cfg.__class__, name)
            if not isinstance(item, ConfigItem): continue

    ⚠ 我第一版把 item 挂到**自己新建的一个类**上（``_SkinConfig``）——
    **没用**：``qconfig._cfg.__class__ is QConfig``，扫的是 ``QConfig``，
    不是我那个类。实测确认过::

        qconfig._cfg.__class__ = <class 'QConfig'>
        我挂的 _SkinConfig      = <class 'src.core.skins._SkinConfig'>
        两者是同一个吗 = False        ← 所以还是存不上

    → 直接 ``setattr(QConfig, ...)``。qfluentwidgets 自己的配置项
    （``qconfig.themeColor`` 那些）就是这么挂的 —— 我们补一个同款。
    """
    global _SKIN_ITEM
    if _SKIN_ITEM is None:
        from qfluentwidgets import OptionsConfigItem, OptionsValidator
        from qfluentwidgets.common.config import QConfig

        #: ⚠⚠⚠ **顺序不能反**（这是我踩的最后一个坑，绕了好几圈）
        #:
        #: ``_ensure_config_file()`` 里会 ``qconfig.load()`` ——
        #: 而 ``load()`` 是**遍历 QConfig 的类属性**把值填进去的。
        #:
        #: 所以必须**先注册 item、再 load**::
        #:
        #:     ① item 建好
        #:     ② 挂到 QConfig 上      ← 让 load() 找得到它
        #:     ③ 改文件路径 + load()  ← 这时才会把磁盘的值填进 item
        #:
        #: 我原来写的是 ③①② —— load() 跑的时候 ``QConfig.skin`` 还不存在，
        #: 于是磁盘上明明有 ``ember``，读出来还是默认的 ``mist``。
        item = OptionsConfigItem(
            "Skins", "CurrentSkin",
            DEFAULT_SKIN,
            OptionsValidator([s["id"] for s in SKINS]),
        )
        try:
            QConfig.skin = item          # type: ignore[attr-defined]
        except Exception:                # noqa: BLE001
            logger.warning("把皮肤配置挂到 QConfig 失败", exc_info=True)

        #: ★ 改动路径 + 重新读盘（会把这个 item 的值填上）
        _ensure_config_file()

        _SKIN_ITEM = item
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


def is_character_skin(skin: dict) -> bool:
    """这个皮肤是不是**角色主题**（带抽卡动画那种）。

    ## 判据

    有 ``character`` 和 ``avatar`` 两个字段 = 角色主题。
    上面那 6 款纯配色皮肤没有这两个字段。

    ## 为什么用"有没有这个字段"而不是加个 ``type`` 字段

    ① 老皮肤定义不用动（向后兼容，不动现有数据结构）；
    ② ``character`` 本身就有意义（界面上要显示"这是哪个角色的主题"），
       不是为判类型而生的占位字段。

    :param skin: 皮肤 dict（可能是 ``None``，容错）
    """
    if not isinstance(skin, dict):
        return False
    return bool(skin.get("character") and skin.get("avatar"))


def character_skins() -> tuple[dict, ...]:
    """所有**角色主题**（带抽卡动画那些）。

    界面把它们单独排一组，和纯配色皮肤区分开。
    """
    return tuple(s for s in SKINS if is_character_skin(s))


def color_skins() -> tuple[dict, ...]:
    """所有**纯配色**皮肤（没有角色主题那些）。"""
    return tuple(s for s in SKINS if not is_character_skin(s))


def gacha_style(skin: dict) -> dict:
    """取一个皮肤的抽卡动画配色（不是角色主题就返回空 dict）。

    :func:`src.gui.gacha_reveal` 用它上色；返回空 dict 时那边自己用兜底色。
    """
    if not is_character_skin(skin):
        return {}
    style = skin.get("gacha")
    return dict(style) if isinstance(style, dict) else {}


def should_play_on_start(skin: dict) -> bool:
    """这个主题要不要在**启动时**自动播一遍开卡动画。

    ## 用户 2026-10-30

    > 我要在启动的就播放爱弥斯的抽卡动画

    ## 判据

    * 必须是角色主题（``is_character_skin``）
    * 且 ``play_on_start`` 为真（角色主题可以单独关掉这个行为）

    默认：角色主题没写 ``play_on_start`` 时**当 False**
    （不写就播的话，以后加角色主题会莫名其妙多出 2.6 秒启动等待）。
    """
    if not is_character_skin(skin):
        return False
    return bool(skin.get("play_on_start"))


def splash_image(skin: dict) -> str:
    """取角色主题的**定格立绘**相对路径（``assets/`` 下的）。

    没有 ``splash`` 字段就退回 ``avatar``（小图，放大会糊但至少有个图）。
    返回值是相对 ``assets/`` 的路径，空串 = 没有图。
    """
    if not is_character_skin(skin):
        return ""
    return str(skin.get("splash") or skin.get("avatar") or "")


def current_skin() -> dict:
    """当前皮肤（没存过就用默认）。"""
    from qfluentwidgets import qconfig

    skin_id = qconfig.get(_skin_item())
    return skin_by_id(str(skin_id)) or skin_by_id(DEFAULT_SKIN)


def gradient_qss(skin: dict) -> str:
    """把 ``bg`` 的 stop 列表拼成 QSS 的 ``qlineargradient``。

    ⚠ 2026-10-31：这是**底层**深色渐变。
    "湿玻璃"那层高光见 :func:`glass_qss`，两个要叠起来用
    （见 :func:`glass_layers`）。
    """
    stops = ", ".join(
        f"stop:{pos:g} {color}" for pos, color in skin["bg"])
    return (f"qlineargradient(x1:0, y1:0, x2:1, y2:1, {stops})")


def glass_qss(skin: dict) -> str:
    """★ 磨砂玻璃的**高光层**（叠在底色渐变之上）。

    ## ★★★ 2026-10-31 用户

        > 现在也没 dsh 的液体玻璃质感啊

    ## 为什么之前没有玻璃感

    原来的 QSS 是::

        QStackedWidget { background: qlineargradient(...); }   ← 一层渐变了事

    那是**一块纯色板**，没有任何玻璃特征。玻璃的视觉要素是：

        ① **顶部高光** —— 光从上方来，面板顶端亮一道，往下迅速渐隐
        ② **边缘反光** —— 1px 浅色描边（玻璃边缘折射）
        ③ **厚度感**   —— 顶边比底边亮

    Qt QSS **不支持** ``box-shadow`` / ``backdrop-filter``，
    所以只能用「**两层渐变叠加**」伪造：

        上层 = 白 → 透明 的竖直渐变（顶部 0.20，38% 处 0.07，底部 0.02）
        下层 = 深色底渐变（原有的 bg）

    这正是 DSH 那个插件的配方（``client.js`` 第 2385~2387 行）::

        background-image: linear-gradient(180deg,
            rgba(255, 255, 255, 0.16),
            rgba(255, 255, 255, 0.05) 38%,
            rgba(255, 255, 255, 0.02));

    :param skin: 主题 dict（按 ``mode`` 决定高光强度 —— 暗底要更亮才看得见）
    """
    dark = skin.get("mode") == "dark"
    top = 0.20 if dark else 0.55
    mid = 0.07 if dark else 0.20
    bot = 0.02 if dark else 0.06
    return (
        "qlineargradient(x1:0, y1:0, x2:0, y2:1,"
        f" stop:0 rgba(255, 255, 255, {top}),"
        f" stop:0.38 rgba(255, 255, 255, {mid}),"
        f" stop:1 rgba(255, 255, 255, {bot}))"
    )


def glass_layers(skin: dict, alpha: float = 1.0) -> str:
    """★ 把"高光层 + 底色层"拼成能直接塞进 ``background:`` 的值。

    ## QSS 的多层 background

    ``background`` 支持逗号分隔多层（Qt 5.6+）::

        background: qlineargradient(<高光>), qlineargradient(<底色>);

    **先写的在上层** —— 所以高光放前面。

    ## ★ ``alpha``：让底下的壁纸透出来

    玻璃的物理前提是"**背后有东西可透**"。
    DSH 那个界面像玻璃，是因为面板后面有壁纸/画面。

    这里把底色的每个 stop 转成 ``rgba()`` 并乘 ``alpha``：

    * ``alpha=1.0`` → 完全不透明（没壁纸时最清楚）
    * ``alpha=0.55`` → 壁纸透出 45%（有壁纸时的玻璃感）

    ⚠ **渐变色本身不支持整体透明度**，必须逐个 stop 转 ``rgba``。
    好在主题的 ``bg`` 本来就是 ``#RRGGBB``，转 rgba 很简单。
    """
    hi = glass_qss(skin)
    if alpha >= 0.99:
        return f"{hi}, {gradient_qss(skin)}"
    #: 把底色的每个 stop 转成半透明 rgba
    stops = []
    for pos, color in skin["bg"]:
        rgb = _hex_to_rgb(color)
        if rgb is None:
            #: 已经带 alpha 或解析不了 → 原样塞
            stops.append(f"stop:{pos:g} {color}")
        else:
            r, g, b = rgb
            stops.append(f"stop:{pos:g} rgba({r}, {g}, {b}, {alpha:g})")
    base = ("qlineargradient(x1:0, y1:0, x2:1, y2:1, "
            + ", ".join(stops) + ")")
    return f"{hi}, {base}"


def _hex_to_rgb(color: str) -> tuple[int, int, int] | None:
    """``#RRGGBB`` → ``(r, g, b)``。其它格式返回 ``None``。"""
    if not isinstance(color, str):
        return None
    c = color.strip()
    if not c.startswith("#") or len(c) != 7:
        return None
    try:
        return (int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16))
    except ValueError:
        return None


def _has_wallpaper() -> bool:
    """★ 当前有没有壁纸在**真的显示**（CPU 或 Chromium 任一路径）。

    ## ★★★ 2026-10-31 修「选了壁纸界面还是深色底」

    用户截图：切到「守岸人钢琴版」显示「使用中」，但**界面背景是纯深色**，
    壁纸完全没显示。

    ## 根因

    `build_qss` / `_paint_nav_panel` / `_paint_title_bar` 三处都这样判断::

        from ..gui import wallpaper_layer as _wl
        _walled = _wl.current_layer() is not None

    **`wallpaper_layer.current_layer()` 只代表 CPU 那条路径**。
    现在壁纸走的是 **Chromium**（`wallpaper_web`），CPU 层是 None ——
    于是三处都以为没有壁纸，QSS 走了**不透明深色底**分支，
    把 Chromium 的壁纸整个盖住了。

    → 统一用这个函数判断（两条路径都查）。
    """
    #: ① CPU 路径
    try:
        from ..gui import wallpaper_layer as _wl  # noqa: PLC0415

        if _wl.current_layer() is not None:
            return True
    except Exception:  # noqa: BLE001
        pass
    #: ② DSH 同款（Chromium 整层）—— 当前主用
    try:
        from ..gui import wallpaper_dsh as _wd  # noqa: PLC0415

        if _wd.current_layer() is not None:
            return True
    except Exception:  # noqa: BLE001
        pass
    #: ③ QtQuick 路径（备用）
    try:
        from ..gui import wallpaper_quick as _wq  # noqa: PLC0415

        if _wq.current_layer() is not None:
            return True
    except Exception:  # noqa: BLE001
        pass
    #: ③ Chromium 路径（保留，备用）
    try:
        from ..gui import wallpaper_web as _ww  # noqa: PLC0415

        if _ww.current_layer() is not None:
            return True
    except Exception:  # noqa: BLE001
        pass
    return False


def card_qss(skin: dict, solid_back=None, solid_alpha: float = 0.0) -> str:
    """把卡片样式拼成 QSS —— **透明玻璃 + 高光边框**（可选深色底）。

    ## ★★★ 2026-10-31 卡片改成**透明**

    用户：

        > 这卡片还挡住了，不能透明的吗

    ## 之前的错误

    我以为"卡片必须够实"才能看清文字，压了 82% 深色底。
    结果**卡片背后的模糊壁纸被完全挡住** —— 那就白模糊了，
    看着就是一块深色板，完全没有玻璃感。

    ## 正确做法（和 DSH 一致）

    **卡片本身透明**，只留：

      * 顶部白色高光渐变（湿玻璃的"反光"）
      * 1px 浅色边框 + 更亮的顶边（玻璃边缘）

    文字之所以清楚，靠的是**背后的模糊壁纸**（由画布绘制），
    不是靠卡片自己压深色 —— 这正是 ``backdrop-filter`` 的原理：
    模糊提供低对比度底，内容自然就清楚了。

    ## ★★★ 2026-10-31 又修：「卡片有一层白底挡住壁纸」

    用户截图：卡片是一片**白半透明**，把背后壁纸盖住了。

    根因是**双背景冲突**：``build_qss`` 之前这样拼::

        _card = card_qss(skin)              #: 含 background: <白高光>
        _card = f"{_card} background: <白0.10+深色0.82>;"
                                 # ↑ QSS 后写的 background **完全覆盖**前面的

    → 那个 0.10 的白就成了"白底"。

    **现在只生成一次 background**：通过参数 ``solid_back`` / ``solid_alpha``
    决定要不要垫深色底 —— 要垫就**合并成一层**（高光在上、深色在下，
    QSS 的多层 background 语法），不再写两遍。

    :param skin: 主题 dict
    :param solid_back: 需要垫的深色底 ``(r, g, b)``；``None`` = 不垫（纯透明）
    :param solid_alpha: 深色底的不透明度
    """
    dark = skin.get("mode") == "dark"
    hi = 0.30 if dark else 0.75
    #: ★ 高光强度：有壁纸时明显（湿玻璃反光），无壁纸时**几乎不要**
    #:
    #: 用户截图：「这种卡片挡住的问题能解决吗」——
    #: 他看到的"挡住"就是这层白高光。
    #:
    #: 有壁纸时它有价值（玻璃反光，和背后的模糊画面产生层次）；
    #: 没壁纸时背后只是一片深色渐变，白色高光纯属**多余的遮挡**。
    if solid_back is not None and solid_alpha > 0:
        hi_scale = 0.18          #: 无壁纸 → 很弱
    else:
        hi_scale = 0.45          #: 有壁纸 → 湿玻璃反光
    hi_layer = (
        f"qlineargradient(x1:0, y1:0, x2:0, y2:1,"
        f"  stop:0 rgba(255, 255, 255, {hi * hi_scale:g}),"
        f"  stop:0.5 rgba(255, 255, 255, {hi * hi_scale * 0.26:g}),"
        f"  stop:1 rgba(255, 255, 255, 0))"
    )
    #: ★★★ 2026-10-31 **照 DSH 插件的玻璃配方**
    #:
    #: 用户：「不对吧，这是 DSH 的设置，你再看下」——
    #: 他指的是壁纸引擎插件设置页里的「玻璃颜色 / 玻璃透明度 / 边框」。
    #:
    #: 从 ``dsh-plugin-wallpaper-engine/lib/client.js`` 挖出来的真配方::
    #:
    #:     READABILITY_FLOOR_DARK = 0.59          (深色主题)
    #:     --we-sur ce-tint-dark  = #0d1524       (深藏青)
    #:     --we-glass-alpha       = 0.40          (用户设的玻璃透明度)
    #:
    #:     background = color-mix(
    #:         #0d1524 × 0.59,                    ← 59% 深藏青
    #:         tint × glass_alpha × 0.9~1.1)      ← 41% 玻璃色
    #:
    #: **DSH 的面板不是"透明 + 模糊"，而是"59% 深藏青底 + 41% 玻璃色"**
    #: —— 这就是它看起来暗一大截的原因。
    #:
    #: 我之前把卡片设成纯透明（只有 6% 白高光），当然比 DSH 亮得多。
    #:
    #: ## 实现
    #:
    #: QSS 没有 ``color-mix``，用 ``rgba`` 手算：
    #: 59% 的 #0d1524 叠在壁纸上 ≈ ``rgba(13, 21, 36, 0.59)``。
    #: ★★★ 2026-11-01 参数**从设置读**（照抄插件，用户可调）
    try:
        from . import wallpaper_settings as _WS  # noqa: PLC0415

        _layers = _WS.glass_layers()
        READ_FLOOR_DARK = _layers["floor"]
        DARK_BASE = _layers["base_rgb"]
        _glass_a = _layers["glass_alpha"]
        _glass_rgb = _layers["glass_rgb"]
    except Exception:  # noqa: BLE001
        READ_FLOOR_DARK = 0.59
        DARK_BASE = (13, 21, 36)
        _glass_a = 0.164
        _glass_rgb = (139, 124, 255)
    if solid_back is not None and solid_alpha > 0:
        #: 无壁纸：用主题派生底色（不需要压这么狠）
        bg = (f"background: {hi_layer},"
              f" rgba({solid_back[0]}, {solid_back[1]}, {solid_back[2]},"
              f" {solid_alpha:g});")
    else:
        #: 有壁纸：DSH 配方 = 玻璃色层 + 深藏青底（参数来自设置）
        gr, gg, gb = _glass_rgb
        glass_a = _glass_a
        bg = (
            f"background: {hi_layer},"
            #: ① 玻璃色（壁纸主色）
            f" rgba({gr}, {gg}, {gb}, {glass_a:.3f}),"
            #: ② 深藏青底 —— 这是"暗"的来源
            f" rgba({DARK_BASE[0]}, {DARK_BASE[1]}, {DARK_BASE[2]},"
            f" {READ_FLOOR_DARK:g});"
        )
    return (
        bg
        #: 1px 浅边 = 玻璃边缘
        + f" border: 1px solid {skin['border']};"
        #: 顶边更亮 = 顶面反光（"湿"的关键）
        + f" border-top-color: rgba(255, 255, 255, {hi:g});"
        + f" border-radius: 10px;"
    )


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

    ``QScrollBar`` 是**滚动条** —— 用户 2026-10-06::

        "这个滑轮组件很丑"

    ⚠ 默认的 ``QScrollBar`` 是**系统原生外观**（灰底 + 方头 + 两端的
    小箭头按钮），跟玻璃主题完全不搭。这里统一刷成：
    透明轨道 + 圆角滑块 + **没有箭头按钮**。

    ⚠ 别用笼统的 ``QWidget { background: ... }`` —— 那会把**所有**
    子控件（图标、标签底）一起涂了，层次全糊（实测过）。
    """
    grad = gradient_qss(skin)
    #: ★★★ 2026-10-31 用**玻璃叠层**替换单层渐变。
    #:
    #: 原来三块背景都是 ``background: {grad}`` —— 一块纯色板，没有玻璃感。
    #: 现在是「白高光渐变 + 深色底渐变」两层叠起来 = 磨砂玻璃。
    #: 见 :func:`glass_qss` 的说明。
    glass = glass_layers(skin)

    #: ★★★ 2026-10-31 **卡片分两种情况**
    #:
    #: 卡片现在是"透明 + 高光 + 边框"（见 :func:`card_qss`）——
    #: 它依赖**背后有模糊壁纸**才看得清（这正是 backdrop-filter 的原理）。
    #:
    #: 所以：
    #:   * **有壁纸** → 用透明版（能透出模糊壁纸，和 DSH 一致）
    #:   * **没壁纸** → 卡片必须自己压一层深色底，否则文字糊在渐变上
    #:
    #: ## ★★★ 2026-10-31 修「卡片有一层白底挡住壁纸」
    #:
    #: 用户截图：卡片上是**一片白半透明**，把背后的壁纸盖住了。
    #:
    #: 根因：原来是这样拼的::
    #:
    #:     _card = card_qss(skin)           #: 里面有 background: <白高光渐变>
    #:     if not _walled:
    #:         _card = (f"{_card} background: <白0.10 + 深色0.82>;")
    #:                                        ↑ QSS 里**后写的 background 完全覆盖**前面的
    #:
    #: 结果卡片的 background 变成 `<白0.10 + 深色0.82>` —— 那个 0.10 的白
    #: 就是用户看到的"白底"。
    #:
    #: → 改成**只生成一次 background**：把 `solid_back` 传给 ``card_qss``，
    #: 由它一次性拼好（要么透明版，要么带深色底的版本）。
    _walled = _has_wallpaper()

    if _walled:
        _card = card_qss(skin)
    else:
        _base = _hex_to_rgb((skin.get("bg") or [(0.0, "#0C0A18")])[0][1])
        if _base is None:
            _base = (12, 10, 24)
        _solid = 0.82 if skin.get("mode") == "dark" else 0.88
        _card = card_qss(skin, solid_back=_base, solid_alpha=_solid)

    #: ★★★ 2026-10-31 **有壁纸时把 Qt 侧背景全透明**
    #:
    #: 现在玻璃由 Chromium 层的 ``backdrop-filter`` 做
    #: （真正 GPU 模糊，见 ``gui/wallpaper_web.py``）。
    #:
    #: 如果 Qt 这边还画着渐变/半透明底，就会**盖在 Web 玻璃上面** ——
    #: 用户看到的是"Qt 的假玻璃"，而不是 Chromium 的真玻璃，
    #: 而且两层叠加会显得更糊。
    #:
    #: → 有壁纸时：三块主背景全部 ``transparent``，
    #:   只保留文字配色和滚动条样式。
    if _walled:
        #: ★★★ 2026-10-31 侧栏 / 标题栏**也走 DSH 配方**（不是纯透明）
        #:
        #: 用户：「不对吧，这是 DSH 的设置，你再看下」——
        #: 他要的是插件设置页里那套（玻璃颜色 + 透明度 + 边框）。
        #:
        #: DSH 深色主题下侧栏是 `#0d1524 @ 0.59 + 玻璃色 @ 16%`，
        #: 不是完全透明透出壁纸。纯透明会让整个界面亮一大截。
        #: ★★★ 2026-11-01 参数全部**从设置读**（照抄插件，可调）
        try:
            from . import wallpaper_settings as _WS  # noqa: PLC0415

            _lay = _WS.glass_layers()
            _floor = _lay["floor"]
            _base = _lay["base_rgb"]
            _pr, _pg, _pb = _lay["glass_rgb"]
            _glass_a = _lay["glass_alpha"]
            _scrim = _lay["scrim"]
        except Exception:  # noqa: BLE001
            _floor, _base = 0.59, (13, 21, 36)
            _pr, _pg, _pb = 139, 124, 255
            _glass_a, _scrim = 0.164, 0.25
        _br, _bg, _bb = _base
        #: ★★★ 2026-11-01 **侧栏用更实的底**
        #:
        #: 用户截图实测（同位置采样）::
        #:
        #:     DSH 侧栏     #0a0913  luma=0.039   ← 几乎纯黑
        #:     我们的侧栏    #1c2639  luma=0.146   ← 亮 3.7 倍
        #:
        #: 原因：侧栏只用了 floor 0.59 的底，剩下 41% 透出壁纸。
        #: DSH 的侧栏**几乎不透明**（它的 CSS 里侧栏是独立设置的）。
        _bar = (
            f"qlineargradient(x1:0, y1:0, x2:0, y2:1,"
            f" stop:0 rgba(255, 255, 255, 0.06),"
            f" stop:1 rgba(255, 255, 255, 0.01)),"
            f" rgba({_pr}, {_pg}, {_pb}, {_glass_a * 0.35:.3f}),"
            f" rgba(10, 9, 19, 0.92)"
        )
        #: 内容区：底板 + scrim 叠加（scrim 是插件里那层整体暗化）
        _content = (f"rgba({_br}, {_bg}, {_bb}, "
                    f"{min(1.0, _floor * 0.6 + _scrim * 0.4):.3f})")
        return (
            f"QStackedWidget {{ background: {_content}; }}"
            f" NavigationPanel {{ background: {_bar}; }}"
            f" NavigationPanel ScrollArea {{ background: transparent; }}"
            f" NavigationPanel ScrollArea > QWidget > QWidget"
            f" {{ background: transparent; }}"
            f" FluentTitleBar {{ background: {_bar}; }}"
            f" CardWidget {{ {_card} }}"
            + scrollbar_qss(skin)
        )

    return (
        f"QStackedWidget {{ background: {glass}; }}"
        f" NavigationPanel {{ background: {glass}; }}"
        f" NavigationPanel ScrollArea {{ background: transparent; }}"
        f" NavigationPanel ScrollArea > QWidget > QWidget"
        f" {{ background: transparent; }}"
        f" FluentTitleBar {{ background: {glass}; }}"
        f" CardWidget {{ {_card} }}"
        + scrollbar_qss(skin)
    )


def scrollbar_qss(skin: dict) -> str:
    """★ 滚动条样式 —— 透明轨道 + 圆角滑块 + 去掉箭头按钮。

    ## 为什么需要（用户 2026-10-06）

        "这个滑轮组件很丑"

    Qt 默认的滚动条是**系统原生外观**：灰色方槽、两端的三角箭头按钮、
    方角滑块 —— 放在玻璃主题里非常突兀（用户截图圈了两处：
    角色列表下面那条横向的、详情区右边那条纵向的）。

    ## 做法

      · 轨道透明（让玻璃透出来）
      · 滑块用皮肤的边框色 + 圆角，hover 时亮一点
      · **宽/高设成 8px**（默认 ~15px，太粗）
      · 两端的 ``add-line`` / ``sub-line`` 按钮**宽高设 0** ——
        这是"去掉箭头"的标准做法（光 ``display:none`` 有时不生效）

    ⚠ 滑块颜色从**皮肤**取（``border`` 那个 rgba），不写死 ——
    否则又是"深色皮肤配深色滑块"看不见（我犯过好几次的错）。
    """
    #: 滑块：皮肤边框色（本来就是"玻璃上的细线"那个色）
    knob = skin.get("border") or "rgba(127, 127, 127, 0.45)"
    #: hover / 按下时亮一点 —— 用一个更实的灰，深浅底上都看得见
    knob_hover = "rgba(127, 127, 127, 0.75)"

    #: ⚠⚠⚠ **选择器顺序不能写反**（我第一版就写错了）
    #:
    #: Qt 的语法是 ``::子控件:方向``::
    #:
    #:     QScrollBar::handle:vertical     ← 对
    #:     QScrollBar::vertical::handle    ← **错**，Qt 不认，整条规则被丢掉
    #:
    #: 我第一版写成后者，**样式一条都没生效** —— 界面上还是原生滚动条
    #: （那正是用户说"很丑"的东西）。方向伪状态要放在**子控件后面**。
    parts = []
    for orient, size in (("vertical", "width"), ("horizontal", "height")):
        parts.append(
            f" QScrollBar:{orient} {{"
            f" background: transparent; {size}: 8px; margin: 0;"
            f" border: none; }}"
            f" QScrollBar::handle:{orient} {{"
            f" background: {knob}; border-radius: 4px;"
            f" min-{size}: 24px; }}"
            f" QScrollBar::handle:{orient}:hover {{"
            f" background: {knob_hover}; }}"
            f" QScrollBar::add-line:{orient},"
            f" QScrollBar::sub-line:{orient} {{"
            f" {size}: 0; background: transparent; border: none; }}"
            f" QScrollBar::add-page:{orient},"
            f" QScrollBar::sub-page:{orient} {{"
            f" background: transparent; }}"
            f" QScrollBar::groove:{orient} {{"
            f" background: transparent; {size}: 8px; }}"
        )
    #: 转角（横竖交叉那块）—— 不设的话会露出一个原生小方块
    parts.append(" QScrollBar::corner { background: transparent; }")
    return "".join(parts)


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

    #: ★★ 换肤是**尽力而为**的 —— 主题库抛异常不该让整个界面崩掉
    #:
    #: ## ⚠⚠ 为什么加这个 try（2026-10-06 排查一次"偶发失败"）

    #: ``setTheme`` / ``setThemeColor`` 是 qfluentwidgets 的代码，
    #: 它们内部遍历**弱引用字典**，撞上 GC 会抛
    #: ``RuntimeError: dictionary changed size during iteration``。
    #: :func:`_set_theme_color` 会重试，但::
    #:
    #:   · 重试 3 次仍失败 → 记日志、继续（这条已经是容错的了）
    #:   · **别的** RuntimeError → 它 ``raise`` → 冒到 ``apply_skin`` 外面
    #:
    #: 后者会让调用方（测试 / 换肤按钮）直接炸，而且**界面停在半路**：
    #: ``setTheme`` 生效了、QSS 没刷 —— 正是"浅底浅字"那个症状。
    #:
    #: → 这里兜住：记日志、**继续往下刷 QSS**（至少配色是一致的）。
    try:
        setTheme(Theme.DARK if skin["mode"] == "dark" else Theme.LIGHT,
                 save=False)
        _set_theme_color(setThemeColor, skin["primary"])
    except Exception:  # noqa: BLE001 - 主题库的锅不该拖垮界面
        logger.warning("切换主题基调失败（继续刷配色）", exc_info=True)

    #: ★★★ 记住"**当前真正在用的**皮肤"—— 见 :func:`active_skin` 的说明。
    #: 必须在 ``_paint`` 之前设，否则 QSS 和明暗模式会对不上。
    global _ACTIVE_SKIN
    _ACTIVE_SKIN = skin["id"]

    _paint(skin)

    if save:
        from qfluentwidgets import qconfig

        #: ⚠ 显式 ``save()`` —— ``qconfig.set`` 只改**内存**，
        #: 不落盘的话"重开又变回旧皮肤"（用户 2026-10-08 报的 bug）。
        #: 见 ``_SKIN_ITEM`` 上面那段说明。
        qconfig.set(_skin_item(), skin["id"])
        try:
            qconfig.save()
        except Exception:  # noqa: BLE001 - 存不下也不该让换肤失败
            logger.warning("皮肤配置落盘失败", exc_info=True)
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
    skin = None
    if _ACTIVE_SKIN:
        skin = skin_by_id(_ACTIVE_SKIN)
    if skin is None:
        skin = current_skin()
    return _with_wallpaper_palette(skin)


def _with_wallpaper_palette(skin: dict) -> dict:
    """★ 把壁纸主色**叠加**到主题上（不改 `SKINS` 本身）。

    ## 为什么

    用户：「守岸人是偏蓝色的主题，这里却出现了紫色的按钮」。
    主题的`primary`是硬编码的，壁纸一换就撞色。

    → 从壁纸抽到主色后，这里返回**一份改过的副本**：
    原来的 dict 不动（`SKINS` 是模块级常量，改了会影响所有地方，
    而且用户切回没壁纸时要还原）。

    ## 合并内容

    * `primary` → 壁纸主色
    * `border`  → 主色 + 低透明度
    * `dim`     → 主色淡化（次要文字）
    * `bg`      → 按主色派生的暗色渐变（没壁纸时的兜底底色）
    """
    if not _WALLPAPER_PRIMARY:
        return skin
    try:
        from . import color_extract as CE  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        return skin
    out = dict(skin)
    p = _WALLPAPER_PRIMARY
    out["primary"] = p
    #: 边框：主色 + 低 alpha
    try:
        h = p.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        out["border"] = f"rgba({r}, {g}, {b}, 0.22)"
        #: dim：主色混白（次要文字，够亮又带色相）
        dr = int(r * 0.55 + 255 * 0.45)
        dg = int(g * 0.55 + 255 * 0.45)
        db = int(b * 0.55 + 255 * 0.45)
        out["dim"] = f"#{dr:02X}{dg:02X}{db:02X}"
    except (ValueError, IndexError):
        pass
    #: 背景：同色相的暗渐变
    out["bg"] = CE.derive_dark_bg(p)
    return out


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
        _notify_custom_widgets(w)       #: ★ 自定义控件自己重取色

    #: ★★★ 2026-10-30 动态壁纸（参照 dsh-plugin-wallpaper-engine）。
    #:
    #: 有 ``wallpaper`` 的主题 → 在窗口背后铺一层循环播放的视频，
    #: 并把三块主背景（QStackedWidget / NavigationPanel / FluentTitleBar）
    #: 改成**透明 + 黑纱**，让视频透出来。
    #:
    #: ⚠ 必须在**设完主 QSS 之后**套透明覆盖 —— 后写的优先级高，正好盖掉
    #: 主 QSS 里的渐变背景。反过来的话主 QSS 会把透明又盖回去。
    try:
        _apply_wallpaper_for(targets, skin)
    except Exception:  # noqa: BLE001 - 壁纸失败绝不能影响换肤
        logger.warning("壁纸应用失败", exc_info=True)

    #: ★ 记下"已经刷过这份 QSS + 这些窗口"—— 下次同一个皮肤 + 同样窗口才跳过
    _PAINTED_QSS = qss
    _PAINTED_WINDOWS = set(map(id, targets))


#: ★★ 换肤时**回调自定义控件**的钩子名
#:
#: ## 为什么需要（用户 2026-10-06 连报两次"换了皮肤这里也要换色"）
#:
#: ``_paint`` 只把 QSS 挂到**窗口 / 页面**那一层 —— 它**不知道**
#: 页面里有哪些"自己 ``setStyleSheet`` 的自定义控件"。
#:
#: 于是换肤之后，那些控件还留着**上一个皮肤**的颜色::
#:
#:     用户："换了皮肤 这里应该也要换色"
#:
#: 我第一版在抽卡页里加了个 ``refresh_skin_colors()`` 手动调 —— 但那是
#: **局部补丁**：别的页面（练度详情）照样不跟随。
#:
#: → 改成**通用机制**：任何控件只要定义了同名方法，换肤时自动被调用。
#: 约定优于配置 —— 不用注册、不用继承。
SKIN_REFRESH_METHOD = "refresh_skin_colors"


def _apply_wallpaper_for(windows: list, skin: dict) -> None:
    """★ 按主题给每个窗口铺/拆动态壁纸。

    ## 分层

    有 ``wallpaper`` 的主题 = **动态壁纸模式**：

        ① ``gui.wallpaper_layer`` 在窗口背后铺一层循环视频
        ② 本函数给窗口**追加**一段"透明覆盖 QSS"
           （``wallpaper_qss``），让三块主背景透明、视频透出来

    没有壁纸的主题 = 普通渐变模式：拆掉视频 + 移除透明覆盖。

    ## ⚠ 透明覆盖要**追加**在主 QSS 后面

    Qt 里后设的 QSS 优先级更高。所以顺序必须是::

        w.setStyleSheet(主 QSS)              #: 渐变背景
        w.setStyleSheet(主 QSS + 透明覆盖)    #: 后加的把渐变盖成透明

    只设"透明覆盖"的话，主 QSS 里 20 多处的渐变会全丢，
    连文字颜色都没了。
    """
    from ..gui import wallpaper_layer  # noqa: PLC0415 - 避免循环导入

    has_wallpaper = False
    for w in windows:
        try:
            ok = wallpaper_layer.apply_wallpaper(w, skin)
            if ok:
                has_wallpaper = True
                #: ★ 追加透明覆盖（不是替换！）
                try:
                    base = w.styleSheet() or ""
                    overlay = wallpaper_layer.wallpaper_qss(skin)
                    if overlay and overlay not in base:
                        w.setStyleSheet(base + "\n" + overlay)
                except (RuntimeError, AttributeError):
                    continue
            else:
                #: 没有壁纸 → 把之前追加的透明覆盖去掉
                try:
                    base = w.styleSheet() or ""
                    overlay = wallpaper_layer.wallpaper_qss(
                        {"wallpaper": "yes"})       #: 用同样模板生成
                    if overlay and overlay in base:
                        w.setStyleSheet(base.replace(overlay, ""))
                except (RuntimeError, AttributeError):
                    continue
        except (RuntimeError, AttributeError):
            continue
        except Exception:  # noqa: BLE001 - 单个窗口失败不影响别的
            logger.warning("壁纸：处理窗口失败", exc_info=True)

    if has_wallpaper:
        logger.info("壁纸：已启用动态壁纸模式")


def _notify_custom_widgets(window) -> None:
    """★ 沿控件树找``refresh_skin_colors()`` 并调用（换肤后重取颜色）。

    ⚠ 用 ``findChildren`` 递归 —— 自定义控件可能嵌在好几层里
    （页面 → 卡片 → 详情视图 → 属性格子）。

    ⚠ 单个控件报错**不能影响整体换肤** —— 记日志继续。
    """
    try:
        from PySide6.QtWidgets import QWidget

        kids = window.findChildren(QWidget)
    except (RuntimeError, AttributeError, ImportError):
        return
    for child in kids:
        fn = getattr(child, SKIN_REFRESH_METHOD, None)
        if not callable(fn):
            continue
        try:
            fn()
        except Exception:  # noqa: BLE001 - 坏一个不该拖垮换肤
            logger.warning("换肤回调失败：%s", type(child).__name__,
                           exc_info=True)


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


def parse_color(text: str) -> tuple[int, int, int, float] | None:
    """★ 解析**任意颜色写法**（``rgba(...)`` / ``rgb(...)`` / ``#rrggbb``）。

    跟 :func:`_rgba` 的区别：
      · ``_rgba`` 只认 ``rgba()``，认不出就回落成白色（给 Qt 调色板用）；
      · 这个**两种都认**，认不出返回 ``None``（给"算混色"用 ——
        那里必须知道"到底解析出来了没有"，不能瞎给个白色）。

    ## ⚠⚠ 这份实现**只能有一份**

    2026-10-06 我在 ``detail_view.py`` 里又写了一遍同样的解析/混色 ——
    于是同一套颜色数学有**两份实现**（改了这处忘那处）。

    → 现在都走这里：:func:`blend_color` / :func:`solid_card_on` 是公共实现。
    """
    import re

    t = str(text or "").strip()
    m = re.match(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)"
                 r"\s*(?:,\s*([\d.]+))?\)", t, re.I)
    if m:
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)),
                float(m.group(4)) if m.group(4) is not None else 1.0)
    m = re.match(r"#([0-9a-fA-F]{6})$", t)
    if m:
        h = m.group(1)
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 1.0)
    m = re.match(r"#([0-9a-fA-F]{3})$", t)
    if m:
        h = "".join(c * 2 for c in m.group(1))
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 1.0)
    return None


def blend_color(base: str, top: str, alpha: float) -> str:
    """★ 把 ``top`` 按 ``alpha`` 叠到 ``base`` 上，返回不透明的 ``#rrggbb``。

    ⚠ 任一边解析不出来就**原样返回 ``base``**（不瞎算）。
    """
    b = parse_color(base)
    t = parse_color(top)
    if not b or not t:
        return base
    a = max(0.0, min(1.0, alpha))
    return "#{:02x}{:02x}{:02x}".format(
        *[max(0, min(255, round(b[i] * (1 - a) + t[i] * a)))
          for i in range(3)])


def solid_card_on(card: str, base: str, dark: bool) -> str:
    """★ 把半透明的 ``card`` **合成到**背景 ``base`` 上，得到实心色。

    ## 为什么需要

    Qt 的**调色板**不吃 alpha；而且表格行要**实心**才看得出分块
    （半透明叠在渐变上会「糊成一片」）。

    ⚠ 深色皮肤下卡片常常**几乎全透明**（``rgba(255,255,255,0.055)``）——
    合成后跟背景一模一样，行就看不出分块了。这时**往亮里提一点**
    （深底上提亮 = 看得见）。
    """
    c = parse_color(card)
    b = parse_color(base)
    if not c:
        return base if b else ("#22283d" if dark else "#f7f7f7")
    if not b:
        return "#{:02x}{:02x}{:02x}".format(*[max(0, min(255, x))
                                               for x in c[:3]])
    r, g, bl = (round(c[i] * c[3] + b[i] * (1 - c[3])) for i in range(3))
    if dark and abs(r - b[0]) < 6:
        r, g, bl = r + 14, g + 14, bl + 18
    return "#{:02x}{:02x}{:02x}".format(
        max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, bl)))


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
    """把 ``top`` 按 ``alpha`` 混到 ``base`` 上（返回 **QColor**）。

    ⚠ 这是 :func:`blend_color` 的 **QColor 版** —— 调色板那边要的是
    ``QColor`` 对象不是字符串。**混色公式只有一份**
    （:func:`parse_color` / :func:`blend_color` 那套），这里转一下类型。

    ⚠⚠ 2026-10-06 之前这里是**第二份**独立的混色实现 ——
    和 ``detail_view`` 里那份各算各的。现在统一了。
    """
    from PySide6.QtGui import QColor

    hexed = blend_color(base.name(), top.name(), alpha)
    return QColor(hexed)


def _paint_title_bar(window, skin: dict) -> None:
    """单独给顶部标题栏刷背景（它自带 styleSheet，会盖掉继承的）。

    ⚠ 光设 ``setStyleSheet`` **不够** —— 它的
    ``WA_StyledBackground`` 默认是 ``False``，Qt 不会拿样式表画它的底，
    必须一起打开（实测：只设样式时顶部还是浅灰）。

    ## ★★★ 2026-10-31 壁纸模式下要用玻璃（用户截图圈的就是这里）

    用户：

        > 背景还是很糊啊，而且上面你没改

    「上面」就是标题栏。和侧栏同一个 bug：这里写死
    ``gradient_qss(skin)``（**不透明**渐变），壁纸铺上后标题栏
    还是一块实心板 —— 壁纸透不出来。

    → 按 :func:`_paint_nav_panel` 同样的做法：壁纸模式用湿玻璃高光。
    """
    bar = getattr(window, "titleBar", None)
    if bar is None:
        return
    #: 判断当前是不是壁纸模式
    walled = _has_wallpaper()

    if walled:
        bg = _wallpaper_nav_bg(skin)      #: 湿玻璃高光 + 半透明主题底
        border = " border-bottom: 1px solid rgba(255, 255, 255, 0.08);"
    else:
        bg = gradient_qss(skin)
        border = ""

    try:
        bar.setStyleSheet(
            f"FluentTitleBar {{ background: {bg};{border} }}")
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
    """单独给左侧栏刷背景（它自带 styleSheet，会盖掉继承的）。

    ## ★★★ 2026-10-31 壁纸模式下**必须**用玻璃高光层

    用户截图：

        > 这个侧边栏怎么没有这个效果

    侧栏用的是 :func:`_paint_nav_panel` **单独**设 QSS（它自带 584 字符
    的样式，会盖掉从窗口继承的）。而这个函数原来写死::

        panel.setStyleSheet(f"NavigationPanel {{ background: {grad}; }}")

    ``grad`` 是**不透明渐变** —— 壁纸模式下的"透明 + 玻璃高光"
    被它整个盖掉了，所以侧栏看着就是一块实心板。

    → 现在按 ``wallpaper_layer`` 的模式判断：
    有壁纸时用**湿玻璃高光渐变**（可透出壁纸），没壁纸时用原来的底色渐变。
    """
    panel = getattr(getattr(window, "navigationInterface", None),
                    "panel", None)
    if panel is None:
        return
    #: ★ 判断当前是不是壁纸模式（壁纸层活着 = 是）
    walled = _has_wallpaper()

    if walled:
        #: 壁纸模式：湿玻璃高光（半透，能透出模糊壁纸）
        bg = _wallpaper_nav_bg(skin)
    else:
        bg = gradient_qss(skin)
    try:
        panel.setStyleSheet(f"NavigationPanel {{ background: {bg}; }}")
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


def _wallpaper_nav_bg(skin: dict) -> str:
    """壁纸模式下侧栏的背景 —— 湿玻璃高光 + 半透明主题底。

    ## ★ 2026-10-31 对齐用户 DSH 设置

    DSH 里::

        玻璃透明度   40%      → 不透明度 60%
        雾化         9px      → 见 wallpaper_layer.DEFAULT_BLUR
        玻璃保真度   20%

    侧栏比内容区**再实 10%**（导航文字必须清楚），
    所以用 ``0.60 + 0.10 = 0.70``。

    配方照抄 DSH 插件（``client.js`` 2385 行）::

        linear-gradient(180deg,
            rgba(255,255,255,0.16),
            rgba(255,255,255,0.05) 38%,
            rgba(255,255,255,0.02))

    底下再垫一层**半透明主题底**（保证导航文字在亮壁纸上也看得清）。
    """
    hi = glass_qss(skin)
    #: 侧栏：0.60（玻璃不透明度）+ 0.10 = 0.70
    rgb = _hex_to_rgb(skin["bg"][0][1]) or (20, 16, 32)
    base = (f"qlineargradient(x1:0, y1:0, x2:0, y2:1,"
            f" stop:0 rgba({rgb[0]}, {rgb[1]}, {rgb[2]}, 0.70),"
            f" stop:1 rgba({rgb[0]}, {rgb[1]}, {rgb[2]}, 0.62))")
    return f"{hi}, {base}"


#: ★ 壁纸主色覆盖（内存里，不落盘）
#:
#: 用户 2026-10-31：「守岸人是偏蓝色的主题，这里却出现了紫色的按钮」。
#: 壁纸抽到的主色存这儿，`active_skin()` 会把它合并进主题。
_WALLPAPER_PRIMARY: str = ""
_WALLPAPER_TINT: float = 0.0


def apply_wallpaper_palette(primary: str, tint: float = 0.0) -> None:
    """★ 按壁纸主色覆盖主题配色（内存，不写盘）。

    ## 为什么是覆盖而不是改主题

    主题（`SKINS`）是**用户选的**，不该被壁纸悄悄改掉。
    但壁纸一换，紫色按钮配蓝色画面确实难看。

    → 折中：在内存里维护一对壁纸主色/暗化，`active_skin()` 读主题时
    把它们合并进去。换壁纸就换主色，**主题本身不动**。

    ## 合并规则

    * `primary`  → 直接用壁纸主色（按钮、选中条、徽章）
    * `border`   → 主色 + 低透明度（玻璃边缘）
    * `bg`       → 按主色派生一组同色相的暗色渐变
    * `tint`     → 壁纸暗化层（壁纸越亮压得越多）

    :param primary: 主色 `#RRGGBB`
    :param tint: 暗化层不透明度 0~0.45
    """
    global _WALLPAPER_PRIMARY, _WALLPAPER_TINT
    _WALLPAPER_PRIMARY = str(primary or "")
    _WALLPAPER_TINT = max(0.0, min(0.62, float(tint or 0.0)))
    logger.info("皮肤：壁纸配色 primary=%s tint=%.2f",
                _WALLPAPER_PRIMARY, _WALLPAPER_TINT)
    #: ★★★ 2026-10-31 **必须立刻重刷界面**
    #:
    #: 用户：「这怎么还是紫色啊，应该是搭配的蓝色啊」。
    #:
    #: 根因：这个函数只写了内存变量，**没重刷**。
    #: 而按钮的紫色来自 `qfluentwidgets.setThemeColor()`
    #: （那是全局主题色，不是 QSS 里的 primary）——
    #: 不重刷的话它一直是上次 `_paint` 时设的值。
    #:
    #: → 这里清缓存 + 全量重刷，让 `setThemeColor` 用新主色。
    try:
        #: ★ ① **先重设 qfluentwidgets 的全局主题色**
        #:
        #: 按钮的紫色来自 `setThemeColor`（不是 QSS 的 primary）——
        #: 不重设的话它一直是上次 `_paint` 时设的值。
        from qfluentwidgets import setThemeColor  # noqa: PLC0415

        _set_theme_color(setThemeColor, _WALLPAPER_PRIMARY)
        #: ★ ② 清缓存
        invalidate_paint_cache()
        #: ★ ③ 重刷 QSS
        refresh_windows()
        #: ★④ **再设一次 themeColor** —— 顺序关键！
        #:
        #: `setThemeColor` 内部会 `updateStyleSheet()` 把它的配色刷到
        #: app 级 QSS 里；而我们 `refresh_windows()` 又用
        #: `app.setStyleSheet(自定义 QSS)` **整个覆盖掉**。
        #:
        #: 所以两次之间必须再补一次——
        #: 实测（button.grab() 取色）：补设后按钮从 #009faa（紫）变成
        #: #2756db（蓝）。
        _set_theme_color(setThemeColor, _WALLPAPER_PRIMARY)
        logger.info("皮肤：壁纸配色已应用 primary=%s", _WALLPAPER_PRIMARY)
    except Exception:  # noqa: BLE001
        logger.warning("皮肤：壁纸配色重刷失败", exc_info=True)


def clear_wallpaper_palette() -> None:
    """清掉壁纸配色覆盖（取消壁纸时调）。

    ## ★★★ 2026-10-31 必须真的重刷

    实测（``PrimaryPushButton.grab()`` 取色）::

        apply_wallpaper_palette('#2756DB') → 按钮 #4f7dff（蓝）✅
        clear_wallpaper_palette()          → 按钮 #4f7dff（还是蓝）❌

    只清变量不重刷 → 界面停在壁纸配色上，
    用户取消壁纸后按钮还是蓝的（应该回到主题原本颜色）。
    """
    global _WALLPAPER_PRIMARY, _WALLPAPER_TINT
    if not _WALLPAPER_PRIMARY and _WALLPAPER_TINT == 0.0:
        return
    _WALLPAPER_PRIMARY = ""
    _WALLPAPER_TINT = 0.0
    #: 重刷回原主题配色（和 apply 同样顺序：先设色、再刷、再补设）
    try:
        from qfluentwidgets import setThemeColor  # noqa: PLC0415

        skin = current_skin()
        _set_theme_color(setThemeColor, skin["primary"])
        invalidate_paint_cache()
        refresh_windows()
        _set_theme_color(setThemeColor, skin["primary"])
        logger.info("皮肤：已恢复主题原配色 %s", skin["primary"])
    except Exception:  # noqa: BLE001
        logger.warning("皮肤：恢复原配色失败", exc_info=True)


def wallpaper_palette() -> tuple:
    """当前壁纸配色 `(primary, tint)`；没有覆盖时返回 `("", 0.0)`。"""
    return (_WALLPAPER_PRIMARY, _WALLPAPER_TINT)


def apply_card_backgrounds(windows=None) -> int:
    """★ 给所有 qfluentwidgets 卡片设**深色玻璃底**（DSH 配方）。

    ## ★★★ 2026-11-01 为什么必须这么做

    用户：「这怎么还是紫色啊」→ 修了配色；「还是这么亮」→ 修了暗化。
    但**卡片一直完全透明**。

    ## 根因：qfluentwidgets 的卡片**自己画背景**

    `SimpleCardWidget.paintEvent` 的实际代码::

        def paintEvent(self, e):
            painter = QPainter(self)
            painter.setBrush(self.backgroundColor)      # ← 用属性！
            painter.drawRoundedRect(...)

    **它根本不读 QSS 的 `background`** —— 我往 QSS 里写了 N 遍
    `rgba(13,21,36,0.59)` 都没用，全被自绘覆盖。

    ## 正确接口：`setBackgroundColor`

    实测（`setBackgroundColor(QColor(13,21,36,150))`）::

        卡片立刻变成明显的深色玻璃 ✅（和 DSH 一致）

    :param windows: 要处理的窗口列表；`None` = 全部顶层窗口
    :return: 设了多少个卡片
    """
    try:
        from PySide6.QtGui import QColor

        layers = _glass_for_cards()
    except Exception:  # noqa: BLE001
        return 0
    if layers is None:
        return 0
    names = ("SimpleCardWidget", "CardWidget", "ElevatedCardWidget",
             "HeaderCardWidget", "GroupHeaderCardWidget", "ToolCard")
    count = 0
    try:
        from PySide6.QtWidgets import QApplication, QWidget

        app = QApplication.instance()
        if app is None:
            return 0
        roots = list(windows) if windows else app.topLevelWidgets()
        for root in roots:
            if root is None:
                continue
            try:
                for child in root.findChildren(QWidget):
                    if type(child).__name__ not in names:
                        continue
                    if not hasattr(child, "setBackgroundColor"):
                        continue
                    child.setBackgroundColor(layers)
                    count += 1
            except (RuntimeError, AttributeError):
                continue
    except Exception:  # noqa: BLE001
        logger.warning("卡片底色：设置失败", exc_info=True)
    return count


def _glass_for_cards():
    """算出卡片的玻璃底色（DSH 配方合成成一个 QColor）。

    公式（`client.js` L2195-2197）::

        深色底 = surface-tint-dark #0d1524 @ readability-floor 0.59
        玻璃色 = glass tint @ (1 - floor) × glassAlpha

    Qt 的 `setBackgroundColor` 只吃**一个**颜色，所以这里把两层
    **预合成**成一个等效不透明的 rgba：

        alpha = floor + (1 - floor) × glass_alpha
        rgb   = 深色底 × (floor / alpha) + 玻璃色 × (glass_alpha / alpha)

    :return: `QColor`；没有壁纸时返回 `None`
    """
    try:
        from PySide6.QtGui import QColor
    except Exception:  # noqa: BLE001
        return None
    #: 没壁纸就不用改（让卡片保持主题默认）
    try:
        if not _has_wallpaper():
            return None
    except Exception:  # noqa: BLE001
        return None
    try:
        from . import wallpaper_settings as _WS

        lay = _WS.glass_layers()
        floor = float(lay["floor"])
        br, bg, bb = lay["base_rgb"]
        gr, gg, gb = lay["glass_rgb"]
        ga = float(lay["glass_alpha"])
    except Exception:  # noqa: BLE001
        floor, (br, bg, bb) = 0.59, (13, 21, 36)
        (gr, gg, gb), ga = (139, 124, 255), 0.082
    alpha = min(1.0, floor + (1.0 - floor) * ga)
    if alpha <= 0.001:
        return QColor(0, 0, 0, 0)
    #: 按 alpha 权重混合两层
    wr = floor / alpha
    wg = ga * (1.0 - floor) / alpha
    r = int(br * wr + gr * wg)
    g = int(bg * wr + gg * wg)
    b = int(bb * wr + gb * wg)
    return QColor(max(0, min(255, r)), max(0, min(255, g)),
                  max(0, min(255, b)), int(round(alpha * 255)))


def invalidate_paint_cache() -> None:
    """★ 清掉 QSS 缓存，强制下次 ``_paint`` 真的重刷。

    ## 为什么需要（2026-10-31 用户报「壁纸在播但看不见」）

    ``_paint`` 里有个缓存::

        if qss == _PAINTED_QSS and set(map(id, targets)) <= _PAINTED_WINDOWS:
            return        #: 同一个皮肤 + 同样窗口 → 跳过

    这个优化本来是对的（重复刷 QSS 要 1.4 秒）。但它有个前提：
    **QSS 字符串要反映当前的所有状态**。

    「有没有壁纸」会改变 QSS 内容（不透明渐变 ↔ 玻璃高光），
    但**切换壁纸的那一刻 QSS 字符串还没变**（壁纸层刚铺上、
    ``current_layer()`` 刚有值，而 ``_paint`` 还没跑）。
    缓存判断看到"QSS 相同"就跳过了，界面还挂着旧的不透明渐变 ——
    壁纸被完全盖住。

    → 壁纸切换后**显式清缓存**，逼 ``_paint`` 重新生成 QSS。

    ⚠ 只在"影响 QSS 内容的东西变了"时调（壁纸切换）。
    别随便调 —— 每次重刷要 1.4 秒。
    """
    global _PAINTED_QSS, _PAINTED_WINDOWS
    _PAINTED_QSS = ""
    _PAINTED_WINDOWS = set()
    logger.info("皮肤：QSS 缓存已清（强制下次重刷）")


def invalidate_paint_cache() -> None:
    """★ 清掉 QSS 缓存，强制下次 ``_paint`` 真的重刷。

    ## 为什么需要（2026-10-31 用户报「壁纸在播但看不见」）

    ``_paint`` 里有个缓存::

        if qss == _PAINTED_QSS and set(map(id, targets)) <= _PAINTED_WINDOWS:
            return        #: 同一个皮肤 + 同样窗口 → 跳过

    这个优化本来是对的（重复刷 QSS 要 1.4 秒）。但它有个前提：
    **QSS 字符串要反映当前的所有状态**。

    「有没有壁纸」会改变 QSS 内容（不透明渐变 ↔ 玻璃高光），
    但**切换壁纸的那一刻 QSS 字符串还没变**（壁纸层刚铺上、
    ``current_layer()`` 刚有值，而 ``_paint`` 还没跑）。
    缓存判断看到"QSS 相同"就跳过了，界面还挂着旧的不透明渐变 ——
    壁纸被完全盖住。

    → 壁纸切换后**显式清缓存**，逼 ``_paint`` 重新生成 QSS。

    ⚠ 只在"影响 QSS 内容的东西变了"时调（壁纸切换）。
    别随便调 —— 每次重刷要 1.4 秒。
    """
    global _PAINTED_QSS, _PAINTED_WINDOWS
    _PAINTED_QSS = ""
    _PAINTED_WINDOWS = set()
    logger.info("皮肤：QSS 缓存已清（强制下次重刷）")


def refresh_glass_panels(windows: list | None = None) -> None:
    """★ 壁纸铺上后，**单独重刷侧栏 + 标题栏**（绕过 QSS 缓存）。

    ## 为什么需要这个（2026-10-31 用户截图）

        > 背景还是很糊啊，而且上面你没改

    "上面" = 标题栏。

    ## 根因

    ``_paint_nav_panel`` / ``_paint_title_bar`` 都靠
    ``wallpaper_layer.current_layer()`` 判断"要不要用玻璃"。
    但用户点壁纸时的顺序是::

        ① _on_wallpaper_chosen()
        ②   apply_video()              ← 壁纸层这时才活
        ③   skins.refresh_windows()    ← 走 _paint，缓存可能跳过

    第 ③ 步即使不跳过，``_paint`` 里调 ``_paint_nav_panel`` 的时机
    也可能早于壁纸层真正 start（``apply_video`` 是异步的）。

    → 所以壁纸铺好后**再显式刷一次这两个面板**，这次一定看得到
    ``current_layer()`` 有值。这个函数就是干这个的。

    :param windows: 要刷的窗口列表；``None`` = 所有可见顶层窗口
    """
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        return
    targets = windows
    if targets is None:
        targets = []
        for w in app.topLevelWidgets():
            try:
                if w.isVisible():
                    targets.append(w)
            except (RuntimeError, AttributeError):
                continue
    skin = active_skin()
    for w in targets:
        try:
            _paint_nav_panel(w, skin)
            _paint_title_bar(w, skin)
        except (RuntimeError, AttributeError):
            continue
        except Exception:  # noqa: BLE001 - 单个窗口失败不影响别的
            logger.warning("皮肤：重刷玻璃面板失败", exc_info=True)
    logger.info("皮肤：玻璃面板已重刷（%d 个窗口）", len(targets))


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

    ## ★ 顺便刷卡片底色（2026-11-01）

    ``qfluentwidgets`` 的卡片是**自绘背景**（``paintEvent`` 里
    ``setBrush(self.backgroundColor)``），不读 QSS。
    所以每次刷窗口都要顺手把 ``backgroundColor`` 设成玻璃配方。
    """
    _paint(active_skin())
    #: 刷完 QSS 再刷卡片底色（顺序无所谓，但都做）
    try:
        apply_card_backgrounds()
    except Exception:  # noqa: BLE001
        logger.debug("皮肤：刷新卡片底色失败", exc_info=True)
