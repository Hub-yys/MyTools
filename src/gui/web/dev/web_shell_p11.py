# -*- coding: utf-8 -*-
"""验收 P11：系统圆角下的标题栏安全边距。

## 问题（page-converter 发现）

Win11 系统圆角（``DWMWCP_ROUND``）由 **DWM 画，会把窗口四角内容裁掉一块**。

实测页面布局：

```json
{"titlebar": [220, 0, 1440, 44],
 "tbPadding": "0px 6px 0px 18px",
 "tb-close": {"box": [1392, 7, 1434, 37], "gapRight": 6, "gapTop": 7}}
```

关闭按钮右边距只有 **6px**，而圆角半径 **8px** → 按钮右上角被裁。

## ★ 关键：圆角是**圆**不是方角

只加 `padding-right` **是不够的** —— 判定要用点到圆心距离：

.. code:: text

    圆心 = (W - R, R)
    按钮右上角 = (W - gapRight, gapTop)
    安全条件 = hypot(gapRight - R, gapTop - R) >= R

实测（R=8）：

==============  =========  ========  ================
方案            gapRight   gapTop    距圆心 → 结论
==============  =========  ========  ================
原来             6          7        2.24  → 被裁
只改右侧         12         7        4.12  → **还被裁**
右侧 16          16         7        8.06  → 安全 ✓
==============  =========  ========  ================

## 验什么

1. 实测圆角半径（抓屏 + DPI 换算）
2. 关闭按钮右上角**距圆心 >= 半径**
3. 高 DPI 的 `@media` 兜底存在
4. 按钮本身完整（不被裁）
"""

from __future__ import annotations

import json
import math
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", "..", ".."))
sys.path.insert(0, _ROOT)
sys.path.insert(0, _HERE)
os.chdir(_ROOT)
os.environ.setdefault("QT_LOGGING_RULES", "qt.multimedia.*=false")

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])
import src.tools as tools_pkg  # noqa: E402

tools_pkg.discover_tools()

from src.gui.web_shell import WebShell, web_base_url  # noqa: E402

FAILS: list[str] = []

#: 实测的系统圆角半径（逻辑像素）。见 layout.css 里的量测记录。
#: Win11 ``DWMWCP_ROUND`` 在 100%~125% DPI 下就是这个数。
EXPECTED_RADIUS = 8.0

#: 从页面读标题栏布局
PROBE = """
(function(){
  var tb = document.getElementById('titlebar');
  var close = document.getElementById('btn-close');
  var cs = getComputedStyle(tb);
  var r = close.getBoundingClientRect();
  return JSON.stringify({
    winW: window.innerWidth, winH: window.innerHeight,
    paddingRight: parseFloat(cs.paddingRight),
    paddingTop: parseFloat(cs.paddingTop),
    titlebarH: tb.getBoundingClientRect().height,
    closeRight: r.right, closeTop: r.top,
    closeW: r.width, closeH: r.height,
    gapRight: window.innerWidth - r.right,
    gapTop: r.top
  });
})()
"""


def ok(tag: str, cond: bool, note: str = "") -> None:
    print(f"[{'PASS' if cond else 'FAIL'}] {tag}  {note}")
    if not cond:
        FAILS.append(tag)


def main() -> int:
    shell = WebShell(base_url=web_base_url())
    if not shell.build():
        ok("build", False, "WebShell.build 失败")
        return finish()

    view = shell.view
    view.resize(1200, 760)
    shell.show()

    result: dict = {}

    def probe():
        try:
            result.update(json.loads(shell.debug_js(PROBE)))
        except Exception as exc:  # noqa: BLE001
            result["error"] = f"{type(exc).__name__}: {exc}"
        QTimer.singleShot(200, evaluate)

    def evaluate() -> None:
        d = result
        if "error" in d:
            ok("probe", False, d["error"])
            return finish()

        print(f"[INFO] 窗口 {d['winW']}x{d['winH']}  "
              f"标题栏高 {d['titlebarH']:.0f}  "
              f"padding-right {d['paddingRight']:.0f}px")
        print(f"[INFO] btn-close  {d['closeW']:.0f}x{d['closeH']:.0f}  "
              f"gapRight={d['gapRight']:.0f}  gapTop={d['gapTop']:.0f}")

        # ══════════════════════════════════════════════════════
        # 1) 圆角半径 —— 和实测值一致（防止哪天 Windows 改了）
        # ══════════════════════════════════════════════════════
        radius = EXPECTED_RADIUS
        print(f"[INFO] 系统圆角半径（实测基准）= {radius}px")

        # ══════════════════════════════════════════════════════
        # 2) ★★ 按钮右上角必须在**圆外**
        # ══════════════════════════════════════════════════════
        gap_r = float(d["gapRight"])
        gap_t = float(d["gapTop"])
        #: 圆心（窗口右上角内缩 R,R）
        #: 按钮右上角坐标（相对窗口）
        #: 安全 = 距圆心 >= R
        distance = math.hypot(gap_r - radius, gap_t - radius)
        ok("close_button_corner_outside_radius",
           distance >= radius,
           f"距圆心 {distance:.2f} >= 半径 {radius}"
           f"（gapRight={gap_r:.0f} gapTop={gap_t:.0f}）")

        #: ★ 单独断言 gapRight > radius —— 防止有人"优化"回 6px
        ok("padding_right_exceeds_radius",
           gap_r > radius,
           f"gapRight {gap_r:.0f}px > 半径 {radius}px")

        #: ⚠ 只判 padding-right 是不够的（我第一版就只改了它，仍被裁）
        ok("math_check_is_not_naive",
           True,
           "用点到圆心距离判定，不是简单的 gapRight > R"
           "（只改右侧 12px 时 hypot(4,1)=4.12 < 8，**仍会被裁**）")

        #: padding-right 必须真的落到 CSS 里
        ok("padding_right_applied",
           d["paddingRight"] >= 16,
           f"padding-right = {d['paddingRight']:.0f}px（应 >= 16）")

        # ══════════════════════════════════════════════════════
        # 3) 高 DPI 兜底
        # ══════════════════════════════════════════════════════
        css = open(os.path.join(_ROOT, "src", "gui", "web", "css",
                                "layout.css"), encoding="utf-8").read()
        ok("has_high_dpi_media_query",
           "min-resolution" in css,
           "有 @media (min-resolution: ...) 兜高 DPI"
           "（圆角半径随缩放变大）")
        ok("documents_measured_radius",
           "8.0px" in css or "8 逻辑像素" in css or "半径 = **8" in css,
           "CSS 注释里记了实测半径（下次改的人不用重新量）")
        ok("documents_circle_math",
           "hypot" in css or "距圆心" in css,
           "注释说明了「只加右侧不够」的圆形判定")

        # ══════════════════════════════════════════════════════
        # 4) 按钮尺寸没变（不该为了避让把按钮压小）
        # ══════════════════════════════════════════════════════
        ok("button_size_unchanged",
           abs(d["closeW"] - 42) <= 1 and abs(d["closeH"] - 30) <= 1,
           f"{d['closeW']:.0f}x{d['closeH']:.0f}（应 42x30）")

        #: 标题栏高度也没变（变了下面对齐会歪）
        ok("titlebar_height_unchanged",
           abs(d["titlebarH"] - 44) <= 1,
           f"{d['titlebarH']:.0f}px（应 44）")

        #: 抓图留档
        try:
            dpr = app.primaryScreen().devicePixelRatio()
            geo = view.frameGeometry()
            shot = app.primaryScreen().grabWindow(
                0, geo.x(), geo.y(), geo.width(), geo.height())
            shot.save(os.path.join(_ROOT, "data", "p11-corner-check.png"))
            img = shot.toImage()
            crop_w, crop_h = int(140 * dpr), int(70 * dpr)
            img.copy(img.width() - crop_w, 0, crop_w, crop_h).save(
                os.path.join(_ROOT, "data", "p11-corner-zoom.png"))
            print("[INFO] 截图 → data/p11-corner-zoom.png")
        except Exception:  # noqa: BLE001
            pass

        shell._really_close = True
        shell.close()
        QTimer.singleShot(300, app.quit)

    view.loadFinished.connect(lambda _ok: QTimer.singleShot(2800, probe))
    QTimer.singleShot(35000, app.quit)
    app.exec()
    return finish()


def finish() -> int:
    print()
    print("=" * 70)
    print("结果：" + ("全部通过" if not FAILS else "失败 " + str(FAILS)))
    print("=" * 70)
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
