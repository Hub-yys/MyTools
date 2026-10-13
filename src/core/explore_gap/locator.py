# -*- coding: utf-8 -*-
"""定位 + 测偏离 + **可信度闸门** —— 整套方案的地基。

## 它回答两个问题

1. **我在视频第几秒？** → 拿当前画面在参考库里找最像的那一帧
2. **我偏了多少、往哪边偏？** → 拿那一帧和当前画面做相位相关

第 2 个才是纠偏的依据。"知道自己在第几秒"本身不够 ——
必须知道"我相对那一秒偏了多少"。

## ★★ 实测标定（2026-10-11，p4.mp4 27 分钟真实视频）

::

    可信度闸门 peak >= 0.05
      闸门内残差：中位 0.002 px   90分位 0.204 px   最大 1.814 px
      可用测量占比 71%

    按偏离量看通过率（S = 横向平移像素）：
        S      通过率    通过时最大残差
        3~10    100%      0.02~0.87 px
        15~40    92~96%   0.9~1.4 px
        60       72%      1.8 px
        120      28%      0.3 px
        160+     16~24%   0.2~0.4 px

## ⚠⚠ 闸门为什么是**安全阀**而不是精度调节

大偏离下相位相关会返回**垃圾值**（实测见过 1201.9px、743px 这种）。
如果不看 ``peak`` 直接采信，机器就会照着垃圾值猛转 —— **整条路线就毁了**。

闸门拦住 = "这一帧我看不准，等下一帧"。所以::

    通过率下降 ≠ 变差
    通过率下降 = 被拦下了 = 不会乱动 = 安全

**回路的工作点是"小偏离"**：3~40px 全部通过且残差 ~0。
它靠高频小幅纠偏维持，本来就不需要一次修掉大偏离 ——
真偏到 160px 以上（相当于视角转了小半屏），说明已经跟丢了，
那时正确的动作是**停下来报错**，不是硬纠。

## ⚠ 三条实测教训（写在代码旁边，别改回去）

**① 撤销用 ``-dx``。** 相位相关返回的是"第二张相对第一张"的位移，
   所以撤销要取负。第一版用了 ``+dx``，残差**恰好是初始偏离的 200%**。

**② ``peak`` 是运行时唯一能拿到的可信度信号。**
   "定位对不对"是事后才知道的标签，控制回路**没有**它。

**③ 建库用 ``degrade=""``，查询用 ``degrade="hard"``。**
   两边都用同一份图 = 自己跟自己比 = 必然 100% 命中（假结论）。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .descriptor import descriptor, similarity, world_region
from .locate import (
    ALIGNED_MARGIN_MIN,
    DEFAULT_WINDOW,
    MARGIN_MIN,
    locate_aligned,
    locate_windowed,
    should_relax,
)

#: ★ 可信度闸门（实测标定，见模块文档）。
#: 低于它 = 这一帧测不准，**必须放弃**。
PEAK_MIN = 0.05

#: 相位相关的搜索上限（像素）。
#: 超过它说明"这不是平移能解释的偏差"（换场景了 / 跟丢了），
#: 与其返回一个大得离谱的值，不如判定为无效。
MAX_SHIFT = 400.0


def peak_gate_ok(peak: float, threshold: float = PEAK_MIN) -> bool:
    """这一帧的测量能不能信。

    单独一个函数是因为**整个闭环的安全性都挂在它上面** ——
    要能单独测、单独调，而不是埋在某个类的方法里。
    """
    return peak >= threshold


@dataclass(frozen=True)
class Fix:
    """一次测量结果。"""

    #: 在参考库里的下标（第几个参考帧）
    index: int
    #: 参考帧号（原视频第几帧）
    frame: int
    #: 视频时间（秒）
    time_s: float
    #: 匹配相似度（余弦）
    similarity: float
    #: 最佳匹配与"远处第二名"的差距 —— 越大越不容易认错地方
    margin: float
    #: 横向偏离像素（把当前画面**移回**参考帧需要的量）
    dx: float
    #: 纵向偏离像素
    dy: float
    #: 相位相关峰值 = 可信度
    peak: float

    @property
    def trusted(self) -> bool:
        """这次测量可不可信（过没过闸门）。"""
        return peak_gate_ok(self.peak)

    @property
    def shift(self) -> float:
        """偏离量（像素，欧氏距离）。"""
        return float(np.hypot(self.dx, self.dy))


class Locator:
    """拿参考库做定位 + 测偏离。

    :param library: :class:`~.library.ReferenceLibrary`
    :param peak_min: 闸门阈值（默认实测值 0.05）
    :param window: 连续性搜索窗口（参考帧）；``0`` = 关闭（全库搜）
    :param margin_min: 独特性余量门槛（见 :mod:`.locate`）

    ## ★★ 为什么默认**开启**连续性约束

    实测（2026-10-11，192 个样本）只靠闸门会漏掉危险格::

        只用闸门    : 危险格 5   定位跑飞 23%   ← 会朝错方向纠偏
        连续性+闸门 : 危险格 0   定位跑飞  0%   ← 而且可用率更高（92% vs 72%）

    最恶劣的一例是"一帧之内从视频 10 分钟处跳到 21 分钟处"，
    但 ``peak=0.057`` 越过了闸门 —— 因为**别处的画面也能对得很齐**。
    闸门量的是"对齐质量"，连续性量的是"位置合理性"，两件事。

    :meth:`measure` 每次都会把 ``near`` 更新成刚定位到的下标，
    所以只要调用方每次喂相邻帧，约束就自然生效。
    """

    def __init__(self, library, *, peak_min: float = PEAK_MIN,
                 window: int = DEFAULT_WINDOW,
                 margin_min: float = ALIGNED_MARGIN_MIN):
        self.library = library
        self.peak_min = peak_min
        self.window = window
        self.margin_min = margin_min
        #: 汉宁窗缓存（相位相关要用；形状不变就复用）
        self._win = None
        #: ★ 上一帧的位置 —— 连续性约束的"我大概在哪"。
        #: ``None`` = 还没有上一帧（起点），此时退化成全库搜。
        self.near: int | None = None
        #: 连续在窗口内找不到的次数（用来决定要不要放宽，见 locate.should_relax）
        self.unclear_streak = 0
        #: 最近一次定位量到的对齐位移（决策层要它去纠偏）
        self.last_dx = 0.0
        self.last_dy = 0.0

    def reseat(self, index: int | None) -> None:
        """手动设定"我大概在哪"（重定位、切段时用）。"""
        self.near = index
        self.unclear_streak = 0

    # ------------------------------------------------------------------ 定位
    def locate(self, frame) -> tuple[int, float, float] | None:
        """定位 —— **先对齐再打分**（大偏航下也能认准地方）。

        :return: ``(参考库下标, 对齐后得分, 对齐后余量)``；没认准返回 ``None``

        ⚠ **不会**更新 :attr:`near` —— 只有 :meth:`measure` 会。
        这样单独调 ``locate`` 做诊断时不会把状态搞乱。

        ## 为什么不用"原始相似度选最佳"

        相关型描述子不是平移不变的：画面横移 80px 时，**真值那一帧**的
        相似度从 0.99 掉到 0.93，而别处的帧本来就在 0.92 —— 余量被压没，
        于是认不出地方。实测命中率：80px 偏航下只有 **18%**。

        :func:`~.locate.locate_aligned` 把候选搬回去再打分（平移不变），
        同一条件下 **100%**。代价是每个候选多一次相位相关。
        """
        near = self.near
        #: 连续找不到就放宽一次（从"被传送走"里恢复）
        if should_relax(self.unclear_streak):
            near = None
        got = locate_aligned(self.library, frame, near=near,
                             window=self.window,
                             margin_min=self.margin_min,
                             phase_shift=self.phase_shift)
        if got is None:
            return None
        index, score, margin, dx, dy = got
        self.last_dx, self.last_dy = dx, dy
        return index, score, margin

    # ------------------------------------------------------------------ 测量
    def measure(self, frame, *, ref_frame=None) -> Fix | None:
        """定位 + 测偏离，一次给全。

        :param frame: 当前画面（BGR）
        :param ref_frame: 已知参考帧时直接给（省一次 seek）；不给就自己定位

        :return: :class:`Fix`；定位或测量失败返回 ``None``

        ## 副作用（**这就是连续性约束怎么生效的**）

        定位成功时把 :attr:`near` 更新成刚定位到的下标 —— 下一次
        :meth:`locate` 就在它附近搜。所以**只要按顺序喂帧**，
        约束自然生效，调用方不需要额外做什么。

        ⚠ 定位失败时 ``near`` **保持不变**（不是清空）—— 一次没认出来
        不代表位置变了，清空会退化成全库搜、把之前的约束丢掉。
        """
        if ref_frame is None:
            found = self.locate(frame)
            if found is None:
                self.unclear_streak += 1
                return None
            index, sim, margin = found
            ref_frame = self.library.frame_image(index)
        else:
            index, sim, margin = -1, float("nan"), float("nan")

        if ref_frame is None:
            self.unclear_streak += 1
            return None

        off = self.phase_shift(ref_frame, frame)
        if off is None:
            self.unclear_streak += 1
            return None
        dx, dy, peak = off

        if index >= 0:
            self.near = index                    #: ★ 更新连续性锚点
            self.unclear_streak = 0

        return Fix(
            index=index,
            frame=self.library.frames[index] if index >= 0 else -1,
            time_s=self.library.time_of(index) if index >= 0 else float("nan"),
            similarity=sim,
            margin=margin,
            dx=dx,
            dy=dy,
            peak=peak,
        )

    def phase_shift(self, ref_frame, frame):
        """两张帧之间的平移（相位相关 + 汉宁窗）。

        :return: ``(dx, dy, peak)``；形状不符或位移超界返回 ``None``

        ⚠ ``dx`` 是"把 ``frame`` 对齐到 ``ref_frame``"需要的平移 ——
        也就是**撤销**偏离要施加的量（见模块文档教训 ①）。

        ## ★★ 分辨率不再要求一致（2026-10-11 修的真 bug）

        原来这里第一句是 ``if a.shape != b.shape: return None``，
        而 ``world_region`` 按比例裁原图 → **尺寸跟着分辨率变**。
        于是**游戏分辨率 ≠ 视频分辨率时，相位相关每次必返回 None**，
        定位必定失败（实测：真机 1536x864 vs 视频 1280x720）。

        现在 ``world_region`` 输出**恒定的规范尺寸**，形状永远一致。

        ## ⚠ 返回值已换算回**当前帧**的像素

        相位相关在规范尺寸上量位移，但调用方要的是"当前画面偏了多少
        真像素"，好交给 ``PX_PER_TURN_SEC``（真机分辨率下标定的）
        去换算转向时长。所以这里乘上 ``phase_scale``。

        ⚠ 两张图分辨率不同时，**以 ``frame`` 为准** ——
        要动的是当前画面，不是参考帧。
        """
        cv2 = _cv2()

        a = world_region(ref_frame)
        b, (sx, sy) = world_region(frame, with_scale=True)
        if a is None or b is None or a.shape != b.shape:
            return None
        if self._win is None or self._win.shape != a.shape:
            self._win = cv2.createHanningWindow((a.shape[1], a.shape[0]),
                                                cv2.CV_32F)
        (dx, dy), peak = cv2.phaseCorrelate(a * self._win, b * self._win)
        #: ★ 规范尺寸 → 本帧像素
        dx, dy = float(dx) * sx, float(dy) * sy
        peak = float(peak)
        if abs(dx) > MAX_SHIFT or abs(dy) > MAX_SHIFT:
            return None
        return dx, dy, peak


def _far_margin(sims: np.ndarray, best: int, *, exclude: int) -> float:
    """最佳成绩 减 **远处**第二名。"""
    far = [float(s) for j, s in enumerate(sims) if abs(j - best) > exclude]
    if not far:
        return float(sims[best])
    return float(sims[best]) - max(far)


def _cv2():
    """复用 descriptor 的延迟导入缓存。"""
    from .descriptor import _cv2 as inner       # noqa: PLC0415

    return inner()
