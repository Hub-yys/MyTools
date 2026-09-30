"""生成**工具图标**（``assets/icons/<名字>.png``）。

和 ``tools/make_app_icon.py`` 同一套画法（qfluentwidgets 的 FluentIcon 字形 + 圆角底），
只是输出成 512×512 的 png —— 侧栏和主页的工具卡片用的是这个。

    python tools/make_tool_icon.py auto_combat GAME "#C0392B"

参数：工具 key、FluentIcon 成员名、底色（可省，默认 Fluent 主色蓝）。

⚠ **2026-09-30 起五个工具都有专门设计的图标了**（用户提供的 SVG 转 PNG），
现在这个脚本只在"**新加工具、暂时没图**"时用来顶一下：

    4C 自动战斗      assets/icons/auto_combat.png
    声骸自动强化      assets/icons/echo_enhance.png
    声骸批量调频      assets/icons/echo_change.png
    抽卡记录分析      assets/icons/gacha.png
    资源库更新       assets/icons/wuwa_library_update.png

**别拿这个脚本去覆盖它们** —— 生成的是一色底 + 单色字形，
和那套设计好的图完全不同。``assets/icons/`` 也不在 .gitignore 里
（工具图标是**自制**的，不是游戏素材，入库）。
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "assets" / "icons"

CANVAS = 512
GLYPH_RATIO = 0.58


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2
    name, glyph_name = argv[1], argv[2]
    background = argv[3] if len(argv) > 3 else "#0F6CBD"

    sys.path.insert(0, str(ROOT))

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QPainter, QPixmap
    from PySide6.QtWidgets import QApplication
    from qfluentwidgets import FluentIcon

    if not hasattr(FluentIcon, glyph_name):
        print("FluentIcon 里没有 %s" % glyph_name)
        return 2

    app = QApplication([])  # QPixmap 需要 QApplication

    canvas = QPixmap(CANVAS, CANVAS)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(background))
    radius = int(CANVAS * 0.22)
    painter.drawRoundedRect(0, 0, CANVAS, CANVAS, radius, radius)

    size = int(CANVAS * GLYPH_RATIO)
    glyph = getattr(FluentIcon, glyph_name).icon().pixmap(size, size)
    painter.drawPixmap((CANVAS - size) // 2, (CANVAS - size) // 2, glyph)
    painter.end()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{name}.png"
    if not canvas.save(str(out), "PNG"):
        raise SystemExit("保存失败：%s" % out)
    print("已生成 %s（%d×%d，字形 %s，底色 %s）"
          % (out, CANVAS, CANVAS, glyph_name, background))
    del app
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
