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
import json
import pathlib
import sys
import unittest
import unittest.mock

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


class TestKurobbsEntryDetail(unittest.TestCase):
    """★ 套装效果 / 声骸技能也来自库街区（详情接口）。

    我原先断言"这两项**只有 bwiki 有**" —— 用户给了页面链接纠正：
    "库街区也有套装效果"。根因是被 ``getPage`` 的**空 textList 模板**
    骗了：列表接口只给骨架，**文字在 getEntryDetail 详情里**。
    """

    def test_detail_url_constant(self):
        self.assertIn("getEntryDetail", wuwa_update.KUROBBS_ENTRY_DETAIL)

    def test_entry_id_from_linkId(self):
        """声骸（1107）用 ``content.linkId``。"""
        record = {"content": {"linkId": "1553877397214363648"}}
        self.assertEqual(wuwa_update._entry_id_from_record(record),
                         "1553877397214363648")

    def test_entry_id_from_linkUrl(self):
        """★ 套装（1219）**没有 linkId**，只有 ``linkUrl``。

        只认 linkId 的话，37 套效果一条都取不到
        （实测就是这个原因先跑出"0 套"的）。
        """
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
        """★ 实测形状：名字 / (N件套) / 正文。"""
        lines = ["茜染怀想之花", "(2件套)", "治疗效果提升10%。",
                 "茜染怀想之花", "(5件套)", "为队伍中角色提供治疗时…"]
        effects = wuwa_update._parse_set_effects(lines)
        self.assertEqual([e["pieces"] for e in effects], [2, 5])
        self.assertEqual(effects[0]["text"], "治疗效果提升10%。")
        self.assertIn("提供治疗", effects[1]["text"])

    def test_parse_set_effects_without_name_line(self):
        """没有名字行的格式（声骸详情里的合鸣效果）也要能解析。

        所以是按 ``(N件套)`` **定位**、取后一行，而不是"每 3 行取一次"。
        """
        effects = wuwa_update._parse_set_effects(["(2件套)", "攻击提升10%。"])
        self.assertEqual(len(effects), 1)
        self.assertEqual(effects[0]["pieces"], 2)

    def test_parse_set_effects_ignores_junk(self):
        self.assertEqual(wuwa_update._parse_set_effects([]), [])
        self.assertEqual(wuwa_update._parse_set_effects(["随便一行"]), [])

    def test_parse_echo_skill_takes_five_star_only(self):
        """★ 只要 **5★** 那一段。

        库街区把 2★~5★ 各写一遍（数值不同）；全塞进去技能说明会变成
        四段重复文字（本地一直只存 5 星数据）。
        """
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
        """要按「模块名 + 组件名」双层定位 —— 只用组件名会串（都叫「声骸技能」）。"""
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
            ["甲效果"])
        self.assertEqual(
            wuwa_update._kuro_component_texts(detail, "声骸技能", "声骸技能"),
            ["乙技能"])


class TestEffectsComeFromKurobbs(unittest.TestCase):
    """★ 接线：套装效果 / 声骸技能要先走库街区。"""

    def test_fetch_remote_pulls_kurobbs_effects(self):
        source = inspect.getsource(wuwa_update.fetch_remote)
        self.assertIn("_fetch_kurobbs_set_effects", source)
        self.assertIn("_fetch_kurobbs_echo_skills", source)

    def test_kurobbs_effects_before_bwiki(self):
        source = inspect.getsource(wuwa_update.fetch_remote)
        kuro_at = source.find("_fetch_kurobbs_set_effects")
        bwiki_at = source.find("_fetch_bwiki_sets")
        self.assertLess(kuro_at, bwiki_at,
                        "bwiki 又跑到库街区前面了")

    def test_bwiki_effects_only_fill_empty(self):
        """★ bwiki 的效果只在本地**没有**时才写入（不覆盖库街区的）。

        否则 bwiki 那 34 套会把库街区已经写好的 37 套效果盖回去。
        """
        local = {"sets": [{"name": "甲", "effects": [
            {"pieces": 2, "text": "库街区的效果"}]}]}
        snapshot = wuwa_update.RemoteSnapshot()
        snapshot.set_effects = {"甲": [{"pieces": 2, "text": "库街区的效果"}]}
        snapshot.sets = {"甲": [{"pieces": 2, "text": "bwiki 的效果"}]}
        wuwa_update._merge_sets_data(local, snapshot)
        effects = local["sets"][0]["effects"]
        self.assertEqual(effects[0]["text"], "库街区的效果",
                         "bwiki 把库街区的效果覆盖了")

    def test_bwiki_still_fills_missing_effect(self):
        """库街区没给的套装，bwiki 仍要能补上。"""
        local = {"sets": [{"name": "乙", "effects": []}]}
        snapshot = wuwa_update.RemoteSnapshot()
        snapshot.set_effects = {}
        snapshot.sets = {"乙": [{"pieces": 2, "text": "bwiki 补的"}]}
        wuwa_update._merge_sets_data(local, snapshot)
        self.assertEqual(local["sets"][0]["effects"][0]["text"], "bwiki 补的")

    def test_kurobbs_effect_overwrites_local(self):
        """★ 库街区的效果要能**更新**已有的（数值会随版本调整）。"""
        local = {"sets": [{"name": "丙", "effects": [
            {"pieces": 2, "text": "旧的"}]}]}
        snapshot = wuwa_update.RemoteSnapshot()
        snapshot.set_effects = {"丙": [{"pieces": 2, "text": "新的"}]}
        snapshot.sets = {}
        wuwa_update._merge_sets_data(local, snapshot)
        self.assertEqual(local["sets"][0]["effects"][0]["text"], "新的")

    def test_echo_skill_skips_only_when_text_exists(self):
        """★ 只按"名字在不在"跳过是**错的**。

        本地 187 条大多是 ``{"skill": "", "cooldown": ""}`` 的空壳
        （只有名字、没有正文）—— 按名字跳过的话一个都补不上
        （实测第一次跑就是"0 个拿到"）。要看**有没有正文**。
        """
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "wuwa_echo_skills.json"
            path.write_text(json.dumps({"echoes": {
                "空壳": {"skill": "", "cooldown": ""},
                "有正文": {"skill": "已经有的技能", "cooldown": "5秒"},
            }}, ensure_ascii=False), encoding="utf-8")

            original = wuwa_update.SKILLS_FILE
            wuwa_update.SKILLS_FILE = path
            try:
                with unittest.mock.patch.object(
                        wuwa_update, "_kuro_page",
                        return_value=([{"name": "空壳"}, {"name": "有正文"},
                                       {"name": "全新"}], {})):
                    with unittest.mock.patch.object(
                            wuwa_update, "_entry_id_from_record",
                            return_value="123"):
                        with unittest.mock.patch.object(
                                wuwa_update, "_kuro_entry_detail",
                                return_value={}):
                            # 只验证"要拉哪些"——看它有没有把空壳算进去
                            logs: list[str] = []
                            wuwa_update._fetch_kurobbs_echo_skills(
                                logs.append, {})
                joined = " ".join(logs)
                self.assertIn("需要补 2 个", joined,
                              f"空壳没被算进「待补」（日志：{joined}）")
            finally:
                wuwa_update.SKILLS_FILE = original


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
