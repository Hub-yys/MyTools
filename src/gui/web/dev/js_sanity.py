"""改完 ``tool-panels.js`` / ``pages.css`` 之后的**快速自检**（不开浏览器）。

## 为什么要有这个

2026-11-02 我两次用「按行号/块边界替换」的方式改 ``tool-panels.js``，
两次都把**别的函数整块删掉了**：

  ① 删 ② 调频的重复块 → 把 ① ``auto_combat`` 的 ``registerPanel`` 一起删了
     现象：点进 4C 页面显示「页面渲染失败 / cfgCard is not defined」

  ② 删 ⑦ 资源库的旧块 → 把 ``cfgCard()`` 和整个 ① 又删了一次，
     恢复时还造成 ``auto_combat`` **重复注册**（panels: 8）

两次都是**数花括号数不出来**的：

* 第一次：删掉的是**自身平衡**的一整块 → 花括号数看不出来（-1 变成 -1）
* 第二次：``// 注释里出现 "cfgCard" 字样`` → 字符串搜索误报「还在」

## 所以这个脚本检查的是**语义**，不是字符数

1. **关键符号存在** —— 按 ``function xxx`` / ``const xxx`` / ``registerPanel('x'`` 精确匹配，
   并且**排除注释行**（``//`` 开头）和**注释块内**的行
2. **花括号平衡** —— 先剥掉字符串字面量和 ``//`` 注释再数
3. **7 个面板都注册了** —— 旧界面 7 个工具，一个都不能少
4. **没有重复注册** —— 每个 key 只能 ``registerPanel`` 一次
5. **没有 prereq 残留** —— 用户圈出「干掉」的那块，一行都不许留
6. **CSS 类名有定义** —— JS 里用的 ``cfg-*`` / ``enh-*`` / ``sweep-*`` 等
   在 ``pages.css`` 里必须有对应规则（否则样式悄悄失效）

## 用法

.. code:: powershell

   .venv\\Scripts\\python.exe src\\gui\\web\\dev\\js_sanity.py
   .venv\\Scripts\\python.exe src\\gui\\web\\dev\\js_sanity.py --verbose

退出码 0 = 全过，1 = 有问题。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

WEB_DIR = Path(__file__).resolve().parent.parent
JS_DIR = WEB_DIR / "js"
CSS_DIR = WEB_DIR / "css"

#: 旧界面 7 个工具（``ToolRegistry.all_metas()`` 的 key）—— 一个都不能少
REQUIRED_PANELS = (
    "wuwa_library_update",
    "auto_combat",
    "echo_change",
    "nest_sweep",
    "character_build",
    "gacha",
    "echo_enhance",
)

#: ``tool-panels.js`` 里必须存在的顶层符号。
#:
#: ⚠ 这里列的是**被其它函数调用**的东西 —— 它们一消失，页面会整块白屏
#: （``cfgCard is not defined`` 那种），而且**不会**在编译期报错。
REQUIRED_SYMBOLS_PANELS = (
    "function cfgCard",
    "function collapsibleCard",
    # ① 4C 自动战斗
    "function buildCombatRunCard",
    "function buildCombatStyleCard",
    "function buildCombatShutdownCard",
    "function buildCombatReportCard",
    "function buildCombatHistoryCard",
    "const COMBAT_STYLES_FALLBACK",
    "const COMBAT_STATE",
    # ② 声骸批量调频
    "const TARGET_STATS",
    "function changeSaveSettings",
    # ③ 扫荡残像聚落
    "const SWEEP_COLUMNS",
    "function sweepCard",
    "const SWEEP_STATE",
    # ④ 声骸自动强化
    "const ENHANCE_ALL_STATS",
    "function enhanceOnCoreChange",
    "const ENHANCE_STATE",
    # ⑤ 抽卡记录分析
    "const GACHA_STATE",
    "function gachaRenderOverview",
    # ⑥ 查询角色练度
    "const BUILD_STATE",
    # ⑦ 资源库更新
    "const LIB_STATE",
    "function libNormalizeReport",
)

#: ``pages/config.js`` 里必须存在的符号（P7 新增的「新增/编辑」对话框）
#:
#: ⚠ 这些是「点了没反应」那类 bug 的防线：
#:   按钮绑到一个不存在的函数时，**页面本身照样渲染**（只有点下去那一刻才
#:   在控制台报 ``xxx is not defined``），所以很容易漏掉 —— 用户就是这么
#:   发现「新增」点了没弹框的。
REQUIRED_SYMBOLS_CONFIG = (
    "function openConfigTypeDialog",
    "function openEchoProfileDialog",
    "function openEditDialog",
    "function openDialog",
    "function closeDialog",
    "function characterPicker",
    "function buildDialogSettingsEditor",
    "function validateProfileName",
    "function submitEchoProfile",
    "function loadCharacterOptions",
    "function takenCharacters",
    "const CONFIG_TYPES",
)


def _strip_js_code(line: str) -> str:
    """去掉字符串字面量和行尾注释，只留「结构字符」。

    用来数花括号 —— 直接 ``str.count`` 会被这些骗到：

    * ``'文字{'`` —— 字符串里的花括号
    * ``// 注释里有 }`` —— 注释里的花括号
    * ``'it\\'s'`` —— 转义引号（会提前结束字符串）
    """
    out: list[str] = []
    i = 0
    quote: str | None = None
    while i < len(line):
        ch = line[i]
        if quote is not None:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in "\"'`":
            quote = ch
            i += 1
            continue
        if ch == "/" and i + 1 < len(line) and line[i + 1] == "/":
            break
        out.append(ch)
        i += 1
    return "".join(out)


def _code_lines(text: str) -> list[tuple[int, str]]:
    """返回 ``(行号, 内容)``，**跳过整块注释**（``/* … */``）和行注释。

    ``// 注释里提到 cfgCard`` 不算「符号存在」—— 这就是第二次误判的原因。
    """
    result: list[tuple[int, str]] = []
    in_block = False
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw
        if in_block:
            end = line.find("*/")
            if end < 0:
                continue
            line = line[end + 2:]
            in_block = False
        #: 行内可能先出现 ``/*``
        while True:
            start = line.find("/*")
            if start < 0:
                break
            end = line.find("*/", start + 2)
            if end < 0:
                line = line[:start]
                in_block = True
                break
            line = line[:start] + line[end + 2:]
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            continue
        result.append((lineno, line))
    return result


def check_symbols(path: Path) -> list[str]:
    """关键符号存在（按代码行检查，注释不算）"""
    problems: list[str] = []
    if not path.exists():
        return [f"文件不存在：{path}"]
    text = path.read_text(encoding="utf-8")
    code = "\n".join(line for _, line in _code_lines(text))
    symbols = (REQUIRED_SYMBOLS_CONFIG
               if path.name == "config.js" else REQUIRED_SYMBOLS_PANELS)
    for symbol in symbols:
        if symbol not in code:
            problems.append(f"符号缺失：{symbol}")
    return problems


def check_braces(path: Path) -> list[str]:
    """花括号平衡（剥掉字符串和注释再数）"""
    problems: list[str] = []
    if not path.exists():
        return [f"文件不存在：{path}"]
    text = path.read_text(encoding="utf-8")
    depth = 0
    first_negative = 0
    for lineno, raw in enumerate(text.splitlines(), 1):
        code = _strip_js_code(raw)
        depth += code.count("{") - code.count("}")
        if depth < 0 and not first_negative:
            first_negative = lineno
    if first_negative:
        problems.append(f"花括号在第 {first_negative} 行就变负（多了一个 }}）")
    if depth != 0:
        problems.append(f"花括号不平衡：最终深度 {depth}（应为 0）")
    return problems


def check_panels(path: Path) -> list[str]:
    """7 个面板都注册了，且没有重复"""
    problems: list[str] = []
    if not path.exists():
        return [f"文件不存在：{path}"]
    text = path.read_text(encoding="utf-8")
    registered: list[str] = []
    for _, line in _code_lines(text):
        for hit in re.finditer(r"registerPanel\(\s*'([^']+)'", line):
            registered.append(hit.group(1))

    for key in REQUIRED_PANELS:
        if key not in registered:
            problems.append(f"面板没注册：{key}")
    seen: set[str] = set()
    for key in registered:
        if key in seen:
            problems.append(f"面板**重复注册**：{key}（会导致渲染两次）")
        seen.add(key)
    unknown = [k for k in seen if k not in REQUIRED_PANELS]
    if unknown:
        problems.append(f"注册了未知面板：{unknown}（旧界面只有 7 个工具）")
    return problems


def check_prereq(path: Path) -> list[str]:
    """「运行前提」一行都不许留（用户圈出「干掉」）"""
    problems: list[str] = []
    if not path.exists():
        return [f"文件不存在：{path}"]
    text = path.read_text(encoding="utf-8")
    for lineno, line in _code_lines(text):
        if "prereqHost" in line or "Panels.prerequisites" in line:
            problems.append(
                f"第 {lineno} 行还有 prereq 残留：{line.strip()[:70]}")
    return problems


def check_css_classes(css_path: Path, js_path: Path) -> list[str]:
    """JS 里用到的自定义**类名**，CSS 里必须有定义。

    ⚠ 只查 ``class: '…'`` 属性里的值 —— **不查 ``id: '…'``**：
    很多 ``build-*`` / ``lib-*`` 是 id（``document.getElementById`` 用的），
    它们本来就不该有 CSS 规则。第一版没区分，误报了 5 个。

    ⚠ 也只查**本项目自己的**前缀 —— ``btn`` / ``card`` 那些通用类不查。
    """
    problems: list[str] = []
    if not css_path.exists():
        return [f"文件不存在：{css_path}"]
    if not js_path.exists():
        return [f"文件不存在：{js_path}"]

    css_text = css_path.read_text(encoding="utf-8")
    js_text = js_path.read_text(encoding="utf-8")

    prefixes = ("cfg-", "enh-", "coll-", "sweep-", "gk-", "lib-",
                "build-", "wallpaper-", "skin-", "nav-group")
    class_attr = re.compile(
        r"""class:\s*'([^']+)'"""      #: class: 'a b c'
        r"""|class:\s*"([^"]+)\"""")   #: class: "a b c"

    used: set[str] = set()
    for _, line in _code_lines(js_text):
        for hit in class_attr.finditer(line):
            raw = hit.group(1) or hit.group(2) or ""
            for token in raw.split():
                if token.startswith(prefixes):
                    used.add(token)

    for name in sorted(used):
        if f".{name}" not in css_text:
            problems.append(f"CSS 里没有 .{name} 的规则（JS 在用）")
    return problems


def check_bridge_calls(js_path: Path, bridge_path: Path) -> list[str]:
    """JS 里每个 ``P.call('xxx', ...)`` / ``Bridge.call('xxx', ...)`` 的参数个数
    必须和后端 ``@Slot(...)`` 声明**完全一致**。

    ## 为什么必须查这个（2026-11-02 真踩到）

    QWebChannel **参数个数不匹配时不报错，直接返回空**。表现是：

    * 后端 ``@Slot(str, result=str) def getGachaOverview(self, player_id="")``
    * 前端 ``P.call('getGachaOverview')`` ← 少传一个
    * 结果：**静默返回 ``[]``**，页面显示 6 个「—」，日志里一个字都没有

    我照着「后端有默认值 = 可以不传」去写，结果排查了半小时。
    **默认值只在 Python 侧生效，QWebChannel 在 JS 侧就拦住了。**

    这个检查把「JS 实际传几个」和「@Slot 声明几个」对齐。
    """
    problems: list[str] = []
    if not js_path.exists() or not bridge_path.exists():
        return []

    bridge_text = bridge_path.read_text(encoding="utf-8")
    js_text = js_path.read_text(encoding="utf-8")

    #: 解析 ``@Slot(...)`` 里**输入**参数的个数（``result=`` 不算输入）
    slot_args: dict[str, int] = {}
    pending = 0
    for line in bridge_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("@Slot("):
            #: ``@Slot(str, result=str)`` → 1
            #: ``@Slot(str, int, result=str)`` → 2
            #: ``@Slot(result=str)`` → 0
            inner = stripped[len("@Slot("):]
            inner = inner.rsplit(")", 1)[0]
            inner = inner.split("result=")[0]
            parts = [x for x in inner.split(",") if x.strip()]
            pending = len(parts)
            continue
        if stripped.startswith("def ") and pending >= 0 and "(" in stripped:
            name = stripped[4:].split("(")[0].strip()
            if name:
                slot_args[name] = pending
            pending = 0

    #: 解析 JS 调用：``P.call('name', a, b)`` / ``Bridge.call('name')``
    #:
    #: ⚠ 正则要**把闭合引号一起吃进去** —— 第一版只吃到名字结尾，
    #: 于是 ``tail`` 从 ``'`` 开始，被当成"传了 1 个参数"，全部误报。
    #: ★ **第一个捕获组是调用方式**（``P.call`` / ``P.callMulti`` …）。
    #:   判断 ``callMulti`` 必须靠这个，不能靠"往前数几个字符"——
    #:   第一版就是这么写的，结果 ``deleteConfig`` 那条一直误报。
    call_re = re.compile(
        r"""((?:P|Bridge)\.(?:call|callMulti|callWith))"""
        r"""\(\s*'([A-Za-z_][A-Za-z0-9_]*)'\s*""")

    for lineno, line in _code_lines(js_text):
        for hit in call_re.finditer(line):
            how = hit.group(1)
            name = hit.group(2)
            if name not in slot_args:
                continue
            #: 数这次调用传了几个参数（从**闭合引号之后**开始）
            tail = line[hit.end():]
            #: 找到匹配的右括号（tail 以 ``)`` 或 ``,`` 开头）
            depth = 0
            end_idx = len(tail)
            for idx, ch in enumerate(tail):
                if ch in "([{":
                    depth += 1
                elif ch in ")]}":
                    if depth == 0:
                        end_idx = idx
                        break
                    depth -= 1
            args_text = tail[:end_idx].strip()
            #: 去掉开头可能残留的逗号
            args_text = args_text.lstrip(",").strip()
            if not args_text:
                passed = 0
            else:
                depth2 = 0
                passed = 1
                for ch in args_text:
                    if ch in "([{":
                        depth2 += 1
                    elif ch in ")]}":
                        depth2 -= 1
                    elif ch == "," and depth2 == 0:
                        passed += 1
            #: ★ ``P.callMulti('x', [a, b])`` —— 数组会被**展开**成多个参数，
            #:   所以 ``[a, b]`` 是传 **2** 个，不是 1 个。
            #:   第一版靠"往前数 12 个字符"判断，没命中，一直误报。
            if "callMulti" in how:
                if args_text.startswith("[") and args_text.endswith("]"):
                    inner = args_text[1:-1].strip()
                    if not inner:
                        passed = 0
                    else:
                        depth3 = 0
                        passed = 1
                        for ch in inner:
                            if ch in "([{":
                                depth3 += 1
                            elif ch in ")]}":
                                depth3 -= 1
                            elif ch == "," and depth3 == 0:
                                passed += 1
            expect = slot_args[name]
            if passed != expect:
                problems.append(
                    f"第 {lineno} 行 {name}：JS 传 {passed} 个参数，"
                    f"后端 @Slot 要 {expect} 个 —— **会静默返回 []**")
    return problems


def check_html_scripts(html_path: Path) -> list[str]:
    """``index.html`` 里 ``<script src>`` 引用的文件必须真实存在。

    引用一个不存在的 js 会让整页功能静默失效（控制台只有一个 404）。
    """
    problems: list[str] = []
    if not html_path.exists():
        return [f"文件不存在：{html_path}"]
    html = html_path.read_text(encoding="utf-8")
    base = html_path.parent
    for hit in re.finditer(r"""<script[^>]+src=['"]([^'"]+)['"]""", html):
        src = hit.group(1)
        #: ⚠ ``qrc://`` 是 Qt 资源协议（qwebchannel.js 就在里面），不是文件路径。
        #: 第一版只跳过了 http(s)，把它误报成"文件不存在"。
        if src.startswith(("http://", "https://", "//", "qrc:", "data:")):
            continue
        rel = src.split("?")[0].lstrip("./")
        target = (base / rel).resolve()
        if not target.exists():
            problems.append(f"index.html 引用了不存在的文件：{src}")
    return problems
    """JS 里用到的自定义**类名**，CSS 里必须有定义。

    ⚠ 只查 ``class: '…'`` 属性里的值 —— **不查 ``id: '…'``**：
    很多 ``build-*`` / ``lib-*`` 是 id（``document.getElementById`` 用的），
    它们本来就不该有 CSS 规则。第一版没区分，误报了 5 个。

    ⚠ 也只查**本项目自己的**前缀 —— ``btn`` / ``card`` 那些通用类不查。
    """
    problems: list[str] = []
    if not css_path.exists():
        return [f"文件不存在：{css_path}"]
    if not js_path.exists():
        return [f"文件不存在：{js_path}"]

    css_text = css_path.read_text(encoding="utf-8")
    js_text = js_path.read_text(encoding="utf-8")

    #: 本项目自定义前缀（新加的类名都在这里面）
    prefixes = ("cfg-", "enh-", "coll-", "sweep-", "gk-", "lib-",
                "build-", "wallpaper-", "skin-", "nav-group")
    class_attr = re.compile(
        r"""class:\s*'([^']+)'"""      #: class: 'a b c'
        r"""|class:\s*"([^"]+)\"""")   #: class: "a b c"

    used: set[str] = set()
    for _, line in _code_lines(js_text):
        for hit in class_attr.finditer(line):
            raw = hit.group(1) or hit.group(2) or ""
            for token in raw.split():
                if token.startswith(prefixes):
                    used.add(token)

    for name in sorted(used):
        if f".{name}" not in css_text:
            problems.append(f"CSS 里没有 .{name} 的规则（JS 在用）")
    return problems


def check_undeclared_globals(js_path: Path) -> list[str]:
    """★ 查找「批量替换丢了对象前缀」造成的未声明变量。

    ## 为什么要有这条（2026-11-02 一天内踩了 3 次）

    我用替换脚本改 ``.el.disabled`` → ``.input.disabled`` 时，产出了：

    .. code:: javascript

      local.critField.el.classList.add('cfg-number');
        critField.input.classList.add('cfg-number-input');   // ← 少了 local.
                              ^^^^^^^^^

    → 运行时 ``ReferenceError: critField is not defined``。
    **三次都是同一模式**，而且症状都是「点了没反应」。

    ## 为什么只查**行首**这一种形态

    第一版我扫全行所有 ``identifier.`` —— 结果 182 条误报：
    ``classList`` / ``style`` / ``main`` 这些出现在**字符串和注释正文**里的词
    全被当成代码。做作用域分析又太重。

    收窄成：**一行开头的 `identifier.`**，且该 identifier 不在已知集合里。

    这类事故的产出行长这样（替换脚本把新行插在缩进里）：
    .. code:: javascript

          critField.input.classList.add('cfg-number-input');

    行首就是那个丢失了前缀的 identifier —— 抓它命中率最高、误报最低。
    """
    problems: list[str] = []
    if not js_path.exists():
        return []

    text = js_path.read_text(encoding="utf-8")
    code = "\n".join(line for _, line in _code_lines(text))

    declared: set[str] = set()
    for m in re.finditer(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)", code):
        declared.add(m.group(1))
    for m in re.finditer(r"\bfunction\s+([A-Za-z_$][\w$]*)", code):
        declared.add(m.group(1))
    for m in re.finditer(r"function\s*[\w$]*\s*\(([^)]*)\)", code):
        for part in m.group(1).split(","):
            name = part.strip().split("=")[0].strip()
            if re.fullmatch(r"[A-Za-z_$][\w$]*", name):
                declared.add(name)
    for m in re.finditer(r"\(([^)]*)\)\s*=>", code):
        for part in m.group(1).split(","):
            name = part.strip().split("=")[0].strip()
            if re.fullmatch(r"[A-Za-z_$][\w$]*", name):
                declared.add(name)

    known = declared | {
        "window", "document", "console", "Math", "JSON", "String", "Number",
        "Boolean", "Array", "Object", "Date", "Set", "Map", "Promise", "Error",
        "isFinite", "isNaN", "parseInt", "parseFloat", "undefined",
        "this", "self", "globalThis", "setTimeout", "clearTimeout",
        "setInterval", "clearInterval", "requestAnimationFrame",
        "Event", "MouseEvent", "KeyboardEvent", "URL", "Blob", "File",
        "Node", "Element", "HTMLElement", "RegExp", "Intl", "arguments",
        "encodeURIComponent", "decodeURIComponent",
        #: 本项目全局
        "P", "Pages", "App", "TP", "ToolPanels", "Bridge", "Panel", "Panels",
        "DATA", "debug", "module", "exports", "require",
    }

    #: ★ 只查「行首 identifier.」—— 批量替换事故的产出行就是这种形状
    head_access = re.compile(r"^\s*([a-z][A-Za-z0-9_$]*)\.[A-Za-z_$]")
    for lineno, line in _code_lines(text):
        m = head_access.match(line)
        if not m:
            continue
        name = m.group(1)
        if name in known:
            continue
        problems.append(
            f"第 {lineno} 行以 ``{name}.`` 开头，且 ``{name}`` 没有声明 "
            f"—— 批量替换丢了对象前缀？运行时会抛 ReferenceError")
    return problems


def check_silent_failures(js_path: Path) -> list[str]:
    """★ 查找「失败时没有任何用户可见信号」的静默返回。

    ## 为什么这条最重要（2026-11-02 一天内踩了 4 次）

    这个项目里出现过 4 种「用户看到的是『点了没反应』」的失败：

    ==========================================  ====================================
    现象                                         根因
    ==========================================  ====================================
    点「下一步」没反应                           async 弹框抛异常 →
                                                **不进 window.onerror**
    点「编辑」没反应                             ``if (!noticeHost) return``
                                                （容器重渲染后失效）
    ④ 跳过/继续/停止/运行失败全无提示            ``ENHANCE_STATE.stateLabel``
                                                **从未被赋值**，恒为 null
    抽卡历史一直空                               ``@Slot(str)`` 少传参 →
                                                **静默返回 []**
    ==========================================  ====================================

    **共同点：失败时用户看不到任何东西。** 这比"报错"难查得多 ——
    报错至少有 stack，静默失败连日志都没有。

    ## 这条检查抓什么

    1. ``if (!obj.field) return;`` —— 对象属性不存在时静默返回
       （**只查 ``obj.xxx`` 形式**；``if (!el) return`` 那种纯局部变量
       是正常防御性编程，DOM 不在就别画，不误报）
    2. ``XXX_STATE.field`` 被引用但**从未赋值** —— 恒为 null，
       依赖它的分支永远不执行
    """
    problems: list[str] = []
    if not js_path.exists():
        return []

    text = js_path.read_text(encoding="utf-8")
    code_lines = _code_lines(text)

    # ── ① 对象属性形式的静默返回 ──
    prop_guard = re.compile(
        r"if\s*\(\s*!\s*([A-Za-z_]\w*)\.([A-Za-z_]\w*)\s*\)\s*return\s*;")
    for lineno, line in code_lines:
        hit = prop_guard.search(line)
        if hit:
            obj, field = hit.group(1), hit.group(2)
            problems.append(
                f"第 {lineno} 行：``if (!{obj}.{field}) return;`` —— "
                f"该属性失效时**静默什么都不做**（用户看到「点了没反应」）；"
                f"改用兜底出口（toast / 页面固定区域）")

    # ── ② 读了但从未赋值的 STATE 字段 ──
    for m in re.finditer(r"const\s+([A-Z][A-Z0-9_]*_STATE)\s*=\s*\{(.*?)\};",
                         text, re.S):
        state_name, body = m.group(1), m.group(2)
        declared = set()
        for item in body.split(","):
            if ":" in item:
                key = item.split(":")[0].strip()
                if re.fullmatch(r"[A-Za-z_]\w*", key):
                    declared.add(key)
        for field in sorted(declared):
            full = f"{state_name}.{field}"
            #: 赋值形式有三种，都要认：
            #:   ``X.f = v``       直接赋值
            #:   ``X.f[k] = v``    下标赋值（``coreBoxes[stat] = cb`` 就是这种）
            #:   ``const f = X.f; f[k] = ...``  —— 太绕，不查
            assigned = len(re.findall(
                re.escape(full) + r"\s*(?:\[[^\]]*\]\s*)?=(?!=)", text))
            used = text.count(full)
            #: 引用 > 0 且赋值 == 0 才报 —— 那说明它恒为 null
            if used and not assigned:
                problems.append(
                    f"{full} 被引用 {used} 次但**从未赋值**（恒为 null）"
                    f"—— 依赖它的分支永远不会执行")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Web shell JS/CSS 快速自检")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="打印检查了哪些文件")
    args = parser.parse_args(argv)

    panels_js = JS_DIR / "pages" / "tool-panels.js"
    config_js = JS_DIR / "pages" / "config.js"
    pages_css = CSS_DIR / "pages" / "pages.css"
    #: 后端桥接（跨目录：``src/core/web_bridge.py``）
    bridge_py = WEB_DIR.parent.parent / "core" / "web_bridge.py"
    index_html = WEB_DIR / "index.html"

    checks = [
        ("tool-panels 符号", lambda: check_symbols(panels_js)),
        ("tool-panels 花括号", lambda: check_braces(panels_js)),
        ("config 符号", lambda: check_symbols(config_js)),
        ("config 花括号", lambda: check_braces(config_js)),
        ("面板注册", lambda: check_panels(panels_js)),
        ("prereq 残留", lambda: check_prereq(panels_js)),
        ("CSS 类名定义", lambda: check_css_classes(pages_css, panels_js)),
        ("config CSS 类名", lambda: check_css_classes(pages_css, config_js)),
        #: ★ 最重要的一条（用户痛感最强）：失败时必须看得见
        ("tool-panels 静默失败", lambda: check_silent_failures(panels_js)),
        ("config 静默失败", lambda: check_silent_failures(config_js)),
        #: ★ 批量替换丢前缀 → ReferenceError（2026-11-02 一天踩了 3 次）
        ("tool-panels 未声明变量", lambda: check_undeclared_globals(panels_js)),
        ("config 未声明变量", lambda: check_undeclared_globals(config_js)),
        #: ★ 最重要的一条：参数个数不匹配 = **静默返回 []**，最难查
        ("tool-panels 调用签名", lambda: check_bridge_calls(panels_js, bridge_py)),
        ("config 调用签名", lambda: check_bridge_calls(config_js, bridge_py)),
        ("index.html 引用", lambda: check_html_scripts(index_html)),
    ]

    if args.verbose:
        print(f"JS   : {panels_js}")
        print(f"CSS  : {pages_css}")
        print(f"Bridge: {bridge_py}")
        print(f"HTML : {index_html}")
        print()

    total_problems = 0
    for title, fn in checks:
        try:
            problems = fn()
        except Exception as exc:  # noqa: BLE001 - 自检工具不该因自身异常中断
            problems = [f"检查本身出错：{exc}"]
        if problems:
            total_problems += len(problems)
            print(f"[FAIL] {title}")
            for item in problems:
                print(f"       {item}")
        else:
            print(f"[PASS] {title}")

    print()
    if total_problems:
        print(f"结果：{total_problems} 个问题 —— **先修这些再跑验证套件**")
        return 1
    print("结果：全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
