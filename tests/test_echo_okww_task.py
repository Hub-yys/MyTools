"""ok-ww 声骸强化任务（MyTools 子类）的适配测试。

    python tests/test_echo_okww_task.py

2026-09-23：声骸自动强化从"MyTools 自己写点击/OCR"改成"跑 ok-ww 的
``EnhanceEchoTask`` + 只换判定条件"（见 ``src/tools/game/echo_enhance/okww_task.py``）。
这个文件只测**我们加的那层适配**，不测 ok-ww 自己的流程：

* OCR 的「属性名 + 数值」两列怎么配对成 :class:`EchoStat`（含噪声过滤）；
* 判定三态怎么映射回 ok-ww 要的布尔（``True``=继续强化 / ``False``=弃置）；
* 任务 key / 类名 / 注册路径三处不能各写一份（写岔了任务会静默不出现）。
"""

from __future__ import annotations

import inspect
import pathlib
import re
import unittest
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.tools.game.echo_enhance import okww_task  # noqa: E402
from src.tools.game.echo_enhance.okww_task import (  # noqa: E402
    MyToolsEnhanceEchoTask,
    to_echo_stats,
)
from src.tools.game.echo_enhance.stats import (  # noqa: E402
    CRIT,
    CRIT_DMG,
    JudgeConfig,
)


class FakeBox:
    """够用的 ok-script Box 替身 —— 配对逻辑只用到 `.name` 与 `.y`。"""

    def __init__(self, name: str, y: float):
        self.name = name
        self.y = y


def make_task(config: JudgeConfig) -> MyToolsEnhanceEchoTask:
    """不跑 ``__init__``（那需要 executor/app 两个真对象），只造个能调判定的壳。

    判定这条路只用到 ``judge_config`` / ``fail_reason`` / ``info`` / 两个日志方法，
    所以这么绕开是安全的 —— 也正是把这些依赖收得很窄的回报。
    """
    task = object.__new__(MyToolsEnhanceEchoTask)
    task.judge_config = config
    task.fail_reason = ""
    task.info = {}
    task.last_judgement = ""
    # 统计用的两个计数（正常由 __init__ 初始化，这里绕过了 __init__）
    task.discard_tally = {}
    task.checked_echoes = 0
    task.log_info = lambda *a, **k: None
    task.info_set = lambda key, value: task.info.__setitem__(key, value)
    return task


class TestPairing(unittest.TestCase):
    """OCR 两列文本 → EchoStat。"""

    def test_basic_pairing_by_nearest_y(self):
        props = [FakeBox("暴击伤害", 0.35), FakeBox("攻击", 0.37)]
        vals = [FakeBox("12.6%", 0.35), FakeBox("40", 0.37)]
        stats = to_echo_stats(props, vals)
        self.assertEqual([(s.name, s.value) for s in stats],
                         [(CRIT_DMG, 12.6), ("攻击", 40.0)])

    def test_percent_sign_decides_flat_or_percent(self):
        """「攻击」既可能是固定值也可能是百分比，靠数值里有没有 % 区分。"""
        stats = to_echo_stats([FakeBox("攻击", 0.3), FakeBox("攻击", 0.4)],
                              [FakeBox("40", 0.3), FakeBox("10.5%", 0.4)])
        self.assertEqual([s.name for s in stats], ["攻击", "攻击百分比"])

    def test_full_width_percent(self):
        """游戏里会出现全角 ％（OCR 也常这么读）。"""
        stats = to_echo_stats([FakeBox("暴击", 0.3)], [FakeBox("8.1％", 0.3)])
        self.assertEqual([(s.name, s.value) for s in stats], [(CRIT, 8.1)])

    def test_unknown_names_do_not_consume_values(self):
        """★ 认不出的属性名不能"吃掉"一个数值 —— 否则后面整体错位一格。"""
        props = [FakeBox("暴击伤害", 0.35), FakeBox("攻击", 0.37),
                 FakeBox("辅音", 0.40), FakeBox("共鸣效率", 0.41),
                 FakeBox("暴击", 0.43)]
        vals = [FakeBox("12.6%", 0.35), FakeBox("40", 0.37),
                FakeBox("10.0%", 0.41), FakeBox("8.1%", 0.43)]
        stats = to_echo_stats(props, vals)
        self.assertEqual([s.name for s in stats],
                         [CRIT_DMG, "攻击", "共鸣效率", CRIT])
        self.assertEqual([s.value for s in stats], [12.6, 40.0, 10.0, 8.1])

    def test_property_without_any_value_is_skipped(self):
        """数值比属性名少时，多出来的属性名不该造出 0 值的假词条。"""
        stats = to_echo_stats([FakeBox("暴击", 0.3), FakeBox("暴击伤害", 0.4)],
                              [FakeBox("8.1%", 0.3)])
        self.assertEqual([s.name for s in stats], [CRIT])

    def test_empty_inputs(self):
        self.assertEqual(to_echo_stats([], []), [])
        self.assertEqual(to_echo_stats([FakeBox("暴击", 0.3)], []), [])


class TestJudgementMapping(unittest.TestCase):
    """判定三态 → ok-ww 要的布尔。"""

    def test_discard_maps_to_false(self):
        """双爆不达标 → False，交给 ok-ww 去弃置。"""
        task = make_task(JudgeConfig())
        keep = task.check_echo_stats([FakeBox("暴击", 0.3), FakeBox("暴击伤害", 0.4)],
                                     [FakeBox("8.1%", 0.3), FakeBox("12.6%", 0.4)])
        self.assertFalse(keep)

    def test_keep_maps_to_true(self):
        task = make_task(JudgeConfig())
        keep = task.check_echo_stats([FakeBox("暴击", 0.3), FakeBox("暴击伤害", 0.4)],
                                     [FakeBox("9.0%", 0.3), FakeBox("18.0%", 0.4)])
        self.assertTrue(keep)

    def test_max_roll_protection_stays_true(self):
        """满暴击要走「强化到满级再上锁」，所以必须是 True（不能判弃置）。"""
        task = make_task(JudgeConfig())
        keep = task.check_echo_stats([FakeBox("暴击", 0.3)], [FakeBox("10.5%", 0.3)])
        self.assertTrue(keep)
        self.assertIn("满分", task.last_judgement)

    def test_fail_reason_is_safe_for_screenshot_name(self):
        """ok-ww 会把 fail_reason 拼进失败截图文件名，不能留空、不能带非法字符。"""
        task = make_task(JudgeConfig())
        task.check_echo_stats([FakeBox("暴击伤害", 0.3)], [FakeBox("9.9%", 0.3)])
        self.assertTrue(task.fail_reason)
        self.assertIsNone(re.search(r'[<>:"/\\|?*]', task.fail_reason),
                          f"fail_reason 含非法字符：{task.fail_reason!r}")

    def test_judge_config_is_per_instance(self):
        """判定条件是按任务实例注入的，改一个不该影响另一个。"""
        strict = make_task(JudgeConfig())
        loose = make_task(JudgeConfig(crit_min=1.0, crit_dmg_min=1.0, min_valid_count=2))
        props = [FakeBox("暴击", 0.3), FakeBox("暴击伤害", 0.4)]
        vals = [FakeBox("5.0%", 0.3), FakeBox("10.0%", 0.4)]
        self.assertFalse(strict.check_echo_stats(props, vals))
        self.assertTrue(loose.check_echo_stats(props, vals))


class TestWiring(unittest.TestCase):
    """任务 key / 类名 / 注册路径三处必须一致 —— 写岔了任务会静默不出现。"""

    def test_task_key_matches_tool_page(self):
        from src.tools.game.echo_enhance import settings, tool

        self.assertEqual(okww_task.TASK_KEY, settings.TASK_KEY)
        self.assertEqual(tool.TASK_KEY, settings.TASK_KEY)

    def test_host_registers_our_class(self):
        from src.tools.game.auto_combat import okww_boot

        self.assertEqual(okww_boot.TASKS[okww_task.TASK_KEY],
                         okww_task.TASK_CLASS_NAME)
        # 配置里声明的是"模块路径 + 类名"，ok 就是按这两项去 import 的
        entries = [tuple(e) for e in okww_boot.build_config()["onetime_tasks"]]
        self.assertIn(("src.tools.game.echo_enhance.okww_task",
                       okww_task.TASK_CLASS_NAME), entries)
        # ok-ww 原版不该再单独注册（两套筛选条件并存会让人分不清哪个在生效）
        self.assertNotIn(("okww.task.EnhanceEchoTask", "EnhanceEchoTask"), entries)

    def test_class_name_matches_constant(self):
        self.assertEqual(MyToolsEnhanceEchoTask.__name__, okww_task.TASK_CLASS_NAME)

    def test_is_okww_subclass(self):
        from okww.task.EnhanceEchoTask import EnhanceEchoTask

        self.assertTrue(issubclass(MyToolsEnhanceEchoTask, EnhanceEchoTask))


class TestDefaults(unittest.TestCase):
    """构造需要 executor/app，所以这两条改成对 __init__ 源码的断言 ——
    它们要防的是"以后有人顺手把这两行删了"，源码断言正好能拦住。"""

    def test_pause_after_success_is_turned_off(self):
        """ok-ww 默认"成功即暂停"；批量工具必须关掉，否则看着像只跑一个就停。"""
        src = inspect.getsource(MyToolsEnhanceEchoTask.__init__)
        self.assertRegex(src, r'Pause after Success"\]\s*=\s*False')

    def test_judge_config_is_reset_per_instance(self):
        src = inspect.getsource(MyToolsEnhanceEchoTask.__init__)
        self.assertRegex(src, r"self\.judge_config\s*=\s*JudgeConfig\(\)")


class TestLanguageGate(unittest.TestCase):
    """ok-script 会按语言**静默跳过**任务注册 —— 2026-09-24 的致命事故根源。

    ``task_manager.init_tasks()``::

        if len(task.supported_languages) == 0 or locale_name in task.supported_languages:
            tasks.append(task)

    宿主是无 GUI 的，``app.locale`` 实测是 qfluentwidgets 的默认值 **en_US**，
    而 ok-ww 的 ``EnhanceEchoTask`` 声明了 ``["zh_CN", "zh_TW"]`` ——
    子类推承了门禁 → 任务根本没进引擎 → 点「运行」只得到「找不到任务」。
    """

    def test_base_class_really_declares_the_gate(self):
        """反证：不覆盖的话确实会被跳过 —— 免得以后有人以为那行多余。"""
        from okww.task.EnhanceEchoTask import EnhanceEchoTask

        src = inspect.getsource(EnhanceEchoTask.__init__)
        self.assertRegex(src, r'supported_languages\s*=\s*\["zh_CN"')

    def test_language_gate_is_cleared(self):
        src = inspect.getsource(MyToolsEnhanceEchoTask.__init__)
        self.assertRegex(src, r"self\.supported_languages\s*=\s*\[\]")


class TestDiscardTally(unittest.TestCase):
    """弃置原因统计：一次运行结束要能看出"为什么都被弃置"。"""

    def test_format_tally(self):
        text = okww_task.format_tally(9, {"crit": 5, "valid": 3, "core": 1})
        self.assertIn("已判 9 次", text)
        self.assertIn("弃置 9 个", text)
        # 按数量降序：最多的原因排最前
        self.assertLess(text.index("双爆不达标"), text.index("有效词条不足"))
        self.assertIn("凑不齐核心属性", text)

    def test_format_tally_without_discards(self):
        self.assertIn("暂无弃置", okww_task.format_tally(3, {}))

    def test_check_echo_stats_records_reason(self):
        task = make_task(JudgeConfig(enable_max_roll_lock=False))
        keep = task.check_echo_stats(
            [FakeBox(CRIT, 0.4), FakeBox(CRIT_DMG, 0.4)],
            [FakeBox("6.3%", 0.4), FakeBox("12.6%", 0.4)],
        )
        self.assertFalse(keep)                       # 双爆都低于下限 → 弃置
        self.assertEqual(task.checked_echoes, 1)
        self.assertEqual(task.discard_tally, {"crit": 1})
        self.assertIn("判定统计", task.info)          # 页面靠它把原因显示出来

    def test_keep_does_not_touch_tally(self):
        task = make_task(JudgeConfig(min_valid_count=2, crit_min=0.0,
                                     crit_dmg_min=0.0, enable_max_roll_lock=False))
        keep = task.check_echo_stats([FakeBox(CRIT, 0.3)], [FakeBox("9.3%", 0.3)])
        self.assertTrue(keep)
        self.assertEqual(task.checked_echoes, 1)
        self.assertEqual(task.discard_tally, {})


class TestMaterialInsertRecovery(unittest.TestCase):
    """材料插入的状态机 —— 2026-09-26 修 ok-ww 的致命缺口。

    ok-ww 只认「阶段放入」。而那个按钮的文案是**随状态变**的：
    材料空着 = 「阶段放入」，材料已在里面 = 「清 除」。
    只要有一轮「强化并调谐」没把材料消耗掉，下一轮就找不到「阶段放入」→
    空等 5 秒 → 抛异常 → **整个任务当场结束**（实测跑完 42 次判定后死在这）。

    这组用例把"该恢复"和"该报错"两条路分开钉死。
    """

    def _task(self, *, stage: bool, clear: bool):
        """只造个能调 find_add_mat 的壳（绕开需要 executor/device 的 __init__）。"""
        task = object.__new__(MyToolsEnhanceEchoTask)
        task._materials_ready_sent = False
        task.wait_ocr = lambda *a, **k: FakeBox("阶段放入", 0.7) if stage else None
        task.ocr = lambda *a, **k: FakeBox("清 除", 0.7) if clear else None
        task.log_info = lambda *a, **k: None      # 恢复路径会记日志
        return task

    def test_sentinel_is_truthy(self):
        """哨兵必须为真 —— ok-ww 的循环是 ``if add_mat: have_add_mat = True``。"""
        self.assertTrue(okww_task._MATERIALS_READY)

    def test_stage_button_returned_when_empty(self):
        """材料空着 → 正常返回「阶段放入」（点它把材料放进去）。"""
        got = self._task(stage=True, clear=False).find_add_mat()
        self.assertIsNotNone(got)
        self.assertIsNot(got, okww_task._MATERIALS_READY)

    def test_clear_button_reports_ready_then_none(self):
        """★ 材料已在里面 → **报告一次就绪**，然后返回 None。

        两步缺一不可：
        * 不报告 → 走 ok-ww 的 raise，整个任务死掉（这就是线上那个 bug）；
        * 不返回 None → 外层 ``if have_add_mat: break`` 永远进不去，
          每个声骸白等满 5 秒。
        """
        task = self._task(stage=False, clear=True)
        self.assertIs(task.find_add_mat(), okww_task._MATERIALS_READY)
        self.assertIsNone(task.find_add_mat())

    def test_neither_button_returns_none(self):
        """两个都找不到 → 才是真该报错的情况（游戏里「阶段放入」没开）。"""
        self.assertIsNone(self._task(stage=False, clear=False).find_add_mat())

    def test_flag_resets_when_stage_reappears(self):
        """下一轮「阶段放入」回来 → 复位，之后还能再报告一次。"""
        task = self._task(stage=True, clear=True)
        task.find_add_mat()                        # 阶段放入 → 复位哨兵
        task.wait_ocr = lambda *a, **k: None       # 材料放进去了
        self.assertIs(task.find_add_mat(), okww_task._MATERIALS_READY)
        self.assertIsNone(task.find_add_mat())

    def test_second_round_also_recovers(self):
        """连续两轮都卡在同一状态 → 每一轮都要能恢复（不能只救第一次）。"""
        task = self._task(stage=False, clear=True)
        for _ in range(2):
            self.assertIs(task.find_add_mat(), okww_task._MATERIALS_READY)
            self.assertIsNone(task.find_add_mat())

    def test_sentinel_click_is_noop(self):
        """★ 哨兵被 click 时必须直接返回，不能落到真实点击上。

        真点下去 = 点「清 除」= 把刚放进去的材料**撤掉**。
        这里故意不给 device：一旦落到 ``super().click`` 就会抛异常，用例即失败。
        """
        task = self._task(stage=False, clear=True)
        task.click(okww_task._MATERIALS_READY, after_sleep=0.3)


    def test_okww_loop_no_longer_raises(self):
        """★ 端到端：照抄 ok-ww ``run()`` 那段循环，喂给它"材料还留在里面"的状态。

        这一段就是线上把整个任务打死的地方。修复前它必定抛
        「强化设置需要开启阶段放入!」；修复后必须**正常 break 出去**。
        """
        import time

        task = self._task(stage=False, clear=True)

        # ↓↓↓ 逐字照抄 okww/task/EnhanceEchoTask.py run() 里的内层 while ↓↓↓
        start_wait = time.time()
        have_add_mat = False
        while time.time() - start_wait < 5:
            add_mat = task.find_add_mat()
            if add_mat:
                have_add_mat = True
                task.click(add_mat, after_sleep=0.3)
            else:
                if have_add_mat:
                    break
        if not have_add_mat:
            raise AssertionError("仍然会抛「强化设置需要开启阶段放入!」"
                                 " —— 修复没生效")
        # ↑↑↑ 抄完 ↑↑↑

    def test_okww_loop_still_raises_when_truly_missing(self):
        """反证：真的两样都没有时**必须**照样抛 —— 别把真错误也吞了。"""
        import time

        task = self._task(stage=False, clear=False)
        start_wait = time.time()
        have_add_mat = False
        while time.time() - start_wait < 0.05:          # 缩短，用例别真等 5 秒
            add_mat = task.find_add_mat()
            if add_mat:
                have_add_mat = True
                task.click(add_mat, after_sleep=0.3)
            else:
                if have_add_mat:
                    break
        self.assertFalse(have_add_mat, "不该被判成就绪")


if __name__ == "__main__":
    unittest.main(verbosity=2)
