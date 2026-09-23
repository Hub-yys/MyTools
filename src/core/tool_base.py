"""工具基类。

新增工具只需要：继承 :class:`BaseTool`，用 ``@registry.register`` 装饰，
实现 :meth:`create_widget`。除此之外框架不要求任何东西。

    @registry.register(category=ToolCategory.GAME, name="存档备份")
    class SaveBackupTool(BaseTool):
        key = "save_backup"
        description = "定期备份游戏存档到指定目录"

        def create_widget(self, parent=None):
            return MyWidget(self, parent)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .categories import ToolCategory


@dataclass(frozen=True)
class ToolMeta:
    """注册时写死的静态信息，不含运行时状态。"""

    key: str
    name: str
    category: ToolCategory
    description: str = ""
    icon_name: str = "APPLICATION"
    #: 自定义图标文件（png/ico 路径）。填了就优先用它，否则用 icon_name 对应的 Fluent 图标
    icon_path: str = ""
    author: str = ""
    version: str = "0.1.0"
    tags: tuple[str, ...] = field(default_factory=tuple)
    coming_soon: bool = True
    #: 任务流程里能不能自动运行（见 :attr:`BaseTool.supports_task_run`）
    supports_task_run: bool = False


class BaseTool:
    """所有工具的抽象基类。

    子类必须提供 ``key`` / ``name`` / ``category``；剩下的都有默认值。
    """

    key: str = ""
    name: str = ""
    category: ToolCategory = ToolCategory.GAME
    description: str = ""
    icon_name: str = "APPLICATION"
    #: 自定义图标文件路径（png/ico）。填了就优先用它，否则用 icon_name。
    #: ⚠ meta() 里引用了这个属性 —— 不给默认值的话，凡是不写它的工具类一注册就炸。
    icon_path: str = ""
    author: str = ""
    version: str = "0.1.0"
    tags: tuple[str, ...] = ()
    #: 为 True 时主页显示"即将到来"角标，点进去是占位页
    coming_soon: bool = True
    #: 任务流程里能不能自动运行这个工具（配合 :meth:`create_task_runner`）。
    #: 声明式标记 —— 编排界面靠它列出"可用组件"，不去实例化探测（实例化有副作用）。
    supports_task_run: bool = False

    # ---------------------------------------------------------------- 元信息
    @classmethod
    def meta(cls) -> ToolMeta:
        if not cls.key:
            raise ValueError(f"{cls.__name__} 没有设置 key")
        return ToolMeta(
            key=cls.key,
            name=cls.name or cls.__name__,
            category=cls.category,
            description=cls.description,
            icon_name=cls.icon_name,
            icon_path=cls.icon_path,
            author=cls.author,
            version=cls.version,
            tags=tuple(cls.tags),
            coming_soon=cls.coming_soon,
            supports_task_run=cls.supports_task_run,
        )

    # ---------------------------------------------------------------- 生命周期
    def create_widget(self, parent=None):
        """返回本工具的主面板 QWidget。

        默认实现给出占位面板；真正实现功能时重写它。
        """
        from ..gui.widgets import ComingSoonWidget

        return ComingSoonWidget(self.meta(), parent)

    # ---------------------------------------------------------------- 任务系统
    def create_task_runner(self, options: dict, log, should_stop):
        """任务流程运行钩子（可选实现）。

        「任务流程」功能按顺序运行各工具时会调这里。返回一个带
        ``run()``（结束时返回结果对象，带 ``summary()`` 更好）的对象；
        返回 ``None`` 表示本工具不支持被任务自动运行（流程里会记一条跳过）。

        ``options`` 是编排时挂在这个工具步骤下的配置等信息：
        ``{"configs": [配置名, ...]}``。工具用不用是它自己的事。
        ``log(str)`` 用来吐进度，``should_stop()`` 返回 True 时要尽快退出。
        """
        return None

    def create_task_prep(self, options: dict, log, should_stop):
        """任务流程**开始步**的准备钩子（可选实现）。

        流程跑到「开始」时，会按顺序问每个工具步骤"要不要先把环境摆好"，
        第一个返回了对象的**就执行它**（准备是"把游戏摆好"，摆一次就够），
        然后才真正开始跑各步骤。

        返回一个有 ``run()`` 的对象；``run()`` 返回 ``None`` 表示准备正常完成，
        返回别的对象则取它的 ``summary()`` 记一条日志（比如"有步骤待校准"）。
        不实现（返回 None）= 本工具不需要准备。
        """
        return None

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"<{type(self).__name__} key={self.key!r} category={self.category.key!r}>"
