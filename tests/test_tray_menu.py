# -*- coding: utf-8 -*-
"""托盘菜单配色 —— 单测。

## 为什么要有这个文件（用户 2026-10-09："托盘退出怎么都看不见"）

托盘右键菜单是 ``QMenu``（**裸 Qt 控件**），它的文字色走 ``ButtonText``
调色板角色。皮肤只把调色板设成"深色皮肤配浅字" —— 看着没错，但**实测
渲染出来是深字压深底**：

    深空玻璃（用户在用的）: 背景 rgb(11,16,38)、最亮像素 rgb(1,2,4)
                            → 反差 **19/255**，"退出"两个字完全糊在底里
    晨雾玻璃（浅色）:       反差 223/255 → 正常

所以那边现在**显式钉死**菜单配色（见 ``tray.style_menu``）。
本文件钉住两件事：

1. 六款皮肤下，菜单的底色和文字色**必须真的不一样**（按亮度算，不查字符串）；
2. 换肤之后菜单跟着变（走 ``aboutToShow`` 重刷）。

⚠ 断言的是**渲染出来的像素**，不是样式表字符串 —— 那个坑本仓刚踩过
（``opacity`` 写在 QSS 里根本不生效，但字符串查得出来，测试假绿了很久）。
"""

from __future__ import annotations

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _lum(color) -> float:
    return (0.299 * color.red() + 0.587 * color.green()
            + 0.114 * color.blue()) / 255


class TestTrayMenuColors(unittest.TestCase):
    """★ 托盘菜单在**每款皮肤**下都要看得见。"""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def _menu(self):
        from PySide6.QtGui import QAction
        from PySide6.QtWidgets import QMenu

        menu = QMenu()
        menu.addAction(QAction("显示 鸣潮工具箱", menu))
        menu.addSeparator()
        menu.addAction(QAction("退出", menu))
        return menu

    def _skin_ids(self):
        from src.core import skins

        return [s["id"] for s in skins.all_skins()]

    def test_menu_colors_are_not_pinned_constants(self):
        """★ 配色跟着皮肤走（不是写死一套）。"""
        from src.core import skins
        from src.gui import tray

        seen = set()
        for sid in self._skin_ids():
            skins.apply_skin(sid, save=False)
            seen.add(tray._menu_palette())
        self.assertGreater(len(seen), 1,
                           f"所有皮肤算出来同一套菜单色（{seen}）—— "
                           f"说明没跟皮肤走")

    def test_text_contrasts_with_background(self):
        """★★ 每款皮肤下，菜单文字和底色必须有足够反差。

        ⚠ 这条是**回归护栏**：修之前深色皮肤是 19/255（几乎纯色）。
        阈值取 0.35 —— 正常皮肤是 0.8 上下，坏掉是 0.07。
        """
        from PySide6.QtGui import QColor

        from src.core import skins
        from src.gui import tray

        for sid in self._skin_ids():
            skins.apply_skin(sid, save=False)
            bg, text, _hi = tray._menu_palette()
            with self.subTest(skin=sid):
                diff = abs(_lum(QColor(bg)) - _lum(QColor(text)))
                self.assertGreater(
                    diff, 0.35,
                    f"{sid}：菜单底 {bg} 和文字 {text} 反差只有 {diff:.2f} "
                    f"—— 「退出」会看不见（修之前就是这个毛病）")

    def test_style_menu_applies_to_both_palette_and_qss(self):
        """★★ 调色板和样式表**都要设**（故意的冗余，见 ``tray.style_menu``）。

        ⚠ 实测**任一个单独就够**（只设调色板 206 / 只设样式表 203，
        都不设才是 19）。所以这条不是为了"少一个就坏"，
        而是钉住"两个都在"这个**有意的冗余设计** ——
        哪天有人觉得其中一个多余顺手删掉，这条会拦住他，
        让他先去看 ``style_menu`` 里那段实测数据。
        """
        from PySide6.QtGui import QPalette

        from src.core import skins
        from src.gui import tray

        skins.apply_skin("deepglass", save=False)
        menu = self._menu()
        tray.style_menu(menu)

        bg, text, _hi = tray._menu_palette()

        #: ① 样式表里两种色都要出现（负责底/分隔线/圆角）
        sheet = menu.styleSheet()
        self.assertIn(bg, sheet, "样式表里没有菜单底色")
        self.assertIn(text, sheet, "样式表里没有菜单文字色")

        #: ② 调色板也要跟上（兜底那层）
        pal = menu.palette()
        self.assertEqual(pal.color(QPalette.ColorRole.ButtonText).name().lower(),
                         text.lower(), "调色板 ButtonText 没设对")
        self.assertEqual(pal.color(QPalette.ColorRole.Window).name().lower(),
                         bg.lower(), "调色板 Window 没设对")

    def test_rendered_menu_is_readable(self):
        """★★★ 真渲染出来量像素 —— 最亮和最暗必须拉开。

        ## ⚠⚠ 这条**只在 windows 平台插件下才有意义**（实测）

        这个 bug 是 **Windows 平台插件**特有的：同一个"菜单完全不设配色"
        的变异，两个平台量出来差得天壤之别::

            offscreen:  反差 224  ← 看起来完全正常（**假的**）
            windows:    反差 19   ← 用户实际看到的：深字压深底

        所以：
        * 在 Windows 上跑（``QT_QPA_PLATFORM=windows``）→ 这条是**真护栏**；
        * 在默认的 offscreen 下 → 它**抓不到**这个 bug，只是"渲染没崩"的冒烟。

        ⚠ 我不想让它假装自己抓得住 —— 所以这里**显式说明**，
        并把"配色算对了没有"交给 ``test_text_contrasts_with_background``
        （那条不依赖平台，两边都能抓）。
        """
        from src.core import skins
        from src.gui import tray

        for sid in self._skin_ids():
            skins.apply_skin(sid, save=False)
            menu = self._menu()
            tray.style_menu(menu)
            menu.show()
            self.app.processEvents()
            self.app.processEvents()

            img = menu.grab().toImage()
            vals = []
            for y in range(img.height()):
                for x in range(img.width()):
                    vals.append(_lum(img.pixelColor(x, y)))
            menu.hide()
            span = max(vals) - min(vals)
            with self.subTest(skin=sid):
                self.assertGreater(
                    span, 100 / 255,
                    f"{sid}：渲染出来最亮 {max(vals):.2f} / 最暗 {min(vals):.2f}"
                    f"（差 {span:.2f}）—— 文字糊在底色里了")

    def test_alpha_helper_uses_rgba_not_hex(self):
        """★★ 半透明必须走 ``rgba()`` —— 8 位十六进制在 QSS 里是 ``#AARRGGBB``。

        ⚠ 我第一版写 ``{hi}40``（想加 25% 透明），Qt 解析成 alpha=0x4A、
        R=0x9E、G=0xFF、B=0x40 → 菜单边框变成**一条绿线**
        （实测像素 rgb(63,95,54)）。
        """
        from src.gui import tray

        out = tray._alpha("#4a9eff", 0.45)
        self.assertTrue(out.startswith("rgba("), f"没走 rgba()：{out}")
        self.assertNotRegex(out, r"#[0-9a-fA-F]{8}",
                            "出现了 8 位十六进制（Qt 会当成 #AARRGGBB）")

    def test_border_is_not_green(self):
        """★★ 边框不能是绿的（上面那个坑的**像素级**护栏）。"""
        from src.core import skins
        from src.gui import tray

        skins.apply_skin("deepglass", save=False)
        menu = self._menu()
        tray.style_menu(menu)
        menu.show()
        self.app.processEvents()
        self.app.processEvents()
        img = menu.grab().toImage()
        menu.hide()

        #: 沿上边缘扫，找最"彩色"的那个像素 —— 蓝底菜单不该出现绿占优
        worst = 0
        for x in range(img.width()):
            for y in (0, 1, 2):
                c = img.pixelColor(x, y)
                worst = max(worst, c.green() - max(c.red(), c.blue()))
        self.assertLess(worst, 30,
                        f"菜单边框偏绿（绿分量比红蓝高 {worst}）—— "
                        f"多半又是 8 位十六进制被当成 #AARRGGBB")


class TestTrayMenuFollowsSkinChange(unittest.TestCase):
    """★ 换肤之后菜单也要换色（不能停在建菜单那一刻的颜色）。

    ⚠ 这些测试走 :func:`tray.build_menu`，**不依赖系统托盘** ——
    托盘在无头/远程会话里拿不到（``make_tray`` 返回 None），
    要是只能经 ``make_tray`` 测，这两条在默认 offscreen 下就**永远 skip**，
    等于没有护栏（我第一版就是这样）。
    """

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def _menu(self):
        from src.gui import tray

        return tray.build_menu(None, on_show=lambda: None, on_quit=lambda: None)

    def test_build_menu_styles_immediately(self):
        """★★ 菜单建出来就得带上当前皮肤的配色（不是等谁手动调）。"""
        from src.core import skins
        from src.gui import tray

        skins.apply_skin("deepglass", save=False)
        menu = self._menu()
        bg, text, _hi = tray._menu_palette()
        sheet = menu.styleSheet()
        self.assertTrue(sheet, "build_menu 没给菜单设样式")
        self.assertIn(bg, sheet, "菜单底色不是当前皮肤的")
        self.assertIn(text, sheet, "菜单文字色不是当前皮肤的")

    def test_about_to_show_restyles(self):
        """★★★ 每次弹出前要重刷配色 —— 换肤后菜单不能留着旧颜色。

        ⚠⚠ 这条**故意不自己调** ``style_menu`` —— 只 ``emit()`` 信号。
        护栏验证时我第一版手动调了一次 style_menu，结果把
        ``aboutToShow.connect`` 删掉测试**照样通过**（假绿）。
        现在只依赖"信号接上了没有"。
        """
        from src.core import skins
        from src.gui import tray

        skins.apply_skin("mist", save=False)
        menu = self._menu()

        #: 弹出一次 → 应该是 mist 的配色
        menu.aboutToShow.emit()
        mist_sheet = menu.styleSheet()

        #: 换皮肤后再弹出 → 必须变成 deepglass 的配色
        skins.apply_skin("deepglass", save=False)
        menu.aboutToShow.emit()
        dark_sheet = menu.styleSheet()

        self.assertNotEqual(mist_sheet, dark_sheet,
                            "换肤后菜单配色没变 —— aboutToShow 没接上")
        self.assertIn(tray._menu_palette()[0], dark_sheet,
                      "重刷后的配色不是当前皮肤的")

    def test_menu_has_show_and_quit(self):
        """★ 菜单里得有「显示」和「退出」两项（用户找的就是退出）。"""
        menu = self._menu()
        texts = [a.text() for a in menu.actions()]
        self.assertTrue(any("退出" in t for t in texts),
                        f"菜单里没有「退出」（{texts}）")
        self.assertTrue(any(t.startswith("显示") for t in texts),
                        f"菜单里没有「显示」（{texts}）")

    def test_make_tray_uses_build_menu(self):
        """★ ``make_tray`` 必须走 :func:`tray.build_menu`（别又各写一份）。"""
        import inspect

        from src.gui import tray

        src = inspect.getsource(tray.make_tray)
        self.assertIn("build_menu(", src,
                      "make_tray 没走 build_menu —— 配色/换肤那两条护栏会失效")


if __name__ == "__main__":
    unittest.main()
