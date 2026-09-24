"""角色配置（一套声骸搭配）的模型 + 本地 JSON 存储。

**纯逻辑**：不依赖 Qt，所以可以命令行单测（见 ``tests/test_loadout.py``）。

一条配置 = 一个角色 + 一套声骸套装 + 4C/3C/1C 各挑若干声骸（可多选，每条声骸的属性也可多选）。
同一个角色允许多条配置（比如两套不同思路的搭配），不做唯一性限制。
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .game_data import (
    COST_1,
    COST_3,
    COST_4,
    COST_SECTIONS,
    EchoInfo,
    find_character,
    find_echo_set,
)
from . import paths

#: 「配置类型」的稳定标识 —— **任务流程的步骤里存它**，用来分辨这一步挂的是
#: 哪一类配置（两类配置的 key 长得不一样：一个 id、一个 id）。
#: ⚠ 定义在 core 而不是 gui：``src/tools/`` 里的工具要根据它判断"挂的是不是我这类配置"，
#:   tools 层不该 import gui 层。
KIND = "loadout"

#: 默认存放位置：用户数据目录下的 loadouts.json
#: （开发态 = <项目根>/data；打包后 = %LOCALAPPDATA%/WutheringWavesTools，见 core/paths.py）
DEFAULT_STORE_PATH = paths.user_data_dir() / "loadouts.json"


@dataclass
class EchoPick:
    """某个费用档位选中的声骸 + 该声骸要哪些属性（**可多选**）。

    ``stats`` 是元组 —— 一条声骸可以同时要"暴击 + 暴击伤害"等多条主词条
    （2026-09-22 起：界面上的属性框从单选改成真多选）。
    空元组表示还没选。
    """

    echo: str = ""
    stats: tuple[str, ...] = ()

    def __post_init__(self):
        # 防手滑：传成单个字符串就当单元素元组用，别让元组字段里混进一个 str
        if isinstance(self.stats, str):
            self.stats = (self.stats,) if self.stats else ()

    @property
    def is_empty(self) -> bool:
        return not self.echo.strip()

    @property
    def stat(self) -> str:
        """兼容读取：多选里的第一条（老代码 / 老配置用）。没有就是空串。"""
        return self.stats[0] if self.stats else ""

    def describe(self) -> str:
        if self.is_empty:
            return "未选"
        if not self.stats:
            return self.echo
        return f"{self.echo}（{'、'.join(self.stats)}）"


def parse_picks(value) -> list[EchoPick]:
    """解析一个档位的声骸选择。

    同时吃三种格式，免得老配置文件一升级就读不出来：

    - 老版本的单条 dict（``{"echo":..,"stat":..}``）
    - dict 列表（每条只有 ``stat`` 单属性）→ 单属性转成单元素元组
    - 新版本的 dict 列表（每条 ``stats`` 是属性列表）
    """
    if isinstance(value, dict):
        items = [value]
    elif isinstance(value, list):
        items = [v for v in value if isinstance(v, dict)]
    else:
        return []

    result: list[EchoPick] = []
    for item in items:
        raw_stats = item.get("stats")
        if isinstance(raw_stats, (list, tuple)):
            stats = tuple(str(s) for s in raw_stats if str(s).strip())
        else:
            legacy = str(item.get("stat", "")).strip()
            stats = (legacy,) if legacy else ()
        pick = EchoPick(echo=str(item.get("echo", "")), stats=stats)
        if not pick.is_empty:
            result.append(pick)
    return result


# ---------------------------------------------------------------- 筛选面板上的两行
# 游戏里「筛选」面板有：状态 / 品质 / 合鸣（= 套装）/ 主音属性。
# 合鸣和主音属性这条配置里本来就有（`echo_set` + 各档 `picks` 的属性），
# **状态和品质是 2026-09-26 用户指出漏掉的**，这里补上。

#: 状态 —— **单选**（游戏里那行是三个单选圈）
STATUS_DISCARDED = "已弃置"
STATUS_LOCKED = "已锁定"
STATUS_UNMARKED = "未标记"
STATUS_CHOICES = (STATUS_DISCARDED, STATUS_LOCKED, STATUS_UNMARKED)
#: 默认「已锁定」（2026-09-28 用户批注："默认已锁定"）。
#: 新增配置时状态勾的就是它 —— 这条只是**新增时的起点**，编辑已有配置
#: 照样回填它自己存的值（走 :func:`normalize_status`）。
#: 老数据里没有 ``status`` 字段时也落回这个默认 —— 用户要的就是这个起点。
DEFAULT_STATUS = STATUS_LOCKED

#: 品质 —— **多选**（游戏里那组是勾选框）
QUALITY_CHOICES = ("二星", "三星", "四星", "五星")
#: 默认只勾五星（用户 2026-09-26："品质（默认就是五星）"）
DEFAULT_QUALITIES = ("五星",)


def normalize_status(value) -> str:
    """任意输入 → 合法的状态；不认识的落回默认（老数据没有这个字段）。"""
    text = str(value or "").strip()
    return text if text in STATUS_CHOICES else DEFAULT_STATUS


def normalize_qualities(value) -> tuple[str, ...]:
    """任意输入 → 合法的品质元组（去重、按固定顺序、丢掉不认识的值）。

    空元组也保留 —— 那是"用户把勾都取消了"，不该被悄悄塞回默认值。
    """
    if not isinstance(value, (list, tuple)):
        return DEFAULT_QUALITIES
    picked = {str(v) for v in value}
    return tuple(q for q in QUALITY_CHOICES if q in picked)


@dataclass
class Loadout:
    """一条配置。"""

    character: str = ""
    avatar: str = ""                                    # 相对 assets/game/ 的路径
    #: 用户自己选的头像（绝对路径），填了就优先用它
    custom_avatar: str = ""
    echo_set: str = ""
    #: 每档位选中的声骸（可多选）：cost -> [EchoPick, ...]
    picks: dict[int, list[EchoPick]] = field(default_factory=dict)
    #: 筛选面板：状态（单选）/ 品质（多选）
    status: str = DEFAULT_STATUS
    qualities: tuple[str, ...] = DEFAULT_QUALITIES
    id: str = ""
    updated_at: str = ""

    # ------------------------------------------------------------ 声骸选择
    def picks_of(self, cost: int) -> list[EchoPick]:
        """某个档位选中的声骸（**可以多个**）。"""
        return list(self.picks.get(cost, []))

    def set_picks(self, cost: int, picks: list[EchoPick]) -> None:
        """整档替换（空的选择会被丢掉）。"""
        self.picks[cost] = [p for p in picks if not p.is_empty]

    def add_pick(self, cost: int, echo: "EchoInfo | str",
                 stats: "str | tuple[str, ...] = ()") -> EchoPick:
        name = echo.name if isinstance(echo, EchoInfo) else str(echo)
        stats_tuple = (stats,) if isinstance(stats, str) else tuple(stats)
        pick = EchoPick(echo=name, stats=stats_tuple)
        self.picks.setdefault(cost, []).append(pick)
        return pick

    def clear_picks(self, cost: int) -> None:
        self.picks[cost] = []

    # ------------------------------------------------------------ 校验
    def validate(self) -> list[str]:
        """检查必填项，返回错误说明列表（空列表表示通过）。

        ★ 2026-09-28 用户批注："**1C、3C、4C 都可以不填，不校验必填**"。

        所以这里**只**要求两件事：

        * 角色必填；
        * 声骸套装必填（声骸是挂在套装下的，没套装就无从谈起）。

        各档（1C / 3C / 4C）**一个都不选也是合法的** —— 用户可能只想先建一条
        "先筛选、后补声骸"的配置，或者这次只想限制其中一档。以前这里会报
        「4C 声骸为必填项」，正是截图里那条拦人的提示。

        ⚠ 保留的检查：**已经选了**的声骸必须带上属性 —— 半截数据（选了声骸
        没选属性）会让筛选步骤生成不出来，属于真错误，不是"没填"。
        这条只在 ``picks`` 非空时生效，不影响"一个都不填"。
        """
        errors: list[str] = []

        if not self.character.strip():
            errors.append("角色为必填项")

        if not self.echo_set.strip():
            # 声骸依赖套装，套装没选时先说这件事
            errors.append("请先选择声骸套装")
        elif find_echo_set(self.echo_set) is None:
            errors.append(f"声骸套装「{self.echo_set}」不在数据集里")
        else:
            # 各档**不再是必填** —— 只校验"选了的那些"是否完整。
            for _cost, label in COST_SECTIONS:
                picks = self.picks_of(_cost)
                missing = [p.echo for p in picks if not p.stats]
                if missing:
                    errors.append(f"{label} 声骸「{'、'.join(missing)}」还没选属性")

        return errors

    # ------------------------------------------------------------ 展示
    def summary(self) -> str:
        """列表里那行摘要：套装 + 三个档位。一档选了多个就用顿号连起来。"""
        parts = [self.echo_set or "未选套装"]
        for cost, label in COST_SECTIONS:
            picks = self.picks_of(cost)
            text = "、".join(p.describe() for p in picks) if picks else "未选"
            parts.append(f"{label} {text}")
        return " · ".join(parts)

    def sync_avatar(self) -> None:
        """角色能匹配到数据集时，顺手把头补齐（匹配不到就留空）。"""
        info = find_character(self.character)
        self.avatar = info.avatar if info else ""

    @property
    def display_avatar(self) -> str:
        """界面上该显示哪张头像：用户自选的优先，否则用角色联动的。"""
        return self.custom_avatar or self.avatar

    def main_stats_by_cost(self) -> dict[int, tuple[str, ...]]:
        """每档**要筛的主属性** = 该档所有声骸 pick 上勾的属性并集。

        游戏「主音属性筛选」弹窗里，4C / 3C / 1C 各是一个页签、每个页签一组
        主属性勾选框 —— 配置里"每档声骸各带属性"其实就是在表达这个
        （用户 2026-09-26："另外这里也是对应上的"）。

        按数据集里 `STATS_BY_COST` 的顺序去重，保证生成的点击顺序稳定。
        """
        from .game_data import STATS_BY_COST

        result: dict[int, tuple[str, ...]] = {}
        for cost in sorted(self.picks, reverse=True):
            wanted = {s for pick in self.picks_of(cost) for s in pick.stats if s}
            if not wanted:
                continue
            known = [s for s in STATS_BY_COST.get(cost, ()) if s in wanted]
            # 数据集里没有的（老数据 / 手改过）也带上，别默默丢掉
            extra = sorted(wanted - set(known))
            result[cost] = tuple(known) + tuple(extra)
        return result

    # ------------------------------------------------------------ 序列化
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "character": self.character,
            "avatar": self.avatar,
            "custom_avatar": self.custom_avatar,
            "echo_set": self.echo_set,
            "status": normalize_status(self.status),
            "qualities": list(normalize_qualities(self.qualities)),
            "picks": {
                str(cost): [
                    # 只写新格式（stats 列表）；旧文件由 parse_picks 的兼容读取兜底
                    {"echo": p.echo, "stats": list(p.stats)}
                    for p in picks
                ]
                for cost, picks in self.picks.items()
                if picks
            },
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Loadout":
        """从 JSON 字典还原。缺字段一律用默认值，别让半截数据把整个列表带崩。"""
        picks: dict[int, list[EchoPick]] = {}
        raw_picks = data.get("picks")
        if isinstance(raw_picks, dict):
            for key, value in raw_picks.items():
                try:
                    cost = int(key)
                except (TypeError, ValueError):
                    continue
                parsed = parse_picks(value)
                if parsed:
                    picks[cost] = parsed

        return cls(
            id=str(data.get("id", "")),
            character=str(data.get("character", "")),
            avatar=str(data.get("avatar", "")),
            custom_avatar=str(data.get("custom_avatar", "")),
            echo_set=str(data.get("echo_set", "")),
            # 老数据没有这两个字段 → normalize 会给出默认（未标记 / 五星）
            status=normalize_status(data.get("status")),
            qualities=normalize_qualities(data.get("qualities")),
            picks=picks,
            updated_at=str(data.get("updated_at", "")),
        )


class LoadoutStore:
    """配置的本地存储（一个 JSON 文件装全部）。

    读的时候尽量宽容：文件不存在 / 内容损坏 / 单条格式不对，都只跳过，不抛异常
    —— 配置文件坏了不该让整个程序起不来。
    """

    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path is not None else DEFAULT_STORE_PATH
        self._items: list[Loadout] = []
        self.load()

    # ------------------------------------------------------------ 读写
    def load(self) -> None:
        self._items = []
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return

        records = raw.get("loadouts") if isinstance(raw, dict) else raw
        if not isinstance(records, list):
            return
        for record in records:
            if isinstance(record, dict):
                self._items.append(Loadout.from_dict(record))

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "loadouts": [item.to_dict() for item in self._items]}
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ------------------------------------------------------------ 查询
    def all(self) -> list[Loadout]:
        """按更新时间倒序（最近改的排前面）。"""
        return sorted(self._items, key=lambda x: x.updated_at, reverse=True)

    def __len__(self) -> int:
        return len(self._items)

    def get(self, loadout_id: str) -> Loadout | None:
        for item in self._items:
            if item.id == loadout_id:
                return item
        return None

    def by_character(self, character: str) -> list[Loadout]:
        return [item for item in self._items if item.character == character]

    def occupied_characters(self) -> set[str]:
        """已经被占用的角色名 —— **一个角色只能有一条配置**（用户 2026-09-26 要求）。

        界面拿它把已占用的角色从下拉里剔掉；保存时再校一次（见
        ``LoadoutDialog.validate``）—— 候选里没有拦不住手打的字。

        ⚠ 为什么 ``add()`` **不**在这里硬拦：loadout 的主键是 ``id`` 不是角色名，
        而且**老文件里可能已经存在同一角色的多条**（旧版允许），
        那些必须照常读得出来、显示得出来（用户自己删多的那条）。
        所以"一角色一条"是**界面层的规则**，不是存储层的不变量 ——
        这点和 :class:`~src.core.echo_profile.EchoProfileStore` 不同，
        那边主键本来就是名字，天然拒绝重名。
        """
        return {item.character for item in self._items if item.character}

    def has_character(self, character: str) -> bool:
        """这个角色是不是已经有配置了（界面保存前的校验用）。"""
        return character in self.occupied_characters()

    # ------------------------------------------------------------ 增删改
    def add(self, loadout: Loadout) -> Loadout:
        if not loadout.id:
            loadout.id = uuid.uuid4().hex[:12]
        loadout.updated_at = _now()
        loadout.sync_avatar()
        self._items.append(loadout)
        self.save()
        return loadout

    def update(self, loadout: Loadout) -> bool:
        for index, item in enumerate(self._items):
            if item.id == loadout.id:
                loadout.updated_at = _now()
                loadout.sync_avatar()
                self._items[index] = loadout
                self.save()
                return True
        return False

    def remove(self, loadout_id: str) -> bool:
        for index, item in enumerate(self._items):
            if item.id == loadout_id:
                del self._items[index]
                self.save()
                return True
        return False

    def clear(self) -> None:
        self._items.clear()
        self.save()


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
