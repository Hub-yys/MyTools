"""声骸自动强化的设置：界面 ↔ 判定配置 ↔ 磁盘。

一份设置同时喂三个地方：

1. **工具页的控件** —— 打开页面时恢复上次的选择，关掉程序再回来还是那套；
2. **工具页点「运行」** —— 用界面上当前的值（本来就是）；
3. **任务流程的运行** —— 这里以前是 ``JudgeConfig()``（代码里的默认值），
   于是"从任务页跑"和"从工具页跑"用的**不是同一套规则**：用户在界面上配的核心属性 /
   双爆下限 / 有效词条数全都没生效，任务按默认规则去弃置声骸。**已修**。

存的时候跟 :mod:`src.core.tool_settings` 走（用户数据目录下的 ``tool_settings.json``）。
**纯逻辑**：不依赖 Qt，可以单测。
"""

from __future__ import annotations

from dataclasses import dataclass

from ....core import tool_settings
from .stats import (
    ALL_STATS,
    CRIT,
    CRIT_DMG,
    DEFAULT_CRIT_DMG_MIN,
    DEFAULT_CRIT_MIN,
    MAX_VALID_COUNT,
    MIN_VALID_COUNT,
    OPTIONAL_CHOICES,
    JudgeConfig,
)

#: 存盘用的 key（= 工具的 key）
SETTINGS_KEY = "echo_enhance"

#: ok-ww 宿主里的任务注册名。**单一真源**：
#: 工具页启动任务用它、``okww_task.py`` 声明用它、``okww_boot.TASKS`` 也是这个 key。
#: 放在这里是为了让工具页不必 import okww（那会拖慢启动 —— 引擎只在点「运行」时才加载）。
TASK_KEY = "声骸自动强化"

#: 默认就是界面第一次打开时的样子：双爆强制勾选、可选属性不勾、有效词条 3 条
DEFAULT_CORE: tuple[str, ...] = (CRIT, CRIT_DMG)
DEFAULT_VALID_COUNT = 3

_VALID_COUNT_RANGE = (MIN_VALID_COUNT, MAX_VALID_COUNT)


@dataclass
class EchoSettings:
    """一次强化要用的全部设置。"""

    core_stats: tuple[str, ...] = DEFAULT_CORE
    optional_stats: tuple[str, ...] = ()
    crit_min: float = DEFAULT_CRIT_MIN
    crit_dmg_min: float = DEFAULT_CRIT_DMG_MIN
    enable_crit_check: bool = True
    enable_max_roll_lock: bool = True
    min_valid_count: int = DEFAULT_VALID_COUNT

    # ---------------------------------------------------------------- 磁盘
    @classmethod
    def load(cls) -> "EchoSettings":
        """从盘上读；没有 / 坏了就用默认值（见 :meth:`from_dict`）。"""
        return cls.from_dict(tool_settings.load(SETTINGS_KEY))

    def save(self) -> None:
        """写回盘上。任务流程运行时读的就是这一份。"""
        tool_settings.save(SETTINGS_KEY, self.to_dict())

    def to_dict(self) -> dict:
        return {
            "core_stats": list(self.core_stats),
            "optional_stats": list(self.optional_stats),
            "crit_min": self.crit_min,
            "crit_dmg_min": self.crit_dmg_min,
            "enable_crit_check": self.enable_crit_check,
            "enable_max_roll_lock": self.enable_max_roll_lock,
            "min_valid_count": self.min_valid_count,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "EchoSettings":
        """把盘上的 dict 变成设置对象。**每个字段都容错**：

        文件是手改过的、旧版本留下来的、被人塞了乱七八糟的值 —— 全都落回默认值 /
        夹到合法范围，绝不让它把判定引擎搞崩（JudgeConfig 对非法值会直接抛异常）。
        """
        raw = raw if isinstance(raw, dict) else {}

        core = _pick(raw.get("core_stats"), ALL_STATS)
        # 双爆永远是核心属性，谁也去不掉
        core = tuple(dict.fromkeys([*DEFAULT_CORE, *core]))

        return cls(
            core_stats=core,
            optional_stats=_pick(raw.get("optional_stats"), OPTIONAL_CHOICES),
            crit_min=_number(raw.get("crit_min"), DEFAULT_CRIT_MIN),
            crit_dmg_min=_number(raw.get("crit_dmg_min"), DEFAULT_CRIT_DMG_MIN),
            enable_crit_check=_flag(raw.get("enable_crit_check"), True),
            enable_max_roll_lock=_flag(raw.get("enable_max_roll_lock"), True),
            min_valid_count=_count(raw.get("min_valid_count")),
        )

    # ---------------------------------------------------------------- 判定
    def to_judge_config(self) -> JudgeConfig:
        """变成判定引擎吃的配置。"""
        return JudgeConfig(
            core_stats=frozenset(self.core_stats),
            optional_stats=frozenset(self.optional_stats),
            crit_min=self.crit_min,
            crit_dmg_min=self.crit_dmg_min,
            enable_crit_check=self.enable_crit_check,
            enable_max_roll_lock=self.enable_max_roll_lock,
            min_valid_count=self.min_valid_count,
        )

    @classmethod
    def from_judge_config(cls, config: JudgeConfig) -> "EchoSettings":
        return cls(
            core_stats=tuple(ALL_STATS_ORDERED(config.core_stats)),
            optional_stats=tuple(ALL_STATS_ORDERED(config.optional_stats)),
            crit_min=config.crit_min,
            crit_dmg_min=config.crit_dmg_min,
            enable_crit_check=config.enable_crit_check,
            enable_max_roll_lock=config.enable_max_roll_lock,
            min_valid_count=config.min_valid_count,
        )

    def describe(self) -> str:
        """一行摘要 —— 日志里要能看出"这次到底按什么规则跑"。"""
        crit = (
            f"暴击≥{self.crit_min:g} 爆伤≥{self.crit_dmg_min:g}"
            if self.enable_crit_check
            else "双爆下限：已关闭"
        )
        return (
            f"核心 {'/'.join(self.core_stats) or '无'}"
            f" / 可选 {'、'.join(self.optional_stats) or '无'}"
            f" / {crit}"
            f" / 有效词条 ≥{self.min_valid_count}"
            f" / 满值保护：{'开' if self.enable_max_roll_lock else '关'}"
        )


def ALL_STATS_ORDERED(names) -> list[str]:
    """按 ``ALL_STATS`` 的顺序排一遍（界面上的勾选项顺序就是它，日志看着也稳定）。"""
    wanted = set(names or ())
    return [name for name in ALL_STATS if name in wanted]


def _pick(value, allowed: tuple[str, ...]) -> tuple[str, ...]:
    """从盘上的列表里挑出合法的属性名（不认识的丢掉，保持界面顺序）。"""
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(ALL_STATS_ORDERED(set(str(v) for v in value) & set(allowed)))


def _number(value, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(100.0, number))


def _flag(value, default: bool) -> bool:
    return bool(value) if isinstance(value, bool) else default


def _count(value) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return DEFAULT_VALID_COUNT
    low, high = _VALID_COUNT_RANGE
    return max(low, min(high, number))
