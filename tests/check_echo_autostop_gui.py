# -*- coding: utf-8 -*-
r"""端到端冒烟：真起主窗口 + 声骸工具页，确认这次改动没把界面搞坏。

    .\.venv\Scripts\python.exe tests\check_echo_autostop_gui.py

盯三件事：
  ① 工具页能建出来（新增的卡片区/开关没把构造搞崩）
  ② 设置区里有那个「启用/不启用」开关，且**存盘往返**正确
  ③ 结果报告的卡片区在**真实工具页**里能正常显示/隐藏
"""
from __future__ import annotations

import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

SHOTS = ROOT / "tests" / "_shots"
CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append((name, bool(ok), detail))


def main() -> int:
    from PySide6.QtWidgets import QApplication, QLabel

    app = QApplication(sys.argv)

    from src.core import paths, tool_settings
    from src.core.registry import ToolRegistry
    from src.tools import discover_tools

    discover_tools()

    #: 隔离：别写用户真正的 tool_settings.json
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="echo-autostop-"))
    real = tool_settings.settings_file
    tool_settings.settings_file = lambda: tmp / "tool_settings.json"
    try:
        from src.tools.game.echo_enhance import echo_tool_import_check  # noqa: F401
    except ImportError:
        pass

    try:
        from src.tools.game.echo_enhance import tool as echo_tool
        from src.tools.game.echo_enhance.settings import EchoSettings

        meta = next(m for m in ToolRegistry.all_metas() if m.key == "echo_enhance")
        page = echo_tool.EchoEnhanceWidget(meta)
        page.resize(900, 1200)
        page.show()
        for _ in range(3):
            app.processEvents()
        check("工具页建得出来", True)

        #: ① 新开关在界面上，且默认开
        sw = getattr(page.editor, "autostop_switch", None)
        check("设置区有「自动停止」开关", sw is not None)
        if sw is not None:
            check("开关默认启用", sw.isChecked(), f"checked={sw.isChecked()}")
            check("开关是启用/不启用两种文案",
                  sw.onText == "启用" and sw.offText == "不启用",
                  f"{sw.onText!r}/{sw.offText!r}")

        #: ② 改开关 → settings() 跟着变
        if sw is not None:
            sw.setChecked(False)
            app.processEvents()
            check("关掉开关后 settings() 反映出来",
                  page.editor.settings().enable_auto_stop is False)
            sw.setChecked(True)
            app.processEvents()

        #: ②b ★「继续」按钮必须存在 —— 自动停止是 pause，没这个就回不去
        resume = getattr(page, "resume_button", None)
        check("有「继续」按钮（自动暂停后能接着跑）", resume is not None)
        if resume is not None:
            check("没暂停时「继续」是灰的", not resume.isEnabled(),
                  f"enabled={resume.isEnabled()}")
            check("「继续」文案对", resume.text() == "继续", repr(resume.text()))

        #: ③ 卡片区存在，且初始隐藏
        area = getattr(page, "echo_area", None)
        check("报告里有声骸卡片区", area is not None)
        if area is not None:
            check("初始没有内容时卡片区隐藏", area.isHidden())

        #: ④ 塞两个符合条件的声骸 → 卡片区显示，且画出了卡片
        page._update_echo_cards([
            {"index": 1, "stats": ["暴击 10.5", "攻击 30"],
             "image": "", "perfect": True},
            {"index": 2, "stats": ["暴击 9.9"], "image": "", "perfect": False},
        ])
        for _ in range(2):
            app.processEvents()
        if area is not None:
            check("有内容时卡片区显示", not area.isHidden())
        cards = page.findChildren(echo_tool.QualifyingEchoCard)
        check("画出了 2 张声骸卡", len(cards) == 2, f"{len(cards)} 张")
        texts = " ".join(w.text() for c in cards
                         for w in c.findChildren(QLabel) if w.text())
        check("卡片里有词条", "暴击 10.5" in texts and "暴击 9.9" in texts,
              texts[:70])
        check("满属性标记只出现在第 1 张", texts.count("满属性") == 1,
              f"{texts.count('满属性')} 次")

        #: ⑤ 设置往返（含新开关）
        s = EchoSettings(enable_auto_stop=False)
        s.save()
        check("存盘后读回来开关一致",
              EchoSettings.load().enable_auto_stop is False)

        #: 截图留档
        SHOTS.mkdir(parents=True, exist_ok=True)
        from PySide6.QtGui import QColor, QPixmap

        pm = QPixmap(page.size())
        pm.fill(QColor("#fdfdfe"))
        page.render(pm)
        pm.save(str(SHOTS / "echo_autostop_page.png"))

        page.close_without_prompt() if hasattr(page, "close_without_prompt") else None
    finally:
        tool_settings.settings_file = real

    print()
    bad = [c for c in CHECKS if not c[1]]
    for name, ok, det in CHECKS:
        print("  [%s] %s%s" % ("PASS" if ok else "FAIL", name,
                               ("   " + det) if det else ""))
    print()
    print("共 %d 项，%d 项失败" % (len(CHECKS), len(bad)))
    print("★", "全部通过" if not bad else "⚠ 见上面的 FAIL")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
