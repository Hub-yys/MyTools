# -*- coding: utf-8 -*-
"""真实启动 ok-ww 引擎，断言 ``TASKS`` 里的任务**确实注册进了引擎**。

    ./.venv/Scripts/python.exe tests/check_okww_registration.py

## 为什么需要这个检查（2026-09-24 事故）

ok-script 的 ``task_manager.init_tasks()``::

    if len(task.supported_languages) == 0 or locale_name in task.supported_languages:
        tasks.append(task)

—— **不满足就静默不注册**。宿主是无 GUI 的（``resolve_ui_config(None) → headless``），
``init_app_config()`` 拿不到 ok-ww GUI 里那个「语言」设置，``app.locale`` 实测就是
qfluentwidgets 的默认值 **en_US**；而 ok-ww 的 ``EnhanceEchoTask`` 声明了
``supported_languages = ["zh_CN", "zh_TW"]``。

结果：MyTools 的声骸强化任务**根本没进引擎**，页面上一切正常、点「运行」却什么
都不发生。这种"静默消失"光靠读代码看不出来，必须真起一次引擎数一数。

不需要游戏、不需要管理员权限；大约 10 秒。
"""
from __future__ import annotations

import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

BOOT_TIMEOUT = 180          # 首次可能要解 OCR 模型，给足


def main() -> int:
    from src.tools.game.auto_combat.okww_boot import TASKS, get_host

    host = get_host()
    print("· 启动 ok-ww 引擎（无需游戏）…", flush=True)
    host.boot()

    deadline = time.time() + BOOT_TIMEOUT
    while time.time() < deadline and host.state not in ("ready", "error"):
        time.sleep(1)

    if host.state == "error":
        print("[FAIL] 引擎启动失败：%s" % host.boot_error)
        return 1
    if host.state != "ready":
        print("[FAIL] %d 秒内没就绪（当前 %s）" % (BOOT_TIMEOUT, host.state))
        return 1

    registered = host.registered_task_names()
    print("引擎已就绪；注册的任务类：%s" % ("、".join(registered) or "（无）"))

    locale = getattr(host._ok.app, "locale", None)
    locale_name = locale.name() if hasattr(locale, "name") else str(locale or "?")
    print("引擎语言：%s" % locale_name)

    failures: list[str] = []
    for key, class_name in TASKS.items():
        task = host.find_task(key)
        if task is None:
            failures.append("%s（类名 %s）" % (key, class_name))
            print("  [FAIL] %s -> %s" % (key, class_name))
        else:
            print("  [PASS] %s -> %s" % (key, type(task).__name__))

    if failures:
        print("\n[FAIL] 这些任务没注册：%s" % "；".join(failures))
        print("提示：ok-script 会因 supported_languages 与引擎语言不符而**静默跳过**；"
              "任务类必须显式清空它（见 src/tools/game/echo_enhance/okww_task.py）。")
        return 1

    print("\n[PASS] %d 个任务全部已注册。" % len(TASKS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
