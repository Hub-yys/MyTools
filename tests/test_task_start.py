"""任务流程「开始」步前置检查的单元测试。

用 monkeypatch 换掉 ``game_client.check``，因为真实环境里没装游戏：
* 换成一个"永远在跑"的假检查 → 验通过分支；
* 换成"永远不在跑" → 验报错分支；
* 换成"被调用就炸" → 验非游戏类型真的**没有去查**（别白跑一趟枚举）。
"""

from __future__ import annotations

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.core import game_client  # noqa: E402
from src.core.categories import ToolCategory  # noqa: E402
from src.core.game_client import ClientStatus  # noqa: E402
from src.core.task_start import TaskStartError, check_start  # noqa: E402
from src.core.tasks import TaskFlow  # noqa: E402


def flow(type_key: str = "", sub_key: str = "") -> TaskFlow:
    return TaskFlow(name="测试流程", type_key=type_key, sub_key=sub_key)


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
    def test_unclassified_skips(self):
        self._forbid_check()
        check_start(flow(), self.logs.append)
        self.assertTrue(any("跳过" in line for line in self.logs))

    def test_data_type_skips(self):
        self._forbid_check()
        check_start(flow(ToolCategory.DATA.key, "wuwa"), self.logs.append)
        self.assertTrue(any("数据" in line for line in self.logs))

    def test_office_type_skips(self):
        self._forbid_check()
        check_start(flow(ToolCategory.OFFICE.key, "generic"), self.logs.append)

    # ---------------------------------------------------------- 游戏类
    def test_game_without_specific_title_only_warns(self):
        self._forbid_check()
        check_start(flow(ToolCategory.GAME.key, "generic"), self.logs.append)
        self.assertTrue(any("没指定具体游戏" in line for line in self.logs))

    def test_game_running_passes(self):
        self._patch(running=True)
        check_start(flow(ToolCategory.GAME.key, "wuwa"), self.logs.append)
        joined = "\n".join(self.logs)
        self.assertIn("鸣潮", joined)
        self.assertIn("已启动", joined)

    def test_game_not_running_stops_the_task(self):
        self._patch(running=False)
        with self.assertRaises(TaskStartError) as ctx:
            check_start(flow(ToolCategory.GAME.key, "wuwa"), self.logs.append)
        message = str(ctx.exception)
        self.assertIn("鸣潮", message)
        self.assertIn("没在运行", message)
        # 报错信息要给出下一步动作，不能只说"失败了"
        self.assertIn("打开", message)

    def test_log_is_optional(self):
        """不传日志出口也不该炸（流程之外的调用点）。"""
        self._patch(running=True)
        check_start(flow(ToolCategory.GAME.key, "wuwa"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
