# ⚠ LEGACY（2026-09-23）：本模块属于 MyTools **自写**的声骸强化实现，已不是主路径。
# 强化流程现在整段走 ok-ww 引擎（echo_enhance/okww_task.py + auto_combat/okww_boot.py），
# 判定条件走 echo_enhance/stats.py。保留它只是因为还有测试覆盖它；
# **不要在新代码里引用**，也不要照着它改流程。
"""从游戏画面读声骸词条。

职责边界：**只负责"图 → 词条列表"**，不碰键鼠、不碰判定。
截图由 :mod:`controller` 提供，判定交给 :mod:`stats`。

做法参照 ok-ww：在声骸面板的固定相对区域里跑 OCR，然后把
「属性名」和「数值」按纵坐标就近配对。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np

from .stats import ALL_STATS, EchoStat, normalize_stat_name, parse_value

#: 声骸面板里 5 条副属性所在的相对区域 (x1, y1, x2, y2)，取值 0~1。
#: 数值参照 ok-ww 的 `self.ocr(0.09, 0.3, 0.40, 0.53)`，必要时在界面上可调。
DEFAULT_STATS_REGION = (0.09, 0.30, 0.40, 0.53)

#: 属性名至少是 2 个连续汉字
_CJK_RE = re.compile(r"[\u4e00-\u9fff]{2,}")

#: 纯数值行：数字、小数点、百分号（含全角）
_NUMBER_LINE_RE = re.compile(r"^[\d.%％\s+-]+$")


@dataclass(frozen=True)
class OcrLine:
    """OCR 出来的一行文本。"""

    text: str
    score: float
    x: float
    y: float
    width: float = 0.0
    height: float = 0.0

    @property
    def center_y(self) -> float:
        return self.y + self.height / 2

    def __str__(self) -> str:
        return f"{self.text}({self.score:.2f})"


def parse_ocr_result(result) -> list[OcrLine]:
    """把 onnxocr 的返回值拍平成 :class:`OcrLine` 列表。

    onnxocr 返回形如::

        [[ [ [x1,y1],[x2,y2],[x3,y3],[x4,y4] ], ("文本", 置信度) ], ... ]

    外层是"每张图一项"，内层才是文本行。这里对结构差异做容错，
    免得换个版本就整个崩掉。
    """
    lines: list[OcrLine] = []
    if not result:
        return lines

    pages = result if isinstance(result, (list, tuple)) else [result]
    for page in pages:
        if not page:
            continue
        for item in page:
            try:
                box, payload = item[0], item[1]
                text, score = payload[0], float(payload[1])
            except (TypeError, IndexError, ValueError):
                continue

            try:
                xs = [float(p[0]) for p in box]
                ys = [float(p[1]) for p in box]
            except (TypeError, IndexError, ValueError):
                continue

            lines.append(
                OcrLine(
                    text=str(text).strip(),
                    score=score,
                    x=min(xs),
                    y=min(ys),
                    width=max(xs) - min(xs),
                    height=max(ys) - min(ys),
                )
            )
    return lines


class EchoReader:
    """声骸词条读取器。"""

    def __init__(self, ocr=None, region: tuple[float, float, float, float] | None = None):
        self._ocr = ocr
        self.region = region or DEFAULT_STATS_REGION

    # ---------------------------------------------------------------- OCR
    @property
    def ocr(self):
        """懒加载 OCR 引擎（首次调用会加载模型，约 0.5s）。"""
        if self._ocr is None:
            from onnxocr.onnx_paddleocr import ONNXPaddleOcr

            self._ocr = ONNXPaddleOcr()
        return self._ocr

    def crop_region(self, frame: np.ndarray) -> np.ndarray:
        """按相对坐标裁出属性区域。"""
        h, w = frame.shape[:2]
        x1, y1, x2, y2 = self.region
        return frame[int(y1 * h): int(y2 * h), int(x1 * w): int(x2 * w)]

    def ocr_lines(self, frame: np.ndarray) -> list[OcrLine]:
        """整帧 OCR（不做区域裁剪，交给调用方决定裁哪里）。"""
        return parse_ocr_result(self.ocr.ocr(frame))

    # ---------------------------------------------------------------- 解析
    @staticmethod
    def _is_value_line(text: str) -> bool:
        """像"数值"的行：纯数字/百分号，且至少含一个数字。"""
        stripped = (text or "").strip()
        return bool(stripped) and bool(_NUMBER_LINE_RE.match(stripped)) and any(
            ch.isdigit() for ch in stripped
        )

    @staticmethod
    def _is_stat_line(text: str) -> bool:
        """像"属性名"的行：含至少两个连续汉字。"""
        return bool(_CJK_RE.search(text or ""))

    def pair_lines(self, lines: list[OcrLine]) -> list[EchoStat]:
        """把属性名行和数值行按纵坐标就近配对，产出词条列表。"""
        props = [ln for ln in lines if self._is_stat_line(ln.text)]
        values = [ln for ln in lines if self._is_value_line(ln.text)]

        used: set[int] = set()
        stats: list[EchoStat] = []

        for prop in props:
            best: tuple[float, int, OcrLine] | None = None
            for idx, value in enumerate(values):
                if idx in used:
                    continue
                distance = abs(value.center_y - prop.center_y)
                if best is None or distance < best[0]:
                    best = (distance, idx, value)
            if best is None:
                continue

            used.add(best[1])
            value_line = best[2]

            name = normalize_stat_name(prop.text, value_line.text)
            value = parse_value(value_line.text)
            if name is None or value is None:
                continue
            if name not in ALL_STATS:
                continue

            stats.append(EchoStat(name, value))

        return stats

    def read_stats(
        self, frame: np.ndarray
    ) -> tuple[list[EchoStat], list[OcrLine]]:
        """读一帧画面，返回 ``(词条列表, 原始 OCR 行)``。

        原始行一并返回，方便界面把"OCR 到底看到了什么"打出来排查。
        """
        cropped = self.crop_region(frame)
        lines = self.ocr_lines(cropped)
        return self.pair_lines(lines), lines
