"""声骸批量调频工具（改主属性）。

游戏里的「调频」＝ 花材料**改声骸的主属性**，走详情页的「数据重构」。
流程来自 ok-ww 的 ``ChangeEchoTask``（AGPL-3.0，见 README「开源许可」），
但**容错按 MyTools 的标准重写**（原版会在几种常见情况下把整个任务打断）。

    okww_task.py   任务本体（ok-ww 流程 + MyTools 容错 + 统计）
    tool.py        注册入口 + 配置界面（目标属性 / 运行 / 停止 / 报告）

⚠ 「调频」和「声骸自动强化」是两件事：
**强化**改**副词条**（强化并调谐），**调频**改**主属性**（数据重构）。

⚠ 上游一旦改了 ``ChangeEchoTask.run()``，这里的重写就要重新对齐 ——
见 ``docs/声骸批量调频工具设计.md``。
"""

from .okww_task import (
    DEFAULT_TARGET,
    ESC_TIMEOUT,
    MAX_CONSECUTIVE_FAILURES,
    SETTINGS_KEY,
    TARGET_STATS,
    MyToolsChangeEchoTask,
    stat_matches,
    target_pattern,
)

__all__ = [
    "DEFAULT_TARGET",
    "ESC_TIMEOUT",
    "MAX_CONSECUTIVE_FAILURES",
    "SETTINGS_KEY",
    "TARGET_STATS",
    "MyToolsChangeEchoTask",
    "stat_matches",
    "target_pattern",
]
