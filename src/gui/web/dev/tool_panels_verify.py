# -*- coding: utf-8 -*-
"""★ P4 工具面板验证（无头，逐面板独立可测）。

## 跑法

.. code:: powershell

    cd "D:\\AI Work\\workbuddy\\MyTools"
    .venv\\Scripts\\python.exe src\\gui\\web\\dev\\tool_panels_verify.py

## 为什么单独一个脚本（不和 ``pages_verify.py`` 合并）

``pages_verify.py`` 验的是**4 个固定页面**（主页/任务/配置/资源库），
它是一条 47 项的阶段链。

P4 要验的是**7 个工具面板**，每个面板结构一样（页头 + 状态 + 日志），
所以这里用**面板注册表 + 逐面板独立断言**：

.. code:: python

    CHECKS = {
        "wuwa_library_update": [...],
        "echo_change": [...],
    }

好处：

* 加一个面板 = 加一条表项，**不用动流水线**（P2 那次「阶段链漏了一行
  导致卡死 60 秒」的坑，根源就是手写闭包链）
* 某个面板断言失败不影响其它面板
* 想看单个面板：``--only echo_change``

## 每个面板统一验这 5 件事

========  ====================================================
编号       断言
========  ====================================================
名 P1     面板注册成功（``App._pages`` 里有 ``tool:<key>``）
名 P2     点进工具页后**不再是占位**（没有 ``.empty-title`` 的"面板"字样）
名 P3     页头标题 = 工具名
名 P4     有状态条 + 日志区（``_panels.js`` 的骨架）
名 P5     点「运行」后状态机有反应（running / blocked / failed 之一，
           **不能**静默什么都不发生）
========  ====================================================
"""

from __future__ import annotations

import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

os.environ.setdefault(
    "QT_LOGGING_RULES", "qt.multimedia.*=false;qt.webenginecontext.debug=false"
)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []
DETAIL: dict = {}


def check(case_id: str, ok: bool, note: str = "") -> None:
    RESULTS.append((case_id, bool(ok), note))
    print(f"[{'PASS' if ok else 'FAIL'}] {case_id}  {note}", flush=True)


#: ★ 面板注册表 —— 加面板只加这里
#:
#: 第三列 ``kind`` 决定 P5「运行反应」怎么断言：
#:
#: * ``engine``（默认）—— 跑 ok-ww / FlowRunThread 的工具。
#:   点运行后状态机必须离开 idle（running / preparing / blocked / failed 之一）。
#:
#: * ``sync``  —— **同步工具**（抽卡分析、角色练度）。
#:   它们不发任务、不起线程，点按后的正确表现是「立刻给出结果 + 状态回到
#:   idle/done」。所以**不能**要求状态机离开 idle —— 那会把正确行为判成失败。
#:   这类只断言「日志有反应」：说明按钮确实接到了处理函数。
PANELS: list[tuple[str, str, str]] = [
    #: (key, 中文名, kind)
    ("wuwa_library_update", "资源库更新", "engine"),
    ("echo_change", "声骸批量调频", "engine"),
    ("auto_combat", "4C 自动战斗", "engine"),
    ("nest_sweep", "扫荡残像聚落", "engine"),
    ("echo_enhance", "声骸自动强化", "engine"),
    ("gacha", "抽卡记录分析", "sync"),
    ("character_build", "查询角色练度", "sync"),
]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="P4 工具面板无头验证（7 个面板 × 9 项）"
    )
    parser.add_argument("--only", default="", help="只跑某个面板 key")
    parser.add_argument(
        "--headed", action="store_true",
        help=("显示真实窗口并放慢节奏（给人看）。"
              "不加这个参数时窗口是隐藏的、节奏快。")
    )
    parser.add_argument(
        "--hold", type=int, default=0,
        help="--headed 模式下每步额外停留的秒数（默认 0）"
    )
    args = parser.parse_args()

    #: ★ --headed：真机排查用。
    #:
    #: 无头模式跑得快，但人看不到画面，无法判断"是不是环境问题"。
    #: 加这个参数后：
    #:   * 窗口**显示**出来（3 秒一屏，能看清）
    #:   * 每步之间多等一会儿，方便人眼跟
    #:   * 结束时**不停**，等用户按回车 —— 好让人看最后的状态
    headed = bool(args.headed)
    #: 每步之间的额外等待（毫秒）。无头不加，headed 每步停 2.2 秒
    pace = (2200 + max(0, args.hold) * 1000) if headed else 0

    app = QApplication.instance() or QApplication([])

    import src.tools as tools_pkg  # noqa: PLC0415

    tools_pkg.discover_tools()

    from src.gui.web_shell import WebShell, web_base_url  # noqa: PLC0415

    base = web_base_url()
    print(f"\n=== base url: {base} ===\n", flush=True)
    if not base:
        print("HTTP 服务起不来", flush=True)
        return 1

    shell = WebShell(base_url=base)
    if not shell.build():
        print("WebShell.build() 失败", flush=True)
        return 1

    view = shell.view
    view.resize(1440, 900)
    if headed:
        view.show()
        view.raise_()
        print("=== --headed：窗口已显示，可以看着跑 ===", flush=True)
    else:
        #: 无头：不显示窗口（QtWebEngine 仍然渲染，只是不可见）
        view.resize(1440, 900)

    js = shell.debug_js

    def bundle(code: str, label: str):
        raw = js(code)
        if raw is None:
            DETAIL[label] = None
            return None
        try:
            value = json.loads(raw)
            DETAIL[label] = value
            return value
        except (TypeError, ValueError):
            DETAIL[label] = raw
            return raw

    # ── 选面板 ──
    targets = PANELS
    if args.only:
        targets = [p for p in PANELS if p[0] == args.only]

    cursor = {"i": 0}

    def step_next() -> None:
        if cursor["i"] >= len(targets):
            QTimer.singleShot(150, finish_and_quit)
            return
        entry = targets[cursor["i"]]
        key, name = entry[0], entry[1]
        kind = entry[2] if len(entry) > 2 else "engine"
        run_panel(key, name, kind)

    # ══════════════════════════════════════════════════════════════════════
    #  单个面板的检查（P1-P8）
    # ══════════════════════════════════════════════════════════════════════
    def run_panel(key: str, name: str, kind: str = "engine") -> None:
        short = key[:14]

        # ── P1：注册成功 ──
        registered = js(
            "(function(){"
            "  if(!window.App || !App._pages) return 'no-app';"
            "  return App._pages.has('tool:" + key + "') ? 'yes' : 'no';"
            "})()"
        )
        check(f"{short}.P1", str(registered) == "yes",
              f"{name}：面板已注册（tool:{key}）= {registered}")

        # ── 进面板 ──
        #
        #: ★ 每个工具「一张卡」的 CSS 选择器（和页面实现一一对应）。
        #: 先写进 window，``check_rendered`` 里读它来数本面板的卡片数。
        #: 7 个工具在这点上**不一样** —— 照旧界面各自的实现来。
        card_sel = {
            "auto_combat": ".cfg-card",
            "echo_change": ".cfg-card",
            "nest_sweep": ".cfg-card",
            "echo_enhance": ".cfg-card",
            "gacha": ".gk-overview",
            "character_build": ".build-card",
            "wuwa_library_update": ".lib-status-card",
        }.get(key, ".cfg-card")
        js("window.__PANEL_CARD_SEL__ = " + repr(card_sel).replace("'", "'") + ";")

        js("App.go('tool:" + key + "', {silent:true})")
        #: headed 时多等一会儿，让人看清面板长什么样
        QTimer.singleShot(900 + pace, lambda: check_rendered(key, name, kind))

    def check_rendered(key: str, name: str, kind: str) -> None:
        short = key[:14]
        data = bundle(
            "JSON.stringify({"
            #: 页头标题（旧界面很多工具**没有**页头标题，标题在卡片里）
            "title: (function(){var t=document.querySelector("
            "  '.page.is-active .page-title');"
            "  return t?t.textContent.trim():'';})(),"
            #: 占位判定：app.js 的 _renderToolStub 会写「X 面板」
            "isStub: !!(function(){var a=document.querySelector('.page.is-active');"
            "  if(!a) return false;"
            "  var t=a.querySelector('.empty-title');"
            "  return t ? /面板$/.test(t.textContent.trim()) : false;})(),"
            #: ★ P6 起：**旧界面的卡片结构**（ConfigCard 等价物）
            "cfgCards: Array.from(document.querySelectorAll("
            "  '.page.is-active .cfg-card-title'))"
            "  .map(function(t){return t.textContent.trim();}),"
            #: 卡片内的主按钮（旧界面跑在卡片里，不在页头）
            "cfgBtns: Array.from(document.querySelectorAll("
            "  '.page.is-active .cfg-btn'))"
            "  .map(function(b){return b.textContent.trim();}),"
            #: 整页文字（P3 用：工具名在页面任何地方出现就算对）
            "bodyText: (function(){var a=document.querySelector('.page.is-active');"
            "  return a ? a.textContent : '';})(),"
            #: 页面内所有按钮数（不限于卡片内）
            "anyBtnCount: document.querySelectorAll("
            "  '.page.is-active button, .page.is-active .btn').length,"
            #: 带背景的视觉卡片数（各类面板的容器）
            "visualCardCount: document.querySelectorAll("
            "  '.page.is-active .cfg-card, .page.is-active .card-glass, "
            "  .page.is-active .build-card').length,"
            #: ★ 本面板**自己的**卡片选择器命中数（P4 用）
            "ownCardCount: (function(){"
            "  var a=document.querySelector('.page.is-active');"
            "  if(!a) return 0;"
            "  var sel = window.__PANEL_CARD_SEL__ || '.cfg-card';"
            "  return a.querySelectorAll(sel).length;})(),"
            #: ★ 这些是 **P5 自己加的、旧界面没有** 的东西 —— 必须不存在
            "hasPrereq: (function(){var a=document.querySelector('.page.is-active');"
            "  return a ? a.textContent.indexOf('运行前提') >= 0 : false;})(),"
            "hasStateBar: !!document.querySelector("
            "  '.page.is-active .flow-state'),"
            "hasLogBox: !!document.querySelector('.page.is-active .log-box')"
            "})",
            f"panel_{key}",
        )
        d = data if isinstance(data, dict) else {}

        # ── P2：不再是占位 ──
        check(f"{short}.P2", d.get("isStub") is False,
              f"{name}：不是占位面板（isStub={d.get('isStub')}）")

        # ══════════════════════════════════════════════════════════════════
        #  P3（P6 重写）：工具名必须出现在**旧界面放它的位置**
        #
        #  不同工具放标题的位置不一样（都在旧代码里写死的）：
        #
        #    ① auto_combat        → ``ConfigCard("4C 自动战斗", …)`` 卡片标题
        #    ② echo_change        → ``ConfigCard("声骸批量调频", …)`` 卡片标题
        #    ③ nest_sweep         → ``ConfigCard("扫荡残像聚落", …)`` 卡片标题
        #    ④ echo_enhance       → ``StrongBodyLabel("声骸自动强化")`` 标题行
        #    ⑤ gacha              → ``TitleLabel("抽卡记录分析")`` 页面标题
        #    ⑥ character_build    → ``TitleLabel("查询角色练度")`` 页面标题
        #    ⑦ wuwa_library_update→ ``TitleLabel("资源库更新")`` 页面标题
        #
        #  所以判定：**页面里任何地方**出现工具名就算对（textContent 包含）。
        #  这比"指定某个选择器"更结实 —— 换个放法只要名字还在就不会误报。
        # ══════════════════════════════════════════════════════════════════
        body_text = str(d.get("bodyText") or "")
        title = str(d.get("title") or "")
        cards = d.get("cfgCards") or []
        ok_title = (name in title) or (name in body_text) or \
            any(name in str(c) for c in cards)
        check(f"{short}.P3", ok_title,
              f"{name}：标题出现（页头={title!r} / 卡片={cards}）")

        # ══════════════════════════════════════════════════════════════════
        #  P4（P6 重写）：面板必须有**旧界面那种卡片结构**
        #
        #  ⚠ 7 个工具用的卡片类不一样，照旧界面：
        #    ① ② ③ ④ → ``.cfg-card``（ConfigCard 等价物）
        #    ⑤        → ``.gk-*`` 块（旧界面不是卡片式）
        #    ⑥        → ``.build-card``（5 张卡的容器）
        #    ⑦        → ``.lib-status-card``（单张状态卡）
        #
        #  统一判据：**页面里至少有一块带背景的容器**，且有一个按钮。
        # ══════════════════════════════════════════════════════════════════
        cfg_btns = d.get("cfgBtns") or []
        any_btn = int(d.get("anyBtnCount") or 0)
        visual_cards = int(d.get("visualCardCount") or 0)

        #: 各类面板「一张卡」的选择器（和 CSS 里的类名一一对应）
        CARD_SELECTORS = {
            "auto_combat": ".cfg-card",
            "echo_change": ".cfg-card",
            "nest_sweep": ".cfg-card",
            "echo_enhance": ".cfg-card",
            "gacha": ".gk-overview",
            "character_build": ".build-card",
            "wuwa_library_update": ".lib-status-card",
        }
        want_card = CARD_SELECTORS.get(key, ".cfg-card")
        has_own_card = bool(d.get("ownCardCount"))

        ok_skeleton = has_own_card and (len(cfg_btns) >= 1 or any_btn >= 1)
        check(f"{short}.P4", ok_skeleton,
              f"{name}：卡片({want_card})={d.get('ownCardCount')} "
              f"卡片内按钮={cfg_btns} 全部按钮={any_btn} "
              f"（visualCards={visual_cards}）")

        # ── ★ P4b：**绝对不能有「运行前提」**（用户圈出「干掉」）──
        check(f"{short}.P4b", d.get("hasPrereq") is False,
              f"{name}：无「运行前提」块（hasPrereq={d.get('hasPrereq')}"
              f" —— 旧界面没有这块，用户要求删掉）")

        # ── ★ P4c：不能有我们自加的状态条 / 日志区 ──
        #
        #  ⚠ 例外：④ 声骸强化 和 ⑥ 练度 旧界面**有**日志区，
        #  这两个 key 单独放行。
        if key in ("echo_enhance", "character_build"):
            check(f"{short}.P4c", True,
                  f"{name}：旧界面本就有日志区，跳过")
        else:
            check(f"{short}.P4c",
                  d.get("hasStateBar") is False and d.get("hasLogBox") is False,
                  f"{name}：无自加的状态条/日志区"
                  f"（stateBar={d.get('hasStateBar')} logBox={d.get('hasLogBox')}）")

        # ══════════════════════════════════════════════════════════════════
        #  ★ P4d：④ 声骸强化的 **CollapsibleCard 结构**（2026-11-02 加）
        #
        #  只有 ④ 用 ``CollapsibleCard``（``gui/widgets.py`` L591）。用户
        #  上传截图指出 4 处不一致，这条把它们钉死：
        #
        #  ① DOM 顺序必须是 **head → hint → summary → content**
        #     （``summary_label`` 在 content **上方**，收起时也可见）
        #  ② 核心属性 13 个复选框是 **4 列、按列填充**
        #     （``grid.addWidget(box, index % rows, index // rows)``）
        #  ③ 满值锁定 / 自动停止 是**普通 CardWidget**（不是折叠卡），
        #     开关 ``AlignTop``
        #  ④ 「可选属性」的「未选」也是 summary（content 上方）
        # ══════════════════════════════════════════════════════════════════
        if key == "echo_enhance":
            structure = bundle(
                "JSON.stringify({"
                "coreOrder: (function(){"
                "  var c=document.querySelector('.page.is-active .coll-card');"
                "  if(!c) return [];"
                "  return Array.from(c.children).map(function(x){"
                "    return x.className.split(' ')[0];});})(),"
                "gridFlow: (function(){"
                "  var g=document.querySelector("
                "    '.page.is-active .enh-core-grid');"
                "  return g ? getComputedStyle(g).gridAutoFlow : '';})(),"
                "gridRows: (function(){"
                "  var g=document.querySelector("
                "    '.page.is-active .enh-core-grid');"
                "  return g ? getComputedStyle(g).gridTemplateRows : '';})(),"
                "switchAlign: (function(){"
                "  var s=document.querySelector("
                "    '.page.is-active .enh-switch-top');"
                "  return s ? getComputedStyle(s).alignSelf : '';})(),"
                "switchCards: document.querySelectorAll("
                "  '.page.is-active .enh-switch-card').length,"
                "collCards: document.querySelectorAll("
                "  '.page.is-active .coll-card').length"
                "})",
                "enhance_structure",
            )
            s = structure if isinstance(structure, dict) else {}

            #: ① summary 必须在 content **之前**
            order = s.get("coreOrder") or []
            def _idx(name):
                return order.index(name) if name in order else -1
            ok_order = (_idx("coll-head") == 0
                        and _idx("coll-hint") == 1
                        and _idx("coll-summary") == 2
                        and _idx("coll-content") == 3)
            check(f"{short}.P4d", ok_order,
                  f"{name}：CollapsibleCard 顺序 = {order}"
                  f"（期望 head→hint→summary→content，摘要在内容**上方**）")

            #: ② 4 列**按列填充**
            flow = str(s.get("gridFlow") or "")
            rows_css = str(s.get("gridRows") or "")
            check(f"{short}.P4e",
                  "column" in flow and "4" in rows_css,
                  f"{name}：复选框网格 flow={flow!r} rows={rows_css!r}"
                  f"（期望 column + repeat(4, …) —— 旧界面按列填 4 行）")

            #: ③ 满值/自动停止是普通卡 + 开关顶部对齐
            align = str(s.get("switchAlign") or "")
            check(f"{short}.P4f",
                  int(s.get("switchCards") or 0) == 2
                  and "flex-start" in align,
                  f"{name}：满值/自动停止卡 = {s.get('switchCards')} 张，"
                  f"开关 alignSelf={align!r}"
                  f"（期望 2 张普通卡 + flex-start 顶部对齐）")

            #: ④ 可选属性也是 CollapsibleCard（所以 coll-card 共 2 张）
            check(f"{short}.P4g", int(s.get("collCards") or 0) == 2,
                  f"{name}：折叠卡 = {s.get('collCards')} 张"
                  f"（期望 2：核心属性 + 可选属性）")

        # ══════════════════════════════════════════════════════════════════
        #  P5：点**主操作按钮**后有反应
        #
        #  ⚠ 7 个工具的「主按钮」位置/类名各不相同（照旧界面）：
        #    ① ② ③ → ``.cfg-btn-primary``（卡片内）
        #    ④      → 标题行的「运行」（``.enh-title-row .btn``）
        #    ⑤      → 「获取抽卡记录」（``.gk-link-row``）
        #    ⑥      → 卡片内的按钮（``.build-card .btn``）
        #    ⑦      → 「重新检查」（``.lib-status-head``）
        # ══════════════════════════════════════════════════════════════════
        PRIMARY_SELECTOR = {
            "auto_combat": ".page.is-active .cfg-btn-primary",
            "echo_change": ".page.is-active .cfg-btn-primary",
            "nest_sweep": ".page.is-active .cfg-btn-primary",
            "echo_enhance": ".page.is-active .enh-title-row .btn-primary",
            "gacha": ".page.is-active .gk-link-row .btn-primary",
            "character_build": ".page.is-active .build-card .btn",
            "wuwa_library_update": ".page.is-active .lib-status-head .btn",
        }
        selector = PRIMARY_SELECTOR.get(key, ".page.is-active .cfg-btn-primary")

        found = js("String(document.querySelectorAll(" +
                   repr(selector).replace("'", "'") +
                   ").length > 0)")
        if str(found) != "true":
            check(f"{short}.P5", False,
                  f"{name}：没找到主按钮（{selector}）")
            cursor["i"] += 1
            QTimer.singleShot(120, step_next)
            return

        js("(function(){var b=document.querySelector(" +
           repr(selector).replace("'", "'") + ");"
           "if(b) b.click();})()")
        QTimer.singleShot(1300 + pace,
                          lambda: check_run_reaction(key, name, kind))

    def check_run_reaction(key: str, name: str, kind: str = "engine") -> None:
        short = key[:14]
        data = bundle(
            "JSON.stringify({"
            #: 旧界面的状态是**页面上的一行文字**。各工具位置不同，全都要认：
            #:   ``.cfg-state``        —— 红色系（4C / 调频 的 ``state_label``）
            #:   ``.cfg-muted``        —— 灰色（扫荡的 ``_muted(state_label)``）
            #:   ``.gk-status``        —— 抽卡页的状态行
            #:   ``.lib-status-text`` —— 资源库更新的状态文字
            #:
            #: ⚠ 练度页（⑥）**没有**单独的状态行 —— 它的反馈在
            #:   ``.build-log``（日志）和 ``.build-overview-line``（概览）里。
            #:   单列出来，别混进 ``states``（否则概览的数值会被当成"状态"）。
            "states: Array.from(document.querySelectorAll("
            "  '.page.is-active .cfg-state, .page.is-active .cfg-muted, "
            "   .page.is-active .gk-status, .page.is-active .lib-status-text'))"
            "  .map(function(e){return e.textContent.trim();})"
            "  .filter(function(t){return t;}),"
            "buildLogText: (function(){var e=document.querySelector("
            "  '.page.is-active .build-log');"
            "  return e ? e.textContent.trim() : '';})(),"
            "buildOverview: (function(){var e=document.querySelector("
            "  '.page.is-active .build-overview-line');"
            "  return e ? e.textContent.trim() : '';})(),"
            "statusLine: (function(){var e=document.querySelector("
            "  '.page.is-active .gk-status');"
            "  return e ? e.textContent.trim() : '';})(),"
            "notices: document.querySelectorAll("
            "  '.page.is-active .notice').length"
            "})",
            f"panel_run_{key}",
        )
        d = data if isinstance(data, dict) else {}
        states = d.get("states") or []
        status_line = str(d.get("statusLine") or "")
        build_log = str(d.get("buildLogText") or "")
        build_overview = str(d.get("buildOverview") or "")

        #: ⚠ 判定不能太窄（2026-11-02 踩过）：不同工具的状态文案完全不同 ——
        #:   「引擎：就绪 · 点「运行」开始调频」
        #:   「正在检查更新…」（资源库更新）
        #:   「这里显示的是上次同步的缓存…」（练度，只读缓存）
        #:   「自动获取失败（接口未就绪）—— 可以手动粘贴链接。」（抽卡）
        #:
        #: ★ 练度页（⑥）特殊：它**没有状态行** —— 点「刷新数据」只重读缓存，
        #:   反馈在 ``.build-log``（「读取角色练度缓存…」「✓ 读到 21 个角色」）
        #:   和 ``.build-overview-line``（6 项概览）里。所以这两条也算数。
        keywords = ("引擎", "启动", "运行", "就绪", "停止", "占用", "加载",
                    "失败", "分析", "链接", "勾选", "正在", "检查", "更新",
                    "缓存", "同步", "刷新", "数据", "…", "：",
                    #: 练度页日志 / 概览里的字样
                    "读到", "结晶", "声骸", "角色", "日志")
        combined = " ".join(
            [str(s) for s in states] + [status_line, build_log, build_overview]
        ).strip()
        ok = bool(combined) and any(k in combined for k in keywords)
        shown = states[:2] if states else (build_log[:60] or build_overview[:60]
                                           or status_line)
        check(f"{short}.P5", ok,
              f"{name}（{kind}）：点按钮后页面状态文字 = {shown!r}")

        # ── P6：不能把「启动中」误判成「已完成」 ──
        check(f"{short}.P6", "已完成" not in combined,
              f"{name}：点按钮 1.3s 后不应是「已完成」")

        # ── ★ 清理：停掉可能跑起来的任务，别污染下一个面板 ──
        #
        # 3 个 ok-ww 面板共用一个 host（同一时刻只能跑一个）。
        # 不清理的话第 2 个面板必然撞 ``busy``，看起来像"面板坏了"。
        QTimer.singleShot(60, lambda: stop_after(key, name))

    def stop_after(key: str, name: str) -> None:
        """停掉本面板可能启动的任务，为下一个面板腾出引擎。"""
        js("(window.Bridge && Bridge.call('stopOkwwTask'))")
        js("(window.Bridge && Bridge.call('stopTask'))")
        #: ★ 用**轮询**而不是固定 sleep 等引擎释放。
        #:
        #: ``stop_task()`` 只置标志位，**当前动作跑完才退** ——
        #: 动作可能 1 秒也可能 20 秒（一次 OCR 判定 + 点击）。
        #: 固定 700ms 在真实场景（有任务真的在跑）下会偶发不够，
        #: 于是 P8 误报"引擎没释放"，看起来像面板 bug。
        #:
        #: 这里轮询到 ``state !== 'running' 且 runningTask 为空`` 为止，
        #: 最多等 15 秒（验证脚本不该真的等 30 秒）。
        wait_stopped(key, name, deadline=15000)

    def wait_stopped(key: str, name: str, deadline: int) -> None:
        raw = bundle("(window.Bridge && Bridge.call('getOkwwState'))",
                     f"okww_poll_{key}")
        state = ""
        running = ""
        if isinstance(raw, dict):
            state = str(raw.get("state") or "")
            running = str(raw.get("runningTask") or "")

        released = (not running) and state not in ("running",)
        if released or deadline <= 0:
            check_stopped(key, name)
            return
        QTimer.singleShot(300, lambda: wait_stopped(key, name, deadline - 300))

    def check_stopped(key: str, name: str) -> None:
        """P8：★ 跑完之后必须能停下来（否则会污染后续面板/真实使用）。

        这是验证脚本自身的健壮性断言 —— 4 个面板共用一个全局引擎，
        任何一个「停不下来」都会让后面全部显示 ``busy``，
        看起来像"面板全坏了"，实际只是没清理。
        """
        short = key[:14]
        raw = bundle(
            "(window.Bridge && Bridge.call('getOkwwState'))",
            f"okww_after_{key}",
        )
        state = ""
        running = ""
        if isinstance(raw, dict):
            state = str(raw.get("state") or "")
            running = str(raw.get("runningTask") or "")
        idle_ok = (state in ("idle", "ready", "error", "")) and not running
        check(f"{short}.P8", idle_ok,
              f"{name}：停止后引擎已释放（state={state!r} running={running!r}）")

        cursor["i"] += 1
        QTimer.singleShot(200, step_next)

    # ══════════════════════════════════════════════════════════════════════
    def finish_and_quit() -> None:
        try:
            shot_dir = os.path.join(_ROOT, "data", "_shots")
            os.makedirs(shot_dir, exist_ok=True)
            if targets:
                js("App.go('tool:" + targets[0][0] + "', {silent:true})")
        except Exception:  # noqa: BLE001
            pass
        #: ★ 先把结果写出来再退出 —— 直接 ``app.exit()`` 有时会卡住
        #: （QtWebEngine 的渲染进程还在收尾），所以用 ``QTimer`` 兜一层，
        #: 并且**先**调 ``finish()`` 落盘。
        code = finish()
        QTimer.singleShot(80, lambda: _hard_exit(app, code))

    def _hard_exit(app, code: int) -> None:
        """退出应用程序，并确保不会因为 WebEngine 子进程而挂住。

        ## ⚠ 为什么要 ``os._exit``

        实测：``app.exit(code)`` 之后进程**不返回** —— QtWebEngine 的
        渲染子进程还在收尾，主事件循环已经停了但解释器退不出去
        （表现是脚本"跑完了"但 PowerShell 一直不返回，要手动 Ctrl+C）。

        ``view.stop()`` / ``view.close()`` / ``deleteLater()`` 都试过，不够。

        这里的结果**已经落盘**（``finish()`` 里写的 JSON），所以直接
        ``os._exit`` 是安全的 —— 没有待刷的缓冲区需要保留。
        """
        try:
            view.stop()
        except Exception:  # noqa: BLE001
            pass
        try:
            view.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            app.processEvents()
        except Exception:  # noqa: BLE001
            pass
        #: 强制退出，绕过 WebEngine 子进程的清理
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(int(code))

    #: ★ watchdog —— 上一版没有，卡住了只能干等（P2 踩过一次同样的坑）
    #:
    #: headed 模式放慢了节奏，watchdog 也要相应放宽（7 面板 × 2 步 × pace）。
    watchdog_ms = 90_000 + len(targets) * 2 * pace + 20_000
    def watchdog() -> None:
        check("TIMEOUT", False,
              f"超时未完成，已收 {len(RESULTS)} 项（可能某个面板没回调）")
        code = finish()
        _hard_exit(app, code)

    QTimer.singleShot(watchdog_ms, watchdog)

    view.page().loadFinished.connect(
        lambda ok: QTimer.singleShot(2600 + pace, step_next) if ok else None
    )

    return app.exec()


def finish() -> int:
    print("\n" + "=" * 62, flush=True)
    total = len(RESULTS)
    passed = sum(1 for _cid, ok, _note in RESULTS if ok)
    for cid, ok, note in RESULTS:
        if not ok:
            print(f"  FAIL {cid}: {note}", flush=True)
    print(f"结果：{passed}/{total} 通过", flush=True)
    if passed == total and total:
        print("✓ 工具面板全部通过", flush=True)
    else:
        print("✗ 有未通过项，见上面的 FAIL 行", flush=True)
    print("=" * 62, flush=True)

    try:
        out = os.path.join(_ROOT, "data", "_tool_panels_verify.json")
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(
                {"results": [{"id": c, "ok": o, "note": n}
                             for c, o, n in RESULTS],
                 "detail": DETAIL},
                fh, ensure_ascii=False, indent=2, default=str,
            )
            #: ★ **必须 fsync 再关闭**。
            #:
            #: 这个脚本默认用 ``os._exit()`` 强制退出（见 ``_hard_exit``
            #: 的说明 —— QtWebEngine 的渲染子进程会拖住解释器）。
            #: ``os._exit`` **不做缓冲区刷新**，如果文件还在 Python 的
            #: 缓冲里就直接退，JSON 会是空的或截断的。
            #:
            #: ``with`` 块结束时只是把数据交给 OS 页缓存，
            #: 加 ``flush() + os.fsync()`` 才确保落到磁盘。
            fh.flush()
            os.fsync(fh.fileno())
        print(f"详细结果：{out}", flush=True)
    except Exception:  # noqa: BLE001
        pass
    return 0 if passed == total and total else 1


if __name__ == "__main__":
    sys.exit(main())
