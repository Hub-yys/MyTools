"""声骸自动强化工具。

目录说明（分层刻意如此，方便单独测试）：
    stats.py        词条定义 + 判定引擎，**纯逻辑，不依赖 Qt / OCR / 截图**
    reader.py       从游戏画面读词条（窗口截图 + OCR）
    controller.py   窗口句柄、键鼠输入
    runner.py       强化流程状态机（后台线程跑）
    tool.py         注册入口 + 配置界面

改判定规则只需要动 stats.py，改界面只需要动 tool.py。
"""

from .stats import (
    ALL_STATS,
    CRIT,
    CRIT_DMG,
    OPTIONAL_CHOICES,
    EchoStat,
    JudgeConfig,
    JudgeResult,
    judge,
    normalize_stat_name,
    parse_value,
)

__all__ = [
    "ALL_STATS",
    "CRIT",
    "CRIT_DMG",
    "OPTIONAL_CHOICES",
    "EchoStat",
    "JudgeConfig",
    "JudgeResult",
    "judge",
    "normalize_stat_name",
    "parse_value",
]
