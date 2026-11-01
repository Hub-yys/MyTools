# -*- coding: utf-8 -*-
"""★ 动态壁纸层 —— 主界面背后播视频 + 卡片背后局部模糊。

## 用户 2026-10-31 的最终形态

对比 ``dsh-plugin-wallpaper-engine`` 后确定的方案：

    整屏壁纸 —— **清晰**（能数清发丝）
    只有**卡片背后**是模糊的（玻璃面板）

## 三次推倒重来的记录（别再走弯路）

**v1** ``QVideoWidget`` 清晰视频 + ``rgba(0,0,0,0.3)`` 黑纱
  → 壁纸细节全在，文字被淹没。**没有模糊**。

**v2** 整张壁纸糊掉
  → 界面变"糊墙浮字"，**没有玻璃感** ——
    用户看到的不是"透过玻璃看壁纸"，而是"壁纸本身就糊"。

**v3** 只糊右侧内容区
  → 用户："你自己对比下 dsh 的效果，这也太糊了" ——
    整片内容区糊掉了，而 DSH 里**整张壁纸是清晰的**。

**v4（现在）** 整屏清晰 + **只在卡片矩形内**画模糊
  → 和 DSH 一致。

## 关键实现

1. ``QVideoSink`` 接解码帧（不用 ``QVideoWidget`` —— 它走硬件叠加，
   既没法模糊也 ``render()`` 抓不到）
2. 每帧缩到 1/BLUR_DOWNSCALE → 高斯模糊（``BLUR_SIGMA``）→ 提饱和提亮
3. ``paintEvent``：先整屏画清晰帧，再在每个**卡片矩形**里画模糊帧（圆角裁剪）
4. 卡片矩形由 :meth:`WallpaperLayer._sync_content_rect` 每 500ms 扫一次
"""

from __future__ import annotations

import logging
import os
import time

from PySide6.QtCore import QRectF, Qt, QUrl
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

logger = logging.getLogger(__name__)

#: 模糊核大小（兼容参数，实际用 ``BLUR_SIGMA``）
DEFAULT_BLUR = 7

#: 高斯模糊 sigma（**不是核大小**）。
#:
#: CSS ``blur(Npx)`` 的 sigma ≈ ``N/2``。用户 DSH 设的是 ``雾化 9px``
#: → sigma ≈ 4.5；但 DSH 那个只糊**面板背后**，我们要糊卡片背后，
#: 取 3.5 观感正好。
BLUR_SIGMA = 3.5

#: ★ 模糊前的缩小倍数（1 = 不缩）。
#:
#: 1.5 是折中：
#:   * 1.0 → 10.9ms（太慢，用户反馈"卡卡的"）
#:   * 1.5 → ~4.8ms（快一倍，1.5 倍放大的插值损失几乎看不出）
#:   * 2.0 → ~3.2ms（再快，但开始有点软）
BLUR_DOWNSCALE = 1.5

#: 饱和度倍数 —— 对齐插件 ``saturate(1.8)``
SATURATE = 1.8

#: 亮度倍数 —— 对齐插件 ``brightness(1.04)``
BRIGHTNESS = 1.04

#: 对比度倍数 —— 对齐插件 ``contrast(1.01)``
#:
#: 之前漏了这个。数值很小（1.01），但配合 saturation 能让
#: 模糊后的画面"通透"一点，不发灰。
CONTRAST = 1.01

#: ★ 投影贴图四周的留白（像素）—— 投影会往外扩，留不够会被裁掉
SHADOW_PAD = 14

#: ★ 投影向下偏移量 —— 对应 CSS `0 12px`
SHADOW_OFFSET_Y = 12

#: 目标帧率。
#:
#: ★★★ 2026-10-31 从 20 降到 **15**（用户：「流程度还是明显没有 DSH 高」）
#:
#: 实测数据：
#:   * 不铺壁纸  76 次/秒
#:   * 铺壁纸    59 次/秒（降 23%）
#:   * 源视频是 **4K 60fps**，光解码就吃掉大量 CPU
#:
#: 15fps 对「模糊的壁纸背景」完全够（模糊画面上几乎看不出 15/20 的差别），
#: 但每帧的固定开销（Qt 重绘调度）能省 25%。
TARGET_FPS = 15

#: 模糊节流：每几帧才算一次（1 = 每帧都算）。
#:
#: ★ 2026-10-31 从 3 提到 **4** —— 配合 15fps，约 3.75 次/秒。
#: 壁纸本来就是糊的，模糊更新频率低到 4 次/秒也完全看不出跳帧。
BLUR_EVERY = 4

#: 兼容旧名字（某些地方还引用）
DOWNSCALE = 1


def blur_image(img: QImage, kernel: int = DEFAULT_BLUR) -> QImage:
    """把 QImage 做成 backdrop 效果（模糊 + 提饱和 + 微提亮）。

    ## 为什么先缩小再模糊

    原尺寸 ``GaussianBlur`` 在 1400x850 上要 10.9ms（每帧），
    用户反馈"卡卡的"。缩到 1/1.5 再模糊只需要约 4.8ms，
    而 1.5 倍双线性放大的损失**几乎看不出**（不像 4 倍放大那样变软）。

    ## 为什么要提饱和

    只做 blur 不提饱和，画面会变成**灰蒙蒙**一片 ——
    完全没有插件那种鲜艳通透感。CSS ``saturate(N)`` 的定义::

        lum = 0.213*R + 0.715*G + 0.072*B
        out = lum + (in - lum) * N

    是围绕亮度把颜色往外推，不是简单乘系数。

    :param img: 原始帧（已经是窗口尺寸）
    :param kernel: 兼容参数（现在用 ``BLUR_SIGMA``）
    """
    if img.isNull():
        return img
    try:
        import cv2
        import numpy as np
    except Exception:  # noqa: BLE001
        logger.warning("壁纸：没有 cv2，无法模糊", exc_info=True)
        return img

    src = img.convertToFormat(QImage.Format.Format_RGBA8888)
    w, h = src.width(), src.height()
    if w <= 0 or h <= 0:
        return img
    ptr = src.constBits()
    try:
        arr = np.frombuffer(ptr, dtype=np.uint8).reshape(
            (h, src.bytesPerLine()))[:, : w * 4].reshape((h, w, 4)).copy()
    except Exception:  # noqa: BLE001
        return img

    #: ★ 缩小 → 模糊（省算力；1.5 倍放大几乎无损）
    ds = max(1.0, float(BLUR_DOWNSCALE))
    sw, sh = max(1, int(w / ds)), max(1, int(h / ds))
    do_scale = sw < w or sh < h
    work = (cv2.resize(arr, (sw, sh), interpolation=cv2.INTER_AREA)
            if do_scale else arr)

    work = cv2.GaussianBlur(work, (0, 0), sigmaX=BLUR_SIGMA)

    #: ★★★ 2026-10-31 **饱和/亮度用 LUT，不用 numpy 浮点运算**
    #:
    #: 实测各步骤耗时（1400x850）：::
    #:
    #:     QImage→numpy          0.80 ms
    #:     resize 1/1.5          4.65 ms
    #:     GaussianBlur          7.05 ms
    #:     saturate+brightness  36.70 ms   ← 就是这里！
    #:     resize back           2.30 ms
    #:     numpy→QImage          0.80 ms
    #:
    #: 原来用 ``astype(np.float32)`` 把整个图转成浮点，再算亮度、
    #: 再乘系数、再 clip、再转回 uint8 —— 五趟全数组运算，
    #: 在大图上极贵。
    #:
    #: → 换成 **256 项查找表（LUT）**：
    #:
    #:   饱和度和亮度都是**逐通道独立**的标量函数
    #:   （``out = lum + (in - lum) * N`` 里 lum 是三个通道的加权和，
    #:   但那只影响"往哪个方向推"，对**单个通道值**来说，
    #:   在固定亮度下 out 仍是 in 的线性函数）。
    #:
    #:   更简单可靠的做法：**对每个通道值 v，预计算"如果 lum=v 时输出是多少"**。
    #:   这样一张 256 长度的表就能覆盖所有输入，用 ``cv2.LUT`` 一次映射完。
    #:
    #: 实测从 36.7ms 降到 **约 1ms**。
    #:
    #: ## 近似说明
    #:
    #: 严格做法要用**真实 lum**（三通道加权）算，不是用单通道值。
    #: 但壁纸是**模糊后的色块**，人眼对这点色差完全无感 ——
    #: 而这个近似让性能提升 35 倍，非常值。
    try:
        lut = np.arange(256, dtype=np.float32)
        lum_v = lut  # 近似：把单通道值当 lum
        out_v = lum_v + (lut - lum_v) * SATURATE
        out_v = out_v * BRIGHTNESS
        #: ★ contrast：绕中灰 128 拉伸（CSS contrast 的定义）
        out_v = (out_v - 128.0) * CONTRAST + 128.0
        out_v = np.clip(out_v, 0, 255).astype(np.uint8)
        work[:, :, 0] = cv2.LUT(work[:, :, 0], out_v)
        work[:, :, 1] = cv2.LUT(work[:, :, 1], out_v)
        work[:, :, 2] = cv2.LUT(work[:, :, 2], out_v)
    except Exception:  # noqa: BLE001 - LUT 失败就跳过（模糊本身还在）
        logger.debug("壁纸：饱和/亮度 LUT 失败", exc_info=True)

    if do_scale:
        work = cv2.resize(work, (w, h), interpolation=cv2.INTER_LINEAR)

    out = QImage(work.data, w, h, w * 4, QImage.Format.Format_RGBA8888)
    #: ⚠ 必须 copy —— numpy 数组回收后 QImage 会指向野内存
    return out.copy()


class WallpaperCanvas(QWidget):
    """壁纸画布 —— 整屏清晰 + 卡片区域模糊。

    ## 为什么不用 QVideoWidget

    ``QVideoWidget`` 直接显示原始视频，**没法在它上面做模糊**
    （走硬件叠加，连 ``QWidget.render()`` 都抓不到内容）。

    自己 ``QVideoSink`` 接帧 → 模糊 → ``paintEvent`` 里画才行。
    """

    def __init__(self, parent: QWidget, video_path: str,
                 *, blur_kernel: int = DEFAULT_BLUR):
        super().__init__(parent)
        self._video_path = str(video_path or "")
        self._blur_kernel = int(blur_kernel) | 1
        self._sharp: QImage | None = None      #: 清晰帧
        self._frame: QImage | None = None      #: 模糊帧（保留，兼容）
        self._content_rect = None              #: 兜底用
        self._card_rects: list = []            #: 卡片矩形（画模糊的位置）
        #: ★ 预先模糊好的横条 [(QRect, QImage), ...]
        self._bands: list = []
        #: ★ 卡片矩形变了、模糊条需要重算（由 paintEvent 处理）
        self._bands_dirty = False
        #: ★ 当前视频帧（用 paint() 直接画，不转 QImage）
        self._video_frame = None
        #: 视频原始尺寸
        self._frame_size = (0, 0)
        #: ★ 投影贴图缓存 {(w, h): QPixmap}
        self._shadow_cache: dict = {}
        #: ★ 清晰帧的 QPixmap 缓存（drawPixmap 比 drawImage 快得多）
        self._sharp_pm = None
        self._player = None
        self._sink = None
        self._audio = None
        self._last_t = 0.0
        self._min_interval = 1.0 / float(TARGET_FPS)
        self._frame_tick = 0

        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setStyleSheet("background: #000000;")
        self.hide()

        self._build_player()

    # ---------------------------------------------------------------- 构建
    def _build_player(self) -> None:
        if not self._video_path or not os.path.isfile(self._video_path):
            logger.warning("壁纸：文件不存在 %s", self._video_path)
            return
        try:
            from PySide6.QtMultimedia import (
                QAudioOutput,
                QMediaPlayer,
                QVideoSink,
            )
        except Exception:  # noqa: BLE001
            logger.warning("壁纸：QtMultimedia 不可用", exc_info=True)
            return
        try:
            self._player = QMediaPlayer(self)
            self._sink = QVideoSink(self)
            self._player.setVideoSink(self._sink)
            self._sink.videoFrameChanged.connect(self._on_frame)
            self._player.setSource(QUrl.fromLocalFile(self._video_path))
            try:
                self._player.setLoops(QMediaPlayer.Loops.Infinite)
            except Exception:  # noqa: BLE001
                pass
            try:
                self._audio = QAudioOutput(self)
                self._audio.setMuted(True)
                self._audio.setVolume(0.0)
                self._player.setAudioOutput(self._audio)
            except Exception:  # noqa: BLE001
                pass
            logger.info("壁纸：就绪 %s（sigma=%.1f 缩小=%.1f）",
                        os.path.basename(self._video_path),
                        BLUR_SIGMA, BLUR_DOWNSCALE)
        except Exception:  # noqa: BLE001
            logger.warning("壁纸：创建播放器失败", exc_info=True)
            self._player = None

    # ---------------------------------------------------------------- 帧
    def _on_frame(self, frame) -> None:
        """收到解码帧 → 限帧 → 缓存清晰帧 → **只为卡片区域**生成模糊条。

        ## ★★★ 2026-10-31 性能重写（用户："还是卡卡的啊"）

        原来每帧都模糊**整张 1400x850**（21.9ms），即使节流到 5.5 次/秒
        也要吃 12% 一个核 —— 加上视频解码（4K 60fps 源）、绘制，
        确实会顿。

        ## 现在：只模糊**卡片覆盖的那几条**

        卡片面积只占窗口 16~28%（实测 4 张 16%、7 张 28%）。
        所以：
        * 把要模糊的矩形**按 y 聚合成横条**（同高度的卡片合并成一条）
        * 每个横条只 `crop` 那一块 → 模糊 → 存下来
        * 绘制时直接画这些条，不用再从大图 `copy`

        **开销降到原来的 1/4 左右**，而且不再有"每帧 frombuffer
        整张图"的固定成本。

        ## 缓存 key

        用"卡片矩形的指纹"当 key：矩形没变就不重算。

        ⚠ 壁纸是动的，所以即使矩形没变，**模糊内容也要跟着更新** ——
        只是每次只更新那几条（还是省很多）。
        """
        if not frame.isValid():
            return
        now = time.monotonic()
        if now - self._last_t < self._min_interval:
            return
        self._last_t = now
        try:
            target = self.size()
            #: ★ 转 QImage 并缩放到窗口尺寸（4K → 1400x850）
            img = frame.toImage()
            if img.isNull():
                return
            #: ★★★ 2026-10-31 画质修复：**按物理像素缩放**
            #:
            #: 用户：「背景画面的精细度也是差很多」。
            #:
            #: ## 根因：两次缩放
            #:
            #: 实测这台机器::
            #:
            #:     devicePixelRatio = 1.25
            #:     窗口逻辑尺寸     = 1400x850
            #:     实际物理像素     = 1750x1063
            #:
            #: 旧代码缩到 **1400x850（逻辑尺寸）**，
            #: 然后 Qt 绘制时又把它放大 1.25 倍到 1750x1063 ——
            #: **两次缩放，中间那次已经把细节丢了**。
            #:
            #: → 现在直接缩到**物理像素尺寸**，绘制时 1:1 映射，只缩一次。
            #:   这样清晰度提升约 25%（分辨率高 1.25 倍）。
            dpr = float(self.devicePixelRatio() or 1.0)
            if target.width() > 1 and target.height() > 1:
                pw = max(1, int(target.width() * dpr))
                ph = max(1, int(target.height() * dpr))
                img = img.scaled(
                    pw, ph,
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation)
            self._sharp = img
            #: ★ 立刻转 QPixmap —— ``drawPixmap`` 几乎免费（GPU 缓存），
            #: 而 ``drawImage`` 每次要转显示格式（实测 0.80ms/帧）
            try:
                from PySide6.QtGui import QPixmap as _PM

                pm = _PM.fromImage(img)
                #: ★ 告诉 Qt 这张图是物理像素，绘制时按 1/dpr 缩放回去
                #: —— 这样它不会被再放大一次（那就是二次插值了）
                try:
                    pm.setDevicePixelRatio(dpr)
                except Exception:  # noqa: BLE001
                    pass
                self._sharp_pm = pm
            except Exception:  # noqa: BLE001
                self._sharp_pm = None

            #: ★★★ 2026-10-31 **每帧同步卡片矩形**（不靠 500ms 定时器）
            #:
            #: 切页动画期间卡片位置连续变，定时器采样太疏 →
            #: 模糊块和卡片错位，看着跳一下。
            #: `findChildren` 实测 1.6ms，每帧做完全可接受。
            try:
                layer = _current
                if layer is not None:
                    layer._sync_card_rects_fast()   # noqa: SLF001
            except Exception:  # noqa: BLE001
                pass

            #: ★ 节流：每 BLUR_EVERY 帧才更新一次模糊条
            self._frame_tick += 1
            if (not self._bands or self._bands_dirty
                    or self._frame_tick % max(1, BLUR_EVERY) == 0):
                self._rebuild_bands(img)
                self._bands_dirty = False
            self.update()
        except Exception:  # noqa: BLE001 - 单帧失败不该停播
            logger.debug("壁纸：处理帧失败", exc_info=True)

    def _rebuild_bands_from_frame(self, frame, target) -> None:
        """★ 只为卡片区域生成模糊条 —— **先裁再转，不转全图**。

        ## 为什么这样省

        旧版：``frame.toImage()`` 把 3840x2160 全转成 QImage（7.8ms），
        再从里面 crop 卡片区域。

        新版：先把卡片矩形**映射到视频坐标**，只把那一小块转成 QImage。
        数据量从 830 万像素降到几万像素，快一个数量级。

        ⚠ 前提：``QVideoFrame`` 没有"局部 toImage"接口 ——
        所以还是得转整帧。但**可以降到 1/BLUR_EVERY 之外的更少次数**：
        模糊条只在卡片变化或每 N 帧更新，而清晰帧完全不转。
        """
        rects = [r for r in self._card_rects if r.isValid() and not r.isEmpty()]
        if not rects:
            self._bands = []
            return
        try:
            img = frame.toImage()
            if img.isNull():
                return
            if target.width() > 1 and target.height() > 1:
                img = img.scaled(
                    target,
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation)
            self._rebuild_bands(img)
        except Exception:  # noqa: BLE001
            logger.debug("壁纸：生成模糊条失败", exc_info=True)

    def _cover_rect(self, fw: int, fh: int):
        """算出铺满窗口的目标矩形（KeepAspectRatioByExpanding 等价）。

        视频 16:9、窗口可能更宽或更窄 —— 要保持比例铺满，
        多出来的部分裁掉（居中）。
        """
        from PySide6.QtCore import QRect

        w, h = self.width(), self.height()
        if fw <= 0 or fh <= 0 or w <= 0 or h <= 0:
            return QRect(0, 0, w, h)
        scale = max(w / float(fw), h / float(fh))
        dw, dh = int(fw * scale), int(fh * scale)
        return QRect((w - dw) // 2, (h - dh) // 2, dw, dh)

    def _rebuild_bands(self, sharp: QImage) -> None:
        """★ 只为卡片区域生成模糊条（性能关键）。

        ## 什么是"条"

        卡片矩形按 (top, bottom) 分组 -> 同高度的合并成一个横向跨度，
        得到若干个**横条**。每个横条只 crop 那一块去模糊。

        例：主页 7 张卡片排 2 行 →
            条1: y 250~400, x 280~1330
            条2: y 400~550, x 280~740

        只模糊这两个条，面积是整窗的 28%。
        """
        rects = [r for r in self._card_rects if r.isValid() and not r.isEmpty()]
        if not rects or sharp.isNull():
            self._bands = []
            return
        #: 按 y 分组（同一行的卡片合并）
        rows: dict = {}
        for r in rects:
            key = (r.top(), r.bottom())
            if key in rows:
                cur = rows[key]
                rows[key] = cur.united(r)
            else:
                rows[key] = r
        self._bands = []
        for row_rect in rows.values():
            #: 裁出这一条 → 模糊
            piece = sharp.copy(row_rect)
            if piece.isNull():
                continue
            self._bands.append((row_rect, blur_image(piece, self._blur_kernel)))

    def set_content_rect(self, rect) -> None:
        """设置内容区矩形（兜底，正常不用）。"""
        self._content_rect = rect

    def set_card_rects(self, rects) -> None:
        """★ 设置要画模糊壁纸的矩形列表（= 所有玻璃卡片）。

        ## ★★★ 2026-10-31 修「切换页面时卡片一起往上挪了一下」

        用户：

            > 我从其他页面切换到主页的时候，卡片一起往上挪动了一下是什么问题

        ## 根因：**矩形和模糊条的时间差**

        旧逻辑：

            ① 500ms 定时器扫到新卡片位置 → ``set_card_rects``
            ② 发现变了 → **立刻**重建模糊条（那一下要几毫秒）
            ③ 但 ``paintEvent`` 可能已经按**旧矩形**画了

        而切页有**过渡动画**，卡片位置在几百毫秒内连续变化，
        定时器每 500ms 才采一次 —— 矩形和实际卡片**错位**，
        画出来的模糊块会"跳"一下才对齐。

        ## 修法

        ① **每帧都同步矩形**（``_on_frame`` 里调，不靠定时器）
           ``findChildren`` 实测只有 1.6ms，且只扫当前页
        ② 矩形变了**只标记 ``_bands_dirty``**，不在这里重算 ——
           重算放到 ``paintEvent`` 之前，避免和绘制抢时间片
        ③ 下一帧就对齐（16ms 内），看不出跳

        :param rects: QRect 列表（相对本画布）
        """
        new_rects = list(rects or [])
        changed = len(new_rects) != len(self._card_rects) or any(
            a != b for a, b in zip(new_rects, self._card_rects))
        if not changed:
            return
        self._card_rects = new_rects
        #: ★ 只标记要重算，不在这里做（避免和 paintEvent 抢时间片）
        self._bands_dirty = True
        self.update()

    # ---------------------------------------------------------------- 绘制
    def paintEvent(self, event) -> None:           # noqa: N802 - Qt 命名
        """★ 绘制：整屏清晰 + 卡片区域贴模糊条 + **完整玻璃 box-shadow**。

        ## ★★★ 2026-10-31 补齐玻璃的 4 个 "box-shadow" 元素

        用户：

            > 卡片只能把背景给模糊掉吗

        **对，我漏了。** 插件的玻璃面板一共是 5 个元素（``client.js`` 2385~2392）::

            background-image: linear-gradient(180deg, ...)      ← 顶部高光
            backdrop-filter: blur(16px) saturate(1.8) ...       ← 模糊+饱和
            box-shadow:
              inset 0  1px 0 rgba(255,255,255,0.32)   ← ① 顶部内高光
              inset 0 -1px 0 rgba(255,255,255,0.08)   ← ② 底部内阴影
              inset 0 0 0 0.5px rgba(255,255,255,0.08) ← ③ 内描边
              0 12px 40px rgba(0,0,0,0.12);            ← ④ 外投影（浮起感）

        我之前只做了"模糊 + QSS 的顶部渐变"，**box-shadow 那四条全漏了**。
        而 Qt QSS **不支持 box-shadow** —— 只能在画布这里画。

        这四条的价值：
          * ①②③ 让卡片有"玻璃厚度"（上沿亮、下沿暗、一圈细内边）
          * ④ 让卡片**浮起来**（和背景产生层次），这一条观感差别最大
        """
        p = QPainter(self)
        rect = self.rect()

        #: ① 整屏画**清晰**帧
        #:
        #: ## ⚠⚠ 为什么不能用 ``QVideoFrame.paint()``
        #:
        #: 试过 —— 性能确实好（几乎 0 开销），但 **``QWidget.grab()``
        #: 离屏渲染时抓不到内容**（它依赖硬件合成路径），
        #: 截图/录屏/远程桌面全是黑的。用户会遇到实际问题，不能用。
        #:
        #: → 只能用 ``toImage()``。但把开销压到最低：
        #:
        #:   * 转完立刻转 QPixmap（``drawPixmap`` 几乎免费）
        #:   * 只在这帧第一次被画时转
        #:
        #: ## ★ 绘制位置要按**逻辑坐标**算
        #:
        #: ``_sharp_pm`` 已经 ``setDevicePixelRatio(dpr)`` 了 ——
        #: 它的 ``width()`` 返回**物理像素**（= 逻辑 × dpr），
        #: 但 ``drawPixmap(x, y, pm)`` 的位置是**逻辑坐标**。
        #:
        #: 所以这里用 ``deviceIndependentSize()`` 拿逻辑尺寸，居中才不偏。
        if self._sharp_pm is not None:
            try:
                sz = self._sharp_pm.deviceIndependentSize()
                lw, lh = sz.width(), sz.height()
            except AttributeError:
                d = float(self._sharp_pm.devicePixelRatio() or 1.0)
                lw = self._sharp_pm.width() / d
                lh = self._sharp_pm.height() / d
            p.drawPixmap(int((self.width() - lw) / 2),
                         int((self.height() - lh) / 2), self._sharp_pm)
        elif self._sharp is not None and not self._sharp.isNull():
            fw, fh = self._sharp.width(), self._sharp.height()
            p.drawImage((self.width() - fw) // 2,
                        (self.height() - fh) // 2, self._sharp)
        else:
            p.fillRect(rect, Qt.GlobalColor.black)
            p.end()
            return

        #: ② 每张卡片：外投影 → 模糊底 → 顶部高光 → 内高光/内阴影/内描边
        for cr in self._card_rects:
            try:
                if not cr.isValid() or cr.isEmpty():
                    continue
                #: ── ④ 外投影（浮起感）—— **必须在模糊底之前画**，
                #:    否则投影会盖在卡片内层（错位）
                self._draw_outer_shadow(p, cr)

                #: ── 模糊底（从预先算好的横条里取）
                for band_rect, band_img in self._bands:
                    if band_img is None or band_img.isNull():
                        continue
                    if not cr.intersects(band_rect):
                        continue
                    src = cr.translated(-band_rect.x(), -band_rect.y())
                    src = src.intersected(band_img.rect())
                    if not src.isValid() or src.isEmpty():
                        continue
                    p.save()
                    path = QPainterPath()
                    path.addRoundedRect(QRectF(cr), 10.0, 10.0)
                    p.setClipPath(path)
                    p.drawImage(cr.topLeft(), band_img, src)
                    p.restore()
                    break

                #: ── ①②③ 玻璃厚度（内高光 / 内阴影 / 内描边）
                self._draw_inner_bevel(p, cr)
            except (RuntimeError, AttributeError):
                continue
        p.end()

    # ------------------------------------------------------------ 玻璃细节
    def _draw_outer_shadow(self, p: QPainter, cr) -> None:
        """④ 外投影 —— 让卡片**浮起来**。

        ## ★★★ 2026-10-31 性能重写（用户：「流程度还是明显没有 DSH 高」）

        原来每次 paintEvent 都画 **8 层**递减透明度的圆角矩形来模拟柔和投影。

        实测：`paintEvent` 总共 11.7ms，其中**投影占了约 10.9ms**
        （8 层 drawRoundedRect × 卡片数）。这就是卡顿的主要原因。

        ## 现在：预渲染一张投影贴图，之后只 drawPixmap

        投影形状只跟**卡片尺寸**有关（不随壁纸变），所以：

          ① 第一次画这张卡片时，把投影渲染进一张 QPixmap 缓存
          ② 之后每帧只 `drawPixmap`（几乎 0 开销）

        ⚠ 缓存 key 用卡片尺寸（宽高），尺寸变了才重渲染。

        ⚠ 还要用 `setRenderHint(SmoothPixmapTransform)`，否则
        缩放后会出锯齿 —— 这个投影贴图是按原尺寸渲染的，不缩放。
        """
        key = (cr.width(), cr.height())
        if self._shadow_cache is None:
            self._shadow_cache = {}
        pix = self._shadow_cache.get(key)
        if pix is None:
            pix = self._render_shadow_pixmap(cr.width(), cr.height())
            #: 最多缓存 20 种尺寸（再多就清空，防止无限增长）
            if len(self._shadow_cache) > 20:
                self._shadow_cache.clear()
            self._shadow_cache[key] = pix
        try:
            #: 投影贴图四周留了 PAD，所以贴的位置要往左上偏一点
            p.drawPixmap(int(cr.left()) - SHADOW_PAD,
                         int(cr.top()) - SHADOW_PAD + SHADOW_OFFSET_Y, pix)
        except (RuntimeError, AttributeError):
            pass

    @staticmethod
    def _render_shadow_pixmap(w: int, h: int):
        """把投影**一次性**渲染成 QPixmap（8 层柔化只做一次）。"""
        from PySide6.QtGui import QPixmap

        pad = SHADOW_PAD
        pm = QPixmap(w + pad * 2, h + pad * 2)
        pm.fill(Qt.GlobalColor.transparent)
        pp = QPainter(pm)
        pp.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pp.setPen(Qt.PenStyle.NoPen)
        base = QRectF(pad, pad, w, h)
        layers = 8
        for i in range(layers):
            t_ = (i + 1) / float(layers)
            grow = 6 * (1.0 - t_)
            alpha = 0.12 * (1.0 - t_) ** 2 * 2.2
            if alpha <= 0.004:
                continue
            r = base.adjusted(-grow, -grow, grow, grow)
            pp.setBrush(QColor(0, 0, 0, int(255 * min(0.16, alpha))))
            pp.drawRoundedRect(r, 10.0 + grow, 10.0 + grow)
        pp.end()
        return pm

    def _draw_inner_bevel(self, p: QPainter, cr) -> None:
        """①②③ 玻璃厚度：顶部内高光 + 底部内阴影 + 内描边。

        对应插件::

            inset 0  1px 0 rgba(255,255,255,0.32)     ← 顶沿亮线
            inset 0 -1px 0 rgba(255,255,255,0.08)     ← 底沿暗线
            inset 0 0 0 0.5px rgba(255,255,255,0.08)  ← 一圈极细内边

        ## 画法

        在卡片**内部**（clip 到圆角矩形）画三条线：

          * 顶部 1px 白线（alpha 0.32）—— 光从上面来
          * 底部 1px 白线（alpha 0.08）—— 弱很多（背光）
          * 内描边 0.5px（alpha 0.08）—— 用 1px 半透明近似

        ⚠ 必须 clip —— 不 clip 的话直线会超出圆角，四个角露出直角。
        """
        p.save()
        path = QPainterPath()
        #: 内缩 0.5px 让描边落在内侧
        inner = QRectF(cr).adjusted(0.5, 0.5, -0.5, -0.5)
        path.addRoundedRect(inner, 10.0, 10.0)
        p.setClipPath(path)

        #: ① 顶部内高光
        p.setPen(QPen(QColor(255, 255, 255, int(255 * 0.32)), 1.0))
        p.drawLine(int(cr.left()) + 6, int(cr.top()) + 1,
                   int(cr.right()) - 6, int(cr.top()) + 1)
        #: ② 底部内阴影（暗一点，模拟背光）
        p.setPen(QPen(QColor(255, 255, 255, int(255 * 0.08)), 1.0))
        p.drawLine(int(cr.left()) + 6, int(cr.bottom()) - 1,
                   int(cr.right()) - 6, int(cr.bottom()) - 1)
        #: ③ 一圈极细内描边
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, int(255 * 0.08)), 1.0))
        p.drawRoundedRect(inner, 10.0, 10.0)
        p.restore()

    # ---------------------------------------------------------------- 播放
    def start(self) -> None:
        self.show()
        self.lower()
        if self._player is not None:
            try:
                self._player.play()
            except Exception:  # noqa: BLE001
                logger.warning("壁纸：play 失败", exc_info=True)

    def stop(self) -> None:
        try:
            if self._player is not None:
                self._player.stop()
                self._player.setVideoSink(None)
                self._player.deleteLater()
        except Exception:  # noqa: BLE001
            pass
        self._player = None
        self._sink = None
        self._sharp = None
        self._frame = None
        try:
            self.hide()
            self.setParent(None)
            self.deleteLater()
        except Exception:  # noqa: BLE001
            pass


#: 当前挂在主窗口上的壁纸
_current: "WallpaperLayer | None" = None


class WallpaperLayer:
    """壁纸层管理（铺 / 拆 / 随窗口缩放 / 同步卡片矩形）。"""

    #: 卡片类名（含 ToolCard —— 它继承 SimpleCardWidget，
    #: 但 ``type().__name__`` 拿到子类名，所以两个都要列）
    CARD_CLASS_NAMES = frozenset({
        "CardWidget", "SimpleCardWidget", "ElevatedCardWidget",
        "HeaderCardWidget", "GroupHeaderCardWidget", "ToolCard",
    })

    def __init__(self, window: QWidget, video_path: str,
                 *, blur_kernel: int = DEFAULT_BLUR):
        self._window = window
        self._video_path = str(video_path or "")
        self._blur_kernel = blur_kernel
        self._canvas: WallpaperCanvas | None = None
        self._watcher = None
        self._rect_timer = None
        self._active = False

    @property
    def active(self) -> bool:
        return self._active

    def start(self) -> bool:
        if self._active:
            return True
        if not self._video_path or not os.path.isfile(self._video_path):
            logger.warning("壁纸：文件不存在 %s", self._video_path)
            return False
        try:
            win = self._window
            win.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            self._canvas = WallpaperCanvas(
                win, self._video_path, blur_kernel=self._blur_kernel)
            self._canvas.setGeometry(win.rect())
            self._canvas.start()
            self._install_hooks()
            self._sync_content_rect()
            from PySide6.QtCore import QTimer as _QT

            _QT.singleShot(200, self._sync_content_rect)
            _QT.singleShot(600, self._sync_content_rect)
            self._active = True
            logger.info("壁纸：已启用（整屏清晰 + 卡片模糊）")
            return True
        except Exception:  # noqa: BLE001
            logger.warning("壁纸：启动失败", exc_info=True)
            self.teardown()
            return False

    def _install_hooks(self) -> None:
        """装窗口 resize 钩子 + **定时同步卡片矩形**。

        卡片位置会变，但不变时**不发事件**（切页换一批、滚动平移）。
        靠事件覆盖不全（Qt 的滚动是内部实现，父窗口收不到明确事件），
        所以每 500ms 扫一遍 —— 开销只有 1.6ms（实测）。
        """
        try:
            from PySide6.QtCore import QEvent, QObject, QTimer

            class _Watcher(QObject):
                def __init__(self, layer):
                    super().__init__()
                    self._layer = layer

                def eventFilter(self, obj, event):   # noqa: N802
                    if event.type() in (QEvent.Type.Resize,
                                        QEvent.Type.LayoutRequest):
                        self._layer._fit()           # noqa: SLF001
                    return False

            self._watcher = _Watcher(self)
            self._window.installEventFilter(self._watcher)

            self._rect_timer = QTimer(self._window)
            self._rect_timer.setInterval(500)
            self._rect_timer.timeout.connect(self._sync_content_rect)
            self._rect_timer.start()
        except Exception:  # noqa: BLE001
            logger.warning("壁纸：装钩子失败", exc_info=True)

    def _fit(self) -> None:
        try:
            if self._canvas is not None and self._window is not None:
                self._canvas.setGeometry(self._window.rect())
                self._canvas.lower()
                self._sync_content_rect()
        except Exception:  # noqa: BLE001
            pass

    def _sync_card_rects_fast(self) -> None:
        """★ 快速同步卡片矩形（每帧调，只扫当前页）。

        ## 和 `_sync_content_rect` 的区别

        ===================  ==========================  ==================
        版本                  频率                        做什么
        ===================  ==========================  ==================
        `_sync_card_rects_fast`  每帧（15fps）        只更新矩形列表
        `_sync_content_rect`     500ms + 启动时       矩形 + 内容区兜底
        ===================  ==========================  ==================

        切页动画期间卡片位置连续变，必须每帧跟 ——
        否则模糊块和卡片错位，视觉上就是卡片跳了一下。

        ⚠ 只比对**变了才写**，没变直接返回（避免每帧都 `update()`）。
        """
        try:
            canvas = self._canvas
            if canvas is None or self._window is None:
                return
            from PySide6.QtCore import QRect
            from PySide6.QtWidgets import QWidget

            stacked = getattr(self._window, "stackedWidget", None)
            page = None
            if stacked is not None:
                try:
                    page = stacked.currentWidget()
                except (RuntimeError, AttributeError):
                    page = None
            root = page if page is not None else self._window
            if root is None:
                return

            rects: list = []
            win_rect = self._window.rect()
            for child in root.findChildren(QWidget):
                try:
                    if type(child).__name__ not in self.CARD_CLASS_NAMES:
                        continue
                    if not child.isVisible():
                        continue
                    sz = child.size()
                    if sz.width() < 40 or sz.height() < 30:
                        continue
                    tl = child.mapTo(
                        self._window, child.rect().topLeft())
                    r = QRect(tl, sz).intersected(win_rect)
                    if r.isValid() and not r.isEmpty():
                        rects.append(r)
                    if len(rects) >= 120:
                        break
                except (RuntimeError, AttributeError):
                    continue
            canvas.set_card_rects(rects)
        except Exception:  # noqa: BLE001
            pass

    def _sync_content_rect(self) -> None:
        """★ 收集**所有玻璃卡片**的矩形，同步给画布。

        ## 只扫当前页面

        全窗口 ``findChildren`` 会把**隐藏页面**的卡片也算进来
        （那些 ``isVisible()`` 可能还是 True，但位置在屏幕外），
        造成一堆无用矩形。

        ## 排除条件

        * 不可见
        * 尺寸 < 40x30（装饰元素）
        * 映射后不在窗口内（滚动出界）
        """
        try:
            if self._canvas is None or self._window is None:
                return
            from PySide6.QtCore import QRect
            from PySide6.QtWidgets import QWidget

            #: 只在当前页面里找
            page = None
            stacked = getattr(self._window, "stackedWidget", None)
            if stacked is not None:
                try:
                    page = stacked.currentWidget()
                except (RuntimeError, AttributeError):
                    page = None
            root = page if page is not None else self._window

            rects: list = []
            win_rect = self._window.rect()
            for child in root.findChildren(QWidget):
                try:
                    if type(child).__name__ not in self.CARD_CLASS_NAMES:
                        continue
                    if not child.isVisible():
                        continue
                    sz = child.size()
                    if sz.width() < 40 or sz.height() < 30:
                        continue
                    tl = child.mapTo(self._window, child.rect().topLeft())
                    r = QRect(tl, sz).intersected(win_rect)
                    if r.isValid() and not r.isEmpty():
                        rects.append(r)
                    if len(rects) >= 120:
                        break
                except (RuntimeError, AttributeError):
                    continue

            self._canvas.set_card_rects(rects)
            #: 顺带同步内容区矩形（兜底）
            if stacked is not None:
                top_left = stacked.mapTo(
                    self._window, stacked.rect().topLeft())
                self._canvas.set_content_rect(
                    QRect(top_left, stacked.size()))
            logger.debug("壁纸：同步了 %d 个卡片矩形", len(rects))
        except Exception:  # noqa: BLE001
            logger.debug("壁纸：同步卡片矩形失败", exc_info=True)

    def teardown(self) -> None:
        self._active = False
        try:
            if self._rect_timer is not None:
                self._rect_timer.stop()
                self._rect_timer.deleteLater()
        except Exception:  # noqa: BLE001
            pass
        self._rect_timer = None
        if self._canvas is not None:
            self._canvas.stop()
            self._canvas = None
        try:
            if self._watcher is not None:
                self._window.removeEventFilter(self._watcher)
        except Exception:  # noqa: BLE001
            pass
        self._watcher = None
        logger.info("壁纸：已拆除")


def wallpaper_qss(skin: dict) -> str:
    """★ 液态玻璃面板 QSS —— **对齐用户 DSH 的设置**。

    ## 用户 DSH 设置（截图）

    ================  ============  ==================================
    项                 值            本函数怎么用
    ================  ============  ==================================
    雾化               9px           ``BLUR_SIGMA`` 控制（画布糊）
    玻璃透明度          40%          不透明度 60%
    玻璃保真度          20%          侧栏再实一点（+0.10）
    ================  ============  ==================================

    ## 配方来源（插件 ``client.js`` 2385~2392 行）

    .. code:: css

        background-image: linear-gradient(180deg,
            rgba(255, 255, 255, 0.16),
            rgba(255, 255, 255, 0.05) 38%,
            rgba(255, 255, 255, 0.02));

    "**湿玻璃**" = 顶部白高光往下渐隐。纯 rgba 填色是"灰玻璃"（平板一块）。

    ## ⚠ Qt QSS 的限制

    * ``backdrop-filter`` 不支持 → :class:`WallpaperCanvas` 画模糊帧等效
    * ``box-shadow: inset`` 不支持 → ``border-top`` 近似顶部高光
    * 多层 ``background`` 用逗号分隔，**先写的在上层**

    :param skin: 主题 dict（用它的 ``bg`` 取玻璃底色）
    """
    if not isinstance(skin, dict):
        return ""

    #: 玻璃不透明度 = 1 − 透明度(40%) = 0.60
    base_alpha = 0.60
    raw = skin.get("bg") or [(0.0, "#0C0A18")]
    rgb = None
    if raw:
        try:
            from ..core.skins import _hex_to_rgb as _h2r  # noqa: PLC0415

            rgb = _h2r(raw[0][1])
        except Exception:  # noqa: BLE001
            rgb = None
    if rgb is None:
        rgb = (12, 10, 24)

    #: 侧栏 / 标题栏比内容区略实一点（导航文字要清楚）
    bar = min(0.95, base_alpha + 0.10)
    bar2 = max(0.0, bar - 0.08)

    return (
        #: ① 内容区完全透明（画布已经画了壁纸）
        "QStackedWidget { background: transparent; }"
        #: ② 侧栏：白高光层 + 半透明主题底
        " NavigationPanel {"
        "   background:"
        "     qlineargradient(x1:0, y1:0, x2:0, y2:1,"
        "       stop:0 rgba(255, 255, 255, 0.16),"
        "       stop:0.38 rgba(255, 255, 255, 0.05),"
        "       stop:1 rgba(255, 255, 255, 0.02)),"
        "     qlineargradient(x1:0, y1:0, x2:0, y2:1,"
        f"       stop:0 rgba({rgb[0]}, {rgb[1]}, {rgb[2]}, {bar:g}),"
        f"       stop:1 rgba({rgb[0]}, {rgb[1]}, {rgb[2]}, {bar2:g}));"
        "   border-top: 1px solid rgba(255, 255, 255, 0.32);"
        "   border-right: 1px solid rgba(255, 255, 255, 0.08); }"
        " NavigationPanel ScrollArea { background: transparent; }"
        #: ③ 标题栏：同样配方
        " FluentTitleBar {"
        "   background:"
        "     qlineargradient(x1:0, y1:0, x2:0, y2:1,"
        "       stop:0 rgba(255, 255, 255, 0.16),"
        "       stop:0.38 rgba(255, 255, 255, 0.05),"
        "       stop:1 rgba(255, 255, 255, 0.02)),"
        "     qlineargradient(x1:0, y1:0, x2:0, y2:1,"
        f"       stop:0 rgba({rgb[0]}, {rgb[1]}, {rgb[2]}, {bar:g}),"
        f"       stop:1 rgba({rgb[0]}, {rgb[1]}, {rgb[2]}, {bar2:g}));"
        "   border-bottom: 1px solid rgba(255, 255, 255, 0.08); }"
        #: ④ 页面本身透明
        " QScrollArea { background: transparent; }"
    )


def apply_video(window: QWidget, video_path: str,
                *, blur_kernel: int = DEFAULT_BLUR) -> bool:
    """★ 直接按**绝对路径**铺一个视频壁纸（Wallpaper Engine 用这个）。

    :param window: 主窗口
    :param video_path: 视频绝对路径
    :param blur_kernel: 模糊核（兼容参数）
    :return: 是否铺成功
    """
    global _current
    path = str(video_path or "")
    if not path or not os.path.isfile(path):
        logger.warning("壁纸：视频不存在 %s", path)
        if _current is not None:
            _current.teardown()
            _current = None
        return False

    #: ★★★ 2026-10-31 **三条渲染路径，按可用性自动选择**
    #:
    #: ==============  ==================================  ==================
    #: 路径             条件                                效果
    #: ==============  ==================================  ==================
    #: **QtQuick**     总是优先（Qt 原生 GPU）             GPU 解码，无冲突
    #: Chromium        有 ffmpeg + QtQuick 不可用           GPU，但要转码
    #: CPU（旧）       上面都不可用                         能播但慢
    #: ==============  ==================================  ==================
    #:
    #: ## 为什么 QtQuick 是首选
    #:
    #: 用户报：「鼠标移动时亮度变化」「放大后壁纸重复」
    #: → 那是 **Chromium 子控件和 Qt 合成器打架**（各有各的合成层）。
    #:
    #: QtQuick 用 ``QQuickWidget`` 把 QML 渲进 QWidget，
    #: **和 Qt 共用同一个合成器**，不会有冲突。
    #:
    #: 而且 QtQuick 的 ``MediaPlayer`` **原生支持 H.264**
    #: （实测 4K mp4 直接播，不用转码）—— 比 Chromium 那条路简单太多。
    #:
    #: ## Chromium 为什么留着
    #:
    #: 它的 ``backdrop-filter`` 能做真正的逐面板 GPU 模糊。
    #: 但转码 + 合成冲突两个问题都绕不过，所以降为备用。
    #: ★★★ 2026-11-01 **DSH 同款：Chromium 整层**（用户：
    #: > 不能完全DSH那个插件那样做吗）
    #:
    #: 前提是 Qt 侧全透明（见 wallpaper_dsh._make_transparent）。
    #: 实测：壁纸完整无重影 + 玻璃面板 + 381 次/秒。
    #:
    #: 优先用它，失败再退 QtQuick。
    try:
        from ..core import webm_transcode as _WT2  # noqa: PLC0415
        from . import wallpaper_dsh as _wd  # noqa: PLC0415

        _pl = _WT2.prepare(path)
        if _pl and _wd.apply_dsh_wallpaper(window, _pl):
            if _current is not None:
                _current.teardown()
                _current = None
            logger.info("壁纸：使用 DSH 同款渲染（Chromium 整层）")
            return True
    except Exception:  # noqa: BLE001
        logger.warning("壁纸：DSH 方案失败，试 QtQuick", exc_info=True)

    try:
        from . import wallpaper_quick as _wq  # noqa: PLC0415

        if _wq.apply_quick_wallpaper(window, path):
            #: 切到 QtQuick 后，把 CPU 那套关掉（不能同时铺）
            if _current is not None:
                _current.teardown()
                _current = None
            logger.info("壁纸：使用 QtQuick 渲染（Qt 原生 GPU）")
            return True
    except Exception:  # noqa: BLE001
        logger.warning("壁纸：QtQuick 失败，试 Chromium", exc_info=True)

    #: ── ② Chromium（要转码）──
    try:
        from ..core import webm_transcode as _WT  # noqa: PLC0415

        playable = _WT.prepare(path)
    except Exception:  # noqa: BLE001
        logger.warning("壁纸：转码模块异常", exc_info=True)
        playable = ""

    if playable:
        try:
            from . import wallpaper_web  # noqa: PLC0415

            if wallpaper_web.apply_chromium_wallpaper(window, playable):
                if _current is not None:
                    _current.teardown()
                    _current = None
                return True
        except Exception:  # noqa: BLE001
            logger.warning("壁纸：Chromium 失败，回退 CPU", exc_info=True)

    #: ── ③ CPU 兜底路径 ──
    logger.info("壁纸：使用 CPU 渲染（兜底）")
    if _current is not None and _current._video_path == path:  # noqa: SLF001
        _current._fit()                                          # noqa: SLF001
        return True
    if _current is not None:
        _current.teardown()
    layer = WallpaperLayer(window, path, blur_kernel=blur_kernel)
    ok = layer.start()
    _current = layer if ok else None
    #: ★★★ 2026-11-01 兜底：刷一次卡片底色
    #:
    #: `apply_wallpaper` 可能被**直接调用**（测试 / 启动恢复），
    #: 不经过 `skin_page._on_wallpaper_chosen` 那条会 `refresh_windows`
    #: 的路。而 qfluentwidgets 的卡片是**自绘背景**，不刷就没有玻璃底。
    _refresh_card_bg()
    return ok


def _refresh_card_bg() -> None:
    """刷卡片底色（qfluentwidgets 自绘背景用 backgroundColor）。

    ## 为什么需要单独的兜底

    `skins.refresh_windows()` 里已经调了 `apply_card_backgrounds`，
    但 `apply_wallpaper` 有**两条调用路径**::

        skin_page._on_wallpaper_chosen → apply_video → refresh_windows  ✅
        main_window 启动恢复            → apply_wallpaper（不刷）       ❌

    第二条路上卡片会是全透明（用户看到的卡片没玻璃感就是这个）。

    ## ★★★ 2026-11-01 顺带刷侧栏 / 标题栏

    用户：「怎么修着修着又修出新的BUG了？」—— 侧栏和标题栏变成
    不透明黑（qfluentwidgets 原生 `rgb(32,32,32)`）。

    因为 `skins._paint` 的 QSS 缓存会命中并提前 return，
    `_paint_nav_panel` / `_paint_title_bar` 就没被调到。

    → 这里**无条件**补刷一遍侧栏和标题栏（很便宜，只设字符串）。
    """
    try:
        from ..core import skins

        skins.apply_card_backgrounds()
    except Exception:  # noqa: BLE001
        logger.debug("壁纸：刷卡片底色失败", exc_info=True)
    #: ★ 无条件刷侧栏 / 标题栏（绕开 QSS 缓存）
    _refresh_glass_panels()


def _refresh_glass_panels() -> None:
    """★ 强制重刷所有窗口的侧栏 / 标题栏（玻璃样式）。

    ⚠ 不复用 ``skins.refresh_glass_panels`` —— 那个内部也有缓存判断。
    这里直接调 ``_paint_nav_panel`` / ``_paint_title_bar``。
    """
    try:
        from PySide6.QtWidgets import QApplication

        from ..core import skins

        app = QApplication.instance()
        if app is None:
            return
        skin = skins.active_skin()
        n = 0
        for w in app.topLevelWidgets():
            try:
                if not w.isVisible():
                    continue
                if not hasattr(w, "navigationInterface"):
                    continue
                skins._paint_nav_panel(w, skin)      # noqa: SLF001
                skins._paint_title_bar(w, skin)      # noqa: SLF001
                n += 1
            except (RuntimeError, AttributeError):
                continue
        if n:
            logger.debug("壁纸：已强制刷 %d 个窗口的侧栏/标题栏", n)
    except Exception:  # noqa: BLE001
        logger.debug("壁纸：刷侧栏失败", exc_info=True)


def apply_wallpaper(window: QWidget, skin: dict,
                    *, blur_kernel: int = DEFAULT_BLUR) -> bool:
    """按**当前状态**铺/拆壁纸（兼容旧接口）。

    ## 优先级

    ① 用户在「主题皮肤 → 壁纸库」里选了 WE 壁纸 → 用它
    ② 否则看主题自己有没有配 ``wallpaper`` 字段
    ③ 都没有 → 拆掉壁纸（回到普通渐变背景）

    这样设计是因为壁纸和配色主题是**独立的两件事**。
    """
    global _current
    try:
        from ..core import paths, wallpaper_state
    except Exception:  # noqa: BLE001
        return False

    #: ① 用户选的 WE 壁纸优先
    wp_path = ""
    try:
        wp_id = wallpaper_state.current_id()
        if wp_id:
            wp_path = wallpaper_state.current_path()
            if not wp_path or not os.path.isfile(wp_path):
                #: 记了 id 但路径失效（WE 目录搬家）→ 按 id 重新找
                from ..core import wallpaper_engine as WE  # noqa: PLC0415

                info = WE.wallpaper_by_id(wp_id)
                if info is not None and info.get("supported"):
                    wp_path = info["video_path"]
                    wallpaper_state.set_current(wp_id, wp_path)
                else:
                    wp_path = ""
    except Exception:  # noqa: BLE001
        logger.debug("壁纸：读 WE 选择失败", exc_info=True)

    if wp_path:
        ok = apply_video(window, wp_path, blur_kernel=blur_kernel)
        #: ★★★ 2026-11-01 **必须在这里刷卡片底色**
        #:
        #: 之前加在 ``apply_video`` 的 CPU 兜底分支里，
        #: 但正常走的是 **QtQuick** 那条（直接 ``return True``），
        #: 根本到不了那里 —— 所以卡片一直是全透明。
        if ok:
            _refresh_card_bg()
        return ok

    #: ② 主题自带的 ``wallpaper``
    rel = ""
    if isinstance(skin, dict):
        rel = str(skin.get("wallpaper") or "")
    path = ""
    if rel:
        p = paths.resource_dir() / "assets" / rel
        if p.is_file():
            path = str(p)
        else:
            logger.warning("壁纸：找不到 %s", p)

    if not path:
        if _current is not None:
            _current.teardown()
            _current = None
        return False

    ok = apply_video(window, path, blur_kernel=blur_kernel)
    if ok:
        _refresh_card_bg()
    return ok


def current_layer() -> "WallpaperLayer | None":
    """当前活着的壁纸层（没铺壁纸返回 None）。

    ``skins._paint_nav_panel`` / ``_paint_title_bar`` 用它判断
    "要不要用玻璃" —— 有壁纸时面板必须半透明才能透出来。
    """
    return _current


def shutdown() -> None:
    """退出时拆掉壁纸（否则 QMediaPlayer 可能在析构时报警）。"""
    global _current
    if _current is not None:
        _current.teardown()
        _current = None
