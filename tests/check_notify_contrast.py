# -*- coding: utf-8 -*-
r"""量消息页在**六款皮肤**下的文字/底色反差（本仓三次栽在"字看不见"上）。

    .\.venv\Scripts\python.exe tests\check_notify_contrast.py
"""
from __future__ import annotations

import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

#: 反差低于这个就算"看不清"（本仓练度页那次实测坏的是 7~11）
MIN_DIFF = 40.0


def _lum(color) -> float:
    return 0.2126 * color.red() + 0.7152 * color.green() + 0.114 * color.blue()


def main() -> int:
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QApplication, QLabel

    app = QApplication(sys.argv)

    from src.core import notifications as N
    from src.core import skins
    from src.gui import notify_page as P

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="notify-contrast-"))
    store = N.NotificationStore(tmp / "n.json")
    store.add("声骸自动强化 · 完成", "符合条件 3 · 弃置 39", level=N.LEVEL_SUCCESS)
    store.add("声骸批量调频 · 失败", "找不到 强化并调谐", level=N.LEVEL_ERROR)
    store.add("4C 自动战斗 · 已自动暂停", "出现符合条件的声骸",
              level=N.LEVEL_INFO)

    rows = []
    print("%-11s %-9s %-9s %s" % ("皮肤", "模式", "最差反差", "结论"))
    print("-" * 62)
    for skin in skins.all_skins():
        skins.apply_skin(skin["id"], save=False)
        page = P.NoticeInterface(store=store)
        page.refresh()
        page.refresh_skin_colors()
        for _ in range(3):
            app.processEvents()

        bg = QColor(P.card_bg_color())
        worst, worst_what = 1e9, ""
        for label in page.findChildren(QLabel):
            name = label.objectName()
            if name not in ("noticeMark", "noticeTitle", "noticeBody",
                            "noticeTime", "noticePageHint"):
                continue
            if not label.text().strip():
                continue
            #: 从 setStyleSheet 里把 color 抠出来
            sheet = label.styleSheet() or ""
            for part in sheet.split(";"):
                if "color:" in part and "background" not in part:
                    hexv = part.split("color:")[1].strip()
                    c = QColor(hexv)
                    if not c.isValid():
                        continue
                    diff = abs(_lum(c) - _lum(bg))
                    if diff < worst:
                        worst, worst_what = diff, name
                    break
        flag = "OK" if worst >= MIN_DIFF else "★ 太接近"
        rows.append(worst >= MIN_DIFF)
        print("%-11s %-9s %-9.1f %s%s" % (
            skin["id"], skin["mode"], worst, flag,
            "" if worst >= MIN_DIFF else f"（{worst_what}）"))
        page.setParent(None)
        page.deleteLater()

    print()
    ok = all(rows)
    print("阈值 %.0f；%d/%d 款通过" % (MIN_DIFF, sum(rows), len(rows)))
    print("★", "全部看得清" if ok else "⚠ 有皮肤下文字看不清")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
