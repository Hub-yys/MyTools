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

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget
from qfluentwidgets import FluentWindow, NavigationItemPosition, setThemeColor

from ..app_config import (
    APP_DISPLAY_NAME,
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
from . import tray as tray_mod
from .compat import app_icon, resolve_icon
from .config_interface import ConfigInterface
from .home_interface import HomeInterface
from .library_interface import WuwaLibraryInterface
from .nav_reorder import ORDER_KEY, NavReorderHelper
from .tasks_interface import TasksInterface
from .skin_page import build_skin_page
from .widgets import ComingSoonWidget, tool_icon_of

#: 侧栏里那个"工具"分组项的 routeKey
TOOL_GROUP_KEY = "tool_group"

#: 各导航项的 routeKey（就是界面的 objectName）
HOME_KEY = "HomeInterface"
CONFIG_KEY = "ConfigInterface"
TASKS_KEY = "TasksInterface"

#: 侧栏「资源库」的 routeKey。
#: ⚠ 2026-09-30 起它**就是页面本身**（不再是"分组/子项"两层）——
#: 用户要求去掉多余的「鸣潮资源库」那一层（"资源库本身就是了"）。
#: 值必须和 :class:`WuwaLibraryInterface` 的 ``objectName`` 一致，
#: 侧栏高亮和拖拽排序都按它找项。
LIBRARY_KEY = "WuwaLibraryInterface"


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

        # ★ 工具面板是**懒创建**的 —— 皮肤刷 QSS 那会儿它还不存在，
        #   所以这里建好后要补一次透明（否则它在玻璃背景上是一块白）。
        #   见 src/core/skins.py 的 paint_page_widget 说明。
        from src.core import skins as _skins

        _skins.paint_page_widget(self)
        _skins.paint_page_widget(panel)
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
    #: 「任务已启动」用的**跨线程通知**信号。
    #:
    #: ★ 为什么非得转这一手（2026-09-27 卡死的根因）：
    #: ok-ww 宿主喊这一声时，调用链是
    #: ``FlowRunThread.run()``（**工作线程**）→ ``OkwwHost.start_task()``
    #: → ``_notify_task_started()`` → 这个回调。而回调做的事
    #: （``hide()`` / ``processEvents()`` / ``QTimer.singleShot``）**只能在主线程做**。
    #:
    #: 表现是：日志停在 ``[宿主] ▶ 已启动任务`` 之后**再也没有输出** ——
    #: 因为 ``start_task`` 卡在这句通知里没返回，``OkwwTaskRunner.run()`` 的第一条
    #: 日志根本没机会打出来；界面上流程永远「运行中」，停止也没反应。
    #:
    #: ``emit()`` 跨线程是**安全**的：Qt 自动把槽排到接收者所属线程（主线程）执行，
    #: 不阻塞调用方。
    task_started = Signal()

    def __init__(self, parent: QWidget | None = None, ui_state: UiState | None = None):
        super().__init__(parent)
        self.setWindowTitle(APP_DISPLAY_NAME)
        # 任务栏 / 托盘都用这个图标。**不设的话任务栏会显示 python.exe 的图标**
        # （2026-09-25 用户反馈"你来设计个图标"就是这事 —— app.ico 早就有，
        #  只是没人调用它）。
        self.setWindowIcon(app_icon())
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

        #: ★ 皮肤页面 —— 用户："皮肤加在左侧边栏，不是左下角"（2026-10-05）
        #:
        #: ⚠ 第一版是塞在侧栏**底部**的一排小圆点，用户明确说不要那样：
        #: "右边显示所有的皮肤，以卡片的形式展示" → 做成正式导航项。
        self.skin_interface = build_skin_page(self)
        self.addSubInterface(
            self.skin_interface, resolve_icon("SKIN"), "皮肤"
        )

        self._build_tool_group()
        self._build_library_group()

        # 主页卡片 -> 跳到对应工具
        self.home_interface.requestOpenTool.connect(self.open_tool)

        self._setup_nav_reorder()

        #: ★ 应用存下来的皮肤（启动时）—— 见 :mod:`src.core.skins`
        from src.core import skins as _skins

        _skins.apply_current_skin()
        self._install_nav_resizer()
        self._tweak_navigation()
        self.center_on_screen()

        #: 真正退出时置真 —— ``closeEvent`` 靠它区分「用户要关」和「我们已经决定退了」，
        #: 否则点「停止并退出」会再弹一次确认框（死循环）。
        self._force_quit = False
        #: 托盘图标。拿不到系统托盘时为 None，这时「隐藏」退化成最小化。
        self._tray = None
        self._setup_tray()
        # ★ 信号→槽：宿主在任何线程 emit，槽都在**主线程**执行（见 task_started 的说明）
        self.task_started.connect(self.go_background_to_game)
        self._listen_task_started()

        #: ★ 启动后静默检查更新 —— 用户 2026-10-05："增加检查更新功能"
        self._maybe_auto_check_update()

    # ------------------------------------------------------------------ 自动更新
    def _maybe_auto_check_update(self) -> None:
        """启动后**悄悄地**查一下有没有新版本（不打扰用户）。

        ## 为什么要"静默"

        用户要的是"有更新能自动更新"，但**不该**每次启动都弹框问
        "要不要检查更新" —— 那是骚扰。

        → 开关在**配置页的更新卡**上（默认开）。开了就：
        延迟几秒（让界面先画出来）→ 后台查 → **只有真有更新**才提示。

        ⚠ 延迟是必须的：启动阶段一堆单例在建，这时候抢网络 + 建线程
        会让首屏明显变慢。
        """
        try:
            from src.core import ui_state

            if not bool(ui_state.UiState().get("update_auto_check", True)):
                return
        except Exception:                      # noqa: BLE001 - 读不到就当开
            pass

        from PySide6.QtCore import QTimer

        QTimer.singleShot(3000, self._auto_check_update)

    def _auto_check_update(self) -> None:
        """真正去查（延迟后由 QTimer 调起来）。"""
        try:
            from src.core import updater
            from src.gui.update_card import CheckThread
        except Exception:                      # noqa: BLE001
            return

        #: ⚠ 线程要挂个"长命"的父对象 + 留个引用，否则函数一返回就被回收、
        #:    信号也收不到（实测：不挂父对象时回调根本不触发）
        thread = CheckThread(updater._current_version(), self)
        self._update_thread = thread
        thread.done.connect(self._on_auto_checked)
        thread.start()

    def _on_auto_checked(self, info) -> None:
        """静默检查的结果 —— **只有真有更新**才提示。"""
        if not getattr(info, "has_update", False):
            return                           #: 没更新 / 查不到 → 什么都不做
        try:
            from qfluentwidgets import InfoBar, InfoBarPosition

            InfoBar.new(
                title="发现新版本",
                content=f"{info.current} → {info.latest}　"
                        f"到「配置 → 检查更新」里一键更新",
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP_RIGHT,
                duration=8000,
                parent=self,
            ).show()
        except Exception:                      # noqa: BLE001 - 提示失败无所谓
            logger.debug("弹更新提示失败", exc_info=True)

    # ------------------------------------------------------------------ 托盘 / 关闭
    def _setup_tray(self) -> None:
        """建托盘图标（拿不到就留 None，「隐藏」退化成最小化）。"""
        self._tray = tray_mod.make_tray(
            self,
            on_show=self.restore_from_tray,
            on_quit=self.quit_app,
            icon=self.windowIcon(),
        )

    def restore_from_tray(self) -> None:
        """把窗口从托盘 / 最小化状态叫回来。"""
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def go_background_to_game(self) -> None:
        """点运行之后：本程序退到后台，并把游戏切到前台。

        为什么要切游戏：用户点完「运行」就是想回去玩，本程序留在前台会挡着 ——
        而且引擎走的是 PostMessage 后台按键，根本不需要前台。

        ⚠ **先让窗口状态落地，再去抢前台**。``hide()`` / ``showMinimized()``
        只是把请求排进事件队列，真正的窗口状态变更要等下一次事件循环；
        如果紧接着就 ``SetForegroundWindow``，Windows 看到"发起抢前台的进程
        还有可见窗口"，可能把**那个窗口**提上来 ——
        表现就是"刚缩下去、界面又自己弹回来了"（2026-09-25 用户报的现象）。
        所以在这里先 ``processEvents()`` 把 hide 落地，抢前台再延后一拍。
        """
        if self._tray is not None:
            self.hide()
        else:
            self.showMinimized()
        QApplication.processEvents()          # 让 hide/最小化先落到系统
        QTimer.singleShot(120, self._focus_game)

    def _focus_game(self) -> None:
        """把游戏切到前台（延后调用，见 :meth:`go_background_to_game`）。"""
        try:
            from ..tools.game.auto_combat import okww_boot

            okww_boot.bring_game_to_front()
        except Exception:  # noqa: BLE001 - 切不过去不算错误，用户 Alt+Tab 即可
            logger.debug("把游戏切到前台失败", exc_info=True)

    def _listen_task_started(self) -> None:
        """注册「任务已启动」回调 —— 点运行后自动退到后台 + 切游戏。

        ⚠ 回调里**只 emit 信号**，不直接碰界面：这个回调会在 ok-ww 宿主的
        调用线程（通常是 ``FlowRunThread``）上执行，直接调 ``go_background_to_game()``
        等于从工作线程操作 Qt（2026-09-27 卡死的根因，详见 :attr:`task_started`）。
        """
        try:
            from ..tools.game.auto_combat import okww_boot

            okww_boot.get_host().add_task_started_listener(
                lambda _key: self.task_started.emit()
            )
        except Exception:  # noqa: BLE001 - 引擎侧坏了不该挡住主窗口
            logger.debug("注册任务启动回调失败", exc_info=True)

    def quit_app(self) -> None:
        """真的退出（托盘菜单的「退出」也走这里）。"""
        self._force_quit = True
        self.close()

    def close_without_prompt(self) -> None:
        """不弹确认框直接关掉。

        ⚠ ``smoke_gui`` / ``check_*`` 这些脚本收尾时会调 ``window.close()`` ——
        加了关闭确认之后那会**弹出模态框并挂住等输入**。脚本要的是"收尾关掉"，
        不是模拟用户点 X，所以走这个入口。
        """
        self._force_quit = True
        self.close()

    def _game_host(self):
        """已经建好的引擎宿主；从没建过就是 None。

        用 ``current_host`` 而不是 ``get_host`` —— 关窗口只想读一下
        "有没有任务在跑"，不该顺手把宿主造出来。
        """
        try:
            from ..tools.game.auto_combat import okww_boot

            return okww_boot.current_host()
        except Exception:  # noqa: BLE001
            return None

    def _teardown_tray(self) -> None:
        if self._tray is not None:
            try:
                self._tray.hide()
            except Exception:  # noqa: BLE001
                pass

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt 回调
        """关闭确认：隐藏到托盘 / 直接退出 / 取消。

        * **有工具或任务在跑** → 先点明是哪个，再问「停止并退出」
        * **没有** → 问「隐藏到托盘」还是「直接退出」
        * **按 X / Esc** → 什么都不做（:data:`tray_mod.CLOSE_CANCEL`）

        三种出口的判定逻辑全在 :mod:`src.gui.tray` 里（纯函数，有单测覆盖），
        这里只负责执行。
        """
        if self._force_quit:
            self._teardown_tray()
            event.accept()
            return

        host = self._game_host()
        running = tray_mod.running_task_name(host)
        choice = tray_mod.ask_close(self, running,
                                    allow_hide=self._tray is not None)

        if choice == tray_mod.CLOSE_CANCEL:
            event.ignore()
            return

        if choice == tray_mod.CLOSE_HIDE:
            self.go_background_to_game()
            event.ignore()
            return

        # CLOSE_QUIT：有任务在跑就先停掉，别留个半死不活的引擎
        if running and host is not None:
            try:
                host.stop_task()
            except Exception:  # noqa: BLE001 - 停不掉也得让用户退出去
                logger.warning("退出前停止任务失败", exc_info=True)
        self._force_quit = True
        self._teardown_tray()
        event.accept()
        QApplication.quit()

    # ------------------------------------------------------------------ 侧栏排序
    def _setup_nav_reorder(self) -> None:
        """「配置」和「工具」可以按住上下拖动换位置，「主页」固定在最上面。

        顺序存到本地，下次启动照旧。
        """
        self.nav_reorder = NavReorderHelper(
            self.navigationInterface,
            movable_keys=[CONFIG_KEY, TASKS_KEY, TOOL_GROUP_KEY, LIBRARY_KEY],
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
        """侧栏「资源库」—— **直接就是鸣潮资源库页面**。

        ★ 2026-09-30 用户要求去掉多余那一层：

            资源库展开没有「鸣潮资源库」这个标签了，干掉他，
            因为资源库本身就是了

        原来是"资源库"分组 + 一个叫"鸣潮资源库"的子项 —— 目前只有一个
        游戏页，展开一层再点一次纯属多余。

        ⚠ 路由键用 :data:`LIBRARY_KEY`（= ``WuwaLibraryInterface``），
        侧栏高亮、拖拽排序都按它找项。
        以后真加了第二个游戏的资源页，再把这个函数改回 `addItem` +
        `addSubInterface` 的分组写法即可。
        """
        self.wuwa_library = WuwaLibraryInterface(self)
        self.addSubInterface(
            self.wuwa_library,
            resolve_icon("LIBRARY"),
            "资源库",
        )

    # ------------------------------------------------------------------ 跳转
    def open_skin_page(self) -> None:
        """切到皮肤页并把侧栏那一项高亮。

        ⚠ 必须用 ``switchTo``（**不是** ``navigationInterface.setCurrentItem``）——
        实测 ``setCurrentItem`` 只高亮侧栏，**页面不切换**
        （皮肤页停在 100x30 / 不可见）。``open_tool`` 也是这么做的。
        """
        self.switchTo(self.skin_interface)
        self.navigationInterface.setCurrentItem(
            self.skin_interface.objectName())

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
