"""主窗口：左侧导航 + 右侧内容区。

侧栏结构：

    主页
    工具            ← 可展开的分组项（本身不切页面）
        ├ 声骸自动强化   ← 每个工具一项，点它切到对应面板
        └ ...

也就是"工具"这一项就是需求里说的**下拉列表**，展开后列出的全是工具名。

另外侧栏还做了三件事：藏掉左上角的菜单(☰)按钮、关掉折叠、在右边缘加一条
可拖拽的分隔条（框架自带的导航栏不支持拖拽调宽，那条是自己加的）。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QVBoxLayout, QWidget
from qfluentwidgets import FluentWindow, NavigationItemPosition, setThemeColor

from ..app_config import (
    APP_NAME,
    MIN_NAV_WIDTH,
    NAV_EXPAND_WIDTH,
    WINDOW_DEFAULT_HEIGHT,
    WINDOW_DEFAULT_WIDTH,
    WINDOW_MIN_HEIGHT,
    WINDOW_MIN_WIDTH,
)
from ..core.registry import ToolRegistry, logger
from ..core.tool_base import ToolMeta
from ..core.ui_state import UiState
from .compat import resolve_icon
from .config_interface import ConfigInterface
from .home_interface import HomeInterface
from .library_interface import WuwaLibraryInterface
from .nav_reorder import ORDER_KEY, NavReorderHelper
from .tasks_interface import TasksInterface
from .widgets import ComingSoonWidget, tool_icon_of

#: 侧栏里那个"工具"分组项的 routeKey
TOOL_GROUP_KEY = "tool_group"

#: 各导航项的 routeKey（就是界面的 objectName）
HOME_KEY = "HomeInterface"
CONFIG_KEY = "ConfigInterface"
TASKS_KEY = "TasksInterface"

#: 侧栏「资源库」分组项的 routeKey
LIBRARY_GROUP_KEY = "library_group"


class ToolInterfaceHost(QWidget):
    """工具界面的延迟宿主：第一次真正显示时才创建面板。

    这样十个工具也不会拖慢启动，而且单个工具构造失败也只影响它自己那一个页面。
    """

    def __init__(self, meta: ToolMeta, parent=None):
        super().__init__(parent)
        self.meta = meta
        # objectName 会被 FluentWindow 当成 routeKey，必须非空且唯一
        self.setObjectName(f"tool_{meta.key}")
        self._panel: QWidget | None = None

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)

    def showEvent(self, event) -> None:  # noqa: N802 - Qt 回调
        super().showEvent(event)
        self.ensure_panel()

    def ensure_panel(self) -> QWidget:
        """确保真实面板已创建，返回它。"""
        if self._panel is not None:
            return self._panel

        tool = ToolRegistry.make(self.meta.key)
        panel: QWidget | None = None
        if tool is not None:
            try:
                panel = tool.create_widget(self)
            except Exception:  # noqa: BLE001 - 单个工具炸了不能拖垮主程序
                logger.exception("工具界面创建失败: %s", self.meta.key)

        if panel is None:
            panel = ComingSoonWidget(self.meta, self)

        self._layout.addWidget(panel)
        self._panel = panel
        return panel


class NavResizer(QWidget):
    """导航栏右边缘的分隔条，按住左右拖动即可调整侧栏宽度。"""

    def __init__(self, nav, parent=None):
        super().__init__(parent)
        self._nav = nav
        self._start_global_x = 0
        self._start_width = NAV_EXPAND_WIDTH
        self.setFixedWidth(5)
        self.setCursor(Qt.CursorShape.SizeHorCursor)
        self.setToolTip("拖动可调整侧栏宽度")

    def _apply(self, width: int) -> None:
        width = max(MIN_NAV_WIDTH, width)
        self._nav.setExpandWidth(width)
        self._nav.setFixedWidth(width)

    def mousePressEvent(self, event):  # noqa: N802 - Qt 回调
        self._start_global_x = event.globalPosition().toPoint().x()
        self._start_width = max(self._nav.width(), MIN_NAV_WIDTH)
        event.accept()

    def mouseMoveEvent(self, event):  # noqa: N802 - Qt 回调
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        delta = event.globalPosition().toPoint().x() - self._start_global_x
        self._apply(self._start_width + delta)
        event.accept()


class MainWindow(FluentWindow):
    def __init__(self, parent: QWidget | None = None, ui_state: UiState | None = None):
        super().__init__(parent)
        self.setWindowTitle(APP_NAME)
        self.resize(WINDOW_DEFAULT_WIDTH, WINDOW_DEFAULT_HEIGHT)
        self.setMinimumSize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)

        #: 界面状态（侧栏顺序之类）。可以注入，测试就不必碰真实的 data/ui_state.json
        self.ui_state = ui_state if ui_state is not None else UiState()
        self._tool_hosts: dict[str, ToolInterfaceHost] = {}

        self.home_interface = HomeInterface(self)
        self.addSubInterface(self.home_interface, self.home_interface.icon(), "主页")

        self.config_interface = ConfigInterface(self)
        self.addSubInterface(self.config_interface, self.config_interface.icon(), "配置")

        self.tasks_interface = TasksInterface(self)
        self.addSubInterface(
            self.tasks_interface, resolve_icon("TASK"), "任务"
        )

        self._build_tool_group()
        self._build_library_group()

        # 主页卡片 -> 跳到对应工具
        self.home_interface.requestOpenTool.connect(self.open_tool)

        self._setup_nav_reorder()

        setThemeColor("#006FD6")
        self._install_nav_resizer()
        self._tweak_navigation()
        self.center_on_screen()

    # ------------------------------------------------------------------ 侧栏排序
    def _setup_nav_reorder(self) -> None:
        """「配置」和「工具」可以按住上下拖动换位置，「主页」固定在最上面。

        顺序存到本地，下次启动照旧。
        """
        self.nav_reorder = NavReorderHelper(
            self.navigationInterface,
            movable_keys=[CONFIG_KEY, TASKS_KEY, TOOL_GROUP_KEY, LIBRARY_GROUP_KEY],
            fixed_keys=[HOME_KEY],
            on_order_changed=lambda keys: self.ui_state.set_list(ORDER_KEY, keys),
            parent=self,
        )
        saved = self.ui_state.get_list(ORDER_KEY)
        if saved and self.nav_reorder.apply_order(saved):
            # 顺序动过之后指示条还停在旧位置上，让它对齐到当前项
            self.navigationInterface.setCurrentItem(self.home_interface.objectName())

    def nav_order(self) -> list[str]:
        """当前侧栏顶级项的顺序（测试用）。"""
        return self.nav_reorder.current_order()

    # ------------------------------------------------------------------ 侧栏工具分组
    def _build_tool_group(self) -> None:
        """把「工具」做成可展开的分组，子项就是所有工具名。"""
        metas = ToolRegistry.all_metas()

        if not metas:
            # 一个工具都没有时，直接加一个不可点的提示项，免得留个空分组
            self.navigationInterface.addItem(
                routeKey=TOOL_GROUP_KEY,
                icon=resolve_icon("TOOLS"),
                text="工具（暂无）",
                selectable=False,
                position=NavigationItemPosition.TOP,
                tooltip="还没有可用的工具，去 src/tools/ 下加一个",
            )
            return

        # 分组项本身不切页面，点它是展开/收起子项
        self.navigationInterface.addItem(
            routeKey=TOOL_GROUP_KEY,
            icon=resolve_icon("TOOLS"),
            text="工具",
            selectable=False,
            position=NavigationItemPosition.TOP,
            tooltip="展开查看所有工具",
        )

        for meta in metas:
            host = ToolInterfaceHost(meta, self)
            icon = tool_icon_of(meta)
            self.addSubInterface(host, icon, meta.name, parent=TOOL_GROUP_KEY)
            self._tool_hosts[meta.key] = host

    # ------------------------------------------------------------------ 侧栏资源库
    def _build_library_group(self) -> None:
        """「资源库」分组：下面挂各个游戏的资源页（目前只有鸣潮）。"""
        self.navigationInterface.addItem(
            routeKey=LIBRARY_GROUP_KEY,
            icon=resolve_icon("LIBRARY"),
            text="资源库",
            selectable=False,
            position=NavigationItemPosition.TOP,
            tooltip="展开查看资源库",
        )
        self.wuwa_library = WuwaLibraryInterface(self)
        self.addSubInterface(
            self.wuwa_library,
            self.wuwa_library.icon(),
            "鸣潮资源库",
            parent=LIBRARY_GROUP_KEY,
        )

    # ------------------------------------------------------------------ 跳转
    def open_tool(self, key: str) -> None:
        """打开某个工具：展开侧栏分组 → 切到面板 → 侧栏那一项选中高亮。"""
        host = self._tool_hosts.get(key)
        if host is None:
            return
        self.expand_tool_group()
        self.switchTo(host)
        # routeKey 就是界面的 objectName，setCurrentItem 会把左侧对应项高亮
        self.navigationInterface.setCurrentItem(host.objectName())

    def expand_tool_group(self) -> None:
        """展开侧栏的「工具」分组，让工具名（子项）显示出来。"""
        nav = getattr(self, "navigationInterface", None)
        if nav is None:
            return
        # 各版本拿节点的方法名不一致，挨个试
        for method_name in ("widget", "item", "findItem"):
            getter = getattr(nav, method_name, None)
            if not callable(getter):
                continue
            try:
                node = getter(TOOL_GROUP_KEY)
            except Exception:  # noqa: BLE001
                continue
            if node is not None and hasattr(node, "setExpanded"):
                node.setExpanded(True)
                return

    def tool_panel(self, key: str) -> QWidget | None:
        """取（必要时创建）某个工具的真实面板，方便外部/测试直接用。"""
        host = self._tool_hosts.get(key)
        return host.ensure_panel() if host else None

    # ------------------------------------------------------------------ 侧栏外观
    def showEvent(self, event) -> None:  # noqa: N802 - Qt 回调
        super().showEvent(event)
        # 基类 show 的时候会把导航栏按钮重新显示出来，所以这里再关一次
        self._tweak_navigation()
        # 注意：这里**不**展开工具分组。启动时侧栏保持收起，
        # 只有从主页点卡片跳转时才展开（见 open_tool）。

    def _install_nav_resizer(self) -> None:
        """把分隔条插到导航栏右边（FluentWindow 的主布局是 hBoxLayout）。"""
        self.nav_resizer = NavResizer(self.navigationInterface, self)
        layout = getattr(self, "hBoxLayout", None)
        if layout is None:
            return
        try:
            index = layout.indexOf(self.navigationInterface)
            if index >= 0:
                layout.insertWidget(index + 1, self.nav_resizer)
        except Exception:  # noqa: BLE001 - 布局结构变了也不影响主流程
            pass

    def _tweak_navigation(self) -> None:
        """侧栏：藏掉左上角的菜单(☰)按钮、关掉折叠、保持展开宽度。"""
        nav = getattr(self, "navigationInterface", None)
        if nav is None:
            return

        for name, arg in (("setCollapsible", False), ("setExpandWidth", NAV_EXPAND_WIDTH)):
            method = getattr(nav, name, None)
            if callable(method):
                try:
                    method(arg)
                except Exception:  # noqa: BLE001 - 各版本 API 有差异，失败不影响主流程
                    pass

        expand = getattr(nav, "expand", None)
        if callable(expand):
            try:
                expand(useAni=False)
            except TypeError:
                expand()

        # 藏按钮必须放在 expand 之后，否则又被它显示出来
        button = getattr(getattr(nav, "panel", None), "menuButton", None)
        if button is not None:
            button.hide()

    def center_on_screen(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        geometry = screen.availableGeometry()
        self.move(
            (geometry.width() - self.width()) // 2,
            (geometry.height() - self.height()) // 2,
        )
