"""声骸词条定义 + 判定引擎。

**纯逻辑**：不依赖 Qt、不依赖 OCR、不碰截图，所以可以随便单测。

判定规则（按需求整理，参照 ok-ww EnhanceEchoTask.check_echo_stats 的思路）：

1. **核心属性**：属于"必须有"的属性。如果剩余孔位已经凑不齐 → 弃置。
   暴击 / 暴击伤害永远算核心属性，不可取消。
2. **双爆下限**：暴击、暴击伤害**各自**有下限，任一项不达标 → 弃置。
   （只出了其中一项时不在这一步判定 —— 另一项还有孔位可以博。）
   这一整套检查可以用 :attr:`JudgeConfig.enable_crit_check` 整体关掉。
3. **可选属性**：核心之外另外勾选的属性，同样计入"有效词条"。
4. **有效词条数**：满级时至少要达到 N 条（2~5）。
   若「当前有效条数 + 剩余孔位」都不到 N → 弃置。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

# --------------------------------------------------------------------- 常量

CRIT = "暴击"
CRIT_DMG = "暴击伤害"

#: 声骸副词条全集（与游戏内简体中文一致）
ALL_STATS: tuple[str, ...] = (
    CRIT,
    CRIT_DMG,
    "攻击",
    "攻击百分比",
    "生命",
    "生命百分比",
    "防御",
    "防御百分比",
    "共鸣效率",
    "普攻伤害加成",
    "重击伤害加成",
    "共鸣技能伤害加成",
    "共鸣解放伤害加成",
)

#: 可选属性列表 = 全集去掉双爆（需求：双爆已在核心属性里强制勾选）
OPTIONAL_CHOICES: tuple[str, ...] = tuple(s for s in ALL_STATS if s not in (CRIT, CRIT_DMG))

#: 声骸最多 5 条副词条
MAX_SUB_STATS = 5

#: 核心属性最多勾 5 条、有效词条数 2~5（可选属性不设条数上限）
MAX_CORE_STATS = 5
MIN_VALID_COUNT = 2
MAX_VALID_COUNT = 5

#: 暴击 / 暴击伤害各自的默认下限。界面上的加减框用这两个值做默认。
#: 参考：5 星声骸双爆满值 10.5% + 21%，7.5 / 15.0 大致相当于满值的七成。
DEFAULT_CRIT_MIN = 7.5
DEFAULT_CRIT_DMG_MIN = 15.0

#: 5 星声骸副词条的**满值**（暴击 10.5% / 暴击伤害 21.0%）。
#: 「满暴击 / 满爆伤」这条规则用它来判断"是不是满分词条"。
MAX_CRIT = 10.5
MAX_CRIT_DMG = 21.0
#: 判满值时留的读数余量（OCR 难免差一点）。
#: 取 0.3 是有依据的：副词条是**离散档位**，暴击最高两档差 0.6（10.5 vs 9.9）、
#: 爆伤差 1.2（21.0 vs 19.8）—— 容差压在半个档距以内，
#: 既能兜住 OCR 把 10.5 读成 10.4 这类误差，又不会把次高档错认成满值。
MAX_ROLL_EPSILON = 0.3

_ACTION = Literal["continue", "lock", "discard"]

_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")


# --------------------------------------------------------------------- 解析

def parse_value(text: str) -> float | None:
    """从 OCR 文本里抠出数值。

    游戏里写作 ``6.3%``、``40``、``12.6％``（全角百分号）等，都可能出现。
    抠不出来返回 None，调用方负责丢掉这一项。
    """
    if not text:
        return None
    match = _NUMBER_RE.search(text.replace("％", "%").replace(" ", ""))
    if not match:
        return None
    try:
        return float(match.group())
    except ValueError:
        return None


def normalize_stat_name(raw_name: str, value_text: str = "") -> str | None:
    """把 OCR 认出来的属性名归一化成 :data:`ALL_STATS` 里的标准名。

    游戏里"攻击"既可能是固定值也可能是百分比，两者靠数值里有没有 ``%`` 区分。
    OCR 有时候会多认几个字（比如"辅音"之类），所以用"包含"而不是等于来匹配。
    认不出来返回 None。
    """
    name = (raw_name or "").strip()
    if not name:
        return None

    # 百分比词条靠三处判断：数值里的 % 、全角 ％ 、或属性名本身写了"百分比"
    percent = "％" in value_text or "%" in value_text or "百分比" in name

    if "暴击伤害" in name:
        return CRIT_DMG
    if "暴击" in name:
        return CRIT
    if "攻击" in name:
        return "攻击百分比" if percent else "攻击"
    if "生命" in name:
        return "生命百分比" if percent else "生命"
    if "防御" in name:
        return "防御百分比" if percent else "防御"
    if "效率" in name:
        return "共鸣效率"
    if "普攻" in name:
        return "普攻伤害加成"
    if "重击" in name:
        return "重击伤害加成"
    if "解放" in name:
        return "共鸣解放伤害加成"
    if "技能" in name:
        return "共鸣技能伤害加成"
    return None


# --------------------------------------------------------------------- 结构

@dataclass(frozen=True)
class EchoStat:
    """一条已识别的副词条。"""

    name: str
    value: float

    def __str__(self) -> str:
        return f"{self.name} {self.value:g}"


@dataclass(frozen=True)
class JudgeConfig:
    """一次强化任务的判定配置。"""

    core_stats: frozenset[str] = frozenset({CRIT, CRIT_DMG})
    optional_stats: frozenset[str] = frozenset()
    #: 暴击 / 暴击伤害各自的下限
    crit_min: float = DEFAULT_CRIT_MIN
    crit_dmg_min: float = DEFAULT_CRIT_DMG_MIN
    #: 界面右侧那个开关：关掉就完全跳过双爆下限检查
    enable_crit_check: bool = True
    #: 满暴击 / 满爆伤自动保护：出现满值词条就一律强化到满级并上锁。
    #: **这一步跑在弃置判定之前** —— 其它条件都该弃置时也照样保住它。
    enable_max_roll_lock: bool = True
    #: 满级时至少要有多少条有效词条
    min_valid_count: int = 3
    max_sub_stats: int = MAX_SUB_STATS

    def __post_init__(self) -> None:
        # 双爆强制进核心属性，谁也去不掉
        forced = self.core_stats | {CRIT, CRIT_DMG}
        if forced is not self.core_stats:
            object.__setattr__(self, "core_stats", frozenset(forced))

        # 可选属性里不该出现双爆（界面上本来也不会给）
        cleaned_optional = frozenset(self.optional_stats) - {CRIT, CRIT_DMG}
        if cleaned_optional != self.optional_stats:
            object.__setattr__(self, "optional_stats", cleaned_optional)

        if len(self.core_stats) > MAX_CORE_STATS:
            raise ValueError(f"核心属性最多 {MAX_CORE_STATS} 条，收到 {len(self.core_stats)} 条")
        if not MIN_VALID_COUNT <= self.min_valid_count <= MAX_VALID_COUNT:
            raise ValueError(
                f"有效词条数需在 {MIN_VALID_COUNT}~{MAX_VALID_COUNT} 之间，收到 {self.min_valid_count}"
            )

    @property
    def valid_stats(self) -> frozenset[str]:
        """算作"有效词条"的属性 = 核心属性 ∪ 可选属性。"""
        return frozenset(self.core_stats | self.optional_stats)


@dataclass
class JudgeResult:
    """一次判定的结论。"""

    action: _ACTION
    reason: str = ""
    crit: float | None = None
    crit_dmg: float | None = None
    valid_count: int = 0
    remaining: int = 0
    stats: list[EchoStat] = field(default_factory=list)

    @property
    def keep(self) -> bool:
        return self.action != "discard"

    def __str__(self) -> str:
        parts = [f"{self.action}"]
        if self.crit is not None and self.crit_dmg is not None:
            parts.append(f"双爆{self.crit:g}/{self.crit_dmg:g}")
        parts.append(f"有效{self.valid_count}条")
        parts.append(f"剩{self.remaining}孔")
        if self.reason:
            parts.append(self.reason)
        return " | ".join(parts)


# --------------------------------------------------------------------- 判定

def judge(stats: list[EchoStat], config: JudgeConfig) -> JudgeResult:
    """判断当前词条该继续强化、保留，还是直接弃置。

    ``stats`` 是**当前已经调谐出来的**词条（不一定是 5 条），
    所以判定要结合"剩余孔位"来算——剩几个孔还没揭开，就还有多少可能。
    """
    present = [s for s in stats if s.name in ALL_STATS]
    names = {s.name for s in present}
    used = len(present)
    remaining = max(0, config.max_sub_stats - used)

    def result(action: _ACTION, reason: str = "", crit: float | None = None,
               crit_dmg: float | None = None, valid: int = 0) -> JudgeResult:
        return JudgeResult(
            action=action,
            reason=reason,
            crit=crit,
            crit_dmg=crit_dmg,
            valid_count=valid,
            remaining=remaining,
            stats=list(present),
        )

    # ---- 0. 满暴击 / 满爆伤：**先于弃置判定**，出了就直接保护
    #   （需求："这个是未判断弃置之前" —— 所以它必须排在所有弃置规则前面，
    #    否则满暴击但双爆下限不达标的声骸会先被判掉）
    if config.enable_max_roll_lock:
        perfect = [
            s for s in present
            if (s.name == CRIT and s.value >= MAX_CRIT - MAX_ROLL_EPSILON)
            or (s.name == CRIT_DMG and s.value >= MAX_CRIT_DMG - MAX_ROLL_EPSILON)
        ]
        if perfect:
            text = "、".join(f"{s.name} {s.value:g}" for s in perfect)
            got_crit = sum(s.value for s in present if s.name == CRIT) if CRIT in names else None
            got_dmg = (
                sum(s.value for s in present if s.name == CRIT_DMG)
                if CRIT_DMG in names else None
            )
            valid = sum(1 for s in present if s.name in config.valid_stats)
            if used >= config.max_sub_stats:
                return result(
                    "lock", f"满{text}（满分词条，直接上锁）",
                    crit=got_crit, crit_dmg=got_dmg, valid=valid,
                )
            return result(
                "continue", f"满{text}（满分词条，强化到满级后上锁）",
                crit=got_crit, crit_dmg=got_dmg, valid=valid,
            )

    # ---- 1. 核心属性：剩余孔位够不够凑齐
    missing_core = config.core_stats - names
    if len(missing_core) > remaining:
        missing_text = "、".join(sorted(missing_core))
        return result(
            "discard",
            f"凑不齐核心属性（缺 {missing_text}，只剩 {remaining} 孔）",
        )

    # ---- 2. 双爆各自下限
    crit: float | None = None
    crit_dmg: float | None = None
    if CRIT in names and CRIT_DMG in names:
        crit = sum(s.value for s in present if s.name == CRIT)
        crit_dmg = sum(s.value for s in present if s.name == CRIT_DMG)
        # 双爆值总是读出来（日志里能看到），是否拿它判定看开关
        if config.enable_crit_check:
            below: list[str] = []
            if crit < config.crit_min:
                below.append(f"暴击 {crit:g} < {config.crit_min:g}")
            if crit_dmg < config.crit_dmg_min:
                below.append(f"暴伤 {crit_dmg:g} < {config.crit_dmg_min:g}")
            if below:
                return result(
                    "discard",
                    "双爆不达标（" + "，".join(below) + "）",
                    crit=crit,
                    crit_dmg=crit_dmg,
                )

    # ---- 3. 有效词条数上限
    valid_set = config.valid_stats
    valid_count = sum(1 for s in present if s.name in valid_set)
    if valid_count + remaining < config.min_valid_count:
        return result(
            "discard",
            f"有效词条最多只能到 {valid_count + remaining} 条"
            f"（当前 {valid_count} + 剩余 {remaining} 孔），达不到 {config.min_valid_count} 条",
            crit=crit,
            crit_dmg=crit_dmg,
            valid=valid_count,
        )

    # ---- 4. 满级且全部通过 → 保留
    if used >= config.max_sub_stats:
        return result(
            "lock",
            f"满 {used} 条且符合条件（有效 {valid_count} 条）",
            crit=crit,
            crit_dmg=crit_dmg,
            valid=valid_count,
        )

    return result("continue", f"继续强化（已出 {used} 条，有效 {valid_count} 条）",
                  crit=crit, crit_dmg=crit_dmg, valid=valid_count)
