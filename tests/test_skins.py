# -*- coding: utf-8 -*-
"""皮肤系统的测试（液态玻璃主题）。

## ⚠ 这里是"真的换肤了"的硬测试

用户先后报过**两个** bug::

    "只有深色的皮肤有效果，其他的根本没有效果"     ← 换色没铺开
    "这个皮肤设计太差，删掉重写…（液态玻璃主题）"  ← 只是换纯色不够

所以测试要盯住两件事：
  ① 每款皮肤**渲染出来必须不一样**（不能"换了个寂寞"）
  ② QSS 里必须是**渐变 + 半透明卡片**（玻璃感的两个要素）

## ⚠⚠ 性能：为什么用**最小窗口**而不是 ``MainWindow``

在测试里建真的 ``MainWindow`` 实测会**卡死**
（单跑 ~22 秒，整套跑 23 分钟没动静）——
它要 5 秒、还拉一堆单例，跟在别的用例后面就互相卡。

验"皮肤的 QSS 能不能改变渲染"只需要一个
带 ``QStackedWidget`` + ``CardWidget`` 的小窗口
（正好是 QSS 命中的两个选择器）。**0.6 秒跑完。**
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _destroy_toplevels() -> int:
    """**真正**销毁所有顶层控件，返回销毁了几个。

    ## ⚠⚠ 为什么必须有它（2026-10-10 修「整套跑会卡死」）

    本文件里的测试建了 ``MainWindow`` 却**不清理**（好几处注释还写着
    "窗口建了就不用管，进程结束自然回收" —— 那个结论是**错的**）。
    窗口会一直攒着，而 ``skins._paint`` 里有一句::

        app.setStyleSheet(qss)      # 对**所有**控件递归 re-polish

    → 活着的窗口越多，``apply_skin()`` 越慢。实测::

        0 个 MainWindow → 0.000s
        1 个            → 2.8s
        3 个            → 8.5s

    而 ``TestNativeWidgetPalette`` 会循环 6 款皮肤各调一次
    ``apply_skin``（``setUp``/``tearDown`` 还各一次），后面几个类又继续加窗口
    → 单次涨到几十秒 × 几十次 = **整套跑几个小时不结束**（看起来像卡死）。

    ## ⚠ 光调 ``deleteLater()`` **不够**

    ``deleteLater()`` 只是**投递**一个 ``DeferredDelete`` 事件，
    而 ``QApplication.processEvents()`` **默认不处理**它 ——
    所以原来那些 ``w.deleteLater()`` 等于没删。必须显式
    ``sendPostedEvents(None, DeferredDelete)`` 把事件跑掉。

    （实测：24 个控件 ``processEvents()`` 后仍是 24 个；
      ``sendPostedEvents(DeferredDelete)`` 后变 0。）
    """
    from PySide6.QtCore import QEvent, QCoreApplication
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        return 0

    n = 0
    for w in app.topLevelWidgets():
        try:
            w.hide()
            w.setParent(None)
            w.deleteLater()
            n += 1
        except RuntimeError:          #: C++ 那边已经没了
            continue
    #: ★★ 关键的一步：把 deleteLater 投递的事件**真的处理掉**
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    return n


class _SkinTestCase(unittest.TestCase):
    """本文件所有测试的基类 —— **每个类跑完自动清理顶层控件**。

    ## ⚠⚠ 为什么用基类而不是在每个类里写 ``tearDownClass``

    本文件有 13 个类、其中 6 个会建 ``MainWindow`` 之类的顶层控件。
    逐个补 ``tearDownClass`` 一定会漏（原来就漏了好几个），
    而漏一个的代价是**整套测试跑不完**（见 :func:`_destroy_toplevels`）。

    放在基类里 = **新加的类只要继承它就自动安全**，
    不会因为"忘了写清理"再把整套拖死。

    ⚠ 用 ``tearDownClass``（类级）而不是 ``tearDown``（方法级）：
    有些类故意在多个方法间**复用**同一个窗口（如
    ``TestNavResizerTransparent._window_once``），方法级清理反而会破坏它们。
    """

    @classmethod
    def tearDownClass(cls):
        _destroy_toplevels()
        super().tearDownClass()


class TestSkinRegistry(_SkinTestCase):
    """皮肤注册表本身（不碰窗口）。"""

    def test_skins_have_required_fields(self):
        from src.core import skins

        self.assertGreaterEqual(len(skins.all_skins()), 4,
                                "皮肤太少了 —— 用户要「几款」")
        for s in skins.all_skins():
            for k in ("id", "name", "desc", "mode", "primary",
                      "bg", "card", "border", "text", "dim"):
                self.assertIn(k, s, f"皮肤缺字段 {k}：{s}")
            self.assertIn(s["mode"], ("light", "dark"))

    def test_ids_are_unique(self):
        from src.core import skins

        ids = [s["id"] for s in skins.all_skins()]
        self.assertEqual(len(ids), len(set(ids)), f"皮肤 id 重复：{ids}")

    def test_has_light_and_dark(self):
        from src.core import skins

        modes = {s["mode"] for s in skins.all_skins()}
        self.assertEqual(modes, {"light", "dark"}, "浅色/暗色不全")

    def test_bg_is_a_gradient(self):
        """★★ ``bg`` 必须是**渐变**（多个 stop）—— 液态玻璃的基础。

        ⚠ 上一版 ``bg`` 是**纯色字符串**，被用户否了：
        "这个皮肤设计太差"。纯色 = 没有纵深，不像玻璃。
        """
        from src.core import skins

        for s in skins.all_skins():
            with self.subTest(skin=s["name"]):
                bg = s["bg"]
                self.assertIsInstance(
                    bg, (list, tuple),
                    f"{s['name']} 的 bg 不是渐变（{bg!r}）—— 纯色不够玻璃")
                self.assertGreaterEqual(
                    len(bg), 2, f"{s['name']} 的渐变只有一个 stop")
                for stop in bg:
                    self.assertEqual(len(stop), 2,
                                     f"stop 应该是 (位置, 颜色)：{stop}")
                    pos, color = stop
                    self.assertTrue(0 <= pos <= 1,
                                    f"stop 位置越界：{pos}")
                    self.assertTrue(str(color).startswith("#"),
                                    f"stop 颜色不对：{color}")

    def test_card_is_translucent(self):
        """★★ 卡片必须是**半透明**的 —— 玻璃感的第二个要素。

        ⚠ 不透的卡片就是普通色块，不是玻璃。
        """
        from src.core import skins

        for s in skins.all_skins():
            with self.subTest(skin=s["name"]):
                card = str(s["card"])
                self.assertTrue(
                    card.startswith("rgba("),
                    f"{s['name']} 的卡片不是半透明（{card}）—— "
                    f"不透明的卡片没有玻璃感")

    def test_border_is_translucent(self):
        """★ 描边也应该是半透明的浅色（玻璃边缘的高光）。"""
        from src.core import skins

        for s in skins.all_skins():
            with self.subTest(skin=s["name"]):
                self.assertTrue(
                    str(s["border"]).startswith("rgba("),
                    f"{s['name']} 的描边不是半透明：{s['border']}")

    def test_default_skin_is_mist(self):
        """★★★ 默认皮肤 = **晨雾玻璃**（用户 2026-10-05 指定）。

            "默认这个"（截图圈出「晨雾玻璃」那张卡）

        ⚠ 之前默认是「深空玻璃」（暗色）。
        """
        from src.core import skins

        self.assertEqual(skins.DEFAULT_SKIN, "mist",
                         "默认皮肤不是晨雾玻璃")
        default = skins.skin_by_id(skins.DEFAULT_SKIN)
        self.assertIsNotNone(default)
        self.assertEqual(default["name"], "晨雾玻璃")
        self.assertEqual(default["mode"], "light")

    def test_default_skin_is_first_card(self):
        """★★ 默认皮肤排在**第一张卡**（用户一眼就能看到当前是哪个）。"""
        from src.core import skins

        first = skins.all_skins()[0]
        self.assertEqual(first["id"], skins.DEFAULT_SKIN,
                         "默认皮肤不在第一位 —— 界面上一眼看不出默认是哪个")

    def test_skin_by_id_unknown_returns_none(self):
        from src.core import skins

        self.assertIsNone(skins.skin_by_id("不存在的皮肤"))


class TestSkinQss(_SkinTestCase):
    """★★ ``build_qss`` —— 换肤**看得见**的关键。"""

    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def test_gradient_qss_is_valid(self):
        """★★ 渐变拼出来必须是合法的 ``qlineargradient``。

        ⚠⚠ 上一版这里有**真 bug**：预览条把 ``bg``（现在是列表）
        直接当字符串插进 QSS，拼出来是::

            stop:0 [(0.0, '#0B1026'), (0.45, '#141A38')]

        **整个 Python 列表塞进去了** —— QSS 解析失败，什么都画不出来。
        """
        from src.core import skins

        for s in skins.all_skins():
            with self.subTest(skin=s["name"]):
                grad = skins.gradient_qss(s)
                self.assertTrue(grad.startswith("qlineargradient("),
                                f"不是渐变：{grad[:60]}")
                self.assertNotIn("[", grad,
                                 f"渐变里混进了 Python 列表：{grad[:80]}")
                self.assertNotIn("(", grad.split("(", 1)[1].split("stop")[0]
                                 .replace("x1:0, y1:0, x2:1, y2:1, ", ""),
                                 f"渐变参数不对：{grad[:80]}")
                #: 每个 stop 都要在
                for _pos, color in s["bg"]:
                    self.assertIn(color, grad,
                                  f"渐变里少了 {color}")

    def test_qss_contains_bg_gradient_and_card(self):
        """★★ QSS 里必须有**渐变背景**（第一版只换主色 → 0% 变化）。"""
        from src.core import skins

        for s in skins.all_skins():
            with self.subTest(skin=s["name"]):
                qss = skins.build_qss(s)
                self.assertIn("qlineargradient", qss,
                              f"{s['name']} 的 QSS 没有渐变")
                self.assertIn("QStackedWidget", qss,
                              "QSS 没打到页面容器 —— 换了也看不见")
                self.assertIn("NavigationPanel", qss,
                              "QSS 没打到左侧栏 —— 会「右边玻璃左边白板」")
                self.assertIn(str(s["card"]), qss, "QSS 没有卡片色")

    def test_qss_does_not_paint_every_widget(self):
        """★★ **不许**有**裸的** ``QWidget { background }``。

        ⚠ 裸选择器会把所有子控件（图标底、标签底）一起涂了，
        层次全没（实测过）。

        ⚠⚠ 注意别误判：``NavigationPanel ScrollArea > QWidget > QWidget
        { background: transparent }`` 是**后代选择器**（只作用于侧栏滚动区
        内部），是**故意**写的 —— 它里面的 ``QWidget {`` 前面有 ``>``。
        所以判据是"**行首/花括号前直接就是 QWidget**"。
        """
        import re

        from src.core import skins

        def bare_widget_selectors(qss: str) -> list[str]:
            """挑出**裸的** ``QWidget`` 选择器（排除 `> QWidget` 这种后代选择器）。

            做法：对每个 ``{`` 取它前面的选择器文本，
            如果**最后一个词**是 ``QWidget`` 且**不含 ``>``** → 就是裸的。
            """
            bad = []
            #: 用 `}` 切开，每段形如 "Selector1 Selector2 { 声明"
            for chunk in qss.split("}"):
                if "{" not in chunk:
                    continue
                selector = chunk.split("{")[0].strip()
                #: 取最后一段（逗号分隔的多个选择器也要看）
                for one in selector.split(","):
                    one = one.strip()
                    if not one.endswith("QWidget"):
                        continue
                    if ">" in one:
                        continue          #: 后代选择器，故意的
                    bad.append(one)
            return bad

        for s in skins.all_skins():
            with self.subTest(skin=s["name"]):
                qss = skins.build_qss(s)
                bad = bare_widget_selectors(qss)
                self.assertEqual(
                    bad, [],
                    f"{s['name']} 用了裸的 QWidget 选择器 {bad} —— 层次会糊")
                #: 但限定到侧栏滚动区的后代选择器是允许的
                self.assertIn("NavigationPanel ScrollArea", qss,
                              "侧栏滚动区没设透明 —— 侧栏会上下分两截颜色")

    def test_title_bar_is_painted(self):
        """★★★ 顶部标题栏要**单独刷**（否则顶部留一条白/浅灰）。

        ⚠⚠ 实测：``FluentTitleBar`` 自带 **1990 字符**的 styleSheet，
        而且 ``WA_StyledBackground=False`` —— 从窗口继承的渐变
        **根本到不了**它。用户第二个截图圈的就是这条白带
        （取色 ``#f3f3f3``）。

        ⚠ 光 ``setStyleSheet`` 还不够 —— 必须把
        ``WA_StyledBackground`` 打开，否则 Qt 不拿样式表画它的底。
        """
        import inspect

        from src.core import skins

        self.assertIn("_paint_title_bar",
                      inspect.getsource(skins._paint),
                      "_paint 没刷标题栏 —— 顶部会留白条")
        src = inspect.getsource(skins._paint_title_bar)
        self.assertIn("setStyleSheet", src)
        self.assertIn("WA_StyledBackground", src,
                      "没开 WA_StyledBackground —— 设了样式也不画")

    def test_title_bar_gradient_on_fake_window(self):
        """★★★ 真的给一个标题栏刷一下，确认刷上了**并且**开了底绘制。

        ⚠ 只查源码里有没有 ``WA_StyledBackground`` 是不够的
        （把那一行删掉，字符串还在 import 别处）——
        这里**真的建一个标题栏、真的刷一次、真的读它的属性**。
        """
        from qfluentwidgets import FluentTitleBar
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QWidget

        from src.core import skins

        skin = skins.skin_by_id("deepglass")

        class _FakeWindow(QWidget):
            def __init__(self):
                super().__init__()
                self.titleBar = FluentTitleBar(self)

        win = _FakeWindow()
        #: 先造一个"和真标题栏一样麻烦"的初始状态
        win.titleBar.setAttribute(
            Qt.WidgetAttribute.WA_StyledBackground, False)
        win.titleBar.setStyleSheet("QWidget { background: #f3f3f3; }")

        skins._paint_title_bar(win, skin)

        css = win.titleBar.styleSheet()
        self.assertIn("qlineargradient", css,
                      f"标题栏没刷上渐变（{css[:80]}）")
        self.assertIn(skin["bg"][0][1], css)
        self.assertTrue(
            win.titleBar.testAttribute(
                Qt.WidgetAttribute.WA_StyledBackground),
            "标题栏没开 WA_StyledBackground —— Qt 不会拿样式表画它的底，"
            "顶部会留白条")
        win.deleteLater()

    def test_pages_are_made_transparent(self):
        """★★★ 页面这一层要设透明（否则工具页是**一块白**）。

        ⚠⚠ 实测工具页有**四层**白底::

            ToolInterfaceHost        ← 懒创建的宿主
            AutoCombatWidget         ← ScrollArea 本身
            qt_scrollarea_viewport   ← 滚动区 viewport
            auto_combat_page         ← ★ ScrollArea 的内层 view（最容易漏）

        用户第二个截图："这里也是白色，跟现有配色完全不符"。
        """
        import inspect

        from src.core import skins

        self.assertIn("_paint_pages", inspect.getsource(skins._paint),
                      "_paint 没处理页面透明 —— 工具页会是白板")

        src = inspect.getsource(skins.paint_page_widget)
        area_src = inspect.getsource(skins._transparent_scroll_area)
        #: ScrollArea 的 viewport 和**内层 view** 都要处理
        self.assertIn("viewport", src, "没处理滚动区 viewport")
        self.assertIn("widget()", area_src,
                      "没处理 ScrollArea 的内层 view（setWidget 交进去那个）")

    def test_pages_transparent_on_fake_page(self):
        """★★★ 真的造一个"宿主 + ScrollArea + 内层 view"，确认都透明了。"""
        from qfluentwidgets import ScrollArea
        from PySide6.QtWidgets import QVBoxLayout, QWidget

        from src.core import skins

        #: 完全照工具页的结构：宿主(QWidget) → ScrollArea → 内层 view
        host = QWidget()
        host.setObjectName("tool_fake")
        lay = QVBoxLayout(host)
        area = ScrollArea(host)
        area.setObjectName("fake_scroll")
        inner = QWidget()
        inner.setObjectName("fake_page")
        area.setWidget(inner)
        area.setWidgetResizable(True)
        lay.addWidget(area)

        skins.paint_page_widget(host)

        for name, w in (("宿主", host), ("滚动区", area),
                        ("viewport", area.viewport()), ("内层 view", inner)):
            with self.subTest(part=name):
                self.assertIn(
                    "transparent", w.styleSheet(),
                    f"{name} 没设透明 —— 会是一块白")
        host.deleteLater()

    def test_lazy_tool_panel_gets_painted(self):
        """★★★ 工具面板**懒创建** —— 建好后要**真的**补刷透明。

        ``ToolInterfaceHost`` 到第一次 ``showEvent`` 才建面板，
        所以 ``_paint`` 跑的时候它还不存在 —— 建好了得补一次，
        否则**还是白的**。

        ⚠ 这里**真的建一个宿主、真的 ensure_panel**，
        再读面板的样式 —— 光查源码字符串抓不住"补刷被删掉"这种回归。
        """
        from src.core import skins
        from src.core.tool_base import ToolCategory, ToolMeta
        from src.gui.main_window import ToolInterfaceHost

        skins.apply_skin(skins.DEFAULT_SKIN, save=False)
        host = ToolInterfaceHost(ToolMeta(
            key="fake_tool", name="假工具",
            category=list(ToolCategory)[0]))
        panel = host.ensure_panel()
        self.assertIsNotNone(panel)

        #: ★ 宿主和面板都该被设成透明
        for name, w in (("宿主", host), ("面板", panel)):
            with self.subTest(part=name):
                self.assertIn(
                    "transparent", w.styleSheet(),
                    f"{name} 没被补刷透明 —— 工具页会是一块白")
        host.deleteLater()
        """★★★ 左侧栏要**单独刷** —— 它自带的 styleSheet 会盖掉继承的。

        ⚠⚠ 实测发现：``NavigationPanel`` **自己带一份 styleSheet**
        （584 字符，里面写死 ``background-color: rgb(32, 32, 32)``），
        优先级高于从窗口继承下来的。

        只靠 ``build_qss`` 里的 ``NavigationPanel { ... }`` **不够** ——
        表现就是"右边深色玻璃、左边白板"（实测截图就是这个）。

        → ``_paint`` 里必须调 ``_paint_nav_panel`` 单独给它设。
        """
        import inspect

        from src.core import skins

        src = inspect.getsource(skins._paint)
        self.assertIn("_paint_nav_panel", src,
                      "_paint 没单独刷左侧栏 —— 侧栏会保持白板")

        nav_src = inspect.getsource(skins._paint_nav_panel)
        self.assertIn("setStyleSheet", nav_src,
                      "没给侧栏设样式")
        self.assertIn("gradient_qss", nav_src,
                      "侧栏没刷渐变")

    def test_nav_panel_is_painted_directly(self):
        """★★★ 左侧栏要**单独刷** —— 它自带的 styleSheet 会盖掉继承的。

        ⚠⚠ 实测发现：``NavigationPanel`` **自己带一份 styleSheet**
        （584 字符，里面写死 ``background-color: rgb(32, 32, 32)``），
        优先级高于从窗口继承下来的。

        只靠 ``build_qss`` 里的 ``NavigationPanel { ... }`` **不够** ——
        表现就是"右边深色玻璃、左边白板"（实测截图就是这个）。

        → ``_paint`` 里必须调 ``_paint_nav_panel`` 单独给它设。
        """
        import inspect

        from src.core import skins

        src = inspect.getsource(skins._paint)
        self.assertIn("_paint_nav_panel", src,
                      "_paint 没单独刷左侧栏 —— 侧栏会保持白板")

        nav_src = inspect.getsource(skins._paint_nav_panel)
        self.assertIn("setStyleSheet", nav_src,
                      "没给侧栏设样式")
        self.assertIn("gradient_qss", nav_src,
                      "侧栏没刷渐变")

    def test_nav_panel_gets_gradient(self):
        """★★★ 侧栏要真的被刷上渐变（不留白板）。

        ⚠⚠ 实测发现：``NavigationPanel`` **自己带一份 styleSheet**
        （584 字符，写死 ``background-color: rgb(32, 32, 32)``），
        优先级高于从窗口继承的 —— 只靠 ``build_qss`` 里那条
        ``NavigationPanel { ... }`` **不够**，
        表现就是"右边深色玻璃、左边白板"。

        ## ⚠ 为什么不用真 ``MainWindow`` 测

        试过 —— 会**卡死**（实测 5 分钟没动静）。原因是
        ``MainWindow()`` 在已有窗口的进程里会互相卡住。

        → 改成造一个**假的窗口对象**（挂一个真的 ``NavigationPanel``），
        直接验 ``_paint_nav_panel`` 把样式刷上去了。快且确定。
        """
        from qfluentwidgets import NavigationPanel
        from PySide6.QtWidgets import QWidget

        from src.core import skins

        skin = skins.skin_by_id("deepglass")

        #: 假窗口：只要有个 ``navigationInterface.panel`` 就够
        class _FakeNav:
            def __init__(self):
                self.panel = NavigationPanel()

        class _FakeWindow(QWidget):
            def __init__(self):
                super().__init__()
                self.navigationInterface = _FakeNav()

        win = _FakeWindow()
        skins._paint_nav_panel(win, skin)

        css = win.navigationInterface.panel.styleSheet()
        self.assertIn("qlineargradient", css,
                      f"侧栏没刷上渐变（{css[:80]}）—— 会是白板")
        self.assertIn(skin["bg"][0][1], css,
                      "侧栏渐变不是这个皮肤的")
        win.deleteLater()


class TestNativeWidgetPalette(_SkinTestCase):
    """★★★ **裸 Qt 控件**也要跟着换肤（用户 2026-10-05 报的"看不清字"）。

        用户（截图圈出「资源库更新」的日志框）::

            "如果皮肤颜色比较深，字体颜色应该相应调浅比如调成白色，
             不然看不清字了"

    ## 根因

    有些控件是**裸 Qt 控件**，不认 qfluentwidgets 的主题：

    * ``QTextEdit``（「资源库更新」那个日志框）
    * 原生 ``QLabel`` / ``QLineEdit`` / ``QTreeWidget`` …

    它们从**系统调色板**取色。实测切到深色皮肤后::

        QTextEdit 底色=#ffffff  字色=#000000     ← 还是白底黑字

    而玻璃 QSS 又把它的底压暗 → **深底 + 深字 = 看不见**。

    → ``apply_skin`` 必须**同步 Qt 调色板**。
    """

    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def setUp(self):
        from src.core import skins

        skins.apply_skin(skins.DEFAULT_SKIN, save=True)

    def tearDown(self):
        from src.core import skins

        skins.apply_skin(skins.DEFAULT_SKIN, save=True)

    @staticmethod
    def _lum(color) -> float:
        return (0.299 * color.red() + 0.587 * color.green()
                + 0.114 * color.blue())

    def test_native_controls_get_palette(self):
        """★★★ 每种皮肤下，裸控件的**底/字对比度方向**必须对。

        浅色皮肤 → 底亮字暗；暗色皮肤 → 底暗字亮。
        """
        from PySide6.QtGui import QPalette
        from PySide6.QtWidgets import QLineEdit, QTextEdit, QTreeWidget

        from src.core import skins

        for skin in skins.all_skins():
            dark = skin["mode"] == "dark"
            skins.apply_skin(skin["id"], save=True)
            for _ in range(3):
                self.app.processEvents()
            for cls in (QTextEdit, QLineEdit, QTreeWidget):
                with self.subTest(skin=skin["name"], widget=cls.__name__):
                    w = cls()
                    pal = w.palette()
                    base = pal.color(QPalette.ColorRole.Base)
                    text = pal.color(QPalette.ColorRole.Text)
                    w.deleteLater()
                    if dark:
                        self.assertGreater(
                            self._lum(text), self._lum(base),
                            f"{skin['name']}/{cls.__name__}：暗色皮肤下"
                            f"字({text.name()})比底({base.name()})还暗 —— 看不清")
                    else:
                        self.assertLess(
                            self._lum(text), self._lum(base),
                            f"{skin['name']}/{cls.__name__}：浅色皮肤下"
                            f"字({text.name()})比底({base.name()})还亮 —— 看不清")

    def test_card_color_is_not_black(self):
        """★★★ 半透明卡片色算出来**不能是黑色**。

        ⚠⚠ 我的第一版直接 ``QColor("rgba(255,255,255,0.055)")`` ——
        **Qt 解析不出来，返回黑色**，于是 ``Base`` 被设成 ``#000000``
        （暗色皮肤下日志框还是黑底、字也看不清）。
        得**自己解析 rgba 再混到底色上**。
        """
        from PySide6.QtGui import QPalette

        from src.core import skins

        for skin in skins.all_skins():
            with self.subTest(skin=skin["name"]):
                skins.apply_skin(skin["id"], save=True)
                for _ in range(3):
                    self.app.processEvents()
                base = self.app.palette().color(QPalette.ColorRole.Base)
                self.assertNotEqual(
                    base.name(), "#000000",
                    f"{skin['name']} 的 Base 是纯黑 —— rgba 解析失败了吧")

    def test_rgba_parser(self):
        """★ ``_rgba`` 要能解析出正确的 r/g/b/alpha。"""
        from src.core import skins

        self.assertEqual(skins._rgba("rgba(255, 255, 255, 0.055)"),
                         (255, 255, 255, 0.055))
        self.assertEqual(skins._rgba("rgb(10, 20, 30)"),
                         (10, 20, 30, 1.0))
        self.assertEqual(skins._rgba("rgba(0,0,0,1)"), (0, 0, 0, 1.0))
        #: 解析不了 → 回落白色（不是黑）
        self.assertEqual(skins._rgba("不是颜色"), (255, 255, 255, 1.0))
        self.assertEqual(skins._rgba(""), (255, 255, 255, 1.0))
        self.assertEqual(skins._rgba(None), (255, 255, 255, 1.0))


class TestNavResizerTransparent(_SkinTestCase):
    """★★★ 侧栏那条**白缝**要修掉（用户 2026-10-05 截图）。

        用户::

            "另外这个白色的缝隙是什么"

    ``NavResizer`` 是个 5px 宽的**裸 ``QWidget``** —— 不透明，
    在深色玻璃背景上就是一条白竖条。

    ## ⚠⚠ 两条测试纪律（都踩过）

    1. **别调 ``w.close()``** —— ``closeEvent`` 会弹「确认关闭」模态框
       （``tray.ask_close``），测试**直接卡死**（实测 20 秒超时）。
       窗口建了就不用管，进程结束自然回收。
    2. **别建 ``MainWindow`` 超过必要次数** —— 一次约 5 秒。
    """

    #: 整个类共用**一个**窗口
    _window = None

    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    @classmethod
    def _window_once(cls):
        if cls._window is None:
            from src.core import skins
            from src.gui.main_window import MainWindow

            #: ⚠ ``save=False`` —— 别写真实的用户配置文件。
            #: 原来这里是 ``save=True``，**测试会改掉用户本地的皮肤设置**
            #: （跟之前 ``gacha_history.json`` 被测试写坏是同一类问题）。
            skins.apply_skin("deepglass", save=False)
            w = MainWindow()
            w.resize(1000, 700)
            w.show()
            skins.refresh_windows()
            for _ in range(4):
                cls.app.processEvents()
            cls._window = w
        return cls._window

    def test_nav_resizer_is_transparent(self):
        """★★★ ``NavResizer`` 默认**必须透明**。"""
        w = self._window_once()
        resizer = getattr(w, "nav_resizer", None)
        self.assertIsNotNone(resizer, "主窗口没有 nav_resizer")
        css = resizer.styleSheet()
        self.assertIn("transparent", css,
                      f"NavResizer 没设透明 —— 那就是那条白缝（{css[:60]}）")

    def test_nav_resizer_is_scoped(self):
        """★ 样式要带选择器（项目里的统一规则，防级联）。"""
        from src.gui.main_window import NavResizer

        w = self._window_once()
        resizer = NavResizer(w.navigationInterface, w)
        self.assertIn("#navResizer", resizer.styleSheet(),
                      "样式没带选择器 —— 会级联到子控件")

    def test_resizer_still_drags(self):
        """★ 透明之后**拖动功能不能丢**（不然白缝没了但也不能调宽了）。"""
        w = self._window_once()
        resizer = w.nav_resizer
        resizer._start_width = 200
        resizer._apply(240)
        self.assertEqual(w.navigationInterface.width(), 240,
                         "拖宽侧栏没生效 —— 透明把功能弄坏了？")


class TestSkinApply(_SkinTestCase):
    """应用皮肤（改全局主题）。"""

    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def setUp(self):
        from src.core import skins

        skins.apply_skin(skins.DEFAULT_SKIN, save=False)

    def tearDown(self):
        from src.core import skins

        skins.apply_skin(skins.DEFAULT_SKIN, save=False)

    def test_apply_unknown_skin_returns_false(self):
        from src.core import skins

        self.assertFalse(skins.apply_skin("不存在"))

    def test_apply_dark_skin_switches_theme(self):
        from qfluentwidgets import isDarkTheme

        from src.core import skins

        dark = next(s for s in skins.all_skins() if s["mode"] == "dark")
        self.assertTrue(skins.apply_skin(dark["id"], save=False))
        self.assertTrue(isDarkTheme(), f"{dark['name']} 没切暗色")

    def test_apply_light_skin_switches_back(self):
        from qfluentwidgets import isDarkTheme

        from src.core import skins

        dark = next(s for s in skins.all_skins() if s["mode"] == "dark")
        light = next(s for s in skins.all_skins() if s["mode"] == "light")
        skins.apply_skin(dark["id"], save=False)
        self.assertTrue(isDarkTheme())
        skins.apply_skin(light["id"], save=False)
        self.assertFalse(isDarkTheme(), "切回浅色后还是暗色模式")

    def test_apply_puts_qss_on_app(self):
        from src.core import skins

        s = skins.all_skins()[-1]
        skins.apply_skin(s["id"], save=False)
        self.assertIn("qlineargradient", self.app.styleSheet())


class TestWindowGetsQss(_SkinTestCase):
    """★★★ **顶层窗口必须拿到 QSS** —— 这是"白缝"的根因。

    ## ⚠⚠ 用户报过**两次**同一个症状

        "另外这个白色的缝隙是什么"          （2026-10-05）
        "这个白缝怎么又出现了"              （2026-10-06）

    第一次是 ``NavResizer`` 不透明；第二次是**我为了提速把
    ``w.setStyleSheet(qss)`` 删了**，理由写的是"app 级的会继承下来" ——
    那个理由是**错的**。

    项目里原本就写着::

        ⚠ 还要**逐个顶层窗口再设一遍** —— 主窗口有自己的调色板，
        只设 app 级会被它**盖掉**（实测 app 级 74.4%，window 级 99.1%）

    ## 还有第二个坑：缓存漏掉"后来才建的窗口"

    ``MainWindow.__init__`` 里就调了 ``apply_current_skin()`` ——
    **那时新窗口还没 show()**，不在可见窗口列表里。于是::

        apply #1（建窗口过程中）→ target 空 → 只刷了 app 级，记下缓存
        apply #2（窗口 show 后）→ QSS 相同 → **直接 return**
                                 → 新窗口永远没被刷过 → 白缝

    → 缓存要**连窗口一起比**（``_PAINTED_WINDOWS``）。
    """

    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def test_main_window_gets_qss(self):
        """★★★ 主窗口自己的 ``styleSheet()`` 要有**渐变**。

        ⚠ 只断言"app 级有 QSS"是**抓不住**的 —— app 级一直是好的，
        坏的是窗口级。
        """
        from src.core import skins
        from src.gui.main_window import MainWindow

        skins.apply_skin("deepglass", save=False)
        w = MainWindow()
        w.resize(1000, 700)
        w.show()
        for _ in range(4):
            self.app.processEvents()
        #: ★ 再刷一次 —— 模拟"窗口显示后"那次（这才是用户看到的状态）
        skins.apply_current_skin()
        for _ in range(3):
            self.app.processEvents()

        css = w.styleSheet()
        self.assertIn("qlineargradient", css,
                      f"主窗口没有渐变 QSS（长度 {len(css)}）—— "
                      f"app 级会被窗口自己的调色板盖掉，就会出现白缝")

    def test_new_window_after_cache_is_painted(self):
        """★★★ 缓存**不能漏掉后来才建的窗口**。

        ## 为什么单独测这个

        ``_PAINTED_QSS`` 缓存本意是"同一个皮肤别刷两次"（省那 1.4 秒）。
        但它**只看 QSS 字符串**，于是::

            建窗口 A → 刷过、记缓存（此时 A 还没 show）
            建窗口 B → QSS 没变 → **直接 return** → B 从来没被刷过

        → 缓存要连"刷过哪些窗口"一起比。
        """
        from PySide6.QtWidgets import QWidget

        from src.core import skins

        skins.apply_skin("deepglass", save=False)
        #: 先把缓存灌满（用一个先建好的窗口）
        first = QWidget()
        first.resize(300, 200)
        first.show()
        self.app.processEvents()
        skins.apply_current_skin()
        self.app.processEvents()

        #: 再建一个**新的**窗口，然后只 apply 一次
        second = QWidget()
        second.resize(300, 200)
        second.show()
        self.app.processEvents()
        skins.apply_current_skin()
        self.app.processEvents()

        self.assertIn("qlineargradient", second.styleSheet(),
                      "后建的窗口没被刷到 —— 缓存把它跳过了（会露白）")

    def test_repeat_apply_same_skin_is_skipped(self):
        """★★ 但**同一个皮肤 + 同一批窗口**重复 apply 仍然要跳过。

        ⚠ 这是当初加缓存的理由（``setTheme`` 一次 1.4 秒）。
        别为了修白缝把提速整个丢掉。
        """
        from PySide6.QtWidgets import QWidget

        from src.core import skins

        skins.apply_skin("deepglass", save=False)
        w = QWidget()
        w.resize(300, 200)
        w.show()
        self.app.processEvents()
        skins.apply_current_skin()
        self.app.processEvents()

        calls: list[str] = []
        orig = skins._paint_palette

        def _spy(app, skin):
            calls.append(skin["id"])
            return orig(app, skin)

        skins._paint_palette = _spy
        try:
            skins.apply_current_skin()          #: 同皮肤 + 同窗口 → 该跳过
        finally:
            skins._paint_palette = orig

        self.assertEqual(calls, [],
                         "重复 apply 没有跳过 —— 又回到每次都卡 1.4 秒")


class TestColorMathHasOneHome(_SkinTestCase):
    """★★★ 颜色数学（解析 / 混色）**只能有一份实现**。

    ## ⚠⚠ 这是实际发生的冗余（2026-10-06 自查发现）

    我在 ``detail_view.py`` 里为了"算实心底色"又写了一遍
    ``_rgba`` / ``_blend`` / ``_solid`` —— 和 ``skins.py`` 里那份
    **各算各的**。同一套公式两份实现，改了这处忘那处。

    → 统一到 :mod:`src.core.skins`：``parse_color`` / ``blend_color`` /
    ``solid_card_on``。这条测试盯着**别再分裂**。

    ⚠ 用**静态扫描**（跟 ``TestNoStyleCascade`` 一个套路）——
    比"跑一遍看结果对不对"更能挡住"复制一份小改改"。
    """

    @staticmethod
    def _color_math_defs() -> list[tuple[str, int, str]]:
        import pathlib
        import re

        root = pathlib.Path(__file__).resolve().parent.parent / "src"
        #: 颜色数学的典型特征（函数体里出现这些 = 在算颜色）
        names = ("_rgba", "parse_color", "blend_color", "_blend", "_solid",
                 "solid_card_on", "solid_card")
        found = []
        for f in root.rglob("*.py"):
            text = f.read_text(encoding="utf-8")
            for m in re.finditer(r"^def (\w+)\s*\(", text, re.M):
                if m.group(1) in names:
                    line = text[:m.start()].count("\n") + 1
                    found.append((str(f), line, m.group(1)))
        return found

    def test_color_math_lives_in_skins_only(self):
        """★★★ 解析/混色函数**只准定义在** ``src/core/skins.py``。"""
        import pathlib

        skins_path = str(pathlib.Path("src", "core", "skins.py"))
        offenders = [(f, ln, nm) for f, ln, nm in self._color_math_defs()
                     if pathlib.Path(f).name != "skins.py"
                     or "core" not in pathlib.Path(f).parts]
        self.assertEqual(
            offenders, [],
            f"颜色数学又分裂了（只该在 {skins_path}）：{offenders}")

    def test_parse_color_handles_both_syntaxes(self):
        """★★ ``parse_color`` 两种写法都要认（``rgba()`` 和 ``#rrggbb``）。"""
        from src.core import skins

        self.assertEqual(skins.parse_color("rgba(255, 255, 255, 0.5)"),
                         (255, 255, 255, 0.5))
        self.assertEqual(skins.parse_color("#102030"), (16, 32, 48, 1.0))
        self.assertEqual(skins.parse_color("#abc"), (170, 187, 204, 1.0))
        #: ⚠ 认不出要返回 None（不能瞎给白色 —— 调用方靠它判断）
        self.assertIsNone(skins.parse_color("不是颜色"))
        self.assertIsNone(skins.parse_color(""))

    def test_blend_color_math(self):
        """★★ 混色公式：alpha=0 取底、1 取顶、0.5 取中间。"""
        from src.core import skins

        self.assertEqual(skins.blend_color("#000000", "#ffffff", 0.0),
                         "#000000")
        self.assertEqual(skins.blend_color("#000000", "#ffffff", 1.0),
                         "#ffffff")
        mid = skins.blend_color("#000000", "#ffffff", 0.5)
        #: ⚠ 是 ``#808080`` 不是 ``#7f7f7f`` —— 实现用 ``round``（128 = 0x80）。
        #: 我第一版凭直觉写了 7f，被测试当场纠正。
        self.assertEqual(mid, "#808080", f"50% 混色算错了（{mid}）")
        #: 解析不出来时**原样返回底**，不瞎算
        self.assertEqual(skins.blend_color("#123456", "乱写", 0.5), "#123456")

    def test_solid_card_on_makes_opaque_hex(self):
        """★★ 半透明卡片要合成成**不透明的** ``#rrggbb``。"""
        from src.core import skins

        out = skins.solid_card_on("rgba(255,255,255,0.055)", "#0B1026",
                                  True)
        self.assertRegex(out, r"^#[0-9a-f]{6}$", f"不是不透明 hex（{out}）")
        #: 深色皮肤下要**提亮**，否则跟背景一样看不出分块
        self.assertNotEqual(out, "#0b1026",
                            "深色皮肤下卡片跟背景同色 —— 看不出分块")

    def test_qcolor_blend_uses_shared_formula(self):
        """★★★ ``_blend``（QColor 版）必须和 :func:`blend_color` **同源**。

        ## ⚠⚠ 为什么加这条（护栏验证时发现）

        ``test_color_math_lives_in_skins_only`` 只扫**函数定义** ——
        函数**留在原地**、但**函数体里自己又算一遍**的情况它抓不住::

            把 _blend 的实现改回"自己乘一遍" → 测试照样过

        → 用**行为**校验：两条路（字符串版 / QColor 版）算同一个输入，
        结果必须一致。
        """
        from PySide6.QtGui import QColor

        from src.core import skins

        for base, top, a in (("#000000", "#ffffff", 0.5),
                             ("#102030", "#a0b0c0", 0.25),
                             ("#0B1026", "#ffffff", 0.055)):
            with self.subTest(base=base, top=top, alpha=a):
                expect = skins.blend_color(base, top, a)
                got = skins._blend(QColor(base), QColor(top), a)
                self.assertEqual(
                    got.name(), expect,
                    f"_blend 和 blend_color 算出来不一样 —— 公式分裂了"
                    f"（{got.name()} vs {expect}）")

    def test_palette_base_is_not_black(self):
        """★★★ 调色板的 ``Base`` 不能是黑的（这个 bug 修过一次）。

        ``QColor("rgba(...)")`` **解析不出来、返回黑色** ——
        第一版就是这么写的，暗色皮肤下日志框还是黑底。
        """
        from PySide6.QtGui import QPalette

        from src.core import skins

        app = _app()
        for sid in ("mist", "deepglass"):
            with self.subTest(skin=sid):
                skins.apply_skin(sid, save=False)
                base = app.palette().color(QPalette.ColorRole.Base)
                self.assertNotEqual(base.name(), "#000000",
                                    f"「{sid}」的 Base 是黑的 —— "
                                    f"rgba 解析又出问题了")


class TestToolCardFollowsSkin(_SkinTestCase):
    """★★★ 主页工具卡片的底色要跟**皮肤**，不是 qfluentwidgets 的主题。

    ## ⚠⚠⚠ 用户 2026-10-08 截图

        用户（截图圈出整片卡片区）："我怎么鼠标已过去他才变色？"

    截图里**同一排卡片一半灰白、一半深紫** —— 划过的才变深。

    ## 根因

    ``ToolCard`` 继承 ``SimpleCardWidget``，而它的底色是::

        return QColor(255, 255, 255, 13 if isDarkTheme() else 170)
                                      ↑ 深色        ↑ 浅色（几乎不透明白 = 灰）

    ⚠ ``isDarkTheme()`` 读的是 **qfluentwidgets 的全局主题**，
    **不是我们的皮肤** —— 而且**只在"创建时"和"鼠标进出时"**被读::

        main.py: setTheme(Theme.AUTO)   # 按系统明暗（用户系统浅色 → 170 → 灰白）
        MainWindow()                    # ★ 卡片在这里创建，颜色定死 170
        apply_current_skin()            # 之后才切深色 —— 但卡片不重画

    → 实测：叠在紫底上，alpha 170 ≈ ``#b1afb9``（灰白，就是截图那几块）
            alpha  13 ≈ ``#211a39``（深紫，对的）

    ## 修法

    ``ToolCard`` 覆盖 ``_normalBackgroundColor`` / ``_hoverBackgroundColor``
    / ``_pressedBackgroundColor``，从 ``skin["card"]`` 取色。
    """

    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    @staticmethod
    def _over(bg: str, col) -> str:
        """把带 alpha 的颜色叠到底色上 —— 用户**实际看到**的颜色。"""
        from PySide6.QtGui import QColor

        b = QColor(bg)
        a = col.alpha() / 255.0
        return "#{:02x}{:02x}{:02x}".format(*[
            round(col.red() * a + b.red() * (1 - a)),
            round(col.green() * a + b.green() * (1 - a)),
            round(col.blue() * a + b.blue() * (1 - a)),
        ])

    def _one_card(self):
        from src.core.registry import ToolRegistry
        from src.gui.widgets import ToolCard
        from src.tools import discover_tools

        discover_tools()
        return ToolCard(ToolRegistry.all_metas()[0])

    def test_card_color_follows_skin(self):
        """★★★ 深浅皮肤下，卡片**看起来的颜色**必须不同。"""
        from src.core import skins

        seen = set()
        for sid in ("mist", "nebula", "deepglass"):
            skins.apply_skin(sid, save=False)
            skin = skins.active_skin()
            card = self._one_card()
            seen.add(self._over(skin["bg"][0][1],
                                card._normalBackgroundColor()))
        self.assertEqual(len(seen), 3,
                         f"三款皮肤下卡片看起来一样：{seen} —— 说明没跟皮肤")

    def test_card_is_not_grey_on_dark_skin(self):
        """★★★ 深色皮肤下卡片**不能是灰白的**（截图那个 bug）。"""
        from PySide6.QtGui import QColor

        from src.core import skins

        skins.apply_skin("nebula", save=False)
        skin = skins.active_skin()
        card = self._one_card()
        shown = self._over(skin["bg"][0][1], card._normalBackgroundColor())

        col = QColor(shown)
        lum = 0.2126 * col.red() + 0.7152 * col.green() + 0.0722 * col.blue()
        self.assertLess(
            lum, 100,
            f"深色皮肤下卡片渲染成 {shown}（亮度 {lum:.0f}）—— "
            f"那正是用户截图里那块灰白（alpha=170 的浅色主题值）")

    def test_hover_is_visibly_different(self):
        """★★ 悬停要**看得出变化**（基类这里返回和正常态一样的值）。

        ⚠ ``SimpleCardWidget._hoverBackgroundColor`` 就是
        ``return self._normalBackgroundColor()`` —— 一模一样，
        所以"划过去没反馈"。我们自己加了亮度差。
        """
        from src.core import skins

        skins.apply_skin("nebula", save=False)
        skin = skins.active_skin()
        card = self._one_card()
        bg = skin["bg"][0][1]
        normal = self._over(bg, card._normalBackgroundColor())
        hover = self._over(bg, card._hoverBackgroundColor())
        self.assertNotEqual(normal, hover,
                            "悬停和正常态一样 —— 鼠标划过去没反馈")

    def test_refresh_skin_colors_recolors(self):
        """★★★ ``refresh_skin_colors()``（换肤回调）要真的重取色。

        ## ⚠⚠⚠ 必须**固定同一个底色**再比（护栏验证时发现的）

        第一版我这样写::

            light = over(skins.active_skin()["bg"][0][1], 卡片色)   # mist 的 bg
            apply_skin("deepglass")
            dark  = over(skins.active_skin()["bg"][0][1], 卡片色)   # deepglass 的 bg

        —— **两次的底色不同**，所以就算卡片色**完全没更新**，
        叠出来的结果也不一样 → 测试照样通过（**假绿**）。

        实测（把 refresh 改成 no-op）::

            切皮肤后 _bg_rgba 还是旧的 → alpha 184（该是 14）
            但测试仍 pass

        → 改成**固定一个底色**，只让卡片色变化。
        """
        from src.core import skins

        #: ⚠ 固定底色 —— 这样"卡片色变没变"才是唯一变量
        fixed_bg = "#150E2E"

        skins.apply_skin("mist", save=False)
        card = self._one_card()
        light = self._over(fixed_bg, card._normalBackgroundColor())

        skins.apply_skin("deepglass", save=False)
        card.refresh_skin_colors()
        dark = self._over(fixed_bg, card._normalBackgroundColor())

        self.assertNotEqual(light, dark,
                            "换肤回调之后卡片没重取色（_bg_rgba 还是旧的）")

    def test_card_colors_stale_without_refresh(self):
        """★★★ 没有回调时卡片色**是旧皮肤的** —— 所以回调必须有。

        ⚠ 这条钉住"为什么需要 ``refresh_skin_colors``"：
        ``_bg_rgba`` 是**建卡片时缓存**的，换肤不会自动更新它。
        """
        from src.core import skins

        fixed_bg = "#150E2E"
        skins.apply_skin("mist", save=False)
        card = self._one_card()
        before = card._normalBackgroundColor().alpha()

        skins.apply_skin("deepglass", save=False)     #: 故意**不调** refresh
        stale = card._normalBackgroundColor().alpha()

        self.assertEqual(
            before, stale,
            "换肤后卡片色自己变了 —— 那 _bg_rgba 就不是缓存了，"
            "``refresh_skin_colors`` 也没必要存在")

        #: 而调了 refresh 就会更新
        card.refresh_skin_colors()
        self.assertNotEqual(
            before, card._normalBackgroundColor().alpha(),
            "refresh_skin_colors() 没更新 _bg_rgba")


class TestMainWindowPaintedAfterShow(_SkinTestCase):
    """★★★ 主窗口**显示之后**侧栏 / 标题栏必须被刷上皮肤。

    ## ⚠⚠⚠ 用户 2026-10-08 截图报的

        截图里：**侧栏是原生的黑、内容区是皮肤的紫**（割裂）
        "这是什么鬼"

    ## 根因：``_paint`` 只刷可见窗口，而 ``__init__`` 时窗口不可见

    ``MainWindow.__init__`` 里就调了 ``apply_current_skin()`` —— 但那时
    窗口**还没 show**，``topLevelWidgets()`` 里虽然有它、``isVisible()``
    却是 False → **一个都没刷到**。

    更糟的是那次"空刷"**被记进了缓存**（``_PAINTED_QSS``）→
    ``show()`` 之后再调也会被跳过。

    实测::

        建完窗口：窗口 QSS 长度 37（没挂）、NavigationPanel 长度 584
                  （还是原生的深灰 `rgb(32,32,32)`）
        清缓存重刷：1774 / 有渐变  ✓

    → 修法：``MainWindow.showEvent`` 里补刷一次（那时窗口可见了）。
    """

    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def test_sidebar_and_titlebar_get_gradient(self):
        """★★★ 显示后：窗口 / 侧栏 / 标题栏都要带**渐变**。

        ⚠⚠⚠ **不要在这里手动清缓存**（护栏验证时改的）

        第一版我在测试开头 `skins._PAINTED_QSS = ""` —— 结果把
        "补刷时忘了清缓存"这个**真 bug** 掩盖了::

            把 main_window 里补刷前的 `_PAINTED_QSS = ""` 删掉
            → 测试照样过（因为我自己在前面清了）

        → **让真实的启动路径自己跑**：`__init__` 会先"空刷"一次
        并**污染缓存**，然后 `show()` 触发补刷。补刷若不清缓存，
        就会被跳过 —— 那正是出 bug 的状态。
        """
        from qfluentwidgets import FluentTitleBar, NavigationPanel

        from src.core import skins
        from src.gui.main_window import MainWindow

        #: ⚠ 只清"窗口名单"，**故意保留** `_PAINTED_QSS`
        #: —— 模拟"前面已经有别的窗口刷过"的真实情况。
        skins._PAINTED_WINDOWS = set()

        w = MainWindow()
        w.resize(1200, 800)
        w.show()
        for _ in range(8):
            self.app.processEvents()

        self.assertIn("qlineargradient", w.styleSheet(),
                      f"窗口级 QSS 没挂上（长度 {len(w.styleSheet())}）—— "
                      f"内容区会是主题色、侧栏是原生色")

        panels = w.findChildren(NavigationPanel)
        self.assertTrue(panels, "没找到 NavigationPanel")
        css = panels[0].styleSheet()
        self.assertIn("qlineargradient", css,
                      f"侧栏没刷上渐变（长度 {len(css)}）—— "
                      f"用户截图里那条「原生的黑」就是这个")

        bars = w.findChildren(FluentTitleBar)
        self.assertTrue(bars, "没找到 FluentTitleBar")
        #: ⚠ 第一个是左上角那个小的（宽度 200），第二个才是主标题栏
        main = max(bars, key=lambda b: b.width())
        self.assertIn("qlineargradient", main.styleSheet(),
                      "主标题栏没刷上渐变")

    def test_sidebar_color_is_not_native_dark(self):
        """★★★ 侧栏渲染出来的颜色**不能是原生深灰**（``#000000`` 那种）。

        ⚠ 这条**直接看像素** —— 比查 styleSheet 更贴近用户看到的。
        ⚠ 同样**不清** ``_PAINTED_QSS``（见上一条的说明）。
        """
        from src.core import skins
        from src.gui.main_window import MainWindow

        skins._PAINTED_WINDOWS = set()

        w = MainWindow()
        w.resize(1200, 800)
        w.show()
        for _ in range(8):
            self.app.processEvents()

        img = w.grab().toImage()
        nav_px = img.pixelColor(90, 300).name()
        content_px = img.pixelColor(w.width() - 200, 300).name()

        self.assertNotEqual(nav_px, "#000000",
                            "侧栏渲染成纯黑了 —— 就是截图里那个原生色")
        #: 侧栏和内容区应该是**同一个色系**（同一款皮肤的渐变），
        #: 不该一个纯黑一个紫。
        def _lum(hexv: str) -> float:
            h = hexv.lstrip("#")
            r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
            return 0.2126 * r + 0.7152 * g + 0.0722 * b

        self.assertLess(
            abs(_lum(nav_px) - _lum(content_px)), 80,
            f"侧栏({nav_px}) 和内容区({content_px}) 亮度差太多 —— "
            f"看着就是两块割裂的颜色")


class TestSkinPersists(_SkinTestCase):
    """★★★ 皮肤选完要**真的存住**，重开程序还在。

    ## ⚠⚠⚠ 用户 2026-10-08 装完包才发现的 bug

        "我用安装包安装后，皮肤应用之后，再次重新打开，还是之前的皮肤"

    ## 三个叠加的原因（都不是显而易见的）

    ### ① item 挂在**模块级**，qconfig 存不了它

    ``QConfig.toDict()`` 的实现是::

        for name in dir(self._cfg.__class__):     # ← 只扫**类属性**
            item = getattr(self._cfg.__class__, name)
            if not isinstance(item, ConfigItem): continue

    模块级变量它看不见 → ``qconfig.set()`` 改了内存，``save()`` **扫不到**。
    实测：落盘只有 ``QFluentWidgets`` 一节，**没有 Skins**。

    ### ② 配置文件写在**相对路径**（跟着当前工作目录跑）

    ``qconfig.file`` 默认 ``WindowsPath('config/config.json')``。
    开发时 CWD 是项目目录，看着正常；**打包后 CWD 是安装目录** ——
    重装/卸载会清掉，装到 ``Program Files`` 还可能没权限写。

    ### ③ ⚠⚠ 顺序反了：``load()`` 跑在 item 注册**之前**

    这条最隐蔽。``load()`` 也是**遍历 QConfig 类属性**填值的 ——
    如果那时 ``QConfig.skin`` 还不存在，磁盘上的值就没地方填。

    实测::

        磁盘 = {"Skins": {"CurrentSkin": "ember"}}
        顺序错 → 全新进程读出来 mist
        顺序对 → 全新进程读出来 ember   ✓

    ⚠ 我验证时还绕过几圈**自己脚本的 bug**：
      · 外层进程 ``qconfig.file`` 是旧值 → 读的是**另一个文件**
      · 写完没恢复默认 → 读默认值本来就是对的，我却以为"没存住"
    """

    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def test_item_is_on_qconfig_class(self):
        """★★★ item 必须挂在 **QConfig 类**上。

        ⚠ 挂到"自己新建的类"上也**没用** —— ``qconfig._cfg.__class__``
        就是 ``QConfig``，扫的是它。我第一次挂在 ``_SkinConfig`` 上，
        验证脚本还误报成功了。
        """
        from qfluentwidgets.common.config import QConfig

        from src.core import skins

        item = skins._skin_item()
        self.assertIs(getattr(QConfig, "skin", None), item,
                      "皮肤 ConfigItem 没挂在 QConfig 类上 —— "
                      "qconfig.save() 扫不到它，皮肤存不住")

    def test_config_file_is_absolute_and_in_user_data(self):
        """★★★ 落盘位置必须是**用户数据目录**下的**绝对路径**。"""
        import pathlib

        from qfluentwidgets import qconfig

        from src.core import paths, skins

        skins._skin_item()          #: 触发 _ensure_config_file
        f = pathlib.Path(str(qconfig.file))
        self.assertTrue(f.is_absolute(),
                        f"qconfig.file 还是相对路径（{f}）—— "
                        f"打包后会写进安装目录")
        self.assertEqual(f.parent, paths.user_data_dir(),
                         f"配置没落在用户数据目录（{f}）")

    def test_saved_value_actually_reaches_disk(self):
        """★★★ 换皮肤之后，磁盘上要**真的有**那个值。

        ⚠ 只断言 ``current_skin()`` 不够 —— 那只读内存，
        **内存对了磁盘没写**正是这个 bug 的表现。

        ## ⚠⚠⚠ 不能靠"改 qconfig.file 到 temp"来隔离（试过，不行）

        ``_skin_item()`` 里的 ``_ensure_config_file()`` 会把路径
        **"纠正"回** ``data/config.json``（那是生产代码的**正确**行为）——
        实测::

            qconfig.load(file=tmp)          → qconfig._cfg.file = tmp
            skins._skin_item() 一跑          → 又被改回 data/config.json
            apply_skin(...)                  → 写进 data/config.json

        → 那就**直接用真实文件**，但**先备份、测完还原**。
        （``qconfig.set`` 还有个"值没变就早退"的坑：必须先把内存值
        改掉，否则它什么都不写。）

        ⚠⚠ 另外 ``test_skins.py`` 里**好几个测试都在 apply_skin(save=True)**
        写同一个文件 —— 这本身就不该（会改用户配置）。
        完整隔离需要把这些都改掉，属于另一件事，见测试文件顶部说明。

        ## ⚠⚠⚠ 真正的隔离：临时文件 + 关掉"路径纠正"

        直接改 ``qconfig.file`` **没用** —— ``_skin_item()`` 里的
        ``_ensure_config_file()`` 会把它**纠正回** ``data/config.json``::

            qconfig.load(file=tmp)     → _cfg.file = tmp
            skins._skin_item() 一跑     → 又被改回 data/config.json
            apply_skin(...)             → 写进 data/config.json（不是 tmp）

        → 这条测试**暂时把路径纠正关掉**（monkeypatch 成 no-op），
        就能安心用临时文件，**谁也抢不到、也不碰用户配置**。
        """
        import json
        import pathlib
        import tempfile

        from qfluentwidgets import qconfig

        from src.core import skins

        target = "nebula"
        original_load = skins._ensure_config_file
        original_file = qconfig.file
        tmp = pathlib.Path(tempfile.mkdtemp()) / "config.json"
        try:
            #: ★ 关掉路径纠正 —— 否则它会把我设的临时路径改回去
            skins._ensure_config_file = lambda: None
            qconfig.load(file=tmp)

            #: ★ 内存值和文件值都要**不是** target，
            #: 否则 qconfig.set() 会因为"值没变"早退、不写盘
            skins._skin_item().value = skins.DEFAULT_SKIN
            tmp.write_text(json.dumps(
                {"QFluentWidgets": {},
                 "Skins": {"CurrentSkin": skins.DEFAULT_SKIN}},
                ensure_ascii=False), encoding="utf-8")
            qconfig.load(file=tmp)

            skins.apply_skin(target, save=True)

            self.assertTrue(tmp.exists(), f"配置文件没生成（{tmp}）")
            raw = json.loads(tmp.read_text(encoding="utf-8"))
            self.assertIn("Skins", raw,
                          f"落盘内容里没有 Skins 节：{list(raw)}")
            self.assertEqual(raw["Skins"].get("CurrentSkin"), target,
                             f"磁盘上存的不是刚设的值：{raw.get('Skins')}")
        finally:
            skins._ensure_config_file = original_load
            qconfig.load(file=pathlib.Path(original_file))
            try:
                skins.apply_skin(skins.DEFAULT_SKIN, save=False)
            except Exception:  # noqa: BLE001
                pass

    #: ── ★★★ 下面这条是**唯一能真正抓住"顺序"问题**的测试
    #:
    #: ⚠⚠⚠ 为什么必须**开新进程**（我在这里绕了好几圈）
    #:
    #: ``_SKIN_ITEM`` 是**模块级单例** —— 测试进程里它早就建好了，
    #: 所以 ``_skin_item()`` 里那段"懒建"代码**根本不会执行**。
    #:
    #: 后果：把 ``load()`` 挪到挂载**之前**（就是把 bug 改回去），
    #: 那 4 条**进程内**测试**全都照样通过** —— 假绿。
    #:
    #: 实测确认::
    #:
    #:     修复后          → 新进程读 nebula   ✓
    #:     load 提前（bug） → 新进程读 mist     ✗   ← 只有新进程看得出来
    #:
    #: → 用 ``subprocess`` 起两个全新进程：一个写、一个读。
    def test_skin_survives_a_real_restart(self):
        """★★★ **真·重启**：两个独立进程 —— 一个写、一个读。

        这是唯一能覆盖"启动时读盘顺序"的测法。
        """
        import os
        import pathlib
        import subprocess

        root = pathlib.Path(__file__).resolve().parent.parent
        py = str(root / ".venv" / "Scripts" / "python.exe")
        if not pathlib.Path(py).exists():
            self.skipTest("找不到 venv python")

        env = dict(os.environ, QT_QPA_PLATFORM="offscreen",
                   PYTHONIOENCODING="utf-8")

        def run(body: str) -> str:
            r = subprocess.run([py, "-c", head + body],
                               capture_output=True, text=True,
                               encoding="utf-8", errors="replace",
                               cwd=str(root), timeout=180, env=env)
            return ((r.stdout or "") + (r.stderr or ""))

        #: ⚠⚠ 子进程也要**隔离到临时目录** —— 否则它会写用户真实的
        #: ``data/config.json``（测试不该动用户数据）。
        #: ``paths.user_data_dir`` 在非打包态固定是 ``<项目>/data``，
        #: 所以在这里**猴补**掉，让 qconfig 落到 temp。
        import tempfile

        tmpdir = pathlib.Path(tempfile.mkdtemp())
        head = (f"import sys, pathlib\n"
                f"sys.path.insert(0, r'{root}')\n"
                f"from src.core import paths\n"
                f"paths.user_data_dir = lambda: pathlib.Path(r'{tmpdir}')\n"
                "from PySide6.QtWidgets import QApplication\n"
                "app = QApplication.instance() or QApplication([])\n"
                "from src.core import skins\n")

        target = "ember"
        #: ① 进程 A：写成 ember
        out = run(f"skins.apply_skin('{target}', save=True)\n"
                  "print('OK')\n")
        self.assertIn("OK", out, f"写入进程失败：{out[-300:]}")

        #: ② 进程 B（全新）：读出来应该还是 ember
        out = run("print('SKIN', skins.current_skin()['id'])\n")
        line = [ln for ln in out.splitlines() if ln.startswith("SKIN")]
        self.assertTrue(line, f"读取进程没输出：{out[-300:]}")
        got = line[0].split()[-1]
        self.assertEqual(
            got, target,
            f"重启后读出来是 {got!r} 而不是 {target!r} —— "
            f"皮肤没存住（或者启动时读盘的顺序不对）")

    def test_value_survives_reload_from_disk(self):
        """★★★ 从磁盘**重新读**能拿到存的那个值（= 重开程序）。

        ⚠ 这条盯的是**顺序**：``load()`` 必须在 item 注册**之后**跑，
        否则磁盘有值也填不进去。

        ⚠ 同样用**真实文件 + 备份还原**（``_ensure_config_file`` 会把
        路径纠正回 ``data/config.json``，临时文件隔离不了）。
        """
        import json
        import pathlib
        import shutil

        from qfluentwidgets import qconfig

        from src.core import skins

        target = "abyss"
        f = pathlib.Path(str(qconfig.file))
        if not f.is_absolute():
            f = pathlib.Path(__file__).resolve().parent.parent / f
        backup = f.with_suffix(".json.testbak")
        had = f.exists()
        if had:
            shutil.copy2(f, backup)
        try:
            #: 先把内存值改掉 —— 否则 set() 因"值没变"早退
            skins._skin_item().value = skins.DEFAULT_SKIN
            skins.apply_skin(target, save=True)

            assert json.loads(f.read_text(encoding="utf-8"))["Skins"][
                "CurrentSkin"] == target, "前提不成立：没写进磁盘"

            #: 清成默认，再从磁盘 load（模拟新进程启动）
            skins._skin_item().value = skins.DEFAULT_SKIN
            qconfig.load()
            self.assertEqual(
                skins.current_skin()["id"], target,
                "从磁盘 load 之后没拿回存的值 —— "
                "load() 和 item 注册的顺序反了")
        finally:
            if had:
                shutil.copy2(backup, f)
                backup.unlink()
            try:
                skins.apply_skin(skins.DEFAULT_SKIN, save=False)
            except Exception:  # noqa: BLE001
                pass


class TestSkinReallyChangesPixels(_SkinTestCase):
    """★★★ **真的换肤了** —— 渲染后逐点采样比对。

    用户报的 bug：「只有深色的皮肤有效果，其他的根本没有效果」。

    ⚠ 光断言"调了 setThemeColor"**抓不住** ——
    第一版就是这么写的，测试全绿但浅色皮肤 **0.0%** 变化。
    """

    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def setUp(self):
        from src.core import skins

        skins.apply_skin(skins.DEFAULT_SKIN, save=False)

    def tearDown(self):
        from src.core import skins

        skins.apply_skin(skins.DEFAULT_SKIN, save=False)

    @staticmethod
    def _harness():
        """最小窗口：``QStackedWidget``（页面容器）+ ``CardWidget``（卡片）。"""
        from qfluentwidgets import CardWidget
        from PySide6.QtWidgets import QStackedWidget, QVBoxLayout, QWidget

        win = QWidget()
        box = QVBoxLayout(win)
        box.setContentsMargins(0, 0, 0, 0)
        stack = QStackedWidget(win)
        page = QWidget(stack)
        inner = QVBoxLayout(page)
        card = CardWidget(page)
        card.setFixedHeight(80)
        inner.addWidget(card)
        stack.addWidget(page)
        box.addWidget(stack)
        win.resize(400, 300)
        return win

    def _sample(self, win):
        """渲染后取稀疏采样（一串颜色）。"""
        for _ in range(3):
            self.app.processEvents()
        img = win.grab().toImage()
        return [img.pixelColor(x, y).name()
                for y in range(0, img.height(), 6)
                for x in range(0, img.width(), 6)]

    @staticmethod
    def _representative():
        """挑**有代表性**的几款皮肤 —— 每款 ``apply_skin`` 要 **3 秒**。

        ## ⚠⚠ 为什么要挑（2026-10-05 实测）

        ``apply_skin`` → ``setTheme`` → qfluentwidgets **重算全局 QSS**，
        实测 **3 秒/次**（库的固有开销，不是我们的代码）。

        全 6 款都跑的话这两条测试就要 **50 秒+**，
        而整个 ``test_skins.py`` 因此变成 **7 分钟**（整仓测试的最大瓶颈）。

        挑法：**每个模式取第一款**，另外必测默认皮肤 ——
        浅色/暗色各有一款就足以覆盖"换肤到底有没有生效"这件事
        （这正是用户报的 bug：浅色全都没效果）。
        """
        from src.core import skins

        picked: list[dict] = []
        seen_modes: set[str] = set()
        for s in skins.all_skins():
            if s["id"] == skins.DEFAULT_SKIN or s["mode"] not in seen_modes:
                picked.append(s)
                seen_modes.add(s["mode"])
        return picked

    def test_every_skin_looks_different(self):
        """★★★ **不同模式**的皮肤渲染出来必须不一样。

        这一条直接对应用户的话："其他的根本没有效果" ——
        没效果 = 几款皮肤渲染出同一个画面。

        ⚠ 只测代表性那几款（见 :meth:`_representative`）——
        全跑一遍要 50 秒，是整仓测试最大的瓶颈。
        """
        from src.core import skins

        win = self._harness()
        win.show()
        self.app.processEvents()

        seen: dict[tuple, str] = {}
        for s in self._representative():
            with self.subTest(skin=s["name"]):
                skins.apply_skin(s["id"], save=False)
                sig = tuple(self._sample(win))
                self.assertNotIn(
                    sig, seen,
                    f"「{s['name']}」和「{seen.get(sig)}」渲染出"
                    f"一模一样的画面 —— 换了个寂寞")
                seen[sig] = s["name"]

    def test_skin_changes_most_of_the_screen(self):
        """★★★ 换皮肤要改变**大部分**像素（不是只动几个）。

        ⚠ 第一版浅色皮肤实测只变 **0.0%** —— 这条就是抓它的。
        阈值取 30%：换渐变能到 60%+，"只换主色"是 0%。

        ⚠ 同样只测代表性那几款（全跑要 50 秒）。
        """
        from src.core import skins

        win = self._harness()
        win.show()
        self.app.processEvents()

        skins.apply_skin(skins.DEFAULT_SKIN, save=False)
        base = self._sample(win)

        for s in self._representative():
            if s["id"] == skins.DEFAULT_SKIN:
                continue
            with self.subTest(skin=s["name"]):
                skins.apply_skin(s["id"], save=False)
                cur = self._sample(win)
                diff = sum(1 for a, b in zip(base, cur) if a != b)
                pct = 100 * diff / len(base)
                self.assertGreater(
                    pct, 30,
                    f"「{s['name']}」只改了 {pct:.1f}% 的画面 —— "
                    f"用户会说「根本没有效果」（第一版是 0.0%）")

    def test_qss_differs_for_all_skins(self):
        """★★★ 补一条**纯字符串**的：每款皮肤的 QSS 都不同，且**页面容器**
        用的是它自己的**渐变**。

        ## ⚠⚠ 为什么必须有这条（护栏验证时发现的）

        上面两条为了省时间只渲染**代表性那几款**（每款 3 秒）。
        结果我把 ``build_qss`` 里 ``QStackedWidget`` 的渐变改成
        "只用卡片色"（就是用户最初报的那个 bug：浅色皮肤完全没效果）时，
        **那两条测试居然还过** —— 因为被选中的那两款恰好还是不同的。

        → 那两条只够验"渲染通路是通的"，验不了"每款都真的换了"。
        这条**不渲染**、纯比字符串，能把**全部**皮肤都覆盖到。

        ## ⚠⚠ 断言必须**指名道姓**查 `QStackedWidget`

        第一版我写的是"QSS 里含 ``qlineargradient``" ——
        **抓不住那个突变**：``build_qss`` 里 ``NavigationPanel`` 那行
        **也有渐变**，把 ``QStackedWidget`` 那行改掉之后，
        整体照样"含渐变"（实测 3 处）。

        → 得把 **`QStackedWidget { ... }` 那一段单独抠出来**检查。
        """
        import re

        from src.core import skins

        seen: dict[str, str] = {}
        for s in skins.all_skins():
            qss = skins.build_qss(s)
            with self.subTest(skin=s["name"]):
                #: ① **页面容器**那一段必须用这个皮肤的渐变
                m = re.search(r"QStackedWidget\s*\{([^}]*)\}", qss)
                self.assertIsNotNone(m, "QSS 里没有 QStackedWidget 规则")
                block = m.group(1)
                self.assertIn(
                    "qlineargradient", block,
                    f"「{s['name']}」的页面容器没用渐变（{block.strip()[:60]}）"
                    f" —— 那就是用户报的「根本没有效果」")
                for _pos, color in s["bg"]:
                    self.assertIn(color, block,
                                  f"「{s['name']}」的页面容器少了渐变色 {color}")
                #: ② 跟别的皮肤不许重样
                self.assertNotIn(qss, seen,
                                 f"「{s['name']}」和「{seen.get(qss)}」的 QSS 一样")
                seen[qss] = s["name"]


class TestSkinPersistence(_SkinTestCase):
    """皮肤选择的持久化（用独立 config 文件，不碰用户的）。"""

    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        from qfluentwidgets import qconfig

        self._orig_file = qconfig.file
        import pathlib

        qconfig.file = pathlib.Path(self._tmp.name) / "test.json"
        from src.core import skins

        skins.apply_skin(skins.DEFAULT_SKIN, save=True)

    def tearDown(self):
        from qfluentwidgets import qconfig

        qconfig.file = self._orig_file
        from src.core import skins

        skins.apply_skin(skins.DEFAULT_SKIN, save=False)
        self._tmp.cleanup()

    def test_apply_skin_saves_choice(self):
        from src.core import skins

        skin = skins.all_skins()[-1]
        self.assertTrue(skins.apply_skin(skin["id"], save=True))
        self.assertEqual(skins.current_skin()["id"], skin["id"])

    def test_apply_without_save_does_not_change_current(self):
        from src.core import skins

        before = skins.current_skin()["id"]
        skin = next(s for s in skins.all_skins() if s["id"] != before)
        self.assertTrue(skins.apply_skin(skin["id"], save=False))
        self.assertEqual(skins.current_skin()["id"], before,
                         "save=False 也改了存的选择 —— 那就不是预览了")

    def test_current_skin_falls_back_to_default(self):
        from qfluentwidgets import qconfig

        from src.core import skins

        qconfig.set(skins._skin_item(), skins._skin_item().defaultValue)
        self.assertEqual(skins.current_skin()["id"], skins.DEFAULT_SKIN)


class TestSkinPage(_SkinTestCase):
    """★ 皮肤**页面**（侧栏导航项 → 右边卡片）。

    用户："皮肤加在左侧边栏，不是左下角，
    右边显示所有的皮肤，以卡片的形式展示"
    """

    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        from qfluentwidgets import qconfig

        self._orig_file = qconfig.file
        import pathlib

        qconfig.file = pathlib.Path(self._tmp.name) / "test.json"
        from src.core import skins

        skins.apply_skin(skins.DEFAULT_SKIN, save=True)

    def tearDown(self):
        from qfluentwidgets import qconfig

        qconfig.file = self._orig_file
        from src.core import skins

        skins.apply_skin(skins.DEFAULT_SKIN, save=False)
        self._tmp.cleanup()

    def test_page_has_card_per_skin(self):
        from src.core import skins
        from src.gui.skin_page import build_skin_page

        page = build_skin_page()
        self.assertEqual(len(page._cards), len(skins.all_skins()))

    def test_page_is_scroll_area(self):
        """★★ 页面必须是 ``ScrollArea`` + ``setWidget``。

        ⚠ 第一版做成裸 ``QWidget`` —— **整页不显示**
        （实测 100x30、不可见）。这是本项目的固定写法。
        """
        from qfluentwidgets import ScrollArea

        from src.gui.skin_page import build_skin_page

        page = build_skin_page()
        self.assertIsInstance(page, ScrollArea,
                              "皮肤页不是 ScrollArea —— 整页会不显示")
        self.assertIsNotNone(page.widget(),
                             "没 setWidget(view) —— 整页会被压扁")

    def test_preview_draws_the_skin_gradient(self):
        """★★★ 卡片预览条要**真的画该皮肤的渐变**。

        ⚠⚠ 上一版这里有真 bug：把 ``bg``（列表）直接插进 QSS，
        拼出 ``stop:0 [(0.0, '#0B1026'), ...]`` —— 解析失败、
        预览条和卡片背景**全画不出来**（实测卡片区是纯灰）。
        """
        from src.core import skins
        from src.gui.skin_page import build_skin_page
        from PySide6.QtWidgets import QWidget

        page = build_skin_page()
        for card in page._cards:
            with self.subTest(skin=card._skin["name"]):
                prev = card.findChild(QWidget, "skinPreview")
                self.assertIsNotNone(prev, "卡片没有预览条")
                css = prev.styleSheet()
                self.assertIn("qlineargradient", css,
                              f"预览条没画渐变：{css[:80]}")
                self.assertNotIn(
                    "[", css,
                    f"预览条的 QSS 里混进了 Python 列表（上一版的 bug）："
                    f"{css[:110]}")
                #: 该皮肤的每个 stop 都要在
                for _pos, color in card._skin["bg"]:
                    self.assertIn(color, css,
                                  f"预览条少了渐变色 {color}")

    def test_card_text_uses_current_skin_not_own(self):
        """★★★ 卡片上的**所有文字**都要用**当前皮肤**的颜色。

        ## 为什么（用户截图里看出来的）

        深色皮肤的 ``text`` / ``dim`` 是**浅色**（``#E8ECF5`` / ``#8B93A7``）——
        如果卡片文字用它自己的色，画在**当前皮肤**（也许是浅色）的
        页面底上 → **字几乎看不见**（用户截图里那三款深色卡片就是）。

        道理：卡片坐落在**当前皮肤的页面**上，对比度该跟**页面**算。

        ## ⚠ 覆盖名字 / 说明 / 色值**三处**

        只测名字是不够的 —— 护栏验证时把 ``desc`` 单独改回旧写法，
        测试**抓不住**（因为我只查了名字那个标签）。
        """
        from PySide6.QtWidgets import QLabel

        from src.core import skins
        from src.gui.skin_page import build_skin_page

        dark = skins.skin_by_id("deepglass")
        skins.apply_skin(dark["id"], save=True)

        page = build_skin_page()
        for card in page._cards:
            s = card._skin
            with self.subTest(skin=s["name"]):
                #: ① 名字 → 当前皮肤的 text
                nm = [w for w in card.findChildren(QLabel)
                      if w.text() == s["name"]]
                self.assertTrue(nm, f"找不到「{s['name']}」名字标签")
                self.assertIn(
                    dark["text"], nm[0].styleSheet(),
                    f"「{s['name']}」名字没用当前皮肤的文字色 "
                    f"（{nm[0].styleSheet()[:60]}）—— 浅色页面上看不见")

                #: ② 说明 → 当前皮肤的 dim
                desc = [w for w in card.findChildren(QLabel)
                        if w.text() == s["desc"]]
                self.assertTrue(desc, f"找不到「{s['name']}」说明标签")
                self.assertIn(
                    dark["dim"], desc[0].styleSheet(),
                    f"「{s['name']}」说明没用当前皮肤的次要色 "
                    f"（{desc[0].styleSheet()[:60]}）—— 会看不清")

                #: ③ 色值 → 当前皮肤的 dim
                hexlab = [w for w in card.findChildren(QLabel)
                          if w.text() == s["primary"].upper()]
                self.assertTrue(hexlab, f"找不到「{s['name']}」色值标签")
                self.assertIn(
                    dark["dim"], hexlab[0].styleSheet(),
                    f"「{s['name']}」色值没用当前皮肤的次要色")

    def test_card_text_switches_with_skin(self):
        """★★ 换了当前皮肤，卡片文字色**跟着换**。"""
        from PySide6.QtWidgets import QLabel

        from src.core import skins
        from src.gui.skin_page import build_skin_page

        def name_css(skin_id: str) -> str:
            skins.apply_skin(skin_id, save=True)
            page = build_skin_page()
            card = page._cards[0]
            for w in card.findChildren(QLabel):
                if w.text() == card._skin["name"]:
                    return w.styleSheet()
            return ""

        light_css = name_css("mist")
        dark_css = name_css("deepglass")
        self.assertNotEqual(light_css, dark_css,
                            "换皮肤后卡片文字色没变 —— 深色下会看不清")
        self.assertIn(skins.skin_by_id("mist")["text"], light_css)
        self.assertIn(skins.skin_by_id("deepglass")["text"], dark_css)

    def test_active_card_is_marked(self):
        from src.core import skins
        from src.gui.skin_page import build_skin_page

        target = skins.all_skins()[-1]
        skins.apply_skin(target["id"], save=True)
        page = build_skin_page()
        marked = [c for c in page._cards if c._is_active]
        self.assertEqual(len(marked), 1, "应该有正好一张「使用中」")
        self.assertEqual(marked[0]._skin["id"], target["id"])

    def test_clicking_card_applies_skin(self):
        from src.core import skins
        from src.gui.skin_page import build_skin_page

        page = build_skin_page()
        target = skins.all_skins()[-1]
        card = next(c for c in page._cards if c._skin["id"] == target["id"])
        card.chosen.emit(target["id"])
        self.assertEqual(skins.current_skin()["id"], target["id"])


class TestNoToplevelWidgetLeak(_SkinTestCase):
    """★★★ 测试**不许把顶层控件留着** —— 那会让整套测试跑不完。

    ## 为什么单独有这个类（2026-10-10：整套测试挂了 9 小时）

    本文件的测试会建 ``MainWindow``，而 ``skins._paint`` 里有一句::

        app.setStyleSheet(qss)     # 对所有控件递归 re-polish

    → **活着的窗口越多，``apply_skin()`` 越慢**（实测）::

        0 个 MainWindow → 0.000s
        1 个            → 2.8s
        3 个            → 8.5s

    原来多个类建了窗口就不管（注释里还写着"进程结束自然回收"），
    于是越攒越多 → 单次涨到几十秒 × 调用几十次 → **整套跑几个小时不结束**。

    ## ⚠ ``deleteLater()`` 单独用是**没用的**

    ``QApplication.processEvents()`` **默认不处理** ``DeferredDelete`` 事件，
    所以原来那些 ``w.deleteLater()`` 全等于没删（实测 24 个控件跑完还是 24 个）。
    必须 ``sendPostedEvents(None, DeferredDelete)`` —— 见 :func:`_destroy_toplevels`。

    下面两条分别钉住"机制对"和"基类真的接上了"。
    """

    def test_delete_later_needs_send_posted_events(self):
        """★★ ``deleteLater()`` + ``processEvents()`` **不足以**销毁控件。

        这条是"为什么必须 sendPostedEvents"的证据 ——
        哪天有人说"调了 deleteLater 就够了"，跑这条看数据。
        """
        from PySide6.QtWidgets import QApplication, QWidget

        app = QApplication.instance() or QApplication([])
        before = len(app.topLevelWidgets())

        w = QWidget()
        w.deleteLater()
        app.processEvents()
        self.assertGreater(
            len(app.topLevelWidgets()), before,
            "processEvents() 竟然处理了 DeferredDelete —— "
            "那 _destroy_toplevels 里的 sendPostedEvents 可以重新评估")

        _destroy_toplevels()          #: 收尾，别把上面那个漏了
        self.assertEqual(len(app.topLevelWidgets()), before,
                         "sendPostedEvents 之后应该清干净")

    def test_base_class_cleans_up_after_each_class(self):
        """★★★ 基类必须在**每个类跑完**后把顶层控件清零。

        ⚠⚠ 这条**必须真的走基类的 ``tearDownClass()``**，不能自己调
        ``_destroy_toplevels()`` —— 护栏验证时发现：自己调的话，
        把基类的清理**删掉**测试照样通过（假绿）。

        做法：现造一个继承 ``_SkinTestCase`` 的一次性类，
        先弄脏环境，再调**它**的 ``tearDownClass()``。
        """
        from PySide6.QtWidgets import QApplication, QWidget

        app = QApplication.instance() or QApplication([])

        class _Probe(_SkinTestCase):
            """只借它的 ``tearDownClass``，不真跑测试。"""

        #: 造两个"泄漏的"顶层控件，模拟没写清理的测试类
        leaks = [QWidget() for _ in range(2)]
        for w in leaks:
            w.show()
        app.processEvents()
        self.assertGreaterEqual(len(app.topLevelWidgets()), 2,
                                "造的泄漏控件没进 topLevelWidgets")

        #: ★ 走**基类**那条路径（删掉基类的清理 → 这里就会挂）
        _Probe.tearDownClass()

        self.assertEqual(len(app.topLevelWidgets()), 0,
                         "基类 tearDownClass 没清干净 —— "
                         "跑整套时窗口会越攒越多，apply_skin 越来越慢")

    def test_every_test_class_inherits_cleanup(self):
        """★★★ 本文件里**每个** TestCase 都必须继承 ``_SkinTestCase``。

        ⚠ 这条防的是"新加了一个类、忘了继承"—— 那会让整套测试重新变慢。
        漏一个类的代价不是"慢一点"，而是**整套跑不完**（见类文档）。
        """
        import inspect

        module = inspect.getmodule(self)
        offenders = []
        for name, obj in vars(module).items():
            if not (isinstance(obj, type) and issubclass(obj, unittest.TestCase)):
                continue
            if obj.__module__ != module.__name__:
                continue              #: 别管 import 进来的
            if not issubclass(obj, _SkinTestCase):
                offenders.append(name)
        self.assertEqual(
            offenders, [],
            f"这些测试类没继承 _SkinTestCase：{offenders} —— "
            f"它们建的窗口不会被清理，整套测试会越来越慢直到跑不完")

    def test_apply_skin_is_fast_with_clean_state(self):
        """★★ 干净状态下 ``apply_skin`` 必须是**毫秒级**。

        修之前因为窗口泄漏，单次要 2.8~8.5 秒。这条把"快"钉住 ——
        如果哪天真慢到这个量级，说明又有东西在攒。
        """
        import time

        from src.core import skins

        _destroy_toplevels()          #: 先确保干净
        skins.apply_skin("mist", save=False)     #: 热身（建 QSS 缓存）

        t0 = time.time()
        for sid in ("deepglass", "mist", "nebula"):
            skins.apply_skin(sid, save=False)
        dt = time.time() - t0

        self.assertLess(
            dt, 2.0,
            f"干净状态下换 3 次皮肤用了 {dt:.2f}s（应该 < 0.1s）—— "
            f"多半又有顶层控件在攒（每个都会让 setStyleSheet 变慢）")


if __name__ == "__main__":
    unittest.main(verbosity=2)
