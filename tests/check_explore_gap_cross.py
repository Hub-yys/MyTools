# -*- coding: utf-8 -*-
"""★ 跨视频测试（objective ① 要求的"非循环 + 跨视频"）。

## 为什么非要跨视频

在**同一个视频**上建库+查询，测的只是"记得住吗"。
真正要回答的是两件不同的事：

**① 泛化**：库从 A 视频建，能不能认出 A 里**没见过**的帧？
   （非循环 —— 查询帧不在库里）

**② 拒识**：拿 **B 视频**的帧去查 A 的库，会不会**乱认**一个位置？
   这个比 ① 更重要 —— 乱认 = 机器会朝完全错误的方向走。
   正确的行为是"认不出来"（返回 None），而不是"硬给一个答案"。

## 视频关系（实测）

``p1.mp4`` 与 ``head.mp4`` 前 ~1000 帧（片头）相同，之后内容不同；
``p4.mp4`` 是另一段 27 分钟的视频。

所以：
* **A = p1.mp4**（9.6 分钟，独立建库）
* **B = p4.mp4**（27.3 分钟，完全不同的路线）

## 判据（事先写死）

* 泛化：A 的留出帧 ±2 命中 ≥ 65%，且**不限窗口**（冷启动）
* 拒识：B 的帧去查 A 的库，报出位置的**比例要低**，
  而且报出来的那些**不能是"高可信"**的（peak 要低）
  —— 换句话说：**不能自信地认错**

⚠ 这条测试**必须不联网、不开游戏**，纯离线跑。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, r"D:\AI Work\workbuddy\MyTools")
sys.stdout.reconfigure(encoding="utf-8")

import numpy as np                                   # noqa: E402

A_VIDEO = r"D:\DeepSeek Work\_vid\p1.mp4"            #: 建库用
B_VIDEO = r"D:\DeepSeek Work\_vid\p4.mp4"            #: 完全不同的路线
A_LIB = r"D:\DeepSeek Work\_vid\_cross_p1_lib.npz"

if not (os.path.isfile(A_VIDEO) and os.path.isfile(B_VIDEO)):
    print("缺视频 —— 跳过")
    raise SystemExit(0)

import cv2                                           # noqa: E402

from src.core.explore_gap import (                  # noqa: E402
    Locator,
    build_library,
    load_library,
    save_library,
)

FAILURES: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


# ══════════════════════════════════════════ 建 A 的库
print("=" * 76)
print("① 用 p1.mp4 建库（与 p4 完全不同的路线）")
print("=" * 76)
if os.path.isfile(A_LIB):
    lib = load_library(A_LIB)
    print(f"  复用已建好的库：{len(lib)} 帧")
else:
    lib = build_library(A_VIDEO)
    save_library(lib, A_LIB)
    print(f"  建成：{len(lib)} 帧（覆盖 {len(lib)*lib.step/lib.fps/60:.1f} 分钟）")

loc = Locator(lib, peak_min=0.05)
cap = cv2.VideoCapture(A_VIDEO)
NA = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

# ══════════════════════════════════════════ ② 泛化（非循环）
print()
print("=" * 76)
print("② 泛化：A 的**留出帧**（不在库里）能不能定位对")
print("=" * 76)
rng = np.random.default_rng(20261011)
picks = np.sort(rng.choice(len(lib) - 1, size=120, replace=False))
want = {int(lib.frames[i]) + 7: i for i in picks
        if int(lib.frames[i]) + 7 < NA}
errs, margins = [], []
cur = 0
while want:
    ok, fr = cap.read()
    if not ok:
        break
    if cur in want:
        ti = want.pop(cur)
        loc.reseat(None)                       #: 冷启动（不限窗口）
        got = loc.locate(fr)
        if got is not None:
            idx, _sim, margin = got
            errs.append(abs(idx - ti))
            margins.append(margin)
    cur += 1
cap.release()

if errs:
    E = np.array(errs)
    within2 = 100 * float((E <= 2).mean())
    within5 = 100 * float((E <= 5).mean())
    print(f"  样本 {len(E)}   命中 ±2 {within2:.1f}%   ±5 {within5:.1f}%")
    print(f"  误差中位 {np.median(E):.0f}   余量中位 {np.median(margins):.3f}")
    check(within2 >= 65.0, f"跨视频建库后 A 的留出帧 ±2 ≥ 65%（{within2:.1f}%）")
    check(within5 >= 70.0, f"±5 ≥ 70%（{within5:.1f}%）")
else:
    check(False, "没采到样本")

# ══════════════════════════════════════════ ③ 拒识（最关键）
print()
print("=" * 76)
print("③ ★★ 拒识：拿 **p4** 的帧去查 **p1** 的库 —— 不能自信地认错")
print("=" * 76)
print("  正确的行为是「认不出来」，而不是硬给一个位置。")
print("  乱认的代价：机器朝完全错误的方向走。")

cap = cv2.VideoCapture(B_VIDEO)
NB = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
#: 从 p4 各处取样（跳过前 1000 帧的公共片头）
sample_at = np.linspace(2000, NB - 100, 40).astype(int)
alien = []
for idx in sample_at:
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(idx))
    ok, fr = cap.read()
    if ok:
        alien.append((int(idx), fr))
cap.release()
print(f"  取到 p4 的 {len(alien)} 帧")

loc2 = Locator(lib, peak_min=0.05)
answered, confident = 0, 0
peaks, margins_b = [], []
for idx, fr in alien:
    loc2.reseat(None)
    got = loc2.locate(fr)
    if got is None:
        continue
    answered += 1
    _i, _s, margin = got
    margins_b.append(margin)
    #: 再看这一帧的相位相关可信度（"自信不自信"）
    off = loc2.phase_shift(lib.frame_image(got[0]), fr)
    if off is not None:
        peaks.append(off[2])
        if off[2] >= 0.05:
            confident += 1

rate = 100 * answered / max(len(alien), 1)
conf_rate = 100 * confident / max(len(alien), 1)
print(f"  报出位置（未拒识）的：{answered}/{len(alien)} = {rate:.0f}%")
print(f"  其中**高可信**（peak ≥ 0.05）的：{confident} = {conf_rate:.0f}%")
if peaks:
    print(f"  peak 中位 {np.median(peaks):.3f}   最大 {max(peaks):.3f}")
if margins_b:
    print(f"  余量中位 {np.median(margins_b):.3f}")

#: ★ 核心判据：**不能自信地认错**
#: 允许"偶尔报个位置"（描述子总有偶然相似），但**不许高可信**
check(conf_rate <= 20.0,
      f"错库帧里高可信的比例 ≤ 20%（实测 {conf_rate:.0f}%）")

print()
print("=" * 76)
if FAILURES:
    print(f"结论：**{len(FAILURES)} 项不通过**")
    for f in FAILURES:
        print("  ✗", f)
    raise SystemExit(1)
print("结论：跨视频泛化 + 拒识都成立 —— 不会自信地认错地方")
print("=" * 76)
