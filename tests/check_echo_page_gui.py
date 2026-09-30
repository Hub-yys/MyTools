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

    # ⑩b 核心 ↔ 可选联动：进了核心的属性，在可选里**置灰且不可勾选**
    #    （同一条属性两边都勾是自相矛盾的：核心是"必须有"，可选是"另外算有效词条"）
    opt = page._optional_boxes.get("攻击百分比")
    check("★ 核心勾了的属性，可选里置灰",
          opt is not None and not opt.isEnabled(),
          f"enabled={opt.isEnabled() if opt else None}")
    check("★ 置灰的同时清掉可选的勾选（不能留个灰着的已勾项）",
          opt is not None and not opt.isChecked())
    check("★ 置灰项有提示说明原因",
          opt is not None and "核心属性" in opt.toolTip(),
          opt.toolTip() if opt else "")

    # 核心取消 → 可选恢复可点，但**不自动勾回来**（不替用户做决定）
    page._core_boxes["攻击百分比"].setChecked(False)
    app.processEvents()
    check("★ 核心取消后可选恢复可点", opt.isEnabled())
    check("★ 恢复可点但不自动勾回来", not opt.isChecked())

    # 没进核心的可选项不受影响
    other = page._optional_boxes.get("共鸣效率")
    check("未进核心的可选项照常可勾", other is not None and other.isEnabled())

    # 可选里自己勾的，不该反过来把核心置灰（只做用户要求的那一个方向）
    other.setChecked(True)
    app.processEvents()
    check("可选勾选不影响核心选框",
          page._core_boxes["共鸣效率"].isEnabled())
    other.setChecked(False)
    app.processEvents()

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

    # ⑬ ★ 和「角色声骸强化」那些配置**互不影响**（2026-09-26 用户明确）
    #    曾经加过"顶部下拉 + 改动写回当前那套"，属于错误设计，已拆掉。
    check("★ 工具页没有「用哪条配置」的下拉",
          not hasattr(page2, "profile_box"),
          "有 profile_box 说明又把两类配置绑一起了")
    check("工具页不持有配置仓库（不该读也不该写）",
          not hasattr(page2, "_profiles"))

    # 反证：页面上改点东西，**不该**动到配置文件里那条配置
    # ⚠ 2026-09-26 晚起不再有「默认」那条了（名字就是角色名），
    #   所以这里自己建一条**以真实角色为名**的配置来做对照。
    from src.core import tool_settings as _ts
    from src.core.echo_profile import EchoProfile as _EP
    from src.core.echo_profile import EchoProfileStore as _Store
    from src.core.game_data import CHARACTERS as _CHARS

    probe_char = _CHARS[0].name
    store = _Store()
    store.load()
    if store.get(probe_char) is None:
        store.add(_EP(name=probe_char, settings={"core_stats": ["暴击"]}))
    profile = store.get(probe_char)
    check("检查前置：对照配置确实在（否则下面是空转）",
          profile is not None, str(store.names()))
    before = dict(profile.settings) if profile else None

    page2._core_boxes["攻击百分比"].setChecked(True)
    app.processEvents()

    again = _Store()
    again.load()
    after = dict(again.get(probe_char).settings) if again.get(probe_char) else None
    check("★ 改工具页设置**不会**影响「角色声骸强化」配置", before == after,
          f"被改了：{before} → {after}")
    check("但工具页自己的设置确实存盘了（两边的存盘互相独立）",
          "攻击百分比" in (_ts.load("echo_enhance").get("core_stats") or []),
          str(_ts.load("echo_enhance").get("core_stats")))

    # 反向反证：改配置**也不该**动到工具页的设置
    profile = again.get(probe_char)
    if profile is not None:
        profile.settings = {"core_stats": ["生命"], "min_valid_count": 5}
        again.update(profile)
    tools_after = _ts.load("echo_enhance").get("core_stats") or []
    check("★ 改配置**也不会**动到工具页的设置",
          "生命" not in tools_after, str(tools_after))

    # ⑭ ★ 回填顺序：先收敛范围、再填「有效词条数」
    #    反过来的话 set_value 会被**旧范围**钳住 —— 编辑器刚构造时可选属性还空着，
    #    范围是 (2,2)，于是别处存着 3 的配置载进来会变成 2（保存下去还会把它改掉）。
    #    2026-09-26 实测：配置页新建的弹框显示 2、而源配置是 3。
    from src.tools.game.echo_enhance.settings import EchoSettings as _ES
    page2._apply_settings(_ES(
        core_stats=("暴击", "暴击伤害"),
        optional_stats=("攻击百分比", "共鸣效率"),
        min_valid_count=4))
    app.processEvents()
    check("★ 回填后「有效词条数」没被旧范围钳住",
          page2.valid_stepper.value() == 4,
          f"实际 {page2.valid_stepper.value()}（范围 {page2.valid_stepper.minimum}"
          f"~{page2.valid_stepper.maximum}）")
    # 再验一次会被"真的钳住"的情形：要 5 条但集合只有 4 条 → 应当钳到 4
    page2._apply_settings(_ES(
        core_stats=("暴击", "暴击伤害"),
        optional_stats=("攻击百分比", "共鸣效率"),
        min_valid_count=5))
    app.processEvents()
    check("超出合法范围的仍然要被钳住（不是不钳了）",
          page2.valid_stepper.value() == 4,
          f"实际 {page2.valid_stepper.value()}")

    page2.close()

    # 恢复 InfoBar（后面的检查如果还要弹，不致被静默吞掉）
    from qfluentwidgets import InfoBar as _RealInfoBar
    for name in ("success", "warning", "error", "info"):
        setattr(qfluentwidgets.InfoBar, name, getattr(_RealInfoBar, name))

    # ---- 配置页的小标题必须**来自 TYPE_* 常量**，不许再各处写一遍字面量 ----
    # 2026-09-26 用户把「角色声骸搭配」改名成「角色声骸筛选配置」，一共散在 3 处
    # （小节标题 / 计数文案 / 新增时的类型下拉）。改成一处常量后，
    # 这条守住"没有漏网的硬编码字面量"——以后改显示名只动常量、不会漏掉某一处。
    from qfluentwidgets import StrongBodyLabel

    from src.gui.config_interface import ConfigInterface
    from src.gui.echo_profile_ui import (
        CONFIG_TYPES,
        TYPE_ECHO_PROFILE,
        TYPE_LOADOUT,
        ConfigTypeDialog,
        EchoProfileDialog,
        EchoProfileRow,
    )

    cfg = ConfigInterface()
    cfg.reload()
    app.processEvents()
    titles = {w.text() for w in cfg.findChildren(StrongBodyLabel)}
    for _label in CONFIG_TYPES:
        check(f"配置页小标题用的是常量「{_label}」（不是硬编码字面量）",
              _label in titles, f"实际小标题 {sorted(titles)}")
    # ⚠ 只查子串是**弱断言**：`TYPE_LOADOUT` 恰好是另一个字面量的前缀
    #   （"角色声骸筛选" ⊂ "角色声骸筛选配置"），硬编码那处会**侥幸通过**。
    #   要真的证明"文案来自常量"，只能**改常量看界面跟不跟**。
    import src.gui.config_interface as _ci
    import src.gui.echo_profile_ui as _epu

    _orig_type = _ci.TYPE_LOADOUT
    _probe_type = "XX探针类型"
    try:
        _ci.TYPE_LOADOUT = _probe_type          # 模块级 from-import 的绑定
        _epu.TYPE_LOADOUT = _probe_type
        _probe_page = _ci.ConfigInterface()
        _probe_titles = {w.text() for w in _probe_page.findChildren(StrongBodyLabel)}
        check("★ 改常量后小标题跟着变（证明不是硬编码字面量）",
              _probe_type in _probe_titles, f"小标题 {sorted(_probe_titles)}")
        check("★ 改常量后计数文案也跟着变",
              f"条{_probe_type}" in _probe_page.subtitle.text(),
              _probe_page.subtitle.text())
        _probe_page.close()
    finally:
        _ci.TYPE_LOADOUT = _orig_type
        _epu.TYPE_LOADOUT = _orig_type
    chooser = ConfigTypeDialog(cfg)
    check("新增时的类型候选 = CONFIG_TYPES（顺序也一致）",
          [chooser.typeBox.itemText(i) for i in range(chooser.typeBox.count())]
          == list(CONFIG_TYPES),
          str([chooser.typeBox.itemText(i) for i in range(chooser.typeBox.count())]))
    chooser.close()

    # ---- ★ 「默认」那条：不再种子，而且启动时把遗留的**清掉** ----
    # 用户 2026-09-26 明确："去掉种子并删掉已有的「默认」"。
    from src.core.echo_profile import EchoProfileStore as _PS

    _legacy_path = pathlib.Path(tool_settings.settings_file()).parent / "echo_profiles.json"
    _seed = _PS(path=_legacy_path)
    _seed.load()
    _seed.add(_EP(name="默认", settings={}))
    check("前置：已经塞了一条遗留的「默认」（否则下面是空转）",
          _seed.get("默认") is not None, str(_seed.names()))

    _tmp_cfg = ConfigInterface()          # 构造时会跑 _migrate_profiles
    _after = _PS(path=_legacy_path)
    _after.load()
    check("★ 构造配置页会把遗留的「默认」清掉",
          _after.get("默认") is None, str(_after.names()))
    check("★ 清「默认」不会顺手种一条新的（不再有种子逻辑）",
          _after.get(probe_char) is not None and len(_after) >= 1,
          str(_after.names()))
    _tmp_cfg.close()
    # 把对照配置留给后面（后面的检查还要用它比"改配置不影响工具页"）

    # ---- ★ 名字过长不破版：行高不随名字长度变、头像恒在、超长省略号 ----
    # 用户截图：名字长了之后头像没了 / 三行字把行撑高。
    from PySide6.QtWidgets import QWidget as _QW

    from src.core.loadout import Loadout as _L
    from src.gui.config_interface import LoadoutRow as _LR

    def _row_probe(row):
        row.set_summary_width(1000)          # 给足宽度，摘要不参与对比
        avatar = [w for w in row.findChildren(_QW)
                  if w.width() == 48 and w.height() == 48]
        return row.height(), bool(avatar), row.nameLabel.text()

    _long_name = "非" * 12                    # 等于 MAX_NAME_LENGTH
    _longest_char = max((c.name for c in _CHARS), key=len)
    for _cls, _maker, _label, _type_name in (
        (EchoProfileRow, lambda n: EchoProfileRow(_EP(name=n, settings={})),
         "角色声骸强化行", TYPE_ECHO_PROFILE),
        (_LR, lambda n: _LR(_L(character=n)), "角色声骸筛选行", TYPE_LOADOUT),
    ):
        # ⚠ 期望值**在这里自己算**（角色名 + "-" + 类型名去掉开头的「角色」），
        #   **不要调 config_display_name** —— 用它算期望就成了自己跟自己比：
        #   哪天那个函数坏成返回空串，期望和实际一起变空、这条照样绿。
        #   （实测过：把 type_suffix 改成 return ""，用 helper 算期望的版本 100% PASS。）
        #   唯一该共享的是类型名常量本身。
        _suffix = "-" + str(_type_name).removeprefix("角色")

        def _expect(n, _s=_suffix):
            return n + _s

        _short = _row_probe(_maker("绯雪"))
        _long = _row_probe(_maker(_long_name))
        check(f"{_label}：名字带类型后缀（「{_expect('绯雪')}」）",
              _short[2] == _expect("绯雪"), f"实际 {_short[2]!r}")
        check(f"{_label}：行高不随名字长度变化",
              _short[0] == _long[0], f"短名 {_short[0]}px vs 长名 {_long[0]}px")
        check(f"{_label}：长名时头像还在（截图那个问题）",
              _short[1] and _long[1], f"短 {_short[1]} / 长 {_long[1]}")
        check(f"{_label}：长名被省略号截断（不换行、不溢出）",
              "…" in _long[2], repr(_long[2]))
        check(f"{_label}：短名完整显示（别误截）",
              "…" not in _short[2], repr(_short[2]))
        check(f"{_label}：省略后仍能悬停看到全名（含后缀）",
              _maker(_long_name).nameLabel.toolTip() == _expect(_long_name),
              repr(_maker(_long_name).nameLabel.toolTip()))
        # ★ 名字列**宽度要够**：用数据集里**最长的角色名** + 后缀来量，
        #   而不是钉一个魔数 —— 以后加了长名角色，这条会提醒你加宽 ROW_LEFT_WIDTH。
        _widest = _row_probe(_maker(_longest_char))
        check(f"{_label}：最长角色名「{_longest_char}」加后缀后不被截",
              _widest[2] == _expect(_longest_char), f"实际 {_widest[2]!r}")

    # ---- ★ 新增弹框：名字是**角色下拉**、且"一角色一条" ----
    _chars = [c.name for c in _CHARS]
    _taken = {_chars[1], _chars[2]}
    _dlg = EchoProfileDialog(cfg, profile=None, taken_chars=_taken)
    check("★ 名字是角色下拉，不是自由输入框",
          (not hasattr(_dlg, "nameEdit")) and hasattr(_dlg, "characterBox"),
          f"有 nameEdit={hasattr(_dlg, 'nameEdit')}")
    _choices = _dlg.characterBox.matched_texts()
    check("★ 已被占用的角色不在候选里（选不到）",
          not (_taken & set(_choices)),
          f"候选 {len(_choices)} 个 / 应有 {len(_chars) - len(_taken)}")
    _dlg.characterBox.setText("绯雪声骸强化配置")      # 用户截图里那个输入
    check("★ 不是角色的名字被拒（否则头像会消失）",
          _dlg.validate() is False, _dlg.errorLabel.text())
    _dlg.characterBox.setText(_chars[1])
    check("★ 已被别人占用的角色被拒（一角色一条）",
          _dlg.validate() is False, _dlg.errorLabel.text())
    _dlg.characterBox.setText(_chars[0])
    check("合法角色放行", _dlg.validate() is True)

    # ★ 角色输入框**宽度**：用户 2026-09-26 "太长了，缩短"（原来填满整行 650px）
    from PySide6.QtGui import QFontMetrics as _QFM

    from src.gui.pickers import CHARACTER_BOX_HINT, CHARACTER_BOX_WIDTH

    check("★ 角色下拉框已缩短（= CHARACTER_BOX_WIDTH，不再填满整行）",
          _dlg.characterBox.width() == CHARACTER_BOX_WIDTH,
          f"实际 {_dlg.characterBox.width()} / 期望 {CHARACTER_BOX_WIDTH}")
    _fm = _QFM(_dlg.characterBox.font())
    check("★ 下拉里的提示文字放得下（不会被截成半句）",
          _fm.horizontalAdvance(CHARACTER_BOX_HINT) <= CHARACTER_BOX_WIDTH - 40,
          f"{_fm.horizontalAdvance(CHARACTER_BOX_HINT)}px / 可用 "
          f"{CHARACTER_BOX_WIDTH - 40}px：{CHARACTER_BOX_HINT!r}")
    # ★★ 弹框的初始值必须和「声骸自动强化」页**打开时显示的一模一样**。
    #    这是用户 2026-09-26 的原话（"这里应该跟声骸自动强化一样"）。
    #
    #    ⚠ 踩过的坑：这里一度读的是 `tool_settings` 里**存盘**的那套，
    #      而工具页**每次进入都显示出厂默认**（用户早先定的规则）→
    #      弹框一打开就是「双爆不启用 / 可选勾了 2 条 / 有效词条 3」，
    #      和他看到的工具页完全不同。所以他连问三句"为什么默认……"。
    #
    #    所以这条**不能**去断言文案里有没有某句话（那种断言拦不住这个 bug），
    #    必须**把两边的实际状态抓出来比**。
    def _editor_state(ed):
        return (
            tuple(k for k, b in ed._core_boxes.items() if b.isChecked()),
            tuple(k for k, b in ed._optional_boxes.items() if b.isChecked()),
            bool(ed.crit_switch.isChecked()),
            float(ed.valid_stepper.value()),
            bool(ed.maxroll_switch.isChecked()),
        )

    _fresh_page = echo_tool.EchoEnhanceWidget(meta)     # 刚打开的「声骸自动强化」页
    _fresh_page.resize(900, 900)
    app.processEvents()
    from qfluentwidgets import CaptionLabel as _CapLbl

    # ⚠ 走**真实路径**（config_interface 自己构造弹框的那个方法），
    #   而不是在这里 new 一个 —— 这个 bug 就出在"调用方传错了起点"，
    #   自己 new 只能测到"弹框的默认行为"，拦不住它。
    _fresh_dlg = cfg._new_profile_dialog()
    _fresh_dlg.show()
    for _ in range(10):
        app.processEvents()
    _dlg_state, _page_state = _editor_state(_fresh_dlg.editor), _editor_state(_fresh_page)
    check("★ 弹框初始值 == 声骸自动强化页打开时的值（用户原话：「应该跟声骸自动强化一样」）",
          _dlg_state == _page_state,
          f"弹框 {_dlg_state} vs 工具页 {_page_state}")
    check("检查前置：两边都不是空转（核心属性确实有值）",
          bool(_dlg_state[0]) and bool(_page_state[0]))
    check("★ 新增默认 = 出厂默认（可选不预勾、有效词条 2、双爆下限启用）",
          _dlg_state[1] == () and _dlg_state[2] is True and _dlg_state[3] == 2.0,
          f"可选 {_dlg_state[1]} / 双爆下限 {_dlg_state[2]} / 有效词条 {_dlg_state[3]}")
    check("★ 顶部提示写明了「新增时的默认 = 出厂默认」",
          any("出厂默认" in w.text() for w in _fresh_dlg.findChildren(_CapLbl)),
          "提示里没写这句 —— 用户强调过很多次")
    _fresh_dlg.close()
    _fresh_page.close()
    _dlg.close()

    # ---- ★ 弹框内容**不许竖直重叠** ----
    # 2026-09-26 踩到：弹框的 viewLayout 本来就需要 786px、卡片只有 682px，
    # 我又在底部加了一行提示 → 它直接**叠在「可选属性」卡片上**。
    # 这类"加一行就叠"的毛病光看代码看不出来，必须量几何。
    # ⚠ 父窗口**必须 show 出来**，否则弹框的内容不会排版（所有子项 geometry 都是 0），
    #   下面的"不重叠"就成了**空转**（空列表当然不重叠）。实测踩过。
    cfg.resize(1000, 700)
    cfg.show()
    for _ in range(6):
        app.processEvents()

    _fit = EchoProfileDialog(cfg, profile=None, taken_chars=_taken,
                             initial_settings={})
    _fit.show()
    for _ in range(10):
        app.processEvents()
    _visible = [(type(_fit.viewLayout.itemAt(_i).widget()).__name__,
                _fit.viewLayout.itemAt(_i).widget().geometry().top(),
                _fit.viewLayout.itemAt(_i).widget().geometry().bottom())
               for _i in range(_fit.viewLayout.count())
               if _fit.viewLayout.itemAt(_i).widget() is not None
               and _fit.viewLayout.itemAt(_i).widget().isVisible()]
    check("检查前置：弹框已经排版（否则下面的「不重叠」是空转）",
          bool(_visible) and max(b for _, _, b in _visible) > 0,
          f"可见项 {_visible}")
    _bad = [( _visible[_i][0], _visible[_i + 1][0])
            for _i in range(len(_visible) - 1) if _visible[_i + 1][1] < _visible[_i][2]]
    check("★ 弹框里的可见项不重叠（加提示行加过头就会叠）",
          not _bad, f"重叠：{_bad}")
    # ⚠ 别用 `yesButton.mapTo(...)` 量"按钮有没有被挤出卡片"：弹框没排完时它给出的是
    #   贴着顶的假值（实测报 30/462，看着"通过"其实是空转）。
    #   量"最后一个可见项的底"更实在 —— 超出卡片高度就是被挤出去了。
    _last_bottom = max((b for _, _, b in _visible), default=0)
    check("★ 弹框内容没超出卡片底部",
          _last_bottom <= _fit.widget.height(),
          f"内容底 {_last_bottom} / 卡片高 {_fit.widget.height()}")
    _fit.close()

    # ---- ★ 筛选配置那边同样两条 ----
    from src.gui.loadout_dialog import LoadoutDialog as _LD

    _ldlg = _LD(cfg, None, taken_chars=_taken)
    _lchoices = _ldlg.character_combo.matched_texts()
    check("★ 筛选配置：已被占用的角色也不在候选里",
          not (_taken & set(_lchoices)),
          f"候选 {len(_lchoices)} 个 / 应有 {len(_chars) - len(_taken)}")
    _ldlg.character_combo.setText("查无此人")
    _ldlg._collect()
    from src.core.game_data import character_choice_error as _cce
    _ldlg_err = _cce(_ldlg.loadout.character, _taken)
    check("★ 筛选配置：不是角色也要拦（保存前校验）",
          bool(_ldlg_err), _ldlg_err)
    _ldlg.character_combo.setText(_chars[1])
    _ldlg._collect()
    _ldlg_err2 = _cce(_ldlg.loadout.character, _taken)
    check("★ 筛选配置：已被占用的角色也要拦（一角色一条）",
          bool(_ldlg_err2), _ldlg_err2)
    _ldlg.close()

    # ---- ★ 被任务流程引用的配置**不能删**（用户 2026-09-28）----
    # "已完成任务流程里使用的配置，不能直接删除配置，需要先删除任务，才能删除配置"
    #
    # 这里**不真的弹框**（弹出来会卡住脚本）—— 拦不拦由 ``_blocked_by_flows``
    # 决定，所以直接验它：被引用 → True（拦下），没被引用 → False（放行）。
    import tempfile as _tf
    from pathlib import Path as _P

    from src.core.echo_profile import EchoProfile as _EP2
    from src.core.echo_profile import EchoProfileStore as _PS2
    from src.core.loadout import Loadout as _LO2
    from src.core.loadout import LoadoutStore as _LS2
    from src.core.tasks import TaskFlow as _TF2
    from src.core.tasks import TaskStep as _TS2
    from src.core.tasks import (
        STEP_CONFIG as _SC2,
        STEP_TOOL as _ST2,
        TaskStore as _TSk2,
    )

    with _tf.TemporaryDirectory() as _tmp2:
        _tmpd = _P(_tmp2)
        # 造一条流程 + 一个被它引用的筛选配置
        _tstore = _TSk2(_tmpd / "tasks.json")
        _lstore = _LS2(_tmpd / "loadouts.json")
        _lo2 = _LO2(character="景燃", echo_set="凝夜白霜")
        _lstore.add(_lo2)
        _tstore.add(_TF2(name="引用了景燃的流程", steps=[
            _TS2(type=_ST2, key="echo_enhance", name="声骸自动强化"),
            _TS2(type=_SC2, key=_lo2.id, name="景燃", config_kind="loadout"),
        ]))

        from src.core.tasks import flows_using_config as _fuc

        _users = _fuc(_tstore.all(), "loadout", _lo2.id, "景燃")
        check("★ 被流程引用的配置 → 检测得到引用（会拦下删除）",
              _users == ["引用了景燃的流程"], str(_users))

        # 没被引用的配置 → 放行
        _lo3 = _LO2(character="爱弥斯", echo_set="凝夜白霜")
        _lstore.add(_lo3)
        check("★ 没被引用的配置 → 不拦（照旧能删）",
              _fuc(_tstore.all(), "loadout", _lo3.id, "爱弥斯") == [],
              str(_fuc(_tstore.all(), "loadout", _lo3.id, "爱弥斯")))

    # 源码级：两个删除入口都必须先过 _blocked_by_flows（别只接了一个）
    _ci_src = (ROOT / "src/gui/config_interface.py").read_text(encoding="utf-8")
    for _fn in ("def delete_profile", "def delete_loadout"):
        _body = _ci_src.split(_fn, 1)[1] if _fn in _ci_src else ""
        _body = _body.split("\n    def ", 1)[0]      # 截到下一个方法
        check(f"★ {_fn[4:]} 删除前调用了 _blocked_by_flows",
              "_blocked_by_flows" in _body)

    cfg.close()

    width = max(len(name) for name, _, _ in CHECKS)
    for name, ok, detail in CHECKS:
        print("%-*s %s%s" % (width, name, "PASS" if ok else "FAIL",
                             ("  " + detail) if detail else ""))
    failed = [c for c in CHECKS if not c[1]]
    print("\n%d 项检查，%d 项失败" % (len(CHECKS), len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
