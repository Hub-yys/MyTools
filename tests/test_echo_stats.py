"""声骸判定引擎单元测试。

    python tests/test_echo_stats.py          直接跑
    或在 PyCharm 里右键 Run 'Unittests in test_echo_stats.py'

覆盖：暴击/爆伤各自下限（含阈值边界）、核心属性缺失、有效词条上限、满级上锁、
配置校验、以及 OCR 文本解析的容错。
"""

from __future__ import annotations

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.tools.game.echo_enhance.stats import (  # noqa: E402
    CRIT,
    CRIT_DMG,
    DEFAULT_CRIT_DMG_MIN,
    DEFAULT_CRIT_MIN,
    EchoStat,
    JudgeConfig,
    MAX_CRIT,
    MAX_CRIT_DMG,
    OPTIONAL_CHOICES,
    judge,
    normalize_stat_name,
    parse_value,
)


def stats(*pairs: tuple[str, float]) -> list[EchoStat]:
    return [EchoStat(name, value) for name, value in pairs]


class TestParse(unittest.TestCase):
    def test_parse_percent(self):
        self.assertEqual(parse_value("6.3%"), 6.3)

    def test_parse_fullwidth_percent(self):
        self.assertEqual(parse_value("12.6％"), 12.6)

    def test_parse_plain_number(self):
        self.assertEqual(parse_value("40"), 40.0)

    def test_parse_garbage_returns_none(self):
        for bad in ("", "暴击", "-", "abc"):
            self.assertIsNone(parse_value(bad), f"{bad!r} 应该解析失败")


class TestNormalize(unittest.TestCase):
    def test_crit_and_crit_dmg(self):
        self.assertEqual(normalize_stat_name("暴击"), CRIT)
        self.assertEqual(normalize_stat_name("暴击伤害"), CRIT_DMG)

    def test_crit_dmg_takes_priority_over_crit(self):
        # "暴击伤害" 里含 "暴击"，必须先判爆伤，否则会被吃成暴击
        self.assertEqual(normalize_stat_name("暴击伤害 12.6%", "12.6%"), CRIT_DMG)

    def test_attack_fixed_vs_percent(self):
        self.assertEqual(normalize_stat_name("攻击", "40"), "攻击")
        self.assertEqual(normalize_stat_name("攻击", "6.3%"), "攻击百分比")

    def test_other_stats(self):
        cases = {
            "共鸣效率": "共鸣效率",
            "普攻伤害加成": "普攻伤害加成",
            "重击伤害加成": "重击伤害加成",
            "共鸣技能伤害加成": "共鸣技能伤害加成",
            "共鸣解放伤害加成": "共鸣解放伤害加成",
            "生命": "生命",
            "防御百分比": "防御百分比",
        }
        for raw, expected in cases.items():
            self.assertEqual(normalize_stat_name(raw, ""), expected, raw)

    def test_ocr_noise_tolerated(self):
        # 游戏里 OCR 偶尔会多认几个字，用"包含"匹配要能扛住
        self.assertEqual(normalize_stat_name("暴击 率", ""), CRIT)

    def test_unknown_returns_none(self):
        self.assertIsNone(normalize_stat_name("辅音", ""))


class TestConfigValidation(unittest.TestCase):
    def test_crit_always_forced_into_core(self):
        cfg = JudgeConfig(core_stats=frozenset(), optional_stats=frozenset())
        self.assertIn(CRIT, cfg.core_stats)
        self.assertIn(CRIT_DMG, cfg.core_stats)

    def test_crit_cannot_be_removed(self):
        cfg = JudgeConfig(core_stats=frozenset({"攻击"}), optional_stats=frozenset())
        self.assertIn(CRIT, cfg.core_stats)
        self.assertIn(CRIT_DMG, cfg.core_stats)
        self.assertIn("攻击", cfg.core_stats)

    def test_optional_cannot_contain_crit(self):
        cfg = JudgeConfig(optional_stats=frozenset({CRIT, "攻击"}))
        self.assertNotIn(CRIT, cfg.optional_stats)
        self.assertIn("攻击", cfg.optional_stats)

    def test_too_many_core_raises(self):
        with self.assertRaises(ValueError):
            # 双爆是强制的，所以再给 5 条就超了 5 条上限
            JudgeConfig(core_stats=frozenset({"攻击", "生命", "防御", "攻击百分比", "生命百分比"}))

    def test_optional_has_no_upper_limit(self):
        # 需求变更：可选属性的 3 条上限已去掉，全勾也不报错
        cfg = JudgeConfig(optional_stats=frozenset(OPTIONAL_CHOICES))
        self.assertEqual(cfg.optional_stats, frozenset(OPTIONAL_CHOICES))

    def test_valid_count_out_of_range_raises(self):
        for bad in (1, 6):
            with self.assertRaises(ValueError):
                JudgeConfig(min_valid_count=bad)

    def test_valid_stats_union(self):
        cfg = JudgeConfig(
            core_stats=frozenset({CRIT, CRIT_DMG}), optional_stats=frozenset({"攻击百分比"})
        )
        self.assertEqual(cfg.valid_stats, frozenset({CRIT, CRIT_DMG, "攻击百分比"}))


class TestJudge(unittest.TestCase):
    """默认配置：核心=双爆，可选=攻击百分比，暴击>=7.5 / 爆伤>=15.0，有效词条 >= 3。

    ⚠ 这里**故意关掉满值保护**（``enable_max_roll_lock=False``）：本类测的是
    双爆下限等规则本身，而构造里会用到 (暴击 10.5) / (爆伤 21.0) 这种满值词条，
    开着保护会被先手保住、测不到原规则。满值保护单独见 TestMaxRollLock。
    """

    def setUp(self):
        self.cfg = JudgeConfig(
            core_stats=frozenset({CRIT, CRIT_DMG}),
            optional_stats=frozenset({"攻击百分比"}),
            crit_min=DEFAULT_CRIT_MIN,
            crit_dmg_min=DEFAULT_CRIT_DMG_MIN,
            min_valid_count=3,
            enable_max_roll_lock=False,
        )

    # ---------------------------------------------------------- 双爆各自下限
    def test_both_below_threshold_discards(self):
        # 暴击 6.3 < 7.5 且 爆伤 12.6 < 15.0 → 弃置
        result = judge(stats((CRIT, 6.3), (CRIT_DMG, 12.6)), self.cfg)
        self.assertEqual(result.action, "discard")
        self.assertIn("双爆不达标", result.reason)
        self.assertIn("暴击", result.reason)
        self.assertIn("暴伤", result.reason)

    def test_only_crit_below_discards(self):
        # 爆伤达标但暴击不达标 → 一样弃置
        result = judge(stats((CRIT, 6.3), (CRIT_DMG, 21.0)), self.cfg)
        self.assertEqual(result.action, "discard")
        self.assertIn("暴击", result.reason)

    def test_only_crit_dmg_below_discards(self):
        # 暴击达标但爆伤不达标 → 一样弃置
        result = judge(stats((CRIT, 10.5), (CRIT_DMG, 12.6)), self.cfg)
        self.assertEqual(result.action, "discard")
        self.assertIn("暴伤", result.reason)

    def test_both_above_threshold_continues(self):
        # 暴击 10.5 >= 7.5 且 爆伤 21.0 >= 15.0 → 通过
        result = judge(stats((CRIT, 10.5), (CRIT_DMG, 21.0)), self.cfg)
        self.assertNotEqual(result.action, "discard")
        self.assertAlmostEqual(result.crit, 10.5)
        self.assertAlmostEqual(result.crit_dmg, 21.0)

    def test_exactly_at_threshold_passes(self):
        # 边界：正好等于阈值要算通过（>=）
        result = judge(stats((CRIT, 7.5), (CRIT_DMG, 15.0)), self.cfg)
        self.assertNotEqual(result.action, "discard")

    def test_only_one_crit_present_still_judged(self):
        """只出了暴击、还没出爆伤 → **照样当场弃置**。

        声骸每种副词条**只会出现一次**：已经读出来的 6.3 就是这个声骸最终的
        暴击值，后面孔位再多也变不出第二个暴击 → 永远到不了 7.5，
        等下去只是白烧材料。

        （2026-09-25 修正。原实现要求两项都出现才判，注释理由是
        "另一项还有孔位可以博" —— 那个理由对双爆自身不成立：能博的是
        **别的**词条，博不出第二个暴击。）
        """
        result = judge(stats((CRIT, 6.3)), self.cfg)
        self.assertEqual(result.action, "discard")
        self.assertIn("双爆不达标", result.reason)
        self.assertAlmostEqual(result.crit, 6.3)

    def test_single_crit_below_dmg_discards(self):
        """爆伤单项低于下限 → 同样当场弃置。"""
        result = judge(stats((CRIT_DMG, 12.6)), self.cfg)
        self.assertEqual(result.action, "discard")
        self.assertIn("暴伤", result.reason)

    def test_remaining_slots_do_not_save_low_crit(self):
        """用户强调的那条：**剩余孔位再多也救不了已经低了的暴击**。

        只出了暴击 6.3，还剩 4 个孔（远够凑「有效词条 ≥3」）→ 仍然弃置。
        """
        result = judge(stats((CRIT, 6.3)), self.cfg)
        self.assertEqual(result.action, "discard")
        self.assertGreater(result.remaining, 0)     # 确实还有孔位，但没意义

    def test_single_crit_passing_continues(self):
        """单项已达标时不能误判 —— 另一项还没出来，继续强化。"""
        self.assertNotEqual(judge(stats((CRIT, 8.0)), self.cfg).action, "discard")
        self.assertNotEqual(judge(stats((CRIT_DMG, 16.0)), self.cfg).action, "discard")

    def test_crit_check_can_be_disabled(self):
        # 右侧开关关掉后，双爆下限整个不参与判定：
        # 6.3 / 12.6 本来两项都不达标，这里不该被判弃置
        cfg = JudgeConfig(
            core_stats=frozenset({CRIT, CRIT_DMG}),
            optional_stats=frozenset({"攻击百分比"}),
            crit_min=DEFAULT_CRIT_MIN,
            crit_dmg_min=DEFAULT_CRIT_DMG_MIN,
            enable_crit_check=False,
            min_valid_count=3,
        )
        result = judge(stats((CRIT, 6.3), (CRIT_DMG, 12.6), ("攻击百分比", 10.0)), cfg)
        self.assertNotEqual(result.action, "discard")
        # 双爆值仍然读出来记在结果里（日志能看到），只是不用来判定
        self.assertAlmostEqual(result.crit, 6.3)

    # ---------------------------------------------------------- 核心属性
    def test_missing_core_without_enough_slots_discards(self):
        # 4 条已出，全是垃圾：剩 1 孔但要凑双爆，凑不齐 → 弃置
        result = judge(
            stats(("攻击", 40), ("生命", 500), ("防御", 40), ("共鸣效率", 10.0)), self.cfg
        )
        self.assertEqual(result.action, "discard")
        self.assertIn("核心属性", result.reason)

    def test_missing_core_but_slots_left_continues(self):
        # 出了暴击，还有 4 孔可以博爆伤
        result = judge(stats((CRIT, 10.5)), self.cfg)
        self.assertEqual(result.action, "continue")

    # ---------------------------------------------------------- 有效词条数
    def test_not_enough_valid_slots_discards(self):
        # 已出 3 条全都不是有效词条，剩 2 孔 → 最多 2 条有效 < 要求 3 → 弃置
        # ⚠ 有效词条集合得真的放得下 3 条：这里多勾两个可选属性。
        #   否则「≥3」在只有 2 条的集合上永远达不到（见 TestUnreachableValidCount）。
        cfg = JudgeConfig(
            optional_stats=frozenset({"攻击百分比", "共鸣效率"}),
            min_valid_count=3, crit_min=0.0, crit_dmg_min=0.0,
        )
        result = judge(
            stats(("攻击", 40), ("生命", 500), ("防御", 40)), cfg
        )
        self.assertEqual(result.action, "discard")
        self.assertIn("有效词条", result.reason)

    def test_optional_stat_counts_as_valid(self):
        # 攻击百分比属于可选属性 → 算有效词条
        cfg = JudgeConfig(
            optional_stats=frozenset({"攻击百分比"}),
            min_valid_count=3,
            crit_min=0.0,
            crit_dmg_min=0.0,
        )
        result = judge(stats(("攻击百分比", 10.0), (CRIT, 10.5)), cfg)
        self.assertGreaterEqual(result.valid_count, 2)
        self.assertNotEqual(result.action, "discard")

    def test_min_valid_count_2_allows_earlier_keep(self):
        cfg = JudgeConfig(min_valid_count=2, crit_min=0.0, crit_dmg_min=0.0)
        result = judge(stats(("攻击", 40)), cfg)
        # 1 条有效 + 4 孔 = 5 >= 2，可以继续
        self.assertEqual(result.action, "continue")

    # ---------------------------------------------------------- 满级
    def test_full_five_stats_locks(self):
        result = judge(
            stats(
                (CRIT, 10.5),
                (CRIT_DMG, 21.0),
                ("攻击百分比", 11.6),
                ("共鸣效率", 10.0),
                ("普攻伤害加成", 11.6),
            ),
            self.cfg,
        )
        self.assertEqual(result.action, "lock")
        self.assertTrue(result.keep)

    def test_full_five_stats_but_bad_crit_discards(self):
        result = judge(
            stats(
                (CRIT, 6.3),
                (CRIT_DMG, 12.6),
                ("攻击百分比", 3.9),
                ("共鸣效率", 6.4),
                ("普攻伤害加成", 5.6),
            ),
            self.cfg,
        )
        self.assertEqual(result.action, "discard")
        self.assertIn("双爆不达标", result.reason)

    # ---------------------------------------------------------- 容错
    def test_unknown_stat_names_are_ignored(self):
        # OCR 认出来的垃圾属性不该推进"已出条数"
        result = judge(stats(("辅音", 1.0), (CRIT, 10.5)), self.cfg)
        self.assertEqual(len(result.stats), 1)
        self.assertEqual(result.remaining, 4)


class TestCoreStats(unittest.TestCase):
    """核心属性规则：缺核心、且剩余孔位凑不齐核心 → 直接弃置。

    核心取 4 条（双爆 + 攻击 + 生命）；关掉双爆数值检查、有效词条阈值压到 2，
    把变量隔离成「核心属性凑不凑得齐」这一条。
    """

    def setUp(self):
        self.cfg = JudgeConfig(
            core_stats=frozenset({CRIT, CRIT_DMG, "攻击", "生命"}),
            optional_stats=frozenset(),
            enable_crit_check=False,
            min_valid_count=2,
        )

    def test_missing_core_but_enough_slots_continues(self):
        # 一条都没出：缺 4 条，剩 5 孔 → 还有机会补，继续强化
        result = judge([], self.cfg)
        self.assertEqual(result.remaining, 5)
        self.assertEqual(result.action, "continue")

    def test_missing_equal_to_remaining_slots_continues(self):
        # 临界：缺 4 条、正好剩 4 孔 → 还在"理论上凑得齐"的范围，不弃置
        result = judge(stats(("攻击百分比", 5.0)), self.cfg)
        self.assertEqual(result.remaining, 4)
        self.assertEqual(result.action, "continue")

    def test_missing_exceeds_remaining_slots_discards(self):
        # 临界 +1：缺 4 条、只剩 3 孔 → 凑不齐，弃置
        result = judge(stats(("攻击百分比", 5.0), ("防御", 40)), self.cfg)
        self.assertEqual(result.remaining, 3)
        self.assertEqual(result.action, "discard")
        self.assertIn("核心属性", result.reason)

    def test_full_but_core_incomplete_discards(self):
        # 5 条出满、仍缺 2 条核心（剩 0 孔）→ 弃置
        result = judge(
            stats(
                ("攻击", 40),
                ("生命", 470),
                ("攻击百分比", 5.0),
                ("防御", 40),
                ("共鸣效率", 8.0),
            ),
            self.cfg,
        )
        self.assertEqual(result.remaining, 0)
        self.assertEqual(result.action, "discard")
        self.assertIn("核心属性", result.reason)

    def test_core_complete_can_lock(self):
        # 4 条核心全齐 → 满 5 条时上锁
        result = judge(
            stats((CRIT, 10.0), (CRIT_DMG, 20.0), ("攻击", 40), ("生命", 470), ("防御", 40)),
            self.cfg,
        )
        self.assertEqual(result.action, "lock")

    def test_more_core_stats_means_earlier_discard(self):
        # 同样的 2 条垃圾词条：默认核心（双爆 2 条）还有机会，4 条核心就直接弃置
        default_cfg = JudgeConfig(min_valid_count=2)
        junk = stats(("攻击百分比", 5.0), ("防御", 40))
        self.assertNotEqual(judge(junk, default_cfg).action, "discard")
        self.assertEqual(judge(junk, self.cfg).action, "discard")

    def test_core_rule_runs_before_valid_count_rule(self):
        # 两条规则同时满足弃置条件时，报出来的应该是核心 —— 证明核心这条先执行
        result = judge(
            stats(
                ("攻击百分比", 5.0),
                ("防御", 40),
                ("共鸣效率", 8.0),
                ("生命百分比", 5.0),
            ),
            self.cfg,
        )
        self.assertEqual(result.action, "discard")
        self.assertIn("核心属性", result.reason)
        self.assertNotIn("有效词条", result.reason)


class TestMaxRollLock(unittest.TestCase):
    """满暴击 / 满爆伤自动保护（``enable_max_roll_lock`` 默认开着）。

    规则位置是关键：**排在所有弃置判定之前** —— 出了满分词条就一律保下来，
    哪怕双爆下限、核心属性、有效词条这几条都想把它弃置。

    （2026-09-25 曾一度把双爆下限提到它前面，用户随后澄清：
    "出现满暴击/爆伤，后续无论如何都要强化满级并锁定" —— 已改回最高优先。
    两条规则不冲突：双爆下限管的是**没出满值**的那些声骸。）
    """

    def setUp(self):
        # 默认配置 = 保护开着，双爆下限也照常开着
        self.cfg = JudgeConfig(
            core_stats=frozenset({CRIT, CRIT_DMG}),
            optional_stats=frozenset({"攻击百分比"}),
            min_valid_count=3,
        )

    def test_max_crit_outranks_crit_check(self):
        """爆伤 12.6 不达标、本来该弃置；满暴击先手 → 保住。"""
        result = judge(stats((CRIT, MAX_CRIT), (CRIT_DMG, 12.6)), self.cfg)
        self.assertNotEqual(result.action, "discard")
        self.assertIn(CRIT, result.reason)
        self.assertIn("满", result.reason)

    def test_max_crit_dmg_outranks_crit_check(self):
        """反过来一样：满爆伤救得了不达标的暴击。"""
        result = judge(stats((CRIT, 6.3), (CRIT_DMG, MAX_CRIT_DMG)), self.cfg)
        self.assertNotEqual(result.action, "discard")
        self.assertIn(CRIT_DMG, result.reason)
        self.assertIn("满", result.reason)

    def test_max_roll_on_full_echo_locks(self):
        # 已经满 5 条 → 直接上锁
        result = judge(
            stats(
                (CRIT, MAX_CRIT), (CRIT_DMG, MAX_CRIT_DMG),
                ("攻击", 40), ("防御", 40), ("生命", 470),
            ),
            self.cfg,
        )
        self.assertEqual(result.action, "lock")
        self.assertTrue(result.keep)

    def test_protection_outranks_core_rule(self):
        """保护排在核心属性规则之前：同样的词条，只把暴击从 10.0 换成满值 10.5。"""
        cfg = JudgeConfig(
            core_stats=frozenset({CRIT, CRIT_DMG, "攻击", "生命"}),
            enable_crit_check=False,
            min_valid_count=2,
        )
        junk = stats((CRIT, 10.0), ("防御", 40), ("共鸣效率", 8.0))
        self.assertEqual(judge(junk, cfg).action, "discard")      # 凑不齐核心 → 弃置

        perfect = stats((CRIT, MAX_CRIT), ("防御", 40), ("共鸣效率", 8.0))
        result = judge(perfect, cfg)
        self.assertNotEqual(result.action, "discard")             # 满值保护先手
        self.assertIn("满", result.reason)

    def test_almost_max_is_not_protected(self):
        # 差一点不算满：10.0 不是满暴击，照旧按双爆下限判弃置
        result = judge(stats((CRIT, 10.0), (CRIT_DMG, 12.6)), self.cfg)
        self.assertEqual(result.action, "discard")
        self.assertIn("双爆不达标", result.reason)

    def test_epsilon_tolerates_ocr_rounding(self):
        """OCR 读成 10.4 / 20.95 也算满 —— 容差 0.3 压在半个档距以内，别因读数误差漏掉极品。"""
        self.assertNotEqual(judge(stats((CRIT, 10.4), (CRIT_DMG, 12.6)), self.cfg).action,
                            "discard")
        self.assertNotEqual(judge(stats((CRIT, 6.3), (CRIT_DMG, 20.95)), self.cfg).action,
                            "discard")

    def test_can_be_disabled(self):
        """关掉之后完全回到原规则（需求：跟双爆不低于一样，可以启用或不启用）。"""
        cfg = JudgeConfig(enable_max_roll_lock=False)
        result = judge(stats((CRIT, MAX_CRIT), (CRIT_DMG, 12.6)), cfg)
        self.assertEqual(result.action, "discard")


class TestUnreachableValidCount(unittest.TestCase):
    """「有效词条数」超过有效集合条数时**不能按原值判**。

    声骸每种副词条只会出现一次，所以「有效词条数」的实际上限 = 有效集合的条数。
    默认配置只勾双爆（集合 2 条）而界面默认要求 ≥3 —— 2026-09-24 用户实测
    "声骸自动强化完全没用"就是这个：**每个声骸都在满级那一刻被判弃置**。
    """

    def test_unreachable_is_reported(self):
        cfg = JudgeConfig(min_valid_count=3, crit_min=0.0, crit_dmg_min=0.0)
        self.assertEqual(len(cfg.valid_stats), 2)
        self.assertTrue(cfg.min_valid_count_unreachable)
        self.assertEqual(cfg.effective_min_valid_count, 2)
        self.assertIn("达不到", cfg.criterion_warning())

    def test_reachable_has_no_warning(self):
        cfg = JudgeConfig(optional_stats=frozenset({"攻击百分比"}), min_valid_count=3)
        self.assertFalse(cfg.min_valid_count_unreachable)
        self.assertEqual(cfg.effective_min_valid_count, 3)
        self.assertEqual(cfg.criterion_warning(), "")

    def test_full_echo_with_both_crit_survives_default_config(self):
        """默认配置（只勾双爆、要求 ≥3）下的满级声骸：必须**上锁**而不是弃置。"""
        cfg = JudgeConfig(
            crit_min=DEFAULT_CRIT_MIN, crit_dmg_min=DEFAULT_CRIT_DMG_MIN,
            min_valid_count=3, enable_max_roll_lock=False,
        )
        result = judge(
            stats((CRIT, 9.3), (CRIT_DMG, 18.6), ("攻击", 40), ("生命", 500), ("防御", 40)),
            cfg,
        )
        self.assertEqual(result.action, "lock")
        self.assertTrue(result.keep)

    def test_reachable_count_still_enforced(self):
        """能达到了就照原值严格判：集合 4 条、要求 3 条，只出双爆 2 条 → 弃置。"""
        cfg = JudgeConfig(
            optional_stats=frozenset({"攻击百分比", "共鸣效率"}),
            min_valid_count=3, crit_min=0.0, crit_dmg_min=0.0,
            enable_max_roll_lock=False,
        )
        result = judge(
            stats((CRIT, 9.3), (CRIT_DMG, 18.6), ("攻击", 40), ("生命", 500), ("防御", 40)),
            cfg,
        )
        self.assertEqual(result.action, "discard")
        self.assertEqual(result.code, "valid")

    def test_discard_codes(self):
        """弃置原因分类码 —— 统计"为什么全被弃置"要用。"""
        crit_bad = judge(stats((CRIT, 6.3), (CRIT_DMG, 12.6)),
                         JudgeConfig(enable_max_roll_lock=False))
        self.assertEqual(crit_bad.code, "crit")

        core_missing = judge(
            stats(("攻击", 40), ("生命", 500), ("防御", 40), ("共鸣效率", 10.0)),
            JudgeConfig(min_valid_count=2, enable_max_roll_lock=False),
        )
        self.assertEqual(core_missing.code, "core")

        valid_short = judge(
            stats((CRIT, 9.3), (CRIT_DMG, 18.6), ("攻击", 40), ("生命", 500), ("防御", 40)),
            JudgeConfig(optional_stats=frozenset({"攻击百分比", "共鸣效率"}),
                        min_valid_count=3, enable_max_roll_lock=False),
        )
        self.assertEqual(valid_short.code, "valid")


from src.tools.game.echo_enhance.stats import format_result_report  # noqa: E402


class TestResultReport(unittest.TestCase):
    """结果报告排版（页面卡片 / 结束弹窗 / 任务流程 summary 共用这份）。"""

    def test_nothing_judged_gives_hint(self):
        text = format_result_report(checked=0, kept=0, dropped=0)
        self.assertIn("没有判定任何声骸", text)

    def test_basic_line(self):
        text = format_result_report(checked=12, kept=5, dropped=7)
        self.assertIn("判定 12 个", text)
        self.assertIn("符合条件 5", text)
        self.assertIn("弃置 7", text)

    def test_perfect_hidden_when_not_enabled(self):
        text = format_result_report(checked=3, kept=1, dropped=2, perfect=None)
        self.assertNotIn("满属性", text)

    def test_perfect_shown_when_enabled(self):
        text = format_result_report(checked=3, kept=2, dropped=1, perfect=1)
        self.assertIn("满属性 1", text)

    def test_reason_line_uses_human_names(self):
        text = format_result_report(checked=9, kept=2, dropped=7,
                                    tally={"crit": 4, "valid": 3})
        self.assertIn("弃置原因：双爆不达标 4、有效词条不足 3", text)

    def test_failed_reason_takes_priority(self):
        """异常中断时优先显示**真实原因**，别让用户去查界面。

        2026-09-25 实测：ok-ww 抛的是「强化设置需要开启阶段放入!」，
        界面却显示「请确认停在 背包 → 声骸 界面」，用户对着界面查了半天。
        """
        text = format_result_report(checked=0, kept=0, dropped=0,
                                    failed_reason="强化设置需要开启阶段放入!")
        self.assertIn("强化设置需要开启阶段放入!", text)
        self.assertNotIn("请确认停在", text)

    def test_failed_reason_ignored_when_something_judged(self):
        """真判定过声骸时，中断原因不该顶掉统计数字。"""
        text = format_result_report(checked=3, kept=1, dropped=2,
                                    failed_reason="随便什么原因")
        self.assertIn("判定 3 个", text)
        self.assertNotIn("随便什么原因", text)

    def test_blank_reason_keeps_legacy_hint(self):
        """空白原因等同于没传 —— 旧行为不能退化。"""
        for blank in (None, "", "   ", "\n"):
            with self.subTest(blank=blank):
                text = format_result_report(checked=0, kept=0, dropped=0,
                                            failed_reason=blank)
                self.assertIn("没有判定任何声骸", text)

    def test_unknown_reason_code_shown_raw(self):
        text = format_result_report(checked=1, kept=0, dropped=1,
                                    tally={"mystery": 1})
        self.assertIn("mystery 1", text)


from src.tools.game.echo_enhance.stats import parse_result_counts  # noqa: E402


class TestParseResultCounts(unittest.TestCase):
    """把报告文本读回成数字（任务页的「本轮报告 / 累计统计」靠它取数）。

    ⚠ 这是**往返测试**：改了 ``format_result_report`` 的排版就必须让这里继续过，
    否则任务页的统计会悄悄变成 0（谁都发现不了）。
    """

    def test_roundtrip(self):
        text = format_result_report(checked=12, kept=5, dropped=7)
        self.assertEqual(parse_result_counts(text),
                         {"checked": 12, "kept": 5, "dropped": 7})

    def test_roundtrip_with_perfect_and_tally(self):
        """带「满属性」和「弃置原因」两行时照样读得对。"""
        text = format_result_report(checked=9, kept=2, dropped=7, perfect=1,
                                    tally={"crit": 4, "valid": 3})
        self.assertEqual(parse_result_counts(text),
                         {"checked": 9, "kept": 2, "dropped": 7})

    def test_zero_counts_stay_zero(self):
        """没判定任何声骸 → 全 0，不会把提示语里的数字误抓出来。"""
        text = format_result_report(checked=0, kept=0, dropped=0)
        self.assertEqual(parse_result_counts(text),
                         {"checked": 0, "kept": 0, "dropped": 0})

    def test_interrupted_task_yields_zeros(self):
        """异常中断（只有原因那句话）→ 0，不该编数字。"""
        text = format_result_report(checked=0, kept=0, dropped=0,
                                    failed_reason="强化设置需要开启阶段放入!")
        self.assertEqual(parse_result_counts(text),
                         {"checked": 0, "kept": 0, "dropped": 0})

    def test_garbage_input_is_safe(self):
        for bad in ("", None, "完全不是报告", "判定 abc 个"):
            with self.subTest(bad=bad):
                self.assertEqual(parse_result_counts(bad),
                                 {"checked": 0, "kept": 0, "dropped": 0})

    def test_discard_reason_line_does_not_override_total(self):
        """★ 回归护栏：「弃置原因：双爆不达标 4」里的 4 **不能**顶掉总的弃置数。

        正则要的是「弃置 N」（后面不跟原因），而原因行是「… 4」——
        这条测试就是防止有人把正则放宽成 ``弃置.*?(\\d+)``。
        """
        text = format_result_report(checked=9, kept=2, dropped=7,
                                    tally={"crit": 4})
        self.assertEqual(parse_result_counts(text)["dropped"], 7)


if __name__ == "__main__":
    unittest.main(verbosity=2)
