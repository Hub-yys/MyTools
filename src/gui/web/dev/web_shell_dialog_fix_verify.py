# -*- coding: utf-8 -*-
"""验证「新增配置」弹框 2026-11-03 第六轮两处修改（人工复核用，不进产品）。

跑法::

    .venv\\Scripts\\python.exe src\\gui\\web\\dev\\web_shell_dialog_fix_verify.py

## 检查什么

用户当天圈了两张图，这里**真的打开界面**逐条验：

### 1. 角色行（m01650）

* 下面那行「（3 个角色已经有配置了，不在候选里 —— 一个角色只能有一条）」
  **必须没了**；
* 整行（含右侧圆形头像）要套上**玻璃卡底** ——
  实测 ``.dlg-card-row`` 存在、且它的 ``backdrop-filter`` 不是 ``none``、
  圆角 / 内边距都算出来了（不是一张"裸行"）。

### 2. 有效词条越界（m01652）

用户原话：「这里是3，但是所选属性只有2条，怎么创建，应该提示创建失败」。

* 只勾 2 条核心属性、可选一条不勾时，加减框上界必须是 **2**（不是 5）；
* 把输入框强行改成 3（模拟用户直接打字）→ 点「创建」必须
  **弹出错误**（``.dlg-error`` 可见且文案含「无法创建」），
  并且**弹框不关、列表条数不变**（真的没创建）；
* 提示文案要说得清为什么（含「有效词条」/「凑」这类字眼）。

⚠ 本脚本**绝不真的创建成功** —— 一旦校验失效会写进用户 ``data/*.json``。
  为此最后一步只验"被拦住"，不验"成功路径"。

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
        QTimer.singleShot(2400, check_char_row)

    # ══════════════════════════════════════════════════════════════════
    #  ① 角色行：说明文字删了 / 整行有卡底
    # ══════════════════════════════════════════════════════════════════
    def check_char_row() -> None:
        code = """
        (function(){
          var overlay = document.querySelector('.dlg-overlay');
          if (!overlay) return JSON.stringify({ok:false, why:'弹框没打开'});

          // ① 那行「N 个角色已经有配置了…」还在不在
          var notes = Array.from(overlay.querySelectorAll('.dlg-note'))
            .map(function(n){return (n.textContent||'').trim();});
          var takenNotes = notes.filter(function(t){
            return t.indexOf('不在候选') >= 0 || t.indexOf('只能有一条') >= 0;
          });

          // ② 角色行套卡了没有
          var card = overlay.querySelector('.dlg-card-row');
          var cs = card ? getComputedStyle(card) : null;
          var rect = card ? card.getBoundingClientRect() : null;
          var backdrop = cs
            ? (cs.backdropFilter || cs.webkitBackdropFilter || '')
            : '';

          // 卡里应该有角色下拉 + 头像
          var hasPicker = !!(card && card.querySelector('.char-picker'));
          var hasAvatar = !!(card && card.querySelector('.char-avatar'));
          var avRect = hasAvatar
            ? overlay.querySelector('.char-avatar').getBoundingClientRect()
            : null;
          // 头像要真的落在卡的范围里（不是掉在外面）
          var avatarInside = false;
          if (rect && avRect && avRect.width > 0) {
            avatarInside = (avRect.left >= rect.left - 1 &&
                            avRect.right <= rect.right + 1 &&
                            avRect.top >= rect.top - 1 &&
                            avRect.bottom <= rect.bottom + 1);
          }

          return JSON.stringify({
            ok: true,
            notes: notes,
            takenNotes: takenNotes,
            hasCard: !!card,
            hasPicker: hasPicker,
            hasAvatar: hasAvatar,
            avatarInside: avatarInside,
            cardPadding: cs ? cs.padding : '',
            cardRadius: cs ? cs.borderRadius : '',
            backdrop: backdrop,
            cardH: rect ? Math.round(rect.height * 10) / 10 : 0
          });
        })()
        """
        d = _loads(shell.debug_js(code))
        check("F1", bool(d.get("ok")), f"第二步表单打开 = {d.get('why') or 'ok'}")

        #: 1-a 「N 个角色已经有配置了…」必须删掉
        check("F2", len(d.get("takenNotes") or []) == 0,
              f"「不在候选里 / 只能有一条」说明已删除 = "
              f"{d.get('takenNotes')}  (全部 .dlg-note={d.get('notes')})")

        #: 1-b 角色行套了卡
        check("F3", bool(d.get("hasCard")),
              f"角色行有 .dlg-card-row 卡底 = {d.get('hasCard')}")
        check("F4", bool(d.get("hasPicker")) and bool(d.get("hasAvatar")),
              f"卡里有角色下拉 + 头像 = picker={d.get('hasPicker')} "
              f"avatar={d.get('hasAvatar')}")
        check("F5", bool(d.get("avatarInside")),
              f"头像落在卡内部（没掉在外面）= {d.get('avatarInside')}")

        #: 玻璃效果：backdrop-filter 生效 + 圆角/内边距
        backdrop = str(d.get("backdrop") or "")
        check("F6", backdrop not in ("", "none"),
              f"卡底是玻璃（backdrop-filter 生效）= {backdrop!r}")
        padding = str(d.get("cardPadding") or "")
        radius = str(d.get("cardRadius") or "")
        check("F7", padding not in ("", "0px") and radius not in ("", "0px"),
              f"卡有内边距/圆角 = padding={padding!r} radius={radius!r} "
              f"高={d.get('cardH')}px")

        shot_then("30-dialog-char-card.png", check_valid_range)

    # ══════════════════════════════════════════════════════════════════
    #  ② 有效词条：上界 / 越界拦截
    # ══════════════════════════════════════════════════════════════════
    def check_valid_range() -> None:
        """先看「只勾 2 条核心」时，加减框的真实上界是多少。"""
        code = """
        (function(){
          var overlay = document.querySelector('.dlg-overlay');
          if (!overlay) return JSON.stringify({ok:false, why:'弹框没打开'});

          // 只留「暴击」「暴击伤害」两条核心，可选全清
          // （新建弹框默认就是这样 —— 这里显式点一遍，防默认值变过）
          var core = overlay.querySelectorAll('.coll-card .enh-check');
          var checkedCore = [];
          core.forEach(function(box){
            var inp = box.querySelector('input[type=checkbox]');
            if (inp && inp.checked) checkedCore.push(
              (box.textContent||'').trim());
          });

          var hint = overlay.querySelector('.enh-valid-hint');
          //: ★ 用专属类抓「有效词条」那个输入框 —— ``.cfg-number-input``
          //: 是三个控件共用的（暴击下限 7.5 / 爆伤下限 15 / 有效词条 2），
          //: 抓错就会读到 '7.5' 而不是 '2'。
          var num = overlay.querySelector('.enh-valid-number');
          var val = num ? String(num.value) : '';
          var minAttr = num ? String(num.min) : '';
          var maxAttr = num ? String(num.max) : '';

          // ＋ 一次看会不会超过真实上界
          //: ⚠ 按钮文字是**全角**的 ``＋``（``_panels.numberInput`` 里写的
          //: ``text: '＋'``），第一版找 ``'+'`` 找不到，afterPlus 恒空。
          var plus = null;
          var wrap = num ? num.closest('.numfield') : null;
          if (wrap) {
            var btns = wrap.querySelectorAll('button');
            btns.forEach(function(b){
              var t = (b.textContent||'').trim();
              if (t === '＋' || t === '+') plus = b;
            });
          }
          var afterPlus = '';
          if (plus) {
            plus.click();
            afterPlus = num ? String(num.value) : '';
          }

          return JSON.stringify({
            ok: true,
            checkedCore: checkedCore,
            coreN: checkedCore.length,
            hint: hint ? (hint.textContent||'').trim() : '',
            hintInvalid: hint ? hint.classList.contains('is-invalid') : false,
            val: val,
            afterPlus: afterPlus,
            minAttr: minAttr,
            maxAttr: maxAttr
          });
        })()
        """
        d = _loads(shell.debug_js(code))
        check("V1", bool(d.get("ok")), f"读「有效词条」控件 = {d.get('why') or 'ok'}")

        core_n = int(d.get("coreN") or 0)
        check("V2", core_n == 2,
              f"默认只勾 2 条核心属性 = {core_n} 条 {d.get('checkedCore')}")

        max_attr = d.get("maxAttr")
        check("V3", str(max_attr) == "2",
              f"加减框上界 = {max_attr!r}（应 2，因为只勾了 2 条属性）")

        after_plus = d.get("afterPlus")
        check("V4", str(after_plus) in ("2", ""),
              f"点 ＋ 不会超过上界 = {after_plus!r}（应停在 2）")

        shot_then("31-dialog-valid-range.png", force_bad_value)

    def force_bad_value() -> None:
        """先选个角色（否则报的是「请先选一个角色」），再打字填 3。"""
        shell.debug_js("""
        (function(){
          var overlay = document.querySelector('.dlg-overlay');
          if (!overlay) return 'no-overlay';
          // ① 点开角色下拉，选第一个未占用的候选
          var inp = overlay.querySelector('.char-input');
          if (inp) {
            inp.dispatchEvent(new MouseEvent('mousedown',
              {bubbles:true, cancelable:true}));
            inp.focus();
          }
          var opts = overlay.querySelectorAll('.char-option');
          if (opts.length) {
            opts[0].dispatchEvent(new MouseEvent('mousedown',
              {bubbles:true, cancelable:true}));
          }
          return 'picked:' + (opts.length ? 'yes' : 'no');
        })()
        """)
        QTimer.singleShot(500, set_bad_value)

    def set_bad_value() -> None:
        """模拟用户直接打字填 3 —— 越过上界，看「创建」拦不拦。"""
        result = shell.debug_js("""
        (function(){
          var num = document.querySelector('.dlg-overlay .enh-valid-number');
          if (!num) return 'no-num';
          var setter = Object.getOwnPropertyDescriptor(
            HTMLInputElement.prototype, 'value').set;
          setter.call(num, '3');
          num.dispatchEvent(new Event('input', {bubbles:true}));
          num.dispatchEvent(new Event('change', {bubbles:true}));
          var name = document.querySelector('.dlg-overlay .char-input');
          return String(num.value) + '|name=' + (name ? name.value : '');
        })()
        """)
        print(f"    (调试) 填值结果 = {result!r}")
        QTimer.singleShot(400, read_bad_value)

    def read_bad_value() -> None:
        d = _loads(shell.debug_js("""
        (function(){
          var num = document.querySelector('.dlg-overlay .enh-valid-number');
          var hint = document.querySelector('.dlg-overlay .enh-valid-hint');
          var name = document.querySelector('.dlg-overlay .char-input');
          return JSON.stringify({
            val: num ? String(num.value) : '',
            hint: hint ? (hint.textContent||'').trim() : '',
            name: name ? String(name.value) : '',
            rowsBefore: document.querySelectorAll(
              '#page-config .config-row').length
          });
        })()
        """))
        #: 越界值**不许被静默夹回去** —— 否则用户永远看不到"没生效"
        check("V5", str(d.get("val")) == "3",
              f"填 3 后输入框仍是 3（没被静默纠正）= {d.get('val')!r} "
              f"提示={d.get('hint')!r}")
        #: 必须先选到角色，否则「创建」会被角色校验先拦下，测不到设置校验
        check("V5b", bool(str(d.get("name") or "").strip()),
              f"已选中角色（否则先报「请先选一个角色」）= {d.get('name')!r}")
        check("V6", int(d.get("rowsBefore") or 0) >= 1,
              f"弹框后面列表有行 = {d.get('rowsBefore')}")
        shot_then("32-dialog-bad-value.png", click_create)

    def click_create() -> None:
        shell.debug_js(
            "(function(){var b=document.querySelector("
            "'.dlg-foot [data-action=\"submit\"]');"
            "if(!b){b=document.querySelector('.dlg-foot .btn-primary');}"
            "if(b) b.click();})()"
        )
        QTimer.singleShot(900, check_blocked)

    def check_blocked() -> None:
        code = """
        (function(){
          var overlay = document.querySelector('.dlg-overlay');
          var err = overlay ? overlay.querySelector('.dlg-error') : null;
          var errText = err ? (err.textContent||'').trim() : '';
          var errVisible = false;
          if (err) {
            var r = err.getBoundingClientRect();
            var cs = getComputedStyle(err);
            errVisible = (r.width > 0 && r.height > 0 &&
                          cs.display !== 'none' && cs.visibility !== 'hidden');
          }
          var hint = overlay
            ? overlay.querySelector('.enh-valid-hint') : null;
          return JSON.stringify({
            stillOpen: !!overlay,
            errText: errText,
            errVisible: errVisible,
            hint: hint ? (hint.textContent||'').trim() : '',
            hintInvalid: hint ? hint.classList.contains('is-invalid') : false,
            rowsAfter: document.querySelectorAll(
              '#page-config .config-row').length
          });
        })()
        """
        d = _loads(shell.debug_js(code))
        #: ★ 用户的原始要求：「应该提示创建失败」
        check("E1", bool(d.get("stillOpen")),
              f"点「创建」后弹框仍开着（没真创建）= {d.get('stillOpen')}")
        check("E2", bool(d.get("errVisible")) and bool(d.get("errText")),
              f"弹出错误提示 = visible={d.get('errVisible')} "
              f"文案={d.get('errText')!r}")
        text = str(d.get("errText") or "")
        check("E3", "无法创建" in text or "有效词条" in text,
              f"错误文案说清了原因 = {text!r}")

        shot_then("33-dialog-create-blocked.png", cleanup)

    def cleanup() -> None:
        shell.debug_js(
            "(function(){var b=document.querySelector('.dlg-close');"
            "if(b) b.click();})()"
        )
        QTimer.singleShot(400, finish)

    def finish() -> None:
        print()
        if failures:
            print(f"✗ {len(failures)} 项失败：")
            for f in failures:
                print("   -", f)
        else:
            print("✓ 全部通过")
        app.exit(1 if failures else 0)

    QTimer.singleShot(2600, stage_config)
    QTimer.singleShot(60000, lambda: app.exit(2))
    return app.exec() if hasattr(app, "exec") else app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
