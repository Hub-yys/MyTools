# -*- coding: utf-8 -*-
"""视频 → 参考库的**目录管理**：一个视频一份库，互不覆盖。

## ★ 为什么需要这个模块（原来的设计是错的）

最开始 ``library_path()`` 返回的是一个**固定文件名**::

    <用户数据>/video_follow_ref.npz      ← 只有一个

于是"上传第二个视频"会把第一个的库**直接覆盖掉** ——
用户想给不同路线各建一份库，结果永远只剩最后一份。

而用户的原话是::

    "我上传一个视频，你能跟着视频做"

**一个视频 = 一条路线 = 一份库**。所以库要按视频分开存::

    <用户数据>/explore_gap/
        ├── 无光之森找宝箱.npz       ← 视频 A
        ├── 七丘声匣.npz             ← 视频 B
        └── ...

## 名字怎么来的（这里最容易出问题）

库名从**视频文件名**派生，但要处理几件麻烦事：

============================  ==========================================
坑                             处理
============================  ==========================================
中文文件名                      Windows 允许，**原样保留**（别转拼音/哈希，
                               用户要能一眼认出哪个是哪个）
文件名里的非法字符              尖括号 / 冒号 / 引号 / 斜杠 / 竖线 / 问号 /
                                星号，以及控制字符 → 换成 ``_``
``..`` / 前导点                 先按路径分隔符切开再逐段清理，防目录穿越
超长名                          截断到 :data:`MAX_STEM`
重名                            同名视频不同目录 → 加短哈希区分
============================  ==========================================

短哈希用**源视频的绝对路径**算 —— 同一个视频永远得到同一个名字
（重复上传不会攒一堆副本），不同视频即使同名也不会撞。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from .library import REF_STEP, ReferenceLibrary, load_library, save_library

#: 库文件统一放这个子目录（用户数据目录下）
LIB_DIR_NAME = "explore_gap"

#: 改名前的目录名 —— 首次运行会从这里**继承**已建好的库。
#:
#: ⚠ 用户可能已经建过库了。直接换名字会让那些库"消失"
#: （列表变空、要重新建一遍，27 分钟视频就是白等 1~2 分钟）。
#: 所以启动时把老目录整树搬过来一次。
LEGACY_DIR_NAMES: tuple[str, ...] = ("video_follow",)

#: 库名主干的最大长度（字符）。留余量给哈希后缀和 ``.npz``。
MAX_STEM = 60

#: 文件名里不允许出现的字符（Windows + POSIX 取并集，宁可严一点）
_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

#: 短哈希长度（十六进制位）
HASH_LEN = 6


def sanitize_stem(name: str) -> str:
    """把任意字符串变成可以当文件名的主干。

    * **先按路径分隔符切开**，只取最后一段 —— 这一步必须在替换非法
      字符**之前**做。反过来的话 ``../etc/passwd`` 会先变成
      ``.._etc_passwd``，那个前导 ``..`` 就留在名字里了
      （测试抓到的：期望 ``etc_passwd``，实际 ``_etc_passwd``）。
    * 非法字符 → ``_``
    * 前导点 → 去掉（防目录穿越 + Windows 不允许）
    * 结尾的点和空格 → 去掉（Windows 不允许）
    * 空白折叠成单个下划线
    * 空结果 → ``"video"``
    * 超长 → 截断到 :data:`MAX_STEM`

    **中文原样保留** —— 用户要能一眼认出哪个库是哪条路线。
    """
    text = str(name or "")
    #: ★ 先取最后一段路径成分（``..`` / ``/`` / ``\`` 都在这一步被吃掉）
    text = re.split(r"[/\\]", text)[-1]
    text = _ILLEGAL.sub("_", text)
    text = re.sub(r"\s+", "_", text.strip())
    text = text.lstrip(".")          #: 此时剩下的前导点一律是坏的
    text = text.rstrip(". ")
    text = text.strip("_")           #: 清理后可能只剩分隔符留下的下划线
    if len(text) > MAX_STEM:
        text = text[:MAX_STEM].rstrip("._")
    return text or "video"


def short_hash(text: str) -> str:
    """稳定短哈希（同一个输入永远同一个输出）。"""
    digest = hashlib.sha1(str(text).encode("utf-8", "replace")).hexdigest()
    return digest[:HASH_LEN]


def library_dir(user_data_dir: Path | str) -> Path:
    """所有参考库放哪儿。"""
    return Path(user_data_dir) / LIB_DIR_NAME


def adopt_legacy_dir(user_data_dir: Path | str) -> list[str]:
    """把改名前的库目录整树继承过来。

    :return: 做过的事（给日志用）；不需要继承时返回空列表

    ## 为什么必须有这个

    工具从「跟着画面走」改名成「查缺补漏」时，库目录也跟着从
    ``video_follow/`` 变成 ``explore_gap/``。

    用户可能**已经建过库**（27 分钟视频要等 1~2 分钟）。
    直接换名字会让那些库从列表里"消失"，用户只能重传重扫。

    做法跟 ``paths.migrate_legacy_user_data`` 一致：**复制**而不是移动
    （老目录原样留着当兜底），且**只在目标目录还不存在时**做一次 ——
    之后用户的操作都在新目录里，绝不会拿旧的覆盖新的。
    """
    base = Path(user_data_dir)
    target = base / LIB_DIR_NAME
    if target.exists():
        return []
    done: list[str] = []
    import shutil                                     # noqa: PLC0415

    for legacy_name in LEGACY_DIR_NAMES:
        legacy = base / legacy_name
        if not legacy.is_dir():
            continue
        try:
            shutil.copytree(legacy, target, dirs_exist_ok=True)
        except OSError:
            continue                                  #: 拷不动就算了，不挡启动
        done.append(f"{legacy_name}/ → {LIB_DIR_NAME}/")
        break
    return done


def library_path_for(video_path: Path | str,
                     user_data_dir: Path | str) -> Path:
    """某个视频对应的库文件路径。

    ## 为什么要带哈希

    光用文件名会撞：``D:/a/攻略.mp4`` 和 ``E:/b/攻略.mp4`` 是**两条
    不同的路线**，只按名字的话第二个会覆盖第一个。

    所以名字里带一段由**源视频绝对路径**算出的短哈希::

        攻略_a1b2c3.npz

    同一个视频重复上传 → 同一个名字（不会攒副本）；
    不同视频即使同名 → 不同名字（不会互相覆盖）。
    """
    raw = Path(str(video_path))
    stem = sanitize_stem(raw.stem)
    tag = short_hash(str(raw.resolve()) if raw.exists() else str(raw))
    return library_dir(user_data_dir) / f"{stem}_{tag}.npz"


@dataclass(frozen=True)
class VideoEntry:
    """一个"已上传的视频"及其库的状态。"""

    #: 源视频路径
    video: str
    #: 库文件路径
    library: str
    #: 库建好了吗
    built: bool
    #: 源视频还在吗（⚠ 不在就没法定位 —— 库只存描述子）
    video_present: bool
    #: 参考帧数（库没建好时为 0）
    frames: int = 0
    #: 覆盖时长（分钟，库没建好时为 0）
    minutes: float = 0.0
    #: ★ 学到多少次按键。``0`` 意味着跑起来**只会转视角 + 按 W**，
    #: 遇到飞 / 解谜 / 长按机关 / 对话分支会卡住 —— 用户需要知道这点。
    keys: int = 0

    @property
    def name(self) -> str:
        return Path(self.video).stem

    @property
    def runnable(self) -> bool:
        """能不能跑。

        ⚠ **两个条件都要**：库在 **且** 源视频在。
        库只有描述子，对齐要回源视频取原图 —— 视频不在就什么都认不出来。
        """
        return self.built and self.video_present

    def status_text(self) -> str:
        """一行状态，给界面/日志用。"""
        if not self.built:
            return "还没建库"
        if not self.video_present:
            return "⚠ 源视频不在了 —— 定位会失效，要重新上传建库"
        base = f"{self.frames} 个参考帧 · {self.minutes:.1f} 分钟"
        if self.keys:
            base += f" · 学到 {self.keys} 次按键"
        else:
            base += " · ⚠ 没学到按键（只会跟着走，不会解机关）"
        return base


def _sidecar_path(library: Path) -> Path:
    """库旁边那个记录"源视频是谁"的小文件。"""
    return library.with_suffix(".src")


def remember_source(library: Path, video: Path | str) -> None:
    """把源视频路径记在库旁边。

    ## 为什么不能只靠库里的 ``src`` 字段

    库的 ``.npz`` 里**已经**存了 ``src``（见 :mod:`~.library`）——
    但那要**打开库**才读得到。而列列表时要显示"视频还在不在"，
    为几十个库各打开一次 npz 太慢（每个都要解压描述子矩阵）。

    所以再放一个纯文本 sidecar，列列表时只读它。
    """
    try:
        _sidecar_path(Path(library)).write_text(
            str(video), encoding="utf-8")
    except OSError:
        pass                                   #: 记不上不影响功能


def source_of(library: Path | str) -> str:
    """读库对应的源视频路径（先看 sidecar，再退回库内 ``src``）。"""
    lib = Path(library)
    side = _sidecar_path(lib)
    if side.is_file():
        try:
            text = side.read_text(encoding="utf-8").strip()
            if text:
                return text
        except OSError:
            pass
    #: 退回打开库读 src（慢，但只有这个库有这情况）
    try:
        return load_library(lib).src
    except Exception:                          # noqa: BLE001
        return ""


def list_entries(user_data_dir: Path | str) -> list[VideoEntry]:
    """列出所有已上传的视频 / 已建的库（按名字排序）。

    ⚠ 只读 sidecar + 文件是否存在，**不解压任何 npz** ——
    所以哪怕有几十个库也是毫秒级。

    会**顺手继承**改名前的旧库目录（见 :func:`adopt_legacy_dir`）——
    放在这里是因为列表是"用户第一次看到库"的地方，
    继承必须在那一刻之前发生。用户不该为了改名重扫一遍视频。
    """
    adopt_legacy_dir(user_data_dir)
    out: list[VideoEntry] = []
    base = library_dir(user_data_dir)
    if not base.is_dir():
        return out
    for lib in sorted(base.glob("*.npz")):
        if lib.name.endswith(".tmp.npz"):
            continue
        video = source_of(lib)
        info = _read_meta(lib)
        out.append(VideoEntry(
            video=video or f"（来源不明）{lib.stem}",
            library=str(lib),
            built=True,
            video_present=bool(video) and Path(video).is_file(),
            frames=info[0],
            minutes=info[1],
            keys=info[2],
        ))
    out.sort(key=lambda e: e.name)
    return out


def _read_meta(library: Path) -> tuple[int, float, int]:
    """从库旁边的 ``.meta`` 读帧数/时长/按键数（没有就给 0）。

    ⚠ ``keys`` 是后来才加的第 4 个字段 —— 旧 meta 只有 3 个，
    所以缺字段要给默认值（不然升级后列表全读不出来）。

    ## ⚠⚠ 这个 sidecar 会**过期**（实测踩到）

    它是给"列表不解压 npz"用的缓存。但缓存就得有人更新 ——
    实测：我改了库里的 ``key_events``（10 条）却没重写 meta，
    工具页就一直显示「⚠ 没学到按键」，而库里明明有。

    现在 :func:`src.core.explore_gap.library.save_library` 会**自动**
    一起写 meta，所以正常路径下不会过期；这里只是读。
    """
    meta = library.with_suffix(".meta")
    if not meta.is_file():
        return 0, 0.0, 0
    try:
        parts = meta.read_text(encoding="utf-8").split()
        keys = int(parts[3]) if len(parts) > 3 else 0
        return int(parts[0]), float(parts[1]), keys
    except (OSError, ValueError, IndexError):
        return 0, 0.0, 0


def write_meta(library: Path | str, lib: ReferenceLibrary) -> None:
    """记下帧数/时长/按键数，供列表快速显示。

    ⚠ 由 ``save_library`` **自动调用** —— 别在别处单独调，
    否则会出现"库改了、meta 没改"的过期（列表显示错的状态）。
    """
    minutes = len(lib) * lib.step / (lib.fps or 30.0) / 60.0
    try:
        Path(library).with_suffix(".meta").write_text(
            f"{len(lib)} {minutes:.3f} {REF_STEP} {len(lib.key_events or [])}",
            encoding="utf-8")
    except OSError:
        pass


def build_for(video_path: Path | str, user_data_dir: Path | str,
              *, progress=None, learn_keys=None) -> tuple[Path, ReferenceLibrary]:
    """给一个视频建库并**存到它自己的位置**（不覆盖别的视频）。

    :param learn_keys: ★ 可选 —— 建库时顺便学按键（见
        :func:`~.library.build_library`）。不传就只建库、不学按键，
        那样跑起来只会"转视角 + 一直按 W"。

    :return: ``(库文件路径, 库对象)``
    :raises FileNotFoundError: 视频不存在
    :raises RuntimeError: 建库失败

    ⚠ 源视频路径会被记下来（sidecar + 库内 ``src``），
    因为**对齐要回源视频取原图** —— 视频没了定位就失效。
    """
    from .library import build_library                  # noqa: PLC0415

    video = Path(str(video_path))
    if not video.is_file():
        raise FileNotFoundError(f"找不到视频：{video}")

    lib = build_library(video, progress=progress, learn_keys=learn_keys)
    target = library_path_for(video, user_data_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    save_library(lib, target)          #: ★ 它内部会一起写 meta
    remember_source(target, video)
    return target, lib


def forget(library: Path | str) -> list[str]:
    """删掉一个库（连同 sidecar / meta）。

    ⚠ **不动源视频** —— 用户上传的视频是他的东西。
    :return: 实际删掉的文件名（给日志/界面用）
    """
    lib = Path(library)
    removed: list[str] = []
    for path in (lib, _sidecar_path(lib),
                 lib.with_suffix(".meta"), lib.with_suffix(".npz.tmp")):
        try:
            if path.is_file():
                path.unlink()
                removed.append(path.name)
        except OSError:
            pass
    return removed
