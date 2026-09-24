"""任务流程「开始」步前置检查的单元测试。

用 monkeypatch 换掉 ``game_client.check``，因为真实环境里没装游戏：
* 换成一个"永远在跑"的假检查 → 验通过分支；
* 换成"永远不在跑" → 验报错分支；
* 换成"被调用就炸" → 验非游戏类型真的**没有去查**（别白跑一趟枚举）。

⚠ 任务类型现在是**从步骤推导**的（2026-09-26 用户要求去掉那两个下拉），
所以这里按"流程里放了什么工具"来造用例，不再直接给 ``type_key``。
"""

from __future__ import annotations

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.core import game_client  # noqa: E402
from src.core.game_client import ClientStatus  # noqa: E402
from src.core.task_start import TaskStartError, check_start  # noqa: E402
from src.core.tasks import STEP_TOOL, TaskFlow, TaskStep  # noqa: E402

# 类型推导要查 ToolRegistry —— 显式发现一次，否则一切都推成"未分类"而假绿
from src.tools import discover_tools  # noqa: E402

discover_tools()


def flow(*, game: bool = False, data: bool = False) -> TaskFlow:
    """按"放了哪些工具"造流程 —— 类型由它推导出来。"""
    steps = []
    if data:
        steps.append(TaskStep(type=STEP_TOOL, key="wuwa_library_update", name="资源库更新"))
    if game:
        steps.append(TaskStep(type=STEP_TOOL, key="echo_enhance", name="声骸自动强化"))
    return TaskFlow(name="测试流程", steps=steps)


class TestCheckStart(unittest.TestCase):
    def setUp(self):
        self.logs: list[str] = []
        self._original = game_client.check

    def tearDown(self):
        game_client.check = self._original

    def _patch(self, running: bool) -> None:
        def fake(spec):
            return ClientStatus(
                running=running,
                display_name=spec.display_name,
                matched_by="窗口" if running else "",
                detail="假窗口" if running else "没找到",
            )

        game_client.check = fake

    def _forbid_check(self) -> None:
        def boom(spec):  # pragma: no cover - 被调到就该失败
            raise AssertionError("这个任务类型不该去查游戏客户端")

        game_client.check = boom

    # ---------------------------------------------------------- 非游戏：跳过
    def test_empty_flow_skips(self):
        """没有工具步骤 → 未分类 → 跳过检查。"""
        self._forbid_check()
        check_start(flow(), self.logs.append)
        self.assertTrue(any("跳过" in line for line in self.logs))

    def test_data_tool_skips(self):
        """只有「资源库更新」（数据类）→ 跳过，不去查游戏客户端。"""
        self._forbid_check()
        check_start(flow(data=True), self.logs.append)
        self.assertTrue(any("数据" in line for line in self.logs))

    def test_log_mentions_type_is_derived(self):
        """日志里说清类型是"按流程里的工具推导"的 —— 用户已经看不到那个下拉了。"""
        self._forbid_check()
        check_start(flow(), self.logs.append)
        self.assertTrue(any("推导" in line for line in self.logs),
                        f"日志没说清类型哪来的：{self.logs}")

    # ---------------------------------------------------------- 游戏类
    def test_game_running_passes(self):
        self._patch(running=True)
        check_start(flow(game=True), self.logs.append)
        joined = "\n".join(self.logs)
        self.assertIn("鸣潮", joined)
        self.assertIn("已启动", joined)

    def test_game_not_running_stops_the_task(self):
        self._patch(running=False)
        with self.assertRaises(TaskStartError) as ctx:
            check_start(flow(game=True), self.logs.append)
        message = str(ctx.exception)
        self.assertIn("鸣潮", message)
        self.assertIn("没在运行", message)
        # 报错信息要给出下一步动作，不能只说"失败了"
        self.assertIn("打开", message)

    def test_mixed_flow_still_checks_game(self):
        """数据 + 游戏混着放 → 按游戏算，照样检查客户端。"""
        self._patch(running=False)
        with self.assertRaises(TaskStartError):
            check_start(flow(game=True, data=True), self.logs.append)

    def test_log_is_optional(self):
        """不传日志出口也不该炸（流程之外的调用点）。"""
        self._patch(running=True)
        check_start(flow(game=True))


if __name__ == "__main__":
    unittest.main(verbosity=2)
