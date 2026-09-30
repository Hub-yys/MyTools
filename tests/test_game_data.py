"""游戏静态数据集的单元测试。

这层没逻辑、全是数据，但它是界面和配置的**唯一数据源**，写死几个不变量值回票价：
名字不重复、图标路径拼得对、查询函数的边界行为。
"""

from __future__ import annotations

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.core.game_data import (  # noqa: E402
    ASSETS_ROOT,
    CHARACTERS,
    COST_1,
    COST_3,
    COST_4,
    COST_SECTIONS,
    DATA_META,
    ECHO_SETS,
    ELEMENT_DAMAGE_STATS,
    ECHOES_BY_COST,
    STATS_BY_COST,
    CharacterInfo,
    CONFIGURABLE_ECHO_SETS,
    EchoSetInfo,
    character_choice_error,
    find_character,
    find_echo_set,
    icon_path,
    match_characters,
)


class TestCharacters(unittest.TestCase):
    def test_not_empty(self):
        self.assertTrue(CHARACTERS)

    def test_names_unique(self):
        names = [c.name for c in CHARACTERS]
        self.assertEqual(len(names), len(set(names)), "角色名有重复")

    def test_every_character_has_avatar(self):
        for character in CHARACTERS:
            self.assertTrue(character.avatar, f"{character.name} 没有头像路径")
            self.assertTrue((ASSETS_ROOT / character.avatar).exists(),
                            f"{character.name} 的头像文件不存在")

    def test_find_character_exact(self):
        first = CHARACTERS[0]
        self.assertIs(find_character(first.name), first)

    def test_find_character_strips_space(self):
        first = CHARACTERS[0]
        self.assertIs(find_character(f"  {first.name}  "), first)

    def test_find_character_missing(self):
        for key in ("", "   ", "查无此人"):
            self.assertIsNone(find_character(key), f"{key!r} 不该匹配到角色")

    def test_find_character_is_exact_not_partial(self):
        """半截输入不该联动头像。

        ⚠ 用**名字长度 >1** 的角色来截，别拿 ``CHARACTERS[0]`` ——
        3.7 的「心」是单字名，``name[:1]`` 就是它自己，这条会假失败。
        """
        target = next((c for c in CHARACTERS if len(c.name) > 1), None)
        self.assertIsNotNone(target, "数据集里没有多字角色名，测不了")
        self.assertIsNone(find_character(target.name[:1]))


class TestMatchCharacters(unittest.TestCase):
    def test_empty_returns_all(self):
        self.assertEqual(match_characters(""), CHARACTERS)

    def test_contains_match(self):
        first = CHARACTERS[0]
        result = match_characters(first.name[1:])
        self.assertIn(first, result)

    def test_no_match_returns_empty(self):
        self.assertEqual(match_characters("zzz不存在"), ())


class TestCharacterChoiceError(unittest.TestCase):
    """★ 配置页两类配置共用的「角色选择」校验（用户 2026-09-26）。

    规则：**必须精确命中一个角色** + **一个角色只能有一条配置**。

    为什么值得单独测：这两条以前只是"候选里没有"（界面层），
    而 ``FilterComboBox`` 是**可输入**的 —— 用户能把候选筛空、直接敲个字就保存。
    用户实测就是把名字改成"绯雪声骸强化配置"，结果**头像当场消失**
    （行上的头像是拿名字去 ``find_character`` 查的）。
    """

    def setUp(self):
        self.first = CHARACTERS[0].name

    def test_valid_character_passes(self):
        self.assertEqual(character_choice_error(self.first), "")

    def test_blank_rejected(self):
        for blank in ("", "   ", None):
            self.assertIn("请先选一个角色", character_choice_error(blank))

    def test_unknown_character_rejected(self):
        """★ 就是用户截图里那个输入 —— 它不是角色，必须拒绝。"""
        error = character_choice_error("绯雪声骸强化配置")
        self.assertIn("不是一个角色", error)
        self.assertIn("绯雪声骸强化配置", error, "报错要说清是哪个词不行")

    def test_taken_character_rejected(self):
        """同一个角色只能有一条。"""
        error = character_choice_error(self.first, [self.first])
        self.assertIn("一个角色只能有一条", error)

    def test_taken_is_compared_after_strip(self):
        """带空格的输入要按去空格之后比 —— 否则会绕过"已占用"。"""
        error = character_choice_error(f"  {self.first}  ", [self.first])
        self.assertIn("一个角色只能有一条", error)

    def test_other_taken_does_not_block(self):
        self.assertEqual(character_choice_error(self.first, ["别的角色"]), "")

    def test_max_length_enforced_when_given(self):
        # 用一个真实角色名 + 很短的 max_length 来验证长度这条。
        # ⚠ 必须挑**名字比 max_length 长**的角色：3.7 的「心」只有 1 个字，
        #   max_length=1 时它没超长，这条会假失败。
        target = next((c for c in CHARACTERS if len(c.name) > 1), None)
        self.assertIsNotNone(target, "数据集里没有多字角色名，测不了")
        self.assertIn("太长", character_choice_error(target.name, (), 1))

    def test_max_length_optional(self):
        """不传 max_length 就不查长度 —— 角色从数据集里选时长度天然有界。"""
        self.assertEqual(character_choice_error(self.first, (), None), "")

    def test_order_existence_before_taken(self):
        """既不存在、又在 taken 里时，先说"不是一个角色"（更根本的那个问题）。"""
        error = character_choice_error("查无此人", ["查无此人"])
        self.assertIn("不是一个角色", error)


class TestEchoSets(unittest.TestCase):
    def test_not_empty(self):
        self.assertTrue(ECHO_SETS)

    def test_names_unique(self):
        names = [s.name for s in ECHO_SETS]
        self.assertEqual(len(names), len(set(names)), "套装名有重复")

    def test_every_set_has_icon(self):
        for echo_set in ECHO_SETS:
            self.assertTrue((ASSETS_ROOT / echo_set.icon).exists(),
                            f"{echo_set.name} 的图标文件不存在")

    def test_by_cost_filters_correctly(self):
        # 只有收录了声骸明细、且填得完整的套装才逐档断言
        self.assertTrue(CONFIGURABLE_ECHO_SETS, "一个能填完整的套装都没有")
        for echo_set in CONFIGURABLE_ECHO_SETS:
            for cost in echo_set.required_costs:
                got = echo_set.by_cost(cost)
                self.assertTrue(all(e.cost == cost for e in got))
                self.assertTrue(got, f"{echo_set.name} 没有 {cost}C 声骸")

    def test_configurable_is_subset_with_echoes(self):
        self.assertTrue(set(CONFIGURABLE_ECHO_SETS).issubset(set(ECHO_SETS)))
        for echo_set in CONFIGURABLE_ECHO_SETS:
            self.assertTrue(echo_set.has_echoes, f"{echo_set.name} 不该出现在可配置列表里")

    def test_by_cost_unknown_returns_empty(self):
        self.assertEqual(ECHO_SETS[0].by_cost(9), ())

    def test_effects_are_filled(self):
        # 效果文字来自 wiki 抓取（tools/refresh_wuwa_data.py），正常情况每套都该有
        missing = [s.name for s in ECHO_SETS if not s.effects]
        self.assertEqual(missing, [], f"这些套装缺效果文字：{missing}")
        for echo_set in ECHO_SETS:
            for pieces, text in echo_set.effects:
                self.assertIn(pieces, (1, 2, 3, 5), f"{echo_set.name} 件数不像话：{pieces}")
                self.assertTrue(text.strip(), f"{echo_set.name} 有空的效果文字")

    def test_effect_lines_are_readable(self):
        for echo_set in ECHO_SETS:
            for line in echo_set.effect_lines:
                self.assertRegex(line, r"^\d件套：\S")
        self.assertTrue(ECHO_SETS[0].description)

    def test_find_echo_set(self):
        first = ECHO_SETS[0]
        self.assertIs(find_echo_set(first.name), first)
        self.assertIsNone(find_echo_set("不存在的套装"))
        self.assertIsNone(find_echo_set(""))

    def test_cost_sections_cover_all_costs(self):
        self.assertEqual([cost for cost, _label in COST_SECTIONS], [4, 3, 1])

    def test_every_echo_has_stats(self):
        for echo_set in ECHO_SETS:
            for echo in echo_set.echoes:
                self.assertTrue(echo.stats, f"{echo.name} 没有候选属性")
                self.assertEqual(echo.stats, STATS_BY_COST[echo.cost])


class TestCharacterTagline(unittest.TestCase):

    def test_tagline_joins_rarity_element_weapon(self):
        character = find_character("爱弥斯")
        self.assertIsNotNone(character)
        self.assertEqual(character.tagline, "5星 · 热熔 · 迅刀")

    def test_empty_fields_yield_empty_tagline(self):
        self.assertEqual(CharacterInfo("测试", "avatars/x.png").tagline, "")


class TestDataMeta(unittest.TestCase):
    """数据文件本身要说清这份资料哪来的、什么时候的。"""

    def test_source_and_date_recorded(self):
        self.assertTrue(DATA_META["fetched"], "没记录抓取时间")
        self.assertTrue(DATA_META["echo_sets_source"], "没记录套装数据来源")
        self.assertTrue(DATA_META["characters_source"], "没记录角色数据来源")


class TestMainStatPools(unittest.TestCase):
    """三档的**主词条池**要跟游戏一致 —— 界面上那排勾选框就是照它渲染的。

    依据（库街区官方社区 / 3DM / gamekee / okemu 四个来源一致）：
    4C 六种、3C 五类（属性伤害分六元素）、1C 只有百分比。
    """

    def test_cost4_pool(self):
        self.assertEqual(
            STATS_BY_COST[COST_4],
            ("暴击", "暴击伤害", "治疗加成", "攻击百分比", "防御百分比", "生命百分比"),
        )

    def test_cost1_has_no_flat_values(self):
        self.assertEqual(STATS_BY_COST[COST_1], ("攻击百分比", "防御百分比", "生命百分比"))
        for flat in ("攻击", "防御", "生命"):
            self.assertNotIn(flat, STATS_BY_COST[COST_1], "1C 不该有固定值词条")

    def test_cost3_lists_every_element(self):
        self.assertTrue(set(ELEMENT_DAMAGE_STATS).issubset(STATS_BY_COST[COST_3]))
        self.assertEqual(len(ELEMENT_DAMAGE_STATS), 6, "属性伤害加成应该是六种")
        for stat in ELEMENT_DAMAGE_STATS:
            self.assertIn(stat, STATS_BY_COST[COST_3])

    def test_cost3_has_no_vague_element_entry(self):
        # 以前是一个笼统的「属性伤害加成」，现在拆成六种具体属性，不能再出现笼统那条
        self.assertNotIn("属性伤害加成", STATS_BY_COST[COST_3])

    def test_cost4_has_no_element_damage(self):
        self.assertNotIn("属性伤害加成", STATS_BY_COST[COST_4])
        for stat in ELEMENT_DAMAGE_STATS:
            self.assertNotIn(stat, STATS_BY_COST[COST_4])

    def test_every_echo_uses_its_tier_pool(self):
        for echo_set in ECHO_SETS:
            for echo in echo_set.echoes:
                self.assertEqual(echo.stats, STATS_BY_COST[echo.cost])


class TestSetOrder(unittest.TestCase):
    """套装按**出场版本倒序**排（最新的在最前面）—— 资源库和配置页下拉都照这个顺序。"""

    def test_every_set_has_a_version(self):
        missing = [s.name for s in ECHO_SETS if not s.version]
        self.assertEqual(missing, [], f"这些套装没记版本：{missing}")

    def test_versions_look_like_versions(self):
        for echo_set in ECHO_SETS:
            self.assertRegex(echo_set.version, r"^\d+\.\d+$", f"{echo_set.name} 版本号怪怪的")

    def test_sorted_newest_first(self):
        keys = [s.version_key for s in ECHO_SETS]
        self.assertEqual(keys, sorted(keys, reverse=True), "不是按版本倒序排的")

    def test_newest_is_first_and_oldest_is_last(self):
        self.assertEqual(ECHO_SETS[0].version, max(s.version for s in ECHO_SETS))
        self.assertEqual(ECHO_SETS[-1].version, min(s.version for s in ECHO_SETS))

    def test_same_version_keeps_name_order(self):
        # 同一版本内按名称排 —— 顺序可预期，不会每次启动都不一样
        groups: dict[str, list[str]] = {}
        for echo_set in ECHO_SETS:
            groups.setdefault(echo_set.version, []).append(echo_set.name)
        for version, names in groups.items():
            self.assertEqual(names, sorted(names), f"{version} 组内没按名字排")

    def test_version_key_parsing(self):
        self.assertEqual(EchoSetInfo("x", "i", version="3.10").version_key, (3, 10))
        self.assertEqual(EchoSetInfo("x", "i", version="2.0").version_key, (2, 0))
        self.assertEqual(EchoSetInfo("x", "i", version="").version_key, ())
        self.assertGreater(
            EchoSetInfo("x", "i", version="3.10").version_key,
            EchoSetInfo("x", "i", version="3.5").version_key,
            "3.10 要比 3.5 新",
        )

    def test_configurable_follows_same_order(self):
        order = [s.name for s in ECHO_SETS]
        picked = [s.name for s in CONFIGURABLE_ECHO_SETS]
        self.assertEqual(picked, [n for n in order if n in set(picked)])


class TestRequiredCosts(unittest.TestCase):
    """配置页该要求哪几档 —— 1 件套只要一个声骸，不该逼用户填 3C/1C。"""

    def test_normal_set_requires_all_three(self):
        for name in ("凝夜白霜", "雪落无声之愿", "冥途夜行之灯"):
            info = find_echo_set(name)
            self.assertEqual(info.piece_counts, (2, 5), f"{name} 应该是常规 2/5 件套")
            self.assertEqual(info.required_costs, (COST_4, COST_3, COST_1))

    def test_single_piece_set_requires_one_tier_only(self):
        info = find_echo_set("碎梦亡鬼之魇")
        self.assertIsNotNone(info, "3.4 联动套应该在数据里")
        self.assertEqual(info.piece_counts, (1,))
        self.assertTrue(info.is_single_piece)
        self.assertEqual(info.required_costs, (COST_4,))
        self.assertTrue(info.is_configurable, "1 件套只有 4C 也该算『能填完整』")
        self.assertFalse(info.by_cost(COST_3), "它的 3C 本来就不存在，不是缺数据")
        self.assertFalse(info.by_cost(COST_1))

    def test_three_piece_set_still_needs_all_tiers(self):
        info = find_echo_set("失序彼岸之梦")
        self.assertEqual(info.piece_counts, (3,))
        self.assertFalse(info.is_single_piece)
        self.assertEqual(info.required_costs, (COST_4, COST_3, COST_1))

    def test_required_costs_are_always_filled_for_configurable(self):
        for info in CONFIGURABLE_ECHO_SETS:
            for cost in info.required_costs:
                self.assertTrue(info.by_cost(cost), f"{info.name} 的 {cost}C 是空的")


class TestEchoGallery(unittest.TestCase):
    """资源库「声骸图鉴」用到的按 COST 分组的全量声骸索引。"""

    def test_groups_match_cost_sections(self):
        self.assertEqual(set(ECHOES_BY_COST), {COST_4, COST_3, COST_1})
        for cost, items in ECHOES_BY_COST.items():
            self.assertTrue(items, f"{cost}C 分组不该是空的")
            self.assertTrue(all(e.cost == cost for e in items),
                            f"{cost}C 分组里混进了别的档位")

    def test_names_unique_within_group(self):
        for cost, items in ECHOES_BY_COST.items():
            names = [e.name for e in items]
            self.assertEqual(len(names), len(set(names)), f"{cost}C 组内名字有重复")

    def test_total_echo_count(self):
        """声骸总数**不能是硬编码数字**。

        原来这里钉的是 181（当时和库街区一致）。但游戏每出新套装就会加声骸
        ——2026-09-30 加了 3 套（+6 个声骸）之后它就假失败了。
        数字本身不是"约定"，只是当时的快照；真正该守住的是"别比已知基线还少"。
        """
        total = sum(len(items) for items in ECHOES_BY_COST.values())
        self.assertGreaterEqual(total, 181, f"声骸总数不该比 3.6 时（181）还少：{total}")

    def test_new_sets_have_echoes(self):
        """★ 3.7 新增的 3 套必须**带着声骸**（2026-09-30 用户报"没看到新套装"）。

        它们的效果文字是手工补的、声骸池来自库街区；这里钉住"补完是完整的"。
        """
        for name in ("衔梦照世之心", "镜影流电之瞬", "茜染怀想之花"):
            with self.subTest(name=name):
                info = find_echo_set(name)
                self.assertIsNotNone(info, f"{name} 不在数据集里")
                self.assertTrue(info.effects, f"{name} 没有套装效果")
                self.assertTrue(info.echoes, f"{name} 一个声骸都没有")

    def test_skill_fields_loaded(self):
        # bwiki 只给老声骸建了页，43 个新声骸没技能是已知现状（见 fetch_wuwa_echo_skills.py）
        with_skill = [e for items in ECHOES_BY_COST.values() for e in items if e.skill]
        self.assertTrue(with_skill, "一个带技能说明的声骸都没有，技能数据加载挂了")
        example = next(e for e in with_skill if e.cooldown)
        self.assertTrue(example.skill.strip(), "技能说明不该是空白")


class TestIconPath(unittest.TestCase):
    def test_joins_under_assets_root(self):
        self.assertEqual(icon_path("avatars/a.png"), ASSETS_ROOT / "avatars/a.png")


if __name__ == "__main__":
    unittest.main(verbosity=2)
