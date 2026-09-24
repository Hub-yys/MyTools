"""任务类型（两级下拉）与流程里类型字段的单元测试（纯逻辑）。

    python tests/test_task_types.py
"""

from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.core.categories import ToolCategory  # noqa: E402
from src.core.task_types import (  # noqa: E402
    UNCLASSIFIED_KEY,
    UNCLASSIFIED_NAME,
    describe,
    normalize,
    sub_options,
    type_options,
)
from src.core.tasks import STEP_TOOL, TaskFlow, TaskStep, TaskStore  # noqa: E402

# ★ 类型推导要查 ToolRegistry（工具的 category 声明）—— 不发现工具就推不出类型，
#   测试会变成"未分类"而假绿。这里显式发现一次。
from src.tools import discover_tools  # noqa: E402

discover_tools()


def tool() -> TaskStep:
    return TaskStep(type=STEP_TOOL, key="echo_enhance", name="声骸自动强化")


class TestTaxonomy(unittest.TestCase):
    def test_type_options_first_is_unclassified(self):
        """未分类排最前 = 默认值（老流程没有类型，落到这里最诚实）。"""
        self.assertEqual(type_options()[0], (UNCLASSIFIED_KEY, UNCLASSIFIED_NAME))

    def test_type_options_follow_tool_categories(self):
        """一级直接复用工具分类：加一个分类，下拉里自动多一项。"""
        keys = [key for key, _ in type_options()[1:]]
        self.assertEqual(keys, [c.key for c in ToolCategory.sorted_all()])
        self.assertIn("game", keys)
        self.assertIn("office", keys)

    def test_sub_options_game_has_wuwa(self):
        self.assertEqual([k for k, _ in sub_options("game")], ["generic", "wuwa"])
        self.assertEqual(dict(sub_options("game"))["wuwa"], "鸣潮")

    def test_sub_options_unclassified_is_empty(self):
        """未分类没有二级 —— 界面上二级下拉要置灰。"""
        self.assertEqual(sub_options(UNCLASSIFIED_KEY), [])

    def test_sub_options_unknown_type_is_empty(self):
        self.assertEqual(sub_options("乱写的分类"), [])

    def test_normalize_unknown_type_falls_back_to_unclassified(self):
        self.assertEqual(normalize("乱写的分类", "wuwa"), (UNCLASSIFIED_KEY, ""))

    def test_normalize_unknown_sub_falls_back_to_first(self):
        self.assertEqual(normalize("game", "不存在的游戏"), ("game", "generic"))
        self.assertEqual(normalize("game", "wuwa"), ("game", "wuwa"))

    def test_describe(self):
        self.assertEqual(describe("game", "wuwa"), "游戏 · 鸣潮")
        self.assertEqual(describe("office", "generic"), "办公 · 通用")
        self.assertEqual(describe(UNCLASSIFIED_KEY, ""), "")


class TestDerivedType(unittest.TestCase):
    """★ 任务类型现在**从步骤推导**（2026-09-26 用户要求去掉那两个下拉）。

    原来自定义一个 ``type_key`` / ``sub_key`` 存在流程上，用户手选。
    用户要求去掉：类型本来就是"这条流程属于哪一类"，看它放了什么工具就知道，
    不该再让人手填一遍。存盘里也不再写那两个字段。
    """

    def test_no_tool_steps_is_unclassified(self):
        self.assertEqual(TaskFlow().derived_type(), ("", ""))
        self.assertEqual(TaskFlow().type_text(), "")     # 未分类不显示标签

    def test_only_markers_is_unclassified(self):
        """只有开始/结束标记（没放工具）→ 未分类。"""
        flow = TaskFlow(steps=[TaskStep(type="start", key="start", name="开始"),
                               TaskStep(type="end", key="end", name="结束")])
        self.assertEqual(flow.derived_type(), ("", ""))

    def test_game_tool_derives_game_wuwa(self):
        """有游戏类工具 → 游戏 · 鸣潮。

        具体游戏直接定成 ``wuwa`` —— 本工具目前只有鸣潮一个客户端判据，
        定成它，「开始」步的前置检查才能真去查客户端。
        """
        flow = TaskFlow(steps=[tool()])
        self.assertEqual(flow.derived_type(), ("game", "wuwa"))
        self.assertEqual(flow.type_text(), "游戏 · 鸣潮")
        self.assertIsNotNone(flow.client_spec(), "推导出游戏类型就该带得出客户端判据")

    def test_non_game_tool_derives_its_category(self):
        """非游戏类工具 → 那个分类 + 通用（不检查游戏客户端）。"""
        flow = TaskFlow(steps=[TaskStep(type=STEP_TOOL, key="wuwa_library_update",
                                        name="资源库更新")])
        self.assertEqual(flow.derived_type(), ("data", "generic"))
        self.assertIsNone(flow.client_spec())

    def test_game_wins_when_mixed(self):
        """流程里既有游戏工具又有别的 → 按游戏算（前置检查最该做的那件事）。"""
        flow = TaskFlow(steps=[
            TaskStep(type=STEP_TOOL, key="wuwa_library_update", name="资源库更新"),
            tool(),
        ])
        self.assertEqual(flow.derived_type(), ("game", "wuwa"))

    def test_unknown_tool_key_falls_back_to_unclassified(self):
        """key 已失效（工具卸载了）→ 当未分类，不能炸。"""
        flow = TaskFlow(steps=[TaskStep(type=STEP_TOOL, key="早就没了的工具", name="x")])
        self.assertEqual(flow.derived_type(), ("", ""))

    def test_stored_type_is_no_longer_written(self):
        """★ 存盘里**不再有** type_key / sub_key（存了会过期、还会误导）。"""
        flow = TaskFlow(name="日常", steps=[tool()])
        data = flow.to_dict()
        self.assertNotIn("type_key", data)
        self.assertNotIn("sub_key", data)

    def test_old_json_with_type_fields_is_ignored(self):
        """老 JSON 里留着那两个字段 → 直接忽略，类型照样从步骤推导出来。"""
        old = {"id": "abc", "name": "老流程", "steps": [tool().to_dict()],
               "type_key": "office", "sub_key": "generic",
               "updated_at": "2026-09-01 10:00:00"}
        flow = TaskFlow.from_dict(old)
        self.assertEqual(flow.derived_type(), ("game", "wuwa"),
                         "按步骤推导，不该被老数据里的 office 带跑")
        self.assertEqual(flow.validate(), [])

    def test_store_roundtrip_keeps_steps_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "tasks.json"
            store = TaskStore(path)
            flow = store.add(TaskFlow(name="x", steps=[tool()]))
            restored = TaskStore(path).get(flow.id)
            self.assertEqual(restored.derived_type(), ("game", "wuwa"))
            self.assertEqual(restored.type_text(), "游戏 · 鸣潮")
            raw = path.read_text(encoding="utf-8")
            self.assertNotIn("type_key", raw, "存盘里不该再出现 type_key")


if __name__ == "__main__":
    unittest.main(verbosity=2)
