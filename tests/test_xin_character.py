"""「心」的角色支持：注册 / 模板 / 补丁可重放。

    python tests/test_xin_character.py

⚠ **测不了战斗逻辑本身** —— 那要接实时截图（见 ``Xin.py`` 的模块说明）。
这里守的是三件**会静默失败**的事：

1. `char_xin` 没注册 → 角色退化成通用循环（**不报错**，只是打得不好）
2. 识别模板尺寸被 ok-script 缩放 → 匹配率归零（**不报错**，只是一直匹配不上）
3. 上游更新把 vendor 里的改动冲掉 → 同上（**不报错**）
"""

from __future__ import annotations

import ast
import json
import os
import pathlib
import re
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor" / "okww"

#: ⚠ 必须放在最前面 —— 本文件有些用例要 import ``src.*``（战斗报告），
#: 而别的用例会 chdir 到 vendor。不先加这一条会 ModuleNotFoundError。
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

#: 给「心」加的东西
XIN_LABELS = ("char_xin", "xin_red", "xin_red_idle", "xin_white", "xin_dominion")

#: ★ 游戏分辨率 —— 用户的游戏就是 1920×1080（他给了图像设置截图）。
#: 底图和 COCO 声明都必须用这个，否则模板会被 ok-script 缩放（见下面的说明）。
SCREEN = (1920, 1080)

#: 模板的原始尺寸（1920×1080 下必须是这个 —— 被缩放就说明 COCO 声明错了）
EXPECTED_SIZES = {
    "char_xin": (60, 37),        # 认人用（对齐 ok-ww 原生量级）
    "xin_red": (405, 70),        # 状态条（从 1280 截图裁后放大到 1920 尺度）
    "xin_red_idle": (405, 70),
    "xin_white": (405, 70),
    "xin_dominion": (405, 70),
}


class TestUltimateAfterDominion(unittest.TestCase):
    """★★ 「心」必须**放得出二段大招**。

    用户 2026-10-01 报："心不放二段大招"。

    ## 根因（我的 bug）
    二段大招原来放在 ``perform_finish`` 里，靠 ``do_perform`` 的下一轮分派 ——
    但 ``do_perform`` 的 ``finally`` 会在 ``perform_dominion`` 返回后
    **立刻切人**；而且此时协奏已满，ok-ww 下次轮到这个角色时又会马上切走。
    于是 ``perform_finish`` **永远没机会跑**。

    日志证据（用户实机）：
        ``[统御众机] 13 秒到`` 出现 9 次，``[收尾]`` 出现 **0 次**。

    ## 修法
    二段大招必须在**切人之前**放完 —— 由 ``perform_dominion`` 当场连着调
    ``perform_finish()``。
    """

    def setUp(self):
        self.path = VENDOR / "okww" / "char" / "Xin.py"
        self.text = self.path.read_text(encoding="utf-8")
        tree = ast.parse(self.text)
        self.fn = next(
            n for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "perform_dominion")
        #: 常量要从源码里读（不在测试进程里 import ok-ww，那会拖进整个 ok 链）
        self.consts = {
            m.group(1): float(m.group(2))
            for m in re.finditer(
                r"^\s{4}([A-Z_]+) = ([\d.]+)\s*$", self.text, re.M)
        }

    def test_dominion_calls_finish(self):
        """★ ``perform_dominion`` 必须**自己**调 ``perform_finish``。"""
        calls = {
            n.func.attr for n in ast.walk(self.fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        }
        self.assertIn(
            "perform_finish", calls,
            "perform_dominion 没调 perform_finish —— 二段大招放不出来"
            "（do_perform 的 finally 会先切人）")

    def test_finish_after_heavy(self):
        """顺序：终结重击 → 二段大招（不能反）。

        ⚠ 用 **AST 的行号**比，不能拿源码字符串 find ——
        方法的 docstring 里也提到了 ``perform_finish``，
        字符串搜索会命中注释（实测踩过）。
        """
        heavy_line = finish_line = None
        for n in ast.walk(self.fn):
            if (isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Attribute)):
                if n.func.attr == "heavy_attack" and heavy_line is None:
                    heavy_line = n.lineno
                elif n.func.attr == "perform_finish" and finish_line is None:
                    finish_line = n.lineno
        self.assertIsNotNone(heavy_line, "没有终结重击")
        self.assertIsNotNone(finish_line, "没有 perform_finish 调用")
        self.assertLess(
            heavy_line, finish_line,
            f"顺序反了（重击 L{heavy_line} / 二段大 L{finish_line}）——"
            f" 二段大招必须在终结重击**之后**（攻略：提前开会大幅缩水）")

    def test_no_phase_finish_dispatch(self):
        """★ 不该再有 ``phase = "finish"`` —— 那条路走不通。

        ⚠ 这条防的是"改回去"：只要还有人设 ``phase = "finish"``，
        就说明二段大招又被丢给下一轮了。
        """
        self.assertNotIn(
            'phase = "finish"', self.text,
            '又设 phase = "finish" 了 —— 那条路永远轮不到（见类说明）')

    def test_finish_exists_as_method(self):
        """``perform_finish`` 本身要留着（可读性 + 可单测）。"""
        tree = ast.parse(self.text)
        names = {n.name for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef)}
        self.assertIn("perform_finish", names)

    def test_click_liberation_used(self):
        """二段大招靠 ``click_liberation`` 放。"""
        tree = ast.parse(self.text)
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef)
                  and n.name == "perform_finish")
        calls = {
            n.func.attr for n in ast.walk(fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        }
        self.assertIn("click_liberation", calls, "没按大招键")

    def test_waits_for_heavy_settle(self):
        """★★ 终结重击之后要**等收招**再去按大招。

        用户 2026-10-02 反馈"还是不行"，日志显示：:

            [统御众机] 13 秒到 → 终结重击【镇寰宇】
            [收尾] 找二段大招
            clicked liberation but no effect   ← 连续 4 次

        原因：二段大是【镇寰宇】**打完那一刻**才解锁的
        （攻略：「消耗完全部照心值后，重击替换为镇世，**随后**解锁
        第二阶段共鸣解放」）。重击有收招动画，抢在动画里按大招
        必然 no effect。

        ⚠ 这条防的是"把那个等待删掉"。
        """
        self.assertIn("HEAVY_SETTLE", self.text,
                      "没有 HEAVY_SETTLE 常量 —— 收招等待被删了")
        settle_line = None
        for n in ast.walk(self.fn):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "sleep"):
                seg = ast.get_source_segment(self.text, n) or ""
                if "HEAVY_SETTLE" in seg and settle_line is None:
                    settle_line = n.lineno
        self.assertIsNotNone(
            settle_line,
            "perform_dominion 里没有等收招（sleep(HEAVY_SETTLE)）——"
            " 大招会在动画期间被抢按，全部 no effect")

    def test_settle_between_heavy_and_finish(self):
        """顺序必须是：重击 → 等收招 → 找大招。"""
        heavy_line = settle_line = finish_line = None
        for n in ast.walk(self.fn):
            if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)):
                continue
            name = n.func.attr
            if name == "heavy_attack" and heavy_line is None:
                heavy_line = n.lineno
            elif name == "sleep" and settle_line is None:
                seg = ast.get_source_segment(self.text, n) or ""
                if "HEAVY_SETTLE" in seg:
                    settle_line = n.lineno
            elif name == "perform_finish" and finish_line is None:
                finish_line = n.lineno
        self.assertIsNotNone(heavy_line, "没有终结重击")
        self.assertIsNotNone(settle_line, "没有等收招")
        self.assertIsNotNone(finish_line, "没有 perform_finish")
        self.assertLess(heavy_line, settle_line,
                        "等收招必须在重击**之后**")
        self.assertLess(settle_line, finish_line,
                        "找大招必须在等收招**之后**")

    def test_finish_waits_for_ultimate_ready(self):
        """★ 收尾里要先查 ``ultimate_ready()`` 再按 —— 不闷头乱按。"""
        tree = ast.parse(self.text)
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef)
                  and n.name == "perform_finish")
        calls = {
            n.func.attr for n in ast.walk(fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        }
        self.assertIn(
            "ultimate_ready", calls,
            "perform_finish 没查 ultimate_ready —— 会像之前那样"
            "在动画期间连按 4 次 no effect")

    def test_finish_timeout_is_reasonable(self):
        """★ 等大招的窗口要有上界，但也不能太短。"""
        settle = self.consts.get("HEAVY_SETTLE")
        timeout = self.consts.get("FINISH_TIMEOUT")
        self.assertIsNotNone(settle, "没有 HEAVY_SETTLE 常量")
        self.assertIsNotNone(timeout, "没有 FINISH_TIMEOUT 常量")
        self.assertGreater(settle, 0, "收招等待必须是正数")
        self.assertLess(settle, 5.0, "收招等待太久会拖慢循环")
        self.assertGreaterEqual(
            timeout, 3.0,
            f"等大招只有 {timeout}s —— 动画+解锁判定不够，会像之前那样错过")
        self.assertLessEqual(
            timeout, 15.0,
            f"等大招 {timeout}s 太久 —— 协奏早满了，该切人了还在原地等")


class TestDontSwitchMidCombo(unittest.TestCase):
    """★★ 一套没打完**不能切人**（协奏满了也不行）。

    用户 2026-10-02 报："心怎么没打完一套就切人了？虽然他的协奏满了"。

    日志现象::

        [白狐] 开始攒照世心
        [红狐] 开始攒应世心            ← 白狐被打断，从红狐重来
        [白狐] 照世心满 → 强化 E 进统御众机
        switch_next_char Xin -> ShoreKeeper   ← 刚进统御就被切走

    ## 根因：我误解了 ``SwitchPriority.NO``

    它只表示「**别把我选为切换目标**」
    （``_choose_switch_target`` 用 ``> SwitchPriority.NO`` 过滤候选人），
    **不阻止**当前角色自己调 ``switch_next_char()``。

    而 ``do_perform`` 原来在 ``finally`` 里**无条件**调它 ——
    那是心**主动**要求换人，所以那个"保护"完全没生效。

    ## 修法
    ``do_perform`` 里用 :meth:`should_stay` 判断：一套走完（回红狐）才切。
    """

    def setUp(self):
        import logging
        import os

        self.text = (VENDOR / "okww" / "char" / "Xin.py").read_text(
            encoding="utf-8")
        logging.disable(logging.CRITICAL)
        vendor = str(VENDOR)
        if vendor not in sys.path:
            sys.path.insert(0, vendor)
        self._old_cwd = os.getcwd()
        os.chdir(VENDOR)
        try:
            from okww.char.Xin import Xin

            class _Task:
                def __getattr__(self, _n):
                    return lambda *a, **k: None

            self.char = Xin(_Task(), 0, char_name="char_xin")
        finally:
            os.chdir(self._old_cwd)

    def test_white_phase_does_not_switch(self):
        """★ 白狐阶段（中途）不能切。"""
        self.char.phase = "white"
        self.assertTrue(self.char.should_stay(),
                        "白狐阶段还要切人 —— 一套会被打断")

    def test_dominion_phase_does_not_switch(self):
        """★ 统御阶段（中途）不能切。"""
        self.char.phase = "dominion"
        self.assertTrue(self.char.should_stay(),
                        "统御阶段还要切人 —— 13 秒窗口会被打断")

    def test_red_phase_switches(self):
        """红狐 = 一套的起点/终点 → 可以切。"""
        self.char.phase = "red"
        self.assertFalse(self.char.should_stay(),
                         "红狐阶段不切人 —— 会永远占场")

    def test_do_perform_guards_the_switch(self):
        """★ ``do_perform`` 里切人要**受 should_stay 保护**。

        ⚠ 这条防的是"改回无条件切人"。用 AST 看 finally 里有没有 if。
        """
        tree = ast.parse(self.text)
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "do_perform")
        # 找 finally 块
        final_body = fn.body[-1]
        self.assertIsInstance(final_body, ast.Try, "do_perform 没有 try")
        self.assertTrue(final_body.finalbody, "do_perform 没有 finally")

        # finally 里必须有一个 If（判断 should_stay）
        has_guard = any(isinstance(n, ast.If) for n in final_body.finalbody)
        self.assertTrue(
            has_guard,
            "do_perform 的 finally 里没有条件判断 —— 又是无条件切人了"
            "（协奏一满就被切走，一套打不完）")

        # 那个 If 必须查 should_stay
        guard_src = " ".join(ast.get_source_segment(self.text, n) or ""
                             for n in final_body.finalbody
                             if isinstance(n, ast.If))
        self.assertIn("should_stay", guard_src,
                      "finally 里的判断不是 should_stay")

    def test_switch_priority_not_used_as_guard(self):
        """★ 别再把 ``SwitchPriority.NO`` 当"别切我"的开关。

        它只影响"谁被选为**目标**"，不影响当前角色主动切走 ——
        用它做保护是无效的（我就是这么错的）。

        ⚠ 只查**真代码**（AST），不查 docstring —— 方法文档里正好在
        解释这件事，字符串搜索会命中它（第一版就是这么误报的）。
        """
        tree = ast.parse(self.text)
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef)
                  and n.name == "get_switch_priority")
        # 收集方法体里真实用到的属性名（不看注释/docstring）
        used = set()
        for n in ast.walk(fn):
            if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name):
                used.add(f"{n.value.id}.{n.attr}")
        self.assertNotIn(
            "SwitchPriority.NO", used,
            "get_switch_priority 又拿 SwitchPriority.NO 当保护了 ——"
            " 那拦不住主动切人（2026-10-02 踩过）")

    def test_every_phase_eventually_returns_to_red(self):
        """★ 不切人会不会卡死？每条路都要能回到 red。

        红狐/白狐/统御三条路都有**超时兜底**，最终都会 phase="red"
        （``perform_finish`` 负责设回 red）。

        ⚠ 用 AST 查**字符串赋值**，不查源码文本 ——
        docstring 里也提到了 phase（第一版误报过）。
        """
        tree = ast.parse(self.text)

        def assigned_strings(fn_name: str) -> set:
            """方法体里 ``self.xxx = "字面量"`` 的所有字面量。"""
            fn = next(n for n in ast.walk(tree)
                      if isinstance(n, ast.FunctionDef) and n.name == fn_name)
            out = set()
            for n in ast.walk(fn):
                if (isinstance(n, ast.Assign)
                        and isinstance(n.value, ast.Constant)
                        and isinstance(n.value.value, str)):
                    out.add(n.value.value)
            return out

        # 三条路各自会推进到下一个形态
        self.assertIn("white", assigned_strings("perform_red"),
                      "perform_red 没把 phase 推进到 white")
        self.assertIn("dominion", assigned_strings("perform_white"),
                      "perform_white 没把 phase 推进到 dominion")
        # perform_finish 是唯一把 phase 设回 red 的地方
        self.assertIn("red", assigned_strings("perform_finish"),
                      "perform_finish 没把 phase 设回 red —— 会永远不切人")
        # 统御靠调 perform_finish 收尾
        dom = next(n for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef)
                   and n.name == "perform_dominion")
        called = {n.func.attr for n in ast.walk(dom)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        self.assertIn("perform_finish", called,
                      "perform_dominion 没收尾 —— phase 回不到 red，会卡住不切人")


class TestPhaseSurvivesReset(unittest.TestCase):
    """★★ 形态 phase 必须**跨 ``reset_state`` 保留**。

    用户 2026-10-02 报："心二阶段打满金色能量后，还是没有释放重击…
    打满金色能量后，一直在普攻"。

    ## 根因
    ``BaseChar.reset_state`` 的文档写明这些字段是**队伍重新识别时刷新**的：

        "Do not store long-term combat decisions only in these fields;
         they are refreshed whenever the team is re-read from the screen."

    ok-ww 每次 ``combat_once()``（每场战斗）都会 ``load_chars()``
    → 对每个角色调 ``reset_state()``。我原来在里面把 ``phase`` 设回
    ``"red"`` —— 于是：

    * 白狐/统御形态被清掉，下次 ``do_perform`` 又从 ``perform_red`` 开始
      （日志里形态序列反复出现 ``白狐 → 红狐 → 白狐``，
      72 次一段大、61 次白狐重新攒能）；
    * 攒照世心的进度**永远接不上** → 看起来就是"打满金色能量后一直普攻"。
    """

    def setUp(self):
        import logging
        import os

        self.text = (VENDOR / "okww" / "char" / "Xin.py").read_text(
            encoding="utf-8")
        logging.disable(logging.CRITICAL)
        vendor = str(VENDOR)
        if vendor not in sys.path:
            sys.path.insert(0, vendor)
        self._old_cwd = os.getcwd()
        os.chdir(VENDOR)
        try:
            from okww.char.Xin import Xin
        finally:
            os.chdir(self._old_cwd)
        self.Xin = Xin

    def _char(self):
        class _Task:
            def __getattr__(self, _n):
                return lambda *a, **k: None

        return self.Xin(_Task(), 0, char_name="char_xin")

    def test_white_phase_survives_reset(self):
        """★ 白狐形态不能被 reset_state 清回红狐。"""
        char = self._char()
        char.phase = "white"
        char.reset_state()
        self.assertEqual(
            char.phase, "white",
            "reset_state 把白狐形态清回红狐了 —— 攒照世心的进度会永远接不上"
            "（表现为「打满金色能量后一直普攻」）")

    def test_dominion_phase_survives_reset(self):
        char = self._char()
        char.phase = "dominion"
        char.dominion_start = 123.0
        char.reset_state()
        self.assertEqual(char.phase, "dominion")
        self.assertEqual(char.dominion_start, 123.0,
                         "统御的开始时刻丢了 —— 13 秒窗口会重新计时")

    def test_intro_state_still_cleared(self):
        """对照：**入场**状态仍该被父类清掉（别把该清的也留下）。"""
        char = self._char()
        char.has_intro = True
        char.current_con = 0.5
        char.reset_state()
        self.assertFalse(char.has_intro, "has_intro 没被清")
        self.assertEqual(char.current_con, 0, "current_con 没被清")

    def test_reset_state_calls_super(self):
        """必须调 ``super().reset_state()`` —— 否则父类那些清理全丢。"""
        tree = ast.parse(self.text)
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "reset_state")
        calls = [
            n for n in ast.walk(fn)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "reset_state"
        ]
        self.assertTrue(calls, "reset_state 没调 super() —— 入场状态清不掉")


class TestDominionDetectsSignal(unittest.TestCase):
    """★★ 统御阶段要**检测信号**，不能盲等 13 秒。

    用户报"打满金色能量后一直普攻"。原来 ``perform_dominion`` 是
    ``while 时间 < 13: 平A`` —— 盲等。但机制是：

        进统御 → 攻击**消耗照世心** → **耗尽后**重击才变成【镇寰宇】
        → 打完才解锁二段大

    盲等的两个坏处：
    * 照世心早早耗尽时白等剩下的秒数（浪费输出窗口）；
    * 13 秒还没耗尽时强行放重击 —— 打出来的不是【镇寰宇】，
      自然解锁不了二段大（这正是"亮了但按不生效"的来源）。
    """

    def setUp(self):
        self.text = (VENDOR / "okww" / "char" / "Xin.py").read_text(
            encoding="utf-8")
        tree = ast.parse(self.text)
        self.fn = next(
            n for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "perform_dominion")

    def _loop(self) -> ast.While:
        loops = [n for n in ast.walk(self.fn) if isinstance(n, ast.While)]
        self.assertTrue(loops, "perform_dominion 里没有 while 循环")
        return loops[0]

    def test_dominion_checks_forte(self):
        """★ 循环里要查 ``forte_ready()``（照世心耗尽 = 重击就绪）。"""
        calls = {
            n.func.attr for n in ast.walk(self._loop())
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        }
        self.assertIn(
            "forte_ready", calls,
            "统御循环没查 forte_ready —— 会盲等 13 秒，"
            "照世心耗尽也不知道停手")

    def test_dominion_breaks_early(self):
        """★ 检测到信号要 ``break`` —— 不能打满整 13 秒。"""
        breaks = [n for n in ast.walk(self._loop())
                  if isinstance(n, ast.Break)]
        self.assertTrue(breaks, "统御循环没有 break —— 永远打满 13 秒")

    def test_elapsed_still_capped(self):
        """13 秒仍要作为**兜底上限**（信号读不到时别卡死）。"""
        self.assertIn("DOMINION_DURATION", ast.get_source_segment(
            self.text, self._loop()) or "",
            "统御循环没有时间上限 —— 信号失灵时会卡死")


class TestVendorFiles(unittest.TestCase):
    """vendor 里的四处改动都在（不看运行，只看文件）。"""

    def test_labels_has_xin(self):
        text = (VENDOR / "okww" / "Labels.py").read_text(encoding="utf-8")
        for name in XIN_LABELS:
            with self.subTest(name=name):
                self.assertIn(f"{name} = '{name}'", text,
                              f"Labels 里没有 {name} —— 跑 tools/install_xin_patch.py")

    def test_factory_registers_xin(self):
        text = (VENDOR / "okww" / "char" / "CharFactory.py").read_text(
            encoding="utf-8")
        self.assertIn("from okww.char.Xin import Xin", text,
                      "CharFactory 没导入 Xin")
        self.assertIn("Labels.char_xin", text,
                      "CharFactory 没注册 char_xin —— 角色会退化成通用循环")

    def test_xin_class_exists(self):
        path = VENDOR / "okww" / "char" / "Xin.py"
        self.assertTrue(path.exists(), "Xin.py 不存在")
        text = path.read_text(encoding="utf-8")
        self.assertIn("class Xin(BaseChar)", text)
        self.assertIn("def do_perform", text)
        # 攻略明确写"固定13秒" —— 常量写对没有
        self.assertIn("DOMINION_DURATION = 13.0", text)

    def test_uses_generic_forte_detection(self):
        """★★ 必须用 ok-ww 的**通用**强化重击检测，不要自造模板。

        第一版用我自己裁的 `xin_red` 能量条模板判"能不能强化重击"，
        实机**一直失败**（日志"应世心攒满超时"，表现是一直平A）。
        原因：ok-ww 判这个用的是**所有角色共用**的通用检测
        （``is_forte_full`` 量屏幕底部白色占比 / ``is_mouse_forte_full``
        找 ``mouse_forte`` 模板），根本不看角色专属资源条。

        ⚠ 这条护栏防的就是"又退回去用自造模板"。
        ⚠ 也不能只查字符串 —— 还要**真的实例化**确认这些方法调得通
        （只 grep 的话，把 ``self.is_mouse_forte_full()`` 改成
        ``self.never_exists()`` 也能骗过去，实测漏过一次）。
        """
        text = (VENDOR / "okww" / "char" / "Xin.py").read_text(encoding="utf-8")
        self.assertIn("is_mouse_forte_full", text,
                      "没用通用强化重击检测 —— 会一直平A")
        self.assertIn("is_forte_full", text)
        # 不该再用自造的状态条模板判形态
        for bad in ("find_one(Labels.xin_", "Labels.xin_red",
                    "Labels.xin_white", "Labels.xin_dominion"):
            with self.subTest(bad=bad):
                self.assertNotIn(
                    bad, text,
                    f"又在用自造模板 {bad} 判形态了 —— 实机验证过那条路走不通")

    def test_xin_methods_actually_exist(self):
        """★ 实例化 Xin，确认它调用的**每个** ok-ww 方法都真实存在。

        ⚠ 这条是补上一条的漏洞：光看源码字符串不够，
        写成 ``self.never_exists()`` 一样能通过 grep。
        这里直接对着 ``BaseChar`` 查方法有没有。
        """
        import ast

        path = VENDOR / "okww" / "char" / "Xin.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))

        # 收集所有 self.xxx(...) 调用
        called = set()
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "self"):
                called.add(node.func.attr)

        old = os.getcwd()
        os.chdir(VENDOR)
        sys.path.insert(0, str(VENDOR))
        try:
            from okww.char.BaseChar import BaseChar
            from okww.char.Xin import Xin as _Xin  # noqa: F401
        finally:
            os.chdir(old)

        # 自己定义的方法不算；其余必须在 BaseChar 上找得到
        own = {"do_perform", "perform_red", "perform_white",
               "perform_dominion", "perform_finish",
               "forte_ready", "ultimate_ready", "skill_ready",
               "press_heavy_forte"}
        missing = sorted(
            n for n in called
            if n not in own and not hasattr(BaseChar, n)
            and not hasattr(_Xin, n))
        self.assertEqual(
            missing, [],
            f"Xin.py 调了 BaseChar 上不存在的方法：{missing} "
            f"（实机就是一直平A，因为异常被吞了）")

    def test_templates_exist(self):
        coco = VENDOR / "ok_tasks" / "assets" / "coco_annotations.json"
        png = (VENDOR / "ok_tasks" / "assets" / "images"
               / "xin_templates.png")
        self.assertTrue(coco.exists(), "识别模板的 COCO 不在")
        self.assertTrue(png.exists(), "识别模板的底图不在")


class TestCocoFormat(unittest.TestCase):
    """★ COCO 的两个坑（都会静默失效）。"""

    def _coco(self) -> dict:
        return json.loads((VENDOR / "ok_tasks" / "assets"
                           / "coco_annotations.json").read_text(encoding="utf-8"))

    def test_ascii_only(self):
        """★ 整个 json 必须是**纯 ASCII**。

        ok-script 的 ``load_json`` 用 ``open(path, 'r')``（**没指定
        encoding**），中文 Windows 上按 GBK 解码 —— 写中文进去会
        UnicodeDecodeError 把**整个模板加载**搞崩（实测踩过）。
        """
        raw = (VENDOR / "ok_tasks" / "assets"
               / "coco_annotations.json").read_bytes()
        try:
            raw.decode("ascii")
        except UnicodeDecodeError as exc:
            self.fail(f"COCO 里有非 ASCII 字符（会让 ok-script 按 GBK 解码崩）：{exc}")

    def test_declares_screen_size_not_canvas_size(self):
        """★ ``images[].width/height`` 要声明成**游戏分辨率**。

        ok-script 按 ``scale = screen_w / image_w`` 缩放模板，而
        ``image_w`` 取的是 **PNG 文件的实际尺寸**。如果底图做得很紧凑
        （比如 270px 宽），模板会被放大好几倍 → 匹配率归零。
        所以底图**就是** 1920×1080，声明也是 1920×1080（scale=1）。
        """
        coco = self._coco()
        image = coco["images"][0]
        self.assertEqual((image["width"], image["height"]), SCREEN,
                         "COCO 里声明的不是游戏分辨率")

        from PIL import Image

        png = VENDOR / "ok_tasks" / "assets" / "images" / "xin_templates.png"
        self.assertEqual(Image.open(png).size, SCREEN,
                         "底图尺寸和声明不一致 —— 模板会被缩放")

    def test_categories_and_annotations_match(self):
        coco = self._coco()
        names = {c["name"] for c in coco["categories"]}
        self.assertEqual(names, set(XIN_LABELS))
        # 每个类别都要有 bbox
        by_cat = {c["id"]: c["name"] for c in coco["categories"]}
        covered = {by_cat[a["category_id"]] for a in coco["annotations"]}
        self.assertEqual(covered, set(XIN_LABELS), "有类别没有 bbox")


class TestTemplatesLoad(unittest.TestCase):
    """★ 真的让 ok-script 加载一遍 —— 尺寸必须**原样**（scale=1）。"""

    def test_loads_at_native_size(self):
        from ok.feature.FeatureSet import read_from_json

        coco = VENDOR / "ok_tasks" / "assets" / "coco_annotations.json"
        old = os.getcwd()
        os.chdir(VENDOR)          # ok-ww 跑起来时 cwd 就是这里
        try:
            feats, _boxes, _c, success, _k = read_from_json(str(coco), *SCREEN)
        finally:
            os.chdir(old)

        self.assertTrue(success, "模板加载失败")
        for name, (w, h) in EXPECTED_SIZES.items():
            with self.subTest(name=name):
                self.assertIn(name, feats, f"{name} 没加载出来")
                mat = feats[name].mat
                self.assertEqual(
                    (mat.shape[1], mat.shape[0]), (w, h),
                    f"{name} 被缩放了 —— COCO 的尺寸声明不对")


class TestPatchScript(unittest.TestCase):
    """★ 上游更新会冲掉 vendor 里的改动 —— 补丁脚本要能重放。"""

    def test_patch_reports_all_installed(self):
        result = subprocess.run(
            [sys.executable, "tools/install_xin_patch.py"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", cwd=ROOT)
        out = (result.stdout or "") + (result.stderr or "")
        self.assertIn("全部就位", out,
                      f"补丁脚本报有缺失：\n{out}")

    def test_patch_is_idempotent(self):
        """跑两次不该重复插入（文本锚点替换必须是幂等的）。"""
        before = (VENDOR / "okww" / "Labels.py").read_text(encoding="utf-8")
        subprocess.run([sys.executable, "tools/install_xin_patch.py", "--apply"],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=ROOT)
        after = (VENDOR / "okww" / "Labels.py").read_text(encoding="utf-8")
        self.assertEqual(before, after, "补丁跑第二次改了文件 —— 不幂等")
        self.assertEqual(after.count("char_xin = 'char_xin'"), 1,
                         "char_xin 被插了多次")


class TestRecognizesXin(unittest.TestCase):
    """★★ 最重要的一条：**认得出来**。

    用户报的 bug 就是"心被识别成渊武"。所以这里做**端到端复现**：
    把 char_xin 和 ok-ww 全部 68 个 char_* 一起，在心的位置上比 ——
    必须 char_xin 分最高。
    """

    def _load(self, width, height):
        from ok.feature.FeatureSet import read_from_json

        old = os.getcwd()
        os.chdir(VENDOR)
        try:
            return read_from_json(
                str(VENDOR / "assets" / "coco_annotations.json"), width, height)
        finally:
            os.chdir(old)

    def test_char_xin_wins_at_xin_slot(self):
        """在用户给的战斗截图里，心的位置必须由 char_xin 胜出。"""
        import cv2
        import numpy as np

        shots_dir = pathlib.Path(r"D:\DeepSeek Work\xin_shots")
        if not shots_dir.exists():
            self.skipTest("没有实机截图（那是用户的素材，不随仓库分发）")

        shots = ["99a35152d30d216c8b7d733b16b408e6_720.png",
                 "b2f63b36b5d7baca1db2bb6696c8d7d9_720.png",
                 "5b3637a1e52a9aef8b45332c41a5e607_720.png"]
        shots = [s for s in shots if (shots_dir / s).exists()]
        if not shots:
            self.skipTest("截图文件不在")

        # 那些截图是 1280x720（QQ 缩略图），所以按 1280 加载
        mf, mb, _a, _b, _c = self._load(1280, 720)
        coco = VENDOR / "ok_tasks" / "assets" / "coco_annotations.json"
        old = os.getcwd()
        os.chdir(VENDOR)
        try:
            from ok.feature.FeatureSet import read_from_json

            ef, _e, _a2, _b2, _c2 = read_from_json(str(coco), 1280, 720)
        finally:
            os.chdir(old)

        xin = ef["char_xin"].mat
        merged = {n: f.mat for n, f in mf.items()}
        merged["char_xin"] = xin
        names = [n for n in merged if n.startswith("char_")]
        box = mb["box_char_1"]

        for shot in shots:
            frame = cv2.imread(str(shots_dir / shot))
            region = frame[box.y:box.y + box.height, box.x:box.x + box.width]
            scores = []
            for n in names:
                t = merged[n]
                if t.shape[0] > region.shape[0] or t.shape[1] > region.shape[1]:
                    continue
                try:
                    scores.append((float(cv2.matchTemplate(
                        region, t, cv2.TM_CCOEFF_NORMED).max()), n))
                except Exception:
                    continue
            scores.sort(reverse=True)
            with self.subTest(shot=shot):
                self.assertTrue(scores, "一个模板都没匹配上")
                self.assertEqual(
                    scores[0][1], "char_xin",
                    f"心又被认成 {scores[0][1]}（{scores[0][0]:.3f}）；"
                    f"char_xin 只有 "
                    f"{next((s for s, n in scores if n == 'char_xin'), -1):.3f}")

    def test_template_not_absurdly_large(self):
        """模板尺寸要和 ok-ww 原生量级相当（不能大好几倍）。

        ⚠ 这条是踩过的坑：第一版做了 140x125，而原生的都是 20~50 ——
        ok-script 会把它缩到框里，细节全丢，于是认成渊武。
        """
        coco = VENDOR / "ok_tasks" / "assets" / "coco_annotations.json"
        old = os.getcwd()
        os.chdir(VENDOR)
        try:
            from ok.feature.FeatureSet import read_from_json

            ef, _e, _a, _b, _c = read_from_json(str(coco), *SCREEN)
            mf, _m, _a2, _b2, _c2 = read_from_json(
                str(VENDOR / "assets" / "coco_annotations.json"), *SCREEN)
        finally:
            os.chdir(old)

        mine = ef["char_xin"].mat
        natives = [f.mat.shape[1] for n, f in mf.items()
                   if n.startswith("char_") and not n.endswith("_text")]
        biggest = max(natives)
        self.assertLessEqual(
            mine.shape[1], biggest * 1.5,
            f"char_xin 宽 {mine.shape[1]}px，比 ok-ww 最大的原生认人模板"
            f"（{biggest}px）还大不少 —— 会匹配不准")


class TestReportShowsAvatar(unittest.TestCase):
    """★ 战斗报告里「心」要有名字 + 头像。

    用户 2026-10-01 报："识别出来了，但是显示的不是头像"。

    根因：报告的角色名走 ok-ww 的翻译文件（``i18n/zh_CN/.../ok.po``），
    而**上游没有「心」** → po 里没有 ``msgid "Xin"`` → 名字保持英文 ``Xin``
    → 数据集里查不到（数据集存的是中文「心」）→ 没有头像。
    """

    def test_xin_maps_to_chinese_name(self):
        from src.tools.game.auto_combat import report

        class _Fake:
            pass

        _Fake.__name__ = "Xin"
        self.assertEqual(report.char_display_name(_Fake()), "心",
                         "Xin 没映射到中文名 —— 报告里会没头像")

    def test_local_char_names_table_exists(self):
        from src.tools.game.auto_combat import report

        self.assertIn("Xin", report.LOCAL_CHAR_NAMES)
        self.assertEqual(report.LOCAL_CHAR_NAMES["Xin"], "心")

    def test_avatar_resolves(self):
        from src.core import game_data
        from src.tools.game.auto_combat import report

        game_data.ensure_loaded()

        class _Fake:
            pass

        _Fake.__name__ = "Xin"
        name = report.char_display_name(_Fake())
        info = game_data.find_character(name)
        self.assertIsNotNone(info, f"数据集里找不到「{name}」")
        self.assertTrue(info.avatar, "心 没有头像路径")
        self.assertTrue((ROOT / "assets" / "game" / info.avatar).exists()
                        or info.avatar, "头像路径为空")

    def test_upstream_characters_unaffected(self):
        """加了 LOCAL_CHAR_NAMES 不该影响上游角色。"""
        from src.tools.game.auto_combat import report

        for cls, expect in (("ShoreKeeper", "守岸人"),
                            ("Cantarella", "坎特蕾拉")):
            with self.subTest(cls=cls):
                class _Fake:
                    pass

                _Fake.__name__ = cls
                self.assertEqual(report.char_display_name(_Fake()), expect)


if __name__ == "__main__":
    unittest.main(verbosity=2)
