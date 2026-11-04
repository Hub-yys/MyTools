# -*- coding: utf-8 -*-
"""★ 视频版抽卡动画 —— 直接播放 `assets/game/splash/<角色>.mp4`。

## 用户 2026-10-30

给了 B站 视频地址（《鸣潮》爱弥斯抽卡唤取动画CG纯享版），并明确：

    > 直播视频，其实就十几秒

也就是**别用 QPainter 模拟，直接放真实抽卡 CG**。

## 和 QPainter 版（`gacha_reveal.py`）的关系

两个都要，按"有没有视频素材"自动选：

* 主题配了 ``video`` 且文件存在 → 用**本模块**播真实 CG
* 没配视频 → 退回 `gacha_reveal.GachaReveal`（QPainter 光效 + 定格图）

这样以后给别的角色加主题时，有视频就放视频，没视频也不至于没动画。

## 实现要点

用 ``QMediaPlayer`` + ``QVideoWidget``：

    player = QMediaPlayer()
    sink   = QVideoWidget()         #: 渲染到控件上（不是独立窗口）
    player.setVideoOutput(sink)

## ⚠⚠ 三个必须处理的坑

① **无音轨**：B站 的 dash 视频流是**纯视频**（音频在另一个文件）。
   ``setAudioOutput`` 传 None 就行，不然某些平台会报错。

② **播放完成要自己收尾**：`mediaStatusChanged` → `EndOfMedia`
   时关掉覆盖层。不能只靠定时器（视频长度会变）。

③ **播放失败不能卡死**：文件损坏/解码器缺失时
   `errorOccurred` 会触发 —— 必须**立刻收尾**（关覆盖层并回调），
   否则用户卡在一个黑屏上什么都点不了。

## 跳过

用户点一下 / 按 Esc / 空格 → 立刻停播 + 收尾（和 QPainter 版一致）。
"""

from __future__ import annotations

import logging
import os

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtWidgets import QWidget

logger = logging.getLogger(__name__)


class VideoGachaReveal(QWidget):
    """视频版开卡动画层（覆盖在父窗口上，播完自动消失）。

    :param parent: 覆盖在哪个控件上（通常是主窗口）
    :param skin: 主题 dict（要带 ``character`` / ``video``）

    ## 为什么用 ``QVideoWidget`` 而不是 ``QGraphicsVideoItem``

    ``QVideoWidget`` 是普通 QWidget，能直接 ``setGeometry`` 铺满、
    能当子控件叠在主界面上 —— 正是我们要的"覆盖层"。
    ``QGraphicsVideoItem`` 要自己搭 scene/view，多一层没好处。
    """

    #: 播放结束（正常播完 / 跳过 / 出错都会发一次）
    finished = Signal()

    def __init__(self, parent: QWidget, skin: dict):
        super().__init__(parent)
        self._skin = skin or {}
        self._done = False
        self._player = None
        self._sink = None
        self._audio = None
        self._start_retry = 0

        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("background: #000000;")   #: 视频黑边用黑底
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.hide()

        self._video_path = self._resolve_video()
        self._build_player()

    # ---------------------------------------------------------------- 资源
    def _resolve_video(self) -> str:
        """找到这个主题的视频文件（绝对路径）。找不到返回空串。"""
        rel = str(self._skin.get("video") or "")
        if not rel:
            return ""
        try:
            from ..core import paths  # noqa: PLC0415

            path = paths.resource_dir() / "assets" / rel
            if not path.is_file():
                logger.warning("视频动画：找不到 %s", path)
                return ""
            return str(path)
        except Exception:  # noqa: BLE001
            logger.warning("视频动画：解析路径失败", exc_info=True)
            return ""

    def _build_player(self) -> None:
        """创建播放器和渲染控件。失败就设 ``self._player = None``。"""
        if not self._video_path:
            return
        try:
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
            from PySide6.QtMultimediaWidgets import QVideoWidget
        except Exception:  # noqa: BLE001 - 没装 QtMultimedia
            logger.warning("视频动画：QtMultimedia 不可用", exc_info=True)
            return

        try:
            from PySide6.QtWidgets import QVBoxLayout

            self._player = QMediaPlayer(self)
            self._sink = QVideoWidget(self)
            self._sink.setStyleSheet("background: #000000;")
            #: ★ 关键：视频渲染控件必须**铺满**，否则视频只占左上角一小块
            lay = QVBoxLayout(self)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.addWidget(self._sink)
            self._player.setVideoOutput(self._sink)

            #: ★ ① 无音轨 —— B站 dash 是纯视频，音频在另一个文件里。
            #: 显式给个 QAudioOutput 并静音，比 setAudioOutput(None) 更稳
            #: （某些平台的解码器会因为"没有音频输出"报错）。
            try:
                self._audio = QAudioOutput(self)
                self._audio.setMuted(True)
                self._audio.setVolume(0.0)
                self._player.setAudioOutput(self._audio)
            except Exception:  # noqa: BLE001
                pass

            self._player.setSource(QUrl.fromLocalFile(self._video_path))
            #: ★ ② 播完收尾（不能只靠定时器：视频长度会变）
            self._player.mediaStatusChanged.connect(self._on_status)
            #: ★ ③ 出错立刻收尾（不能卡在黑屏）
            self._player.errorOccurred.connect(self._on_error)
            logger.info("视频动画：就绪 %s", os.path.basename(self._video_path))
        except Exception:  # noqa: BLE001
            logger.warning("视频动画：创建播放器失败", exc_info=True)
            self._player = None

    # ---------------------------------------------------------------- 播放
    def start(self) -> None:
        """开始播（铺满父窗口、置顶、抢键盘以便跳过）。"""
        self._start_retry += 1
        parent = self.parentWidget()
        ready = parent is not None and parent.width() > 1 and parent.height() > 1
        if not ready:
            if self._start_retry <= 60:
                QTimer.singleShot(16, self.start)
                return
            logger.warning("视频动画：父窗口一直没有尺寸，放弃")
            self._on_anim_done()
            return

        self.setGeometry(0, 0, parent.width(), parent.height())
        self.show()
        self.raise_()
        self.setFocus(Qt.FocusReason.OtherFocusReason)

        if self._player is None:
            #: 没有播放器（无视频/无 QtMultimedia）→ 立刻收尾，
            #: 让上层退回 QPainter 版
            logger.warning("视频动画：没有播放器，立刻收尾")
            QTimer.singleShot(0, self._on_anim_done)
            return
        try:
            self._player.play()
            logger.info("视频动画：开始播放")
        except Exception:  # noqa: BLE001
            logger.warning("视频动画：play() 失败", exc_info=True)
            QTimer.singleShot(0, self._on_anim_done)

    def skip(self) -> None:
        """立刻结束（用户点一下 / Esc）。"""
        if self._done:
            return
        self._on_anim_done()

    def _on_status(self, status) -> None:
        try:
            from PySide6.QtMultimedia import QMediaPlayer

            if status == QMediaPlayer.MediaStatus.EndOfMedia:
                logger.info("视频动画：播完")
                self._on_anim_done()
        except Exception:  # noqa: BLE001
            pass

    def _on_error(self, *args) -> None:
        logger.warning("视频动画：播放出错 %s", args)
        self._on_anim_done()

    def _on_anim_done(self) -> None:
        """收尾：停播、隐藏、发信号、自删。"""
        if self._done:
            return
        self._done = True
        try:
            if self._player is not None:
                self._player.stop()
        except Exception:  # noqa: BLE001
            pass
        self.hide()
        self.finished.emit()
        self.deleteLater()

    # ---------------------------------------------------------------- 事件
    def mousePressEvent(self, event) -> None:      # noqa: N802 - Qt 命名
        self.skip()
        event.accept()

    def keyPressEvent(self, event) -> None:        # noqa: N802 - Qt 命名
        if event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_Space,
                           Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.skip()
            event.accept()
            return
        super().keyPressEvent(event)

    def resizeEvent(self, event) -> None:          # noqa: N802 - Qt 命名
        super().resizeEvent(event)
        if self._sink is not None:
            self._sink.resize(self.size())


def has_video(skin: dict) -> bool:
    """这个主题有没有可用的抽卡视频（给上层选"视频版 / QPainter 版"）。"""
    if not isinstance(skin, dict):
        return False
    rel = str(skin.get("video") or "")
    if not rel:
        return False
    try:
        from ..core import paths  # noqa: PLC0415

        return (paths.resource_dir() / "assets" / rel).is_file()
    except Exception:  # noqa: BLE001
        return False


def play_video_reveal(parent: QWidget, skin: dict,
                      on_done=None) -> VideoGachaReveal:
    """播视频版开卡动画（播完调 ``on_done``）。"""
    reveal = VideoGachaReveal(parent, skin)
    if on_done is not None:
        reveal.finished.connect(on_done)
    QTimer.singleShot(0, reveal.start)
    return reveal
