"""任务流程模型 + 存储的单元测试（纯逻辑，不碰网络和 Qt）。

    python tests/test_tasks.py
"""

from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.core.tasks import (  # noqa: E402
    STEP_CONFIG,
    STEP_TOOL,
    TaskFlow,
    TaskStep,
    TaskStore,
    bind_configs_to_tools,
)


def tool(key: str = "echo_enhance", name: str = "声骸自动强化") -> TaskStep:
    return TaskStep(type=STEP_TOOL, key=key, name=name)


def config(key: str = "cfg1", name: str = "景燃") -> TaskStep:
    return TaskStep(type=STEP_CONFIG, key=key, name=name)


class TestTaskStep(unittest.TestCase):
    def test_describe(self):
        self.assertEqual(tool().describe(), "[工具] 声骸自动强化")
        self.assertEqual(config().describe(), "[配置] 景燃")

    def test_from_dict_bad_type_falls_back_to_tool(self):
        step = TaskStep.from_dict({"type": "乱写", "key": "x", "name": "y"})
        self.assertTrue(step.is_tool)


class TestTaskFlow(unittest.TestCase):
    def test_validate_empty(self):
        errors = TaskFlow().validate()
        self.assertIn("任务名称为必填项", errors)
        self.assertIn("流程里至少要有一步", errors)

    def test_validate_needs_a_tool(self):
        flow = TaskFlow(name="x", steps=[config()])
        self.assertIn("流程里至少要有一个工具步骤", flow.validate())

    def test_validate_passes(self):
        flow = TaskFlow(name="日常", steps=[tool(), config()])
        self.assertEqual(flow.validate(), [])

    def test_bindings_config_attaches_to_nearest_tool_above(self):
        """★ 旧行为不变：配置**上面**的工具就是它的归属。"""
        flow = TaskFlow(
            name="x",
            steps=[tool(name="A"), config(name="c1"), config(name="c2"), tool(name="B")],
        )
        bindings = flow.tool_bindings()
        self.assertEqual(len(bindings), 2)
        self.assertEqual([c.name for c in bindings[0]["configs"]], ["c1", "c2"])
        self.assertEqual(bindings[1]["configs"], [])

    def test_bindings_orphan_configs_fall_through_to_tool_below(self):
        """★ 2026-09-27 修：前面没有工具的配置，**改绑给下面的工具**。

        用户的流程正是「开始 → 配置「绯雪-声骸筛选」 → 配置「绯雪-声骸强化」
        → 工具「声骸自动强化」」—— 读起来就是"先筛选、再强化"，非常自然。
        旧逻辑因为那时还没扫到任何工具（``result`` 是空的），把它们**直接丢掉**
        ⇒ 运行时"配置挂着却不生效"，用户报「进去就直接声骸强化、根本没筛选」。

        这种**静默失效**（不报错、流程看着完全正常）比报错难查得多。
        """
        steps = [config(name="绯雪-声骸筛选"), config(name="绯雪-声骸强化"),
                 tool(name="声骸自动强化")]
        bindings = bind_configs_to_tools(steps)
        self.assertEqual(len(bindings), 1)
        self.assertEqual([c.name for c in bindings[0]["configs"]],
                         ["绯雪-声骸筛选", "绯雪-声骸强化"])

    def test_bindings_both_tools_get_their_own_configs(self):
        """上下都有工具时各归各的：悬空的顺延到**下面**那个，不当"给最近的一个"。"""
        flow = TaskFlow(name="x", steps=[
            config(name="悬空"), tool(name="A"), config(name="c1"), tool(name="B")])
        bindings = flow.tool_bindings()
        self.assertEqual([c.name for c in bindings[0]["configs"]], ["悬空", "c1"])
        self.assertEqual(bindings[1]["configs"], [])

    def test_bindings_keep_config_order(self):
        """绑到同一个工具时，配置要保持流程里的先后顺序。"""
        steps = [config(name="c1"), tool(name="A"), config(name="c2")]
        bindings = bind_configs_to_tools(steps)
        self.assertEqual([c.name for c in bindings[0]["configs"]], ["c1", "c2"])

    def test_bindings_no_tool_at_all(self):
        """流程里一个工具都没有 → 配置无处可绑（``validate()`` 也会拦）。"""
        self.assertEqual(bind_configs_to_tools([config(), config()]), [])

    def test_summary(self):
        flow = TaskFlow(name="x", steps=[tool(), config()])
        self.assertEqual(flow.summary(), "声骸自动强化 → 景燃")

    def test_dict_roundtrip(self):
        original = TaskFlow(name="日常", steps=[tool(), config(key="abc")])
        restored = TaskFlow.from_dict(original.to_dict())
        self.assertEqual(restored.name, "日常")
        self.assertEqual([s.type for s in restored.steps], [STEP_TOOL, STEP_CONFIG])
        self.assertEqual([s.key for s in restored.steps], ["echo_enhance", "abc"])


class TestStore(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = pathlib.Path(self._tmp.name) / "tasks.json"
        self.store = TaskStore(self.path)

    def tearDown(self):
        self._tmp.cleanup()

    def test_add_assigns_id_and_time(self):
        flow = self.store.add(TaskFlow(name="x", steps=[tool()]))
        self.assertTrue(flow.id)
        self.assertTrue(flow.updated_at)
        self.assertEqual(len(self.store), 1)

    def test_update_remove(self):
        flow = self.store.add(TaskFlow(name="旧名", steps=[tool()]))
        flow.name = "新名"
        self.assertTrue(self.store.update(flow))
        self.assertEqual(self.store.get(flow.id).name, "新名")
        self.assertTrue(self.store.remove(flow.id))
        self.assertEqual(len(self.store), 0)
        self.assertFalse(self.store.remove(flow.id))

    def test_persist_and_reload(self):
        flow = self.store.add(TaskFlow(name="x", steps=[tool(), config()]))
        fresh = TaskStore(self.path)
        restored = fresh.get(flow.id)
        self.assertEqual(restored.name, "x")
        self.assertEqual([s.describe() for s in restored.steps], ["[工具] 声骸自动强化", "[配置] 景燃"])

    def test_missing_and_corrupted_file_are_empty(self):
        self.assertEqual(len(self.store), 0)
        self.assertFalse(self.path.exists())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("{ 坏的", encoding="utf-8")
        self.assertEqual(len(TaskStore(self.path)), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
