"""「角色战斗」配置 —— 配置页里的第三类配置。

用户 2026-09-30 要求新增：

    配置增加角色战斗配置，角色（下拉列表选择）；角色头像（与角色联动）；
    有角色技能快捷键，技能快捷键分为声骸技能（默认 Q）、共鸣技能（默认 E）、
    共鸣解放（默认 R）；角色链路 +− 按钮 加 1 减 1，最大为 6 最小为 0；
    角色战斗脚本

## 名字就是**角色名**（和另外两类一致）

一条配置 = 一个角色，名字只能从角色列表里选，**同一个角色只能有一条**。
理由同 :mod:`src.core.echo_profile`：行上的头像是拿名字去
``game_data.find_character()`` 查的，自由文本会导致**头像消失**。

## 「角色链路」是什么

鸣潮的**合轴/变奏链条** —— 一个角色最多能接几段。用户要求用 +/− 按钮调，
**范围 0~6**。存成 int，越界的值在加载时夹回来（手改过 JSON 也不能让界面崩）。

## ★ 现在**只存不跑**

用户明确："先只存不跑" —— 快捷键和战斗脚本都只是**存下来**，
界面能编辑、能保存、能回填；**暂时不接任何按键执行**。
以后要做执行时，从这里读、显式注入任务即可（别去和工具页的设置联动）。

## 纯逻辑

core 层，不依赖 Qt，可单独单测。
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

#: 「配置类型」的稳定标识（见 :mod:`src.core.loadout` 里的同名说明）。
KIND = "battle_profile"

#: 文件名（和另外两类一样，放在 tool_settings.json 旁边 —— 那套隔离自动覆盖）
FILE_NAME = "battle_profiles.json"

#: 名字长度上限（角色名最长 6 个字，留一倍余量做防御）
MAX_NAME_LENGTH = 12

#: 技能快捷键的**默认值**（用户指定：声骸 Q / 共鸣技能 E / 共鸣解放 R）。
DEFAULT_SKILL_KEYS = {
    "echo": "Q",          # 声骸技能
    "resonance": "E",     # 共鸣技能
    "liberation": "R",    # 共鸣解放
}

#: 三个快捷键在界面上的显示名（顺序就是界面上的顺序）。
SKILL_KEY_LABELS = (
    ("echo", "声骸技能"),
    ("resonance", "共鸣技能"),
    ("liberation", "共鸣解放"),
)

#: 快捷键键名长度上限。只支持**单键**（一个字母/数字），
#: 所以 1 就够；留 2 是防手改数据里塞了 "Ctrl" 之类把界面撑破。
MAX_KEY_LENGTH = 2

#: 「角色链路」的范围（用户指定：最大 6、最小 0）—— 界面上的 +/− 按它夹。
MIN_CHAIN = 0
MAX_CHAIN = 6

#: 战斗脚本长度上限。纯粹是防御：正常脚本也就几百字，
#: 但手改 JSON 塞个几 MB 进去会把输入框卡死。
MAX_SCRIPT_LENGTH = 20000


def battle_profiles_file() -> Path:
    """配置文件位置 —— **跟着 tool_settings 走**（见 echo_profile 的同名说明）。"""
    from . import tool_settings  # noqa: PLC0415 - 避免模块级循环导入

    return tool_settings.settings_file().parent / FILE_NAME


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def clamp_chain(value) -> int:
    """把链路夹进 :data:`MIN_CHAIN` ~ :data:`MAX_CHAIN`。

    ⚠ 界面上的 +/− 也要用它 —— 边界逻辑只有这一份，
    否则"按钮夹了、加载时没夹"会出现越界值。
    """
    try:
        number = int(value)
    except (TypeError, ValueError):
        return MIN_CHAIN
    return max(MIN_CHAIN, min(MAX_CHAIN, number))


def _clean_key(value, default: str) -> str:
    """规范化一个快捷键。

    * 空 / 非字符串 → 用默认值（**不是空串** —— 界面上一格空着会让人以为坏了）；
    * 去掉首尾空白、转大写（``q`` 和 ``Q`` 是同一个键，统一存大写免得看着像两个）；
    * 太长就截断（只支持单键）。
    """
    text = str(value or "").strip().upper()
    if not text:
        return default
    return text[:MAX_KEY_LENGTH]


@dataclass
class BattleProfile:
    """一套「角色战斗」配置。

    :param name: 角色名（= 配置名，只能从角色列表里选）
    :param skill_keys: ``{"echo": "Q", "resonance": "E", "liberation": "R"}``
    :param chain: 角色链路（0~6）
    :param script: 角色战斗脚本（**暂时只存不跑**）
    """

    name: str
    skill_keys: dict = field(default_factory=lambda: dict(DEFAULT_SKILL_KEYS))
    chain: int = 0
    script: str = ""
    created: str = ""
    #: 稳定 id —— 和另两类一样：名字（=角色）会变，任务步骤要指着"这一条"。
    id: str = ""

    def __post_init__(self) -> None:
        self.name = str(self.name or "").strip()[:MAX_NAME_LENGTH]
        self.id = str(self.id or "").strip() or uuid.uuid4().hex[:12]
        self.chain = clamp_chain(self.chain)
        self.script = str(self.script or "")[:MAX_SCRIPT_LENGTH]
        if not self.created:
            self.created = _now()

        # ⚠ 三个键**都要有**：老数据缺键时补默认值，界面才不会出现空格子
        raw = self.skill_keys if isinstance(self.skill_keys, dict) else {}
        self.skill_keys = {
            key: _clean_key(raw.get(key), default)
            for key, default in DEFAULT_SKILL_KEYS.items()
        }

    # ------------------------------------------------------------------ 展示
    def key_of(self, skill: str) -> str:
        """取某个技能的快捷键（``"echo"`` / ``"resonance"`` / ``"liberation"``）。"""
        return self.skill_keys.get(skill, DEFAULT_SKILL_KEYS.get(skill, ""))

    @property
    def keys_text(self) -> str:
        """``"声骸 Q · 共鸣技能 E · 共鸣解放 R"`` —— 列表行那一行小字。"""
        return " · ".join(
            f"{label} {self.key_of(key)}" for key, label in SKILL_KEY_LABELS)

    def describe(self) -> str:
        """一行摘要（列表里不点开就知道这套是什么）。"""
        parts = [self.keys_text, f"链路 {self.chain}"]
        if self.script.strip():
            # 脚本内容可能很长 —— 只报"有没有 / 多少行"
            parts.append(f"脚本 {len(self.script.strip().splitlines())} 行")
        else:
            parts.append("脚本（空）")
        return " · ".join(parts)

    # ------------------------------------------------------------------ 序列化
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "skill_keys": dict(self.skill_keys),
            "chain": self.chain,
            "script": self.script,
            "created": self.created,
            "id": self.id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BattleProfile":
        """从存盘数据还原。坏数据一律走默认值，**不抛异常**。

        ⚠ ``script`` 用 ``get`` 而不是 ``[]``：老数据没有这个键的时候
        直接下标会 KeyError，一条坏数据就把整份配置读不出来。
        """
        data = data if isinstance(data, dict) else {}
        return cls(
            name=str(data.get("name", "") or ""),
            skill_keys=data.get("skill_keys") or {},
            chain=data.get("chain", MIN_CHAIN),
            script=data.get("script", ""),
            created=str(data.get("created", "") or ""),
            id=str(data.get("id", "") or ""),
        )


class BattleProfileStore:
    """「角色战斗」配置的读写。接口和另外两类**保持一致**（好记、好复用）。"""

    def __init__(self, path: Path | str | None = None):
        self._path = Path(path) if path is not None else None
        self._items: list[BattleProfile] = []
        self.load()

    @property
    def path(self) -> Path:
        return self._path if self._path is not None else battle_profiles_file()

    # ------------------------------------------------------------------ 读写
    def load(self) -> None:
        path = self.path
        self._items = []
        if not path.exists():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("角色战斗配置读不出来（%s）：%s —— 当作没有", path, exc)
            return
        if not isinstance(raw, dict):
            return

        items = raw.get("profiles")
        if isinstance(items, list):
            # 名字为空的条目直接丢 —— 名字就是角色名，没名字的条目
            # 既查不到头像、也点不出什么（坏数据，不兜底）
            self._items = [p for p in (BattleProfile.from_dict(x) for x in items)
                           if p.name]
            # 老数据没有 id → 补发后**立刻落盘**，否则每次启动都换新的，
            # 任务流程里指向它的步骤就永远找不到（和 echo_profile 同一个坑）
            if self._items and not all(
                    isinstance(x, dict) and x.get("id") for x in items):
                logger.info("给 %d 条「角色战斗」配置补发稳定 id 并落盘",
                            len(self._items))
                self.save()

    def save(self) -> None:
        path = self.path
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"profiles": [p.to_dict() for p in self._items]}
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
            tmp.replace(path)
        except OSError as exc:
            # 写不下来不该让功能不可用（和 tool_settings 一个态度）
            logger.warning("角色战斗配置写不进去（%s）：%s", path, exc)

    # ------------------------------------------------------------------ 查询
    def all(self) -> list[BattleProfile]:
        return list(self._items)

    def names(self) -> list[str]:
        return [p.name for p in self._items]

    def __len__(self) -> int:
        return len(self._items)

    def get(self, name: str) -> BattleProfile | None:
        want = str(name or "").strip()
        for p in self._items:
            if p.name == want:
                return p
        return None

    def has(self, name: str) -> bool:
        return self.get(name) is not None

    def by_id(self, item_id: str) -> BattleProfile | None:
        """按稳定 id 找（任务流程里的步骤用它指向配置）。"""
        want = str(item_id or "").strip()
        if not want:
            return None
        for profile in self._items:
            if profile.id == want:
                return profile
        return None

    def occupied_characters(self) -> set[str]:
        """已被占用的角色名 —— 界面用它把"一角色一条"做成下拉里选不到。"""
        return {p.name for p in self._items}

    # ------------------------------------------------------------------ 改
    def add(self, profile: BattleProfile) -> bool:
        """加一条。名字（＝角色）重复直接拒绝。"""
        if not profile.name or self.has(profile.name):
            return False
        profile.name = profile.name[:MAX_NAME_LENGTH]
        self._items.append(profile)
        self.save()
        return True

    def update(self, profile: BattleProfile) -> bool:
        for i, p in enumerate(self._items):
            if p.name == profile.name:
                self._items[i] = profile
                self.save()
                return True
        return False

    def remove(self, name: str) -> bool:
        target = self.get(name)
        if target is None:
            return False
        self._items = [p for p in self._items if p.name != target.name]
        self.save()
        return True

    def rename(self, old: str, new: str) -> bool:
        """改名（＝换角色）。新名字为空 / 已被别的配置占用 → 拒绝。"""
        new = str(new or "").strip()[:MAX_NAME_LENGTH]
        target = self.get(old)
        if target is None or not new or (new != old and self.has(new)):
            return False
        target.name = new
        self.save()
        return True
