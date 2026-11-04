# -*- coding: utf-8 -*-
"""验证配置页 2026-11-03 三处 UI 修改（人工复核用，不进产品）。

跑法::

    .venv\\Scripts\\python.exe src\\gui\\web\\dev\\web_shell_config_ui_verify.py

## 检查什么

用户当天圈了三个问题，这里**真的打开界面**逐条验：

1. **「这个是什么？干掉」** —— 搜索框左侧那个深色小方块
   （``App.icon('DOCUMENT')`` 的 mask）必须没了；
   图鉴页、练度页同款图标也一并删了。

2. **「这个下拉列表的下拉按钮呢」** —— 搜索框右侧要有 ``.search-caret``，
   点它能展开/收起候选面板，展开时箭头翻转（``.is-open``）。

3. **「这个新增放的也太紧凑了吧」** —— 「配置」标题与「新增」按钮之间
   要有实际间距（实测 ``getBoundingClientRect`` 的水平间隙）。

4. **「删除时，要弹出一个提示确认是否删除」** —— 点行内「删除」按钮
   **不能直接删**，要先弹 ``.dlg-overlay`` 确认框：
     * 标题「删除配置」
     * 正文里有头像/名字/类型
     * 有「不可恢复」提示
     * 底部「取消」+「删除」两个按钮
   然后点「取消」→ 弹框关闭，**列表条数不变**（真的没删）。

⚠ 本脚本**绝不点最终的「删除」按钮** —— 那会真删用户数据
（后端 ``deleteConfig`` 直接写 ``data/*.json``）。

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

#: ⚠ Windows 控制台默认 GBK，打印 ``▾`` / ``‹`` 这类字符会
#: ``UnicodeEncodeError`` 直接打断检查流程（第一版就挂了）。
#: 统一改成 UTF-8 + ``backslashreplace``，打不出来也不报错。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    except (AttributeError, ValueError):
        pass

failures: list[str] = []


def check(tag: str, ok: bool, detail: str = "") -> None:
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {tag} {detail}")
    if not ok:
        failures.append(f"{tag} {detail}")


def _loads(text):
    import json

    try:
        return json.loads(text) if isinstance(text, str) else {}
    except (TypeError, ValueError):
        return {}


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
        """隔一拍再截图（``debug_js`` 改完 DOM 立刻截会抓到上一帧）。"""

        def grab() -> None:
            shell.debug_screenshot(os.path.join(OUT, path))
            if nxt is not None:
                QTimer.singleShot(150, nxt)

        QTimer.singleShot(delay, grab)

    # ══════════════════════════════════════════════════════════════════
    #  ① 配置页：图标 / 下拉箭头 / 新增间距
    # ══════════════════════════════════════════════════════════════════
    def stage_config() -> None:
        shell.debug_js("window.App && App.go('config', {silent:true}); 'ok'")
        QTimer.singleShot(1500, check_config_chrome)

    def check_config_chrome() -> None:
        code = """
        (function(){
          var sec = document.getElementById('page-config');
          if (!sec) return JSON.stringify({ok:false, why:'页面没找到'});

          var search = sec.querySelector('.config-char-search');
          var panel  = sec.querySelector('.config-search-panel');
          if (!search || !panel) return JSON.stringify({ok:false, why:'搜索控件没找到'});

          // ① 图标：删干净了没有
          var icons = search.querySelectorAll('.nav-icon');

          // ② 下拉箭头
          var caret = search.querySelector('.search-caret');
          var caretRect = caret ? caret.getBoundingClientRect() : null;

          // 点箭头 → 面板应展开
          var openedBefore = !panel.hidden;
          if (caret) {
            caret.dispatchEvent(new MouseEvent('mousedown',
              {bubbles:true, cancelable:true}));
          }
          var openedAfter = !panel.hidden;
          var isOpenClass = search.classList.contains('is-open');
          var caretTransform = caret ? getComputedStyle(caret).transform : '';

          // 再点一次 → 应收回
          if (caret) {
            caret.dispatchEvent(new MouseEvent('mousedown',
              {bubbles:true, cancelable:true}));
          }
          var closedAfter = panel.hidden;

          // ③「配置」标题 vs「新增」按钮的实际间隙
          var title = sec.querySelector('.page-title');
          var addBtn = sec.querySelector('[data-action="add-config"]');
          var gap = null;
          if (title && addBtn) {
            var tr = title.getBoundingClientRect();
            var ar = addBtn.getBoundingClientRect();
            gap = Math.round((ar.left - tr.right) * 10) / 10;
          }

          return JSON.stringify({
            ok: true,
            iconCount: icons.length,
            hasCaret: !!caret,
            caretText: caret ? (caret.textContent || '').trim() : '',
            caretVisible: !!(caretRect && caretRect.width > 0 && caretRect.height > 0),
            //: ★ 2026-11-03 用户圈图：「这个下拉箭头也太小了吧」
            caretW: caretRect ? Math.round(caretRect.width * 10) / 10 : 0,
            caretH: caretRect ? Math.round(caretRect.height * 10) / 10 : 0,
            caretFontSize: caret ? (getComputedStyle(caret).fontSize || '') : '',
            openedBefore: openedBefore,
            openedAfter: openedAfter,
            closedAfter: closedAfter,
            isOpenClass: isOpenClass,
            caretTransform: caretTransform,
            gap: gap,
            hasTitle: !!title,
            hasAddBtn: !!addBtn,
            addBtnText: addBtn ? (addBtn.textContent || '').trim() : ''
          });
        })()
        """
        d = _loads(shell.debug_js(code))
        check("C1", bool(d.get("ok")), f"配置页存在 = {d}")
        check("C2", int(d.get("iconCount") or 0) == 0,
              f"搜索框左侧已无深色方块图标 = {d.get('iconCount')} 个 .nav-icon")
        check("C3", bool(d.get("hasCaret")) and bool(d.get("caretVisible")),
              f"搜索框右侧有下拉箭头 = caret={d.get('hasCaret')} "
              f"可见={d.get('caretVisible')} 字符={d.get('caretText')!r}")
        #: ★ 2026-11-03 用户圈图：「这个下拉箭头也太小了吧」
        #:   原来 18×18 / 10px；现在要求 >= 22px 且字号 >= 13px。
        caret_w = float(d.get("caretW") or 0)
        caret_fs = str(d.get("caretFontSize") or "")
        check("C3b", caret_w >= 22 and "13" in caret_fs or "14" in caret_fs or "15" in caret_fs,
              f"下拉箭头已放大 = {d.get('caretW')}×{d.get('caretH')}px "
              f"字号={caret_fs}（要求 ≥22px / 字号 ≥13px）")
        check("C4", not d.get("openedBefore") and bool(d.get("openedAfter")),
              f"点箭头能展开候选面板 = {d.get('openedBefore')} → {d.get('openedAfter')}")
        check("C5", bool(d.get("isOpenClass")),
              f"展开时加 .is-open（箭头翻转）= {d.get('isOpenClass')} "
              f"transform={d.get('caretTransform')!r}")
        check("C6", bool(d.get("closedAfter")),
              f"再点一次能收起 = {d.get('closedAfter')}")
        gap = d.get("gap")
        check("C7", isinstance(gap, (int, float)) and float(gap) >= 10,
              f"「配置」标题与「新增」按钮间距 = {gap}px（要求 ≥10）")
        check("C8", "新增" in str(d.get("addBtnText") or ""),
              f"「新增」按钮还在 = {d.get('addBtnText')!r}")
        shot_then("20-config-chrome.png", stage_caret_rotate)

    def stage_caret_rotate() -> None:
        """箭头翻转要**等过渡动画跑完**再读。

        ⚠ 第一版在点完立刻 ``getComputedStyle`` —— 那时 ``transform``
        过渡（160ms）还没开始，读到的是 ``matrix(1,0,0,1,0,0)``
        （单位矩阵 = 没转），误判成「样式没生效」。
        """
        shell.debug_js("""
        (function(){
          var search = document.querySelector('#page-config .config-char-search');
          var caret = search.querySelector('.search-caret');
          if (caret && !search.classList.contains('is-open')) {
            caret.dispatchEvent(new MouseEvent('mousedown',
              {bubbles:true, cancelable:true}));
          }
          return 'ok';
        })()
        """)
        QTimer.singleShot(400, read_caret_transform)

    def read_caret_transform() -> None:
        d = _loads(shell.debug_js("""
        (function(){
          var search = document.querySelector('#page-config .config-char-search');
          var caret = search.querySelector('.search-caret');
          if (!caret) return JSON.stringify({ok:false});
          return JSON.stringify({
            ok: true,
            isOpen: search.classList.contains('is-open'),
            transform: getComputedStyle(caret).transform
          });
        })()
        """))
        #: ``rotate(180deg)`` 的矩阵是 ``matrix(-1, 0, 0, -1, 0, 0)``
        tr = str(d.get("transform") or "")
        rotated = tr.startswith("matrix(-1")
        check("C9", bool(d.get("isOpen")) and rotated,
              f"展开后箭头翻转 180°（等过渡跑完再读）= isOpen={d.get('isOpen')} "
              f"transform={tr!r}")
        #: 收回，别把面板留在展开态影响后面的删除用例
        shell.debug_js("""
        (function(){
          var search = document.querySelector('#page-config .config-char-search');
          var caret = search.querySelector('.search-caret');
          if (caret && search.classList.contains('is-open')) {
            caret.dispatchEvent(new MouseEvent('mousedown',
              {bubbles:true, cancelable:true}));
          }
          return 'ok';
        })()
        """)
        QTimer.singleShot(300, stage_delete_dialog)

    # ══════════════════════════════════════════════════════════════════
    #  ② 删除 → 必须先弹确认框
    # ══════════════════════════════════════════════════════════════════
    def stage_delete_dialog() -> None:
        code = """
        (function(){
          var sec = document.getElementById('page-config');
          if (!sec) return JSON.stringify({ok:false, why:'页面没找到'});
          // 先把可能残留的弹框关掉，保证干净
          var stray = document.querySelector('.dlg-overlay');
          if (stray) stray.remove();

          var btn = sec.querySelector('.config-actions [data-action="delete"]');
          if (!btn) return JSON.stringify({ok:false, why:'删除按钮没找到'});

          var row = btn.closest('.config-row');
          var nameEl = row ? row.querySelector('.config-name') : null;
          var kindEl = row ? row.querySelector('.config-kind') : null;
          var rowsBefore = sec.querySelectorAll('.config-row').length;

          btn.click();

          var overlay = document.querySelector('.dlg-overlay');
          if (!overlay) {
            return JSON.stringify({
              ok:false, why:'点删除后没有弹出确认框',
              rowsBefore: rowsBefore,
              rowsAfter: sec.querySelectorAll('.config-row').length
            });
          }

          var title = overlay.querySelector('.dlg-title');
          var bodyText = (overlay.querySelector('.dlg-body') || {}).textContent || '';
          var footBtns = Array.from(overlay.querySelectorAll('.dlg-foot .btn'))
            .map(function(b){ return (b.textContent || '').trim(); });
          var cancel = overlay.querySelector('.dlg-foot [data-action="cancel"]');
          var confirm = overlay.querySelector('.dlg-foot [data-action="confirm-delete"]');
          var targetName = (overlay.querySelector('.del-target-name') || {}).textContent || '';
          var targetKind = (overlay.querySelector('.del-target-kind') || {}).textContent || '';
          var hasFace = !!overlay.querySelector('.del-target-face');

          return JSON.stringify({
            ok: true,
            rowName: nameEl ? nameEl.textContent.trim() : '',
            rowKind: kindEl ? kindEl.textContent.trim() : '',
            rowsBefore: rowsBefore,
            rowsAfter: sec.querySelectorAll('.config-row').length,
            title: title ? title.textContent.trim() : '',
            bodyText: bodyText.slice(0, 160),
            footBtns: footBtns,
            hasCancel: !!cancel,
            hasConfirm: !!confirm,
            confirmIsDanger: confirm ? confirm.classList.contains('btn-danger') : false,
            targetName: targetName,
            targetKind: targetKind,
            hasFace: hasFace
          });
        })()
        """
        d = _loads(shell.debug_js(code))
        check("D1", bool(d.get("ok")), f"点「删除」→ 弹出确认框 = {d}")
        check("D2", int(d.get("rowsBefore") or 0) == int(d.get("rowsAfter") or -1),
              f"弹框出现时**没有**立即删除 = 前 {d.get('rowsBefore')} 行 / "
              f"后 {d.get('rowsAfter')} 行")
        check("D3", (d.get("title") or "") == "删除配置",
              f"弹框标题 = {d.get('title')!r}")
        check("D4", "不可恢复" in str(d.get("bodyText") or ""),
              f"正文有不可恢复提示 = {d.get('bodyText')!r}")
        check("D5", bool(d.get("hasCancel")) and bool(d.get("hasConfirm")),
              f"底部有取消+删除两个按钮 = {d.get('footBtns')}")
        check("D6", bool(d.get("confirmIsDanger")),
              f"「删除」是危险色（btn-danger）= {d.get('confirmIsDanger')}")
        row_name = str(d.get("rowName") or "")
        check("D7", bool(row_name) and row_name in str(d.get("targetName") or ""),
              f"弹框里写着要删哪个角色 = 行={row_name!r} 弹框={d.get('targetName')!r}")
        check("D8", bool(d.get("targetKind")),
              f"弹框里写着配置类型 = {d.get('targetKind')!r}")
        check("D9", bool(d.get("hasFace")), f"弹框里有头像位 = {d.get('hasFace')}")
        shot_then("21-config-delete-confirm.png", stage_cancel_delete)

    def stage_cancel_delete() -> None:
        code = """
        (function(){
          var sec = document.getElementById('page-config');
          var overlay = document.querySelector('.dlg-overlay');
          if (!overlay) return JSON.stringify({ok:false, why:'弹框已经不在了'});
          var rowsBefore = sec.querySelectorAll('.config-row').length;
          var cancel = overlay.querySelector('.dlg-foot [data-action="cancel"]');
          if (!cancel) return JSON.stringify({ok:false, why:'取消按钮没找到'});
          cancel.click();
          return JSON.stringify({
            ok: true,
            overlayGone: !document.querySelector('.dlg-overlay'),
            rowsBefore: rowsBefore,
            rowsAfter: sec.querySelectorAll('.config-row').length
          });
        })()
        """
        d = _loads(shell.debug_js(code))
        check("D10", bool(d.get("ok")), f"点「取消」= {d}")
        check("D11", bool(d.get("overlayGone")), f"点取消后弹框关闭 = {d.get('overlayGone')}")
        check("D12", int(d.get("rowsBefore") or 0) == int(d.get("rowsAfter") or -1),
              f"取消后配置条数不变（确实没删）= {d.get('rowsBefore')} → "
              f"{d.get('rowsAfter')}")
        shot_then("22-config-after-cancel.png", stage_build_page)

    # ══════════════════════════════════════════════════════════════════
    #  ③ 练度页 / 图鉴页：同款图标也删了
    # ══════════════════════════════════════════════════════════════════
    def stage_build_page() -> None:
        shell.debug_js(
            "window.App && App.go('tool:character_build', {silent:true}); 'ok'")
        QTimer.singleShot(3000, check_build_page)

    def check_build_page() -> None:
        code = """
        (function(){
          var box = document.querySelector('.build-char-search');
          if (!box) return JSON.stringify({ok:false, why:'练度页搜索框没找到'});
          var caret = box.querySelector('.search-caret');
          var cs = caret ? getComputedStyle(caret) : null;
          return JSON.stringify({
            ok: true,
            iconCount: box.querySelectorAll('.nav-icon').length,
            placeholder: (box.querySelector('input') || {}).placeholder || '',
            hasCaret: !!caret,
            caretW: cs ? parseFloat(cs.width) : 0,
            caretText: caret ? (caret.textContent || '').trim() : ''
          });
        })()
        """
        d = _loads(shell.debug_js(code))
        check("B1", bool(d.get("ok")), f"练度页搜索框存在 = {d}")
        check("B2", int(d.get("iconCount") or 0) == 0,
              f"练度页搜索框已无深色方块图标 = {d.get('iconCount')} 个")
        check("B3", "拼音" in str(d.get("placeholder") or ""),
              f"练度页 placeholder 提示拼音 = {d.get('placeholder')!r}")
        #: ★ 2026-11-03 用户：「所有设计角色搜索的，都按照这个做」
        check("B4", bool(d.get("hasCaret")) and float(d.get("caretW") or 0) >= 22
              and str(d.get("caretText") or "") == "▼",
              f"练度页 ▼ 箭头 {d.get('caretW')}px text={d.get('caretText')!r}")
        shot_then("23-build-chrome.png", stage_library_page)

    def stage_library_page() -> None:
        shell.debug_js("window.App && App.go('library', {silent:true}); 'ok'")
        QTimer.singleShot(2400, check_library_page)

    def check_library_page() -> None:
        code = """
        (function(){
          var sec = document.getElementById('page-library');
          if (!sec) return JSON.stringify({ok:false, why:'页面没找到'});
          var box = sec.querySelector('.result-bar .search');
          if (!box) return JSON.stringify({ok:false, why:'搜索框没找到'});
          var caret = box.querySelector('.search-caret');
          var cs = caret ? getComputedStyle(caret) : null;
          var panel = box.querySelector('.lib-char-panel');
          return JSON.stringify({
            ok: true,
            iconCount: box.querySelectorAll('.nav-icon').length,
            placeholder: (box.querySelector('input') || {}).placeholder || '',
            hasCaret: !!caret,
            caretW: cs ? parseFloat(cs.width) : 0,
            caretText: caret ? (caret.textContent || '').trim() : '',
            caretHidden: caret ? caret.classList.contains('hidden') : true,
            hasPanel: !!panel
          });
        })()
        """
        d = _loads(shell.debug_js(code))
        check("L1", bool(d.get("ok")), f"图鉴页搜索框存在 = {d}")
        check("L2", int(d.get("iconCount") or 0) == 0,
              f"图鉴页搜索框已无深色方块图标 = {d.get('iconCount')} 个")
        check("L3", "拼音" in str(d.get("placeholder") or ""),
              f"图鉴页 placeholder 提示拼音 = {d.get('placeholder')!r}")
        #: ★ 2026-11-03 用户：「所有设计角色搜索的，都按照这个做」
        #:   图鉴页「角色」页签下也要有 ▼ + 下拉面板
        check("L4", bool(d.get("hasCaret")) and not d.get("caretHidden")
              and float(d.get("caretW") or 0) >= 22
              and str(d.get("caretText") or "") == "▼",
              f"图鉴页 ▼ 箭头 {d.get('caretW')}px "
              f"text={d.get('caretText')!r} hidden={d.get('caretHidden')}")
        check("L5", bool(d.get("hasPanel")),
              f"图鉴页有角色候选面板 = {d.get('hasPanel')}")
        shot_then("24-library-chrome.png", finish)

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
    QTimer.singleShot(90000, app.quit)
    app.exec()
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
