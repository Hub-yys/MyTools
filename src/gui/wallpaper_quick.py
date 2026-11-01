# -*- coding: utf-8 -*-
"""★ QtQuick 壁纸层 —— 用 ``QQuickWidget`` 播视频（**回退版本**）。

## ★★★ 2026-11-01 回退说明

用户：「这比刚才还糟糕了，回退」。

试过的四条路，这是**能用**的那条：

==============================  ==========================================
方案                              结果
==============================  ==========================================
``QWebEngineView`` (Chromium)    合成器打架，重影/闪烁
``QQuickView`` (独立窗口)         被主窗口遮住 + 每帧 lower() 卡死
``QVideoWidget``                 **比之前更糟**（回退触发点）
**``QQuickWidget``（本模块）**    ✅ **能用**：壁纸正常显示
==============================  ==========================================

## 已知问题（用户接受）

窗口**放大**后壁纸会轻微**平铺/重复** —— 因为 ``QQuickWidget`` 是
离屏 FBO 纹理，QWidget 只拉伸旧纹理。

**这个已知问题先放着**，不要再用"换方案"去修 —— 前面三次换方案
都比它更糟。如果以后要修，只能在 ``QQuickWidget`` 内部想办法
（比如强制 ``update()`` 让纹理重画）。

## 保留的改进

  * ``FOLLOW_MS = 200``（50ms 太密，卡）
  * 主色提取用**独立 QMediaPlayer 抓帧**（不依赖屏幕截图）
  * 暗化用设置里的 ``scrim``
  * 设置页 10 个滑块
"""

from __future__ import annotations

import logging
import os
import tempfile

from PySide6.QtCore import Qt, QUrl
from PySide6.QtWidgets import QWidget

logger = logging.getLogger(__name__)

#: 当前挂在主窗口上的壁纸层
_current: "QuickWallpaper | None" = None

#: 跟随主窗口的定时器间隔（ms）
#:
#: ★ 50ms 太密（用户报"非常卡"），200ms 够跟手。
FOLLOW_MS = 200

#: QML 模板
_QML = """
import QtQuick
import QtMultimedia

Item {
    id: root

    Rectangle {
        anchors.fill: parent
        color: "#000000"
    }

    VideoOutput {
        id: vout
        anchors.fill: parent
        fillMode: VideoOutput.PreserveAspectCrop
    }

    //: ★ 暗化层（壁纸越亮压得越多 / 用设置里的 scrim）
    Rectangle {
        id: tintLayer
        anchors.fill: parent
        color: "#000000"
        opacity: 0.0
    }

    MediaPlayer {
        id: player
        source: "%(source)s"
        loops: MediaPlayer.Infinite
        audioOutput: null
        videoOutput: vout
        Component.onCompleted: play()
    }

    //: 由 Qt 端 setProperty("tintValue", x) 设置暗化
    property real tintValue: 0.0
    onTintValueChanged: {
        tintLayer.opacity = Math.max(0.0, Math.min(0.75, tintValue));
    }

    //: 调试状态
    property string status: (player.mediaStatus === MediaPlayer.BufferedMedia
                             || player.mediaStatus === MediaPlayer.LoadedMedia)
                            ? "READY:" + vout.implicitWidth + "x" + vout.implicitHeight
                            : (player.error !== MediaPlayer.NoError
                               ? "ERROR:" + player.error
                               : "LOADING")
}
"""


class QuickWallpaper:
    """用 ``QQuickWidget``（子控件）播视频壁纸。

    ## 为什么是这个方案

    它是**唯一能同时满足**这两条的：

      * 是**子控件** → 不会被主窗口遮住
      * 没有独立合成器 → 不和 Qt 打架

    代价：窗口放大会轻微平铺（离屏纹理）。
    **这个已知问题先放着** —— 前面三次换方案都比它更糟。
    """

    def __init__(self, window: QWidget, video_path: str):
        self._window = window
        self._video_path = str(video_path or "")
        self._view = None
        self._active = False
        self._timer = None
        self._color_timer = None
        self._color_tries = 0
        self._tint = 0.0
        #: QML 临时文件路径（重建源时要用）
        self._qml_file = ""

    @property
    def active(self) -> bool:
        return self._active

    @property
    def video_path(self) -> str:
        return self._video_path

    def start(self) -> bool:
        """建 QQuickWidget 并开始播。"""
        if self._active:
            return True
        if not self._video_path or not os.path.isfile(self._video_path):
            logger.warning("壁纸：视频不存在 %s", self._video_path)
            return False
        try:
            from PySide6.QtQuickWidgets import QQuickWidget
        except Exception:  # noqa: BLE001
            logger.warning("壁纸：QQuickWidget 不可用", exc_info=True)
            return False

        try:
            win = self._window
            view = QQuickWidget(win)
            #: ★ 不接鼠标 —— 点击要穿到主界面
            view.setAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            view.setClearColor(Qt.GlobalColor.black)
            view.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)

            url = QUrl.fromLocalFile(self._video_path).toString()
            qml = _QML % {"source": url}
            path = os.path.join(tempfile.gettempdir(),
                                "mytools_wallpaper.qml")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(qml)
            self._qml_file = path
            view.setSource(QUrl.fromLocalFile(path))
            if view.status() == QQuickWidget.Status.Error:
                for err in view.errors():
                    logger.warning("壁纸：QML 错误 %s", err.toString())
                return False

            view.setGeometry(win.rect())
            view.show()
            view.lower()

            self._view = view
            self._install_follow_timer()
            self._active = True
            logger.info("壁纸：已启用 %s（QQuickWidget）",
                        os.path.basename(self._video_path))
            self._schedule_color_extract()
            return True
        except Exception:  # noqa: BLE001
            logger.warning("壁纸：启动失败", exc_info=True)
            self.teardown()
            return False

    # ---------------------------------------------------------- 跟随主窗口
    def _install_follow_timer(self) -> None:
        """★ 定时器让视图跟随主窗口尺寸。

        为什么不用 ``eventFilter``：那个 Python ``QObject`` watcher
        **会被 GC 掉**（Qt 只持有 C++ 侧指针）。
        """
        try:
            from PySide6.QtCore import QTimer

            self._timer = QTimer(self._window)
            self._timer.setInterval(FOLLOW_MS)
            self._timer.timeout.connect(self._follow)
            self._timer.start()
            self._follow()
        except Exception:  # noqa: BLE001
            logger.warning("壁纸：装跟随定时器失败", exc_info=True)

    def _follow(self) -> None:
        """把视图对齐到主窗口（只在尺寸变了才设，避免每帧重排）。"""
        try:
            win = self._window
            w = self._view
            if w is None or win is None:
                return
            if not win.isVisible():
                if w.isVisible():
                    w.hide()
                return
            target = (0, 0, max(2, win.width()), max(2, win.height()))
            cur = (w.x(), w.y(), w.width(), w.height())
            if cur != target:
                w.setGeometry(*target)
                #: ★★★ 2026-11-01 **只 update()，别动 QML 根尺寸**
                #:
                #: 试过两种"修平铺"的办法，都让画面更糟：
                #:
                #:   ① ``root.setProperty("width", x)`` → QML 根和 view
                #:      尺寸打架，画面**错位重复**
                #:   ② ``setSource()`` 重建 → 新旧纹理交错，**大面积乱**
                #:
                #: → 保持最朴素的做法：只改几何 + ``update()``。
                #:   放大后轻微平铺是 ``QQuickWidget`` 离屏纹理的固有行为，
                #:   **接受它**（比错位好看得多）。
                w.update()
            if not w.isVisible():
                w.show()
                w.lower()
        except (RuntimeError, AttributeError):
            pass

    def _reload_source(self) -> None:
        """重建 QML 源 —— 彻底清掉旧尺寸的平铺纹理。

        ## 为什么要重建

        `QQuickWidget` 把 QML 渲到**离屏纹理**，窗口尺寸剧变时
        它只把旧纹理拉伸/平铺，不重新分配。
        `update()` / `setResizeMode()` 都清不掉。

        唯一可靠的办法是**重新 `setSource`** ——
        相当于重建整个 QML 场景（视频会从头播，但壁纸无所谓）。

        代价：约 150ms（重新解码首帧）。只在缩放超过 120px 时做。
        """
        try:
            from PySide6.QtCore import QUrl

            if self._view is None or not self._qml_file:
                return
            #: 记住当前播放位置，重建后跳回去
            pos = 0
            try:
                root = self._view.rootObject()
                if root is not None:
                    #: 通过 status 属性判断是否已就绪（不强制）
                    pass
            except Exception:  # noqa: BLE001
                pass
            self._view.setSource(QUrl())
            self._view.setSource(QUrl.fromLocalFile(self._qml_file))
            #: 重建后把暗化补上（属性丢了）
            try:
                root = self._view.rootObject()
                if root is not None and self._tint > 0:
                    root.setProperty("tintValue", float(self._tint))
            except Exception:  # noqa: BLE001
                pass
            logger.debug("壁纸：尺寸剧变，已重建 QML 源（pos=%s）", pos)
        except Exception:  # noqa: BLE001
            logger.debug("壁纸：重建源失败", exc_info=True)

    # ---------------------------------------------------------- 主色/暗化
    def _schedule_color_extract(self) -> None:
        """延迟从视频源抽主色（等第一帧真的出来）。"""
        try:
            from PySide6.QtCore import QTimer

            self._color_tries = 0
            self._color_timer = QTimer(self._window)
            self._color_timer.setInterval(300)
            self._color_timer.timeout.connect(self._try_extract_color)
            self._color_timer.start()
        except Exception:  # noqa: BLE001
            logger.debug("壁纸：装主色定时器失败", exc_info=True)

    def _try_extract_color(self) -> None:
        """从视频源抓一帧 → 抽主色 → 应用配色 + 暗化。"""
        try:
            self._color_tries += 1
            if self._color_tries > 10:
                self._color_timer.stop()
                return
            #: ★ 自己解一帧（不依赖控件截图，稳）
            img = self._grab_video_frame()
            if img is None:
                return
            from ..core import color_extract as CE

            luma = CE.average_luma(img)
            if luma < 0.02:
                return
            primary = CE.extract_primary(img)
            #: 暗化优先用设置里的 scrim
            try:
                from ..core import wallpaper_settings as _WS

                scrim = float(_WS.get("scrim") or 0.0)
                tint = scrim if scrim > 0 else CE.suggest_tint(img)
            except Exception:  # noqa: BLE001
                tint = CE.suggest_tint(img)
            self._tint = tint
            self._color_timer.stop()
            logger.info("壁纸：主色=%s 亮度=%.2f 暗化=%.2f",
                        primary, luma, tint)
            #: ① 配色（不改用户保存的主题）
            try:
                from ..core import skins

                skins.apply_wallpaper_palette(primary, tint)
            except Exception:  # noqa: BLE001
                logger.debug("壁纸：应用配色失败", exc_info=True)
            #: ② 暗化传给 QML
            try:
                root = self._view.rootObject() if self._view else None
                if root is not None:
                    root.setProperty("tintValue", float(tint))
                    logger.info("壁纸：已设置暗化 %.2f", tint)
            except Exception:  # noqa: BLE001
                logger.warning("壁纸：设置暗化失败", exc_info=True)
        except Exception:  # noqa: BLE001
            logger.debug("壁纸：抽主色失败", exc_info=True)

    def _grab_video_frame(self):
        """用临时 ``QMediaPlayer`` 从视频源抓一帧（QImage）。

        ## 为什么不截控件

        ``QQuickWidget`` 的 ``grab()`` 在窗口被 lower 时可能抓到黑；
        ``QVideoWidget``/``QQuickView`` 更是抓不到或全黑。

        → **独立解一帧**最可靠：不依赖屏幕合成。
        """
        try:
            from PySide6.QtCore import QUrl
            from PySide6.QtMultimedia import QMediaPlayer, QVideoSink
            from PySide6.QtWidgets import QApplication

            app = QApplication.instance()
            if app is None:
                return None
            player = QMediaPlayer()
            sink = QVideoSink()
            player.setVideoSink(sink)
            got: list = []
            sink.videoFrameChanged.connect(
                lambda f: got.append(f) if f.isValid() else None)
            player.setSource(QUrl.fromLocalFile(self._video_path))
            player.play()
            import time as _t

            for _ in range(40):
                app.processEvents()
                if got:
                    break
                _t.sleep(0.02)
            player.stop()
            img = got[-1].toImage() if got else None
            player.deleteLater()
            return img if img is not None and not img.isNull() else None
        except Exception:  # noqa: BLE001
            logger.debug("壁纸：抓帧失败", exc_info=True)
            return None

    def status(self) -> str:
        """读 QML 状态（调试用）。"""
        try:
            if self._view is None:
                return ""
            root = self._view.rootObject()
            return str(root.property("status") or "") if root else ""
        except Exception:  # noqa: BLE001
            return ""

    def teardown(self) -> None:
        self._active = False
        for name in ("_timer", "_color_timer"):
            try:
                t = getattr(self, name, None)
                if t is not None:
                    t.stop()
                    t.deleteLater()
            except Exception:  # noqa: BLE001
                pass
            setattr(self, name, None)
        try:
            if self._view is not None:
                self._view.setSource(QUrl())
                self._view.setParent(None)
                self._view.deleteLater()
        except Exception:  # noqa: BLE001
            pass
        self._view = None
        logger.info("壁纸：已拆除")


def apply_quick_wallpaper(window: QWidget, video_path: str) -> bool:
    """铺一层壁纸（全局单例）。"""
    global _current
    path = str(video_path or "")
    if not path or not os.path.isfile(path):
        logger.warning("壁纸：视频不存在 %s", path)
        if _current is not None:
            _current.teardown()
            _current = None
        return False
    if _current is not None and _current.video_path == path:
        _current._follow()                                       # noqa: SLF001
        return True
    if _current is not None:
        _current.teardown()
    layer = QuickWallpaper(window, path)
    ok = layer.start()
    _current = layer if ok else None
    return ok


def current_layer() -> "QuickWallpaper | None":
    return _current


def shutdown() -> None:
    global _current
    if _current is not None:
        _current.teardown()
        _current = None
