"""生成「查询角色练度」的工具图标 —— 风格对齐现有那 5 个。

## 现有图标的样式（看了 echo_change.png）

    · 512x512
    · **深色底**（近黑，略偏蓝）圆角方块
    · **金色细边框**（约 3px）
    · 主体是**发光的紫色线条图标**（line-art，带外发光）
    · 居中，四周留白充足

## 本脚本

用 PIL 画一个同规格的：
    主体 = 角色卡片（圆角矩形 + 头像圆点 + 两条文字线）
           + 放大镜（压在卡片右下角）
    表示"查看角色详情"。
"""
import math
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8")

from PIL import Image, ImageDraw, ImageFilter

SIZE = 512
OUT = pathlib.Path(
    r"D:\AI Work\workbuddy\MyTools\assets\icons\character_build.png")

#: 现有图标的配色（取自 echo_change.png）
BG = (23, 26, 38)              # 深色底
BORDER = (198, 160, 74)        # 金色边框
GLOW = (123, 97, 255)          # 发光紫
LINE = (157, 140, 255)         # 线条亮紫

#: 圆角半径
RADIUS = 96
#: 内容缩放（留白）
PAD = 104


def rounded_mask(size: int, radius: int) -> Image.Image:
    m = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(m)
    d.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=255)
    return m


def draw_motif(draw: ImageDraw.ImageDraw, color, width: int) -> None:
    """画主体：角色卡片 + 放大镜（**放大镜在卡片外侧**，不压住卡片）。"""
    # ── 角色卡片（圆角矩形）—— 往左上缩，给放大镜腾地方
    card = (PAD - 10, PAD - 30, SIZE - PAD - 92, SIZE - PAD - 96)
    draw.rounded_rectangle(card, radius=24, outline=color, width=width)

    # ── 头像圆点
    cx, cy, r = card[0] + 48, card[1] + 52, 25
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=color,
                 width=width)

    # ── 两条文字线
    x0 = cx + r + 22
    for i, y in enumerate((cy - 14, cy + 16)):
        draw.line((x0, y, card[2] - 28 - i * 30, y), fill=color, width=width)

    # ── 放大镜（**右下角外侧**，和卡片只是轻轻相切）
    lx = card[2] + 8
    ly = card[3] + 8
    lr = 58
    draw.ellipse((lx - lr, ly - lr, lx + lr, ly + lr), outline=color,
                 width=width + 4)
    #: 手柄（45° 向右下）
    hx = lx + lr * math.cos(math.radians(45))
    hy = ly + lr * math.sin(math.radians(45))
    draw.line((hx, hy, hx + 46, hy + 46), fill=color, width=width + 8)


def build() -> Image.Image:
    # ── 底色 + 圆角
    base = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    plate = Image.new("RGBA", (SIZE, SIZE), BG + (255,))
    base.paste(plate, (0, 0), rounded_mask(SIZE, RADIUS))

    # ── 金色边框
    edge = ImageDraw.Draw(base)
    edge.rounded_rectangle((2, 2, SIZE - 3, SIZE - 3), radius=RADIUS,
                           outline=BORDER + (255,), width=3)

    # ── 发光层（先画粗的模糊紫线）
    glow = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw_motif(ImageDraw.Draw(glow), GLOW + (170,), 14)
    glow = glow.filter(ImageFilter.GaussianBlur(18))

    # ── 主线条层
    lines = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw_motif(ImageDraw.Draw(lines), LINE + (255,), 11)

    out = Image.alpha_composite(base, glow)
    out = Image.alpha_composite(out, lines)
    return out


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    img = build()
    img.save(OUT)
    print(f"✓ 已生成 -> {OUT}")
    print(f"   尺寸 {img.size[0]}x{img.size[1]}"
          f"   大小 {OUT.stat().st_size / 1024:.1f} KB")

    #: 和现有的对比
    for name in ("echo_change", "gacha", "auto_combat"):
        p = OUT.parent / f"{name}.png"
        if p.exists():
            im = Image.open(p)
            print(f"   （现有 {name}.png: {im.size[0]}x{im.size[1]}"
                  f"  {p.stat().st_size / 1024:.1f} KB）")


if __name__ == "__main__":
    main()
