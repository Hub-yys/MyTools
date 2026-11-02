# -*- coding: utf-8 -*-
"""★ 验证 `Bridge.callWith()` —— 多参数 Slot 到底能不能调通。

## 为什么需要这个（2026-11-02，page-converter 报的）

``QWebChannel`` 按 **JS 实参个数**精确匹配 Slot 签名。个数不对时：

.. code:: text

    No candidates found for "deleteConfig" with 1 arguments

**不抛异常、不 reject**，Promise 永远挂着 —— 最阴的一类失败。

``deleteConfig(kind, id)`` 是 ``@Slot(str, str, result=str)``，
第一版 ``Bridge.call('deleteConfig', kind)`` 只传 1 个，永远调不通。

修法：``bridge.js`` 加了 ``callWith(method, argsArray)``。

## 这个脚本验什么

真开一个 QWebChannel，从**页面里**调这几个方法，确认：

1. ``callWith('deleteConfig', [kind, id])`` → 真的到达 Python（拿到返回）
2. ``call('deleteConfig', kind)`` → **失败**（证明个数确实必须匹配，
   也证明测试是有效的 —— 不是两个都"通过"其实都没调）
3. ``callWith`` 对 0/1 参方法也能用（通用性）
4. 单参方法用 ``call`` 仍然正常（没破坏老路径）

⚠ **不真的删数据**：用不存在的 id，Python 会返回 ``not_found`` ——
能拿到这个 JSON 就说明打通了。
"""

from __future__ import annotations

import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", "..", ".."))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)
os.environ.setdefault("QT_LOGGING_RULES", "qt.multimedia.*=false")

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

FAILS: list[str] = []


def ok(tag: str, cond: bool, note: str = "") -> None:
    print(f"[{'PASS' if cond else 'FAIL'}] {tag}  {note}")
    if not cond:
        FAILS.append(tag)


def main() -> int:
    app = QApplication.instance() or QApplication([])
    import src.tools as tools_pkg

    tools_pkg.discover_tools()
    from src.gui.web_shell import WebShell, web_base_url

    shell = WebShell(base_url=web_base_url())
    if not shell.build():
        ok("build", False, "WebShell.build 失败")
        return 1
    shell.view.resize(1100, 720)
    shell.view.show()

    def probe() -> None:
        #: 页面里跑：先确认 callWith 存在，再真调
        raw = shell.debug_js(
            "JSON.stringify({"
            "has_call: typeof (window.Bridge && Bridge.call),"
            "has_callWith: typeof (window.Bridge && Bridge.callWith)"
            "})")
        try:
            info = json.loads(raw or "{}")
        except ValueError:
            info = {}
        ok("bridge_callWith_exists",
           info.get("has_callWith") == "function",
           f"Bridge.callWith = {info.get('has_callWith')}")
        ok("bridge_call_exists",
           info.get("has_call") == "function",
           f"Bridge.call = {info.get('has_call')}")

        #: ★ 核心测试：从页面里真的调（异步 → 把结果写到 window，再轮询读）
        shell.debug_js(
            "window.__R__ = {done: false, results: {}};"
            #: ① 多参方法走 callWith
            "Bridge.callWith('deleteConfig', ['loadout', '__nope__'])"
            "  .then(function (r) {"
            "    window.__R__.results.multi = r;"
            "    window.__R__.multi_ok = true;"
            "  }, function (e) {"
            "    window.__R__.multi_ok = false;"
            "    window.__R__.multi_err = String(e);"
            "  })"
            #: ② 单参方法走 call（老路径不能被破坏）
            "  .then(function () { return Bridge.call('runTask', '__nope__'); })"
            "  .then(function (r) {"
            "    window.__R__.results.single = r;"
            "    window.__R__.single_ok = true;"
            #: ③ 零参方法
            "    return Bridge.call('getSkin');"
            "  })"
            "  .then(function (r) {"
            "    window.__R__.results.zero = r ? Object.keys(r).length : 0;"
            "    window.__R__.zero_ok = true;"
            #: ④ callWith 对单参也能用
            "    return Bridge.callWith('switchPage', ['home']);"
            "  })"
            "  .then(function (r) {"
            "    window.__R__.results.one_via_callWith = r;"
            "    window.__R__.one_ok = true;"
            "    window.__R__.done = true;"
            "  }, function (e) {"
            "    window.__R__.error = String(e);"
            "    window.__R__.done = true;"
            "  });"
            "'started'")
        QTimer.singleShot(2500, read_results)

    def read_results() -> None:
        raw = shell.debug_js("JSON.stringify(window.__R__ || {})")
        try:
            r = json.loads(raw or "{}")
        except ValueError:
            r = {}
        results = r.get("results") or {}

        ok("async_completed", r.get("done") is True,
           f"done={r.get('done')} error={r.get('error')}")

        #: ① 多参 —— 这是本次要验的核心
        multi = results.get("multi")
        ok("multi_arg_reached_python",
           isinstance(multi, dict) and multi.get("reason") == "not_found",
           f"deleteConfig → {json.dumps(multi, ensure_ascii=False)[:120]}")

        #: ② 单参老路径
        single = results.get("single")
        ok("single_arg_still_works",
           isinstance(single, dict) and single.get("reason") == "unknown_tool",
           f"runTask → {json.dumps(single, ensure_ascii=False)[:100]}")

        #: ③ 零参
        ok("zero_arg_works", r.get("zero_ok") is True
           and int(results.get("zero") or 0) >= 4,
           f"getSkin 返回 {results.get('zero')} 个字段")

        #: ④ callWith 通用性
        one = results.get("one_via_callWith")
        ok("callWith_works_for_one_arg",
           isinstance(one, dict) and one.get("ok") is True,
           f"switchPage → {json.dumps(one, ensure_ascii=False)[:80]}")

        #: ★ 反向验证：用 call（1 参）调 deleteConfig（2 参）应当**失败**。
        #: 这证明"个数必须匹配"确实成立 —— 不然上面几条可能都是假通过。
        shell.debug_js(
            "window.__NEG__ = {done: false};"
            "Bridge.call('deleteConfig', 'loadout')"
            "  .then(function (r) {"
            "    window.__NEG__.result = r;"
            "    window.__NEG__.done = true;"
            "  }, function (e) {"
            "    window.__NEG__.error = String(e);"
            "    window.__NEG__.done = true;"
            "  });"
            #: 兜底：3 秒后强制标 done（真静默失败时 Promise 根本不会 settle）
            "setTimeout(function () {"
            "  if (!window.__NEG__.done) {"
            "    window.__NEG__.done = true;"
            "    window.__NEG__.timeout = true;"
            "  }"
            "}, 3000);"
            "'started'")
        QTimer.singleShot(3800, read_negative)

    def read_negative() -> None:
        raw = shell.debug_js("JSON.stringify(window.__NEG__ || {})")
        try:
            n = json.loads(raw or "{}")
        except ValueError:
            n = {}

        #: 1 个参数调 2 参 Slot 的真实表现（实测 2026-11-02）：
        #:
        #:   ``{"done": true, "result": []}``
        #:
        #: 也就是 QWebChannel 没找到匹配的 Slot，回调被调用时给的是
        #: **空数组**（不是我们约定的 JSON 字符串，也没有 ``reason``）。
        #: 页面侧 ``JSON.parse('[]')`` → ``[]``，于是 ``result.ok`` 是
        #: ``undefined`` —— **不报错、不 reject**，最阴的失败形态。
        #:
        #: 所以判据是：结果里**没有**正常的业务字段（``reason``/``ok``）。
        res = n.get("result")
        timed_out = n.get("timeout") is True
        #: 正常业务返回一定带 ok 或 reason（看 _json 的约定）
        looks_like_real_answer = (
            isinstance(res, dict) and ("ok" in res or "reason" in res)
        )
        bad = timed_out or not looks_like_real_answer
        ok("negative_wrong_arity_fails", bad,
           f"call('deleteConfig') 单参 → {json.dumps(n, ensure_ascii=False)[:130]}"
           f"（不是合法业务返回 → 证明参数个数必须精确匹配）")

        finish(app)

    def finish(app_) -> None:
        print()
        print("=" * 64)
        print("结果：" + ("全部通过" if not FAILS else "失败 " + str(FAILS)))
        print("=" * 64)
        shell.close()
        QTimer.singleShot(300, app_.quit)

    shell.view.loadFinished.connect(lambda o: QTimer.singleShot(3200, probe))
    QTimer.singleShot(45000, app.quit)
    app.exec()
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
