"""批量生成占位图标（角色头像 / 声骸套装 / 声骸）。

**不含任何官方素材** —— 全部是程序画出来的渐变色块 + 名称首字，只为了让界面有图可显示。
数据来源是 ``src/core/game_data.py``，所以加一个新角色/套装/声骸后重跑一遍这个脚本就行：

    .venv\\Scripts\\python tools\\make_placeholders.py

颜色按名称算出来（用 crc32，跨进程稳定），所以同一个名字每次生成的颜色都一样。
想换成真实图标：跑 ``tools/fetch_wuwa_assets.py`` 从 wiki 下载，或直接把同名 png
覆盖到 ``assets/game/<分类>/`` 下即可，不用改代码。

⚠ **只补缺的，不覆盖已有的**（除非加 ``--force``）—— 已经有真图了就不该被色块冲掉。
"""

from __future__ import annotations

import argparse
import colorsys
import pathlib
import sys
import zlib

from PIL import Image, ImageDraw, ImageFont

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.core.game_data import (  # noqa: E402
    ASSETS_ROOT,
    CHARACTERS,
    COST_1,
    COST_3,
    COST_4,
    ECHO_SETS,
    EchoInfo,
)

SIZE = 128
FONT_CANDIDATES = (
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\simsun.ttc",
)


def load_font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if pathlib.Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def hue_of(text: str) -> int:
    """按名字取一个稳定的色相（crc32 不受 PYTHONHASHSEED 影响）。"""
    return zlib.crc32(text.encode("utf-8")) % 360


def gradient(size: int, hue: int, sat: float, light_top: float, light_bottom: float):
    """竖直线性渐变的底图。"""
    image = Image.new("RGB", (size, size))
    draw = ImageDraw.Draw(image)
    for y in range(size):
        t = y / max(1, size - 1)
        light = light_top + (light_bottom - light_top) * t
        r, g, b = colorsys.hls_to_rgb(hue / 360.0, light, sat)
        draw.line([(0, y), (size, y)], fill=(int(r * 255), int(g * 255), int(b * 255)))
    return image


def rounded_mask(size: int, radius: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=255)
    return mask


def circle_mask(size: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
    return mask


def draw_centered(draw: ImageDraw.ImageDraw, text: str, font, box: tuple[int, int, int, int],
                  fill) -> None:
    left, top, right, bottom = box
    tl, tt, tr, tb = draw.textbbox((0, 0), text, font=font)
    x = left + (right - left - (tr - tl)) / 2 - tl
    y = top + (bottom - top - (tb - tt)) / 2 - tt
    draw.text((x, y), text, font=font, fill=fill)


def make_avatar(name: str, out: pathlib.Path) -> None:
    """角色头像：圆形渐变 + 首字。"""
    hue = hue_of(name)
    image = gradient(SIZE, hue, 0.62, 0.42, 0.30).convert("RGBA")
    image.putalpha(circle_mask(SIZE))
    draw = ImageDraw.Draw(image)
    draw_centered(draw, name[0], load_font(60), (0, 0, SIZE, SIZE), (255, 255, 255, 245))
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out)


def make_echo_set(name: str, out: pathlib.Path) -> None:
    """套装图标：大圆角方形 + 首字 + 顶部一道亮边。"""
    hue = hue_of(name)
    image = gradient(SIZE, hue, 0.55, 0.46, 0.34).convert("RGBA")
    image.putalpha(rounded_mask(SIZE, 34))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((10, 10, SIZE - 11, 24), radius=7, fill=(255, 255, 255, 70))
    draw_centered(draw, name[0], load_font(58), (0, 0, SIZE, SIZE), (255, 255, 255, 245))
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out)


def make_echo(item: EchoInfo, out: pathlib.Path) -> None:
    """声骸图标：圆角方形 + 首字 + 右下角费用角标（4/3/1）。"""
    hue = hue_of(item.name) if item.cost == COST_4 else hue_of(item.name) + 24 * (4 - item.cost)
    image = gradient(SIZE, hue % 360, 0.50, 0.52, 0.40).convert("RGBA")
    image.putalpha(rounded_mask(SIZE, 26))
    draw = ImageDraw.Draw(image)
    draw_centered(draw, item.name[0], load_font(56), (0, 0, SIZE, SIZE - 8), (255, 255, 255, 240))

    badge_text = {COST_4: "4", COST_3: "3", COST_1: "1"}[item.cost]
    draw.ellipse((SIZE - 46, SIZE - 46, SIZE - 6, SIZE - 6), fill=(20, 22, 28, 205))
    draw_centered(draw, badge_text, load_font(28), (SIZE - 46, SIZE - 48, SIZE - 6, SIZE - 4),
                  (255, 255, 255, 250))
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="生成角色头像 / 声骸套装 / 声骸的占位图标（默认只补缺的）"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="连已存在的文件也覆盖。默认不覆盖 —— 见下面那段注释",
    )
    args = parser.parse_args()

    created = 0
    kept = 0

    def emit(path: pathlib.Path, make) -> None:
        """写一张占位图 —— **已经存在的文件默认不动**。

        为什么必须这样：`fetch_wuwa_assets.py` 下回来的真图标（头像 / 套装 / 声骸）
        就放在同一个目录、同名。无脑重写会把它们全冲成自绘色块 ——
        2026-09-21 连犯两次（用户头像全变成占位图）。
        真要重画用 ``--force``。
        """
        nonlocal created, kept
        if path.exists() and not args.force:
            kept += 1
            return
        make()
        created += 1

    for character in CHARACTERS:
        emit(ASSETS_ROOT / character.avatar, lambda c=character: make_avatar(c.name, ASSETS_ROOT / c.avatar))

    seen: set[str] = set()
    for echo_set in ECHO_SETS:
        emit(
            ASSETS_ROOT / echo_set.icon,
            lambda s=echo_set: make_echo_set(s.name, ASSETS_ROOT / s.icon),
        )
        for item in echo_set.echoes:
            if item.icon in seen:
                continue
            seen.add(item.icon)
            emit(ASSETS_ROOT / item.icon, lambda i=item: make_echo(i, ASSETS_ROOT / i.icon))

    print(f"[OK] 新生成 {created} 张占位图（跳过已存在的 {kept} 张）→ {ASSETS_ROOT}")
    print(f"     角色 {len(CHARACTERS)} / 套装 {len(ECHO_SETS)} / 声骸 {len(seen)}")
    if kept and not args.force:
        print("     想连已有文件一起重画，加 --force（注意会覆盖下载回来的真图标）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
