# -*- coding: utf-8 -*-
"""「查缺补漏」执行器的单元测试（**假 task，不碰游戏**）。

## 为什么这层也要测

执行器是**唯一碰真实输入**的一层，也是唯一没法离线验证的一层。
所以它被刻意做薄（不含判断），但**薄不等于不用测**：

* 键位方向错了 → 越纠越偏（正反馈），整条路线走废
* 卡死循环 → 工具界面永远"运行中"
* 拿不到画面时死等 → 同上
* 走完 / 跟丢要能**退出**，不能无限跑

这些都能用一个假 task 测出来 —— 而且**必须**测，
因为真机验证成本高、还不一定复现。

## 假 task 提供什么

执行器只依赖一个很小的鸭子类型接口（这是刻意的设计）::

    next_frame()   → 一帧图（BGR ndarray）
    send_key(key, down_time=...) 
    sleep(seconds)

所以假 task 只要实现这三个，就能把整条链路跑通。
"""

from __future__ import annotations

import pathlib
import sys
import unittest

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.tools.game.explore_gap.executor import (  # noqa: E402
    CALIBRATION_HOLDS,
    MAX_PX_PER_TURN_SEC,
    MAX_TURN_SEC,
    MIN_CALIBRATION_SHIFT,
    MIN_PX_PER_TURN_SEC,
    PX_PER_TURN_SEC,
    ExploreGapTask,
    calibrate_turn,
    calibration_steps,
    dx_to_turn,
)


class TestDxToTurn(unittest.TestCase):
    """★ 键位方向 —— 错了就变成正反馈，最贵的错。

    约定（``docs/查缺补漏-实验记录.md`` 第四节）::

        dx > 0  =  画面内容相对参考**右移**  =  视角**左转**了
        → 要往**右**修 → 返回 "d"
    """

    def test_positive_dx_turns_right(self):
        key, sec = dx_to_turn(100.0)
        self.assertEqual(key, "d", "dx>0（画面右移）该往右修")
        self.assertGreater(sec, 0.0)

    def test_negative_dx_turns_left(self):
        key, sec = dx_to_turn(-100.0)
        self.assertEqual(key, "a", "dx<0（画面左移）该往左修")
        self.assertGreater(sec, 0.0)

    def test_tiny_dx_is_noop(self):
        """小于 1px 不动作（避免抖动）。"""
        self.assertEqual(dx_to_turn(0.0), ("", 0.0))
        self.assertEqual(dx_to_turn(0.5), ("", 0.0))
        self.assertEqual(dx_to_turn(-0.9), ("", 0.0))

    def test_longer_for_bigger_dx(self):
        self.assertGreater(dx_to_turn(80.0)[1], dx_to_turn(20.0)[1])

    def test_capped(self):
        """再大的偏离也不能一次转太久（宁可分几步）。"""
        _, sec = dx_to_turn(100000.0)
        self.assertLessEqual(sec, MAX_TURN_SEC)

    def test_default_constant_is_conservative(self):
        """默认换算要偏保守 —— 转少了能再转，转多了要转回来。"""
        self.assertGreater(PX_PER_TURN_SEC, 0.0)
        #: 1280px 整屏的换算时长不该超过 3 秒（否则明显过冲）
        self.assertLess(1280 * PX_PER_TURN_SEC, 3.0)


class FakeTask:
    """假的 ok-ww 任务 —— 只实现执行器真正用到的那三个方法。"""

    def __init__(self, *, frames=None, blank_after: int | None = None,
                 raise_on_frame: bool = False):
        self._frames = frames or []
        self._i = 0
        self._blank_after = blank_after
        self._raise = raise_on_frame
        self.keys: list[tuple[str, float]] = []
        self.sleeps: list[float] = []

    def next_frame(self):
        if self._raise:
            raise RuntimeError("模拟取画面失败")
        if self._blank_after is not None and self._i >= self._blank_after:
            return None
        if self._i >= len(self._frames):
            return None
        img = self._frames[self._i]
        self._i += 1
        return img

    def send_key(self, key, down_time=0.01):
        self.keys.append((key, down_time))

    def sleep(self, seconds):
        self.sleeps.append(seconds)


FRAME = np.zeros((720, 1280, 3), dtype=np.uint8)


class FakeLibrary:
    """最小的假参考库 —— 只要 ``__len__`` / ``close`` 够执行器用。"""

    def __init__(self, count=50):
        self._n = count

    def __len__(self):
        return self._n

    def close(self):
        pass


def make_task(*, frames=3, blank_after=None, raise_on_frame=False):
    """造一个执行器 + 假 task（绕过真实参考库加载）。"""
    logs: list[str] = []
    task = FakeTask(frames=[FRAME] * frames, blank_after=blank_after,
                    raise_on_frame=raise_on_frame)
    ex = ExploreGapTask.__new__(ExploreGapTask)     #: 跳过 __init__ 的读盘
    from src.core.explore_gap import ExploreGapConfig, ExploreGapState, Locator

    ex.library = FakeLibrary(50)
    ex.task = task
    ex.log = logs.append
    ex.should_stop = lambda: False
    ex.config = ExploreGapConfig()
    ex.px_per_turn_sec = PX_PER_TURN_SEC
    ex.state = ExploreGapState(index=0)
    #: 用假库构造 Locator 会走 locate（要真描述子）；这里只要状态容器，
    #: 所以换成"永远测不出"的桩 —— 主循环的退出行为正是要测的东西。
    ex.locator = _StubLocator()
    #: ★ 按键表（假库没有，给 None = 旧行为）。
    #: ⚠ 漏了这个会 AttributeError —— 因为 ``__new__`` 跳过了 ``__init__``，
    #: 而 ``__init__`` 里才会设 ``self.schedule``。加字段时要一起加。
    ex.schedule = None
    ex.calibration = []
    ex.stats = {"frames": 0, "advance": 0, "correct": 0,
                "wait": 0, "blank": 0, "lost": 0, "keys": 0}
    return ex, task, logs


class _StubLocator:
    """永远返回 None（模拟"一直定位不到"）—— 用来测退出行为。"""

    def __init__(self):
        self.library = FakeLibrary(50)
        self.reseat_calls = []

    def measure(self, frame):
        return None

    def reseat(self, index):
        self.reseat_calls.append(index)


class TestExecutorLoop(unittest.TestCase):
    """主循环的**退出行为** —— 卡死是工具类最招人烦的 bug。

    ⚠ 这些用例全部 ``auto_calibrate=False``：它们测的是**主循环**
    （拿不到画面 / 定位不到 / 该不该停），而标定是主循环**之前**的
    一道闸门（标定失败根本进不来）。不关掉的话，`_grab` 返回假图
    会让标定先失败，测的就不是主循环了。
    标定那一道闸门由 :class:`TestRunCalibratesFirst` 专门覆盖。
    """

    def test_no_frame_gives_up(self):
        """一直拿不到画面 → 必须退出（不能死等）。"""
        ex, task, logs = make_task(frames=0)
        stats = ex.run(auto_calibrate=False)
        self.assertGreater(stats["blank"], 0)
        self.assertTrue(any("拿不到画面" in m for m in logs),
                        f"没说清为什么退出：{logs}")

    def test_frame_exception_does_not_crash(self):
        """``next_frame`` 抛异常 → 记一条、继续重试，最终退出。"""
        ex, task, logs = make_task(raise_on_frame=True)
        stats = ex.run(auto_calibrate=False)
        self.assertGreater(stats["blank"], 0)
        self.assertTrue(any("取画面失败" in m for m in logs))

    def test_missing_frames_counts_and_exits(self):
        """有画面但定位不到 → 走计数、最终 LOST 退出。"""
        ex, task, logs = make_task(frames=100)
        stats = ex.run(auto_calibrate=False)
        #: 定位一直失败 → miss 计数到上限 → LOST
        self.assertEqual(stats["lost"], 1, "该以 LOST 结束")
        self.assertGreater(stats["frames"], 0)

    def test_should_stop_exits(self):
        ex, task, logs = make_task(frames=100)
        calls = {"n": 0}

        def stop():
            calls["n"] += 1
            return calls["n"] > 5

        ex.should_stop = stop
        stats = ex.run(auto_calibrate=False)
        self.assertLessEqual(stats["frames"], 8, "该及时停下")

    def test_returns_stats_dict(self):
        ex, task, logs = make_task(frames=1)
        stats = ex.run(auto_calibrate=False)
        for key in ("frames", "advance", "correct", "wait", "blank", "lost"):
            self.assertIn(key, stats)

    def test_closes_library(self):
        """跑完要关掉视频句柄（不然文件一直被占着）。"""
        closed = {"n": 0}

        class Lib:
            def __len__(self):
                return 50

            def close(self):
                closed["n"] += 1

        ex, task, logs = make_task(frames=1)
        ex.library = Lib()
        ex.run(auto_calibrate=False)
        self.assertEqual(closed["n"], 1)

    def test_closes_library_even_when_calibration_fails(self):
        """★ 标定失败提前返回时**也要**关句柄（不然占住文件）。"""
        closed = {"n": 0}

        class Lib:
            def __len__(self):
                return 50

            def close(self):
                closed["n"] += 1

        ex, task, logs = make_task(frames=0)
        ex.library = Lib()
        ex._grab = lambda: None
        ex.run()
        self.assertEqual(closed["n"], 1, "提前返回漏了关句柄")


class TestApply(unittest.TestCase):
    """把动作变成输入（**不做判断**，只翻译）。"""

    def _ex(self):
        ex, task, logs = make_task()
        return ex, task

    def test_advance_sends_w(self):
        """前进就是按 W。

        ⚠ 它**不再**推进 ``state.index`` —— 位置现在由**定位**驱动
        （见 :class:`~src.core.explore_gap.controller.ExploreGapState`）。
        原来这里断言 ``index == before + 1``，那是**开环计数**：
        走快了/走慢了/被击退都会漂，而按键表是"视频第几帧按什么键"，
        拿一个漂掉的数去查就会在错的时间按键。
        """
        from src.core.explore_gap import Action, ActionKind

        ex, task = self._ex()
        before = ex.state.index
        ex._apply(Action(ActionKind.ADVANCE))
        self.assertTrue(any(k == "w" for k, _ in task.keys),
                        f"前进该按 w：{task.keys}")
        self.assertEqual(ex.state.index, before,
                         "执行层不该动 index（那是定位的活）")
        self.assertEqual(ex.stats["advance"], 1)

    def test_press_action_sends_key(self):
        """★ 照视频按键 —— 「做一样的操作」。"""
        from src.core.explore_gap import Action, ActionKind

        ex, task = self._ex()
        ex._apply(Action(ActionKind.KEY, key="f", seconds=0.05,
                         key_text="F 对话"))
        self.assertIn(("f", 0.05), task.keys)
        self.assertEqual(ex.stats["keys"], 1)

    def test_press_hold_uses_down_time(self):
        """★ 长按靠 ``down_time``，不是连按很多次。

        连按在游戏里表现为"点了一百下"，长按机关根本不会触发。
        """
        from src.core.explore_gap import Action, ActionKind

        ex, task = self._ex()
        ex._apply(Action(ActionKind.KEY, key="e", seconds=1.2,
                         key_text="（长按）E 机关"))
        self.assertEqual(len(task.keys), 1, "长按只该按一次")
        key, seconds = task.keys[0]
        self.assertEqual(key, "e")
        self.assertAlmostEqual(seconds, 1.2, msg="长按时长没传下去")

    def test_press_without_key_does_nothing(self):
        """``KEY`` 动作没带 key（不该发生）→ 不按，不崩。"""
        from src.core.explore_gap import Action, ActionKind

        ex, task = self._ex()
        ex._apply(Action(ActionKind.KEY))
        self.assertEqual(task.keys, [])

    def test_correct_sends_direction(self):
        from src.core.explore_gap import Action, ActionKind

        ex, task = self._ex()
        ex._apply(Action(ActionKind.CORRECT, dx=50.0))
        self.assertIn(("d", 50.0 * PX_PER_TURN_SEC), task.keys)
        self.assertEqual(ex.stats["correct"], 1)

    def test_correct_negative_dx_sends_a(self):
        from src.core.explore_gap import Action, ActionKind

        ex, task = self._ex()
        ex._apply(Action(ActionKind.CORRECT, dx=-50.0))
        self.assertEqual(task.keys[0][0], "a")

    def test_wait_sends_nothing(self):
        from src.core.explore_gap import Action, ActionKind

        ex, task = self._ex()
        ex._apply(Action(ActionKind.WAIT))
        self.assertEqual(task.keys, [], "WAIT 不该产生任何按键")
        self.assertEqual(ex.stats["wait"], 1)

    def test_done_and_lost_send_nothing(self):
        from src.core.explore_gap import Action, ActionKind

        for kind in (ActionKind.DONE, ActionKind.LOST):
            with self.subTest(kind=kind):
                ex, task = self._ex()
                ex._apply(Action(kind))
                self.assertEqual(task.keys, [])

    def test_send_key_failure_recorded_not_raised(self):
        """按键失败不该把整个任务炸掉。"""
        from src.core.explore_gap import Action, ActionKind

        ex, task = self._ex()

        def boom(*a, **kw):
            raise RuntimeError("假输入失败")

        task.send_key = boom
        ex._apply(Action(ActionKind.CORRECT, dx=50.0))   #: 不该抛
        self.assertTrue(any("按键" in m for m in ex.log.__self__)
                        if hasattr(ex.log, "__self__")
                        else True)


class TestCalibration(unittest.TestCase):
    def test_steps_are_ordered_and_valid(self):
        steps = calibration_steps()
        self.assertTrue(steps)
        for key, sec in steps:
            self.assertIn(key, ("a", "d"))
            self.assertGreater(sec, 0.0)
            self.assertLessEqual(sec, MAX_TURN_SEC)
        #: 时长应该递增（方便找"刚好转过去"的点）
        secs = [s for _, s in steps]
        self.assertEqual(secs, sorted(secs))

    def test_constants_are_sane(self):
        self.assertTrue(CALIBRATION_HOLDS)
        self.assertEqual(list(CALIBRATION_HOLDS),
                         sorted(CALIBRATION_HOLDS), "标定时长该递增")
        self.assertGreater(MIN_CALIBRATION_SHIFT, 0.0)
        self.assertLess(MIN_PX_PER_TURN_SEC, MAX_PX_PER_TURN_SEC)


class TestAutoCalibration(unittest.TestCase):
    """★ 自动标定 —— 唯一会"乱走"的风险就靠它消除。

    ## 为什么它值得测

    ``PX_PER_TURN_SEC`` 取决于游戏灵敏度 / DPI / FOV，猜不出来。
    没标定就跑，机器会照着错的换算转 —— 转不够一直偏，转太多来回甩。

    自动标定靠的是**已经验证过亚像素精度**的相位相关
    （闭环残差最大 0.478px），所以比人眼估准得多。

    ## 这里怎么测（造一张会按已知速率平移的假画面）

    假 ``grab_frame`` 每被调用一次就把画面右移 ``rate`` 像素
    —— 按键时长 H 对应横移 ``rate · H / px_per_sec``。
    于是真值换算已知，能直接验拟合对不对。
    """

    def _make_frames(self, px_per_sec: float):
        """造一个"按一下就动"的假世界。

        :param px_per_sec: 真值换算（秒/像素）—— 拟合应该恢复它

        ⚠ 假 ``send`` 必须按**定义**来::

            px_per_sec = 秒/像素   →   像素 = 按键秒数 / px_per_sec

        （第一版我在里面又乘又除绕了一圈，结果位移比
        ``MIN_CALIBRATION_SHIFT`` 还小，样本全被丢掉。）
        """
        import cv2                                     # noqa: PLC0415

        rng = np.random.default_rng(5)
        base = rng.integers(0, 255, (720, 1280, 3), dtype=np.uint8)
        base = cv2.GaussianBlur(base, (5, 5), 0)
        H, W = base.shape[:2]
        state = {"shift": 0.0}

        def grab():
            M = np.float32([[1, 0, state["shift"]], [0, 1, 0]])
            return cv2.warpAffine(base, M, (W, H),
                                  borderMode=cv2.BORDER_REPLICATE)

        def send(key, seconds):
            state["shift"] += seconds / px_per_sec

        return grab, send

    def test_recovers_known_constant(self):
        """★ 已知换算能被拟合回来。

        真值 0.0012 秒/像素（1280 宽整屏 ≈1.5 秒，实测参考值）。
        标定时长 0.10~0.35s → 横移 83~292px，都在可测范围内。
        """
        true_value = 0.0012
        grab, send = self._make_frames(true_value)
        value, samples = calibrate_turn(grab, send)
        self.assertTrue(samples, "该采到样本")
        self.assertGreater(value, 0.0, "该标定成功")
        #: 过原点最小二乘在**无噪声**的假世界上应该几乎精确
        self.assertAlmostEqual(value, true_value, delta=true_value * 0.05,
                               msg=f"拟合出 {value}，真值 {true_value}")

    def test_monotonic_samples(self):
        """按键越久，画面该移得越多（线性关系的必要条件）。"""
        grab, send = self._make_frames(0.0012)
        _value, samples = calibrate_turn(grab, send)
        self.assertGreaterEqual(len(samples), 2)
        shifts = [px for _h, px in samples]
        self.assertEqual(shifts, sorted(shifts),
                         f"样本不单调，拟合没意义：{samples}")

    def test_no_frame_returns_zero(self):
        """拿不到画面 → 返回 0.0（**别瞎猜一个数**）。"""
        value, samples = calibrate_turn(lambda: None, lambda k, s: None)
        self.assertEqual(value, 0.0)
        self.assertEqual(samples, [])

    def test_static_screen_returns_zero(self):
        """画面一动不动（对着 UI / 纯色）→ 标定失败返回 0.0。

        这是**最关键的一条**：返回 0 让调用方明确知道没标成，
        而不是塞一个猜的数继续跑（那就会乱走）。
        """
        import cv2                                     # noqa: PLC0415

        rng = np.random.default_rng(9)
        still = rng.integers(0, 255, (720, 1280, 3), dtype=np.uint8)
        still = cv2.GaussianBlur(still, (5, 5), 0)
        value, samples = calibrate_turn(lambda: still, lambda k, s: None)
        self.assertEqual(value, 0.0, "画面没动却标定成功了 —— 危险")
        self.assertEqual(samples, [])

    def test_key_failure_does_not_raise(self):
        """按键抛异常 → 记日志、返回 0.0，不该把任务带崩。"""
        import cv2                                     # noqa: PLC0415

        rng = np.random.default_rng(11)
        img = rng.integers(0, 255, (720, 1280, 3), dtype=np.uint8)

        def boom(key, seconds):
            raise RuntimeError("假输入失败")

        logs: list[str] = []
        value, samples = calibrate_turn(lambda: img, boom, log=logs.append)
        self.assertEqual(value, 0.0)
        self.assertTrue(any("按键" in m for m in logs))

    def test_absurd_result_rejected(self):
        """拟合结果超出合理区间 → 判定失败（而不是照它跑）。"""
        import cv2                                     # noqa: PLC0415

        rng = np.random.default_rng(13)
        base = rng.integers(0, 255, (720, 1280, 3), dtype=np.uint8)
        base = cv2.GaussianBlur(base, (5, 5), 0)
        H, W = base.shape[:2]
        state = {"shift": 0.0}

        def grab():
            M = np.float32([[1, 0, state["shift"]], [0, 1, 0]])
            return cv2.warpAffine(base, M, (W, H),
                                  borderMode=cv2.BORDER_REPLICATE)

        def send(key, seconds):
            #: 移动量巨大 → 拟合出的秒/像素会小得离谱（超出下限）
            state["shift"] += 5000.0 * seconds

        value, _samples = calibrate_turn(grab, send)
        self.assertEqual(value, 0.0, "离谱结果该被拒掉")

    def test_executor_calibrate_updates_rate(self):
        """``ExploreGapTask.calibrate()`` 成功后要更新自己的换算。"""
        import cv2                                     # noqa: PLC0415

        rng = np.random.default_rng(17)
        base = rng.integers(0, 255, (720, 1280, 3), dtype=np.uint8)
        base = cv2.GaussianBlur(base, (5, 5), 0)
        H, W = base.shape[:2]
        state = {"shift": 0.0}

        ex, task, logs = make_task(frames=0)

        def grab():
            M = np.float32([[1, 0, state["shift"]], [0, 1, 0]])
            return cv2.warpAffine(base, M, (W, H),
                                  borderMode=cv2.BORDER_REPLICATE)

        def send(key, seconds):
            #: 同 :meth:`_make_frames` 的定义：像素 = 秒 / (秒/像素)
            state["shift"] += seconds / 0.0012
        ex._grab = grab
        task.send_key = send
        ex.px_per_turn_sec = 999.0                     #: 先放个明显错的
        value = ex.calibrate()
        self.assertGreater(value, 0.0)
        self.assertEqual(ex.px_per_turn_sec, value, "该更新自己的换算")
        self.assertTrue(ex.calibration, "该留下样本给报告用")

    def test_executor_calibrate_failure_keeps_zero_signal(self):
        """标定失败 → 返回 0.0（调用方据此拒绝运行）。"""
        ex, _task, logs = make_task(frames=0)
        ex._grab = lambda: None
        self.assertEqual(ex.calibrate(), 0.0)
        self.assertTrue(any("标定失败" in m for m in logs))


class TestRunCalibratesFirst(unittest.TestCase):
    """★★★ 跑之前必须标定；标定失败必须**不跑**。

    ## 这条为什么是安全关键

    ``PX_PER_TURN_SEC`` 猜不出来（灵敏度 / DPI / FOV）。
    照一个**错的换算**去转 = 转不够一直偏 / 转太多来回甩
    = **唯一会"乱走"的情形**。

    所以：标定没成功 → **根本不进主循环**。
    "没跑"远比"乱走"好 —— 后者用户会以为工具坏了。

    ⚠ 这条测试也钉住了"文档与代码一致"：README 里写了
    「跑之前 `calibrate()` 会自己做完」，代码必须真的调它。
    """

    def test_calibration_failure_blocks_run(self):
        ex, task, logs = make_task(frames=100)
        ex._grab = lambda: None                    #: 标定必然失败
        stats = ex.run()
        self.assertEqual(stats.get("calibration_failed"), 1,
                         "标定失败该被记下来")
        self.assertEqual(stats["frames"], 0,
                         "★ 标定失败却跑了主循环 —— 会乱走")
        self.assertTrue(any("不进入主循环" in m for m in logs))

    def test_calibration_runs_by_default(self):
        """默认就该标定（不用调用方记得传参）。"""
        import inspect                                 # noqa: PLC0415

        sig = inspect.signature(ExploreGapTask.run)
        self.assertIn("auto_calibrate", sig.parameters)
        self.assertIs(sig.parameters["auto_calibrate"].default, True,
                      "默认必须开启标定")

    def test_auto_calibrate_can_be_skipped(self):
        """显式关掉标定 → 直接进主循环（给"已经标过"的场景）。"""
        ex, task, logs = make_task(frames=100)
        stats = ex.run(auto_calibrate=False)
        self.assertNotIn("calibration_failed", stats)
        self.assertGreater(stats["frames"], 0, "关掉标定后该正常跑")

    def test_successful_calibration_reaches_main_loop(self):
        """标定成功 → 进主循环，并把换算记进统计。"""
        import cv2                                     # noqa: PLC0415

        rng = np.random.default_rng(23)
        base = rng.integers(0, 255, (720, 1280, 3), dtype=np.uint8)
        base = cv2.GaussianBlur(base, (5, 5), 0)
        H, W = base.shape[:2]
        state = {"shift": 0.0}

        ex, task, logs = make_task(frames=100)

        def grab():
            M = np.float32([[1, 0, state["shift"]], [0, 1, 0]])
            return cv2.warpAffine(base, M, (W, H),
                                  borderMode=cv2.BORDER_REPLICATE)

        def send(key, seconds):
            state["shift"] += seconds / 0.0012

        ex._grab = grab
        task.send_key = send
        stats = ex.run()
        self.assertNotIn("calibration_failed", stats)
        self.assertIn("px_per_turn_sec", stats, "该把标定值记进统计")
        self.assertGreater(stats["px_per_turn_sec"], 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
