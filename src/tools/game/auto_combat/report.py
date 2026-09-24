# -*- coding: utf-8 -*-
"""战斗报告的数据层：把 ok-ww 任务实例上的**现成统计**读成一份报告。

★ 关键认识（2026-09-24 逐行读 ok-ww 源码后确认）：这些数字**不是我们统计的** ——
  ok-ww 自己一直在算，只是塞进任务的 ``self.info`` 字典当"实时信息"显示，
  **没有**报告界面（全仓搜 ``战斗报告|BattleReport`` 零命中，``stats`` 的命中全是
  ``cv2.connectedComponentsWithStats`` 和声骸词条判定）。报告要做的是"翻译"它们：

      ======================= ============ ====================================================
      来源                    报告字段     ok-ww 在哪里 +1
      ======================= ============ ====================================================
      task.info['Combat Count'] 战斗次数   BaseCombatTask.combat_once()
      task.info['Echo Count']   声骸数量   BaseWWTask.incr_drop()
      task.chars                使用队伍   BaseCombatTask.load_chars()（屏幕模板匹配出来的）
      task.aim_boss             战斗声骸   FarmEchoTask.check_boss_name()
      时长                      ——         由宿主掐表（本次运行 = 点「启动」到「停止」）
      ======================= ============ ====================================================

  所以这个模块**不碰 ok-ww 的执行逻辑**，只做三件事：**取差值**、**名字转中文**、**算时长**。

⚠ 为什么必须取差值：``info`` 是任务 ``__init__`` 里建的空 dict，**同一进程内跨次运行会
  一直累加**（不是每次运行清零）。而用户要的是"本次 4C 自动战斗的次数，从运行开始到停止"，
  所以宿主在开跑前快照一份基线，报告显示 ``当前 − 基线``。

⚠ 战斗声骸有个**硬限制**：ok-ww 只在 ``check_boss_name()`` 认出屏幕上的 Boss 名时才设
  ``aim_boss``，而它的 ``boss_dict`` 只覆盖 4 个（伪作的神王 / 异构武装 / 荣耀狮像 / 罗蕾莱）。
  识别不出时只剩配置里的英文档位名（Hyvatia、Fenrico…），报告照实显示并标「未识别」。
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from ....core import game_data, paths

#: ok-ww 的中文翻译表（角色名就靠它转中文）。打包时随 vendor/i18n 一起分发。
ZH_PO_PARTS = ("vendor", "okww", "i18n", "zh_CN", "LC_MESSAGES", "ok.po")

#: ok-ww ``BaseCombatTask.mismatched_names`` 的副本（类名 → 它的翻译键）。
#: 抄过来是为了**不必 import okww 包**（那会把 ok 的导入链一起拖进来，很重）。
#: 内容不多且稳定；ok-ww 改了这里跟着改即可。
MISMATCHED_NAMES = {
    "Douling": "Buling",
    "Xigelika": "Sigrika",
    "Linnai": "Lynae",
    "Luhesi": "Luuk Herssen",
    "Xiangliyao": "Xiangli Yao",
    "ShoreKeeper": "Shorekeeper",
    "Rover": "Rover",
    "YangYangSp": "Yangyang: Xuanling",
}

_QUOTED = re.compile(r'^"(.*)"$', re.DOTALL)


def _unquote(text: str) -> str:
    m = _QUOTED.match(text.strip())
    body = m.group(1) if m else text.strip()
    return body.replace('\\"', '"').replace("\\n", "\n").replace("\\\\", "\\")


def parse_po(text: str) -> dict[str, str]:
    """解析 gettext ``.po`` 里的 ``msgid → msgstr``（容忍多行续行）。

    只取"有译文"的条目；``msgstr ""``（未翻译）跳过 —— 否则会把角色名翻成空串。
    """
    entries: dict[str, str] = {}
    msgid: str | None = None
    msgstr: str | None = None

    def flush() -> None:
        if msgid and msgstr:
            entries[msgid] = msgstr

    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("#") or not line:
            continue
        if line.startswith("msgid "):
            flush()
            msgid, msgstr = _unquote(line[6:]), None
        elif line.startswith("msgstr ") and msgid is not None:
            msgstr = _unquote(line[7:])
        elif line.startswith('"') and msgid is not None:
            chunk = _unquote(line)
            if msgstr is None:
                msgid += chunk
            else:
                msgstr += chunk
    flush()
    return entries


_ZH_CACHE: dict[str, str] | None = None


def zh_names(path: Path | None = None) -> dict[str, str]:
    """ok-ww 英文名 → 中文名。读不到就返回空字典（调用方会退回英文名）。"""
    global _ZH_CACHE
    if path is None and _ZH_CACHE is not None:
        return _ZH_CACHE
    po = path or Path(paths.resource_dir(*ZH_PO_PARTS))
    try:
        table = parse_po(po.read_text(encoding="utf-8"))
    except OSError:
        table = {}
    if path is None:
        _ZH_CACHE = table
    return table


# ------------------------------------------------------------------ 队伍成员

@dataclass(frozen=True)
class TeamMember:
    """报告里"一个队员"的展示信息。"""

    name: str                      # 展示用的名字（尽量是中文）
    avatar: str = ""               # MyTools 数据集里的相对路径（``avatars/今汐.png``）
    resolved: bool = False         # 是否在 MyTools 角色数据里对上了（对不上就没头像）


def char_display_name(char) -> str:
    """从一个 ok-ww 角色对象上抠出展示名（优先中文）。

    取名字的顺序是有讲究的：
    1. ``display_name``：ok-ww 自定义角色可以显式指定；
    2. ``type(char).__name__``（如 ``Jinhsi``）：**这才是 ``mismatched_names`` 的键**，
       也是 ``.po`` 里的 msgid；
    3. ``char.name`` / ``char.char_name``：兜底（后者是模板图 id，如 ``char_jinhsi``）。
    """
    if char is None:
        return ""
    explicit = str(getattr(char, "display_name", "") or "")
    if explicit:
        return explicit

    table = zh_names()
    cls_name = type(char).__name__
    candidates = [
        cls_name,
        MISMATCHED_NAMES.get(cls_name, ""),
        str(getattr(char, "name", "") or ""),
        str(getattr(char, "char_name", "") or ""),
    ]
    for key in candidates:
        if key and key in table:
            return table[key]
    return MISMATCHED_NAMES.get(cls_name) or cls_name


def resolve_team(chars) -> tuple[TeamMember, ...]:
    """把 ok-ww 的 ``task.chars`` 转成展示用的队伍（带 MyTools 头像）。"""
    members: list[TeamMember] = []
    for char in chars or ():
        if char is None:
            continue
        name = char_display_name(char)
        if not name:
            continue
        info = game_data.find_character(name)
        if info is None:
            # 精确匹配不到再试前缀（如 ok-ww 只说「漂泊者」，数据集里是「漂泊者·导电」）
            info = next((c for c in game_data.CHARACTERS if c.name.startswith(name)), None)
        members.append(
            TeamMember(name=info.name if info else name,
                       avatar=info.avatar if info else "",
                       resolved=info is not None)
        )
    return tuple(members)


# ------------------------------------------------------------------ 战斗声骸

@dataclass(frozen=True)
class EchoTarget:
    """报告里"在打的声骸"。``identified=False`` 时界面要标「未识别」。"""

    name: str
    icon: str = ""
    identified: bool = True


def _echo_index() -> dict[str, object]:
    """声骸名 → EchoInfo（181 条，调用时现建，够快且不怕资源库更新后失效）。"""
    return {
        echo.name: echo
        for cost in sorted(game_data.ECHOES_BY_COST)
        for echo in game_data.ECHOES_BY_COST[cost]
    }


def resolve_echo(task) -> EchoTarget:
    """战斗声骸：优先用 ok-ww **识别出来**的 Boss 名，否则退回配置档位名。"""
    aim = str(getattr(task, "aim_boss", "") or "").strip()
    if aim:
        info = _echo_index().get(aim)
        return EchoTarget(name=aim, icon=getattr(info, "icon", "") if info else "", identified=True)

    # ok-ww 没认出来 —— 按用户定的规矩：显示配置里的档位名，并标「未识别」
    config = getattr(task, "config", None) or {}
    profile = str(config.get("Boss", "") or "").strip()
    if profile and profile != "Other":
        return EchoTarget(name=profile, icon="", identified=False)
    return EchoTarget(name="未知", icon="", identified=False)


# ------------------------------------------------------------------ 报告本体

def _delta(current: int, baseline: int) -> int:
    """``当前 − 基线``，但**取不到负数**。

    ``info`` 正常是跨次累加的，所以差值就是"本次运行"。但万一 ok-ww 哪次把 ``info``
    重置了（当前 < 基线），差值会变成负数 —— 那种时候"当前值"本身就是本次的数量，
    直接用它更合理。
    """
    return current - baseline if current >= baseline else current


def _as_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def snapshot_counters(task) -> dict[str, int]:
    """开跑前快照基线（宿主在 ``start_task`` 里调）。"""
    info = getattr(task, "info", None) or {}
    return {
        "battles": _as_int(info.get("Combat Count", 0)),
        "echoes": _as_int(info.get("Echo Count", 0)),
    }


# ---------------------------------------------------------------- 拾取角标统计

#: 「拾取到的声骸」的三种状态 —— 对应游戏左下角那个自动锁定 / 自动弃置角标
LOCKED = "locked"
DROPPED = "dropped"
NONE = "none"

#: 角标特征名（ok-ww 自带，与强化界面判锁/弃置用的是同一批图标）
LOCKED_FEATURE = "echo_locked"
DROPPED_FEATURE = "echo_dropped"


def classify_badges(names) -> str:
    """把匹配到的特征名映射成状态。**纯函数，好单测**。

    规则（按优先级）：看到 ``echo_locked`` → 锁定；看到 ``echo_dropped`` → 弃置；
    其余（包括一个都没看到）→ 两者都不。

    最后那条是刻意的：游戏对"都没"这种情况**可能压根不画角标**，而我们没法区分
    "本来就没角标"和"判定区域猜错了"。所以按"都没"算，并且把三个数都显示在报告里 ——
    区域要是错了，会表现为「锁定/弃置恒为 0、都没=全部」，一眼就能看出来，不会被静默吞掉。
    """
    found = {str(n) for n in names if n}
    if LOCKED_FEATURE in found:
        return LOCKED
    if DROPPED_FEATURE in found:
        return DROPPED
    return NONE


@dataclass
class PickupTally:
    """本次运行内"拾取到的声骸"按状态分类的计数。"""

    locked: int = 0
    dropped: int = 0
    none: int = 0

    @property
    def total(self) -> int:
        return self.locked + self.dropped + self.none

    def add(self, state: str) -> None:
        if state == LOCKED:
            self.locked += 1
        elif state == DROPPED:
            self.dropped += 1
        else:
            self.none += 1


_TALLY = PickupTally()
_TALLY_LOCK = threading.Lock()


def reset_pickup_tally() -> None:
    """开跑前清零（宿主在 ``start_task`` 里调）—— 报告要的是"本次运行"。"""
    global _TALLY
    with _TALLY_LOCK:
        _TALLY = PickupTally()


def pickup_tally() -> PickupTally:
    """当前计数的**副本**（免得读到一半被任务线程改）。"""
    with _TALLY_LOCK:
        return PickupTally(_TALLY.locked, _TALLY.dropped, _TALLY.none)


def tally_pickup(state: str) -> None:
    """记一次拾取（由 4C 任务的子类 ``okww_farm.py`` 调用）。"""
    with _TALLY_LOCK:
        _TALLY.add(state)


def format_duration(seconds: float) -> str:
    """秒 → ``mm:ss`` / ``h:mm:ss``（不到 1 小时不显示小时位）。"""
    total = max(0, int(seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


@dataclass(frozen=True)
class BattleReport:
    """一次 4C 自动战斗运行的报告快照（从点「启动」到「停止」）。"""

    running: bool = False
    battles: int = 0
    echo_count: int = 0
    seconds: float = 0.0
    team: tuple[TeamMember, ...] = field(default_factory=tuple)
    echo: EchoTarget = field(default_factory=lambda: EchoTarget("未知", identified=False))
    pickups: PickupTally = field(default_factory=PickupTally)

    @property
    def duration_text(self) -> str:
        return format_duration(self.seconds)

    @property
    def team_text(self) -> str:
        return "、".join(m.name for m in self.team) if self.team else "还没识别到"


def read_report(task, *, baseline: dict | None = None, started_at: float = 0.0,
                stopped_at: float = 0.0, running: bool = False,
                now: float | None = None,
                pickups: PickupTally | None = None) -> BattleReport:
    """把 ok-ww 任务实例 + 宿主的时间信息，合成一份报告快照。

    纯函数（只读 task 的属性、不做任何副作用）—— 所以单测里拿个假对象就能覆盖全部分支。
    """
    baseline = baseline or {}
    now = time.time() if now is None else now

    info = getattr(task, "info", None) or {}
    battles = _delta(_as_int(info.get("Combat Count", 0)), _as_int(baseline.get("battles", 0)))
    echoes = _delta(_as_int(info.get("Echo Count", 0)), _as_int(baseline.get("echoes", 0)))

    # 停止后时长**冻结**在那一刻，不再跟着墙上时钟走字
    end = stopped_at or now
    seconds = max(0.0, end - started_at) if started_at else 0.0

    return BattleReport(
        running=running,
        battles=max(0, battles),
        echo_count=max(0, echoes),
        seconds=seconds,
        team=resolve_team(getattr(task, "chars", None)),
        echo=resolve_echo(task),
        pickups=pickups if pickups is not None else pickup_tally(),
    )
