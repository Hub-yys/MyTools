# -*- coding: utf-8 -*-
"""验证「角色搜索 = 下拉列表 + 名称/拼音模糊匹配」（人工复核用，不进产品）。

跑法::

    .venv\\Scripts\\python.exe src\\gui\\web\\dev\\web_shell_search_verify.py

## 检查什么

★ 2026-11-03 用户圈图：「这个搜索应该是**下拉列表搜索**，
**可根据名称或拼音模糊匹配**角色」「所有的角色搜索都按照这样做」。

所以这里不只看代码有没有改，而是**真的打开界面敲字**：

1. 配置页 —— 点搜索框 → 候选面板弹出（`.config-search-panel` 可见）
2. 配置页 —— 打 ``fx`` → 出现候选，且**名字里有「绯雪」**
3. 配置页 —— 打 ``feixue`` → 同样命中
4. 配置页 —— 打中文 ``绯`` → 命中
5. 配置页 —— 说明行**不再出现**「角色战斗配置」
6. 练度页 —— 打 ``fx`` → 候选命中（``.build-char-panel``）

退出码 0 = 全过，1 = 有失败。
"""

from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", "..", ".."))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)
os.environ.setdefault("QT_LOGGING_RULES", "qt.multimedia.*=false")

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

OUT = os.path.join(_ROOT, "data", "_shots")

failures: list[str] = []


def check(tag: str, ok: bool, detail: str = "") -> None:
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {tag} {detail}")
    if not ok:
        failures.append(f"{tag} {detail}")


def main() -> int:
    app = QApplication.instance() or QApplication([])
    import src.tools as tools_pkg  # noqa: PLC0415

    tools_pkg.discover_tools()

    from src.gui.web_shell import WebShell, web_base_url  # noqa: PLC0415

    os.makedirs(OUT, exist_ok=True)
    shell = WebShell(base_url=web_base_url())
    if not shell.build():
        print("build failed")
        return 1
    shell.view.resize(1400, 880)
    shell.view.show()

    def shot_then(path: str, nxt=None, delay: int = 400) -> None:
        """隔一拍再截图。

        ⚠ ``debug_js`` 改完 DOM 后立刻截图会抓到**上一帧**（Chromium 还没
        重绘），所以这里等 400ms —— 否则截图里看到的和断言结果对不上
        （第一版就出现过：断言说「候选 1 条」，图里却是空的输入框）。
        """

        def grab() -> None:
            shell.debug_screenshot(os.path.join(OUT, path))
            if nxt is not None:
                QTimer.singleShot(150, nxt)

        QTimer.singleShot(delay, grab)

    def stage_config() -> None:
        shell.debug_js("window.App && App.go('config', {silent:true}); 'ok'")
        QTimer.singleShot(1200, check_config_opened)

    def check_config_opened() -> None:
        #: ① 点搜索框 → 候选面板可见
        code = """
        (function(){
          var inp = document.querySelector('#page-config .config-char-search input');
          var panel = document.querySelector('#page-config .config-search-panel');
          if (!inp || !panel) return JSON.stringify({ok:false, why:'控件没找到'});
          inp.focus();
          inp.dispatchEvent(new MouseEvent('mousedown', {bubbles:true}));
          inp.dispatchEvent(new FocusEvent('focus'));
          var cs = getComputedStyle(panel);
          //: ★ 2026-11-03 用户圈图「干掉」：类型标签已删，改统计
          //:   ``is-plain``（未配置的角色）来证明候选池是全量的。
          var plain = Array.from(panel.querySelectorAll('.config-search-opt.is-plain'))
            .map(function(n){return n.textContent.trim();});
          return JSON.stringify({
            ok: true,
            visible: !panel.hidden && cs.display !== 'none',
            opts: panel.querySelectorAll('.config-search-opt').length,
            kinds: Array.from(panel.querySelectorAll('.config-search-kind'))
              .map(function(n){return n.textContent.trim();}),
            plain: plain.length,
            unconfigured: plain.length,
            empty: (panel.querySelector('.config-search-empty')||{}).textContent || ''
          });
        })()
        """
        res = shell.debug_js(code)
        d = _loads(res)
        check("S1", bool(d.get("ok")), f"配置页搜索控件存在 = {d}")
        check("S2", bool(d.get("visible")), f"点输入框后候选面板展开 = {d.get('visible')}")
        check("S3", int(d.get("opts") or 0) >= 1,
              f"未输入时候选条数 = {d.get('opts')}（空态提示={d.get('empty')!r}）")
        #: ★ 2026-11-03 用户圈图：「这个是角色搜索，包含游戏目前所有的角色」
        #:   候选池必须来自 ``getCharacterOptions`` 的全量 61 个角色，
        #:   而不是只列已配置的 8 个。
        total = int(d.get("opts") or 0)
        check("S3b", total >= 50,
              f"候选池是**全部角色**（>=50）= 实际 {total} 条"
              f"（其中未配置 {d.get('unconfigured')} 条）")
        check("S3c", int(d.get("unconfigured") or 0) >= 1,
              f"候选里有未配置的角色（``is-plain``，全量池的特征）= {d.get('unconfigured')} 条")
        #: ★ 2026-11-03 用户圈图：「干掉」——候选行右侧类型标签必须消失
        kinds_left = d.get("kinds") or []
        check("S3d", len(kinds_left) == 0,
              f"候选行不再有类型标签（.config-search-kind）= {kinds_left[:5]}")
        #: 截图留证（⚠ 要等一拍，否则抓到的是重绘前的帧）
        shot_then("10-config-search-open.png", lambda: check_type("fx"))

    def _type_and_read(kw: str) -> str:
        #: 用原生 setter + input 事件，才能触发页面自己的监听（React 式的坑）
        return f"""
        (function(){{
          var inp = document.querySelector('#page-config .config-char-search input');
          var panel = document.querySelector('#page-config .config-search-panel');
          if (!inp || !panel) return '{{"ok":false}}';
          var setter = Object.getOwnPropertyDescriptor(
            window.HTMLInputElement.prototype, 'value').set;
          setter.call(inp, {kw!r});
          inp.dispatchEvent(new Event('input', {{bubbles:true}}));
          var names = Array.from(panel.querySelectorAll('.config-search-name'))
            .map(function(n){{return n.textContent.trim();}});
          //: ★ 列表行（不是候选面板）—— 用户「我都选心了怎么还出现这些
          //:   不相关的」抱怨的就是这里被 ``summary`` 里的「核心」带偏
          var rows = Array.from(
            document.querySelectorAll('#page-config .config-row .config-name'))
            .map(function(n){{return n.textContent.trim();}});
          var subtitle = document.querySelector('#page-config .config-subtitle');
          return JSON.stringify({{
            ok: true,
            names: names,
            count: names.length,
            rows: rows,
            rowCount: rows.length,
            empty: (panel.querySelector('.config-search-empty')||{{}}).textContent || '',
            subtitle: subtitle ? subtitle.textContent.trim() : ''
          }});
        }})()
        """

    def check_type(kw: str) -> None:
        d = _loads(shell.debug_js(_type_and_read(kw)))
        names = d.get("names") or []
        tag = "S4" if kw == "fx" else (
            "S5" if kw == "feixue" else ("S6" if kw == "绯" else "S6c"))
        check(tag, len(names) >= 1,
              f"打「{kw}」→ 候选 {len(names)} 条 {names[:6]}"
              f"（空态={d.get('empty')!r}）")
        if kw == "fx":
            check("S4b", any("绯雪" in n for n in names),
                  f"「fx」命中绯雪 = {names[:6]}")
            sub = str(d.get("subtitle") or "")
            check("S4c", "战斗配置" not in sub,
                  f"说明行不含「角色战斗配置」= {sub!r}")
            shot_then("11-config-search-fx.png", lambda: check_type("feixue"))
        elif kw == "feixue":
            check("S5b", any("绯雪" in n for n in names),
                  f"「feixue」命中绯雪 = {names[:6]}")
            QTimer.singleShot(150, lambda: check_type("绯"))
        elif kw == "绯":
            check("S6b", any("绯" in n for n in names),
                  f"「绯」命中绯雪 = {names[:6]}")
            QTimer.singleShot(150, lambda: check_type("心"))
        else:
            #: ★★★ 2026-11-03 用户：「我都选心了怎么还出现这些不相关的」
            #:
            #: 打中文时**每一个**候选名、**每一条**列表行名都必须真的含这个字。
            #: 之前 ``matchesKeyword`` 还会比 ``summary``（「核心：暴击…」），
            #: 于是「心」把一大堆角色连带筛出来 —— 这几条断言就是钉子。
            bad_cand = [n for n in names if "心" not in n]
            check("S6c1", not bad_cand,
                  f"打「心」→ 候选全部含「心」= 共 {len(names)} 条，"
                  f"不含的 {bad_cand[:5]}")
            rows = d.get("rows") or []
            bad_rows = [n for n in rows if "心" not in n]
            check("S6c2", not bad_rows,
                  f"打「心」→ 列表行全部含「心」= 共 {len(rows)} 行 {rows[:6]}，"
                  f"不含的 {bad_rows[:5]}")
            sub = str(d.get("subtitle") or "")
            check("S6c3", "命中" in sub,
                  f"打「心」→ 说明行 {sub!r}")
            shot_then("13-config-search-heart.png", stage_build)

    def stage_build() -> None:
        shell.debug_js("window.App && App.go('tool:character_build', {silent:true}); 'ok'")
        QTimer.singleShot(2200, check_build)

    def check_build() -> None:
        #: ⚠ 练度页的候选池来自**缓存**（``getCharacterBuildCache`` 的
        #: ``characters``），和配置页的来源完全不同 —— 缓存里这 21 个角色
        #: 没有「绯雪」（绯雪只有声骸强化配置、没练度缓存）。
        #: 所以这里用缓存里确实存在的 ``千咲``（拼音 ``qianxiao / qx``）验。
        code = """
        (function(){
          var inp = document.querySelector('.build-char-search input');
          var panel = document.querySelector('.build-char-search .build-char-panel');
          if (!inp || !panel) return JSON.stringify({ok:false, why:'控件没找到'});
          inp.focus();
          inp.dispatchEvent(new MouseEvent('click', {bubbles:true, cancelable:true}));
          var setter = Object.getOwnPropertyDescriptor(
            window.HTMLInputElement.prototype, 'value').set;
          setter.call(inp, 'qx');
          inp.dispatchEvent(new Event('input', {bubbles:true}));
          var names = Array.from(panel.querySelectorAll('.build-char-name'))
            .map(function(n){return n.textContent.trim();});
          return JSON.stringify({
            ok: true,
            count: names.length,
            names: names,
            hasPanel: !panel.hidden && getComputedStyle(panel).display !== 'none'
          });
        })()
        """
        d = _loads(shell.debug_js(code))
        check("S7", bool(d.get("ok")), f"练度页角色搜索控件存在 = {d}")
        names = d.get("names") or []
        check("S8", len(names) >= 1,
              f"练度页打「qx」→ 候选 {len(names)} 条 {names}")
        check("S8b", any("千咲" in n for n in names),
              f"练度页「qx」命中千咲（qianxiao/qx）= {names}")
        shot_then("12-build-search-qx.png", stage_library)

    def stage_library() -> None:
        shell.debug_js("window.App && App.go('library', {silent:true}); 'ok'")
        QTimer.singleShot(2200, check_library)

    def check_library() -> None:
        #: ★ 2026-11-03 用户：「所有设计角色搜索的，都按照这个做」——
        #: 图鉴页也补上了同款下拉候选面板（头像 + 名字 + ▼ 箭头 +
        #: 只看名字/拼音匹配）。这里一并验：
        #:   S9  搜索框存在
        #:   S9b placeholder 提示拼音
        #:   S9c 打 fx → 网格里剩绯雪
        #:   S9d 候选面板能展开且有候选行
        #:   S9e 候选行只有「头像 + 名字」（没有旧的 meta 标签）
        #:   S9f ▼ 箭头存在且够大（≥22px，和配置页一致）
        #:   S9g 汇总行写明「全部 N 个角色」
        code = """
        (function(){
          var sec = document.getElementById('page-library');
          if (!sec) return JSON.stringify({ok:false, why:'页面没找到'});
          var inp = sec.querySelector('.search input');
          if (!inp) return JSON.stringify({ok:false, why:'搜索框没找到'});
          var setter = Object.getOwnPropertyDescriptor(
            window.HTMLInputElement.prototype, 'value').set;
          setter.call(inp, 'fx');
          inp.dispatchEvent(new Event('input', {bubbles:true}));
          var names = Array.from(sec.querySelectorAll('.avatar-tile .avatar-name, .avatar-tile'))
            .map(function(n){
              var t = n.querySelector('.avatar-name');
              if (t) return t.textContent.trim();
              var img = n.querySelector('img');
              return (img && img.alt) || n.title || '';
            }).filter(Boolean);

          //: ── 下拉候选面板（图鉴页新增）──
          var caret = sec.querySelector('.lib-char-search .search-caret');
          var panel = sec.querySelector('.lib-char-search .lib-char-panel');
          if (caret) {
            caret.dispatchEvent(new MouseEvent('mousedown', {
              bubbles:true, cancelable:true
            }));
          }
          var optNames = [], optMetas = 0, hint = '';
          if (panel) {
            optNames = Array.from(panel.querySelectorAll('.config-search-name'))
              .map(function(n){return n.textContent.trim();});
            optMetas = panel.querySelectorAll(
              '.config-search-kind, .char-option-meta, .build-char-meta').length;
            var h = panel.querySelector('.config-search-hint');
            hint = h ? h.textContent.trim() : '';
          }
          var cs = caret ? getComputedStyle(caret) : null;
          return JSON.stringify({
            ok: true,
            placeholder: inp.placeholder,
            count: names.length,
            names: names.slice(0, 8),
            title: (sec.querySelector('.avatar-tile') || {}).title || '',
            hasCaret: !!caret,
            caretVisible: !!(cs && cs.display !== 'none'),
            caretW: cs ? parseFloat(cs.width) : 0,
            caretText: caret ? (caret.textContent || '').trim() : '',
            hasPanel: !!panel,
            panelOpen: !!(panel && !panel.hidden &&
              getComputedStyle(panel).display !== 'none'),
            optCount: optNames.length,
            optNames: optNames.slice(0, 6),
            optMetas: optMetas,
            hint: hint
          });
        })()
        """
        d = _loads(shell.debug_js(code))
        check("S9", bool(d.get("ok")), f"图鉴页搜索框存在 = {d}")
        check("S9b", "拼音" in str(d.get("placeholder") or ""),
              f"图鉴搜索框 placeholder 提示拼音 = {d.get('placeholder')!r}")
        titles = " ".join(str(d.get("title") or "") for _ in [0])
        names = d.get("names") or []
        check("S9c", any("绯雪" in str(n) for n in names) or "绯雪" in titles,
              f"图鉴页打「fx」→ {len(names)} 条 {names}（首项 title={titles!r}）")
        check("S9d", bool(d.get("panelOpen")) and int(d.get("optCount") or 0) >= 1,
              f"图鉴页候选面板展开 = {d.get('panelOpen')}，候选 {d.get('optCount')} 条 "
              f"{d.get('optNames')}")
        check("S9e", int(d.get("optMetas") or 0) == 0,
              f"图鉴页候选行没有类型/meta 标签（应为 0）= {d.get('optMetas')}")
        check("S9f", bool(d.get("hasCaret")) and float(d.get("caretW") or 0) >= 22
              and str(d.get("caretText") or "") == "▼",
              f"图鉴页 ▼ 箭头 {d.get('caretW')}px text={d.get('caretText')!r}")
        check("S9g", "个角色" in str(d.get("hint") or ""),
              f"图鉴页候选汇总行 = {d.get('hint')!r}")
        shot_then("13-library-search-fx.png", stage_library_other_tab)

    def stage_library_other_tab() -> None:
        #: 图鉴页的搜索框是**全局**的（4 个页签共用），但只有「角色」
        #: 页签才谈得上「角色搜索」。切到其它页签时必须：
        #:   * 收起 ▼ 箭头（否则点开是空的角色候选，莫名其妙）
        #:   * 收起已展开的候选面板
        #:   * placeholder 换成「搜索名称 / 效果…」（写「角色名」会误导）
        code = """
        (function(){
          var sec = document.getElementById('page-library');
          if (!sec) return JSON.stringify({ok:false, why:'页面没找到'});
          var inp = sec.querySelector('.search input');
          var caret = sec.querySelector('.lib-char-search .search-caret');
          var panel = sec.querySelector('.lib-char-search .lib-char-panel');
          if (!inp || !caret) return JSON.stringify({ok:false, why:'控件没找到'});
          var beforeHidden = caret.classList.contains('hidden');

          //: 点「声骸套装」页签（.seg[data-value="echoSets"]）
          var seg = sec.querySelector('.segmented .seg[data-value="echoSets"]');
          if (!seg) return JSON.stringify({ok:false, why:'页签没找到'});
          seg.click();

          var cs = getComputedStyle(caret);
          return JSON.stringify({
            ok: true,
            beforeHidden: beforeHidden,
            afterHidden: caret.classList.contains('hidden'),
            caretDisplay: cs.display,
            caretW: parseFloat(cs.width) || 0,
            panelOpen: !!(panel && !panel.hidden &&
              getComputedStyle(panel).display !== 'none'),
            placeholder: inp.placeholder,
            activeSeg: (sec.querySelector('.segmented .seg.is-active') || {}).textContent || ''
          });
        })()
        """
        d = _loads(shell.debug_js(code))
        check("S10", bool(d.get("ok")), f"图鉴页页签切换可操作 = {d}")
        check("S10b", not d.get("beforeHidden") and bool(d.get("afterHidden")),
              "角色页签时箭头可见 → 切到「声骸套装」后箭头隐藏 "
              f"= {d.get('beforeHidden')} → {d.get('afterHidden')}")
        check("S10c", not d.get("panelOpen"),
              f"切页签后角色候选面板已收起 = {d.get('panelOpen')}")
        check("S10d", "角色名" not in str(d.get("placeholder") or ""),
              f"非角色页签 placeholder 不再写「角色名」= {d.get('placeholder')!r}")
        shot_then("14-library-other-tab.png", finish)

    def finish() -> None:
        if failures:
            print(f"\n失败 {len(failures)} 项：")
            for f in failures:
                print("  -", f)
        else:
            print("\n全部通过")
        app.quit()

    def on_load(ok: bool) -> None:
        if not ok:
            print("load failed")
            app.quit()
            return
        QTimer.singleShot(2600, stage_config)

    shell.view.loadFinished.connect(on_load)
    QTimer.singleShot(60000, app.quit)
    app.exec()
    return 0 if not failures else 1


def _loads(text):
    import json

    try:
        return json.loads(text) if isinstance(text, str) else {}
    except (TypeError, ValueError):
        return {}


if __name__ == "__main__":
    raise SystemExit(main())
