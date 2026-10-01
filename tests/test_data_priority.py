"""数据源：**只从库街区拿**（用户 2026-10-01 明确要求）。

    python tests/test_data_priority.py

演变过程（三轮，用户每次都比上一次更明确）：

1. 2026-09-30 用户看着日志顺序问："为什么不是优先从库街区拿？"
   → 改成库街区主源、bwiki 兜底。
2. 同一天用户给页面链接纠正："库街区也有套装效果"
   → 确认 ``getEntryDetail`` 详情接口能拿到文字。
3. **2026-10-01 用户要求："除去一切其他来源数据，只从库街区拿"**
   → 把 bwiki 整个删掉。

最后一轮的依据是实测：**bwiki 没有独占数据**（库街区 37 套 / 205 声骸 /
60 角色；bwiki 34 / 255 / 58，全是子集），而两个源的**文字措辞不同**
（bwiki 的套装效果多一句"延奏技能伤害提升60%"之类），
留着只会导致"效果更新 30 套"那种假报。

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


class TestBwikiIsGone(unittest.TestCase):
    """★ bwiki 的代码**不该再存在**（用户要求"除去一切其他来源数据"）。"""

    def test_no_bwiki_constants(self):
        for name in ("BWIKI_API", "SETS_PAGE", "ECHO_ASK", "CHARACTER_ASK"):
            with self.subTest(name=name):
                self.assertFalse(hasattr(wuwa_update, name),
                                 f"{name} 还在 —— bwiki 没删干净")

    def test_no_bwiki_functions(self):
        for name in ("_bwiki", "_fetch_bwiki_sets", "_fetch_bwiki_echo_index",
                     "_fetch_bwiki_characters", "_fetch_skill"):
            with self.subTest(name=name):
                self.assertFalse(hasattr(wuwa_update, name),
                                 f"{name} 还在 —— bwiki 没删干净")

    def test_snapshot_has_no_bwiki_fields(self):
        """快照上也不该留 bwiki 的入口字段（留着就会被重新用起来）。"""
        snapshot = wuwa_update.RemoteSnapshot()
        for field_name in ("sets", "echoes_bwiki", "characters_bwiki"):
            with self.subTest(field=field_name):
                self.assertFalse(hasattr(snapshot, field_name),
                                 f"RemoteSnapshot.{field_name} 还留着")

    def test_fetch_remote_does_not_call_bwiki(self):
        """``fetch_remote`` 里不该**调用**任何 bwiki 的东西。

        ⚠ 只查代码、不查注释/docstring —— 文档里说明"为什么删掉 bwiki"
        是应该留着的（那是决策记录）。
        """
        import ast
        import textwrap

        source = textwrap.dedent(inspect.getsource(wuwa_update.fetch_remote))
        tree = ast.parse(source)
        called = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertFalse(
            [name for name in called if "bwiki" in name.lower()],
            f"fetch_remote 还在调 bwiki 的东西：{sorted(called)}")


class TestFetchUsesKurobbs(unittest.TestCase):
    """拉取要走库街区的那几个接口。"""

    def test_fetch_remote_pulls_all_kurobbs_parts(self):
        source = inspect.getsource(wuwa_update.fetch_remote)
        for name in ("_fetch_kurobbs", "_fetch_kurobbs_characters",
                     "_fetch_kurobbs_set_effects", "_fetch_kurobbs_echo_skills"):
            with self.subTest(name=name):
                self.assertIn(name, source)

    def test_catalogue_ids_are_the_kurobbs_ones(self):
        source = inspect.getsource(wuwa_update)
        for cid in ("1105", "1106", "1107", "1219"):
            with self.subTest(cid=cid):
                self.assertIn(f'"{cid}"', source,
                              f"catalogueId {cid} 没在用了")


class TestCharacterMerge(unittest.TestCase):
    """角色合并（只有库街区一路，规则不变）。"""

    def _snapshot(self, characters: dict):
        snapshot = wuwa_update.RemoteSnapshot()
        snapshot.characters = characters
        return snapshot

    def test_kurobbs_values_written(self):
        local = {"characters": []}
        wuwa_update._merge_characters_data(
            local, self._snapshot({"绯雪": {"rarity": 5, "element": "冷凝",
                                          "weapon": "迅刀"}}))
        entry = local["characters"][0]
        self.assertEqual(entry["rarity"], 5)
        self.assertEqual(entry["element"], "冷凝")

    def test_new_character_appended(self):
        local = {"characters": [{"name": "旧角色", "rarity": 5}]}
        wuwa_update._merge_characters_data(
            local, self._snapshot({"新角色": {"rarity": 4}}))
        names = {c["name"] for c in local["characters"]}
        self.assertIn("新角色", names)
        self.assertIn("旧角色", names, "已有角色不能被删（只增不减）")

    def test_missing_field_is_filled(self):
        """远端有值就补上缺的字段。"""
        local = {"characters": [{"name": "甲", "rarity": 5,
                                 "element": "", "weapon": "迅刀"}]}
        wuwa_update._merge_characters_data(
            local, self._snapshot({"甲": {"rarity": 5, "element": "湮灭",
                                         "weapon": ""}}))
        self.assertEqual(local["characters"][0]["element"], "湮灭")

    def test_existing_rarity_not_zeroed(self):
        """★ 本地已有的星级**绝不能**被 0 覆盖。"""
        local = {"characters": [{"name": "甲", "rarity": 5}]}
        wuwa_update._merge_characters_data(
            local, self._snapshot({"甲": {"rarity": 0, "element": "",
                                         "weapon": ""}}))
        self.assertEqual(local["characters"][0]["rarity"], 5)

    def test_empty_element_does_not_wipe(self):
        """远端空串不能盖掉本地已有的值。"""
        local = {"characters": [{"name": "甲", "element": "导电"}]}
        wuwa_update._merge_characters_data(
            local, self._snapshot({"甲": {"element": ""}}))
        self.assertEqual(local["characters"][0]["element"], "导电")


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
        """★ 端到端：归一化后不该多出假角色。"""
        local = {"characters": [
            {"name": "漂泊者·导电", "rarity": 5, "element": "导电",
             "weapon": "迅刀"}]}
        snapshot = wuwa_update.RemoteSnapshot()
        snapshot.characters = {
            "漂泊者·导电": {"rarity": 5, "element": "导电", "weapon": "迅刀"}}
        wuwa_update._merge_characters_data(local, snapshot)
        self.assertEqual(len(local["characters"]), 1, "漂泊者被拆成了多条")

    def test_info_score_picks_complete_entry(self):
        fuller = {"rarity": 5, "element": "导电", "weapon": "迅刀"}
        emptier = {"rarity": 0, "element": "", "weapon": ""}
        self.assertGreater(wuwa_update._info_score(fuller),
                           wuwa_update._info_score(emptier))


class TestKurobbsEntryDetail(unittest.TestCase):
    """★ 套装效果 / 声骸技能来自库街区**详情接口**。"""

    def test_detail_url_constant(self):
        self.assertIn("getEntryDetail", wuwa_update.KUROBBS_ENTRY_DETAIL)

    def test_entry_id_from_linkId(self):
        """声骸（1107）用 ``content.linkId``。"""
        record = {"content": {"linkId": "1553877397214363648"}}
        self.assertEqual(wuwa_update._entry_id_from_record(record),
                         "1553877397214363648")

    def test_entry_id_from_linkUrl(self):
        """★ 套装（1219）**没有 linkId**，只有 ``linkUrl``。"""
        record = {"content": {
            "linkUrl": "https://wiki.kurobbs.com/mc/item/1553889998205132800"}}
        self.assertEqual(wuwa_update._entry_id_from_record(record),
                         "1553889998205132800")

    def test_entry_id_missing_returns_empty(self):
        self.assertEqual(wuwa_update._entry_id_from_record({}), "")
        self.assertEqual(wuwa_update._entry_id_from_record({"content": {}}), "")

    def test_html_table_cells(self):
        html = ("<table><tr><td>茜染怀想之花</td></tr>"
                "<tr><td>(2件套)</td></tr>"
                "<tr><td>治疗效果提升10%。</td></tr></table>")
        lines = wuwa_update._html_table_cells(html)
        self.assertIn("(2件套)", lines)
        self.assertIn("治疗效果提升10%。", lines)

    def test_html_table_cells_strips_tags(self):
        html = "<p><strong>加粗</strong>&nbsp;文本<br/>第二行</p>"
        lines = wuwa_update._html_table_cells(html)
        self.assertTrue(lines)
        self.assertNotIn("<", "".join(lines))
        self.assertNotIn("&nbsp;", "".join(lines))

    def test_parse_set_effects(self):
        lines = ["茜染怀想之花", "(2件套)", "治疗效果提升10%。",
                 "茜染怀想之花", "(5件套)", "为队伍中角色提供治疗时…"]
        effects = wuwa_update._parse_set_effects(lines)
        self.assertEqual([e["pieces"] for e in effects], [2, 5])
        self.assertEqual(effects[0]["text"], "治疗效果提升10%。")

    def test_parse_set_effects_without_name_line(self):
        effects = wuwa_update._parse_set_effects(["(2件套)", "攻击提升10%。"])
        self.assertEqual(len(effects), 1)
        self.assertEqual(effects[0]["pieces"], 2)

    def test_parse_set_effects_ignores_junk(self):
        self.assertEqual(wuwa_update._parse_set_effects([]), [])
        self.assertEqual(wuwa_update._parse_set_effects(["随便一行"]), [])

    def test_parse_echo_skill_takes_five_star_only(self):
        """★ 只要 **5★** 那一段（库街区把 2~5★ 各写一遍）。"""
        lines = ["5★", "技能描述", "五星的技能文本。", "冷却时间：8秒",
                 "4★", "技能描述", "四星的技能文本。", "冷却时间：9秒"]
        info = wuwa_update._parse_echo_skill(lines)
        self.assertEqual(info["skill"], "五星的技能文本。")
        self.assertEqual(info["cooldown"], "8秒")
        self.assertNotIn("四星", info["skill"])

    def test_parse_echo_skill_empty(self):
        info = wuwa_update._parse_echo_skill([])
        self.assertEqual(info["skill"], "")
        self.assertEqual(info["cooldown"], "")

    def test_component_texts_picks_right_module(self):
        """要按「模块名 + 组件名」双层定位 —— 只用组件名会串。"""
        detail = {"content": {"modules": [
            {"title": "基本信息",
             "components": [{"title": "合鸣效果",
                             "content": "<td>甲效果</td>"}]},
            {"title": "声骸技能",
             "components": [{"title": "声骸技能",
                             "content": "<td>乙技能</td>"}]},
        ]}}
        self.assertEqual(
            wuwa_update._kuro_component_texts(detail, "基础信息", "合鸣效果"),
            ["甲效果"], "模块名对不上时要能按组件名兜底找到")
        self.assertEqual(
            wuwa_update._kuro_component_texts(detail, "声骸技能", "声骸技能"),
            ["乙技能"])


class TestEffectsMerge(unittest.TestCase):
    """套装 / 效果的合并（库街区一路）。"""

    def test_kurobbs_effect_overwrites_local(self):
        """★ 效果要能**更新**已有的（数值会随版本调整）。"""
        local = {"sets": [{"name": "丙", "effects": [
            {"pieces": 2, "text": "旧的"}]}]}
        snapshot = wuwa_update.RemoteSnapshot()
        snapshot.set_effects = {"丙": [{"pieces": 2, "text": "新的"}]}
        wuwa_update._merge_sets_data(local, snapshot)
        self.assertEqual(local["sets"][0]["effects"][0]["text"], "新的")

    def test_new_set_appended(self):
        local = {"sets": []}
        snapshot = wuwa_update.RemoteSnapshot()
        snapshot.set_effects = {"新套": [{"pieces": 2, "text": "效果"}]}
        wuwa_update._merge_sets_data(local, snapshot)
        self.assertEqual(local["sets"][0]["name"], "新套")

    def test_set_without_effects_still_created(self):
        """只有名单、还没详情的套装也要建出来 —— 否则它带的声骸会整批丢掉。"""
        local = {"sets": []}
        snapshot = wuwa_update.RemoteSnapshot()
        snapshot.echoes_kuro = {"只有名单": {4: ["某声骸"]}}
        wuwa_update._merge_sets_data(local, snapshot)
        self.assertEqual(local["sets"][0]["name"], "只有名单")


if __name__ == "__main__":
    unittest.main(verbosity=2)
