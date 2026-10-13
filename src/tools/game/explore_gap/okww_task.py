# -*- coding: utf-8 -*-
"""「查缺补漏」的 ok-ww 任务类（宿主接线）。

## 这一层只做接线，不做判断

::

    okww.task.WWOneTimeTask  ←  本类（接线）  →  executor.ExploreGapTask
                                                      ↓ 不含判断
                                            core.explore_gap（已离线验证）

⚠ **别把逻辑写进这里。** 本模块跑在 ok-ww 引擎线程里，
离线测不了；判断一律放 :mod:`src.core.explore_gap`。

## ★ 接线（新增任务时最容易漏的一步）

ok-ww 侧要**两处**都登记才会跑：

1. ``src/tools/game/auto_combat/okww_boot.py`` 的 ``TASKS`` 字典
2. 同文件 ``build_config()`` 的 ``onetime_tasks`` 列表

漏掉任何一处 → 界面显示"找不到任务"（而且**不报错**）。
参见 README「接线」一节。

## ★★ ``supported_languages`` 必须清空

ok-ww 原版任务大多声明 ``supported_languages = ["zh_CN"]``，
而宿主**无 GUI** → ``app.locale`` 是 ``en_US`` → ok-script 的
``init_tasks()`` **不注册**它 → 任务被静默跳过。

宿主场景里"引擎语言"这个代理量毫无意义（本工具就是给中文游戏用的），
所以固定清空。这个坑在声骸调频/强化那边都踩过。
"""

from __future__ import annotations

import os
import sys

#: ★ ok-ww 配置里要引用的**模块级类名**。
#:
#: ``onetime_tasks`` 写 ``["src.tools.game.explore_gap.okww_task",
#: "MyToolsExploreGapTask"]`` 时，ok-script 会对本模块做
#: ``getattr(..., "MyToolsExploreGapTask")`` —— 所以在模块尾用
#: ``__getattr__``（PEP 562）懒构造它。
TASK_CLASS_NAME = "MyToolsExploreGapTask"


def _ensure_okww_on_path() -> None:
    """把 vendored ok-ww 挂上 ``sys.path``（照 okww_boot 的做法）。

    ⚠ 必须**先**挂路径再 import okww，否则 ImportError。
    而且不能在模块顶层 import —— 单测环境里没有 ok-ww 挂载点。
    """
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.abspath(os.path.join(here, "..", "..", "..", ".."))
    vendor = os.path.join(root, "vendor", "okww")
    if os.path.isdir(vendor) and vendor not in sys.path:
        sys.path.insert(0, vendor)


def pick_library() -> str:
    """挑一个库来跑 —— 返回路径；**一个都没有 / 有多个时返回空串**。

    ## ★ 一个视频一份库，所以要挑

    用户上传了哪些视频，就有哪些库（见
    :mod:`src.core.explore_gap.catalog`）。跑之前必须知道"跑哪一条"。

    挑选规则::

        ① 配置里显式指定的（用户在任务配置里填了「参考库」）
        ② 唯一那个**能跑的**库（库在 且 源视频在）
        ③ 其余情况（一个都没有 / 有多个）→ 空串，由调用方给一句人话

    ⚠ **只在恰好有一个能用时才自动挑**。多于一个就返回空串 ——
    替用户猜"跑哪条路线"比让他自己选危险得多（跑错路线会乱走）。
    """
    from ....core import paths                        # noqa: PLC0415
    from ....core.explore_gap import list_entries    # noqa: PLC0415

    try:
        entries = list_entries(paths.user_data_dir())
    except Exception:                                 # noqa: BLE001
        return ""
    usable = [e for e in entries if e.runnable]
    if len(usable) == 1:
        return usable[0].library
    return ""


def build_task_class():
    """在**运行时**构造任务类（延迟 import ok-ww）。

    :return: 任务类；ok-ww 不可用时返回 ``None``

    ## 为什么用工厂而不是模块级 class

    模块级 ``class X(...)`` 会在**导入时就**要求 ok-ww 在场。
    而 :mod:`src.tools` 的自动发现会 import 本包 —— 于是没装 ok-ww
    的环境（比如只跑单测）会直接 import 失败，**整个工具包都扫不出来**。

    → 用工厂：import 本模块无害，只有真要跑任务时才碰 ok-ww。

    ## ⚠⚠ 基类不能只写 ``WWOneTimeTask``

    ``okww.task.WWOneTimeTask`` 是个**混入类，没有 ``__init__``**::

        class WWOneTimeTask:
            def run(self): ...

    而 ok-script 实例化时是 ``class_(executor=..., app=...)``，
    单继承它就会炸::

        TypeError: object.__init__() takes exactly one argument

    真实的 ok-ww 任务都是**双继承**：``(WWOneTimeTask, BaseCombatTask)``
    —— ``BaseCombatTask`` 那一路最终继承 ``ok.task.Task``，
    它的 ``__init__(self, executor, app)`` 才是真正干活的。

    → 这里照 ``FarmMapTask`` / ``FarmEchoTask`` 的写法用双继承。
    """
    _ensure_okww_on_path()
    try:
        from okww.task.BaseCombatTask import BaseCombatTask  # noqa: PLC0415
        from okww.task.WWOneTimeTask import WWOneTimeTask    # noqa: PLC0415
    except Exception:                                 # noqa: BLE001
        return None
    return _make_class((WWOneTimeTask, BaseCombatTask))


def _make_class(bases):
    """用给定的基类造出任务类（基类可参数化，好让单测喂假基类）。"""
    from .executor import ExploreGapTask             # noqa: PLC0415

    class MyToolsExploreGapTask(*bases):
        """跟着攻略视频的画面走（视觉伺服，不用世界坐标）。"""

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.name = "🎬 查缺补漏（鸣潮工具箱）"
            self.description = (
                "照参考视频的画面走路线：持续把当前屏幕匹配到视频的某一帧，"
                "偏离了就往回纠。不依赖世界坐标。"
                "需要先用「查缺补漏」工具页建好参考库。"
            )
            #: ★★ 语言门禁清空（否则任务被静默跳过，见模块文档）
            self.supported_languages = []
            #: 本次运行的统计
            self.stats: dict = {}
            self.stop_reason = ""

        @property
        def lib_path(self) -> str:
            """跑哪个库。

            ① 配置里显式填了「参考库」→ 用它
            ② 否则自动挑（**恰好一个能用**时才挑，见 :func:`pick_library`）
            """
            configured = str(self.config.get("参考库") or "").strip()
            return configured or pick_library()

        def _describe_choices(self) -> str:
            """一个都没得挑时，说清"有哪些、为什么不能用"。"""
            from ....core import paths                     # noqa: PLC0415
            from ....core.explore_gap import list_entries  # noqa: PLC0415

            try:
                entries = list_entries(paths.user_data_dir())
            except Exception as exc:                       # noqa: BLE001
                return f"（列表都读不出来：{exc}）"
            if not entries:
                return "还没上传过视频 —— 去「查缺补漏」工具页传一个"
            lines = ["已上传的视频："]
            for e in entries:
                lines.append(f"  · {e.name} —— {e.status_text()}")
            usable = [e for e in entries if e.runnable]
            if len(usable) > 1:
                lines.append("有多个能跑的库 —— 请在任务配置里填「参考库」"
                             "指定跑哪一条（不替你猜，跑错路线会乱走）")
            return "\n".join(lines)

        def run(self) -> None:
            """跑路线。**判断都在 core 里，这里只接线。**

            ⚠ ``ExploreGapTask(...)`` 的**构造**也要包在 try 里 ——
            它内部会 ``load_library``，而库文件坏掉 / 版本不认识时
            会抛 ``RuntimeError``。构造在 try 外面的话，异常会一路
            冒到 ok-ww 引擎里，把整个任务线程带崩（不是"任务失败"，
            是引擎报错）。这个坑是写测试时抓到的。
            """
            path = self.lib_path
            if not path or not os.path.isfile(path):
                why = self._describe_choices()
                self.stop_reason = f"没有可用的参考库。{why}"
                self.log_info(self.stop_reason, notify=True)
                return

            try:
                runner = ExploreGapTask(
                    path, self, self.log_info,
                    lambda: bool(getattr(self, "should_stop", False)),
                )
                self.stats = runner.run()
            except Exception as exc:                  # noqa: BLE001
                self.stop_reason = f"{type(exc).__name__}: {exc}"
                self.log_info(f"查缺补漏失败：{self.stop_reason}",
                              notify=True)
                return

            if self.stats.get("lost"):
                self.stop_reason = "跟丢了（画面已偏离太远）"
            else:
                self.stop_reason = "跑完"
            self.log_info(
                f"查缺补漏结束：{self.stop_reason}  "
                f"前进 {self.stats.get('advance', 0)}  "
                f"纠偏 {self.stats.get('correct', 0)}  "
                f"空等 {self.stats.get('wait', 0)}",
                notify=True)

    return MyToolsExploreGapTask


def _load_okww_class():
    """★ ok-ww 配置里 ``[模块, 类名]`` 走的是 ``getattr`` —— 得有个模块级名字。

    ok-script 解析 ``onetime_tasks`` 的方式是::

        getattr(importlib.import_module(module_name), attribute_name)

    也就是**普通属性查找**，不接受工厂函数的结果。所以本模块必须暴露
    一个模块级类名。但模块级 ``class ... (WWOneTimeTask)`` 会在 import 时
    就要 ok-ww 在场（见 :func:`build_task_class` 的说明）。

    解法：``__getattr__``（PEP 562）—— **模块级懒属性**。
    平时 import 本模块不碰 ok-ww；ok-script 真的 ``getattr`` 时才构造。
    """
    return build_task_class()


def __getattr__(name: str):
    """模块级懒属性（PEP 562）—— 只认任务类名。"""
    if name == TASK_CLASS_NAME:
        cls = _load_okww_class()
        if cls is None:
            raise AttributeError(
                f"{TASK_CLASS_NAME} 需要 ok-ww（vendor/okww 或已安装的 ok-script）")
        #: 缓存，避免每次 getattr 都重建一个类
        globals()[TASK_CLASS_NAME] = cls
        return cls
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
