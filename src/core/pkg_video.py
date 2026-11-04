# -*- coding: utf-8 -*-
"""★ 从 Wallpaper Engine 的 ``scene.pkg`` 里抠出内嵌视频。

## 为什么需要它（用户 2026-11-04）

用户点名要「心月狐」主题，给的资源目录
``D:\\Steam\\steamapps\\workshop\\content\\431960\\3816877839``。
那个目录 ``project.json`` 里 ``type`` 是 ``Scene`` —— 壁纸引擎用 WebGL
渲染 ``scene.pkg``，没有独立 mp4，本项目播不了（见
:mod:`src.core.wallpaper_engine` 的表格）。

但把 ``scene.pkg`` 拆开看，**里面其实塞了完整的 mp4**：

.. code:: text

    文件头：  \\x08\\x00\\x00\\x00 P K G V 0 0 2 4     ← WE 打包格式
    全文搜 'ftyp' 命中 2 处：offset 7646、106474859

每个命中点往前 4 字节就是 mp4 的 ``size`` 字段，往后按 box 链
（``ftyp`` → ``moov`` → ``free`` → ``mdat``）走一遍就知道这段有多长：

.. code:: text

    第 1 段  start 7642      ftyp 32 + moov 11289 + free 8 + mdat 106455486
             → 106466815 字节（h264 3840x2160 8.02s）
    第 2 段  start 106474855 ftyp 28 + moov 11377 + free 8 + mdat 101313564
             → 101324977 字节（hevc 3840x2160 8.02s）

两段画面一样（第二段是 HEVC 版）。我们取**第一段**（h264），
因为它进 :mod:`src.core.webm_transcode` 转 VP9 后 Chromium 一定能播。

## 为什么不直接播 scene.pkg

那需要完整的 WebGL + puppet 骨骼动画渲染，等于自己写个壁纸引擎，
不现实（``wallpaper_engine`` 模块文档也写了这一点）。抠出 mp4 是
**用一张静态壁纸换一个能用的主题**——画面本来就是同一段动画。
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

#: mp4 的 box 类型里我们要认的几种（其余按长度跳过）。
#: ``ftyp`` 是 mp4 的**开头**，用它定位一段视频的起点。
_MP4_MAGIC = b"ftyp"

#: 单段视频的上限（防止 box 长度被读坏时无限往后切）。
_MAX_VIDEO_BYTES = 512 * 1024 * 1024


def _read_u32(buf: bytes, pos: int) -> int:
    """读大端 uint32（mp4 的 size 字段）。读越界返回 0。"""
    if pos < 0 or pos + 4 > len(buf):
        return 0
    return int.from_bytes(buf[pos:pos + 4], "big")


def _walk_boxes(buf: bytes, start: int) -> int | None:
    """从 ``start`` 起走 mp4 box 链，返回**最后一段的结束偏移**。

    走到读不出合法 box 就停 —— 那时已经跨过整段视频了。

    :return: 结束偏移；一个 box 都没走通返回 ``None``
    """
    pos = start
    end = start
    seen = 0
    while pos + 8 <= len(buf):
        size = _read_u32(buf, pos)
        box_type = buf[pos + 4:pos + 8]
        #: ``size == 1`` 表示用 64 位长度（存在这个字段就要再读 8 字节）
        header = 8
        if size == 1:
            if pos + 16 > len(buf):
                break
            size = int.from_bytes(buf[pos + 8:pos + 16], "big")
            header = 16
        if size < header or pos + size > len(buf):
            break
        #: box 类型必须是 4 个可打印 ASCII 字符，否则说明已经走进数据区
        if not all(32 <= c < 127 for c in box_type):
            break
        pos += size
        end = pos
        seen += 1
        #: ``mdat`` 之后通常就是下一个文件 / 尾部垃圾 —— 到这就是一段完整视频
        if box_type == b"mdat":
            break
    return end if seen >= 2 else None


def find_embedded_videos(pkg_path: str) -> list[tuple[int, int]]:
    """列出 ``scene.pkg`` 里内嵌 mp4 的 ``(start, end)`` 区间。

    :param pkg_path: ``scene.pkg`` 绝对路径
    :return: 按出现顺序排好的区间列表（找不到返回空列表）
    """
    try:
        with open(pkg_path, "rb") as fh:  # noqa: PTH123 - 要和 Path 版共存
            buf = fh.read()
    except OSError:
        logger.warning("scene.pkg：读不了 %s", pkg_path, exc_info=True)
        return []

    out: list[tuple[int, int]] = []
    pos = 0
    while True:
        hit = buf.find(_MP4_MAGIC, pos)
        if hit < 0:
            break
        start = hit - 4
        pos = hit + len(_MP4_MAGIC)
        if start < 0:
            continue
        #: ftyp 的 size 字段通常是 24~64，超出这个范围说明是撞巧
        size = _read_u32(buf, start)
        if not (16 <= size <= 512):
            continue
        end = _walk_boxes(buf, start)
        if end is None:
            continue
        if not (4096 <= end - start <= _MAX_VIDEO_BYTES):
            continue
        out.append((start, end))
    sizes = ", ".join(f"{(b - a) / 1048576:.0f}MB" for a, b in out) or "无"
    logger.info("scene.pkg：%s 里找到 %d 段视频（%s）",
                os.path.basename(pkg_path), len(out), sizes)
    return out


def extract_first_video(pkg_path: str, out_path: str) -> str:
    """把 ``scene.pkg`` 里**第一段** mp4 抠到 ``out_path``。

    :return: 成功返回 ``out_path``；失败 / 包里没有视频返回空串
    """
    spans = find_embedded_videos(pkg_path)
    if not spans:
        return ""
    start, end = spans[0]
    try:
        with open(pkg_path, "rb") as src:  # noqa: PTH123
            src.seek(start)
            data = src.read(end - start)
        if len(data) < 4096:
            logger.warning("scene.pkg：抠出来的数据太小（%d 字节）", len(data))
            return ""
        from pathlib import Path  # noqa: PLC0415

        target = Path(out_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(target)
        logger.info("scene.pkg：抠出内嵌视频 → %s（%.1f MB）",
                    target.name, len(data) / 1048576)
        return str(target)
    except Exception:  # noqa: BLE001
        logger.warning("scene.pkg：抠视频失败 %s", pkg_path, exc_info=True)
        return ""


__all__ = ["find_embedded_videos", "extract_first_video"]
