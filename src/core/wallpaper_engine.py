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


def scene_video_dir() -> Path | None:
    """``scene.pkg`` 抠出来的视频放哪：``<用户数据>/wallpapers_scene``。

    为什么不放 ``<用户数据>/wallpapers``：那个目录是**用户自己放视频**的，
    :func:`scan_user_videos` 会把里面每个文件都当成一条壁纸列出来 ——
    抠出来的视频要是也塞进去，壁纸墙会多出一堆重复项。
    """
    try:
        from . import paths  # noqa: PLC0415

        d = paths.user_data_dir() / "wallpapers_scene"
        d.mkdir(parents=True, exist_ok=True)
        return d
    except Exception:  # noqa: BLE001
        return None


def resolve_scene_video(info: dict) -> str:
    """scene 型壁纸 → 从 ``scene.pkg`` 抠出内嵌 mp4 的路径。

    ## 只给「精选主题」抠

    抠一次要读 270MB 的 pkg（实测 0.4 秒 + 106MB 写出），
    所以**只处理 :mod:`wallpaper_themes` 表里点名的那些**，
    其它 scene 壁纸照样显示「不支持」。

    :return: 抠出来（或已在缓存里）的 mp4 路径；不适用返回空串
    """
    pkg = str(info.get("pkg_path") or "")
    if not pkg:
        return ""
    try:
        from . import wallpaper_themes  # noqa: PLC0415

        if wallpaper_themes.theme_for_wallpaper(info.get("id", "")) is None:
            return ""
    except Exception:  # noqa: BLE001
        return ""

    d = scene_video_dir()
    if d is None:
        return ""
    target = d / f"{info.get('id', 'scene')}.mp4"
    if target.is_file() and target.stat().st_size > 4096:
        return str(target)
    try:
        from . import pkg_video  # noqa: PLC0415

        out = pkg_video.extract_first_video(pkg, str(target))
        if out:
            logger.info("壁纸：%s 是 scene 型，已从 scene.pkg 抠出视频",
                        info.get("title", ""))
        return out
    except Exception:  # noqa: BLE001
        logger.warning("壁纸：抠 scene 视频失败 %s", pkg, exc_info=True)
        return ""


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

    #: ★ 2026-11-04：scene 型也可能有**内嵌 mp4**（见 :mod:`pkg_video`）。
    #: 这里只记下 scene.pkg 的路径，**不在读 project 时抽**（那是几百 MB
    #: 的 IO，扫描阶段不该干）—— 由 :func:`scan_wallpapers` 决定要不要抽。
    pkg_path = ""
    if wp_type == "scene":
        pkg = project_dir / "scene.pkg"
        if pkg.is_file():
            pkg_path = str(pkg)

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
        "pkg_path": pkg_path,
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


#: ★ 安装包自带壁纸的子目录（相对程序资源目录）
#:
#: ``<程序目录>/assets/wallpapers/<创意工坊 id>.webm``
#: —— 打包时由 ``packaging/mytools.spec`` 从 ``assets/wallpapers/`` 收进去。
BUNDLED_SUBDIR = ("assets", "wallpapers")


def bundled_video_dir() -> Path | None:
    """★ 安装包**自带**的壁纸目录（2026-11-04 加）。

    用户：

        > 视频单独打包放在一个文件夹，安装完后，壁纸就读这个路径下的，不行吗

    可以，而且比读创意工坊更稳 —— 装完就有，不依赖 Wallpaper Engine
    有没有装、有没有订阅、订阅还在不在。

    ⚠ 目录里放的是**已经转好的 VP9 webm**，不是源 mp4：
    QtWebEngine 不带 H.264 解码器（见 ``packaging/mytools.spec`` 里
    ffmpeg 那一大段注释），源 mp4 放进去也只是摆着。
    文件名 = 创意工坊 id（``3340494990.webm``），这样和精选主题对得上。
    """
    try:
        from . import paths  # noqa: PLC0415

        d = paths.resource_dir().joinpath(*BUNDLED_SUBDIR)
    except Exception:  # noqa: BLE001
        return None
    return d if d.is_dir() else None


def bundled_video_path(wp_id: str) -> str:
    """这张壁纸有没有自带的 webm？有就返回路径，没有返回空串。"""
    d = bundled_video_dir()
    key = str(wp_id or "").strip()
    if d is None or not key:
        return ""
    p = d / f"{key}.webm"
    try:
        if p.is_file() and p.stat().st_size > 4096:
            return str(p)
    except OSError:
        return ""
    return ""


def _items_from_themes() -> list[dict]:
    """没装 Wallpaper Engine 时，用「自带 webm + 精选主题表」拼出列表。

    有创意工坊目录时不会走这里（那边标题是上游给的真名）。
    """
    out: list[dict] = []
    try:
        from . import wallpaper_themes  # noqa: PLC0415

        themes = wallpaper_themes.all_themes()
    except Exception:  # noqa: BLE001
        return out
    for t in themes:
        wp_id = str(t.get("wallpaper_id") or "")
        video = bundled_video_path(wp_id)
        if not video:
            continue
        out.append({
            "id": wp_id,
            "title": str(t.get("name") or wp_id),
            "type": "video",
            "dir": "",
            "main_file": "",
            "video_path": video,
            "pkg_path": "",
            "preview_path": "",
            "supported": True,
            #: 这条是从安装包自带的，不是创意工坊扫出来的
            "is_bundled": True,
        })
    return out


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
        #: ★ 2026-11-04：没装 Wallpaper Engine（或者创意工坊里一个都没有）
        #: 时**不能返回空列表** —— 安装包自带了 7 段转好的 webm，
        #: 装完就该能直接用。见 :func:`_items_from_themes`。
        bundled = _items_from_themes()
        if bundled:
            logger.info("壁纸：没找到创意工坊，用安装包自带的 %d 个", len(bundled))
            bundled.extend(scan_user_videos())
            return bundled
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

    #: ★ 白名单过滤
    #:
    #: 两种口径，**精确 id 优先**：
    #:   ① :func:`allowed_ids`（精选主题引用的 id）—— 2026-11-04 起是主口径。
    #:      好处：创意工坊里「坎特蕾拉」有 4 个同名目录（3454096998 /
    #:      3457201973 / 3457765536 / 3786912221），按标题关键字根本分不清
    #:      用户要的是哪个；按 id 只认他点名的那一个。
    #:   ② :func:`allowed_titles`（标题关键字）—— 老口径，保持兼容。
    ids = allowed_ids()
    if ids:
        kept = [x for x in items if x["id"] in ids]
        if kept:
            logger.info("壁纸：按精选主题 id 过滤 %d → %d 个", len(items), len(kept))
            items = kept
        else:
            logger.warning("壁纸：精选主题的 id 一个都没匹配到，显示全部")
    allow = allowed_titles()
    if not ids and allow:
        kept = [x for x in items
                if any(k in x["title"] for k in allow)]
        if kept:
            logger.info("壁纸：白名单过滤 %d → %d 个（%s）",
                        len(items), len(kept), ", ".join(allow))
            items = kept
        else:
            logger.warning("壁纸：白名单 %s 一个都没匹配到，显示全部",
                           allow)

    #: ★ 安装包自带的 webm **优先于源 mp4**（2026-11-04）
    #:
    #: 7 个精选主题都随包带了一段转好的 VP9 webm（``assets/wallpapers/<id>.webm``）。
    #: 它比读创意工坊的源 mp4 好三点：
    #:   ① 不用现场转码（每张 20~60 秒，第一次进壁纸页要等好几分钟）；
    #:   ② 用户退订 / 删了创意工坊目录也照样能播；
    #:   ③ 缓存目录被清掉也不用重转。
    #: 所以命中自带件时直接把 ``video_path`` 换过去。
    for info in items:
        bundled = bundled_video_path(info.get("id", ""))
        if bundled:
            info["video_path"] = bundled
            info["supported"] = True
            info["is_bundled"] = True

    #: ★ scene 型：包里内嵌视频的，抽出来当普通视频壁纸用
    for info in items:
        if not info.get("video_path"):
            resolved = resolve_scene_video(info)
            if resolved:
                info["video_path"] = resolved
                info["supported"] = True

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


def allowed_ids() -> tuple[str, ...]:
    """★ 精选主题引用的壁纸 id（2026-11-04 起是白名单主口径）。

    创意工坊里「坎特蕾拉」有 4 个同名目录，按标题关键字分不清，
    只能按用户点名的 id 精确匹配 —— 见 :mod:`wallpaper_themes`。
    """
    try:
        from . import wallpaper_themes  # noqa: PLC0415

        return wallpaper_themes.wallpaper_ids()
    except Exception:  # noqa: BLE001
        return ()


def allowed_titles() -> tuple[str, ...]:
    """当前白名单（标题关键字）。空 = 不过滤。"""
    return _ALLOWED_TITLES


def set_allowed_titles(titles) -> None:
    """改白名单（传空 = 显示全部）。"""
    global _ALLOWED_TITLES
    _ALLOWED_TITLES = tuple(str(t) for t in (titles or ()) if str(t).strip())


def wallpaper_by_id(wp_id: str, *, prefer_bundled: bool = True) -> dict | None:
    """按目录名（Steam 创意工坊 id）找壁纸。

    ⚠ 白名单外的壁纸也**查得到** —— 白名单只影响列表展示，
    不影响"当前选中的那个"（否则取消/恢复时会找不到）。

    :param prefer_bundled: 有安装包自带的 webm 时，``video_path`` 用它
        （不用转码、不怕用户退订）。**打包脚本要传 False** ——
        它需要的是创意工坊里的**源文件**，不是已经转好的自己。
    """
    key = str(wp_id)
    root = find_workshop_dir()
    if root is not None:
        p = root / key
        if p.is_dir():
            info = read_project(p)
            if info is not None:
                if prefer_bundled:
                    #: 有自带 webm 就用自带的（不用转码，也不怕用户退订）
                    bundled = bundled_video_path(key)
                    if bundled:
                        info["video_path"] = bundled
                        info["supported"] = True
                        info["is_bundled"] = True
                elif not info.get("video_path"):
                    #: 调用方要**源文件**（打包脚本），scene 型得现抠
                    resolved = resolve_scene_video(info)
                    if resolved:
                        info["video_path"] = resolved
                        info["supported"] = True
                return info
    for it in scan_wallpapers():
        if it["id"] == key:
            if not prefer_bundled:
                original = _original_video_path(key)
                if original:
                    it = dict(it)
                    it["video_path"] = original
                    it.pop("is_bundled", None)
            return it
    if not prefer_bundled:
        #: 只要源文件就不要兜底（兜底全是自带件）
        return None
    #: ★ 2026-11-04：创意工坊里没有、但安装包自带这段 webm
    #: （用户没装 Wallpaper Engine 的机器上就是这条路）
    bundled = bundled_video_path(key)
    if bundled:
        for it in _items_from_themes():
            if it["id"] == key:
                return it
        return {
            "id": key,
            "title": key,
            "type": "video",
            "dir": "",
            "main_file": "",
            "video_path": bundled,
            "pkg_path": "",
            "preview_path": "",
            "supported": True,
            "is_bundled": True,
        }
    return None


def _original_video_path(wp_id: str) -> str:
    """创意工坊里的**源**视频（无视安装包自带的 webm）。"""
    root = find_workshop_dir()
    key = str(wp_id)
    if root is None:
        return ""
    p = root / key
    if not p.is_dir():
        return ""
    info = read_project(p)
    if info is None:
        return ""
    video = info.get("video_path") or ""
    if video:
        return video
    return resolve_scene_video(info)
