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

#: ★ 挂载表：``{URL 前缀: 目录}``。
#:
#: ## 为什么需要多目录（2026-11-01，Web UI 骨架）
#:
#: 原来只能服务**一个**目录（转码缓存），因为壁纸层只播视频。
#: 现在整个窗口是一个 HTML 页面（见 :mod:`src.gui.web_shell`），
#: 页面自己（index.html + css/js）也必须从 HTTP 拉：
#:
#:   * ``/``       → 转码缓存目录（视频）—— **保持原行为**，``url_for`` 不变
#:   * ``/web/``   → ``src/gui/web``（前端资源）
#:   * ``/user/``  → 用户自备壁纸目录
#:
#: 页面和视频落在**同一个端口** = 同源，``<video>`` 不会撞同源策略。
#:
#: ⚠ 键是小写前缀（``"/web/"``），匹配时按**最长前缀**优先，
#: 否则 ``/`` 会抢先吃掉所有请求。
_mounts: dict[str, str] = {}

#: 允许服务的文件后缀（只给视频/图片 + Web 前端资源）
ALLOWED_SUFFIX = (
    ".webm", ".mp4", ".m4v", ".png", ".jpg", ".jpeg",
    #: ── Web UI 骨架（2026-11-01）──────────────────────────────
    #: 没有这三样，index.html 拿不到自己的 css/js，页面就是白板。
    ".html", ".htm", ".css", ".js", ".mjs", ".svg", ".woff", ".woff2",
    ".json", ".ico", ".webp", ".gif", ".map",
)

#: MIME 类型
MIME = {
    ".webm": "video/webm",
    ".mp4": "video/mp4",
    ".m4v": "video/mp4",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    #: ── Web UI 骨架 ──────────────────────────────────────────
    #: ⚠ ``text/html`` 必须带 charset，否则中文标题变乱码。
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".map": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
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

    def _resolve_mount(self, raw: str) -> tuple[str | None, str]:
        """把请求路径解析成 ``(根目录, 相对路径)``。

        ## 两种挂载的差别（★ 安全性关键）

        * **``/``（视频根）** —— 只认**文件名**，路径里的目录一律丢弃。
          这是原来的行为：``/a/b/c.webm`` 和 ``/c.webm`` 等价，请求方
          没法用 ``../`` 跳出转码缓存目录。
        * **``/web/`` 等命名挂载** —— 认**子路径**（``css/layout.css``），
          因为前端资源天然有目录。越界用 :func:`_safe_join` 挡住。

        :return: ``(根目录, 相对路径)``；不匹配返回 ``(None, "")``
        """
        #: ★ 先 percent-decode。
        #:
        #: ``BaseHTTPRequestHandler`` 的 ``self.path`` 是**原始请求行**，
        #: 不会解码 ``%E8%8E%89`` —— 不解码的话，中文文件名的请求
        #: （``/game/avatars/%E8%8E%89%E8%8E%89.png``）拿到的 rel 就是
        #: 那串 %XX，拼成磁盘路径必然 404。
        #:
        #: 实测：角色头像全是中文名（``莉莉.png`` / ``万囮牢·朽躯.png``），
        #: 用户看到的是一整片破图。
        raw = _unquote_path(raw)

        #: 最长前缀优先 —— 否则 "/" 会吃掉所有请求
        for prefix in sorted(_mounts, key=len, reverse=True):
            if prefix == "/":
                continue
            if raw.startswith(prefix):
                return _mounts[prefix], raw[len(prefix):].lstrip("/")
        #: 兜底：视频根
        root = _mounts.get("/") or self.root_dir
        if not root:
            return None, ""
        return root, os.path.basename(raw.replace("\\", "/"))

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

        #: ★ 挂载表匹配（最长前缀优先）
        root, rel = self._resolve_mount(raw)
        if root is None:
            self.send_error(403)
            return

        #: 白名单后缀检查
        name = os.path.basename(rel.replace("\\", "/"))
        if not name or ".." in rel:
            self.send_error(403)
            return
        suffix = os.path.splitext(name)[1].lower()
        if suffix not in ALLOWED_SUFFIX:
            self.send_error(403)
            return

        #: ★ 命名挂载（/web/ 等）要认子目录；视频根只认文件名（见 _resolve_mount）
        if "/" in rel.strip("/"):
            path = _safe_join(root, rel)
            if path is None:
                self.send_error(403)
                return
        else:
            path = Path(root) / name
        if not path.is_file():
            self.send_error(404)
            return
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


def _unquote_path(raw: str) -> str:
    """URL 路径 percent-decode（``%E8%8E%89`` → ``莉``）。

    ## ⚠ 只解码、不做别的

    * **不解码** ``+`` 成空格 —— URL 路径里 ``+`` 就是字面量 ``+``
      （只有 query string 才把 ``+`` 当空格）。而文件名里真有 ``+``
      的话，替换掉会 404。
    * 解码失败（残缺的 %XX）原样返回 —— 让它走后面的白名单/存在性检查，
      自然 404，不要在这里抛异常把连接挂住。

    ## 安全性

    解码**之后**才做 ``..`` 检查（在 :func:`_safe_join` 里）。
    ⚠ 如果反过来先检查后解码，``%2e%2e%2f`` 这种就能穿过检查 ——
    经典的路径穿越漏洞。
    """
    if "%" not in raw:
        return raw
    try:
        from urllib.parse import unquote  # noqa: PLC0415

        return unquote(raw, encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return raw


def _safe_join(root: str, rel: str) -> Path | None:
    """把 ``rel`` 安全地拼到 ``root`` 下；越界返回 ``None``。

    ``..`` 必须**在拼接前**挡掉 —— 只靠 ``resolve()`` 后比较前缀是不够的：
    Windows 上 ``C:\\a`` 和 ``C:\\ab`` 的纯字符串前缀比较会误判（前者是后者的前缀）。
    ``Path.is_relative_to()`` 按路径分量比，不会有这个坑。
    """
    rel = (rel or "").replace("\\", "/").strip()
    if not rel:
        return None
    parts = [p for p in rel.split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        return None
    try:
        base = Path(root).resolve()
        target = base.joinpath(*parts).resolve()
    except OSError:
        return None
    if not target.is_relative_to(base):
        return None
    return target


def mount(prefix: str, directory: str | Path) -> str:
    """★ 挂一个目录到 URL 前缀（Web UI 骨架用）。

    .. code:: python

        media_server.start(cache_dir)          # "/" → 视频转码缓存
        media_server.mount("/web/", web_dir)   # "/web/" → 前端资源
        media_server.mount("/user/", wp_dir)   # "/user/" → 用户自备壁纸

    :return: 该前缀的完整 base URL（服务没起返回空串）
    """
    global _mounts
    key = "/" + str(prefix or "").strip("/")
    if key != "/":
        key += "/"
    directory = str(directory or "")
    if not directory or not Path(directory).is_dir():
        logger.warning("HTTP 服务：挂载目录不存在 %s → %s", key, directory)
        return ""
    _mounts[key] = directory
    if not _port:
        return ""
    return f"http://127.0.0.1:{_port}{key}"


def unmount(prefix: str) -> None:
    """摘掉一个挂载点。"""
    key = "/" + str(prefix or "").strip("/")
    if key != "/":
        key += "/"
    _mounts.pop(key, None)


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
        #: 视频根始终挂在 "/"
        _mounts["/"] = root
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


def wait_until_ready(timeout: float = 3.0) -> bool:
    """★ 等 HTTP 服务**真的能响应**再返回。

    ## 为什么需要（2026-11-01，lead 实测踩到）

    ``start()`` 里 ``srv`` 构造时 socket 已经 bind+listen 了，但
    ``serve_forever()`` 是**另一个线程**里跑的 —— 线程调度到它之前，
    内核的 accept 队列虽然能接住连接，**却没人应答**。

    现象（lead 第二次启动日志）::

        web_shell：加载 http://127.0.0.1:xxxxx/web/index.html?t=...
        web_shell：页面加载失败 http://127.0.0.1:xxxxx/web/index.html?t=...

    而**再启动一次就正常** —— 典型的启动竞态。
    Chromium 那边表现为 ERR_CONNECTION_REFUSED / ERR_EMPTY_RESPONSE，
    用户看到的就是**首次启动白屏**。

    ## 做法

    用标准库 ``http.client`` 打一个 ``HEAD /`` 探测（很轻），
    成功即返回。失败就每 50ms 重试，总共最多 ``timeout`` 秒。

    ⚠ 探测路径用 ``/`` + 一个**必然 404** 的名字 ——
    只要能拿到 HTTP 状态码（哪怕是 404/403）就说明**服务活着**，
    不必真去读文件。

    :return: 服务可用返回 True
    """
    if not _port:
        return False
    import http.client
    import time as _t

    deadline = _t.monotonic() + max(0.1, timeout)
    while _t.monotonic() < deadline:
        conn = None
        try:
            conn = http.client.HTTPConnection("127.0.0.1", _port, timeout=0.4)
            conn.request("HEAD", "/__ready_probe__")
            conn.getresponse().read()
            return True
        except Exception:  # noqa: BLE001 - 没起来，继续等
            _t.sleep(0.05)
        finally:
            try:
                if conn is not None:
                    conn.close()
            except Exception:  # noqa: BLE001
                pass
    logger.warning("HTTP 服务：等了 %.1fs 仍未就绪（port=%s）",
                   timeout, _port)
    return False


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
    _mounts.clear()


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
    """把文件路径转成 HTTP URL（服务没起就返回空串）。

    ## 自动选前缀（2026-11-01 起）

    文件如果落在某个**命名挂载**（如 ``/web/``）下面，就带上那个前缀；
    否则按老规矩走 ``/``（视频根，只认文件名）。

    以前这里死板地返回 ``/<basename>`` —— 换成多挂载之后，
    ``src/gui/web/js/app.js`` 会变成 ``/app.js``（错的：它在 ``/web/`` 下面），
    页面加载一片 404。所以必须按实际所在目录反查前缀。
    """
    if not _port:
        return ""
    target = Path(file_path)
    try:
        resolved = target.resolve()
    except OSError:
        resolved = target

    #: 最长前缀优先（"//web/" 比 "/" 更具体）
    for prefix in sorted(_mounts, key=len, reverse=True):
        root = _mounts[prefix]
        try:
            base = Path(root).resolve()
            rel = resolved.relative_to(base)
        except (OSError, ValueError):
            continue
        #: Windows 上 URL 分隔符必须用 "/"
        rel_url = rel.as_posix()
        if prefix == "/":
            #: 视频根只认文件名（和 _resolve_mount 的约定一致）
            return f"http://127.0.0.1:{_port}/{Path(rel_url).name}"
        return f"http://127.0.0.1:{_port}{prefix}{rel_url}"

    #: 没挂载过 → 按文件名兜底（老行为）
    return f"http://127.0.0.1:{_port}/{resolved.name}"


def web_url(rel: str = "index.html", *, bust: bool = False) -> str:
    """Web UI 页面的 URL（``/web/`` 挂载点 + 相对路径）。

    :param bust: 加时间戳 —— 改了前端资源后强制 Chromium 重新拉。
    """
    if not _port:
        return ""
    rel = str(rel or "index.html").lstrip("/")
    if "/web/" not in _mounts:
        return ""
    url = f"http://127.0.0.1:{_port}/web/{rel}"
    if bust:
        import time as _t

        url += f"?t={int(_t.time() * 1000)}"
    return url
