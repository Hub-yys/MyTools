# -*- coding: utf-8 -*-
"""图片缓存 —— 把接口给的 ``iconUrl`` 下载到本地并按需加载成 ``QPixmap``。

## 为什么需要它

库街区的接口（``/aki/roleBox/...``）在每个字段旁边都给了 ``iconUrl``::

    属性   {"attributeName": "暴击", "iconUrl": ".../role_attribute_icon/x.png"}
    技能   {"skill": {"name": "应急预案", "iconUrl": ".../role_skill_icon/y.png"}}
    共鸣链 {"name": "极简与繁复", "iconUrl": ".../chain_icon/z.png"}
    武器   {"weapon": {"weaponIcon": ".../weapon_icon/w.png"}}
    声骸   {"phantomProp": {"iconUrl": ".../phantom_icon/v.png"}}

官方那个页面就是**图文并茂**的（用户给的参考图）——
所以要显示成那样，就得把这些图拿下来。

## 设计

* 目录：``assets/game/kuro_icons/<sha1(url)[:2]>/<sha1(url)>.<ext>``
  （用 URL 的哈希当文件名 —— URL 里带时间戳，直接拿末段会撞名）
* ``ensure(url)``  → 本地路径（已存在就直接返回，不重复下载）
* ``pixmap(url, size)`` → 现成的 ``QPixmap``（拿不到就返回空 pixmap）
* **同步下载**，但只在**调用线程**里跑 —— 界面调用前应该先批量
  ``ensure_many()``（在后台线程里），否则会卡界面
* ⚠ **磁盘上没有就返回空**，不抛异常 —— 界面上少一个图标不该崩

## 和 `core/assets.py` 的关系

那边是"资源库更新"用的（按**已知清单**批量补图）。
这边是"运行时遇到新 URL 就顺手缓存"，两者互不干扰，
但都落在 ``assets/game/`` 下（同一个 .gitignore 规则）。
"""

from __future__ import annotations

import hashlib
import logging
import ssl
import urllib.request
from pathlib import Path

from . import paths

logger = logging.getLogger(__name__)

#: 缓存子目录
ICON_DIR = "kuro_icons"

#: 下载超时（秒）
TIMEOUT = 20

#: 单张上限（20MB —— 正常 3~30KB，给足余量防跑飞）
MAX_BYTES = 20 * 1024 * 1024

#: 图床要 Referer
REFERER = "https://www.kurobbs.com/"

#: PNG 文件头
_PNG_MAGIC = b"\x89PNG"


def icon_root() -> Path:
    """图标缓存根目录。"""
    return paths.resource_dir("assets", "game", ICON_DIR)


def _key(url: str) -> str:
    return hashlib.sha1(str(url).encode("utf-8")).hexdigest()


def local_path(url: str, ext: str = ".png") -> Path:
    """``url`` 对应的本地路径（**不保证存在**）。"""
    key = _key(url)
    return icon_root() / key[:2] / f"{key}{ext}"


def ensure(url: str, *, timeout: int = TIMEOUT) -> Path | None:
    """确保 ``url`` 已缓存到本地，返回路径；失败返回 ``None``。

    ⚠ **已存在就直接返回，绝不重复下载**（图床会限流）。
    """
    url = str(url or "").strip()
    if not url.startswith("http"):
        return None
    path = local_path(url)
    if path.is_file() and path.stat().st_size > 0:
        return path
    try:
        ctx = ssl.create_default_context()
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": REFERER,
        })
        with urllib.request.urlopen(req, timeout=timeout,
                                    context=ctx) as resp:
            data = resp.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            logger.warning("图标太大，跳过：%s", url)
            return None
        if not data.startswith(_PNG_MAGIC):
            logger.warning("不是 PNG，跳过：%s", url)
            return None
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path
    except Exception as exc:                   # noqa: BLE001 - 少个图标不该崩
        logger.debug("图标下载失败 %s：%s", url, exc)
        return None


def ensure_many(urls, *, log=None) -> tuple[int, int]:
    """批量下载（**在后台线程里调**）。返回 ``(成功, 失败)``。

    界面上要显示几十个图标，逐个 ``ensure`` 会卡 ——
    所以拉数据的时候顺手在这儿下好。
    """
    seen: set[str] = set()
    ok = bad = 0
    for url in urls or ():
        url = str(url or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        if ensure(url):
            ok += 1
        else:
            bad += 1
        if log and (ok + bad) % 10 == 0:
            log(f"   图标 {ok + bad}/{len(seen)}…")
    return ok, bad


def collect_urls(detail: dict) -> list[str]:
    """从一个角色的详情里**收集所有 ``iconUrl``**。

    涵盖：属性 / 技能 / 共鸣链 / 武器 / 声骸 / 声骸套装。
    """
    urls: list[str] = []

    def take(node, *keys):
        if isinstance(node, dict):
            for k in keys:
                v = node.get(k)
                if isinstance(v, str) and v.startswith("http"):
                    urls.append(v)

    if not isinstance(detail, dict):
        return urls

    for key in ("roleAttributeList", "equipPhantomAddPropList"):
        for item in detail.get(key) or []:
            take(item, "iconUrl")

    for item in detail.get("skillList") or []:
        take(item.get("skill") or {}, "iconUrl")

    for item in detail.get("chainList") or []:
        take(item, "iconUrl")

    weapon = (detail.get("weaponData") or {}).get("weapon") or {}
    take(weapon, "weaponIcon")
    for item in (detail.get("weaponData") or {}).get("mainPropList") or []:
        take(item, "iconUrl")

    ph = detail.get("phantomData") or {}
    for item in ph.get("equipPhantomList") or []:
        take(item.get("phantomProp") or {}, "iconUrl")
        take(item.get("fetterDetail") or {}, "iconUrl")
        for sub in ("mainProps", "subProps"):
            for prop in item.get(sub) or []:
                take(prop, "iconUrl")

    #: 角色自己的头像
    take(detail.get("role") or {}, "roleIconUrl", "rolePicUrl")
    return urls


def pixmap(url: str, size: int = 20):
    """把已缓存的图标读成 ``QPixmap``；没有就返回**空 pixmap**。

    ⚠ 不下载 —— 只读缓存。要下载先在后台线程 ``ensure_many()``。
    """
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPixmap

    path = local_path(url)
    if not path.is_file():
        return QPixmap()
    pix = QPixmap(str(path))
    if pix.isNull():
        return pix
    return pix.scaled(size, size,
                      Qt.AspectRatioMode.KeepAspectRatio,
                      Qt.TransformationMode.SmoothTransformation)


def stats() -> tuple[int, int]:
    """``(文件数, 总字节)`` —— 给"清理缓存"之类用。"""
    root = icon_root()
    if not root.is_dir():
        return 0, 0
    n = total = 0
    for p in root.rglob("*.png"):
        try:
            n += 1
            total += p.stat().st_size
        except OSError:
            continue
    return n, total


def clear() -> int:
    """删掉整个缓存，返回删了几个文件。"""
    root = icon_root()
    if not root.is_dir():
        return 0
    n = 0
    for p in sorted(root.rglob("*"), reverse=True):
        try:
            if p.is_file():
                p.unlink()
                n += 1
            elif p.is_dir():
                p.rmdir()
        except OSError:
            continue
    return n
