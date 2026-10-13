# -*- coding: utf-8 -*-
"""★ WGC 抓帧的**回调契约**测试 —— 不依赖游戏、不依赖真窗口。

## 这个测试钉什么

`tests/check_explore_gap_game.py` 的抓图回调有两条**必须遵守**的契约，
违反了就"一帧都抓不到"，而且**报错很容易被吞掉**：

  ① 处理前必须拿到**独立拷贝**（``np.asarray(buf).copy()``）
  ② 拷贝必须发生在**回调内部** —— 回调返回后缓冲会被复用

## ⚠ 诚实说明：这个测试**没能**复现原始报错

真机实测到的原始报错是::

    ValueError: ndarray is not C-contiguous

它来自我第一版的 ``np.frombuffer(buf, ...).reshape(h, w, 4)``。
我试了列切片 / 行切片 / 转置 / F-order / as_strided 五种构造，
**都没能让 cv2.cvtColor 或 reshape 抛出同样的错** ——
所以那个错的确切触发条件**还没查明**（需要真窗口才能复现，
见 ``_probe/buf_probe.py``）。

**因此这个测试不去假装复现它**，只钉住两件我能确定的事：
  * 拷贝后的结果**与源缓冲解耦**（契约②，可确定性验证）
  * 回调异常**被收集**而不是静默吞掉（这条是那次踩坑的真正教训）
"""

from __future__ import annotations

import pathlib
import sys
import unittest

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class FakeFrame:
    """假的 frame —— 模拟 `windows_capture` 回调拿到的对象。

    共享一块底层内存，`mutate()` 用来模拟"库复用了这块缓冲"。
    """

    def __init__(self, w: int = 64, h: int = 48):
        self.width = w
        self.height = h
        self._buf = np.full((h, w, 4), 128, dtype=np.uint8)

    @property
    def frame_buffer(self):
        return self._buf

    def mutate(self, value: int = 255):
        """改底层数据（模拟缓冲被复用/覆盖）。"""
        self._buf[:, :, :] = value


def collect_one(frame, *, convert: bool = True):
    """复刻 `check_explore_gap_game.grab_frames` 的回调核心逻辑。

    :return: ``(结果列表, 错误列表)``
    """
    got, errors = [], []
    try:
        buf = frame.frame_buffer
        if buf is not None:
            arr = np.asarray(buf).copy()          #: ★ 契约① + ②
            if convert:
                import cv2                        # noqa: PLC0415

                got.append(cv2.cvtColor(arr, cv2.COLOR_BGRA2BGR))
            else:
                got.append(arr)
    except Exception as exc:                      # noqa: BLE001
        errors.append(f"{type(exc).__name__}: {exc}")
    return got, errors


class TestFrameBufferContract(unittest.TestCase):
    def test_result_is_independent_copy(self):
        """★ 契约②：回调返回后缓冲会被复用 —— 存下的结果必须不受影响。

        这是**能确定性验证**的那条，也是踩坑时真正伤人的那条：
        不拷贝的话，事后读到的可能是完全别的画面（而且不报错）。
        """
        f = FakeFrame()
        got, errors = collect_one(f, convert=False)
        self.assertEqual(errors, [])
        before = got[0].copy()

        f.mutate(255)                       #: 模拟"库复用了这块内存"

        self.assertTrue(
            np.array_equal(got[0], before),
            "结果跟着原 buffer 变了 —— 没在回调里拷贝")
        self.assertEqual(int(got[0].max()), 128,
                         "值被后面的 mutate 影响了 —— 不是独立拷贝")

    def test_errors_are_collected_not_swallowed(self):
        """★ 回调异常必须被**收集**（不能静默吞）。

        实测教训：第一版写了 ``except Exception: pass``，于是真正的
        报错被吞掉，表现只是"一帧都抓不到"，看起来像"窗口不对"，
        查了很久。所以这条要钉住。
        """
        class Bad:
            width = 64
            height = 48

            @property
            def frame_buffer(self):
                raise RuntimeError("模拟库内部错误")

        got, errors = collect_one(Bad())
        self.assertEqual(got, [])
        self.assertEqual(len(errors), 1)
        self.assertIn("模拟库内部错误", errors[0])

    def test_converted_shape(self):
        """转换后的形状要对（BGRA → BGR）。"""
        f = FakeFrame(w=64, h=48)
        got, errors = collect_one(f)
        self.assertEqual(errors, [])
        self.assertEqual(got[0].shape, (48, 64, 3))

    def test_none_buffer_is_skipped(self):
        """``frame_buffer`` 可能给 None —— 要跳过而不是崩。"""

        class NoBuf:
            width = 64
            height = 48
            frame_buffer = None

        got, errors = collect_one(NoBuf())
        self.assertEqual(got, [])
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
