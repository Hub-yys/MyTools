# -*- coding: utf-8 -*-
"""**带连续性约束 + 先对齐再打分**的定位。

## ★★ 为什么需要它（2026-10-11 实测抓到的安全洞）

只靠描述子相似度 + 相位相关闸门**不够**。交叉表实测（155 个样本）::

    定位错 **且** 过了闸门 = 12 个

最恶劣的一例::

    anchor#3106  S=60  定位到 #2374   peak=0.057   dx=+0.2

#3106 与 #2374 差 **1272 个参考帧 ≈ 10.6 分钟** —— 一帧之内从视频
10 分钟处"跳"到 21 分钟处，物理上不可能。但 ``peak=0.057`` 越过了
0.05 的闸门，于是它给出的 ``dx=+0.2``（真值 +60）会被采信 ——
**机器朝完全错误的方向纠偏**。

### 为什么闸门堵不住

闸门量的是"**这两张图能不能对齐**"，不是"**这两张图是不是同一个地方**"。
开放世界到处是相似的海岸线/草地，别处的帧当然也能对得很齐。

**两个信号量的是两件不同的事**，缺一不可::

    相似度/peak  →  这一帧匹配得**齐不齐**（局部质量）
    连续性/余量   →  这个位置**合不合理**（全局一致性）

## ★★ 核心：先对齐，再打分（``locate_aligned``）

相关型描述子**不是平移不变的**，这是"大偏航就认不出地方"的根因::

    画面横移 80px 后，与**真值那一帧**的相似度：0.99 → 0.93
    而"别处"的帧本来就在 0.92 上下
    → 余量被压到 0.015，认不出来了

实测命中率（40 帧连续画面）::

    偏航     原始相似度     先对齐再打分
      0px       90%           100%
     20px       82%           100%
     45px       67%           100%
     60px       44%           100%
     80px       18%           100%

修法：不再拿"原始相似度"定最佳，而是

① 取相似度 top-K 候选
② 每个候选做一次相位相关，量出 shift
③ ★ **把查询画面按 shift 搬回去**，再算相似度
④ 谁"搬回去之后"最像，谁才是真位置

对齐之后的相似度是**平移不变**的：真值那一帧回到 ~0.97，
别处的帧对齐后依然不像（余量 0.015 → 0.064，翻了 4 倍）。

代价：每个候选多一次相位相关（K 次）。K=5 时慢几倍，
换来的是"大偏航也能启动"—— 没有它，45px 起步的回路**永远启动不了**
（鸡生蛋：要纠偏得先量准，要量准得先不偏）。

## 连续性约束：把搜索限制在"我可能到得了的地方"

控制器**知道自己上一帧在哪**。正常行走时位置是连续的，一帧最多前进
几个参考帧。所以把候选限制在 ``[near - window, near + window]``，
"跳到 10 分钟外"从根上不可能发生。

顺带还快：3280 个候选 → 窗口内 60 个。

## ⚠ 两个必须处理的边界

**① 起点没有"上一帧"。**
   第一次定位时 ``near=None`` → **退化成全库搜索**（不能瞎限）。
   所以起步阶段仍然可能跳飞 —— 这是为什么 :func:`locate_near`
   在无约束时会把 ``windowed=False`` 标出来，让调用方能区别对待。

**② 跟丢之后不能永远困在窗口里。**
   如果真被击退/传送走了，位置会跳到窗口外。所以连续
   ``relax_after`` 次在窗口内找不到可信匹配时，**放宽到全库**再试一次
   （宁可冒一次跳飞风险，也不能永远找不回来）。
"""

from __future__ import annotations

import numpy as np

from .descriptor import descriptor, similarity

#: 默认搜索窗口（参考帧）。±30 帧 = ±15 秒。
#:
#: 为什么是 30：正常行走 0.5 秒最多走过几个参考帧的距离，
#: 30 留了约 10 倍余量；同时它足够小，能挡掉"10 分钟外"那种跳飞。
DEFAULT_WINDOW = 30

#: 连续多少次窗口内找不到就放宽到全库
RELAX_AFTER = 5

#: ★ 独特性余量门槛 —— "最佳匹配比远处的第二名强多少"。
#:
#: ## 为什么要它（实测，2026-10-11）
#:
#: 诊断跑出两组数据的余量差得很开::
#:
#:     定位准（≤±2 参考帧）: 相似度 0.9716   余量 0.0414
#:     定位错（>±2 参考帧） : 相似度 0.9304   余量 0.0051
#:
#: 余量差了 **8 倍** —— 它比相似度更能说明"是不是认错了地方"。
#: 光靠相似度不行：开放世界里"别处"的帧也能有 0.93 的相似度。
#:
#: ## ⚠⚠ 这个数在 2026-10-11 重标过（描述子改成减均值之后）
#:
#: 上面那组数字是**旧度量**（只做 L2 归一化）下测的 —— 那时
#: "无关帧"也能拿 0.83 的相似度，整条曲线被压缩在 0.83~0.95 之间，
#: 所以余量尺度很小（0.01 这个阈值就是那么来的）。
#:
#: 描述子**减均值**之后，分布完全变了（实测 4078 帧、各 400 样本）::
#:
#:     「对」的余量：中位 0.4434   25% 分位 0.3396   5% 分位 0.0013
#:     「错」的余量：中位 -0.6895  95% 分位 -0.4789  **最大 -0.0001**
#:
#: **两组几乎不重叠** —— "错"的那组余量全是负的。
#: 阈值扫描（``_probe/sweep.py``）::
#:
#:     阈值    漏(对的被打掉)   错(错的被放过)
#:     0.000       0.0%            0.0%
#:     0.010       6.8%            0.0%
#:     0.020       7.3%            0.0%
#:
#: 取 **0.02**：错的放过率 0%，对的漏掉 7.3%（可用率损失可接受）。
#: 这个取舍和项目一贯的"**宁可漏，不可错**"一致 ——
#: 漏的代价是"这一帧不用"（下一帧再来），
#: 错的代价是"朝错方向走"（整条路线报废）。
MARGIN_MIN = 0.02


def locate_windowed(library, frame, *, near: int | None,
                    window: int = DEFAULT_WINDOW,
                    exclude: int = 20,
                    margin_min: float = MARGIN_MIN
                    ) -> tuple[int, float, float] | None:
    """在 ``near`` 附近搜最像的一帧（双重把关：连续性 + 独特性）。

    :param library: :class:`~.library.ReferenceLibrary`
    :param frame: 当前画面（BGR）
    :param near: 上一帧的位置下标；``None`` = 无约束（全库搜）
    :param window: 搜索半径（参考帧）
    :param exclude: 算"独特性余量"时排除多近的邻居
    :param margin_min: 独特性余量门槛；**过了它才算认准了地方**

    :return: ``(下标, 相似度, 独特性余量)``；没认准返回 ``None``

    ## 三重把关，各管一件事
    ::

        连续性（window）  →  位置**合不合理**（挡掉"跳到 10 分钟外"）
        余量（margin_min）→  地方**认没认准**（挡掉"别处也长这样"）
        相位相关 peak     →  这一帧**对不对得齐**（在 locator 里）

    ⚠ 两个信号量的是**不同**的东西，缺一不可：闸门量的是"两张图能不能
    对齐"，连续性/余量量的是"这两张图是不是同一个地方"。开放世界里
    别处的帧当然也能对得很齐 —— 所以光有闸门会漏。

    ## 什么时候会退化成全库搜

    * ``near is None``（起点 —— 还没有"上一帧"）
    * ``window <= 0``（调用方明确要求全库）
    * 窗口里一帧都没有（库太短 / near 出界）
    """
    q = descriptor(frame, degrade="hard")
    if q is None or len(library) == 0:
        return None

    total = len(library)
    lo, hi = 0, total
    if near is not None and window > 0:
        lo = max(0, int(near) - int(window))
        hi = min(total, int(near) + int(window) + 1)
        if hi <= lo:
            lo, hi = 0, total                    #: 窗口空 → 退回全库

    sims = similarity(library.matrix[lo:hi], q)
    local_best = int(np.argmax(sims))
    best = lo + local_best
    best_sim = float(sims[local_best])
    #: 独特性余量按**全库**算 —— 只按窗口算会高估
    #: （窗口外的相似帧同样是"认错地方"的风险）
    all_sims = similarity(library.matrix, q)
    margin = _far_margin(all_sims, best, exclude=exclude)
    if margin < margin_min:
        return None                              #: ★ 认不准 → 当没测到
    return best, best_sim, margin


def _far_margin(sims: np.ndarray, best: int, *, exclude: int) -> float:
    """最佳成绩 减 **远处**第二名。"""
    far = [float(s) for j, s in enumerate(sims) if abs(j - best) > exclude]
    if not far:
        return float(sims[best])
    return float(sims[best]) - max(far)


def should_relax(unclear_streak: int, *, after: int = RELAX_AFTER) -> bool:
    """窗口内连续失败这么多次之后，该放宽到全库试一次。

    ⚠ 别把它做成"一直放宽" —— 那就等于没有连续性约束了。
    放宽是**例外**，用来从"被传送走"这种状态里恢复。
    """
    return unclear_streak > 0 and unclear_streak % after == 0


#: 先对齐再打分时取几个候选。
#:
#: K=5 是"够用"和"别太慢"之间的折中：真值那一帧在原始相似度里
#: 通常排前 5（实测），再往后就都是完全不相干的地方了。
TOP_K = 5

#: 对齐后，候选之间必须拉开这么多分差才算"认准了地方"。
#:
#: ## ⚠⚠ 2026-10-11 重标（描述子减均值 + 修掉分辨率 bug 之后）
#:
#: 旧值 0.02 是在旧度量下定的，重标后实测（库 4078 帧、各 30 样本）::
#:
#:     「对」余量：中位 0.4596  25% 0.3217  5% 0.1908
#:     「错」余量：中位 0.0678  95% 0.2505  **max 0.3628**
#:
#: 扫描::
#:
#:     阈值    漏        错
#:     0.02   0.0%     80.0%
#:     0.10   3.3%     26.7%
#:     0.15   3.3%     **10.0%**
#:     0.20  10.0%      6.7%
#:
#: 取 **0.15**：漏 3.3%、错 10%。再往上（0.20）漏就涨到 10% 了，
#: 不划算。
#:
#: ## ⚠⚠ 但要清楚：这个门槛**挡不住"所有候选都错"**
#:
#: 余量是"最佳 减 第二名"，而第二名是从**同一个窗口**里选出来的。
#: 如果窗口整体落在错的地方，5 个候选**全错**，余量照样能拉开 ——
#: 上面的"错"组 max 0.3628 就是这么来的。
#:
#: → **余量管的是"几个候选里认没认准"，管不了"这几个候选是不是都在错的地方"。**
#:   后者由**绝对分数**和相位相关 ``peak`` 闸门负责（实测"对"的绝对分
#:   是 0.9999 量级，而"错"的只有 0.12~0.39 —— 那个分得比余量干净得多）。
#:
#: ⚠ 给对齐路径加一道**绝对分数门槛**是个待定的设计改动，
#:   不在这一轮里做（要先和用户确认）。
ALIGNED_MARGIN_MIN = 0.15


def locate_aligned(library, frame, *, near: int | None,
                   window: int = DEFAULT_WINDOW,
                   top_k: int = TOP_K,
                   margin_min: float = ALIGNED_MARGIN_MIN,
                   exclude: int = 5,
                   phase_shift=None,
                   max_shift: float = 300.0,
                   ) -> tuple[int, float, float, float, float] | None:
    """★ **先对齐再打分**的定位 —— 大偏航下也能认准地方。

    :param library: :class:`~.library.ReferenceLibrary`
    :param frame: 当前画面（BGR）
    :param near: 上一帧位置；``None`` = 全库候选
    :param window: 连续性搜索半径
    :param top_k: 取原始相似度的前几名做对齐复评
    :param margin_min: 对齐后的余量门槛
    :param exclude: 算余量时排除多近的下标（同一个地方的邻居）
    :param phase_shift: 注入的相位相关函数 ``(ref, frame) -> (dx, dy, peak)``；
        不给就用 :class:`~.locator.Locator` 的默认实现。
        **参数化是为了单测能喂假的**，不必真跑 cv2。
    :param max_shift: 对齐位移超过它就丢弃该候选（明显不是平移关系）

    :return: ``(下标, 对齐后得分, 对齐后余量, dx, dy)``；认不准返回 ``None``

    ## ⚠⚠ 源视频必须还在

    对齐这一步要拿**候选的原图**（``library.frame_image(idx)``）做相位相关。
    而参考库**只存描述子**（21.8MB），原图是回源视频 seek 取的 ——
    所以**源视频文件不能动**（改名 / 删掉 / 移走都会让定位直接失效，
    表现是"什么都认不出来"、返回 ``None``）。

    :meth:`~.library.ReferenceLibrary.save` 里存了 ``src`` 路径就是为这个。
    视频不在时 ``frame_image`` 返回 ``None`` → 所有候选被跳过 → 返回 ``None``
    （**不报错**，所以是个容易查很久的坑）。

    ## 为什么必须"搬回去再打分"

    相关型描述子不是平移不变的 —— 画面横移会让**真值那一帧**的相似度
    从 0.99 掉到 0.93，而别处的帧本来就在 0.92，余量被压没。
    把查询画面按量出的 shift 搬回去之后，真值回到 ~0.97、
    别处依然不像，余量翻 4 倍（0.015 → 0.064）。

    实测命中率：80px 偏航下 18% → **100%**。
    """
    from .descriptor import descriptor as _desc        # noqa: PLC0415

    q = _desc(frame, degrade="hard")
    if q is None or len(library) == 0:
        return None

    total = len(library)
    lo, hi = 0, total
    if near is not None and window > 0:
        lo = max(0, int(near) - int(window))
        hi = min(total, int(near) + int(window) + 1)
        if hi <= lo:
            lo, hi = 0, total

    sims = similarity(library.matrix[lo:hi], q)
    order = np.argsort(-sims)
    #: 挑候选：彼此至少要隔开 ``exclude`` 个下标，否则等于同一个位置
    cands: list[int] = []
    for j in order:
        idx = lo + int(j)
        if all(abs(idx - c) > exclude for c in cands):
            cands.append(idx)
        if len(cands) >= max(1, top_k):
            break

    if phase_shift is None:
        phase_shift = _default_phase_shift()

    import cv2                                          # noqa: PLC0415

    h, w = frame.shape[:2]
    scored: list[tuple[int, float]] = []
    for idx in cands:
        ref_img = library.frame_image(idx)
        if ref_img is None:
            continue
        off = phase_shift(ref_img, frame)
        if off is None:
            continue
        dx, dy, _peak = off
        if abs(dx) > max_shift or abs(dy) > max_shift:
            continue
        #: ★ 把查询画面搬回去（施加 -dx），再算相似度 —— 平移不变
        M = np.float32([[1, 0, -dx], [0, 1, -dy]])
        fixed = cv2.warpAffine(frame, M, (w, h),
                               borderMode=cv2.BORDER_REPLICATE)
        qf = _desc(fixed, degrade="hard")
        if qf is None:
            continue
        scored.append((idx, float(library.matrix[idx] @ qf)))

    if not scored:
        return None

    scored.sort(key=lambda kv: -kv[1])
    best_idx, best_score = scored[0]
    #: 余量 = 最佳 减 第二名（都是"对齐后"的分，可比）
    second = scored[1][1] if len(scored) > 1 else 0.0
    margin = best_score - second
    if margin < margin_min:
        return None

    #: 顺手把对齐位移再量一次（决策层要 dx 去纠偏）
    ref_img = library.frame_image(best_idx)
    off = phase_shift(ref_img, frame) if ref_img is not None else None
    dx, dy = (off[0], off[1]) if off is not None else (0.0, 0.0)
    return best_idx, best_score, margin, float(dx), float(dy)


def _default_phase_shift():
    """默认的相位相关实现（延迟构造，避免循环 import）。"""
    from .locator import Locator                          # noqa: PLC0415

    inst = Locator(library=None)

    def shift(ref_frame, frame):
        return inst.phase_shift(ref_frame, frame)

    return shift
