"""工具包：具体工具都放这里。

约定：``src/tools/<包名>/`` 下的每个模块只要继承了 BaseTool 并用
``@registry.register`` 装饰，就会被 :func:`discover_tools` 自动发现。
加工具不需要动任何界面代码。
"""

from __future__ import annotations

import sys

from ..core.registry import ToolRegistry


def discover_tools() -> list[str]:
    """扫描本包下所有模块并注册其中的工具。返回导入成功的模块名。"""
    return ToolRegistry.discover(sys.modules[__name__])


__all__ = ["discover_tools"]
