# -*- coding: utf-8 -*-
"""★ Wallpaper Engine 壁纸库接入（视频型壁纸）。

## 用户 2026-10-31

    > 这个不能像插件一样接入 Wallpaper Engine 吗

## Wallpaper Engine 的壁纸是什么样的

Steam 创意工坊里每个壁纸是一个**目录**，里面必有 ``project.json``::

    D:\\Steam\\steamapps\\workshop\\content\\431960\\<id>\\
        project.json     ← 元数据（title / type / file / preview）
        preview.jpg      ← 缩略图
        <素材文件>        ← mp4 / scene.json / index.html …

``project.json`` 的关键字段::

    title    显示名
    type     "video" / "scene" / "web"
    file     主文件（video → .mp4；scene → scene.json；web → index.html）
    preview  缩略图文件名

## 本模块支持哪几种

==================  ==========================  ==================
type                怎么播放                      本模块
==================  ==========================  ==================
``video``           直接 QMediaPlayer 播 mp4        ✅ 支持
``scene``           要 WebGL 渲染 scene 包           ❌ 不支持
``web``             要内嵌浏览器                     ❌ 不支持
==================  ==========================  ==================

⚠ scene 占用户壁纸的一半（7/14），但不支持它们 —— 那需要一整套
WebGL/puppet 骨骼渲染（DSH 插件内置了 ``WebWallGL`` 才做到），
从零做不现实。**先把 video 型跑通**，剩下的以后再说。

## 壁纸库怎么找

按顺序找这几个位置（用户可能有多个 Steam 库）::

    ① 环境变量里有没有 STEAM_PATH
    ② 常见盘符下的 steamapps/workshop/content/431960
    ③ 用户自己配的路径（``data/wallpaper_engine.json``）

``431960`` 是 Wallpaper Engine 的 Steam AppID。
"""

from __future__ import annotations

import json
import logging
import os
import string
from pathlib import Path

logger = logging.getLogger(__name__)

#: Wallpaper Engine 的 Steam AppID（创意工坊目录名就是它）
WE_APP_ID = "431960"

#: 支持播放的壁纸类型
SUPPORTED_TYPES = ("video",)


def _candidate_roots() -> list[Path]:
    """可能存放 ``steamapps/workshop/content/431960`` 的根目录。

    ## 为什么列这么多个

    用户往往有多个 Steam 库（C 盘、D 盘、移动硬盘）。
    Steam 的库位置记在 ``<steam>/steamapps/libraryfolders.vdf`` 里，
    但解析 VDF 要写个小解析器；**直接扫常见盘符更省事且够用**
    （每个盘的 ``steamapps`` 目录判断一下就几十毫秒）。
    """
    roots: list[Path] = []

    #: ① 环境变量（有些机器配了）
    env_steam = os.environ.get("STEAM_PATH") or os.environ.get("SteamPath")
    if env_steam:
        roots.append(Path(env_steam))

    #: ② 常见 Steam 安装位置
    for drive in string.ascii_uppercase:
        base = Path(f"{drive}:/")
        if not base.is_dir():
            continue
        for guess in ("Steam", "SteamLibrary", "Program Files (x86)/Steam",
                      "Games/Steam", "Games/SteamLibrary"):
            p = base / guess
            if p.is_dir():
                roots.append(p)

    #: ③ 用户自己配的
    try:
        from ..core import paths

        cfg = paths.user_data_dir() / "wallpaper_engine.json"
        if cfg.is_file():
            data = json.loads(cfg.read_text(encoding="utf-8"))
            extra = data.get("workshop_dir") or data.get("steam_dir")
            if extra:
                roots.append(Path(extra))
    except Exception:  # noqa: BLE001 - 配置坏了不该影响扫描
        logger.debug("壁纸：读配置文件失败", exc_info=True)

    return roots


def find_workshop_dir() -> Path | None:
    """找到 ``.../steamapps/workshop/content/431960`` 目录。

    :return: 找到返回 Path，找不到返回 ``None``
    """
    for root in _candidate_roots():
        try:
            #: root 可能是 steam 根，也可能直接是 workshop 目录
            direct = root / "steamapps" / "workshop" / "content" / WE_APP_ID
            if direct.is_dir():
                return direct
            direct2 = root / "workshop" / "content" / WE_APP_ID
            if direct2.is_dir():
                return direct2
            if root.name == WE_APP_ID and root.is_dir():
                return root
        except OSError:
            continue
    return None


def read_project(project_dir: Path) -> dict | None:
    """读一个壁纸目录的 ``project.json``，补上文件路径。

    :return: 解析后的 dict（含 ``id`` / ``dir`` / ``video_path`` 等），失败返回 None
    """
    pj = project_dir / "project.json"
    if not pj.is_file():
        return None
    try:
        #: ⚠ 用 utf-8-sig —— WE 的 project.json 常带 BOM
        raw = pj.read_text(encoding="utf-8-sig", errors="replace")
        data = json.loads(raw)
    except Exception:  # noqa: BLE001 - 单个壁纸坏了不该中断整轮扫描
        logger.debug("壁纸：解析失败 %s", pj, exc_info=True)
        return None

    wp_type = str(data.get("type") or "scene").lower()
    main_file = str(data.get("file") or "")
    preview_name = str(data.get("preview") or "")

    video_path = ""
    if wp_type == "video" and main_file:
        cand = project_dir / main_file
        if cand.is_file():
            video_path = str(cand)

    preview_path = ""
    if preview_name:
        cand = project_dir / preview_name
        if cand.is_file():
            preview_path = str(cand)

    return {
        "id": project_dir.name,
        "title": str(data.get("title") or project_dir.name),
        #: 归一化：WE 里偶尔写 "Scene" 大写
        "type": wp_type,
        "dir": str(project_dir),
        "main_file": main_file,
        "video_path": video_path,
        "preview_path": preview_path,
        "supported": wp_type in SUPPORTED_TYPES and bool(video_path),
    }


def user_video_dir() -> Path | None:
    """用户自备壁纸视频目录（``<用户数据>/wallpapers``）。

    ## ★★★ 2026-11-01 用户

        > 只要 video 型，我给视频资源，你来加载

    所以除了 Steam 创意工坊，还要能读**用户自己放的视频**。

    目录：``<用户数据>/wallpapers/``
    """
    try:
        from . import paths  # noqa: PLC0415

        d = paths.user_data_dir() / "wallpapers"
        d.mkdir(parents=True, exist_ok=True)
        return d
    except Exception:  # noqa: BLE001
        return None


#: 用户自备视频支持的扩展名
USER_VIDEO_EXTS = (".mp4", ".webm", ".mov", ".mkv", ".m4v", ".avi")


def scan_user_videos() -> list[dict]:
    """扫 ``<用户数据>/wallpapers/`` 下的视频（用户自备）。

    返回格式和 :func:`scan_wallpapers` 一致，``id`` 用
    ``user_<hash>``，和 Steam 的数字 id 不会撞。
    """
    d = user_video_dir()
    if d is None or not d.is_dir():
        return []
    out: list[dict] = []
    try:
        for f in sorted(d.iterdir()):
            if not f.is_file():
                continue
            if f.suffix.lower() not in USER_VIDEO_EXTS:
                continue
            try:
                size = f.stat().st_size
            except OSError:
                continue
            if size < 4096:
                continue
            out.append({
                "id": f"user_{abs(hash(str(f.resolve()))) & 0xFFFFFFFF:08x}",
                "title": f.stem,
                "type": "video",
                "video_path": str(f),
                "preview_path": "",
                "supported": True,
                "workshop_dir": str(d),
                "size": size,
                "is_user": True,
            })
    except OSError:
        logger.warning("壁纸：扫用户视频失败", exc_info=True)
    if out:
        logger.info("壁纸：用户自备视频 %d 个（%s）", len(out), d)
    return out


def scan_wallpapers() -> list[dict]:
    """扫描所有壁纸，返回列表（按标题排序）。

    每项见 :func:`read_project`。``supported`` 为 False 的也能显示
    （界面上标注"不支持"），只是不能选。

    ## ★★★ 2026-11-01 只保留白名单里的壁纸

    用户：

        > 只要 video 型，我给视频资源，你来加载，
        > 而且只留守岸人 + 坎特蕾拉的

    创意工坊里 14 个壁纸（7 video + 7 scene）全列出来太杂，
    而且用户只用这两个 → 用 :func:`allowed_ids` 过滤。

    ⚠ 白名单为空时**返回全部**（向后兼容 / 用户可以清空恢复）。
    """
    root = find_workshop_dir()
    if root is None:
        logger.info("壁纸：没找到 Wallpaper Engine 创意工坊目录")
        return []
    items: list[dict] = []
    try:
        for child in sorted(root.iterdir()):
            if not child.is_dir():
                continue
            info = read_project(child)
            if info is not None:
                items.append(info)
    except OSError:
        logger.warning("壁纸：扫描失败", exc_info=True)
        return []

    #: ★ 白名单过滤（按标题关键字匹配，Steam id 变了也不影响）
    allow = allowed_titles()
    if allow:
        kept = [x for x in items
                if any(k in x["title"] for k in allow)]
        if kept:
            logger.info("壁纸：白名单过滤 %d → %d 个（%s）",
                        len(items), len(kept), ", ".join(allow))
            items = kept
        else:
            logger.warning("壁纸：白名单 %s 一个都没匹配到，显示全部",
                           allow)

    items.sort(key=lambda x: (not x["supported"], x["title"]))
    #: ★ 用户自备视频**不受白名单限制**（用户自己放的就是想用的）
    #: 放在过滤之后加，否则会被白名单误杀。
    items.extend(scan_user_videos())
    logger.info("壁纸：扫到 %d 个（可播放 %d 个）",
                len(items), sum(1 for x in items if x["supported"]))
    return items


#: ★ 只显示这些壁纸（标题关键字）。
#:
#: 用户 2026-11-01：
#:
#:     > 只要 video 型，而且只留守岸人 + 坎特雷拉的
#:
#: 空列表 = 不过滤（显示全部）。
#:
#: ⚠ `坎特` 会同时命中「鸣潮坎特蕾拉」和「鸣潮坎特雷拉02」，
#: 用户只要前者 → 用 :data:_EXCLUDED_TITLES 排掉。
#:
#: ⚠ 用**标题关键字**而不是 Steam id —— 用户重新订阅/换壁纸时
#: id 会变，但标题通常不变。
_ALLOWED_TITLES: tuple[str, ...] = ("守岸人", "鸣潮坎特蕾拉")

#: 即使在白名单里也要**排除**的（标题关键字）
_EXCLUDED_TITLES: tuple[str, ...] = ("坎特雷拉02", "坎特雷拉")


def allowed_titles() -> tuple[str, ...]:
    """当前白名单（标题关键字）。空 = 不过滤。"""
    return _ALLOWED_TITLES


def set_allowed_titles(titles) -> None:
    """改白名单（传空 = 显示全部）。"""
    global _ALLOWED_TITLES
    _ALLOWED_TITLES = tuple(str(t) for t in (titles or ()) if str(t).strip())


def wallpaper_by_id(wp_id: str) -> dict | None:
    """按目录名（Steam 创意工坊 id）找壁纸。

    ⚠ 白名单外的壁纸也**查得到** —— 白名单只影响列表展示，
    不影响"当前选中的那个"（否则取消/恢复时会找不到）。
    """
    root = find_workshop_dir()
    if root is not None:
        p = root / str(wp_id)
        if p.is_dir():
            info = read_project(p)
            if info is not None:
                return info
    for it in scan_wallpapers():
        if it["id"] == str(wp_id):
            return it
    return None
