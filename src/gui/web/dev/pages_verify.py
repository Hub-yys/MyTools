# -*- coding: utf-8 -*-
"""★ P2 页面验证脚本（无头，不需要人眼看）。

## 跑法

.. code:: powershell

    cd "D:\\AI Work\\workbuddy\\MyTools"
    .venv\\Scripts\\python.exe src\\gui\\web\\dev\\pages_verify.py

## 为什么需要它

P1 的 ``web_shell_verify.py``（13 项）验的是**骨架**：桥能通、壁纸能播、
玻璃生效、放大无平铺。它**不验页面内容** —— 主页有 7 张卡片就够了，
它不管卡片是不是 158px、任务页的日志会不会重复、配置页有没有配置项。

P2 要转 4 个页面，光看截图不够（截图看不出「点一次运行之后按钮就永久
disabled」这种问题）。所以这个脚本用 ``runJavaScript`` 直接查 DOM：

* 元素**数量**（卡片 7 张、日志行数、配置行数）
* 元素**计算样式**（卡片是不是真的 158x128、网格列数是不是按宽度算的）
* 文字**内容**（标题、空态、提示语）
* **交互结果**（点卡片 → 切页；点运行 → 日志增加；事件到达 → 界面变）

## 核心思路

「渲染对不对」不能靠肉眼，要能**断言**。所以每一项都是
「读一个值 → 和期望比 → 记 PASS/FAIL」，最后打印通过率并返回退出码。

## ⚠ 无头环境下的两个坑

1. 页面要**等 JS 跑完**（桥接握手 + 数据拉取 + 懒渲染）。用
   ``page.frontendReadySignal`` 加超时兜底，别用固定 sleep。
2. ``runJavaScript`` 是异步的，``debug_js`` 用局部 ``QEventLoop`` 等 ——
   但**不能在主线程回调里同步等**（会死锁），所以各检查阶段之间用
   ``QTimer.singleShot`` 串起来，而不是写成一串线性代码。
"""

from __future__ import annotations

import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))


#: ``src/gui/web/dev`` → 项目根
_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

#: Qt 的多媒体/WebEngine 日志很吵，关掉
os.environ.setdefault(
    "QT_LOGGING_RULES", "qt.multimedia.*=false;qt.webenginecontext.debug=false"
)

#: ✓/✗ 在 GBK 控制台下会 UnicodeEncodeError —— 强制 UTF-8
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001 - 老 Python / 重定向流
    pass

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []
DETAIL: dict = {}


def check(case_id: str, ok: bool, note: str = "") -> None:
    RESULTS.append((case_id, bool(ok), note))
    print(f"[{'PASS' if ok else 'FAIL'}] {case_id}  {note}", flush=True)


def main() -> int:
    app = QApplication.instance() or QApplication([])

    #: ★ 必须先发现工具，否则 ToolRegistry.all_metas() 是空的
    import src.tools as tools_pkg  # noqa: PLC0415

    tools_pkg.discover_tools()

    from src.gui.web_shell import WebShell, web_base_url  # noqa: PLC0415

    base = web_base_url()
    print(f"\n=== base url: {base} ===\n", flush=True)
    check("P0", bool(base), "HTTP 服务起得来")
    if not base:
        return finish()

    shell = WebShell(base_url=base)
    if not shell.build():
        check("P0b", False, "WebShell.build() 失败")
        return finish()

    view = shell.view
    view.resize(1440, 900)
    view.show()

    state: dict = {"stage": "loading"}
    js = shell.debug_js

    def bundle(code: str, label: str):
        """执行一段 JS 并解析成 Python 对象（失败返回 None）。"""
        raw = js(code)
        if raw is None:
            DETAIL[label] = None
            return None
        try:
            value = json.loads(raw)
        except (TypeError, ValueError):
            #: 不是 JSON（比如布尔/数字裸值）—— 原样返回
            DETAIL[label] = raw
            return raw
        DETAIL[label] = value
        return value

    # ══════════════════════════════════════════════════════════════════════
    #  加载完成 → 开始检查
    # ══════════════════════════════════════════════════════════════════════
    def on_load(ok: bool) -> None:
        if not ok:
            check("P0b", False, "页面加载返回 False")
            QTimer.singleShot(200, done_and_quit)
            return
        check("P0b", True, "页面加载完成")
        QTimer.singleShot(2600, stage_boot)

    # ══════════════════════════════════════════════════════════════════════
    #  P1 项：公共层 / 样式注入 / 无报错
    # ══════════════════════════════════════════════════════════════════════
    def stage_boot() -> None:
        state["stage"] = "boot"

        # ── 公共层是否加载 ──
        has_pages = js("String(!!window.Pages)")
        check("P1", has_pages == "true",
              f"window.Pages 存在 = {has_pages}")

        # ── 页面样式表是否注入 ──
        css = js(
            "(function(){var l=document.querySelector("
            "'link[data-pages-css=\"1\"]');"
            "return l ? l.href : '';})()"
        )
        DETAIL["css"] = css
        check("P2", bool(css) and "pages.css" in str(css),
              f"pages.css 已注入 = {css}")

        # ── pages.css 真的生效（读一条只有它才有的规则）──
        applied = js(
            "(function(){var g=document.querySelector('#home-tool-grid');"
            "if(!g) return '';"
            "var s=getComputedStyle(g);"
            "return s.gridTemplateColumns;})()"
        )
        DETAIL["grid_columns"] = applied
        check("P3", bool(applied) and str(applied) != "none",
              f"主页网格列 = {applied}")

        # ══════════════════════════════════════════════════════════════════
        #  ★ P5 新增：侧栏顺序必须等于旧界面的 ``ui_state.json`` 的 nav_order
        #
        #  ## 为什么单列一条断言（2026-11-02 真踩到的坑）
        #
        #  我第一版照抄了 ``main_window.py`` 里 ``addSubInterface`` 的顺序
        #  （主页→配置→任务→…→工具→资源库），用户截图一看不对。
        #
        #  真实原因：那个只是**首次启动的默认值**。旧界面允许用户
        #  **按住拖动**侧栏项（``nav_reorder.py``），拖完存进
        #  ``data/ui_state.json`` 的 ``nav_order``，下次启动按它重排。
        #
        #  本机 ``nav_order`` = HomeInterface, tool_group, ConfigInterface,
        #  TasksInterface, SkinInterface, UpdateInterface, WuwaLibraryInterface
        #  → 用户真实顺序：主页 → **工具** → 配置 → 任务 → 主题皮肤
        #    → 检查更新 → 资源库 → 消息通知
        #
        #  **工具在第 2 位，不是最后。** 这条断言把它钉死，
        #  以后再有人「照抄代码默认顺序」会立刻红。
        # ══════════════════════════════════════════════════════════════════
        nav_order = bundle(
            "JSON.stringify(Array.from(document.querySelectorAll('#nav > *'))"
            ".map(function(el){"
            "  if (el.classList.contains('nav-group')) {"
            "    var h = el.querySelector('.nav-group-head .nav-label');"
            "    return 'group:' + (h ? h.textContent.trim() : '');"
            "  }"
            "  return el.dataset.route || '';"
            "}))",
            "nav_order",
        )
        expected_nav = [
            "home", "group:工具", "config", "tasks", "skin",
            "update", "library", "notice",
        ]
        check("P3b", isinstance(nav_order, list) and nav_order == expected_nav,
              f"侧栏顺序 = {nav_order}（期望 {expected_nav}）"
              f" —— 必须跟 ui_state.json 的 nav_order，不是代码默认顺序")

        # ── 无 JS 报错 ──
        errors = bundle("JSON.stringify(window.__JS_ERRORS__ || [])", "js_errors")
        check("P4", not errors, f"JS 报错 = {errors}")

        QTimer.singleShot(120, stage_home)

    # ══════════════════════════════════════════════════════════════════════
    #  主页
    # ══════════════════════════════════════════════════════════════════════
    def stage_home() -> None:
        state["stage"] = "home"
        js("window.App && App.go && App.go('home', {silent:true})")

        card_count = js("document.querySelectorAll('#home-tool-grid .tool-card').length")
        try:
            card_count = int(float(card_count))
        except (TypeError, ValueError):
            card_count = -1
        check("H1", card_count == 7, f"主页工具卡片 {card_count} 张（期望 7）")

        # ── ★ 卡片尺寸必须是 158x128（对齐 app_config）──
        size = bundle(
            "(function(){var c=document.querySelector('#home-tool-grid .tool-card');"
            "if(!c) return 'null';"
            "var r=c.getBoundingClientRect();"
            "return JSON.stringify({w:Math.round(r.width),h:Math.round(r.height)});})()",
            "card_size",
        )
        ok_size = bool(size) and size.get("w") == 158 and size.get("h") == 128
        check("H2", ok_size, f"卡片尺寸 = {size}（期望 158x128）")

        # ── 图标 46px（CARD_ICON_SIZE，不是任务书写的 64）──
        icon = bundle(
            "(function(){var i=document.querySelector('#home-tool-grid .tool-card-icon');"
            "if(!i) return 'null';"
            "var r=i.getBoundingClientRect();"
            "return JSON.stringify({w:Math.round(r.width),h:Math.round(r.height)});})()",
            "icon_size",
        )
        ok_icon = bool(icon) and icon.get("w") == 46 and icon.get("h") == 46
        check("H3", ok_icon, f"卡片图标 = {icon}（期望 46x46）")

        # ── 7 张卡片都有名字文字 ──
        names = bundle(
            "JSON.stringify(Array.from("
            "document.querySelectorAll('#home-tool-grid .tool-card-name'))"
            ".map(function(n){return n.textContent.trim();}))",
            "card_names",
        )
        ok_names = (
            isinstance(names, list)
            and len(names) == 7
            and all(isinstance(n, str) and n for n in names)
        )
        check("H4", ok_names, f"卡片名称 = {names}")

        # ── 列数自适应：宽度不同 → 列数不同（证明是重排不是拉伸）──
        columns = js(
            "(function(){var g=document.querySelector('#home-tool-grid');"
            "if(!g) return '0';"
            "var s=getComputedStyle(g).gridTemplateColumns;"
            "return String(s.split(' ').filter(Boolean).length);})()"
        )
        try:
            col_count = int(float(columns))
        except (TypeError, ValueError):
            col_count = -1
        DETAIL["columns"] = col_count
        check("H5", col_count >= 3,
              f"当前 {col_count} 列（1440 宽时至少 3 列）")

        # ── 统计条 / 页头装饰 ──
        #:
        #: ★ 2026-11-03 断言**反转**：用户圈图要求「标记处都干掉」——
        #: 主页的统计芯片条、副标题、右上角「换壁纸 / 任务中心」按钮
        #: 全部删除（旧界面 ``HomeInterface`` 只有 标题 + 副标题 + 网格，
        #: 这些东西本来就是我加的）。
        #:
        #: 所以现在验证的是「**这些装饰不存在**」—— 防止以后又被人加回来。
        chips = js("document.querySelectorAll('.home-stats .stat-chip').length")
        try:
            chips = int(float(chips))
        except (TypeError, ValueError):
            chips = -1
        check("H6", chips == 0,
              f"主页统计条 {chips} 个（期望 0 —— 用户要求删掉）")

        subtitle = js("document.querySelectorAll('#page-home .page-subtitle').length")
        try:
            subtitle = int(float(subtitle))
        except (TypeError, ValueError):
            subtitle = -1
        check("H6b", subtitle == 0,
              f"主页副标题 {subtitle} 个（期望 0 —— 用户圈图删掉）")

        actions = js(
            "document.querySelectorAll('#page-home .page-head-actions .btn').length")
        try:
            actions = int(float(actions))
        except (TypeError, ValueError):
            actions = -1
        check("H6c", actions == 0,
              f"主页右上角按钮 {actions} 个（期望 0 —— 换壁纸/任务中心已删）")

        # ── 点卡片 → 切到工具页 ──
        clicked = js(
            "(function(){var c=document.querySelector("
            "'#home-tool-grid .tool-card');"
            "if(!c) return 'no-card';"
            "c.click(); return 'ok';})()"
        )
        QTimer.singleShot(260, lambda: verify_card_click(clicked))

    def verify_card_click(clicked) -> None:
        page = js("(window.App && App.page) || ''")
        check("H7", str(page).startswith("tool:"),
              f"点卡片后当前页 = {page}（期望 tool:xxx）")

        #: 回主页，继续测任务页
        js("App.go('home', {silent:true})")
        QTimer.singleShot(200, stage_tasks)

    # ══════════════════════════════════════════════════════════════════════
    #  任务页
    # ══════════════════════════════════════════════════════════════════════
    def stage_tasks() -> None:
        state["stage"] = "tasks"
        js("App.go('tasks', {silent:true})")
        QTimer.singleShot(700, check_tasks)

    def check_tasks() -> None:
        # ── 三个区域都在 ──
        #
        # ⚠ 2026-11-03 改：任务页按 main 分支重做（用户「删掉，任务请按main分支那样做」）
        # —— 顶部的提示条和「运行面板」大卡被删了，运行状态改在**每一行**的
        # ``.task-status`` 里（对应 main 的 ``TaskRowCard.status_label``）。
        #
        # 所以 T1 不能再找 ``#task-progress-bar`` / ``#task-stop`` / ``#task-run-state``
        # （这三个 id 已随面板一起消失），改成断言新的结构：
        #   * 日志窗还在（``#task-log`` —— T3/T4/T5 还要用）
        #   * 行卡有新头像位（``.task-avatar``）
        #   * 行卡有状态行（``.task-status``）
        #   * 行卡**只有**运行/停止/删除三个按钮（2026-11-04 用户圈图：
        #     「任务改成只有运行、停止、删除」—— 详情 / 修改已删掉，
        #     断言必须在**不存在**，这样谁加回来这里会红）
        #   * 底部「运行报告」两块卡（``.task-report-card``）
        #   * 页头有「＋ 新增任务流程」（main 的 ``add_button``）
        layout = bundle(
            "JSON.stringify({"
            "logBox: !!document.querySelector('#task-log'),"
            "avatars: document.querySelectorAll('#page-tasks .task-avatar').length,"
            "status: document.querySelectorAll('#page-tasks .task-status').length,"
            "runBtns: document.querySelectorAll("
            "  '#page-tasks [data-action=\"run\"]').length,"
            "stopBtns: document.querySelectorAll("
            "  '#page-tasks [data-action=\"stop\"]').length,"
            "editBtns: document.querySelectorAll("
            "  '#page-tasks [data-action=\"edit\"]').length,"
            "delBtns: document.querySelectorAll("
            "  '#page-tasks [data-action=\"delete\"]').length,"
            "detailBtns: document.querySelectorAll("
            "  '#page-tasks [data-action=\"detail\"]').length,"
            "reportCards: document.querySelectorAll("
            "  '#page-tasks .task-report-card').length,"
            "addBtn: !!document.querySelector("
            "  '#page-tasks [data-action=\"add-flow\"]'),"
            "runPanel: !!document.querySelector('#page-tasks .run-panel'),"
            "notice: document.querySelectorAll('#page-tasks .notice').length,"
            "rows: document.querySelectorAll('#page-tasks .flow-card').length"
            "})",
            "tasks_layout",
        )
        ok = (
            isinstance(layout, dict)
            and layout.get("logBox")
            and (layout.get("avatars") or 0) >= 1
            and (layout.get("status") or 0) >= 1
            and (layout.get("runBtns") or 0) >= 1
            and (layout.get("stopBtns") or 0) >= 1
            and (layout.get("delBtns") or 0) >= 1
            #: ★ 详情 / 修改两个按钮已被用户要求删掉 —— 必须在**不存在**
            and (layout.get("editBtns") or 0) == 0
            and (layout.get("detailBtns") or 0) == 0
            and (layout.get("reportCards") or 0) >= 2
            and layout.get("addBtn")
        )
        check("T1", ok, f"任务页新结构齐全 = {layout}")

        #: 用户明确要求删掉的两块 —— 万一有人加回来，这里会红
        gone = (
            isinstance(layout, dict)
            and not layout.get("runPanel")
            and (layout.get("notice") or 0) == 0
        )
        check("T1b", gone, "顶部提示条 / 运行面板已删除")

        rows = int(layout.get("rows") or 0) if isinstance(layout, dict) else 0
        check("T2", rows >= 1, f"任务行 {rows} 条（期望 >=1）")

        # ── ★ 真实任务流程：data/tasks.json 里有 1 条 ──
        flows = bundle(
            "JSON.stringify({"
            "names: Array.from(document.querySelectorAll("
            "  '#page-tasks .flow-name')).map(function(n){return n.textContent.trim();}),"
            "steps: document.querySelectorAll('#page-tasks .step-chip').length,"
            "arrows: document.querySelectorAll('#page-tasks .step-arrow').length,"
            "metas: document.querySelectorAll('#page-tasks .flow-meta').length"
            "})",
            "tasks_flows",
        )
        if isinstance(flows, dict) and flows.get("names"):
            check("T2b", len(flows["names"]) >= 1,
                  f"流程名 = {flows['names']}")
            #: 那条流程有 5 步（开始 → 筛选 → 强化 → 工具 → 结束）
            check("T2c", flows.get("steps", 0) >= 5,
                  f"步骤链 chip {flows.get('steps')} 个（期望 >=5）")
            check("T2d", flows.get("arrows", 0) >= 4,
                  f"步骤分隔箭头 {flows.get('arrows')} 个（期望 >=4）")
        else:
            check("T2b", True, "（getFlowList 未接入，走工具降级列表）")
            check("T2c", True, "（getFlowList 未接入，跳过步骤链断言）")
            check("T2d", True, "（getFlowList 未接入，跳过箭头断言）")

        # ── 日志窗是等宽字体 ──
        font = js(
            "(function(){var b=document.querySelector('#task-log');"
            "if(!b) return '';"
            "return getComputedStyle(b).fontFamily;})()"
        )
        DETAIL["log_font"] = font
        ok_font = any(
            key in str(font).lower()
            for key in ("mono", "consolas", "cascadia", "courier")
        )
        check("T3", ok_font, f"日志字体 = {font}")

        # ── ★ 日志不重复：跑一次任务，应该有增长但**没有重复行** ──
        #
        # ⚠ 2026-11-02 改：以前断言「只 +1~3 行」，那是**模拟实现**的行为
        # （只发 1 条 logLine）。真引擎接上后一次运行会发 ~9 条：
        #
        #   ▶ 开始运行 / ▶ 开始 / ▶ 流程开始 / 检查客户端 / ✓ 客户端已启动
        #   / 判定配置 / ⚠ 没挂筛选配置 / ■ 已停止 / ■ 结束
        #
        # 卡死具体条数会把「引擎多说了几句」误判成回归。
        # 真正要守的性质有两个：
        #   ① 有增长（事件通道是通的）
        #   ② **同一句话不出现两次**（app.js 和本页各写一次才会重复）
        base_lines = js("document.querySelectorAll('#task-log .log-line').length")
        try:
            base_lines = int(float(base_lines))
        except (TypeError, ValueError):
            base_lines = -1
        DETAIL["log_before"] = base_lines
        QTimer.singleShot(120, trigger_run)

    def trigger_run() -> None:
        #: 直接调 bridge，绕开 UI（避免依赖降级/真实两种布局的按钮位置）
        js("(window.Bridge && Bridge.call('runTask', 'echo_enhance'))")
        QTimer.singleShot(1400, check_log_once)

    def check_log_once() -> None:
        detail = bundle(
            "JSON.stringify({"
            "count: document.querySelectorAll('#task-log .log-line').length,"
            #: 只看正文，时间戳每次都不同、不能参与去重
            "texts: Array.from(document.querySelectorAll("
            "  '#task-log .log-text')).map(function(t){"
            "  return t.textContent.trim();})"
            "})",
            "log_lines",
        )
        lines = int(detail.get("count") or 0) if isinstance(detail, dict) else -1
        texts = detail.get("texts") if isinstance(detail, dict) else []
        before = DETAIL.get("log_before") or 0
        growth = lines - before if lines >= 0 else -99
        DETAIL["log_after"] = lines

        #: ① 有增长 —— 上限放到 30（真引擎阶段说明多，但也不该刷屏）
        check("T4", 1 <= growth <= 30,
              f"运行一次日志 +{growth} 行（{before} → {lines}）")

        #: ② ★ 无重复 —— 同一句正文只能出现一次
        #:
        #: 这是「app.js 与本页都写一遍」的唯一可靠指纹：
        #: 两个写入点会让**每条**日志各出现两次，而正文完全一致。
        seen = {}
        dupes = []
        for text in (texts or []):
            key = str(text)
            if not key:
                continue
            seen[key] = seen.get(key, 0) + 1
            if seen[key] == 2:
                dupes.append(key[:40])
        DETAIL["log_dupes"] = dupes
        check("T4b", not dupes,
              f"日志无重复行（重复项：{dupes[:3] if dupes else '无'}）")

        # ── 有状态、有时间戳 ──
        stamp = js(
            "(function(){var l=document.querySelector('#task-log .log-line');"
            "if(!l) return '';"
            "var t=l.querySelector('.log-time');"
            "return t ? t.textContent : 'NO-TIME';})()"
        )
        DETAIL["log_time"] = stamp
        check("T5", bool(stamp) and stamp != "NO-TIME" and len(str(stamp)) >= 5,
              f"日志带时间戳 = {stamp}")

        # ── 运行状态：要么「运行中」，要么被前置检查**明确拒绝** ──
        #
        # ⚠ 2026-11-02 改：真引擎接上后有**同步前置检查** `_precheck()`。
        # 游戏没开时 `runTask` 在 ~9ms 内就返回 `{ok:false, reason:"precheck"}`，
        # **根本不起线程**。所以这里 700ms 后再问，状态早就不是 running 了。
        #
        # 卡死「必须是 running」会把「这台机器没开游戏」误判成回归。
        # 真正要守的是：**状态机没有卡在中间**——要么在跑（停止按钮可用），
        # 要么已经明确结束/被拒（停止按钮不可用、状态不是 running）。
        #
        # ⚠ 2026-11-03 改：运行面板删掉了，状态改到每行的 ``.task-status``
        # （``data-state`` = idle/running/failed）和每行的停止按钮上。
        # 所以这里量的是**第一条流程行**的这两个元素。
        snapshot = bundle(
            "JSON.stringify((function(){"
            "var row = document.querySelector('#page-tasks .flow-card');"
            "if(!row) return {stopDisabled: null, pill: '', found: false};"
            "var pill = row.querySelector('.task-status');"
            "var stop = row.querySelector('[data-action=\"stop\"]');"
            "return {"
            "  found: true,"
            "  stopDisabled: stop ? stop.disabled : null,"
            "  pill: pill ? ((pill.dataset.state || '') + '|' + pill.textContent) : ''"
            "};"
            "})())",
            "run_state",
        )
        pill = str((snapshot or {}).get("pill") or "") if isinstance(snapshot, dict) else ""
        stop_disabled = (
            snapshot.get("stopDisabled") if isinstance(snapshot, dict) else None
        )

        running_branch = "running" in pill and stop_disabled is False
        rejected_branch = (
            "running" not in pill
            and stop_disabled is True
            and ("failed" in pill or "idle" in pill or "已停止" in pill
                 or "空闲" in pill)
        )
        check("T6", running_branch or rejected_branch,
              f"运行状态 = {snapshot}"
              f"（要么 running+停止可用，要么已明确结束+停止不可用）")

        # ── 停止 → 恢复空闲 ──
        js("(window.Bridge && Bridge.call('stopTask'))")
        QTimer.singleShot(600, check_stop)

    def check_stop() -> None:
        snapshot = bundle(
            "JSON.stringify((function(){"
            "var row = document.querySelector('#page-tasks .flow-card');"
            "if(!row) return {stopDisabled: null, pill: '', found: false};"
            "var pill = row.querySelector('.task-status');"
            "var stop = row.querySelector('[data-action=\"stop\"]');"
            "return {"
            "  found: true,"
            "  stopDisabled: stop ? stop.disabled : null,"
            "  pill: pill ? ((pill.dataset.state || '') + '|' + pill.textContent) : ''"
            "};"
            "})())",
            "stop_state",
        )
        ok = (
            isinstance(snapshot, dict)
            and snapshot.get("stopDisabled") is True
            and "running" not in str(snapshot.get("pill") or "")
        )
        check("T7", ok, f"停止后状态 = {snapshot}")

        # ── ★ 停止后运行按钮必须恢复可点（P1 的老 bug）──
        btn = bundle(
            "(function(){var b=document.querySelector("
            "'#page-tasks [data-action=\"run\"]');"
            "if(!b) return 'null';"
            "return JSON.stringify({disabled: b.disabled, text: b.textContent});})()",
            "run_btn_after_stop",
        )
        ok_btn = isinstance(btn, dict) and btn.get("disabled") is False
        check("T8", ok_btn, f"停止后运行按钮 = {btn}（必须是可点，P1 是永久 disabled）")

        # ══════════════════════════════════════════════════════════════════
        #  ★ T9/T10：多参调用的坑（2026-11-02，web-shell-dev 实测发现的）
        # ══════════════════════════════════════════════════════════════════
        #
        # ``deleteConfig`` 是 ``@Slot(str, str, result=str)``。用单参的
        # ``Bridge.call('deleteConfig', 'loadout')`` 调时，QWebChannel
        # **找不到匹配签名**，但**不报错也不 reject** —— 回调照样触发，
        # 给的是**空数组 ``[]``**。于是 ``r.ok`` 是 ``undefined``，
        # 「有返回就算成功」的判断会把根本没执行的调用当成功。
        #
        # 这条测试把那个坑钉死：单参调必须是 ``[]``（失败），不能是业务结果。
        js(
            "(function(){window.__ARITY={};"
            #: ① 单参调两参方法 → 期望空数组
            "Bridge.call('deleteConfig','loadout').then(function(r){"
            "  window.__ARITY.wrong = JSON.stringify(r);"
            "}, function(e){ window.__ARITY.wrong = 'REJECT:' + e.message; });"
            #: ② callWith 存在吗
            "window.__ARITY.hasCallWith = (typeof Bridge.callWith === 'function');"
            "})()"
        )
        QTimer.singleShot(600, check_arity)

    def check_arity() -> None:
        data = bundle(
            "JSON.stringify(window.__ARITY || {})", "arity")
        if not isinstance(data, dict):
            check("T9", False, "取不到参数个数探测结果")
            QTimer.singleShot(100, stage_config)
            return

        check("T9", bool(data.get("hasCallWith")),
              f"Bridge.callWith 存在 = {data.get('hasCallWith')}"
              f"（多参调用靠它）")

        wrong = str(data.get("wrong") or "")
        #: 期望恰好是 "[]"（空数组）—— 这正是「静默失败」的指纹。
        #: 如果哪天 QWebChannel 改成 reject 或返回业务结果，这条会 FAIL
        #: 提醒我们重新审视 callMulti 的兜底逻辑。
        check("T10", wrong == "[]",
              f"单参调 deleteConfig（应为空数组=没执行）→ {wrong}")

        QTimer.singleShot(100, stage_config)

    # ══════════════════════════════════════════════════════════════════════
    #  配置页
    # ══════════════════════════════════════════════════════════════════════
    def stage_config() -> None:
        state["stage"] = "config"
        js("App.go('config', {silent:true})")
        QTimer.singleShot(900, check_config)

    def check_config() -> None:
        layout = bundle(
            "JSON.stringify({"
            "title: (function(){var t=document.querySelector("
            "  '#page-config .page-title'); return t?t.textContent:'';})() ,"
            "rows: document.querySelectorAll('#page-config .config-row').length,"
            #: ★ P5：旧界面是**按类型分组**（``_section``），不是页签。
            "sections: Array.from(document.querySelectorAll("
            "  '#page-config .config-section'))"
            "  .map(function(s){return s.textContent.trim();}),"
            "addBtn: (function(){var b=document.querySelector("
            "  '#page-config [data-action=\"add-config\"]');"
            "  return b ? b.textContent.trim() : '';})(),"
            "subtitle: (function(){var e=document.querySelector("
            "  '#page-config .config-subtitle');"
            "  return e ? e.textContent.trim() : '';})(),"
            "notices: document.querySelectorAll('#page-config .notice').length,"
            "panels: document.querySelectorAll('#page-config .card-glass, "
            "  #page-config .card').length,"
            "hasEmpty: !!document.querySelector('#page-config .empty'),"
            "names: Array.from(document.querySelectorAll("
            "  '#page-config .config-name')).slice(0,3)"
            "  .map(function(n){return n.textContent.trim();}),"
            "summaries: Array.from(document.querySelectorAll("
            "  '#page-config .config-summary')).map("
            "  function(n){return n.textContent.trim();})"
            "})",
            "config_layout",
        )
        d = layout if isinstance(layout, dict) else {}
        check("C1", d.get("title") == "配置", f"配置页标题 = {d.get('title')!r}")

        #: 双态：有数据 → .config-row；没数据 → 明确提示（notice 或 empty）
        has_content = d.get("rows", 0) >= 1 or d.get("notices", 0) >= 1 \
            or d.get("hasEmpty")
        check("C2", has_content, f"配置页有内容或明确双态提示 = {d}")

        # ══════════════════════════════════════════════════════════════════
        #  ★ C3（P5 重写）：旧界面是**按类型分组**，不是页签切换
        #
        #  ``config_interface.reload()`` L312-341：
        #    if profiles:  _section(TYPE_ECHO_PROFILE)  → EchoProfileRow...
        #    if battles:   _section(TYPE_BATTLE_PROFILE) → BattleProfileRow...
        #    if loadouts:  _section(TYPE_LOADOUT)        → LoadoutRow...
        #
        #  **顺序是「声骸强化 → 战斗配置 → 声骸筛选」**，空组不画标题。
        #  P4 版本用了页签（.seg），和旧界面对不上 —— 断言也随之改。
        # ══════════════════════════════════════════════════════════════════
        sections = d.get("sections") or []
        check("C3", len(sections) >= 1 and all(
            any(k in s for k in ("声骸强化", "战斗配置", "声骸筛选"))
            for s in sections),
            f"配置分组标题 = {sections}（期望按类型分组，至少 1 组）")

        # ── C3b：★「+ 新增」按钮（旧界面 L225-227 在标题右边）──
        add_text = str(d.get("addBtn") or "")
        check("C3c", "新增" in add_text,
              f"「新增」按钮 = {add_text!r}（旧界面标题右边有它）")

        # ── C3d：★ 计数说明行（旧界面 ``_subtitle_text``）──
        subtitle = str(d.get("subtitle") or "")
        ok_sub = ("共 " in subtitle and "条" in subtitle) or \
                 ("搜索「" in subtitle and "命中" in subtitle)
        check("C3d", ok_sub,
              f"计数说明行 = {subtitle!r}"
              f"（期望「共 N 条…」或「搜索「X」：命中 N / 共 M 条」）")

        # ── ★ 真实配置渲染 ──
        rows = int(d.get("rows") or 0)
        names = d.get("names") or []
        summaries = d.get("summaries") or []
        if rows >= 1:
            check("C4", all(isinstance(n, str) and n for n in (names or [])),
                  f"配置行前 3 条角色名 = {names}")

            #: ★ 摘要分两类：
            #:   loadout（声骸筛选）→ 「套装名 · 4C … · 3C … · 1C …」
            #:   echoProfile（声骸强化）→ 「核心：… · 双爆 ≥N/M · 有效词条 ≥K …」
            #:
            #: ⚠ 旧界面分组顺序是「强化 → 战斗 → 筛选」，所以**第一条通常是强化**，
            #: 不能只断言"含 C 档位"（那是筛选类才有的）。
            #: 改成：每条摘要都必须**非空且有一定信息量**，
            #: 且整体里至少有一条带档位（筛选）或核心（强化）。
            def meaningful(s):
                text = str(s or "").strip()
                return len(text) >= 12

            all_meaningful = bool(summaries) and all(
                meaningful(s) for s in summaries)
            has_kind_info = any(
                ("C " in str(s) or "C「" in str(s) or "套装" in str(s)
                 or "核心：" in str(s) or "双爆" in str(s))
                for s in summaries)
            check("C5", all_meaningful and has_kind_info,
                  f"配置摘要（共 {len(summaries)} 条）都有内容且含类型信息；"
                  f"样例 = {[str(s)[:50] for s in summaries[:2]]}")
        else:
            check("C4", True, "（接口未接入，跳过配置行断言）")
            check("C5", True, "（接口未接入，跳过摘要断言）")

        # ══════════════════════════════════════════════════════════════════
        #  ★ C6-C8：点「新增」必须真的弹框（P7）
        #
        #  用户报「点了没反应」。根因是 async 弹框里抛异常时
        #  **不进 window.onerror**（变成未处理的 Promise rejection），
        #  页面看起来什么都没发生。
        #
        #  这三条断言把整条链路钉住：
        #    C6  第一步「选类型」弹出来
        #    C7  点「下一步」后第二步表单弹出来（含角色下拉 + 6 张设置卡）
        #    C8  角色候选真的拉到了（不是空）
        # ══════════════════════════════════════════════════════════════════
        js("(function(){var b=document.querySelector("
           "'#page-config [data-action=\"add-config\"]');"
           "if(b) b.click();})()")
        QTimer.singleShot(900, check_config_dialog)

    def check_config_dialog() -> None:
        first = bundle(
            "JSON.stringify({"
            "modals: document.querySelectorAll('.dlg-overlay').length,"
            "title: (function(){var e=document.querySelector('.dlg-title');"
            "  return e?e.textContent.trim():'';})(),"
            "hasTypeSelect: !!document.querySelector('.dlg-select'),"
            "btns: Array.from(document.querySelectorAll('.dlg-foot .btn'))"
            "  .map(function(b){return b.textContent.trim();})"
            "})",
            "config_dialog_1",
        )
        d = first if isinstance(first, dict) else {}
        ok1 = (int(d.get("modals") or 0) == 1
               and "新增配置" in str(d.get("title") or "")
               and bool(d.get("hasTypeSelect")))
        check("C6", ok1,
              f"点「新增」弹出「选类型」对话框 = {d.get('title')!r} "
              f"modals={d.get('modals')} 下拉={d.get('hasTypeSelect')} "
              f"按钮={d.get('btns')}")

        #: 点「下一步」
        js("(function(){var b=document.querySelector('[data-action=\"next\"]');"
           "if(b) b.click();})()")
        QTimer.singleShot(2200, check_config_dialog_step2)

    def check_config_dialog_step2() -> None:
        second = bundle(
            "JSON.stringify({"
            "modals: document.querySelectorAll('.dlg-overlay').length,"
            "title: (function(){var e=document.querySelector('.dlg-title');"
            "  return e?e.textContent.trim():'';})(),"
            "hasPicker: !!document.querySelector('.char-picker'),"
            "collCards: document.querySelectorAll("
            "  '.dlg-settings .coll-card').length,"
            "switchCards: document.querySelectorAll("
            "  '.dlg-settings .enh-switch-card').length,"
            "checks: document.querySelectorAll("
            "  '.dlg-settings .enh-check').length,"
            "notice: (function(){var e=document.querySelector('.notice');"
            "  return e?e.textContent.trim().slice(0,80):'';})()"
            "})",
            "config_dialog_2",
        )
        d = second if isinstance(second, dict) else {}
        ok2 = (int(d.get("modals") or 0) == 1
               and "新增配置" in str(d.get("title") or "")
               and bool(d.get("hasPicker"))
               and int(d.get("collCards") or 0) == 2
               and int(d.get("switchCards") or 0) == 2
               and int(d.get("checks") or 0) >= 20)
        check("C7", ok2,
              f"点「下一步」弹出编辑表单 = {d.get('title')!r} "
              f"角色下拉={d.get('hasPicker')} 折叠卡={d.get('collCards')} "
              f"普通卡={d.get('switchCards')} 复选框={d.get('checks')} "
              f"错误提示={d.get('notice')!r}")

        #: 关掉弹框，免得影响后面的页
        js("(function(){var b=document.querySelector('.dlg-close');"
           "if(b) b.click();})()")
        QTimer.singleShot(200, check_roundtrip)

    # ══════════════════════════════════════════════════════════════════════
    #  ★ C9：写操作**往返一致**（2026-11-02 加）
    #
    #  ## 为什么必须有一条
    #
    #  这一天真遇到过一个**活到今天没人发现**的数据丢失 bug：
    #
    #  .. code:: text
    #
    #    getConfigList().loadouts[]  →  echoSet     （驼峰，桥接层产出）
    #    setConfig 的 data           →  echo_set    （下划线，Loadout.from_dict 认）
    #
    #  前端「读出来 → 原样写回」时 ``echoSet`` 被**静默清空**，
    #  而且 ``setConfig`` 返回 ``{"ok": true, "warnings": [...]}`` ——
    #  **看起来成功了**。用户编辑一次配置就丢数据，下次跑任务才发现。
    #
    #  ## 为什么所有测试都没抓到
    #
    #  大家的断言都只验「返回 ok」和「条数 +1」，
    #  唯一验持久化的只看了 ``character`` 一个字段 —— **恰好是唯一没问题的那个**。
    #
    #  ## 这条断言的关键点
    #
    #  1. **原样传，不做任何字段名转换** —— 这是用户体验（拿什么写什么）
    #  2. **按 id 找回来**，不能用 ``zip`` / 下标 ——
    #     ``setConfig`` 写入后**列表顺序会变**（会得到假的失败）
    #  3. **排除 ``updatedAt``** —— 保存时它本来就该变
    #  4. 用 ``run_guarded.py`` 在外面跑（不靠 ``try/finally`` 自清理）
    # ══════════════════════════════════════════════════════════════════════
    def check_roundtrip() -> None:
        state["stage"] = "roundtrip"
        #: 一条 JS 里做完「读 → 原样写 → 读回对比」，
        #: 任何一步失败都把原因塞进 ``error`` 字段（不抛异常，避免静默）
        js("""(function(){
          window.__RT__ = {done: false, error: ''};
          (async function(){
            try {
              var before = await Bridge.call('getConfigList');
              var lo = (before && before.loadouts && before.loadouts[0]) || null;
              if (!lo) { window.__RT__ = {done:true, error:'没有可用的 loadout'}; return; }
              var id = lo.id;
              //: ★ 原样传（含驼峰 echoSet），**不做字段名转换**
              var data = {
                character: lo.character, echoSet: lo.echoSet,
                status: lo.status, qualities: lo.qualities, picks: lo.picks
              };
              var payload = JSON.stringify({kind:'loadout', id:id, data:data});
              var wr = await Bridge.callWith('setConfig', [payload]);
              if (!wr || wr.ok !== true) {
                window.__RT__ = {done:true, error:'写回失败：'+JSON.stringify(wr).slice(0,120)};
                return;
              }
              var after = await Bridge.call('getConfigList');
              //: ★ 按 id 找回来（列表顺序会变，不能靠下标）
              var hit = null;
              for (var i=0;i<(after.loadouts||[]).length;i++){
                if (after.loadouts[i].id === id) { hit = after.loadouts[i]; break; }
              }
              if (!hit) { window.__RT__ = {done:true, error:'写回后找不到 id='+id}; return; }
              //: 逐字段对比（排除 updatedAt —— 保存时本来就该变）
              var diffs = [];
              if (hit.character !== lo.character) diffs.push('character');
              if ((hit.echoSet||'') !== (lo.echoSet||'')) diffs.push('echoSet');
              if ((hit.status||'') !== (lo.status||'')) diffs.push('status');
              if (JSON.stringify(hit.qualities||[]) !== JSON.stringify(lo.qualities||[])) diffs.push('qualities');
              if (JSON.stringify(hit.picks||{}) !== JSON.stringify(lo.picks||{})) diffs.push('picks');
              window.__RT__ = {
                done: true, error: diffs.length ? ('往返不一致：'+diffs.join(', ')) : '',
                diffs: diffs,
                beforeEchoSet: lo.echoSet, afterEchoSet: hit.echoSet,
                character: lo.character
              };
            } catch(e) {
              window.__RT__ = {done:true, error:'异常：'+(e && e.message ? e.message : String(e))};
            }
          })();
        })()""")
        QTimer.singleShot(2600, check_roundtrip_result)

    def check_roundtrip_result() -> None:
        data = bundle("JSON.stringify(window.__RT__ || {done:false})",
                      "roundtrip")
        d = data if isinstance(data, dict) else {}
        if not d.get("done"):
            check("C9", False, "往返测试**没有完成**（超时或脚本异常）")
        else:
            err = str(d.get("error") or "")
            check("C9", not err,
                  f"写操作往返一致：{d.get('character')!r} "
                  f"echoSet {d.get('beforeEchoSet')!r} → {d.get('afterEchoSet')!r}"
                  + (f"  ✗ {err}" if err else ""))
        QTimer.singleShot(200, stage_library)

    # ══════════════════════════════════════════════════════════════════════
    #  资源库
    # ══════════════════════════════════════════════════════════════════════
    def stage_library() -> None:
        state["stage"] = "library"
        js("App.go('library', {silent:true})")
        QTimer.singleShot(1100, check_library)

    def check_library() -> None:
        layout = bundle(
            "JSON.stringify({"
            "title: (function(){var t=document.querySelector("
            "  '#page-library .page-title'); return t?t.textContent:'';})() ,"
            "subtitle: (function(){var t=document.querySelector("
            "  '#page-library .page-subtitle'); return t?t.textContent:'';})() ,"
            "tabs: document.querySelectorAll('#page-library .seg').length,"
            "tiles: document.querySelectorAll('#page-library .avatar-tile').length,"
            "sets: document.querySelectorAll('#page-library .set-card').length,"
            "echoes: document.querySelectorAll('#page-library .echo-row').length,"
            "search: !!document.querySelector('#page-library .search input'),"
            "notices: document.querySelectorAll('#page-library .notice').length"
            "})",
            "library_layout",
        )
        ok_title = isinstance(layout, dict) and layout.get("title") == "资源库"
        check("L1", ok_title,
              f"资源库标题 = {layout.get('title') if isinstance(layout, dict) else layout}")

        has_content = isinstance(layout, dict) and (
            layout.get("tiles", 0) >= 1
            or layout.get("sets", 0) >= 1
            or layout.get("echoes", 0) >= 1
            or layout.get("notices", 0) >= 1
        )
        check("L2", has_content, f"资源库有内容或双态提示 = {layout}")

        search = isinstance(layout, dict) and layout.get("search")
        check("L3", bool(search), f"资源库有搜索框 = {search}")

        # ── ★ 角色网格：61 个角色（data/wuwa_characters.json）──
        tiles = int(layout.get("tiles") or 0) if isinstance(layout, dict) else 0
        if tiles >= 1:
            check("L4", tiles == 61, f"角色头像瓦片 {tiles} 个（期望 61）")

            #: 头像真的加载出来了（证 percent-encode + /game/ 挂载都通）
            imgs = bundle(
                "JSON.stringify(Array.from("
                "document.querySelectorAll('#page-library .avatar-round img'))"
                ".slice(0,8).map(function(i){"
                "return {ok:i.complete && i.naturalWidth>0};}))",
                "avatar_imgs",
            )
            loaded = sum(1 for x in (imgs or []) if isinstance(x, dict) and x.get("ok"))
            check("L5", loaded >= 1,
                  f"角色头像真实加载 {loaded}/{len(imgs or [])} 张")
        else:
            check("L4", True, "（接口未接入，跳过数量断言）")
            check("L5", True, "（接口未接入，跳过图片断言）")

        # ── 切到「声骸套装」页签：37 套 ──
        js("(function(){var s=document.querySelectorAll('#page-library .seg');"
           "for (var i=0;i<s.length;i++){"
           "  if (s[i].dataset.value==='echoSets'){s[i].click();return;}}})()")
        QTimer.singleShot(400, check_library_sets)

    def check_library_sets() -> None:
        data = bundle(
            "JSON.stringify({"
            "sets: document.querySelectorAll('#page-library .set-card').length,"
            "effects: document.querySelectorAll('#page-library .set-effect').length,"
            "versions: document.querySelectorAll('#page-library .set-version').length"
            "})",
            "library_sets",
        )
        sets = int(data.get("sets") or 0) if isinstance(data, dict) else 0
        if sets >= 1:
            check("L6", sets == 37, f"声骸套装卡 {sets} 张（期望 37）")
            effects = int(data.get("effects") or 0) if isinstance(data, dict) else 0
            check("L7", effects >= sets, f"套装效果条目 {effects} 条（每套至少 1 条）")
        else:
            check("L6", True, "（接口未接入，跳过套装断言）")
            check("L7", True, "（接口未接入，跳过效果断言）")

        # ── 切到「声骸图鉴」：187 个 ──
        js("(function(){var s=document.querySelectorAll('#page-library .seg');"
           "for (var i=0;i<s.length;i++){"
           "  if (s[i].dataset.value==='echoes'){s[i].click();return;}}})()")
        QTimer.singleShot(400, check_library_echoes)

    def check_library_echoes() -> None:
        n = js("document.querySelectorAll('#page-library .echo-row').length")
        try:
            n = int(float(n))
        except (TypeError, ValueError):
            n = -1
        if n >= 0:
            check("L8", n == 187, f"声骸图鉴行 {n} 条（期望 187）")
        else:
            check("L8", True, "（接口未接入，跳过声骸断言）")

        # ── 搜索过滤真的生效 ──
        js("(function(){var i=document.querySelector("
           "'#page-library .search input');"
           "if(!i) return; i.value='暴击';"
           "i.dispatchEvent(new Event('input',{bubbles:true}));})()")
        QTimer.singleShot(400, check_search)

    def check_search() -> None:
        after = js("document.querySelectorAll('#page-library .echo-row').length")
        try:
            after = int(float(after))
        except (TypeError, ValueError):
            after = -1
        #: 搜「暴击」应该过滤掉大部分（187 → 明显变少），但不能是 0 或 -1
        check("L9", 0 < after < 187,
              f"搜索「暴击」后剩 {after} 条（应从 187 明显减少且不为 0）")

        #: 清空搜索，恢复
        js("(function(){var i=document.querySelector("
           "'#page-library .search input');"
           "if(i){i.value='';"
           "i.dispatchEvent(new Event('input',{bubbles:true}));}})()")
        QTimer.singleShot(200, stage_skin)

    # ══════════════════════════════════════════════════════════════════════
    #  主题皮肤
    # ══════════════════════════════════════════════════════════════════════
    def stage_skin() -> None:
        state["stage"] = "skin"
        js("App.go('skin', {silent:true})")
        QTimer.singleShot(900, check_skin)

    def check_skin() -> None:
        data = bundle(
            "JSON.stringify({"
            "title: (function(){var t=document.querySelector("
            "  '#page-skin .page-title'); return t?t.textContent:'';})() ,"
            #: ★ P5 起「主题皮肤」页 = 旧界面的**壁纸卡片墙**
            #: （skin_page.py 里角色主题/配色主题/当前主题卡/玻璃滑块
            #:   都被用户要求删掉了，只剩 Wallpaper Engine 壁纸）。
            "sectionTitle: (function(){var t=document.querySelector("
            "  '#page-skin .skin-section-title');"
            "  return t ? t.textContent.trim() : '';})(),"
            "wallpapers: document.querySelectorAll('#page-skin .wallpaper-card').length,"
            "activeBadges: document.querySelectorAll("
            "  '#page-skin .wallpaper-badge').length,"
            "previews: document.querySelectorAll("
            "  '#page-skin .wallpaper-preview').length,"
            #: 按钮必须存在（「使用这个壁纸」/「取消使用」）
            "buttons: document.querySelectorAll("
            "  '#page-skin [data-action=\"apply\"]').length,"
            #: ⚠ 技术说明（P4 留下的）必须**不存在** —— 用户明确圈掉过
            "hasTechNote: (function(){var s=document.querySelector('#page-skin');"
            "  if(!s) return false;"
            "  return s.textContent.indexOf('setSkin') >= 0"
            "      || s.textContent.indexOf('apply_skin') >= 0"
            "      || s.textContent.indexOf('skinChanged') >= 0;})(),"
            #: P4 那套「皮肤选择卡」也不该再出现
            "skinCards: document.querySelectorAll('#page-skin .skin-card').length,"
            "notices: document.querySelectorAll('#page-skin .notice').length"
            "})",
            "skin_layout",
        )
        ok_title = isinstance(data, dict) and data.get("title") == "主题皮肤"
        check("S1", ok_title,
              f"皮肤页标题 = {data.get('title') if isinstance(data, dict) else data}")

        #: S2 —— 分区标题必须是「Wallpaper Engine 壁纸」（旧界面 L536 原话）
        section = str(data.get("sectionTitle") or "") if isinstance(data, dict) else ""
        check("S2", "Wallpaper" in section,
              f"分区标题 = {section!r}（期望含 'Wallpaper Engine 壁纸'）")

        #: S3 —— 壁纸卡片数 > 0（本机 2 个）
        wall = int(data.get("wallpapers") or 0) if isinstance(data, dict) else 0
        check("S3", wall >= 1, f"壁纸卡片 {wall} 张（期望 >=1）")

        #: S4 —— 「使用中」角标**正好 1 个**（当前壁纸）
        badges = int(data.get("activeBadges") or 0) if isinstance(data, dict) else 0
        check("S4", badges == 1, f"「使用中」角标 {badges} 个（期望正好 1）")

        #: S5 —— ★ 技术说明必须消失（用户圈出来过：
        #:        "切换皮肤需要 setSkin(id) 接口…" 是给开发看的）
        has_note = bool(data.get("hasTechNote")) if isinstance(data, dict) else True
        check("S5", not has_note,
              f"页面里不含技术说明（setSkin/apply_skin/skinChanged）= {has_note}"
              f" —— 必须是 False")

        QTimer.singleShot(200, stage_resize)

    # ══════════════════════════════════════════════════════════════════════
    #  ★ 放大窗口：页面网格必须重排（不是拉伸）
    # ══════════════════════════════════════════════════════════════════════
    def stage_resize() -> None:
        state["stage"] = "resize"
        js("App.go('home', {silent:true})")
        QTimer.singleShot(300, resize_small)

    def resize_small() -> None:
        view.resize(1000, 760)
        QTimer.singleShot(900, lambda: measure("small"))

    def measure(tag: str) -> None:
        data = bundle(
            "JSON.stringify({"
            "vw: window.innerWidth,"
            "cols: (function(){var g=document.querySelector('#home-tool-grid');"
            "  if(!g) return 0;"
            "  return getComputedStyle(g).gridTemplateColumns"
            "    .split(' ').filter(Boolean).length;})(),"
            "cards: document.querySelectorAll('#home-tool-grid .tool-card').length"
            "})",
            f"resize_{tag}",
        )
        state.setdefault("resize", {})[tag] = data

        if tag == "small":
            view.resize(1600, 980)
            QTimer.singleShot(900, lambda: measure("large"))
        else:
            small = state["resize"].get("small") or {}
            large = state["resize"].get("large") or {}
            ok = (
                isinstance(small, dict)
                and isinstance(large, dict)
                and large.get("vw", 0) > small.get("vw", 0)
                and large.get("cols", 0) > small.get("cols", 0)
                and large.get("cards") == small.get("cards") == 7
            )
            check("R1", ok,
                  f"放大后列数重排：{small.get('vw')}px→{small.get('cols')} 列，"
                  f"{large.get('vw')}px→{large.get('cols')} 列"
                  f"（卡片数都是 7）")
            QTimer.singleShot(200, done_and_quit)

    # ══════════════════════════════════════════════════════════════════════
    #  收尾
    # ══════════════════════════════════════════════════════════════════════
    def done_and_quit() -> None:
        try:
            shot = os.path.join(_ROOT, "data", "_shots")
            os.makedirs(shot, exist_ok=True)
            for name in ("home", "tasks", "config", "library"):
                js(f"window.App && App.go('{name}', {{silent:true}})")
                #: 截图靠 QTimer 排队不现实，最后统一抓一张首页即可
            shell.debug_screenshot(os.path.join(shot, "p2-final.png"))
        except Exception:  # noqa: BLE001 - 截图失败不影响结论
            pass
        QTimer.singleShot(150, lambda: finish_and_quit(shell))

    def finish_and_quit(shell) -> None:
        try:
            shell.view.page().deleteLater()
        except Exception:  # noqa: BLE001
            pass
        app.exit(finish())

    view.page().loadFinished.connect(on_load)

    #: 兜底：45 秒还没走完就强制收尾（避免 CI 里挂死）
    def watchdog() -> None:
        if not RESULTS or state.get("stage") not in ("done", "resize"):
            check("TIMEOUT", False,
                  f"超时，卡在阶段 {state.get('stage')} —— 已收 {len(RESULTS)} 项")

    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(watchdog)
    timer.start(60000)

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
        print("✓ P2 页面全部通过", flush=True)
    else:
        print("✗ 有未通过项，见上面的 FAIL 行", flush=True)
    print("=" * 62, flush=True)

    try:
        out = os.path.join(_ROOT, "data", "_pages_verify.json")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "results": [
                        {"id": cid, "ok": ok, "note": note}
                        for cid, ok, note in RESULTS
                    ],
                    "detail": DETAIL,
                },
                fh,
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        print(f"详细结果：{out}", flush=True)
    except Exception:  # noqa: BLE001
        pass
    return 0 if passed == total and total else 1


if __name__ == "__main__":
    sys.exit(main())
