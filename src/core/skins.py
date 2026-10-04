# -*- coding: utf-8 -*-
"""皮肤系统 —— 给整个工具箱换**主题色 + 亮暗模式**。

## 为什么是"皮肤"，不只是"暗色模式"

qfluentwidgets 自带 ``setTheme(DARK)`` —— 但那是**全局亮暗切换**，
配色方案**没法换**。用户要的是"几款好看的皮肤" ——
每个皮肤 = **一套完整配色**（主色 + 背景 + 卡片 + 文字 + 强调色）。

## 用 ``qconfig`` 落盘

``qfluentwidgets`` 的 ``qconfig`` 已经管了主题持久化
（``~/.config/<app>/config.json``），我们**往它自己的键里加**——
别再造一份。

## 皮肤一览

每个皮肤四个字段::

    {id, name, mode, primary}

    id       皮肤 id（存盘用）
    name     显示名（中文）
    mode     "light" / "dark"
    primary  主色（qfluentwidgets 的 setThemeColor 那个）
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

#: 皮肤注册表（顺序 = 界面上显示的顺序）
SKINS: tuple[dict, ...] = (
    {
        "id": "solaris",
        "name": "暖阳（默认）",
        "mode": "light",
        "primary": "#006FD6",
    },
    {
        "id": "frost",
        "name": "霜色",
        "mode": "light",
        "primary": "#2E7D6E",
    },
    {
        "id": "dusk",
        "name": "暮色",
        "mode": "light",
        "primary": "#B4572E",
    },
    {
        "id": "midnight",
        "name": "子夜",
        "mode": "dark",
        "primary": "#7B61FF",
    },
    {
        "id": "jade",
        "name": "清竹",
        "mode": "light",
        "primary": "#3F8F4F",
    },
    {
        "id": "ember",
        "name": "余烬",
        "mode": "dark",
        "primary": "#D64545",
    },
)

#: 默认皮肤 id（启动时回落到它）
DEFAULT_SKIN = "solaris"

#: 持久化用的 ``ConfigItem`` —— qconfig 只认它（**不是**裸字符串）
#:
#: ⚠ 我第一版写了 ``qconfig.get("skin", DEFAULT_SKIN)`` ——
#: ``qconfig.get()`` 只接**一个 ``ConfigItem``**，
#: 传字符串会炸 ``TypeError``（启动时就崩了）。
_SKIN_ITEM = None


def _skin_item():
    """皮肤配置的 ``ConfigItem``（懒建）。"""
    global _SKIN_ITEM
    if _SKIN_ITEM is None:
        from qfluentwidgets import OptionsConfigItem, OptionsValidator

        _SKIN_ITEM = OptionsConfigItem(
            "Skins", "CurrentSkin",
            DEFAULT_SKIN,
            OptionsValidator([s["id"] for s in SKINS]),
        )
    return _SKIN_ITEM


def all_skins() -> tuple[dict, ...]:
    """全部皮肤（顺序固定）。"""
    return SKINS


def skin_by_id(skin_id: str) -> dict | None:
    """按 id 找皮肤；找不到返回 ``None``。"""
    for s in SKINS:
        if s["id"] == skin_id:
            return s
    return None


def current_skin() -> dict:
    """当前皮肤（没存过就用默认）。"""
    from qfluentwidgets import qconfig

    skin_id = qconfig.get(_skin_item())
    return skin_by_id(str(skin_id)) or skin_by_id(DEFAULT_SKIN)


def apply_skin(skin_id: str, *, save: bool = True) -> bool:
    """应用一个皮肤（立刻生效）。返回是否成功。"""
    skin = skin_by_id(skin_id)
    if skin is None:
        logger.warning("不认识的皮肤 id：%s", skin_id)
        return False

    from qfluentwidgets import qconfig, setTheme, setThemeColor, Theme

    #: 先切亮暗模式，再设主色（顺序无所谓，但别漏了暗色）
    setTheme(Theme.DARK if skin["mode"] == "dark" else Theme.LIGHT)
    setThemeColor(skin["primary"])

    if save:
        qconfig.set(_skin_item(), skin["id"])
    return True


def apply_current_skin() -> dict:
    """启动时：把存的皮肤应用上。"""
    skin = current_skin()
    apply_skin(skin["id"], save=False)
    return skin
