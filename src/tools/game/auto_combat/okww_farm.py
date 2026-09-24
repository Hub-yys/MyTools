# -*- coding: utf-8 -*-
"""4C 刷声骸 —— ok-ww ``FarmEchoTask`` 的子类，只为**读拾取时的角标**。

**为什么要子类**：ok-ww 自己**不区分**拾取到的声骸是锁定了还是弃置了
（``BaseWWTask.incr_drop()`` 只记 ``info['Echo Count']`` 加一）。
但用户实测：**按 F 吸收那一刻，游戏会在屏幕左下角显示自动锁定/自动弃置的角标**
（锁定 / 弃置 / 两者都不）。所以我们在拾取动作上挂一个钩子，顺手把那个角标读出来。

**挂点选 ``incr_drop()``**：ok-ww 每次成功拾到一个声骸都会走它
（``FarmEchoTask.do_run()`` 的三条拾取分支 + ``on_combat_check()`` 的边走边捡），
是"刚刚捡到东西"的唯一收敛点，比在 UI 线程轮询 ``Echo Count`` 增量准得多
（轮询要么重复计数、要么错过只闪一下的通知）。

⚠ 判定区域是**屏幕左下象限**（用户实测结论）。角标长什么样来自 ok-ww 自己的特征
（``echo_locked`` / ``echo_not_locked`` / ``echo_dropped`` / ``echo_not_dropped``，
它与强化界面用的是同一套图标）。如果游戏换了 UI，改 :data:`PICKUP_BOX` 即可。
"""

from __future__ import annotations

import sys
import time


def _ensure_vendor_on_path() -> None:
    """把 vendored ok-ww 挂到 ``sys.path``（照抄 okww_task.py 的做法）。

    本模块要在**任何**上下文里都能被 import：工具发现（registry.discover，
    此时 boot 还没跑、vendor 不在 path 上）、ok 的 ``init_class_by_name``
    （boot 时，vendor 已在）、PyInstaller 静态分析、单测。2026-09-24：没有
    这步时 discover 会打一条「工具模块导入失败」的 traceback —— 虽然 boot
    时能自愈，但每次启动都吓人一次。
    """
    from ....core import paths  # noqa: PLC0415 - 避免模块级循环导入

    vendor = str(paths.resource_dir("vendor", "okww"))
    if vendor not in sys.path:
        sys.path.insert(0, vendor)


_ensure_vendor_on_path()

from okww.task.FarmEchoTask import FarmEchoTask  # noqa: E402

from . import report

#: 与 ok-ww ``EnhanceEchoTask`` 判锁/弃置状态用的是同一批特征名
PICKUP_FEATURES = ("echo_locked", "echo_not_locked", "echo_dropped", "echo_not_dropped")


class MyToolsFarmEchoTask(FarmEchoTask):
    """ok-ww 的 4C 刷声骸 + 「拾取到的声骸里有多少锁定/弃置」的计数。"""

    #: 判定区域（相对屏幕坐标）：**左下象限**。用户实测：角标绝对出现在左下区域。
    PICKUP_BOX = (0.0, 0.5, 0.5, 1.0)
    #: 匹配阈值 —— 跟 EnhanceEchoTask 保持一致
    PICKUP_THRESHOLD = 0.7
    #: 拾取后最多找多久（秒）。通知可能晚一瞬才画出来，所以不是读一帧就完事；
    #: 但也不能等太久 —— 刷声骸是循环任务，每轮多等 1 秒就是白掉的效率。
    #: 找到"明确"角标（锁定/弃置）会立刻返回，只有"都没"这种才走满这个窗口。
    PICKUP_WAIT = 0.8
    #: 每次重试之间的间隔
    PICKUP_POLL = 0.15

    # ------------------------------------------------------------------ 钩子
    def incr_drop(self, dropped):
        super().incr_drop(dropped)
        if dropped:
            report.tally_pickup(self.read_pickup_state())

    # ------------------------------------------------------------------ 读角标
    def read_pickup_state(self) -> str:
        """读左下角，返回 :data:`report.LOCKED` / ``DROPPED`` / ``NONE``。

        在 :data:`PICKUP_WAIT` 秒内反复找：**先出现的角标说了算**。
        一直没找到按"都没"算（用户描述的第三种状态）—— 若区域不对，表现就是
        「锁定 0 / 弃置 0 / 都没 = 全部」，这在报告里能一眼看出来，不会被静默吞掉。
        """
        found: list[str] = []
        deadline = time.time() + self.PICKUP_WAIT
        try:
            while time.time() < deadline:
                box = self.box_of_screen(*self.PICKUP_BOX)
                hit = self.find_best_match_in_box(
                    box, list(PICKUP_FEATURES), threshold=self.PICKUP_THRESHOLD)
                if hit is not None:
                    found.append(str(getattr(hit, "name", "")))
                    state = report.classify_badges(found)
                    if state != report.NONE:
                        return state
                    # 只找到 not_* 之类还不算定论，继续等更明确的角标出现
                self.sleep(self.PICKUP_POLL)
        except Exception as e:  # noqa: BLE001 - 读不到角标绝不能把刷声骸打断
            self.log_debug("读取拾取角标失败：%s: %s" % (type(e).__name__, e))
            return report.NONE
        return report.classify_badges(found)
