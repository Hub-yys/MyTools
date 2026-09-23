"""「开始」步准备动作（开背包 + 探测）的单元测试（假窗口 + 假 OCR）。

    python tests/test_echo_prep.py

验证的是：
* 已校准的步骤真的按了键 / 点了位置，且**点的相对坐标换算正确**（区域 → 整帧）；
* 没校准的步骤**一个都不点**（这是安全底线：不确定的坐标绝不落地）；
* 探测把「截图 + 每行文字的相对/像素坐标」落盘，格式能被校准直接使用；
* 窗口找不到 / 外部叫停时行为明确。

验证不了的是真实游戏里那些按钮到底在哪 —— 那要靠探测结果校准，见 prepare.py 顶部。
"""

from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.tools.game.echo_enhance.controller import WindowNotFound  # noqa: E402
from src.tools.game.echo_enhance.prepare import (  # noqa: E402
    PREP_STEPS,
    EchoPrep,
    PrepAction,
)
from src.tools.game.echo_enhance.reader import OcrLine  # noqa: E402

FRAME_H, FRAME_W = 1080, 1920


class FakeWindow:
    """假游戏窗口：记录按键/点击，画面给一张黑图。"""

    def __init__(self, found: bool = True):
        self.keys: list[str] = []
        self.clicks: list[tuple[float, float]] = []
        self._found = found

    def find(self):
        return 12345 if self._found else None

    def describe(self):
        return "FakeWindow"

    def bring_to_front(self):
        pass

    def grab(self):
        return np.zeros((FRAME_H, FRAME_W, 3), dtype=np.uint8)

    def press(self, key, after_sleep=0.3):
        self.keys.append(key)

    def click(self, x, y, after_sleep=0.3):
        self.clicks.append((x, y))


class FakeReader:
    """假 OCR：返回预先摆好的行（坐标是**裁剪图内**的像素坐标）。"""

    def __init__(self, lines: list[OcrLine] | None = None):
        self.lines = lines or []
        self.calls = 0

    def ocr_lines(self, frame):
        self.calls += 1
        return list(self.lines)


def line(text: str, x: float, y: float, w: float = 100.0, h: float = 40.0) -> OcrLine:
    return OcrLine(text=text, score=0.99, x=x, y=y, width=w, height=h)


class TestPrepSteps(unittest.TestCase):
    def test_default_table_has_only_bag_opening_calibrated(self):
        """安全底线：除了"按 B"，其它步骤都还没校准、不会真去点。"""
        verified = [s.label for s in PREP_STEPS if s.verified]
        self.assertEqual(verified, ["打开背包"])
        self.assertTrue(all(s.kind == "click_text" for s in PREP_STEPS[1:]))
        self.assertFalse(any(s.text == "" for s in PREP_STEPS[1:]))


class TestPrepRun(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.probe_dir = pathlib.Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_unverified_steps_are_skipped_not_clicked(self):
        window = FakeWindow()
        prep = EchoPrep(window=window, reader=FakeReader([]), probe_dir=self.probe_dir)
        result = prep.run()

        self.assertEqual(window.keys, ["b"], "只应该按了一次 B")
        self.assertEqual(window.clicks, [], "未校准的步骤一个都不许点")
        self.assertIsNotNone(result)
        self.assertEqual(len(result.pending), len(PREP_STEPS) - 1)

    def test_all_verified_runs_through_without_probe(self):
        window = FakeWindow()
        steps = (
            PrepAction("press", "打开背包", key="b", verified=True, wait=0.0),
        )
        prep = EchoPrep(window=window, reader=FakeReader([]), probe_dir=self.probe_dir,
                        steps=steps)
        self.assertIsNone(prep.run(), "全校准好了就不该再出探测产物")
        self.assertEqual(window.keys, ["b"])
        self.assertEqual(list(self.probe_dir.iterdir()), [])

    def test_clicked_coordinates_are_converted_from_region(self):
        """区域 (0.5,0.5,1.0,1.0) 里的一行 → 点它的中心，坐标要换算回整帧。

        裁剪图 960x540，行在裁剪图里的 (300,200,100,40)：
            相对 x = 0.5 + 300/960*0.5 = 0.65625，宽 = 100/960*0.5 = 0.052083
        所以点中心 = 0.682292；y 同理 = 0.703704。
        """
        window = FakeWindow()
        reader = FakeReader([line("声骸", 300, 200, 100, 40)])
        steps = (
            PrepAction("click_text", "切到声骸页签", region=(0.5, 0.5, 1.0, 1.0),
                       text="声骸", verified=True, wait=0.0),
        )
        prep = EchoPrep(window=window, reader=reader, probe_dir=self.probe_dir, steps=steps)
        self.assertIsNone(prep.run())
        self.assertEqual(len(window.clicks), 1)
        x, y = window.clicks[0]
        self.assertAlmostEqual(x, 0.682292, places=5)
        self.assertAlmostEqual(y, 0.703704, places=5)

    def test_missing_text_raises_instead_of_clicking_blind(self):
        window = FakeWindow()
        steps = (
            PrepAction("click_text", "切到声骸页签", region=(0.5, 0.5, 1.0, 1.0),
                       text="声骸", verified=True, wait=0.0),
        )
        prep = EchoPrep(window=window, reader=FakeReader([line("武器", 300, 200)]),
                        probe_dir=self.probe_dir, steps=steps)
        with self.assertRaises(RuntimeError) as ctx:
            prep.run()
        self.assertIn("没找到文字", str(ctx.exception))
        self.assertEqual(window.clicks, [], "找不到就绝不能乱点")

    def test_window_not_found(self):
        prep = EchoPrep(window=FakeWindow(found=False), reader=FakeReader([]),
                        probe_dir=self.probe_dir)
        with self.assertRaises(WindowNotFound):
            prep.run()

    def test_stop_request_aborts(self):
        prep = EchoPrep(window=FakeWindow(), reader=FakeReader([]),
                        probe_dir=self.probe_dir, should_stop=lambda: True)
        with self.assertRaises(RuntimeError) as ctx:
            prep.run()
        self.assertIn("已停止", str(ctx.exception))


class TestProbeOutput(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.probe_dir = pathlib.Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _probe(self, lines):
        logs: list[str] = []
        prep = EchoPrep(window=FakeWindow(), reader=FakeReader(lines),
                        probe_dir=self.probe_dir, log=logs.append, force_probe=True)
        return prep, prep.run(), logs

    def test_writes_png_and_txt(self):
        prep, result, logs = self._probe([line("声骸", 100, 200), line("筛选", 1500, 60)])
        self.assertTrue(result.png_path.exists())
        self.assertTrue(result.txt_path.exists())
        self.assertGreater(result.png_path.stat().st_size, 1000, "截图不该是空文件")
        self.assertEqual(result.lines, 2)
        self.assertTrue(any("探测" in line for line in logs))

    def test_txt_has_relative_and_pixel_coordinates(self):
        prep, result, _logs = self._probe([line("声骸", 960, 540, 96, 54)])
        text = result.txt_path.read_text(encoding="utf-8")
        lines = text.splitlines()
        self.assertIn("窗口 1920x1080", lines[0])
        # 第 3 行是第 1 条文字：相对 0.5,0.5,0.05,0.05 / 像素 960,540,96,54
        row = lines[2]
        self.assertIn("声骸", row)
        self.assertIn("0.5000,0.5000,0.0500,0.0500", row)
        self.assertIn("960,540,96,54", row)

    def test_lines_sorted_top_to_bottom(self):
        prep, result, _logs = self._probe([
            line("下面", 100, 900),
            line("上面", 100, 100),
        ])
        rows = result.txt_path.read_text(encoding="utf-8").splitlines()[2:]
        self.assertIn("上面", rows[0])
        self.assertIn("下面", rows[1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
