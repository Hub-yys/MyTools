# -*- coding: utf-8 -*-
"""「查缺补漏」的 ok-ww 执行器 —— 把决策变成真正的按键与转向。

## 它在整条链路里的位置

::

    视频 → [建库] → 参考库 ─┐
                            ├─→ Locator.measure → decide → ★本模块 → 游戏
    屏幕 → [描述子] ────────┘

前三步（建库 / 定位 / 决策）都是**纯逻辑、已离线验证**。
本模块是**唯一碰真实输入**的一层，也是唯一没法离线测的一层 ——
所以它被刻意做得很薄：**不含任何判断**，判断全在
:mod:`src.core.explore_gap.controller` 里。

## ⚠ 它为什么这么薄（设计约束，别加逻辑）

离线能测的部分已经测透了（77 个单测 + 真视频验收）。
把判断搬到这里 = 搬进一个测不了的地方 = 前功尽弃。

所以本模块只做三件事::

    ① 拿一帧（self.next_frame()）
    ② 问控制器要动作
    ③ 照着做（转视角 / 走 / 停下报错）

## ⚠ 坐标系约定（最容易错的地方）

``Action.dx`` 是"**当前画面相对参考**的横向位移"（像素）。
撤销它 = 对当前画面施加 ``-dx``。

对应到游戏操作：画面右偏（dx>0）说明**视角左转了**，
要把视角**往右转回来**。

⚠ 这个方向我错了三次（见 ``docs/查缺补漏-实验记录.md`` 第四节）。
所以这里把"像素 → 按键"的换算单独抽成 :func:`dx_to_turn`，
并且它**有单测**（不依赖游戏）。

## 两个还没在真机上验过的量

**① 像素 → 转向时长的比例**（``PX_PER_TURN_SEC``）
   取决于游戏灵敏度设置、鼠标 DPI、FOV。**必须真机标定**。
   代码里给的是保守初值，用 :meth:`ExploreGapTask.calibrate` 可以量。

**② 前进一步对应多少画面时间**（``ADVANCE_SLEEP``）
   走快了会冲过参考点，走慢了磨蹭。也偏保守。

→ 所以本任务**默认不自动跑**，必须先跑一次标定。
"""

from __future__ import annotations

import time

from ....core.explore_gap import (
    ActionKind,
    ExploreGapConfig,
    ExploreGapState,
    Locator,
)

#: 横向像素 → 转向时长（秒/像素）。
#:
#: ⚠ **必须真机标定**（灵敏度 / DPI / FOV 都会变）。
#: 这个初值是按"常见灵敏度下 1280 宽画面，转完整屏约 1.5 秒"估的：
#: 1280px 对应 1.5 秒 → 约 0.0012 秒/像素。
#: 偏小是刻意的 —— 转少了可以再转，转多了要转回来（浪费还容易晕）。
PX_PER_TURN_SEC = 0.0012

#: 单次转向的时长上限（秒）—— 别一次转太多，宁可分几步
MAX_TURN_SEC = 0.6

#: 前进/等待时的一帧间隔（秒）
FRAME_INTERVAL = 0.1

#: 连续多少帧拿不到画面就放弃
MAX_BLANK_FRAMES = 30


def dx_to_turn(dx: float, *, px_per_sec: float = PX_PER_TURN_SEC,
               max_sec: float = MAX_TURN_SEC) -> tuple[str, float]:
    """``Action.dx`` → 该按哪个键、按多久。

    ## 方向（★ 实测钉死，别猜）

    ``dx > 0`` = 画面内容相对参考**右移**了 = 视角**左转**了
    → 要把视角**往右转回来** → 按 ``d``（游戏里 d = 右转视角... 见下）

    ⚠ 这里有个**游戏相关的约定**需要真机确认：鸣潮里
    ``a``/``d`` 是"角色左右移动"还是"视角左右转"取决于是否按住
    鼠标右键（或是否在自由视角模式）。ok-ww 的 ``turn_direction``
    用的是 ``send_key`` + ``center_camera``，也就是**按键即移动**。

    所以这里返回的是**"需要往哪边修正"**的语义键：
    ``"d"`` = 往右修、``"a"`` = 往左修，由调用方决定怎么按
    （按一下 / 按住 / 转鼠标）。

    :return: ``(键, 时长秒)``；``dx`` 太小返回 ``("", 0.0)``
    """
    if abs(dx) < 1.0:
        return "", 0.0
    #: dx>0（画面右移）→ 视角左转了 → 往右修 → "d"
    key = "d" if dx > 0 else "a"
    seconds = min(abs(dx) * px_per_sec, max_sec)
    return key, seconds


class ExploreGapTask:
    """照视频跑路线的 ok-ww 任务。

    :param ref_lib_path: 参考库 ``.npz`` 路径
    :param task: ok-ww 任务实例（提供 ``next_frame`` / ``frame`` / ``send_key``）
    :param log: 日志函数
    :param should_stop: 返回 True 时尽快退出
    :param config: 闭环参数
    :param route_start: 从参考库的哪个下标开始（默认 0）

    ## 用法

    这个类**不**继承 ok-ww 的 Task —— 它只依赖一个很小的鸭子类型接口
    （``next_frame`` / ``frame`` / ``send_key`` / ``sleep``），
    这样它在**没有 ok-ww 的环境里也能被单测**（喂假的 task 即可）。

    真正的 ok-ww 任务类在 ``okww_task.py`` 里，那个只是把
    :class:`okww.task.WWOneTimeTask` 和本类接起来。
    """

    def __init__(self, ref_lib_path, task, log, should_stop,
                 *, config: ExploreGapConfig | None = None,
                 route_start: int = 0,
                 px_per_turn_sec: float = PX_PER_TURN_SEC):
        from ....core.explore_gap import load_library     # noqa: PLC0415

        self.library = load_library(ref_lib_path)
        self.task = task
        self.log = log
        self.should_stop = should_stop
        self.config = config or ExploreGapConfig()
        self.px_per_turn_sec = px_per_turn_sec
        self.state = ExploreGapState(index=route_start)
        self.locator = Locator(self.library, peak_min=self.config.peak_min)
        self.locator.reseat(route_start)
        #: 统计（给报告用）
        self.stats = {
            "frames": 0, "advance": 0, "correct": 0,
            "wait": 0, "blank": 0, "lost": 0,
            #: ★ 照视频按了多少次键（「做一样的操作」的量化）
            "keys": 0,
        }
        #: 标定样本（跑之前量出来的，给报告显示）
        self.calibration: list[tuple[float, float]] = []
        #: ★ 视频的按键表（没有的话只做"转视角 + 前进"）
        self.schedule = self.library.schedule() if self.library.has_keys() \
            else None
        if self.schedule is not None:
            self.log(f"按键表：{self.schedule.describe()}")
        else:
            self.log("⚠ 这个库没有按键表（建库时没学到按键）—— "
                     "只会转视角 + 一直按 W，遇到机关会卡住")

    # ---------------------------------------------------------------- 标定
    def calibrate(self) -> float:
        """★ 自动标定转向比例（跑之前先做）。

        :return: 标定出的秒/像素；**没标成返回 0.0**

        ## 为什么要自动标定而不是让用户填

        ``PX_PER_TURN_SEC`` 取决于游戏灵敏度 / 鼠标 DPI / FOV，机器猜不出来。
        没标定就跑，机器会照着一个**错的换算**去转 —— 转不够就一直偏，
        转太多就来回甩。那是唯一会"乱走"的情形。

        手动填要人眼估像素，不准还麻烦。而这套东西**测偏移**已经能做到
        亚像素精度（闭环残差最大 0.478px），直接拿它量就行。

        ## 怎么量

            ① 拍一帧 → 按键 H 秒 → 再拍一帧
            ② 相位相关量出画面横移多少像素
            ③ 几个不同的 H 各做一次 → 过原点最小二乘拟合

        ⚠ 标定**会真的按键**（按 ``d``），所以要在游戏里、别对着 UI。
        """
        if self.should_stop():
            return 0.0
        self.log("开始自动标定转向比例（会按几次 d 键）…")
        value, samples = calibrate_turn(
            self._grab, self.task.send_key, log=self.log)
        self.calibration = samples
        if value <= 0.0:
            self.log("标定失败 —— 画面没动 / 位置不对。"
                     "请在游戏里对着大片场景重试。")
            return 0.0
        self.px_per_turn_sec = value
        self.log(f"标定成功：{value:.6f} 秒/像素（{len(samples)} 个样本）")
        return value

    # ------------------------------------------------------------------ 主循环
    def run(self, *, auto_calibrate: bool = True) -> dict:
        """跑路线。返回统计 dict（不会抛 —— 失败也返回统计，由调用方决定怎么报）。

        :param auto_calibrate: 跑之前先自动标定转向比例（默认**开**）

        ## ★ 为什么标定是跑的一部分

        ``PX_PER_TURN_SEC`` 猜不出来（取决于灵敏度 / DPI / FOV）。
        没标定就跑 = 照一个错的换算转 = **唯一会"乱走"的情形**。
        所以默认先量一次 —— 量不出就**根本不进入主循环**，
        而不是照猜的数硬跑。

        ## 结束条件（三个都要能退出）

        1. 走完参考库 → 正常结束
        2. 控制器报 ``LOST`` → 停下（**不要硬走**）
        3. ``should_stop()`` / 连续拿不到画面 / 标定失败 → 退出
        """
        self.log(f"查缺补漏：参考库 {len(self.library)} 帧，"
                 f"从第 {self.state.index} 帧开始")

        if auto_calibrate:
            if self.calibrate() <= 0.0:
                #: ★ 标定失败就**不跑**。照错的换算走会乱走，
                #: 比"没跑"糟得多（用户会以为工具坏了）。
                self.stats["calibration_failed"] = 1
                self.log("标定没成功 —— 不进入主循环（照错的换算走会乱走）")
                self._close()
                return dict(self.stats)
            self.stats["px_per_turn_sec"] = self.px_per_turn_sec

        blank = 0
        while True:
            if self.should_stop():
                self.log("被要求停止")
                break

            frame = self._grab()
            if frame is None:
                blank += 1
                self.stats["blank"] += 1
                if blank >= MAX_BLANK_FRAMES:
                    self.log(f"连续 {blank} 帧拿不到画面 —— 退出")
                    break
                self._sleep(FRAME_INTERVAL)
                continue
            blank = 0
            self.stats["frames"] += 1

            fix = self.locator.measure(frame)
            action = self._decide(fix)
            self._apply(action)

            if action.kind is ActionKind.DONE:
                self.log("参考路线走完")
                break
            if action.kind is ActionKind.LOST:
                self.stats["lost"] += 1
                self.log(f"跟丢了，停下：{action.reason}")
                break

            self._sleep(FRAME_INTERVAL)

        #: ⚠ 关的是 ``self.library``（真正打开视频的那个），**不是**
        #: ``self.locator.library`` —— 后者在生产里是同一个对象，
        #: 但在测试里可以换掉；关错了就会留下一个没关的视频句柄
        #: （Windows 上会占住文件，重跑/改名/删除都失败）。
        self._close()

        return dict(self.stats)

    def _close(self) -> None:
        """关掉视频句柄（两个都试一遍，幂等，不抛）。"""
        seen = set()
        for owner in (self.library, getattr(self.locator, "library", None)):
            if owner is None or id(owner) in seen:
                continue
            seen.add(id(owner))
            try:
                owner.close()
            except Exception:                        # noqa: BLE001
                pass

    # ------------------------------------------------------------------ 内部
    def _grab(self):
        """拿一帧（ok-ww 的 ``next_frame()`` 会推进帧）。"""
        try:
            img = self.task.next_frame()
        except Exception as exc:                     # noqa: BLE001 - 测不了的那层
            self.log(f"取画面失败：{type(exc).__name__}: {exc}")
            return None
        return img if img is not None else None

    def _decide(self, fix):
        from ....core.explore_gap import at_end, decide   # noqa: PLC0415

        if at_end(self.state, len(self.library)):
            from ....core.explore_gap import Action       # noqa: PLC0415
            return Action(ActionKind.DONE, reason="已到参考末尾")
        return decide(fix, self.state, self.config,
                      library_len=len(self.library),
                      schedule=self.schedule)

    def _apply(self, action) -> None:
        """把动作变成真实输入。**这里不做任何判断。**"""
        kind = action.kind
        if kind is ActionKind.ADVANCE:
            self.stats["advance"] += 1
            self._advance()
        elif kind is ActionKind.CORRECT:
            self.stats["correct"] += 1
            self._turn(action.dx)
        elif kind is ActionKind.KEY:
            #: ★ 照视频按键 —— 「做一样的操作」就是这一步
            self.stats["keys"] += 1
            self._press(action)
        elif kind is ActionKind.WAIT:
            self.stats["wait"] += 1
        #: DONE / LOST 由主循环处理

    def _press(self, action) -> None:
        """照视频按一个键（含长按）。

        ## ⚠ 长按靠 ``down_time``，不是"按很多次"

        ok-ww 的 ``send_key(key, down_time=S)`` 语义是"按住 S 秒再松"。
        所以长按机关直接传大 ``down_time`` 就行；连按一百下是**错的**
        （游戏里表现为点了一百下，机关根本没被"按住"）。

        按完给一点缓冲 —— 机关触发 / 对话弹出都要时间，
        立刻取下一帧会拍到动画中间态，定位会抖。
        """
        if not action.key:
            return
        self._send(action.key, action.seconds)
        self.log(f"照视频按 {action.key.upper()}（{action.key_text}）"
                 f"{' 长按' if action.seconds > 0.5 else ''}")
        #: 长按之后多等一会儿（机关动画 / 对话弹出）
        self._sleep(max(FRAME_INTERVAL, action.seconds * 0.5))

    def _advance(self) -> None:
        """往前走一步。

        ⚠ ``state.index`` 的推进**不再由这里负责** ——
        ``decide`` 每帧用**定位结果**覆盖它（开环计数会漂：
        走快了/走慢了/被击退都会让它对不上视频，那样按键表就会在
        错的时间触发。见
        :class:`~src.core.explore_gap.controller.ExploreGapState`）。
        这里只负责按键。
        """
        self._send("w", 0.05)

    def _turn(self, dx: float) -> None:
        """转向纠偏。"""
        key, seconds = dx_to_turn(dx, px_per_sec=self.px_per_turn_sec)
        if not key:
            return
        self._send(key, seconds)

    def _send(self, key: str, seconds: float) -> None:
        """按一下键（失败不致命 —— 记一条继续）。"""
        try:
            self.task.send_key(key, down_time=max(0.01, float(seconds)))
        except Exception as exc:                     # noqa: BLE001
            self.log(f"按键 {key} 失败：{type(exc).__name__}: {exc}")

    def _sleep(self, seconds: float) -> None:
        try:
            self.task.sleep(seconds)
        except Exception:                            # noqa: BLE001
            time.sleep(seconds)


def calibration_steps(*, widths=(20, 40, 80)) -> list[tuple[str, float]]:
    """标定序列：让人量出"转 X 像素需要多久"。

    用法：把游戏画面停在一个有参照物的位置，依次执行这些步骤，
    每步后**目测**画面移动了多少像素，反推 ``PX_PER_TURN_SEC``。

    :return: ``[(键, 时长秒), ...]`` —— 逐步加长时间，方便找出
        "刚好转过去"的那个点

    > ⚠ 这是**手动**标定的兜底。优先用 :func:`calibrate_turn` ——
    > 它能自己量，不用人眼估。
    """
    steps = []
    for px in widths:
        key, seconds = dx_to_turn(px, max_sec=MAX_TURN_SEC)
        if key:
            steps.append((key, seconds))
    return steps


#: 自动标定用的按键时长（秒）。取三个点做线性拟合。
CALIBRATION_HOLDS = (0.10, 0.20, 0.35)

#: 标定用的按键（往一边转就行 —— 量的是"每个键各转多少度"，方向不影响）
CALIBRATION_KEY = "d"

#: 单次标定测量低于这个像素数就算不可靠（转动太小，噪声占比高）
MIN_CALIBRATION_SHIFT = 5.0

#: 拟合出的换算落在什么范围才算合理（秒/像素）。
#:
#: 实测参考值约 0.0012（1280 宽整屏 ≈ 1.5 秒）。给一个宽松但有意义的区间：
#: 太小说明几乎没转（测不到），太大说明游戏里按键根本不在转视角。
MIN_PX_PER_TURN_SEC = 1e-5
MAX_PX_PER_TURN_SEC = 0.05


def calibrate_turn(grab_frame, send_key, *, key: str = CALIBRATION_KEY,
                   holds=CALIBRATION_HOLDS,
                   log=None) -> tuple[float, list[tuple[float, float]]]:
    """★ **自动标定**「转动 1 像素需要多少秒」。

    ## 它解决什么（这是唯一会"乱走"的风险）

    ``PX_PER_TURN_SEC`` 取决于游戏灵敏度 / 鼠标 DPI / FOV，机器猜不出来。
    没标定就跑，机器会照着一个**错的换算**去转 —— 转不够就一直偏，
    转太多就来回甩。

    手动标定要人眼估像素，不准还麻烦。既然**测偏移**已经能做到
    亚像素精度（实测闭环残差最大 0.478px），那就直接用它量：

        ① 拍一帧 → 按键 H 秒 → 再拍一帧
        ② 用相位相关量出画面横移了多少像素
        ③ 换几个不同的 H 各做一次 → 线性拟合出 秒/像素

    :param grab_frame: 无参可调用，返回当前帧（BGR）；拿不到返回 ``None``
    :param send_key: ``(key, seconds)`` —— 真的按键
    :param key: 用哪个键标定（默认 ``"d"``，往右转）
    :param holds: 依次尝试的按住时长（秒）
    :param log: 可选日志函数

    :return: ``(px_per_turn_sec, samples)``，``samples`` 是
        ``[(按键秒数, 实测像素), ...]``，给界面显示/排查用

    ## ⚠ 失败时返回保守值而不是 0

    测不到（画面没动 / 全是噪声）说明环境不对（没进游戏 / 画面是静止 UI）。
    这时返回 **0.0** 并把样本带回去 —— 让调用方**明确知道没标定成功**，
    而不是塞一个瞎猜的数继续跑。调用方应该据此拒绝运行。

    ## 拟合怎么做的

    理论关系是线性的：``像素 = 按键秒数 / 秒每像素``。
    所以过原点最小二乘：``秒每像素 = Σ(h·px) / Σ(px²)`` 取倒数那侧 ——
    这里直接对 ``(px, h)`` 做过原点拟合得斜率 ``k = h/px``（秒/像素）。
    """
    samples: list[tuple[float, float]] = []
    for hold in holds:
        before = grab_frame()
        if before is None:
            if log:
                log(f"标定 {hold:.2f}s：拿不到画面，跳过")
            continue
        try:
            send_key(key, hold)
        except Exception as exc:                     # noqa: BLE001
            if log:
                log(f"标定按键失败：{type(exc).__name__}: {exc}")
            continue
        after = grab_frame()
        if after is None:
            if log:
                log(f"标定 {hold:.2f}s：按完拿不到画面，跳过")
            continue

        #: 量画面横移（复用生产的那套相位相关）
        from ....core.explore_gap.locator import Locator  # noqa: PLC0415

        loc = Locator(library=None)
        off = loc.phase_shift(before, after)
        if off is None:
            if log:
                log(f"标定 {hold:.2f}s：两张图对不上（画面变了？），跳过")
            continue
        dx, _dy, peak = off
        shift = abs(float(dx))
        if log:
            log(f"标定 {hold:.2f}s → 横移 {shift:.1f}px（可信度 {peak:.2f}）")
        if shift < MIN_CALIBRATION_SHIFT:
            if log:
                log(f"  转动太小（<{MIN_CALIBRATION_SHIFT}px），不计入")
            continue
        samples.append((hold, shift))

    if not samples:
        return 0.0, samples

    #: 过原点最小二乘：h ≈ k · px  →  k = Σ(h·px) / Σ(px²)
    num = sum(h * px for h, px in samples)
    den = sum(px * px for _h, px in samples)
    if den <= 0:
        return 0.0, samples
    k = num / den
    if not (MIN_PX_PER_TURN_SEC <= k <= MAX_PX_PER_TURN_SEC):
        if log:
            log(f"标定结果 {k:.6f} 秒/像素超出合理区间 —— 判定失败")
        return 0.0, samples
    return float(k), samples
