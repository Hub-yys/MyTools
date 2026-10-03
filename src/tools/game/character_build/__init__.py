# -*- coding: utf-8 -*-
"""「查询角色练度」工具。

手机号 + 短信验证码 → APP 端登录 → 拉取账号里的角色与声骸数据。

    tool.py        工具页（登录 + 拉数据 + 展示）
    kuro_account   接口客户端在 :mod:`src.core.kuro_account`
                   （库街区账号接口，**和公开的 wiki 接口是两套**）
"""

from .tool import CharacterBuildPanel, CharacterBuildTool

__all__ = ["CharacterBuildPanel", "CharacterBuildTool"]
