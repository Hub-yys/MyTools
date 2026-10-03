# -*- coding: utf-8 -*-
"""「查询角色练度」工具。

登录库街区 → 拉取账号里的角色与声骸 → 比对哪些声骸属性需要重刷。

    tool.py        工具页（登录 + 拉数据 + 展示）
    kuro_account   接口客户端在 :mod:`src.core.kuro_account`
                    （库街区「数据终端」，**和公开的 wiki 接口是两套**）
"""

from .tool import CharacterBuildPanel, CharacterBuildTool

__all__ = ["CharacterBuildPanel", "CharacterBuildTool"]
