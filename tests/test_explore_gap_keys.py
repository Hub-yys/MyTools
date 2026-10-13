# -*- coding: utf-8 -*-
"""★ 「照视频做操作」的单元测试 —— 这一半原来**完全没做**。

## 原来缺的是什么（必须留个记录）

最初的实现只做两件事::

    ① 照视频**对齐视角**
    ② **一直按 W** 往前走

视频里按 F / 空格 / 长按 E / 选对话，**一个都没学到**。
所以"飞、解谜、长按机关、对话分支"全都没实现 ——
用户从第一个会话就在说这些，我漏了。

这批测试钉的就是补上的那部分：
**从视频里学出按键，走到那一刻时照做。**

## 为什么判定层要测得这么细

按错键的代价不是"没效果"，是**机器在游戏里乱动**（对着空地按跳跃、
在机关门前按对话）。而且这层没法在离线环境真验（要开游戏），
所以只能在这里把各种提示文字、合并规则、时序都穷举掉。
"""

from __future__ import annotations

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.core.explore_gap.controller import (  # noqa: E402
    ActionKind,
    ExploreGapConfig,
    ExploreGapState,
    decide,
)
from src.core.explore_gap.keys import (  # noqa: E402
    DEFAULT_HOLD_SEC,
    MAX_CONSECUTIVE,
    TAP_SEC,
    KeyEvent,
    KeySchedule,
    build_schedule,
    parse_prompt,
)
from src.core.explore_gap.locator import Fix  # noqa: E402


def fix(*, dx: float = 0.0, index: int = 10, peak: float = 0.9) -> Fix:
    return Fix(index=index, frame=index * 15, time_s=index * 0.5,
               similarity=0.95, margin=0.07, dx=dx, dy=0.0, peak=peak)


class TestParsePrompt(unittest.TestCase):
    """把提示文字解析成"按什么键"。"""

    def test_letter_prompts(self):
        for text, want in (("F 对话", "f"), ("按 E 调查", "e"),
                           ("R 使用", "r"), ("Q 声骸技能", "q")):
            with self.subTest(text=text):
                got = parse_prompt(text)
                self.assertIsNotNone(got)
                self.assertEqual(got.key, want)

    def test_chinese_prompts(self):
        for text, want in (("空格 跳跃", "space"),
                           ("共鸣技能", "e"),
                           ("声骸", "q"),
                           ("按 跳跃 跳过去", "space")):
            with self.subTest(text=text):
                got = parse_prompt(text)
                self.assertIsNotNone(got, f"「{text}」该能解析")
                self.assertEqual(got.key, want)

    def test_key_plus_target_name(self):
        """★★★ 「键 + 目标名」——**游戏提示最常见的形状**。

        ## 这是实测抓到的漏判

        用户给的「在下油甘 3.5 无主的梁鸢」视频，建完库**学到了 0 个按键**。
        看上去像"这视频没提示"，把高分帧裁出来一看::

            [F] 鸱吻          ← 清清楚楚一个交互提示

        OCR 也读出来了（``'F 鸱吻'``）—— 但解析层丢了它，
        因为「鸱吻」是机关名，不在动作词表里。

        **判据写得太窄**：目标名可以是任何东西
        （鸱吻 / 声匣 / 宝箱 / 信标 / NPC 名字…），列全是不可能的。
        所以改成按**形状**判：开头是交互键 + 后面还有内容。
        """
        for text, want in (("F 鸱吻", "f"), ("F 声匣", "f"),
                           ("E 信标", "e"), ("F 宝箱", "f"),
                           ("Q 使用声骸技能", "q")):
            with self.subTest(text=text):
                got = parse_prompt(text)
                self.assertIsNotNone(got, f"「{text}」是正经提示，该认")
                self.assertEqual(got.key, want)

    def test_scene_noise_with_letters_rejected(self):
        """★★ 场景杂字里的大写字母**不能**被当成按键。

        ## 为什么必须有这条

        只按"形状"（开头是字母 + 后面有内容）判的话，实测抓到反例::

            'A B C'   → 会被当成"按 A"
            'B 方案'  → 会被当成"按 B"
            'D 方案'  → 会被当成"按 D"

        这些都是分组标注 / 方案编号，不是提示。
        而 **A / D 是转视角键** —— 误按会让机器乱转。

        → 所以要求开头那个字母在 ``INTERACTION_KEYS`` 里
          （只收实测见过是交互键的）。
        """
        for text in ("A B C", "B 方案", "D 方案", "第 3 期 A 组",
                     "北", "东 南 西", "在下油甘", "宝箱位置"):
            with self.subTest(text=text):
                self.assertIsNone(
                    parse_prompt(text),
                    f"「{text}」是场景杂字，不该解析成按键")

    def test_hold_detection(self):
        """★ 长按必须认出来 —— 用点按是**不会触发**长按机关的。"""
        for text in ("长按 F 对话", "按住 E 调查", "hold F 使用",
                     "长按 空格 跳跃"):
            with self.subTest(text=text):
                got = parse_prompt(text)
                self.assertIsNotNone(got, f"「{text}」该能解析")
                self.assertTrue(got.hold, f"{text} 该判成长按")
                self.assertAlmostEqual(got.seconds, DEFAULT_HOLD_SEC)

    def test_tap_is_short(self):
        got = parse_prompt("F 对话")
        self.assertFalse(got.hold)
        self.assertAlmostEqual(got.seconds, TAP_SEC)

    def test_no_key_returns_none(self):
        """**不认识的提示不猜** —— 猜错会在游戏里乱动。"""
        for text in ("", "   ", "宝箱就在前面", "这里风景不错", None):
            with self.subTest(text=text):
                self.assertIsNone(parse_prompt(text))

    def test_uppercase_letter_preferred(self):
        """有大写单字母就用它（比中文键名更明确）。"""
        got = parse_prompt("按 F 使用共鸣技能")
        self.assertEqual(got.key, "f")

    def test_unknown_letter_passes_through(self):
        """不认识的字母原样试一下（宁可试，也别静默丢掉）。"""
        got = parse_prompt("按 K 打开")
        self.assertEqual(got.key, "k")

    def test_text_preserved(self):
        """原文要留着 —— 出问题要能回查"视频里当时写的是什么"。"""
        got = parse_prompt("F 对话")
        self.assertEqual(got.text, "F 对话")


class TestPromptGate(unittest.TestCase):
    """★★ 挡住"场景杂字"—— OCR 读出来的**不都是**按键提示。

    ## 为什么这道闸是必需的（实测抓到的）

    真视频上 OCR 读出过::

        "宁（长按）离开心钥井"     ← 开头「宁」是噪声

    噪声本身不致命，但它证明 **OCR 会读进无关文字**。
    要是某段无关文字里碰巧有个大写字母（菜单标题、UP 主字幕），
    就会被当成按键去按 —— 那是**机器在游戏里乱动**。

    所以要求提示里至少有一个**动作词**，或者一个明确的中文键名。
    """

    def test_scene_labels_rejected(self):
        """画面标注（方向 / 水印 / UP 主名）**不该**被当按键。"""
        for text in ("北", "东 南 西", "在下油甘", "攻略组",
                     "第 3 期", "宝箱位置", "A B C"):
            with self.subTest(text=text):
                self.assertIsNone(
                    parse_prompt(text),
                    f"「{text}」是场景杂字，不该解析成按键")

    def test_letter_alone_rejected(self):
        """★ 光有大写字母不够 —— 场景里到处是大写字母。"""
        self.assertIsNone(parse_prompt("F"))
        self.assertIsNone(parse_prompt("E"))
        self.assertIsNone(parse_prompt("QWER"))

    def test_action_word_plus_letter_accepted(self):
        for text, want in (("F 对话", "f"), ("E 调查", "e"),
                           ("长按 F 使用", "f"), ("按 R 启动", "r")):
            with self.subTest(text=text):
                got = parse_prompt(text)
                self.assertIsNotNone(got, f"「{text}」是正经提示，该认")
                self.assertEqual(got.key, want)

    def test_chinese_key_name_alone_accepted(self):
        """中文键名本身就是动作词，单说也能认。"""
        for text, want in (("跳跃", "space"), ("共鸣技能", "e"),
                           ("声骸", "q"), ("冲刺", "shift")):
            with self.subTest(text=text):
                got = parse_prompt(text)
                self.assertIsNotNone(got)
                self.assertEqual(got.key, want)

    def test_action_word_without_key_refuses_to_guess(self):
        """★★★ **只有动作词、没有键名 → 宁可不按**。

        ## 这是实测抓到的一个**危险**误判

        真提示是 ``[F] （长按）离开心钥井`` ——
        **F 是键，"离开心钥井"是要做的事**。

        OCR 常常只读出文字、读不到那个 F 图标。
        我原来把"离开"映射成了 ESC，于是这种情况会**按 ESC** ——
        那会**打开暂停菜单**，把整条路线打断。

        → 现在"离开 / 返回"只算动作词、不提供键；
          读不到键名就返回 ``None``。

        "少做一次"只是卡一下；"按错键"会毁掉整段流程。
        """
        for text in ("（长按）离开心钥井", "宁（长按）离开心钥井",
                     "离开", "返回", "对话", "调查"):
            with self.subTest(text=text):
                self.assertIsNone(
                    parse_prompt(text),
                    f"「{text}」没有键名，不该猜一个键出来")

    def test_never_maps_to_escape(self):
        """★ ESC 是**危险键**（打开暂停菜单）—— 任何提示都不该映射到它。"""
        for text in ("（长按）离开心钥井", "离开", "返回", "ESC",
                     "F 离开", "长按 返回"):
            with self.subTest(text=text):
                got = parse_prompt(text)
                if got is not None:
                    self.assertNotEqual(
                        got.key, "esc",
                        f"「{text}」映射到了 ESC —— 会打开暂停菜单")

    def test_real_ocr_sample_with_key(self):
        """实测那条**带 F** 的原文 → 长按 F（这才是正确结果）。"""
        got = parse_prompt("F （长按）离开心钥井")
        self.assertIsNotNone(got)
        self.assertEqual(got.key, "f")
        self.assertTrue(got.hold)


class TestBuildSchedule(unittest.TestCase):
    """逐帧观测 → 按键表。"""

    def test_single_prompt_merges_into_one_event(self):
        """★★ 同一个提示连续出现好几帧，必须**合并成一次**。

        不合并的话，一次"按 F"会变成"连按 F 十几下" ——
        游戏里表现为疯狂连点，很多机关会被点坏或没反应。
        """
        obs = [(i, "F 对话") for i in range(10, 15)]
        sched = build_schedule(obs)
        self.assertEqual(len(sched.events), 1, f"该合并成 1 次：{sched.events}")
        e = sched.events[0]
        self.assertEqual(e.start, 10)
        self.assertEqual(e.frames, 5)

    def test_prompt_disappearing_ends_event(self):
        obs = [(10, "F 对话"), (11, "F 对话"), (12, None), (13, None)]
        sched = build_schedule(obs)
        self.assertEqual(len(sched.events), 1)
        self.assertEqual(sched.events[0].end, 11)

    def test_two_different_prompts_two_events(self):
        obs = [(10, "F 对话"), (11, "F 对话"), (12, "空格 跳跃")]
        sched = build_schedule(obs)
        self.assertEqual(len(sched.events), 2)
        self.assertEqual(sched.events[0].key, "f")
        self.assertEqual(sched.events[1].key, "space")

    def test_same_prompt_later_is_new_event(self):
        """中间断开了，后面又出现同一个提示 = **两次**按键。"""
        obs = [(10, "F 对话"), (11, None), (12, None), (13, "F 对话")]
        sched = build_schedule(obs)
        self.assertEqual(len(sched.events), 2)

    def test_unreadable_counted(self):
        obs = [(10, "宝箱在这里"), (11, "F 对话")]
        sched = build_schedule(obs)
        self.assertEqual(sched.unreadable, 1)
        self.assertEqual(len(sched.events), 1)

    def test_hold_event_keeps_hold(self):
        obs = [(10, "长按 E 机关")] * 4
        sched = build_schedule(obs)
        self.assertTrue(sched.events[0].hold)
        press = sched.presses_for(10)[0]
        self.assertTrue(press.hold)
        self.assertAlmostEqual(press.seconds, DEFAULT_HOLD_SEC)

    def test_consecutive_capped(self):
        """卡在一句提示上不该无限延长（有上限）。"""
        obs = [(i, "F 对话") for i in range(100)]
        sched = build_schedule(obs)
        self.assertLessEqual(sched.events[0].frames, MAX_CONSECUTIVE + 1)

    def test_empty(self):
        sched = build_schedule([])
        self.assertEqual(sched.events, [])
        self.assertEqual(sched.scanned, 0)
        self.assertIn("没学到", sched.describe())

    def test_describe(self):
        sched = build_schedule([(1, "F 对话"), (3, "空格 跳跃"),
                                (5, "（长按）E")])
        text = sched.describe()
        self.assertIn("3 次", text)
        self.assertIn("长按 1", text)


class TestPressesFor(unittest.TestCase):
    """★ 什么时候该按 —— 只在**起点**按一次。"""

    def test_presses_only_at_start(self):
        sched = build_schedule([(10, "F 对话"), (11, "F 对话"),
                                (12, "F 对话")])
        self.assertEqual(len(sched.presses_for(10)), 1, "起点该按一次")
        self.assertEqual(sched.presses_for(11), [], "持续帧不该重复按")
        self.assertEqual(sched.presses_for(12), [], "持续帧不该重复按")

    def test_presses_at_correct_index(self):
        sched = build_schedule([(10, "F 对话"), (20, "空格 跳跃")])
        self.assertEqual(sched.presses_for(10)[0].key, "f")
        self.assertEqual(sched.presses_for(20)[0].key, "space")
        self.assertEqual(sched.presses_for(15), [])

    def test_press_carries_frame_index(self):
        sched = build_schedule([(42, "F 对话")])
        self.assertEqual(sched.presses_for(42)[0].frame_index, 42)


class TestDecidePressesKeys(unittest.TestCase):
    """★★★ 端到端：走到视频按过键的位置，**决策层真的输出 KEY 动作**。

    这就是原来缺的那一半 —— 原来 ``decide`` 只会输出
    CORRECT / ADVANCE，从来不会"照视频按键"。
    """

    def _schedule(self):
        return build_schedule([(10, "F 对话"), (30, "（长按）E 机关")])

    def test_key_action_at_press_position(self):
        sched = self._schedule()
        st = ExploreGapState()
        act = decide(fix(index=10), st, ExploreGapConfig(),
                     library_len=100, schedule=sched)
        self.assertEqual(act.kind, ActionKind.KEY,
                         f"走到第 10 帧该按键，却出了 {act.kind}")
        self.assertEqual(act.key, "f")
        self.assertIn("F 对话", act.key_text)

    def test_hold_action_carries_seconds(self):
        sched = self._schedule()
        st = ExploreGapState()
        act = decide(fix(index=30), st, ExploreGapConfig(),
                     library_len=100, schedule=sched)
        self.assertEqual(act.kind, ActionKind.KEY)
        self.assertEqual(act.key, "e")
        self.assertAlmostEqual(act.seconds, DEFAULT_HOLD_SEC,
                               msg="长按机关必须带长按时长")

    def test_non_press_position_does_not_press(self):
        sched = self._schedule()
        st = ExploreGapState()
        act = decide(fix(index=50), st, ExploreGapConfig(),
                     library_len=100, schedule=sched)
        self.assertNotEqual(act.kind, ActionKind.KEY)

    def test_no_schedule_falls_back_to_old_behavior(self):
        """没按键表（旧库）→ 退回"转视角 + 前进"，不该崩。"""
        st = ExploreGapState()
        act = decide(fix(index=10), st, ExploreGapConfig(),
                     library_len=100, schedule=None)
        self.assertIn(act.kind, (ActionKind.ADVANCE, ActionKind.CORRECT))

    def test_press_keys_can_be_disabled(self):
        """配置里能关掉按键（给"只想让它跟着走"的场景）。"""
        sched = self._schedule()
        st = ExploreGapState()
        act = decide(fix(index=10), st,
                     ExploreGapConfig(press_keys=False),
                     library_len=100, schedule=sched)
        self.assertNotEqual(act.kind, ActionKind.KEY)

    def test_key_counted(self):
        sched = self._schedule()
        st = ExploreGapState()
        decide(fix(index=10), st, ExploreGapConfig(),
               library_len=100, schedule=sched)
        self.assertEqual(st.keys_pressed, 1)

    def test_key_takes_priority_over_correction(self):
        """★ 按键排在纠偏**前面**。

        视频里按 F 的那一刻人已经站到机关前了；先纠偏会多花几帧，
        等纠完画面早已不是那一帧，按键时机就错过了。
        """
        sched = self._schedule()
        st = ExploreGapState()
        #: 偏离很大（本该纠偏），但位置正好是按键点
        act = decide(fix(dx=200.0, index=10), st, ExploreGapConfig(),
                     library_len=100, schedule=sched)
        self.assertEqual(act.kind, ActionKind.KEY,
                         "有按键时该先按键，而不是先纠偏")

    def test_untrusted_never_presses(self):
        """★★ 测不准时**绝不能**按键 —— 位置可能是错的，按下去就是乱动。"""
        sched = self._schedule()
        st = ExploreGapState()
        act = decide(fix(index=10, peak=0.001), st, ExploreGapConfig(),
                     library_len=100, schedule=sched)
        self.assertNotEqual(act.kind, ActionKind.KEY)
        self.assertEqual(act.kind, ActionKind.WAIT)


class TestStateTracksLocatedIndex(unittest.TestCase):
    """★★ ``state.index`` 要跟**定位结果**走，不是开环计数。

    拿一个会漂的步数去查按键表，会在错的时间按键
    （在平地上按跳跃、在机关门前按对话）。
    """

    def test_index_follows_fix(self):
        st = ExploreGapState(index=0)
        decide(fix(index=37), st, ExploreGapConfig(), library_len=100)
        self.assertEqual(st.index, 37, "该用定位到的位置覆盖计数")

    def test_index_not_moved_when_untrusted(self):
        """测不准那一帧不能拿它的 index 去覆盖（那可能是错的位置）。"""
        st = ExploreGapState(index=20)
        decide(fix(index=99, peak=0.001), st, ExploreGapConfig(),
               library_len=100)
        self.assertEqual(st.index, 20, "测不准的定位不该改位置")

    def test_index_not_moved_when_missing(self):
        st = ExploreGapState(index=20)
        decide(None, st, ExploreGapConfig(), library_len=100)
        self.assertEqual(st.index, 20)


class TestKeyEventDataclass(unittest.TestCase):
    def test_frames(self):
        e = KeyEvent(text="F", key="f", hold=False, start=10, end=14)
        self.assertEqual(e.frames, 5)

    def test_press_label(self):
        sched = build_schedule([(1, "（长按）E")])
        press = sched.presses_for(1)[0]
        self.assertIn("长按", press.label)

    def test_schedule_default_empty(self):
        s = KeySchedule()
        self.assertEqual(s.events, [])
        self.assertEqual(s.presses_for(0), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
