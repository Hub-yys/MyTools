"""排查界面上「文字显示不全」的地方。

## 为什么写它（2026-09-27 用户要求）

用户在「配置详情」弹框里发现 4C/3C/1C 那几行**被卡片右边直接截断**
（「霁息兽尊　属性：攻…」）。那是 `BodyLabel` 没开 ``setWordWrap``。

用户接着说：「**其他地方也看看有没有类似的问题**」——
靠人一个个界面点着看太容易漏，所以把判据写成代码：

    **有文字 + 没开自动换行 + 文本像素宽度 > 控件宽度** ⇒ 一定会被截断

## 判据的两个细节

* 必须 ``show()`` + 跑几轮事件循环再量 —— 没排版时 ``width()`` 是默认值，
  量出来全是"够宽"，这条检查就成了空转；
* ``ElidedLabel``（我们自己的那种"超宽显示省略号 + tooltip"）**不算问题** ——
  它的设计就是截断加悬浮提示。

## 界面的两个来源

* **常驻界面**：`MainWindow` 和它的子界面；
* **弹框**：`LoadoutDetailDialog` / `EchoProfileDialog` —— 不常驻，得单独构造。
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append((name, ok, detail))


def overflowing_labels(root, *, skip_types=()) -> list[str]:
    """在 ``root`` 的子孙里找"会被截断"的文本控件。

    ⚠ 只统计 ``isVisibleTo(root)`` 的控件 —— 没被排版过的控件
    ``width()`` 是默认值（实测一律 100px），拿它比会满屏假阳性
    （第一版就误报了一堆未激活子页面里的 `SubtitleLabel`）。
    所以调用方要**先把页面切出来**再量（见 :func:`main`）。
    """
    from PySide6.QtWidgets import QLabel

    bad: list[str] = []
    for lb in root.findChildren(QLabel):
        if isinstance(lb, skip_types) or not lb.isVisibleTo(root):
            continue
        text = lb.text()
        if not text or len(text) < 8:          # 短标签本来就不会溢出
            continue
        if lb.wordWrap():                       # 开了换行 → 会折行，不算问题
            continue
        if lb.width() <= 0:
            continue
        need = lb.fontMetrics().horizontalAdvance(text)
        # 留 2px 容差：Qt 的 advance 和实际排版会差一点点
        if need > lb.width() + 2:
            bad.append(f"{type(lb).__name__}({lb.width()}px < 需要{need}px): {text[:46]}")
    return bad


def pump(app, rounds: int = 12) -> None:
    import time
    for _ in range(rounds):
        app.processEvents()
    time.sleep(0.35)
    app.processEvents()


def main() -> int:
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)

    from src.tools import discover_tools
    discover_tools()

    from src.core.loadout import LoadoutStore
    from src.gui.compat import ElidedLabel
    from src.gui.echo_profile_ui import EchoProfileDialog
    from src.gui.loadout_dialog import LoadoutDetailDialog
    from src.gui.main_window import MainWindow

    win = MainWindow()
    win.resize(1100, 800)
    win.show()
    pump(app)

    # ---- ① 常驻界面：**每个页面都切出来量一遍** ----
    #   只量当前页是不够的（其余页面没排版，宽度全是默认值）；而"不切页就量"
    #   又会满屏假阳性。所以两件事都得做。
    #
    # ⚠ 页面清单从 `stackedWidget` 拿，别按属性名猜：`FluentWindow` 的子界面
    #   命名并不统一（`wuwa_library` 就不是 `*interface` 结尾），
    #   而且工具页是动态加的 —— 第一版按 `endswith("interface")` 过滤，
    #   直接把资源库页和所有工具页漏掉了，还照样报"0 失败"。
    from PySide6.QtWidgets import QLabel

    pages = []
    sw = getattr(win, "stackedWidget", None)
    if sw is not None:
        for i in range(sw.count()):
            page = sw.widget(i)
            if page is not None:
                pages.append((type(page).__name__, page))
    check("确实找到了要排查的子页面", len(pages) >= 3,
          f"{len(pages)} 个：{[n for n, _ in pages]}")

    all_bad: list[str] = []
    for name, page in pages:
        try:
            win.switchTo(page)
        except Exception:  # noqa: BLE001 - 切不过去就跳过这一页
            continue
        pump(app)
        bad = overflowing_labels(win, skip_types=(ElidedLabel,))
        all_bad += [f"[{name}] {b}" for b in bad]
    # 量完切回主页，别让窗口停在一个奇怪的页面
    try:
        win.switchTo(win.home_interface)
    except Exception:  # noqa: BLE001
        pass
    check(f"子页面（{len(pages)} 个）：没有被截断的长文本", not all_bad,
          "；".join(all_bad[:3]) if all_bad else
          f"扫过 {len(win.findChildren(QLabel))} 个文本控件")

    # ---- ② 两个配置详情弹框（不常驻，单独造）----
    loadouts = LoadoutStore().all()
    if loadouts:
        # 挑「内容最长」的那条 —— 短的测不出问题
        longest = max(loadouts, key=lambda lo: sum(len(p.echo) + len(p.stats)
                                                   for c in (4, 3, 1)
                                                   for p in lo.picks_of(c)))
        dlg = LoadoutDetailDialog(win, longest)
        dlg.show()
        pump(app)
        bad = overflowing_labels(dlg.widget, skip_types=(ElidedLabel,))
        check(f"配置详情弹框（最长那条：{longest.character}）没有被截断的长文本",
              not bad, "；".join(bad[:3]) if bad else "最长那条也放得下")
        # 卡片要装得下内容
        need = dlg.viewLayout.sizeHint().height()
        got = dlg.widget.height()
        check("配置详情卡片高度装得下内容", need <= got, f"需要 {need}px / 卡片 {got}px")
        dlg.close()

    from src.core.echo_profile import EchoProfileStore
    profiles = [p for p in EchoProfileStore().all() if p.name] if hasattr(
        EchoProfileStore(), "all") else []
    if profiles:
        dlg = EchoProfileDialog(win, profile=profiles[0], read_only=True)
        dlg.show()
        pump(app)
        bad = overflowing_labels(dlg.widget, skip_types=(ElidedLabel,))
        check("强化配置详情弹框没有被截断的长文本", not bad, "；".join(bad[:3]))
        dlg.close()

    win.close_without_prompt()

    width = max(len(n) for n, _, _ in CHECKS)
    failed = 0
    for name, ok, detail in CHECKS:
        print(f"{name:<{width}} {'PASS' if ok else 'FAIL'}  {detail[:120]}")
        if not ok:
            failed += 1
    print()
    print(f"{len(CHECKS)} 项检查，{failed} 项失败")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
