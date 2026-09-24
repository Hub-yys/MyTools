# -*- coding: utf-8 -*-
"""声骸强化页面：核心属性 ↔ 有效词条数 的联动检查（不需游戏）。

    QT_QPA_PLATFORM=windows ./.venv/Scripts/python.exe tests/check_echo_page_gui.py

盯三件事：

1. **下限 = 核心属性条数**、上限 = 有效词条集合总条数（用户要求）；
2. **改核心属性时「有效词条数」跟着回到核心条数** —— 减少核心也要跟着降；
3. **这个脚本不许写脏用户真正的配置**。

第 3 条是补的：2026-09-24 用户报"核心只有 2 条，有效词条却不是 2" ——
查下来是这个脚本在切换复选框/加减框时触发了 `_save_settings()`，把
`optional_stats` / `min_valid_count` 写进了项目里的 `data/tool_settings.json`，
而**「可选属性」卡片默认收起**、界面上根本看不出那几条还勾着。
所以现在：把设置文件指到临时目录，并在结尾断言真实文件一个字节都没变。
"""
from __future__ import annotations

import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SHOTS = ROOT / "tests" / "_shots"
REAL_SETTINGS = ROOT / "data" / "tool_settings.json"

CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append((name, ok, detail))


def main() -> int:
    from PySide6.QtWidgets import QApplication
    from qfluentwidgets import Theme, setTheme

    app = QApplication(sys.argv)
    setTheme(Theme.LIGHT)

    from src.core import tool_settings
    from src.core.registry import ToolRegistry
    from src.tools import discover_tools

    discover_tools()

    # ★ 隔离：把设置文件指到临时目录（**必须早于构造页面**）—— 别碰用户真正的配置
    tmp_dir = pathlib.Path(tempfile.mkdtemp(prefix="echo-page-check-"))
    tool_settings.settings_file = lambda: tmp_dir / "tool_settings.json"
    real_before = REAL_SETTINGS.read_bytes() if REAL_SETTINGS.is_file() else None

    from src.tools.game.echo_enhance import tool as echo_tool

    meta = next(m for m in ToolRegistry.all_metas() if m.key == "echo_enhance")
    page = echo_tool.EchoEnhanceWidget(meta)
    page.resize(900, 900)
    page.show()
    app.processEvents()
    app.processEvents()

    stepper = page.valid_stepper
    label = page.criterion_label
    for box in page._optional_boxes.values():
        box.setChecked(False)
    app.processEvents()

    # ① 默认（核心 = 双爆 2 条、可选空）→ 只能是 2 条
    check("默认范围 2~2", (stepper.minimum, stepper.maximum) == (2, 2),
          f"实际 {stepper.minimum}~{stepper.maximum}")
    check("默认值 = 核心条数 2", stepper.value() == 2, f"实际 {stepper.value()}")
    check("提示提到核心词条数", "不可小于核心词条数（2 条）" in label.text(), label.text()[:56])
    check("提示说明为什么只能设 2", "只能设 2 条" in label.text())
    check("提示是可见的", label.isVisible())

    # ② 降不下去：想设 1 也要停在核心条数上
    stepper.set_value(1)
    app.processEvents()
    check("减少不动（不可小于核心词条数）", stepper.value() == 2, f"实际 {stepper.value()}")
    check("减号已置灰", not stepper.minus.isEnabled())

    # ③ 核心属性加一条 → 下限跟着抬到 3，当前值也跟着升
    page._core_boxes["攻击百分比"].setChecked(True)
    app.processEvents()
    check("核心 +1 → 范围 3~3", (stepper.minimum, stepper.maximum) == (3, 3),
          f"实际 {stepper.minimum}~{stepper.maximum}")
    check("下限抬起后当前值跟着升", stepper.value() == 3, f"实际 {stepper.value()}")

    # ④ 可选属性抬上限 → 能把有效词条数调高到 4
    page._optional_boxes["共鸣效率"].setChecked(True)
    app.processEvents()
    check("可选 +1 → 范围 3~4", (stepper.minimum, stepper.maximum) == (3, 4),
          f"实际 {stepper.minimum}~{stepper.maximum}")
    stepper.set_value(4)
    app.processEvents()
    check("上限内可以调高", stepper.value() == 4, f"实际 {stepper.value()}")

    # ⑤ ★ 核心属性减一条 → 有效词条数**跟着降回核心条数**（用户 2026-09-24 报的问题）
    page._core_boxes["攻击百分比"].setChecked(False)
    app.processEvents()
    # 取消 1 条核心后只剩 1 个可选属性 → 集合 = 双爆 + 共鸣效率 = 3 条，上限是 3
    check("核心 -1 → 范围 2~3", (stepper.minimum, stepper.maximum) == (2, 3),
          f"实际 {stepper.minimum}~{stepper.maximum}")
    check("★ 减少核心后有效词条数跟着降", stepper.value() == 2, f"实际 {stepper.value()}")
    saved = echo_tool.EchoSettings.load()
    check("★ 盘上也跟着降（不是只改了界面）", saved.min_valid_count == 2,
          f"盘上 {saved.min_valid_count}")
    check("提示里的核心条数已回到 2", "不可小于核心词条数（2 条）" in label.text())

    # ⑥ 截一张"可调范围"的图（核心 2 + 可选 2 → 2~4）
    page._optional_boxes["攻击百分比"].setChecked(True)
    stepper.set_value(3)
    app.processEvents()
    check("截图场景范围 2~4", (stepper.minimum, stepper.maximum) == (2, 4),
          f"实际 {stepper.minimum}~{stepper.maximum}")
    shot = SHOTS / "echo_enhance_valid_link.png"
    SHOTS.mkdir(parents=True, exist_ok=True)
    page.grab().save(str(shot))
    check("截图已保存", shot.is_file(), str(shot.relative_to(ROOT)))

    # ⑦ ★ 真实配置一个字节都没变
    real_after = REAL_SETTINGS.read_bytes() if REAL_SETTINGS.is_file() else None
    check("★ 没写脏真实配置 data/tool_settings.json", real_before == real_after,
          "" if real_before == real_after else "真实文件被改过！")

    # ------------------------------------------------------------- 2026-09-24 下午
    # ⑧ ★ 误弹「任务结束」回归：引擎自启完成（booting→ready、没跑过任务）不弹
    # ⑨ 真跑过任务 → ready 时弹结果报告 + 卡片更新
    # ⑩ 核心属性勾满 → 其余自选框置灰 + 文案说清双爆占 2 条
    from src.tools.game.echo_enhance.stats import CRIT, CRIT_DMG, format_result_report
    from src.tools.game.auto_combat.okww_boot import OkwwHost
    import qfluentwidgets

    shown: list[str] = []
    for name in ("success", "warning", "error", "info"):
        def _recorder(*a, _n=name, **k):
            shown.append(f"{_n}: {a[0] if a else k.get('title', '')} / "
                         f"{a[1] if len(a) > 1 else k.get('content', '')}")
        setattr(qfluentwidgets.InfoBar, name, staticmethod(_recorder))

    # 停掉真实轮询定时器 —— 下面手动驱动 _poll()，不能让 300ms 定时器
    # 半路杀进来消费掉模拟的状态序列（否则断言时好时坏）
    page._timer.stop()

    original_state = OkwwHost.state

    # ⑧ booting→ready，期间从没见过本页任务 → 不许弹「任务结束」
    seq = ["booting", "booting", "ready", "ready"]
    OkwwHost.state = property(lambda self: seq.pop(0) if seq else "ready")
    try:
        page._task_seen = False
        shown.clear()
        for _ in range(4):
            page._poll()
            app.processEvents()
        check("★ booting→ready（没跑过任务）不弹「任务结束」",
              not any("任务结束" in s or "声骸强化结果" in s for s in shown), str(shown))
    finally:
        OkwwHost.state = original_state

    # ⑨ 真跑过任务（_task_seen + 有统计快照）→ ready 弹结果、卡片定格
    seq = ["running", "ready", "ready"]
    OkwwHost.state = property(lambda self: seq.pop(0) if seq else "ready")
    try:
        page._task_seen = True
        page._last_stats = {"checked": 12, "kept": 5, "dropped": 7,
                            "perfect": 2, "tally": {"crit": 4, "valid": 3}}
        shown.clear()
        page._poll()          # 第 1 次：进入 running（此刻还不算结束）
        page._poll()          # 第 2 次：running → ready，触发「任务结束」分支
        app.processEvents()
        check("★ 真跑过任务才弹「声骸强化结果」",
              any("声骸强化结果" in s for s in shown), str(shown))
        check("弹窗首行含统计", any("判定 12 个" in s and "符合条件 5" in s for s in shown),
              str(shown[:1]))
        check("报告卡含满属性统计", "满属性 2" in page.report_label.text(),
              page.report_label.text()[:60])
        check("报告卡含弃置原因分布", "双爆不达标 4" in page.report_label.text())
        check("报告已消费（_task_seen 复位）", page._task_seen is False)
    finally:
        OkwwHost.state = original_state

    # ⑩ 核心属性勾满 5 条（双爆 2 + 自选 3）
    #   → 已勾的**必须仍可取消**（不能整片置灰卡死）；再勾第 6 条 → 红字报错并回滚
    for name in ("攻击百分比", "生命百分比", "防御百分比"):
        page._core_boxes[name].setChecked(True)
    app.processEvents()
    checked_optional = [n for n, b in page._core_boxes.items()
                        if n not in (CRIT, CRIT_DMG) and b.isChecked()]
    enabled_checked = [n for n in checked_optional if page._core_boxes[n].isEnabled()]
    check("★ 勾满 5 条后已勾项仍可取消（不禁用）",
          len(page._checked_core()) == 5 and len(enabled_checked) == len(checked_optional),
          f"已勾 {checked_optional}，其中可点 {enabled_checked}")
    # 满了还勾 → 撤销**刚点的那个** + 红字「核心属性最多只能勾选5条」
    remaining = [n for n, b in page._core_boxes.items()
                 if n not in (CRIT, CRIT_DMG) and not b.isChecked()]
    shown.clear()
    if remaining:
        page._core_boxes[remaining[0]].setChecked(True)
        app.processEvents()
    check("★ 超限红字文案含「核心属性最多只能勾选5条」",
          any("核心属性最多只能勾选5条" in s for s in shown), str(shown))
    check("★ 超限时是 error（红字）不是 warning",
          any(s.startswith("error:") for s in shown), str(shown))
    check("超限勾选被撤销", len(page._checked_core()) == 5,
          f"实际 {len(page._checked_core())}")
    # 满员时**未勾的**必须置灰（一点就看得懂"到顶了"）；
    # 曾经的"全部可点、点了才弹红字"被用户否掉：『报错提示出现了，但为什么我还是
    # 可以勾选这么多』（2026-09-24）
    unchecked_now = [n for n, b in page._core_boxes.items()
                     if n not in (CRIT, CRIT_DMG) and not b.isChecked()]
    grey = [n for n in unchecked_now if not page._core_boxes[n].isEnabled()]
    check("★ 满员后未勾的自选框置灰", len(grey) == len(unchecked_now),
          f"未勾 {unchecked_now}，其中置灰 {grey}")
    # 取消一条 → 能再勾回来（不再被置灰挡住）
    page._core_boxes["攻击百分比"].setChecked(False)
    app.processEvents()
    check("取消一条后能再勾",
          len(page._checked_core()) == 4, f"实际 {len(page._checked_core())}")
    page._core_boxes["攻击百分比"].setChecked(True)
    app.processEvents()
    check("取消后重新勾选成功", len(page._checked_core()) == 5,
          f"实际 {len(page._checked_core())}")

    # ⑪ 摘要行要能看出「这不是默认」—— 2026-09-24 用户把上次的勾选当成"默认坏了"
    check("偏离默认时摘要标「非默认」", "非默认" in page.core_count_label.text(),
          page.core_count_label.text())
    check("标题栏有「恢复默认」按钮", page.reset_button.text() == "恢复默认")

    # ⑫ 点「恢复默认」→ 回到双爆 2 条、可选清空，并且写盘
    from qfluentwidgets import MessageBox
    _original_exec = MessageBox.exec
    MessageBox.exec = lambda self: 1          # 直接当"确认"（不弹窗）
    try:
        page.reset_button.click()
        app.processEvents()
    finally:
        MessageBox.exec = _original_exec
    check("★ 恢复默认：核心只剩双爆", tuple(page._checked_core()) == ("暴击", "暴击伤害"),
          str(page._checked_core()))
    check("★ 恢复默认：可选属性清空", page._checked_optional() == [],
          str(page._checked_optional()))
    check("★ 恢复默认：有效词条回到 2", stepper.value() == 2, f"实际 {stepper.value()}")
    check("恢复后摘要不再标「非默认」", "非默认" not in page.core_count_label.text(),
          page.core_count_label.text())
    _saved_after_reset = echo_tool.EchoSettings.load()
    check("★ 恢复默认已写盘",
          tuple(_saved_after_reset.core_stats) == ("暴击", "暴击伤害")
          and _saved_after_reset.min_valid_count == 2,
          f"盘上 {_saved_after_reset.core_stats} / {_saved_after_reset.min_valid_count}")

    # ⑬ ★ 盘上是脏数据（超过 5 条）时，界面也不能显示成「8 / 5 条」
    #    （2026-09-24 用户截图就是这个：加载路径以前不做上限校验）
    from src.tools.game.echo_enhance.settings import DEFAULT_CORE
    from src.tools.game.echo_enhance.stats import MAX_CORE_STATS

    dirty = echo_tool.EchoSettings(
        core_stats=("暴击", "暴击伤害", "攻击", "攻击百分比", "生命",
                    "生命百分比", "防御", "防御百分比"),
        optional_stats=(),
        min_valid_count=5,
    )
    page._apply_settings(dirty)
    app.processEvents()
    check("★ 脏配置加载后核心截到上限 5 条",
          len(page._checked_core()) == MAX_CORE_STATS, str(page._checked_core()))
    check("★ 截断后强制项还在", set(DEFAULT_CORE) <= set(page._checked_core()),
          str(page._checked_core()))
    check("摘要不再出现「8 / 5」", "8 / 5" not in page.core_count_label.text(),
          page.core_count_label.text())

    # ⑭ ★ 每次进入都是出厂默认（用户 2026-09-24 要求：不要遗留上次的勾选）
    echo_tool.EchoSettings(
        core_stats=("暴击", "暴击伤害", "生命百分比"),
        optional_stats=("共鸣效率",),
        min_valid_count=4,
    ).save()
    page2 = echo_tool.EchoEnhanceWidget(meta)
    page2.show()
    for _ in range(3):
        app.processEvents()
    check("★ 再次进入是出厂默认（不回填上次的核心）",
          tuple(page2._checked_core()) == ("暴击", "暴击伤害"), str(page2._checked_core()))
    check("★ 可选项也不回填", page2._checked_optional() == [], str(page2._checked_optional()))
    check("★ 有效词条回默认 2",
          page2.valid_stepper.value() == 2, f"实际 {page2.valid_stepper.value()}")
    check("默认态摘要不带「非默认」", "非默认" not in page2.core_count_label.text(),
          page2.core_count_label.text())
    page2.close()

    # 恢复 InfoBar（后面的检查如果还要弹，不致被静默吞掉）
    from qfluentwidgets import InfoBar as _RealInfoBar
    for name in ("success", "warning", "error", "info"):
        setattr(qfluentwidgets.InfoBar, name, getattr(_RealInfoBar, name))

    width = max(len(name) for name, _, _ in CHECKS)
    for name, ok, detail in CHECKS:
        print("%-*s %s%s" % (width, name, "PASS" if ok else "FAIL",
                             ("  " + detail) if detail else ""))
    failed = [c for c in CHECKS if not c[1]]
    print("\n%d 项检查，%d 项失败" % (len(CHECKS), len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
