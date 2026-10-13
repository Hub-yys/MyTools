# -*- coding: utf-8 -*-
"""提示区读取的单元测试（**假 OCR，不碰真视频**）。

## 这里钉的是什么

真实验收（``check_explore_gap_ocr_live.py``）用的是真视频 + 真 OCR，
但那要几十秒、还要模型。这批测试用**假 OCR** 钉住**判定规则**：

* 多比例投票：单比例会漏按键图标 → 必须有兜底
* 只有动作词、没有键名 → **不许猜**（猜错会按 ESC 打开暂停菜单）
* OCR 抛异常 / 返回怪形状 → 不炸、不瞎编

## ★ 为什么要测"多比例"

实测（同一帧，8 个缩放）::

    1.0 → 'F （长按）离开心钥井'   ← 有 F
    2.0 → '宁（长按）离开心钥井'   ← **丢了 F**（我原来拍的常数）
    3.0 → '（长按）离开心钥井'     ← 丢了 F
    4.0 → 'F （长按）离开心钥井'   ← 有 F

单比例读不到 F 时，只剩"离开"（动作词），解析层会拒绝猜 →
**一个按键都学不到**。多比例投票就是为了兜住这个。
"""

from __future__ import annotations

import pathlib
import sys
import unittest

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.core.explore_gap.reader import (  # noqa: E402
    OCR_SCALES,
    PROMPT_REGION,
    crop_prompt,
    learn_from_ocr,
    prompt_score,
    read_prompt_text,
)


def fake_prompt_image(h=720, w=1280):
    """造一张"提示区有条"的假帧（暗底 + 亮字）。"""
    img = np.zeros((h, w, 3), dtype=np.uint8)
    x0, y0, x1, y1 = PROMPT_REGION
    py0, py1 = int(h * y0), int(h * y1)
    px0, px1 = int(w * x0), int(w * x1)
    img[py0:py1, px0:px1] = 20          #: 暗底
    #: 中间来一条亮的（像文字）
    img[py0 + 20:py1 - 20, px0 + 40:px1 - 40] = 230
    return img


class TestPromptScore(unittest.TestCase):
    def test_prompt_image_scores(self):
        img = fake_prompt_image()
        roi = crop_prompt(img)
        self.assertGreater(prompt_score(roi), 0.02)

    def test_plain_scene_scores_low(self):
        """全灰的画面（没有暗底+亮字）→ 不该像提示条。"""
        img = np.full((720, 1280, 3), 120, dtype=np.uint8)
        self.assertLess(prompt_score(crop_prompt(img)), 0.02)

    def test_none_and_empty(self):
        self.assertEqual(prompt_score(None), 0.0)
        self.assertEqual(prompt_score(np.zeros((0, 0, 3), dtype=np.uint8)),
                         0.0)

    def test_crop_none(self):
        self.assertIsNone(crop_prompt(None))


class TestMultiScale(unittest.TestCase):
    """★ 多比例投票 —— 单比例会漏按键图标。

    ⚠ 判据是"**谁的信息量大**"，不是"第一个非空"。
    第一个非空很可能拿到"只有动作词"的那条，而那按不了键。
    """

    def test_prefers_text_with_key(self):
        """★ 有键名的结果必须赢过只有动作词的。"""
        roi = fake_prompt_image()
        base_h = roi.shape[0]

        def ocr_by_scale(img):
            #: 模拟实测的比例依赖：放大到 2 倍读不到那个按键图标。
            #: ⚠ 判据按**相对**倍数算（``base_h``），不是绝对像素 ——
            #: 第一版写死 200px，而这张假图本来就不高，
            #: 所有比例都 < 200 → 全都返回"有 F"，测不出东西。
            ratio = img.shape[0] / base_h
            if abs(ratio - 2.0) < 0.1:
                return "宁（长按）离开心钥井"          #: 丢了 F
            return "F （长按）离开心钥井"              #: 有 F

        got = read_prompt_text(roi, ocr_by_scale, scales=(2.0, 1.0))
        self.assertIn("F", got, f"该挑出带键名的那条，实际 {got!r}")

    def test_stops_early_once_key_found(self):
        """已经拿到带键名的结果就不再试（OCR 很贵）。"""
        roi = fake_prompt_image()
        calls = []

        def ocr(img):
            calls.append(img.shape[0])
            return "F 对话"

        read_prompt_text(roi, ocr, scales=(1.0, 2.0, 4.0))
        self.assertEqual(len(calls), 1, f"该第一次就收手，实际 {calls}")

    def test_keeps_trying_when_no_key(self):
        """读到的都没键名 → 继续试后面的比例。"""
        roi = fake_prompt_image()
        calls = []

        def ocr(img):
            calls.append(img.shape[0])
            return "宁（长按）离开心钥井"        #: 只有动作词

        read_prompt_text(roi, ocr, scales=(1.0, 2.0, 4.0))
        self.assertEqual(len(calls), 3, "该把所有比例都试一遍")

    def test_ocr_exception_does_not_kill_frame(self):
        """某个比例抛异常 → 试下一个，不该让整帧白掉。"""
        roi = fake_prompt_image()
        state = {"n": 0}

        def ocr(img):
            state["n"] += 1
            if state["n"] == 1:
                raise RuntimeError("假 OCR 炸了")
            return "F 对话"

        got = read_prompt_text(roi, ocr, scales=(1.0, 2.0))
        self.assertIn("F", got, "第二次该救回来")

    def test_all_fail_returns_empty(self):
        got = read_prompt_text(fake_prompt_image(),
                               lambda img: "", scales=(1.0, 2.0))
        self.assertEqual(got, "")

    def test_all_raise_returns_empty(self):
        def boom(img):
            raise RuntimeError("x")

        self.assertEqual(read_prompt_text(fake_prompt_image(), boom,
                                          scales=(1.0, 2.0)), "")

    def test_none_result_handled(self):
        self.assertEqual(read_prompt_text(fake_prompt_image(),
                                          lambda img: None,
                                          scales=(1.0,)), "")

    def test_scales_constant_sane(self):
        self.assertTrue(OCR_SCALES)
        self.assertEqual(list(OCR_SCALES), sorted(set(OCR_SCALES),
                                                  key=OCR_SCALES.index),
                         "不该有重复比例")
        #: ⚠ 2.0 是实测最差的那个，不该排第一
        self.assertNotEqual(OCR_SCALES[0], 2.0,
                            "2.0 是实测读不到按键图标的比例，别排第一")


class TestLearnFromOcr(unittest.TestCase):
    """``learn_from_ocr`` 是建库时每帧调的钩子。"""

    def test_returns_none_on_plain_scene(self):
        """画面不像有提示条 → **不该调 OCR**（省时间）。"""
        learner = learn_from_ocr(lambda img: "F 对话")
        calls = []

        def ocr(img):
            calls.append(1)
            return "F 对话"

        learner = learn_from_ocr(ocr)
        plain = np.full((720, 1280, 3), 120, dtype=np.uint8)
        self.assertIsNone(learner(0, plain))
        self.assertEqual(calls, [], "不像提示条的帧不该浪费 OCR")

    def test_reads_prompt_frame(self):
        learner = learn_from_ocr(lambda img: "F 对话")
        self.assertEqual(learner(0, fake_prompt_image()), "F 对话")

    def test_ocr_failure_returns_none(self):
        def boom(img):
            raise RuntimeError("x")

        learner = learn_from_ocr(boom)
        self.assertIsNone(learner(0, fake_prompt_image()))

    def test_empty_ocr_returns_none(self):
        learner = learn_from_ocr(lambda img: "")
        self.assertIsNone(learner(0, fake_prompt_image()))

    def test_does_not_raise_on_weird_frame(self):
        """怪形状的帧 → 返回 None，不炸（建库不能因此失败）。"""
        learner = learn_from_ocr(lambda img: "F 对话")
        for bad in (np.zeros((0, 0, 3), dtype=np.uint8),
                    np.zeros((5, 5, 3), dtype=np.uint8),
                    np.zeros((720, 1280), dtype=np.uint8)):
            with self.subTest(shape=bad.shape):
                learner(0, bad)               #: 只要不抛就行


if __name__ == "__main__":
    unittest.main(verbosity=2)
