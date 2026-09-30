"""数据源优先级：**库街区优先，bwiki 只补它没有的**。

    python tests/test_data_priority.py

用户 2026-09-30 看着「资源库更新」的日志问："为什么不是优先从库街区拿？"
—— 他早就说过"这些数据以后优先从库街区拿"，但代码一直是
**bwiki 先拉、库街区只补缺**。

这里钉住三件事：
1. ``fetch_remote`` 里**库街区先拉**；
2. 合并时**库街区的值不被 bwiki 覆盖**（反过来就会退化成旧行为）；
3. 库街区角色名要**归一化**（漂泊者男/女 → 本地那 4 条），
   否则每更新一次就多出 8 个假角色。

不打网络 —— 全用构造的 RemoteSnapshot。
"""

from __future__ import annotations

import inspect
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.core import wuwa_update  # noqa: E402


class TestFetchOrder(unittest.TestCase):
    """★ 拉取顺序：库街区在前。"""

    def test_kurobbs_is_fetched_before_bwiki(self):
        """源码里 ``_fetch_kurobbs`` 要出现在 ``_fetch_bwiki_sets`` 之前。

        ⚠ 这条正是用户看到的那几行日志顺序。顺序本身不影响"并集"结果，
        但它代表了**谁是主源** —— 而且日志顺序就是用户判断的依据。
        """
        source = inspect.getsource(wuwa_update.fetch_remote)
        kuro_at = source.find("_fetch_kurobbs(")
        bwiki_at = source.find("_fetch_bwiki_sets(")
        self.assertGreater(kuro_at, -1, "没找到 _fetch_kurobbs")
        self.assertGreater(bwiki_at, -1, "没找到 _fetch_bwiki_sets")
        self.assertLess(kuro_at, bwiki_at,
                        "bwiki 又跑到库街区前面了 —— 数据源优先级反了")

    def test_characters_come_from_both_sources(self):
        """角色名单：库街区是主源（``characters``），bwiki 是兜底。

        两个字段都要在，合并时才能"主源先写、兜底补空"。
        """
        source = inspect.getsource(wuwa_update.fetch_remote)
        self.assertIn("_fetch_kurobbs_characters", source)
        self.assertIn("_fetch_bwiki_characters", source)


class TestCharacterMergePriority(unittest.TestCase):
    """★ 合并时库街区的值不能被 bwiki 盖掉。"""

    def _snapshot(self, kuro: dict, bwiki: dict):
        snapshot = wuwa_update.RemoteSnapshot()
        snapshot.characters = kuro
        snapshot.characters_bwiki = bwiki
        return snapshot

    def test_kurobbs_wins_on_conflict(self):
        """★ 同一个角色两边都有值时，**以库街区为准**。

        这正是改之前的毛病：bwiki 的稀有度是 0（它没有结构化字段），
        先写进去之后就把位置占住了，库街区真正的「五星」反而进不来。
        """
        local = {"characters": []}
        snapshot = self._snapshot(
            kuro={"某角色": {"rarity": 5, "element": "导电", "weapon": "迅刀"}},
            bwiki={"某角色": {"rarity": 0, "element": "", "weapon": ""}},
        )
        wuwa_update._merge_characters_data(local, snapshot)
        entry = local["characters"][0]
        self.assertEqual(entry["rarity"], 5, "库街区的稀有度被 bwiki 盖掉了")
        self.assertEqual(entry["element"], "导电")

    def test_bwiki_still_fills_gaps(self):
        """bwiki 仍要能**补库街区没有的**（不能因为改优先级就不管它了）。"""
        local = {"characters": []}
        snapshot = self._snapshot(
            kuro={"甲": {"rarity": 5, "element": "导电", "weapon": "迅刀"}},
            bwiki={"乙": {"rarity": 4, "element": "热熔", "weapon": "长刃"}},
        )
        wuwa_update._merge_characters_data(local, snapshot)
        names = {c["name"] for c in local["characters"]}
        self.assertEqual(names, {"甲", "乙"}, "bwiki 独有的角色没进来")

    def test_bwiki_fills_missing_field_of_kuro_character(self):
        """库街区缺的字段，bwiki 补上（互补，不是二选一）。"""
        local = {"characters": []}
        snapshot = self._snapshot(
            kuro={"某角色": {"rarity": 5, "element": "", "weapon": "迅刀"}},
            bwiki={"某角色": {"rarity": 0, "element": "湮灭", "weapon": ""}},
        )
        wuwa_update._merge_characters_data(local, snapshot)
        entry = local["characters"][0]
        self.assertEqual(entry["element"], "湮灭", "bwiki 的补空能力没了")
        self.assertEqual(entry["rarity"], 5)

    def test_existing_local_rarity_not_zeroed(self):
        """本地已有的星级**绝不能**被 0 覆盖（老数据的保命规则）。"""
        local = {"characters": [{"name": "甲", "rarity": 5,
                                 "element": "导电", "weapon": "迅刀"}]}
        snapshot = self._snapshot(
            kuro={"甲": {"rarity": 0, "element": "", "weapon": ""}},
            bwiki={"甲": {"rarity": 0, "element": "", "weapon": ""}},
        )
        wuwa_update._merge_characters_data(local, snapshot)
        self.assertEqual(local["characters"][0]["rarity"], 5)


class TestStarParsing(unittest.TestCase):
    """★ 稀有度解析：库街区写的是「**五星**」不是「5星」。"""

    def test_chinese_numerals(self):
        for text, expect in (("五星", 5), ("四星", 4), ("三星", 3),
                             ("一星", 1), ("二星", 2)):
            with self.subTest(text=text):
                self.assertEqual(wuwa_update._parse_stars(text), expect)

    def test_arabic_numerals(self):
        for text, expect in (("5星", 5), ("4星", 4), ("5", 5)):
            with self.subTest(text=text):
                self.assertEqual(wuwa_update._parse_stars(text), expect)

    def test_junk_is_zero(self):
        for text in ("", "  ", "不知道", None):
            with self.subTest(text=text):
                self.assertEqual(wuwa_update._parse_stars(text), 0)

    def test_real_tag_value_parses(self):
        """实测值：库街区 tagTree 里就是这个字符串。

        我第一版直接 ``replace("星","")`` → 剩下「五」→ ``int()`` 失败 → 0，
        结果 64 个角色"有稀有度的"算出来是 **0 个**。
        """
        self.assertEqual(wuwa_update._parse_stars("五星"), 5)


class TestCharacterNameNormalization(unittest.TestCase):
    """★ 漂泊者：库街区按男/女拆成 8 条，本地一直用 4 条属性版。"""

    def test_traveller_variants_collapse(self):
        """男/女两种都要归一到同一个本地名字。"""
        pairs = [
            ("漂泊者-男-导电", "漂泊者·导电"),
            ("漂泊者-女-导电", "漂泊者·导电"),
            ("漂泊者-男-湮灭", "漂泊者·湮灭"),
            ("漂泊者-女-气动", "漂泊者·气动"),
        ]
        for raw, expect in pairs:
            with self.subTest(raw=raw):
                self.assertEqual(
                    wuwa_update._normalize_character_name(raw), expect)

    def test_other_names_untouched(self):
        for name in ("心", "锁暝", "绯雪", "维里奈"):
            with self.subTest(name=name):
                self.assertEqual(
                    wuwa_update._normalize_character_name(name), name)

    def test_no_duplicate_travellers_after_merge(self):
        """★ 端到端：归一化后不该多出假角色。

        不归一化的话，每点一次「获取最新数据」就多 8 条
        （而原有的 4 条又删不掉，因为合并是"只增不减"）。
        """
        local = {"characters": [
            {"name": "漂泊者·导电", "rarity": 5, "element": "导电",
             "weapon": "迅刀"}]}
        snapshot = wuwa_update.RemoteSnapshot()
        snapshot.characters = {
            "漂泊者·导电": {"rarity": 5, "element": "导电", "weapon": "迅刀"},
        }
        snapshot.characters_bwiki = {}
        wuwa_update._merge_characters_data(local, snapshot)
        self.assertEqual(len(local["characters"]), 1,
                         "漂泊者被拆成了多条")

    def test_info_score_picks_complete_entry(self):
        """归一化撞车时保留信息更全的那条。"""
        fuller = {"rarity": 5, "element": "导电", "weapon": "迅刀"}
        emptier = {"rarity": 0, "element": "", "weapon": ""}
        self.assertGreater(wuwa_update._info_score(fuller),
                           wuwa_update._info_score(emptier))


class TestEchoPoolPriority(unittest.TestCase):
    """声骸掉落池：库街区先并（新的套装声骸先到位）。"""

    def test_kurobbs_pools_merged_first(self):
        source = inspect.getsource(wuwa_update._merge_sets_data)
        kuro_at = source.find("snapshot.echoes_kuro")
        bwiki_at = source.find("snapshot.echoes_bwiki")
        self.assertGreater(kuro_at, -1)
        self.assertGreater(bwiki_at, -1)
        self.assertLess(kuro_at, bwiki_at,
                        "bwiki 掉落池又跑到库街区前面了")


if __name__ == "__main__":
    unittest.main(verbosity=2)
