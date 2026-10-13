# -*- coding: utf-8 -*-
"""★ 用**真视频**验证「查缺补漏」全链路（走生产代码，不是原型脚本）。

## 为什么要两种模式分开测

连续性约束（``Locator``）**假设喂进来的是相邻帧**。所以必须分清::

    冷启动模式   每帧都 reseat(None) → 全库搜
                 对应：刚打开工具、找起点、跟丢后重定位
                 代价：没有连续性保护

    顺序模式     按视频顺序连帧喂，让它自己维持 near
                 对应：**真实跑路线时**（每帧间隔 ~0.1 秒）
                 收益：连续性 + 余量双重把关，危险格归零

⚠ 第一版这个脚本把**随机锚点**当顺序帧喂了 —— 连续性自然全部失效
（上一个锚点在 10 分钟处、下一个在 20 分钟处），可用率掉到 10%。
那不是代码的锅，是**测试喂错了序列**。真实运行永远是顺序的。

## 判据（事先写死，且用实测值）

冷启动模式（全库搜，无连续性保护）::

    ±2 参考帧命中  >= 65%     原型"100%"是自比对的假结论；
                              诚实值是 70~80%，够用（每帧都重测，偶尔错一帧不影响）
    ±5 参考帧命中  >= 70%

顺序模式（真实工况）::

    定位跑飞率     == 0        ★ 连续性必须完全防住"跳几分钟"
    误纠偏         == 0        ★ 定位跑飞还给出纠偏 = 会朝错方向走
    可用率         >= 60%
    闸门内残差最大 <= 3px

没装 cv2 / 没视频时**跳过**（环境问题，不是代码问题）。
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))) or ".")
sys.stdout.reconfigure(encoding="utf-8")

import numpy as np                                   # noqa: E402

VIDEO = r"D:\DeepSeek Work\_vid\p4.mp4"
LIB = r"D:\DeepSeek Work\_vid\_mytools_reflib.npz"

#: 「不可接受」的定位误差（参考帧）。>5 帧 = >2.5 秒 = 画面上已是另一个地方
BAD_ERR = 5
#: 「跑飞」= 误差大到离谱（>20 参考帧 = >10 秒）
FLY_ERR = 20

FAILURES: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


def main() -> int:
    try:
        import cv2
    except Exception as exc:                         # noqa: BLE001
        print(f"没装 cv2（{exc}）—— 跳过")
        return 0
    if not os.path.isfile(VIDEO):
        print(f"没找到测试视频 {VIDEO} —— 跳过")
        return 0

    from src.core.explore_gap import (
        Locator,
        build_library,
        load_library,
        save_library,
    )
    from src.core.explore_gap.library import library_shape_ok

    print("=" * 76)
    print("① 建库 / 存盘 / 读回（真视频）")
    print("=" * 76)
    if os.path.isfile(LIB):
        lib = load_library(LIB)
        print(f"  复用已建好的库：{len(lib)} 帧")
        check(library_shape_ok(lib), "库结构自洽")
    else:
        t0 = time.time()
        lib = build_library(VIDEO)
        print(f"  参考帧 {len(lib)} 个，用时 {time.time()-t0:.0f} 秒")
        check(library_shape_ok(lib), "库结构自洽")
        save_library(lib, LIB)
    print(f"  覆盖时长 ≈ {len(lib)*lib.step/lib.fps/60:.1f} 分钟")

    cap = cv2.VideoCapture(VIDEO)
    N = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()

    # ══════════════════════════════════════════ ② 冷启动模式
    print()
    print("=" * 76)
    print("② 冷启动模式（每帧 reseat(None) → 全库搜，无连续性保护）")
    print("=" * 76)
    loc = Locator(lib)
    rng = np.random.default_rng(20261011)
    picks = np.sort(rng.choice(len(lib) - 1, size=150, replace=False))
    want = {int(lib.frames[i]) + 7: i for i in picks
            if int(lib.frames[i]) + 7 < N}

    cap = cv2.VideoCapture(VIDEO)
    errs, margins = [], []
    cur = 0
    while want:
        ok, fr = cap.read()
        if not ok:
            break
        if cur in want:
            ti = want.pop(cur)
            loc.reseat(None)                         #: ★ 冷启动：不假设上一帧
            got = loc.locate(fr)
            if got is not None:
                idx, sim, margin = got
                errs.append(abs(idx - ti))
                margins.append(margin)
        cur += 1
    cap.release()

    if errs:
        E = np.array(errs)
        within2 = 100 * float((E <= 2).mean())
        within5 = 100 * float((E <= 5).mean())
        flew = 100 * float((E > FLY_ERR).mean())
        print(f"  样本 {len(E)} 个（查询帧 = 参考帧 +7，不在库里）")
        print(f"  命中 ±2: {within2:.1f}%   ±5: {within5:.1f}%   "
              f"跑飞(>{FLY_ERR}): {flew:.1f}%")
        print(f"  误差 中位 {np.median(E):.0f}  最大 {E.max():.0f} 参考帧")
        print(f"  余量 中位 {np.median(margins):.3f}  最小 {min(margins):.3f}")
        check(within2 >= 65.0, f"冷启动 ±2 命中 ≥ 65%（实测 {within2:.1f}%）")
        check(within5 >= 70.0, f"冷启动 ±5 命中 ≥ 70%（实测 {within5:.1f}%）")
    else:
        check(False, "冷启动没采到样本")

    # ══════════════════════════════════════════ ③ 顺序模式（真实工况）
    print()
    print("=" * 76)
    print("③ ★ 顺序模式（真实工况：按视频顺序连帧喂，连续性生效）")
    print("=" * 76)
    loc = Locator(lib)
    cap = cv2.VideoCapture(VIDEO)
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))

    #: 取一段连续视频，注入已知的**逐步漂移**（模拟玩家逐渐偏航），
    #: 看控制器能不能靠测量把画面拉回来。
    start = int(lib.frames[len(lib) // 4])
    seq = []
    cap.set(cv2.CAP_PROP_POS_FRAMES, start)
    for k in range(120):
        ok, fr = cap.read()
        if not ok:
            break
        #: 人为偏航：绕一圈 0→60→0 度（像素级）
        S = 60.0 * abs(np.sin(k / 40.0 * np.pi))
        M = np.float32([[1, 0, S], [0, 1, 0]])
        seq.append((k, S, cv2.warpAffine(fr, M, (W, H),
                                         borderMode=cv2.BORDER_REPLICATE)))
    cap.release()
    print(f"  连续 {len(seq)} 帧，注入偏航 0~60px（周期性）")

    loc.reseat(None)                                 #: 冷启动一次找到起点
    rows = []
    for k, S, fr in seq:
        fx = loc.measure(fr)
        rows.append((k, S, fx))

    located = [r for r in rows if r[2] is not None]
    trusted = [r for r in located if r[2].trusted]
    #: 定位合理 = 相对起点没跳太远（这一段本来就是连续行走）
    runaway = [r for r in trusted
               if r[2].index < 0
               or abs(r[2].index - int(np.where(lib.frames == start)[0][0])) > 200]
    #: 误纠偏 = 可信测量、但给出的 dx 与注入值差得远
    wrong = [r for r in trusted if abs(r[2].dx - r[1]) > 20]

    print(f"  定位上 {len(located)}/{len(rows)}   过闸门 {len(trusted)}/{len(rows)}"
          f"  → 可用率 {100*len(trusted)/max(len(rows),1):.0f}%")
    if trusted:
        resid = [abs(r[2].dx - r[1]) for r in trusted]
        print(f"  dx 误差：中位 {np.median(resid):.1f}px  90分位 "
              f"{np.percentile(resid, 90):.1f}px  最大 {max(resid):.1f}px")
    print(f"  定位跑飞 {len(runaway)}   误纠偏 {len(wrong)}")

    check(len(runaway) == 0, f"顺序模式定位跑飞 = 0（实测 {len(runaway)}）")
    check(len(wrong) == 0, f"顺序模式误纠偏 = 0（实测 {len(wrong)}）")
    check(100 * len(trusted) / max(len(rows), 1) >= 60.0,
          f"顺序模式可用率 ≥ 60%（实测 {100*len(trusted)/max(len(rows),1):.0f}%）")

    # ══════════════════════════════════════════ ④ 闭环残差
    print()
    print("=" * 76)
    print("④ 闭环残差（按 -dx 撤销后还剩多少）")
    print("=" * 76)
    cap = cv2.VideoCapture(VIDEO)
    residuals = []
    for k, S, fr in seq[::6]:
        if k >= len(seq):
            continue
        _, _, fx = seq[k]
        if fx is None:
            continue
        loc.reseat(None)
        m = loc.measure(fx)
        if m is None or not m.trusted:
            continue
        ref = lib.frame_image(m.index)
        if ref is None:
            continue
        M2 = np.float32([[1, 0, -m.dx], [0, 1, -m.dy]])
        fixed = cv2.warpAffine(fx, M2, (W, H), borderMode=cv2.BORDER_REPLICATE)
        after = loc.phase_shift(ref, fixed)
        if after is not None:
            residuals.append(float(np.hypot(after[0], after[1])))
    cap.release()

    if residuals:
        arr = np.array(residuals)
        print(f"  样本 {len(arr)}   中位 {np.median(arr):.3f}px   "
              f"90分位 {np.percentile(arr,90):.3f}px   最大 {arr.max():.3f}px")
        check(float(arr.max()) <= 3.0,
              f"闭环残差全部 ≤ 3px（最大 {arr.max():.3f}px）")
    else:
        check(False, "没采到残差样本")

    print()
    print("=" * 76)
    if FAILURES:
        print(f"结论：**{len(FAILURES)} 项不通过**")
        for f in FAILURES:
            print("  ✗", f)
        return 1
    print("结论：全链路通过 —— 生产代码复现并**加固**了原型结论")
    print("=" * 76)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
