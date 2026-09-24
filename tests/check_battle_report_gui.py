"""战斗报告卡片的外观检查（不需要游戏）：喂假数据 → 断言 + 截图。

本机没装鸣潮、跑不了真实战斗，所以用假 report 把卡片真画出来 ——
版式、头像、角标这些只能靠看，纯逻辑单测覆盖不到。

跑：QT_QPA_PLATFORM=windows .venv/Scripts/python.exe tests/check_battle_report_gui.py
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402
from qfluentwidgets import Theme, setTheme  # noqa: E402

from src.tools.game.auto_combat.report import (  # noqa: E402
    BattleReport,
    EchoTarget,
    PickupTally,
    TeamMember,
)
from src.tools.game.auto_combat.tool import BattleReportCard  # noqa: E402

failures: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        failures.append(msg)


def labels_of(widget) -> list[str]:
    return [w.text() for w in widget.findChildren(QLabel)]


def main() -> int:
    app = QApplication(sys.argv)
    setTheme(Theme.LIGHT)          # 截图统一浅色，避免跟着终端主题跑偏

    card = BattleReportCard()
    card.resize(680, 340)

    # -------------------------------------------------- ① 还没跑过
    card.update_report(None)
    check(card.stats["战斗次数"].text() == "—", "未开始时数字显示占位「—」")
    check(card.stats["锁定声骸"].text() == "—", "未开始时「锁定声骸」也显示占位")
    check(not card.hint.isHidden(), "未开始时显示提示文案")
    check(card.pickup_hint.isHidden(), "未开始时隐藏拾取分类诊断行")

    # -------------------------------------------------- ② 有数据（声骸已识别）
    team = (
        TeamMember("今汐", "avatars/今汐.png", True),
        TeamMember("椿", "avatars/椿.png", True),
        TeamMember("守岸人", "avatars/守岸人.png", True),
    )
    card.update_report(
        BattleReport(running=True, battles=3, echo_count=5, seconds=252.0, team=team,
                     echo=EchoTarget("异构武装", "echoes/异构武装.png", True),
                     pickups=PickupTally(locked=2, dropped=1, none=2))
    )
    app.processEvents()
    check(card.stats["战斗次数"].text() == "3", "战斗次数 = 3")
    check(card.stats["声骸数量"].text() == "5", "声骸数量 = 5")
    check(card.stats["锁定声骸"].text() == "2", f"锁定声骸 = {card.stats['锁定声骸'].text()}")
    check(card.stats["时长"].text() == "04:12", f"时长 = {card.stats['时长'].text()}")
    check(card.hint.isHidden(), "有数据后提示文案收起")

    hint = card.pickup_hint.text()
    check(not card.pickup_hint.isHidden(), "有拾取数据后诊断行可见")
    for want in ("锁定 2", "弃置 1", "都没 2"):
        check(want in hint, f"诊断行含「{want}」（实际：{hint}）")

    names = labels_of(card)
    for want in ("今汐", "椿", "守岸人", "异构武装"):
        check(want in names, f"卡片上有「{want}」")
    check("未识别" not in names, "有名字时不该出现「未识别」角标")

    shots = ROOT / "tests" / "_shots"
    shots.mkdir(parents=True, exist_ok=True)
    card.show()
    app.processEvents()
    card.grab().save(str(shots / "battle_report_ok.png"))
    print("  -> 截图 tests/_shots/battle_report_ok.png")

    # -------------------------------------------------- ③ 声骸未识别分支
    card.update_report(
        BattleReport(battles=1, echo_count=1, seconds=8.0,
                     echo=EchoTarget("Fenrico", "", False),
                     pickups=PickupTally(locked=0, dropped=0, none=1))
    )
    app.processEvents()
    names = labels_of(card)
    check("Fenrico" in names, "识别不出时显示配置档位名")
    check("未识别" in names, "识别不出时显示「未识别」角标")
    card.grab().save(str(shots / "battle_report_unidentified.png"))
    print("  -> 截图 tests/_shots/battle_report_unidentified.png")

    print()
    if failures:
        print(f"=== 结果：{len(failures)} 项失败 ===")
        for item in failures:
            print("   -", item)
        return 1
    print("=== 结果：全部通过 ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
