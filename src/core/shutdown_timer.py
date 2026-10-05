"""定时关机 —— 「跑 N 分钟后关机」+ 关机前提醒。

## 用户要求（按时间先后）

2026-10-01："4C自动战斗增加设置定时关机的功能"，并确认了细节：

* **跑多少分钟后关**（从点「启动」开始计时），不是"到某个时刻关"；
* 关机前**提前提醒且可取消**。

2026-10-05（截图圈出「定时关机」那张卡）::

    "这里改为不用确认，到时间就自动关机"

→ **到点直接关，不再弹"立即关机 / 取消关机"的确认框。**
  提前那 N 秒改成**不挡路的通知**（InfoBar），用户想反悔就点里面的取消。

## ⚠⚠ 为什么必须去掉那个模态确认框（不只是"用户嫌烦"）

原来的写法是：进提醒窗口 → 弹**模态** ``MessageBox`` → 等用户点。

但模态框只挡得住**调用方的代码**，`QTimer` 的轮询**照跑不误**：

    t=0     启动，deadline = 60
    t=1     should_warn → 弹模态框（用户还没点）
    t=61    should_fire → **True** ← 框还开着，电脑照样关了

也就是说「取消关机」按钮**只有 60 秒有效期**，
超过就点不动了 —— 用户以为能取消，其实早就关了。

改成"非模态通知 + 到点直接关"之后，这条时间线**不存在**了：
没有等待中的框，到点就是到点。

## 纯逻辑 + 可测

``ShutdownTimer`` 是**纯状态机**（不碰 Qt、不真的关机）：
``should_fire()`` 返回"该执行关机了"，由调用方去调 :func:`shutdown`。
这样单测能直接喂时间、不用等 30 分钟，也不会真的把你电脑关掉。

## ⚠ 关机是不可逆的

所以保命设计是：

1. **提前通知**（默认 60 秒）—— 不挡路，但看得见；
2. 通知里说清"到点会自动关机，想反悔点这里取消"；
3. ``cancel()`` 在任何阶段都有效 —— **直到真正执行前一刻**。
"""

from __future__ import annotations

import logging
import subprocess
import sys
import time

logger = logging.getLogger(__name__)

#: 关机前的通知时长（秒）
#:
#: ⚠ 用户 2026-10-05 明确了"到时间就自动关机、不用确认" ——
#: 这个秒数现在是**通知**（不挡路），不是"等你点确认"的倒计时。
WARN_SECONDS = 60

#: 允许的分钟范围。上限 24 小时：再长就不该用"定时关机"了
MIN_MINUTES = 1
MAX_MINUTES = 24 * 60

#: ``shutdown`` 命令的等待秒数（Windows 会在关机前强制延迟这么久）
_SHUTDOWN_DELAY = 0


def clamp_minutes(value) -> int:
    """把分钟数夹进 :data:`MIN_MINUTES` ~ :data:`MAX_MINUTES`。

    ⚠ 界面和读设置都调它 —— 边界只有一份，否则会出现"界面夹了、读盘没夹"。
    """
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return 0
    if number <= 0:
        return 0                      # 0 = 不启用
    return max(MIN_MINUTES, min(MAX_MINUTES, number))


class ShutdownTimer:
    """"再过多久关机"的纯状态机。

    用法::

        timer = ShutdownTimer(30)      # 30 分钟后关机
        timer.start()
        ...
        if timer.should_warn():        # 进入提醒窗口（只报一次）
            弹提醒
        if timer.should_fire():        # 到点了
            shutdown()

    时间用 :func:`time.monotonic`（不受系统时钟调整影响）。
    """

    def __init__(self, minutes: int = 0, *, warn_seconds: int = WARN_SECONDS):
        self.minutes = clamp_minutes(minutes)
        self.warn_seconds = max(0, int(warn_seconds))
        self._deadline: float | None = None
        self._warned = False
        self._fired = False

    # ------------------------------------------------------------------ 控制
    @property
    def enabled(self) -> bool:
        return self.minutes > 0

    def start(self, now: float | None = None) -> bool:
        """开始计时（从点「启动」那一刻算）。返回是否真的启用了。"""
        self._warned = False
        self._fired = False
        if not self.enabled:
            self._deadline = None
            return False
        self._deadline = (now if now is not None else time.monotonic()) \
            + self.minutes * 60
        return True

    def cancel(self) -> None:
        """取消 —— 任何阶段都有效（关机真正执行前都来得及）。"""
        self._deadline = None
        self._warned = False
        self._fired = False

    @property
    def active(self) -> bool:
        return self._deadline is not None and not self._fired

    # ------------------------------------------------------------------ 查询
    def remaining(self, now: float | None = None) -> float:
        """还剩多少秒；没在计时返回 0。"""
        if self._deadline is None:
            return 0.0
        current = now if now is not None else time.monotonic()
        return max(0.0, self._deadline - current)

    def remaining_text(self, now: float | None = None) -> str:
        """``"29 分 12 秒"`` / ``"45 秒"`` —— 界面上那一行。"""
        if not self.active:
            return ""
        seconds = int(self.remaining(now))
        minutes, rest = divmod(seconds, 60)
        if minutes:
            return f"{minutes} 分 {rest} 秒"
        return f"{rest} 秒"

    def should_warn(self, now: float | None = None) -> bool:
        """是否该弹提醒了（**只报一次**）。"""
        if not self.active or self._warned:
            return False
        if self.remaining(now) <= self.warn_seconds:
            self._warned = True
            return True
        return False

    def should_fire(self, now: float | None = None) -> bool:
        """是否到点该关机了（**只报一次**）。"""
        if not self.active or self._fired:
            return False
        if self.remaining(now) <= 0:
            self._fired = True
            self._deadline = None
            return True
        return False

    @property
    def warned(self) -> bool:
        return self._warned


def shutdown(*, seconds: int = _SHUTDOWN_DELAY) -> tuple[bool, str]:
    """真的关机。返回 ``(是否成功, 说明)``。

    ⚠ 只对 **Windows** 有效（本项目就是 Windows-only：要管理员、要窗口模式）。
    其它平台直接返回失败并说明 —— 不做"假装关了"。

    ⚠ **这是不可逆操作**，调用方必须已经确认过（提醒 + 用户没取消）。
    """
    if sys.platform != "win32":
        return False, "只支持 Windows"
    command = ["shutdown", "/s", "/t", str(max(0, int(seconds)))]
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception as exc:  # noqa: BLE001 - 关机失败要说出来，不能静默
        logger.warning("关机命令执行失败", exc_info=True)
        return False, f"{type(exc).__name__}: {exc}"
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "").strip()
        return False, message or f"退出码 {result.returncode}"
    logger.info("已发出关机命令（%s 秒后）", seconds)
    return True, "已安排关机"
