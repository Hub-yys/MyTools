# -*- coding: utf-8 -*-
"""「扫荡残像聚落」的**目标清单**（残像聚落 + 梦魇残像）。

## 这个模块只管一件事：**有哪些可以刷的目标、按什么顺序**

清单来自用户数据目录下的一份 **可编辑 JSON**::

    <用户数据>/game_data/wuwa_sweep_targets.json

首次运行由 :func:`src.core.paths.ensure_user_data` 从 ``src/core/data/`` 播种一份。
用户改这个文件 → 界面上的卡片跟着变，**不用改代码**。

## ★ 为什么做成数据文件而不是写死在代码里

用户 2026-10-13 的原话是「展示**当前版本**所有的残像聚落和梦魇残像」。
"当前版本"是个**会变的东西**：每个版本都可能新增聚落 / 梦魇，
而写死在代码里就意味着**每出一版都要改代码重新打包**。

做成数据文件之后，版本更新时只需要改 JSON（或者跟着「资源库更新」走）。
这是本项目对"会随版本变的数据"的一贯处理（见 ``wuwa_set_versions.json``）。

## ⚠⚠ 名单的可靠性：梦魇那一半是权威的，聚落那一半需要你核对

============================  ==========================================
部分                           来源与可信度
============================  ==========================================
**梦魇残像**（25 条）          库街区官方 wiki 的「梦魇声骸」标签，
                              名称**逐条对得上**，可以直接用
**残像聚落**                   中文名单**没有可靠来源**。日站只给了
                              区域（落渊南丘 / 盲落 / 逆脑 / 滞澜 /
                              梦枢天罗）和每日数量（普通 24 / 困难 48，
                              另有 36 / 41 两种，见 ok-ww 的判据）
============================  ==========================================

所以聚落那部分**故意留着让你改**：名称对不上时，直接编辑 JSON 里的
``name`` / ``aliases``，界面和任务都会跟着变（匹配是**子串 + 别名**，
不要求一字不差）。

> ⚠ 我**没有**为了让名单看起来完整而编造聚落名。拿不准的条目在 JSON 里
> 用 ``"verified": false`` 标出来，界面上会显示一个「待核对」角标 ——
> 这比给一串看着像模像样的假名字强得多。

## 顺序就是刷取顺序

``order`` 小的先刷。这个顺序**和游戏指南里的行序一致**才最稳 ——
任务侧先按名称匹配，匹配不上才退回按行号点（见 :mod:`.plan`）。

**纯逻辑**：只依赖 :mod:`src.core.paths`，不碰 Qt、不碰 ok-ww，可以单测
（见 ``tests/test_nest_sweep_catalog.py``）。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from .. import paths

logger = logging.getLogger(__name__)

#: 数据文件名（放在 ``game_data`` 目录下，和别的图鉴 JSON 同一层）
CATALOG_FILE = "wuwa_sweep_targets.json"

#: 两类目标 —— 对应游戏索拉指南里的两个页签
KIND_NEST = "nest"              #: 残像聚落
KIND_NIGHTMARE = "nightmare"    #: 梦魇残像（梦魇拔除）

#: key → 界面上显示的分类名
KIND_NAMES: dict[str, str] = {
    KIND_NEST: "残像聚落",
    KIND_NIGHTMARE: "梦魇残像",
}

#: 页签的显示顺序（也是默认的刷取分组顺序）
KIND_ORDER: tuple[str, ...] = (KIND_NEST, KIND_NIGHTMARE)


@dataclass(frozen=True)
class SweepTarget:
    """一个可刷的目标（一处残像聚落，或一个梦魇残像）。"""

    #: 稳定标识。**存盘只存它** —— 名称改了也不会把用户的勾选弄丢。
    key: str
    #: 游戏内的显示名（界面上给人看的）
    name: str
    #: :data:`KIND_NEST` 或 :data:`KIND_NIGHTMARE`
    kind: str = KIND_NEST
    #: 刷取顺序，小的先刷
    order: int = 0
    #: 所在区域（指南里的分组 / 帮助辨认用）
    region: str = ""
    #: 每日可刷数量 —— 就是指南行里 ``0/24`` 的那个分母。
    #: 任务侧拿它做**佐证**（名称匹配不上时的兜底判据之一）。
    count: int = 0
    #: 出现的版本（"3.7" 这种）
    version: str = ""
    #: 别名 / 简称 —— 匹配时和 ``name`` 一起试（OCR 容易漏字，别名很管用）
    aliases: tuple[str, ...] = ()
    #: 名字是不是**核对过**的。False 时界面显示「待核对」角标。
    verified: bool = True

    @property
    def kind_name(self) -> str:
        """:data:`KIND_NAMES` 里对应的中文分类名。"""
        return KIND_NAMES.get(self.kind, self.kind)

    def match_names(self) -> tuple[str, ...]:
        """匹配时依次尝试的**全部**名字（本名 + 别名，去掉重复和空串）。

        ⚠ 长的排前面：``梦魇·刺玫菇（稚形）`` 和 ``梦魇·刺玫菇`` 同时存在，
        先拿长的去比才不会被短名抢先命中（那是另一个目标）。
        """
        seen: list[str] = []
        for candidate in (self.name, *self.aliases):
            text = str(candidate or "").strip()
            if text and text not in seen:
                seen.append(text)
        seen.sort(key=len, reverse=True)
        return tuple(seen)


# --------------------------------------------------------------------- 解析

def _to_int(value, default: int = 0) -> int:
    """能转 int 就转，转不了给默认值 —— 数据文件是手改的，要经得起手滑。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_aliases(value) -> tuple[str, ...]:
    """别名可以是数组，也可以是逗号 / 顿号分隔的字符串（手写时两种都自然）。"""
    if isinstance(value, str):
        parts = value.replace("，", ",").replace("、", ",").split(",")
        return tuple(p.strip() for p in parts if p.strip())
    if isinstance(value, (list, tuple)):
        return tuple(str(p).strip() for p in value if str(p).strip())
    return ()


def parse_target(raw: dict, *, index: int = 0) -> SweepTarget | None:
    """把数据文件里的一条记录变成 :class:`SweepTarget`。

    坏记录返回 ``None``（**不抛异常**）—— 数据文件是给人改的，
    一条写坏了不该让整个工具页变空。

    :param index: 这条在文件里的位置，用来在没写 ``order`` 时兜底排序。
    """
    if not isinstance(raw, dict):
        return None

    name = str(raw.get("name", "") or "").strip()
    if not name:
        return None

    kind = str(raw.get("kind", "") or "").strip().lower()
    if kind not in KIND_NAMES:
        # 没写 / 写错分类时按「残像聚落」处理 —— 而不是把这条丢掉。
        # 用户新加一条时最容易忘的就是 kind，丢掉会让人以为"改了没生效"。
        kind = KIND_NEST

    key = str(raw.get("key", "") or "").strip()
    if not key:
        # 没给 key 就用「分类:名称」现造一个。同一个名字在同一分类下稳定，
        # 所以存盘的勾选不会因为重启而丢。
        key = f"{kind}:{name}"

    return SweepTarget(
        key=key,
        name=name,
        kind=kind,
        order=_to_int(raw.get("order"), index),
        region=str(raw.get("region", "") or "").strip(),
        count=max(0, _to_int(raw.get("count"), 0)),
        version=str(raw.get("version", "") or "").strip(),
        aliases=_parse_aliases(raw.get("aliases")),
        # ⚠ 只有**显式**写了 false 才算未核对。缺字段的老数据按"已核对"处理，
        #   免得整页挂满角标（用户加条目时不会想着写这个字段）。
        verified=raw.get("verified", True) is not False,
    )


def parse_catalog(raw) -> tuple[SweepTarget, ...]:
    """把整个数据文件的 dict 解析成有序目标表。

    排序规则：**先分类（聚落在前）、再 order、最后 name**。

    ⚠ 一定要有**兜底排序键**（``name``）：order 相同时（用户新加条目很容易
    都写 0）如果只按 order 排，顺序就取决于 JSON 里的书写顺序 ——
    看起来能用，但没有任何保证。加上 name 之后至少是**确定**的。
    """
    if not isinstance(raw, dict):
        return ()

    items = raw.get("targets")
    if not isinstance(items, list):
        return ()

    parsed: list[SweepTarget] = []
    seen: set[str] = set()
    for index, entry in enumerate(items):
        target = parse_target(entry, index=index)
        if target is None:
            logger.warning("扫荡清单第 %d 条读不出来，已跳过：%r", index, entry)
            continue
        if target.key in seen:
            # ⚠ key 撞车必须挡住：存盘按 key 记勾选，重复 key 会让
            #   "勾了一个，另一个跟着亮" —— 那是个很难查的怪现象。
            logger.warning("扫荡清单里有重复的 key，已跳过后者：%s", target.key)
            continue
        seen.add(target.key)
        parsed.append(target)

    kind_rank = {kind: i for i, kind in enumerate(KIND_ORDER)}
    parsed.sort(key=lambda t: (kind_rank.get(t.kind, len(kind_rank)),
                               t.order, t.name))
    return tuple(parsed)


# --------------------------------------------------------------------- 落点

def catalog_path() -> Path:
    """数据文件的落点（开发态在仓库里，打包后在用户数据目录）。"""
    return paths.game_data_dir() / CATALOG_FILE


def load_catalog(path: Path | None = None) -> tuple[SweepTarget, ...]:
    """读目标清单。

    文件不存在 / 坏掉都返回**空元组** —— 界面上退化成"暂无目标"，
    **绝不抛异常**（一个数据文件不该让工具页打不开）。
    """
    target = path or catalog_path()
    try:
        with target.open(encoding="utf-8") as fh:
            raw = json.load(fh)
    except FileNotFoundError:
        logger.warning("扫荡清单不存在：%s", target)
        return ()
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("扫荡清单读不出来（%s）：%s", target, exc)
        return ()
    return parse_catalog(raw)


def catalog_by_kind(
    targets: tuple[SweepTarget, ...] | None = None,
) -> dict[str, tuple[SweepTarget, ...]]:
    """按分类分组（**保持 :data:`KIND_ORDER` 的顺序**，空的分类不出现）。"""
    items = load_catalog() if targets is None else targets
    grouped: dict[str, list[SweepTarget]] = {}
    for target in items:
        grouped.setdefault(target.kind, []).append(target)
    ordered: dict[str, tuple[SweepTarget, ...]] = {}
    for kind in KIND_ORDER:
        if grouped.get(kind):
            ordered[kind] = tuple(grouped[kind])
    # 清单里出现了 KIND_ORDER 之外的分类（用户自己加的）也要显示出来
    for kind, group in grouped.items():
        if kind not in ordered:
            ordered[kind] = tuple(group)
    return ordered


def find_target(
    key: str, targets: tuple[SweepTarget, ...] | None = None,
) -> SweepTarget | None:
    """按 key 取一个目标；找不到返回 ``None``。"""
    items = load_catalog() if targets is None else targets
    for target in items:
        if target.key == key:
            return target
    return None
