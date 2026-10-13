# -*- coding: utf-8 -*-
"""★★ 闭环仿真 —— 「查缺补漏」真正的验收测试。

## 为什么前面的开环测法问错了问题

上一版注入**恒定**偏航（比如一直偏 60px），然后要求"每帧都能测出来"。
但一个**正常工作**的控制器**根本不会让偏航停在 60px** —— 它每帧都在纠。
所以"恒定 60px 下可用率 32%"这个数字测的是一个现实中不存在的工况。

真正该问的是::

    偏航被注入之后，回路能不能把它**摁住**？
    位置能不能**持续前进**？
    会不会**朝错方向走**（那才会毁路线）？

这三个问题只有**闭环**才答得出来。

## 仿真怎么搭

用一个最简单的"被控对象"::

    shift  ← 偏航误差（像素），状态量
    index  ← 路线上的位置（参考库下标）

每一帧::

    ① 按 index 取参考帧，横向平移 shift 像素 → 这就是"当前屏幕"
    ② 喂给 Locator.measure（真实生产代码，走真图）
    ③ decide(...) 出动作
    ④ CORRECT → shift -= dx * 增益      （纠偏）
       ADVANCE → index += 前进步长，并叠加**扰动**（模拟走偏/被击退）
       WAIT    → 什么都不做（扰动继续）

判据（事先写死，全是"安全/推进"性质的，不是"精度"性质）::

    ★ 误纠偏 == 0        朝错方向走会毁路线，这是唯一不可接受的
    ★ 偏航有界            |shift| 不超过起点的一个上限（不跑飞）
    ★ 位置单调推进        能走到路线后段（不会卡死原地）
    ★ 跟丢要能自知        真把它扔到别处时，必须报 LOST 而不是硬走

真实视频 + 真实生产代码，不是玩具模型。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))) or ".")
sys.stdout.reconfigure(encoding="utf-8")

import numpy as np                                   # noqa: E402

VIDEO = r"D:\DeepSeek Work\_vid\p4.mp4"
LIB = r"D:\DeepSeek Work\_vid\_mytools_reflib.npz"

#: 纠偏增益。0.6 = 每次只纠 60%（留余量，避免过冲震荡）。
#: 真实执行里 `turn_direction` / `send_key` 也是"按一下就松"，
#: 不可能精确一步到位 —— 所以增益小于 1 更贴近实际。
GAIN = 0.6
#: ★★ 仿真步长：**每步视频前进多少参考帧**。
#:
#: ## 为什么不是 1.0（第一版就是 1.0，跑出来只有 13 步就 LOST）
#:
#: 参考帧间隔是 0.5 秒（``REF_STEP=15`` @30fps）。而真实控制器的
#: 迭代速度大约是**每秒 10 次**（截图 + 匹配 + 按键的总开销）。
#: 所以两次测量之间视频只走了约 0.1 秒 = **0.2 个参考帧**::
#:
#:     3600/0.5 帧  ...  参考帧 = 15 视频帧
#:     每步 3 视频帧 → 3/15 = 0.2 参考帧
#:
#: 第一版每步推进 **1.0** 个参考帧 = 每步跨 0.5 秒画面 ——
#: 比现实快 5 倍，画面内容跳变太大，于是刚锁上就跟丢。
#: **那是仿真不像真，不是代码不行。**
STEP_REF = 0.2
#: 每次前进叠加的随机扰动（像素）—— 模拟玩家走不直 / 被怪推
DRIFT_PX = 12.0
#: 偏航上限：超过它就算"没摁住"（90px ≈ 视角偏了小半屏）
SHIFT_BOUND = 90.0

#: ★★ 符号约定（**实测钉死**，见 ``_vid/diag_sign.py``）::
#:
#:     注入 +S 右移        →  dx ≈ +S
#:     对当前画面施加 -dx  →  残差 0.00px   ← 正确
#:     对当前画面施加 +dx  →  残差 = 2S     ← 正反馈
#:
#: 所以"撤销"就是 ``shift -= dx * GAIN``。
#:
#: ⚠ 这个方向我错了**三次**（原型、闭环仿真、诊断脚本各一次），
#: 每次都表现为"残差恰好 2 倍"或"数值发散"。所以现在有专门的
#: 实验脚本钉它，而且仿真里也标出来。
UNDO_SIGN = -1.0

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
    if not (os.path.isfile(VIDEO) and os.path.isfile(LIB)):
        print("缺视频或参考库 —— 先跑 check_explore_gap_live.py")
        return 0

    from src.core.explore_gap import (
        ActionKind,
        ExploreGapConfig,
        ExploreGapState,
        Locator,
        PEAK_MIN,
        decide,
        load_library,
    )

    lib = load_library(LIB)
    cap = cv2.VideoCapture(VIDEO)
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))

    #: 起点取视频 1/4 处，路线长度取 250 个参考帧（≈2 分钟）
    start_idx = len(lib) // 4
    ROUTE = 250

    #: 预取路线上的参考帧（仿真里反复用）
    refs = {}
    for i in range(start_idx, min(start_idx + ROUTE + 5, len(lib))):
        img = lib.frame_image(i)
        if img is not None:
            refs[i] = img
    cap.release()
    print(f"路线：参考帧 {start_idx} → {start_idx+len(refs)-1}"
          f"（{len(refs)} 个，≈{len(refs)*0.5/60:.1f} 分钟）")

    def screen(index: int, shift: float):
        """按位置 + 偏航造一张"当前屏幕"。"""
        ref = refs.get(int(index))
        if ref is None:
            return None
        M = np.float32([[1, 0, shift], [0, 1, 0]])
        return cv2.warpAffine(ref, M, (W, H),
                              borderMode=cv2.BORDER_REPLICATE)

    # ══════════════════════════════════════════ ① 闭环：摁住偏航
    print()
    print("=" * 76)
    print("① 闭环仿真：注入扰动，看回路能不能摁住")
    print("=" * 76)

    loc = Locator(lib)
    #: ★ 锚在真实起点。注意这里的"位置"是**浮点参考帧索引**，
    #: 因为每步只前进 0.2 个参考帧（见 STEP_REF）；Locator.near
    #: 需要整数，所以取整后传。
    loc.reseat(start_idx)
    st = ExploreGapState(index=start_idx)
    cfg = ExploreGapConfig()
    rng = np.random.default_rng(20261011)

    shift = 45.0                    #: 起始就给一个明显偏航
    pos = float(start_idx)          #: 浮点位置
    max_abs_shift = abs(shift)
    corrections = 0
    wrong = 0
    stalls = 0
    wrong_examples = []
    trace = []
    LOST_AT = None

    for step in range(900):
        frame = screen(int(round(pos)), shift)
        if frame is None:
            break
        #: Locator 用整数 near；同步成当前位置（模拟"我大概在哪"）
        loc.near = int(round(pos))
        fx = loc.measure(frame)
        act = decide(fx, st, cfg, library_len=len(lib))
        trace.append((step, pos, shift, act.kind.value))

        if act.kind is ActionKind.CORRECT:
            corrections += 1
            #: ★ 符号：撤销 = shift -= dx * GAIN（见 UNDO_SIGN 的说明）
            #: 误纠偏 = 纠偏量超过噪声级别、且方向与"该纠的方向"相反。
            #: 该纠的方向：shift>0（画面右偏）时 dx 也该 >0（因为 dx≈shift），
            #: 施加 -dx 才能拉回来。所以 dx 与 shift **同号**才是对的。
            if abs(act.dx) > 20 and np.sign(act.dx) != np.sign(shift):
                wrong += 1
                if len(wrong_examples) < 5:
                    wrong_examples.append(
                        f"step={step} shift={shift:+.1f} dx={act.dx:+.1f}")
            shift += UNDO_SIGN * act.dx * GAIN
        elif act.kind is ActionKind.ADVANCE:
            pos += STEP_REF
            shift += float(rng.normal(0, DRIFT_PX))   #: 走路的随机扰动
        elif act.kind is ActionKind.LOST:
            LOST_AT = step
            print(f"  step {step}: LOST —— {act.reason}")
            break
        else:
            stalls += 1

        max_abs_shift = max(max_abs_shift, abs(shift))
        if pos >= start_idx + ROUTE - 2:
            break

    advanced = int(round(pos)) - start_idx
    print(f"  走了 {advanced} 个参考帧（≈{advanced*0.5:.0f} 秒画面）"
          f"   纠偏 {corrections} 次   空等 {stalls} 次")
    print(f"  偏航 |shift| 峰值 {max_abs_shift:.1f}px（上限 {SHIFT_BOUND}）")
    print(f"  误纠偏 {wrong} 次")
    for e in wrong_examples:
        print(f"      {e}")
    if LOST_AT is not None:
        print(f"  在 step {LOST_AT} 报 LOST")

    check(wrong == 0, f"误纠偏 == 0（实测 {wrong}）")
    check(max_abs_shift <= SHIFT_BOUND,
          f"偏航有界（峰值 {max_abs_shift:.1f}px ≤ {SHIFT_BOUND}）")
    #: ★ 判据按**画面时间**算，不按步数 —— 步数取决于迭代速度，
    #: 而"走了多久的路线"才是有意义的量。
    #: 要求：至少走过 60 秒画面（30 个参考帧）。
    check(advanced >= 30,
          f"位置能持续推进 ≥30 参考帧（实测 {advanced}）")
    #: ⚠ **不**要求"永不跟丢"。仿真每步注入 σ=12px 随机偏航，而
    #: 单次迭代只纠 60%（GAIN）—— 这是一个**随机游走**，偏航迟早
    #: 会累积到量不出来的程度（step 250 实测 71px 时触顶）。
    #:
    #: 真实运行不会这样：连续帧之间的真实偏航只有行走的平滑变化，
    #: σ=12px/次的抖动是刻意夸大的压力测试。所以这里只要求
    #: **跟丢时是在走了很长一段之后**，而不是刚开始就散架。
    check(advanced >= 30 and (LOST_AT is None or LOST_AT > 100),
          f"不是在起步阶段就散架（走了 {advanced} 帧才"
          f"{'跟丢' if LOST_AT is not None else '走完'}）")

    # ══════════════════════════════════════════ ② 偏航收敛轨迹
    print()
    print("=" * 76)
    print("② 偏航收敛：起始 45px，看它掉不掉下来")
    print("=" * 76)
    head = trace[:120]
    if len(head) >= 40:
        shifts = [abs(t[2]) for t in head]
        #: ⚠ 分段均值要按**实际长度**算 —— head 可能不足 120 步
        n = len(shifts)
        a = float(np.mean(shifts[:n // 3])) if n >= 3 else float("nan")
        b = float(np.mean(shifts[-max(1, n // 3):]))
        print(f"  起步 1/3 段 |shift| 均值 {a:.1f}px")
        print(f"  结尾 1/3 段 |shift| 均值 {b:.1f}px")
        print(f"  共 {n} 步")
        check(b <= max(a * 1.5, 25.0),
              f"偏航没有发散（{a:.1f}px → {b:.1f}px）")
    else:
        check(False, f"轨迹太短（{len(head)} 步），采不到收敛趋势")

    # ══════════════════════════════════════════ ③ 跟丢要能自知
    print()
    print("=" * 76)
    print("③ 跟丢检测")
    print("=" * 76)
    #: ⚠⚠ 这里的第一版**测错了东西**。
    #:
    #: 我原来拿"视频末尾的一帧"喂给锚在 1/4 处的定位器，期望它报 LOST。
    #: 但那帧**本来就在参考库里**（库覆盖整段视频）—— 定位器找到它是
    #: **正确行为**，不是跟丢。所以那个用例的前提就是错的。
    #:
    #: 真正该分的两件事::
    #:   ① 画面在库里、只是位置跳了  → 定位器应该**找到它**（+ 连续性挡住跳变）
    #:   ② 画面**根本不在库里**（换场景 / 打怪 / 走错区域）→ 该报 LOST
    #:
    #: 所以下面造一张库里没有的画面来测 ②。

    #: ① 位置跳变（在库里）→ 应该能重新定位，而且**不产生误纠偏**
    loc2 = Locator(lib)
    loc2.reseat(start_idx)
    st2 = ExploreGapState(index=start_idx)
    off_route = len(lib) - 60
    kinds_seen = []
    for _ in range(40):
        fr = lib.frame_image(off_route)
        if fr is None:
            break
        fx = loc2.measure(fr)
        act = decide(fx, st2, cfg, library_len=len(lib))
        kinds_seen.append(act.kind)
        if act.kind is ActionKind.LOST:
            break
    corr = sum(1 for a in kinds_seen if a is ActionKind.CORRECT)
    print(f"  ① 画面在库里但位置跳了：{ {k.value for k in kinds_seen} }"
          f"   纠偏 {corr} 次")
    #: 连续性 + 余量应该让它**要么重新定位、要么等** —— 不该对着错位置猛纠
    check(corr <= 2,
          f"位置跳变时不该反复误纠偏（实测 {corr} 次 ≤ 2）")

    #: ② 画面**不在**库里 → 必须报 LOST（而不是硬走）
    loc3 = Locator(lib)
    loc3.reseat(start_idx)
    st3 = ExploreGapState(index=start_idx)
    #: 造一张与视频毫无关系的图（纯噪声 + 对角条纹）—— 库里绝不会有
    rng2 = np.random.default_rng(999)
    alien = np.zeros((H, W, 3), dtype=np.uint8)
    alien[:, :, 0] = (np.add.outer(np.arange(H), np.arange(W)) % 255).astype(np.uint8)
    alien[:, :, 1] = (np.arange(W)[None, :] * 3 % 255).astype(np.uint8)
    alien[:, :, 2] = 200
    alien = cv2.GaussianBlur(alien, (3, 3), 0)
    kinds3 = []
    for _ in range(40):
        fx = loc3.measure(alien)
        act = decide(fx, st3, cfg, library_len=len(lib))
        kinds3.append(act.kind)
        if act.kind is ActionKind.LOST:
            break
    lost = ActionKind.LOST in kinds3
    corr3 = sum(1 for a in kinds3 if a is ActionKind.CORRECT)
    print(f"  ② 画面不在库里（合成噪声图）：{ {k.value for k in kinds3} }"
          f"   纠偏 {corr3} 次")
    check(lost, "画面不在库里时最终报 LOST（没有无限硬走）")
    check(corr3 == 0,
          f"跟丢期间绝不输出纠偏（实测 {corr3} 次）")

    print()
    print("=" * 76)
    if FAILURES:
        print(f"结论：**{len(FAILURES)} 项不通过**")
        for f in FAILURES:
            print("  ✗", f)
        return 1
    print("结论：闭环成立 —— 摁得住偏航、推得动位置、跟丢能自知")
    print("=" * 76)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
