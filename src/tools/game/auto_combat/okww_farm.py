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

from . import report, rotation

#: 与 ok-ww ``EnhanceEchoTask`` 判锁/弃置状态用的是同一批特征名
PICKUP_FEATURES = ("echo_locked", "echo_not_locked", "echo_dropped", "echo_not_dropped")


class MyToolsFarmEchoTask(FarmEchoTask):
    """ok-ww 的 4C 刷声骸 + 「拾取到的声骸里有多少锁定/弃置」的计数。

    另外还**接管了切人**：用户要的是固定循环轴（见
    :mod:`src.tools.game.auto_combat.rotation`），而 ok-ww 默认是
    通用增益调度器（按 buff 剩余 / 角色定位临时挑人）—— 表现就是"乱切人"。
    """

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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        #: 固定轴状态机（每个任务实例一份）
        self.rotation_state = rotation.RotationState()

    # ------------------------------------------------------------------ 固定轴
    def _choose_switch_target(self, current_char, has_intro,
                              target_low_con=False):
        """★ 按固定轴挑下一个上场的人 —— 覆盖 ok-ww 的通用增益调度。

        ## 为什么只覆盖这一个方法

        ok-ww 挑人在 ``_choose_switch_target`` 里。我们**只换这一个决策点**，
        其余（协奏值读取、入场判定、切人动作、漂移容错）全部沿用原实现 ——
        那些是踩过坑的，重写风险大。

        ## 什么时候**不**接管（交回 ok-ww）

        * 队伍不完整（不足 3 人）：轴没有意义；
        * 轴里找不到在场的人：说明位置对不上号，硬切更危险。

        这两种情况返回 ``super()`` 的结果，行为和原来一致。

        ## 关于返回 ``current_char``

        ``switch_next_char`` 里 ``switch_to == current_char`` 会被判成
        "can't find next char"，然后**提前返回 = 不换人** ——
        行为是对的，只是会打条 warning 日志。
        所以这里返回 ``current_char`` 表示"这一棒还没到换人时机"，
        是**刻意为之**（用户要求：协奏没满就别换）。
        """
        chars = [c for c in getattr(self, "chars", []) or [] if c is not None]
        if len(chars) != len(rotation.ROTATION):
            return super()._choose_switch_target(current_char, has_intro,
                                                 target_low_con)

        state = self.rotation_state
        here = rotation.slot_of(current_char)
        if here is not None:
            # 轴跟着**实际**在场的人走（漂移容错：ok-ww 或玩家可能已经换过人了）
            state.resync(here)

        should_go, why = state.should_hand_off(
            con_full=self._con_is_full(current_char), slot=here)
        if not should_go:
            # 还没到换人时机 → 不换（ok-ww 会打条 warning，属正常）
            return current_char
        self.log_info(f"固定轴：{why} → 换下一棒")

        # 推进到下一棒，并找出对应的角色
        want = state.advance()
        target = self._char_at_slot(want)
        if target is None or target is current_char:
            # 找不到目标（位置对不上）—— 退回 ok-ww 的原逻辑，别硬切
            self.log_debug(f"固定轴：{want} 号位没有可用角色，交回 ok-ww 调度")
            return super()._choose_switch_target(current_char, has_intro,
                                                 target_low_con)
        return target

    def _char_at_slot(self, slot: int):
        """取队伍里 ``slot`` 号位（1 起）的角色对象。"""
        for char in getattr(self, "chars", []) or []:
            if rotation.slot_of(char) == slot:
                return char
        return None

    def _con_is_full(self, char) -> bool:
        """协奏能量满了没 —— 用 ok-ww 自己的判定，不自己造信号。"""
        try:
            if char is not None and hasattr(char, "is_con_full"):
                return bool(char.is_con_full())
            index = rotation.slot_of(char)
            return bool(self.is_con_full(index - 1)) if index else False
        except Exception as exc:  # noqa: BLE001 - 读不到就当没满，交给超时兜底
            self.log_debug(f"读协奏值失败：{type(exc).__name__}: {exc}")
            return False

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
