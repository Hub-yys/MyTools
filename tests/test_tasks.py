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
    flows_using_config,
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


class TestFlowsUsingConfig(unittest.TestCase):
    """★ 配置被任务流程引用时**不能删除**（用户 2026-09-28 要求）。

    规则："已完成任务流程里使用的配置，不能直接删除配置，需要先删除任务，
    才能删除配置"。

    这是纯逻辑（不弹框），界面上那两个删除入口都调它。
    """

    def _flow(self, name: str, *steps: TaskStep) -> TaskFlow:
        return TaskFlow(name=name, steps=list(steps))

    def _cfg(self, key: str, kind: str = "loadout",
             name: str = "景燃") -> TaskStep:
        return TaskStep(type=STEP_CONFIG, key=key, name=name, config_kind=kind)

    def test_matches_by_id(self):
        flow = self._flow("流程A", tool(), self._cfg("id-123"))
        self.assertEqual(flows_using_config([flow], "loadout", "id-123"),
                         ["流程A"])

    def test_returns_empty_when_unused(self):
        """没被引用的配置 → 空列表（可以删）。"""
        flow = self._flow("流程A", tool(), self._cfg("id-123"))
        self.assertEqual(flows_using_config([flow], "loadout", "别的id"), [])

    def test_matches_by_name_for_legacy_flows(self):
        """★ 老流程步骤里存的是**角色名**而不是 id（2026-09-26 之前）。

        只比 id 的话这种引用会被漏掉、配置照样能删出事 —— 所以名字也要比。
        """
        flow = self._flow("老流程", tool(),
                          self._cfg("景燃", kind="echo_profile"))
        self.assertEqual(
            flows_using_config([flow], "echo_profile", "某id", "景燃"),
            ["老流程"])

    def test_kind_filters_by_type(self):
        """筛选配置的 id 和强化配置的 id 可能撞车 —— kind 不同的不该误判。"""
        flow = self._flow("流程A", tool(), self._cfg("same-key", kind="loadout"))
        self.assertEqual(flows_using_config([flow], "loadout", "same-key"),
                         ["流程A"])
        self.assertEqual(flows_using_config([flow], "echo_profile", "same-key"),
                         [])

    def test_step_without_kind_still_matches(self):
        """极老的步骤没有 config_kind 字段 —— 仍应算作引用（防御性）。"""
        flow = self._flow("老流程", tool(),
                          TaskStep(type=STEP_CONFIG, key="k1", name="景燃"))
        self.assertEqual(flows_using_config([flow], "loadout", "k1"), ["老流程"])

    def test_each_flow_reported_once(self):
        """同一条流程里引用了两次也只报一次（别在提示里重复列同一个名字）。"""
        flow = self._flow("流程A", tool(), self._cfg("k1"), self._cfg("k1"))
        self.assertEqual(flows_using_config([flow], "loadout", "k1"), ["流程A"])

    def test_multiple_flows_all_listed(self):
        flows = [self._flow("流程A", tool(), self._cfg("k1")),
                 self._flow("流程B", tool(), self._cfg("k1"))]
        self.assertEqual(flows_using_config(flows, "loadout", "k1"),
                         ["流程A", "流程B"])

    def test_tool_steps_are_ignored(self):
        """工具步骤的 key 不该被当成配置引用（哪怕字符串一样）。"""
        flow = self._flow("流程A", tool(key="k1"))
        self.assertEqual(flows_using_config([flow], "loadout", "k1"), [])

    def test_empty_keys_never_match(self):
        """没有可比的键（空 id / 空名字）→ 不拦（宁可放行也不要误拦）。"""
        flow = self._flow("流程A", tool(), self._cfg("k1"))
        self.assertEqual(flows_using_config([flow], "loadout"), [])
        self.assertEqual(flows_using_config([flow], "loadout", "", "   "), [])

    def test_empty_flow_list(self):
        self.assertEqual(flows_using_config([], "loadout", "k1"), [])
        self.assertEqual(flows_using_config(None, "loadout", "k1"), [])

    def test_unnamed_flow_gets_placeholder(self):
        flow = self._flow("", tool(), self._cfg("k1"))
        self.assertEqual(flows_using_config([flow], "loadout", "k1"),
                         ["（未命名）"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
