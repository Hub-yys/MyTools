# -*- coding: utf-8 -*-
r"""用**真实账号数据**渲染「查询角色练度」详情页，截图确认改动效果。

    .\.venv\Scripts\python.exe tests\check_chain_icons_gui.py

⚠ 只读 ``data/kuro_练度.json``（用户真实缓存），不写任何东西。
"""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CACHE = ROOT / "data" / "kuro_练度.json"
SHOTS = ROOT / "tests" / "_shots"
SHOTS.mkdir(parents=True, exist_ok=True)

CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append((name, ok, detail))


def main() -> int:
    from PySide6.QtGui import QColor, QPixmap
    from PySide6.QtWidgets import QApplication, QLabel, QWidget

    app = QApplication(sys.argv)

    from src.core import icon_cache as IC
    from src.core import skins

    skins.apply_skin("mist", save=False)

    from src.tools.game.character_build import detail_view as DV
    from src.tools.game.character_build.detail_view import EchoDetailView

    data = json.loads(CACHE.read_text(encoding="utf-8"))
    details = data["details"]

    #: 找一个**有激活也有未激活**、且图标都缓存好了的角色
    pick = None
    for rid, o in details.items():
        ch = [c for c in (o.get("chainList") or []) if isinstance(c, dict)]
        if len(ch) != 6:
            continue
        if not (0 < sum(1 for c in ch if c.get("unlocked")) < 6):
            continue
        if all(not IC.pixmap(c.get("iconUrl"), 40).isNull() for c in ch):
            pick = (rid, o, ch)
            break
    if pick is None:
        print("找不到合适的角色（图标未缓存？）")
        return 1

    rid, detail, chains = pick
    n_on = sum(1 for c in chains if c.get("unlocked"))
    print(f"角色：{detail['role'].get('roleName')}（{n_on}/6 激活）")

    view = EchoDetailView()
    view.resize(1100, 1000)
    view.show_detail(detail)
    view.show()
    for _ in range(4):
        app.processEvents()

    #: 单独拿共鸣链块出来量像素（整块渲染才拿得到正确答案）
    blk = DV._chains_block(chains, None)
    blk.resize(940, 10)
    blk.show()
    app.processEvents()
    blk.adjustSize()
    blk.resize(940, blk.sizeHint().height())
    for _ in range(3):
        app.processEvents()

    # ── ① 图标行里不该有任何黄底方块
    YELLOW = "#ffe9a8"
    guilty = [w.objectName() or type(w).__name__
              for w in view.findChildren(QWidget)
              if YELLOW in (w.styleSheet() or "")]
    check("图标行没有黄底方块", not guilty, f"还有：{guilty}")

    icons = [w for w in view.findChildren(QLabel)
             if w.objectName() == "chainIcon"]
    check("共鸣链图标数 = 6", len(icons) == 6, f"实际 {len(icons)}")

    #: 块里的图标（量亮度用它）
    blk_icons = [w for w in blk.findChildren(QLabel)
                 if w.objectName() == "chainIcon"]
    check("块里图标数 = 6", len(blk_icons) == 6, f"实际 {len(blk_icons)}")

    # ── ② 压暗：未激活的必须**真的**比已激活的暗
    #:
    #: ⚠ 必须读**整块渲染出来的图**，不能拿单个 QLabel 单独 render ——
    #: 带 QGraphicsOpacityEffect 的控件单独 render 得到的是**全黑**
    #: （实测峰值 0），那样这条检查就变成假的通行证了。
    def peak_in(blk_img, i):
        """第 i 个图标在**整块图**里的最亮像素。

        ⚠ 位置**从控件自己问**（``mapTo``），别硬编码内边距/间距 ——
        我第一版写死了 ``12 + i*(40+8)``，结果全量到 0：
        布局实际摆放的位置和那个公式不一样。
        """
        holder = blk_icons[i]
        tl = holder.mapTo(blk, holder.rect().topLeft())
        best = 0.0
        for y in range(tl.y(), min(tl.y() + holder.height(), blk_img.height())):
            for x in range(tl.x(), min(tl.x() + holder.width(), blk_img.width())):
                if x < 0 or y < 0:
                    continue
                c = blk_img.pixelColor(x, y)
                best = max(best, (c.red() + c.green() + c.blue()) / 3)
        return best

    pm_tmp = QPixmap(blk.size())
    pm_tmp.fill(QColor(DV.solid_card_color()))
    blk.render(pm_tmp)
    img = pm_tmp.toImage()
    peaks = [peak_in(img, i) for i in range(len(blk_icons))]
    on = [peaks[i] for i, c in enumerate(chains) if c.get("unlocked")]
    off = [peaks[i] for i, c in enumerate(chains) if not c.get("unlocked")]
    check("已激活的比未激活的亮",
          bool(on) and bool(off) and min(on) > max(off),
          f"已激活 {[round(v) for v in on]} vs 未激活 {[round(v) for v in off]}")
    check("未激活的**还能看见**（没被压没）", bool(off) and min(off) > 0,
          f"最暗 {round(min(off)) if off else 'n/a'}")

    # ── ③ 点未激活那条 → 标题带（未激活）
    idx_off = next(i for i, c in enumerate(chains) if not c.get("unlocked"))
    blk_icons[idx_off].mousePressEvent(None)
    for _ in range(3):
        app.processEvents()
    texts = [t.text() for w in blk.findChildren(QWidget)
             if w.objectName() == "expandPanel"
             for t in w.findChildren(QLabel) if t.text()]
    check("展开未激活那条 → 标题带（未激活）",
          any("（未激活）" in t for t in texts), f"{texts}")

    # ── 截图
    view.grab().save(str(SHOTS / "chain_icons_after.png"))

    #: 再截一张**滚到共鸣链那块**的详情页（整页太长，共鸣链在下面）
    bar = view.verticalScrollBar()
    bar.setValue(bar.maximum())
    for _ in range(3):
        app.processEvents()
    view.grab().save(str(SHOTS / "chain_icons_scrolled.png"))

    #: 再截一张共鸣链块的特写（此时未激活那条已经展开）
    blk.adjustSize()
    blk.resize(940, blk.sizeHint().height())
    for _ in range(2):
        app.processEvents()
    pm = QPixmap(blk.size())
    pm.fill(QColor(DV.solid_card_color()))
    blk.render(pm)
    pm.save(str(SHOTS / "chain_icons_block.png"))

    print()
    bad = [c for c in CHECKS if not c[1]]
    for name, ok, det in CHECKS:
        print(f"  {'OK  ' if ok else 'BAD '} {name}" + (f"   {det}" if det else ""))
    print()
    print(f"截图：{SHOTS / 'chain_icons_after.png'}")
    print(f"      {SHOTS / 'chain_icons_block.png'}")
    print("★", "全部通过" if not bad else f"⚠ {len(bad)} 项没过")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
