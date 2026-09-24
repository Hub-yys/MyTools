"""任务流程名的自动后缀（角色 → 「角色-声骸自动强化」）单元测试。

    python tests/test_flow_name.py

用户 2026-09-28 批注："任务这里也是选角色，保存时自动加后缀声骸自动强化"。

**纯逻辑**（不弹 Qt 框）：后缀的拼/拆都在 ``gui/config_names.py`` 里，
这里覆盖它的边界 —— 尤其是**存量流程名**（手打、不带连字符）的兼容。
"""

from __future__ import annotations

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.gui.config_names import (  # noqa: E402
    FLOW_NAME_SUFFIX,
    flow_character_of,
    flow_name_for,
    is_flow_name_of_character,
    live_flow_avatar,
)


class TestFlowNameFor(unittest.TestCase):
    """角色名 → 流程名。"""

    def test_appends_suffix(self):
        self.assertEqual(flow_name_for("绯雪"), f"绯雪{FLOW_NAME_SUFFIX}")
        self.assertEqual(flow_name_for("漂泊者·衍射"),
                         f"漂泊者·衍射{FLOW_NAME_SUFFIX}")

    def test_suffix_is_the_documented_one(self):
        """后缀字面量钉死 —— 它是用户直接指定的（"自动加后缀声骸自动强化"）。"""
        self.assertEqual(FLOW_NAME_SUFFIX, "-声骸自动强化")

    def test_idempotent(self):
        """★ 关键：编辑老流程时名字是完整的，再补一次不能变成两个后缀。"""
        once = flow_name_for("绯雪")
        self.assertEqual(flow_name_for(once), once)
        self.assertEqual(flow_name_for(flow_name_for(once)), once)

    def test_legacy_suffix_is_not_appended_again(self):
        """存量名字「绯雪声骸自动强化」（**没连字符**）也不该再补一个后缀。"""
        legacy = "绯雪声骸自动强化"
        self.assertEqual(flow_name_for(legacy), legacy)

    def test_strips_whitespace(self):
        self.assertEqual(flow_name_for("  绯雪  "), f"绯雪{FLOW_NAME_SUFFIX}")

    def test_blank_is_blank(self):
        for blank in ("", "   ", None):
            with self.subTest(blank=blank):
                self.assertEqual(flow_name_for(blank), "")


class TestFlowCharacterOf(unittest.TestCase):
    """流程名 → 角色名（编辑时回填角色下拉）。"""

    def test_strips_new_suffix(self):
        self.assertEqual(flow_character_of("绯雪-声骸自动强化"), "绯雪")

    def test_strips_legacy_suffix_without_hyphen(self):
        """★ 存量流程名就是这么存的（``data/tasks.json`` 实测）——
        认不出来会打开「修改」时把角色下拉留空、还误报一句"这不是一个角色"。"""
        self.assertEqual(flow_character_of("绯雪声骸自动强化"), "绯雪")
        self.assertEqual(flow_character_of("爱弥斯声骸自动强化"), "爱弥斯")
        self.assertEqual(flow_character_of("卡缇希娅声骸自动强化"), "卡缇希娅")

    def test_unknown_name_is_returned_as_is(self):
        """不是这个格式的名字原样返回 —— 不猜一个角色出来。"""
        self.assertEqual(flow_character_of("日常清声骸"), "日常清声骸")

    def test_roundtrip(self):
        for who in ("绯雪", "爱弥斯", "漂泊者·衍射"):
            with self.subTest(who=who):
                self.assertEqual(flow_character_of(flow_name_for(who)), who)

    def test_blank(self):
        for blank in ("", "   ", None):
            with self.subTest(blank=blank):
                self.assertEqual(flow_character_of(blank), "")

    def test_suffix_alone_is_not_over_stripped(self):
        """名字**就是**后缀时不该被剥成空串（会变成"没选角色"的怪状态）。"""
        self.assertEqual(flow_character_of("声骸自动强化"), "声骸自动强化")


class TestIsFlowNameOfCharacter(unittest.TestCase):
    """形状判断：要不要给用户弹"旧名字不是角色"那条提示。"""

    def test_recognises_both_forms(self):
        self.assertTrue(is_flow_name_of_character("绯雪-声骸自动强化"))
        self.assertTrue(is_flow_name_of_character("绯雪声骸自动强化"))

    def test_free_form_name_is_not_recognised(self):
        self.assertFalse(is_flow_name_of_character("日常清声骸"))
        self.assertFalse(is_flow_name_of_character(""))

    def test_real_stored_names_are_recognised(self):
        """★ 回归护栏：拿真实 tasks.json 里的三个名字试一遍。"""
        for name in ("绯雪声骸自动强化", "爱弥斯声骸自动强化", "卡缇希娅声骸自动强化"):
            with self.subTest(name=name):
                self.assertTrue(is_flow_name_of_character(name),
                                f"{name} 不被认出来 → 打开修改会误报一条警告")


class TestLiveFlowAvatar(unittest.TestCase):
    """任务行上的角色头像（用户 2026-09-28："这里也加上显示角色头像吧"）。"""

    @classmethod
    def setUpClass(cls):
        from src.core import game_data

        game_data.ensure_loaded()
        cls._chars = {c.name: c.avatar for c in game_data.CHARACTERS}

    def _flow(self, name: str):
        from src.core.tasks import TaskFlow

        return TaskFlow(name=name)

    def test_finds_avatar_from_flow_name(self):
        """★ 主路径：流程名 = 角色 + 后缀 → 查得到那个角色的头像。"""
        # 挑一个**确实有头像**的角色（别赌某个角色一定有图）
        who = next((n for n, a in self._chars.items() if a), None)
        self.assertIsNotNone(who, "数据集里一个带头像的角色都没有，测不了")
        self.assertEqual(live_flow_avatar(self._flow(flow_name_for(who))),
                         self._chars[who])

    def test_legacy_name_without_hyphen_still_works(self):
        """★ 存量流程名（手打、没连字符）也要查得到头像。

        认不出来的话，用户那三条老流程升级后头像全是空的。
        """
        who = next((n for n, a in self._chars.items() if a), None)
        self.assertTrue(live_flow_avatar(self._flow(f"{who}声骸自动强化")),
                        f"{who}声骸自动强化 查不到头像")

    def test_character_without_avatar_is_blank(self):
        """数据集里没头像的角色 → 空串（**不画占位图**）。"""
        who = next((n for n, a in self._chars.items() if not a), None)
        if who is None:
            self.skipTest("数据集里所有角色都有头像，测不到这个分支")
        self.assertEqual(live_flow_avatar(self._flow(flow_name_for(who))), "")

    def test_free_form_name_is_blank(self):
        """老流程的自由名字（「日常清声骸」）→ 空串，不能猜出一个角色来。"""
        self.assertEqual(live_flow_avatar(self._flow("日常清声骸")), "")

    def test_blank_name_is_blank(self):
        for blank in ("", "   "):
            with self.subTest(blank=blank):
                self.assertEqual(live_flow_avatar(self._flow(blank)), "")

    def test_missing_name_attribute_is_safe(self):
        """对象没有 name（坏数据）也不该炸 —— 留空就行。"""
        self.assertEqual(live_flow_avatar(object()), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
