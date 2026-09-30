"""配置页的搜索框（用户 2026-09-30 要求）。

    python tests/test_config_search.py

"加上搜索，和前面下拉列表搜索一样的" —— 所以匹配规则必须**复用**
``gui/pickers.py`` 的那一份（中文子串 + 拼音全拼/首字母），
不能另写一套。这里既测规则本身，也测"全项目只有一份实现"。
"""

from __future__ import annotations

import os
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class TestKeywordMatching(unittest.TestCase):
    """``matches_keyword`` —— 下拉框和搜索框**共用**的匹配规则。"""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def _match(self, name: str, keyword: str) -> bool:
        from src.gui.pickers import matches_keyword, pinyin_keys

        return matches_keyword(pinyin_keys(name), name, keyword)

    def test_empty_keyword_matches_everything(self):
        self.assertTrue(self._match("绯雪", ""))
        self.assertTrue(self._match("绯雪", "   "))

    def test_chinese_substring(self):
        self.assertTrue(self._match("绯雪", "雪"))
        self.assertTrue(self._match("绯雪", "绯雪"))

    def test_pinyin_full(self):
        self.assertTrue(self._match("绯雪", "feixue"))

    def test_pinyin_initials(self):
        """首字母也要认（下拉框一直是这个行为）。"""
        self.assertTrue(self._match("爱弥斯", "ams"))
        self.assertTrue(self._match("赞妮", "zn"))

    def test_pinyin_case_insensitive(self):
        self.assertTrue(self._match("绯雪", "FeiXue"))

    def test_no_match(self):
        self.assertFalse(self._match("绯雪", "zzz"))
        self.assertFalse(self._match("绯雪", "锁暝"))

    def test_dropdown_uses_the_same_rule(self):
        """★ 下拉框必须**调用**这份规则，不能自己再写一套。

        用户明确要求"和前面下拉列表搜索一样的" —— 两边逻辑一旦分叉，
        就会出现"下拉框搜得到、配置页搜不到"（或反过来），很难查。
        """
        import inspect

        from src.gui.pickers import FilterComboBox

        source = inspect.getsource(FilterComboBox._matches)
        self.assertIn("matches_keyword", source,
                      "下拉框没复用 matches_keyword —— 两边规则会分叉")


class TestConfigSearchBox(unittest.TestCase):
    """配置页上的搜索框本身。"""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def _page(self):
        from PySide6.QtWidgets import QWidget

        from src.gui.config_interface import ConfigInterface

        self._holder = QWidget()
        self._holder.resize(1200, 900)
        page = ConfigInterface()
        page.setParent(self._holder)
        page.resize(1200, 900)
        self._holder.show()
        self.app.processEvents()
        return page

    def _counts(self, page) -> tuple[int, int]:
        from src.gui.config_interface import LoadoutRow
        from src.gui.echo_profile_ui import EchoProfileRow

        return (len(page.findChildren(EchoProfileRow)),
                len(page.findChildren(LoadoutRow)))

    def test_has_search_box(self):
        page = self._page()
        self.assertTrue(hasattr(page, "search_edit"), "配置页没有搜索框")

    def test_filters_rows(self):
        """★ 搜索要真的把不匹配的行从列表里去掉。"""
        page = self._page()
        before = self._counts(page)
        if sum(before) == 0:
            self.skipTest("没有配置数据可搜")

        page.search_edit.setText("zzz不可能匹配")
        self.app.processEvents()
        self.assertEqual(self._counts(page), (0, 0),
                         "搜一个不可能的词，行却没被过滤掉")

        page.search_edit.setText("")
        self.app.processEvents()
        self.assertEqual(self._counts(page), before, "清空搜索后没恢复")

    def test_matches_by_pinyin(self):
        """★ 拼音也能搜到（用户要的是"和下拉列表一样"）。"""
        page = self._page()
        before = self._counts(page)
        if sum(before) == 0:
            self.skipTest("没有配置数据可搜")

        # 拿第一条筛选配置的角色名，取它的拼音首字母来搜
        from src.core.loadout import Loadout
        from src.gui.config_interface import LoadoutRow
        from src.gui.pickers import pinyin_keys

        rows = page.findChildren(LoadoutRow)
        if not rows:
            self.skipTest("没有筛选配置可测")
        name = rows[0].loadout.character
        initial = pinyin_keys(name)[1]
        if not initial:
            self.skipTest("没装 pypinyin，拼音搜索不可用")

        page.search_edit.setText(initial)
        self.app.processEvents()
        heavy, light = self._counts(page)
        self.assertGreater(heavy + light, 0,
                           f"用「{name}」的首字母「{initial}」搜不到任何东西")

    def test_subtitle_shows_hit_over_total(self):
        """★ 搜索时副标题要带**总数** —— 否则用户以为配置被删了。"""
        page = self._page()
        if sum(self._counts(page)) == 0:
            self.skipTest("没有配置数据")

        page.search_edit.setText("zzz不可能匹配")
        self.app.processEvents()
        text = page.subtitle.text()
        self.assertIn("命中", text)
        self.assertIn("共", text)

    def test_empty_hint_mentions_keyword(self):
        """搜不到时的提示要和"一条都没建"区分开（原因完全不同）。"""
        page = self._page()
        if sum(self._counts(page)) == 0:
            self.skipTest("没有配置数据")

        page.search_edit.setText("zzz不可能匹配")
        self.app.processEvents()

        from qfluentwidgets import CaptionLabel

        texts = " ".join(lb.text() for lb in page.findChildren(CaptionLabel))
        self.assertIn("zzz不可能匹配", texts,
                      "搜不到时没提示搜索词 —— 用户不知道是搜索造成的")


if __name__ == "__main__":
    unittest.main(verbosity=2)
