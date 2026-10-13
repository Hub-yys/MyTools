# -*- coding: utf-8 -*-
"""把 ok-ww 的 OCR 接成"读一行字"的回调。

## 为什么要这一层

项目里已经有 OCR（ok-ww 那套 onnxocr，中文识别验过）。
本模块把"引擎里的 OCR 对象"包成一个**纯函数** ``(图) -> 文字``，
好让 :mod:`src.core.explore_gap`（不依赖 ok-ww 的 core 层）能用它。

## ⚠ 三种环境都要能活

============================  ==========================================
环境                           结果
============================  ==========================================
没装 ok-ww                     ``make_ocr()`` 返回 ``None``
                               → 建库照常，只是**不学按键**
ok-ww 在，但引擎没启动        同上（拿不到 OCR 对象）
引擎已启动                     拿到真 OCR
============================  ==========================================

**绝不抛异常** —— 学不到按键是"功能少一半"，而抛出去会让
**整个建库失败**（连定位都用不了）。这个取舍是刻意的。
"""

from __future__ import annotations

import os
import sys


def _ensure_okww_on_path() -> None:
    """把 vendored ok-ww 挂上 ``sys.path``。"""
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.abspath(os.path.join(here, "..", "..", "..", ".."))
    vendor = os.path.join(root, "vendor", "okww")
    if os.path.isdir(vendor) and vendor not in sys.path:
        sys.path.insert(0, vendor)


def make_ocr():
    """造一个 OCR 回调；拿不到返回 ``None``。

    :return: ``(BGR 图) -> str``，或 ``None``

    ## ★★ 优先**直接构造** onnxocr（不必开游戏）

    项目已经装了 ``onnxocr`` + ``onnxruntime`` + 模型（实测在 venv 里），
    所以**不需要引擎启动**就能 OCR。

    这一点很要紧：**建库本来就是离线活**（用户传个视频、机器扫一遍），
    那时游戏很可能没开、引擎更没起。原来只从引擎全局取 OCR，
    结果就是"建库时永远学不到按键"。

    实测确认（``_vid/probe_ocr2.py``）::

        ONNXPaddleOcr(use_gpu=False)      ← 直接构造，0.5 秒
        读「（长按）离开心钥井」置信度 0.986
        读「F」置信度 0.988

    ## 退路：从引擎全局取

    直接构造失败（没装 onnxocr）时再试引擎全局 ——
    引擎那种情况只在"跑任务时想临时读一块"才用得上。
    """
    direct = _make_direct()
    if direct is not None:
        return direct
    return _make_from_engine()


def _make_direct():
    """直接构造 onnxocr（推荐路径）。失败返回 ``None``。"""
    try:
        from onnxocr.onnx_paddleocr import ONNXPaddleOcr  # noqa: PLC0415
    except Exception:                                # noqa: BLE001
        return None
    for kwargs in ({"use_gpu": False}, {}):
        try:
            engine = ONNXPaddleOcr(**kwargs)
        except Exception:                            # noqa: BLE001
            continue
        fn = getattr(engine, "ocr", None)
        if callable(fn):
            return _wrap(fn)
    return None


def _make_from_engine():
    """从 ok-ww 引擎全局取 OCR（退路）。拿不到返回 ``None``。"""
    _ensure_okww_on_path()
    try:
        from ok import og                        # noqa: PLC0415
    except Exception:                            # noqa: BLE001
        return None

    #: 引擎把 OCR 放在 og.my_app / og.executor 这类全局上。
    #: ⚠ 属性名各版本可能不同，所以逐个试 —— 不写死一个。
    for holder in (getattr(og, "my_app", None),
                   getattr(og, "executor", None),
                   getattr(og, "task_executor", None)):
        if holder is None:
            continue
        ocr = getattr(holder, "ocr", None)
        if ocr is None:
            continue
        fn = getattr(ocr, "ocr", None) or getattr(ocr, "run", None)
        if not callable(fn):
            continue
        return _wrap(fn)
    return None


def _wrap(fn):
    """把引擎的 OCR 调用包成"喂图出字"。

    ⚠ 各版本返回值形状不同（``str`` / ``[(box, text, score)]`` /
    ``(texts, scores)``），这里统一压成一行字符串。
    """
    def read(image) -> str:
        try:
            result = fn(image)
        except Exception:                        # noqa: BLE001
            return ""
        return _as_text(result)
    return read


def _as_text(result) -> str:
    """把 OCR 的各种返回形状压成一行文字。

    ## ★★ 为什么必须**递归**收集（这个 bug 让功能整个失效过）

    onnxocr（本项目实际用的那套）返回的是**三层嵌套**::

        [[[[[386.0, 16.0], [794.0, 16.0], ...], ('（长按）离开心钥井', 0.986)]]]

    结构是 ``[ 页[ 行[ [框], (文字, 置信度) ] ] ]``。

    我第一版只遍历了**一层**（``for item in result: for sub in item``），
    于是 sub 拿到的是``[[框], (文字, 分数)]`` —— 一个 list，
    不是 str，被跳过 → **一个字都读不出来**。

    实测后果：提示区裁得完全正确（存出来的图能肉眼看到
    「（长按）离开心钥井」）、OCR 也确实读出了 98.6% 置信度的文字，
    但解析层把它丢了 —— **按键盘表永远是空的**。

    现在递归收集**所有**字符串。置信度是 float 不是 str，
    所以不会被误收；框坐标也是数字，同理。

    :param result: OCR 的原始返回
    :return: 一行文字（多段用空格连）
    """
    if result is None:
        return ""
    if isinstance(result, str):
        return result

    found: list[str] = []

    def walk(node) -> None:
        if isinstance(node, str):
            if node.strip():
                found.append(node.strip())
            return
        if isinstance(node, (list, tuple)):
            for child in node:
                walk(child)

    walk(result)
    return " ".join(found)
