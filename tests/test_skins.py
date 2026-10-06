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


class TestSkinRegistry(unittest.TestCase):
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


class TestSkinQss(unittest.TestCase):
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


class TestNativeWidgetPalette(unittest.TestCase):
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


class TestNavResizerTransparent(unittest.TestCase):
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

            skins.apply_skin("deepglass", save=True)
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


class TestSkinApply(unittest.TestCase):
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


class TestSkinReallyChangesPixels(unittest.TestCase):
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


class TestSkinPersistence(unittest.TestCase):
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


class TestSkinPage(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
