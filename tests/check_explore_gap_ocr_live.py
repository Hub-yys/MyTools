# -*- coding: utf-8 -*-
"""★ 真 OCR 端到端：**真视频帧 → 裁提示区 → OCR → 解析按键**。

用真图、真 OCR、真解析，不注入任何假数据。

## 期望

真视频里那条提示是 ``[F] （长按）离开心钥井``。
正确结果是 **长按 F**（不是 ESC —— 那会打开暂停菜单）。
"""
import os
import sys

sys.path.insert(0, r"D:\AI Work\workbuddy\MyTools")
sys.path.insert(0, r"D:\AI Work\workbuddy\MyTools\vendor\okww")
os.chdir(r"D:\AI Work\workbuddy\MyTools")
sys.stdout.reconfigure(encoding="utf-8")

import cv2                                           # noqa: E402

from src.core.explore_gap.keys import parse_prompt   # noqa: E402
from src.core.explore_gap.reader import (            # noqa: E402
    crop_prompt,
    learn_from_ocr,
    prompt_score,
)
from src.tools.game.explore_gap.ocr import make_ocr  # noqa: E402

FAIL = []


def check(cond, msg):
    print(f"  [{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAIL.append(msg)


ocr = make_ocr()
print("=" * 72)
print("① OCR 拿得到吗")
print("=" * 72)
check(ocr is not None, "直接构造 onnxocr 成功（不用开游戏引擎）")
if ocr is None:
    raise SystemExit(1)

video = r"D:\DeepSeek Work\_vid\p4.mp4"
learn = learn_from_ocr(ocr)

print()
print("=" * 72)
print("② 扫真视频，找有提示的帧并读出来")
print("=" * 72)
cap = cv2.VideoCapture(video)
total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
#: 1035 秒附近有一条已知提示（实测 score 最高那帧）
targets = [int(1017.5 * 30), int(1428.0 * 30), int(569.0 * 30)]

found = []
for frame_no in targets:
    if frame_no >= total:
        continue
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_no)
    ok, frame = cap.read()
    if not ok:
        continue
    roi = crop_prompt(frame)
    score = prompt_score(roi)
    if score < 0.02:
        continue
    text = learn(0, frame)
    found.append((frame_no, score, text))
    print(f"  帧 {frame_no:>6}  score={score:.4f}  OCR={text!r}")
cap.release()

check(bool(found), f"从真视频里读到了提示（{len(found)} 条）")

print()
print("=" * 72)
print("③ 解析成按键")
print("=" * 72)
parsed = []
for frame_no, score, text in found:
    press = parse_prompt(text or "")
    if press:
        parsed.append((frame_no, press))
        print(f"  帧 {frame_no}: 「{text}」 → {press.label} "
              f"（{press.seconds:.2f}s）")
    else:
        print(f"  帧 {frame_no}: 「{text}」 → （不猜，返回 None）")

if parsed:
    key, press = parsed[0][1].key, parsed[0][1]
    check(press.key != "esc", "★ 没有映射到 ESC（那会打开暂停菜单）")
    print(f"  第一个解析出的键：{press.key}")

print()
print("=" * 72)
print("④ 完整链路（含决策层）")
print("=" * 72)
from src.core.explore_gap import (                   # noqa: E402
    ActionKind,
    ExploreGapConfig,
    ExploreGapState,
    build_schedule,
    decide,
)
from src.core.explore_gap.locator import Fix         # noqa: E402

#: 用**真读到的文字**造按键表
obs = [(100 + i, t) for i, (_f, _s, t) in enumerate(found)] or \
      [(100, "F 对话")]
sched = build_schedule(obs)
print(f"  按键表：{sched.describe()}")
if sched.events:
    idx = sched.events[0].start
    fx = Fix(index=idx, frame=idx * 15, time_s=idx * 0.5,
             similarity=0.95, margin=0.07, dx=0.0, dy=0.0, peak=0.9)
    act = decide(fx, ExploreGapState(), ExploreGapConfig(),
                 library_len=1000, schedule=sched)
    print(f"  走到第 {idx} 帧 → {act.kind.value}"
          f"{'  键=' + act.key if act.key else ''}")
    check(act.kind is ActionKind.KEY, "决策层在那个位置输出按键动作")

print()
print("=" * 72)
if FAIL:
    print(f"结论：**{len(FAIL)} 项不通过**")
    for f in FAIL:
        print("  ✗", f)
    raise SystemExit(1)
print("结论：真视频 → 真 OCR → 真解析 → 决策层按键，链路通")
print("=" * 72)
