"""工具注册表 + 自动发现。

设计目标（照搬 ok-ww 那种"加一个文件就多一个功能"的路子）：
新工具只要躺在 ``src/tools/<包名>/`` 下、继承 BaseTool、被 register 装饰，
界面上就会自动出现，不需要在任何地方手动登记。
"""

from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil
from types import ModuleType

from .categories import ToolCategory
from .tool_base import BaseTool, ToolMeta

logger = logging.getLogger(__name__)


class ToolRegistry:
    """全局单例式的注册表，全部用类方法，省得传实例到处跑。"""

    _classes: dict[str, type[BaseTool]] = {}

    # ------------------------------------------------------------------ 注册
    @classmethod
    def register(
        cls,
        *,
        category: ToolCategory,
        name: str | None = None,
        description: str | None = None,
        icon_name: str | None = None,
        coming_soon: bool | None = None,
    ):
        """类装饰器：把工具类登记进来。

        装饰器参数只是"换个显示名/换个图标"的快捷方式，
        真正的实现依然写在类里。
        """

        def decorator(tool_cls: type[BaseTool]) -> type[BaseTool]:
            if not (inspect.isclass(tool_cls) and issubclass(tool_cls, BaseTool)):
                raise TypeError(f"{tool_cls} 必须继承 BaseTool")

            tool_cls.category = category
            if name:
                tool_cls.name = name
            if description:
                tool_cls.description = description
            if icon_name:
                tool_cls.icon_name = icon_name
            if coming_soon is not None:
                tool_cls.coming_soon = coming_soon

            if not tool_cls.key:
                raise ValueError(f"{tool_cls.__name__} 缺少 key")

            if tool_cls.key in cls._classes:
                logger.warning("工具 key 重复，后者覆盖前者: %s", tool_cls.key)

            cls._classes[tool_cls.key] = tool_cls
            logger.debug("registered tool %s (%s)", tool_cls.key, tool_cls.__name__)
            return tool_cls

        return decorator

    # ------------------------------------------------------------------ 查询
    @classmethod
    def all_metas(cls) -> list[ToolMeta]:
        metas = [c.meta() for c in cls._classes.values()]
        metas.sort(key=lambda m: (m.category.spec.order, m.name))
        return metas

    @classmethod
    def by_category(cls, category: ToolCategory) -> list[ToolMeta]:
        return [m for m in cls.all_metas() if m.category is category]

    @classmethod
    def get_class(cls, key: str) -> type[BaseTool] | None:
        return cls._classes.get(key)

    @classmethod
    def get_meta(cls, key: str) -> ToolMeta | None:
        tool_cls = cls._classes.get(key)
        return tool_cls.meta() if tool_cls else None

    @classmethod
    def make(cls, key: str) -> BaseTool | None:
        """实例化工具。失败返回 None 而不是抛异常——一个工具坏掉不该带崩整个界面。"""
        tool_cls = cls._classes.get(key)
        if tool_cls is None:
            return None
        try:
            return tool_cls()
        except Exception:  # noqa: BLE001 - 故意兜住，日志里留痕
            logger.exception("工具实例化失败: %s", key)
            return None

    @classmethod
    def clear(cls) -> None:
        cls._classes.clear()

    # ------------------------------------------------------------------ 发现
    @classmethod
    def discover(cls, package: ModuleType) -> list[str]:
        """递归导入 ``package`` 下所有子模块，触发 register 装饰器。

        返回成功导入的模块名，方便 main 里打日志验收。
        """
        imported: list[str] = []
        prefix = package.__name__ + "."

        for module_info in pkgutil.walk_packages(package.__path__, prefix):
            try:
                importlib.import_module(module_info.name)
                imported.append(module_info.name)
            except Exception:  # noqa: BLE001
                logger.exception("工具模块导入失败: %s", module_info.name)

        if not imported:
            # ⚠ 打包成 exe 后最容易踩的坑：代码进了压缩归档，**文件系统上没有 .py**，
            #   ``walk_packages`` 会一个模块都扫不到 —— 界面上表现为「工具（暂无）」、
            #   "已收录 0 个工具"，而且不报错。这条 warning 就是那个报警器。
            #   修法见 packaging/mytools.spec：把工具目录的源码当数据放一份到解包目录。
            logger.warning(
                "在 %s 下一个工具模块都没发现（__path__=%s）—— "
                "打包版请确认工具目录被当成数据放进了 _internal/",
                package.__name__, list(package.__path__),
            )
        return imported


# 便利别名：@registry.register(...)
registry = ToolRegistry
