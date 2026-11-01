# -*- coding: utf-8 -*-
"""★ Chromium 壁纸层 —— **完全照 DSH 插件的方式**实现液态玻璃。

## 用户 2026-10-31

    > 还是没有 DSH 那样自然，完全按照 DSH 那样做吧

## DSH 到底怎么做的（从源码挖出来的）

它的玻璃不是"一张模糊图贴在面板背后"，而是 **CSS 的 ``backdrop-filter``**：

.. code:: css

    /* client.js 2385~2392 行 —— 每个玻璃面板 */
    .glass {
      /* ① 顶部白高光（"湿玻璃"的反射） */
      background-image: linear-gradient(180deg,
          rgba(255, 255, 255, 0.16),
          rgba(255, 255, 255, 0.05) 38%,
          rgba(255, 255, 255, 0.02));

      /* ② ★★★ 真正的魔法：浏览器把**面板背后那一块**实时模糊 */
      backdrop-filter: blur(16px) saturate(1.8)
                       brightness(1.04) contrast(1.01);

      /* ③ 玻璃厚度：内高光 + 内阴影 + 内描边 + 外投影 */
      box-shadow:
        inset 0  1px 0 rgba(255, 255, 255, 0.32),
        inset 0 -1px 0 rgba(255, 255, 255, 0.08),
        inset 0 0 0 0.5px rgba(255, 255, 255, 0.08),
        0 12px 40px rgba(0, 0, 0, 0.12);
    }

**关键差别**：``backdrop-filter`` 是浏览器在 **GPU 上**对"面板背后那块像素"
做真实高斯模糊 —— 和 Qt 里用 ``cv2.GaussianBlur`` 对整张图 CPU 卷积完全不同。

## 为什么之前做不到"一样"

| 环节 | DSH (Chromium) | 我的 Qt 方案 |
|---|---|---|
| 模糊 | GPU 着色器，< 0.1ms | CPU 卷积，23.5ms |
| 视频解码 | GPU 硬解 | CPU 软解 |

实测相差 **235 倍** —— 参数怎么调都补不上。

## 本模块的做法

**壁纸和玻璃全部交给 Chromium**，和 DSH 一模一样：

.. code:: html

    <video class="wp">              <!-- GPU 解码的视频 -->
    <div class="glass">             <!-- backdrop-filter 玻璃层 -->
    <div class="card">...</div>     <!-- 每张卡片也是玻璃 -->

## ⚠ 前提：视频必须是 WebM

QtWebEngine 是开源 Chromium，**不含 H.264 解码器**（实测
``canPlayType('avc1...')`` 返回空）。所以 WE 的 mp4 必须先转成 WebM。

见 :mod:`src.core.webm_transcode`。
"""

from __future__ import annotations

import json
import logging
import os

from PySide6.QtCore import Qt, QUrl
from PySide6.QtWidgets import QWidget

logger = logging.getLogger(__name__)

#: 当前挂在主窗口上的 Chromium 壁纸层
_current: "ChromiumWallpaper | None" = None

#: DSH 的玻璃参数（默认值，用户可在 DSH 里改到别处）
GLASS = {
    #: 雾化（面板背后）px。
    #:
    #: ★ 2026-10-31 从 16 降到 **10** —— 用户在 DSH 里设的是 9px，
    #: 而且我们只在面板上糊（面积小），10px 观感正好。
    "blur": 10,
    "saturate": 1.8,
    "brightness": 1.04,
    "contrast": 1.01,
    "alpha": 0.60,       #: 玻璃透明度 40% → 不透明度 60%
    #: ★ 壁纸整体暗化（0 = 不暗化）。
    #:
    #: 用户反馈「背景太糊」其实一部分是**太亮**——
    #: 暗一点之后文字对比度上来，看着就不糊了。
    "tint": 0.12,
    #: ★ 面板底色的不透明度。太低会看不清文字，太高就挡住了玻璃感。
    "panel_alpha": 0.42,
}


def _html(video_url: str, glass: dict) -> str:
    """生成壁纸页面 —— 结构和 CSS 都照 DSH。

    :param video_url: ``file:///`` 形式的视频地址
    :param glass: 玻璃参数（blur / saturate / alpha …）
    """
    g = {**GLASS, **(glass or {})}
    blur = int(g["blur"])
    sat = float(g["saturate"])
    bri = float(g["brightness"])
    con = float(g["contrast"])
    alpha = float(g["alpha"])
    #: 高光层的大致亮度（DSH 是 0.16 / 0.05 / 0.02，按 alpha 缩放）
    hi = alpha / 0.60 * 0.16
    #: ★ 壁纸整体暗化（让主界面文字有对比度，但**不模糊**）
    tint = float(g.get("tint", 0.0))
    #: ★ 面板底色的不透明度（玻璃实的程度）
    panel_alpha = float(g.get("panel_alpha", 0.42))

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
  html, body {{
    margin: 0; padding: 0; width: 100%; height: 100%;
    overflow: hidden; background: transparent;
  }}
  /* ══════════════════════════════════════════════════════════════
     ① 壁纸视频（GPU 解码 + GPU 合成）
     ══════════════════════════════════════════════════════════════ */
  #wp {{
    position: fixed; inset: 0;
    width: 100%; height: 100%;
    object-fit: cover;
    /* ★ 强制 GPU 合成层 —— 让 Chromium 走硬件路径 */
    will-change: transform;
    transform: translateZ(0);
    backface-visibility: hidden;
    /* 颜色校正（对齐 DSH 的 brightness/saturate） */
    filter: saturate({sat}) brightness({bri}) contrast({con});
  }}

  /* ══════════════════════════════════════════════════════════════
     ② 玻璃层 —— 只覆盖面板区域，不是整屏

     修「背景太糊 + 鼠标一动就闪」：
     旧版把 backdrop-filter 加到铺满整屏的元素上
     （position fixed + inset 0）→ 整片壁纸都被糊，且每帧重算全屏
     像素导致鼠标一动就闪。

     现在 .glass 不模糊，只做轻微暗化；
     真正的模糊由 .panel-glass（面板）各自做 —— 面积小、GPU 搞定。
     ══════════════════════════════════════════════════════════════ */
  .glass {{
    position: fixed; inset: 0;
    /* 只加一层极淡的暗化，让文字有基础对比度 —— **不模糊** */
    background: rgba(0, 0, 0, {tint:.3f});
    pointer-events: none;
  }}

  /* 面板玻璃（侧栏 / 标题栏 / 卡片共用的基类）*/
  .panel-glass {{
    position: fixed;
    background-image: linear-gradient(180deg,
        rgba(255, 255, 255, {hi:.4f}),
        rgba(255, 255, 255, {hi * 0.31:.4f}) 38%,
        rgba(255, 255, 255, {hi * 0.12:.4f}));
    background-color: rgba(12, 10, 24, {panel_alpha:.3f});
    -webkit-backdrop-filter: blur({blur}px) saturate({sat}) brightness({bri}) contrast({con});
    backdrop-filter: blur({blur}px) saturate({sat}) brightness({bri}) contrast({con});
    /* ★ 固定合成层 —— 避免鼠标移动引发重绘闪烁 */
    will-change: auto;
    transform: translateZ(0);
    contain: paint;
    pointer-events: none;
  }}

  /* ══════════════════════════════════════════════════════════════
     ③ 卡片玻璃（由 JS 动态创建，用 .panel-glass 的配方 + 圆角阴影）
     ══════════════════════════════════════════════════════════════ */
  .card-glass {{
    position: fixed;
    border-radius: 10px;
    background-image: linear-gradient(180deg,
        rgba(255, 255, 255, {hi * 2.2:.4f}),
        rgba(255, 255, 255, 0.02));
    -webkit-backdrop-filter: blur({blur}px) saturate({sat}) brightness({bri}) contrast({con});
    backdrop-filter: blur({blur}px) saturate({sat}) brightness({bri}) contrast({con});
    box-shadow:
      inset 0  1px 0 rgba(255, 255, 255, 0.32),
      inset 0 -1px 0 rgba(255, 255, 255, 0.08),
      inset 0 0 0 0.5px rgba(255, 255, 255, 0.08),
      0 12px 40px rgba(0, 0, 0, 0.12);
    pointer-events: none;
  }}
</style></head>
<body>
  <video id="wp" autoplay loop muted playsinline preload="auto"
         disablepictureinpicture></video>
  <div class="glass" id="glass"></div>
<script>
  const V = document.getElementById('wp');
  V.src = {json.dumps(video_url)};
  V.play().catch(function (e) {{ console.log('autoplay blocked', e); }});

  //: 调试：把状态写到 title，Qt 端可以读回来
  V.addEventListener('loadeddata', function () {{
    document.title = 'READY:' + V.videoWidth + 'x' + V.videoHeight;
  }});
  V.addEventListener('error', function () {{
    document.title = 'ERROR:' + ((V.error && V.error.code) || '?');
  }});

  //: 卡片玻璃由 Qt 通过 runJavaScript 注入（见 ChromiumWallpaper.set_cards）
  window.__setCards = function (rects) {{
    document.querySelectorAll('.card-glass').forEach(n => n.remove());
    rects.forEach(function (r) {{
      const d = document.createElement('div');
      d.className = 'card-glass';
      d.style.left = r[0] + 'px';
      d.style.top = r[1] + 'px';
      d.style.width = r[2] + 'px';
      d.style.height = r[3] + 'px';
      document.body.appendChild(d);
    }});
  }};
</script>
</body></html>"""


class ChromiumWallpaper:
    """用 ``QWebEngineView`` 铺一层 GPU 壁纸 + ``backdrop-filter`` 玻璃。

    ## 和之前版本的区别

    旧版：壁纸层只播视频，玻璃由 Qt QSS 提供（CPU 半透明）。
    新版：**玻璃也在 Web 层用 ``backdrop-filter`` 做** —— 和 DSH 一致。

    ## 尺寸同步

    ``set_cards(rects)`` 把卡片矩形传给页面，页面用 ``.card-glass``
    在同样的位置画 ``backdrop-filter`` 玻璃 —— 这样卡片背后是真的
    被 GPU 模糊过的壁纸，而不是 Qt 用 CPU 糊出来的图。
    """

    def __init__(self, window: QWidget, video_path: str,
                 *, glass: dict | None = None):
        self._window = window
        self._video_path = str(video_path or "")
        self._glass = dict(glass or {})
        self._view = None
        self._active = False
        self._watcher = None
        self._last_rects: list = []

    @property
    def active(self) -> bool:
        return self._active

    @property
    def video_path(self) -> str:
        return self._video_path

    def start(self) -> bool:
        if self._active:
            return True
        if not self._video_path or not os.path.isfile(self._video_path):
            logger.warning("Chromium 壁纸：视频不存在 %s", self._video_path)
            return False
        try:
            from PySide6.QtWebEngineWidgets import QWebEngineView
        except Exception:  # noqa: BLE001
            logger.warning("Chromium 壁纸：QtWebEngine 不可用", exc_info=True)
            return False

        try:
            win = self._window
            win.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

            view = QWebEngineView(win)
            #: ★ 透明背景 —— 让主界面控件（在上面）和壁纸共存
            try:
                from PySide6.QtGui import QColor

                view.page().setBackgroundColor(QColor(0, 0, 0, 255))
            except Exception:  # noqa: BLE001
                pass
            #: ★ 不接鼠标 —— 点击要穿到主界面
            view.setAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            view.setGeometry(win.rect())
            view.lower()
            view.show()

            #: ★★★ 2026-10-31 **必须用 HTTP，不能用 file://**
            #:
            #: 实测（见 media_server 模块文档）：``file://`` 喂给
            #: ``setHtml()`` 的页面，Chromium 一律报
            #: ``MEDIA_ERR_SRC_NOT_SUPPORTED``（ERR4）—— 哪怕文件是
            #: 合法 WebM、哪怕 ``canPlayType`` 说 probably。
            #: 根因是 ``setHtml()`` 的**同源策略**。
            #:
            #: 走本地 HTTP 服务就正常（实测 READY:800）。
            #: DSH 那个插件也是起 HTTP 给视频用的。
            from ..core import media_server  # noqa: PLC0415

            base = media_server.start(os.path.dirname(self._video_path))
            if base:
                url = media_server.url_for(self._video_path)
                logger.info("Chromium 壁纸：视频走 HTTP %s", url)
            else:
                #: 服务起不来 → 退回 file://（大概率播不了，但有日志可查）
                url = QUrl.fromLocalFile(self._video_path).toString()
                logger.warning("Chromium 壁纸：HTTP 服务不可用，退回 file://")

            #: ★★★ 关键：**用 setUrl 加载 HTTP 页面**，不用 setHtml
            #:
            #: `setHtml` 给的页面 baseUrl 是 about:blank / file 目录，
            #: Chromium 认为它和视频（http://）**不同源** → 拒绝加载视频
            #: （ERR4）。实测把页面也从同一个 HTTP 服务取就好了。
            media_server.set_page(_html(url, self._glass))
            page = media_server.page_url()
            if page:
                logger.info("Chromium 壁纸：页面走 HTTP %s", page)
                view.setUrl(QUrl(page))
            else:
                view.setHtml(_html(url, self._glass))

            self._view = view
            self._install_resize_hook()
            self._install_card_timer()
            self._active = True
            logger.info("Chromium 壁纸：已启用 %s（blur=%s）",
                        os.path.basename(self._video_path),
                        self._glass.get("blur", GLASS["blur"]))
            return True
        except Exception:  # noqa: BLE001
            logger.warning("Chromium 壁纸：启动失败", exc_info=True)
            self.teardown()
            return False

    def _install_card_timer(self) -> None:
        """★ 定时把卡片矩形同步给 Web 层（玻璃效果的关键）。

        ## 为什么需要

        用户截图：壁纸显示了，但**卡片背后没有模糊**（只剩 Qt 的深色边）。
        因为 ``set_cards`` 定义了却**没人调用** ——
        ``wallpaper_layer._sync_card_rects_fast`` 只管 CPU 那条路径。

        现在由 Chromium 层自己起一个 400ms 定时器扫卡片矩形，
        传给页面（页面用 ``.card-glass`` 画 ``backdrop-filter``）。

        ⚠ 400ms 不是每帧 —— 卡片位置只在切页/滚动/重排时变。
        """
        try:
            from PySide6.QtCore import QTimer

            self._card_timer = QTimer(self._window)
            self._card_timer.setInterval(400)
            self._card_timer.timeout.connect(self._sync_cards)
            #: ★ 顺手同步视图尺寸（eventFilter 的 _Watcher 可能被 GC 掉）
            self._card_timer.timeout.connect(self._fit)
            self._card_timer.start()
            #: 立刻同步一次（等布局稳定）
            QTimer.singleShot(300, self._sync_cards)
        except Exception:  # noqa: BLE001
            logger.warning("Chromium 壁纸：装卡片定时器失败", exc_info=True)

    def _sync_cards(self) -> None:
        """扫当前页面的卡片矩形，传给 Web 层。"""
        try:
            from PySide6.QtCore import QRect
            from PySide6.QtWidgets import QWidget

            win = self._window
            stacked = getattr(win, "stackedWidget", None)
            page = None
            if stacked is not None:
                try:
                    page = stacked.currentWidget()
                except (RuntimeError, AttributeError):
                    page = None
            root = page if page is not None else win
            if root is None:
                return

            names = {
                "CardWidget", "SimpleCardWidget", "ElevatedCardWidget",
                "HeaderCardWidget", "GroupHeaderCardWidget", "ToolCard",
            }
            rects = []
            win_rect = win.rect()
            for child in root.findChildren(QWidget):
                try:
                    if type(child).__name__ not in names:
                        continue
                    if not child.isVisible():
                        continue
                    sz = child.size()
                    if sz.width() < 40 or sz.height() < 30:
                        continue
                    tl = child.mapTo(win, child.rect().topLeft())
                    r = QRect(tl, sz).intersected(win_rect)
                    if r.isValid() and not r.isEmpty():
                        rects.append(r)
                    if len(rects) >= 120:
                        break
                except (RuntimeError, AttributeError):
                    continue
            self.set_cards(rects)
        except Exception:  # noqa: BLE001
            logger.debug("Chromium 壁纸：同步卡片失败", exc_info=True)

    def set_cards(self, rects) -> None:
        """把卡片矩形传给页面（页面用 ``backdrop-filter`` 画玻璃）。

        :param rects: ``[QRect, ...]``
        """
        if self._view is None:
            return
        try:
            data = [[int(r.x()), int(r.y()), int(r.width()),
                     int(r.height())] for r in (rects or [])]
            #: 没变就不重复注入（``runJavaScript`` 有 IPC 开销）
            if data == self._last_rects:
                return
            self._last_rects = data
            js = f"window.__setCards && window.__setCards({json.dumps(data)});"
            self._view.page().runJavaScript(js)
        except Exception:  # noqa: BLE001
            logger.debug("Chromium 壁纸：注入卡片失败", exc_info=True)

    def _install_resize_hook(self) -> None:
        try:
            from PySide6.QtCore import QEvent, QObject

            class _Watcher(QObject):
                def __init__(self, layer):
                    super().__init__()
                    self._layer = layer

                def eventFilter(self, obj, event):   # noqa: N802
                    if event.type() == QEvent.Type.Resize:
                        self._layer._fit()           # noqa: SLF001
                    return False

            self._watcher = _Watcher(self)
            self._window.installEventFilter(self._watcher)
        except Exception:  # noqa: BLE001
            logger.warning("Chromium 壁纸：装 resize 钩子失败", exc_info=True)

    def _fit(self) -> None:
        """把 Web 视图铺满主窗口。"""
        try:
            if self._view is None or self._window is None:
                return
            r = self._window.rect()
            if self._view.geometry() != r:
                self._view.setGeometry(r)
            self._view.lower()
        except Exception:  # noqa: BLE001
            pass

    def teardown(self) -> None:
        self._active = False
        try:
            if getattr(self, "_card_timer", None) is not None:
                self._card_timer.stop()
                self._card_timer.deleteLater()
        except Exception:  # noqa: BLE001
            pass
        self._card_timer = None
        try:
            if self._view is not None:
                self._view.stop()
                self._view.setPage(None)
                self._view.setParent(None)
                self._view.deleteLater()
        except Exception:  # noqa: BLE001
            pass
        self._view = None
        try:
            if self._watcher is not None:
                self._window.removeEventFilter(self._watcher)
        except Exception:  # noqa: BLE001
            pass
        self._watcher = None
        logger.info("Chromium 壁纸：已拆除")


def apply_chromium_wallpaper(window: QWidget, video_path: str,
                             *, glass: dict | None = None) -> bool:
    """铺一层 Chromium 壁纸（全局单例）。"""
    global _current
    path = str(video_path or "")
    if not path or not os.path.isfile(path):
        logger.warning("Chromium 壁纸：视频不存在 %s", path)
        if _current is not None:
            _current.teardown()
            _current = None
        return False
    if _current is not None and _current.video_path == path:
        _current._fit()                                          # noqa: SLF001
        return True
    if _current is not None:
        _current.teardown()
    layer = ChromiumWallpaper(window, path, glass=glass)
    ok = layer.start()
    _current = layer if ok else None
    return ok


def current_layer() -> "ChromiumWallpaper | None":
    return _current


def shutdown() -> None:
    global _current
    if _current is not None:
        _current.teardown()
        _current = None
