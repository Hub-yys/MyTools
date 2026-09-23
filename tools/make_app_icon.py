"""生成应用图标 ``assets/app.ico``（安装包 / exe 用）。

没有现成的 app 级图标，这里用**项目自己已经在用的 qfluentwidgets 图标集**
（``FluentIcon.DEVELOPER_TOOLS``，工具箱语义）画一个圆角方块底 + 白色字形，
风格和界面里其它图标一致 —— 不引入外来素材。

想换图标：直接替换 ``assets/app.ico`` 即可，不用改这个脚本。

    python tools/make_app_icon.py
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "app.ico"

#: 底色调成 Fluent 主色系，深色 / 浅色桌面上都看得清
BACKGROUND = "#0F6CBD"
#: 先按大尺寸画、再缩小，边缘比直接画小图干净得多
CANVAS = 1024
#: 字形占画布的比例
GLYPH_RATIO = 0.60
#: .ico 里要包含的尺寸
SIZES = (16, 24, 32, 48, 64, 128, 256)


def main() -> int:
    sys.path.insert(0, str(ROOT))

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QPainter, QPixmap
    from PySide6.QtWidgets import QApplication
    from qfluentwidgets import FluentIcon

    app = QApplication([])  # QPixmap 需要 QApplication

    canvas = QPixmap(CANVAS, CANVAS)
    canvas.fill(Qt.GlobalColor.transparent)

    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(BACKGROUND))
    radius = int(CANVAS * 0.22)          # Windows 应用磁贴那种圆角
    painter.drawRoundedRect(0, 0, CANVAS, CANVAS, radius, radius)

    glyph_size = int(CANVAS * GLYPH_RATIO)
    glyph = FluentIcon.DEVELOPER_TOOLS.icon().pixmap(glyph_size, glyph_size)
    painter.drawPixmap((CANVAS - glyph_size) // 2, (CANVAS - glyph_size) // 2, glyph)
    painter.end()

    # 用 PIL 组装多尺寸 .ico（Qt 存不了 ico）
    from PIL import Image

    png = OUT.with_suffix(".png")
    if not canvas.save(str(png), "PNG"):
        raise SystemExit("PNG 保存失败：%s" % png)
    try:
        with Image.open(png) as image:
            image.convert("RGBA").save(OUT, format="ICO", sizes=[(s, s) for s in SIZES])
    finally:
        png.unlink(missing_ok=True)

    print("已生成 %s（%.1f KB，含尺寸 %s）"
          % (OUT, OUT.stat().st_size / 1024, "、".join(str(s) for s in SIZES)))
    del app
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
