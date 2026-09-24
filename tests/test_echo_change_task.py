"""声骸批量调频（``MyToolsChangeEchoTask``）的适配测试。

    python tests/test_echo_change_task.py

这个文件只测**我们改掉的那层**，不测 ok-ww 自己的点击序列：

* **语言门禁必须清空** —— 否则任务被 ok-script 静默不注册（"凭空消失"）。
  带**反证**：基类确实声明了 ``["zh_CN"]``，不清空就会被跳过。
* **属性名必须精确比较** —— 原版用子串匹配，``"攻击" in "攻击百分比"`` 是 True，
  会把"明明该改的"声骸误判成"已经相同"并**抛异常中断整个任务**。
* **「已经是目标属性」走跳过分支**，不是抛异常。
* **跳过 / 失败分开统计**（混在一起用户会以为工具坏了）。
* 接线三处（TASKS 映射 / 工具页 key / 类名）不能各写一份。
"""

from __future__ import annotations

import inspect
import pathlib
import re
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.tools.game.auto_combat import okww_boot  # noqa: E402
from src.tools.game.echo_change import (  # noqa: E402
    DEFAULT_TARGET,
    TARGET_STATS,
    MyToolsChangeEchoTask,
    stat_matches,
    target_pattern,
)
from src.tools.game.echo_change import okww_task as mod  # noqa: E402


class FakeBox:
    """够用的 ok-script Box 替身 —— 这里只用到 ``.name``。"""

    def __init__(self, name: str):
        self.name = name


class FakeClickOcr:
    """``wait_click_ocr`` 的替身：返回一个"点到手了"的框。"""

    def __init__(self, name: str):
        self.name = name


def make_task(current_main: str = "防御百分比", target: str = DEFAULT_TARGET):
    """不跑 ``__init__``（要 executor/app 两个真对象），造个能调流程的壳。"""
    task = object.__new__(MyToolsChangeEchoTask)
    task.config = {"目标属性": target}
    task.info = {}
    task.fail_reason = ""
    task.ok_echoes = 0
    task.skipped_echoes = 0
    task.failed_echoes = 0
    task.fail_tally = {}
    task._consecutive_failures = 0
    task.stop_reason = ""
    task.log_info = lambda *a, **k: None
    task.log_error = lambda *a, **k: None
    task.sleep = lambda *a, **k: None
    task.info_set = lambda key, value: task.info.__setitem__(key, value)
    task.click = lambda *a, **k: None
    task.send_key = lambda *a, **k: None

    def wait_ocr(*args, **kwargs):
        # 区域调用（4 个位置参数）= 读当前主属性
        if len(args) == 4:
            return FakeBox(current_main)
        return FakeBox(str(kwargs.get("match") or "ok"))

    task.wait_ocr = wait_ocr
    task.wait_click_ocr = lambda *a, **k: FakeClickOcr("ok")
    return task


class TestStatMatching(unittest.TestCase):
    """★ 属性名精确比较 —— 原版子串匹配的 bug 就在这里。"""

    def test_same_name_matches(self):
        self.assertTrue(stat_matches("攻击", "攻击"))

    def test_prefix_must_not_match(self):
        """`攻击百分比` 与 `攻击` 是**两个不同的主属性**，绝不能互相命中。

        原版 ``target in current`` 在这里是 True → 误判"已经相同" →
        抛异常 → **整个任务中断**，而明明该改。
        """
        self.assertFalse(stat_matches("攻击百分比", "攻击"))
        self.assertFalse(stat_matches("攻击", "攻击百分比"))

    def test_crit_must_not_match_crit_dmg(self):
        """`暴击` 与 `暴击伤害` 同理 —— 原版也会误判。"""
        self.assertFalse(stat_matches("暴击伤害", "暴击"))
        self.assertFalse(stat_matches("暴击", "暴击伤害"))

    def test_normalizes_ocr_noise(self):
        """OCR 常见的噪声（前缀 +、空白、主属性字样）不该影响判定。"""
        for noisy in ("+攻击百分比", "攻击百分比 ", " 攻击百分比",
                      "主属性 攻击百分比", "主音属性攻击百分比"):
            with self.subTest(noisy=noisy):
                self.assertTrue(stat_matches(noisy, "攻击百分比"))

    def test_strength_suffix_is_ignored(self):
        """★「攻击力百分比」≡「攻击百分比」—— 游戏 UI 里两种写法都可能出现。

        ok-ww ``FiveToOneTask`` 的主属性表用的就是带「力」的形态，
        不带这一层归一化的话，"已经是对的了"会被判成"还没改"，
        白花材料又改一遍（或者反过来，该改的被误判成"已经是目标"）。
        """
        self.assertTrue(stat_matches("攻击力百分比", "攻击百分比"))
        self.assertTrue(stat_matches("生命值百分比", "生命百分比"))
        self.assertTrue(stat_matches("防御力百分比", "防御百分比"))

    def test_flat_and_percent_still_differ(self):
        """归一化吃掉「力浮」但**不能**把固定值和百分比混为一谈。"""
        self.assertFalse(stat_matches("攻击力", "攻击百分比"))
        self.assertFalse(stat_matches("攻击", "攻击百分比"))

    def test_full_width_percent(self):
        self.assertTrue(stat_matches("攻击百分比", "攻击百分比"))

    def test_original_substring_bug_is_real(self):
        """反证：原版那种写法确实会误判 —— 免得以后有人以为上面的用例多余。"""
        self.assertIn("攻击", "攻击百分比")
        self.assertIn("暴击", "暴击伤害")

    def test_subclass_does_not_use_substring_compare(self):
        """子类源码里不该再出现 ``target_main in current`` 那种子串比较。"""
        src = inspect.getsource(mod)
        self.assertNotIn("target_main in current", src)


class TestLanguageGate(unittest.TestCase):
    """语言门禁 —— 不清空任务会被静默跳过（和声骸强化踩过的同一个坑）。"""

    def test_base_class_really_declares_the_gate(self):
        """反证：基类确实声明了 zh_CN，不清空就进不了引擎。"""
        base = (ROOT / "vendor/okww/okww/task/ChangeEchoTask.py").read_text(
            encoding="utf-8", errors="replace")
        self.assertIn('supported_languages = ["zh_CN"]', base)

    def test_subclass_clears_it(self):
        src = inspect.getsource(mod)
        self.assertIn("self.supported_languages = []", src)


class TestAlreadyTargetIsSkip(unittest.TestCase):
    """「已经是目标属性」必须是**跳过**，不是致命异常（原版会中断整个任务）。"""

    def test_raises_internal_signal(self):
        task = make_task(current_main="防御百分比", target="攻击百分比")   # 不同 → 正常往下走
        try:
            task._do_change()
        except mod._AlreadyTarget:
            self.fail("属性不同时不该报「已经是目标属性」")
        except Exception:
            pass            # 后续步骤在壳里没打桩，抛别的也算"走过去了"

    def test_same_stat_raises_signal(self):
        task = make_task(current_main="攻击百分比", target="攻击百分比")
        with self.assertRaises(mod._AlreadyTarget):
            task._do_change()

    def test_strength_variant_also_counts_as_same(self):
        """「攻击力百分比」也要被认成"已经是目标"——不然会白改一遍。"""
        task = make_task(current_main="攻击力百分比", target="攻击百分比")
        with self.assertRaises(mod._AlreadyTarget):
            task._do_change()

    def test_signal_is_not_a_plain_exception_upstream(self):
        """信号必须是**独立类型**：不然没法跟"真出错了"分开统计。"""
        self.assertTrue(issubclass(mod._AlreadyTarget, Exception))
        self.assertIsNot(mod._AlreadyTarget, RuntimeError)

    def test_skip_counts_separately_from_failure(self):
        task = make_task()
        task._record_skip("攻击")
        self.assertEqual(task.skipped_echoes, 1)
        self.assertEqual(task.failed_echoes, 0)
        self.assertIn("跳过", task.tally_text())

    def test_failure_counts_separately(self):
        task = make_task()
        task._record_failure(RuntimeError("找不到「数据重构」"))
        self.assertEqual(task.failed_echoes, 1)
        self.assertEqual(task.skipped_echoes, 0)
        self.assertIn("失败", task.tally_text())


class TestFailureHandling(unittest.TestCase):
    def test_fail_reason_is_filename_safe(self):
        """ok-ww 会把 fail_reason 拼进失败截图文件名 —— 不能带非法字符。"""
        task = make_task()
        task._record_failure(RuntimeError('找不到 <数据重构>: "x/y"?'))
        for key in task.fail_tally:
            self.assertIsNone(re.search(r'[<>:"/\\|?*]', key), key)

    def test_consecutive_limit_is_bounded(self):
        self.assertGreater(mod.MAX_CONSECUTIVE_FAILURES, 0)
        self.assertLessEqual(mod.MAX_CONSECUTIVE_FAILURES, 10)

    def test_tally_text_lists_reasons(self):
        task = make_task()
        task._record_failure(RuntimeError("找不到「数据重构」"))
        task._push_stats()
        text = task.tally_text()
        self.assertIn("失败 1", text)
        self.assertIn("原因", text)


class TestStepRetry(unittest.TestCase):
    """``_step`` 的有限重试：第一次失败不该直接抛。"""

    def test_succeeds_after_transient_failures(self):
        task = make_task()
        calls = {"n": 0}

        def flaky():
            calls["n"] += 1
            return "ok" if calls["n"] >= 2 else None

        self.assertEqual(task._step("x", flaky), "ok")
        self.assertGreaterEqual(calls["n"], 2)

    def test_raises_after_exhausting_retries(self):
        task = make_task()
        with self.assertRaises(RuntimeError) as ctx:
            task._step("找不到「数据重构」", lambda: None)
        self.assertIn("数据重构", str(ctx.exception))

    def test_swallows_exception_then_raises_with_label(self):
        task = make_task()

        def boom():
            raise ValueError("OCR 炸了")

        with self.assertRaises(RuntimeError) as ctx:
            task._step("读主属性", boom)
        self.assertIn("读主属性", str(ctx.exception))


class TestWiring(unittest.TestCase):
    """三处名字不能各写一份 —— 写岔了任务会静默不出现。"""

    def test_task_registered_in_host(self):
        self.assertIn("声骸批量调频", okww_boot.TASKS)

    def test_host_points_at_our_class(self):
        self.assertEqual(okww_boot.TASKS["声骸批量调频"],
                         MyToolsChangeEchoTask.__name__)

    def test_tool_page_key_matches_host(self):
        from src.tools.game.echo_change.tool import TASK_KEY
        self.assertEqual(TASK_KEY, "声骸批量调频")
        self.assertIn(TASK_KEY, okww_boot.TASKS)

    def test_default_target_is_in_choices(self):
        self.assertIn(DEFAULT_TARGET, TARGET_STATS)

    def test_targets_cover_the_game_list(self):
        """12 个可选主属性（和 ok-ww 原版一致的**数量**，但名字修正过）。"""
        self.assertEqual(len(TARGET_STATS), 12)
        for name in ("攻击百分比", "生命百分比", "防御百分比",
                     "暴击", "暴击伤害", "共鸣效率"):
            self.assertIn(name, TARGET_STATS)

    def test_main_stats_are_percent_forms(self):
        """★ 主属性只有**百分比**形态。

        ok-ww 原版的选项表写的是 ``攻击`` / ``生命`` / ``防御`` ——
        那是**副词条**的形态，当主属性目标用的话游戏里根本选不到（2026-09-26 用户指出）。
        """
        for flat in ("攻击", "生命", "防御"):
            self.assertNotIn(flat, TARGET_STATS, f"{flat} 不是主属性形态")
        for pct in ("攻击百分比", "生命百分比", "防御百分比"):
            self.assertIn(pct, TARGET_STATS)

    def test_default_is_a_percent_form(self):
        self.assertIn("百分比", DEFAULT_TARGET)


class TestTargetPattern(unittest.TestCase):
    """选项检索要吃得下「攻击力百分比」这种带「力」的写法。

    ok-ww 自己的 ``FiveToOneTask`` 用的就是带「力」的形态
    （``main_stats = ["攻击力百分比", ...]``、``black_list = ["主属性攻击力", ...]``），
    所以游戏 UI 里很可能是「攻击力百分比」。
    字面量匹配会**漏掉**（中间多个「力」），必须做成可选。
    """

    def test_literal_only_would_miss(self):
        """反证：字面量匹配确实抓不到带「力」的写法。"""
        self.assertIsNone(re.search("攻击百分比", "攻击力百分比"))

    def test_pattern_matches_both_forms(self):
        pat = target_pattern("攻击百分比")
        for text in ("攻击百分比", "攻击力百分比", "主属性攻击力百分比"):
            with self.subTest(text=text):
                self.assertIsNotNone(pat.search(text))

    def test_pattern_covers_life_and_defense(self):
        self.assertIsNotNone(target_pattern("生命百分比").search("生命值百分比"))
        self.assertIsNotNone(target_pattern("防御百分比").search("防御力百分比"))

    def test_pattern_still_rejects_different_stats(self):
        """宽松 ≠ 乱匹配：不能把别的属性也吃进来。"""
        pat = target_pattern("攻击百分比")
        self.assertIsNone(pat.search("生命百分比"))
        self.assertIsNone(pat.search("攻击"))            # 固定值形态不是它
        self.assertIsNone(pat.search("暴击"))

    def test_crit_pattern_does_not_hit_crit_dmg(self):
        """★★ 最关键的一条：``暴击`` 的匹配式**不能**碰到 ``暴击伤害``。

        面板上这两个框同时存在。用子串匹配会先撞上「暴击伤害」那个框 →
        **把主属性改成用户没要的那个**，而且界面看起来"成功了"。
        （这就是 ok-ww 原版那个子串 bug 的同一类错误，我第一版这里也犯了，
        被这条用例抓出来 —— 所以它必须留着。）
        """
        pat = target_pattern("暴击")
        self.assertIsNotNone(pat.search("暴击"))
        self.assertIsNone(pat.search("暴击伤害"))
        self.assertIsNone(pat.search("暴击率"))       # 别的叫法也一样

    def test_pattern_is_anchored(self):
        """两头有锚点：带前缀可以，带后缀不行。"""
        pat = target_pattern("共鸣效率")
        self.assertIsNotNone(pat.search("共鸣效率"))
        self.assertIsNotNone(pat.search("主属性共鸣效率"))
        self.assertIsNotNone(pat.search("+共鸣效率"))
        self.assertIsNone(pat.search("共鸣效率提升"))


class TestSettingsKey(unittest.TestCase):
    def test_settings_key(self):
        self.assertEqual(mod.SETTINGS_KEY, "echo_change")


if __name__ == "__main__":
    unittest.main(verbosity=2)
