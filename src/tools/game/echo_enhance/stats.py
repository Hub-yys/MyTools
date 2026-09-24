"""声骸词条定义 + 判定引擎。

**纯逻辑**：不依赖 Qt、不依赖 OCR、不碰截图，所以可以随便单测。

判定规则（**顺序即优先级**，前面的先判，命中就返回）：

1. **满暴击 / 满爆伤**：出现满值词条（暴击 10.5 / 爆伤 21）→ 保下来
   （未满 5 条就继续强化，满了就上锁）。用 :attr:`JudgeConfig.enable_max_roll_lock`
   开关。**最高优先** —— 出了满值，下面所有弃置规则都不再看。
2. **双爆下限**：暴击、暴击伤害**各自**有下限，**任一"已出现"项**低于下限 → 弃置。
   声骸每种副词条**只会出现一次**，所以已经读出来的低值就是这个声骸的最终值，
   后面的孔位再多也补不回来 —— 不必等另一项，也不受"剩余孔位够凑有效词条数"影响。
   这一整套检查可以用 :attr:`JudgeConfig.enable_crit_check` 整体关掉。
3. **核心属性**：属于"必须有"的属性。如果剩余孔位已经凑不齐 → 弃置。
   暴击 / 暴击伤害永远算核心属性，不可取消。
4. **可选属性**：核心之外另外勾选的属性，同样计入"有效词条"。
5. **有效词条数**：满级时至少要达到 N 条（2~5）。
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

#: 弃置原因分类码 → 人话。**给统计用** —— 一次运行结束要能一眼看出"到底为什么
#: 全被弃置"，否则用户只看到"全丢掉了"却无从下手（2026-09-24 的教训）。
DISCARD_CODES: dict[str, str] = {
    "core": "凑不齐核心属性",
    "crit": "双爆不达标",
    "valid": "有效词条不足",
}

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
    #: **最高优先** —— 排在所有弃置规则之前（包括双爆下限），出了满值就保住。
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

    @property
    def effective_min_valid_count(self) -> int:
        """**真正生效**的「有效词条数」下限。

        为什么需要它：``valid_stats`` 最多 13 条，而声骸的 5 个孔位里
        **每种词条只会出现一次** —— 所以「有效词条数」的实际上限就是
        ``len(valid_stats)``。默认配置（核心只有双爆、可选一条没勾）下这个集合
        只有 2 条，而界面默认要 ``>= 3``：**永远达不到 → 每个声骸都在满级那一刻
        被判弃置**（2026-09-24 用户实测"完全没用"就是这个）。
        这里把下限夹到可达范围 —— 宁可放宽，也不能让它无声地把所有声骸丢掉。
        """
        return min(self.min_valid_count, len(self.valid_stats))

    @property
    def min_valid_count_unreachable(self) -> bool:
        """用户填的「有效词条数」是不是根本达不到。"""
        return self.min_valid_count > len(self.valid_stats)

    def criterion_warning(self) -> str:
        """配置自相矛盾时给一句人话；没问题时返回空串。"""
        if not self.min_valid_count_unreachable:
            return ""
        names = "、".join(sorted(self.valid_stats))
        return (
            f"「有效词条 ≥{self.min_valid_count}」达不到：有效词条集合只有 "
            f"{len(self.valid_stats)} 条（{names}），声骸每种词条最多出现一次 —— "
            f"已按 ≥{self.effective_min_valid_count} 执行。"
            f"想提高要求，请在「可选属性」里多勾几条。"
        )


@dataclass
class JudgeResult:
    """一次判定的结论。"""

    action: _ACTION
    reason: str = ""
    #: 弃置原因分类码（见 :data:`DISCARD_CODES`）；保留时为空串
    code: str = ""
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

    def result(action: _ACTION, reason: str = "", code: str = "",
               crit: float | None = None, crit_dmg: float | None = None,
               valid: int = 0) -> JudgeResult:
        return JudgeResult(
            action=action,
            reason=reason,
            code=code,
            crit=crit,
            crit_dmg=crit_dmg,
            valid_count=valid,
            remaining=remaining,
            stats=list(present),
        )

    # ---- 1. 满暴击 / 满爆伤：**最高优先，出了就无论如何强化到满级并上锁**
    #   它排在所有弃置规则之前，双爆下限也压不住它 ——
    #   "暴击 10.5 + 爆伤 12.6" 这种照样保下来（用户 2026-09-25 明确要求）。
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
            # code="max_roll" 给统计用：出了满分词条 → 这个声骸要算进「满属性」。
            # 注意它不是弃置原因（不进 DISCARD_CODES）。
            if used >= config.max_sub_stats:
                return result(
                    "lock", f"满{text}（满分词条，直接上锁）", code="max_roll",
                    crit=got_crit, crit_dmg=got_dmg, valid=valid,
                )
            return result(
                "continue", f"满{text}（满分词条，强化到满级后上锁）", code="max_roll",
                crit=got_crit, crit_dmg=got_dmg, valid=valid,
            )

    # ---- 2. 双爆各自下限：**任一「已出现」项低于下限就弃置**
    #   ⚠ 2026-09-25 修正。原实现要求暴击与爆伤**都出现**才判，理由写的是
    #     "只出其中一项时另一项还有孔位可以博" —— 这个理由是**错的**：
    #     声骸每种副词条**只会出现一次**，已经读出来的暴击 6.3 就是这个声骸
    #     最终的暴击值，后面孔位再多也变不出第二个暴击，永远到不了 7.5。
    #     所以单项低于下限 = 本条**再也无法达标** → 当场弃置，
    #     既不必等另一项出来，也**不受**"剩余孔位够凑有效词条数"影响。
    crit: float | None = None
    crit_dmg: float | None = None
    if CRIT in names:
        crit = sum(s.value for s in present if s.name == CRIT)
    if CRIT_DMG in names:
        crit_dmg = sum(s.value for s in present if s.name == CRIT_DMG)
    if config.enable_crit_check:
        below: list[str] = []
        # ⚠ 这里**不能写 "<"**：reason 会被 ok-ww 拼进失败截图文件名，
        #   而 < > : " / \ | ? * 在 Windows 文件名里非法。
        #   （ok-ww 自己会 re.sub 洗一遍，但 MyTools 这边的 fail_reason 契约
        #    要求本身就是干净的 —— 见 tests/test_echo_okww_task.py
        #    test_fail_reason_is_safe_for_screenshot_name。）
        if crit is not None and crit < config.crit_min:
            below.append(f"暴击 {crit:g} 低于 {config.crit_min:g}")
        if crit_dmg is not None and crit_dmg < config.crit_dmg_min:
            below.append(f"暴伤 {crit_dmg:g} 低于 {config.crit_dmg_min:g}")
        if below:
            return result(
                "discard",
                "双爆不达标（" + "，".join(below) + "）",
                code="crit",
                crit=crit,
                crit_dmg=crit_dmg,
            )

    # ---- 3. 核心属性：剩余孔位够不够凑齐
    missing_core = config.core_stats - names
    if len(missing_core) > remaining:
        missing_text = "、".join(sorted(missing_core))
        return result(
            "discard",
            f"凑不齐核心属性（缺 {missing_text}，只剩 {remaining} 孔）",
            code="core",
        )

    # ---- 4. 有效词条数上限
    valid_set = config.valid_stats
    valid_count = sum(1 for s in present if s.name in valid_set)
    # ⚠ 用 effective_min_valid_count 而不是用户填的原值：集合只有 N 条时 "≥N+1"
    #   永远达不到，照原值判会把**每个**声骸都弃置（2026-09-24 事故）。
    if valid_count + remaining < config.effective_min_valid_count:
        return result(
            "discard",
            f"有效词条最多只能到 {valid_count + remaining} 条"
            f"（当前 {valid_count} + 剩余 {remaining} 孔），"
            f"达不到 {config.effective_min_valid_count} 条",
            code="valid",
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



# ------------------------------------------------------------------ 结果报告


def format_result_report(*, checked: int, kept: int, dropped: int,
                         perfect: int | None = None,
                         tally: dict[str, int] | None = None,
                         failed_reason: str | None = None) -> str:
    """把一次强化运行的统计排成给人看的报告。

    页面卡片、结束弹窗、任务流程的 ``summary()`` 共用这一份排版。

    * ``perfect`` 传 ``None`` = 没启用「满暴击/满爆伤自动锁定」——
      这项不统计也不显示（用户要求：启用时才统计）；
    * ``tally`` 的键是 :data:`DISCARD_CODES` 里的弃置原因码，有内容才出第二行；
    * ``failed_reason`` = 任务**异常中断**的原因（ok-ww 抛的那句原文）。
      有它就**优先显示它**。

    为什么 ``failed_reason`` 必须优先：一个都没判定时，真正的原因几乎都在
    那句话里，而默认那句「请确认停在 背包 → 声骸 界面」会把用户带偏 ——
    实测 2026-09-25：ok-ww 抛的是
    「强化设置需要开启阶段放入!」（游戏内设置没开），
    界面却显示「请确认停在背包→声骸界面」，用户对着界面查了半天。
    """
    checked = int(checked or 0)
    kept = int(kept or 0)
    dropped = int(dropped or 0)
    reason = (failed_reason or "").strip()
    if checked <= 0 and kept <= 0 and dropped <= 0:
        if reason:
            return f"任务中断：{reason}"
        return ("本次没有判定任何声骸 —— 请确认停在 背包 → 声骸 界面，"
                "且过滤器后有可强化的声骸")
    parts = [f"判定 {checked} 个", f"符合条件 {kept}", f"弃置 {dropped}"]
    if perfect is not None:
        parts.append(f"满属性 {int(perfect)}")
    text = " · ".join(parts)
    if tally:
        reasons = "、".join(
            f"{DISCARD_CODES.get(code, code)} {count}"
            for code, count in tally.items())
        text += f"\n弃置原因：{reasons}"
    return text


def parse_result_counts(report: str) -> dict[str, int]:
    """把 :func:`format_result_report` 那行报告**读回成数字**。

    返回 ``{"checked": N, "kept": K, "dropped": D}``；解析不出来的项是 **0**
    （不猜、不填默认值 —— 宁可少一行，也不要编一个错的数字）。

    为什么需要它（2026-09-28 加）：任务页要出「本轮报告 / 累计统计」，
    而流程线程拿到的只有工具 ``.summary()`` 那行**文本** ——
    ``create_task_runner`` 的契约就是"``run()`` 返回一个有 ``summary()`` 的东西"，
    结构化数据在这一层已经被拍平了。所以要有个地方把文本读回来，
    而且**读的规则必须和写的规则在同一个文件里**（就是这里）——
    否则改了排版、报告那边就悄悄变成 0，谁都发现不了。

    ⚠ 改动 :func:`format_result_report` 的排版时**必须**同步这里，
    两侧由 ``tests/test_echo_stats.py`` 里的往返测试兜着。
    """
    text = str(report or "")
    counts = {"checked": 0, "kept": 0, "dropped": 0}
    patterns = (
        ("checked", r"判定\s*(\d+)\s*个"),
        ("kept", r"符合条件\s*(\d+)"),
        ("dropped", r"弃置\s*(\d+)"),
    )
    for key, pattern in patterns:
        match = re.search(pattern, text)
        if match:
            try:
                counts[key] = int(match.group(1))
            except (TypeError, ValueError):   # pragma: no cover - 正则已保证是数字
                counts[key] = 0
    return counts
