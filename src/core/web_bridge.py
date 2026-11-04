# -*- coding: utf-8 -*-
"""★ Python ↔ JavaScript 双向桥 —— Web UI 骨架的数据与命令通道。

## 这是什么

MyTools 的「整个窗口就是一个 HTML 页面」架构里，Python 不再画任何界面，
**只提供数据和收命令**。这个模块就是那条通道，基于 :class:`QWebChannel`。

.. code:: text

    ┌───────────────────── Chromium 页面 ─────────────────────┐
    │  index.html  js/app.js  js/pages/*.js                   │
    │      │                                                 │
    │      └── bridge.call("getTools").then(...)             │
    └──────────────────────┬─────────────────────────────────┘
                           │  QWebChannel（异步回调）
    ┌──────────────────────┴─────────────────────────────────┐
    │  WebBridge（本模块）                                     │
    │    ├─ @Slot  getTools / switchPage / runTask / ...      │
    │    └─ Signal taskStarted / logLine / progress / ...     │
    └────────────────────────────────────────────────────────┘

## ⚠ QWebChannel 的三条硬规矩（踩过才知道）

1. **``@Slot`` 必须有明确的类型签名**。只写 ``@Slot()`` 不给 ``result=str``，
   JS 那边回调**永远不会触发**（没有报错，就是静默挂着 —— 最难查的一类）。
2. **跨线程 emit 是安全的**，Qt 会把槽排到接收者线程；但如果从 worker 线程
   **直接调用** ``page().runJavaScript()`` 就会崩。所以本模块**只发 Signal**，
   绝不在 Slot 里直接碰页面对象。
3. **JS 侧方法名 = Python 的 ``camelCase`` 名字**。QWebChannel 生成的 JS 代理用
   Python 定义名（本模块专门把方法定义成 camelCase，省得两边对不上）。

## 事件订阅

JS 侧订阅 Python 推送有两种写法，本模块都支持：

.. code:: js

    // ① 一次性订阅全部事件（推荐，最简单）
    bridge.subscribe(function (name, payload) { ... });

    // ② 按名字订阅
    bridge.on("logLine", function (payload) { ... });

Python 侧统一走 :meth:`WebBridge.emitEvent` / 那几个便捷方法。

## 为什么 ``getTools()`` 要自己 discover

``ToolRegistry.all_metas()`` 在 :func:`src.tools.discover_tools` 跑之前**是空的**
（返回 0 个，不报错）。以前主窗口由 ``main.py`` 保证先 discover，但 Web 页面
可能在任何时机第一次调 ``getTools()`` —— 所以这里**第一次调用时兜底 discover 一次**。
"""

from __future__ import annotations

import ast
import json
import logging
import os

from PySide6.QtCore import QObject, Signal, Slot

#: ★ 拼音搜索索引 —— 从 ``core.text_match`` 拿（**不要** import ``gui.pickers``：
#: core 是底层，依赖方向不能反）。
from .text_match import pinyin_keys

logger = logging.getLogger(__name__)

#: 单次 discover 的标记 —— 见模块文档末尾那段说明
_discovered = False


def _ensure_tools_discovered() -> None:
    """确保 :mod:`src.tools` 的工具都被注册过（幂等）。"""
    global _discovered
    if _discovered:
        return
    try:
        import src.tools as _tools  # noqa: PLC0415

        _tools.discover_tools()
    except Exception:  # noqa: BLE001 - 发现失败不该带崩界面
        logger.warning("WebBridge：工具发现失败", exc_info=True)
    _discovered = True


def _json(obj) -> str:
    """序列化成 JS 能吃的 JSON 字符串。

    ``ensure_ascii=False`` 很重要 —— 工具名全是中文，转义成
    ``\\uXXXX`` 之后 JS 端读起来没问题，但**日志/调试时没法看**，
    而且体积翻三倍。
    """
    try:
        return json.dumps(obj, ensure_ascii=False, default=str)
    except Exception:  # noqa: BLE001
        logger.warning("WebBridge：JSON 序列化失败", exc_info=True)
        return "null"


def _single_tool_flow(key: str):
    """合成一条只有「开始 + 一个工具」的流程（给 ``runTask`` 用）。

    让单个工具也能走 ``FlowRunThread`` 这条完整路径 —— 权限闸门、
    前置检查、准备动作、报告统计全都自动继承，和「从任务页跑」行为一致。

    ## ⚠ 为什么是模块级函数而不是类方法

    第一版写成类方法却按模块级调用（``_single_tool_flow(key)`` 少了
    ``self.``）→ ``NameError`` → **``runTask`` 100% 崩**。
    ``py_compile`` 抓不到这种错误（语法是对的），只有真跑一次才暴露。
    改成模块级就没这个歧义了。
    """
    from ..core.registry import ToolRegistry  # noqa: PLC0415
    from ..core.tasks import STEP_START, STEP_TOOL, TaskFlow, TaskStep  # noqa: PLC0415

    meta = ToolRegistry.get_meta(key)
    name = meta.name if meta else key
    steps = [TaskStep(type=STEP_START, name="开始")]

    #: ⚠⚠ 2026-11-02 删掉了「插 config 步骤」那段代码（lead 要求）。
    #:
    #: 曾经这里会读 ``tool_settings["web_echo_profile_pick"]``，
    #: 有选定就插一条 ``config`` 步骤。**方向是错的** ——
    #: ``echo_enhance/tool.py`` L531 写着：
    #:
    #:     这里**故意没有**「用哪套配置」的选择器。
    #:     —— 用户 2026-09-26 明确："角色声骸强化类型配置与声骸自动强化
    #:     工具的配置是无关的"。
    #:
    #: 旧界面曾经加过这个下拉，被用户否掉后拆掉了；
    #: P4 时 lead 又让我加回来，现在一并撤掉。
    #:
    #: 真要「按配置跑」应该走**任务流程**（编排里显式挂 config 步骤），
    #: 而不是让工具页和配置页共享存储。

    steps.append(TaskStep(type=STEP_TOOL, key=key, name=name))
    return TaskFlow(name=name, steps=steps)




#: 首字占位头像的色相总数（照抄 ``src/gui/pickers.py`` 的 ``_FALLBACK_HUES``）
#:
#: ★★ 必须和旧界面**完全一致** —— 用户 2026-11-02：
#: 「配置页头像全是灰圈」「请不要擅自修改原先的布局内容」。
#:
#: 旧界面 :func:`src.gui.pickers._initial_icon` 的算法：
#:
#: .. code:: python
#:
#:     hue = zlib.crc32(text.encode("utf-8")) % 360
#:     base = QColor.fromHsv(hue, 90, 200)      # 饱和度 90/255、亮度 200/255
#:     # 圆底 + 白色首字（0.52 字号、加粗）
#:
#: 这里把**同一个散列**算出来交给前端画 —— 同一个角色在旧界面和新界面
#: 会得到**同一个色相**，截图对照时不会「看着像换了个角色」。
_FALLBACK_HUES = 360

#: 占位圆底的 HSV 参数（和旧界面 ``QColor.fromHsv(hue, 90, 200)`` 对齐）
_INITIAL_SAT = 90      #: 0~255
_INITIAL_VAL = 200     #: 0~255


def _initial_avatar_hue(name: str) -> int:
    """名字 → 色相（0~359）。**照抄** ``pickers._initial_icon`` 的散列。

    ``zlib.crc32`` 而不是 ``hash()`` —— 后者带随机种子（``PYTHONHASHSEED``），
    同一个角色每次启动颜色都不一样。旧界面用 crc32 正是为了稳定。
    """
    text = str(name or "").strip()
    if not text:
        return 0
    import zlib  # noqa: PLC0415

    return int(zlib.crc32(text.encode("utf-8")) % _FALLBACK_HUES)


def _hsv_to_hex(hue: int, sat: int = _INITIAL_SAT, val: int = _INITIAL_VAL) -> str:
    """HSV(0~359, 0~255, 0~255) → ``#RRGGBB``。

    和 ``QColor.fromHsv`` 的取值口径一致（Qt 的 h 是 0~359、s/v 是 0~255）。
    页面拿到这个 hex 直接当圆底背景色，首字用白色 —— 就还原了旧界面的占位图。
    """
    import colorsys  # noqa: PLC0415

    h = (int(hue) % 360) / 360.0
    s = max(0, min(255, int(sat))) / 255.0
    v = max(0, min(255, int(val))) / 255.0
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    return "#%02X%02X%02X" % (round(r * 255), round(g * 255), round(b * 255))


def _initial_avatar(name: str) -> dict:
    """给页面画「首字圆图」用的全套数据。

    返回 ``{name, initial, hue, color, textColor}``：

    * ``initial`` —— 首字（旧界面就是 ``text[0]``）
    * ``hue``     —— 色相 0~359（页面想自己算深浅时用）
    * ``color``   —— 圆底 ``#RRGGBB``（照旧界面 HSV→RGB）
    * ``textColor`` —— 首字颜色（旧界面是白色 245/255 透明）

    ⚠ 为什么后端算而不让页面算：页面里写一遍 crc32+HSV 就是**第二份实现**，
    迟早和旧界面对不上。后端给结果，页面只负责画。
    """
    text = str(name or "").strip()
    if not text:
        return {}
    hue = _initial_avatar_hue(text)
    return {
        "name": text,
        "initial": text[0],
        "hue": hue,
        "color": _hsv_to_hex(hue),
        #: 旧界面 ``QColor(255, 255, 255, 245)`` → 白色带 ~96% 不透明
        "textColor": "rgba(255,255,255,0.96)",
    }


def _normalize_loadout_payload(body: dict) -> dict:
    """把 ``Loadout`` 的 **camelCase 字段名映射成 snake_case**。

    ## 为什么需要（2026-11-02 查出的真 bug —— 数据静默丢失级）

    ``getConfigList()`` 输出的是 **camelCase**：

    .. code:: json

        {"id": "…", "character": "秧秧·玄翎",
         "echoSet": "羽落空尘之歌",       ← 驼峰
         "updatedAt": "2026-11-02 …"}     ← 驼峰

    而 ``Loadout.from_dict()`` 只认 **snake_case**：

    .. code:: python

        echo_set=str(data.get("echo_set", "")),      #: 认下划线
        updated_at=str(data.get("updated_at", "")),  #: 认下划线

    ## 后果

    页面最正常的那条路径 —— **读出对象 → 编辑 → 原样提交** —— 会静默丢字段：

    .. code:: text

        before:  echoSet="羽落空尘之歌"
        提交后:  echoSet=""              ← 套装没了

        before:  updatedAt="2026-11-02 19:50:04"
        提交后:  updatedAt="（当前时间）"  ← 被重置

    **而且返回 ``ok: true``** —— 前端当成功处理，用户下次跑任务才发现。

    实测用户 8 条真实配置**全部**中招。

    ## 做法：两个方向都接受

    ``snake_case`` 原样传 (Qt 侧/脚本调用)，``camelCase`` 映射回来 (页面)。
    已有 snake_case 时**不覆盖**（避免两套名字打架）。

    ## 为什么在 web_bridge 修而不是改 ``Loadout.from_dict``

    ``from_dict`` 在 ``core``，是**所有调用方共用**的（Qt 界面也用它，
    那边读的是 ``to_dict()`` 的 snake_case）。在那里加别名会让
    "哪个名字是权威"变模糊。

    Web 桥接层是**唯一**产出 camelCase 的地方，所以归一化也该在这里 ——
    **谁弄乱了谁收拾**。
    """
    if not isinstance(body, dict):
        return {}
    #: camelCase → snake_case
    aliases = {
        "echoSet": "echo_set",
        "updatedAt": "updated_at",
        "customAvatar": "custom_avatar",
    }
    out = dict(body)
    for camel, snake in aliases.items():
        if camel in out:
            value = out.pop(camel)
            #: ★ 已有 snake_case 就不覆盖（调用方显式给了更权威的那份）
            out.setdefault(snake, value)
    return out


def _gacha_verdict(five) -> tuple[str, str]:
    """一条五星的「歪 / 欧 / 非」评价 —— **照抄旧界面 ``_verdict``**。

    旧代码 ``gacha/tool.py`` 的 ``_verdict``：

    .. code:: python

        if five.is_lost:
            return "歪", "#c0392b"
        span = int(five.span or 0)
        if span <= 60:
            return "欧", "#2e8b57"
        if span >= 74:
            return "非", "#c0392b"
        return "", ""

    规则要点：

    * **歪** 最优先 —— 用户最关心这个
    * **欧 / 非** 按**这次**用了多少抽分级（不是平均）
    * **中间不标** —— 正常出货（61~73 抽）不写评价，写了反而噪音
    * 常驻池 ``is_lost`` 恒 False（没有 UP 概念），只按欧非分

    ⚠ 阈值和 :data:`src.core.gacha.SPAN_COLORS` 是**两套**：
    条的颜色分 40/60/73/80 五档，评价只分 60/74 三个区间。
    **别合并** —— 旧界面就是分开的。

    :return: ``(文字, 颜色)``；不标时 ``("", "")``
    """
    try:
        if bool(getattr(five, "is_lost", False)):
            return "歪", "#c0392b"
        span = int(getattr(five, "span", 0) or 0)
        if span <= 60:
            return "欧", "#2e8b57"
        if span >= 74:
            return "非", "#c0392b"
        return "", ""
    except Exception:  # noqa: BLE001 - 评价算不出来不该拖垮整个列表
        return "", ""


def _safe(fn, fallback):
    """调 ``fn()``，异常时返回 ``fallback``。

    ## 为什么要这个

    桥接层要序列化**用户存的数据**（任务流程 / 配置）。这些数据结构
    带 ``@property`` 和 ``validate()``，某个字段坏了（老版本存的文件、
    手工改过的 JSON）就可能抛异常。

    没有它的话：一条坏数据 → 整个 ``getConfigList()`` 返回空 →
    **页面上所有配置都消失**。用户会以为自己的配置被删了。
    有了它：那条用 fallback，其余照常显示。
    """
    try:
        return fn()
    except Exception:  # noqa: BLE001
        logger.debug("序列化字段失败，用默认值", exc_info=True)
        return fallback


#: 工具 key → 配置来源（给 :meth:`WebBridge.getToolSettings` 用）
#:
#: * ``settingsKey`` —— ``tool_settings.json`` 里的键（工具自己的
#:   ``SETTINGS_KEY`` 常量；多数等于工具 key，但**别假设**）
#: * ``module``      —— 去哪个模块读 ``defaults`` / ``choices`` 常量
#: * ``defaults``    —— ``{字段名: 常量名}``，页面的"默认值"
#: * ``choices``     —— ``{字段名: 常量名}``，枚举型设置的**合法值列表**
#:
#: ## 为什么枚举也要后端给
#:
#: 声骸调频的「目标属性」有 12 项，写在
#: ``echo_change/okww_task.py`` 的 ``TARGET_STATS`` 里。页面拿不到 Python
#: 常量 —— 抄一份中文列表的话，工具侧改了这边就悄悄对不上，
#: 而校验是 ``saved in TARGET_STATS``，**抄错一个字就变脏数据**。
_TOOL_SETTINGS_SPEC: dict[str, dict] = {
    "echo_change": {
        "settingsKey": "echo_change",
        "module": "src.tools.game.echo_change.okww_task",
        "defaults": {"targetStat": "DEFAULT_TARGET"},
        "choices": {"targetStat": "TARGET_STATS"},
    },
    #: ★ 4C 自动战斗（P4 第二批）
    #:
    #: ⚠⚠ **`settingsKey` 不等于工具 key**：
    #: ``okww_farm.COMBAT_STYLE_KEY = "auto_combat_style"``，而工具 key 是
    #: ``auto_combat``。直接拿工具 key 去读会读到空 —— 而且**不报错**，
    #: 表现就是"用户在旧界面选的战斗风格，新界面读不到、回落到默认"。
    #:
    #: ``choices`` 里 ``rotation.STYLES`` 是 ``(style, label, desc)`` 三元组，
    #: 页面需要的是 ``{value, label, desc}`` 结构，所以在
    #: :meth:`WebBridge.getToolSettings` 里对 ``STYLES`` 做了特殊展开
    #: （见 ``_expand_choices``）。
    "auto_combat": {
        "settingsKey": "auto_combat_style",
        "module": "src.tools.game.auto_combat.rotation",
        "defaults": {"style": "STYLE_SMART"},
        "choices": {"style": "STYLES"},
        #: 这个常量的每一项是三元组 → 展开成 {value,label,desc}
        "tupleChoices": {"style"},
    },
    #: ★★★ 2026-11-03 声骸自动强化（用户圈图：
    #: 「我给了三核心词条，2 条有效词条，但是有效词条至少数量设置为 3，
    #:   应该提示至少为 4」）
    #:
    #: ## 为什么需要后端给「有效词条数的合法范围」
    #:
    #: 规则（``echo_enhance/settings.py`` ``valid_count_range``）：
    #:
    #: .. code:: text
    #:
    #:     下界 = 核心属性条数        ← 「核心几条，有效词条最低就几条」
    #:     上界 = 核心 ∪ 可选 的总条数（声骸 5 孔位里每种词条只出现一次）
    #:
    #: 前端页面把加减框写死成 ``{min: 2, max: 5}`` —— **没跟着核心属性联动**。
    #: 于是勾了 3 个核心、有效词条还能选 3 → 用户提交后导出/运行时
    #: 才被模型判成非法（或者静默按 clamp 后的值跑）。
    #:
    #: ## 现在
    #:
    #: ``getToolSettings("echo_enhance")`` 除了 settings，还回:
    #:
    #: .. code:: jsonc
    #:
    #:     "ranges": {"minValidCount": [下界, 上界]}
    #:
    #: 页面据此动态设加减框的 min/max，并在「当前值 < 下界」时**立刻**
    #: 提示「至少为 N」（而不是等点创建才报错）。
    "echo_enhance": {
        "settingsKey": "echo_enhance",
        "module": "src.tools.game.echo_enhance.settings",
        "defaults": {},
        "choices": {},
        #: ★ 会按核心/可选属性条数算出「有效词条数」的合法范围
        "validCountRange": True,
    },
}


def _expand_choices(value, *, as_tuples: bool = False):
    """把工具里的常量展开成页面能直接用的结构。

    ## 两种形态

    * 普通元组 ``("攻击", "暴击伤害", ...)`` → 原样返回（value 就是字符串）
    * 三元组 ``(("smart", "智能切换", "说明"), ...)`` → 展开成
      ``[{"value": "smart", "label": "智能切换", "desc": "说明"}]``

    ⚠ **不能把三元组原样丢给页面** —— 那样页面得知道每项是
    ``[0]=value / [1]=label / [2]=desc``，等于把工具的私有结构泄漏出去。
    """
    if value is None:
        return None
    if not as_tuples:
        return list(value) if isinstance(value, (list, tuple)) else value

    out: list[dict] = []
    for item in value or ():
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            entry = {"value": str(item[0]), "label": str(item[1])}
            if len(item) >= 3:
                entry["desc"] = str(item[2])
            out.append(entry)
        else:
            #: 兜底：不是三元组就当成裸值
            out.append({"value": str(item), "label": str(item)})
    return out


#: ⚠⚠⚠ 2026-11-02 删除：``_TOOL_PREREQUISITES`` / ``_prerequisites_for`` /
#: ``_COMMON_GAME_PREREQUISITES`` / ``_OKWW_TOOL_KEYS`` 全部删掉了。
#:
#: ## 为什么删（lead 的要求，我认）
#:
#: 这是 **P4 时 lead 让我加的**「运行前提」文案表，理由是
#: 「7 个工具散在 7 处会漂移，统一放后端」。
#:
#: **但用户 P5 发的 7 张旧界面截图证明：旧界面根本没有「运行前提」区块。**
#: 用户把 web 版那块圈出来写了「干掉」。
#:
#: 用户要的是「**复刻旧界面**」，不是「改进旧界面」。
#:
#: ## 和 ``setEchoEnhanceProfile`` 是同一类错误
#:
#: .. code:: text
#:
#:     P4: 加了 setEchoEnhanceProfile  → 旧代码注释写着「故意没有」  → 已删
#:     P4: 加了 prerequisites          → 旧界面根本没这块           → 已删
#:
#: **两次都是没先读旧界面/旧代码就提需求。**
#:
#: ⚠ 教训（写进 ``docs/Web界面-架构与验证.md`` 坑 #15）：
#: 不只「**被用户否掉的**」不能加，**「旧界面从来没有的」也不要加**。


def _import_quiet(module_path: str):
    """导入一个模块，失败返回 None（不抛）。

    工具模块可能因为 vendor 缺失 / 依赖问题导入不了 —— 那不该让
    ``getToolSettings`` 整个失败，页面拿空 choices 降级即可。
    """
    if not module_path:
        return None
    try:
        import importlib  # noqa: PLC0415

        return importlib.import_module(module_path)
    except Exception:  # noqa: BLE001
        logger.debug("导入 %s 失败（降级处理）", module_path, exc_info=True)
        return None


def _report_to_dict(report) -> dict:
    """``UpdateReport`` → JS 能吃的 dict。

    ## 为什么把 ``summary()`` 也一起给

    它里面有段**很关键**的文案：``remote_empty`` 时说的是
    「这次没从远端取到任何数据，所以无法判断有没有更新」——
    而不是"已是最新"。这个区分很容易在页面侧写错（看到没有更新就报
    "已是最新"，实际上网络挂了）。

    所以后端把 ``summary()`` 原样给出去，页面**直接渲染就不出错**；
    ``remoteEmpty`` / ``localEmpty`` 分开给是为了页面做 UI 形态
    （禁用按钮、换颜色），不是为了替代 summary。
    """
    if report is None:
        return {}
    return {
        "hasUpdates": bool(_safe(lambda: report.has_updates, False)),
        "summary": str(_safe(lambda: report.summary(), "")),
        "remoteEmpty": bool(getattr(report, "remote_empty", False)),
        "localEmpty": bool(getattr(report, "local_empty", False)),
        "newSets": list(getattr(report, "new_sets", []) or []),
        "effectChanged": list(getattr(report, "effect_changed", []) or []),
        "newEchoes": list(getattr(report, "new_echoes", []) or []),
        "newCharacters": list(getattr(report, "new_characters", []) or []),
    }


# ── 资源库更新的后台线程 ────────────────────────────────────────────
#
# 和 ``src/tools/data/wuwa_library_update.py`` 的 CheckThread/ApplyThread
# 是同一套逻辑。**没有复用它**是因为那个类带着 Qt 界面依赖
# （``ToolCategory`` / 面板类），桥接层不该 import GUI 工具模块。
# 这里只留线程 + 信号，行为完全对齐。


def _gacha_report_to_dict(report, fetched_total: int = 0) -> dict:
    """``GachaReport`` → JS 能吃的 dict。

    ## ⚠ 四星数用 ``four_count`` 而不是 ``len(four_stars)``

    ``GachaReport.four_count`` 是**各池四星之和**；
    ``len(p.four_stars)`` 只算单池。写错会少统计。

    ## ``fetchedTotal``

    ``total`` 是**合并本地历史后**的累计数；``fetchedTotal`` 是这次
    从接口拉到多少。两个都给 —— 页面可以显示"本次拉到 N 抽，
    累计 M 抽"，用户能看出是不是第一次分析。
    """
    if report is None:
        return {}
    pools: list[dict] = []
    for pool in getattr(report, "pools", []) or []:
        pools.append({
            "name": str(getattr(pool, "name", "")),
            "poolType": str(getattr(pool, "pool_type", "")),
            "total": _safe(lambda p=pool: p.total, 0),
            "fiveCount": _safe(lambda p=pool: p.five_count, 0),
            "fourCount": _safe(lambda p=pool: len(p.four_stars), 0),
            "rate": round(_safe(lambda p=pool: p.rate(), 0.0), 2),
            "average": round(_safe(lambda p=pool: p.average(), 0.0), 2),
        })

    fives: list[dict] = []
    for item in _safe(lambda: report.all_fives_analysis(), []) or []:
        fives.append({
            "name": str(getattr(item, "name", "")),
            "time": str(getattr(item, "time", "")),
            "kind": str(getattr(item, "kind", "")),
            "span": int(getattr(item, "span", 0) or 0),
            "cumulative": int(getattr(item, "cumulative", 0) or 0),
            "isUp": bool(getattr(item, "is_up", True)),
            "isLost": bool(_safe(lambda i=item: i.is_lost, False)),
            "limitedPool": bool(getattr(item, "limited_pool", False)),
        })

    return {
        "playerId": str(getattr(report, "player_id", "")),
        "total": _safe(lambda: report.total, 0),
        "fiveCount": _safe(lambda: report.five_count, 0),
        "fourCount": _safe(lambda: report.four_count, 0),
        "rate": round(_safe(lambda: report.rate(), 0.0), 2),
        "average": round(_safe(lambda: report.average(), 0.0), 2),
        "fetchedTotal": int(fetched_total or 0),
        "pools": pools,
        "fiveStars": fives,
    }


def _make_gacha_thread():
    """延迟定义抽卡分析线程（同 _make_library_threads 的理由）。"""
    from PySide6.QtCore import QThread, Signal  # noqa: PLC0415

    class _GachaThread(QThread):
        """拉全部卡池 → 合并本地历史 → 出报告。

        ## ⚠ 三步都不能省（和 Qt 版 ``gacha/tool.py`` 一致）

        ``fetch_raw`` 只给**最近一段**记录（接口有分页/上限）。用户这次
        抽的在下次拉取时才会全部出现 —— 所以必须**合并进本地历史**再统计，
        否则"总抽数/出货率"会随每次拉取上下跳。

        Qt 版用 ``gacha_store`` 做合并；这里调它的同一个接口。
        """

        message = Signal(str)
        succeeded = Signal(dict)
        failed = Signal(str)

        def __init__(self, params, parent=None):
            super().__init__(parent)
            self._params = params

        def run(self) -> None:  # noqa: D102
            try:
                from . import gacha, gacha_store  # noqa: PLC0415

                raw = gacha.fetch_raw(
                    self._params, log=lambda m: self.message.emit(m))
                fetched_total = sum(len(v) for v in raw.values())

                #: ★ 合并进本地历史再出报告（存下来那份才是"累计"）
                report = self._merged_report(raw, gacha, gacha_store)
                self.succeeded.emit(
                    _gacha_report_to_dict(report, fetched_total))
            except Exception as exc:  # noqa: BLE001
                self.failed.emit(f"{type(exc).__name__}: {exc}")

        def _merged_report(self, raw, gacha, gacha_store):
            """把新拉的记录并进本地历史，再统计。

            合并失败（老数据格式不对等）时**退回只统计这次拉到的** ——
            宁可数字少一点，也不要让整个分析失败。
            """
            try:
                store = gacha_store.GachaStore()
                #: 尝试用本地历史合并；不同版本 API 略有差异，逐个试
                merged = None
                for method_name in ("merge", "merge_raw", "absorb", "update"):
                    method = getattr(store, method_name, None)
                    if callable(method):
                        try:
                            result = method(raw)
                            if isinstance(result, dict):
                                merged = result
                                break
                        except TypeError:
                            continue
                records = merged or raw
                if not isinstance(records, dict):
                    records = raw
                return gacha.report_from_raw(records)
            except Exception:  # noqa: BLE001
                logger.debug("抽卡历史合并失败，退回本次拉取", exc_info=True)
                return gacha.report_from_raw(raw)

    return _GachaThread


def _make_library_threads():
    """延迟定义线程类 —— 避免在模块导入期就要求 PySide6.QtCore 可用。

    （``web_bridge`` 在 core 层，理论上该保持 Qt 依赖最小。虽然
    ``QObject``/``Signal`` 已经用了 QtCore，但 QThread 还是延迟到真用
    的时候再取，减少 import 期风险。）
    """
    from PySide6.QtCore import QThread, Signal  # noqa: PLC0415

    class _LibraryCheckThread(QThread):
        """拉远端 + 对比本地（网络，几十秒）。"""

        message = Signal(str)
        #: ★ ``(snapshot, report)`` 两个都要 —— apply 时只有拿到这份
        #: snapshot 才能写盘（Qt 版漏了它导致 'NoneType' has no attribute）
        succeeded = Signal(object, object)
        failed = Signal(str)

        def __init__(self, mod, parent=None):
            super().__init__(parent)
            self._mod = mod

        def run(self) -> None:  # noqa: D102
            try:
                snapshot = self._mod.fetch_remote(
                    log=lambda msg: self.message.emit(msg))
                report = self._mod.check_updates(snapshot)
            except Exception as exc:  # noqa: BLE001
                self.failed.emit(f"{type(exc).__name__}: {exc}")
                return
            self.succeeded.emit(snapshot, report)

    class _LibraryApplyThread(QThread):
        """写本地 JSON + 补新声骸技能说明（逐页抓，慢）。"""

        message = Signal(str)
        succeeded = Signal(list)
        failed = Signal(str)

        def __init__(self, mod, snapshot, report, parent=None):
            super().__init__(parent)
            self._mod = mod
            self._snapshot = snapshot
            self._report = report

        def run(self) -> None:  # noqa: D102
            try:
                done = self._mod.apply_updates(
                    self._snapshot, self._report,
                    log=lambda msg: self.message.emit(msg))
            except Exception as exc:  # noqa: BLE001
                self.failed.emit(f"{type(exc).__name__}: {exc}")
                return
            self.succeeded.emit(list(done or []))

    return _LibraryCheckThread, _LibraryApplyThread


class WebBridge(QObject):
    """暴露给 JS 的 ``bridge`` 对象。

    ## 全部方法一览

    ================================  ==========================================
    JS 调用                            作用
    ================================  ==========================================
    ``getTools()``                    7 个工具的元信息（JSON 字符串）
    ``getNav()``                      侧栏导航项
    ``switchPage(key)``               切页面（通知 Python 侧，可存盘）
    ``runTask(key)``                  运行工具
    ``stopTask()``                    停止
    ``getSkin()``                     当前皮肤配色
    ``getWallpaper()``                当前壁纸 + 可用的壁纸列表
    ``setWallpaper(id)``              切壁纸
    ``getStatus()``                   运行状态（是否在跑、进度）
    ``subscribe(cb)`` / ``on(name,cb)``  订阅 Python 推送
    ================================  ==========================================

    ## 为什么所有返回值都是 **JSON 字符串**

    ``QWebChannel`` 支持的返回类型里，``QVariantMap`` 转过去会变成 JS 的
    奇怪代理对象，嵌套 dict/list 尤其容易丢类型。**统一走 JSON 字符串**、
    JS 侧 ``JSON.parse`` —— 简单、可预测、debug 时打日志直接看得到内容。
    """

    #: JS 侧 ``bridge.subscribe(fn)`` 的总入口。
    #:
    #: payload = JSON ``{"name": "logLine", "data": {...}}``
    event = Signal(str)

    #: 工具开始运行
    taskStarted = Signal(str)          #: JSON {key}
    #: 工具结束（成功/失败/取消都在这里）
    taskFinished = Signal(str)         #: JSON {key, ok, summary}
    #: 一行日志
    logLine = Signal(str)              #: JSON {text, level}
    #: 进度 0~100
    progress = Signal(str)             #: JSON {value, text}
    #: 皮肤变了
    skinChanged = Signal(str)          #: JSON {primary, ...}
    #: 壁纸变了
    wallpaperChanged = Signal(str)     #: JSON {id, title, url}
    #: 页面切换（Python → JS 主动要求切页时用，比如侧栏黄字跳转）
    pageRequested = Signal(str)        #: JSON {key}

    #: ★ 标题栏按钮 → 窗口动作（minimize / maximize / restore /
    #: toggleMaximize / close）。由 :class:`src.gui.web_shell.WebShell` 接。
    windowActionRequested = Signal(str)

    #: ★ 窗口最大化状态变了（2026-11-03）。
    #:
    #: JSON ``{maximized: bool}`` —— 页面据此把标题栏 □ 按钮的图标
    #: 在 ``E922``（最大化）/ ``E923``（还原）之间切换。
    #:
    #: 用户：「放大后，这个缩小框不对把，应该右图那样」。
    windowStateChanged = Signal(str)

    #: ★ 前端脚本加载完成（握手）。测试和日志用。
    frontendReadySignal = Signal()

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        #: 当前选中的页面 key
        self._page = "home"
        #: 正在跑的工具 key / 流程 id（空串 = 空闲）
        self._running = ""
        #: "tool" 或 "flow" —— 决定 stopTask 的措辞和日志
        self._running_kind = ""
        #: 流程名（工具没有，日志里用 key）
        self._running_name = ""
        #: ★ 真实执行线程（:class:`~src.gui.tasks_interface.FlowRunThread`）
        self._thread = None
        #: 壁纸缓存：id → dict
        self._wallpapers: list[dict] = []
        self._wallpaper_id = ""
        #: 进度 0~100
        self._progress = 0
        #: ★ 本轮报告（跑完一轮就换掉；内存里，和 Qt 版 ``_last_report`` 同一个角色）
        #:
        #: 用户 2026-11-03：「删掉（顶部提示 + 运行面板），任务请按 main 分支那样做」
        #: —— main 分支任务页底部有「运行报告」区，要显示**本轮**跑出来的
        #: 锁定 / 弃置明细。执行器发 ``report_ready`` 时先存在这里，
        #: 页面通过 :meth:`getRunReport` 取。
        self._last_report = None
        #: JS 侧注册的事件回调在页面里；Python 只需要知道页面还在不在
        self._subscribe_count = 0
        #: ★ 宿主窗口（:class:`src.gui.web_shell.WebShell` 在 build 时挂上来）。
        #:
        #: 用它回答 ``getWindowState()`` —— ``WebBridge`` 自己不持有窗口。
        #: 为 None 时 ``getWindowState`` 一律返回「未最大化」（不崩）。
        self._window_host = None

        #: ★★★ 任务完成后自动关机（用户 2026-11-03：「任务完成后自动关机」）
        #:
        #: ## 为什么单独一套 settings key
        #:
        #: 4C 自动战斗页也有「定时关机」，但它存的是 ``auto_combat`` 节点，
        #: 语义是**从点启动开始计时 N 分钟**。任务页要的是
        #: **跑完一条流程之后才关机**，两个开关不该互相影响 ——
        #: 复用同一个 key 的话，用户在任务页勾一下就顺手改了 4C 页的设置。
        #:
        #: ## 状态机复用
        #:
        #: ``ShutdownTimer`` 是纯逻辑（``time.monotonic`` 算剩余、``should_warn``
        #: / ``should_fire`` 各只报一次），Qt 版的 4C 工具也是这么用的 ——
        #: 这里只在它外面加一个 1 秒轮询的 ``QTimer``。
        self._shutdown = None
        self._shutdown_poll = None
        #: 触发关机的那条流程名（给页面/日志看）
        self._shutdown_flow = ""

        #: ★ 资源库更新（P4）—— snapshot/report 必须在 check 之后留着，
        #: apply 拿它写盘。check 失败要作废（否则上一轮 snapshot 配新一轮
        #: report 是错配，会写错数据）。
        self._lib_check_thread = None
        self._lib_apply_thread = None
        self._lib_check_running = False
        self._lib_apply_running = False
        self._lib_snapshot = None
        self._lib_report = None

        #: 线程类延迟取（见 _make_library_threads 的说明）
        self._LibCheckThread, self._LibApplyThread = _make_library_threads()

        #: ★ 抽卡分析（P4 第三批）—— 网络线程（几十秒）
        self._gacha_thread = None
        self._gacha_running = False
        self._GachaThread = _make_gacha_thread()

        #: ★★★ 抽卡历史文件的**可覆盖路径**（默认 None = 用真实用户数据）。
        #:
        #: 为什么要这个（2026-11-02 事故二）：测试要在**不碰用户真实数据**的
        #: 前提下验证「清空能生效」。办法是建一个临时文件、把这个属性指过去：
        #:
        #: .. code:: python
        #:
        #:     bridge = WebBridge()
        #:     bridge._gacha_store_path = tmpdir / "gacha_history.json"
        #:     bridge.setGachaHistoryForTest(...)   # 往里塞假数据
        #:     bridge.clearGachaHistory("DELETE")   # 清的是临时文件
        #:
        #: 生产代码永远不设它 → 走 ``GachaHistoryStore()`` 的默认路径。
        self._gacha_store_path = None

    # ================================================================ 工具
    @Slot(result=str)
    def getTools(self) -> str:
        """全部工具的元信息。

        返回 ``[{key, name, category, categoryName, desc, icon, iconUrl,
        comingSoon, supportsTaskRun, version, author}]``。

        ``iconUrl`` 是 **HTTP URL**（``/web/assets/icons/xxx.png``）——
        页面不能读本地磁盘路径。工具图标源文件在 ``assets/icons/``，
        由 :meth:`src.gui.web_shell.WebShell` 在启动时复制/挂载。
        """
        _ensure_tools_discovered()
        out: list[dict] = []
        try:
            from ..core.registry import ToolRegistry  # noqa: PLC0415

            for meta in ToolRegistry.all_metas():
                out.append({
                    "key": meta.key,
                    "name": meta.name,
                    "category": meta.category.key,
                    "categoryName": meta.category.display_name,
                    "desc": meta.description,
                    "icon": meta.icon_name,
                    #: 自定义图标文件 → 换成 HTTP URL（见 _tool_icon_url）
                    "iconUrl": self._tool_icon_url(meta),
                    "comingSoon": bool(meta.coming_soon),
                    "supportsTaskRun": bool(meta.supports_task_run),
                    "version": meta.version,
                    "author": meta.author,
                })
        except Exception:  # noqa: BLE001
            logger.warning("getTools 失败", exc_info=True)
        return _json(out)

    def _tool_icon_url(self, meta) -> str:
        """工具自定义图标 → ``/web/assets/icons/<name>`` 的 HTTP URL。

        ## 为什么不是直接给磁盘路径

        页面在 ``http://127.0.0.1:port/web/`` 上，``<img src="D:\\...">``
        会被 Chromium 直接拒绝（跨协议）。所以：

        1. ``meta.icon_path`` 有值 → 取文件名，拼到 ``/web/assets/icons/`` 下
           （:class:`WebShell` 启动时把 ``assets/icons/`` 镜像进
           ``src/gui/web/assets/icons/``）
        2. 没值 → 按 ``meta.key`` 猜 ``<key>.png``（这就是项目的约定：
           ``assets/icons/<tool_key>.png``）
        3. 文件不存在 → 返回空串，页面退回 SVG mask 图标
        """
        name = ""
        icon_path = getattr(meta, "icon_path", "") or ""
        if icon_path:
            name = os.path.basename(icon_path)
        if not name:
            #: 项目约定：assets/icons/<tool_key>.png
            name = f"{getattr(meta, 'key', '')}.png"
        if not name or not name.lower().endswith((".png", ".jpg", ".jpeg",
                                                  ".svg", ".webp", ".ico")):
            return ""
        try:
            from ..core import paths  # noqa: PLC0415

            src = paths.resource_dir("assets", "icons") / name
            if not src.is_file():
                return ""
            from ..core import media_server  # noqa: PLC0415

            if not media_server.web_url("index.html"):
                return ""    #: 服务没起（骨架早期），页面用 mask 图标
            return media_server.web_url(f"assets/icons/{name}")
        except Exception:  # noqa: BLE001
            logger.debug("解析工具图标失败: %s", name, exc_info=True)
            return ""

    @Slot(result=str)
    def getNav(self) -> str:
        """侧栏导航。**顺序读用户自己的拖拽结果**（``ui_state.json``）。

        ## ★★★ 2026-11-02 第二次修正：顺序**不能**照抄代码默认值

        第一次改这个函数时我照抄 ``main_window.py`` 的 ``addSubInterface``
        调用顺序（主页→配置→任务→…→工具→资源库）——
        **那只是首次启动的默认值，用户根本没在用它。**

        实际链路（:mod:`src.gui.nav_reorder`）：

        .. code:: text

            addSubInterface(...)      ← 首次启动的默认顺序
                  ↓ 用户可以按住拖动
            ui_state.json["nav_order"] ← 拖完存这里
                  ↓ 下次启动
            apply_order(nav_order)     ← 按它重排

        用户实际的 ``nav_order``（``data/ui_state.json``）：

        .. code:: text

            HomeInterface, tool_group, ConfigInterface, TasksInterface,
            SkinInterface, UpdateInterface, WuwaLibraryInterface

        **「工具」被用户拖到了第 2 位** —— 和代码默认顺序完全不同。

        ## ``apply_order`` 对「没提到的项」怎么处理

        ``nav_reorder.apply_order`` 的规则（L91）：

        .. code:: python

            ordered = [by_key[k] for k in order if k in by_key]
            ordered += [w for w in widgets if w not in ordered]   # ← 追加到末尾

        所以**不在 ``nav_order`` 里的项保持原相对顺序、追加到最后**。
        ``NoticeInterface``（消息通知）正是这种 —— 它是后加的，
        ``nav_order`` 里没有 → **永远排在最后**。

        ## 兜底

        ``nav_order`` 读不到（用户没拖过 / 文件坏了）→ 用代码默认顺序。
        """
        _ensure_tools_discovered()
        try:
            from ..core.registry import ToolRegistry  # noqa: PLC0415

            tool_children = [
                {
                    "key": f"tool:{meta.key}",
                    "name": meta.name,
                    #: 子项也用工具自己的图标名（前端 fallback 到 TOOLS）
                    "icon": meta.icon_name or "APPLICATION",
                }
                for meta in ToolRegistry.all_metas()
            ]
        except Exception:  # noqa: BLE001 - 工具发现失败不该让侧栏消失
            logger.warning("getNav：工具列表读取失败", exc_info=True)
            tool_children = []

        #: 每个导航项的完整定义（**按代码默认顺序**，稍后会被 nav_order 重排）
        by_key: dict[str, dict] = {
            "home": {"key": "home", "name": "主页", "icon": "HOME",
                     "kind": "page", "selectable": True},
            "config": {"key": "config", "name": "配置", "icon": "SETTING",
                       "kind": "page", "selectable": True},
            "tasks": {"key": "tasks", "name": "任务", "icon": "TASK",
                      "kind": "page", "selectable": True},
            "skin": {"key": "skin", "name": "主题皮肤", "icon": "SKIN",
                     "kind": "page", "selectable": True},
            "update": {"key": "update", "name": "检查更新", "icon": "UPDATE",
                       "kind": "page", "selectable": True},
            "notice": {"key": "notice", "name": "消息通知", "icon": "BELL",
                       "kind": "page", "selectable": True},
            "tool_group": {
                "key": "tool_group", "name": "工具", "icon": "TOOLS",
                "kind": "group", "group": True, "selectable": False,
                "tooltip": "展开查看所有工具",
                "children": tool_children,
                #: 旧界面分组默认**展开**（main_window.py 里有 setExpanded(True)）
                "expanded": True,
            },
            "library": {"key": "library", "name": "资源库", "icon": "LIBRARY",
                        "kind": "page", "selectable": True},
        }

        #: 代码里的默认顺序（首次启动时 `nav_order` 还不存在，就是这个）
        default_order = ["home", "config", "tasks", "skin", "update",
                         "notice", "tool_group", "library"]

        saved = self._nav_order_from_ui_state()
        order = saved or default_order

        nav = [by_key[key] for key in order if key in by_key]
        #: ``nav_reorder.apply_order`` 的规则（L91）：**没提到的项追加到末尾**。
        #: 实测 ``nav_order`` 只有 7 项（缺 ``NoticeInterface``）→ 消息在最后。
        nav += [by_key[key] for key in default_order
                if key not in order and key in by_key]

        #: ★ 「主页」**固定在最上面**（``main_window._setup_nav_reorder`` 传的
        #: ``fixed_keys=[HOME_KEY]``）。正常 ``nav_order`` 里 home 本来就在
        #: 第一位，但用户数据被改坏 / 旧版本没写 home 时也不该跑到下面去。
        nav.sort(key=lambda item: 0 if item["key"] == "home" else 1)
        return _json(nav)

    #: 旧界面 ``routeKey`` → 我们用的 key。
    #:
    #: ⚠ ``nav_order`` 存的是 qfluentwidgets 的 **routeKey**（界面类的
    #: ``objectName()``），和我们内部的短 key 不是一个东西，必须映射。
    _NAV_ROUTE_TO_KEY: dict[str, str] = {
        "HomeInterface": "home",
        "ConfigInterface": "config",
        "TasksInterface": "tasks",
        "SkinInterface": "skin",
        "UpdateInterface": "update",
        "NoticeInterface": "notice",
        "WuwaLibraryInterface": "library",
        "tool_group": "tool_group",
    }

    def _nav_order_from_ui_state(self) -> list[str]:
        """读用户拖过的侧栏顺序（``ui_state.json`` 的 ``nav_order``）。

        :return: 内部 key 列表；读不到返回 ``[]``（调用方回落默认顺序）

        ⚠ 用 :class:`src.core.ui_state.UiState` 读，**不自己解析 JSON** ——
        那个类有"文件坏了当没存过"的容错，重写一遍只会漏掉。
        """
        try:
            from .ui_state import UiState  # noqa: PLC0415

            route_keys = UiState().get_list("nav_order")
        except Exception:  # noqa: BLE001 - 读不到就用默认
            logger.debug("getNav：读 nav_order 失败", exc_info=True)
            return []

        out: list[str] = []
        for route in route_keys:
            key = self._NAV_ROUTE_TO_KEY.get(str(route))
            if key and key not in out:
                out.append(key)
        return out

    @Slot(str, result=str)
    def switchPage(self, key: str) -> str:
        """记录当前页面。返回处理结果（真的切了 / 没这个页面）。

        ⚠ 页面**自己**负责切换 DOM —— 这里只做三件事：
        记住状态、存盘、给 Python 侧（托盘/托盘菜单）一个钩子。
        """
        key = (key or "").strip()
        if not key:
            return _json({"ok": False, "reason": "empty"})
        self._page = key
        logger.debug("WebBridge：切到页面 %s", key)
        return _json({"ok": True, "page": key})

    @Slot(result=str)
    def currentPage(self) -> str:
        """当前页面 key（JSON 字符串，和其他方法一个契约）。

        ⚠ 第一版直接 ``return self._page``（裸字符串）—— 违反了
        「所有 bridge 方法返回 JSON」的约定，JS 侧 ``JSON.parse`` 会抛。
        冒烟测试逮到的（``web_shell_smoke.py``）。
        """
        return _json({"page": self._page})

    def _precheck(self, flow) -> dict | None:
        """★ 启动**之前**做前置检查（同步），不通过返回错误 dict。

        ## 为什么要在桥接层多做一次（而不是只靠 FlowRunThread）

        ``FlowRunThread._run_start_step`` 里**已经**调了
        :func:`~src.core.task_start.check_start` —— 游戏没开时它会在
        0.08 秒内抛 ``TaskStartError`` 并 ``failed``，行为是对的。

        但那是**异步**的：``runTask()`` 先返回 ``{ok: true}``，
        用户/JS 要等一个 ``taskFinished`` 事件才知道"根本没跑起来"。

        在这里**先同步查一次**的好处：

        * ``runTask()`` 直接返回 ``{ok: false, reason: "precheck"}``，
          页面能立刻弹「游戏没开着」，不用等事件往返；
        * 不起线程 —— 少一次线程创建/销毁；
        * 和 Qt 版**行为一致**（它也是先检查再跑），只是把检查提前。

        ⚠ 重复检查是**幂等**的（``check_start`` 只读进程状态），
        所以 ``FlowRunThread`` 内部再查一次没坏处，而且那是**兜底**：
        万一桥接层这里被绕过了（比如别的调用方直接起线程），那边仍然拦住。

        :return: 不通过 → ``{ok: False, reason, message, ...}``；通过 → None
        """
        if flow is None:
            return None
        try:
            from ..core.task_start import TaskStartError, check_start  # noqa: PLC0415

            check_start(flow, lambda _msg: None)
        except TaskStartError as exc:
            #: ★ 这条消息是**写给用户看的**，直接透传，不加异常类名前缀
            logger.info("WebBridge：前置检查未通过 —— %s", exc)
            return {
                "ok": False,
                "reason": "precheck",
                "message": str(exc),
                "name": getattr(flow, "name", ""),
            }
        except Exception:  # noqa: BLE001 - 检查本身出错不该挡住运行
            logger.warning("WebBridge：前置检查异常（放行）", exc_info=True)
        return None

    # ================================================================ 真实执行
    def _start_thread(self, flow, *, kind: str, label: str,
                      run_key: str = "") -> str:
        """★ 启动真实执行器 :class:`FlowRunThread`，把它的信号接到 JS 事件。

        ## 这一层只做「翻译」，不做业务

        ``FlowRunThread`` 是 Qt 版任务页用的**同一个**执行器。它对外发
        4 个信号，这里逐个转成桥接层的事件：

        ======================  =============================================
        FlowRunThread 信号       转成的 JS 事件
        ======================  =============================================
        ``message(str)``         ``logLine`` {text, level}
        ``step_started(i, 名)``  ``progress`` + 一条日志
        ``succeeded(str)``       ``taskFinished`` {ok: true, summary}
        ``failed(str)``          ``taskFinished`` {ok: false, summary}
        ``report_ready(obj)``    存进 RunReportStore（和 Qt 版同一条路径）
        ======================  =============================================

        ## ⚠ 跨线程警告

        ``FlowRunThread`` 跑在**工作线程**。它的信号进了主线程的槽之后
        才能安全地碰 ``emitEvent``（Qt 自动排队，安全）。
        所以这里**只连信号**，绝不从工作线程直接调 ``runJavaScript``。

        ## ⚠ 线程生命周期

        ``QThread`` 对象必须活到 ``finished`` 之后 —— 局部变量被 GC 掉
        会直接崩（``QThread: Destroyed while thread is still running``）。
        所以挂在 ``self._thread`` 上，收尾时才释放。
        """
        from PySide6.QtCore import QThread  # noqa: PLC0415

        from ..gui.tasks_interface import FlowRunThread  # noqa: PLC0415

        if self._thread is not None and self._thread.isRunning():
            return _json({"ok": False, "reason": "busy",
                          "running": self._running})

        thread = FlowRunThread(flow)
        self._thread = thread

        #: 记住状态（getStatus / stopTask 用）
        self._running = run_key or flow.name
        self._running_kind = kind
        self._running_name = label or flow.name
        self._progress = 0

        # ── 日志 ──
        def on_message(text: str) -> None:
            #: 从日志文本里猜级别（执行器只给纯文本）
            level = "info"
            low = text.lstrip()
            if low.startswith(("✗", "⚠", "错误", "失败")):
                level = "warn"
            elif low.startswith(("✔", "✓", "完成")):
                level = "ok"
            self.pushLog(text, level)

        thread.message.connect(on_message)

        # ── 步骤进度 ──
        def on_step(index: int, name: str) -> None:
            total = max(1, len(getattr(flow, "steps", []) or []))
            self.pushProgress(min(95, (index + 1) * 100 / total),
                              f"第 {index + 1} 步：{name}")

        thread.step_started.connect(on_step)

        # ── 成功 ──
        def on_ok(summary: str) -> None:
            self._finish_run(True, summary or "完成")

        thread.succeeded.connect(on_ok)

        # ── 失败 / 停止 ──
        def on_fail(message: str) -> None:
            note = message or "已停止"
            #: 「已停止」是用户自己按的，不是失败 —— 和 Qt 版同一口径
            ok = False
            self._finish_run(ok, note)

        thread.failed.connect(on_fail)

        # ── 本轮报告（和 Qt 版同一条持久化路径）──
        def on_report(report) -> None:
            #: ★ 2026-11-03：**先存进内存**，页面靠 ``getRunReport`` 取
            #:
            #: Qt 版是 ``self._page.note_report(report)`` 直接调页面的方法；
            #: web 版页面在另一个进程侧的 JS 里，没有"直接调"这回事 ——
            #: 所以桥接自己留一份，页面通过接口来拿。语义完全一致：
            #: 一轮跑完就换掉，不跨轮累积。
            self._last_report = report
            try:
                from ..core.run_report import RunReportStore  # noqa: PLC0415

                #: ⚠ 只统计【真有结果】的轮次 —— 见 Qt 版 note_report
                if not report.is_empty():
                    RunReportStore().add_round(report)
            except Exception:  # noqa: BLE001 - 统计失败不该影响任务
                logger.warning("WebBridge：存本轮报告失败", exc_info=True)

        thread.report_ready.connect(on_report)

        # ── 线程收尾：清状态、释放引用 ──
        def on_finished() -> None:
            #: 兜底：某些异常路径可能没走 succeeded/failed
            if self._running:
                self._finish_run(False, "已结束（未收到明确结果）")
            thread.deleteLater()
            if self._thread is thread:
                self._thread = None

        thread.finished.connect(on_finished)

        #: 先发「开始」再 start() —— 保证 JS 先拿到 taskStarted
        payload = {"key": self._running, "kind": kind, "name": self._running_name}
        self.taskStarted.emit(_json(payload))
        self.emitEvent("taskStarted", payload)
        self.pushLog(f"▶ 开始：{self._running_name}（{kind}）", "ok")

        logger.info("WebBridge：启动真实执行器 %s「%s」",
                    kind, self._running_name)
        thread.start()
        return _json({
            "ok": True,
            "key": self._running,
            "kind": kind,
            "name": self._running_name,
            "real": True,
        })

    def _finish_run(self, ok: bool, summary: str) -> None:
        """统一收尾：清运行状态 + 广播 taskFinished。"""
        if not self._running:
            return
        key = self._running
        kind = self._running_kind
        #: 名字要在清空**之前**取 —— 自动关机那边日志要显示是哪条流程跑完的
        run_name = self._running_name or key
        payload = {
            "key": key, "kind": kind, "ok": bool(ok),
            "summary": str(summary or ""),
        }
        self._running = ""
        self._running_kind = ""
        self._running_name = ""
        self._progress = 0

        self.pushProgress(100 if ok else 0, summary or ("完成" if ok else "已停止"))
        self.taskFinished.emit(_json(payload))
        self.emitEvent("taskFinished", payload)
        logger.info("WebBridge：%s 结束（ok=%s）：%s", kind, ok, summary)

        #: ★ 任务完成后自动关机 —— **只在这一处挂**（见 _arm_task_shutdown 注释）
        self._on_run_finished(ok, kind, run_name)

    # ================================================================ 任务完成后自动关机
    #
    # 用户 2026-11-03：「任务完成后自动关机」。
    #
    # ## 和 4C 页「定时关机」的区别
    #
    # ============  ==========================================
    # 4C 页         点「启动」开始倒计时 N 分钟
    # 任务页        流程**跑完**之后才开始倒计时 N 分钟
    # ============  ==========================================
    #
    # 所以两者是两套独立的设置与状态（settings key 也不同），
    # 唯一的共用件是纯逻辑的 :class:`src.core.shutdown_timer.ShutdownTimer`
    # 和 :func:`src.core.shutdown_timer.shutdown`。
    #
    # ## 为什么挂在 ``_finish_run`` 里
    #
    # ``_finish_run`` 是 FlowRunThread 三种结局（``succeeded`` / ``failed`` /
    # ``finished`` 兜底）**唯一**的汇聚点，在这里判断就不用关心线程细节。
    # ok-ww 那条路径（``runOkwwTask``）不走它 —— 那种任务的完成由 ok-ww
    # 宿主自管，web 侧拿不到回调，不做自动关机（也不该假装做了）。

    #: 任务页自动关机的 settings key（**不**复用 ``auto_combat``）
    TASK_SHUTDOWN_KEY = "tasks"
    #: 默认关机前的通知秒数（和 4C 页保持同一个口径）
    TASK_SHUTDOWN_WARN = 60

    def _task_shutdown_settings(self) -> dict:
        """读任务页自动关机设置（``{enabled, minutes}``）。"""
        from . import shutdown_timer, tool_settings  # noqa: PLC0415

        saved = tool_settings.load(self.TASK_SHUTDOWN_KEY) or {}
        minutes = shutdown_timer.clamp_minutes(
            saved.get("auto_shutdown_minutes") or 0)
        return {
            "enabled": bool(saved.get("auto_shutdown_enabled")) and minutes > 0,
            "minutes": minutes,
        }

    def _on_run_finished(self, ok: bool, kind: str, run_name: str) -> None:
        """一次运行结束：按设置决定要不要安排关机。

        ## 只有「跑成功了」才关

        失败 / 被停止 / 前置检查没过就关机，用户第二天回来会一脸问号 ——
        他睡前点的是一条**能跑完**的任务，跑挂了应该留着窗口让人看日志。

        ## 只在跑「流程」时关，跑单个工具不关

        任务页「运行」是 ``runFlow(flowId)``（``kind == "flow"``）；
        ``runTask(toolKey)``（``kind == "tool"``）是工具面板里的单跑，
        不属于「任务完成后」。两者混着触发会让用户在工具页点一下也关机。
        """
        try:
            if str(kind or "") != "flow":
                return
            settings = self._task_shutdown_settings()
            if not settings["enabled"]:
                return
            if not ok:
                self.pushLog("（这条流程没有成功结束，按设置不安排关机）", "warn")
                return
            self._arm_task_shutdown(settings["minutes"], run_name)
        except Exception:  # noqa: BLE001
            logger.warning("安排任务完成后关机失败", exc_info=True)

    def _arm_task_shutdown(self, minutes: int, flow_name: str) -> None:
        """起一个 ShutdownTimer + 1 秒轮询。"""
        from . import shutdown_timer  # noqa: PLC0415

        self._cancel_task_shutdown(quiet=True)
        timer = shutdown_timer.ShutdownTimer(minutes,
                                             warn_seconds=self.TASK_SHUTDOWN_WARN)
        if not timer.start():
            return
        self._shutdown = timer
        self._shutdown_flow = str(flow_name or "")

        from PySide6.QtCore import QTimer  # noqa: PLC0415
        poll = QTimer(self)
        poll.setInterval(1000)
        #: ★★★ 必须用 lambda 包一层，**不能**直接
        #: ``poll.timeout.connect(self._tick_task_shutdown)``。
        #:
        #: ## 为什么（实测踩到的坑，2026-11-04）
        #:
        #: 把信号接到 ``self``（就是 ``Bridge`` 本身，QWebChannel 发布出去的
        #: 那个对象）的一个**没加 ``@Slot`` 的绑定方法**上，会**悄悄废掉
        #: QWebChannel 往 JS 转发 ``event`` 信号的链路**：
        #:
        #: * Python 侧再发 ``emitEvent`` —— 本进程内的 ``bridge.event``
        #:   监听器**照样收到**；
        #: * 但 JS 侧 ``Bridge.subscribe`` 的回调**一次都收不到**；
        #: * 且**不可恢复** —— JS 重新 ``subscribe`` 也没用，
        #:   只有重开窗口才活过来。
        #:
        #: 交叉验证过的对照（每个变体单独起进程跑）：
        #:
        #: ================================  ==========
        #: connect 目标                        结果
        #: ================================  ==========
        #: ``bridge._tick_task_shutdown``       ★ 通道死
        #: ``bridge._stop_task_shutdown_poll``  ★ 通道死
        #: ``bridge.pushLog``                    ★ 通道死
        #: ``bridge.getTaskShutdown``（@Slot）   正常
        #: ``lambda: bridge._tick_task_shutdown()``  正常
        #: ``shell.close``（别的 QObject）        正常
        #: 普通 Python 对象的方法                  正常
        #: ================================  ==========
        #:
        #: 症状很隐蔽：日志不增、进度不动、页面看着「卡住」，
        #: 而 Python 侧一切正常 —— 所以这里留长注释防止有人「顺手简化掉」。
        poll.timeout.connect(lambda: self._tick_task_shutdown())
        poll.start()
        self._shutdown_poll = poll

        text = timer.remaining_text()
        self.pushLog(f"⏻ 「{self._shutdown_flow}」跑完了 —— {text}后自动关机"
                     f"（关机前 {self.TASK_SHUTDOWN_WARN} 秒会提醒，"
                     f"想反悔可以点「取消关机」）", "warn")
        self.emitEvent("shutdownArmed", {
            "flowName": self._shutdown_flow,
            "minutes": timer.minutes,
            "remaining": timer.remaining(),
            "remainingText": text,
            "warnSeconds": timer.warn_seconds,
        })

    def _tick_task_shutdown(self) -> None:
        """每秒跑一次：该提醒就提醒，该关就关。"""
        from . import shutdown_timer  # noqa: PLC0415

        timer = self._shutdown
        if timer is None or not timer.active:
            self._stop_task_shutdown_poll()
            return
        if timer.should_warn():
            left = int(timer.remaining() or 0)
            self.pushLog(f"⚠ {left} 秒后自动关机！要取消就点任务页的"
                         f"「取消关机」。", "warn")
            self.emitEvent("shutdownWarning", {
                "seconds": left,
                "flowName": self._shutdown_flow,
            })
        if timer.should_fire():
            ok, message = shutdown_timer.shutdown()
            self._stop_task_shutdown_poll()
            if ok:
                self.pushLog("⏻ 已安排关机（系统会在几秒内关闭）", "warn")
            else:
                self.pushLog(f"✗ 关机失败：{message}", "error")
            self.emitEvent("shutdownFired", {"ok": bool(ok),
                                             "message": str(message or "")})
            self._shutdown = None
            self._shutdown_flow = ""

    def _stop_task_shutdown_poll(self) -> None:
        poll = self._shutdown_poll
        self._shutdown_poll = None
        if poll is not None:
            try:
                poll.stop()
                poll.deleteLater()
            except RuntimeError:
                #: C++ 侧已销毁（关窗时）—— 忽略即可
                pass

    def _cancel_task_shutdown(self, quiet: bool = False) -> bool:
        """取消还没到点的关机。返回「本来是否在倒计时」。"""
        timer = self._shutdown
        was_active = bool(timer is not None and timer.active)
        if timer is not None:
            timer.cancel()
        self._stop_task_shutdown_poll()
        self._shutdown = None
        flow = self._shutdown_flow
        self._shutdown_flow = ""
        if was_active and not quiet:
            self.pushLog(f"⏻ 已取消「{flow}」跑完后的自动关机", "ok")
            self.emitEvent("shutdownCancelled", {"flowName": flow})
        return was_active

    @Slot(result=str)
    def getTaskShutdown(self) -> str:
        """读任务页「完成后自动关机」设置 + 当前倒计时。

        :return: ``{ok, enabled, minutes, minMinutes, maxMinutes,
                  defaultMinutes, active, remaining, remainingText, flowName}``
        """
        try:
            from . import shutdown_timer  # noqa: PLC0415

            settings = self._task_shutdown_settings()
            timer = self._shutdown
            active = bool(timer is not None and timer.active)
            return _json({
                "ok": True,
                "enabled": settings["enabled"],
                "minutes": settings["minutes"] or 30,
                "minMinutes": shutdown_timer.MIN_MINUTES,
                "maxMinutes": shutdown_timer.MAX_MINUTES,
                "defaultMinutes": 30,
                "warnSeconds": self.TASK_SHUTDOWN_WARN,
                "active": active,
                "remaining": timer.remaining() if active else 0,
                "remainingText": timer.remaining_text() if active else "",
                "flowName": self._shutdown_flow if active else "",
            })
        except Exception:  # noqa: BLE001
            logger.warning("getTaskShutdown 失败", exc_info=True)
            return _json({"ok": False, "reason": "error",
                          "message": "读自动关机设置失败，详见日志"})

    @Slot(str, result=str)
    def setTaskShutdown(self, payload: str) -> str:
        """存任务页「完成后自动关机」设置。

        ``payload`` = ``{"enabled": bool, "minutes": int}``

        ⚠ **合并写**：``tasks`` 这个 key 以后可能还有别的字段，
        覆盖式写会把它们抹掉（Qt 版 ``_save_shutdown`` 也是合并写）。
        """
        try:
            data = json.loads(payload or "{}")
        except (TypeError, ValueError):
            return _json({"ok": False, "reason": "bad_json",
                          "message": "payload 不是合法 JSON"})
        if not isinstance(data, dict):
            return _json({"ok": False, "reason": "bad_data",
                          "message": "payload 必须是对象"})

        try:
            from . import shutdown_timer, tool_settings  # noqa: PLC0415

            enabled = bool(data.get("enabled"))
            minutes = shutdown_timer.clamp_minutes(data.get("minutes") or 0)
            if enabled and not minutes:
                return _json({"ok": False, "reason": "bad_minutes",
                              "message": "分钟数必须在 1 ~ 1440 之间"})

            saved = dict(tool_settings.load(self.TASK_SHUTDOWN_KEY) or {})
            saved["auto_shutdown_enabled"] = enabled
            if minutes:
                saved["auto_shutdown_minutes"] = minutes
            tool_settings.save(self.TASK_SHUTDOWN_KEY, saved)

            #: 关掉开关时，正在倒计时的那次也要停 —— 否则用户以为关掉了，
            #: 电脑还是会在他不在的时候关。
            if not enabled:
                self._cancel_task_shutdown(quiet=True)

            return _json({"ok": True, "enabled": enabled,
                          "minutes": minutes or int(saved.get(
                              "auto_shutdown_minutes") or 0)})
        except Exception:  # noqa: BLE001
            logger.warning("setTaskShutdown 失败", exc_info=True)
            return _json({"ok": False, "reason": "error",
                          "message": "保存自动关机设置失败，详见日志"})

    @Slot(result=str)
    def cancelTaskShutdown(self) -> str:
        """取消正在倒计时的关机（页面上的「取消关机」按钮）。"""
        try:
            cancelled = self._cancel_task_shutdown()
            return _json({"ok": True, "cancelled": cancelled})
        except Exception:  # noqa: BLE001
            logger.warning("cancelTaskShutdown 失败", exc_info=True)
            return _json({"ok": False, "reason": "error",
                          "message": "取消失败，详见日志"})

    # ================================================================ 运行
    @Slot(str, result=str)
    def runTask(self, key: str) -> str:
        """运行**一个工具**（key = ``ToolRegistry`` 里的 ``tool.key``）。

        ## ⚠⚠ key 语义（2026-11-01 和 page-converter 对齐）

        ``runTask`` 只认**工具 key**（``echo_enhance`` /
        ``auto_combat`` …），**不是**任务流程 id（``16a74fd2b097``）。

        流程要跑请用 :meth:`runFlow` —— 两者拆开是因为底层走的路径完全不同：

        ==================  ===============================================
        方法                 做什么
        ==================  ===============================================
        ``runTask(toolKey)``  ``ToolRegistry.make(toolKey)`` → 单个工具的 runner
        ``runFlow(flowId)``   ``TaskStore.get(flowId)`` → 整条流程按步骤跑
        ==================  ===============================================

        如果混用，会踩「拿 flow id 去 ``ToolRegistry.make()`` 查不到工具」
        —— 那是个**静默失败**（返回 None，什么都没发生）。

        ## ★ 真实执行（2026-11-02 接上引擎）

        不再模拟 —— 走和 Qt 版**完全相同**的执行器
        :class:`src.gui.tasks_interface.FlowRunThread`：

        .. code:: text

            runTask(toolKey)  → 合成一条只有 [开始, 工具] 的流程
                              → FlowRunThread.run()
                              → tool.create_task_runner(...).run()
                              → 真的按 ok-ww 引擎动作

        这样「从主页点运行」和「从任务页跑流程」走的是同一套代码，
        行为不会分叉（包括权限闸门、准备动作、报告统计）。

        ⚠ 不支持自动运行的工具（``meta.supports_task_run == False``）会
        明确返回 ``{ok: false, reason: "not_runnable"}`` ——
        以前那种"发几个事件假装跑过了"是最糟的行为（用户以为在跑）。
        """
        key = (key or "").strip()
        if not key:
            return _json({"ok": False, "reason": "empty"})

        _ensure_tools_discovered()
        if self._running:
            return _json({"ok": False, "reason": "busy", "running": self._running})

        #: ★ 先校验 key 是不是真的工具 —— 比"跑起来发现查不到"早一步报错。
        #: 这能立刻抓住「传了 flow id」那种误用。
        from ..core.registry import ToolRegistry  # noqa: PLC0415

        tool_cls = ToolRegistry.get_class(key)
        if tool_cls is None:
            looks_like_flow = len(key) <= 16 and "-" not in key
            return _json({
                "ok": False,
                "reason": "unknown_tool",
                "key": key,
                "hint": ("这是任务流程 id 的话请用 runFlow(flowId)"
                         if looks_like_flow else "没有这个工具"),
            })

        meta = ToolRegistry.get_meta(key)
        if meta is not None and not meta.supports_task_run:
            return _json({
                "ok": False,
                "reason": "not_runnable",
                "key": key,
                "name": meta.name,
                "hint": (f"「{meta.name}」没有实现自动运行"
                         f"（create_task_runner 返回 None），"
                         f"请到工具页手动操作"),
            })

        #: 合成一条最小流程：[开始] → [工具]
        #:
        #: 为什么要加「开始」步：``FlowRunThread._run_start_step`` 会做
        #: **前置检查**（游戏客户端在不在跑）和**准备动作**（把游戏摆到
        #: 正确界面）。少了它，单工具运行就绕过了这些保护 —— 和 Qt 版不一致。
        flow = _single_tool_flow(key)
        #: ★ 先同步过前置检查（游戏没开就立刻返回，不起线程）
        blocked = self._precheck(flow)
        if blocked is not None:
            blocked["key"] = key
            blocked["kind"] = "tool"
            return _json(blocked)
        #: ⚠ 必须传 run_key=key —— 不传的话 _start_thread 会拿 flow.name
        #: （中文显示名「声骸自动强化」）当 key，于是 stopTask 回报的
        #: 和 JS 传进来的对不上。冒烟/集成测试逮到的。
        return self._start_thread(flow, kind="tool",
                                  label=meta.name if meta else key,
                                  run_key=key)

    @Slot(str, result=str)
    def runFlow(self, flow_id: str) -> str:
        """运行**一条任务流程**（flow_id = ``TaskStore`` 里的 ``flow.id``）。

        和 :meth:`runTask` 分开 —— 见那个方法的说明。

        ## ★ 真实执行（2026-11-02 接上引擎）

        走 ``FlowRunThread`` —— 和 Qt 版任务页**完全同一个执行器**。
        流程按 ``flow.steps`` 顺序跑，穿插工具步骤 / 配置步骤，
        「开始」步做前置检查 + 准备动作。
        """
        flow_id = (flow_id or "").strip()
        if not flow_id:
            return _json({"ok": False, "reason": "empty"})
        if self._running:
            return _json({"ok": False, "reason": "busy", "running": self._running})

        flow = None
        try:
            from ..core.tasks import TaskStore  # noqa: PLC0415

            flow = TaskStore().get(flow_id)
        except Exception:  # noqa: BLE001
            logger.warning("runFlow：读流程失败 %s", flow_id, exc_info=True)

        if flow is None:
            return _json({"ok": False, "reason": "not_found", "id": flow_id})

        name = flow.name or flow_id
        errors = _safe(lambda: flow.validate(), [])
        if errors:
            #: 校验不通过的流程**不给跑** —— 和 Qt 版「任务编排」一致，
            #: 不然跑到一半才发现缺配置，用户会以为程序坏了。
            return _json({
                "ok": False, "reason": "invalid", "id": flow_id,
                "name": name, "errors": errors,
            })

        #: ★ 同步前置检查（游戏没开就立刻返回，不起线程）
        blocked = self._precheck(flow)
        if blocked is not None:
            blocked["id"] = flow_id
            blocked["kind"] = "flow"
            return _json(blocked)

        result = self._start_thread(flow, kind="flow", label=name,
                                    run_key=flow_id)
        return result

    @Slot(result=str)
    def stopTask(self) -> str:
        """停止当前正在跑的流程 / 工具。

        ## ★ 真实停止（2026-11-02）

        调 ``FlowRunThread.request_stop()`` —— 它只置一个标志位，
        **当前动作跑完才退出**（和 Qt 版一样）。不做 ``terminate()``：
        强杀线程会把引擎/游戏窗口留在半死状态。

        所以这里**不立刻**清 ``_running``，而是等执行器的 ``failed`` 信号
        走 :meth:`_finish_run` —— 那样状态流转才和执行器一致。
        """
        if not self._running:
            return _json({"ok": False, "reason": "idle"})
        key = self._running
        kind = getattr(self, "_running_kind", "tool")
        name = getattr(self, "_running_name", "") or key

        #: ★ 手动停止 = 用户回来了，正在倒计时的关机也要撤掉
        #: （Qt 版 ``_on_stop`` 里的 ``_cancel_shutdown("已停止任务，定时关机一并取消")``
        #: 是同一个口径）。放在最前面：无论下面走哪条分支都要撤。
        self._cancel_task_shutdown()

        thread = self._thread
        if thread is not None and thread.isRunning():
            try:
                thread.request_stop()
            except Exception:  # noqa: BLE001
                logger.warning("WebBridge：请求停止失败", exc_info=True)
            self.pushLog("⏹ 已请求停止，等当前动作结束…", "warn")
            #: 状态由执行器的 failed 信号收尾 —— 这里只回报"已受理"
            return _json({"ok": True, "key": key, "kind": kind,
                          "pending": True})

        #: 没有活线程（模拟/异常残留）→ 直接收尾
        self._finish_run(False, "已取消")
        logger.info("WebBridge：已停止 %s %s", kind, name)
        return _json({"ok": True, "key": key, "kind": kind})

    @Slot(result=str)
    def getStatus(self) -> str:
        """当前运行状态（页面刷新后恢复用）。"""
        return _json({
            "running": self._running,
            "progress": self._progress,
            "page": self._page,
        })

    # ================================================================ 写接口
    #
    # ★ 2026-11-02 加（task-3）。三个写接口都遵循同一套规矩：
    #
    # 1. **不改业务逻辑** —— 直接调 ``core`` 里现成的 Store；
    # 2. **存盘** —— Store 的 add/update/remove 内部会 save()；
    # 3. **失败要有话说** —— 返回 ``{ok: false, reason, message}``，
    #    页面能直接弹给人看，不是静默失败；
    # 4. ★ **不让数据和运行冲突** —— 有任务在跑时禁止改配置：
    #    ``FlowRunThread`` 手里握着 step 的引用，这时候删掉配置
    #    会让它跑到一半找不到东西。

    #: 配置类型 → (中文名, 存储工厂, 主键字段名)
    #:
    #: ⚠ ``echo_profile`` 的主键是**角色名**（不是 id）——
    #: 见 :class:`~src.core.echo_profile.EchoProfile`。
    #: 配置类型的**用户可见名称**（错误提示里拼进去）
    #:
    #: ★★★ 2026-11-03 改文案：``echo_profile`` 原来叫「战斗配置」——
    #: 那是**旧代码里的历史叫法**，界面上这类配置叫「角色声骸强化」。
    #:
    #: 实测用户被这个文案坑过：删除失败提示写
    #: 「没有 id=「xxx」的**战斗配置**」，而他在界面上操作的是
    #: 「角色声骸强化」那一类 —— 两边对不上，看不懂在说什么。
    #:
    #: 现在和 ``config.js`` 的 ``TYPE_ECHO_PROFILE`` 保持一致。
    _CONFIG_KINDS = {
        "loadout": "角色声骸筛选",
        "echo_profile": "角色声骸强化",
    }

    # ================================================ 声骸套装（P12）
    #
    # ★ 2026-11-02：LoadoutDialog（配置页「角色声骸筛选」弹框）要的
    # 4C/3C/1C 逐档多选。数据在 :mod:`src.core.game_data` 的
    # ``ECHO_SETS`` 里（37 套 / 369 个声骸，全部有明细）。
    #
    # ★★ 为什么拆成**两个**接口（实测数据支撑，不是凭感觉）
    #
    # .. code:: text
    #
    #     轻量清单（只有名字/件数/档位/图标）  5,287 字节
    #     全量明细（含每档声骸 + 技能文本）  153,344 字节  ← 29 倍
    #
    # 一次给 153 KB 在 QWebChannel 上序列化 + JS 反序列化会明显卡
    # （参考 ``getLibraryData`` 的 150 KB —— 那个已经是"一次给完"的上限）。
    #
    # 而打开对话框**只需要 37 个名字**。用户切换套装时才需要明细。

    @Slot(result=str)
    def getEchoSetList(self) -> str:
        """声骸套装**轻量清单**（约 5 KB）。

        打开 LoadoutDialog 时调一次，用来渲染「声骸套装」下拉。

        返回 ``{ok, sets: [...], count}``，每项：

        .. code:: json

            {"name": "茜染怀想之花",
             "isSinglePiece": false,      // 1 件套（3.4 联动套那种）
             "requiredCosts": [4, 3, 1],  // 要摆哪几档
             "availableCosts": [4, 3],    // ★ 实际有货的档（可能少于 required）
             "isConfigurable": false,     // ★ 数据不全 → 前端该提示
             "iconUrl": "http://…/echo_sets/…png",
             "version": "3.7"}

        ⚠ **顺序就是 ``ECHO_SETS`` 的顺序**（按出场版本倒序 ——
        用户 2026-10-24 要求「新套装在前」）。**别自己排。**

        ## ★ ``availableCosts`` / ``isConfigurable`` 为什么单独给

        实测 37 套里有 **2 套数据不全**：

        .. code:: text

            茜染怀想之花   required=[4,3,1]  实际只有 [4,3]（缺 1C）
            镜影流电之瞬   required=[4,3,1]  实际只有 [4,3]（缺 1C）

        ``required_costs`` 说"三档都要"，但那两套的 1C **游戏里没有 / 没收录**。
        页面如果照 ``requiredCosts`` 摆一个空的 1C 框，用户会卡在那里
        （"必须选"但没得选）。

        ``isConfigurable=False`` 时页面应该：**只摆 availableCosts 那几档**，
        或者显示一句"这套的 1C 数据还没收录"。
        """
        try:
            from . import game_data  # noqa: PLC0415

            game_data.ensure_loaded()
            sets = list(getattr(game_data, "ECHO_SETS", []) or [])
        except Exception:  # noqa: BLE001
            logger.warning("getEchoSetList 失败", exc_info=True)
            return _json({"ok": False, "reason": "error",
                          "message": "读声骸套装失败，详见日志"})

        out: list[dict] = []
        for info in sets:
            name = str(getattr(info, "name", "") or "")
            if not name:
                continue
            rel_icon = str(getattr(info, "icon", "") or "")
            required = list(_safe(lambda i=info: i.required_costs, ()) or ())
            available = [
                cost for cost in (4, 3, 1)
                if _safe(lambda i=info, c=cost: bool(i.by_cost(c)), False)
            ]
            out.append({
                "name": name,
                "isSinglePiece": bool(
                    _safe(lambda i=info: i.is_single_piece, False)),
                "requiredCosts": required,
                #: ★ 实际有货的档位（可能少于 requiredCosts）
                "availableCosts": available,
                #: ★ 数据全不全 —— False 时页面别摆空框
                "isConfigurable": bool(
                    _safe(lambda i=info: i.is_configurable, False)),
                "iconUrl": self._safe_icon_url(rel_icon),
                "version": str(getattr(info, "version", "") or ""),
            })

        return _json({"ok": True, "sets": out, "count": len(out)})

    @Slot(str, result=str)
    def getEchoSetDetail(self, set_name: str) -> str:
        """单套声骸的**明细**（每档有哪些声骸 + 可选主属性 + 技能说明）。

        用户**切换套装时**才调（约 1.5 KB/套；全量是 153 KB）。

        :param set_name: 套装名（精确匹配，和 ``getEchoSetList`` 给的 name 一致）

        返回 ``{ok, set: {...}}``：

        .. code:: json

            {"name": "茜染怀想之花",
             "isSinglePiece": false,
             "requiredCosts": [4, 3, 1],
             "availableCosts": [4, 3],
             "isConfigurable": false,
             "iconUrl": "…",
             "version": "3.7",
             "effects": [[2, "两件套效果…"], [5, "五件套效果…"]],
             "byCost": {
               "4": [{"name": "千傀重楼", "cost": 4, "iconUrl": "…",
                      "stats": ["暴击","暴击伤害",…],   // ★ 该声骸的候选主词条
                      "skill": "使用声骸技能…",
                      "cooldown": "20s"}],
               "3": [ … ],
               "1": []                                  // 可能为空（见 isConfigurable）
             }}

        ⚠ **``byCost`` 的 key 是字符串** ``"4"/"3"/"1"`` ——
        JSON 对象的 key 只能是字符串。页面用 ``detail.byCost[c]`` 取，
        ``c`` 传数字时 JS 会自动转字符串，所以两种写法都对。

        ⚠ ``stats`` 是**这个声骸可选的主属性**（界面上从中单选一条），
        不是"全部属性池"。不同声骸的 stats 不一样 —— 别用同一个池子去校验。

        :return: 找不到套装时 ``{ok: false, reason: "not_found", available: [名字…]}``
        """
        name = str(set_name or "").strip()
        if not name:
            return _json({"ok": False, "reason": "empty",
                          "message": "没给套装名"})

        try:
            from . import game_data  # noqa: PLC0415

            game_data.ensure_loaded()
            info = game_data.find_echo_set(name)
        except Exception:  # noqa: BLE001
            logger.warning("getEchoSetDetail 失败", exc_info=True)
            return _json({"ok": False, "reason": "error",
                          "message": "读声骸套装失败，详见日志"})

        if info is None:
            #: ★ 列出可选项，别让页面自己猜
            names = [str(getattr(s, "name", "") or "")
                     for s in (getattr(game_data, "ECHO_SETS", []) or [])]
            return _json({
                "ok": False, "reason": "not_found",
                "message": f"没有叫「{name}」的声骸套装",
                "available": [n for n in names if n][:40],
            })

        by_cost: dict[str, list[dict]] = {}
        for cost in (4, 3, 1):
            echoes = _safe(lambda i=info, c=cost: i.by_cost(c), ()) or ()
            items: list[dict] = []
            for echo in echoes:
                items.append({
                    "name": str(getattr(echo, "name", "") or ""),
                    "cost": int(getattr(echo, "cost", cost) or cost),
                    "iconUrl": self._safe_icon_url(
                        str(getattr(echo, "icon", "") or "")),
                    #: ★ 这个声骸的可选主属性（不是全部属性池）
                    "stats": [str(x) for x in
                              (getattr(echo, "stats", ()) or ())],
                    "skill": str(getattr(echo, "skill", "") or ""),
                    "cooldown": str(getattr(echo, "cooldown", "") or ""),
                })
            #: ★ JSON key 必须是字符串
            by_cost[str(cost)] = items

        required = list(_safe(lambda: info.required_costs, ()) or ())
        available = [c for c in (4, 3, 1) if by_cost.get(str(c))]
        effects = [
            [int(pieces), str(text)]
            for pieces, text in (_safe(lambda: info.effects, ()) or ())
        ]

        return _json({
            "ok": True,
            "set": {
                "name": str(getattr(info, "name", "") or name),
                "isSinglePiece": bool(
                    _safe(lambda: info.is_single_piece, False)),
                "requiredCosts": required,
                "availableCosts": available,
                "isConfigurable": bool(
                    _safe(lambda: info.is_configurable, False)),
                "iconUrl": self._safe_icon_url(
                    str(getattr(info, "icon", "") or "")),
                "version": str(getattr(info, "version", "") or ""),
                #: 套装效果 [[件数, 文字], ...]
                "effects": effects,
                "byCost": by_cost,
            },
        })

    @Slot(str, result=str)
    def getCharacterOptions(self, kind: str = "") -> str:
        """角色下拉候选（配置页「新增/编辑」弹框用）。

        ## 数据源（**照抄旧界面 ``loadout_dialog.py`` L205-206**）

        .. code:: python

            self.character_combo.set_choices(
                [(c.name, avatar_icon(c.avatar, c.name)) for c in CHARACTERS])

        ``CHARACTERS`` 是 :mod:`src.core.game_data` 的模块级清单 ——
        **全部角色**（本机 61 个），已经按「实装版本倒序」排好
        （用户 2026-10-24 要求「新角色降序，不算复刻的」）。

        ⚠ **不要自己排、不要自己筛** —— 顺序是用户提过的需求。

        ## 「一个角色只能有一条配置」（用户 2026-09-26）

        旧界面 :func:`game_data.character_choice_error` 的两条规则：

        1. 名字必须**精确命中** ``CHARACTERS`` 里的一个（不能自由输入）
        2. **一个角色只能有一条**配置

        ``taken`` 就是「已被别的配置占用的角色名」。

        ## ⚠⚠ ``kind`` 决定 taken 从哪儿算

        ==================  =============================================
        ``kind``             taken 来源
        ==================  =============================================
        ``"loadout"``        ``LoadoutStore`` 里已有的 ``character``
        ``"echo_profile"``   ``EchoProfileStore`` 里已有的 ``name``
        ``""``（不给）        两个都算（保守：任何一类占了就算占）
        ==================  =============================================

        ⚠ 两类配置**各自独立**：一个角色可以同时有「声骸筛选」和
        「强化配置」各一条 —— 那是两回事（用户 2026-09-26 明确过）。
        所以 ``kind`` 给具体值时，**只算同类**的占用。

        :param kind: ``"loadout"`` / ``"echo_profile"`` / 空串
        :param excludeId: 修改模式下传自己的 id —— 自己不算占用自己。
                          通过 URL 风格 ``"kind|excludeId"`` 传，见下面的说明。

        :return: ``{ok, items: [{name, avatarUrl, avatarHue, initial,
                  taken, element, weapon, rarity, pinyin}], takenCount, total}``
        """
        #: ``kind`` 支持 ``"loadout|<id>"`` 形式（``Bridge.call`` 只能传一个
        #: 字符串参数，所以把"修改模式要排除的 id"拼在第二段）。
        raw_kind = str(kind or "").strip()
        exclude_id = ""
        if "|" in raw_kind:
            raw_kind, _, exclude_id = raw_kind.partition("|")
            exclude_id = exclude_id.strip()
        kind_key = raw_kind.strip()

        try:
            from . import game_data  # noqa: PLC0415

            game_data.ensure_loaded()
            characters = list(getattr(game_data, "CHARACTERS", []) or [])
        except Exception:  # noqa: BLE001
            logger.warning("getCharacterOptions：读角色清单失败", exc_info=True)
            return _json({"ok": False, "reason": "error",
                          "message": "读角色清单失败，详见日志"})

        taken = self._taken_characters(kind_key, exclude_id)

        items: list[dict] = []
        for info in characters:
            name = str(getattr(info, "name", "") or "")
            if not name:
                continue
            rel_avatar = str(getattr(info, "avatar", "") or "")
            items.append({
                "name": name,
                #: 头像：文件真在才给 URL（否则页面用 initial 画首字圆）
                "avatarUrl": self._safe_icon_url(rel_avatar),
                "avatarHue": _initial_avatar_hue(name),
                "initial": _initial_avatar(name),
                #: ★ 已被别的配置占用
                "taken": name in taken,
                #: 库街区那几个属性（页面要显示筛选/分组时用）
                "element": str(getattr(info, "element", "") or ""),
                "weapon": str(getattr(info, "weapon", "") or ""),
                "rarity": int(getattr(info, "rarity", 0) or 0),
                "releaseVersion": str(
                    getattr(info, "release_version", "") or ""),
                #: ★ 拼音搜索索引（页面下拉可输入过滤，规则和配置页搜索一致）
                "pinyin": list(pinyin_keys(name)),
            })

        #: 可选的（没被占用的）数量 —— 页面可以显示「还剩 N 个可选」
        available = sum(1 for x in items if not x["taken"])
        return _json({
            "ok": True,
            "items": items,
            "total": len(items),
            "takenCount": len(items) - available,
            "availableCount": available,
            "kind": kind_key,
            "excludeId": exclude_id,
        })

    def _taken_characters(self, kind: str, exclude_id: str = "") -> set[str]:
        """已被占用的角色名集合。

        :param kind: ``"loadout"`` / ``"echo_profile"`` / 空串（两个都算）
        :param exclude_id: 修改模式要排除的那条配置 id
        """
        taken: set[str] = set()
        want_loadout = kind in ("", "loadout")
        want_profile = kind in ("", "echo_profile")

        if want_loadout:
            try:
                from .loadout import LoadoutStore  # noqa: PLC0415

                for item in LoadoutStore().all():
                    if exclude_id and str(getattr(item, "id", "")) == exclude_id:
                        continue
                    name = str(getattr(item, "character", "") or "").strip()
                    if name:
                        taken.add(name)
            except Exception:  # noqa: BLE001
                logger.debug("读 loadout 占用失败", exc_info=True)

        if want_profile:
            try:
                from .echo_profile import EchoProfileStore  # noqa: PLC0415

                store = EchoProfileStore()
                store.load()          #: ⚠ 这个 Store 不自动读盘
                for item in store.all():
                    #: EchoProfile 的主键是**角色名**（没有独立的 id 可排除时
                    #: 用名字判断：修改模式下 exclude_id 传的就是角色名）
                    name = str(getattr(item, "name", "") or "").strip()
                    if not name:
                        continue
                    if exclude_id and (
                            str(getattr(item, "id", "")) == exclude_id
                            or name == exclude_id):
                        continue
                    taken.add(name)
            except Exception:  # noqa: BLE001
                logger.debug("读 echo_profile 占用失败", exc_info=True)

        return taken

    @Slot(str, result=str)
    def setConfig(self, payload: str) -> str:
        """新增 / 修改一条配置。

        ``payload`` = JSON ``{"kind": "loadout"|"echo_profile",
        "id"?: "...", "data": {...}}``

        * 有 ``id`` → 修改（找不到就报 ``not_found``，不偷偷新建）
        * 没 ``id`` → 新增

        :return: ``{ok, kind, id, created}`` 或 ``{ok: false, reason, message}``
        """
        if self._running:
            return _json({
                "ok": False, "reason": "busy",
                "message": "有任务在跑，先停止再改配置"
                           "（运行中的流程还握着旧配置）",
                "running": self._running,
            })
        try:
            data = json.loads(payload or "{}")
        except (TypeError, ValueError):
            return _json({"ok": False, "reason": "bad_json",
                          "message": "payload 不是合法 JSON"})
        if not isinstance(data, dict):
            return _json({"ok": False, "reason": "bad_payload",
                          "message": "payload 必须是对象"})

        kind = str(data.get("kind") or "").strip()
        if kind not in self._CONFIG_KINDS:
            return _json({
                "ok": False, "reason": "bad_kind",
                "message": f"kind 只能是 {sorted(self._CONFIG_KINDS)}",
            })
        body = data.get("data")
        if not isinstance(body, dict):
            return _json({"ok": False, "reason": "bad_data",
                          "message": "data 必须是对象"})

        target_id = str(data.get("id") or body.get("id") or "").strip()
        try:
            if kind == "loadout":
                return self._save_loadout(target_id, body)
            return self._save_echo_profile(target_id, body)
        except Exception:  # noqa: BLE001
            logger.warning("setConfig 失败 kind=%s id=%s", kind, target_id,
                           exc_info=True)
            return _json({"ok": False, "reason": "error",
                          "message": "保存失败，详见日志"})

    def _save_loadout(self, target_id: str, body: dict) -> str:
        """保存声骸配置（``Loadout``）。

        ## ★★ 「一个角色只能一条」（用户 2026-09-26）

        旧界面是**两层**校验：

        1. **UI 层** —— 从下拉里剔掉已占用的（前端做）
        2. **校验层** —— ``validate()`` 再校一次

        为什么两层：下拉是 ``FilterComboBox``（**可输入**的），
        用户能直接打字输入不在候选里的名字。

        ⚠ **Web 版必须自己再校一次** —— 前端可以被绕过（控制台直接调
        ``Bridge.call`` / 页面脚本出错）。这一层是后端的责任。

        校验用 :func:`src.core.game_data.character_choice_error` ——
        **和旧界面同一份逻辑**（那条规则本来就放在 core 就是为了共用）。
        """
        from ..core.loadout import Loadout, LoadoutStore  # noqa: PLC0415

        store = LoadoutStore()
        #: ★★★ 归一化字段名（2026-11-02 查出**真 bug**）
        #:
        #: ``getConfigList()`` 输出的是 **camelCase**（``echoSet`` /
        #: ``updatedAt``），而 ``Loadout.from_dict`` 只认 **snake_case**
        #: （``echo_set`` / ``updated_at``）。
        #:
        #: 后果：页面「读出对象 → 编辑 → 原样提交」这条最正常的路径
        #: **会静默丢掉声骸套装和修改时间**：
        #:
        #: .. code:: text
        #:
        #:     before: {echoSet: "羽落空尘之歌", updatedAt: "2026-11-02 …"}
        #:     提交后: {echoSet: "",            updatedAt: "…（新时间）"}
        #:
        #: 实测 8 条配置**全部**有这个差异（``roundtrip_identical_*`` 断言
        #: 抓到的）。不报错，用户只会发现"套装怎么没了"。
        #:
        #: → 两个方向都接受：snake_case 原样传，camelCase 映射回来。
        body = _normalize_loadout_payload(dict(body))
        item = Loadout.from_dict(body)

        #: ★ 先校验角色名（新建和修改都要 —— 修改也可能改名）
        problem = self._character_choice_problem(
            str(getattr(item, "character", "") or ""),
            kind="loadout", exclude_id=target_id)
        if problem:
            return _json({
                "ok": False, "reason": "bad_character",
                "kind": "loadout", "character": item.character,
                "message": problem,
            })

        if target_id:
            item.id = target_id
            if not store.update(item):
                return _json({
                    "ok": False, "reason": "not_found", "kind": "loadout",
                    "id": target_id,
                    "message": f"没有 id={target_id} 的声骸配置",
                })
            created = False
        else:
            item.id = ""          #: 让 Store 生成
            item = store.add(item)
            created = True

        #: 校验只**提示**不拦截 —— 用户可能就想先存一版半成品
        problems = _safe(lambda: item.validate(), [])

        #: ★★ 但「半截数据」要**拦下来**（2026-11-02，lead 要求）
        #:
        #: 判定条件是 **``echo_set`` 空 AND ``picks`` 非空** ——
        #: 不能是「``echo_set`` 空就报错」，因为 ``validate()`` 说
        #: 「各档一个都不选也合法」（用户 2026-09-28 明确），
        #: 用户可能就想建一条**完全空的**配置以后再填。
        #:
        #: 真正矛盾的是**选了声骸却没指定套装**：声骸是挂在套装下的，
        #: 没套装的话筛选步骤生成不出来 —— 那时光返回 ``ok: true``
        #: 会让前端以为存好了，下次跑任务才发现配置是废的。
        echo_set = str(getattr(item, "echo_set", "") or "").strip()
        has_picks = any(
            bool(v) for v in (getattr(item, "picks", None) or {}).values())
        if not echo_set and has_picks:
            #: ⚠ 已经写进 Store 了 —— 撤回，别留一条废数据
            try:
                if created:
                    store.remove(item.id)
                elif target_id:
                    #: 修改模式下：这次改动先不管，让用户补套装再来。
                    #: （不回滚 —— 调用方手里有 before 快照，页面会重新拉）
                    logger.warning(
                        "WebBridge：声骸配置 %s 选了声骸但没套装（未保存 picks）",
                        target_id)
            except Exception:  # noqa: BLE001
                logger.warning("回滚新建的废配置失败", exc_info=True)
            return _json({
                "ok": False, "reason": "bad_echo_set", "kind": "loadout",
                "message": "选了声骸却没指定「声骸套装」——"
                           "声骸要挂在套装下，请先选套装",
            })

        logger.info("WebBridge：保存声骸配置 %s（%s）",
                    item.id, "新建" if created else "修改")
        return _json({
            "ok": True, "kind": "loadout", "id": item.id,
            "created": created, "warnings": problems,
        })

    def _character_choice_problem(self, name: str, *, kind: str,
                                  exclude_id: str = "") -> str:
        """校验角色名 —— 返回给用户看的错误说明，空串 = 通过。

        直接调 :func:`src.core.game_data.character_choice_error`
        （**旧界面用的同一个函数**，两条规则都在里面）：
        精确命中 ``CHARACTERS`` + 一个角色只能一条配置。
        """
        try:
            from . import game_data  # noqa: PLC0415

            game_data.ensure_loaded()
            taken = self._taken_characters(kind, exclude_id)
            return game_data.character_choice_error(name, taken)
        except Exception:  # noqa: BLE001 - 校验器崩了不该挡住保存
            logger.warning("角色校验失败（放行）", exc_info=True)
            return ""


    def _save_echo_profile(self, target_id: str, body: dict) -> str:
        """保存战斗配置（``EchoProfile``，主键是角色名）。

        ## ⚠⚠ 必须显式 ``store.load()``（2026-11-02 踩到）

        ``EchoProfileStore.__init__`` **不会**自动读盘 —— 它只把
        ``self._items`` 初始化成空列表（对比 ``LoadoutStore.__init__``
        结尾有 ``self.load()``，两个 Store 行为不一致）。

        不调 ``load()`` 的后果：``add()`` 往一个**空**的 ``_items`` 里加，
        然后 ``save()`` **整个覆盖**文件 ——

        * 用户原来 8 条声骸配置 → 全被抹掉，只剩新加那 1 条
        * 而且 ``add()`` 还返回 True，看起来"成功"

        这是**数据丢失级**的坑，静默、不可逆。所以这里先 ``load()``。

        ⚠ ``getConfigList()`` 里读的时候也必须 ``load()``，
        否则永远返回空（"保存了但列表里没有"）。
        """
        from ..core.echo_profile import EchoProfile, EchoProfileStore  # noqa: PLC0415

        store = EchoProfileStore()
        #: ★ 先读盘，否则下一步 save() 会覆盖掉用户所有已有配置
        store.load()

        item = EchoProfile.from_dict(dict(body))
        key = target_id or getattr(item, "name", "")
        if not key:
            return _json({"ok": False, "reason": "bad_data",
                          "message": "战斗配置必须有 name"})

        #: ★ 「一个角色只能一条」（用户 2026-09-26）—— 和 loadout 同一条规则。
        #:
        #: ⚠ 但这里**同名是允许的**（``echo_profile`` 的主键就是角色名，
        #: 同名 = 修改那一条）。所以 ``exclude_id`` 要传**当前这条的名字**，
        #: 否则"编辑自己"会被判成"已占用"。
        problem = self._character_choice_problem(
            str(getattr(item, "name", "") or ""),
            kind="echo_profile",
            exclude_id=(target_id or getattr(item, "name", "")))
        if problem:
            return _json({
                "ok": False, "reason": "bad_character",
                "kind": "echo_profile", "character": item.name,
                "message": problem,
            })

        exists = store.get(key) is not None
        if target_id:
            if not exists:
                return _json({"ok": False, "reason": "not_found",
                              "kind": "echo_profile", "id": target_id,
                              "message": f"没有「{target_id}」这条战斗配置"})
            ok = store.update(item)
            created = False
            if not ok:
                return _json({"ok": False, "reason": "update_failed",
                              "kind": "echo_profile", "id": key})
        else:
            if exists:
                #: 同名已存在 → 当成修改（页面「保存」按钮不用先查存在性）
                store.update(item)
                created = False
            else:
                store.add(item)
                created = True

        problems = _safe(lambda: item.validate(), [])
        logger.info("WebBridge：保存战斗配置 %s（%s）",
                    key, "新建" if created else "修改")
        return _json({
            "ok": True, "kind": "echo_profile", "id": key,
            "created": created, "warnings": problems,
        })

    @Slot(str, str, result=str)
    def deleteConfig(self, kind: str, cfg_id: str) -> str:
        """删除一条配置。

        ⚠ 有任务在跑时禁止 —— 和 :meth:`setConfig` 同理。
        """
        if self._running:
            return _json({
                "ok": False, "reason": "busy",
                "message": "有任务在跑，先停止再删除配置",
                "running": self._running,
            })
        kind = (kind or "").strip()
        cfg_id = (cfg_id or "").strip()
        if kind not in self._CONFIG_KINDS:
            return _json({"ok": False, "reason": "bad_kind",
                          "message": f"kind 只能是 {sorted(self._CONFIG_KINDS)}"})
        if not cfg_id:
            return _json({"ok": False, "reason": "empty_id",
                          "message": "要删哪个？没给 id"})
        try:
            if kind == "loadout":
                from ..core.loadout import LoadoutStore  # noqa: PLC0415

                removed = LoadoutStore().remove(cfg_id)
            else:
                from ..core.echo_profile import EchoProfileStore  # noqa: PLC0415

                store = EchoProfileStore()
                #: ★ 必须 load() —— 否则 remove 时 _items 是空的，
                #: 找不到目标，而且 save() 会拿空列表覆盖整个文件。
                store.load()
                # ══════════════════════════════════════════════════════
                # ★★★ 2026-11-03 **修「删除失败：没有 id=「xxx」的战斗配置」**
                #
                # ## 症状（用户圈图）
                #
                # 点「删除」→ 红字：``删除失败：没有 id=「dca7ab2d3b0e」的
                # 战斗配置``，但这条配置**明明就在列表里**、
                # ``echo_profiles.json`` 里也确实有这个 id。
                #
                # ## 根因：查错了键
                #
                # ``EchoProfileStore`` 有两套查法：
                #
                # .. code:: python
                #
                #     get(name)      # 按**角色名**查（主键是 name）
                #     by_id(item_id) # 按 **id** 查
                #
                #     remove(name)   # ← 内部调 get()，所以只认**名字**
                #
                # 而这里把 **id** 传给了 ``remove()`` →
                # ``get('dca7ab2d3b0e')`` 去找名字叫「dca7ab2d3b0e」的配置
                # → 当然找不到 → 返回 False → 报「没有这个 id」。
                #
                # 顺带解释了错误文案为什么带 id：那是 ``cfg_id`` 原样拼的。
                #
                # ## 修法
                #
                # 先用 ``by_id()`` 找到那条，拿它的 **name** 再 ``remove()``。
                # 这样两套键都能用（前端传 id，store 内部按 name 删）。
                # ══════════════════════════════════════════════════════
                target = store.by_id(cfg_id)
                if target is None:
                    #: 兼容"前端传的其实是名字"的情况（老版本 / 手工调用）
                    target = store.get(cfg_id)
                if target is None:
                    removed = False
                else:
                    removed = store.remove(target.name)
            if not removed:
                return _json({
                    "ok": False, "reason": "not_found", "kind": kind,
                    "id": cfg_id,
                    "message": f"没有 id=「{cfg_id}」的"
                               f"{self._CONFIG_KINDS[kind]}",
                })
            logger.info("WebBridge：删除%s %s", self._CONFIG_KINDS[kind], cfg_id)
            return _json({"ok": True, "kind": kind, "id": cfg_id})
        except Exception:  # noqa: BLE001
            logger.warning("deleteConfig 失败 kind=%s id=%s", kind, cfg_id,
                           exc_info=True)
            return _json({"ok": False, "reason": "error",
                          "message": "删除失败，详见日志"})

    @Slot(str, result=str)
    def saveFlow(self, payload: str) -> str:
        """新增 / 修改一条任务流程。

        ``payload`` = JSON ``{"id"?: "...", "name": "...", "steps": [...]}``

        * 有 ``id`` → 修改；没 ``id`` → 新增
        * ``steps`` 每项是 ``{"type": "tool"|"config"|"start"|"end",
          "key": ..., "name": ..., "config_kind": ...}``

        ⚠ **不让存**校验不过的流程（和 Qt 版编排一致）——
        存进去也跑不了，不如当场告诉用户缺什么。
        """
        if self._running:
            return _json({
                "ok": False, "reason": "busy",
                "message": "有任务在跑，先停止再改流程",
                "running": self._running,
            })
        try:
            data = json.loads(payload or "{}")
        except (TypeError, ValueError):
            return _json({"ok": False, "reason": "bad_json",
                          "message": "payload 不是合法 JSON"})
        if not isinstance(data, dict):
            return _json({"ok": False, "reason": "bad_payload",
                          "message": "payload 必须是对象"})

        try:
            from ..core.tasks import TaskFlow, TaskStore  # noqa: PLC0415

            store = TaskStore()
            target_id = str(data.get("id") or "").strip()
            flow = TaskFlow.from_dict(dict(data))

            #: ★ 校验不过就不存（存了也跑不了）
            problems = flow.validate()
            if problems:
                return _json({
                    "ok": False, "reason": "invalid",
                    "errors": problems,
                    "message": "；".join(problems),
                })

            if target_id:
                flow.id = target_id
                if not store.update(flow):
                    return _json({
                        "ok": False, "reason": "not_found", "id": target_id,
                        "message": f"没有 id={target_id} 的流程",
                    })
                created = False
            else:
                flow.id = ""
                flow = store.add(flow)
                created = True

            logger.info("WebBridge：保存流程 %s「%s」（%s）",
                        flow.id, flow.name, "新建" if created else "修改")
            return _json({
                "ok": True, "id": flow.id, "name": flow.name,
                "created": created, "stepCount": len(flow.steps),
            })
        except Exception:  # noqa: BLE001
            logger.warning("saveFlow 失败", exc_info=True)
            return _json({"ok": False, "reason": "error",
                          "message": "保存流程失败，详见日志"})

    @Slot(str, result=str)
    def deleteFlow(self, flow_id: str) -> str:
        """删除一条任务流程。

        ★ 2026-11-03 新增 —— main 分支任务页每行都有「删除」按钮
        （``TaskRowCard._delete`` → ``TasksInterface.delete_flow``），
        web 版之前只能新增/修改，删不掉。

        ## 和 Qt 版同样的两条限制

        1. **有任务在跑就不让删** —— Qt 版是
           ``InfoBar.warning("正在运行", "先停止再删除这条流程。")``。
           这里用 ``reason:"busy"`` 让页面显示同一句话。
        2. **删不存在的不报错、返回 not_found** —— 页面提示一句即可，
           不弹红字（可能只是另一处已经删了）。

        :param flow_id: 流程 id（``TaskFlow.id``，不是名字）
        :returns: ``{"ok": true, "id": ...}`` /
                  ``{"ok": false, "reason": "busy"|"not_found"|"error", "message": ...}``
        """
        target = str(flow_id or "").strip()
        if not target:
            return _json({"ok": False, "reason": "bad_payload",
                          "message": "没给流程 id"})
        if self._running:
            return _json({
                "ok": False, "reason": "busy",
                "message": "先停止再删除这条流程。",
                "running": self._running,
            })
        try:
            from ..core.tasks import TaskStore  # noqa: PLC0415

            store = TaskStore()
            flow = store.get(target)
            if flow is None:
                return _json({
                    "ok": False, "reason": "not_found", "id": target,
                    "message": "这条流程已经不在了（可能别处删过）",
                })
            if not store.remove(target):
                return _json({
                    "ok": False, "reason": "not_found", "id": target,
                    "message": "删除失败：流程没找到",
                })
            logger.info("WebBridge：删除流程 %s「%s」", target, flow.name)
            return _json({"ok": True, "id": target, "name": flow.name})
        except Exception:  # noqa: BLE001
            logger.warning("deleteFlow 失败", exc_info=True)
            return _json({"ok": False, "reason": "error",
                          "message": "删除流程失败，详见日志"})

    @Slot(result=str)
    def getNewFlowOptions(self) -> str:
        """「新增任务」弹框需要的全部候选数据（★ 2026-11-03 新增）。

        ## 用户圈图

        任务页「＋ 新增任务流程」弹框原先是**完整编排编辑器**（左边
        组件调色板、右边手动排步骤），用户圈住调色板标题批注：

        > 增加任务类型，任务类型，目前有，声骸自动强化，
        > 而且还有选择是否成套，44111、43311 这些都东西呢？

        也就是要 main 分支 ``src/gui/new_flow_dialog.py`` 的
        ``NewFlowDialog``：**选任务类型 + 角色 + 属性级别 + 是否成套，
        保存后自动生成整条流程**，不用再手动挑组件。

        ## 为什么不把这套逻辑抄到 JS 里

        ``new_flow_dialog`` 里那几个函数是**纯逻辑**（查配置配对、算有效
        词条上界、查重、写回级别），main 分支和单测都靠它们。抄一份到 JS
        就有两份会漂的规则（比如"完美毕业做不到时不许静默夹成 4"）。

        所以这里只把**选项和判定结果**算好交给页面，页面负责画。

        :returns: ``{"ok": true, "taskTypes": [{"name","key"}],
                   "attrLevels": [{"name","count"}], "defaultLevel": "大毕业",
                   "setChoices": ["不成套","成套"], "setPlans": ["43311","44111"],
                   "defaultSetBonus": "不成套",
                   "characters": [{"name","avatarUrl","pinyin",
                                   "loadoutId","profileId","levelCap",
                                   "ready": bool, "missing": [..],
                                   "levelOk": {"大毕业": true, ...}}]}``
        """
        try:
            from ..core import game_data  # noqa: PLC0415
            from ..core.echo_profile import EchoProfileStore  # noqa: PLC0415
            from ..core.loadout import LoadoutStore  # noqa: PLC0415
            from ..gui import new_flow_dialog as nf  # noqa: PLC0415
            from ..core.tasks import (  # noqa: PLC0415
                DEFAULT_SET_BONUS, SET_BONUS_CHOICES, SET_BONUS_PLANS,
            )

            #: 两类配置按角色名索引（缺一个就没法自动生成流程）
            by_char_loadout: dict[str, object] = {}
            try:
                store = LoadoutStore()
                store.load()
                for item in store.all():
                    who = str(getattr(item, "character", "") or "").strip()
                    if who:
                        by_char_loadout[who] = item
            except Exception:  # noqa: BLE001 - 读不到就当没有，页面会提示
                logger.warning("getNewFlowOptions：读筛选配置失败", exc_info=True)

            by_char_profile: dict[str, object] = {}
            try:
                pstore = EchoProfileStore()
                pstore.load()
                for item in pstore.all():
                    who = str(getattr(item, "name", "") or "").strip()
                    if who:
                        by_char_profile[who] = item
            except Exception:  # noqa: BLE001
                logger.warning("getNewFlowOptions：读强化配置失败", exc_info=True)

            characters: list[dict] = []
            #: 顺序照 ``game_data.CHARACTERS``（已按实装版本倒序，别重排）
            for info in game_data.CHARACTERS:
                who = str(getattr(info, "name", "") or "").strip()
                if not who:
                    continue
                loadout = by_char_loadout.get(who)
                profile = by_char_profile.get(who)
                missing: list[str] = []
                if loadout is None:
                    missing.append("角色声骸筛选")
                if profile is None:
                    missing.append("角色声骸强化")
                cap = nf.valid_count_cap(profile) if profile is not None else 0
                level_ok: dict[str, bool] = {}
                for level_name, need in nf.ATTR_LEVELS.items():
                    #: 上界 0 = 读不到配置 → 谈不上"做得到"
                    level_ok[level_name] = bool(cap) and need <= cap
                characters.append({
                    "name": who,
                    "avatarUrl": _safe(
                        lambda i=info: self._safe_icon_url(
                            str(getattr(i, "avatar", "") or "")), ""),
                    "pinyin": _safe(
                        lambda n=who: list(pinyin_keys(n)), []),
                    "loadoutId": str(getattr(loadout, "id", "") or "")
                    if loadout is not None else "",
                    "profileId": str(getattr(profile, "id", "") or "")
                    if profile is not None else "",
                    #: 有效词条上界（核心 + 可选条数）—— 页面拿它提示"做不到"
                    "levelCap": cap,
                    "ready": not missing,
                    "missing": missing,
                    "levelOk": level_ok,
                })

            return _json({
                "ok": True,
                "taskTypes": [{"name": k, "key": v}
                              for k, v in nf.TASK_TYPES.items()],
                "attrLevels": [{"name": k, "count": v}
                               for k, v in nf.ATTR_LEVELS.items()],
                "defaultLevel": nf.DEFAULT_ATTR_LEVEL,
                "setChoices": list(SET_BONUS_CHOICES),
                "setPlans": list(SET_BONUS_PLANS),
                "defaultSetBonus": DEFAULT_SET_BONUS,
                "characters": characters,
            })
        except Exception:  # noqa: BLE001
            logger.warning("getNewFlowOptions 失败", exc_info=True)
            return _json({"ok": False, "reason": "error",
                          "message": "读取新增任务选项失败，详见日志"})

    @Slot(str, result=str)
    def createFlowFromOptions(self, payload: str) -> str:
        """按「任务类型 + 角色 + 属性级别 + 是否成套」**自动生成**一条流程。

        对应 main 分支 ``TasksInterface._add_flow`` 里
        ``NewFlowDialog.result_flow()`` 干的活：

        .. code:: text

            开始 → <角色>-声骸筛选 → <角色>-声骸强化 → 声骸自动强化 → 结束

        ``payload`` = JSON::

            {"character": "绯雪", "taskType": "声骸强化",
             "level": "大毕业", "setBonus": "成套", "setPlan": "43311"}

        ## 三条硬规矩（都来自 main，别放宽）

        1. **两个配置必须都已存在** —— 缺一个流程跑不起来，当场说缺什么。
        2. **级别不能超过配置的有效词条上界** —— 上界 = 核心 + 可选条数
           （5 个孔位每种词条只出现一次）。做不到就说做不到，
           **绝不静默夹成上界值**（用户以为选了完美毕业、实际按大毕业跑）。
        3. **同角色 + 同级别只能一条** —— 级别写进流程名，从流程名反推查重。

        :returns: ``{"ok": true, "id", "name", "stepCount"}`` /
                  ``{"ok": false, "reason": "busy"|"bad_payload"|
                  "bad_character"|"missing_config"|"bad_type"|"bad_level"|
                  "level_too_high"|"duplicate"|"error", "message": ...}``
        """
        if self._running:
            return _json({
                "ok": False, "reason": "busy",
                "message": "有任务在跑，先停止再新增流程",
                "running": self._running,
            })
        try:
            data = json.loads(payload or "{}")
        except (TypeError, ValueError):
            return _json({"ok": False, "reason": "bad_json",
                          "message": "payload 不是合法 JSON"})
        if not isinstance(data, dict):
            return _json({"ok": False, "reason": "bad_payload",
                          "message": "payload 必须是对象"})

        try:
            from ..core import game_data  # noqa: PLC0415
            from ..core.echo_profile import EchoProfileStore  # noqa: PLC0415
            from ..core.tasks import TaskStore  # noqa: PLC0415
            from ..gui import new_flow_dialog as nf  # noqa: PLC0415

            who = str(data.get("character") or "").strip()
            task_type = str(data.get("taskType") or "").strip()
            level = str(data.get("level") or "").strip()
            set_bonus = str(data.get("setBonus") or "").strip()
            set_plan = str(data.get("setPlan") or "").strip()

            #: ① 角色必须是数据集里的（不能自由输入 —— 和配置页同一条规则）
            if not who:
                return _json({"ok": False, "reason": "bad_character",
                              "message": "请先选一个角色"})
            if game_data.find_character(who) is None:
                return _json({
                    "ok": False, "reason": "bad_character",
                    "message": f"「{who}」不是一个角色 —— 请从列表里选一个"
                               "（可以打拼音筛）",
                })

            #: ② 任务类型
            if task_type and task_type not in nf.TASK_TYPES:
                return _json({
                    "ok": False, "reason": "bad_type",
                    "message": f"未知的任务类型「{task_type}」",
                })
            if not task_type:
                task_type = next(iter(nf.TASK_TYPES))

            #: ③ 两类配置都得有
            try:
                loadouts = nf.compatible_characters()
            except Exception:  # noqa: BLE001
                loadouts = []
            pair = next((x for x in loadouts if x[0] == who), None)
            if pair is None:
                #: 说清楚缺哪一个（两个都缺就都列出来）
                missing: list[str] = []
                try:
                    from ..core.loadout import LoadoutStore  # noqa: PLC0415

                    lstore = LoadoutStore()
                    lstore.load()
                    if not any(str(getattr(x, "character", "") or "") == who
                               for x in lstore.all()):
                        missing.append("角色声骸筛选")
                except Exception:  # noqa: BLE001
                    missing.append("角色声骸筛选")
                try:
                    pstore = EchoProfileStore()
                    pstore.load()
                    if not any(str(getattr(x, "name", "") or "") == who
                               for x in pstore.all()):
                        missing.append("角色声骸强化")
                except Exception:  # noqa: BLE001
                    missing.append("角色声骸强化")
                return _json({
                    "ok": False, "reason": "missing_config",
                    "missing": missing,
                    "message": f"「{who}」还缺「{'」「'.join(missing)}」配置"
                               " —— 请先到「配置」页建好",
                })
            _char, loadout_id, profile_id = pair

            #: ④ 级别：必须认识，且不能超过这条强化配置的上界
            level_count = nf.ATTR_LEVELS.get(level)
            if level and level_count is None:
                return _json({
                    "ok": False, "reason": "bad_level",
                    "message": f"未知的声骸属性级别「{level}」",
                })
            profile = None
            try:
                pstore = EchoProfileStore()
                pstore.load()
                profile = next(
                    (x for x in pstore.all()
                     if str(getattr(x, "name", "") or "") == who), None)
            except Exception:  # noqa: BLE001
                logger.warning("createFlowFromOptions：读强化配置失败",
                               exc_info=True)
            if level_count is not None and profile is not None:
                cap = nf.valid_count_cap(profile)
                if cap and level_count > cap:
                    return _json({
                        "ok": False, "reason": "level_too_high",
                        "cap": cap,
                        "message": f"「{level}」要求 {level_count} 条有效词条，"
                                   f"但「{who}-声骸强化」只配了 {cap} 条可用属性"
                                   "（核心 + 可选）—— 请先到「配置」页补属性，"
                                   "或换低一级",
                    })

            #: ⑤ 同角色 + 同级别只能一条
            dup = nf.existing_flow_for(who, level)
            if dup is not None:
                return _json({
                    "ok": False, "reason": "duplicate",
                    "existing": getattr(dup, "id", ""),
                    "message": f"「{getattr(dup, 'name', who)}」已经存在了 —— "
                               "同一角色同一级别只能有一条任务",
                })

            #: ⑥ 把级别写回强化配置（任务跑的时候读的是配置里那份）
            if level and profile is not None:
                if not nf.apply_attr_level(profile, level):
                    return _json({
                        "ok": False, "reason": "level_apply_failed",
                        "message": "写回「有效词条」数量失败，详见日志",
                    })

            #: ⑦ 生成并保存
            flow = nf.build_echo_enhance_flow(
                who, loadout_id, profile_id,
                level=level,
                set_plan=set_plan if set_bonus == "成套" else "",
            )
            problems = flow.validate()
            if problems:
                return _json({
                    "ok": False, "reason": "invalid",
                    "errors": problems,
                    "message": "；".join(problems),
                })
            store = TaskStore()
            store.add(flow)
            logger.info("WebBridge：按选项新建流程「%s」（%s）", flow.name, task_type)
            return _json({
                "ok": True,
                "id": flow.id,
                "name": flow.name,
                "stepCount": len(flow.steps),
            })
        except Exception:  # noqa: BLE001
            logger.warning("createFlowFromOptions 失败", exc_info=True)
            return _json({"ok": False, "reason": "error",
                          "message": "新建任务失败，详见日志"})

    @Slot(result=str)
    def getRunReport(self) -> str:
        """任务页底部「运行报告」区的数据（★ 2026-11-03 新增）。

        对应 main 分支 ``TasksInterface._refresh_report()`` 读的两样东西：

        .. code:: text

            {"ok": true,
             "round": {"flowName", "summary", "lines": [...], "ok", "note",
                       "locked", "dropped", "checked", "empty": bool} | null,
             "total": {"locked", "dropped", "checked", "rounds", "updatedAt",
                       "summary", "empty": bool}}

        * ``round`` = **本轮**报告（``self._last_report``，只在内存里，
          进程重启就没了 —— 和 Qt 版一致：那也只在内存）。
        * ``total`` = **所有任务累计**（``core.run_report.RunReportStore``，
          持久化在 ``data/echo_run_stats.json``，每次现读，不缓存 ——
          别的入口也可能改它）。

        页面拿 ``empty`` 决定显示空态文案（「还没有跑过。…」/
        「还没有累计数据。」），不用自己判断。
        """
        try:
            from ..core.run_report import RunReportStore  # noqa: PLC0415

            round_data = None
            report = self._last_report
            if report is not None:
                round_data = {
                    "flowName": str(getattr(report, "flow_name", "") or ""),
                    "summary": _safe(lambda: report.summary(), ""),
                    "lines": _safe(lambda: list(report.lines()), []),
                    "ok": bool(getattr(report, "ok", True)),
                    "note": str(getattr(report, "note", "") or ""),
                    "locked": _safe(lambda: int(report.locked), 0),
                    "dropped": _safe(lambda: int(report.dropped), 0),
                    "checked": _safe(lambda: int(report.checked), 0),
                    "empty": _safe(lambda: bool(report.is_empty()), True),
                }

            stats = RunReportStore().load()
            total_data = {
                "locked": _safe(lambda: int(stats.locked), 0),
                "dropped": _safe(lambda: int(stats.dropped), 0),
                "checked": _safe(lambda: int(stats.checked), 0),
                "rounds": _safe(lambda: int(stats.rounds), 0),
                "updatedAt": str(getattr(stats, "updated_at", "") or ""),
                "summary": _safe(lambda: stats.summary(), ""),
                #: 全是 0 = 还没有任何累计（页面据此显示「还没有累计数据。」）
                "empty": _safe(
                    lambda: stats.rounds <= 0 and stats.locked == 0
                    and stats.dropped == 0, True),
            }
            return _json({"ok": True, "round": round_data, "total": total_data})
        except Exception:  # noqa: BLE001
            logger.warning("getRunReport 失败", exc_info=True)
            return _json({"ok": False, "reason": "error",
                          "message": "读取运行报告失败，详见日志",
                          "round": None, "total": None})

    @Slot(result=str)
    def resetRunReport(self) -> str:
        """把「所有任务累计」清零（★ 2026-11-03 新增）。

        对应 main 分支 ``TasksInterface._reset_total()`` —— 那张卡右上角的
        「清零」按钮，tooltip「把所有任务的累计统计归零（本轮报告不受影响）」。

        ⚠ **本轮报告不动** —— 这是 Qt 版明写的口径：清零只清持久化的累计，
        刚跑完这一轮的明细还留在「本轮报告」卡里。
        """
        try:
            from ..core.run_report import RunReportStore  # noqa: PLC0415

            RunReportStore().reset()
            logger.info("WebBridge：累计统计已清零")
            return _json({"ok": True})
        except Exception:  # noqa: BLE001
            logger.warning("resetRunReport 失败", exc_info=True)
            return _json({"ok": False, "reason": "error",
                          "message": "清零失败，详见日志"})

    # ================================================================ ok-ww 引擎
    #
    # ★★ 2026-11-02 P4：补 5 个接口，因为有 **5/7 个工具不在** ``runTask``
    # 覆盖范围内（它们没覆写 ``create_task_runner``）：
    #
    # ======================  ==========================================
    # 工具                     真实入口
    # ======================  ==========================================
    # echo_enhance            ✅ create_task_runner（runTask 可用）
    # nest_sweep              ✅ create_task_runner（runTask 可用）
    # auto_combat             ❌ okww_boot.get_host().start_task(...)
    # echo_change             ❌ 同上
    # gacha                   ❌ gacha.fetch_raw() + FetchThread
    # character_build         ❌ kuro_account 登录
    # wuwa_library_update     ❌ wuwa_update.fetch_remote()
    # ======================  ==========================================
    #
    # ⚠ ok-ww host 是**全局单例**，一次只能跑一个。所有走 okww 的接口
    # 统一在 busy 时返回 ``{"ok": false, "reason": "busy", "running": ...}``。
    #
    # ⚠ ``start_task()`` 返回 ``None`` = **成功**（反直觉），返回字符串是
    # 错误信息。这里统一转成 ``{ok: true/false}``。

    @Slot(result=str)
    def getOkwwState(self) -> str:
        """ok-ww 宿主状态。

        返回 ``{state, runningTask, pendingStart, bootError, tasks: [...]}``。

        ## ``tasks`` 为什么带三个字段

        ``TASKS`` 的 key **本身就是中文名**（``"声骸批量调频"``），
        但页面按**工具 key**（``echo_change``）组织代码。只给中文名的话
        页面得靠字符串反查 —— 而 ``auto_combat`` 的显示名（"4C 自动战斗"）
        和它的 taskKey（"4C 刷声骸"）**并不一样**，反查会错。

        所以每条给全：

        * ``key``     —— 工具 key（页面用这个）
        * ``name``    —— 工具显示名（**不是** taskKey）
        * ``taskKey`` —— 真正传给 ``runOkwwTask`` 的 TASKS key
        """
        payload: dict = {
            "state": "idle", "runningTask": "", "pendingStart": "",
            "bootError": "", "tasks": [], "available": True,
        }
        try:
            from ..tools.game.auto_combat import okww_boot  # noqa: PLC0415

            host = okww_boot.current_host()
            if host is not None:
                payload["state"] = _safe(lambda: host.state, "idle")
                payload["runningTask"] = _safe(
                    lambda: host.running_task or "", "")
                payload["pendingStart"] = _safe(
                    lambda: host.pending_start or "", "")
                payload["bootError"] = _safe(
                    lambda: host.boot_error or "", "")
            payload["tasks"] = self._okww_task_map()
        except Exception:  # noqa: BLE001
            logger.warning("getOkwwState 失败", exc_info=True)
            payload["available"] = False
            payload["message"] = "ok-ww 引擎模块不可用"
        return _json(payload)

    def _okww_task_map(self) -> list[dict]:
        """工具 key → ok-ww TASKS key 的映射表。

        ⚠ 用 ``getattr`` 兜底读各工具自己的 ``TASK_KEY`` 常量：工具改名
        这张表自动跟上，不用改两处。
        """
        from ..core.registry import ToolRegistry  # noqa: PLC0415
        from ..tools.game.auto_combat import okww_boot  # noqa: PLC0415

        #: 工具 key → (模块路径, 常量名)；None = 用 okww_boot.DEFAULT_TASK_KEY
        sources: dict[str, tuple[str, str] | None] = {
            "auto_combat": None,
            "echo_change": ("src.tools.game.echo_change.tool", "TASK_KEY"),
            "echo_enhance": ("src.tools.game.echo_enhance.okww_task", "TASK_KEY"),
            "nest_sweep": ("src.tools.game.nest_sweep.runner", "TASK_KEY"),
        }
        out: list[dict] = []
        available = set(getattr(okww_boot, "TASKS", {}) or {})
        for tool_key, spec in sources.items():
            meta = ToolRegistry.get_meta(tool_key)
            task_key = ""
            if spec is None:
                task_key = str(getattr(okww_boot, "DEFAULT_TASK_KEY", "") or "")
            else:
                module_path, const = spec
                try:
                    import importlib  # noqa: PLC0415

                    mod = importlib.import_module(module_path)
                    task_key = str(getattr(mod, const, "") or "")
                except Exception:  # noqa: BLE001 - 工具缺失不该炸
                    logger.debug("读 %s 的 TASK_KEY 失败", tool_key,
                                 exc_info=True)
            out.append({
                "key": tool_key,
                "name": meta.name if meta else tool_key,
                "taskKey": task_key,
                "registered": task_key in available,
            })
        return out

    @Slot(str, result=str)
    def runOkwwTask(self, payload: str) -> str:
        """启动 ok-ww 任务（``auto_combat`` / ``echo_change`` /
        ``echo_enhance`` / ``nest_sweep``）。

        ``payload`` = JSON ``{"taskKey": "声骸批量调频", "config": {...}}``

        ``taskKey`` 可以是 ok-ww 的 TASKS key（中文名），也可以是**工具 key**
        （``echo_change``）—— 内部会转。

        ## 返回

        .. code:: json

            {"ok": true, "taskKey": "...", "toolKey": "..."}
            {"ok": false, "reason": "permission", "message": "……"}
            {"ok": false, "reason": "busy", "running": "...", "message": "…"}
            {"ok": false, "reason": "unknown_task", "message": "…", "available": [...]}

        ⚠ ``message`` 一律是**写给用户看的中文**，直接显示。
        """
        try:
            data = json.loads(payload or "{}")
        except (TypeError, ValueError):
            return _json({"ok": False, "reason": "bad_json",
                          "message": "payload 不是合法 JSON"})
        if not isinstance(data, dict):
            return _json({"ok": False, "reason": "bad_payload",
                          "message": "payload 必须是对象"})

        raw_key = str(data.get("taskKey") or data.get("toolKey") or "").strip()
        if not raw_key:
            return _json({"ok": False, "reason": "empty",
                          "message": "没给 taskKey"})

        try:
            from ..tools.game.auto_combat import okww_boot  # noqa: PLC0415
        except Exception:  # noqa: BLE001
            logger.warning("runOkwwTask：okww_boot 不可用", exc_info=True)
            return _json({"ok": False, "reason": "unavailable",
                          "message": "ok-ww 引擎模块不可用（vendor 缺失？）"})

        tasks = getattr(okww_boot, "TASKS", {}) or {}
        task_key = self._resolve_okww_task(raw_key)
        if task_key not in tasks:
            return _json({
                "ok": False, "reason": "unknown_task",
                "message": f"找不到任务「{raw_key}」",
                "available": sorted(tasks.keys()),
            })

        # ── ① 同步前置检查：权限 ──
        #: ``input_permission_error()`` 的文案是写给用户看的（"不是管理员"/
        #: "游戏没开"），**原样透传**，不要自己重写。
        try:
            blocked = okww_boot.input_permission_error()
        except Exception:  # noqa: BLE001
            logger.warning("runOkwwTask：权限检查异常（放行）", exc_info=True)
            blocked = None
        if blocked:
            logger.info("WebBridge：okww 启动被拦 —— %s", blocked)
            return _json({"ok": False, "reason": "permission",
                          "message": blocked, "taskKey": task_key})

        # ── ② 桥接层互斥 ──
        if self._running:
            return _json({
                "ok": False, "reason": "busy", "running": self._running,
                "message": f"已有任务在跑：{self._running_name or self._running}",
            })

        cfg = data.get("config")
        configure = self._make_configure(task_key, cfg) \
            if isinstance(cfg, dict) and cfg else None

        host = okww_boot.get_host()
        try:
            error = host.start_task(task_key, configure=configure)
        except Exception as exc:  # noqa: BLE001
            logger.warning("runOkwwTask：start_task 抛异常", exc_info=True)
            return _json({"ok": False, "reason": "start_failed",
                          "message": f"{type(exc).__name__}: {exc}",
                          "taskKey": task_key})

        if error:
            #: 上游把 busy / 找不到 / 启动失败都塞在返回字符串里
            reason = "busy" if "已有任务在跑" in error else "start_failed"
            out = {"ok": False, "reason": reason,
                   "message": error, "taskKey": task_key}
            if reason == "busy":
                out["running"] = _safe(lambda: host.running_task or "", "")
            return _json(out)

        # ── ③ 受理成功 ──
        self._running = task_key
        self._running_kind = "okww"
        self._running_name = task_key
        out = {"ok": True, "taskKey": task_key,
               "toolKey": self._tool_key_for_task(task_key)}
        evt = {**out, "kind": "okww", "name": task_key}
        self.taskStarted.emit(_json(evt))
        self.emitEvent("taskStarted", evt)
        self.pushLog(f"▶ ok-ww 任务已受理：{task_key}", "ok")
        logger.info("WebBridge：ok-ww 任务已受理 %s", task_key)

        # ★★ 「受理」≠「真的在跑」—— page-converter 和 lead 都踩到过
        #
        # 现象（2026-11-02 双方实测）：
        #
        #     runOkwwTask → {ok: true}
        #     之后 state=ready 且 runningTask 全程为空
        #
        # 这和「任务刚跑完」一模一样，页面判不出来。根因：
        # ``input_permission_error()`` 在**游戏没开时返回 None**
        # （它只在能检测到游戏窗口时才判断权限），于是 start_task 放行、
        # 引擎真的 boot 起来 —— 但 ``do_start`` 找不到游戏窗口就静默失败，
        # ``running_task`` 永远不会被设置。
        #
        # 桥接层能做的最有用的事：**如实回报**，别让页面靠轮询猜 8 秒。
        engine_state, may_not_run, warning = self._probe_engine_after_start(host)
        out["engineStarted"] = engine_state in ("ready", "running")
        out["engineState"] = engine_state
        if may_not_run:
            out["mayNotRun"] = True
            out["warning"] = warning
            self.pushLog(f"⚠ {warning}", "warn")
        return _json(out)

    #: 起任务后最多等多久看引擎状态（毫秒）。别太长 —— 页面在等返回值。
    _ENGINE_PROBE_MS = 1200

    def _probe_engine_after_start(self, host) -> tuple[str, bool, str]:
        """起任务后短暂探测引擎状态，判断"是不是真的能跑"。

        :return: ``(state, mayNotRun, warning)``

        ## 为什么不一直等到 running

        ``do_start`` 要刷新设备、等游戏窗口稳定、入队 —— 可能几十秒。
        阻塞那么久页面一直转圈，比"给个警告"糟。

        所以只等 1.2 秒（够引擎从 ``booting`` 走到 ``ready``），然后如实回报：

        * 引擎 ready 且任务进了 running → 正常
        * 引擎 ready 但 runningTask 仍空 → ``mayNotRun``（游戏没开/界面不对）
        * 引擎还在 booting → **不判死**（首次启动慢是正常的）
        """
        from PySide6.QtCore import QEventLoop, QTimer  # noqa: PLC0415

        loop = QEventLoop()
        QTimer.singleShot(self._ENGINE_PROBE_MS, loop.quit)
        loop.exec()

        state = _safe(lambda: host.state, "idle")
        running = _safe(lambda: host.running_task or "", "")
        boot_err = _safe(lambda: host.boot_error or "", "")

        if running:
            return state, False, ""
        if state == "booting":
            #: 首次启动慢是正常的，别吓唬用户
            return state, False, ""
        if state == "error":
            return state, True, (
                f"引擎启动失败：{boot_err}" if boot_err
                else "引擎启动失败，详情见日志")
        if state == "ready":
            return state, True, (
                "引擎已就绪，但任务没有进入运行状态 —— 多半是游戏没开着 / "
                "界面不在正确位置 / 不是管理员权限。请逐条检查前置条件后重试。")
        return state, True, f"引擎状态异常（{state}），任务可能没有真正启动"

    def _resolve_okww_task(self, raw: str) -> str:
        """把用户传的 key 解析成 ok-ww 的 TASKS key。

        接受：① 已经是 TASKS key（中文名）② 工具 key（``echo_change``）。
        都不是就原样返回，让调用方报 ``unknown_task``。
        """
        from ..tools.game.auto_combat import okww_boot  # noqa: PLC0415

        if raw in (getattr(okww_boot, "TASKS", {}) or {}):
            return raw
        for item in self._okww_task_map():
            if item["key"] == raw and item["taskKey"]:
                return item["taskKey"]
        return raw

    def _tool_key_for_task(self, task_key: str) -> str:
        """反查：TASKS key → 工具 key。"""
        for item in self._okww_task_map():
            if item["taskKey"] == task_key:
                return item["key"]
        return ""

    def _make_configure(self, task_key: str, cfg: dict):
        """生成 ``start_task(configure=...)`` 的回调。

        ## 何时被调

        ``start_task`` 在**任务实例拿到之后、真正开跑之前**调一次，用来
        把宿主这边的运行时配置注入任务（ok-ww 的任务自己不知道用户在
        工具页配了什么）。

        ## 为什么 ``setattr`` 而不是塞配置 dict

        各任务类接受的字段名不一样。这里**只塞用户明确给的键**，且跳过
        私有/非法名 —— 宁可少配一项，也不要把任务对象搞坏。
        """
        safe_cfg = {
            str(k): v for k, v in (cfg or {}).items()
            if not str(k).startswith("_") and str(k).isidentifier()
        }

        def configure(task) -> None:
            for key, value in safe_cfg.items():
                try:
                    setattr(task, key, value)
                except Exception:  # noqa: BLE001 - 单字段失败不中断
                    logger.debug("注入 %s.%s 失败", task_key, key,
                                 exc_info=True)

        return configure

    @Slot(result=str)
    def stopOkwwTask(self) -> str:
        """停 ok-ww 任务。

        ⚠ 和 ``stopTask`` 分工：那个停 ``FlowRunThread``，这个停 ok-ww 宿主
        里的任务。**页面不需要区分** —— 两个都调也行（各自 idle 时返回
        ``reason: "idle"``，无害）。
        """
        try:
            from ..tools.game.auto_combat import okww_boot  # noqa: PLC0415

            host = okww_boot.current_host()
            if host is None:
                self._clear_run_state()
                return _json({"ok": False, "reason": "idle",
                              "message": "引擎还没启动过，没有任务在跑"})

            error = host.stop_task()
            if error:
                return _json({"ok": False, "reason": "stop_failed",
                              "message": error})

            self._clear_run_state()
            payload = {"ok": True, "kind": "okww", "summary": "已停止"}
            self.taskFinished.emit(_json(payload))
            self.emitEvent("taskFinished", payload)
            self.pushLog("⏹ ok-ww 任务已停止", "warn")
            logger.info("WebBridge：ok-ww 任务已停止")
            return _json({"ok": True})
        except Exception as exc:  # noqa: BLE001
            logger.warning("stopOkwwTask 失败", exc_info=True)
            return _json({"ok": False, "reason": "error",
                          "message": f"{type(exc).__name__}: {exc}"})

    def _clear_run_state(self) -> None:
        """清运行标记（okww 路径用；FlowRunThread 走 :meth:`_finish_run`）。"""
        self._running = ""
        self._running_kind = ""
        self._running_name = ""
        self._progress = 0

    # ------------------------------------------------ 继续 / 跳过（P5，旧界面有）
    #
    # ★ 2026-11-02：用户 P5 反馈「声骸强化也有 5 个按钮」，其中
    # 「继续」「跳过」旧界面有、Web 版没有。两条都**不是可有可无的**：
    #
    # * **继续** —— 旧界面注释原话：
    #   "少了它，'可续跑'就只是个说法（只能停止再重跑，前面强化的白费）"
    # * **跳过** —— 用户 2026-10-30：
    #   "跳过相当于他已经强化好了，需要跳过同类型同名声骸"
    #
    # ## 实现原则：**照抄旧界面调用的那两个 API**

    @Slot(result=str)
    def okwwResumeTask(self) -> str:
        """继续 —— 把**自动暂停**的任务放回去接着跑。

        照抄 ``echo_enhance/tool.py`` 的 ``_on_resume``：

        .. code:: python

            task = host.find_task(TASK_KEY)
            task.unpause()      # ← ok-ww 自己的恢复，不自己造逻辑

        ``unpause()`` 会把 ``_paused`` 置假、``executor.start()`` 唤醒
        执行线程 —— 和 ok-ww GUI 里那个「继续」是同一条路。

        :return: ``{ok, message}`` / ``{ok: false, reason, message}``

        ## 什么时候会失败

        * 引擎没起过 → ``reason: "idle"``
        * 没有正在跑的任务 → ``reason: "no_task"``（任务已经结束了）
        * ``unpause()`` 自己抛异常 → ``reason: "resume_failed"``

        ⚠ **不是所有中止都能"继续"** —— 只有 ``autostop`` 的
        ``pause()`` 那种才可以。用户主动点「停止」是 ``stop_task()``，
        那个已经真的结束了，得重跑。
        """
        try:
            from ..tools.game.auto_combat import okww_boot  # noqa: PLC0415

            host = okww_boot.current_host()
            if host is None:
                return _json({"ok": False, "reason": "idle",
                              "message": "引擎还没启动过，没有可继续的任务"})

            #: 找当前在跑的那个任务实例。旧界面是写死 ``find_task(TASK_KEY)``，
            #: 但 Web 端可能跑的是别的工具，所以优先用宿主记录的 running_task。
            task = None
            running = _safe(lambda: host.running_task, None)
            if running:
                task = _safe(lambda: host.find_task(running), None)
            if task is None:
                #: 兜底：扫一遍 TASKS，找第一个存在且 paused 的
                for key in (getattr(okww_boot, "TASKS", {}) or {}):
                    candidate = _safe(lambda k=key: host.find_task(k), None)
                    if candidate is not None and getattr(
                            candidate, "paused", False):
                        task = candidate
                        break
            if task is None:
                return _json({"ok": False, "reason": "no_task",
                              "message": "没有可继续的任务（任务已经结束了，"
                                         "请重新运行）"})

            method = getattr(task, "unpause", None)
            if not callable(method):
                return _json({"ok": False, "reason": "unsupported",
                              "message": "当前任务不支持继续（不是自动暂停状态）"})
            method()
            msg = "已继续（从自动暂停处接着强化）"
            self.pushLog(f"▶ {msg}", "ok")
            logger.info("WebBridge：ok-ww 任务已继续")
            return _json({"ok": True, "message": msg})
        except Exception as exc:  # noqa: BLE001 - 恢复失败要说清楚，别静默
            logger.warning("okwwResumeTask 失败", exc_info=True)
            return _json({"ok": False, "reason": "resume_failed",
                          "message": f"{type(exc).__name__}: {exc}"})

    @Slot(result=str)
    def okwwSkipEcho(self) -> str:
        """跳过当前声骸 —— **当成"已强化好"**，同名同类型的后面也跳过。

        照抄 ``OkwwHost.request_skip_current()``（工具页那个按钮用的同一个 API）。

        ## 语义（用户 2026-10-30 原话）

        > 跳过相当于他已经强化好了，需要跳过同类型同名声骸

        所以按一下 =
        * 跳过它本身
        * 之后**同名同类型**（含「异相」版）的都跳过
        * 成套模式下计入该 Cost 档的种类数

        ## 为什么走宿主中转而不是直接改任务属性

        任务跑在**引擎线程**里，界面线程直接改它的属性有两个问题：
        竞态（界面改了、任务正好在读写）、任务实例可能还没建出来。
        主机上放一个**一次性标志**、任务自己在检查点取走 —— 宿主有锁。

        :return: ``{ok, message}`` / ``{ok: false, reason, message}``
        """
        try:
            from ..tools.game.auto_combat import okww_boot  # noqa: PLC0415

            host = okww_boot.current_host()
            if host is None:
                return _json({"ok": False, "reason": "idle",
                              "message": "引擎还没启动过，没有正在跑的强化任务"})

            request = getattr(host, "request_skip_current", None)
            if not callable(request):
                return _json({"ok": False, "reason": "unsupported",
                              "message": "当前引擎版本不支持跳过"})

            #: 上游返回 True = 已记下请求 / False = 当前没有在跑的强化任务
            accepted = bool(request())
            if not accepted:
                return _json({"ok": False, "reason": "no_task",
                              "message": "当前没有正在跑的强化任务，跳过无处可去"})
            msg = "已请求跳过当前声骸（同名同类型的后面也跳过）"
            self.pushLog(f"⏭ {msg}", "warn")
            logger.info("WebBridge：已请求跳过当前声骸")
            return _json({"ok": True, "message": msg})
        except Exception as exc:  # noqa: BLE001
            logger.warning("okwwSkipEcho 失败", exc_info=True)
            return _json({"ok": False, "reason": "error",
                          "message": f"{type(exc).__name__}: {exc}"})

    # ================================================ 声骸强化历史（P5）
    #
    # ★ 用户 P5：「图7 声骸强化也是，请不要擅自修改原先的布局内容」
    #
    # 旧界面有「历史记录」卡（``tool.py`` 的 ``_build_history_card``，L577）：
    # 每次「运行 → 停止」记一条，**最多展示最近 10 轮**。
    #
    # 数据在 ``<用户数据>/echo_enhance_history.json``，
    # 由 :class:`src.core.tool_history.ToolHistoryStore` 读写 —— 直接调它，
    # **不要自己解析 JSON**（字段和迁移逻辑都在那个模块里）。

    #: 历史记录默认返回几条（旧界面就是 10）
    _ECHO_HISTORY_LIMIT = 10

    # ------------------------------------------------ 4C 自动战斗（P6）
    #
    # ★ 2026-11-02 用户发了 7 张旧界面截图，要求「对着旧界面的代码复刻」。
    #
    # 旧界面这块有：
    # * **历史记录卡**（``auto_combat/tool.py`` L107 ``HistoryCard``）——
    #   5 列：时间 / 时长 / 战斗 / 声骸 / 锁定，**最近 5 次**，底部有汇总
    # * **定时关机卡**（L452 ``_build_shutdown_card``）——
    #   「启用」勾选框 + 「N 分钟后关机」输入框（1~1440 分钟）
    #
    # ⚠ 两个都**不是**我 P4 自造的那种「运行前提」区块 —— 那是用户圈出来
    # 要求「干掉」的。这两个在旧界面里**真实存在**。

    #: 4C 历史默认返回几条 —— 旧界面 ``HistoryCard.MAX_ROWS = 5``
    _COMBAT_HISTORY_LIMIT = 5

    @Slot(str, result=str)
    def getCombatHistory(self, limit: str = "") -> str:
        """4C 自动战斗的历史记录（每次「启动 → 停止」一条）。

        照抄旧界面 ``HistoryCard``（``auto_combat/tool.py`` L107）：

        * 5 列：**时间 / 时长 / 战斗 / 声骸 / 锁定**
        * 只显示最近 **5** 次（``MAX_ROWS = 5``）
        * 底部有「共 N 次」汇总（见返回里的 ``totalText``）

        :param limit: 最多返回几条；空串 = 5（旧界面的数量）

        返回 ``{ok, items, count, total, totalText}``，每条：

        .. code:: json

            {"when": "10-28 14:30", "duration": "12:34",
             "battles": 8, "echoes": 12, "locked": 2,
             "team": ["角色A","角色B","角色C"], "echo": "声骸名"}

        ⚠ 用 ``auto_combat.history.HistoryStore``（**不是**
        ``core.tool_history``）—— 这个工具的记录结构不一样（有 battles /
        echoes / locked 三个专属字段），它有自己的 store 和文件。
        """
        try:
            from ..tools.game.auto_combat import history as combat_history  # noqa: PLC0415

            store = combat_history.HistoryStore()
            all_records = store.load()

            try:
                count = int(str(limit).strip() or self._COMBAT_HISTORY_LIMIT)
            except (TypeError, ValueError):
                count = self._COMBAT_HISTORY_LIMIT
            count = max(1, min(50, count))

            recent = store.records(count)
            items: list[dict] = []
            for rec in recent or []:
                items.append({
                    "when": _safe(lambda r=rec: r.when_text, "—"),
                    "duration": _safe(lambda r=rec: r.duration_text, "—"),
                    "startedAt": float(_safe(lambda r=rec: r.started_at, 0.0)),
                    "endedAt": float(_safe(lambda r=rec: r.ended_at, 0.0)),
                    #: 5 列里除「时间/时长」外的三列
                    "battles": int(_safe(lambda r=rec: r.battles, 0)),
                    "echoes": int(_safe(lambda r=rec: r.echoes, 0)),
                    "locked": int(_safe(lambda r=rec: r.locked, 0)),
                    #: 队伍 / 声骸名（旧界面有 team_text / echo_text）
                    "team": list(_safe(lambda r=rec: r.team, ()) or ()),
                    "echo": str(_safe(lambda r=rec: r.echo, "") or ""),
                })

            return _json({
                "ok": True,
                "items": items,
                "count": len(items),
                "total": len(all_records),
                #: 旧界面底部的汇总行（"共 N 次 · 战斗 X · 锁定 Y"）
                "totalText": _safe(lambda: store.total_text(), ""),
                "limit": count,
            })
        except Exception as exc:  # noqa: BLE001
            logger.warning("getCombatHistory 失败", exc_info=True)
            return _json({"ok": False, "reason": "error",
                          "message": f"{type(exc).__name__}: {exc}"})

    @Slot(result=str)
    def getShutdownTimer(self) -> str:
        """读定时关机设置（旧界面 ``_build_shutdown_card``）。

        返回 ``{ok, enabled, minutes, minMinutes, maxMinutes, defaultMinutes}``。

        ⚠ ``enabled=False`` 时 ``minutes`` 仍是**上次填的值**（旧界面
        存盘时就是这么存的，取消勾选不清掉分钟数）。
        """
        try:
            from . import shutdown_timer, tool_settings  # noqa: PLC0415
            from ..tools.game.auto_combat.tool import (  # noqa: PLC0415
                DEFAULT_SHUTDOWN_MINUTES, SHUTDOWN_SETTINGS_KEY,
            )

            saved = tool_settings.load(SHUTDOWN_SETTINGS_KEY) or {}
            enabled = bool(saved.get("shutdown_enabled"))
            minutes = shutdown_timer.clamp_minutes(
                saved.get("shutdown_minutes") or DEFAULT_SHUTDOWN_MINUTES)
            return _json({
                "ok": True,
                "enabled": enabled,
                "minutes": minutes or DEFAULT_SHUTDOWN_MINUTES,
                #: 让页面画输入框的 min/max，不用把常数抄一遍
                "minMinutes": shutdown_timer.MIN_MINUTES,
                "maxMinutes": shutdown_timer.MAX_MINUTES,
                "defaultMinutes": DEFAULT_SHUTDOWN_MINUTES,
            })
        except Exception:  # noqa: BLE001
            logger.warning("getShutdownTimer 失败", exc_info=True)
            return _json({"ok": False, "reason": "error",
                          "message": "读定时关机设置失败，详见日志"})

    @Slot(str, result=str)
    def setShutdownTimer(self, payload: str) -> str:
        """存定时关机设置（旧界面 ``_save_shutdown``）。

        ``payload`` = ``{"enabled": bool, "minutes": int}``

        ## ⚠ 必须和旧界面存成同一个形状

        旧界面 ``_save_shutdown``（``auto_combat/tool.py`` L665）：

        .. code:: python

            tool_settings.save(SHUTDOWN_SETTINGS_KEY, {
                **dict(tool_settings.load(SHUTDOWN_SETTINGS_KEY) or {}),  # ← 合并
                "shutdown_enabled": ...,
                "shutdown_minutes": shutdown_timer.clamp_minutes(...) or DEFAULT,
            })

        两个要点：

        1. **合并**而不是覆盖 —— 同一个 key 下还有别的设置（比如战斗风格
           在 ``COMBAT_STYLE_KEY``，但别的地方也可能用这个 key）
        2. **clamp 过再存** —— 别把脏数据写进盘

        :return: ``{ok, enabled, minutes}``（回显夹过的实际值）
        """
        try:
            data = json.loads(payload or "{}")
        except (TypeError, ValueError):
            return _json({"ok": False, "reason": "bad_json",
                          "message": "payload 不是合法 JSON"})
        if not isinstance(data, dict):
            return _json({"ok": False, "reason": "bad_data",
                          "message": "payload 必须是对象"})

        try:
            from . import shutdown_timer, tool_settings  # noqa: PLC0415
            from ..tools.game.auto_combat.tool import (  # noqa: PLC0415
                DEFAULT_SHUTDOWN_MINUTES, SHUTDOWN_SETTINGS_KEY,
            )

            enabled = bool(data.get("enabled"))
            minutes = shutdown_timer.clamp_minutes(
                data.get("minutes") or DEFAULT_SHUTDOWN_MINUTES)
            if not minutes:
                minutes = DEFAULT_SHUTDOWN_MINUTES

            tool_settings.save(SHUTDOWN_SETTINGS_KEY, {
                #: ★ 合并，别覆盖同 key 下的其他字段
                **dict(tool_settings.load(SHUTDOWN_SETTINGS_KEY) or {}),
                "shutdown_enabled": enabled,
                "shutdown_minutes": minutes,
            })
            logger.info("WebBridge：定时关机设置 enabled=%s minutes=%s",
                        enabled, minutes)
            return _json({"ok": True, "enabled": enabled, "minutes": minutes})
        except Exception as exc:  # noqa: BLE001
            logger.warning("setShutdownTimer 失败", exc_info=True)
            return _json({"ok": False, "reason": "error",
                          "message": f"{type(exc).__name__}: {exc}"})

    @Slot(str, result=str)
    def getEchoEnhanceHistory(self, limit: str = "") -> str:
        """声骸强化的历史记录（每次「运行 → 停止」一条）。

        :param limit: 最多返回几条；空串 = 用默认 10（旧界面的数量）

        返回 ``{ok, items: [...], count, total}``，每条：

        .. code:: json

            {"when": "10-28 14:30",        // 什么时候跑的
             "duration": "12:34",          // 跑了多久
             "startedAt": 1698... ,        // 原始时间戳（要排序/格式化时用）
             "stats": {"judged": 120, "qualified": 8, "discarded": 112, ...}}

        ``stats`` 是 ``ToolRunRecord.extra`` 原样 —— 字段由工具自定义
        （判定数 / 符合条件 / 弃置 / 各弃置原因计数…），
        页面按 key 取，别假设一定有哪个。

        ⚠ **只读**，不写盘、不改历史。
        """
        try:
            from . import tool_history  # noqa: PLC0415

            store = tool_history.ToolHistoryStore("echo_enhance")
            records = store.load()

            try:
                count = int(str(limit).strip() or self._ECHO_HISTORY_LIMIT)
            except (TypeError, ValueError):
                count = self._ECHO_HISTORY_LIMIT
            count = max(1, min(200, count))

            #: ``records(limit)`` 返回**最近的在前**（见 ToolHistoryStore.records）
            recent = store.records(limit=count)

            items: list[dict] = []
            for rec in recent or []:
                items.append({
                    "when": _safe(lambda r=rec: r.when_text, "—"),
                    "duration": _safe(lambda r=rec: r.duration_text, "—"),
                    "startedAt": float(_safe(lambda r=rec: r.started_at, 0.0)),
                    "endedAt": float(_safe(lambda r=rec: r.ended_at, 0.0)),
                    #: 工具自定义统计原样给（页面按 key 取）
                    "stats": _safe(lambda r=rec: dict(r.extra or {}), {}),
                })

            return _json({
                "ok": True,
                "items": items,
                "count": len(items),
                #: 历史总条数（可能 > count）
                "total": len(records),
                "limit": count,
            })
        except Exception as exc:  # noqa: BLE001
            logger.warning("getEchoEnhanceHistory 失败", exc_info=True)
            return _json({"ok": False, "reason": "error",
                          "message": f"{type(exc).__name__}: {exc}"})

    # ================================================ 资源库更新（P4）
    #
    # GUI 里的等价实现：``src/tools/data/wuwa_library_update.py``
    # （CheckThread / ApplyThread）。线程模型照抄它 —— 网络请求阻塞
    # 几秒到几十秒，**绝不能在主线程跑**。

    @Slot(result=str)
    def checkLibraryUpdate(self) -> str:
        """检查资源库更新（**异步**）。

        完成后推 ``libraryChecked``：

        .. code:: json

            {"ok": true, "hasUpdates": true, "remoteEmpty": false,
             "localEmpty": false, "summary": "…", "newSets": [],
             "effectChanged": [], "newEchoes": [], "newCharacters": []}

        失败：``{"ok": false, "message": "…"}``
        """
        if self._lib_check_running:
            return _json({"ok": False, "reason": "busy",
                          "message": "正在检查更新，请稍候"})

        try:
            from . import wuwa_update  # noqa: PLC0415
        except Exception:  # noqa: BLE001
            logger.warning("checkLibraryUpdate：模块不可用", exc_info=True)
            return _json({"ok": False, "reason": "unavailable",
                          "message": "资源库更新模块不可用"})

        thread = self._LibCheckThread(wuwa_update, self)
        self._lib_check_thread = thread
        self._lib_check_running = True

        def on_ok(snapshot, report) -> None:
            self._lib_check_running = False
            #: ★ snapshot 必须留着 —— applyLibraryUpdate 靠它写盘。
            #: Qt 版就是因为漏存才崩 'NoneType' has no attribute 'sets'。
            self._lib_snapshot = snapshot
            self._lib_report = report
            data = _report_to_dict(report)
            data["ok"] = True
            self.emitEvent("libraryChecked", data)
            self._log_library(f"检查完成：{data.get('summary', '')}".strip(),
                              "ok")

        def on_fail(message: str) -> None:
            self._lib_check_running = False
            #: 失败 → **作废**这一轮（旧 snapshot 配新 report 是错配，
            #: 点应用会把上一轮数据当这一轮写进去）
            self._lib_snapshot = None
            self._lib_report = None
            self.emitEvent("libraryChecked", {"ok": False, "message": message})
            self._log_library(f"✗ 检查失败：{message}", "error")

        thread.succeeded.connect(on_ok)
        thread.failed.connect(on_fail)
        thread.finished.connect(thread.deleteLater)
        thread.start()
        self._log_library("开始检查资源库更新……", "info")
        return _json({"ok": True})

    @Slot(result=str)
    def applyLibraryUpdate(self) -> str:
        """应用资源库更新（**异步**）。必须先 :meth:`checkLibraryUpdate`。

        完成后推 ``libraryApplied``：``{ok: true, done: ["…"]}``
        """
        if self._lib_apply_running:
            return _json({"ok": False, "reason": "busy",
                          "message": "正在写入更新，请稍候"})
        if self._lib_check_running:
            return _json({"ok": False, "reason": "busy",
                          "message": "还在检查中，等检查完成再应用"})
        if self._lib_snapshot is None or self._lib_report is None:
            return _json({"ok": False, "reason": "not_checked",
                          "message": "还没检查过，请先点「检查更新」"})
        if not getattr(self._lib_report, "has_updates", False):
            return _json({"ok": False, "reason": "no_updates",
                          "message": "没有可应用的更新"})

        try:
            from . import wuwa_update  # noqa: PLC0415
        except Exception:  # noqa: BLE001
            return _json({"ok": False, "reason": "unavailable",
                          "message": "资源库更新模块不可用"})

        thread = self._LibApplyThread(
            wuwa_update, self._lib_snapshot, self._lib_report, self)
        self._lib_apply_thread = thread
        self._lib_apply_running = True

        def on_ok(done: list) -> None:
            self._lib_apply_running = False
            #: 成功 → 作废本轮（再应用一次是错的）
            self._lib_snapshot = None
            self._lib_report = None
            self.emitEvent("libraryApplied",
                           {"ok": True, "done": list(done or [])})
            self._log_library("✓ 更新已写入并即时生效", "ok")

        def on_fail(message: str) -> None:
            self._lib_apply_running = False
            self.emitEvent("libraryApplied", {"ok": False, "message": message})
            self._log_library(f"✗ 写入失败：{message}", "error")

        thread.succeeded.connect(on_ok)
        thread.failed.connect(on_fail)
        thread.finished.connect(thread.deleteLater)
        thread.start()
        self._log_library("开始写入更新……", "info")
        return _json({"ok": True})

    # ================================================ 工具设置（P4）
    #
    # 工具页在 Qt 版里把「用户上次选的参数」存在
    # ``<用户数据>/tool_settings.json``（见 :mod:`src.core.tool_settings`）。
    # Web 面板要**继承**这些设置 —— 否则用户从旧界面切过来，
    # 之前调好的属性/数量全丢，得重选一遍。

    @Slot(str, result=str)
    def getToolSettings(self, tool_key: str) -> str:
        """读某个工具上次保存的设置。

        :param tool_key: **工具 key**（``echo_change``），内部会换成
            该工具自己的 ``SETTINGS_KEY``（两者通常相同，但别假设）。

        :return: ``{ok: true, key, settings: {...}, defaults: {...},
                  choices: {...}}``

        ## ``choices`` 是什么

        有些设置是**枚举**（比如声骸调频的「目标属性」12 项）。
        工具里有常量定义（``TARGET_STATS``），但页面拿不到 —— 所以这里
        一并给出去，页面就能渲染下拉框而不用把中文列表抄一遍。

        ⚠ **枚举值必须逐字使用**。工具侧会拿它和 ``TARGET_STATS`` 做
        ``in`` 校验，抄错一个字（比如写成「攻击力」）就会被当成脏数据。

        ⚠⚠ **没有 ``prerequisites`` 字段**（2026-11-02 删）——
        旧界面没有「运行前提」区块，用户明确要求去掉。见模块顶部那段说明。

        返回 ``{ok: false, reason, message}`` 表示这个工具没有设置或模块缺失。
        """
        tool_key = (tool_key or "").strip()
        if not tool_key:
            return _json({"ok": False, "reason": "empty",
                          "message": "没给 tool_key"})

        _ensure_tools_discovered()
        try:
            from . import tool_settings  # noqa: PLC0415
        except Exception:  # noqa: BLE001
            return _json({"ok": False, "reason": "unavailable",
                          "message": "tool_settings 模块不可用"})

        #: 工具 key → 设置键 / 枚举常量（模块路径 + 常量名）
        spec = _TOOL_SETTINGS_SPEC.get(tool_key)
        settings_key = spec["settingsKey"] if spec else tool_key

        settings: dict = {}
        try:
            got = tool_settings.load(settings_key)
            settings = got if isinstance(got, dict) else {}
        except Exception:  # noqa: BLE001 - 读不出来就当没存过
            logger.debug("getToolSettings：读 %s 失败", settings_key,
                         exc_info=True)

        defaults: dict = {}
        choices: dict = {}
        #: ★ 2026-11-03 有些工具还要给「合法范围」（目前只有 echo_enhance）
        ranges: dict = {}
        if spec:
            mod = _import_quiet(spec["module"])
            if mod is not None:
                for field, const in (spec.get("defaults") or {}).items():
                    value = _safe(lambda m=mod, c=const: getattr(m, c), None)
                    if value is not None:
                        defaults[field] = value
                for field, const in (spec.get("choices") or {}).items():
                    value = _safe(lambda m=mod, c=const: getattr(m, c), None)
                    if value is not None:
                        #: ★ 三元组常量（如 rotation.STYLES）要展开成
                        #: [{value,label,desc}]，不能把工具私有结构丢给页面
                        choices[field] = _expand_choices(
                            value,
                            as_tuples=field in (spec.get("tupleChoices") or ()),
                        )
                #: ★★★ 2026-11-03 「有效词条数」的合法范围
                #:
                #: 规则在 ``settings.valid_count_range(core, optional)``：
                #:   下界 = 核心属性条数（「核心几条，有效词条最低就几条」）
                #:   上界 = 核心 ∪ 可选 的总条数
                #:
                #: 用**当前已存设置**算，页面拿到后把加减框的 min/max 设对，
                #: 并在当前值越界时**当场**提示 —— 而不是等点「创建」
                #: 才被后端拒绝（用户圈图抱怨的正是这个）。
                if spec.get("validCountRange"):
                    try:
                        core = settings.get("core_stats")
                        optional = settings.get("optional_stats")
                        low, high = mod.valid_count_range(
                            core if isinstance(core, (list, tuple)) else (),
                            optional if isinstance(optional, (list, tuple)) else (),
                        )
                        ranges["minValidCount"] = [int(low), int(high)]
                    except Exception:  # noqa: BLE001 - 算不出来就不给
                        logger.debug(
                            "getToolSettings：算 valid_count_range 失败",
                            exc_info=True)

        return _json({
            "ok": True,
            "key": tool_key,
            "settingsKey": settings_key,
            "settings": settings,
            "defaults": defaults,
            "choices": choices,
            "ranges": ranges,
            #: ⚠ 这里**没有** ``prerequisites``（2026-11-02 删）——
            #: 旧界面没有「运行前提」区块，用户要求去掉。
        })

    @Slot(str, result=str)
    def setToolSettings(self, payload: str) -> str:
        """保存某个工具的设置（和 Qt 版写同一个文件）。

        ``payload`` = JSON ``{"toolKey": "echo_change", "settings": {...}}``
        """
        try:
            data = json.loads(payload or "{}")
        except (TypeError, ValueError):
            return _json({"ok": False, "reason": "bad_json",
                          "message": "payload 不是合法 JSON"})
        if not isinstance(data, dict):
            return _json({"ok": False, "reason": "bad_payload",
                          "message": "payload 必须是对象"})
        tool_key = str(data.get("toolKey") or "").strip()
        settings = data.get("settings")
        if not tool_key:
            return _json({"ok": False, "reason": "empty",
                          "message": "没给 toolKey"})
        if not isinstance(settings, dict):
            return _json({"ok": False, "reason": "bad_data",
                          "message": "settings 必须是对象"})
        try:
            from . import tool_settings  # noqa: PLC0415

            spec = _TOOL_SETTINGS_SPEC.get(tool_key)
            settings_key = spec["settingsKey"] if spec else tool_key
            tool_settings.save(settings_key, settings)
            logger.info("WebBridge：保存 %s 的工具设置", tool_key)
            return _json({"ok": True, "key": tool_key,
                          "settingsKey": settings_key})
        except Exception as exc:  # noqa: BLE001
            logger.warning("setToolSettings 失败", exc_info=True)
            return _json({"ok": False, "reason": "error",
                          "message": f"{type(exc).__name__}: {exc}"})

    # ================================================ 抽卡记录分析（P4 第三批）
    #
    # GUI 版在 ``src/tools/game/gacha/tool.py``（FetchThread + 本地历史合并）。
    #
    # ## 流程（和 Qt 版一致，别省步骤）
    #
    # .. code:: text
    #
    #     parse_link(link)      ← 校验三种必填参数，报错要"指明问题"
    #       ↓
    #     fetch_raw(params)     ← 拉全部卡池（一个失败就整体失败）
    #       ↓
    #     gacha_store 合并进本地历史   ← ★ 接口只给最近一段，累计才算数
    #       ↓
    #     report_from_records() ← 用**合并后**的全量记录出报告
    #
    # ⚠ **不能直接用 fetch_report()** —— 那只统计"这一次拉到的"，
    # 用户在多个设备/多次拉取之间，累计数字会变少（Qt 版就是这么做的）。

    @Slot(str, result=str)
    def analyzeGacha(self, link: str) -> str:
        """分析抽卡记录（**异步**）。``link`` = 游戏里复制的唤取记录链接。

        :return: ``{ok: true}`` 已受理 /
                 ``{ok: false, reason: "bad_link", message: "…"}`` ——
                 **链接错误是同步返回的**（不满足"三种必填参数"那种，
                 没必要起线程）

        完成后推 ``gachaAnalyzed``：

        .. code:: json

            {"ok": true, "total": 1234, "fiveCount": 20, "fourCount": 300,
             "rate": 1.62, "average": 61.7,
             "pools": [{"name": "角色活动唤取", "total": 500, "fiveCount": 8,
                        "rate": 1.6, "average": 62.5}],
             "fiveStars": [{"name": "…", "time": "…", "span": 42,
                            "isLost": false, …}]}

        失败：``{"ok": false, "message": "…"}``
        """
        if self._gacha_running:
            return _json({"ok": False, "reason": "busy",
                          "message": "正在分析，请稍候"})

        link = str(link or "").strip()
        if not link:
            return _json({"ok": False, "reason": "bad_link",
                          "message": "请先粘贴唤取记录链接"
                                     "（游戏里打开「唤取记录」页面复制）"})

        # ── ① 先同步解析链接（错误立刻返回，用户体验好）──
        try:
            from . import gacha  # noqa: PLC0415

            params = gacha.parse_link(link)
        except Exception as exc:  # noqa: BLE001
            #: ``GachaError`` 的文案是**写给用户看的**（指明缺哪一项），
            #: 原样透传；其他异常才带类名。
            from .gacha import GachaError  # noqa: PLC0415

            message = str(exc) if isinstance(exc, GachaError) \
                else f"{type(exc).__name__}: {exc}"
            return _json({"ok": False, "reason": "bad_link",
                          "message": message})

        # ── ② 起线程拉数据 ──
        thread = self._GachaThread(params, self)
        self._gacha_thread = thread
        self._gacha_running = True

        def on_ok(report_dict: dict) -> None:
            self._gacha_running = False
            report_dict["ok"] = True
            self.emitEvent("gachaAnalyzed", report_dict)
            self.pushLog(
                f"抽卡分析完成：共 {report_dict.get('total', 0)} 抽，"
                f"{report_dict.get('fiveCount', 0)} 个五星", "ok")

        def on_fail(message: str) -> None:
            self._gacha_running = False
            self.emitEvent("gachaAnalyzed",
                           {"ok": False, "message": message})
            self.pushLog(f"✗ 抽卡分析失败：{message}", "error")

        thread.succeeded.connect(on_ok)
        thread.failed.connect(on_fail)
        thread.finished.connect(thread.deleteLater)
        thread.start()
        self.pushLog("开始拉取唤取记录……", "info")
        return _json({"ok": True})

    # ================================================ 抽卡历史（P5 ⑤）
    #
    # ★★ 用户 2026-11-02：「图5 我的抽卡分析记录呢」
    #
    # 旧界面有两块（**都要对齐，不要重写**）：
    #
    # * ``core/gacha_store.py``        —— 快照存储（``GachaHistoryStore``）
    # * ``core/gacha_history_view.py`` —— **按（账号, 年月）聚合的纯函数**
    #
    # 聚合逻辑（``group_by_account_month``）里有一堆用户亲自定的规则：
    # 「同一账号不同时间，数据一样就用最新时间的，不一样就合并」、
    # 数字取 **max 不是 sum**（累计值相加会变天文数字）……
    # **这些规则已经写好了，直接调，不要重新实现。**

    def _gacha_store(self):
        """建 ``GachaHistoryStore`` —— **路径可被测试覆盖**。

        ## 为什么要有这一层（2026-11-02 事故二）

        我的 ``web_shell_gacha_clear.py`` 为了验证「传对令牌真的能清空」，
        **真的清空了用户的 549 KB 抽卡历史**。

        正确做法是让测试**用临时文件跑同一条代码路径**：

        .. code:: python

            bridge = WebBridge()
            bridge._gacha_store_path = tmpdir / "gacha_history.json"
            # 之后 getGachaHistory / clearGachaHistory 都作用于临时文件

        :attr:`_gacha_store_path` 为 None（生产默认）时走真实用户数据。
        """
        from . import gacha_store  # noqa: PLC0415

        path = getattr(self, "_gacha_store_path", None)
        if path:
            return gacha_store.GachaHistoryStore(path=path)
        return gacha_store.GachaHistoryStore()

    def _gacha_report(self, player_id: str = ""):
        """从**本地缓存**重建 ``GachaReport``（不联网）。

        ## ★★★ 照抄旧界面的链路（``gacha/tool.py`` ``_render_from_history``）

        .. code:: python

            history = store.load()
            who = ""                                    # 取最近一个**认得出账号**的快照
            for snap in history.snapshots:
                if snap.player_id:
                    who = str(snap.player_id)
                    break
            rows = history.all_records(who) if who else history.all_records()
            report = gacha.report_from_records(rows, player_id=who)

        ⚠ **不要自己算统计**。``GachaReport`` / ``PoolStats`` 里那堆方法
        （``not_up_rate`` / ``average_per_up`` / ``luck`` …）的公式是
        和鸣潮工坊对照过的，重写必错。这里只负责**把数据喂进去**。

        ⚠ ``snapshots[0]`` 可能是"未知账号"（升级前的旧快照没有 player_id）——
        所以**跳过空账号**取最近一个有账号的。旧代码在这上面修过一个真 bug：
        不过滤时 ``all_records("")`` 会把**所有账号的数据混在一起**。

        :param player_id: 指定账号；空串 = 自动取最近一个有账号的
        :return: ``(report, who, rows)``；没数据时 report 的 total 为 0
        """
        from . import gacha, gacha_store  # noqa: PLC0415

        store = self._gacha_store()
        history = store.load()
        who = str(player_id or "").strip()
        if not who:
            for snap in getattr(history, "snapshots", []) or []:
                if getattr(snap, "player_id", ""):
                    who = str(snap.player_id)
                    break
        rows = history.all_records(who) if who else history.all_records()
        report = gacha.report_from_records(rows, player_id=who)
        return report, who, rows

    @Slot(str, result=str)
    def getGachaPoolDetail(self, player_id: str = "") -> str:
        """4 个卡池的**逐条出金记录**（抽卡页每条抽数条列表）。

        对应旧界面 ``gacha/tool.py`` 的 ``_pool_block()`` / ``_five_row()``。

        ## 用户 2026-09-30（原话）

        > **差在逐条抽数条列表**

        旧界面每个卡池下面是一串：

        .. code:: text

            [头像] ████████████ 68抽          (歪)
            [头像] ██████ 33抽
            [头像] ███████████████ 81抽        (歪)

        条长按 ``span`` 走、颜色按欧非分级（绿→黄→红）。

        ## ★ 顺序：**最新的在最上面**

        旧界面写的是 ``reversed(pool.fives_analysis())``。
        ``fives_analysis()`` 内部已经 ``reversed(self.pulls)``（拉取是"最新在前"，
        反转成"最旧在前"→ 逐个累加 span），所以再反转一次 = **最新在前**。

        这里**后端排好**（前端再排容易排错）。

        ## 返回

        .. code:: json

            {"ok": true,
             "pools": [{
               "poolType": "1", "name": "角色活动唤取",
               "pulls": 790, "five": 18, "rate": 2.28,
               "avgFive": 43.9, "pity": 0, "rank": "欧皇",
               "isLimitedPool": true,
               "fives": [{
                 "name": "安可",
                 "kind": "角色",
                 "span": 68,              // 这一金用了几抽（条长按它）
                 "cumulative": 68,        // 距上次 UP 的抽数（大保底口径）
                 "isUp": true,            // 是 UP
                 "isLost": false,         // 歪了 —— 显示「(歪)」
                 "at": "2026-09-12 21:14",
                 "iconUrl": "…",          // 头像（拿不到就空，前端用首字兜底）
                 "avatarHue": 123, "initial": {…},
                 "rarity": 5,
                 //: ★ 下面两个是**后端算好的展示值**，前端直接用
                 "barColor": "#c8a86a",   // 抽数条颜色（span_color 分级）
                 "verdict": "",           // "歪"/"欧"/"非"/""（_verdict 规则）
                 "verdictColor": ""
               }]
             }]}

        ## 三个口径（都照抄旧界面，没自己算）

        =============  ==================================================
        ``barColor``   ``gacha.span_color(span)`` —— 40/60/73/80 分档
        ``verdict``    ≤60 抽="欧" / ≥74 抽="非" / 歪了="歪" / 中间空
        ``span``       **不是** ``cumulative`` —— 条长看的是"这个金花了几抽"
        =============  ==================================================
        """
        try:
            from . import gacha  # noqa: PLC0415

            report, who, rows = self._gacha_report(player_id)
            if not rows:
                return _json({"ok": False, "reason": "no_data",
                              "message": "还没有抽卡记录 —— 点「分析」粘贴链接"
                                         "拉一次，之后这里就有明细了"})

            pools: list[dict] = []
            for pool in report.active_pools():
                #: ★ 和旧界面同一个顺序：最新在最上面
                fives_raw = list(reversed(pool.fives_analysis()))
                fives: list[dict] = []
                for five in fives_raw:
                    span = int(getattr(five, "span", 0) or 0)
                    name = str(getattr(five, "name", "") or "")
                    kind = str(getattr(five, "kind", "") or "")
                    #: 旧界面 _verdict 的规则（照抄）
                    verdict, verdict_color = _gacha_verdict(five)
                    #: 头像：角色查 avatars / 武器查 weapons（和卡片墙同一套）
                    sub = "weapons" if kind == "武器" else "avatars"
                    rel = f"{sub}/{name}.png" if name else ""
                    fives.append({
                        "name": name,
                        "kind": kind,
                        "span": span,
                        "cumulative": int(
                            getattr(five, "cumulative", 0) or 0),
                        "isUp": bool(getattr(five, "is_up", True)),
                        "isLost": bool(getattr(five, "is_lost", False)),
                        "at": str(getattr(five, "time", "") or ""),
                        "iconUrl": self._safe_icon_url(rel),
                        "avatarHue": _initial_avatar_hue(name),
                        "initial": _initial_avatar(name),
                        "rarity": 5,
                        #: ★ 后端算好的展示值（前端不用自己分档）
                        "barColor": str(gacha.span_color(span)),
                        "verdict": verdict,
                        "verdictColor": verdict_color,
                    })

                pool_avg = pool.average()
                pool_luck = pool.luck()
                pools.append({
                    "poolType": str(pool.pool_type),
                    "name": pool.name,
                    "pulls": int(pool.total),
                    "five": int(pool.five_count),
                    "rate": round(pool.rate(), 2),
                    "avgFive": round(pool_avg, 1) if pool_avg else None,
                    "pity": int(_safe(lambda p=pool: p.pity_count(), 0)),
                    "rank": pool_luck[0] if pool_luck else None,
                    "isLimitedPool": bool(pool.is_limited_pool),
                    "fives": fives,
                })

            return _json({
                "ok": True,
                "pools": pools,
                "playerId": who,
                #: 总五星条数（页面可以显示"共 24 条"）
                "fiveTotal": sum(len(p["fives"]) for p in pools),
            })
        except Exception:  # noqa: BLE001
            logger.warning("getGachaPoolDetail 失败", exc_info=True)
            return _json({"ok": False, "reason": "error",
                          "message": "读抽卡明细失败，详见日志"})

    @Slot(str, result=str)
    def getGachaOverview(self, player_id: str = "") -> str:
        """本地已缓存记录的**完整统计**（不联网）。

        对应旧界面 ``gacha/tool.py`` 的 ``overview_card``（L695）+ 卡片墙。

        ## 为什么需要它（2026-11-02，lead 发现的缺口）

        ``getGachaHistory()`` 只给**历史快照**（每月多少抽/多少金），
        而欧皇卡要的 6 个数字它一个都没有。截图里那 6 个格子全是 ``—``。

        ## 返回

        .. code:: json

            {"ok": true,
             "total": 1131,          // 总抽卡数
             "avgFive": 47,          // 平均出金（.0f 取整，和旧界面一致）
             "noLoseRate": 66.7,     // 小保底不歪 %（null = 没抽过限定池）
             "five": 24,             // 五星数
             "perChar": 71.8,        // 每UP角色需（null = 没出过）
             "perWeapon": 63.3,      // 每UP武器需（null = 没出过）
             "rank": "欧皇",          // 左上角评价（null = 没出过五星）
             "summary": {"limited": 4, "standard": 5,
                         "standardNames": ["凌阳","安可",...],
                         "note": "共获得限定五星 4 个，常驻五星 5 个。"},
             "cards": [{"name":"...", "count":5, "kind":"角色",
                        "avatarUrl":"...", "avatarHue":123, "initial":{...},
                        "isLimited":true}],
             "pools": [{"poolType":"1", "name":"角色活动唤取",
                        "pulls":790, "five":18, "rate":2.3,
                        "avgFive":43.9, "pity":1, "rank":"欧皇"}],
             "playerId": "113152489", "accountLabel": "…",
             "recordCount": 14703}

        ## 口径（**全部来自 ``GachaReport``，逐条对齐旧界面 L1134-1156**）

        ==============  ==========================================
        字段             来源
        ==============  ==========================================
        ``total``        ``report.total``
        ``avgFive``      ``report.average()``（``.0f``）
        ``noLoseRate``   ``report.not_up_rate()``（``.1f`` + ``%``）
        ``five``         ``report.five_count``
        ``perChar``      ``report.average_per_up("角色")``
        ``perWeapon``    ``report.average_per_up("武器")``
        ``rank``         ``report.luck()[0]``
        ==============  ==========================================

        ⚠ **null 不是 0**：没抽过限定池 / 没出过五星时这些是 ``None``，
        旧界面显示 ``—``。页面必须区分（0 会被误读成"每次都歪"）。
        """
        try:
            from . import gacha_store  # noqa: PLC0415

            report, who, rows = self._gacha_report(player_id)

            #: 一条记录都没有 → 明确告诉页面（别显示一排 0）
            if not rows:
                return _json({"ok": False, "reason": "no_data",
                              "message": "还没有抽卡记录 —— 点「分析」粘贴链接"
                                         "拉一次，之后这里就有统计了"})

            average = report.average()
            not_up = report.not_up_rate()
            per_char = report.average_per_up("角色")
            per_weapon = report.average_per_up("武器")
            luck = report.luck()
            limited = report.limited_fives()
            permanent = report.permanent_fives()

            # ---- 五星卡片墙（旧界面 _render_cards）----
            #
            #: 统计每个名字出现几次 + 它是角色还是武器（决定查哪个图标目录）
            counts: dict[str, int] = {}
            kinds: dict[str, str] = {}
            for f in report.all_fives_analysis():
                if not f.name:
                    continue
                counts[f.name] = counts.get(f.name, 0) + 1
                kinds.setdefault(f.name, str(getattr(f, "kind", "") or ""))
            #: 和旧界面一样按次数倒序
            cards: list[dict] = []
            for name, count in sorted(counts.items(), key=lambda kv: -kv[1]):
                kind = kinds.get(name, "")
                #: 角色查 avatars/，武器查 weapons/（旧界面同一套规则）
                sub = "weapons" if kind == "武器" else "avatars"
                rel = f"{sub}/{name}.png"
                cards.append({
                    "name": name,
                    "count": count,
                    "kind": kind,
                    "avatarUrl": self._safe_icon_url(rel),
                    "avatarHue": _initial_avatar_hue(name),
                    "initial": _initial_avatar(name),
                    #: 限定判定和旧界面同一个函数（不是自己写的名单）
                    "isLimited": _safe(lambda n=name, k=kind: gacha.is_limited(n, k),
                                       False),
                })

            # ---- 分卡池（旧界面 _build_pool_tabs 只列抽过的池）----
            pools: list[dict] = []
            for pool in report.active_pools():
                pool_avg = pool.average()
                pool_luck = pool.luck()
                pools.append({
                    "poolType": str(pool.pool_type),
                    "name": pool.name,
                    "pulls": int(pool.total),
                    "five": int(pool.five_count),
                    "rate": round(pool.rate(), 2),
                    #: 平均出金（旧界面每池也显示）
                    "avgFive": round(pool_avg, 1) if pool_avg else None,
                    #: 当前保底计数（"还剩多少抽大保底"）
                    "pity": int(_safe(lambda p=pool: p.pity_count(), 0)),
                    "rank": pool_luck[0] if pool_luck else None,
                    #: 是否限定池（前端决定要不要显示"不歪率"）
                    "isLimitedPool": bool(pool.is_limited_pool),
                })

            return _json({
                "ok": True,
                "total": int(report.total),
                #: ★ 和旧界面一样的格式化口径：平均出金取整、不歪率一位小数
                "avgFive": round(average, 1) if average else None,
                "noLoseRate": round(not_up, 1) if not_up is not None else None,
                "five": int(report.five_count),
                "perChar": round(per_char, 1) if per_char else None,
                "perWeapon": round(per_weapon, 1) if per_weapon else None,
                "rank": luck[0] if luck else None,
                "summary": {
                    "limited": len(limited),
                    "standard": len(permanent),
                    "standardNames": list(permanent),
                    #: 旧界面那句话，直接给（页面不用自己拼）
                    "note": (
                        f"共获得限定五星 {len(limited)} 个，"
                        f"常驻五星 {len(permanent)} 个。"
                        + (f"（常驻：{'、'.join(permanent)}）"
                           if permanent else "")
                    ),
                },
                "cards": cards,
                "pools": pools,
                #: 这些是"这份统计来自哪儿"，页面显示在状态行
                "playerId": who,
                "accountLabel": _safe(
                    lambda: gacha_store.account_label(who), who),
                "recordCount": len(rows),
            })
        except Exception:  # noqa: BLE001
            logger.warning("getGachaOverview 失败", exc_info=True)
            return _json({"ok": False, "reason": "error",
                          "message": "读本地抽卡统计失败，详见日志"})

    @Slot(result=str)
    def getGachaHistory(self) -> str:
        """抽卡历史（按 **账号 × 年月** 聚合，对齐旧界面）。

        返回 ``{ok, items: [...], players: [...], count}``。

        每条：

        .. code:: json

            {"playerId": "137856011",
             "yearMonth": "2026-10",
             "monthText": "2026年10月",   // ← 用户要的格式
             "total": 960, "five": 21,
             "latestAt": "2026-10-14 21:07:33",
             "snapshots": 1}

        ## 为什么要聚合而不是逐条列快照

        用户 2026-10-28：

        > 这里历史记录按时间和账号维度统计……时间显示格式为 xxxx年xx月

        逐条列的话同一个号一个月拉 20 次就是 20 行噪音。
        聚合规则见 :func:`src.core.gacha_history_view.group_by_account_month`
        —— **后端不重复实现，直接调它**。
        """
        try:
            from . import gacha_store  # noqa: PLC0415
            from .gacha_history_view import group_by_account_month  # noqa: PLC0415

            #: ⚠ 用 ``load()`` 不用 ``load_and_repair()`` —— 后者会**写盘**，
            #: 而"读历史列表"不该改用户数据（见 GachaHistoryStore.load 文档里
            #: 那个"读的时候偷偷写盘"的坑）。
            history = self._gacha_store().load()
            snapshots = list(getattr(history, "snapshots", []) or [])
            months = group_by_account_month(snapshots)
        except Exception:  # noqa: BLE001
            logger.warning("getGachaHistory 失败", exc_info=True)
            return _json({"ok": False, "reason": "error",
                          "message": "读抽卡历史失败，详见日志"})

        items = [{
            "playerId": str(m.player_id),
            "yearMonth": str(m.year_month),
            "monthText": m.month_text,
            "total": int(m.total),
            "five": int(m.five),
            "latestAt": str(m.latest_at),
            "snapshots": int(m.snapshots),
        } for m in months]

        #: 账号去重列表（页面可能要按账号筛选）
        players: list[str] = []
        for item in items:
            if item["playerId"] and item["playerId"] not in players:
                players.append(item["playerId"])

        return _json({
            "ok": True,
            "items": items,
            "players": players,
            "count": len(items),
            #: 原始快照条数（诊断用：聚合前有多少条）
            "snapshotCount": len(snapshots),
        })

    #: ``clearGachaHistory`` 要求调用方回传的确认令牌。
    #:
    #: ★★ 2026-11-02（lead 要求）：**后端强制确认，不只靠前端弹窗**。
    #:
    #: 清空抽卡历史是**不可逆**的（用户可能积累了几千条、多个账号）。
    #: 前端加二次确认是好习惯，但**前端可以被绕过**：
    #:
    #: * 页面脚本出错 / 用户手滑点了别处
    #: * 有人从控制台直接 ``Bridge.call('clearGachaHistory')``
    #: * 将来别的前端接这套桥（脚本化调用）
    #:
    #: 所以后端也拦一道：不传令牌 → 只返回 ``needs_confirm`` + 当前会删多少条，
    #: **一个字节都不写**。传了令牌才真清。
    _GACHA_CLEAR_TOKEN = "DELETE"

    @Slot(str, result=str)
    def clearGachaHistory(self, confirm_token: str = "") -> str:
        """清空抽卡历史（**破坏性、不可逆**）。

        ## ⚠⚠ 必须显式确认（2026-11-02，lead 要求）

        调用方要传 ``confirm_token="DELETE"`` 才真的清空。不传时**什么都不写**：

        .. code:: json

            // 没传令牌
            {"ok": false, "reason": "needs_confirm", "pending": 2,
             "message": "清空后无法恢复（当前 2 条历史）。确认请传 confirm_token='DELETE'"}

            // 传了
            {"ok": true, "cleared": 2}

            // 本来就没有
            {"ok": true, "cleared": 0, "message": "本来就没有历史记录"}

        **为什么后端还要拦**：前端弹窗是好习惯，但前端可以被绕过
        （脚本出错、控制台直接调、将来别的前端接这套桥）。
        清空不可逆，多一道保险值得。

        :param confirm_token: 必须正好是 ``"DELETE"``
        """
        try:
            from . import gacha_store  # noqa: PLC0415

            store = self._gacha_store()
            history = store.load()
            before = len(list(getattr(history, "snapshots", []) or []))

            #: ★ 没确认 → 只报告、不写入
            if str(confirm_token or "").strip() != self._GACHA_CLEAR_TOKEN:
                if before == 0:
                    return _json({"ok": True, "cleared": 0,
                                  "message": "本来就没有历史记录，无需清空"})
                logger.info(
                    "WebBridge：请求清空抽卡历史但未确认（%d 条），已拒绝",
                    before)
                return _json({
                    "ok": False,
                    "reason": "needs_confirm",
                    "pending": before,
                    "message": (f"清空后**无法恢复**（当前 {before} 条历史）。"
                                f"确认请传 confirm_token='DELETE'"),
                })

            #: 存一个空历史 —— 和旧界面同一个做法
            store.save(gacha_store.GachaHistory())
            logger.info("WebBridge：抽卡历史已清空（%d 条快照）", before)
            return _json({"ok": True, "cleared": before})
        except Exception as exc:  # noqa: BLE001
            logger.warning("clearGachaHistory 失败", exc_info=True)
            return _json({"ok": False, "reason": "error",
                          "message": f"{type(exc).__name__}: {exc}"})

    # ================================================ 角色练度缓存（P4 第三批）
    #
    # 「查询角色练度」工具是**只读展示**：数据由 Qt 版登录拉取后存在
    # ``data/kuro_练度.json``。Web 面板不需要登录，读缓存即可。
    #
    # ⚠ Web 版**不做登录**（那要手机号 + 验证码 + 风控，且用户明确
    # 只要求"读缓存"）。缓存没有就明确告诉用户去旧界面登录一次。

    @Slot(result=str)
    def kuroLogout(self) -> str:
        """★ 退出库街区登录（2026-11-03 补）。

        ## 用户要求

        > 退出登录怎么不能点？

        之前 Web 版把「退出登录」**禁用**了，理由是"会破坏旧界面保存的
        登录态"。但那只是**保守**，不是事实约束 —— 登出本就是用户的
        合法操作，旧界面也一直是可点的。

        ## 做什么（照抄旧界面 ``_on_logout``）

        .. code:: python

            kuro_account.clear_account()   # 删令牌文件
            clear_cache()                  # 删 kuro_练度.json
            self._account = Account()      # 重新读（变成未登录）
            self._data = {}
            self._render({})               # 清空页面
            self._say("已退出登录（令牌 + 缓存都已删除）")

        ⚠ **删缓存是故意的** —— 旧界面就这么做，而且登出后缓存里的
        角色数据已经没有归属，留着只会让用户以为还登着。

        :return: ``{ok, cleared: bool, message}
        """
        try:
            from . import kuro_account  # noqa: PLC0415
            from . import paths  # noqa: PLC0415

            cleared_token = False
            cleared_cache = False
            try:
                kuro_account.clear_account()
                cleared_token = True
            except Exception:  # noqa: BLE001 - 删不掉也要继续清缓存
                logger.warning("kuroLogout：删令牌失败", exc_info=True)

            try:
                cache_file = paths.user_data_dir() / "kuro_练度.json"
                if cache_file.is_file():
                    cache_file.unlink()
                    cleared_cache = True
            except Exception:  # noqa: BLE001
                logger.warning("kuroLogout：删缓存失败", exc_info=True)

            logger.info("已退出登录（令牌=%s 缓存=%s）",
                        cleared_token, cleared_cache)
            return _json({
                "ok": True,
                "clearedToken": cleared_token,
                "clearedCache": cleared_cache,
                "message": "已退出登录（令牌 + 缓存都已删除）",
            })
        except Exception as exc:  # noqa: BLE001
            logger.warning("kuroLogout 失败", exc_info=True)
            return _json({"ok": False, "reason": "error",
                          "message": f"{type(exc).__name__}: {exc}"})

    @Slot(result=str)
    def getCharacterBuildCache(self) -> str:
        """读角色练度缓存（**只读，不登录**）。

        返回 ``{ok, updatedAt, role, characters: [...], standards, details}``；
        没有缓存时 ``{ok: false, reason: "no_cache", message: "…"}``。

        ## 为什么只给 ``roleList`` 精简版 + 原始 details

        ``kuro_练度.json`` 有 **1.2 MB**，整个给页面太重。
        所以：

        * ``characters`` —— 从 ``roleList`` 抽出的精简列表（名字/等级/星级/
          头像 URL），页面画卡片列表够用
        * ``details`` / ``standards`` —— 原始 dict **按需**再取
          （页面点开某个角色时才需要，走 :meth:`getCharacterBuildDetail`）
        """
        try:
            from . import paths  # noqa: PLC0415

            cache_file = paths.user_data_dir() / "kuro_练度.json"
            if not cache_file.is_file():
                return _json({
                    "ok": False, "reason": "no_cache",
                    "message": "还没有角色练度数据。请先用旧界面"
                               "（MYTOOLS_WEB_SHELL=0）登录一次「查询角色练度」，"
                               "登录后这里会自动读到缓存。",
                })

            raw = json.loads(cache_file.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("getCharacterBuildCache 失败", exc_info=True)
            return _json({"ok": False, "reason": "error",
                          "message": f"{type(exc).__name__}: {exc}"})

        if not isinstance(raw, dict):
            return _json({"ok": False, "reason": "bad_cache",
                          "message": "缓存格式不对"})

        role = raw.get("role") if isinstance(raw.get("role"), dict) else {}
        role_list = raw.get("roleList") if isinstance(raw.get("roleList"), list) \
            else []

        characters: list[dict] = []
        #: ★★★ 2026-11-03 **算出「这个角色有没有不达标项」**（flagged）
        #:
        #: ## 为什么必须后端算
        #:
        #: 页面原来只拿到 ``detailIds``（"有没有详情数据"），于是把
        #: 「有数据」当成「达标」—— 用户圈图：
        #:
        #:   「筛选逻辑有问题，未达标，怎么进入达标里了？」
        #:
        #: 千咲 暴击 41.3% / 推荐 ≥75%，明明是**未达标**，
        #: 但因为"有数据"就被塞进了「达标」分类。
        #:
        #: ## 判定规则（照抄旧界面 ``tool.py`` L1101-1136 的语义）
        #:
        #: ``standards[roleId].attrs`` 里每项有 ``value``（推荐值）和
        #: ``symbol``（``≥`` / ``≤`` / ``=``）；拿
        #: ``details[roleId].roleAttributeList`` 里**同名属性**的当前值比，
        #: 任一不满足就算 flagged。
        #:
        #: ⚠ 两个必须注意的点（前端已经各踩过一次）：
        #:   ① 当前值是**带百分号的字符串**（``'41.3%'``）——
        #:      直接 ``float()`` 会炸，要剥掉 ``%``
        #:   ② 属性名两边**必须完全一致**才配上（「暴击」对「暴击」）
        flagged: dict[str, list[str]] = {}
        details_raw = raw.get("details") if isinstance(
            raw.get("details"), dict) else {}
        standards_raw = raw.get("standards") if isinstance(
            raw.get("standards"), dict) else {}

        def _num(value) -> float | None:
            """``'41.3%'`` / ``41.3`` / ``'1700'`` → float；转不了给 None。"""
            if value is None:
                return None
            if isinstance(value, (int, float)):
                return float(value)
            text = str(value).replace("%", "").strip()
            if not text:
                return None
            try:
                return float(text)
            except ValueError:
                return None

        for rid, detail in details_raw.items():
            if not isinstance(detail, dict):
                continue
            std = standards_raw.get(rid)
            std_attrs = std.get("attrs") if isinstance(std, dict) else None
            if not isinstance(std_attrs, list) or not std_attrs:
                continue
            current: dict[str, float] = {}
            for item in (detail.get("roleAttributeList") or []):
                if not isinstance(item, dict):
                    continue
                nm = str(item.get("attributeName") or "").strip()
                val = _num(item.get("attributeValue"))
                if nm and val is not None:
                    current[nm] = val

            issues: list[str] = []
            for attr in std_attrs:
                if not isinstance(attr, dict):
                    continue
                nm = str(attr.get("name") or "").strip()
                if not nm:
                    continue
                need = _num(attr.get("value"))
                have = current.get(nm)
                #: 面板里没这个属性 → **不算不达标**（旧界面也这么处理）
                if need is None or have is None:
                    continue
                symbol = str(attr.get("symbol") or "≥")
                if symbol == "≤":
                    passed = have <= need
                elif symbol == "=":
                    passed = abs(have - need) < 1e-9
                else:
                    passed = have >= need
                if not passed:
                    #: ⚠ 文案里**不要**用 ``attr['current']`` —— 那个字段
                    #: 后端恒为 ``'0'`` / ``'0.0%'``（没人回填），
                    #: 写进文案就成了「暴击 0.0% 没到 ≥75%」，
                    #: 而真实值是 41.3%（实测踩到）。
                    #: 用我们自己从 ``roleAttributeList`` 取到的当前值。
                    have_text = f"{have:g}"
                    if "%" in str(attr.get("recommend") or ""):
                        have_text += "%"
                    issues.append(
                        f"{nm} {have_text} 没到 "
                        f"{symbol}{attr.get('recommend') or need}")
            if issues:
                flagged[str(rid)] = issues

        for item in role_list:
            if not isinstance(item, dict):
                continue
            rid = str(item.get("roleId") or "")
            characters.append({
                "roleId": rid,
                "name": str(item.get("roleName") or item.get("name") or ""),
                "level": item.get("level") or 0,
                "star": item.get("star") or item.get("quality") or 0,
                "attribute": str(item.get("attributeName") or ""),
                "attributeId": item.get("attributeId") or 0,
                "weaponType": str(item.get("weaponTypeName") or ""),
                "chain": item.get("chainUnlockNum") or 0,
                #: 方形头像（96×96 那种）
                "iconUrl": str(item.get("roleIconUrl") or ""),
                #: ★★ 立绘（竖长，旧界面角色卡 TILE_W=96 / TILE_H=132 用的就是它）
                #:
                #: ⚠ 这是**库街区 CDN 的远程 URL**（web-static.kurobbs.com），
                #: 不是本地文件 —— 页面直接 ``<img src>`` 即可，不用 media_server。
                "picUrl": str(item.get("rolePicUrl") or ""),
                #: ★ 不达标项明细（空数组 = 达标）
                "issues": flagged.get(rid, []),
                "flagged": rid in flagged,
                #: ★★★ 2026-11-03 角色搜索要**支持拼音**（用户：
                #: 「所有的角色搜索都按照这样做」）。
                #:
                #: 拼音靠 ``pypinyin``（Python 包）算，**JS 侧算不出来** ——
                #: 所以必须在这里给：``[全拼, 首字母]``，如绯雪 →
                #: ``["feixue", "fx"]``。规则和配置页 / 弹框下拉**同一份**
                #: （:func:`src.core.text_match.pinyin_keys`）。
                #:
                #: ⚠ 用户在练度页打 ``fx`` 找不到角色的原因就是这个字段
                #:   缺失 —— 前端 ``match()`` 只能退化成中文子串。
                "pinyin": list(pinyin_keys(
                    str(item.get("roleName") or item.get("name") or ""))),
            })

        #: ★★★ 账号概览（旧界面 ②「账号概览」那行 6 项）
        #:
        #: 数据在 ``kuro_练度.json`` 的 ``base`` 里，**都在**，只是之前没返回。
        #: 旧界面显示成「结晶波片 89/240」这种「当前/上限」形式。
        base = raw.get("base") if isinstance(raw.get("base"), dict) else {}
        _b = base or {}

        return _json({
            "ok": True,
            "updatedAt": str(raw.get("at") or ""),
            "nickname": str(role.get("nickName") or role.get("name") or ""),
            "level": role.get("gameLevel") or 0,
            "uid": str(role.get("gameId") or ""),
            #: ★ 账号概览：6 项，字段名和库街区一致（页面按 key 取）
            "base": {
                #: 结晶波片（体力）：89 / 240
                "energy": _b.get("energy") or 0,
                "maxEnergy": _b.get("maxEnergy") or 0,
                #: 结晶单质（存储体力）：61 / 480
                "storeEnergy": _b.get("storeEnergy") or 0,
                "storeEnergyLimit": _b.get("storeEnergyLimit") or 0,
                #: 活跃度：100 / 100
                "liveness": _b.get("liveness") or 0,
                "livenessMaxCount": _b.get("livenessMaxCount") or 0,
                #: 游戏天数
                "activeDays": _b.get("activeDays") or 0,
                #: 联觉等级
                "level": _b.get("level") or 0,
                #: 解锁角色数
                "roleNum": _b.get("roleNum") or 0,
                #: 世界等级 / 成就（旧界面也显示了，一并给）
                "worldLevel": _b.get("worldLevel") or 0,
                "achievementCount": _b.get("achievementCount") or 0,
                #: 昵称（base 里也有，比 role 的更可靠）
                "name": str(_b.get("name") or ""),
                #: 结晶单质的显示名（库街区给的是「结晶单质」）
                "storeEnergyTitle": str(_b.get("storeEnergyTitle") or ""),
                #: 结晶单质的图标（远程 CDN URL）
                "storeEnergyIconUrl": str(_b.get("storeEnergyIconUrl") or ""),
            },
            #: ★ 登录卡数据（Web 版做不了登录，但**照抄外观**）
            #:
            #: ⚠ 手机号来自 ``kuro_account.json``，**脱敏**后再给页面
            #: （只留后 4 位，和旧界面那种全显示不同 —— lead 要求更安全）
            "loginInfo": self._kuro_login_info(role),
            "characters": characters,
            "count": len(characters),
            #: 原始数据按需再取（1.2 MB 不一次塞给页面）
            "hasDetails": isinstance(raw.get("details"), dict),
            "detailIds": sorted((raw.get("details") or {}).keys()),
        })

    def _kuro_login_info(self, role: dict) -> dict:
        """登录卡数据（Web 版做不了登录，但**照抄外观**）。

        旧界面 ① 登录卡显示：特征码 / 手机号 / 验证码。

        Web 版不可能做登录（要手机号 + 短信验证码 + 库街区风控），
        所以这里只给"当前是哪个号"，页面对应控件**置灰**。

        ## ⚠ 手机号只给后 4 位

        ``kuro_account.json`` 里存的是 ``mobile_tail``（**本来就只有 4 位**，
        完整号码从来没落过盘）—— 这里原样给，页面显示成 ``****6241``。

        比旧界面更安全：旧界面那时是全显示的，但 Web 版没有理由把
        完整号码带进前端（前端可被查看、可被截图）。

        :return: ``{gameId, roleId, nickname, phoneTail, phoneMasked,
                    loggedIn, loginAt}``
        """
        info: dict = {
            "gameId": "", "roleId": "", "nickname": "",
            "phoneTail": "", "phoneMasked": "", "loggedIn": False,
            "loginAt": "",
        }
        try:
            info["roleId"] = str(role.get("roleId") or "")
            info["nickname"] = str(role.get("roleName") or "")
            #: ``role.gameId`` 是**游戏内特征码**（旧界面那串数字）
            info["gameId"] = str(role.get("roleId") or "")
        except Exception:  # noqa: BLE001
            pass

        try:
            from . import paths  # noqa: PLC0415

            account_file = paths.user_data_dir() / "kuro_account.json"
            if not account_file.is_file():
                return info
            account = json.loads(account_file.read_text(encoding="utf-8"))
            if not isinstance(account, dict):
                return info

            tail = str(account.get("mobile_tail") or "").strip()
            info["phoneTail"] = tail
            info["phoneMasked"] = f"****{tail}" if tail else ""
            #: 有 token 才算"登录过"（没 token 就是缓存里残留的旧数据）
            info["loggedIn"] = bool(account.get("token"))
            login_at = account.get("login_at")
            if login_at:
                import datetime  # noqa: PLC0415

                try:
                    info["loginAt"] = datetime.datetime.fromtimestamp(
                        float(login_at)).strftime("%Y-%m-%d %H:%M")
                except (TypeError, ValueError, OSError):
                    info["loginAt"] = ""
        except Exception:  # noqa: BLE001 - 登录信息读不到不该拖垮整页
            logger.debug("读 kuro_account 失败", exc_info=True)

        return info

    @Slot(str, result=str)
    def getCharacterBuildDetail(self, role_id: str) -> str:
        """取某个角色的详细练度（``details[roleId]`` + ``standards[roleId]``）。

        :param role_id: ``getCharacterBuildCache`` 里 ``characters[].roleId``

        页面点开某个角色时才调 —— 单条数据几十 KB，比整个 1.2 MB 好得多。
        """
        role_id = str(role_id or "").strip()
        if not role_id:
            return _json({"ok": False, "reason": "empty",
                          "message": "没给 roleId"})
        try:
            from . import paths  # noqa: PLC0415

            cache_file = paths.user_data_dir() / "kuro_练度.json"
            if not cache_file.is_file():
                return _json({"ok": False, "reason": "no_cache",
                              "message": "还没有角色练度数据"})
            raw = json.loads(cache_file.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("getCharacterBuildDetail 失败", exc_info=True)
            return _json({"ok": False, "reason": "error",
                          "message": f"{type(exc).__name__}: {exc}"})

        if not isinstance(raw, dict):
            return _json({"ok": False, "reason": "bad_cache",
                          "message": "缓存格式不对"})
        details = raw.get("details") if isinstance(raw.get("details"), dict) else {}
        standards = raw.get("standards") if isinstance(
            raw.get("standards"), dict) else {}
        if role_id not in details and role_id not in standards:
            return _json({
                "ok": False, "reason": "not_found",
                "message": f"缓存里没有 roleId={role_id} 的详情",
                "available": sorted(set(details) | set(standards)),
            })
        return _json({
            "ok": True,
            "roleId": role_id,
            "detail": details.get(role_id),
            "standard": standards.get(role_id),
        })

    # ================================================ 扫荡残像聚落（P4 第二批）
    #
    # ★ ``nest_sweep`` 的勾选**不能**只靠 getToolSettings 读：
    #
    # 1. 原始值只是 ``{"selected": [key, ...]}``，而页面要**完整目标卡**
    #    （名字/区域/每日次数/能出哪些套装/版本/待核对角标）
    # 2. ``load_selection()`` 会**过滤失效 key**（清单更新后老勾选会失效）——
    #    这个过滤逻辑不该让页面重写一遍
    #
    # 所以直接调 ``core.nest_sweep`` 的现成函数，和 Qt 版工具页走同一条路。

    @Slot(result=str)
    def getNestSweepData(self) -> str:
        """扫荡清单 + 当前勾选。

        返回 ``{ok, targets: [...], selected: [key], count, summary}``。

        ## ⚠ 两个容易写错的字段

        * ``sets`` —— **空数组 = 不知道**（不是"这什么都不掉"）。
          页面别画"0 套"，直接不画那一条。
        * ``verified: false`` —— 名字没核对过，Qt 版显示「待核对」角标。
        """
        try:
            from .nest_sweep import load_catalog, load_selection  # noqa: PLC0415

            targets = load_catalog()
            selected = list(load_selection(targets))
        except Exception:  # noqa: BLE001
            logger.warning("getNestSweepData 失败", exc_info=True)
            return _json({"ok": False, "reason": "error",
                          "message": "读扫荡清单失败，详见日志"})

        items: list[dict] = []
        for t in targets:
            items.append({
                "key": str(getattr(t, "key", "")),
                "name": str(getattr(t, "name", "")),
                "kind": str(getattr(t, "kind", "")),
                "kindName": ("梦魇残像"
                             if str(getattr(t, "kind", "")) == "nightmare"
                             else "残像聚落"),
                "region": str(getattr(t, "region", "")),
                "count": int(getattr(t, "count", 0) or 0),
                "version": str(getattr(t, "version", "")),
                #: ⚠ 空 = 不知道（不是"没有"）
                "sets": list(getattr(t, "sets", ()) or ()),
                "verified": bool(getattr(t, "verified", True)),
                "order": int(getattr(t, "order", 0) or 0),
                "aliases": list(getattr(t, "aliases", ()) or ()),
            })

        return _json({
            "ok": True,
            "targets": items,
            "selected": selected,
            "count": len(items),
            "summary": "已选 %d 个" % len(selected),
        })

    @Slot(str, result=str)
    def setNestSweepSelection(self, payload: str) -> str:
        """保存扫荡勾选。

        ``payload`` = JSON ``{"selected": ["key1", ...]}``（也接受裸数组）。

        ## ⚠ 必须把**清洗后**的结果回给页面

        ``save_selection()`` 内部跑 ``clean_selection()``，会**过滤掉清单里
        不存在的 key**。清单更新过之后，用户之前勾的 key 可能已失效。

        不回清洗结果的话，页面显示"勾着 5 个"而实际只存了 3 个 ——
        用户点运行只跑 3 个，怎么数都对不上。
        """
        try:
            data = json.loads(payload or "null")
        except (TypeError, ValueError):
            return _json({"ok": False, "reason": "bad_json",
                          "message": "payload 不是合法 JSON"})
        raw = data.get("selected") if isinstance(data, dict) else data
        if not isinstance(raw, (list, tuple)):
            return _json({"ok": False, "reason": "bad_data",
                          "message": "selected 必须是数组"})

        try:
            from .nest_sweep import load_catalog, save_selection  # noqa: PLC0415
            from .nest_sweep.plan import clean_selection  # noqa: PLC0415

            targets = load_catalog()
            cleaned = list(clean_selection(raw, targets))
            save_selection(cleaned, targets)
        except Exception as exc:  # noqa: BLE001
            logger.warning("setNestSweepSelection 失败", exc_info=True)
            return _json({"ok": False, "reason": "error",
                          "message": f"{type(exc).__name__}: {exc}"})

        cleaned_set = set(cleaned)
        dropped = [str(k) for k in raw if k not in cleaned_set]
        if dropped:
            logger.info("WebBridge：扫荡勾选丢弃 %d 个失效 key", len(dropped))
        return _json({
            "ok": True,
            "selected": cleaned,
            "dropped": dropped,
            "summary": "已选 %d 个" % len(cleaned),
            "message": (f"{len(dropped)} 个勾选项已失效（清单更新过？），"
                        f"已自动去掉" if dropped else ""),
        })

    def _log_library(self, text: str, level: str = "info") -> None:
        """资源库日志：同时进文件日志和页面（对齐 Qt 版 ``_append_log``）。"""
        logger.info("[资源库] %s", text)
        self.pushLog(text, level)

    # ================================================================ 皮肤
    @Slot(result=str)
    def getSkin(self) -> str:
        """当前皮肤配色 → ``{primary, dim, text, bg, card, border, mode, id, name}``。

        ## ``bg`` 的特殊处理

        ``skins.active_skin()["bg"]`` 是一个 **QSS 渐变字符串**：

        .. code:: text

            [(0.0, '#0C0A18'), (0.5, '#141026'), (1.0, '#090713')]

        JS 那边要的是能给 CSS 用的值，所以这里转成 ``css`` 字段
        （``linear-gradient(...)``），原值也一起给，方便调试。
        """
        payload: dict = {
            "id": "", "name": "", "mode": "dark",
            "primary": "#8B7CFF", "dim": "#9A93C4", "text": "#ECE9FF",
            "bg": "#0C0A18", "css": "", "card": "", "border": "",
        }
        try:
            from ..core import skins  # noqa: PLC0415

            skin = skins.active_skin()
            payload.update({
                "id": skin.get("id", ""),
                "name": skin.get("name", ""),
                "mode": skin.get("mode", "dark"),
                "primary": skin.get("primary", payload["primary"]),
                "dim": skin.get("dim", payload["dim"]),
                "text": skin.get("text", payload["text"]),
                "card": skin.get("card", ""),
                "border": skin.get("border", ""),
            })
            stops = _parse_gradient(skin.get("bg", ""))
            if stops:
                payload["bg"] = stops[0][1]
                payload["css"] = _gradient_css(stops)
        except Exception:  # noqa: BLE001 - 皮肤系统坏了也要能起界面
            logger.warning("getSkin 失败，用默认配色", exc_info=True)
        return _json(payload)

    @Slot(result=str)
    def getSkinList(self) -> str:
        """所有可选皮肤（皮肤页用）。

        ## ⚠ ``bg`` 必须给（2026-11-01，page-converter 报的）

        皮肤页要画**配色预览条**（主色 + 背景两段色块）。
        第一版只返回 ``primary`` 没返回 ``bg`` —— 预览条永远只有一半，
        而且不报错，只是「看着怪」。现在和 :meth:`getSkin` 口径一致：
        给 ``bg``（首个渐变色）+ ``css``（完整渐变），页面按需用。
        """
        out: list[dict] = []
        try:
            from ..core import skins  # noqa: PLC0415

            for skin in skins.all_skins():
                stops = _parse_gradient(skin.get("bg", ""))
                out.append({
                    "id": skin.get("id", ""),
                    "name": skin.get("name", ""),
                    "desc": skin.get("desc", ""),
                    "mode": skin.get("mode", "dark"),
                    "primary": skin.get("primary", ""),
                    #: ★ 补上：预览条的第二段颜色 + 完整渐变
                    "bg": stops[0][1] if stops else "",
                    "css": _gradient_css(stops),
                    "card": skin.get("card", ""),
                    "border": skin.get("border", ""),
                    "text": skin.get("text", ""),
                    "dim": skin.get("dim", ""),
                })
        except Exception:  # noqa: BLE001
            logger.warning("getSkinList 失败", exc_info=True)
        return _json(out)

    @Slot(str, result=str)
    def setSkin(self, skin_id: str) -> str:
        """切换主题皮肤（写操作，2026-11-01 给 page-converter）。

        ## 做什么

        调 ``skins.apply_skin(id, save=True)`` —— 和 Qt 版皮肤页完全同一条
        路径（会重刷 QSS、存盘、切换明暗主题）。然后广播 ``skinChanged``，
        页面收到就用新配色重刷 CSS 变量。

        ## ⚠ 为什么必须走 ``skins.apply_skin`` 而不是只改 CSS 变量

        皮肤不只影响颜色 —— 它还决定 **深色/浅色主题**（``mode``），
        而玻璃的「可读性下限」正是按明暗取的（0.59 / 0.45）。
        只改 CSS 变量的话，切到浅色皮肤后玻璃下限还是深色那档，
        文字对比度会不对。

        ``save=True`` 是为了**重开程序还是这个皮肤**（和 Qt 版一致）。

        :return: ``{ok, id, skin}``；``skin`` 是新配色（供页面立即应用）
        """
        skin_id = (skin_id or "").strip()
        if not skin_id:
            return _json({"ok": False, "reason": "empty"})
        try:
            from ..core import skins  # noqa: PLC0415

            if skins.skin_by_id(skin_id) is None:
                return _json({"ok": False, "reason": "not_found",
                              "id": skin_id})

            ok = bool(skins.apply_skin(skin_id, save=True))
            if not ok:
                return _json({"ok": False, "reason": "apply_failed",
                              "id": skin_id})

            #: 让页面拿到新配色（pushSkin 内部会 emit skinChanged）
            payload = json.loads(self.getSkin())
            self.pushSkin()
            logger.info("WebBridge：已切换皮肤 %s", skin_id)
            return _json({"ok": True, "id": skin_id, "skin": payload})
        except Exception:  # noqa: BLE001
            logger.warning("setSkin 失败 %s", skin_id, exc_info=True)
            return _json({"ok": False, "reason": "error", "id": skin_id})

    # ================================================================ 壁纸
    @Slot(result=str)
    def getWallpaper(self) -> str:
        """当前壁纸 + 全部可用壁纸。

        返回 ``{id, title, url, items: [{id, title, url, supported}]}``。

        ⚠ ``url`` 是 **HTTP URL**（``media_server``），不是文件路径 ——
        见 :mod:`src.core.media_server` 模块文档：``file://`` 会被同源策略拦。
        """
        payload = {"id": "", "title": "", "url": "", "items": []}
        try:
            items = self._scan_wallpapers()
            payload["items"] = items
            if items:
                current = self._pick_current(items)
                payload.update({
                    "id": current.get("id", ""),
                    "title": current.get("title", ""),
                    "url": current.get("url", ""),
                })
                self._wallpaper_id = payload["id"]
        except Exception:  # noqa: BLE001
            logger.warning("getWallpaper 失败", exc_info=True)
        return _json(payload)

    @Slot(str, result=str)
    def setWallpaper(self, wp_id: str) -> str:
        """切换壁纸 → 返回 ``{ok, id, title, url}``。

        页面收到之后自己换 ``<video src>``（本模块只负责解析出 URL）。
        """
        wp_id = (wp_id or "").strip()
        if not wp_id:
            return _json({"ok": False, "reason": "empty"})
        try:
            items = self._scan_wallpapers()
            target = next((x for x in items if x.get("id") == wp_id), None)
            if target is None:
                return _json({"ok": False, "reason": "not_found", "id": wp_id})
            self._wallpaper_id = wp_id
            payload = {
                "ok": True,
                "id": target.get("id", ""),
                "title": target.get("title", ""),
                "url": target.get("url", ""),
            }
            self.wallpaperChanged.emit(_json(payload))
            self.emitEvent("wallpaperChanged", payload)
            logger.info("WebBridge：切壁纸 → %s", target.get("title"))
            return _json(payload)
        except Exception:  # noqa: BLE001
            logger.warning("setWallpaper 失败", exc_info=True)
            return _json({"ok": False, "reason": "error"})

    # ================================================================ 业务数据
    #
    # ★ 下面三个是 2026-11-01 给 page-converter（P2 页面转换）加的。
    #
    # 原则：**只做序列化，不重写业务逻辑**。数据全从 ``src/core/`` 读，
    # 页面拿到的结构跟 Qt 版界面拿到的完全一致 —— 两边行为不会分叉。
    #
    # ⚠ 所有图标都给成 **HTTP URL**（``/game/<子目录>/<文件名>``）。
    #   ``assets/game/`` 只挂了 4 个白名单子目录（见
    #   ``src.gui.web_shell.GAME_ASSET_SUBDIRS``），路径里的中文要
    #   percent-encode —— 见 :func:`_game_icon_url`。

    @Slot(result=str)
    def getFlowList(self) -> str:
        """任务流程列表（``core.tasks.TaskStore.all()``）。

        返回 ``[{id, name, summary, liveSummary, avatarUrl, typeText,
        updatedAt, steps: [...], stepCount, toolCount, errors: [...]}]``。

        ``steps`` 直接给 ``TaskStep.to_dict()`` —— 编排界面 P2 要用。

        ## ★ 2026-11-03：补 ``avatarUrl`` / ``liveSummary``（按 main 分支重做任务页）

        用户圈图：「删掉，任务请按 main 分支那样做」。main 分支
        （``src/gui/tasks_interface.py`` 的 ``TaskRowCard``）的行卡是

        .. code:: text

            [角色头像 48px] 名字
                            步骤摘要（配置那几步用**当前**名字）
                            状态（空闲 / 运行中 / 完成 / 已停止）

        这两个字段就是给那个布局准备的：

        * ``avatarUrl`` ← ``config_names.live_flow_avatar(flow)``
          （流程名 = 角色 + 后缀，剥掉后缀去 ``game_data`` 查头像）。
          **取不到给空串**（不画占位图，和 Qt 版一个态度）。
        * ``liveSummary`` ← ``config_names.live_flow_summary(flow)``
          （配置步骤显示**当前**名字，不是步骤里存的那份快照 ——
          用户 2026-09-26「每次从配置读最新名字」）。

        ``summary`` 保留原样（纯逻辑版，只用步骤快照）—— 有人可能还想用。
        """
        out: list[dict] = []
        try:
            from ..core.tasks import TaskStore  # noqa: PLC0415
            from ..gui import config_names  # noqa: PLC0415 - 只在读列表时用

            store = TaskStore()
            for flow in store.all():
                try:
                    data = flow.to_dict()
                except Exception:  # noqa: BLE001 - 单条坏了不该中断整表
                    logger.debug("getFlowList：流程转换失败 %s", flow.id,
                                 exc_info=True)
                    data = {}
                tool_steps = [s for s in flow.steps if s.is_tool]
                out.append({
                    "id": flow.id,
                    "name": flow.name,
                    "summary": _safe(lambda: flow.summary(), ""),
                    #: ★ 配置步骤用当前名字的摘要（行卡第二行用它）
                    "liveSummary": _safe(
                        lambda f=flow: config_names.live_flow_summary(f), ""),
                    #: ★ 行卡左侧的角色头像（空串 = 画不了，页面留等宽空位）
                    "avatarUrl": _safe(
                        lambda f=flow: self._safe_icon_url(
                            config_names.live_flow_avatar(f)), ""),
                    "typeText": _safe(lambda: flow.type_text(), ""),
                    "updatedAt": flow.updated_at,
                    "stepCount": len(flow.steps),
                    "toolCount": len(tool_steps),
                    #: 校验错误：页面据此标"这条流程有问题"
                    "errors": _safe(lambda: flow.validate(), []),
                    "steps": data.get("steps") or [s.to_dict()
                                                   for s in flow.steps],
                })
        except Exception:  # noqa: BLE001
            logger.warning("getFlowList 失败", exc_info=True)
        return _json(out)

    @Slot(result=str)
    def getConfigList(self) -> str:
        """配置列表 = **声骸配置** + **战斗配置**。

        返回 ``{loadouts: [...], echoProfiles: [...]}``。

        ## 为什么分两组而不是合并成一张表

        两者字段完全不同（``Loadout`` 是"角色 + 声骸套装 + 每档选择"，
        ``EchoProfile`` 是"筛选条件组合"），合并成一张表反而要页面
        天天判 ``kind``。两组并列，页面各自渲染。

        ## ★★ 头像两级兜底（2026-11-02 用户反馈）

        用户：「**配置页头像全是灰圈**」—— 旧界面
        :func:`src.gui.pickers.avatar_icon` 是**两级**的：

        .. code:: python

            icon = load_icon(relative)
            if not icon.isNull():
                return icon
            return _initial_icon(name)    # 散列色相圆 + 白色首字

        新界面只做了第一级 → 文件不在就只剩灰圈。

        所以每条都给三个字段：

        ================  =============================================
        ``avatarUrl``     第一级：真实头像的 HTTP URL（文件不在就是空串）
        ``initial``       第二级：给页面画首字圆图的整套数据
        ``avatarHue``     色相 0~359（和旧界面**同一个散列**）
        ================  =============================================

        ⚠ 页面必须**两级都用**：`avatarUrl` 空了才画 ``initial``。
        只画首字 = 有图也不显示；只等 URL = 回到"全是灰圈"。
        """
        payload: dict = {"loadouts": [], "echoProfiles": []}
        try:
            from ..core import game_data  # noqa: PLC0415
            from ..core.loadout import LoadoutStore  # noqa: PLC0415

            game_data.ensure_loaded()
            store = LoadoutStore()
            for item in store.all():
                rel_avatar = (getattr(item, "custom_avatar", "")
                              or getattr(item, "avatar", ""))
                payload["loadouts"].append({
                    "id": item.id,
                    "character": item.character,
                    "avatar": getattr(item, "avatar", ""),
                    "avatarUrl": self._safe_icon_url(rel_avatar),
                    #: ★ 两级兜底的第二级（照抄旧界面 _initial_icon）
                    "initial": _initial_avatar(item.character),
                    "avatarHue": _initial_avatar_hue(item.character),
                    #: ★ 搜索索引（拼音必须后端算 —— pypinyin 是 Python 包）
                    "pinyin": list(pinyin_keys(item.character)),
                    "echoSet": item.echo_set,
                    "status": item.status,
                    "qualities": list(item.qualities),
                    "updatedAt": item.updated_at,
                    #: 每档选中的声骸：{"4": [{"echo":.., "stats":[..]}], ...}
                    "picks": {
                        str(cost): [
                            {"echo": p.echo, "stats": list(p.stats)}
                            for p in picks
                        ]
                        for cost, picks in (item.picks or {}).items()
                    },
                    "errors": _safe(lambda: item.validate(), []),
                })
        except Exception:  # noqa: BLE001
            logger.warning("getConfigList：读配置失败", exc_info=True)

        try:
            from ..core.echo_profile import EchoProfileStore  # noqa: PLC0415

            store = EchoProfileStore()
            #: ★ 必须 load() —— 见 _save_echo_profile 的说明
            store.load()
            for prof in store.all():
                try:
                    data = prof.to_dict()
                except Exception:  # noqa: BLE001
                    data = {}
                name = str(getattr(prof, "name", "") or "")
                data.setdefault("id", getattr(prof, "id", ""))
                data.setdefault("name", name)
                data["updatedAt"] = getattr(prof, "updated_at", "")
                #: ★★ ``EchoProfile`` 本身**没有 avatar 字段**（它只有一个
                #: ``name``，名字就是角色名）。旧界面是靠
                #: ``avatar_icon(相对路径, 角色名)`` —— 相对路径按**约定**
                #: 推导 ``avatars/<角色名>.png``，文件不在就画首字。
                #: 这里照同一套约定推。
                rel_avatar = f"avatars/{name}.png" if name else ""
                data["avatar"] = rel_avatar
                data["avatarUrl"] = self._safe_icon_url(rel_avatar)
                data["initial"] = _initial_avatar(name)
                data["avatarHue"] = _initial_avatar_hue(name)
                #: ★ 搜索索引（同 loadouts）
                data["pinyin"] = list(pinyin_keys(name))
                payload["echoProfiles"].append(data)
        except Exception:  # noqa: BLE001
            logger.warning("getConfigList：读声骸配置失败", exc_info=True)

        #: ★ 「一个角色只能一条配置」（用户 2026-09-26）
        #:
        #: 配置页的两个列表各自已经带着角色名了，但**页面要画「新增」弹框时
        #: 需要知道哪些角色已经被占**。这里给一份现成的，省得页面再算一遍
        #: （也算不长 —— 但它和 :meth:`getCharacterOptions` 的 taken 必须一致）。
        #:
        #: ⚠ 两类配置**各自独立**：一个角色可以同时有「声骸筛选」和
        #: 「强化配置」各一条 —— 所以分两个集合给，不是一个。
        try:
            payload["takenCharacters"] = {
                "loadout": sorted(
                    self._taken_characters("loadout")),
                "echo_profile": sorted(
                    self._taken_characters("echo_profile")),
            }
        except Exception:  # noqa: BLE001
            logger.debug("getConfigList：算 taken 失败", exc_info=True)
            payload["takenCharacters"] = {"loadout": [], "echo_profile": []}

        return _json(payload)

    def _safe_icon_url(self, relative: str) -> str:
        """``_game_icon_url`` 的安全版：**文件真的存在**才给 URL。

        ## 为什么要多这一层

        ``_game_icon_url`` 只拼 URL、不看文件在不在 —— 文件缺失时页面会
        拿到一个 404 的 URL，``<img>`` 加载失败后**什么都不显示**
        （取决于页面有没有 ``onerror``）。

        旧界面是 ``load_icon()`` 先 ``path.exists()`` 判断，不存在直接
        走首字兜底。这里对齐那个行为：**URL 只在文件真在时才给**，
        页面就能用「avatarUrl 为空 → 画首字」这条简单规则。
        """
        rel = str(relative or "").strip()
        if not rel:
            return ""
        try:
            from ..core import paths  # noqa: PLC0415

            normalized = rel.replace("\\", "/")
            sub, _, name = normalized.partition("/")
            if not name:
                sub, name = "avatars", normalized
            if sub not in ("avatars", "echo_sets", "echoes", "weapons"):
                return ""
            if not (paths.resource_dir("assets", "game", sub) / name).is_file():
                return ""
        except Exception:  # noqa: BLE001
            return ""
        return _safe(lambda: self._game_icon_url(normalized), "") or ""

    @Slot(result=str)
    def getLibraryData(self) -> str:
        """资源库数据（角色 / 声骸套装 / 声骸 / 武器）。

        返回 ``{characters: [...], echoSets: [...], echoesByCost: {...},
        weapons: [...], counts: {...}, assetsAvailable: bool}``。

        ## ``assetsAvailable`` 很重要

        ``assets/game/`` 是**不进仓库**的（见 ``core/assets.py`` 模块文档：
        美术素材版权）。用户可能没有这些图 → 页面要能显示"图标缺失"的
        占位态，而不是一堆破图。所以先全局探一次目录在不在。

        ## 体积

        61 角色 + 37 套装 + 187 声骸 + 123 武器 ≈ 400 条。序列化后
        约 200~300 KB JSON —— 一次传完，不做分页（比来回请求简单可靠）。
        """
        payload: dict = {
            "characters": [], "echoSets": [], "echoesByCost": {},
            "weapons": [], "counts": {}, "assetsAvailable": False,
        }
        try:
            from ..core import game_data  # noqa: PLC0415

            game_data.ensure_loaded()
            payload["assetsAvailable"] = self._game_assets_ok()

            for ch in game_data.CHARACTERS:
                payload["characters"].append({
                    "name": ch.name,
                    "avatar": ch.avatar,
                    "avatarUrl": self._game_icon_url(ch.avatar),
                    "rarity": ch.rarity,
                    "element": ch.element,
                    "weapon": ch.weapon,
                    "releaseVersion": ch.release_version,
                    "tagline": _safe(lambda c=ch: c.tagline, ""),
                    #: ★★★ 2026-11-03 用户：「**所有的角色搜索都按照这样做**」
                    #: （下拉 + 名称/拼音模糊匹配）。
                    #:
                    #: 图鉴页的搜索框是**全局**的（角色/套装/声骸/武器共用
                    #: 一个关键词），不是下拉列表 —— 但「角色」这块同样要
                    #: 支持拼音：打 ``fx`` 应该能搜到「绯雪」。
                    #:
                    #: 拼音只能后端算（``pypinyin`` 是 Python 包），
                    #: 规则同 :func:`src.core.text_match.pinyin_keys`。
                    "pinyin": list(pinyin_keys(ch.name)),
                })

            for st in game_data.ECHO_SETS:
                payload["echoSets"].append({
                    "name": st.name,
                    "icon": st.icon,
                    "iconUrl": self._game_icon_url(st.icon),
                    "version": st.version,
                    "pieceCounts": list(_safe(lambda s=st: s.piece_counts, ())),
                    "effects": [
                        {"pieces": pieces, "text": text}
                        for pieces, text in st.effects
                    ],
                    "echoCount": len(st.echoes),
                })

            for cost, echoes in game_data.ECHOES_BY_COST.items():
                payload["echoesByCost"][str(cost)] = [
                    {
                        "name": e.name,
                        "icon": e.icon,
                        "iconUrl": self._game_icon_url(e.icon),
                        "cost": e.cost,
                        "stats": list(e.stats),
                        "skill": e.skill,
                        "cooldown": e.cooldown,
                    }
                    for e in echoes
                ]

            #: 武器图标没有 avatar 字段 —— 按项目约定推导 weapons/<名字>.png
            for wp in getattr(game_data, "WEAPONS", ()) or ():
                rel = f"weapons/{wp.name}.png"
                payload["weapons"].append({
                    "name": wp.name,
                    "type": getattr(wp, "type", ""),
                    "rarity": getattr(wp, "rarity", 0),
                    "icon": rel,
                    "iconUrl": self._game_icon_url(rel),
                })

            payload["counts"] = {
                "characters": len(payload["characters"]),
                "echoSets": len(payload["echoSets"]),
                "echoes": sum(len(v) for v in payload["echoesByCost"].values()),
                "weapons": len(payload["weapons"]),
            }
        except Exception:  # noqa: BLE001
            logger.warning("getLibraryData 失败", exc_info=True)
        return _json(payload)

    # ── 素材 URL 辅助 ──────────────────────────────────────────────
    def _game_assets_ok(self) -> bool:
        """``assets/game/`` 里到底有没有图（决定页面显不显示占位态）。"""
        try:
            from ..core import paths  # noqa: PLC0415

            for sub in ("avatars", "echoes", "echo_sets", "weapons"):
                d = paths.resource_dir("assets", "game", sub)
                if d.is_dir():
                    return True
        except Exception:  # noqa: BLE001
            pass
        return False

    def _game_icon_url(self, relative: str) -> str:
        """``avatars/莉莉.png`` → ``http://127.0.0.1:p/game/avatars/%E8%8E%89...png``。

        ## ⚠ 必须 percent-encode

        图标文件名**全是中文**（``莉莉.png`` / ``万囮牢·朽躯.png``）。
        原样拼进 URL 的话：

        * ``media_server`` 靠 ``urllib`` 解析路径，中文能过
        * 但 Chromium 发请求时会不会编码，取决于上下文
          （``<img src>`` 会自动编码，``fetch`` 不会）

        统一由 Python 这边编码好，页面直接 ``<img src>`` 用 —— 两边都不踩坑。
        """
        rel = str(relative or "").strip().replace("\\", "/")
        if not rel:
            return ""
        #: 已经带了子目录就直接用；否则按 avatars 兜底
        if "/" not in rel:
            rel = f"avatars/{rel}"
        try:
            from ..core import media_server, paths  # noqa: PLC0415

            base = media_server.web_url("index.html")
            if not base:
                return ""
            host = base.rsplit("/web/", 1)[0]
            #: 只认白名单子目录（和 web_shell.GAME_ASSET_SUBDIRS 对齐）
            sub = rel.split("/", 1)[0]
            if sub not in ("avatars", "echo_sets", "echoes", "weapons"):
                return ""
            #: ★ quote 保留 "/"，把中文和各种符号编码掉
            from urllib.parse import quote  # noqa: PLC0415

            return f"{host}/game/{quote(rel, safe='/')}"
        except Exception:  # noqa: BLE001
            logger.debug("_game_icon_url 失败 %s", rel, exc_info=True)
            return ""

    # ================================================================ 窗口
    @Slot(str, result=str)
    def windowAction(self, action: str) -> str:
        """窗口控制（标题栏那三个按钮）。

        ## 为什么这些动作要绕回 Python

        HTML 页面**没法**最小化 / 最大化 / 关闭原生窗口 —— 那是
        ``QWidget`` 的能力。所以标题栏按钮 → ``bridge.windowAction()``
        → :class:`src.gui.web_shell.WebShell` 的槽。

        ``action`` 取值：``minimize`` / ``maximize`` / ``restore`` /
        ``togglemaximize`` / ``close``。

        ⚠ **拖动窗口不在这里** —— 见 :meth:`startWindowDrag`
        """
        action = (action or "").strip().lower()
        allowed = ("minimize", "maximize", "restore",
                   "togglemaximize", "close")
        if action not in allowed:
            return _json({"ok": False, "reason": "unknown_action"})
        self.windowActionRequested.emit(action)
        return _json({"ok": True, "action": action})

    @Slot(result=str)
    def getWindowState(self) -> str:
        """★ 当前窗口状态（页面加载时问一次，2026-11-03）。

        :return: ``{ok, maximized}``

        ## 为什么需要（除了 ``windowStateChanged`` 推送）

        ``WebShell.show()`` 里会推一次初始状态，但**那时页面可能还没连上
        Bridge**（QWebChannel 握手在 ``window.onload`` 之后才完成）——
        那条推送会丢。

        页面加载完主动问一次才能保证图标正确。

        ## 为什么要问宿主而不是自己算

        页面里没有任何可靠的「窗口是否最大化」信号：
        ``window.outerHeight === screen.availHeight`` 在多显示器、
        任务栏自动隐藏、Aero Snap 分屏（只占一半屏幕）时全都会判错。

        宿主侧 ``QWidget.isMaximized()`` 才是唯一准确的来源。
        """
        host = self._window_host
        if host is None:
            return _json({"ok": True, "maximized": False})
        try:
            return _json({"ok": True, "maximized": bool(host.isMaximized())})
        except Exception:  # noqa: BLE001
            logger.debug("getWindowState 失败", exc_info=True)
            return _json({"ok": True, "maximized": False})

    @Slot(result=str)
    def startWindowDrag(self) -> str:
        """开始拖拽窗口（页面标题栏 mousedown 调它）。

        ## 为什么需要（2026-11-02 无边框窗口）

        用户："那个白色的方块区域去掉，下面本来就有最小化，关闭，放大"

        去掉 Windows 原生标题栏之后，**拖标题栏移动窗口**的能力也没了
        —— 页面要自己接：``.titlebar`` 上 mousedown → 调这里。

        ## 实现（Win32）

        宿主收到之后做：

        .. code:: python

            ReleaseCapture()
            SendMessage(hwnd, WM_NCLBUTTONDOWN, HTCAPTION, 0)

        **让 Windows 以为用户在拖原生标题栏** —— 之后拖动、贴边分屏
        （Aero Snap）全由系统接管，不用算位移。

        ⚠ 页面**不需要**跟 mouseup/mousemove —— 调一次就够，
        系统会一直拖到用户松手。

        :return: ``{ok, action}``
        """
        try:
            self.windowActionRequested.emit("startdrag")
            return _json({"ok": True, "action": "startdrag"})
        except Exception:  # noqa: BLE001
            logger.warning("startWindowDrag 失败", exc_info=True)
            return _json({"ok": False, "reason": "error"})

    @Slot(result=str)
    def frontendReady(self) -> str:
        """★ 前端脚本跑完了（握手完成）。

        无头测试靠这个判断「页面真的加载成功」；正式跑的时候
        :class:`~src.gui.web_shell.WebShell` 用它打一条日志。
        """
        self.frontendReadySignal.emit()
        return _json({"ok": True})

    # ================================================================ 订阅
    @Slot(result=str)
    def ping(self) -> str:
        """握手：页面加载完调一次，确认桥还活着。"""
        return _json({"ok": True, "pong": True})

    @Slot(result=str)
    def getAppInfo(self) -> str:
        """应用名 / 版本 / 平台（标题栏、关于页用）。"""
        try:
            from ..app_config import (  # noqa: PLC0415
                APP_AUTHOR, APP_DISPLAY_NAME, APP_NAME, APP_VERSION,
            )

            return _json({
                "name": APP_NAME,
                "displayName": APP_DISPLAY_NAME,
                "version": APP_VERSION,
                "author": APP_AUTHOR,
            })
        except Exception:  # noqa: BLE001
            return _json({"displayName": "鸣潮工具箱", "version": "?", "name": "?"})

    # ================================================================ 推送
    def emitEvent(self, name: str, data: dict | None = None) -> None:
        """★ 给 JS 推一个事件（所有 ``xxxChanged`` 都从这里走）。

        JS 侧 ``bridge.subscribe(fn)`` 收到的是 ``{"name": ..., "data": ...}``。
        """
        self.event.emit(_json({"name": name, "data": data or {}}))

    def pushLog(self, text: str, level: str = "info") -> None:
        """推一行日志。"""
        payload = {"text": str(text), "level": level}
        self.logLine.emit(_json(payload))
        self.emitEvent("logLine", payload)

    def pushProgress(self, value: float | int, text: str = "") -> None:
        """推进度（自动夹到 0~100）。"""
        try:
            v = max(0, min(100, float(value)))
        except (TypeError, ValueError):
            return
        self._progress = v
        payload = {"value": round(v, 1), "text": str(text)}
        self.progress.emit(_json(payload))
        self.emitEvent("progress", payload)

    def pushSkin(self) -> None:
        """皮肤变了 → 通知页面重刷配色。"""
        payload = self.getSkin()
        try:
            data = json.loads(payload)
        except Exception:  # noqa: BLE001
            data = {}
        self.skinChanged.emit(payload)
        self.emitEvent("skinChanged", data)

    def requestPage(self, key: str) -> None:
        """Python 主动要求页面切到某页（侧栏黄字跳转之类）。"""
        payload = {"key": str(key or "")}
        self.pageRequested.emit(_json(payload))
        self.emitEvent("pageRequested", payload)

    def pushWindowState(self, maximized: bool) -> None:
        """★ 推「窗口是否最大化」（2026-11-03）。

        页面标题栏 □ 按钮据此换图标：

        ==========  ===========  ============================
        窗口状态     图标码位      外观
        ==========  ===========  ============================
        普通         ``E922``     单个方框（ChromeMaximize）
        最大化       ``E923``     两个叠起来的方框（ChromeRestore）
        ==========  ===========  ============================

        用户原话：「放大后，这个缩小框不对把，应该右图那样」。

        ⚠ 光换图标不够 —— 点它必须真的**还原**。所以 ``btn-max``
        发的是 ``toggleMaximize`` 而不是 ``maximize``（见 ``app.js``），
        否则图标换了但点了没反应，比原来更让人困惑。
        """
        payload = {"maximized": bool(maximized)}
        self.windowStateChanged.emit(_json(payload))
        self.emitEvent("windowStateChanged", payload)

    # ================================================================ 内部
    def _pick_current(self, items: list[dict]) -> dict:
        """挑「当前应该播的那个」壁纸。

        优先级：显式选过的 → 上次存盘的 → 列表第一个。
        """
        if self._wallpaper_id:
            hit = next((x for x in items if x.get("id") == self._wallpaper_id), None)
            if hit is not None:
                return hit
        try:
            from ..core import wallpaper_state  # noqa: PLC0415

            saved = wallpaper_state.current_id()
            if saved:
                hit = next((x for x in items if x.get("id") == saved), None)
                if hit is not None:
                    return hit
        except Exception:  # noqa: BLE001 - 没存过/模块变了都正常
            pass
        return items[0]

    def _scan_wallpapers(self) -> list[dict]:
        """扫壁纸并把文件路径换成 HTTP URL。

        ## ⚠ 必须先 prepare（mp4 → webm）

        QtWebEngine **没有 H.264 解码器**，mp4 直接扔给 ``<video>`` 会
        ``MEDIA_ERR_SRC_NOT_SUPPORTED``。:func:`webm_transcode.prepare`
        会把 mp4 转成 webm（有缓存），已经是 webm 的原样返回。

        转码很慢（4K 20~60 秒），所以这里**只用缓存、不现场转** ——
        缓存没命中就先不给 URL（页面显示静态底），由 WebShell 在后台补。
        """
        out: list[dict] = []
        try:
            from ..core import media_server, wallpaper_engine, webm_transcode  # noqa: PLC0415

            items = wallpaper_engine.scan_wallpapers()
            if not items:
                return []
            #: 服务只服务转码缓存目录（不暴露整个磁盘 + 不暴露中文路径）
            cache = webm_transcode.cache_dir()
            base = media_server.start(cache) if cache else ""
            if not base:
                return []
            for item in items:
                video = item.get("video_path") or ""
                url = ""
                if video:
                    suffix = os.path.splitext(video)[1].lower()
                    #: webm 直接播；mp4 只认已转好的缓存
                    if suffix in (".webm", ".ogv", ".ogg"):
                        src = video
                    elif webm_transcode.is_ready(video):
                        ready = webm_transcode.webm_path_for(video)
                        src = str(ready) if ready else ""
                    else:
                        src = ""
                    if src:
                        #: ★ url_for 会按文件实际所在目录自动选 URL 前缀
                        #: （见 media_server.url_for 的说明），不用在这里判断
                        url = media_server.url_for(src)
                out.append({
                    "id": item.get("id", ""),
                    "title": item.get("title", ""),
                    "url": url,
                    "supported": bool(url),
                    "type": item.get("type", ""),
                })
        except Exception:  # noqa: BLE001
            logger.warning("扫壁纸失败", exc_info=True)
        return out


# ---------------------------------------------------------------- 小工具
def _parse_gradient(value) -> list[tuple[float, str]]:
    """解析皮肤的 ``bg`` → ``[(pos, '#RRGGBB'), ...]``。

    ## ⚠ 两种格式都要认（踩过）

    ``skins.SKINS`` 里 ``bg`` 是**真正的 Python 对象**::

        "bg": [(0.0, "#0C0A18"), (0.5, "#141026"), (1.0, "#090713")],

    但历史上（以及 ``current_skin()`` 某些路径）它可能是**它的 repr 字符串**::

        "bg": "[(0.0, '#0C0A18'), (0.5, '#141026'), (1.0, '#090713')]"

    第一版只处理了字符串分支，直接调 ``.strip()`` —— 拿到 list 就
    ``AttributeError: 'list' object has no attribute 'strip'``，
    整条 ``getSkin()`` 挂掉（被 except 兜住 → 页面退回默认配色，
    表现为"皮肤颜色跟 Qt 版对不上"，但**不报错**）。
    """
    parsed = value

    #: ① 已经是 list/tuple → 直接用
    if isinstance(parsed, (list, tuple)):
        pass
    #: ② 字符串 → 尝试 literal_eval
    elif isinstance(parsed, str):
        raw = parsed.strip()
        if not raw:
            return []
        try:
            parsed = ast.literal_eval(raw)
        except (ValueError, SyntaxError):
            return []
    else:
        return []

    out: list[tuple[float, str]] = []
    for entry in parsed if isinstance(parsed, (list, tuple)) else []:
        try:
            pos, color = entry
            out.append((float(pos), str(color)))
        except (TypeError, ValueError):
            continue
    return out


def _gradient_css(stops: list[tuple[float, str]]) -> str:
    """``[(0.0, '#000'), (1.0, '#fff')]`` → ``linear-gradient(180deg, ...)``。"""
    if not stops:
        return ""
    parts = [f"{color} {pos * 100:.1f}%" for pos, color in stops]
    return "linear-gradient(180deg, " + ", ".join(parts) + ")"


__all__ = ["WebBridge"]
