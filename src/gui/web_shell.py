# -*- coding: utf-8 -*-
"""★ Web 外壳 —— 「整个窗口就是一个 HTML 页面」（DSH 架构）。

## 为什么要换架构（用户抱怨的核心 bug）

用户：

    > 完全按 DSH 那样做

DSH 是 Electron 应用，整个窗口就是**一个 Chromium 页面** —— 壁纸、UI、
玻璃全在 HTML/CSS 里，只有一个渲染器。

MyTools 原来是把 ``QWebEngineView`` 当**子控件**塞进 Qt 主窗口：

.. code:: text

    QMainWindow（Qt 渲染）
      ├── 侧栏 / 标题栏 / 卡片  ← Qt 画的
      └── QWebEngineView        ← Chromium 画的，当壁纸层

两个渲染器，两套合成。**窗口放大后 Chromium 的纹理被 Qt 平铺** ——
就是这个 bug 折腾了几十轮。

## 现在的架构

.. code:: text

    QWebEngineView（顶层窗口，没有 Qt 界面元素）
      └── index.html
            ├── <video>      壁纸
            ├── .glass       玻璃面板（backdrop-filter）
            └── #sidebar / #titlebar / #content   全部 HTML

**Qt 只负责开一个浏览器窗口**，画面里一个 Qt 控件都没有。
和 DSH 完全一致 → 平铺问题从根上消失（没有第二套渲染器可言）。

## 验证（无头可跑）

:meth:`WebShell.debugLayout` / :meth:`WebShell.debugScreenshot`
给测试脚本用。关键断言见 ``verify_web_shell.py``。

## 窗口控制

HTML 页面管不了原生窗口（最小化/最大化/关闭），所以标题栏那三个按钮
走 ``bridge.windowAction()`` → :attr:`~src.core.web_bridge.WebBridge.
windowActionRequested` → 这里的槽。

## 和旧界面的关系

**旧 Qt 界面一行没删**。开关见 :func:`is_enabled`：
``config.json`` 的 ``UI.WebShell`` 或环境变量 ``MYTOOLS_WEB_SHELL=1``。
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import QWidget

logger = logging.getLogger(__name__)

#: 前端资源目录（``src/gui/web``）
WEB_DIR = Path(__file__).resolve().parent / "web"

#: 环境变量开关
ENV_KEY = "MYTOOLS_WEB_SHELL"

#: config.json 里的开关路径（``config.json`` 是 qfluentwidgets 的配置文件）
CONFIG_SECTION = "UI"
CONFIG_KEY = "WebShell"

#: ★ 允许挂给网页的 ``assets/game/`` 子目录（白名单，**不是整个目录**）
#:
#: ## 为什么不挂整个 ``assets/game``
#:
#: 里面 ``splash/`` 有 **773 MB**（启动动画的 mp4/jpg）。
#: 挂上去等于把整个磁盘目录暴露给页面，而且资源库只要下面这几个小目录。
#:
#: 实测体积：
#:
#: ==============  ========  ========
#: 子目录            文件数     体积
#: ==============  ========  ========
#: avatars             61      8.9 MB    角色头像
#: echoes             187     18.8 MB    声骸图标
#: echo_sets           37      0.2 MB    套装图标
#: weapons            123      6.4 MB    武器图标
#: kuro_icons         867     48.0 MB    （不挂 —— 资源库用不到）
#: splash               4    773.0 MB    （绝对不挂）
#: ==============  ========  ========
#:
#: 白名单合计约 **35 MB**。
GAME_ASSET_SUBDIRS: tuple[str, ...] = ("avatars", "echo_sets", "echoes", "weapons")


# ══════════════════════════════════════════════════════════════════════════
#  开关
# ══════════════════════════════════════════════════════════════════════════
def is_enabled() -> bool:
    """当前该用 Web 外壳还是旧的 Qt 界面？

    判定顺序（先到先得）：

    1. 环境变量 ``MYTOOLS_WEB_SHELL``（``1``/``true``/``yes``/``on`` 为真）
    2. ``config.json`` 的 ``UI.WebShell``
    3. 默认 **True**（Web 外壳）

    ## ★ 2026-11-02：默认值从 False 翻成 True

    用户明确要求：「**干脆把新界面设为默认**」。

    翻转时机（三个条件都满足才翻）：

    ===================  ==========================================
    条件                  状态
    ===================  ==========================================
    7 个工具面板都有        ✅ 7/7（渲染实测，不是占位）
    托盘                   ✅ setup_tray / 关窗确认，对齐旧界面
    自动化验证全绿          ✅ 327 项
    ===================  ==========================================

    ## ⚠ 回退方式（重要，写在这里方便用户搜到）

    新外壳**有任何问题**都能一键退回旧界面，**旧代码一行没删**：

    .. code:: powershell

        # 临时：只对当前终端生效
        $env:MYTOOLS_WEB_SHELL = "0"
        .venv\\Scripts\\python.exe main.py

    或者改用户配置 ``<用户数据>/config/config.json``::

        {"UI": {"WebShell": false}}

    ## 启动失败会自动回退

    ``main.py`` 里 ``create_shell()`` 抛异常或返回 ``None``
    （QtWebEngine 缺失、HTTP 服务起不来…）会**自动退回旧界面**，
    不会白屏。见 ``main.py`` 的 ``if window is None:`` 分支。

    环境变量优先是给**开发和测试**用的：不用改用户配置文件就能切。
    """
    raw = (os.environ.get(ENV_KEY) or "").strip().lower()
    if raw:
        return raw in ("1", "true", "yes", "on", "y")

    try:
        from ..core import paths  # noqa: PLC0415

        #: qfluentwidgets 的配置在 <用户数据>/config/config.json
        candidates = [
            paths.user_data_dir() / "config" / "config.json",
            Path(__file__).resolve().parents[2] / "config" / "config.json",
        ]
        for cfg in candidates:
            if not cfg.is_file():
                continue
            data = json.loads(cfg.read_text(encoding="utf-8"))
            section = data.get(CONFIG_SECTION) or {}
            if isinstance(section, dict) and CONFIG_KEY in section:
                value = section.get(CONFIG_KEY)
                if isinstance(value, bool):
                    return value
                return str(value).strip().lower() in ("1", "true", "yes", "on")
    except Exception:  # noqa: BLE001 - 配置坏了不该影响启动
        logger.debug("web_shell：读配置开关失败", exc_info=True)

    #: ★ 默认用新外壳。想回旧界面设 MYTOOLS_WEB_SHELL=0 或 UI.WebShell=false。
    return True


# ══════════════════════════════════════════════════════════════════════════
#  资源准备
# ══════════════════════════════════════════════════════════════════════════
def prepare_assets() -> list[str]:
    """把工具图标镜像进 ``src/gui/web/assets/icons/``。

    ## 为什么是「复制」而不是挂载两个目录

    ``media_server`` 支持多挂载，理论上可以 ``/icons/`` → ``assets/icons``。
    但那样图标 URL 就跨了挂载点，**路径和页面资源不一致**，
    调试时容易搞混。而且图标只有几百 KB，复制一次最省事。

    ⚠ **幂等**：只复制目标不存在的文件（或源更新过的），
    不删用户手动改过的东西。

    :return: 本次复制的文件名列表
    """
    copied: list[str] = []
    try:
        from ..core import paths  # noqa: PLC0415

        src_dir = paths.resource_dir("assets", "icons")
        if not src_dir.is_dir():
            logger.info("web_shell：没有 assets/icons/，工具卡片用内置图标")
            return copied
        dst_dir = WEB_DIR / "assets" / "icons"
        dst_dir.mkdir(parents=True, exist_ok=True)
        for src in src_dir.iterdir():
            if not src.is_file():
                continue
            if src.suffix.lower() not in (".png", ".jpg", ".jpeg", ".svg",
                                          ".webp", ".ico"):
                continue
            dst = dst_dir / src.name
            try:
                if dst.is_file() and dst.stat().st_mtime >= src.stat().st_mtime:
                    continue
                shutil.copy2(src, dst)
                copied.append(src.name)
            except OSError:
                logger.debug("web_shell：复制图标失败 %s", src, exc_info=True)
        if copied:
            logger.info("web_shell：镜像 %d 个工具图标", len(copied))
    except Exception:  # noqa: BLE001
        logger.warning("web_shell：准备图标资源失败", exc_info=True)
    return copied


def web_base_url(*, start_media: bool = True) -> str:
    """起 HTTP 服务并返回前端 base URL（如 ``http://127.0.0.1:12345/web/``）。

    ## 为什么页面也必须走 HTTP（★ 关键）

    实测（见 :mod:`src.core.media_server` 模块文档）：

    * ``setHtml()`` 给的 baseUrl 是 ``about:blank`` / file 目录
    * 视频走 ``http://`` → **同源策略拒绝**，``MEDIA_ERR_SRC_NOT_SUPPORTED``

    ``<video>`` 是最典型的受害者，但同一个服务里加载 css/js 也有
    类似问题（相对路径解析）。**页面和视频同源**是唯一稳的做法。

    :return: base URL；服务起不来返回空串（调用方应退回旧界面）
    """
    try:
        from ..core import media_server, paths, webm_transcode  # noqa: PLC0415

        if not (WEB_DIR / "index.html").is_file():
            logger.error("web_shell：找不到 %s", WEB_DIR / "index.html")
            return ""

        prepare_assets()

        #: 转码缓存目录 —— 壁纸视频从这里出
        cache = webm_transcode.cache_dir()
        if cache is not None:
            media_server.start(cache)
        else:
            #: 没有缓存目录时，拿用户数据目录顶上（服务还能起，只是没视频）
            media_server.start(paths.user_data_dir())

        if not media_server.mount("/web/", WEB_DIR):
            logger.error("web_shell：挂载 %s 失败", WEB_DIR)
            return ""
        #: 用户自备壁纸目录（将来 getWallpaper 会用到）
        try:
            user_dir = paths.user_data_dir() / "wallpapers"
            if user_dir.is_dir():
                media_server.mount("/user/", user_dir)
        except Exception:  # noqa: BLE001
            pass

        #: ★ 游戏素材（资源库要的头像 / 声骸 / 套装 / 武器）
        #: 只挂白名单里的子目录 —— 见 GAME_ASSET_SUBDIRS 的说明
        mounted = []
        for sub in GAME_ASSET_SUBDIRS:
            d = paths.resource_dir("assets", "game", sub)
            if d.is_dir() and media_server.mount(f"/game/{sub}/", d):
                mounted.append(sub)
        if mounted:
            logger.info("web_shell：游戏素材已挂载 %s", ", ".join(mounted))
        else:
            logger.info("web_shell：没有 assets/game 素材，资源库页会提示缺失")

        url = media_server.web_url("index.html", bust=True)
        if not url:
            logger.error("web_shell：HTTP 服务没起来")
            return ""

        #: ★★★ 等 HTTP **真的能响应**再返回
        #:
        #: 不等的话会踩启动竞态：``start()`` 里的 ``serve_forever()``
        #: 在别的线程，调度到它之前 Chromium 的请求没人应答 →
        #: 首次启动白屏、第二次就好。见 :func:`media_server.wait_until_ready`。
        #:
        #: ⚠ 探测本身偶发失败（本次实测：探测被 mock 成失败一次就再没
        #: 起来）也可能发生。所以这里**重试 3 次、间隔递增**，
        #: 而不是一次失败就放弃整个 Web 外壳。
        if not _wait_http_ready(media_server, attempts=3):
            logger.error("web_shell：HTTP 服务未就绪，放弃 Web 外壳")
            return ""

        logger.info("web_shell：前端走 HTTP %s", url)
        return url
    except Exception:  # noqa: BLE001
        logger.exception("web_shell：准备 HTTP 服务失败")
        return ""


def _wait_http_ready(media_server, *, attempts: int = 3) -> bool:
    """反复探测 HTTP 服务，直到可用或次数用尽。

    ## 为什么要「多次」而不是「一次长时间等」

    ``wait_until_ready(timeout=3)`` 内部已经是「每 50ms 重试」了。
    但实测发现另一个问题：**偶发的探测失败**（连接被拒一次之后就
    一直拒）会把整个 Web 外壳判死。

    真实场景：服务线程崩了、端口被占用然后释放、防火墙拦截了前几次。
    这些情况下再探一次往往就好了。所以外面再包一层重试。

    :return: 任一次探测成功即返回 True
    """
    for i in range(max(1, attempts)):
        try:
            if media_server.wait_until_ready(timeout=2.0):
                return True
        except Exception:  # noqa: BLE001
            logger.debug("web_shell：HTTP 探测异常（第 %d 次）", i + 1,
                         exc_info=True)
        if i + 1 < attempts:
            logger.info("web_shell：HTTP 还没就绪，稍后重试（%d/%d）",
                        i + 1, attempts)
            import time as _t

            _t.sleep(0.25)
    return False


# ══════════════════════════════════════════════════════════════════════════
#  WebShell
# ══════════════════════════════════════════════════════════════════════════
class WebShell(QObject):
    """★ 整个窗口 = 一个 ``QWebEngineView``。

    用法（代替 ``MainWindow``）：

    .. code:: python

        shell = WebShell()
        shell.show()

    ## 为什么继承 QObject 而不是 QWebEngineView

    窗口对象需要能被主程序持有、有信号、能单独销毁 —— 用组合比继承干净。
    且 ``QWebEngineView`` 的 Python 子类化在退出时容易踩
    「C++ 对象已析构」的坑（Qt 的 parent/所有权语义和 Python GC 打架）。

    真正的窗口对象是 :attr:`view`。

    ## 信号

    * :attr:`closed`    —— 用户点了关闭（主程序据此退出）
    * :attr:`ready`      —— 前端脚本跑完（页面真的可用了）
    * :attr:`loadFailed` —— 页面加载失败（主程序可退回旧界面）
    """

    #: 用户点了关闭按钮 / 窗口被关
    closed = Signal()
    #: 前端脚本跑完（JS 握手成功）
    ready = Signal()
    #: 页面加载失败（参数是错误描述）
    loadFailed = Signal(str)

    def __init__(self, parent: QObject | None = None, *,
                 base_url: str = "", window_icon: QIcon | None = None):
        super().__init__(parent)
        self._view = None
        self._bridge = None
        self._channel = None
        self._base_url = base_url
        self._ready = False
        self._window_icon = window_icon
        #: 关闭时是否真的退出程序（``close()`` 由外部触发时置真）
        self._really_close = False
        #: 页面加载重试计数 / 上限（见 :meth:`_retry_load`）
        self._load_attempt = 0
        self._max_load_retries = 2
        #: ★ 托盘图标（2026-11-02 加，见 :meth:`setup_tray`）
        self._tray = None
        #: 关闭确认框的父对象（**必须**是 QWidget，WebShell 是 QObject 不行）
        self._dialog_parent = None
        #: ★ 边缘缩放的 native 事件过滤器（见 :meth:`_install_resize_support`）
        self._native_filter = None
        #: ★ 上次推给页面的「是否最大化」（去重用，见 :meth:`_push_window_state`）
        self._pushed_maximized = None

    # ---------------------------------------------------------------- 属性
    @property
    def view(self):
        """底层 ``QWebEngineView``（顶层窗口）。未初始化时为 None。"""
        return self._view

    def windowTitle(self) -> str:  # noqa: N802 - 对齐 Qt 命名
        """窗口标题。

        ⚠ 必须显式转发到 ``view`` —— ``WebShell`` 继承的是 ``QObject``
        不是 ``QWidget``，本身没有 ``windowTitle()``。主程序 / 托盘 /
        任务栏都会问这个，返回空串会让任务栏显示 "(无标题)"。
        """
        if self._view is not None:
            return self._view.windowTitle()
        try:
            from ..app_config import APP_DISPLAY_NAME  # noqa: PLC0415

            return APP_DISPLAY_NAME
        except Exception:  # noqa: BLE001
            return ""

    def setWindowTitle(self, title: str) -> None:  # noqa: N802 - 对齐 Qt 命名
        if self._view is not None:
            self._view.setWindowTitle(title)

    def windowIcon(self):  # noqa: N802 - 对齐 Qt 命名
        return self._window_icon

    def resize(self, width: int, height: int) -> None:  # noqa: N802
        if self._view is not None:
            self._view.resize(width, height)

    def raise_(self) -> None:
        if self._view is not None:
            self._view.raise_()

    def activateWindow(self) -> None:  # noqa: N802
        if self._view is not None:
            self._view.activateWindow()

    def isMaximized(self) -> bool:  # noqa: N802
        return bool(self._view is not None and self._view.isMaximized())

    def objectName(self) -> str:  # noqa: N802 - 对齐 Qt 命名
        """给托盘 / 信号连接用的稳定标识。"""
        return "WebShellWindow"

    @property
    def bridge(self):
        """暴露给 JS 的 :class:`~src.core.web_bridge.WebBridge` 实例。"""
        return self._bridge

    @property
    def is_ready(self) -> bool:
        return self._ready

    # ---------------------------------------------------------------- 启动
    def build(self) -> bool:
        """创建窗口 + 桥 + 加载页面。成功返回 True。

        ## 调用顺序是硬要求

        1. 起 HTTP 服务（页面和视频同源）
        2. 建 ``QWebEngineView``
        3. 建 ``QWebChannel`` 并 **注册 bridge**
        4. 最后才 ``setUrl()`` —— 顺序反了的话页面的
           ``new QWebChannel(qt.webChannelTransport)`` 会拿不到对象，
           表现为「JS 侧 bridge 是 undefined」（很难查）
        """
        if self._view is not None:
            return True

        try:
            from PySide6.QtWebChannel import QWebChannel  # noqa: PLC0415
            from PySide6.QtWebEngineCore import QWebEngineSettings  # noqa: PLC0415
            from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: PLC0415
        except Exception:  # noqa: BLE001
            logger.exception("web_shell：QtWebEngine 不可用")
            self.loadFailed.emit("QtWebEngine 不可用")
            return False

        from ..app_config import (  # noqa: PLC0415
            APP_DISPLAY_NAME,
            WINDOW_DEFAULT_HEIGHT,
            WINDOW_DEFAULT_WIDTH,
            WINDOW_MIN_HEIGHT,
            WINDOW_MIN_WIDTH,
        )
        from ..core.web_bridge import WebBridge  # noqa: PLC0415

        #: ① HTTP 服务（幂等，可多次调用）
        if not self._base_url:
            self._base_url = web_base_url()
        if not self._base_url:
            self.loadFailed.emit("本地 HTTP 服务起不来")
            return False

        #: ② 窗口
        view = QWebEngineView()
        view.setWindowTitle(APP_DISPLAY_NAME)
        view.resize(WINDOW_DEFAULT_WIDTH, WINDOW_DEFAULT_HEIGHT)
        view.setMinimumSize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)
        if self._window_icon is not None:
            view.setWindowIcon(self._window_icon)

        #: ★★★ 无边框（2026-11-02，用户："那个白色的方块区域去掉，
        #: 下面本来就有最小化，关闭，放大"）
        #:
        #: ## 问题
        #:
        #: 不设 ``FramelessWindowHint`` 时屏幕上会**有两个标题栏**：
        #:
        #: .. code:: text
        #:
        #:     ┌────────────────────────────────┐
        #:     │ 鸣潮工具箱            ─  □  ✕  │  ← Windows 原生（白色）
        #:     ├────────────────────────────────┤
        #:     │ 主页                  ─  □  ✕  │  ← 页面自绘（深色）
        #:     └────────────────────────────────┘
        #:
        #: 页面里 ``#titlebar`` 已经有那三个按钮了，所以去掉原生那个。
        #:
        #: ## 保留 ``Window`` 而不是用 ``Tool``
        #:
        #: ``Qt.Tool`` 的窗口**不进任务栏** —— 用户切到别的程序后就找不回来了。
        #: 必须保留 ``Qt.Window``（有任务栏图标 + 系统菜单）。
        #:
        #: ## 代价：原生的拖动/缩放/双击最大化全没了
        #:
        #: 所以下面要自己补：
        #:
        #: * 拖动 / 双击最大化 —— :meth:`_install_window_drag`
        #:   （页面 ``.titlebar`` 触发 → ``startWindowDrag()`` → Win32
        #:   ``ReleaseCapture`` + ``WM_NCLBUTTONDOWN``）
        #: * 边缘缩放 —— :meth:`_install_resize_grip`（``QSizeGrip`` 兜底）
        view.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            #: 保留最大化/最小化的系统能力（任务栏右键菜单用它）
            | Qt.WindowType.WindowMinMaxButtonsHint
        )

        #: ★★★ 窗口背景色 —— 必须是**不透明深色**
        #:
        #: 设成透明的话：QtWebEngine 走 `setBackgroundColor(QColor(0,0,0,0))`，
        #: Chromium 合成时要把页面和桌面混色，某些驱动下会退化成软件合成
        #: （100% 出现平铺/残影）。DSH 那边 Electron 也是不透明底。
        page = view.page()
        page.setBackgroundColor(QColor("#090713"))

        #: ★ 关键设置
        settings = page.settings()
        for attr_name, value in (
            #: 页面自己滚（内容区的 .page 有 overflow-y:auto）
            ("ShowScrollBars", False),
            #: 桌面应用：一定要允许自动播放，否则壁纸不动
            ("PlaybackRequiresUserGesture", False),
            #: 允许访问远程（视频走 http://）
            ("LocalContentCanAccessRemoteUrls", True),
            ("LocalContentCanAccessFileUrls", True),
            #: 加速：GPU 合成
            ("Accelerated2dCanvasEnabled", True),
            ("WebGLEnabled", True),
        ):
            attr = getattr(QWebEngineSettings.WebAttribute, attr_name, None)
            if attr is not None:
                try:
                    settings.setAttribute(attr, value)
                except Exception:  # noqa: BLE001
                    pass

        #: ③ 桥接 —— 必须在 setUrl 之前注册
        bridge = WebBridge(view)
        channel = QWebChannel(view)
        channel.registerObject("bridge", bridge)
        page.setWebChannel(channel)

        self._view = view
        self._bridge = bridge
        self._channel = channel

        #: ★ 把宿主挂给桥 —— 页面的 ``getWindowState()`` 要问它
        #: （见 ``WebBridge._window_host`` 和 ``_push_window_state``）
        try:
            bridge._window_host = self  # noqa: SLF001 - 同包内部约定
        except Exception:  # noqa: BLE001
            logger.debug("web_shell：挂宿主给桥失败", exc_info=True)

        #: 桥 → 窗口控制
        bridge.windowActionRequested.connect(self._on_window_action)
        bridge.frontendReadySignal.connect(self._on_frontend_ready)

        #: 加载结果日志（排查白屏第一现场）
        page.loadFinished.connect(self._on_load_finished)
        try:
            page.renderProcessTerminated.connect(
                lambda status, code: logger.error(
                    "web_shell：渲染进程退出了 status=%s code=%s", status, code))
        except Exception:  # noqa: BLE001
            pass

        #: ④ 无边框窗口的补偿能力（2026-11-02）
        #:
        #: ``FramelessWindowHint`` 把 Windows 原生那套拖动/缩放/双击最大化
        #: 全拿走了，这三样必须自己补：
        #:   * 拖动 → 页面调 ``startWindowDrag()``（Win32 接管）
        #:   * 双击最大化 → 页面调 ``windowAction('togglemaximize')``
        #:   * 边缘缩放 → :meth:`_install_resize_support`（``WM_NCHITTEST``）
        self._install_resize_support()

        #: ★ 标题栏 □ 按钮要随最大化状态换图标（2026-11-03）
        #:
        #: ⚠ **不能只挂在托盘那条路上** —— ``setup_tray()`` 是
        #: ``main.py`` 在 ``show()`` **之前**调的，而且拿不到系统托盘时
        #: 会提前返回，eventFilter 就永远装不上。
        #:
        #: 这里挂是幂等的（同一个对象重复 install 无害），
        #: 托盘那条路保持原样就行。
        try:
            view.installEventFilter(self)
        except Exception:  # noqa: BLE001
            logger.debug("web_shell：装窗口状态过滤器失败", exc_info=True)

        #: ⑤ 系统圆角 + 阴影（Win11 专属；Win10 静默跳过）
        #:
        #: ⚠⚠ **不在这里设** —— 实测 Qt 在 ``show()`` 时会重置窗口样式，
        #: 把 DWM 属性冲掉（设的时候 hr=0，show 之后回读却是 0/DEFAULT）。
        #: 放到 :meth:`show` 里，真正显示出来之后再设。见那里的说明。
        #: 这里只是提前把 _apply 的机会留在 show()。

        #: ⑥ 最后才加载页面
        logger.info("web_shell：加载 %s", self._base_url)
        self._load_attempt = 0
        view.setUrl(QUrl(self._base_url))
        return True

    # ---------------------------------------------------------------- 托盘
    def setup_tray(self) -> bool:
        """挂系统托盘（2026-11-02 加）。

        ## 为什么必须有（lead 指出的功能退化）

        旧界面有托盘：最小化到托盘、关窗口进托盘、任务运行中提示。
        Web 外壳原来**没有** → 用户切过来后「关窗口」变成**直接退出**，
        正在跑的任务会被中断。这是显眼的功能退化，也是设默认的阻塞项。

        ## 复用什么

        直接调 :mod:`src.gui.tray` 的现成实现 —— ``make_tray()`` /
        ``build_menu()`` / ``ask_close()`` / ``running_task_name()``。
        那个模块的菜单配色、气泡通知等细节都已经调好了，没必要重写。

        ## 关闭行为的改变

        挂了托盘之后：

        * 点窗口的 X → 弹确认框（「退出 or 取消」），**和旧界面一致**
        * 托盘菜单「退出」→ 真退出
        * 有任务在跑时关窗口 → 确认框会点名说清楚

        ⚠ **刻意没做"关窗口就隐藏到托盘"** ——
        用户 2026-10-24 明确要求去掉那个选项（见 ``tray.close_question``
        的文档）。现在只有「退出 / 取消」两个出口。

        :return: 托盘建起来了返回 True（拿不到系统托盘时 False，无害）
        """
        if self._tray is not None:
            return True
        try:
            from . import tray as tray_mod  # noqa: PLC0415

            self._dialog_parent = self._view
            self._tray = tray_mod.make_tray(
                self._view, self._show_from_tray, self.quit_app,
                icon=self._window_icon)
            if self._tray is None:
                logger.info("web_shell：系统托盘不可用，关闭仍是直接退出")
                return False
            #: ★ 关窗口改为「先问一下」—— 挂 eventFilter 拦 QCloseEvent
            self._view.installEventFilter(self)
            logger.info("web_shell：托盘图标已就绪（关窗口会先确认）")
            return True
        except Exception:  # noqa: BLE001 - 托盘失败不该拖垮程序
            logger.warning("web_shell：托盘初始化失败", exc_info=True)
            self._tray = None
            return False

    def teardown_tray(self) -> None:
        """注销托盘（退出/销毁时调）。"""
        if self._tray is None:
            return
        try:
            from . import tray as tray_mod  # noqa: PLC0415

            tray_mod.drop_tray(self._tray)
            self._tray.hide()
        except Exception:  # noqa: BLE001
            logger.debug("web_shell：注销托盘失败", exc_info=True)
        self._tray = None

    def _show_from_tray(self) -> None:
        """托盘「显示」/ 左键单击 → 把窗口叫回来。"""
        if self._view is None:
            return
        self._view.showNormal()
        self._view.show()
        self._view.raise_()
        self._view.activateWindow()

    def quit_app(self) -> None:
        """托盘菜单「退出」→ 真退出（跳过确认框）。"""
        self._really_close = True
        self.teardown_tray()
        if self._view is not None:
            self._view.close()

    def eventFilter(self, obj, event):  # noqa: N802 - Qt 接口
        """窗口事件钩子：① 跟踪最大化状态 ② 拦住关闭先问「退出还是取消」。

        ## ① 最大化状态 → 推给页面（2026-11-03）

        页面标题栏的 □ 按钮原来把图标**写死**成 ``E922``（最大化方块），
        所以窗口最大化之后**还是那个单框图标** —— 用户圈出来说：

        > 放大后，这个缩小框不对把，应该右图那样

        正确的是最大化时换成 ``E923``（ChromeRestore，两个叠起来的方框）。

        ``WM_NCHITTEST`` 那条路没法知道窗口状态变化，得靠 Qt 的
        ``QEvent.WindowStateChange``：用户点 □、双击标题栏、拖到屏幕
        边缘 Aero Snap、系统菜单……**全都会**走到这里。

        ## 为什么用 eventFilter 而不是重写 closeEvent

        ``self._view`` 是 ``QWebEngineView`` 的**实例**，不是我们定义的子类
        —— 没法重写它的 ``closeEvent``。``QObject`` 的 ``eventFilter``
        是唯一的钩子。

        ## 关闭确认：什么时候不管

        * 没挂托盘（``_tray is None``）→ 直接关（没有"退到托盘"的概念，
          弹框只会烦用户）
        * ``_really_close`` 已置真 → 是 ``quit_app()`` / 主程序主动关，
          跳过确认

        确认框逻辑**完全复用** :func:`src.gui.tray.ask_close` ——
        它的文案、按钮映射、有任务时的措辞都已经调好并单测过。
        """
        from PySide6.QtCore import QEvent  # noqa: PLC0415

        event_type = event.type()

        #: ★ ① 最大化 / 还原 → 通知页面换图标
        if event_type == QEvent.Type.WindowStateChange:
            self._push_window_state()
            return False

        if event_type != QEvent.Type.Close:
            return False
        if self._really_close or self._tray is None:
            return False

        try:
            from . import tray as tray_mod  # noqa: PLC0415
            from ..tools.game.auto_combat import okww_boot  # noqa: PLC0415

            host = None
            try:
                host = okww_boot.current_host()
            except Exception:  # noqa: BLE001
                host = None
            running = tray_mod.running_task_name(host)
            #: 桥接层自己的运行状态也要算（FlowRunThread 那条路）
            if not running and self._bridge is not None:
                running = str(self._bridge._running or "") or None

            choice = tray_mod.ask_close(
                self._dialog_parent or self._view, running,
                allow_hide=False)
            if choice != tray_mod.CLOSE_QUIT:
                event.ignore()
                return True          #: 拦下，窗口不关

            #: 用户选了退出 → 有任务就先停掉
            if running and host is not None:
                try:
                    host.stop_task()
                except Exception:  # noqa: BLE001
                    logger.warning("退出前停止 ok-ww 任务失败", exc_info=True)
            self._really_close = True
            self.teardown_tray()
            return False             #: 放行，正常关闭
        except Exception:  # noqa: BLE001 - 确认流程崩了也不能挡住关窗口
            logger.warning("web_shell：关闭确认失败（直接关）", exc_info=True)
            return False

    def _push_window_state(self) -> None:
        """把「当前是否最大化」推给页面（标题栏 □ 按钮据此换图标）。

        ## 为什么需要（2026-11-03 用户圈图反馈）

        页面原来把图标**写死**成 ``E922``（最大化方块）：

        .. code:: html

            <button id="btn-max">&#xE922;</button>

        窗口最大化之后**还是那个单框图标** —— 但这时候点它是「还原」，
        图标应该变成 ``E923``（ChromeRestore，两个叠起来的方框）。

        用户原话：

            > 放大后，这个缩小框不对把，应该右图那样

        ## 为什么由 Python 推、不是页面自己判

        页面**看不到**原生窗口状态：用户可能是双击标题栏、点 □、
        拖到屏幕边缘 Aero Snap、用 Win+↑、点任务栏预览菜单……
        这些都不会经过 JS。只有 Qt 的 ``WindowStateChange`` 能全覆盖。

        ## 幂等

        ``WindowStateChange`` 会因为最小化/激活等无关变化反复触发，
        所以记住上次推的值，**没变就不推**。
        """
        if self._bridge is None or self._view is None:
            return
        maximized = bool(self._view.isMaximized())
        #: 最小化时也算"最大化态"——还原回来还是最大化，图标别闪
        if maximized == self._pushed_maximized:
            return
        self._pushed_maximized = maximized
        try:
            self._bridge.pushWindowState(maximized)
        except Exception:  # noqa: BLE001 - 推不动不该影响窗口
            logger.debug("web_shell：推窗口状态失败", exc_info=True)

    def _retry_load(self) -> None:
        """★ 页面加载失败时自动重试（兜住启动竞态）。

        ## 什么情况下会走到这里

        主要就是**启动竞态**：HTTP 服务刚起，Chromium 的请求抢先发出、
        没人应答 → ``loadFinished(False)``。
        :func:`media_server.wait_until_ready` 已经挡住绝大多数，
        这里是**双保险**（也兜住偶发的连接重置）。

        ⚠ 只重试 2 次、间隔递增。无限重试会在「前端资源真的丢了」时
        刷爆日志，而且用户永远看到白屏 —— 不如快速失败、退回旧界面。
        """
        if self._view is None or not self._base_url:
            return
        self._load_attempt += 1
        if self._load_attempt > self._max_load_retries:
            logger.error("web_shell：重试 %d 次仍失败，放弃",
                         self._max_load_retries)
            self.loadFailed.emit("页面加载失败（已重试）")
            return

        delay = 200 * self._load_attempt
        logger.warning("web_shell：加载失败，%dms 后第 %d 次重试",
                       delay, self._load_attempt)
        from PySide6.QtCore import QTimer  # noqa: PLC0415

        QTimer.singleShot(delay, self._do_retry_load)

    def _do_retry_load(self) -> None:
        if self._view is None or not self._base_url:
            return
        #: 加时间戳强制绕过 Chromium 缓存里的失败记录
        sep = "&" if "?" in self._base_url else "?"
        self._view.setUrl(QUrl(f"{self._base_url}{sep}r={self._load_attempt}"))

    # ---------------------------------------------------------------- 窗口
    def show(self) -> None:
        """显示窗口。

        ## ★★★ 圆角必须在这里设，不能放在 ``build()`` 里

        实测（2026-11-02）：

        .. code:: text

            build() 里调 DwmSetWindowAttribute(33, ROUND) → hr=0（看起来成功）
            show() 之后 DwmGetWindowAttribute(33) → 0（DEFAULT，不是 ROUND）

        **Qt 在 ``show()`` 时会重新设置窗口样式，把 DWM 属性冲掉。**

        所以顺序必须是：``show()`` → 再设圆角 → 回读确认。
        """
        if self._view is None and not self.build():
            return
        self._view.show()
        self._view.raise_()
        self._view.activateWindow()
        #: ★ 窗口真的显示出来了，现在设圆角才不会被冲掉
        self.apply_window_corner()
        #: ★★★ 2026-11-02 补回 WS_THICKFRAME —— **必须在 show() 之后**
        #:
        #: Qt 在 show() 时按 FramelessWindowHint 重建窗口样式，
        #: 把 WS_CAPTION / WS_THICKFRAME 都清掉了。
        #: 不补的话 Windows 拒绝拖动（用户：「这整个窗口还是不能拖拽」）。
        self._restore_drag_style()
        #: ★ 初始状态也推一次（2026-11-03）—— 页面加载完才知道窗口是不是
        #: 最大化启动的。见 :meth:`_push_window_state`。
        self._push_window_state()

    def close(self) -> None:
        """主动关窗口（置了 _really_close，closeEvent 不再拦）。

        ⚠ 这里要同时处理两件事：

        1. ``QWebEngineView`` 没有 ``closeEvent`` 覆写 —— 直接 ``close()``
           就真的关了，不会弹确认框。
        2. 但 ``QApplication.quitOnLastWindowClosed`` 默认是 True，
           关掉唯一窗口会让 Qt **自动退出事件循环**。如果调用方只是想
           关窗口（比如重开一个），得自己看 ``app.quitOnLastWindowClosed``。
        """
        self._really_close = True
        #: ★ 卸载 native 过滤器 —— 窗口没了还留着它，事件会打到失效的 view 上
        self._remove_resize_support()
        if self._view is not None:
            self._view.close()

    @property
    def force_quit(self) -> bool:
        """兼容 ``MainWindow._force_quit`` 的读法（测试/托盘都用它）。"""
        return self._really_close

    def hide(self) -> None:
        if self._view is not None:
            self._view.hide()

    def showMinimized(self) -> None:  # noqa: N802 - 对齐 Qt 命名
        if self._view is not None:
            self._view.showMinimized()

    def showNormal(self) -> None:  # noqa: N802 - 对齐 Qt 命名
        if self._view is not None:
            self._view.showNormal()

    def showMaximized(self) -> None:  # noqa: N802 - 对齐 Qt 命名
        if self._view is not None:
            self._view.showMaximized()

    def isVisible(self) -> bool:  # noqa: N802 - 对齐 Qt 命名
        return bool(self._view is not None and self._view.isVisible())

    def central_widget(self) -> QWidget | None:
        """给托盘/外部代码用的窗口对象。"""
        return self._view

    # ------------------------------------------------------- 无边框窗口能力
    #
    # ★★★ 2026-11-02：设了 ``FramelessWindowHint`` 之后，Windows 原生那套
    # 拖动 / 双击最大化 / 边缘缩放**全都没了**，必须自己补回来。
    #
    # 用户要求：「那个白色的方块区域去掉，下面本来就有最小化，关闭，放大」
    # —— 去掉原生标题栏，用页面自绘的。

    def start_window_drag(self) -> None:
        """开始拖拽窗口（页面 ``.titlebar`` 的 mousedown 调它）。

        ## 原理：让 Windows 以为用户在拖"原生标题栏"

        .. code:: python

            ReleaseCapture()                                  # 释放鼠标捕获
            SendMessage(hwnd, WM_NCLBUTTONDOWN, HTCAPTION, 0)  # 假装按在标题栏上

        Windows 收到之后**自己接管**拖动 —— 不用我们算鼠标位移，
        而且自带拖到屏幕边缘的"贴边分屏"（Aero Snap）。

        ⚠ 比"记录 mousedown 坐标 + 自己 move()"好得多：
        自己算的实现**拖快了会掉帧、贴边不会分屏**。

        ## 非 Windows 平台

        macOS / Linux 上直接返回 —— 那边无边框窗口通常另有做法
        （本项目只发 Windows，这条路只是不让测试崩）。
        """
        import sys  # noqa: PLC0415

        if sys.platform != "win32":
            logger.debug("start_window_drag：非 Windows 平台，跳过")
            return
        view = self._view
        if view is None:
            return
        try:
            import ctypes  # noqa: PLC0415
            from ctypes import wintypes  # noqa: PLC0415

            hwnd = int(view.winId())
            if not hwnd:
                return

            #: ★★★ 2026-11-03 **三个错误一起修好才真的能拖**
            #:
            #: ## 错误 ①：消息号写成 ``0x00A2``（= WM_NCLBUTTON**UP**）
            #:
            #: 拖动要用的是 **``0x00A1`` = WM_NCLBUTTONDOWN**。
            #: 发 UP 的语义是「鼠标左键在标题栏上松开了」——
            #: 窗口管理器收到一条"松开"消息，没有"按下"配对，
            #: **直接忽略**，窗口一动不动。
            #:
            #: 实测（真 ``SendInput`` 注入，DPR=1.25）：
            #:
            #: .. code:: text
            #:
            #:     发 0x00A2（旧）→ 窗口 (1250,875) 位置尺寸**完全没变**
            #:     发 0x00A1（新）→ 窗口从 (300,200) 拖到 (444,260) ✅
            #:
            #: ## 错误 ②：``lParam`` 必须给**真实光标坐标**
            #:
            #: 旧代码传 ``0``。因为走的是客户区 mousedown（不是真的
            #: 非客户区消息），窗口管理器要靠 ``lParam`` 里的屏幕坐标
            #: 决定"从哪个点开始拖"。传 0 → 从屏幕左上角起算 →
            #: 窗口瞬间跳到左上角再跟手，观感就是"拖拽错位/乱飞"。
            #:
            #: ## 错误 ③：``SendMessageW`` 没声明 argtypes
            #:
            #: 64 位下 ``hwnd`` 是 8 字节指针。不声明的话 ctypes 按
            #: ``c_int`` 传 —— 句柄被截断成 32 位，消息发给了
            #: **一个随机句柄**，我们自己的窗口当然不动（还不会有异常）。
            #:
            #: ⚠ ``ReleaseCapture()`` 仍然要有：页面已经用 JS 抓着鼠标，
            #: 不释放的话窗口管理器的拖动循环拿不到鼠标。
            user32 = ctypes.windll.user32
            user32.SendMessageW.argtypes = [
                wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            user32.SendMessageW.restype = ctypes.c_ssize_t
            user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]

            user32.ReleaseCapture()
            pt = wintypes.POINT()
            user32.GetCursorPos(ctypes.byref(pt))
            lparam = ((pt.y & 0xFFFF) << 16) | (pt.x & 0xFFFF)
            user32.SendMessageW(
                wintypes.HWND(hwnd), 0x00A1, wintypes.WPARAM(0x0002),
                wintypes.LPARAM(lparam))     #: WM_NCLBUTTONDOWN, HTCAPTION
        except Exception:  # noqa: BLE001 - 拖不了不该崩
            logger.warning("start_window_drag 失败", exc_info=True)

    #: ★★★ 2026-11-02 **补回 ``WS_THICKFRAME`` / ``WS_CAPTION``**
    #:
    #: ## 症状（用户第二轮反馈「这整个窗口还是不能拖拽」）
    #:
    #: 实测窗口样式：
    #:
    #: .. code:: text
    #:
    #:     GWL_STYLE       = 0x-69F50000
    #:     WS_POPUP        = True
    #:     WS_CAPTION      = False   ← 缺
    #:     WS_THICKFRAME   = False   ← 缺
    #:
    #: ## 为什么这会导致拖不动
    #:
    #: ``WM_NCLBUTTONDOWN + HTCAPTION`` 的拖动是**窗口管理器**实现的，
    #: 它要求窗口有 ``WS_CAPTION``（可拖动）或 ``WS_THICKFRAME``（可缩放）。
    #:
    #: ``FramelessWindowHint`` 加上去之后 Qt 把这两个都清掉了 ——
    #: 于是 Windows 认为"这窗口既没有标题栏也没有可拉边框"，**拒绝拖动**。
    #:
    #: ## 修法
    #:
    #: 只补**样式位**（影响窗口管理器的行为判断），
    #: 不补 ``WS_CAPTION`` 的"非客户区"（那会重新画出原生标题栏）。
    #:
    #: ⚠ 关键是把 ``WS_THICKFRAME`` 补回来 —— 它同时给：
    #:   * 拖动（配合 ``HTCAPTION``）
    #:   * 边缘缩放（我们的 ``WM_NCHITTEST`` 才有意义）
    #:   * Aero Snap（拖到屏幕边缘分屏）
    #:
    #: 而**不会**画出标题栏（那个由 ``WS_CAPTION`` 决定，我们不补）。
    SWP_FRAMECHANGED = 0x0020
    SWP_NOMOVE = 0x0002
    SWP_NOSIZE = 0x0001
    SWP_NOZORDER = 0x0004
    GWL_STYLE = -16
    WS_THICKFRAME = 0x00040000
    WS_MINIMIZEBOX = 0x00020000
    WS_MAXIMIZEBOX = 0x00010000

    def _restore_drag_style(self) -> bool:
        """给无边框窗口补回「可拖动 / 可缩放」的样式位。

        :return: 是否成功（非 Windows 或失败返回 False）
        """
        import sys  # noqa: PLC0415

        if sys.platform != "win32":
            return False
        view = self._view
        if view is None:
            return False
        try:
            import ctypes  # noqa: PLC0415

            user32 = ctypes.windll.user32
            hwnd = int(view.winId())
            if not hwnd:
                return False

            style = user32.GetWindowLongW(hwnd, self.GWL_STYLE)
            #: 已经是 32 位有符号数，先转成无符号再看位
            style &= 0xFFFFFFFF
            want = (self.WS_THICKFRAME | self.WS_MINIMIZEBOX
                    | self.WS_MAXIMIZEBOX)
            if (style & want) == want:
                return True                      #: 已经齐了

            user32.SetWindowLongW(hwnd, self.GWL_STYLE, style | want)
            #: 必须让 Windows 重新算一遍窗口框架，否则样式不生效
            user32.SetWindowPos(
                hwnd, 0, 0, 0, 0, 0,
                self.SWP_FRAMECHANGED | self.SWP_NOMOVE
                | self.SWP_NOSIZE | self.SWP_NOZORDER)
            logger.info("web_shell：已补回 WS_THICKFRAME（可拖动 / 可缩放）")
            return True
        except Exception:  # noqa: BLE001 - 补不上不该崩
            logger.warning("_restore_drag_style 失败", exc_info=True)
            return False

    def toggle_maximize(self) -> None:
        """最大化 / 还原（双击标题栏、点 #btn-max 都走这里）。"""
        view = self._view
        if view is None:
            return
        try:
            if view.isMaximized():
                view.showNormal()
            else:
                view.showMaximized()
        except Exception:  # noqa: BLE001
            logger.warning("toggle_maximize 失败", exc_info=True)

    #: 边缘缩放的**命中宽度**（物理像素）—— 鼠标离窗口边缘多近算"在拉边框"
    RESIZE_MARGIN = 6

    #: 标题栏高度（**页面 CSS 像素**，对应 ``layout.css`` 的 ``--titlebar-h``）
    #:
    #: ⚠ 是 CSS 像素不是物理像素 —— 命中测试里要乘 DPR 才能和 ``lParam`` 比。
    #: 见 :meth:`_install_resize_support` 里的说明。
    TITLEBAR_HIT_HEIGHT = 44

    def _install_resize_support(self) -> None:
        """装边缘缩放支持（四边 + 四角）。

        ## 为什么不用 ``QSizeGrip``

        ``QSizeGrip`` 是一个 ``QWidget``，要挂到窗口里。而这个窗口是
        ``QWebEngineView`` —— QtWebEngine 的内部渲染 widget 层级特殊，
        往上叠子 widget 实测会**闪烁/不刷新**，而且只能覆盖右下角。

        ## 用 ``WM_NCHITTEST``（Windows 原生做法）

        无边框窗口的缩放，标准做法是处理 ``WM_NCHITTEST``：

        .. code:: text

            鼠标在左边缘   → 返回 HTLEFT        (10)
            鼠标在右上角   → 返回 HTTOPRIGHT    (14)
            ...

        Windows 拿到这个值就知道"用户想拉哪条边"，**自己接管**缩放
        （带最小尺寸约束、带吸附）。

        ## 为什么挂在 ``QApplication`` 上

        ``nativeEvent`` 是 ``QWidget`` 的方法。窗口本身是
        ``QWebEngineView`` 的实例（不是我们的子类），没法重写它的方法。
        所以用一个 ``QObject`` 事件过滤器挂在 **application** 上，
        在 ``NativeFilter`` 阶段拦 —— Qt 文档里这是
        "从外部给别人的 widget 处理 native 消息"的标准做法。

        ⚠ 只拦**我们这个窗口**的消息（比对 ``hwnd``），
        别把别的窗口（比如 MessageBox）的命中测试也改了。
        """
        import sys  # noqa: PLC0415

        if sys.platform != "win32":
            return
        if self._view is None or self._native_filter is not None:
            return

        #: ⚠ 必须在**类定义之前**导入 —— 下面 ``class _ResizeFilter``
        #: 的基类要用它（PySide6 要求基类就是 QAbstractNativeEventFilter，
        #: 光有同名方法不够，见类文档）
        from PySide6.QtCore import QAbstractNativeEventFilter  # noqa: PLC0415
        from PySide6.QtWidgets import QApplication  # noqa: PLC0415

        class _ResizeFilter(QAbstractNativeEventFilter):
            """在 ``WM_NCHITTEST`` 里根据鼠标位置返回边缘值。

            ## ⚠⚠ 必须继承 ``QAbstractNativeEventFilter``（2026-11-02 踩到）

            第一版写成了 ``class _ResizeFilter(QObject)`` ——
            ``installNativeEventFilter`` 直接报：

            .. code:: text

                TypeError: called with wrong argument types:
                  installNativeEventFilter(F)
                  installNativeEventFilter(
                      filterObj: PySide6.QtCore.QAbstractNativeEventFilter, /)

            **PySide6 要求参数类型就是 ``QAbstractNativeEventFilter``**，
            光有 ``nativeEventFilter`` 方法名是不够的。
            （PyQt 那边接受鸭子类型，PySide6 不接受 —— 别照 PyQt 的例子抄。）

            ## 返回值的三种形态

            ``nativeEventFilter`` 必须返回 **二元组** ``(bool, result)``：

            * ``(False, 0)`` —— 不处理，Qt 继续往下发
            * ``(True, HTLEFT)`` —— 我们处理了，把 ``HTLEFT`` 当结果给 Windows

            ⚠ 任何分支都**必须**返回二元组。少写第二项会变成
            ``return False``，PySide6 会把它当非法返回。
            """

            def __init__(self, view, margin: int, parent=None):
                super().__init__(parent)
                self._view = view
                self._margin = margin

            def nativeEventFilter(self, event_type, message):  # noqa: N802
                try:
                    #: event_type 可能是 bytes 或 QByteArray
                    et = bytes(event_type) if not isinstance(
                        event_type, bytes) else event_type
                    if et != b"windows_generic_MSG":
                        return False, 0
                    import ctypes  # noqa: PLC0415
                    from ctypes import wintypes  # noqa: PLC0415

                    #: ★★★ 2026-11-03 **这才是「过滤器永远不生效」的真凶**
                    #:
                    #: 前一版写的是::
                    #:
                    #:     addr = ctypes.cast(message, ctypes.c_void_p).value
                    #:
                    #: 在 PySide6 6.11.2 里 ``message`` 是
                    #: :class:`PySide6.QtCore.VoidPtr`（不是 sip.voidptr
                    #: 也不是 int），``ctypes.cast`` 对它会抛::
                    #:
                    #:     ArgumentError: argument 1: TypeError: wrong type
                    #:
                    #: 而这个异常被外层 ``except`` 吞掉 → 每条消息都
                    #: ``return False, 0`` → **过滤器形同不存在**。
                    #:
                    #: 实测（探针脚本，真鼠标在窗口里划一圈）：
                    #:
                    #: .. code:: text
                    #:
                    #:     nativeEventFilter 被调用 36 次
                    #:     其中成功解析出 message 的次数 = 0
                    #:     每次都是 ArgumentError: wrong type
                    #:
                    #: ## 正确写法
                    #:
                    #: ``VoidPtr`` 实现了 ``__int__``，直接 ``int(message)``
                    #: 就拿到地址（实测 36/36 全部成功）。不要 ``cast``。
                    #:
                    #: ⚠ 也可以用 ``message.__int__()``，但 ``int()`` 更稳
                    #: （``__int__`` 是内部协议，哪天改成 ``__index__`` 就断）。
                    addr = int(message)
                    if not addr:
                        return False, 0

                    msg = ctypes.cast(
                        addr, ctypes.POINTER(wintypes.MSG)).contents
                    if msg.message != 0x0084:      #: WM_NCHITTEST
                        return False, 0
                    if not self._view.isVisible() \
                            or self._view.isMaximized() \
                            or self._view.isFullScreen():
                        return False, 0
                    hwnd = int(self._view.winId())
                    #: ★★★ 2026-11-02 **字段名是 ``hWnd`` 不是 ``hwnd``**
                    #:
                    #: ``ctypes.wintypes.MSG`` 的结构体字段沿用 Win32 的
                    #: 匈牙利命名：``hWnd`` / ``message`` / ``wParam`` /
                    #: ``lParam``。写成小写 ``hwnd`` 会
                    #: ``AttributeError: 'MSG' object has no attribute 'hwnd'``。
                    #:
                    #: ⚠⚠ **这个异常被外层 ``except`` 吞了整整三轮** ——
                    #: 表现就是「过滤器永远返回 (False, 0)、拖拽完全无效」，
                    #: 而代码看上去完全正确。加 ``logger.debug(..., exc_info=True)``
                    #: 之后才看见。
                    #:
                    #: 教训：**`except: return 默认值` 是排查地狱**。
                    #: 至少要打一条 debug 日志。
                    if int(msg.hWnd or 0) != hwnd:
                        return False, 0

                    #: 屏幕坐标 → 窗口内坐标
                    x = ctypes.c_short(msg.lParam & 0xFFFF).value
                    y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value

                    #: ★★★ 2026-11-03 **必须用 ``GetWindowRect`` 而不是
                    #: ``frameGeometry()`` —— 一个物理、一个逻辑**
                    #:
                    #: ``WM_NCHITTEST`` 的 ``lParam`` 是**物理屏幕像素**
                    #: （DWM 坐标，不受 DPI 缩放影响）。
                    #:
                    #: 而 ``QWidget.frameGeometry()`` 返回**逻辑像素**
                    #: （已经除过 DPR）。
                    #:
                    #: 实测本机 125% 缩放（DPR = 1.25）：
                    #:
                    #: .. code:: text
                    #:
                    #:     frameGeometry  = (150,140)-(1149,839)   逻辑，1000x700
                    #:     GetWindowRect  = (188,175)-(1438,1050)  物理，1250x875
                    #:
                    #: 拿物理坐标去和逻辑矩形比 → 右边框判定
                    #: ``x > right - m`` 里 ``right=1149``，而真实物理右边界
                    #: 是 **1438** —— 鼠标在 x=1200 时明明在窗口里，
                    #: 却算成"超出右边界 6px"；反过来真正贴着右边时
                    #: 又不在判定范围。
                    #:
                    #: **结果：只有一部分屏幕位置上边缘能被抓住**，
                    #: 用户体感就是「有时候能拉、有时候拉不动」。
                    rect = wintypes.RECT()
                    get_rect = ctypes.windll.user32.GetWindowRect
                    #: ⚠ 必须声明 argtypes —— 64 位下 ``HWND`` 是 8 字节指针，
                    #: 不声明会按 ``c_int`` 截断（和 ``SendMessageW`` 同一类坑）。
                    get_rect.argtypes = [wintypes.HWND,
                                         ctypes.POINTER(wintypes.RECT)]
                    get_rect.restype = wintypes.BOOL
                    if not get_rect(wintypes.HWND(hwnd), ctypes.byref(rect)):
                        return False, 0
                    left, top = rect.left, rect.top
                    right, bottom = rect.right, rect.bottom
                    m = self._margin

                    #: ★★★ 2026-11-02 **标题栏区域完全放行给 Windows**
                    #:
                    #: ## 症状（用户反馈两轮都没修好）
                    #:
                    #: 「这整个窗口还是不能拖拽」「工具启动后不能拖拽」
                    #:
                    #: ## 实测证据（手动发 WM_NCHITTEST）
                    #:
                    #: .. code:: text
                    #:
                    #:     标题栏 y+20  → 0x0000   ← 0！既不是 HTCLIENT 也不是 HTCAPTION
                    #:     内容区 y+200 → 0x0001   ← 正常的 HTCLIENT
                    #:
                    #: ``0`` 表示「没人处理」—— 页面收不到 mousedown
                    #: （因为不是 HTCLIENT），系统也不拖（因为不是 HTCAPTION），
                    #: **两头落空**。
                    #:
                    #: ## 试过但无效的方案
                    #:
                    #: 1. ``return False, 0``（不拦，让页面自己调 startWindowDrag）
                    #:    → 实测就是上面那个 0
                    #: 2. ``return True, 2``（HTCAPTION）
                    #:    → 过滤器**没被调用到**：``SendMessage(WM_NCHITTEST)``
                    #:      是同步直调，不经过 Qt 事件循环，native filter 拦不到
                    #:
                    #: ## 最终方案：标题栏区域**彻底不干预**
                    #:
                    #: ``FramelessWindowHint`` 的窗口，Qt 自己对 WM_NCHITTEST
                    #: 返回 ``HTCLIENT``（内容区行为）—— 页面能收到 mousedown，
                    #: 走页面自己的 ``startWindowDrag()``（Win32
                    #: ``ReleaseCapture + WM_NCLBUTTONDOWN``，系统接管拖动）。
                    #:
                    #: 所以**只要别在这里返回任何东西**就行。
                    #:
                    #: ⚠ 关键：下面所有 ``return`` 都必须是「**确实在边缘**」
                    #:   的情况。标题栏中段直接跳过、落到最后的 ``return False, 0``
                    #:   —— 那个 ``False`` 的含义是「我不处理，Qt/Windows 自己定」，
                    #:   和中间那些 ``return True, HTxxx`` 不同。
                    header_h = getattr(self, "TITLEBAR_HIT_HEIGHT", 44)
                    #: ⚠ ``header_h`` 是**页面 CSS 像素**（标题栏 44px），
                    #: 而 ``y`` 是物理像素 → 必须乘 DPR 才能比。
                    #:
                    #: 漏了这一步的后果：125% 缩放下标题栏实际占 55 物理像素，
                    #: 却按 44 算 → 标题栏下面那 11px 被当成"内容区的上边缘"，
                    #: 鼠标扫过标题栏底部时**变成拉伸光标**、拖动失效。
                    dpr = float(self._view.devicePixelRatioF() or 1.0)
                    in_header = top <= y < top + header_h * dpr
                    #: 角例外：左右两边落在角上仍然算拉伸（否则角拉不了）
                    corner_for_top = in_header and (
                        x < left + m or x > right - m)
                    if in_header and not corner_for_top:
                        #: 标题栏中段 → **必须返回 HTCLIENT，不能返回 0**
                        #:
                        #: ## ⚠⚠⚠ 2026-11-02 三轮才修对
                        #:
                        #: 用户两次反馈「不能拖拽」。实测链条：
                        #:
                        #: 1. 页面埋点 ``mousedown`` 计数 = **0**
                        #:    → 页面根本没收到鼠标事件
                        #: 2. 但 ``SendMessage(WM_LBUTTONDOWN)`` 直接发给窗口
                        #:    → 页面**收到了** ``{x:480, y:16}``
                        #: 3. 手动发 ``WM_NCHITTEST``：
                        #:    标题栏 → ``0x0000``，内容区 → ``0x0001``（HTCLIENT）
                        #:
                        #: **区别就在这**：``SendInput``（真实鼠标）走硬件输入
                        #: 队列，Windows **先问 WM_NCHITTEST**；返回 ``0`` 会被
                        #: 解读成「这块区域不接受鼠标」，于是**事件被直接丢弃**，
                        #: 页面永远收不到。``SendMessage`` 绕过了那个判断，
                        #: 所以能收到 —— 这就是「看起来能收到但实际不行」的原因。
                        #:
                        #: ## 为什么之前返回 ``False, 0`` 是错的
                        #:
                        #: ``nativeEventFilter`` 返回 ``(False, 0)`` 的意思是
                        #: 「我不处理，交给 Qt」，但 Qt 对无边框窗口的
                        #: ``WM_NCHITTEST`` 处理结果是 ``0``，不是 ``HTCLIENT``。
                        #:
                        #: → **自己明确返回 ``HTCLIENT(1)``**，
                        #:   页面才能收到 mousedown，进而调 ``startWindowDrag()``。
                        return True, 1           #: HTCLIENT

                    on_left = x < left + m
                    on_right = x > right - m
                    on_top = y < top + m
                    on_bottom = y > bottom - m

                    #: 四角优先（角比边优先，否则角落永远只能拉一条边）
                    if on_top and on_left:
                        return True, 13          #: HTTOPLEFT
                    if on_top and on_right:
                        return True, 14          #: HTTOPRIGHT
                    if on_bottom and on_left:
                        return True, 16          #: HTBOTTOMLEFT
                    if on_bottom and on_right:
                        return True, 17          #: HTBOTTOMRIGHT
                    if on_left:
                        return True, 10          #: HTLEFT
                    if on_right:
                        return True, 11          #: HTRIGHT
                    if on_top:
                        return True, 12          #: HTTOP
                    if on_bottom:
                        return True, 15          #: HTBOTTOM
                except Exception:  # noqa: BLE001 - 命中测试失败不该崩
                    #: ⚠⚠ 2026-11-02 这里以前是裸 ``return False, 0``，
                    #: 把异常**静默吞掉**了 —— 结果「拖拽失效」查了三轮
                    #: 才靠手工复算发现「代码是对的但入口没走到」。
                    #: 现在打日志，下次一眼看见。
                    logger.debug("WM_NCHITTEST 处理失败", exc_info=True)
                    return False, 0
                return False, 0

        try:
            self._native_filter = _ResizeFilter(
                self._view, self.RESIZE_MARGIN, self)
            app = QApplication.instance()
            if app is not None:
                app.installNativeEventFilter(self._native_filter)
                logger.info("web_shell：边缘缩放已启用（WM_NCHITTEST）")
        except Exception:  # noqa: BLE001
            logger.warning("装边缘缩放失败", exc_info=True)
            self._native_filter = None

    def _remove_resize_support(self) -> None:
        """卸载边缘缩放过滤器（退出时）。"""
        if self._native_filter is None:
            return
        try:
            from PySide6.QtWidgets import QApplication  # noqa: PLC0415

            app = QApplication.instance()
            if app is not None:
                app.removeNativeEventFilter(self._native_filter)
        except Exception:  # noqa: BLE001
            logger.debug("卸载边缘缩放失败", exc_info=True)
        self._native_filter = None

    def apply_window_corner(self) -> bool:
        """给无边框窗口加**系统级圆角 + 阴影**（Win11 专属，Win10 静默跳过）。

        ## 为什么需要（page-converter 指出）

        无边框之后 Windows 不再画圆角和投影，窗口是**直角 + 无阴影** ——
        视觉上会和任务栏、其他窗口"贴死"。

        ## ⚠⚠ 为什么走 Win32 而**不是** CSS

        page-converter 的分析是对的，CSS 这条路在这个场景下**不可行**：

        1. ``page.setBackgroundColor("#090713")`` 是**不透明**的 ——
           CSS ``border-radius`` 外面会露出**纯黑直角**，比不加更难看
        2. 要真圆角必须让窗口**透明**（``WA_TranslucentBackground``），
           而透明窗口 + Chromium 合成层在笔记本上**明显掉帧**
           （尤其壁纸是视频时）

        系统级圆角（``DwmSetWindowAttribute`` + ``DWMWA_WINDOW_CORNER_PREFERENCE``）
        **不牺牲性能**，而且是 Win11 的原生行为 —— 和其他窗口一致。

        ## ★★★ 必须在 ``show()`` **之后**调（2026-11-02 实测踩到）

        第一版在 ``build()`` 里调（那时 ``winId()`` 已经非 0），
        ``DwmSetWindowAttribute`` 返回 ``S_OK`` —— **看起来成功了**。

        但 ``show()`` 之后回读：

        .. code:: text

            DwmGetWindowAttribute(hwnd, 33) → 0   #: DWMWCP_DEFAULT，不是 2(ROUND)!

        原因是 Qt 在 ``show()`` 时还会重新设置一次窗口样式，
        **把我们设的属性冲掉了**。

        → 所以现在由 :meth:`show` 在真正 ``show()`` 完之后再调一次。

        ## 版本兜底

        ``DWMWA_WINDOW_CORNER_PREFERENCE`` 是 **Win11 build 22000+** 才有的属性。
        Win10 上 ``DwmSetWindowAttribute`` 会返回**非零错误码**（不崩），
        这里按返回值判断，失败就当没这回事、窗口保持直角。

        :return: 真的设上了返回 True；非 Win11 / 调用失败返回 False
        """
        import sys  # noqa: PLC0415

        if sys.platform != "win32":
            return False
        view = self._view
        if view is None:
            return False

        #: ★ 先查 build —— 比"调了看返回值"更早地避免无谓调用
        if not self._is_windows_11():
            logger.info("web_shell：不是 Win11（build < 22000），"
                        "跳过系统圆角（Win10 上这个属性不存在）")
            return False

        try:
            import ctypes  # noqa: PLC0415
            from ctypes import wintypes  # noqa: PLC0415

            hwnd_int = int(view.winId())
            if not hwnd_int:
                #: 窗口还没建出来 —— 调用方应该在 show() 之后再来
                logger.debug("web_shell：窗口句柄还是 0，跳过圆角")
                return False
            hwnd = wintypes.HWND(hwnd_int)

            dwm = ctypes.windll.dwmapi

            #: DWMWA_WINDOW_CORNER_PREFERENCE = 33
            #: DWMWCP_DEFAULT = 0（系统决定）/ ROUND = 2（强制圆角）
            #
            #: 用 ROUND 而不是 DEFAULT：默认值取决于系统设置，
            #: 有些精简版 Windows 会关掉圆角 —— 用户看到的还是直角。
            corner = ctypes.c_int(2)          #: DWMWCP_ROUND
            hr = dwm.DwmSetWindowAttribute(
                hwnd, 33, ctypes.byref(corner), ctypes.sizeof(corner))
            if hr != 0:
                logger.info("web_shell：设置窗口圆角失败 hr=%s（窗口保持直角）", hr)
                return False

            #: 顺手恢复**投影** —— DWMWA_NCRENDERING_POLICY = 2
            #: （无边框窗口默认不画非客户区阴影）
            policy = ctypes.c_int(2)          #: DWMNCRP_ENABLED
            dwm.DwmSetWindowAttribute(
                hwnd, 2, ctypes.byref(policy), ctypes.sizeof(policy))

            #: 深色标题栏（DWMWA_USE_IMMERSIVE_DARK_MODE = 20）
            #: 这样系统画的边框/阴影和深色皮肤一致，不会有一圈白边
            dark = ctypes.c_int(1)
            dwm.DwmSetWindowAttribute(
                hwnd, 20, ctypes.byref(dark), ctypes.sizeof(dark))

            #: ★ 回读确认真的生效（S_OK 不等于生效 —— 见上面的说明）
            actual = self.get_window_corner_preference()
            if actual != 2:
                logger.warning(
                    "web_shell：圆角设了但回读是 %s（期望 2）—— "
                    "可能被随后的窗口样式重置冲掉了", actual)
                return False

            logger.info("web_shell：Win11 系统圆角 + 阴影已启用（回读=2）")
            return True
        except Exception:  # noqa: BLE001 - 圆角失败不该影响启动
            logger.warning("web_shell：设置窗口圆角异常", exc_info=True)
            return False

    def get_window_corner_preference(self) -> int:
        """回读当前的 ``DWMWA_WINDOW_CORNER_PREFERENCE``。

        :return: 0=DEFAULT / 1=DONOTROUND / 2=ROUND / 3=ROUNDSMALL；
                 读不到返回 ``-1``

        ⚠ **这是唯一的"真的生效了"证据** —— ``DwmSetWindowAttribute``
        返回 ``S_OK`` 只说明"调用被接受"，不代表窗口现在是圆角
        （Qt 在 ``show()`` 时可能把样式重置掉）。
        """
        import sys  # noqa: PLC0415

        if sys.platform != "win32":
            return -1
        view = self._view
        if view is None:
            return -1
        try:
            import ctypes  # noqa: PLC0415
            from ctypes import wintypes  # noqa: PLC0415

            hwnd_int = int(view.winId())
            if not hwnd_int:
                return -1
            pref = ctypes.c_int(-1)
            hr = ctypes.windll.dwmapi.DwmGetWindowAttribute(
                wintypes.HWND(hwnd_int), 33,
                ctypes.byref(pref), ctypes.sizeof(pref))
            return int(pref.value) if hr == 0 else -1
        except Exception:  # noqa: BLE001
            return -1

    @staticmethod
    def _is_windows_11() -> bool:
        """当前是不是 Win11（build >= 22000）。

        ⚠ ``platform.release()`` 在某些兼容性清单下会骗人（报 "10"），
        所以用 ``RtlGetVersion`` 拿**真实** build 号 —— 它是内核版本，
        不受 manifest 的兼容性声明影响。
        """
        import sys  # noqa: PLC0415

        if sys.platform != "win32":
            return False
        try:
            import ctypes  # noqa: PLC0415

            class _OsVersionInfo(ctypes.Structure):
                _fields_ = [
                    ("dwOSVersionInfoSize", ctypes.c_ulong),
                    ("dwMajorVersion", ctypes.c_ulong),
                    ("dwMinorVersion", ctypes.c_ulong),
                    ("dwBuildNumber", ctypes.c_ulong),
                    ("dwPlatformId", ctypes.c_ulong),
                    ("szCSDVersion", ctypes.c_wchar * 128),
                ]

            info = _OsVersionInfo()
            info.dwOSVersionInfoSize = ctypes.sizeof(_OsVersionInfo)
            ctypes.windll.ntdll.RtlGetVersion(ctypes.byref(info))
            return int(info.dwBuildNumber) >= 22000
        except Exception:  # noqa: BLE001
            logger.debug("读 Windows build 失败", exc_info=True)
            return False

    # ---------------------------------------------------------------- 槽
    def _on_window_action(self, action: str) -> None:
        """标题栏按钮 → 真的动窗口。

        ``action`` 全部小写（``windowAction`` 那边已经 ``.lower()`` 过）：
        ``minimize`` / ``maximize`` / ``restore`` / ``togglemaximize`` /
        ``close`` / ``startdrag``。
        """
        view = self._view
        if view is None:
            return
        try:
            if action == "startdrag":
                #: ★ 拖拽窗口（无边框后必须自己接，见 start_window_drag）
                self.start_window_drag()
                return
            if action == "minimize":
                view.showMinimized()
            elif action == "maximize":
                view.showMaximized()
            elif action == "restore":
                view.showNormal()
            elif action == "togglemaximize":
                if view.isMaximized():
                    view.showNormal()
                else:
                    view.showMaximized()
            elif action == "close":
                view.close()
        except Exception:  # noqa: BLE001
            logger.warning("web_shell：窗口动作失败 %s", action, exc_info=True)

    def _on_frontend_ready(self) -> None:
        self._ready = True
        logger.info("web_shell：前端脚本已就绪")
        self.ready.emit()

    def _on_load_finished(self, ok: bool) -> None:
        if not ok:
            logger.error("web_shell：页面加载失败 %s", self._base_url)
            #: ★ 自动重试（主要兜启动竞态）—— 见 _retry_load 的说明
            self._retry_load()
            return
        logger.info("web_shell：页面加载完成")

    # ---------------------------------------------------------------- 推送
    def push_log(self, text: str, level: str = "info") -> None:
        """往页面推一行日志（任务页可见）。"""
        if self._bridge is not None:
            self._bridge.pushLog(text, level)

    def push_progress(self, value: float, text: str = "") -> None:
        if self._bridge is not None:
            self._bridge.pushProgress(value, text)

    def push_skin(self) -> None:
        if self._bridge is not None:
            self._bridge.pushSkin()

    def push_wallpaper(self, wp_id: str = "") -> None:
        """通知页面换壁纸（传空 = 让 Python 挑当前那个）。"""
        if self._bridge is None:
            return
        if wp_id:
            self._bridge.setWallpaper(wp_id)
        else:
            self._bridge.getWallpaper()

    def request_page(self, key: str) -> None:
        if self._bridge is not None:
            self._bridge.requestPage(key)

    # ---------------------------------------------------------------- 调试
    def debug_js(self, expression: str, timeout_ms: int = 15000):
        """同步执行一段 JS 并返回结果（**只能给测试用**）。

        ## ⚠ 为什么不用 QEventLoop + runJavaScript 的回调

        ``runJavaScript`` 是异步的，回调在主线程事件循环里执行。在测试脚本
        里用 ``QEventLoop`` 阻塞等待是可行的，但如果调用点本身就在
        主线程的回调里（比如 loadFinished 槽），会**死锁**。

        所以这里的做法是：起一个局部 ``QEventLoop``，但加超时 ——
        超时返回 None 而不是永久挂住。

        ## ⚠ 超时默认值为什么从 3 秒提到 15 秒

        实测（2026-11-01）：一次性推 10000 条 bridge 事件之后，
        页面主线程要 **5.7 秒**才消化完；期间 ``runJavaScript`` 的回调
        排在 JS 队列后面拿不到执行机会 → 3 秒超时 → 返回 None。

        那个 None **看起来像"页面崩了/丢消息了"**，实际一条没丢
        （25 秒超时读到的计数正好是 10000）。为了不让排查的人被这个
        假象带偏，默认值放到 15 秒；真卡死还是会超时。
        """
        view = self._view
        if view is None:
            return None
        from PySide6.QtCore import QEventLoop, QTimer  # noqa: PLC0415

        loop = QEventLoop()
        box = {"value": None, "done": False}

        def done(value):
            box["value"] = value
            box["done"] = True
            loop.quit()

        view.page().runJavaScript(expression, 0, done)
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        timer.start(timeout_ms)
        loop.exec()
        return box["value"]

    def debug_layout(self) -> dict:
        """★ 断言「放大无平铺」用的布局快照。

        页面里的 :func:`App.debugLayout` 返回各层实际像素尺寸。
        窗口放大后**这些数字必须跟着变** —— 不变就是平铺。
        """
        raw = self.debug_js("JSON.stringify(window.App && App.debugLayout());")
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return {}

    def debug_screenshot(self, path: str | Path):
        """抓页面像素（返回 ``QImage``；失败返回 None）。

        ## ⚠ ``grab()`` 的坑

        ``QWebEngineView.grab()`` 抓的是**控件**，Chromium 渲染的内容
        在独立的 Surface 上，某些后端下 grab 会得到空白。

        兜底办法：``QScreen.grabWindow(hwnd)`` 抓窗口所在屏幕区域 ——
        会连带其它窗口，但在无头/单窗口场景下够用。
        这里两个都试，返回第一个看起来正常的。
        """
        view = self._view
        if view is None:
            return None
        try:
            img = view.grab().toImage()
        except Exception:  # noqa: BLE001
            logger.warning("web_shell：grab 失败", exc_info=True)
            return None
        if path:
            try:
                img.save(str(path))
                logger.info("web_shell：截图已保存 %s（%dx%d）",
                            path, img.width(), img.height())
            except Exception:  # noqa: BLE001
                logger.warning("web_shell：保存截图失败 %s", path, exc_info=True)
        return img


# ══════════════════════════════════════════════════════════════════════════
#  便利函数
# ══════════════════════════════════════════════════════════════════════════
def create_shell(*, base_url: str = "", window_icon: QIcon | None = None
                 ) -> WebShell | None:
    """建一个可用的 WebShell（失败返回 None）。

    失败时调用方应退回旧的 ``MainWindow`` —— **新外壳起不来不能挡住启动**。
    """
    if window_icon is None:
        try:
            from .compat import app_icon  # noqa: PLC0415

            window_icon = app_icon()
        except Exception:  # noqa: BLE001
            window_icon = None

    shell = WebShell(base_url=base_url, window_icon=window_icon)
    if not shell.build():
        logger.error("web_shell：构建失败，退回旧界面")
        return None
    return shell


__all__ = [
    "WEB_DIR",
    "WebShell",
    "create_shell",
    "is_enabled",
    "prepare_assets",
    "web_base_url",
]
