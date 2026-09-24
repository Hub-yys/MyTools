"""任务流程「开始」步要做的事。

以前 `开始` / `结束` 只是编排上的**视觉标记**（不执行任何东西）。
现在 `开始` 变成一个真步骤：**按任务类型做前置检查，不过就报错、任务直接停**。

目前的检查只有一类：

* 任务类型 = **游戏** → 按具体游戏（比如 鸣潮）查客户端是否在运行。
  没启动 → 抛 :class:`TaskStartError`，任务停止（由流程运行器报给界面）。
* 任务类型 = 未分类 / 数据 / 办公 → 没有可检查的东西，记一条日志跳过。

## ⚠ 任务类型现在是**推导**出来的（2026-09-26）

原来类型是用户在编排界面上手选的两个下拉。用户要求去掉它们 ——
类型看流程里放了什么工具就知道。所以这里改成读
:meth:`~src.core.tasks.TaskFlow.derived_type`（由工具步骤的分类推出来），
不再读存盘里的 ``type_key`` / ``sub_key``（那两个字段已经废弃）。

**纯逻辑**：只依赖 :mod:`game_client`，不碰 Qt，也不碰游戏窗口的键鼠
（"开背包"那类准备动作在工具层，见 ``tools/game/echo_enhance/prepare.py``）。
"""

from __future__ import annotations

from typing import Callable

from . import game_client
from .categories import ToolCategory
from .tasks import TaskFlow


class TaskStartError(RuntimeError):
    """「开始」步的前置检查没过 —— 任务直接停止。"""


def _noop(_message: str) -> None:
    pass


def check_start(flow: TaskFlow, log: Callable[[str], None] | None = None) -> None:
    """执行「开始」步的前置检查。不通过抛 :class:`TaskStartError`。

    ``log`` 用来吐进度，传流程运行器的日志出口即可。
    """
    say = log or _noop

    # 类型**推导**自步骤（不再读存盘字段）
    type_key, _sub_key = flow.derived_type()
    kind_name = flow.type_text() or "未分类"
    spec = flow.client_spec()

    if type_key != ToolCategory.GAME.key:
        say(f"任务类型「{kind_name}」（按流程里的工具推导）不需要检查游戏客户端，跳过")
        return

    if spec is None:
        # 理论上推导出游戏类型就一定带得上具体游戏；真走到这儿说明推导表被改坏了
        say("⚠ 流程里有游戏工具，但推导不出具体是哪个游戏，没法检查客户端")
        return

    say(f"检查 {spec.display_name} 客户端是否在运行…")
    status = game_client.check(spec)
    if not status.running:
        raise TaskStartError(
            f"{spec.display_name}客户端没在运行。\n"
            f"（{status.detail}）\n"
            f"先把游戏打开、切成窗口模式，再重新运行这条任务。"
        )
    say(f"✓ {status.describe()}")
