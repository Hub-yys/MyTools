# -*- coding: utf-8 -*-
"""验证「任务完成后自动关机」（人工复核用，不进产品）。

跑法::

    .venv\\Scripts\\python.exe src\\gui\\web\\dev\\web_shell_task_shutdown_verify.py

## 检查什么

★ 2026-11-04 用户：「任务完成后自动关机」。

不只看代码，真的开界面点开关、读设置、模拟「流程跑完」：

1. 任务页有「完成后自动关机」卡（开关 + 分钟框 + 说明）
2. 打开开关 → 后端 ``getTaskShutdown`` 返回 enabled
3. 改分钟数 → 后端存住了
4. 模拟流程跑完（``_arm_task_shutdown``）→ 页面出现倒计时条
5. 点「取消关机」→ 倒计时条消失、后端 active=False
6. 关掉开关 → 后端 enabled=False

## 安全措施

**绝不会真的关机** —— 起倒计时前把 ``shutdown_timer.shutdown``
换成桩函数（返回成功、什么都不做），且用 1440 分钟（24 小时）起计时。
跑完还会把 ``data/tool_settings.json`` 原样还回去。

退出码 0 = 全过，1 = 有失败。
"""

from __future__ import annotations

import json
import os
import shutil
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", "..", ".."))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)
os.environ.setdefault("QT_LOGGING_RULES", "qt.multimedia.*=false")

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

OUT = os.path.join(_ROOT, "data", "_shots")
SETTINGS = os.path.join(_ROOT, "data", "tool_settings.json")
BACKUP = SETTINGS + ".shutdown_verify_bak"

failures: list[str] = []


def check(tag: str, ok: bool, detail: str = "") -> None:
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {tag} {detail}")
    if not ok:
        failures.append(f"{tag} {detail}")


def _sections() -> list[str]:
    """``tool_settings.json`` 里现有的节名（排序）。读不出来就是空。"""
    try:
        with open(SETTINGS, "r", encoding="utf-8") as fp:
            data = json.load(fp)
    except Exception:  # noqa: BLE001
        return []
    return sorted(data) if isinstance(data, dict) else []


def main() -> int:
    app = QApplication.instance() or QApplication([])
    import src.tools as tools_pkg  # noqa: PLC0415

    tools_pkg.discover_tools()

    from src.gui.web_shell import WebShell, web_base_url  # noqa: PLC0415

    os.makedirs(OUT, exist_ok=True)

    #: 备份用户设置，跑完还原（这个验证会写 auto_shutdown_* 两个键）
    if os.path.exists(SETTINGS):
        shutil.copy2(SETTINGS, BACKUP)

    shell = WebShell(base_url=web_base_url())
    shell.build()
    view = shell._view
    view.resize(1400, 880)
    view.show()

    bridge = shell._bridge
    out: dict[str, object] = {}
    #: 写下任务页设置**之前**的节名快照 —— 用来证明「合并写」没丢别人的配置
    out["sectionsBefore"] = _sections()

    #: ★ 安全闸：把真关机换成桩，防止探测过程中真的把机器关了
    import src.core.shutdown_timer as shutdown_timer  # noqa: PLC0415

    shutdown_timer.shutdown = lambda **kw: (True, "验证桩：没有真的关机")

    def js(code: str, next_fn, delay: int = 400):
        QTimer.singleShot(delay, lambda: _run_js(code, next_fn))

    def _run_js(code: str, next_fn):
        try:
            result = shell.debug_js(code)
        except Exception as exc:  # noqa: BLE001
            print(f"[FAIL] debug_js 异常：{exc}")
            failures.append(f"debug_js 异常：{exc}")
            finish()
            return
        out["last"] = result
        next_fn(result)

    # ---------------------------------------------------------------- 步骤
    def step_home():
        js("window.App && App.go('tasks', {silent:true}); 'ok'", step_card, 900)

    def step_card(_res):
        js(
            """(function(){
              var card = document.querySelector('#page-tasks .task-shutdown');
              var toggle = document.querySelector('#page-tasks [data-action="toggle-shutdown"]');
              var minutes = document.querySelector('#page-tasks #task-shutdown-minutes');
              var hint = document.querySelector('#page-tasks .task-shutdown-hint');
              var countdown = document.querySelector('#page-tasks .task-shutdown-countdown');
              return JSON.stringify({
                hasCard: !!card,
                hasTitle: !!document.querySelector('#page-tasks .task-shutdown .section-title'),
                hasToggle: !!toggle,
                toggleChecked: toggle ? !!toggle.querySelector('input').checked : null,
                hasMinutes: !!minutes,
                minutesDisabled: minutes ? minutes.disabled : null,
                hintText: hint ? hint.textContent : '',
                countdownHidden: countdown ? countdown.classList.contains('hidden') : null
              });
            })()""",
            step_check_card,
        )

    def step_check_card(res):
        data = json.loads(res) if isinstance(res, str) else {}
        out["card"] = data
        check("K1 有「完成后自动关机」卡", data.get("hasCard") is True, str(data.get("hasCard")))
        check("K2 有标题", data.get("hasTitle") is True)
        check("K3 有开关", data.get("hasToggle") is True)
        check("K4 有分钟框", data.get("hasMinutes") is True,
              f"disabled={data.get('minutesDisabled')}")
        check("K5 有说明文字", bool((data.get("hintText") or "").strip()),
              repr((data.get("hintText") or "")[:40]))
        check("K6 初始没有倒计时条", data.get("countdownHidden") is True)
        step_toggle_on()

    def step_toggle_on():
        #: 点开关：直接改 checked + 派发 change（和真人点一下等价）
        js(
            """(function(){
              var box = document.querySelector('#page-tasks [data-action="toggle-shutdown"]');
              var input = box.querySelector('input');
              var setter = Object.getOwnPropertyDescriptor(
                HTMLInputElement.prototype, 'checked').set;
              setter.call(input, true);
              input.dispatchEvent(new Event('change', {bubbles:true}));
              return 'ok';
            })()""",
            step_read_after_toggle, 600,
        )

    def step_read_after_toggle(_res):
        try:
            raw = bridge.getTaskShutdown()
            data = json.loads(raw) if isinstance(raw, str) else raw
        except Exception as exc:  # noqa: BLE001
            data = {}
            print(f"[FAIL] getTaskShutdown 异常：{exc}")
            failures.append("getTaskShutdown 异常")
        out["afterToggle"] = data
        check("K7 开关打开后后端 enabled", bool(data.get("enabled")) is True, str(data))
        check("K8 后端给了 min/max 范围",
              data.get("minMinutes") == 1 and data.get("maxMinutes") == 1440,
              f"{data.get('minMinutes')}~{data.get('maxMinutes')}")
        step_set_minutes()

    def step_set_minutes():
        #: 改分钟数 → 触发 change → 存盘
        js(
            """(function(){
              var input = document.querySelector('#page-tasks #task-shutdown-minutes');
              var setter = Object.getOwnPropertyDescriptor(
                HTMLInputElement.prototype, 'value').set;
              setter.call(input, '45');
              input.dispatchEvent(new Event('change', {bubbles:true}));
              return 'ok';
            })()""",
            step_read_minutes, 700,
        )

    def step_read_minutes(_res):
        try:
            raw = bridge.getTaskShutdown()
            data = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:  # noqa: BLE001
            data = {}
        out["minutes"] = data
        check("K9 分钟数存住了", data.get("minutes") == 45, str(data.get("minutes")))
        #: 顺便确认确实落了盘（不是只在内存里）
        try:
            with open(SETTINGS, "r", encoding="utf-8") as fp:
                saved = json.load(fp)
            section = saved.get("tasks") or {}
            check("K10 设置写进了 tool_settings.json 的 tasks 节",
                  section.get("auto_shutdown_enabled") is True
                  and section.get("auto_shutdown_minutes") == 45,
                  str(section))
        except Exception as exc:  # noqa: BLE001
            check("K10 设置写进了 tool_settings.json 的 tasks 节", False, str(exc))
        #: K20 —— 存任务页设置**绝不能**碰掉别的工具的配置。
        #: 后端是「合并写」（先 load_all 再改自己那节），这里锁住这个行为：
        #: 少了任何一节，说明有人把 save 改成了整文件覆盖。
        lost = [name for name in out.get("sectionsBefore") or [] if name not in _sections()]
        check("K20 存任务页设置没有碰掉别的工具的配置", not lost,
              f"丢了 {lost}" if lost else f"原有 {len(out.get('sectionsBefore') or [])} 节都在")
        step_arm()

    def step_arm():
        #: 模拟「流程成功跑完」—— 直接调后端那个挂倒计时的方法
        try:
            bridge._arm_task_shutdown(1440, "验证用流程")
        except Exception as exc:  # noqa: BLE001
            print(f"[FAIL] _arm_task_shutdown 异常：{exc}")
            failures.append("_arm_task_shutdown 异常")
        js(
            """(function(){
              var bar = document.querySelector('#page-tasks .task-shutdown-countdown');
              var text = document.querySelector('#page-tasks .task-shutdown-countdown-text');
              return JSON.stringify({
                hidden: bar ? bar.classList.contains('hidden') : null,
                text: text ? text.textContent : '',
                hasCancel: !!(bar && bar.querySelector('[data-action="cancel-shutdown"]'))
              });
            })()""",
            step_check_arm, 900,
        )

    def step_check_arm(res):
        data = json.loads(res) if isinstance(res, str) else {}
        out["armed"] = data
        check("K11 倒计时条出现", data.get("hidden") is False, str(data.get("hidden")))
        check("K12 倒计时文字含流程名",
              "验证用流程" in (data.get("text") or ""), repr(data.get("text")))
        check("K13 倒计时条里有「取消关机」按钮", data.get("hasCancel") is True)
        try:
            raw = bridge.getTaskShutdown()
            state = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:  # noqa: BLE001
            state = {}
        out["armedState"] = state
        check("K14 后端 active=True", bool(state.get("active")) is True, str(state.get("active")))
        check("K15 后端 flowName 正确", state.get("flowName") == "验证用流程",
              repr(state.get("flowName")))
        #: 倒计时显示中拍一张（这才是这功能真正的样子）
        QTimer.singleShot(400, lambda: _shoot("70-task-shutdown.png", step_cancel))

    def _shoot(name, nxt):
        path = os.path.join(OUT, name)
        try:
            shell.debug_screenshot(path)
            print(f"[INFO] 截图：{path}")
        except Exception as exc:  # noqa: BLE001
            print(f"[WARN] 截图失败：{exc}")
        nxt()

    def step_cancel():
        js(
            """(function(){
              var btn = document.querySelector(
                '#page-tasks [data-action="cancel-shutdown"]');
              if (btn) btn.dispatchEvent(new MouseEvent('click', {bubbles:true}));
              return 'ok';
            })()""",
            step_check_cancel, 900,
        )

    def step_check_cancel(_res):
        js(
            """(function(){
              var bar = document.querySelector('#page-tasks .task-shutdown-countdown');
              return JSON.stringify({
                hidden: bar ? bar.classList.contains('hidden') : null
              });
            })()""",
            step_check_cancel2, 500,
        )

    def step_check_cancel2(res):
        data = json.loads(res) if isinstance(res, str) else {}
        check("K16 取消后倒计时条隐藏", data.get("hidden") is True, str(data.get("hidden")))
        try:
            raw = bridge.getTaskShutdown()
            state = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:  # noqa: BLE001
            state = {}
        check("K17 取消后后端 active=False", bool(state.get("active")) is False,
              str(state.get("active")))
        step_toggle_off()

    def step_toggle_off():
        js(
            """(function(){
              var box = document.querySelector('#page-tasks [data-action="toggle-shutdown"]');
              var input = box.querySelector('input');
              var setter = Object.getOwnPropertyDescriptor(
                HTMLInputElement.prototype, 'checked').set;
              setter.call(input, false);
              input.dispatchEvent(new Event('change', {bubbles:true}));
              return 'ok';
            })()""",
            step_check_off, 800,
        )

    def step_check_off(_res):
        try:
            raw = bridge.getTaskShutdown()
            state = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:  # noqa: BLE001
            state = {}
        check("K18 关掉开关后后端 enabled=False", bool(state.get("enabled")) is False,
              str(state.get("enabled")))
        js(
            """(function(){
              var m = document.querySelector('#page-tasks #task-shutdown-minutes');
              return JSON.stringify({ disabled: m ? m.disabled : null });
            })()""",
            step_check_disabled, 400,
        )

    def step_check_disabled(res):
        data = json.loads(res) if isinstance(res, str) else {}
        check("K19 关掉后分钟框变灰", data.get("disabled") is True, str(data.get("disabled")))
        finish()

    # ---------------------------------------------------------------- 收尾
    def finish():
        print()
        print(f"共 {len(failures)} 项失败" if failures else "全部通过")
        #: 还原用户设置
        try:
            shell._bridge._cancel_task_shutdown(quiet=True)
        except Exception:  # noqa: BLE001
            pass
        if os.path.exists(BACKUP):
            shutil.move(BACKUP, SETTINGS)
            print("[INFO] 已还原 data/tool_settings.json")
        try:
            shell.close()
        except Exception:  # noqa: BLE001
            pass
        app.quit()
        raise SystemExit(0 if not failures else 1)

    QTimer.singleShot(2600, step_home)
    QTimer.singleShot(60000, lambda: (print("[FAIL] 超时"), app.quit(), sys.exit(1)))
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
