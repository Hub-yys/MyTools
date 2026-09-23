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

#: 默认存放位置：用户数据目录下的 loadouts.json
#: （开发态 = <项目根>/data；打包后 = %LOCALAPPDATA%/MyTools，见 core/paths.py）
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
        """检查必填项，返回错误说明列表（空列表表示通过）。"""
        errors: list[str] = []

        if not self.character.strip():
            errors.append("角色为必填项")

        if not self.echo_set.strip():
            # 声骸依赖套装，套装没选时先说这件事
            errors.append("请先选择声骸套装")
        elif find_echo_set(self.echo_set) is None:
            errors.append(f"声骸套装「{self.echo_set}」不在数据集里")
        else:
            info = find_echo_set(self.echo_set)
            required = info.required_costs if info else (COST_4, COST_3, COST_1)
            for cost, label in COST_SECTIONS:
                if cost not in required:
                    continue  # 1 件套只要一个声骸，别的档位不该被要求
                picks = self.picks_of(cost)
                if not picks:
                    errors.append(f"{label} 声骸为必填项")
                    continue
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

    # ------------------------------------------------------------ 序列化
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "character": self.character,
            "avatar": self.avatar,
            "custom_avatar": self.custom_avatar,
            "echo_set": self.echo_set,
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
