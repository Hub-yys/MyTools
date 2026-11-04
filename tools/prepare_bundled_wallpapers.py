# -*- coding: utf-8 -*-
"""把 7 个精选主题壁纸转好，落到 ``assets/wallpapers/<id>.webm``（随安装包一起发）。

## 为什么要有这一步

用户 2026-11-04：

    > 视频单独打包放在一个文件夹，安装完后，壁纸就读这个路径下的，不行吗

可以，而且比读创意工坊稳 —— 装完就有，不依赖 Wallpaper Engine 有没有装、
订阅还在不在。但要放进去的**必须是转好的 VP9 webm**，不能是源 mp4：
QtWebEngine 不带 H.264 解码器（详见 ``packaging/mytools.spec`` 里 ffmpeg 那段），
源 mp4 放进去也只是一堆放不出来的文件。

## 跑法

.. code:: bash

    .venv/Scripts/python.exe tools/prepare_bundled_wallpapers.py

* 目标文件已存在且 > 4096 字节 → 跳过（**不会**每次打包都重转几分钟）
* ``--force`` → 全部重转
* 源视频从 Wallpaper Engine 创意工坊读；心月狐那种 scene 型会先走
  :func:`src.core.wallpaper_engine.resolve_scene_video` 从 ``scene.pkg`` 抠出来

打包时由 ``package.ps1`` 在 PyInstaller **之前**调一次（见那边的说明）。
产物 ``assets/wallpapers/`` 不进 git（第三方素材，同 ``assets/game/`` 的理由）。
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_ROOT / "vendor" / "okww") not in sys.path:
    sys.path.insert(0, str(_ROOT / "vendor" / "okww"))

OUT_DIR = _ROOT / "assets" / "wallpapers"


def main() -> int:
    parser = argparse.ArgumentParser(description="准备安装包自带的壁纸 webm")
    parser.add_argument("--force", action="store_true", help="已存在的也重转")
    args = parser.parse_args()

    #: 工具发现要在 import 业务模块之前（和 dev 探针一样的顺序）
    import src.tools as tools_pkg  # noqa: PLC0415

    tools_pkg.discover_tools()

    from src.core import wallpaper_engine, wallpaper_themes, webm_transcode  # noqa: PLC0415

    ffmpeg = webm_transcode.find_ffmpeg()
    if not ffmpeg:
        print("!! 找不到 ffmpeg，没法转码。")
        print("   放到 vendor/ffmpeg/ffmpeg.exe，或设 MYTOOLS_FFMPEG 环境变量。")
        return 1
    print("ffmpeg : %s" % ffmpeg)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("输出   : %s" % OUT_DIR)
    print()

    ok = skipped = failed = 0
    started = time.time()

    for theme in wallpaper_themes.all_themes():
        wp_id = str(theme.get("wallpaper_id") or "")
        name = str(theme.get("name") or wp_id)
        dest = OUT_DIR / f"{wp_id}.webm"

        if dest.is_file() and dest.stat().st_size > 4096 and not args.force:
            print("[跳过] %-6s %s 已存在（%.1f MB）"
                  % (name, dest.name, dest.stat().st_size / 1024 / 1024))
            skipped += 1
            continue

        info = wallpaper_engine.wallpaper_by_id(wp_id, prefer_bundled=False)
        src = (info or {}).get("video_path") or ""
        if not src:
            print("[失败] %-6s 找不到源视频（创意工坊里没有这个 id？）" % name)
            failed += 1
            continue

        suffix = Path(src).suffix.lower()
        if Path(src).resolve() == dest.resolve():
            #: ``--force`` 且源就是上次的产物 → 没有意义（转自己）
            print("[跳过] %-6s 源文件就是自带件本身" % name)
            skipped += 1
            continue
        print("[开始] %-6s ← %s" % (name, Path(src).name), flush=True)
        t0 = time.time()

        if suffix in (".webm", ".ogv", ".ogg"):
            #: 源本身就是能播的格式，直接拷
            shutil.copyfile(src, dest)
        else:
            out = webm_transcode.prepare(src)
            if not out or not Path(out).is_file():
                print("[失败] %-6s ffmpeg 没产出文件" % name)
                failed += 1
                continue
            shutil.copyfile(out, dest)

        size = dest.stat().st_size
        print("[完成] %-6s %s（%.1f MB，%.1f 秒）"
              % (name, dest.name, size / 1024 / 1024, time.time() - t0))
        ok += 1

    print()
    print("=" * 60)
    print("新转 %d 个 / 跳过 %d 个 / 失败 %d 个，共 %.1f 秒"
          % (ok, skipped, failed, time.time() - started))
    total = sum(p.stat().st_size for p in OUT_DIR.glob("*.webm"))
    print("目录合计 %.1f MB" % (total / 1024 / 1024))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
    raise SystemExit(main())
