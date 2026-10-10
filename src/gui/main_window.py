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
from PySide6.QtGui import QColor, QGuiApplication
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
from .notify_page import build_notice_page
from .skin_page import build_skin_page
from .update_card import build_update_page
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

#: ★ 侧栏「检查更新」有新版时的**提示色**（黄）
#:
#: 用户 2026-10-05："有更新时，这里小黄字提示有更新即可"
#:
#: ⚠ 用的是**偏金的黄**（不是纯黄 `#ffff00`）—— 纯黄在浅色背景上
#: 几乎看不清；这个色在浅色和暗色皮肤下都够亮。
UPDATE_BADGE_COLOR = "#E8A33D"

#: 侧栏「消息」那一项的**基础文字**（未读时显示成 ``消息 · 3``）
#:
#: ⚠ 抽成常量是因为它被用在两个地方（建导航项 + 更新角标），
#: 两处写死同一个字符串迟早会不一致（跟「检查更新」那边同样的处理）。
NAV_NOTICE_TEXT = "消息"


def _in_test_mode() -> bool:
    """当前是不是在跑测试 —— **自动检测**，不靠每个测试文件自觉。

    ## ⚠⚠ 为什么要自动检测（2026-10-05 实测踩过）

    自动检查更新会在窗口建好后 **3 秒**去起一个**真网络线程**。
    测试里建一堆 ``MainWindow`` 的话：

      * 每个窗口都挂一个后台线程 + 真去连 GitHub
      * 整仓测试从 **~20 分钟变成 ~51 分钟**（实测）
      * 而且线程跟 GC 抢弱引用字典，偶发
        ``RuntimeError: dictionary changed size during iteration``

    一开始我加了个 ``MYTOOLS_NO_AUTO_UPDATE`` 环境变量，
    **但得每个测试文件自己记着设** —— 结果 7 个建窗口的测试文件里
    只有 1 个设了（其余 6 个继续拖慢）。

    → 改成**自动认**：``sys.argv[0]`` 是测试脚本、或者进程里跑着
    unittest/pytest，就不自动检查。这样**谁都不用记着**，也不会漏。
    """
    import os
    import sys

    #: ① 显式关掉（测试想验自动检查时把它 pop 掉再调）
    if os.environ.get("MYTOOLS_NO_AUTO_UPDATE"):
        return True

    #: ② 命令行入口是个测试脚本（`python tests/test_xxx.py`）
    argv0 = str(sys.argv[0] if sys.argv else "").replace("\\", "/").lower()
    if "/tests/" in argv0 or "pytest" in argv0 or "unittest" in argv0:
        return True

    #: ③ 进程里跑着 unittest / pytest（`python -m unittest discover`）
    if "pytest" in sys.modules or "unittest" in sys.argv[0:1]:
        return True
    main_mod = sys.modules.get("__main__")
    if getattr(main_mod, "__file__", None):
        main_file = str(main_mod.__file__).replace("\\", "/").lower()
        if "/tests/" in main_file:
            return True
    return False


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
    """导航栏右边缘的分隔条，按住左右拖动即可调整侧栏宽度。

    ## ⚠⚠ 它是**那条白缝**的来源（用户 2026-10-05 截图圈出来的）

        "另外这个白色的缝隙是什么"

    它是个 5px 宽的**裸 ``QWidget``** —— 不透明，于是在深色玻璃背景上
    就是一条白竖条。

    → 设成透明（让玻璃透出来），只留**拖动**功能。
    悬停时给一点点高亮，用户才知道这里能拖。
    """

    def __init__(self, nav, parent=None):
        super().__init__(parent)
        self._nav = nav
        self._start_global_x = 0
        self._start_width = NAV_EXPAND_WIDTH
        self.setObjectName("navResizer")
        self.setFixedWidth(5)
        self.setCursor(Qt.CursorShape.SizeHorCursor)
        self.setToolTip("拖动可调整侧栏宽度")
        #: ⚠ 必须透明 —— 不设的话就是那条白缝
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._paint(False)

    def _paint(self, hover: bool) -> None:
        """背景透明；悬停时给一点点可见的提示。"""
        color = ("rgba(127, 127, 127, 0.35)" if hover else "transparent")
        #: ⚠ 带选择器（不带会级联到子控件 —— 项目里的统一规则）
        self.setStyleSheet(f"#navResizer {{ background: {color}; }}")

    def enterEvent(self, event):  # noqa: N802 - Qt 回调
        self._paint(True)
        super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802 - Qt 回调
        self._paint(False)
        super().leaveEvent(event)

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

        #: ★ 检查更新页面 —— 用户 2026-10-05："侧边栏的检查更新呢"
        #:
        #: ⚠⚠ 第一版把更新卡**塞在配置页里面** —— 用户要的是
        #: **侧栏一个导航项**（跟「皮肤」一样）。配置页那份已删。
        self.update_interface = build_update_page(self)
        self.addSubInterface(
            self.update_interface, resolve_icon("UPDATE"), "检查更新"
        )

        #: ★ 消息通知页面 —— 用户 2026-10-10："左侧边栏增加消息通知功能，
        #: 用来储存最近发的通知，最多储存10条，每天自动清理，也可手动清理"
        #:
        #: ⚠ 跟「皮肤」「检查更新」一样是**正式导航项**（用户明确说"左侧边栏增加"），
        #: 不是塞在别页里的一块。未读数走侧栏黄字（和「检查更新」同一套机制）。
        self.notice_interface = build_notice_page(self)
        self.addSubInterface(
            self.notice_interface, resolve_icon("BELL"), NAV_NOTICE_TEXT
        )
        self.notice_interface.changed.connect(self.refresh_notice_badge)
        self._install_notice_read_hook()

        self._build_tool_group()
        self._build_library_group()

        # 主页卡片 -> 跳到对应工具
        self.home_interface.requestOpenTool.connect(self.open_tool)

        self._setup_nav_reorder()

        #: ★ 应用存下来的皮肤（启动时）—— 见 :mod:`src.core.skins`
        #:
        #: ## ⚠⚠⚠ 光在这里调一次是**不够**的（用户 2026-10-08 截图）
        #:
        #: 截图症状：**侧栏 / 标题栏是原生的黑，内容区却是皮肤的紫色**
        #: （"右边玻璃、左边白板"的翻版）。
        #:
        #: 原因：``skins._paint`` 只刷 ``isVisible()`` 的顶层窗口 ——
        #: 而 ``__init__`` 里**窗口还没 show**，一个都刷不到。
        #: 更糟的是它**把这次"空刷"记进了缓存**（``_PAINTED_QSS``），
        #: 于是 ``show()`` 之后就算再调 ``apply_current_skin()`` 也会被跳过。
        #:
        #: 实测::
        #:
        #:     建完窗口后 window 级 QSS 长度 = 37（没挂上）
        #:     NavigationPanel 长度 = 584（还是原生的深灰）
        #:     清掉缓存重刷 → 1774 / 有渐变   ✓
        #:
        #: → 这里照旧调（保证 app 级 QSS 生效），**另外在 showEvent 里
        #: 再刷一次**（那时窗口可见了）。
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

        → 延迟几秒（让界面先画出来）→ 后台查 →
        **只有真有更新**才在侧栏亮黄字（见 :meth:`set_update_badge`）。

        ⚠ 自动检查**一直开着**（用户 2026-10-05 去掉了那个开关：
        "这个不用显示出来"）—— 有更新侧栏会提示，没更新不打扰，
        本来就不需要开关。

        ⚠ 延迟是必须的：启动阶段一堆单例在建，这时候抢网络 + 建线程
        会让首屏明显变慢。

        ⚠⚠ **测试里必须关掉它**（置 ``self._skip_auto_update = True``）。
        不关的话每个 ``MainWindow()`` 都会在 3 秒后起一个**真网络线程**；
        测试跑完一堆窗口正在被回收，而后台线程还在
        ``setThemeColor()`` → ``qfluentwidgets`` 遍历弱引用字典时撞上
        GC → ``RuntimeError: dictionary changed size during iteration``
        （实测就是这么红的，而且**时红时不红**、很难查）。
        """
        if getattr(self, "_skip_auto_update", False):
            return
        if _in_test_mode():
            return

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
        """静默检查的结果 —— **只有真有更新**才在侧栏亮黄字。

        ## 用户 2026-10-05（截图圈出侧栏「检查更新」那一项）

            "有更新时，这里小黄字提示有更新即可"

        ⚠ 原来弹的是 **InfoBar**（右上角浮一条）—— 用户觉得多余，
        改成**侧栏那项直接显示黄字**：位置固定、不打断、
        想看就去点。
        """
        if not getattr(info, "has_update", False):
            return                           #: 没更新 / 查不到 → 什么都不做
        self.set_update_badge(info.latest)

    def set_update_badge(self, version: str = "") -> None:
        """★ 在侧栏「检查更新」那一项上显示**黄色提示**。

        用户 2026-10-05（截图圈出侧栏「检查更新」）::

            "有更新时，这里小黄字提示有更新即可"

        :param version: 新版本号（显示成 ``检查更新 · v1.2.0``）；
            传空字符串则**清掉**提示。

        ⚠ 真正画字/取色那两个坑写在 :meth:`_paint_nav_badge` 里 ——
        2026-10-10 加了「消息」角标后抽出去共用了（两处各写一份必然跑偏）。
        """
        item = None
        try:
            item = self.navigationInterface.widget(
                self.update_interface.objectName())
        except (RuntimeError, AttributeError):
            item = None
        if item is None:
            return
        self._paint_nav_badge(item, "检查更新", version)

    def _install_notice_read_hook(self) -> None:
        """★ 切到「消息」页时 → 标记全部已读（清掉侧栏未读角标）。

        ## 为什么不用"打开页面就清"（在页面自己里做）

        ``NoticeInterface`` 是 ``addSubInterface`` 加进去的**常驻页面** ——
        它在建窗口时就构造好了，**不是每次点开都新建**。所以"在页面里标已读"
        等于"程序一启动就全标已读"，未读角标永远不会亮。

        真正能用的信号是导航项的 ``selectedChanged``（qfluentwidgets 的
        ``NavigationInterface`` **没有** page-changed 信号 —— 实测只有
        ``displayModeChanged`` / ``objectNameChanged`` 这些，都跟页面无关）。

        ⚠ ``selectedChanged`` 每选中/取消都会发（``True``/``False`` 两次），
        所以只在 ``selected=True`` 时清。

        ⚠ 拿不到导航项就**跳过**（别抛）—— 单测里的小窗口未必有完整侧栏。
        """
        item = None
        try:
            item = self.navigationInterface.widget(
                self.notice_interface.objectName())
        except (RuntimeError, AttributeError):
            item = None
        if item is None or not hasattr(item, "selectedChanged"):
            logger.debug("拿不到「消息」导航项，未读角标不会自动清")
            return
        try:
            item.selectedChanged.connect(self._on_notice_selected)
        except (RuntimeError, AttributeError):
            logger.debug("接 selectedChanged 失败", exc_info=True)

    def _on_notice_selected(self, selected: bool) -> None:
        """选中「消息」页 → 标已读（见 :meth:`_install_notice_read_hook`）。"""
        if not selected:
            return
        try:
            self.notice_interface.mark_read()
        except Exception:  # noqa: BLE001 - 标已读失败不该影响切页
            logger.debug("标记消息已读失败", exc_info=True)

    def refresh_notice_badge(self) -> None:
        """★ 侧栏「消息」那一项显示未读数（``消息 · 3``）。

        用户 2026-10-10 要的消息功能 —— 未读时用**和「检查更新」同一种黄字**，
        这样侧栏上"有东西要看"是同一套视觉语言（两处各搞一种颜色只会乱）。

        ⚠ 和「检查更新」不同的地方：这个角标在**切到消息页**时会清掉
        （见 :meth:`_install_notice_read_hook`），而更新提示是"装完新版本才消失"。
        """
        count = 0
        try:
            count = int(self.notice_interface.unread_count())
        except Exception:  # noqa: BLE001 - 读不到就当没有未读
            logger.debug("读未读数失败", exc_info=True)
        item = None
        try:
            item = self.navigationInterface.widget(
                self.notice_interface.objectName())
        except (RuntimeError, AttributeError):
            item = None
        if item is None:
            return
        self._paint_nav_badge(item, NAV_NOTICE_TEXT,
                              str(count) if count > 0 else "")

    def _paint_nav_badge(self, item, base_text: str, badge: str) -> None:
        """给一个侧栏导航项画/清**黄字角标**（「检查更新」和「消息」共用）。

        ## ⚠⚠ 两个坑（都是摸源码才搞清的，别再踩）

        **① 必须用 ``setText()``，不能赋值 ``item.text``**

        ``text`` 是**基类的方法**（``NavigationWidget.text()``），
        绘制时调的是 ``self.text()``。赋值成字符串会把它**覆盖掉**，
        于是 ``paintEvent`` 里 ``self.text()`` 直接::

            TypeError: 'str' object is not callable

        —— 界面一画就崩（实测）。

        **② 颜色也不是 QSS，是 ``setTextColor``**

        ``NavigationTreeItem`` 是**自绘**的，颜色存在
        ``lightTextColor`` / ``darkTextColor`` 两个 ``QColor`` 上。
        写 ``styleSheet("color: ...")`` **没用**（第一版就这么写，白写）。

        :param item: ``navigationInterface.widget(objectName)`` 拿到的项
        :param base_text: 没有角标时的文字（``检查更新`` / ``消息``）
        :param badge: 角标内容（版本号 / 未读数）；空串 = 清掉角标
        """
        #: 真正画字的是里面的 NavigationTreeItem
        inner = item.findChild(QWidget)
        target = inner if inner is not None else item

        try:
            target.setText(f"{base_text} · {badge}" if badge else base_text)
            if badge:
                color = QColor(UPDATE_BADGE_COLOR)
                target.setTextColor(color, color)
            else:
                #: 恢复默认（浅色主题黑字 / 暗色主题白字）
                target.setTextColor(QColor(0, 0, 0), QColor(255, 255, 255))
            target.update()
        except (RuntimeError, AttributeError):
            logger.debug("设置侧栏角标失败：%s", base_text, exc_info=True)

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
            #: ★ 注销登记 —— 否则工具页的 notify() 会往一个已死的图标上发消息
            tray_mod.drop_tray(self._tray)

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

    def open_update_page(self) -> None:
        """切到「检查更新」页（用户 2026-10-05："侧边栏的检查更新呢"）。

        ⚠⚠ 必须 ``switchTo`` —— **不是** ``navigationInterface.setCurrentItem``。

        实测 ``setCurrentItem`` 只把侧栏那一项**高亮**，
        **页面根本不切换**（停在 ``100x30`` / ``isVisible()=False``，
        看着就是"点了没反应"）。``open_tool`` / ``open_skin_page``
        也都是先 ``switchTo`` 再 ``setCurrentItem``。
        """
        self.switchTo(self.update_interface)
        self.navigationInterface.setCurrentItem(
            self.update_interface.objectName())

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

        #: ★★★ **窗口显示后补刷一次皮肤**（用户 2026-10-08 截图）
        #:
        #: ``__init__`` 里调 ``apply_current_skin()`` 时窗口还**不可见** ——
        #: 而 ``skins._paint`` 只刷 ``isVisible()`` 的窗口，于是
        #: **侧栏 / 标题栏一个都没刷到**（还停留在原生的黑），
        #: 内容区却因为 app 级 QSS 是皮肤色 → 截图里那种割裂。
        #:
        #: ⚠ 而且那次"空刷"会被记进 ``_PAINTED_QSS`` 缓存 →
        #: 之后再调也会被跳过。所以这里**清掉缓存**再刷。
        #:
        #: ⚠ 只在真的需要时做（``_PAINTED_WINDOWS`` 里没有自己）——
        #: ``showEvent`` 每次显示都会触发（最小化恢复、切页面…），
        #: 无条件重刷会白花那 1.4 秒。
        self._repaint_skin_if_needed()

    def _repaint_skin_if_needed(self) -> None:
        """窗口显示后若发现自己**没被刷过**，补刷一次皮肤。

        ## ⚠ 不需要清 ``_PAINTED_QSS``（实测确认过）

        我一开始在这里写了 ``_skins._PAINTED_QSS = ""`` —— 以为
        "缓存记着已经刷过，不清就跳过了"。

        **其实是多余的**：``_paint`` 的跳过条件是::

            if qss == _PAINTED_QSS and set(map(id, targets)) <= _PAINTED_WINDOWS:
                return

        —— **连"刷过哪些窗口"一起比**。这个窗口还没进过名单，
        条件自然不成立，``_paint`` 会照常刷。实测（删掉清缓存那行）::

            窗口 QSS 1778 / 侧栏有渐变   ✓ 照样生效

        → 删掉，少一行误导人的代码。
        """
        try:
            from src.core import skins as _skins

            if id(self) in _skins._PAINTED_WINDOWS:  # noqa: SLF001
                return
            #: 这个窗口没进过"已刷"名单 —— 说明建的时候它不可见。
            #: 直接让 ``_paint`` 重来一遍（它会自己判断该不该刷）。
            _skins.refresh_windows()
        except Exception:  # noqa: BLE001 - 换肤失败不该拖垮显示
            logger.warning("显示后补刷皮肤失败", exc_info=True)

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
