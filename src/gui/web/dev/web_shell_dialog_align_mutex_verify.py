# -*- coding: utf-8 -*-
"""验证 2026-11-03 第七轮两处修改（人工复核用，不进产品）。

跑法::

    .venv\\Scripts\\python.exe src\\gui\\web\\dev\\web_shell_dialog_align_mutex_verify.py

## 检查什么

用户当天圈了两张图，这里**真的打开界面**逐条验：

### 1. 角色行左缘对齐（m01908「这里要对齐」）

* 「角色」二字的**左缘**必须和同弹框里其它卡标题（「核心属性」
  「满值锁定」「可选属性」「有效词条」…）的左缘在**同一列**
  （容差 2px —— 字体渲染会有半像素差）；
* ``.dlg-card-row`` 的左右内边距必须是 20px（和 ``.coll-card`` /
  ``.enh-crit-card`` / ``.enh-switch-card`` 一致）；
* 卡的外框本来就是对得齐的（探针实测 361→1039），这里一并复核，
  防止将来有人改宽度把卡也改歪了。

### 2. 核心属性 ↔ 可选属性互斥（m01910）

用户原话：「这里属性是互斥的，上面先选了，下面就不能选，
下面先选了，上面就不能选」。

* **下面先选**：勾「可选属性」里的某一项 → 「核心属性」里同名勾选框
  必须变成 ``disabled``；
* **上面先选**：勾「核心属性」里的某一项 → 「可选属性」里同名勾选框
  必须变成 ``disabled`` **且没被勾上**；
* **取消后恢复**：把一边取消掉，另一边同名项要重新可用；
* 暴击 / 暴击伤害 依旧只在核心属性里出现（可选网格里根本没有这两项）。

⚠ 本脚本**绝不点「创建」** —— 一旦点成功会写进用户 ``data/*.json``。

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
        def grab() -> None:
            shell.debug_screenshot(os.path.join(OUT, path))
            if nxt is not None:
                QTimer.singleShot(150, nxt)

        QTimer.singleShot(delay, grab)

    # ══════════════════════════════════════════════════════════════════
    #  打开「新增配置」第二步（编辑表单）
    # ══════════════════════════════════════════════════════════════════
    def stage_config() -> None:
        shell.debug_js("window.App && App.go('config', {silent:true}); 'ok'")
        QTimer.singleShot(1600, click_add)

    def click_add() -> None:
        shell.debug_js(
            "(function(){var b=document.querySelector("
            "'#page-config [data-action=\"add-config\"]');"
            "if(b) b.click();})()"
        )
        QTimer.singleShot(900, click_next)

    def click_next() -> None:
        shell.debug_js(
            "(function(){var b=document.querySelector('[data-action=\"next\"]');"
            "if(b) b.click();})()"
        )
        QTimer.singleShot(2400, expand_cards)

    def expand_cards() -> None:
        """把「核心属性」「可选属性」两张折叠卡都展开 —— 否则测 rect 全是 0。"""
        shell.debug_js("""
        (function(){
          var overlay = document.querySelector('.dlg-overlay');
          if (!overlay) return 'no-overlay';
          //: ⚠ 展开监听挂在 ``.coll-toggle`` 按钮上（``collapsibleCard`` 里
          //: 只给 toggle 加了 click），点 ``.coll-head`` 不会展开。
          overlay.querySelectorAll('.coll-card').forEach(function(c){
            var t = (c.textContent || '');
            var content = c.querySelector('.coll-content');
            var toggle = c.querySelector('.coll-toggle');
            if (!toggle || !content) return;
            var wantOpen = (t.indexOf('核心属性') >= 0 ||
                            t.indexOf('可选属性') >= 0);
            var isOpen = !content.hidden;
            if (wantOpen && !isOpen) toggle.click();
          });
          return 'ok';
        })()
        """)
        QTimer.singleShot(700, check_align)

    # ══════════════════════════════════════════════════════════════════
    #  ① 角色行左缘对齐
    # ══════════════════════════════════════════════════════════════════
    ALIGN_CODE = """
    (function(){
      var overlay = document.querySelector('.dlg-overlay');
      if (!overlay) return JSON.stringify({ok:false, why:'弹框没打开'});

      //: 文字真实左缘 = 元素 rect.left + 左侧空白。
      //: 简单可靠的做法：给元素套一个 Range 读第一段文字的 ClientRect。
      function textLeft(el){
        if (!el) return null;
        var r = document.createRange();
        r.selectNodeContents(el);
        var rects = r.getClientRects();
        for (var i = 0; i < rects.length; i++) {
          if (rects[i].width > 0.5) return rects[i].left;
        }
        return null;
      }

      var roleCard = overlay.querySelector('.dlg-card-row');
      var roleLabel = roleCard
        ? roleCard.querySelector('.dlg-label') : null;
      var roleLeft = textLeft(roleLabel);

      //: 其它卡的标题文字左缘。
      //: ⚠ 只取 ``.coll-title``（卡片标题）—— ``.enh-inline-label`` 是
      //: **行内标签**（「暴击不低于」「至少」），它们坐在同一行的中间，
      //: 横向位置本来就不在左缘，混进来会把断言的基准值拉歪（第一版
      //: 就是这么误报 274px 的）。
      var others = [];
      var titles = overlay.querySelectorAll('.coll-head .coll-title');
      titles.forEach(function(el){
        if (roleCard && roleCard.contains(el)) return;
        var t = (el.textContent || '').trim();
        if (!t) return;
        var left = textLeft(el);
        if (left != null) others.push({text:t, left:Math.round(left*10)/10});
      });

      var cs = roleCard ? getComputedStyle(roleCard) : null;
      var roleRect = roleCard ? roleCard.getBoundingClientRect() : null;
      var otherRects = [];
      overlay.querySelectorAll(
        '.coll-card, .enh-crit-card, .enh-switch-card').forEach(
          function(c){
            var rr = c.getBoundingClientRect();
            otherRects.push({
              left: Math.round(rr.left*10)/10,
              right: Math.round(rr.right*10)/10 });
          });

      return JSON.stringify({
        ok: true,
        roleLeft: roleLeft == null ? null : Math.round(roleLeft*10)/10,
        roleLabelText: roleLabel ? (roleLabel.textContent||'').trim() : '',
        others: others,
        cardPaddingLeft: cs ? cs.paddingLeft : '',
        cardPaddingRight: cs ? cs.paddingRight : '',
        cardLeft: roleRect ? Math.round(roleRect.left*10)/10 : null,
        cardRight: roleRect ? Math.round(roleRect.right*10)/10 : null,
        otherRects: otherRects
      });
    })()
    """

    def check_align() -> None:
        d = _loads(shell.debug_js(ALIGN_CODE))
        check("A1", bool(d.get("ok")), f"第二步表单打开 = {d.get('why') or 'ok'}")

        role_left = d.get("roleLeft")
        others = d.get("others") or []
        check("A2", role_left is not None and len(others) >= 1,
              f"量到「角色」左缘 + 至少 1 个其它卡标题 "
              f"= {role_left} / 其它 {len(others)} 个")

        #: 所有卡标题左缘应该都在同一列（容差 2px）
        if role_left is not None and others:
            lv = [float(o["left"]) for o in others]
            base = min(lv)
            worst = max([abs(float(role_left) - base)] +
                        [abs(v - base) for v in lv])
            check("A3", worst <= 2.0,
                  f"「角色」与其它卡标题左缘同一列（最大偏差 {worst:.1f}px，"
                  f"容差 2px）；角色={role_left}，其它={lv[:6]}")

        #: 内边距 20px（和 .coll-card / .enh-crit-card / .enh-switch-card 一致）
        pl = str(d.get("cardPaddingLeft") or "")
        pr = str(d.get("cardPaddingRight") or "")
        check("A4", pl == "20px" and pr == "20px",
              f"角色卡左右内边距 = {pl!r} / {pr!r}（应 20px）")

        #: 卡的外框本来就和其它卡对齐
        cl = d.get("cardLeft")
        cr = d.get("cardRight")
        rects = d.get("otherRects") or []
        if cl is not None and rects:
            same = all(abs(float(r["left"]) - float(cl)) <= 1.5 and
                       abs(float(r["right"]) - float(cr)) <= 1.5
                       for r in rects)
            check("A5", same,
                  f"角色卡外框与其它 {len(rects)} 张卡对齐 "
                  f"= 角色 {cl}→{cr}")

        shot_then("40-dialog-align.png", check_mutex_optional_first)

    # ══════════════════════════════════════════════════════════════════
    #  ② 互斥：先在「可选属性」里勾一项
    # ══════════════════════════════════════════════════════════════════
    PICK_OPTIONAL = """
    (function(){
      var overlay = document.querySelector('.dlg-overlay');
      if (!overlay) return JSON.stringify({ok:false, why:'弹框没打开'});

      //: 找可选属性那张卡（按标题定位，别依赖 DOM 顺序）
      var optCard = null, coreCard = null;
      overlay.querySelectorAll('.coll-card').forEach(function(c){
        var t = (c.textContent || '');
        if (t.indexOf('可选属性') >= 0 && !optCard) optCard = c;
        if (t.indexOf('核心属性') >= 0 && !coreCard) coreCard = c;
      });
      if (!optCard || !coreCard) {
        return JSON.stringify({ok:false, why:'找不到两张卡'});
      }

      function boxOf(card, name){
        var hit = null;
        card.querySelectorAll('.enh-check').forEach(function(lbl){
          var txt = (lbl.textContent || '').trim();
          if (txt === name) hit = lbl.querySelector('input[type=checkbox]');
        });
        return hit;
      }

      //: 挑一个「核心没勾、可选没勾」的项（攻击百分比这种自选项）
      var chosen = null;
      var names = [];
      optCard.querySelectorAll('.enh-check').forEach(function(lbl){
        names.push((lbl.textContent || '').trim());
      });
      var prefer = ['攻击百分比', '共鸣效率', '普攻伤害加成'];
      for (var i = 0; i < prefer.length; i++) {
        if (names.indexOf(prefer[i]) >= 0) { chosen = prefer[i]; break; }
      }
      if (!chosen && names.length) chosen = names[0];

      var optBox = boxOf(optCard, chosen);
      var coreBox = boxOf(coreCard, chosen);
      if (!optBox || !coreBox) {
        return JSON.stringify({
          ok:false, why:'同名项没对上', chosen:chosen,
          names:names, hasOpt:!!optBox, hasCore:!!coreBox });
      }

      //: 先确保干净：核心同名项未勾、可选同名项未勾
      var before = {coreChecked: coreBox.checked, coreDisabled: coreBox.disabled,
                    optChecked: optBox.checked, optDisabled: optBox.disabled};

      //: ★ 下面先选 —— 勾可选
      optBox.click();

      return JSON.stringify({
        ok: true,
        chosen: chosen,
        names: names,
        before: before,
        afterOptChecked: optBox.checked,
        afterCoreDisabled: coreBox.disabled,
        afterCoreChecked: coreBox.checked,
        coreTitle: coreBox.closest('.enh-check')
          ? (coreBox.closest('.enh-check').textContent || '').trim() : ''
      });
    })()
    """

    def check_mutex_optional_first() -> None:
        d = _loads(shell.debug_js(PICK_OPTIONAL))
        check("M1", bool(d.get("ok")),
              f"勾「可选属性」某一项 = {d.get('why') or 'ok'} "
              f"(选了 {d.get('chosen')!r})")

        check("M2", bool(d.get("afterOptChecked")),
              f"可选属性这项确实被勾上了 = {d.get('afterOptChecked')}")

        check("M3", bool(d.get("afterCoreDisabled")),
              f"★ 下面先选 → 上面同名项被禁用 = "
              f"coreDisabled={d.get('afterCoreDisabled')} "
              f"coreChecked={d.get('afterCoreChecked')} "
              f"(项 {d.get('chosen')!r})")

        shot_then("41-mutex-optional-first.png", check_mutex_core_first)

    # ══════════════════════════════════════════════════════════════════
    #  ③ 互斥：反向 —— 先在「核心属性」里勾一项
    # ══════════════════════════════════════════════════════════════════
    PICK_CORE = """
    (function(){
      var overlay = document.querySelector('.dlg-overlay');
      if (!overlay) return JSON.stringify({ok:false, why:'弹框没打开'});

      var optCard = null, coreCard = null;
      overlay.querySelectorAll('.coll-card').forEach(function(c){
        var t = (c.textContent || '');
        if (t.indexOf('可选属性') >= 0 && !optCard) optCard = c;
        if (t.indexOf('核心属性') >= 0 && !coreCard) coreCard = c;
      });
      if (!optCard || !coreCard) {
        return JSON.stringify({ok:false, why:'找不到两张卡'});
      }

      function boxOf(card, name){
        var hit = null;
        card.querySelectorAll('.enh-check').forEach(function(lbl){
          var txt = (lbl.textContent || '').trim();
          if (txt === name) hit = lbl.querySelector('input[type=checkbox]');
        });
        return hit;
      }

      //: ① 先把上一步勾的可选项取消，确认「取消后恢复」
      var prev = null;
      optCard.querySelectorAll('.enh-check').forEach(function(lbl){
        var cb = lbl.querySelector('input[type=checkbox]');
        if (cb && cb.checked) prev = (lbl.textContent || '').trim();
      });
      var restore = {prev: prev, coreDisabledAfterUncheck: null};
      if (prev) {
        var pb = boxOf(optCard, prev);
        if (pb) pb.click();
        var cbCore = boxOf(coreCard, prev);
        restore.coreDisabledAfterUncheck = cbCore ? cbCore.disabled : null;
      }

      //: ② 反向：在核心属性里勾一个非强制项
      var chosen = null;
      var coreNames = [];
      coreCard.querySelectorAll('.enh-check').forEach(function(lbl){
        coreNames.push((lbl.textContent || '').trim());
      });
      var prefer = ['攻击百分比', '共鸣效率', '普攻伤害加成'];
      for (var i = 0; i < prefer.length; i++) {
        if (coreNames.indexOf(prefer[i]) >= 0) { chosen = prefer[i]; break; }
      }
      var coreBox = chosen ? boxOf(coreCard, chosen) : null;
      var optBox = chosen ? boxOf(optCard, chosen) : null;
      if (!coreBox || !optBox) {
        return JSON.stringify({
          ok:false, why:'核心同名项没对上', chosen:chosen,
          coreNames:coreNames, hasCore:!!coreBox, hasOpt:!!optBox,
          restore: restore });
      }

      var beforeOptChecked = optBox.checked;
      coreBox.click();

      return JSON.stringify({
        ok: true,
        chosen: chosen,
        restore: restore,
        beforeOptChecked: beforeOptChecked,
        afterCoreChecked: coreBox.checked,
        afterOptDisabled: optBox.disabled,
        afterOptChecked: optBox.checked,
        coreNames: coreNames
      });
    })()
    """

    def check_mutex_core_first() -> None:
        d = _loads(shell.debug_js(PICK_CORE))
        check("M4", bool(d.get("ok")),
              f"反向勾「核心属性」某一项 = {d.get('why') or 'ok'} "
              f"(选了 {d.get('chosen')!r})")

        restore = d.get("restore") or {}
        check("M5", restore.get("coreDisabledAfterUncheck") is False,
              f"★ 取消可选后，上面同名项恢复可用 = "
              f"{restore.get('coreDisabledAfterUncheck')!r} "
              f"(测的项 {restore.get('prev')!r})")

        check("M6", bool(d.get("afterCoreChecked")),
              f"核心属性这项确实被勾上了 = {d.get('afterCoreChecked')}")

        check("M7", bool(d.get("afterOptDisabled")),
              f"★ 上面先选 → 下面同名项被禁用 = "
              f"optDisabled={d.get('afterOptDisabled')} "
              f"optChecked={d.get('afterOptChecked')}")

        check("M8", d.get("afterOptChecked") is False,
              f"下面同名项没被同时勾上 = {d.get('afterOptChecked')!r}")

        #: 暴击 / 暴击伤害 只应该在核心属性里出现
        core_names = d.get("coreNames") or []
        check("M9",
              "暴击" in core_names and "暴击伤害" in core_names,
              f"核心属性里含暴击 / 暴击伤害 = {core_names[:4]}")

        shot_then("42-mutex-core-first.png", check_summaries)

    # ══════════════════════════════════════════════════════════════════
    #  ④ 摘要行跟着变
    # ══════════════════════════════════════════════════════════════════
    SUMMARIES = """
    (function(){
      var overlay = document.querySelector('.dlg-overlay');
      if (!overlay) return JSON.stringify({ok:false, why:'弹框没打开'});
      var coreCard = null, optCard = null;
      overlay.querySelectorAll('.coll-card').forEach(function(c){
        var t = (c.textContent || '');
        if (t.indexOf('可选属性') >= 0 && !optCard) optCard = c;
        if (t.indexOf('核心属性') >= 0 && !coreCard) coreCard = c;
      });
      function summaryOf(card){
        var el = card ? card.querySelector('.coll-summary') : null;
        return el ? (el.textContent || '').trim() : '';
      }
      //: 可选网格里不应该出现暴击 / 暴击伤害
      var optNames = [];
      if (optCard) {
        optCard.querySelectorAll('.enh-check').forEach(function(lbl){
          optNames.push((lbl.textContent || '').trim());
        });
      }
      return JSON.stringify({
        ok: true,
        coreSummary: summaryOf(coreCard),
        optSummary: summaryOf(optCard),
        optNames: optNames
      });
    })()
    """

    def check_summaries() -> None:
        d = _loads(shell.debug_js(SUMMARIES))
        check("S1", bool(d.get("ok")), f"读摘要 = {d.get('why') or 'ok'}")
        core_sum = str(d.get("coreSummary") or "")
        opt_sum = str(d.get("optSummary") or "")
        check("S2", "已勾选" in core_sum,
              f"核心属性摘要刷新了 = {core_sum!r}")
        check("S3", opt_sum == "未选" or "已选" in opt_sum,
              f"可选属性摘要刷新了 = {opt_sum!r}")

        opt_names = d.get("optNames") or []
        check("S4",
              "暴击" not in opt_names and "暴击伤害" not in opt_names,
              f"可选属性网格里没有暴击/爆伤 = {opt_names[:5]}")

        finish()

    def finish() -> None:
        print()
        if failures:
            print(f"✗ {len(failures)} 项失败：")
            for f in failures:
                print("   -", f)
        else:
            print("✓ 全部通过")
        app.quit()

    QTimer.singleShot(2600, stage_config)
    QTimer.singleShot(60000, lambda: (print("TIMEOUT"), app.quit()))
    app.exec()
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
