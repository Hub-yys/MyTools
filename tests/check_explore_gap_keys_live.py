# -*- coding: utf-8 -*-
"""★ 真视频验收：**从上传的视频里真的学到按键了吗**。

## 这个脚本回答的就是用户的质疑

用户问：**"我说的跟着视频走，你真的实现了吗"**

原来的答案是不能 —— 只会转视角 + 按 W。
这个脚本用**真视频**验证补上的那一半：

    ① 建库时**真的扫了提示区**（不是假装扫）
    ② 每个参考帧都拿到一个观测（提示 / 无提示）
    ③ 学到的事件能还原成"第几帧按什么键"
    ④ 决策层**真的会**在那个位置输出按键动作

## ⚠ 关于 OCR

真 OCR 要引擎启动（见 ``ocr.py``）。这个脚本**两条都验**：

* 用**真 OCR**（如果拿得到）→ 报告真学到的按键
* 拿不到 → 用一个"读图里有没有提示条"的**保守桩**，
  只验"扫描链路通了、事件能合并、决策层会按键"

**不伪造 OCR 结果** —— 那等于自己骗自己。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))) or ".")
sys.stdout.reconfigure(encoding="utf-8")

import numpy as np                                   # noqa: E402

VIDEO = sys.argv[1] if len(sys.argv) > 1 else \
    r"D:\DeepSeek Work\_vid\p4.mp4"

FAILURES: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


try:
    import cv2                                       # noqa: E402
except Exception as exc:                             # noqa: BLE001
    print(f"没装 cv2（{exc}）—— 跳过")
    raise SystemExit(0)

if not os.path.isfile(VIDEO):
    print(f"没找到视频 {VIDEO} —— 跳过")
    raise SystemExit(0)

from src.core.explore_gap import (                   # noqa: E402
    ActionKind,
    ExploreGapConfig,
    ExploreGapState,
    build_schedule,
    crop_prompt,
    decide,
    prompt_score,
)
from src.core.explore_gap.locator import Fix         # noqa: E402

print("=" * 76)
print("① 提示区检测：真视频里到底有多少帧像有按键提示")
print("=" * 76)

cap = cv2.VideoCapture(VIDEO)
fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
STEP = 15                                            #: 和建库一致

scores = []
index = 0
cur = 0
while cur < total:
    cap.set(cv2.CAP_PROP_POS_FRAMES, cur)
    ok, frame = cap.read()
    if not ok:
        break
    scores.append(prompt_score(crop_prompt(frame)))
    index += 1
    cur += STEP
cap.release()

arr = np.array(scores) if scores else np.array([0.0])
hit = int((arr >= 0.02).sum())
pct = 100.0 * hit / max(len(arr), 1)
print(f"  采样 {len(arr)} 帧（每 {STEP} 帧 = {STEP/fps:.1f} 秒）")
print(f"  像有提示条：{hit} 帧 = {pct:.1f}%")
print(f"  score 中位 {np.median(arr):.4f}  最大 {arr.max():.4f}")
check(len(arr) > 100, f"采到了足够多的帧（{len(arr)}）")
#: 实测基准是 23.5%（_vid/final.py）。给个宽松区间 —— 不同视频比例不同
check(pct > 0.5,
      f"确实检出了提示条（{pct:.1f}% > 0.5%）—— 判据没瞎报也没全灭")

print()
print("=" * 76)
print("② 扫描链路：每帧一个观测（真扫，不伪造）")
print("=" * 76)


def probe_ocr(roi):
    """保守桩 OCR：**不改写结果**，只说"这块像不像提示条"。

    ⚠ 故意不返回假的按键文字 —— 那会骗过整条链路的验收。
    真 OCR 拿不到时，这里只证明"扫描通了 + 事件能合并 + 决策层会按"。
    """
    return ""


from src.core.explore_gap import learn_from_ocr      # noqa: E402

learn = learn_from_ocr(probe_ocr)
cap = cv2.VideoCapture(VIDEO)
observations = []
cur = 0
index = 0
while cur < total:
    cap.set(cv2.CAP_PROP_POS_FRAMES, cur)
    ok, frame = cap.read()
    if not ok:
        break
    observations.append((index, learn(index, frame)))
    index += 1
    cur += STEP
cap.release()

sched = build_schedule(observations)
print(f"  扫了 {sched.scanned} 帧")
print(f"  其中解析不出按键的：{sched.unreadable}")
print(f"  合并后的按键事件：{len(sched.events)}")
check(sched.scanned == len(arr), "扫描帧数与①一致")
#: 桩 OCR 返回空 → 应该 0 个事件（这正好验证"读不到就不瞎编"）
check(len(sched.events) == 0,
      "桩 OCR 不返回文字时**一个按键都不该造出来**（不瞎编）")

print()
print("=" * 76)
print("③ 真 OCR（如果引擎在跑）")
print("=" * 76)
sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
try:
    from src.tools.game.explore_gap.ocr import make_ocr
    real = make_ocr()
except Exception as exc:                             # noqa: BLE001
    real = None
    print(f"  取 OCR 出错：{type(exc).__name__}: {exc}")

if real is None:
    print("  没拿到真 OCR（引擎没启动）—— 跳过这一段")
    print("  ⚠ 所以**真按键文字**这次没验到；验到的是整条链路通")
else:
    print("  拿到真 OCR，扫 200 帧看能读出什么…")
    learned = learn_from_ocr(real)
    cap = cv2.VideoCapture(VIDEO)
    obs2 = []
    cur = 0
    idx = 0
    while cur < total and idx < 200:
        cap.set(cv2.CAP_PROP_POS_FRAMES, cur)
        ok, frame = cap.read()
        if not ok:
            break
        obs2.append((idx, learned(idx, frame)))
        idx += 1
        cur += STEP
    cap.release()
    got = [t for _i, t in obs2 if t]
    sched2 = build_schedule(obs2)
    print(f"  读出文字的帧：{len(got)}/{len(obs2)}")
    for text in got[:10]:
        print(f"    「{text}」")
    print(f"  合并成 {len(sched2.events)} 个按键事件")
    if sched2.events:
        print(f"  {sched2.describe()}")

print()
print("=" * 76)
print("④ 决策层：学到按键后**真的会按**吗")
print("=" * 76)
#: 造一个已知按键表（模拟"视频第 100 帧按了 F"）
demo = build_schedule([(i, "F 对话") for i in range(100, 104)])


def fix_at(index, peak=0.9, dx=0.0):
    return Fix(index=index, frame=index * 15, time_s=index * 0.5,
               similarity=0.95, margin=0.07, dx=dx, dy=0.0, peak=peak)


st = ExploreGapState()
act_at = decide(fix_at(100), st, ExploreGapConfig(),
                library_len=1000, schedule=demo)
print(f"  走到第 100 帧 → {act_at.kind.value}"
      f"{'  键=' + act_at.key if act_at.key else ''}")
check(act_at.kind is ActionKind.KEY,
      "★ 走到视频按过键的位置，决策层输出 KEY 动作")
check(act_at.key == "f", "键正确（f）")

act_off = decide(fix_at(500), ExploreGapState(), ExploreGapConfig(),
                 library_len=1000, schedule=demo)
print(f"  走到第 500 帧 → {act_off.kind.value}（视频这里没按键）")
check(act_off.kind is not ActionKind.KEY, "没有按键的位置不该按")

st_un = ExploreGapState()
act_un = decide(fix_at(100, peak=0.001), st_un, ExploreGapConfig(),
                library_len=1000, schedule=demo)
print(f"  第 100 帧但**测不准** → {act_un.kind.value}")
check(act_un.kind is not ActionKind.KEY,
      "测不准时绝不能按键（位置可能是错的）")

print()
print("=" * 76)
if FAILURES:
    print(f"结论：**{len(FAILURES)} 项不通过**")
    for f in FAILURES:
        print("  ✗", f)
    raise SystemExit(1)
print("结论：扫描链路通、事件能合并、决策层会按 —— 「照视频做操作」已接上")
print("=" * 76)
