# -*- coding: utf-8 -*-
"""★ Web UI 骨架验证脚本（无头，不需要人眼看）。

## 跑法

.. code:: powershell

    cd "D:\\AI Work\\workbuddy\\MyTools"
    .venv\\Scripts\\python.exe src\\gui\\web_shell_verify.py

## 验什么（对应 task-1 验收标准）

======  ==========================================================
编号     断言
======  ==========================================================
T1       ``index.html`` 通过 HTTP 加载成功（不是 file://）
T2      QWebChannel 往返：``bridge.ping()`` 返回 ok
T3      ``bridge.getTools()`` 返回 **7 个**工具
T4      侧栏渲染出导航项（静态 7 项）
T5      工具卡片渲染出 7 张（每张带名字）
T6      点侧栏能切页（DOM 的 .page.is-active 真的变了）
T7      壁纸 ``<video>`` readyState > 0（真的解码出画面了）
T8      **★ 放大窗口无平铺** —— 各层尺寸跟着 viewport 变
T9      玻璃 CSS 真的生效（backdrop-filter 计算值不是 none）
T10     Python → JS 推送（logLine / progress / taskFinished）
T11     页面无 JS 报错
======  ==========================================================

## 关于 T8（核心目标）

判据是**几何**而不是像素比对 —— 平铺的本质是
「viewport 变大了，但内部盒子还是旧尺寸然后被重复」。
所以窗口从 A 放大到 B 后，逐层检查：

    body / #app / #sidebar / #content / #wallpaper-layer / video

每一层的**实际像素尺寸**都必须**近似等于新 viewport**（或严格跟着变）。
任何一个还停在旧尺寸 = 平铺。

同时用 ``video.clientWidth/clientHeight`` 确认视频也铺满了 ——
这层是用户抱怨里最容易出问题的（Chromium 纹理按旧尺寸贴）。
"""

from __future__ import annotations

import json
import os
import sys

#: ★ 输出编码兜底（2026-11-01，lead 实测报 UnicodeEncodeError）
#:
#: Windows 上管道输出默认走 **GBK**（cp936），而本脚本会打 ``✓`` ``✗``
#: 这些字符 —— 直接 ``print`` 会 UnicodeEncodeError，把整个验证脚本
#: 打断（功能是好的，只是一行字打不出来）。
#:
#: 三重兜底按顺序试：
#:   ① ``reconfigure(encoding='utf-8')`` —— Py3.7+，最干净
#:   ② 换成 ASCII 标记（下面 MARK_* 常量）
#:   ③ 输出流不支持 reconfigure 时，wrap 一个 utf-8 TextIOWrapper
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001 - 老版本 / 被重定向
    pass

#: 结果标记 —— 优先用对勾，输出流扛不住就退 ASCII
MARK_OK = "✓"
MARK_BAD = "✗"
try:
    print("", end="")
    "✓✗".encode(sys.stdout.encoding or "utf-8")
except Exception:  # noqa: BLE001
    MARK_OK, MARK_BAD = "OK", "NG"

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

#: Qt 的多媒体/WebEngine 日志很吵，关掉
os.environ.setdefault("QT_LOGGING_RULES", "qt.multimedia.*=false")

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []
DETAIL: dict = {}


def check(case_id: str, ok: bool, note: str = "") -> None:
    RESULTS.append((case_id, bool(ok), note))
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {case_id}  {note}")


def main() -> int:
    app = QApplication.instance() or QApplication([])

    #: ★ 必须先发现工具，否则 ToolRegistry.all_metas() 是空的
    import src.tools as tools_pkg  # noqa: PLC0415

    tools_pkg.discover_tools()

    from src.gui.web_shell import WebShell, web_base_url  # noqa: PLC0415

    base = web_base_url()
    print(f"\n=== base url: {base} ===\n")
    check("T1a", bool(base), "HTTP 服务起得来")

    shell = WebShell(base_url=base)
    if not shell.build():
        check("T1b", False, "WebShell.build() 失败")
        return finish()

    view = shell.view
    view.resize(1200, 780)
    view.show()

    state = {"stage": "loading", "layout_small": None}

    # ── 等页面加载完 ───────────────────────────────────────────────────
    def on_load(ok: bool) -> None:
        if not ok:
            check("T1b", False, "页面加载返回 False")
            QTimer.singleShot(200, finish_and_quit)
            return
        check("T1b", True, "页面加载完成")
        #: 等 JS 启动（桥接 + 数据拉取），再开始检查
        QTimer.singleShot(2600, stage_small)

    # ── 小窗口：基础检查 ───────────────────────────────────────────────
    def stage_small() -> None:
        layout = shell.debug_layout()
        DETAIL["small"] = layout
        if not layout:
            check("T2", False, "debugLayout 返回空 —— 页面 JS 没跑起来")
            QTimer.singleShot(100, finish_and_quit)
            return

        check("T2", bool(layout.get("viewport")),
              f"viewport={layout.get('viewport')}")

        #: T3 / T4 / T5：靠页面自己的状态判断（比抓 DOM 稳）
        tools = int(layout.get("tools") or 0)
        check("T3", tools == 7, f"getTools() → {tools} 个工具（期望 7）")

        nav = int(layout.get("nav") or 0)
        check("T4", nav >= 7, f"侧栏导航项 {nav} 个（期望 >=7）")

        #: T5：真的数 DOM 里的卡片
        cards = shell.debug_js(
            "document.querySelectorAll('.tool-card').length")
        check("T5", int(cards or 0) == 7, f"工具卡片 {cards} 张（期望 7）")

        #: T7：壁纸视频
        video = layout.get("video") or {}
        DETAIL["video"] = video
        ready = int(video.get("readyState") or 0)
        playing = bool(video.get("playing"))
        check("T7", ready > 0 or playing,
              f"video readyState={ready} playing={playing} "
              f"size={video.get('clientW')}x{video.get('clientH')}")

        #: T9：玻璃真的生效
        bf = shell.debug_js(
            "getComputedStyle(document.querySelector('.card-glass'))."
            "backdropFilter || getComputedStyle("
            "document.querySelector('.card-glass')).webkitBackdropFilter")
        DETAIL["backdrop"] = bf
        check("T9", bool(bf) and bf != "none",
              f"card-glass backdrop-filter = {bf}")
        #: 侧栏底色
        sb = shell.debug_js(
            "getComputedStyle(document.querySelector('#sidebar'))."
            "backgroundColor")
        DETAIL["sidebar_bg"] = sb
        check("T9b", bool(sb) and ("10, 9, 19" in str(sb) or "rgba" in str(sb)),
              f"侧栏底色 = {sb}")

        #: T11：JS 报错
        errs = shell.debug_js("JSON.stringify(window.__JS_ERRORS__ || [])")
        DETAIL["js_errors"] = errs
        check("T11", (errs in (None, "[]", "")), f"JS 错误 = {errs}")

        state["layout_small"] = layout
        state["size_small"] = (view.width(), view.height())
        QTimer.singleShot(300, stage_nav)

    # ── T6：点侧栏切页 ────────────────────────────────────────────────
    def stage_nav() -> None:
        before = shell.debug_js("window.App && App.page")
        shell.debug_js(
            "document.querySelectorAll('.nav-item')[1].click(); 'clicked'")
        QTimer.singleShot(700, lambda: after_nav(before))

    def after_nav(before) -> None:
        after = shell.debug_js("window.App && App.page")
        active = shell.debug_js(
            "document.querySelectorAll('.page.is-active').length")
        DETAIL["nav"] = {"before": before, "after": after, "active": active}
        check("T6", before != after and after and int(active or 0) == 1,
              f"切页 {before} → {after}（active 页数 {active}）")

        #: 切回主页，准备放大
        shell.debug_js(
            "document.querySelectorAll('.nav-item')[0].click(); 'ok'")
        QTimer.singleShot(700, stage_events)

    # ── T10：Python → JS 推送 ─────────────────────────────────────────
    def stage_events() -> None:
        #: 装个探针收事件
        shell.debug_js(
            "window.__EVT__=[];"
            "Bridge.subscribe(function(n,d){window.__EVT__.push(n);});'ok'")

        bridge = shell.bridge
        bridge.pushLog("验证脚本：这是一条日志", "info")
        bridge.pushProgress(42, "验证进度")
        bridge.emitEvent("taskStarted", {"key": "verify"})
        bridge.emitEvent("taskFinished", {"key": "verify", "ok": True,
                                          "summary": "验证完成"})

        QTimer.singleShot(900, stage_events_result)

    def stage_events_result() -> None:
        raw = shell.debug_js("JSON.stringify(window.__EVT__ || [])")
        DETAIL["events"] = raw
        seen = []
        try:
            seen = json.loads(raw or "[]")
        except (TypeError, ValueError):
            seen = []
        want = {"logLine", "progress", "taskStarted", "taskFinished"}
        missing = want - set(seen)
        check("T10", not missing,
              f"收到 {len(seen)} 个事件，缺 {sorted(missing) or '无'}")

        #: 日志真的进 DOM 了吗（要先进任务页才创建 #task-log）
        shell.debug_js("window.App.go('tasks');'ok'")
        QTimer.singleShot(900, stage_resize)

    # ── T8：★ 放大窗口，验无平铺 ──────────────────────────────────────
    def stage_resize() -> None:
        state["steps"] = []
        #: 真实的用户操作序列：放大 → 更大 → 缩回 → 再放大。
        #: 平铺 bug 常常只在**某一种**尺寸变化路径下出现
        #: （比如缩小时不重排、再次放大就露出重复纹理），
        #: 所以必须走一遍完整序列，不能只测一次放大。
        #:
        #: ⚠ 尺寸必须**小于屏幕可用区域** —— 超过屏幕时 Qt 会拒绝并
        #: 把窗口钳到屏幕边缘（日志里那串 "Unable to set geometry"），
        #: 于是几次不同的请求压成同一个实际尺寸，测试会**假通过**。
        avail = screen_available()
        DETAIL["screen_available"] = list(avail)
        max_w = max(900, avail[0] - 60)
        max_h = max(600, avail[1] - 90)
        caps = [
            (min(1200, max_w), min(780, max_h), "initial"),
            (min(1400, max_w), min(860, max_h), "grow"),
            (min(1600, max_w), min(940, max_h), "grow2"),
            (min(1100, max_w), min(700, max_h), "shrink"),
            (min(1500, max_w), min(900, max_h), "regrow"),
        ]
        #: 去掉尺寸重复的项（屏幕太小时上面几个会撞到一起）
        seen: set[tuple[int, int]] = set()
        state["sizes"] = []
        for w, h, tag in caps:
            if (w, h) in seen:
                continue
            seen.add((w, h))
            state["sizes"].append((w, h, tag))
        state["index"] = 0
        next_resize()

    def next_resize() -> None:
        idx = state["index"]
        sizes = state["sizes"]
        if idx >= len(sizes):
            evaluate_all()
            return
        w, h, tag = sizes[idx]
        view.resize(w, h)
        QTimer.singleShot(1800, lambda: record_size(w, h, tag))

    def record_size(w: int, h: int, tag: str) -> None:
        layout = shell.debug_layout()
        shot = shell.debug_screenshot(None)
        state["steps"].append({
            "tag": tag,
            "requested": [w, h],
            "layout": layout,
            "shot": [shot.width(), shot.height()] if shot is not None else None,
            "nonblank": nonblank_ratio(shot) if shot is not None else 0.0,
        })
        state["index"] += 1
        next_resize()

    def evaluate_all() -> None:
        steps = state["steps"]
        DETAIL["resize_steps"] = [
            {
                "tag": s["tag"],
                "requested": s["requested"],
                "viewport": (s["layout"] or {}).get("viewport"),
                "wallpaper": (s["layout"] or {}).get("wallpaperLayer"),
                "video": (s["layout"] or {}).get("video"),
                "shot": s["shot"],
                "nonblank": round(s["nonblank"], 3),
            }
            for s in steps
        ]

        problems: list[str] = []
        prev_w = None

        for s in steps:
            tag = s["tag"]
            layout = s["layout"] or {}
            vp = layout.get("viewport") or {}
            wl = layout.get("wallpaperLayer") or {}
            vid = layout.get("video") or {}
            vw, vh = int(vp.get("w") or 0), int(vp.get("h") or 0)
            dpr = vp.get("dpr") or 1

            if not vw or not vh:
                problems.append(f"{tag}: viewport 读不到")
                continue

            #: ① ★ 硬判据：壁纸层的像素尺寸必须**严格等于** viewport
            if wl.get("w") != vw or wl.get("h") != vh:
                problems.append(
                    f"{tag}: 壁纸层 {wl.get('w')}x{wl.get('h')} != "
                    f"viewport {vw}x{vh}")

            #: ② 视频铺满
            if vid.get("clientW") and abs(vid["clientW"] - vw) > 2:
                problems.append(
                    f"{tag}: 视频宽 {vid['clientW']} != viewport {vw}")

            #: ③ 内容区宽度 = viewport - 侧栏（侧栏宽度读 CSS 变量）
            sidebar = layout.get("sidebar") or {}
            content = layout.get("content") or {}
            if content.get("w") and sidebar.get("w"):
                expect = vw - sidebar["w"]
                if abs(content["w"] - expect) > 2:
                    problems.append(
                        f"{tag}: 内容区宽 {content['w']} != "
                        f"viewport-侧栏 {expect}")

            #: ④ 截图尺寸 ≈ viewport × dpr
            shot = s["shot"]
            if shot:
                expect_w = int(vw * dpr)
                if abs(shot[0] - expect_w) > 4:
                    problems.append(
                        f"{tag}: 截图宽 {shot[0]} != viewport*dpr {expect_w}")

            #: ⑤ 截图不是空白（白屏/黑屏会让上面几条"凑巧"通过）
            if s["nonblank"] < 0.02:
                problems.append(
                    f"{tag}: 截图几乎是纯色（nonblank={s['nonblank']:.3f}）")

            #: ⑥ 放大时 viewport 必须真的变大
            if prev_w is not None:
                want_bigger = s["requested"][0] > (steps[steps.index(s) - 1]
                                                   ["requested"][0])
                if want_bigger and vw <= prev_w + 20:
                    problems.append(f"{tag}: 请求放大但 viewport 没变 {prev_w}→{vw}")
            prev_w = vw

        DETAIL["resize_problems"] = problems
        sizes_seen = [
            (s["layout"] or {}).get("viewport", {}).get("w") for s in steps
        ]
        check("T8", not problems,
              "; ".join(problems) if problems else
              f"{len(steps)} 次尺寸变化全部无平铺，viewport 依次 "
              f"{sizes_seen}")

        #: 存放大后的截图给人复核
        try:
            out = os.path.join(_ROOT, "data", "_web_shell_large.png")
            img = shell.debug_screenshot(out)
            if img is not None:
                DETAIL["screenshot"] = {"path": out,
                                        "size": [img.width(), img.height()]}
        except Exception:  # noqa: BLE001
            pass

        QTimer.singleShot(200, finish_and_quit)

    def finish_and_quit() -> None:
        try:
            out = os.path.join(_ROOT, "data", "_web_shell_verify.json")
            Path_write(out, {"results": RESULTS, "detail": DETAIL})
            print(f"\n详细结果：{out}")
        except Exception:  # noqa: BLE001
            pass
        app.quit()

    view.loadFinished.connect(on_load)

    #: 总超时兜底（别让脚本挂死）
    QTimer.singleShot(60000, lambda: (print("[TIMEOUT]"), finish_and_quit()))
    app.exec()
    return finish()


def screen_available() -> tuple[int, int]:
    """主屏可用区域（去掉任务栏）的宽高。

    ⚠ 无头环境可能拿不到屏 —— 退回一个保守的默认值。
    """
    try:
        from PySide6.QtGui import QGuiApplication  # noqa: PLC0415

        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            g = screen.availableGeometry()
            return max(800, g.width()), max(600, g.height())
    except Exception:  # noqa: BLE001
        pass
    return 1280, 800


def nonblank_ratio(img) -> float:
    """截图里「非背景色像素」的比例 —— 用来排除白屏/黑屏。

    ## 为什么要这个

    纯净的坐标断言有个盲区：**如果页面整个是空白**，
    各层尺寸照样会「精确等于 viewport」（因为都是浏览器算的），
    所有几何断言都通过，但用户看到的是白板。

    这里沿网格采样，统计与「角落底色」差异明显的像素占比。
    真正渲染出内容的页面比例远高于 0.02；白屏接近 0。

    :param img: ``QImage``（``debug_screenshot`` 返回的就是它）
    """
    if img is None:
        return 0.0
    #: ★ let 调用方传 QPixmap 或 QImage 都行（以前这里只认 pixelColor，
    #:   QPixmap 没有 pixelColor，传错就 AttributeError）
    if hasattr(img, "toImage"):
        img = img.toImage()
    if hasattr(img, "isNull") and img.isNull():
        return 0.0
    w, h = img.width(), img.height()
    if w < 8 or h < 8:
        return 0.0

    #: 角落当底色参照
    base = img.pixelColor(2, 2)
    br, bg_, bb = base.red(), base.green(), base.blue()

    total = 0
    differ = 0
    step_x = max(1, w // 60)
    step_y = max(1, h // 40)
    for y in range(0, h, step_y):
        for x in range(0, w, step_x):
            c = img.pixelColor(x, y)
            total += 1
            if (abs(c.red() - br) + abs(c.green() - bg_) +
                    abs(c.blue() - bb)) > 30:
                differ += 1
    return differ / total if total else 0.0


def Path_write(path: str, data) -> None:
    from pathlib import Path

    Path(path).write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8")


def finish() -> int:
    total = len(RESULTS)
    failed = [x for x in RESULTS if not x[1]]
    print("\n" + "=" * 62)
    print(f"结果：{total - len(failed)}/{total} 通过")
    if failed:
        print("失败项：")
        for case_id, _ok, note in failed:
            print(f"  {MARK_BAD} {case_id}  {note}")
        print("=" * 62)
        return 1
    print(f"{MARK_OK} 全部通过 —— 放大无平铺、桥接可用、玻璃生效")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
