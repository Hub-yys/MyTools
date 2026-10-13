# -*- coding: utf-8 -*-
"""参考库 —— 把视频变成"可查询的一串画面"。

## 它是什么

从一段视频里**每隔 0.5 秒**抽一帧，算成描述子存起来::

    实测：p4.mp4（27.3 分钟）→ 3280 个参考帧 → 矩阵 (3280, 9216)
          建库耗时 73 秒

之后 :class:`~.locator.Locator` 就能拿当前画面在它里面查"我在第几秒"。

## ★ 为什么建库用原图、查询用扰动图

`follow.py` 报过"100% 命中"，但它是**自己跟自己比**（查询帧就是
参考库里那一帧）。那不是定位，是自比对，必然 100% —— 证明不了任何东西。

正确的分工：

============================  ==================  ==========================
阶段                            degrade             为什么
============================  ==================  ==========================
**建库**（存参考）              ``""``              参考是"干净的标准答案"
**查询**（当前画面）            ``"hard"``          真实画面有水印/压缩/亮度差
============================  ==================  ==========================

## 存储格式

``.npz``（numpy 压缩），几个小文件而不是一个大文件::

    matrix       (M, D) float32   归一化描述子矩阵
    frames       (M,)   int32     原视频帧号
    fps          ()     float32   原视频帧率（算时间用）
    step         ()     int32     抽帧间隔
    src          字符串            源视频路径（仅供显示/追溯）

⚠ **不存原始帧**：3280 帧原图要好几 GB。需要某一帧时按帧号回源视频
seek（:meth:`ReferenceLibrary.frame_image`）—— 慢一点，但库文件只有几十 MB。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .descriptor import DH, DW, descriptor

logger = logging.getLogger(__name__)

#: 抽帧间隔（帧）—— 实测 0.5 秒一个够用（±0.25s 定位精度）
REF_STEP = 15

#: 库文件格式版本（改了描述子/结构就 +1，读的时候能拒绝旧文件）
#:
#: ## 版本 2 → 3：描述子改成**减均值**（2026-10-11 真机测出来的）
#:
#: 旧库里的 ``matrix`` 是"只做 L2 归一化"的向量，新代码查它算出来的
#: 相似度**没有意义**（新旧向量不在同一空间）。
#:
#: ⚠ 这种不匹配**不会报错** —— ``REF @ q`` 长度一样、照样算出一个数，
#: 只是那个数不再表示"像不像"。所以必须靠版本号**明确拒绝**，
#: 让用户重建库；这正是 :func:`load_library` 那段注释说的情况。
FORMAT_VERSION = 3

#: 回源取原图的缓存容量（帧数）。
#:
#: 一帧 1280x720x3 ≈ 2.7MB，所以 64 帧 ≈ 173MB —— 够用又不至于吃爆内存。
#: 实测 ``locate_aligned`` 一次要用 5 个候选，而**相邻两次 measure
#: 的候选高度重叠**（窗口只挪几帧），所以 64 帧的命中率已经很高。
DEFAULT_FRAME_CACHE = 64


class _FrameCache:
    """取原图的 **LRU 缓存**（按帧号）。

    ## 为什么不用 ``functools.lru_cache``

    它的 key 要能哈希，而 :class:`ReferenceLibrary` 是 dataclass、
    带 ``_capture`` 这种不可哈希的字段。挂在实例上更直白。

    ## 为什么必须限制容量

    34 分钟视频有 4078 个参考帧，全缓存 ≈ 11GB。
    所以按"最近用过的 N 帧"淘汰 —— 实际访问是**局部**的
    （每帧都在同一小段窗口里搜），LRU 正合适。
    """

    __slots__ = ("_cap", "_data", "_order")

    def __init__(self, capacity: int = DEFAULT_FRAME_CACHE):
        self._cap = max(1, int(capacity))
        self._data: dict[int, object] = {}
        #: 最近使用顺序（末尾最新）—— 用 list 就够，容量很小
        self._order: list[int] = []

    def get(self, key: int):
        img = self._data.get(key)
        if img is not None:
            #: 命中就挪到末尾（标记为最近使用）
            try:
                self._order.remove(key)
            except ValueError:
                pass
            self._order.append(key)
        return img

    def put(self, key: int, img) -> None:
        if key in self._data:
            self._order.remove(key)
        self._data[key] = img
        self._order.append(key)
        while len(self._order) > self._cap:
            old = self._order.pop(0)
            self._data.pop(old, None)

    def clear(self) -> None:
        self._data.clear()
        self._order.clear()


@dataclass
class ReferenceLibrary:
    """参考库（内存里 + 可存盘）。"""

    #: (M, D) 归一化描述子
    matrix: np.ndarray
    #: (M,) 原视频帧号
    frames: np.ndarray
    #: 原视频帧率
    fps: float = 30.0
    #: 抽帧间隔（帧）
    step: int = REF_STEP
    #: 源视频路径（仅供显示）
    src: str = ""
    #: ★ **按键表**：视频里在哪些帧按了什么键（``{"index": int,
    #: "text": str, "key": str, "hold": int}`` 的列表）。
    #:
    #: 这是"照视频做操作"的核心 —— 没有它，机器只会一直按 W 往前走，
    #: 遇到飞/解谜/长按机关/对话分支就卡住。
    #:
    #: ⚠ 存成**普通 dict 列表**（不是自定义对象）—— ``np.savez``
    #: 存不了对象（``allow_pickle=False``），而开 pickle 读不可信文件
    #: 是安全问题。
    key_events: list = field(default_factory=list)
    #: 建库时扫了多少帧 / 其中多少帧像有提示（给报告用）
    key_scan: dict = field(default_factory=dict)
    #: 打开的视频（用于按帧号回取原图；不参与序列化）
    _capture: object = None
    #: ★ 取原图的 LRU 缓存（不参与序列化）—— 见 :meth:`frame_image_at`
    _cache: object = None
    #: 缓存容量（帧数）
    _frame_cache_size: int = DEFAULT_FRAME_CACHE

    def __len__(self) -> int:
        return int(self.matrix.shape[0])

    # ------------------------------------------------------------ 按键表
    def schedule(self):
        """把存下来的事件还原成 :class:`~.keys.KeySchedule`。

        惰性构造 —— 不用按键表的话（比如只做定位诊断）不必付这个开销。
        """
        from .keys import KeyEvent, KeySchedule        # noqa: PLC0415

        out = KeySchedule()
        for raw in self.key_events or []:
            try:
                out.events.append(KeyEvent(
                    text=str(raw.get("text") or ""),
                    key=str(raw.get("key") or ""),
                    hold=bool(raw.get("hold")),
                    start=int(raw.get("start", 0)),
                    end=int(raw.get("end", raw.get("start", 0))),
                ))
            except (TypeError, ValueError, AttributeError):
                continue                              #: 坏条目跳过，别炸
        out.scanned = int((self.key_scan or {}).get("scanned", 0))
        out.unreadable = int((self.key_scan or {}).get("unreadable", 0))
        return out

    def has_keys(self) -> bool:
        """学到按键了吗（没有的话执行器不该假装能操作）。"""
        return bool(self.key_events)

    def time_of(self, index: int) -> float:
        """第 ``index`` 个参考帧对应的**视频时间**（秒）。"""
        if index < 0 or index >= len(self):
            return float("nan")
        fps = self.fps if self.fps > 0 else 30.0
        return float(self.frames[index]) / fps

    def frame_image(self, index: int):
        """按参考库下标取**原图**（回源视频 seek）。

        :return: BGR 图；取不到返回 ``None``
        """
        if index < 0 or index >= len(self):
            return None
        return self.frame_image_at(int(self.frames[index]))

    def frame_image_at(self, frame_no: int):
        """按原始帧号取图（带缓存）。

        ## ⚠⚠ 为什么必须缓存（2026-10-11 真机测出来的）

        回源视频 seek 取一帧**极慢** —— 实测这台机器上::

            顺序读 300 帧      11.7 ms/帧
            seek + read 一次   **3087 ms**（中位，232MB 的 mp4）

        而 ``locate_aligned`` 对 top_k(=5) 个候选**各取一次原图**做相位相关，
        于是 ``Locator.measure()`` 一次要 **23 秒**。

        闭环需要 ~10 次/秒 才能跟住走路 —— **慢 230 倍，根本跑不起来**。

        缓存之后：同一个下标第二次取是**内存命中**（~0 秒），
        而实际运行中候选高度重复（每帧都在同一小段里搜），
        命中率很高。

        ⚠ 缓存**有上限**：一个 34 分钟的视频有 4078 个参考帧，
        全缓存要 4078 × 2.7MB ≈ 11GB —— 不可能。
        所以用 LRU（最近最少使用）淘汰，容量按**帧数**算。
        """
        if self._cache is None:
            self._cache = _FrameCache(self._frame_cache_size)

        hit = self._cache.get(frame_no)
        if hit is not None:
            return hit

        cv2 = _cv2()
        cap = self._capture
        if cap is None:
            if not self.src:
                return None
            cap = self._open()
            if cap is None:
                return None
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(frame_no))
        ok, img = cap.read()
        if not ok:
            return None
        self._cache.put(frame_no, img)
        return img

    def _open(self):
        cv2 = _cv2()

        if not self.src or not Path(self.src).is_file():
            return None
        cap = cv2.VideoCapture(str(self.src))
        if not cap.isOpened():
            return None
        self._capture = cap
        return cap

    def close(self) -> None:
        """关掉视频句柄（幂等）。"""
        cap = self._capture
        self._capture = None
        #: 缓存里存的是**解码后的图**，关了视频也还有效；
        #: 但重开可能换了文件，所以一并清掉更稳妥。
        if self._cache is not None:
            self._cache.clear()
        if cap is not None:
            try:
                cap.release()
            except Exception:                    # noqa: BLE001
                pass


def _cv2():
    """复用 descriptor 的延迟导入缓存。"""
    from .descriptor import _cv2 as inner       # noqa: PLC0415

    return inner()


def build_library(video_path, *, step: int = REF_STEP,
                  progress=None, learn_keys=None) -> ReferenceLibrary:
    """从视频建参考库（**顺便学按键**）。

    :param video_path: 视频文件路径
    :param step: 抽帧间隔（帧）
    :param progress: 可选回调 ``progress(done_frames, total_frames)``
    :param learn_keys: ★ 可选回调 ``learn_keys(参考帧序号, BGR帧) -> str|None``
        —— 返回那一帧上的**按键提示文字**（没有提示就返回 ``None``）。

        ## 为什么要一起做（而不是建完库再扫一遍）

        建库本来就要把整个视频**顺序读一遍**（实测 3280 帧 73 秒）。
        按键提示就在这些帧上 —— 另起一遍扫描等于把视频读两次，
        白花一倍时间。

        ## ⚠ 这个回调是**注入**的

        真实现（OCR）在 :mod:`~.reader`，但那个需要 ok-ww / cv2，
        而本模块要能在没装那些的环境里被 import（单测要跑）。
        所以传进来 —— 不传就是"只建库、不学按键"（旧行为）。

    :raises FileNotFoundError: 视频不存在
    :raises RuntimeError: 打不开 / 一帧都读不到

    ⚠ 顺序读比 ``cap.set()`` 快一个数量级 —— 实测 3280 帧
    顺序读 73 秒，用 ``set()`` 要 137 秒。
    """
    import cv2                                   # noqa: PLC0415

    path = Path(video_path)
    if not path.is_file():
        raise FileNotFoundError(f"视频不存在：{path}")

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"打不开视频：{path}")
    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS)) or 30.0
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        vecs: list[np.ndarray] = []
        frames: list[int] = []
        #: ★ 抽帧时**顺手收集按键提示**（同一遍扫描，不多读一次视频）
        observations: list[tuple[int, str | None]] = []
        cur = 0
        index = 0                                #: 参考帧序号（= len(vecs)）
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if cur % step == 0:
                d = descriptor(frame)             #: ★ 建库用干净图
                if d is not None:
                    vecs.append(d)
                    frames.append(cur)
                    #: 按键提示也从**同一帧**上读（不重开视频）
                    if learn_keys is not None:
                        text = learn_keys(index, frame)
                        observations.append((index, text))
                    index += 1
            if progress is not None and cur % (step * 20) == 0:
                progress(cur, total)
            cur += 1
    finally:
        cap.release()

    if not vecs:
        raise RuntimeError(f"一帧都没读到：{path}")

    lib = ReferenceLibrary(
        matrix=np.stack(vecs),
        frames=np.asarray(frames, dtype=np.int64),
        fps=fps,
        step=step,
        src=str(path),
    )

    #: ★ 把观测合并成按键表（"照视频做操作"的核心产物）
    if learn_keys is not None:
        from .keys import build_schedule              # noqa: PLC0415

        schedule = build_schedule(observations)
        lib.key_events = [
            {"text": e.text, "key": e.key, "hold": int(e.hold),
             "start": e.start, "end": e.end}
            for e in schedule.events
        ]
        lib.key_scan = {
            "scanned": schedule.scanned,
            "unreadable": schedule.unreadable,
            "events": len(schedule.events),
        }
        logger.info("按键表：%s", schedule.describe())

    logger.info("参考库建好：%d 帧（源 %s）", len(lib), path.name)
    return lib


def save_library(lib: ReferenceLibrary, path) -> Path:
    """存盘（``.npz``）。

    ⚠ 按键表（``key_events``）用 ``json`` 存成**一个字符串** ——
    npz 在 ``allow_pickle=False`` 下装不了对象列表，而开 pickle
    读不可信文件是安全问题（这几个库是用户从网上下的视频生成的，
    不该假设可信）。
    """
    import json                                     # noqa: PLC0415

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    np.savez_compressed(
        tmp,
        version=np.asarray(FORMAT_VERSION),
        matrix=lib.matrix.astype(np.float32),
        frames=lib.frames.astype(np.int64),
        fps=np.asarray(lib.fps, dtype=np.float64),
        step=np.asarray(lib.step, dtype=np.int64),
        src=np.asarray(lib.src),
        #: 按键表 + 扫描统计（都是 JSON 文本，不用 pickle）
        keys=np.asarray(json.dumps(lib.key_events or [],
                                   ensure_ascii=False)),
        key_scan=np.asarray(json.dumps(lib.key_scan or {},
                                       ensure_ascii=False)),
    )
    #: np.savez 会自己加 .npz —— 先找到真实落点再改名
    written = tmp if tmp.exists() else tmp.with_name(tmp.name + ".npz")
    written.replace(target)

    #: ★ 顺手更新 sidecar —— 列表读它来快速显示（不解压 npz）。
    #:
    #: ⚠ 这一步**必须在这里**，不能只放在"建库"那条路里。
    #: 实测踩到：改了库里的 ``key_events``（0 → 10 条）但没重写 meta，
    #: 工具页就一直显示「⚠ 没学到按键」，而库里明明有 ——
    #: 缓存和真源不一致，而且**不报错**。
    #:
    #: 延迟 import 是为了避免循环依赖（catalog 要 import library）。
    try:
        from .catalog import write_meta             # noqa: PLC0415

        write_meta(target, lib)
    except Exception:                                # noqa: BLE001
        pass                                         #: 写不上不影响库本身
    return target


def load_library(path) -> ReferenceLibrary:
    """读盘。

    :raises FileNotFoundError: 文件不存在
    :raises RuntimeError: 版本不认识 / 内容坏了

    ⚠ 版本不认识时**明确报错**，不要"尽力而为" —— 描述子算法变过之后
    拿旧库去匹配会静默给出错误位置，比读不出来危险得多。
    """
    import json                                     # noqa: PLC0415

    src = Path(path)
    if not src.is_file():
        raise FileNotFoundError(f"参考库不存在：{src}")
    try:
        with np.load(src, allow_pickle=False) as data:
            version = int(data["version"]) if "version" in data else 0
            if version != FORMAT_VERSION:
                raise RuntimeError(
                    f"参考库版本不认识：文件是 {version}，本版是 {FORMAT_VERSION}"
                    f"（重新建一次库即可）")
            keys = []
            if "keys" in data:
                try:
                    parsed = json.loads(str(data["keys"]))
                    keys = parsed if isinstance(parsed, list) else []
                except (ValueError, TypeError):
                    keys = []                   #: 按键表坏了不该让整个库读不出来
            scan = {}
            if "key_scan" in data:
                try:
                    parsed = json.loads(str(data["key_scan"]))
                    scan = parsed if isinstance(parsed, dict) else {}
                except (ValueError, TypeError):
                    scan = {}
            return ReferenceLibrary(
                matrix=data["matrix"].astype(np.float32),
                frames=data["frames"].astype(np.int64),
                fps=float(data["fps"]) if "fps" in data else 30.0,
                step=int(data["step"]) if "step" in data else REF_STEP,
                src=str(data["src"]) if "src" in data else "",
                key_events=keys,
                key_scan=scan,
            )
    except RuntimeError:
        raise
    except Exception as exc:                     # noqa: BLE001
        raise RuntimeError(f"参考库读不出来：{exc}") from exc


def library_shape_ok(lib: ReferenceLibrary) -> bool:
    """库的自洽性检查（描述子维度对不对）。

    建库/读库之后都该过一遍 —— 维度不对的话匹配结果毫无意义，
    而且**不会报错**（``REF @ q`` 形状不符会抛，但同长度不同含义不会）。
    """
    expected = DW * DH
    return lib.matrix.ndim == 2 and lib.matrix.shape[1] == expected \
        and lib.matrix.shape[0] == len(lib.frames)
