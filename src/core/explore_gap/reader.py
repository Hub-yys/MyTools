# -*- coding: utf-8 -*-
"""从视频帧里**读出按键提示** —— 这是"学按键"的眼睛。

## 为什么提示区位置是写死的（而不是检测出来的）

实测（``_vid/final.py``，P4 27 分钟视频）::

    提示区 y = 0.50~0.62, x = 0.62~0.98（相对画面）
    有交互提示的时间：193 / 820 采样点 = 23.5%

位置取自**实测**，不是猜的。写死位置换来的是"不必每帧做昂贵的检测" ——
这个脚本要对 3280 个参考帧跑一遍，位置检测的开销受不了。

> ⚠ 不同游戏/不同 UP 主的提示区位置**可能不一样**。
> 所以 :func:`read_prompts` 允许传 ``region`` 覆盖 ——
> 换游戏时先量一次位置。

## ⚠ 为什么优先用 ok-ww 的 OCR，而不是自己训

项目里已经有 ok-ww 那套 OCR（onnxocr，中文识别验过）。
自己再搞一套等于两份实现要维护，而且识别质量不会更好。

⚠ 但本模块**必须能在没有 ok-ww 的环境里被 import**（单测要跑）——
所以 OCR 是**注入**的：:func:`read_prompts` 接受一个 ``ocr`` 回调。
调用方（工具页/任务）负责传真的 OCR 进来。
"""

from __future__ import annotations

from dataclasses import dataclass

#: 提示区（相对画面的比例）—— 实测值，见模块文档
PROMPT_REGION = (0.62, 0.50, 0.98, 0.62)      #: (x0, y0, x1, y1)

#: 提示条判据：既有很暗的底（<60）、也有很亮的字（>190）才算"有条"
#: （实测这套判据能把 23.5% 的提示时间挑出来）
DARK_MAX = 60
BRIGHT_MIN = 190
#: 两者都要占这么多比例才算有提示
MIN_RATIO = 0.02

#: 裁出来的提示条放大多少倍再喂 OCR。
#:
#: ## ★★ 不要只用一个缩放（实测教训）
#:
#: 提示条上的**按键图标**（那个方框里的 ``F``）是个**图形**，
#: OCR 对它的识别**强烈依赖缩放比例**。实测（同一帧，8 个比例）::
#:
#:     缩放    尺寸         读到的文字
#:     1.0    (86, 461)    'F （长按）离开心钥井'   ← 有 F
#:     1.5    (129, 692)   'F （长按）离开心钥井'   ← 有 F
#:     **2.0  (172, 922)   '宁（长按）离开心钥井'   ← 丢了 F**
#:     2.5    (215, 1152)  'F （长按）离开心钥井'   ← 有 F
#:     3.0    (258, 1383)  '（长按）离开心钥井'     ← 丢了 F
#:     4.0    (344, 1844)  'F （长按）离开心钥井'   ← 有 F
#:     0.75   (64, 346)    'F （长按）离开心钥井'   ← 有 F
#:     0.5    (43, 230)    ''                       ← 太小
#:
#: 我原来拍的常数正好是 **2.0** —— 恰好落在读不到 F 的那个区间。
#: 后果很严重：没有 F 就只剩「（长按）离开心钥井」，
#: 而"离开"是**动作**不是键名，于是解析层（正确地）拒绝猜 →
#: **一个按键都学不到**，整个功能白做。
#:
#: → 所以改成**多比例尝试**（见 :data:`OCR_SCALES`），
#:   哪个读出了键名就用哪个。多花几次 OCR，但这是建库时的
#:   一次性开销，而且**读不到键就什么都做不了**。
OCR_ZOOM = 2.0

#: 依次尝试的缩放比例（按"实测成功率"排）。
#:
#: ⚠ ``2.0`` 刻意**不放第一个** —— 它是实测最差的那个。
OCR_SCALES = (1.0, 1.5, 2.5, 4.0, 2.0)


@dataclass(frozen=True)
class PromptObservation:
    """某一帧上读到的提示。"""

    index: int
    #: 读出来的文字（没读到就是空串）
    text: str
    #: 提示条的"明显程度"（0~1）—— 太低就别浪费 OCR
    score: float


def crop_prompt(frame, region=PROMPT_REGION):
    """裁出提示区（返回 BGR 图；裁不出来返回 ``None``）。"""
    if frame is None:
        return None
    h, w = frame.shape[:2]
    x0 = int(w * region[0])
    y0 = int(h * region[1])
    x1 = int(w * region[2])
    y1 = int(h * region[3])
    if x1 <= x0 or y1 <= y0:
        return None
    return frame[y0:y1, x0:x1]


def prompt_score(roi) -> float:
    """这个区域"像不像有提示条"。

    :return: 0~1；越大越像。用的是实测判据（暗底 + 亮字都够多）

    ⚠ 只吃**彩色（3/4 通道）** 图。灰度图 / 单通道图直接返回 0 ——
    不是"不想支持"，而是 ``cvtColor(BGR2GRAY)`` 对单通道图会**抛
    cv2.error**（实测），而建库是对用户上传的视频跑的，
    帧格式不保证 —— 让一个格式问题把整个建库炸掉不值得。
    """
    if roi is None or getattr(roi, "size", 0) == 0:
        return 0.0
    if getattr(roi, "ndim", 0) != 3 or roi.shape[2] not in (3, 4):
        return 0.0
    import cv2                                       # noqa: PLC0415

    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    dark = float((gray < DARK_MAX).mean())
    bright = float((gray > BRIGHT_MIN).mean())
    return min(dark, bright)


def _zoom(roi, scale: float = OCR_ZOOM):
    """按给定比例放大（小字识别率差）。"""
    import cv2                                       # noqa: PLC0415

    if scale == 1.0:
        return roi
    return cv2.resize(roi, None, fx=scale, fy=scale,
                      interpolation=cv2.INTER_CUBIC)


def read_prompt_text(roi, ocr, *, scales=OCR_SCALES):
    """★ 多比例读同一个提示条，返回**最有信息量**的那个结果。

    :param roi: 提示区图（已裁好）
    :param ocr: ``(BGR 图) -> str``
    :param scales: 依次尝试的缩放

    :return: 读到的文字（都不行就空串）

    ## ★ 为什么"最有信息量"而不是"第一个非空"

    提示条上的**按键图标**是个图形，OCR 对它的识别依赖缩放
    （实测 1.0/1.5/2.5/4.0 能读出 ``F``，2.0 和 3.0 读不出 —— 见
    :data:`OCR_SCALES`）。所以同一个提示条，不同缩放的输出是::

        'F （长按）离开心钥井'     ← 有键名，**有用**
        '宁（长按）离开心钥井'     ← 没键名，按不了

    第一个非空就返回的话，很可能拿到没键名的那条 —— 那等于白读。

    **打分规则**：含大写单字母 / 中文键名的得分高。
    这样"读到 F"的结果总能赢过"只读到动作描述"的结果。

    ⚠ 一个缩放读失败（异常 / 空）就试下一个 —— 不让一次失败毁掉整帧。
    """
    best = ""
    best_score = -1
    for scale in scales:
        try:
            text = str(ocr(_zoom(roi, scale)) or "").strip()
        except Exception:                            # noqa: BLE001
            continue
        if not text:
            continue
        score = _info_score(text)
        if score > best_score:
            best, best_score = text, score
        #: 已经拿到"有键名"的了 —— 不必再试（省 OCR 时间）
        if score >= 2:
            break
    return best


def _info_score(text: str) -> int:
    """这段 OCR 文字有多少"能用来按键"的信息量。

    :return: ``2`` = 有明确的键名；``1`` = 只有动作词；``0`` = 都没有
    """
    from .keys import KEY_ALIASES, _LETTER, _looks_like_prompt  # noqa: PLC0415

    if not _looks_like_prompt(text):
        return 0
    if _LETTER.search(text):
        return 2
    if any(k in text for k in KEY_ALIASES if not k.isascii()):
        return 2
    return 1


def learn_from_ocr(ocr, *, region=PROMPT_REGION,
                   min_score: float = MIN_RATIO):
    """把"单帧 OCR 回调"包成 :func:`~.library.build_library` 要的 ``learn_keys``。

    :param ocr: ``(BGR 图) -> str``
    :param region: 提示区比例
    :param min_score: 低于它就不 OCR（省时间）

    :return: ``learn_keys(index, frame) -> str | None``

    ## 为什么要有这个函数（而不是在调用方手写闭包）

    这个闭包里有**两个容易漏的细节**，写在两处迟早不一致：

    ① **先判"像不像有提示条"再 OCR** —— OCR 很贵（实测 27 分钟视频
       有 23.5% 的时间有提示），不判就会对 3280 帧全跑一遍 OCR。
    ② **先放大再 OCR** —— 提示条是小字，实测放大 2 倍识别率明显更好。

    ⚠ 内部异常一律吞掉返回 ``None`` —— 学不到按键是"功能少一半"，
    而抛出去会让**整个建库失败**（连定位都用不了）。
    """
    def learn(index: int, frame):
        roi = crop_prompt(frame, region)
        if prompt_score(roi) < min_score:
            return None
        #: ★ 多比例读（单个缩放会漏掉按键图标 —— 见 OCR_SCALES）
        text = read_prompt_text(roi, ocr)
        return text or None

    return learn


def read_prompts(frames, *, ocr, region=PROMPT_REGION,
                 min_score: float = MIN_RATIO, log=None):
    """扫一遍视频帧，读出每帧的按键提示。

    :param frames: 可迭代的 ``(参考帧下标, BGR 图)``
    :param ocr: **注入的 OCR 回调** ``(BGR 图) -> str``。
        没有 ok-ww 时传一个返回空串的假实现即可。
        ⚠ 只有"看着像有提示条"的帧才会调它 —— OCR 很贵。
    :param region: 提示区比例（换游戏时覆盖）
    :param min_score: 低于它就不 OCR（省时间）
    :param log: 可选日志

    :return: ``[(下标, 文字或 None), ...]`` —— 直接喂给
        :func:`src.core.explore_gap.keys.build_schedule`
    """
    learn = learn_from_ocr(ocr, region=region, min_score=min_score)
    out = []
    scanned = 0
    hit = 0
    for index, frame in frames:
        scanned += 1
        roi = crop_prompt(frame, region)
        if prompt_score(roi) < min_score:
            out.append((index, None))
            continue
        hit += 1
        text = learn(index, frame)
        if text is None and log:
            log(f"第 {index} 帧像有提示条，但 OCR 没读出字")
        out.append((index, text))
    if log:
        pct = 100.0 * hit / scanned if scanned else 0.0
        log(f"扫了 {scanned} 帧，{hit} 帧像有提示条（{pct:.1f}%），"
            f"交给 OCR")
    return out
