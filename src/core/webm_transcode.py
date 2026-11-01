# -*- coding: utf-8 -*-
"""★ 壁纸视频转码 —— mp4 (H.264) → WebM (VP9)，给 QtWebEngine 用。

## ★★★ 为什么必须转码（2026-10-31）

用户要求「完全按照 DSH 那样做」，所以壁纸层换成 ``QWebEngineView``
（Chromium）。**但 QtWebEngine 是开源 Chromium，不含 H.264 解码器**：

实测 ``video.canPlayType(...)``::

    video/mp4; codecs="avc1.42E01E"   →  (空)       ← H.264 不支持
    video/webm; codecs="vp8"          →  probably   ← 支持

用户的 WE 壁纸**全是 H.264 mp4** → Chromium 直放 = **黑屏**。

## 走过的弯路（别再试）

==============================  ==========================================
尝试                             结果
==============================  ==========================================
OpenCV ``VideoWriter(VP8/VP9)``  能生成，**但 Chromium 不认**（ERROR:4）
                                 —— 它出的容器缺 Cues/SeekHead 等必需元素
``QMediaRecorder`` + WebM        ``WebM 可编码: False``（ResourceError）
                                 —— Qt 自带的 WebM 编码器不可用
pip / winget 装 ffmpeg           网络卡死（7.9KB/s）
==============================  ==========================================

**最终方案：用 ffmpeg**（已下载并放在 ``vendor/ffmpeg/ffmpeg.exe``）。
只有它能生成 Chromium 认的标准 WebM。

## ffmpeg 怎么找

按顺序：
  ① 环境变量 ``MYTOOLS_FFMPEG``
  ② **项目** ``vendor/ffmpeg/ffmpeg.exe`` ← 当前装的在这
  ③ 用户数据目录 ``tools/ffmpeg.exe``
  ④ 系统 PATH

## 缓存策略

转码慢（4K 要几十秒），所以**结果缓存**：

    <用户数据>/wallpaper_webm/<原名>_<指纹>.webm

指纹 = ``路径 + 大小 + mtime`` —— 源视频换了自动重转。
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

#: 转码缓存目录名（在用户数据目录下）
CACHE_DIRNAME = "wallpaper_webm"

#: 输出分辨率上限（宽）。
#:
#: ★ 源视频全是 4K/2K，Chromium 播 4K VP9 吃力；
#: 壁纸铺满窗口 1600 宽完全够（还要被玻璃层糊一部分）。
#: ★★★ 2026-11-01 **从 1600 提到 2560**
#:
#: 用户截图：窗口放大到 1850 宽后，右侧一大块是**重复的画面**。
#:
#: 根因：转码把视频压到了 1600x900，而窗口比这还大 ——
#: HTML 里 `object-fit: cover` 在容器比源大时，
#: 有些浏览器会把源**拉伸/平铺**填满，看着就是重复。
#:
#: → 提到 2560（覆盖 2K 屏；4K 屏也够用）。
#:   代价：单文件从 ~3.5MB 涨到 ~8MB，转码慢一倍。
#:   壁纸是循环播的，体积换清晰度值得。
MAX_WIDTH = 2560

#: 目标帧率（源多是 60fps，降到 30 省一半解码）
TARGET_FPS = 30

#: 最多转多少秒（0 = 不限）。
#:
#: 壁纸循环播放，**前 20 秒足够循环**。
#: 爱弥斯 5480 帧 = 91 秒，截 20 秒省 78% 时间。
MAX_SECONDS = 20

#: VP9 质量（CRF，越低越好；32 画质和体积平衡）
CRF = 32

#: 超时（秒）
TIMEOUT = 600

#: 缓存过期天数
KEEP_DAYS = 60


def find_ffmpeg() -> str:
    """找可用的 ffmpeg 可执行文件。找不到返回空串。"""
    #: ① 环境变量
    env = os.environ.get("MYTOOLS_FFMPEG") or ""
    if env and Path(env).is_file():
        return env

    #: ② 项目 vendor（当前装的在这）
    try:
        from . import paths

        root = paths.resource_dir()
    except Exception:  # noqa: BLE001
        root = None
    if root is not None:
        for rel in ("vendor/ffmpeg/ffmpeg.exe",
                    "vendor/ffmpeg/bin/ffmpeg.exe",
                    "tools/ffmpeg.exe"):
            p = root / rel
            if p.is_file():
                return str(p)

    #: ③ 用户数据目录
    try:
        from . import paths

        p = paths.user_data_dir() / "tools" / "ffmpeg.exe"
        if p.is_file():
            return str(p)
    except Exception:  # noqa: BLE001
        pass

    #: ④ 系统 PATH
    return shutil.which("ffmpeg") or ""


def have_ffmpeg() -> bool:
    """有没有可用的 ffmpeg。"""
    return bool(find_ffmpeg())


def have_encoder() -> bool:
    """兼容旧名字 —— 有 ffmpeg 就能转码。"""
    return have_ffmpeg()


def cache_dir() -> Path | None:
    """转码缓存目录（自动创建）。"""
    try:
        from . import paths

        d = paths.user_data_dir() / CACHE_DIRNAME
        d.mkdir(parents=True, exist_ok=True)
        return d
    except Exception:  # noqa: BLE001
        logger.warning("转码：创建缓存目录失败", exc_info=True)
        return None


def _fingerprint(src: str) -> str:
    """源文件指纹（路径 + 大小 + mtime）。"""
    try:
        st = os.stat(src)
        raw = f"{src}|{st.st_size}|{int(st.st_mtime)}"
    except OSError:
        raw = src
    return hashlib.sha1(raw.encode("utf-8", "replace")).hexdigest()[:12]


def webm_path_for(src: str) -> Path | None:
    """算出这个源文件对应的缓存 webm 路径。

    ## ★★★ 2026-10-31 文件名改成**纯 ASCII hash**

    用户截图：选了壁纸但界面还是深色底，日志里
    ``页面标题: ERROR:4``（视频加载失败）。

    根因：缓存文件名带了**中文**（``守岸人钢琴版_124d4183.webm``），
    拼进 URL 后 Chromium 那边解码失败 ——
    ``http://127.0.0.1:14064/守岸人钢琴版_xxx.webm`` 里的
    中日韩字符在 ``<video src>`` 里必须 percent-encode，
    而这一步不一定做对。

    → 文件名直接用**指纹 hash**（纯 ``[0-9a-f]``），
    中文源头只留在日志里，不进 URL。
    """
    d = cache_dir()
    if d is None:
        return None
    #: 纯 ASCII 名字：<hash>.webm（12 位，碰撞概率可忽略）
    return d / f"{_fingerprint(src)}.webm"


def is_ready(src: str) -> bool:
    """缓存好的 webm 存在吗？"""
    p = webm_path_for(src)
    return p is not None and p.is_file() and p.stat().st_size > 4096


def transcode(src: str, *, progress=None) -> str:
    """把 mp4 转成 webm（**阻塞**，4K 视频约 20~60 秒）。

    ## ffmpeg 参数

    .. code:: text

        -i <src>                          输入
        -t 20                             只取前 20 秒（壁纸循环够用）
        -vf scale='min(1600,iw)':-2       宽最多 1600，高按比例（-2 保证偶数）
        -r 30                             目标帧率
        -c:v libvpx-vp9                   VP9（Chromium 内置支持）
        -crf 32 -b:v 0                    质量（CRF 模式必须配 -b:v 0）
        -pix_fmt yuv420p                  必须！否则 Chromium 播不了
        -an                               去掉音轨（壁纸不要声音）
        -row-mt 1 -cpu-used 2             VP9 多线程提速
        -y                                覆盖

    ⚠ ``-pix_fmt yuv420p`` 是关键 —— 源可能是 10bit/4:2:2，
    不转成 4:2:0 8bit 的话 Chromium 解码失败（实测）。

    :param src: 源视频绝对路径
    :param progress: 可选回调（现在不用，保留接口）
    :return: 转好的 webm 绝对路径；失败返回空串
    """
    if not src or not os.path.isfile(src):
        logger.warning("转码：源文件不存在 %s", src)
        return ""

    out = webm_path_for(src)
    if out is None:
        return ""
    if out.is_file() and out.stat().st_size > 4096:
        logger.info("转码：用缓存 %s", out.name)
        return str(out)

    exe = find_ffmpeg()
    if not exe:
        logger.warning("转码：找不到 ffmpeg —— 壁纸无法在 Chromium 播放")
        return ""

    #: 先写临时文件，成功才改名（避免失败留半个文件）
    tmp = out.with_suffix(".tmp.webm")
    vf = f"scale='min({MAX_WIDTH},iw)':-2"
    cmd = [exe, "-y", "-hide_banner", "-loglevel", "error", "-i", src]
    if MAX_SECONDS > 0:
        cmd += ["-t", str(MAX_SECONDS)]
    cmd += [
        "-vf", vf,
        "-r", str(TARGET_FPS),
        "-c:v", "libvpx-vp9",
        "-crf", str(CRF),
        "-b:v", "0",
        "-pix_fmt", "yuv420p",
        "-an",
        "-row-mt", "1",
        "-cpu-used", "2",
        str(tmp),
    ]
    logger.info("转码：开始 %s（限 %d 秒, %d 宽）",
                os.path.basename(src), MAX_SECONDS, MAX_WIDTH)
    try:
        creation = 0
        if sys.platform == "win32":
            creation = 0x08000000     #: CREATE_NO_WINDOW（不弹黑框）
        proc = subprocess.run(  # noqa: S603
            cmd, capture_output=True, timeout=TIMEOUT,
            creationflags=creation)
        if proc.returncode != 0:
            err = (proc.stderr or b"").decode("utf-8", "replace")[-500:]
            logger.warning("转码：ffmpeg 失败（%s）%s", proc.returncode, err)
            try:
                tmp.unlink()
            except OSError:
                pass
            return ""
        if not tmp.is_file() or tmp.stat().st_size <= 4096:
            logger.warning("转码：输出文件异常")
            return ""
        tmp.replace(out)
        logger.info("转码：完成 %s（%.1f MB）", out.name,
                    out.stat().st_size / 1024 / 1024)
        return str(out)
    except subprocess.TimeoutExpired:
        logger.warning("转码：超时（%d 秒）", TIMEOUT)
        try:
            tmp.unlink()
        except OSError:
            pass
        return ""
    except Exception:  # noqa: BLE001
        logger.warning("转码：失败", exc_info=True)
        return ""


def prepare(src: str, *, progress=None) -> str:
    """★ 给 Chromium 用的**可播放**路径。

    * 已经是 webm → 原样返回
    * 是 mp4 等 → 转成 webm 并返回缓存路径
    * 没有 ffmpeg / 转码失败 → 返回**空串**（调用方退化到 CPU 方案）
    """
    if not src:
        return ""
    ext = os.path.splitext(src)[1].lower()
    if ext in (".webm", ".ogv", ".ogg"):
        return src
    if not have_ffmpeg():
        logger.warning("转码：没有 ffmpeg，%s 无法在 Chromium 播放",
                       os.path.basename(src))
        return ""
    if is_ready(src):
        p = webm_path_for(src)
        return str(p) if p is not None else ""
    return transcode(src, progress=progress)


def cleanup(keep_days: int = KEEP_DAYS) -> None:
    """清掉很久没用的转码缓存。"""
    d = cache_dir()
    if d is None:
        return
    import time as _t

    cutoff = _t.time() - keep_days * 86400
    removed = 0
    try:
        for p in d.glob("*.webm"):
            try:
                if p.stat().st_mtime < cutoff:
                    p.unlink()
                    removed += 1
            except OSError:
                continue
    except OSError:
        return
    if removed:
        logger.info("转码缓存：清理了 %d 个旧文件", removed)
