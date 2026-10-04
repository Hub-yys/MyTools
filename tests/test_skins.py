# -*- coding: utf-8 -*-
"""皮肤系统的测试。

用 offscreen 模式建真窗口 —— 皮肤改动会影响 qfluentwidgets 的全局主题，
所以**用独立的 qconfig 文件**，测完恢复原皮肤（别污染用户设置）。
"""

from __future__ import annotations

import os
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import sys

if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class TestSkinRegistry(unittest.TestCase):
    """皮肤注册表本身（不碰窗口）。"""

    def test_skins_have_required_fields(self):
        from src.core import skins

        self.assertGreaterEqual(len(skins.all_skins()), 3,
                                "皮肤太少了 —— 用户要「几款」")
        for s in skins.all_skins():
            for k in ("id", "name", "mode", "primary"):
                self.assertIn(k, s, f"皮肤缺字段 {k}：{s}")
            self.assertIn(s["mode"], ("light", "dark"))
            self.assertTrue(str(s["primary"]).startswith("#"))

    def test_ids_are_unique(self):
        from src.core import skins

        ids = [s["id"] for s in skins.all_skins()]
        self.assertEqual(len(ids), len(set(ids)),
                         f"皮肤 id 重复了：{ids}")

    def test_default_skin_exists(self):
        from src.core import skins

        self.assertIsNotNone(skins.skin_by_id(skins.DEFAULT_SKIN),
                             f"默认皮肤 {skins.DEFAULT_SKIN} 不存在")

    def test_has_at_least_one_dark_skin(self):
        """★ 用户要"几款好看的" —— 至少给一款暗色的（不然"皮肤"就只剩换主色）。"""
        from src.core import skins

        dark = [s for s in skins.all_skins() if s["mode"] == "dark"]
        self.assertGreaterEqual(len(dark), 1,
                                "一款暗色皮肤都没有")

    def test_skin_by_id_unknown_returns_none(self):
        from src.core import skins

        self.assertIsNone(skins.skin_by_id("不存在的皮肤"))


class TestSkinApply(unittest.TestCase):
    """应用皮肤（改全局主题）。"""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        # 每次测前回到默认皮肤，避免互相污染
        from src.core import skins

        skins.apply_skin(skins.DEFAULT_SKIN, save=False)

    def tearDown(self):
        from src.core import skins

        skins.apply_skin(skins.DEFAULT_SKIN, save=False)

    def test_apply_unknown_skin_returns_false(self):
        from src.core import skins

        self.assertFalse(skins.apply_skin("不存在"))

    def test_apply_skin_changes_theme_color(self):
        """★★ 应用皮肤后，**全局主色**变了。

        ⚠ 这里用**浅色**皮肤断言精确值 —— 暗色模式下
        ``themeColor()`` 会被 qfluentwidgets **提亮**（``#d64545`` →
        ``#ff6e6e``），不是原色（那是它的可读性调整）。
        """
        from qfluentwidgets import themeColor

        from src.core import skins

        light = next(s for s in skins.all_skins() if s["mode"] == "light")
        self.assertTrue(skins.apply_skin(light["id"], save=False))
        self.assertEqual(themeColor().name().lower(),
                         light["primary"].lower())

    def test_apply_dark_skin_switches_theme(self):
        """★★ 暗色皮肤会**切到暗色模式**。"""
        from qfluentwidgets import isDarkTheme

        from src.core import skins

        dark = next(s for s in skins.all_skins() if s["mode"] == "dark")
        self.assertTrue(skins.apply_skin(dark["id"], save=False))
        self.assertTrue(isDarkTheme(),
                        f"切到 {dark['name']} 后不是暗色模式")

    def test_apply_light_skin_switches_back(self):
        """★★ 从暗色切回浅色，主题也切回来。"""
        from qfluentwidgets import isDarkTheme

        from src.core import skins

        dark = next(s for s in skins.all_skins() if s["mode"] == "dark")
        light = next(s for s in skins.all_skins() if s["mode"] == "light")
        skins.apply_skin(dark["id"], save=False)
        self.assertTrue(isDarkTheme())
        skins.apply_skin(light["id"], save=False)
        self.assertFalse(isDarkTheme())


class TestSkinPersistence(unittest.TestCase):
    """皮肤选择的持久化（用独立 config 文件，不碰用户的）。"""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

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
        """★★ 应用皮肤会**存下来**（重启还在）。"""
        from qfluentwidgets import qconfig

        from src.core import skins

        skin = skins.all_skins()[-1]
        self.assertTrue(skins.apply_skin(skin["id"], save=True))
        self.assertEqual(skins.current_skin()["id"], skin["id"])

    def test_apply_without_save_does_not_change_current(self):
        """★ ``save=False`` 只是**临时预览**，不改存的选择。"""
        from src.core import skins

        before = skins.current_skin()["id"]
        skin = skins.all_skins()[-1]
        if skin["id"] == before:
            skin = skins.all_skins()[0]
        self.assertTrue(skins.apply_skin(skin["id"], save=False))
        self.assertEqual(skins.current_skin()["id"], before,
                         "save=False 也改了存的选择 —— 那就不是预览了")

    def test_current_skin_falls_back_to_default(self):
        """★ 没存过皮肤时，`current_skin()` 回落到默认。"""
        from qfluentwidgets import qconfig

        from src.core import skins

        #: 把存的那个键**重置回默认值**（qconfig 没有 clear/remove，
        #: 但 ``_skin_item().defaultValue`` 就是默认）
        qconfig.set(skins._skin_item(), skins._skin_item().defaultValue)
        self.assertEqual(skins.current_skin()["id"], skins.DEFAULT_SKIN)


class TestSkinPickerCard(unittest.TestCase):
    """侧栏皮肤卡。"""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from src.core import skins

        skins.apply_skin(skins.DEFAULT_SKIN, save=False)

    def tearDown(self):
        from src.core import skins

        skins.apply_skin(skins.DEFAULT_SKIN, save=False)

    def test_card_has_one_dot_per_skin(self):
        """★ 每个皮肤一个圆点。"""
        from src.core import skins
        from src.gui.skin_picker import build_skin_card

        card = build_skin_card()
        dots = card._dots
        self.assertEqual(len(dots), len(skins.all_skins()))

    def test_current_skin_dot_is_checked(self):
        """★ 当前皮肤那个圆点是**选中**状态。"""
        from src.core import skins
        from src.gui.skin_picker import build_skin_card

        target = skins.all_skins()[-1]
        skins.apply_skin(target["id"], save=False)
        card = build_skin_card()
        checked = [d for d in card._dots if d.isChecked()]
        self.assertEqual(len(checked), 1, "应该有正好一个选中的圆点")
        self.assertEqual(checked[0]._skin["id"], target["id"])

    def test_clicking_dot_applies_skin(self):
        """★★ 点圆点 → **立刻**应用皮肤。

        ⚠⚠ 不能断言 ``themeColor() == skin.primary`` ——
        **暗色模式下 qfluentwidgets 会把主色"提亮"**（实测
        ``#d64545`` → ``#ff6e6e``），这是它给暗色做的可读性调整，
        不是我们设错。

        → 断言两件事：① 存的选择变了；② 主色**真的变了**（不是原来那个）。
        """
        from qfluentwidgets import themeColor

        from src.core import skins
        from src.gui.skin_picker import build_skin_card

        card = build_skin_card()
        before = themeColor().name().lower()
        target = skins.all_skins()[-1]
        dot = next(d for d in card._dots if d._skin["id"] == target["id"])
        dot.chosen.emit(target["id"])

        self.assertEqual(skins.current_skin()["id"], target["id"],
                         "点圆点没改存的选择")
        self.assertNotEqual(themeColor().name().lower(), before,
                            "点圆点后主色没变")

    def test_main_window_has_skin_card(self):
        """★★ 主窗口**侧栏**有皮肤卡（用户："左侧边栏，增加皮肤功能"）。"""
        from src.gui.main_window import MainWindow

        w = MainWindow()
        self.assertIsNotNone(getattr(w, "_skin_card", None),
                             "主窗口没有皮肤卡")


if __name__ == "__main__":
    unittest.main(verbosity=2)
