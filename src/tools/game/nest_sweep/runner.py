# -*- coding: utf-8 -*-
"""任务流程用的**同步 runner** —— 把 ok-ww 宿主上的扫荡任务包成 ``run()``。

## 为什么要这一层

任务流程（``gui/tasks_interface.FlowRunThread``）是**同步**调 ``runner.run()`` 的
（它自己跑在 QThread 里），而 ok-ww 的任务是**异步**的（丢进引擎队列就返回）。
本模块负责把"异步"桥成"同步"：轮询宿主直到任务跑完或被要求停止。

## ★ ``_configure`` 是"用户当下看到的那份计划"

从**任务流程**里跑的时候没有工具页，用户看不到卡片 —— 那勾选从哪来？

::

    tool_settings.json 里的 selected     ← 唯一来源（工具页存的）

所以这里不去造第二份配置，直接让**任务自己**读盘
（``MyToolsNestSweepTask._resolve_plan`` 的兜底分支）。
runner 只负责"把任务起起来、等它跑完、把结果带回来"。

⚠ 这样"从任务页跑"和"从工具页点运行"用的就是**同一套勾选** ——
本项目在声骸强化那边立下的规矩（见 ``echo_enhance/tool.py`` 的
``_settings_for_run``）：两条入口的规则必须一致，否则会出现
"它按自己的一套刷了"。
"""

from __future__ import annotations

import time

from ..auto_combat.okww_boot import get_host

#: 页面 / TASKS 里的任务名（要和 ``okww_boot.TASKS`` 的键一致）
TASK_KEY = "扫荡残像聚落"


class NestSweepRunner:
    """把 ok-ww 宿主上的扫荡任务包成任务流程能用的 runner。"""

    #: 轮询间隔（秒）
    POLL = 0.3

    #: 「交给引擎后多久还没开始跑」的上限（秒）。
    #:
    #: ⚠ 2026-09-27 用户报「应用卡死」就是栽在这里：引擎把任务排进队列之后
    #: 本该出现 ``get queued onetime_task``（executor 线程真把它取走了），
    #: 那天一直没出现 —— 于是 while 永远转下去，界面上永远「运行中」。
    #: 与其无限等，不如到点认账并说清楚。
    START_TIMEOUT = 60.0

    #: 心跳日志间隔（秒）：长任务期间让日志里能看到"还活着、在等什么"。
    HEARTBEAT = 15.0

    def __init__(self, *, log=None, should_stop=None):
        self._log = log or (lambda msg: None)
        self._should_stop = should_stop or (lambda: False)

    def run(self) -> "SweepSummary":
        host = get_host()
        err = host.start_task(TASK_KEY)
        if err:
            raise RuntimeError(err)
        self._log("扫荡残像聚落：已交给 ok-ww 引擎（按「停止」可中断）")

        last_info: dict = {}
        started = False
        queued_at = time.monotonic()
        last_beat = queued_at
        try:
            while True:
                task = host.find_task(TASK_KEY)
                if task is not None:
                    info = getattr(task, "info", None)
                    if isinstance(info, dict) and info:
                        last_info = dict(info)
                    if getattr(task, "running", False):
                        started = True
                host.poll_done()
                if self._should_stop():
                    host.stop_task()
                    self._log("扫荡残像聚落：已请求停止")
                    break
                if host.running_task != TASK_KEY and host.pending_start != TASK_KEY:
                    break

                now = time.monotonic()
                if not started and now - queued_at > self.START_TIMEOUT:
                    host.stop_task()
                    raise RuntimeError(
                        "已把任务交给 ok-ww 引擎，但 %.0f 秒过去它还没开始跑"
                        "（任务排在队列里，引擎的执行线程没把它取走）—— "
                        "本次没有真正扫荡任何目标，已中止等待。"
                        "引擎侧日志见 data/okww/logs/ok-ww.log"
                        % self.START_TIMEOUT)
                if now - last_beat >= self.HEARTBEAT:
                    last_beat = now
                    self._log("… 等待引擎：已 %.0f 秒（%s）"
                              % (now - queued_at,
                                 "扫荡进行中" if started else "任务还没被引擎取走"))
                time.sleep(self.POLL)
        except Exception:
            host.stop_task()
            raise

        return SweepSummary(info=last_info)


class SweepSummary:
    """任务流程要的 ``.summary()`` 接口。"""

    def __init__(self, *, info: dict | None = None):
        self.info = dict(info or {})

    @property
    def total(self) -> int:
        """这次计划一共几个目标。"""
        try:
            return int(self.info.get("扫荡目标总数") or 0)
        except (TypeError, ValueError):
            return 0

    @property
    def done(self) -> int:
        """实际完成几个。"""
        try:
            return int(self.info.get("扫荡完成数") or 0)
        except (TypeError, ValueError):
            return 0

    def summary(self) -> str:
        """一行结果，进流程报告。

        ⚠ 引擎那条 ``扫荡结果`` 已经带了"未完成：谁谁谁"的明细 ——
        有就直接用它（那是任务自己数出来的、最准），没有才自己拼一个。
        """
        text = str(self.info.get("扫荡结果") or "").strip()
        if text:
            return text
        if self.total:
            return f"扫荡完成：{self.done}/{self.total}"
        return "扫荡结束（引擎没报数量）"
