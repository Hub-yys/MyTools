# -*- coding: utf-8 -*-
"""★ 壁纸 / 液态玻璃设置 —— **照抄 dsh-plugin-wallpaper-engine 的参数表**。

## 用户 2026-11-01

    > 既然你不会调设置，那把这个插件的设置拿过来

## 从插件源码挖出来的完整参数表

``dsh-plugin-wallpaper-engine/lib/settings-schema.js``::

    // ── 壁纸外观（L492-495）─────────────────────────────
    scrim: 0.25                    //: 整体暗化层 0~1
    border: 0.35                   //: 边框强度 0~1
    blur: 16                       //: 面板雾化 px 0~60
    wallpaperBlur: 0               //: 壁纸本身模糊 px 0~60
    backgroundBrightness: 100      //: 壁纸亮度 % 40~160
    backgroundContrast: 100        //: 壁纸对比度 % 40~200
    backgroundSaturate: 100        //: 壁纸饱和度 % 0~200
    wallpaperOpacity: 100          //: 壁纸不透明度 % 0~90

    // ── 液态玻璃（L638-645）─────────────────────────────
    accent: "#4f8cff"              //: 主题强调色
    glassAlpha: 20                 //: 玻璃透明度 % 0~100
    glassColor: {light,dark}       //: 玻璃底色（默认 #ffffff）
    glassDarkSeparate: false       //: 深色单独设置
    glassFidelity: 100             //: 玻璃保真度 % 0~100

    // ── 边框/圆角（L683-692）────────────────────────────
    leftSidebarCornerRadius: '20'
    rightSidebarCornerRadius: '20'

## 关键发现：``scrim`` 才是"暗"的主因

之前我一直以为是 ``glassAlpha``。实际上插件里有两层：

  * ``scrim`` (0.25) —— **整个壁纸**上盖一层黑
  * ``glassAlpha`` (20%) —— 面板玻璃的透明度

两者叠加才是最终观感。之前我只做了 ``tint``（类似 scrim），
但**没有把面板的 glassAlpha 和 border 拆出来**。

## 本模块的定位

  * 存参数（``wallpaper.json`` 旁边存一份）
  * 给 :mod:`src.core.skins` 和 Web 外壳（``src/gui/web/css/base.css``）读
  * 提供 UI（见 ``src/gui/wallpaper_settings.py``）
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

#: ★ 默认值 —— **逐项照抄插件**（settings-schema.js 的 DEFAULTS）
DEFAULTS: dict = {
    #: 壁纸外观
    "scrim": 0.50,                 #: 整体暗化层 0~1（DSH 设的 50%）
    "border": 0.35,                #: 边框强度 0~1
    "blur": 16,                    #: 面板雾化 px 0~60
    "wallpaperBlur": 0,            #: 壁纸本身模糊 px 0~60
    "backgroundBrightness": 75,    #: 壁纸亮度 % 40~160（DSH 设的 75%）
    "backgroundContrast": 110,     #: 壁纸对比度 % 40~200（DSH 设的 110%）
    "backgroundSaturate": 150,     #: 壁纸饱和度 % 0~200（DSH 设的 150%）
    "wallpaperOpacity": 0,         #: 壁纸透明度 % 0~90（DSH 设的 0%）
    #: 液态玻璃
    "accent": "#4f8cff",           #: 强调色
    "glassAlpha": 20,              #: 玻璃透明度 % 0~100
    "glassColor": "#ffffff",       #: 玻璃底色（深色主题会被钳制）
    "glassDarkSeparate": False,    #: 深色单独设置
    "glassDarkColor": "#0d1524",   #: 深色玻璃底色
    "glassFidelity": 100,          #: 玻璃保真度 % 0~100
    #: 跟随壁纸主色（我们的扩展，插件没有）
    "autoAccent": True,            #: 自动从壁纸抽主色
}

#: 每一项的取值范围（照抄插件 ``SETTING_SPECS`` 的 min/max）
RANGES: dict = {
    "scrim": (0.0, 1.0, 0.05),
    "border": (0.0, 1.0, 0.05),
    "blur": (0, 60, 1),
    "wallpaperBlur": (0, 60, 1),
    "backgroundBrightness": (40, 160, 5),
    "backgroundContrast": (40, 200, 5),
    "backgroundSaturate": (0, 200, 5),
    "wallpaperOpacity": (0, 90, 5),
    "glassAlpha": (0, 100, 5),
    "glassFidelity": (0, 100, 5),
}

#: 中文标签（给 UI 用）
LABELS: dict = {
    "scrim": "整体暗化",
    "border": "边框",
    "blur": "面板雾化",
    "wallpaperBlur": "壁纸模糊",
    "backgroundBrightness": "壁纸亮度",
    "backgroundContrast": "壁纸对比度",
    "backgroundSaturate": "壁纸饱和度",
    "wallpaperOpacity": "壁纸不透明度",
    "accent": "强调色",
    "glassAlpha": "玻璃透明度",
    "glassColor": "玻璃颜色",
    "glassDarkSeparate": "深色单独设置",
    "glassDarkColor": "深色玻璃颜色",
    "glassFidelity": "玻璃保真度",
    "autoAccent": "主题随壁纸",
}

#: 内存里的当前值（启动时从盘读）
_values: dict = dict(DEFAULTS)


def _path():
    """配置文件路径（和 ``wallpaper.json`` 同目录）。"""
    try:
        from . import paths  # noqa: PLC0415

        return paths.user_data_dir() / "wallpaper_settings.json"
    except Exception:  # noqa: BLE001
        return None


def load() -> dict:
    """从盘读设置（失败就用默认值）。"""
    global _values
    p = _path()
    data = {}
    if p is not None:
        try:
            if p.is_file():
                with open(p, encoding="utf-8") as fh:
                    data = json.load(fh) or {}
        except (OSError, ValueError):
            logger.warning("壁纸设置：读取失败，用默认值", exc_info=True)
    #: 只接受已知键，且做范围钳制（防止手改配置写出非法值）
    out = dict(DEFAULTS)
    for k, v in (data or {}).items():
        if k not in DEFAULTS:
            continue
        out[k] = _clamp(k, v)
    _values = out
    return dict(_values)


def save(**kw) -> None:
    """写设置到盘（只写已知键）。"""
    global _values
    for k, v in (kw or {}).items():
        if k in DEFAULTS:
            _values[k] = _clamp(k, v)
    p = _path()
    if p is None:
        return
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(_values, fh, ensure_ascii=False, indent=2)
    except OSError:
        logger.warning("壁纸设置：保存失败", exc_info=True)


def get(key: str, default=None):
    """读一项。"""
    if key in _values:
        return _values[key]
    return DEFAULTS.get(key, default)


def all_values() -> dict:
    """读全部（副本）。"""
    return dict(_values)


def reset() -> None:
    """恢复默认。"""
    global _values
    _values = dict(DEFAULTS)
    save()


def _clamp(key: str, value):
    """按 :data:`RANGES` 钳制数值；其它类型做基本校验。"""
    if key in RANGES:
        lo, hi, _step = RANGES[key]
        try:
            v = float(value)
        except (TypeError, ValueError):
            return DEFAULTS[key]
        #: 整数项返回 int（避免 UI 显示 20.0）
        if isinstance(DEFAULTS[key], int):
            return max(int(lo), min(int(hi), int(round(v))))
        return max(lo, min(hi, v))
    if key in ("glassColor", "glassDarkColor", "accent"):
        s = str(value or "")
        if s.startswith("#") and len(s) in (4, 7):
            return s
        return DEFAULTS[key]
    if isinstance(DEFAULTS[key], bool):
        return bool(value)
    return value


def glass_layers() -> dict:
    """★ 算出玻璃配方的**实际数值**（给 QSS 用）。

    ## 这是核心：把插件那套 CSS ``color-mix`` 换算成 rgba

    插件的公式（``client.js`` L2195-2197）::

        --we-readability-floor-base: 0.59          (深色 READABILITY_FLOOR_DARK)
        --we-readability-base: #0d1524
        --we-glass-alpha: glassAlpha / 100

        background = color-mix(
            base × floor,
            tint × glass_alpha × 0.9~1.1)

    换算::

        深色底 alpha = floor = 0.59
        玻璃色 alpha = (1 - floor) × glass_alpha

    :return: ``{"floor": 0.59, "base_rgb": (13,21,36),
               "glass_rgb": (..), "glass_alpha": 0.16,
               "scrim": 0.25, "border": 0.35, "blur": 16}``
    """
    from . import color_extract as CE  # noqa: PLC0415

    floor = 0.59
    base_rgb = (13, 21, 36)          #: #0d1524
    ga = max(0, min(100, int(get("glassAlpha") or 0))) / 100.0
    #: 用户选了玻璃色就用它；否则用壁纸主色
    gc = str(get("glassColor") or DEFAULTS["glassColor"])
    if get("autoAccent"):
        prim = ""
        try:
            from . import skins  # noqa: PLC0415

            prim = skins.wallpaper_palette()[0]
        except Exception:  # noqa: BLE001
            prim = ""
        if prim:
            gc = prim
    try:
        h = gc.lstrip("#")
        glass_rgb = (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except (ValueError, IndexError):
        glass_rgb = (79, 140, 255)
    return {
        "floor": floor,
        "base_rgb": base_rgb,
        "glass_rgb": glass_rgb,
        "glass_alpha": (1.0 - floor) * ga,
        "scrim": float(get("scrim") or 0.0),
        "border": float(get("border") or 0.0),
        "blur": int(get("blur") or 0),
        "wallpaper_blur": int(get("wallpaperBlur") or 0),
        "brightness": int(get("backgroundBrightness") or 100) / 100.0,
        "contrast": int(get("backgroundContrast") or 100) / 100.0,
        "saturate": int(get("backgroundSaturate") or 100) / 100.0,
        "wallpaper_opacity": int(get("wallpaperOpacity") or 100) / 100.0,
        "accent": str(get("accent") or DEFAULTS["accent"]),
    }
