# -*- coding: utf-8 -*-
"""★ 本地视频 HTTP 服务 —— 给 Chromium 播壁纸用。

## ★★★ 2026-10-31 为什么需要它（关键发现）

壁纸视频转成 WebM 后，用 ``file://`` 喂给 ``QWebEngineView`` **播不了**
（``MEDIA_ERR_SRC_NOT_SUPPORTED`` / ERR4），即使：

  * ``canPlayType('video/webm; codecs="vp8"')`` 返回 **probably**
  * 文件确实是合法 WebM（``1A 45 DF A3`` 头 + ``V_VP8`` 标识）
  * ffmpeg 的 VP8 / VP9 / VP9-profile0 全都试过

**根因是 ``setHtml()`` 的同源策略**：``setHtml`` 给的页面 baseUrl 是
``about:blank`` 或某个 file 目录，Chromium 对「页面源」和「视频源」
不一致的 ``<video>`` 会**直接拒绝**（哪怕开了
``LocalContentCanAccessFileUrls``）。

## 解法：起一个本地 HTTP 服务

DSH 那个插件**就是这么做的**（它的 ``serve.js`` / ``media-origin.js``
起 HTTP 给视频用）。

实测对比：

    file://   → ERR4（播不了）
    http://   → READY:800（正常）

## 实现

用标准库 ``http.server`` 在 ``127.0.0.1`` 上开一个**随机端口**的服务：

  * 只监听本机（``127.0.0.1``，外部访问不到）
  * 只服务**转码缓存目录**（不暴露整个磁盘）
  * **支持 Range 请求**（``<video>`` 要拖进度条就必须支持）
  * 无日志输出（不刷屏）

⚠ 必须支持 Range：``SimpleHTTPRequestHandler`` 自己**不支持**，
而 ``<video>`` 播放时一定会发 ``Range: bytes=0-`` —— 不支持的话
Chromium 会认为源不可用（又一个 ERR4 的来源）。所以这里自己实现。
"""

from __future__ import annotations

import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

logger = logging.getLogger(__name__)

#: 单例：全局只起一个服务
_server: ThreadingHTTPServer | None = None
_thread: threading.Thread | None = None
_port: int = 0

#: 允许服务的文件后缀（只给视频，不给任意文件）
ALLOWED_SUFFIX = (".webm", ".mp4", ".m4v", ".png", ".jpg", ".jpeg")

#: MIME 类型
MIME = {
    ".webm": "video/webm",
    ".mp4": "video/mp4",
    ".m4v": "video/mp4",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}


class _Handler(BaseHTTPRequestHandler):
    """处理壁纸视频请求（**支持 Range**）。"""

    #: 由 :func:`start` 填进来，告诉 handler 去哪儿找文件
    root_dir: str = ""

    def log_message(self, *args) -> None:   # noqa: D102 - 静默
        pass

    def do_GET(self) -> None:               # noqa: N802 - BaseHTTPRequestHandler
        try:
            self._serve(head_only=False)
        except Exception:  # noqa: BLE001
            logger.debug("HTTP 壁纸服务：请求失败 %s", self.path, exc_info=True)
            try:
                self.send_error(500)
            except Exception:  # noqa: BLE001
                pass

    def do_HEAD(self) -> None:              # noqa: N802 - BaseHTTPRequestHandler
        try:
            self._serve(head_only=True)
        except Exception:  # noqa: BLE001
            try:
                self.send_error(500)
            except Exception:  # noqa: BLE001
                pass

    #: 由 `start()` 注入：页面 HTML + 视频文件名
    page_html: str = ""

    def _serve_page(self, *, head_only: bool) -> None:
        """返回壁纸页面 HTML（和视频同源，绕开 setHtml 限制）。"""
        body = (self.page_html or "").encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if not head_only:
            self.wfile.write(body)

    def _serve(self, *, head_only: bool) -> None:
        raw = self.path.split("?", 1)[0]
        #: ★ 特殊路由：/wallpaper 返回壁纸页面本身
        #:
        #: 这样页面从 http:// 加载，和视频**同源** —— 绕开
        #: `setHtml()` 的同源限制（那是 ERR4 的真正来源）。
        if raw in ("/wallpaper", "/wallpaper.html"):
            self._serve_page(head_only=head_only)
            return
        #: 白名单后缀检查
        name = os.path.basename(raw.replace("\\", "/"))
        if not name or ".." in raw:
            self.send_error(403)
            return
        suffix = os.path.splitext(name)[1].lower()
        if suffix not in ALLOWED_SUFFIX:
            self.send_error(403)
            return
        path = Path(self.root_dir) / name
        if not path.is_file():
            self.send_error(404)
            return

        size = path.stat().st_size
        ctype = MIME.get(suffix, "application/octet-stream")

        #: ★ Range 请求（<video> 一定会发）
        range_hdr = self.headers.get("Range") or ""
        start, end = 0, size - 1
        partial = False
        if range_hdr.startswith("bytes="):
            spec = range_hdr[len("bytes="):].split(",")[0].strip()
            try:
                a, _, b = spec.partition("-")
                if a:
                    start = int(a)
                    if b:
                        end = int(b)
                elif b:
                    #: "bytes=-N" = 最后 N 字节
                    start = max(0, size - int(b))
                end = min(end, size - 1)
                partial = True
            except ValueError:
                start, end, partial = 0, size - 1, False
        if start > end or start >= size:
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{size}")
            self.end_headers()
            return

        length = end - start + 1
        self.send_response(206 if partial else 200)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        if partial:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if head_only:
            return
        #: 分块发送（大文件不能一次读进内存）
        try:
            with open(path, "rb") as fh:
                fh.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = fh.read(min(256 * 1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            #: 客户端（Chromium）主动断开 —— 正常现象，不是错误
            pass


def start(serve_dir: str | Path) -> str:
    """起服务（幂等）。返回 ``http://127.0.0.1:<port>``，失败返回空串。

    :param serve_dir: 只服务这个目录下的文件（通常是转码缓存目录）
    """
    global _server, _thread, _port
    root = str(serve_dir or "")
    if not root or not Path(root).is_dir():
        logger.warning("HTTP 壁纸服务：目录不存在 %s", root)
        return ""

    #: 已经在跑且目录没变 → 复用
    if _server is not None and _port:
        if _Handler.root_dir == root:
            return f"http://127.0.0.1:{_port}"
        #: 目录变了 → 重启
        stop()

    try:
        _Handler.root_dir = root
        #: 端口 0 = 让系统分配空闲端口（避免 8080 被占）
        srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        srv.daemon_threads = True
        _port = srv.server_address[1]
        _server = srv
        _thread = threading.Thread(
            target=srv.serve_forever, name="wp-http", daemon=True)
        _thread.start()
        logger.info("HTTP 壁纸服务：已启动 http://127.0.0.1:%d（%s）",
                    _port, root)
        return f"http://127.0.0.1:{_port}"
    except Exception:  # noqa: BLE001
        logger.warning("HTTP 壁纸服务：启动失败", exc_info=True)
        _server = None
        _port = 0
        return ""


def stop() -> None:
    """停服务。"""
    global _server, _thread, _port
    try:
        if _server is not None:
            _server.shutdown()
            _server.server_close()
    except Exception:  # noqa: BLE001
        pass
    _server = None
    _thread = None
    _port = 0


def set_page(html: str) -> None:
    """设置 `/wallpaper` 路由返回的页面内容。"""
    _Handler.page_html = html or ""


def page_url(*, bust: bool = False) -> str:
    """壁纸页面的 URL（服务没起返回空串）。

    :param bust: 加时间戳 query —— **切换壁纸时必须加**，
                 否则 Chromium 认为 URL 没变，用缓存页面（画面不更新）。
    """
    if not _port:
        return ""
    if bust:
        import time as _t

        return f"http://127.0.0.1:{_port}/wallpaper?t={int(_t.time() * 1000)}"
    return f"http://127.0.0.1:{_port}/wallpaper"


def url_for(file_path: str | Path) -> str:
    """把文件路径转成 HTTP URL（服务没起就返回空串）。"""
    if not _port:
        return ""
    name = Path(file_path).name
    return f"http://127.0.0.1:{_port}/{name}"
