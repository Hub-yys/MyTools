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


class TestFlowType(unittest.TestCase):
    def test_default_is_unclassified(self):
        flow = TaskFlow()
        self.assertEqual(flow.type_key, "")
        self.assertEqual(flow.type_text(), "")      # 未分类不显示标签

    def test_normalized_on_construct(self):
        """构造时就把坏 key 收拾掉，不用等到存盘。"""
        flow = TaskFlow(type_key="game", sub_key="不存在")
        self.assertEqual((flow.type_key, flow.sub_key), ("game", "generic"))

    def test_dict_roundtrip_keeps_type(self):
        original = TaskFlow(
            name="日常", type_key="game", sub_key="wuwa", steps=[tool()]
        )
        restored = TaskFlow.from_dict(original.to_dict())
        self.assertEqual((restored.type_key, restored.sub_key), ("game", "wuwa"))
        self.assertEqual(restored.type_text(), "游戏 · 鸣潮")

    def test_old_json_without_type_is_unclassified(self):
        """老版本存下来的 JSON 没有这两个字段 —— 读进来必须是未分类，不能炸。"""
        old = {"id": "abc", "name": "老流程", "steps": [tool().to_dict()],
               "updated_at": "2026-09-01 10:00:00"}
        flow = TaskFlow.from_dict(old)
        self.assertEqual((flow.type_key, flow.sub_key), ("", ""))
        self.assertEqual(flow.validate(), [])

    def test_store_persists_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "tasks.json"
            store = TaskStore(path)
            flow = store.add(TaskFlow(name="x", type_key="office", sub_key="generic",
                                      steps=[tool()]))
            restored = TaskStore(path).get(flow.id)
            self.assertEqual((restored.type_key, restored.sub_key), ("office", "generic"))
            self.assertEqual(restored.type_text(), "办公 · 通用")


if __name__ == "__main__":
    unittest.main(verbosity=2)
