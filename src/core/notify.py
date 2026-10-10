# -*- coding: utf-8 -*-
"""「任务 / 工具跑完了」→ 记一条消息的**统一入口**。

用户 2026-10-10::

    "每个任务完成/失败都要进行通知，
     声骸批量调频、声骸自动强化等工具完成/失败时也要通知"

## 为什么要有这个模块（而不是每处各写一行）

要通知的地方**至少有五处**：任务流程、声骸自动强化、声骸批量调频、
4C 自动战斗、声骸自动强化里的自动停止。如果每处各自 ``store.add(...)``，
马上就会出现：标题格式不统一（"完成" / "已完成" / "跑完了"）、
级别记错（失败记成 info）、漏掉一处（用户再报一次"XX 没通知"）。

→ 所有调用方都走 :func:`report`，把"标题怎么拼、级别怎么定"收在一处。

## ⚠ 不依赖 Qt

``notify_page`` 那个页面是 Qt 的，但**记录**这件事不该依赖界面 ——
任务跑在引擎线程里，不该为了记一条消息去碰 Qt 对象。
所以这里只碰 ``core.notifications``，界面自己读 store。

## ⚠ 拿不到 store 时**静默跳过**

程序启动早期（工具页构造）或单测里，用户数据目录可能还没准备好。
记不上消息是件小事，**绝不该**把任务本身搞崩。
"""

from __future__ import annotations

from . import notifications as N
from .registry import logger

#: 复用的 store（整个进程一份，和界面那份是同一个文件）
_store: N.NotificationStore | None = None


def store() -> N.NotificationStore:
    """取（必要时建）进程内共用的 store。"""
    global _store
    if _store is None:
        _store = N.NotificationStore()
    return _store


def set_store(value: N.NotificationStore | None) -> None:
    """换一个 store（**测试用**：指到临时文件，别写用户真实的消息历史）。"""
    global _store
    _store = value


def report(title: str, body: str = "", *, ok: bool = True,
           level: str | None = None) -> N.Notice | None:
    """记一条「任务结果」消息。

    :param title: 给人看的标题（如 ``"声骸自动强化 · 完成"``）
    :param body: 详情 / 统计（可为空）
    :param ok: 成功还是失败 —— **决定级别**（不传 level 时用它的）
    :param level: 显式指定级别（自动停止那种既非成功也非失败的情况用）
    :return: 记下来的那条；记不上返回 ``None``

    ⚠ 级别默认由 ``ok`` 定：**不要让调用方自己拼 level** ——
    那正是"失败记成 info"的来源。
    """
    if level is None:
        level = N.LEVEL_SUCCESS if ok else N.LEVEL_ERROR
    try:
        return store().add(title, body, level=level)
    except Exception:  # noqa: BLE001 - 记不上消息不该影响任务
        logger.warning("记通知失败：%s", title, exc_info=True)
        return None


def report_task_result(name: str, *, ok: bool, detail: str = "") -> N.Notice | None:
    """「任务 X 完成 / 失败」的**标准写法**（标题统一在这里拼）。

    :param name: 任务名（如 ``"声骸自动强化"``）
    :param ok: 成功 / 失败
    :param detail: 详情（统计、失败原因…）

    标题固定为 ``"<名字> · 完成"`` / ``"<名字> · 失败"``——
    用户在消息列表里扫一眼就知道是哪个工具的什么结局。
    """
    name = str(name or "").strip() or "任务"
    return report(f"{name} · {'完成' if ok else '失败'}", detail, ok=ok)
