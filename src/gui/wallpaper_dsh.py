# -*- coding: utf-8 -*-
"""★ 壁纸层（DSH 同款）—— Chromium 整层 + Qt 全透明。

## ★★★ 2026-11-01 **最终方案**（用户：「不能完全DSH那个插件那样做吗」）

答案是**能**，但前提是 **Qt 侧必须完全透明**。

## 为什么之前 Chromium 方案失败

之前把 ``QWebEngineView`` 当**子控件**铺在 Qt 控件下面，但
Qt 侧（侧栏、内容区）还画着**不透明的 QSS 背景** ——
于是 Chromium 被完全遮住，只露出一点，看着像"重影/闪烁"。

**关键前提**：

    win.setAttribute(WA_TranslucentBackground)
    win.setAttribute(WA_StyledBackground)
    win.setStyleSheet("background: transparent")
    #: + skins 的 _walled 分支让侧栏/内容区也透明

只要所有 Qt 背景都是透明的，Chromium 就完整透出来，
**和 DSH（Electron，整个窗口就是 Chromium）一模一样**。

## 实测（真实 MainWindow + 1200x760）

    页面标题: READY:1600x900      ← 视频播放
    面板: 2 个（侧栏 + 标题栏玻璃）
    事件循环: 381 次/秒            ← 不卡
    截图: 壁纸完整、无重影、玻璃面板正确

## 架构

    ┌─────────────────────────────────────────┐
    │ QWebEngineView（铺满，最低层）            │
    │   <video>  ← GPU 解码                    │
    │   <div class=glass>  ← backdrop-filter   │
    ├─────────────────────────────────────────┤
    │ Qt 控件（完全透明背景）                    │
    │   侧栏文字 / 卡片 / 按钮                   │
    └─────────────────────────────────────────┘

## 参数来自设置（照抄插件 settings-schema.js）

  * ``scrim``      整体暗化 0~1（默认 0.25）
  * ``blur``       面板雾化 px（默认 16）
  * ``glassAlpha`` 玻璃透明度 %（默认 20）
  * ``glassColor`` 玻璃底色
  * ``border``     边框强度
"""

from __future__ import annotations

import json
import logging
import os

from PySide6.QtCore import Qt, QUrl
from PySide6.QtWidgets import QWidget

logger = logging.getLogger(__name__)

#: 当前壁纸层
_current: "DshWallpaper | None" = None

#: 跟随主窗口的间隔（ms）
FOLLOW_MS = 200

#: 面板矩形同步间隔（ms）—— 和卡片位置变化频率匹配
PANEL_MS = 300

#: 页面模板
#:
#: ⚠ 用 ``@@X@@`` 占位而不是 ``%`` / ``{}`` ——
#: CSS 里全是 ``{ }`` 和 ``%``，用 ``%`` 格式化会炸。
_PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
  html, body {
    margin: 0; padding: 0; width: 100%; height: 100%;
    overflow: hidden; background: transparent;
  }
  /* ① 壁纸视频 */
  #wp {
    position: fixed; inset: 0;
    width: 100%; height: 100%;
    object-fit: cover;
    /* ★★★ 2026-11-01 移除 GPU 层强制提升
     *
     * 用户截图：窗口放大后右侧一大块**重复画面**。
     *
     * 根因：will-change / translateZ / backface-visibility 这三行
     * 会强制 Chromium 把 <video> 提升为**独立合成层**。
     * 窗口变大时那个层的缓冲区不会重新分配 ——
     * 多出来的区域就**平铺旧内容**。
     *
     * （``object-fit: cover`` 本身没问题，它是标准缩放。）
     *
     * → 去掉这三行，让视频留在主合成层，跟着 viewport 一起重绘。
     */
    /* ★ 颜色校正 —— 对齐 DSH 的亮度/对比度/饱和度 */
    /*   DSH 实测：亮度 75% / 对比度 110% / 饱和度 150% */
    filter: brightness(@@BRIGHT@@) contrast(@@CONTRAST@@) saturate(@@SATURATE@@);
    opacity: @@WALLPAPER_OPACITY@@;
  }
  /* ② 整体暗化（插件里的 scrim） */
  #scrim {
    position: fixed; inset: 0;
    background: rgba(0, 0, 0, @@SCRIM@@);
    pointer-events: none;
  }
  /* ③ 面板玻璃容器（子元素由 JS 动态创建） */
  #panels { position: fixed; inset: 0; pointer-events: none; }
</style></head>
<body>
  <video id="wp" autoplay loop muted playsinline preload="auto"></video>
  <div id="scrim"></div>
  <div id="panels"></div>
<script>
  const V = document.getElementById('wp');
  //: ★★★ 2026-11-01 **照 DSH 的做法：持久页面 + 运行时换 src**
  //:
  //: DSH 插件（client.js L18383）::
  //:
  //:     video.src = selection.url;
  //:     video.load();
  //:
  //: 它**不重新加载页面**，只在同一个 <video> 上换 src。
  //: 这样没有页面缓存问题，切换是即时的。
  //: ★★★ 2026-11-01 **彻底重建 <video> 元素**
  //:
  //: 用户：「还是不能切换」—— DOM 里 src 确实换了，但画面不动。
  //:
  //: 试过 `V.src = url; V.load();` 无效 —— Chromium 里
  //: 已经解码过的 media 元素复用旧纹理，换 src 不重绘。
  //:
  //: → 直接**删除旧元素、创建新的**，这样 100% 重新解码。
  window.__setVideo = function (url) {
    try {
      const old = document.getElementById('wp');
      const parent = old.parentNode;
      const neo = document.createElement('video');
      neo.id = 'wp';
      neo.autoplay = true;
      neo.loop = true;
      neo.muted = true;
      neo.setAttribute('playsinline', '');
      neo.setAttribute('preload', 'auto');
      neo.src = url;
      parent.replaceChild(neo, old);
      neo.addEventListener('loadeddata', function () {
        document.title = 'READY:' + neo.videoWidth + 'x' + neo.videoHeight;
      });
      neo.addEventListener('error', function () {
        document.title = 'ERROR:' + ((neo.error && neo.error.code) || '?');
      });
      neo.load();
      neo.play().catch(function(){});
      return true;
    } catch (e) { return false; }
  };
  //: 首次用初始 URL（@@URL@@ 由 Qt 填）
  V.src = @@URL@@;
  V.addEventListener('loadeddata', function () {
    document.title = 'READY:' + V.videoWidth + 'x' + V.videoHeight;
  });
  V.addEventListener('error', function () {
    document.title = 'ERROR:' + ((V.error && V.error.code) || '?');
  });
  V.play().catch(function(){});

  //: ★ 面板玻璃 —— 由 Qt 传矩形，用 DSH 的配方画
  //:
  //: 配方（client.js L2195-2197）::
  //:     背景 = 深藏青 #0d1524 @ floor 0.59 + 玻璃色 @ (1-floor)*alpha
  //:     模糊 = backdrop-filter: blur(16px) saturate(1.8)
  //:
  //: ★★★ 2026-11-01 **侧栏和卡片用不同不透明度**
  //:
  //: 用户截图实测（同位置采样）::
  //:
  //:     DSH 侧栏     #0a0913  luma=0.039   ← 几乎纯黑
  //:     我们的侧栏    #1c2639  luma=0.146   ← 亮 3.7 倍
  //:
  //: → 侧栏 ``kind='sidebar'`` 用 92% 实色（几乎不透）
  //:   卡片 ``kind='card'`` 保持 59%（有玻璃透光感）
  const GLASS_BG = '@@GLASS_BG@@';
  const GLASS_BORDER = '@@GLASS_BORDER@@';
  const BLUR = @@BLUR@@;
  const RADIUS = @@RADIUS@@;
  //: 侧栏实色底（#0a0913 = DSH 实测值）
  const SIDEBAR_BG = 'rgba(10, 9, 19, 0.92)';

  window.__setPanels = function (rects) {
    const box = document.getElementById('panels');
    while (box.firstChild) box.removeChild(box.firstChild);
    rects.forEach(function (r) {
      const d = document.createElement('div');
      const radius = (r[4] !== undefined) ? r[4] : RADIUS;
      const kind = r[5] || 'card';
      const bg = (kind === 'sidebar') ? SIDEBAR_BG : GLASS_BG;
      d.style.cssText =
        'position:fixed;' +
        'left:' + r[0] + 'px;top:' + r[1] + 'px;' +
        'width:' + r[2] + 'px;height:' + r[3] + 'px;' +
        'border-radius:' + radius + 'px;' +
        'background-image:linear-gradient(180deg,' +
          'rgba(255,255,255,@@HI@@),rgba(255,255,255,0.02));' +
        'background-color:' + bg + ';' +
        'border:1px solid ' + GLASS_BORDER + ';' +
        '-webkit-backdrop-filter:blur(' + BLUR + 'px) saturate(1.8);' +
        'backdrop-filter:blur(' + BLUR + 'px) saturate(1.8);' +
        'pointer-events:none;';
      box.appendChild(d);
    });
  };
</script>
</body></html>"""


class DshWallpaper:
    """DSH 同款：Chromium 整层铺满 + Qt 侧全透明。"""

    def __init__(self, window: QWidget, video_path: str):
        self._window = window
        self._video_path = str(video_path or "")
        self._view = None
        self._active = False
        self._follow_timer = None
        self._panel_timer = None
        self._last_panels: list = []
        self._saved_attrs = None

    @property
    def active(self) -> bool:
        return self._active

    @property
    def video_path(self) -> str:
        return self._video_path

    def start(self) -> bool:
        """建 Chromium 层 + 让 Qt 侧透明。"""
        if self._active:
            return True
        if not self._video_path or not os.path.isfile(self._video_path):
            logger.warning("壁纸：视频不存在 %s", self._video_path)
            return False
        try:
            from PySide6.QtWebEngineWidgets import QWebEngineView
        except Exception:  # noqa: BLE001
            logger.warning("壁纸：QtWebEngine 不可用", exc_info=True)
            return False

        try:
            from PySide6.QtGui import QColor

            from ..core import media_server, wallpaper_settings as WS

            #: ① HTTP 服务（必须 —— file:// 会被同源策略拦）
            base = media_server.start(os.path.dirname(self._video_path))
            if not base:
                logger.warning("壁纸：HTTP 服务启动失败")
                return False

            #: ② 生成页面
            lay = WS.glass_layers()
            br, bg, bb = lay["base_rgb"]
            gr, gg, gb = lay["glass_rgb"]
            floor = float(lay["floor"])
            ga = float(lay["glass_alpha"])
            alpha = min(1.0, floor + (1 - floor) * ga)
            wr = floor / alpha if alpha > 0 else 1.0
            wg = ga * (1 - floor) / alpha if alpha > 0 else 0.0
            cr = int(br * wr + gr * wg)
            cg = int(bg * wr + gg * wg)
            cb = int(bb * wr + gb * wg)
            glass_bg = f"rgba({cr}, {cg}, {cb}, {alpha:.3f})"
            brd = float(WS.get("border") or 0.35)
            glass_border = f"rgba(255, 255, 255, {brd * 0.35:.3f})"
            hi = float(WS.get("border") or 0.35) * 0.30
            page = (_PAGE
                    .replace("@@URL@@", json.dumps(
                        media_server.url_for(self._video_path)))
                    .replace("@@SCRIM@@", f"{float(WS.get('scrim') or 0):.3f}")
                    .replace("@@GLASS_BG@@", glass_bg)
                    .replace("@@GLASS_BORDER@@", glass_border)
                    .replace("@@BLUR@@", str(int(WS.get("blur") or 16)))
                    .replace("@@RADIUS@@", "10")
                    .replace("@@HI@@", f"{hi:.3f}")
                    .replace("@@BRIGHT@@",
                             f"{float(WS.get('backgroundBrightness') or 100) / 100:.2f}")
                    .replace("@@CONTRAST@@",
                             f"{float(WS.get('backgroundContrast') or 100) / 100:.2f}")
                    .replace("@@SATURATE@@",
                             f"{float(WS.get('backgroundSaturate') or 100) / 100:.2f}")
                    .replace("@@WALLPAPER_OPACITY@@",
                             f"{1.0 - float(WS.get('wallpaperOpacity') or 0) / 100:.2f}"))
            media_server.set_page(page)

            #: ③ 让 Qt 侧透明
            self._make_transparent()

            #: ④ Chromium 铺满最低层
            win = self._window
            view = QWebEngineView(win)
            view.page().setBackgroundColor(QColor(0, 0, 0, 255))
            view.setAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            #: ★★★ 2026-11-01 **URL 必须带时间戳**
            #:
            #: 用户：「没有成功切换」—— 状态变了、视频换了、日志正常，
            #: 但画面还是上一个壁纸。
            #:
            #: 根因：Chromium 按 URL 缓存。两次都用
            #: `http://127.0.0.1:PORT/wallpaper`，它认为**页面没变**，
            #: 直接复用旧 DOM（里面是旧视频的 src）。
            #:
            #: → 加 `?t=<毫秒>` 强制重新请求 + 重新解析。
            view.setUrl(QUrl(media_server.page_url(bust=True)))
            view.show()
            view.lower()
            self._view = view

            self._install_timers()
            self._active = True
            #: ★★★ 2026-11-01 **抽主色并应用到主题**
            #:
            #: 用户：「坎特蕾拉那个是以紫色为主题，按钮颜色要随之变化」。
            #:
            #: 抓一帧 → `color_extract.extract_primary` → 应用配色。
            #: 用**独立 QMediaPlayer** 解码（不依赖屏幕截图）。
            self._schedule_color_extract()
            logger.info("壁纸：已启用 %s（DSH 同款 Chromium 整层）",
                        os.path.basename(self._video_path))
            return True
        except Exception:  # noqa: BLE001
            logger.warning("壁纸：启动失败", exc_info=True)
            self.teardown()
            return False

    def switch_video(self, video_path: str) -> bool:
        """★ 切换视频（**不重建视图**，照 DSH 的做法）。

        ## ★★★ 2026-11-01 用户：「还是不能切换啊，你参考dsh里是怎么做的吧」

        DSH 插件（`client.js` L18383）换壁纸是这样::

            video.src = selection.url;
            video.load();

        **不重新加载页面**，只在同一个 `<video>` 上换 `src`。

        我们之前每次都 `teardown()` + 重建 `QWebEngineView` +
        `setUrl(带时间戳)` —— 太多环节可能失败（缓存、销毁时序、
        透明背景恢复…），而且慢（每次重建 Chromium 页面 ~1 秒）。

        → 改成：**视图只建一次，换壁纸只用 JS 换 src**。

        :param video_path: 新的 webm 路径（必须已在 HTTP 服务目录下）
        :return: 是否成功
        """
        if self._view is None or not self._active:
            return False
        try:
            from ..core import media_server

            url = media_server.url_for(video_path)
            if not url:
                logger.warning("壁纸：切换失败，HTTP URL 为空")
                return False
            js = (f"window.__setVideo && window.__setVideo("
                  f"{json.dumps(url)});")
            logger.info("壁纸：[换 src] url=%s", url)
            self._view.page().runJavaScript(js)
            self._video_path = str(video_path)
            logger.info("壁纸：切换视频 → %s", os.path.basename(video_path))
            #: ★★★ 2026-11-01 **切换后必须补刷侧栏 / 标题栏**
            #:
            #: 实测：切换壁纸后 `侧栏 rgba=False`（玻璃丢了，
            #: 退回 qfluentwidgets 原生黑）。
            #:
            #: 因为换 src 这条路不经过 `skins._paint`，
            #: 侧栏的玻璃 QSS 没人设。
            try:
                from . import wallpaper_layer as _wl

                _wl._refresh_glass_panels()          # noqa: SLF001
            except Exception:  # noqa: BLE001
                pass
            #: 重新抽主色
            self._schedule_color_extract()
            return True
        except Exception:  # noqa: BLE001
            logger.warning("壁纸：切换视频失败", exc_info=True)
            return False

    def _make_transparent(self) -> None:
        """把主窗口所有 Qt 背景设成透明。

        ## 这是"完全像 DSH"的关键

        Chromium 在最低层，如果 Qt 侧还有不透明背景 → 全被遮住。

        ## ⚠ 不要 setStyleSheet

        ``win.setStyleSheet("background: transparent")`` 是**整体替换**
        窗口 QSS —— 会把皮肤的玻璃样式（侧栏 / 标题栏）整个冲掉，
        退化成 qfluentwidgets 的原生黑底。

        透明化靠这两条就够：
          ① ``WA_TranslucentBackground``（窗口本身透明）
          ② ``skins.build_qss`` 的 ``_walled`` 分支
        """
        try:
            win = self._window
            #: 记下原状态，teardown 时还原
            self._saved_attrs = (
                win.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground),
                win.testAttribute(Qt.WidgetAttribute.WA_StyledBackground),
            )
            win.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            win.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            logger.info("壁纸：主窗口已设为透明背景（%dx%d）",
                        win.width(), win.height())
        except Exception:  # noqa: BLE001
            logger.warning("壁纸：设置透明失败", exc_info=True)

    def _restore_opaque(self) -> None:
        """还原主窗口背景（取消壁纸时）。

        ## ★★★ 2026-11-01 不要 ``setStyleSheet("")``

        那会把**皮肤的整套 QSS 清空**（侧栏 / 标题栏 / 卡片全退原生黑）。
        正确做法是：只关透明属性，再让 ``skins`` 重刷一遍。
        """
        try:
            win = self._window
            win.setAttribute(
                Qt.WidgetAttribute.WA_TranslucentBackground, False)
            #: 让皮肤系统重新铺（会走「没壁纸」分支，用不透明底）
            try:
                from ..core import skins as _sk

                _sk.invalidate_paint_cache()
                _sk.refresh_windows()
            except Exception:  # noqa: BLE001
                pass
            self._saved_attrs = None
        except Exception:  # noqa: BLE001
            pass

    def _install_timers(self) -> None:
        try:
            from PySide6.QtCore import QTimer

            self._follow_timer = QTimer(self._window)
            self._follow_timer.setInterval(FOLLOW_MS)
            self._follow_timer.timeout.connect(self._follow)
            self._follow_timer.start()

            self._panel_timer = QTimer(self._window)
            self._panel_timer.setInterval(PANEL_MS)
            self._panel_timer.timeout.connect(self._sync_panels)
            self._panel_timer.start()

            self._follow()
        except Exception:  # noqa: BLE001
            logger.warning("壁纸：装定时器失败", exc_info=True)

    def _follow(self) -> None:
        """让 Chromium 跟上主窗口尺寸。"""
        try:
            win = self._window
            v = self._view
            if v is None or win is None:
                return
            if not win.isVisible():
                if v.isVisible():
                    v.hide()
                return
            target = (0, 0, max(2, win.width()), max(2, win.height()))
            cur = (v.x(), v.y(), v.width(), v.height())
            if cur != target:
                v.setGeometry(*target)
                #: ★★★ 2026-11-01 **修「放大后右侧平铺」**
                #:
                #: 用户截图：窗口放大到 1554 后，右边 ~40% 是重复画面。
                #:
                #: 诊断结论（DOM 采样）::
                #:
                #:     innerWidth=1554  ← DOM 认为自己是 1554
                #:     clientWidth=1554
                #:     但实际渲染 surface 只有 ~1210
                #:
                #: 也就是 **DOM 尺寸对了，但 Chromium 的合成表面没重新分配**
                #: → 多出来的部分平铺旧内容。
                #:
                #: `QWebEngineView` 不会自动处理这个。
                #: 唯一可靠的办法：**尺寸变化时重建一次视图**。
                #: 代价 ~800ms，只在拖动窗口时发生（用户能接受）。
                _dw = abs(target[2] - cur[2])
                _dh = abs(target[3] - cur[3])
                if _dw > 100 or _dh > 100:
                    self._rebuild_view()
                    return
                v.update()
                v.lower()
            if not v.isVisible():
                v.show()
                v.lower()
        except (RuntimeError, AttributeError):
            pass

    def _rebuild_view(self) -> None:
        """★ 尺寸剧变时**重建 Web 视图**（修「放大后右侧平铺」）。

        ## 为什么必须重建

        ``QWebEngineView`` 的合成表面（surface）在尺寸变化时**不会**
        自动重新分配 —— DOM 的 ``innerWidth`` 变了（实测 1554），
        但实际渲染区域还是旧的（约 1210）。多出来的部分就
        **平铺最后一列/最后一行像素**。

        试过无效：``setViewportSize`` / ``dispatchEvent('resize')`` /
        ``setUrl`` 重载 / ``update()`` / 移除 ``will-change``。

        唯一有效：**销毁旧视图，按新尺寸建一个新的**。
        代价约 0.8 秒，只在拖动窗口大幅缩放时触发。
        """
        try:
            from PySide6.QtCore import QTimer, QUrl
            from PySide6.QtGui import QColor
            from PySide6.QtWebEngineWidgets import QWebEngineView

            from ..core import media_server

            win = self._window
            old = self._view
            #: 先把旧的藏起来（避免闪一下旧画面）
            if old is not None:
                try:
                    old.hide()
                except Exception:  # noqa: BLE001
                    pass

            view = QWebEngineView(win)
            view.page().setBackgroundColor(QColor(0, 0, 0, 255))
            view.setAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            view.setGeometry(0, 0, max(2, win.width()), max(2, win.height()))
            view.setUrl(QUrl(media_server.page_url(bust=True)))
            view.show()
            view.lower()
            self._view = view

            #: 旧视图**延后**销毁（立刻删可能让 Chromium 崩）
            if old is not None:
                def _kill() -> None:
                    try:
                        old.stop()
                        old.setPage(None)
                        old.setParent(None)
                        old.deleteLater()
                    except Exception:  # noqa: BLE001
                        pass

                QTimer.singleShot(1200, _kill)
            logger.info("壁纸：视图已按 %dx%d 重建",
                        win.width(), win.height())
        except Exception:  # noqa: BLE001
            logger.warning("壁纸：重建视图失败", exc_info=True)

    def _schedule_color_extract(self) -> None:
        """延迟抓帧抽主色（等视频解码就绪）。"""
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
        """抓一帧 → 抽主色 → 应用到主题。"""
        try:
            self._color_tries = getattr(self, "_color_tries", 0) + 1
            if self._color_tries > 10:
                self._color_timer.stop()
                return
            img = self._grab_video_frame()
            if img is None:
                return
            from ..core import color_extract as CE

            luma = CE.average_luma(img)
            if luma < 0.02:
                return
            primary = CE.extract_primary(img)
            try:
                from ..core import wallpaper_settings as _WS

                scrim = float(_WS.get("scrim") or 0.0)
                tint = scrim if scrim > 0 else CE.suggest_tint(img)
            except Exception:  # noqa: BLE001
                tint = CE.suggest_tint(img)
            self._color_timer.stop()
            logger.info("壁纸：主色=%s 亮度=%.2f 暗化=%.2f",
                        primary, luma, tint)
            try:
                from ..core import skins

                skins.apply_wallpaper_palette(primary, tint)
            except Exception:  # noqa: BLE001
                logger.debug("壁纸：应用配色失败", exc_info=True)
            #: ★★★ 2026-11-01 **延迟补刷侧栏 / 标题栏**
            #:
            #: 实测：切换壁纸后 `侧栏 rgba=False`（玻璃丢了）。
            #:
            #: 原因：`apply_wallpaper_palette` 内部会
            #: `invalidate_paint_cache()` + `refresh_windows()`，
            #: 那次 `_paint` 会用**不透明渐变**刷侧栏（它读到的
            #: `_has_wallpaper()` 状态可能还是旧的）。
            #:
            #: → 用 `QTimer.singleShot` 延到**事件循环下一轮**
            #:   再刷（那时所有同步的重刷都做完了，我们最后落笔）。
            def _late_refresh() -> None:
                try:
                    from . import wallpaper_layer as _wl

                    _wl._refresh_glass_panels()      # noqa: SLF001
                except Exception:  # noqa: BLE001
                    pass

            try:
                from PySide6.QtCore import QTimer

                QTimer.singleShot(0, _late_refresh)
                QTimer.singleShot(300, _late_refresh)
            except Exception:  # noqa: BLE001
                _late_refresh()
        except Exception:  # noqa: BLE001
            logger.debug("壁纸：抽主色失败", exc_info=True)

    def _grab_video_frame(self):
        """用临时 QMediaPlayer 从视频源抓一帧（QImage）。"""
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

    def _sync_panels(self) -> None:
        """把侧栏 / 标题栏 / 卡片的矩形传给页面（页面画 backdrop-filter）。

        ## 和 DSH 的对应关系

        DSH 的 ``backdrop-filter`` 挂在
        ``NavigationPanel`` / ``FluentTitleBar`` / ``CardWidget`` 上。
        这里按同样的控件类名扫矩形，传给 Web 层画。
        """
        try:
            win = self._window
            v = self._view
            if v is None or win is None:
                return
            from PySide6.QtCore import QRect
            from PySide6.QtWidgets import QWidget

            rects = []
            #: ① 侧栏 + 标题栏（大面板，圆角 0）
            for attr, radius in (
                ("navigationInterface", 0),
                ("titleBar", 0),
            ):
                obj = getattr(win, attr, None)
                panel = getattr(obj, "panel", obj) if obj is not None else None
                if panel is None:
                    continue
                try:
                    if not panel.isVisible():
                        continue
                    sz = panel.size()
                    if sz.width() < 10 or sz.height() < 10:
                        continue
                    tl = panel.mapTo(win, panel.rect().topLeft())
                    r = QRect(tl, sz)
                    #: ★ 侧栏/标题栏用 0.92 的实色底（DSH 实测 luma 0.039）
                    rects.append([r.x(), r.y(), r.width(), r.height(),
                                  radius, "sidebar"])
                except (RuntimeError, AttributeError):
                    continue

            #: ② 卡片
            names = {"CardWidget", "SimpleCardWidget", "ElevatedCardWidget",
                     "HeaderCardWidget", "GroupHeaderCardWidget", "ToolCard"}
            stacked = getattr(win, "stackedWidget", None)
            page = None
            if stacked is not None:
                try:
                    page = stacked.currentWidget()
                except (RuntimeError, AttributeError):
                    page = None
            root = page if page is not None else win
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
                    r = QRect(tl, sz)
                    #: ★ 卡片用玻璃感（0.59），和 DSH 一致
                    rects.append([r.x(), r.y(), r.width(), r.height(),
                                  10, "card"])
                    if len(rects) >= 60:
                        break
                except (RuntimeError, AttributeError):
                    continue

            if rects == self._last_panels:
                return
            self._last_panels = rects
            js = (f"window.__setPanels && window.__setPanels("
                  f"{json.dumps(rects)});")
            v.page().runJavaScript(js)
        except Exception:  # noqa: BLE001
            logger.debug("壁纸：同步面板失败", exc_info=True)

    def status(self) -> str:
        try:
            return self._view.title() if self._view else ""
        except Exception:  # noqa: BLE001
            return ""

    def teardown(self) -> None:
        self._active = False
        for name in ("_follow_timer", "_panel_timer"):
            try:
                t = getattr(self, name, None)
                if t is not None:
                    t.stop()
                    t.deleteLater()
            except Exception:  # noqa: BLE001
                pass
            setattr(self, name, None)
        #: ★★★ 2026-11-01 **同步销毁旧的 Web 视图**
        #:
        #: 用户：「没有成功切换」—— 状态变了、日志也正常，
        #: 但画面还是上一个壁纸。
        #:
        #: 根因：`deleteLater()` 只是**排队**，要等事件循环转一圈才真删。
        #: 而切换流程紧接着就建新视图 —— 这时**旧的还在屏幕上**，
        #: 新视图被它盖住（或者两者叠加）。
        #:
        #: → 先 `hide()`（立刻消失），再 `setParent(None)`，
        #:   最后 `deleteLater()` 兜底。
        try:
            if self._view is not None:
                self._view.stop()
                self._view.hide()               #: ← 立刻从屏幕消失
                self._view.setUpdatesEnabled(False)
                self._view.setPage(None)
                self._view.setParent(None)
                self._view.deleteLater()
        except Exception:  # noqa: BLE001
            pass
        self._view = None
        self._restore_opaque()
        logger.info("壁纸：已拆除")


def apply_dsh_wallpaper(window: QWidget, video_path: str) -> bool:
    """铺一层 DSH 同款壁纸（全局单例）。"""
    global _current
    path = str(video_path or "")
    if not path or not os.path.isfile(path):
        logger.warning("壁纸：视频不存在 %s", path)
        if _current is not None:
            _current.teardown()
            _current = None
        return False
    if _current is not None and _current.video_path == path:
        logger.info("壁纸：[路径相同] 不切换 %s", os.path.basename(path))
        _current._follow()                                       # noqa: SLF001
        return True
    logger.info("壁纸：[路径不同] 当前=%s 目标=%s",
                os.path.basename(_current.video_path) if _current else "(无)",
                os.path.basename(path))
    #: ★★★ 2026-11-01 **视图已存在 → 只换 src，不重建**
    #:
    #: 照 DSH 的做法（client.js L18383 `video.src = url; video.load()`）。
    #: 重建视图的问题太多：缓存、销毁时序、透明背景恢复、慢（1 秒）。
    if (_current is not None and _current.active
            and _current._view is not None):                     # noqa: SLF001
        if _current.switch_video(path):                          # noqa: SLF001
            return True
        #: 换 src 失败才退回重建
        logger.warning("壁纸：换 src 失败，退回重建视图")
    if _current is not None:
        _current.teardown()
    #: ★★★ 2026-11-01 **让旧视图真的消失再建新的**
    #:
    #: ``deleteLater()`` 只是**排队**，必须让事件循环转一圈才真删。
    #: 不转的话旧视图还在屏幕上，新视图叠上去看不出变化
    #: （用户：「没有成功切换」）。
    try:
        from PySide6.QtWidgets import QApplication

        _app = QApplication.instance()
        if _app is not None:
            for _ in range(8):
                _app.processEvents()
    except Exception:  # noqa: BLE001
        pass
    layer = DshWallpaper(window, path)
    ok = layer.start()
    _current = layer if ok else None
    return ok


def current_layer() -> "DshWallpaper | None":
    return _current


def shutdown() -> None:
    global _current
    if _current is not None:
        _current.teardown()
        _current = None
