# -*- coding: utf-8 -*-
"""★★ 真机验收：**游戏画面能不能在参考库里定位**。

## 这个脚本解决什么

`check_explore_gap_live.py` 那些是**开卷考试** —— 用视频自己的帧查自己的库，
必然命中。它证明不了"真机能不能用"。

真机验收必须用**真的游戏窗口**当输入。而这个脚本就是干那个的。

## ★ 用 WGC 抓图，不用 mss（2026-10-11 踩出来的）

| 方式 | 问题 |
|---|---|
| ``GameWindow.grab()``（mss 屏幕区域） | **被遮挡就抓到挡它的窗口** —— 用户一看报告就被挡，死锁 |
| ``PrintWindow`` | UE 窗口**全黑**（实测 ``非黑像素 0.0%``） |
| **WGC** | ✅ 被遮挡也能抓到**窗口自己的**内容 |

⚠ 上一轮我在这个坑里绕了三轮：抓到的"游戏画面"其实是 DSH 窗口，
基于脏图得出的结论全是错的。**所以这个脚本用 WGC。**

（产品跑任务时走 ok-ww，它本来就配了 ``capture_method: ["WGC", ...]``，
所以没有这个问题 —— 有问题的只是自己写的诊断脚本。）

## ⚠ 需要游戏开着、且**人在参考路线上**

脚本会报"定位到了视频第几分钟"。如果在路线上，结果应该**稳定**
（连续几帧都落在同一小段）；不在路线上，就会是 None 或者乱跳。

## 只读

**不发任何按键** —— 只抓图 + 算。
"""
from __future__ import annotations

import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import ctypes                                     # noqa: E402
import cv2                                        # noqa: E402
import numpy as np                                # noqa: E402
import win32gui                                   # noqa: E402

from src.core import paths                        # noqa: E402
from src.core.explore_gap import list_entries, load_library   # noqa: E402
from src.core.explore_gap.locate import locate_aligned        # noqa: E402
from src.core.explore_gap.locator import PEAK_MIN, Locator    # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")

#: 连抓几帧
FRAMES = 8
#: 抓图超时（秒）
GRAB_TIMEOUT = 15.0
#: 遮挡判定：相交面积小于它不算（1x1 的系统辅助窗口）
MIN_BLOCK_PX = 1000


def find_game():
    """找游戏窗口（按**类名** ``UnrealWindow`` —— 标题匹配会抓错浏览器）。"""
    found = []

    def cb(h, _):
        if win32gui.IsWindowVisible(h) and \
                win32gui.GetClassName(h) == "UnrealWindow":
            found.append(h)

    win32gui.EnumWindows(cb, None)
    return found[0] if found else None


def blockers_of(game):
    """盖在游戏上的窗口类名。

    ⚠ **不能按"标题非空"过滤** —— DSH 的窗口标题是**空的**，
    第一版加了那个条件，于是它被滤掉、检查报"没被挡"，
    但抓出来全是 DSH。
    """
    grown = win32gui.GetWindowRect(game)
    seq = []

    def cb(h, _):
        if win32gui.IsWindowVisible(h):
            seq.append(h)

    win32gui.EnumWindows(cb, None)
    out = []
    for h in seq:
        if h == game:
            break
        r = win32gui.GetWindowRect(h)
        x0, y0 = max(r[0], grown[0]), max(r[1], grown[1])
        x1, y1 = min(r[2], grown[2]), min(r[3], grown[3])
        if max(0, x1 - x0) * max(0, y1 - y0) >= MIN_BLOCK_PX:
            out.append(win32gui.GetClassName(h))
    return out


def crop_client(img, hwnd):
    """把 WGC 帧裁到**客户区**（去掉标题栏和边框）。

    ⚠ 必须裁：WGC 抓的是**整个窗口**（实测 1922x1119），
    而客户区是 1536x864 —— 不裁就会被拉伸，掩膜位置全错。
    """
    wr = win32gui.GetWindowRect(hwnd)
    cr = win32gui.GetClientRect(hwnd)
    cx, cy = win32gui.ClientToScreen(hwnd, (0, 0))
    win_w, win_h = wr[2] - wr[0], wr[3] - wr[1]
    if win_w <= 0 or win_h <= 0:
        return img
    sx, sy = img.shape[1] / win_w, img.shape[0] / win_h
    x0 = max(0, int(round((cx - wr[0]) * sx)))
    y0 = max(0, int(round((cy - wr[1]) * sy)))
    x1 = min(img.shape[1], x0 + int(round(cr[2] * sx)))
    y1 = min(img.shape[0], y0 + int(round(cr[3] * sy)))
    if x1 - x0 < 100 or y1 - y0 < 100:
        return img
    return img[y0:y1, x0:x1]


def grab_frames(hwnd, want: int = FRAMES):
    """用一次 WGC 会话连收 ``want`` 帧（比开 N 次会话快得多）。"""
    from windows_capture import WindowsCapture

    got = []
    errors = []

    def on_frame_arrived(frame, control):
        try:
            buf = frame.frame_buffer
            if buf is not None:
                #: ★★ ``frame_buffer`` **不是 C 连续** —— 实测直接
                #: ``np.asarray(buf)`` 再 ``cvtColor`` 会抛
                #: ``ValueError: ndarray is not C-contiguous``，
                #: 而如果异常被静默吞掉，表现就是"一帧都抓不到"
                #: （查了很久）。所以这里 **先 copy() 再转**。
                #:
                #: ⚠ 而且必须**在回调里就拷** —— 回调返回后缓冲会被复用。
                arr = np.asarray(buf).copy()
                got.append(crop_client(
                    cv2.cvtColor(arr, cv2.COLOR_BGRA2BGR), hwnd))
        except Exception as exc:                   # noqa: BLE001
            #: ⚠ **不要静默吞** —— 记下来，最后一并报出来
            errors.append(f"{type(exc).__name__}: {exc}")
        if len(got) >= want:
            control.stop()

    def on_closed():
        pass

    #: ⚠ ``event()`` **按函数名分派** —— 处理器必须就叫这两个名字
    cap = WindowsCapture(cursor_capture=False, draw_border=False,
                         window_name=win32gui.GetWindowText(hwnd) or "鸣潮")
    cap.event(on_frame_arrived)
    cap.event(on_closed)
    cap.start()

    t0 = time.time()
    while len(got) < want and time.time() - t0 < GRAB_TIMEOUT:
        time.sleep(0.1)

    if not got and errors:
        #: 抓不到 + 有异常 → 把原因说出来，别让调用方去猜
        raise RuntimeError(
            f"WGC 一帧都没抓到，回调报了 {len(errors)} 次错："
            f"{errors[0]}")
    return got


def main() -> int:
    print("=" * 74)
    print("① 权限检查")
    print("=" * 74)
    is_admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
    print(f"  管理员: {is_admin}")
    if not is_admin:
        #: ⚠ 这条**不是**产品缺陷 —— 产品本来就要求管理员
        #: （main.py 的 _check_admin() 不是管理员就拒绝启动）。
        #: 但本脚本在普通权限下只能验**定位**，验不了**按键**。
        print("  ⚠ 不是管理员 —— 本脚本只能验**定位**，验不了**按键**")
        print("     （UIPI 会静默丢弃 Medium→High 的输入；")
        print("      产品自身有 _check_admin() 闸门，所以产品跑起来一定是 High）")
        print("     要验按键：用**管理员终端**重跑本脚本")

    print()
    print("=" * 74)
    print("② 找游戏窗口")
    print("=" * 74)
    game = find_game()
    if not game:
        print("  ✗ 没找到 UnrealWindow —— 游戏没开 / 已最小化？")
        return 2
    print(f"  ✓ hwnd={game}  客户区 {win32gui.GetClientRect(game)}")

    bl = blockers_of(game)
    fg = win32gui.GetForegroundWindow()
    print(f"  是前台   : {fg == game}")
    print(f"  被谁盖住 : {bl or '（没有）'}")
    if bl:
        print("  → ⚠ 被遮挡了，但 WGC 应该照样能抓到（这正是用它的原因）")

    print()
    print("=" * 74)
    print(f"③ WGC 抓 {FRAMES} 帧")
    print("=" * 74)
    shots = grab_frames(game)
    if not shots:
        print("  ✗ 一帧都没抓到")
        return 2
    print(f"  ✓ 拿到 {len(shots)} 帧，形状 {shots[0].shape}  "
          f"（宽高比 {shots[0].shape[1]/shots[0].shape[0]:.3f}，16:9=1.778）")

    #: 存一张给人看 —— 确认抓到的**是游戏**而不是别的窗口
    out_dir = os.path.join("tests", "_shots")
    os.makedirs(out_dir, exist_ok=True)
    shot_path = os.path.join(out_dir, "game_capture.png")
    cv2.imwrite(shot_path, shots[0])
    print(f"  → 已存 {shot_path}（**先看这张确认是游戏**）")

    print()
    print("=" * 74)
    print("④ 加载参考库")
    print("=" * 74)
    entries = [e for e in list_entries(paths.user_data_dir()) if e.runnable]
    if not entries:
        print("  ✗ 没有可用的参考库 —— 先去工具页传视频建库")
        return 2
    lib = load_library(entries[0].library)
    print(f"  ✓ {entries[0].name}  {len(lib)} 帧 / "
          f"{len(lib)*lib.step/(lib.fps or 30)/60:.1f} 分钟")

    print()
    print("=" * 74)
    print("⑤ 连续定位（生产代码 Locator.measure）")
    print("=" * 74)
    loc = Locator(lib)
    idxs = []
    for i, img in enumerate(shots):
        t0 = time.time()
        fix = loc.measure(img)
        ms = (time.time() - t0) * 1000
        if fix is None:
            g = locate_aligned(lib, img, near=None, window=0, margin_min=-9.9,
                               phase_shift=loc.phase_shift)
            extra = (f"  [门槛外 idx={g[0]} {lib.time_of(g[0])/60:.2f}分 "
                     f"score={g[1]:+.3f} m={g[2]:+.3f}]" if g else "")
            print(f"  #{i:02d} → None（{ms:.0f}ms）{extra}")
        else:
            t = lib.time_of(fix.index)
            idxs.append(fix.index)
            print(f"  #{i:02d} → idx={fix.index:<5} {t/60:6.2f}分  "
                  f"sim={fix.similarity:+.4f} m={fix.margin:+.4f} "
                  f"peak={fix.peak:.4f} trust={fix.trusted}  ({ms:.0f}ms)")

    print()
    print("=" * 74)
    print("⑥ 判据")
    print("=" * 74)
    print(f"  有结果 {len(idxs)}/{len(shots)}")
    if idxs:
        span = max(idxs) - min(idxs)
        print(f"  下标 {min(idxs)} ~ {max(idxs)}   跨度 {span} 帧")
        if span <= 4 and len(idxs) >= max(3, len(shots) // 2):
            print("  ✅ **定位稳定** —— 相邻帧结果连续")
        else:
            print("  ⚠ 定位不稳（结果在跳）—— 闭环没法纠偏")
    else:
        print("  ⚠ 一帧都没认准 —— 人可能不在参考路线上")
    print()
    print("  ⚠ 「认准了」还需要 peak 过闸门（PEAK_MIN = "
          f"{PEAK_MIN}）—— 那是**能不能信**的判据。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
