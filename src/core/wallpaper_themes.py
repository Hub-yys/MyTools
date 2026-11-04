# -*- coding: utf-8 -*-
"""★ 精选主题：壁纸 + **固定**主题色。

## 用户 2026-11-04

    > 坎特蕾拉的壁纸替换这个目录下的视频
    > D:\\Steam\\steamapps\\workshop\\content\\431960\\3494867116，
    > 新增心月狐红色主题，资源使用这个
    > "D:\\Steam\\steamapps\\workshop\\content\\431960\\3816877839"，
    > 新增爱弥斯粉红色主题，资源使用这个
    > "D:\\Steam\\steamapps\\workshop\\content\\431960\\3719212255"，
    > 新增千咲黑红色主题，资源使用这个
    > "D:\\Steam\\steamapps\\workshop\\content\\431960\\3609013499"

2026-11-04 第二批：

    > 1.新增长离红色主题，资源在
    >    "D:\\Steam\\steamapps\\workshop\\content\\431960\\3322544922"，
    >    新增尤诺蓝色主题，资源在
    >    "D:\\Steam\\steamapps\\workshop\\content\\431960\\3570276722"
    > 2.按图所做，另外，默认使用守岸人主题

## 为什么要有这张表（而不是继续自动抽色）

自动抽色（:func:`src.core.color_extract.extract_primary`）是从视频首帧
投票算主色，**算出来是什么就是什么**。用户这轮点名的颜色是：

    心月狐 → 红    爱弥斯 → 粉红    千咲 → 黑红

但实测抽色结果（``-ss 2`` 抓帧）是：

.. code:: text

    3719212255 爱弥斯   #DE6B86   ← 粉，碰巧对
    3816877839 心月狐   （scene 型，无视频，抽不了）
    3609013499 千咲     #8569DB   ← 紫，不是黑红

即**抽色满足不了用户的诉求**。所以这里给每个精选主题写死主色 ——
选中这个壁纸时，主题色用表里的值，**不再抽**。

没进这张表的壁纸（用户自己放的视频、白名单外的）继续走自动抽色，
行为不变。

## 主题和皮肤的关系

``skins.SKINS`` 是「界面配色方案」（现在只剩一款「液态玻璃」）。
本表是「**壁纸 + 它的主题色**」—— 不新增皮肤，只是给壁纸配一个
写死的主色。选中即生效，写入 ``skins._WALLPAPER_PRIMARY``。

## 字段

============================  ================================================
``wallpaper_id``              创意工坊目录名（Steam id）
``name``                      主题显示名（也用作卡片角标）
``primary``                   主色 ``#RRGGBB``（写死，不抽色）
``tint``                      玻璃层色调浓度 0~0.62（见 ``skins`` 的说明）
``desc``                      界面上一句话描述
============================  ================================================
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

#: 精选主题表。
#:
#: ⚠ ``primary`` 是**写死**的，改它就能改这套主题的观感。
#: ``tint`` 越大玻璃层越暗（壁纸越不明显），参考：
#: 守岸人 0.42（壁纸偏亮）、千咲 0.40（壁纸很暗，不需要压太多）。
THEMES: tuple[dict, ...] = (
    {
        "wallpaper_id": "3340494990",
        "name": "守岸人",
        "primary": "#2555DB",
        "tint": 0.42,
        "desc": "蓝色（守岸人钢琴版）",
    },
    {
        "wallpaper_id": "3494867116",
        "name": "坎特蕾拉",
        "primary": "#6747DB",
        "tint": 0.43,
        "desc": "紫蓝（坎特蕾拉）",
    },
    {
        "wallpaper_id": "3816877839",
        "name": "心月狐",
        "primary": "#D8323C",
        "tint": 0.40,
        "desc": "红色（心月狐 · 从 scene.pkg 取视频）",
    },
    {
        "wallpaper_id": "3719212255",
        "name": "爱弥斯",
        "primary": "#F07AA0",
        "tint": 0.45,
        "desc": "粉红（爱弥斯）",
    },
    {
        "wallpaper_id": "3609013499",
        "name": "千咲",
        "primary": "#B02A38",
        "tint": 0.40,
        "desc": "黑红（千咲 · 回眸）",
    },
    {
        "wallpaper_id": "3322544922",
        "name": "长离",
        "primary": "#D8503C",
        "tint": 0.42,
        "desc": "红色（长离 · 桔梗对弈）",
    },
    {
        "wallpaper_id": "3570276722",
        "name": "尤诺",
        "primary": "#2E7FE8",
        "tint": 0.44,
        "desc": "蓝色（尤诺 · 月下）",
    },
)


def all_themes() -> list[dict]:
    """全部精选主题（**拷贝**，调用方改了不影响表）。"""
    return [dict(t) for t in THEMES]


#: ★ 默认壁纸（用户 2026-11-04：「默认使用守岸人主题」）。
#:
#: 用在两处：
#:
#: * :meth:`web_bridge.WebBridge._pick_current` —— 没选过壁纸时用它，
#:   而不是「列表第一个」（那个是 ``sort(title)`` 的巧合，加一张壁纸就变了）
#: * :meth:`web_bridge.WebBridge._apply_wallpaper_accent` —— 没存过选择时
#:   也要按它取主色，否则界面播着守岸人、按钮却是紫的
DEFAULT_WALLPAPER_ID: str = "3340494990"


def default_theme() -> dict | None:
    """默认主题（守岸人）。表被改坏了返回 ``None``。"""
    return theme_for_wallpaper(DEFAULT_WALLPAPER_ID)


def theme_for_wallpaper(wp_id: str) -> dict | None:
    """这张壁纸是不是精选主题？是就返回它的配色，不是返回 ``None``。

    :param wp_id: 创意工坊目录名（:func:`wallpaper_engine.read_project` 的 ``id``）
    """
    key = str(wp_id or "").strip()
    if not key:
        return None
    for t in THEMES:
        if t["wallpaper_id"] == key:
            return dict(t)
    return None


def wallpaper_ids() -> tuple[str, ...]:
    """所有被主题引用的壁纸 id（白名单要用）。"""
    return tuple(t["wallpaper_id"] for t in THEMES)


__all__ = [
    "THEMES",
    "all_themes",
    "theme_for_wallpaper",
    "wallpaper_ids",
]
