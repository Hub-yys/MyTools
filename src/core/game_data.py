"""游戏静态数据：角色、声骸套装、声骸（4C / 3C / 1C）。

## 数据从哪来

数据放在同目录的 ``data/`` 下，两个 JSON 文件：

- ``wuwa_echo_sets.json`` —— 套装名 + **套装效果原文** + （部分）声骸明细
- ``wuwa_characters.json`` —— 角色名 + 稀有度 / 属性 / 武器

两处都带着 ``_source`` / ``_fetched`` 字段，注明整理自哪里、什么时候抓的。
游戏更新后重跑 ``tools/refresh_wuwa_data.py`` 就行。

## 图标仍然是占位图

角色头像和套装图标**没有**做成官方的 —— 那些是库洛的美术素材。
需要的话自己往 ``assets/game/`` 里放，文件名对得上就自动生效：

- 角色头像 → ``assets/game/avatars/<角色名>.png``
- 套装图标 → ``assets/game/echo_sets/<套装名>.png``
- 声骸图标 → ``assets/game/echoes/<声骸名>.png``

（用中文名做文件名，是刻意的：你自己丢文件进去时最不容易搞错。）
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from . import paths

logger = logging.getLogger(__name__)

#: 资源根目录：assets/game/（只读，跟着程序走）
ASSETS_ROOT = paths.resource_dir("assets", "game")

#: 游戏数据 JSON 目录（会被「资源库更新」改写 → 算用户数据）
DATA_ROOT = paths.game_data_dir()

#: 声骸费用（游戏里按 COST 分 4C / 3C / 1C 三档）
COST_4, COST_3, COST_1 = 4, 3, 1

#: 三档声骸各自可能出现的主词条（界面上是单选：一个声骸只能挑一条属性）
#: 六种属性伤害加成。3C 的属性伤害加成是**分属性**出的（冷凝/热熔/气动/导电/衍射/湮灭），
#: 界面上要逐条列出来，而不是一个笼统的"属性伤害加成"。
ELEMENT_DAMAGE_STATS: tuple[str, ...] = (
    "冷凝伤害加成",
    "热熔伤害加成",
    "气动伤害加成",
    "导电伤害加成",
    "衍射伤害加成",
    "湮灭伤害加成",
)

#: 各档位声骸的**主词条池** —— 游戏里这个档位实际能出的主词条，一条不多一条不少。
#:
#: 依据（库街区官方社区 / 3DM / gamekee / okemu 四个来源一致）：
#:   * 4C 主词条 6 种：暴击 / 暴击伤害 / 治疗加成 / 攻击% / 防御% / 生命%（**没有属性伤害加成**）
#:   * 3C 主词条 5 类：攻击% / 防御% / 生命% / 共鸣效率 / 属性伤害加成（六种属性各算一条）
#:   * 1C 主词条 3 种：只有百分比，**没有固定值**
#:
#: 三档的"固定攻击 / 固定生命"是声骸**自带的固定词条**，不是可刷的主词条，所以都不列。
STATS_BY_COST: dict[int, tuple[str, ...]] = {
    COST_4: ("暴击", "暴击伤害", "治疗加成", "攻击百分比", "防御百分比", "生命百分比"),
    COST_3: ("攻击百分比", "防御百分比", "生命百分比", "共鸣效率") + ELEMENT_DAMAGE_STATS,
    COST_1: ("攻击百分比", "防御百分比", "生命百分比"),
}

#: 界面里 4C/3C/1C 三段的显示顺序与标题
COST_SECTIONS: tuple[tuple[int, str], ...] = (
    (COST_4, "4C"),
    (COST_3, "3C"),
    (COST_1, "1C"),
)


@dataclass(frozen=True)
class EchoInfo:
    """一个声骸。``stats`` 是它的候选主词条，界面上从中**单选**一条。"""

    name: str
    icon: str          # 相对 assets/game/ 的路径
    cost: int
    stats: tuple[str, ...] = ()
    #: 声骸技能说明（来自 bwiki，少数页面没写就是空串）
    skill: str = ""
    #: 技能冷却，如 ``"20s"``；没收录就是空串
    cooldown: str = ""


@dataclass(frozen=True)
class EchoSetInfo:
    """一套声骸套装：图标 + 套装效果 + （可能为空的）声骸明细。"""

    name: str
    icon: str
    #: 出场版本（如 ``"3.5"``）。来自人工整理的 ``data/wuwa_set_versions.json``；
    #: wiki 那张套装表是按名字排的、没有版本信息，所以这栏单独维护。
    version: str = ""
    #: 套装效果：``((2, "两件套效果文字"), (5, "五件套效果文字"),)``
    #: 新版还有 3 件套 / 1 件套，所以件数不写死。
    effects: tuple[tuple[int, str], ...] = ()
    echoes: tuple[EchoInfo, ...] = ()

    @property
    def version_key(self) -> tuple[int, ...]:
        """把 ``"3.5"`` 变成 ``(3, 5)`` 好排序；没有版本信息就返回空元组（排在最后）。"""
        parts = (self.version or "").split(".")
        try:
            return tuple(int(p) for p in parts if p)
        except ValueError:  # 版本号写成别的格式了，当没有处理
            return ()

    def by_cost(self, cost: int) -> tuple[EchoInfo, ...]:
        """取出某一档（4C/3C/1C）的全部声骸。"""
        return tuple(e for e in self.echoes if e.cost == cost)

    @property
    def piece_counts(self) -> tuple[int, ...]:
        """这套的件套数。常规是 ``(2, 5)``，新版有 ``(3,)``，联动套还有 ``(1,)``。"""
        return tuple(sorted({pieces for pieces, _text in self.effects}))

    @property
    def is_single_piece(self) -> bool:
        """1 件套 —— 装**一个**声骸就生效（3.4 联动套「碎梦亡鬼之魇」是这种）。

        这种套装**本来就只有 4C**，它的 3C/1C 不是"没收录"、而是压根不存在。
        """
        return self.piece_counts == (1,)

    @property
    def required_costs(self) -> tuple[int, ...]:
        """配置里**必须选声骸**的档位。

        常规套装三档都要；1 件套只要一个（就是它有的那一档）。
        """
        if self.is_single_piece:
            for cost in (COST_4, COST_3, COST_1):
                if self.by_cost(cost):
                    return (cost,)
        return (COST_4, COST_3, COST_1)

    @property
    def has_echoes(self) -> bool:
        """有没有收录声骸明细（哪怕只有一档）。"""
        return bool(self.echoes)

    @property
    def is_configurable(self) -> bool:
        """能不能在配置页填完整 —— :attr:`required_costs` 里每一档都得有得选。"""
        return all(self.by_cost(cost) for cost in self.required_costs)

    @property
    def effect_lines(self) -> tuple[str, ...]:
        """效果逐条成行，形如 ``"2件套：攻击力提升10%"``。"""
        return tuple(f"{pieces}件套：{text}" for pieces, text in self.effects)

    @property
    def description(self) -> str:
        """效果拼成一段多行文本（详情、日志里用）。"""
        return "\n".join(self.effect_lines)


@dataclass(frozen=True)
class CharacterInfo:
    name: str
    avatar: str        # 相对 assets/game/ 的路径
    rarity: int = 0    # 0 表示未知
    element: str = ""  # 气动 / 冷凝 / 导电 / 热熔 / 湮灭 / 衍射
    weapon: str = ""   # 迅刀 / 长刃 / 佩枪 / 臂铠 / 音感仪

    @property
    def tagline(self) -> str:
        """卡片下面那行小字，例如 ``"5星 · 热熔 · 迅刀"``。"""
        parts = []
        if self.rarity:
            parts.append(f"{self.rarity}星")
        if self.element:
            parts.append(self.element)
        if self.weapon:
            parts.append(self.weapon)
        return " · ".join(parts)


@dataclass(frozen=True)
class WeaponInfo:
    """一把武器。图标路径按名字推导（``weapons/<名字>.png``）。"""

    name: str
    type: str = ""     # 迅刀 / 长刃 / 佩枪 / 臂铠 / 音感仪
    stat: str = ""     # 主词条：攻击 / 生命 / 防御 / 共鸣效率 / 暴击率 / 暴击伤害
    rarity: int = 0    # 0 表示未知

    @property
    def icon(self) -> str:
        """图标相对路径。⚠ 推导而不是存进数据文件 —— 文件名就是武器名，
        存两份迟早对不上（角色那边也是这么处理的）。"""
        return f"weapons/{self.name}.png"

    @property
    def tagline(self) -> str:
        """卡片/列表下面那行小字，例如 ``"5星 · 迅刀 · 暴击率"``。"""
        parts = []
        if self.rarity:
            parts.append(f"{self.rarity}星")
        if self.type:
            parts.append(self.type)
        if self.stat:
            parts.append(self.stat)
        return " · ".join(parts)


# --------------------------------------------------------------------- 加载

def _load_json(filename: str) -> dict:
    """读数据文件。文件缺失或损坏时返回空 dict —— 界面退化成空列表，不崩。"""
    path = DATA_ROOT / filename
    try:
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        logger.warning("数据文件不存在：%s", path)
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("数据文件读不出来（%s）：%s", path, exc)
        return {}
    return data if isinstance(data, dict) else {}


def _build_characters(raw: dict) -> tuple[CharacterInfo, ...]:
    result: list[CharacterInfo] = []
    for item in raw.get("characters", []) or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        result.append(
            CharacterInfo(
                name=name,
                avatar=f"avatars/{name}.png",
                rarity=int(item.get("rarity", 0) or 0),
                element=str(item.get("element", "") or ""),
                weapon=str(item.get("weapon", "") or ""),
            )
        )
    return tuple(result)


def _build_weapons(raw: dict) -> tuple[WeaponInfo, ...]:
    """``wuwa_weapons.json`` → 武器元组。

    ⚠ 图标**不存进数据文件**（:attr:`WeaponInfo.icon` 按名字推导）——
    文件名就是武器名，存两份迟早对不上。
    """
    result: list[WeaponInfo] = []
    for item in raw.get("weapons", []) or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        try:
            rarity = int(item.get("rarity", 0) or 0)
        except (TypeError, ValueError):
            rarity = 0
        result.append(
            WeaponInfo(
                name=name,
                type=str(item.get("type", "") or ""),
                stat=str(item.get("stat", "") or ""),
                rarity=rarity,
            )
        )
    return tuple(result)


def _build_echo_sets(raw: dict) -> tuple[EchoSetInfo, ...]:
    result: list[EchoSetInfo] = []
    for item in raw.get("sets", []) or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue

        effects: list[tuple[int, str]] = []
        for entry in item.get("effects", []) or []:
            if not isinstance(entry, dict):
                continue
            text = str(entry.get("text", "")).strip()
            if not text:
                continue
            effects.append((int(entry.get("pieces", 0) or 0), text))

        echoes: list[EchoInfo] = []
        for entry in item.get("echoes", []) or []:
            if not isinstance(entry, dict):
                continue
            echo_name = str(entry.get("name", "")).strip()
            if not echo_name:
                continue
            cost = int(entry.get("cost", 0) or 0)
            extra = ECHO_SKILLS.get(echo_name, {})
            echoes.append(
                EchoInfo(
                    name=echo_name,
                    icon=f"echoes/{echo_name}.png",
                    cost=cost,
                    stats=STATS_BY_COST.get(cost, ()),
                    skill=str(extra.get("skill", "") or ""),
                    cooldown=str(extra.get("cooldown", "") or ""),
                )
            )

        result.append(
            EchoSetInfo(
                name=name,
                icon=f"echo_sets/{name}.png",
                version=SET_VERSIONS.get(name, ""),
                effects=tuple(effects),
                echoes=tuple(echoes),
            )
        )
    return tuple(result)


#: 盘上读回来的原始 JSON（``reload_data()`` 会重新赋值）
_CHARACTER_DATA: dict = {}
_ECHO_SET_DATA: dict = {}
_SET_VERSION_DATA: dict = {}
_SKILL_DATA: dict = {}
_WEAPON_DATA: dict = {}

#: 声骸名 → ``{"skill": 技能说明, "cooldown": 冷却}``。抓取见 tools/fetch_wuwa_echo_skills.py。
ECHO_SKILLS: dict[str, dict[str, str]] = {}

#: 套装名 -> 出场版本（如 ``"3.5"``）。人工整理，见同目录的 JSON。
SET_VERSIONS: dict[str, str] = {}

#: ``{名字: 图床 URL}`` —— 角色 / 套装 / 声骸 / 武器的图标来源。
#: 由「资源库更新」抓下来存在 ``wuwa_echo_skills.json`` 的 ``icon_urls`` 里。
#: 自动补图（``core/assets.py``）靠它知道该去哪儿下图。
ICON_URLS: dict[str, str] = {}

# --------------------------------------------------------------------- 内存数据
#
# ⚠ 下面这几个名字是**公用的全局清单**：别的模块是
# ``from ..core.game_data import CHARACTERS`` 这样把名字直接拿走的。
# 所以：
#   1. 它们必须是**可变容器**（list / dict），
#   2. :func:`reload_data` 只能**就地改内容**（``CHARACTERS[:] = ...`` / ``dict.clear()``），
#      **绝不能重新赋值**（那样只是换掉本模块自己的名字，别人手里还是旧对象）。
CHARACTERS: list[CharacterInfo] = []

#: 全部武器（图鉴页用）。和 ``CHARACTERS`` 一样是**公用可变清单**，
#: ``reload_data`` 只能就地改内容（``WEAPONS[:] = ...``）。
WEAPONS: list[WeaponInfo] = []


def _sorted_newest_first(items: tuple[EchoSetInfo, ...]) -> tuple[EchoSetInfo, ...]:
    """按出场版本**倒序**排 —— 最新出的套装排在最前面。

    先按名字排一遍，再按版本倒序：Python 的排序是稳定的，所以同一版本内
    会保持名称顺序（顺序可预期，不会每次跑都不一样）。
    没有版本信息的（``version_key`` 是空元组）会被排到最后。
    """
    ordered = sorted(items, key=lambda item: item.name)
    ordered.sort(key=lambda item: item.version_key, reverse=True)
    return tuple(ordered)


ECHO_SETS: list[EchoSetInfo] = []

#: **配置页能用**的套装：必须 4C/3C/1C 三档都有声骸可选。
CONFIGURABLE_ECHO_SETS: list[EchoSetInfo] = []


def _build_echoes_by_cost() -> dict[int, tuple[EchoInfo, ...]]:
    """全部声骸（按名字去重）按 4C/3C/1C 分组，组内按名字排。

    同一条声骸会挂在多个套装名下（如「重工铁蹄」），这里只留一份 ——
    资源库的「声骸图鉴」按这个展示，一份技能说明不会被重复列出来。
    """
    seen: dict[int, dict[str, EchoInfo]] = {cost: {} for cost, _ in COST_SECTIONS}
    for echo_set in ECHO_SETS:
        for item in echo_set.echoes:
            if item.cost in seen:
                seen[item.cost].setdefault(item.name, item)
    return {
        cost: tuple(sorted(by_name.values(), key=lambda item: item.name))
        for cost, by_name in seen.items()
    }


#: 全量声骸图鉴：``{4: (...), 3: (...), 1: (...)}``，资源库「声骸图鉴」分区用。
ECHOES_BY_COST: dict[int, tuple[EchoInfo, ...]] = {}

#: 数据来源信息（资源库页面上会显示，让用户知道这些字是从哪来的、什么时候的）
DATA_META: dict[str, object] = {}

#: 数据版本号：每重载一次 +1。界面靠它判断"盘上的数据换过了，该重建了"。
DATA_VERSION = 0


def _load_into_memory(version: int) -> None:
    """把 JSON 读进内存 —— **就地填**上面那些公用容器。

    首启动和「获取最新数据」之后都走这里：前者靠 ``main.py`` 在导入前先播种数据，
    后者让更新完的数据立刻生效（不必重启）。
    """
    global _CHARACTER_DATA, _ECHO_SET_DATA, _SET_VERSION_DATA, _SKILL_DATA, DATA_VERSION
    global _WEAPON_DATA

    _CHARACTER_DATA = _load_json("wuwa_characters.json")
    _ECHO_SET_DATA = _load_json("wuwa_echo_sets.json")
    _SET_VERSION_DATA = _load_json("wuwa_set_versions.json")
    _SKILL_DATA = _load_json("wuwa_echo_skills.json")
    _WEAPON_DATA = _load_json("wuwa_weapons.json")

    # 技能 / 版本要先更新：_build_echo_sets 会去查这两个表
    ECHO_SKILLS.clear()
    ECHO_SKILLS.update({
        str(name): {
            "skill": str(info.get("skill", "") or ""),
            "cooldown": str(info.get("cooldown", "") or ""),
        }
        for name, info in dict(_SKILL_DATA.get("echoes", {})).items()
        if isinstance(info, dict)
    })

    SET_VERSIONS.clear()
    SET_VERSIONS.update({
        str(name): str(ver)
        for name, ver in dict(_SET_VERSION_DATA.get("versions", {})).items()
    })

    # 图标 URL：自动补图要靠它（角色 / 套装 / 声骸 / 武器混在一张表里）
    ICON_URLS.clear()
    ICON_URLS.update({
        str(name): str(url)
        for name, url in dict(_SKILL_DATA.get("icon_urls", {})).items()
        if str(url).startswith("http")
    })

    CHARACTERS[:] = _build_characters(_CHARACTER_DATA)
    WEAPONS[:] = _build_weapons(_WEAPON_DATA)
    ECHO_SETS[:] = _sorted_newest_first(_build_echo_sets(_ECHO_SET_DATA))
    CONFIGURABLE_ECHO_SETS[:] = [s for s in ECHO_SETS if s.is_configurable]

    ECHOES_BY_COST.clear()
    ECHOES_BY_COST.update(_build_echoes_by_cost())

    DATA_META.clear()
    DATA_META.update({
        "fetched": str(_ECHO_SET_DATA.get("_fetched", "") or ""),
        "game_version": str(_ECHO_SET_DATA.get("_game_version", "") or ""),
        "echo_sets_source": _ECHO_SET_DATA.get("_source", ""),
        "set_versions_source": _SET_VERSION_DATA.get("_source", ""),
        "characters_source": _CHARACTER_DATA.get("_source", ""),
        "characters_note": str(_CHARACTER_DATA.get("_note", "") or ""),
        "echo_sets_note": str(_ECHO_SET_DATA.get("_note", "") or ""),
    })

    DATA_VERSION = version
    logger.info(
        "游戏数据载入：角色 %d 个 / 套装 %d 套 / 声骸 %d 个（版本 %d）",
        len(CHARACTERS), len(ECHO_SETS),
        sum(len(items) for items in ECHOES_BY_COST.values()), DATA_VERSION,
    )


def reload_data() -> None:
    """重新读盘、**就地刷新**上面那些公用容器（版本号 +1）。

    用途：①「资源库更新」写完盘之后立刻生效；
         ② ``main.py`` 万一顺序又错了，界面还能自己救回来（见 :func:`ensure_loaded`）。
    """
    _load_into_memory(DATA_VERSION + 1)


def is_loaded() -> bool:
    """内存里到底有没有数据。"""
    return bool(CHARACTERS or ECHO_SETS)


def ensure_loaded() -> bool:
    """内存是空的就重新读一次盘。返回是否真的重载了。

    首启动如果 ``game_data`` 被提前导入（种子还没落盘），内存快照就是空的 ——
    界面在真正渲染前调一下这里，白页就没了。
    """
    if is_loaded():
        return False
    reload_data()
    return True


# 模块导入时先装一次（顺序问题在 main.py 里已经堵住，这里是常规路径）
_load_into_memory(1)


# --------------------------------------------------------------------- 查询

def icon_path(relative: str) -> Path:
    """把数据集里的相对路径转成绝对路径。"""
    return ASSETS_ROOT / relative


def find_character(name: str) -> CharacterInfo | None:
    """按**精确**名称找角色（头像联动用）。找不到返回 None。"""
    key = (name or "").strip()
    if not key:
        return None
    for item in CHARACTERS:
        if item.name == key:
            return item
    return None


def match_characters(keyword: str) -> tuple[CharacterInfo, ...]:
    """按输入内容匹配角色（包含匹配）。空关键词返回全部，便于点开就选。

    匹配不到会返回空元组 —— 界面上表现为"下拉列表是空白的"。
    """
    key = (keyword or "").strip()
    if not key:
        return CHARACTERS
    return tuple(c for c in CHARACTERS if key in c.name)


def find_echo_set(name: str) -> EchoSetInfo | None:
    key = (name or "").strip()
    if not key:
        return None
    for item in ECHO_SETS:
        if item.name == key:
            return item
    return None


def character_choice_error(name: str, taken=(), max_length: int | None = None) -> str:
    """校验"用户选/填的角色" —— 配置页两类配置共用这一份。

    返回**给用户看的错误说明**；空串表示通过。

    两条规则（用户 2026-09-26）：
    1. 名字必须**精确命中**数据集里的一个角色（不能自由输入）；
    2. **一个角色只能有一条**配置（``taken`` = 已被别的配置占用的角色）。

    为什么放在 core 而不是各弹框里各写一份：
    这是纯逻辑，**能单测**（项目的 Qt 弹框测试只做假对象，不弹真框）；
    两边界面（角色声骸强化 / 角色声骸筛选）用同一份，消息也不会写岔。

    规则 1 的直接动机：列表行的头像是拿名字去 :func:`find_character` 查的，
    名字一旦是自由文本（用户实测输入"绯雪声骸强化配置"）→ 查不到 → **头像消失**。
    """
    text = str(name or "").strip()
    if not text:
        return "请先选一个角色"
    if max_length is not None and len(text) > max_length:
        return f"名字太长了（最多 {max_length} 个字）"
    if find_character(text) is None:
        return f"「{text}」不是一个角色 —— 请从列表里选一个（可以打拼音筛）"
    if text in {str(x) for x in taken}:
        return f"「{text}」已经有一条配置了 —— 一个角色只能有一条"
    return ""
