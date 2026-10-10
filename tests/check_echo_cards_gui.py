# -*- coding: utf-8 -*-
r"""把「结果报告 + 符合条件的声骸卡片」真渲染出来看一眼。

    .\.venv\Scripts\python.exe tests\check_echo_cards_gui.py

用**真实的历史截图**（data/okww/screenshots/success 下那两张真图）填卡片。
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SHOTS = ROOT / "tests" / "_shots"
SS = ROOT / "data" / "okww" / "screenshots" / "success"


def main() -> int:
    import os

    from PySide6.QtGui import QColor, QPixmap
    from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

    app = QApplication(sys.argv)
    os.environ.setdefault("QT_QPA_PLATFORM", "windows")

    from src.core import paths, skins

    skins.apply_skin("mist", save=False)

    from src.tools.game.echo_enhance import tool as T

    #: 用真实的成功截图（有多少用多少；一张都没有就造一张假的）
    real = sorted(SS.glob("*_original.png")) if SS.is_dir() else []
    print("真实成功截图:", [p.name for p in real] or "（没有，用假图）")

    items = []
    if real:
        for i, p in enumerate(real[:2], 1):
            items.append({
                "index": i,
                "stats": ["暴击 10.5", "暴击伤害 21", "攻击 30",
                          "攻击百分比 6.4", "生命 430"][: 3 + i],
                "image": p.name,
            })
    else:
        items = [{"index": 1, "stats": ["暴击 9.9", "暴击伤害 15", "攻击 30"],
                  "image": ""}]

    host = QWidget()
    host.setObjectName("host")
    host.setStyleSheet("#host { background: #fdfdfe; }")
    lay = QVBoxLayout(host)
    lay.setContentsMargins(20, 20, 20, 20)
    lay.setSpacing(10)

    for it in items:
        lay.addWidget(T.QualifyingEchoCard(it, index=it["index"],
                                           is_perfect=(it["index"] == 1)))
    host.resize(460, 10)
    host.show()
    app.processEvents()
    host.adjustSize()
    host.resize(460, host.sizeHint().height())
    for _ in range(3):
        app.processEvents()

    SHOTS.mkdir(parents=True, exist_ok=True)
    pm = QPixmap(host.size())
    pm.fill(QColor("#fdfdfe"))
    host.render(pm)
    out = SHOTS / "echo_cards_preview.png"
    pm.save(str(out))
    print("截图:", out, host.size())
    return 0


if __name__ == "__main__":
    sys.exit(main())
