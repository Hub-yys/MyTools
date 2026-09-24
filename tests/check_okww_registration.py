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

## 2026-09-25 又中了一次（不同的原因，同样的症状）

新增「声骸批量调频」时，`TASKS` 加了 `MyToolsChangeEchoTask`，
但 `build_config()["onetime_tasks"]` 那条**还指着 vendored 的原版**
`["okww.task.ChangeEchoTask", "ChangeEchoTask"]` —— 原版自己带语言门禁，
也被跳过了，于是**两个都没注册**。这里当场报：

    [FAIL] 声骸批量调频 -> MyToolsChangeEchoTask
    [FAIL] 这些任务没注册：声骸批量调频（类名 MyToolsChangeEchoTask）

同一个坑能踩第二次，说明**静态护栏**才是关键：`test_okww_vendor.py::`
`test_tasks_exposed_to_page` 现在遍历整个 `TASKS` 对照注册表，1 秒就能红。
这个脚本留作"最后一道真机确认"，新增任务时还是要跑一次。

不需要游戏、不需要管理员权限；实测约 4 秒。
"""
from __future__ import annotations

import os
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
    # ⚠ 必须硬退：ok-script 的 ``TaskExecutor`` 是**非守护线程**，``main()`` 返回后
    #   解释器仍会被它们挂住不退出 —— 实测结论早就在 1 秒内打完了，进程却一直活着，
    #   被外层 timeout 杀掉才算完（120s 白等）。管道里跑（``... | tail``）更迷惑：
    #   stdout 被缓冲住，屏幕上**一个字都没有**，看起来像卡在启动阶段。
    #   结论已经打完，这里直接 os._exit，不等那些线程。
    _rc = main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(_rc)
