"""「成套声骸」的套装结构（43311 / 44111 / 4311 …）单元测试。

    python tests/test_set_plan.py

用户 2026-11-07 批注："成套可以自由输入成套时的数字，比如现在现有 44111、
43311，我可以输入 4311，这时强化好 1 个 4C、1 个 3C 就跳过其他 4C、3C，
但是这个输入有校验，数字长度最多为 5，数字加起来不能超过 12"。

**纯逻辑**（不弹 Qt 框、不开引擎）：所有规则都在 ``core/tasks.py``，
GUI / Web 两侧都调它 —— 这里钉死规则本身，免得两边各写一套。
"""

from __future__ import annotations

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.core.tasks import (  # noqa: E402
    DEFAULT_SET_PLAN,
    SET_BONUS_PLANS,
    SET_PLAN_MAX_COST,
    SET_PLAN_MAX_LEN,
    SET_PLAN_PRESETS,
    format_set_plan,
    normalize_set_plan,
    parse_set_plan,
    set_plan_error,
)


class TestLimits(unittest.TestCase):
    """用户明确给的三个数字 —— 写死，别偷偷放宽。"""

    def test_max_length_is_5(self):
        """长度上限 5 = 游戏里 5 个孔位。"""
        self.assertEqual(SET_PLAN_MAX_LEN, 5)

    def test_max_cost_is_12(self):
        """数字之和上限 12 = 五个孔位的 COST 总容量。"""
        self.assertEqual(SET_PLAN_MAX_COST, 12)

    def test_presets_are_the_two_existing_ones(self):
        """现有两条流程用的 43311 / 44111 仍是预设（一键填）。"""
        self.assertEqual(SET_PLAN_PRESETS, ("43311", "44111"))
        self.assertEqual(DEFAULT_SET_PLAN, "43311")


class TestNormalize(unittest.TestCase):
    """输入规整：全角、空格都吃掉，剩下的才是数字串。"""

    def test_plain(self):
        self.assertEqual(normalize_set_plan("4311"), "4311")

    def test_strips_all_whitespace(self):
        """★ 用户可能手打「4 3 1 1」—— 空格是排版噪音，不是语法。"""
        self.assertEqual(normalize_set_plan(" 4 3 1 1 "), "4311")
        self.assertEqual(normalize_set_plan("4\t3\n1 1"), "4311")

    def test_fullwidth_digits(self):
        """中文输入法下容易打出全角数字，直接认。"""
        self.assertEqual(normalize_set_plan("４３１１"), "4311")

    def test_none_and_empty(self):
        self.assertEqual(normalize_set_plan(None), "")  # type: ignore[arg-type]
        self.assertEqual(normalize_set_plan(""), "")
        self.assertEqual(normalize_set_plan("   "), "")


class TestParse(unittest.TestCase):
    """数字串 → ``{Cost: 需要几种}``（引擎只吃这个字典）。"""

    def test_user_example_4311(self):
        """★ 用户举的例子：4311 = 4C×1 + 3C×1 + 1C×2。

        也就是「强化好 1 个 4C、1 个 3C 之后就跳过其他 4C、3C」。
        """
        self.assertEqual(parse_set_plan("4311"), {4: 1, 3: 1, 1: 2})

    def test_existing_43311(self):
        self.assertEqual(parse_set_plan("43311"), {4: 1, 3: 2, 1: 2})

    def test_existing_44111(self):
        self.assertEqual(parse_set_plan("44111"), {4: 2, 1: 3})

    def test_order_independent(self):
        """只数各档的个数，不关心书写顺序。"""
        self.assertEqual(parse_set_plan("1341"), parse_set_plan("4311"))
        self.assertEqual(parse_set_plan("31143"), parse_set_plan("43311"))

    def test_single_digit(self):
        """只强化一个 4C 也合法（和 ≤12、长度 ≤5 都满足）。"""
        self.assertEqual(parse_set_plan("4"), {4: 1})
        self.assertEqual(parse_set_plan("1"), {1: 1})

    def test_uses_given_lenient_text(self):
        """parse 先 normalize —— 带空格/全角也能解析。"""
        self.assertEqual(parse_set_plan("4 3 1 1"), {4: 1, 3: 1, 1: 2})

    def test_invalid_raises_value_error(self):
        """非法输入抛 ``ValueError``，消息就是给人看的那句。"""
        for bad in ("", "   ", "123", "345", "99999", "111111", "4a11"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    parse_set_plan(bad)


class TestErrorMessages(unittest.TestCase):
    """``set_plan_error``：合法返回空串，非法返回中文原因（GUI 直接显示）。

    ★ 2026-11-08 用户逐条指定了提示语原文：

    > 如果超过5位保存时应该报错提示声骸数量超过5个，数字之和超过12提示
    > Cost数超过12，数字不是4、3、1提示只能输入4、3、1，
    > 输入空或未输入提示自定义时不能输入为空

    所以下面按**原话**断言，不写「包含某关键词」那种松散的判断。
    """

    def test_valid_returns_empty(self):
        for good in ("4", "4311", "43311", "44111", "344", "11111"):
            with self.subTest(good=good):
                self.assertEqual(set_plan_error(good), "")

    def test_empty(self):
        """★ 「输入空或未输入提示自定义时不能输入为空」。"""
        self.assertEqual(set_plan_error(""), "自定义时不能输入为空")
        self.assertEqual(set_plan_error("   "), "自定义时不能输入为空")
        self.assertEqual(set_plan_error(None), "自定义时不能输入为空")  # type: ignore[arg-type]

    def test_non_digit(self):
        """字母/中文/符号都不行。"""
        for bad in ("abc", "43a", "4311!", "四三一一"):
            with self.subTest(bad=bad):
                self.assertEqual(set_plan_error(bad), "只能输入数字（0-9）")

    def test_too_long(self):
        """★ 「超过5位…提示声骸数量超过5个」（用户说"数字长度最多为 5"）。"""
        self.assertEqual(
            set_plan_error("433111"), "声骸数量超过 5 个（现在是 6 个）")
        self.assertEqual(
            set_plan_error("444444"), "声骸数量超过 5 个（现在是 6 个）")

    def test_unknown_cost(self):
        """★ 「数字不是4、3、1提示只能输入4、3、1」。

        不静默忽略：``43211`` 加起来只有 11 也照样拒绝，
        否则用户以为 2C 那档生效了，实际强化时会被跳过。
        """
        self.assertEqual(
            set_plan_error("2"), "只能输入 4、3、1（游戏里没有 2C 声骸）")
        self.assertEqual(
            set_plan_error("43211"), "只能输入 4、3、1（游戏里没有 2C 声骸）")
        for bad in ("5", "0", "425"):
            with self.subTest(bad=bad):
                self.assertIn("只能输入 4、3、1", set_plan_error(bad))

    def test_sum_over_12(self):
        """★ 「数字之和超过12提示Cost数超过12」。"""
        self.assertEqual(
            set_plan_error("44444"), "Cost 数超过 12（现在是 20）")
        self.assertEqual(
            set_plan_error("4444"), "Cost 数超过 12（现在是 16）")

    def test_error_order_length_before_sum(self):
        """两样都错时先说**长度**（用户先看得到的那个）。"""
        self.assertEqual(
            set_plan_error("444444"), "声骸数量超过 5 个（现在是 6 个）")

    def test_boundaries_accepted(self):
        """卡在边界上的必须放行：正好 5 位、正好 12。

        （注意 ``44310`` 这种不行 —— 长度虽然只有 5，但 0C 不存在。）
        """
        self.assertEqual(set_plan_error("444"), "")     # 和 = 12、长度 3
        self.assertEqual(set_plan_error("4431"), "")    # 和 = 12
        self.assertEqual(set_plan_error("43111"), "")   # 和 = 10、长度 5
        self.assertEqual(set_plan_error("1111"), "")    # 和 = 4


class TestFormat(unittest.TestCase):
    """``format_set_plan`` —— 给人看的一行（log / GUI 提示共用）。"""

    def test_user_example(self):
        self.assertEqual(format_set_plan({4: 1, 3: 1, 1: 2}),
                         "4C×1 + 3C×1 + 1C×2")

    def test_sorted_by_cost_desc(self):
        """档位从大到小排 —— 和流程名 ``43311`` 的读法一致。"""
        self.assertEqual(format_set_plan({1: 2, 3: 1, 4: 1}),
                         "4C×1 + 3C×1 + 1C×2")

    def test_empty(self):
        self.assertEqual(format_set_plan({}), "")
        self.assertEqual(format_set_plan(None), "")  # type: ignore[arg-type]


class TestBackwardCompat(unittest.TestCase):
    """``SET_BONUS_PLANS`` 老表还在（老代码/配置可能还引用）。"""

    def test_matches_parse(self):
        for name in SET_PLAN_PRESETS:
            with self.subTest(name=name):
                self.assertEqual(SET_BONUS_PLANS[name], parse_set_plan(name))

    def test_exact_values(self):
        self.assertEqual(SET_BONUS_PLANS["43311"], {4: 1, 3: 2, 1: 2})
        self.assertEqual(SET_BONUS_PLANS["44111"], {4: 2, 1: 3})


class TestFlowNameRoundTrip(unittest.TestCase):
    """流程名里的结构：写进去 → 读回来，必须一模一样。

    这是「成套」唯一落盘的地方 —— 名字读漏了，任务跑起来就是全员强化。
    """

    def setUp(self):
        from src.gui.config_names import (  # noqa: PLC0415
            flow_character_of, flow_level_of, flow_name_with_level,
            flow_set_plan_of,
        )
        self.flow_name_with_level = flow_name_with_level
        self.flow_set_plan_of = flow_set_plan_of
        self.flow_character_of = flow_character_of
        self.flow_level_of = flow_level_of

    def test_user_example_4311(self):
        name = self.flow_name_with_level("绯雪", "小毕业", "4311")
        self.assertEqual(name, "绯雪-声骸自动强化（小毕业 4311）")
        self.assertEqual(self.flow_set_plan_of(name), "4311")
        self.assertEqual(self.flow_level_of(name), "小毕业")
        self.assertEqual(self.flow_character_of(name), "绯雪")

    def test_existing_presets_still_round_trip(self):
        for plan in SET_PLAN_PRESETS:
            with self.subTest(plan=plan):
                name = self.flow_name_with_level("绯雪", "大毕业", plan)
                self.assertEqual(self.flow_set_plan_of(name), plan)

    def test_no_plan(self):
        """不成套：名字里不带结构，读回来是空串（= 全员按配置强化）。"""
        name = self.flow_name_with_level("绯雪", "大毕业")
        self.assertEqual(name, "绯雪-声骸自动强化（大毕业）")
        self.assertEqual(self.flow_set_plan_of(name), "")
        self.assertEqual(self.flow_level_of(name), "大毕业")

    def test_renaming_keeps_single_suffix(self):
        """★ 编辑老流程时名字是完整的 —— 再写一次不能变成两个括号。"""
        once = self.flow_name_with_level("绯雪", "小毕业", "4311")
        twice = self.flow_name_with_level(once, "小毕业", "4311")
        self.assertEqual(twice, once)

    def test_switching_plan(self):
        """把 43311 的流程改成 4311 —— 旧结构要被替换掉，不是叠一起。"""
        old = self.flow_name_with_level("绯雪", "小毕业", "43311")
        new = self.flow_name_with_level(old, "小毕业", "4311")
        self.assertEqual(new, "绯雪-声骸自动强化（小毕业 4311）")

    def test_edit_rebuild_keeps_level_and_plan(self):
        """★ 「修改」弹框只让人选角色，重拼名字时**不能把括号整段抹掉**。

        ``TaskEditorDialog._collect()`` 就是这么拼的：从老名字里取出
        级别 / 结构，再和下拉里的角色拼回去。以前直接用
        ``flow_name_for(角色)``，等于把成套结构静默清空 → 跑起来变成
        「不成套」。这里锁住这条重建路径。
        """
        old = self.flow_name_with_level("绯雪", "大毕业", "4311")
        rebuilt = self.flow_name_with_level(
            self.flow_character_of(old),
            self.flow_level_of(old),
            self.flow_set_plan_of(old),
        )
        self.assertEqual(rebuilt, old)
        self.assertEqual(self.flow_set_plan_of(rebuilt), "4311")

    def test_edit_rebuild_keeps_plan_when_switching_character(self):
        """换角色也只换角色 —— 级别和套装结构要跟着走。"""
        old = self.flow_name_with_level("绯雪", "小毕业", "4311")
        rebuilt = self.flow_name_with_level(
            "爱弥斯",
            self.flow_level_of(old),
            self.flow_set_plan_of(old),
        )
        self.assertEqual(rebuilt, "爱弥斯-声骸自动强化（小毕业 4311）")


if __name__ == "__main__":
    unittest.main(verbosity=2)
