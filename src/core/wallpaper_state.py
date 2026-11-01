# -*- coding: utf-8 -*-
"""★ 壁纸选择状态（持久化 —— 下次打开还是这个壁纸）。

## 为什么单独一个模块

``skins`` 管的是**配色主题**（QSS），壁纸是**独立的背景层** ——
两者可以自由组合（同一个壁纸 + 不同配色主题）。

混进 ``skins`` 会让那边的 ``_PAINTED_QSS`` 缓存逻辑变复杂，
所以拆出来。

## 存哪

``<用户数据>/wallpaper.json``::

    {"id": "3674449694", "path": "D:/Steam/.../xxx.mp4"}

⚠ **同时存 id 和 path**：

* ``id`` 用来在壁纸库界面上标「使用中」
* ``path`` 是实际播放路径 —— WE 目录可能搬家，那时 id 还在但 path 失效，
  可以按 id 重新扫描找回来
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

#: 文件名（在 ``paths.user_data_dir()`` 下）
_FILENAME = "wallpaper.json"


def _file():
    from . import paths

    return paths.user_data_dir() / _FILENAME


def load() -> dict:
    """读壁纸配置（读不到返回空 dict）。"""
    try:
        p = _file()
        if not p.is_file():
            return {}
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001 - 配置坏了当没有
        logger.warning("壁纸状态：读取失败", exc_info=True)
        return {}


def save(data: dict) -> None:
    """写壁纸配置。"""
    try:
        p = _file()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                     encoding="utf-8")
    except Exception:  # noqa: BLE001
        logger.warning("壁纸状态：写入失败", exc_info=True)


def current_id() -> str:
    """当前壁纸 id（没选返回空串）。"""
    return str(load().get("id") or "")


def current_path() -> str:
    """当前壁纸的实际播放路径（没选返回空串）。"""
    return str(load().get("path") or "")


def set_current(wp_id: str, path: str = "") -> None:
    """设置当前壁纸。

    :param wp_id: 壁纸 id（空串 = 关闭壁纸）
    :param path: 视频实际路径（可选；不传则只记 id）
    """
    if not wp_id:
        save({})
        logger.info("壁纸状态：已关闭")
        return
    data = load()
    data["id"] = str(wp_id)
    if path:
        data["path"] = str(path)
    save(data)
    logger.info("壁纸状态：设为 %s", wp_id)


def clear() -> None:
    """清掉壁纸选择。"""
    set_current("")
