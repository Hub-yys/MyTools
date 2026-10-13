# -*- coding: utf-8 -*-
"""一帧 → 定长向量（描述子）。

## 为什么是这个尺寸（128x72）

实测（``_vid/follow_log.txt``）::

    描述子 128x72，保留像素 5468 (59%)

128x72 是 16:9 里最小还能保住地形特征的尺寸。再小描述子就不足以
区分"两个都长草的地方"；再大则建库变慢（3280 帧的矩阵已经是
3280x9216）。

## ★ 为什么必须遮住 UI

游戏画面里**大部分区域是 UI**（血条、技能键、小地图、任务列表），
它们**每一帧都在变**（血量、CD、任务进度），拿它们做匹配等于拿噪声
当特征 —— 实测会让"同一个地方"的相似度掉到 0.87 以下。

所以只在**大世界画面**上算描述子。遮罩范围是从抽帧实测出来的
（见 :func:`mask_of` 的注释）。

## ⚠ 不变性

描述子是**归一化**的（L2），所以::

    相似度 = REF @ q      ← 就是余弦相似度，值域 [-1, 1]

归一化同时消掉了**整体亮度**变化（显示器/录制差异），
这也是它能扛住"去水印+压缩+模糊+亮度"四种扰动的原因。
"""

from __future__ import annotations

import numpy as np

#: 描述子宽（16:9 → 128x72）
DW = 128
#: 描述子高
DH = 72

#: cv2 的延迟导入缓存。
#:
#: ⚠ **不在模块顶层 import cv2** —— 项目里 cv2 只在两个函数内部延迟导入
#: （``echo_enhance/prepare.py``），因为它是重依赖且那两条路径都可能
#: 失败。这里跟同一套写法：第一次用到才 import，之后走缓存。
#: （PyInstaller 的 hook-cv2 靠**静态分析**能看见函数内的 import，所以
#:  打包不受影响 —— 见 ``packaging/mytools.spec`` 的说明。）
_CV2 = None


def _cv2():
    """取 cv2（第一次调用时才真正 import）。"""
    global _CV2
    if _CV2 is None:
        import cv2                               # noqa: PLC0415

        _CV2 = cv2
    return _CV2

#: UI 遮罩（只保留大世界画面）
#:
#: 范围从抽帧实测（1280x720 按 0.1 换算到 128x72）：
#:
#: * ``y < 6``      顶部图标条
#: * ``y > 57``     底部 HUD（血条 / 技能 / 进度条）
#: * ``x > 118``    右侧队伍与角色图标
#: * ``x<30 & y<30`` 左上小地图 + UP 水印
def mask_of() -> np.ndarray:
    """造 UI 遮罩（``(DH, DW)`` 的 bool 数组，True = 保留）。"""
    m = np.zeros((DH, DW), dtype=bool)
    ys, xs = np.mgrid[0:DH, 0:DW]
    keep = (ys >= 6) & (ys <= 57) & (xs <= 118) & ~((xs < 30) & (ys < 30))
    m[keep] = True
    return m


#: 模块级共享（只读，别改）
MASK = mask_of()


def descriptor(frame, *, degrade: str = "") -> np.ndarray | None:
    """一帧 → 归一化向量（只在 :data:`MASK` 内计算）。

    :param frame: BGR 图（``numpy`` 数组）。``None`` 返回 ``None``。
    :param degrade: ``""`` 原图 / ``"hard"`` 模拟"我的游戏画面"：
        去水印 + 亮度微调 + 轻微模糊 + JPEG 压缩。

        ⚠ **建库和查询必须用不同的 degrade**，否则就是自己跟自己比
        （``follow.py`` 那个"100% 命中"就是这么来的假结论）。
        正确做法：建库用 ``""``，查询用 ``"hard"``。

    :return: 长度 ``DW*DH`` 的归一化 float32 向量；全黑/无纹理帧返回 ``None``

    ## ★★ 为什么必须先**减均值**（2026-10-11 真机测出来的）

    原来的实现只做 L2 归一化::

        v = np.where(MASK, gray, 0.0)      # 灰度 0~255，**全非负**
        return v / |v|

    L2 归一化只消掉**乘性**亮度差（``v`` 和 ``2v`` 同向），
    **消不掉加性直流分量**。而自然画面的灰度均值很大
    （实测库内中位 82.4、真机帧 103.4）—— 于是所有向量都偏向
    "全 1 方向"，**余弦相似度被整体亮度主导**。

    合成实验（决定性）::

        竖条纹 vs 横条纹（内容正交）   原版 0.5024   ZNCC 0.0000
        纯灰 100 vs 纯灰 200（无内容） 原版 1.0000   ← 满分！

    **纯色对比能拿满分** —— 说明这个度量根本没在量"内容"。

    真机后果（实测）：用户在广场站着，查全库得到::

        最高 0.9096   中位 0.8093      ← 分布是平的，没有一帧突出
        "最像"的是视频 20.4 分钟处一张**地图界面**（与广场毫无关系）

    库里"相距 >500 帧（内容无关）"的帧对中位相似度 **0.8269**，
    而"相距 1 帧"只有 0.9489 —— **差 0.12，分不开**。

    修法就是**减均值**（零均值归一化 = ZNCC 的那一步）::

        v = v - mean(v)      # 量"明暗结构"（地形/边缘），而不是整体亮度
        return v / |v|

    改完实测跨度（最高-中位）从 **0.1002 → 0.4368**，翻了 4.4 倍。

    ## ⚠ 为什么之前一直没发现

    离线验收是**开卷考试**：用视频自己的帧查自己的库。查询帧和参考帧
    来自同一个视频，亮度/色调/UI 完全一致 —— 直流分量在两边**是同一个值**，
    它反而"帮忙"了，所以命中率一直显示 94.8%。
    一旦换成真机画面（显示器不同、有 HUD、亮度有差），它立刻变成噪声。

    ## ⚠ 均值只对**遮罩内**像素求

    遮罩外的像素恒为 0。若对整个 ``DW*DH`` 向量求均值，
    均值会被那 41% 的 0 稀释，减完还会在遮罩外**留下一个非零常数**
    —— 那块本来不该有任何贡献。所以均值只在遮罩内求、
    也只在遮罩内减，遮罩外保持 0。
    """
    if frame is None:
        return None

    f = frame
    if degrade:
        f = _degrade(f)

    cv2 = _cv2()
    small = cv2.resize(f, (DW, DH), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).astype(np.float32)

    inside = gray[MASK]
    #: ★ 减均值：去掉直流分量，只留"明暗结构"。
    #: 无纹理（全平）的帧减完全是 0 —— 范数为 0，返回 None 是对的：
    #: 一张纯色图**没有任何可用于定位的信息**。
    centered = inside - float(inside.mean())

    v = np.zeros(DH * DW, dtype=np.float32)
    v[MASK.ravel()] = centered
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-6 else None


def _degrade(frame):
    """模拟真实采集链路的损失（水印 / 亮度 / 压缩 / 缩放）。"""
    cv2 = _cv2()

    f = frame.copy()
    #: ① 抹掉 UP 水印 —— 真实场景里"我的画面"上没有它
    #:    ⚠ 只在帧够大时做（小图越界）
    if f.shape[0] >= 100 and f.shape[1] >= 400:
        f[0:90, 0:300] = int(f[60:100, 300:400].mean())
    #: ② 亮度微调（显示器 / 录制差异）
    f = cv2.convertScaleAbs(f, alpha=1.06, beta=-6)
    #: ③ 轻微模糊（压缩 / 缩放损失）
    f = cv2.GaussianBlur(f, (3, 3), 0)
    #: ④ JPEG 压缩
    ok, enc = cv2.imencode(".jpg", f, [cv2.IMWRITE_JPEG_QUALITY, 55])
    if ok:
        f = cv2.imdecode(enc, cv2.IMREAD_COLOR)
    return f


#: 相位相关用的**规范尺寸** ``(宽, 高)``。
#:
#: ## ⚠⚠ 为什么必须固定（2026-10-11 真机测出来的真 bug）
#:
#: :func:`world_region` 原来是**按比例裁原图**的 ——
#: 于是裁出来的尺寸**跟着输入分辨率变**::
#:
#:     视频 1280x720   → (510, 1180)
#:     真机 1536x864   → (612, 1416)     ← 形状不同！
#:     1080p           → (765, 1770)
#:
#: 而 :meth:`Locator.phase_shift` 第一句就是::
#:
#:     if a.shape != b.shape:
#:         return None
#:
#: → **只要游戏分辨率和视频分辨率不一样，相位相关每次必返回 None**，
#: 所有候选被跳过，定位**必定失败** —— 而且和"人在不在路线上"无关。
#: 实测：真机帧走对齐路径连门槛放到最低都返回 None。
#:
#: 修法：两边都缩放到这个**固定尺寸**再相关。只要宽高比一致，
#: 缩放不引入形变（本项目的裁剪区宽高比恒为 1180/510 ≈ 2.314）。
#:
#: ⚠ 缩放之后量出来的 ``dx``/``dy`` 是**规范尺寸**上的像素，
#: 必须按 :func:`phase_scale` 换算回**当前帧自己的**像素 ——
#: 否则执行器的"像素 → 转向时长"换算（``PX_PER_TURN_SEC``，
#: 那是在真机分辨率下标定的）会整体偏掉。
PHASE_CANON = (1180, 510)

#: 规范尺寸的宽 / 高（拆开写方便下面用）
_CANON_W, _CANON_H = PHASE_CANON


def crop_box(frame) -> tuple[int, int, int, int]:
    """遮罩对应的**大世界区域**在全分辨率原图上的像素框。

    :return: ``(x0, y0, x1, y1)``

    左上角（小地图 + 水印）不在框里 —— 那块每帧都变，留着会污染相关。
    比例和 :data:`MASK` 一致（``y 6~57``、``x 0~118``）。
    """
    h, w = frame.shape[:2]
    return (0, int(6 / DH * h), int(118 / DW * w), int(57 / DH * h))


def phase_scale(frame) -> tuple[float, float]:
    """规范尺寸 → **本帧像素** 的换算系数 ``(sx, sy)``。

    用法：``dx_本帧 = dx_规范 * sx``。
    """
    x0, y0, x1, y1 = crop_box(frame)
    return ((x1 - x0) / _CANON_W, (y1 - y0) / _CANON_H)


def world_region(frame, *, with_scale: bool = False):
    """裁出大世界画面（灰度 float32）—— 给相位相关用。

    相位相关需要比 128x72 更高的分辨率才能给出亚像素精度，
    所以它吃原图，不吃描述子。

    左上角（小地图 + 水印）**填 0**：那块每帧都变，留着会污染相关。

    ★ 输出**恒定**是 :data:`PHASE_CANON`（与输入分辨率无关）——
    这是"游戏分辨率 ≠ 视频分辨率也能定位"的关键，见该常量的说明。

    :param with_scale: 同时返回 ``(sx, sy)``（规范 → 本帧像素的换算）
    :return: 灰度图；``with_scale=True`` 时返回 ``(灰度图, (sx, sy))``
    """
    cv2 = _cv2()

    x0, y0, x1, y1 = crop_box(frame)
    g = cv2.cvtColor(frame[y0:y1, x0:x1],
                     cv2.COLOR_BGR2GRAY).astype(np.float32)
    #: 左上小地图 + UP 水印 —— 按比例填 0
    h, w = frame.shape[:2]
    g[: int(30 / DH * h) - y0, : int(30 / DW * w) - x0] = 0.0
    #: ★ 缩放到固定规范尺寸（宽高比一致 → 无形变）
    if (g.shape[1], g.shape[0]) != PHASE_CANON:
        g = cv2.resize(g, PHASE_CANON, interpolation=cv2.INTER_AREA)
    if with_scale:
        return g, ((x1 - x0) / _CANON_W, (y1 - y0) / _CANON_H)
    return g


def similarity(ref_matrix: np.ndarray, query: np.ndarray) -> np.ndarray:
    """``REF @ q`` —— 归一化向量点积 = 余弦相似度。

    单独拎出来是为了**只有一个地方**知道"相似度怎么算" ——
    建库那边和查询那边要是算法不一致，就会出现"对不上"却查不出原因。
    """
    return ref_matrix @ query
