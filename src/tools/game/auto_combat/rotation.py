# -*- coding: utf-8 -*-
"""固定循环轴（"轮椅轴"）—— 覆盖掉 ok-ww 的通用切人调度。

## 为什么需要它

用户报："还是在乱切人"。

根因在日志里一目了然 —— ok-ww 的切人是**通用增益调度器**在临时决策，
每次原因都不一样：

    reason=lowest_support_buff_remaining
    reason=unbuffed_healer
    reason=fallback_role_order
    reason=intro_role_order_main_sub_healer
    reason=support_buffs_active_return_to_main_dps

它按「谁的增益快过期了 / 谁还没上增益 / 角色定位顺序」挑人
（见 ``BaseCombatTask._choose_switch_target_by_buff_time``），
**没有"固定轴的顺序"这个概念**。所以看起来就是乱切。

## 用户要的轴

    3号位（守岸人）打完一套满协奏
      → 2号位（坎特蕾拉）打完一套慢卸载
      → 1号位（心）打完一套满协奏
      → 回到 3号位，循环

队伍固定：**1=心、2=坎特蕾拉、3=守岸人**。

## 实现方式：**只覆盖"下一个是谁"，不碰别的**

ok-ww 的调度器在 ``BaseCombatTask._choose_switch_target`` 里挑目标。
我们只替换那**一个决策点**，其余（入场判定、协奏值读取、切人动作、
漂移容错）全部沿用 ok-ww 的原实现 —— 那些都是踩过坑的，重写风险大。

⚠ **为什么不改 vendor/ 里的 ok-ww 代码**：那是上游的，
改了以后每次更新都要手动合并（这个坑在「心」的模板上已经踩过一次）。
MyTools 本来就有 ok-ww 任务的子类（``MyToolsFarmEchoTask``），
在那里挂一层最干净。

## 怎么判"一套打完了"

不自己造信号，用 ok-ww 自己的：**协奏能量满 = ``is_con_full()``**。

* 用户在轴里说的"满协奏"就是它；
* "慢卸载"（坎特蕾拉）额外等一个 :data:`SLOW_UNLOAD_SECONDS` 的窗口
  —— 她那一套是长流程，协奏满了还要把延奏打完才划算。

⚠ 每棒都有**超时兜底**（:data:`MAX_FIELD_SECONDS`）：万一某个信号
一直不满（比如低配卡帧、或角色没按预期出招），也会按时换人 ——
宁可少打点伤害，也不能原地卡死。
"""

from __future__ import annotations

import time

#: 固定轴：按**队伍位置**（1 起）排的循环顺序。
#: 用户要的是「3 → 2 → 1 → 3 …」，队伍的 1/2/3 号位分别是他自己定的。
ROTATION = (3, 2, 1)

#: 每一棒最多站场多久（秒）—— 超时无条件换人，避免卡死。
MAX_FIELD_SECONDS = 12.0

#: "慢卸载"角色（坎特蕾拉）在协奏满之后再多打一会儿。
#: 用户原话是"打完一套**慢卸载**" —— 她那一套流程长，协奏满了还该收个尾。
SLOW_UNLOAD_SECONDS = 3.0

#: 需要"慢卸载"的**队伍位置**（1 起）。2 号位 = 坎特蕾拉。
SLOW_UNLOAD_SLOTS = frozenset({2})


class RotationState:
    """固定轴的**纯状态机** —— 不碰任何游戏/UI，方便单测。

    只回答一个问题：**这一棒该轮到几号位了？**
    """

    def __init__(self, rotation: tuple[int, ...] = ROTATION) -> None:
        if not rotation:
            raise ValueError("rotation 不能是空的")
        self.rotation = tuple(rotation)
        self._pos = 0
        #: 本次站场开始的时刻（单调钟，不受系统时间调整影响）
        self._since = time.monotonic()

    @property
    def current(self) -> int:
        """当前该站场的队伍位置（1 起）。"""
        return self.rotation[self._pos]

    def advance(self) -> int:
        """换下一棒，返回新的位置。"""
        self._pos = (self._pos + 1) % len(self.rotation)
        self._since = time.monotonic()
        return self.current

    def resync(self, slot: int) -> None:
        """把轴对齐到**实际**在场的位置（漂移容错）。

        ok-ww 自己也可能因为协奏满/入场而换人，或者玩家手动切了。
        这时轴要跟着走，不能继续按自己的节奏 —— 否则会一直想切到
        一个"它以为不在场"的人。
        """
        if slot in self.rotation:
            self._pos = self.rotation.index(slot)
            self._since = time.monotonic()

    def elapsed(self) -> float:
        """当前这一棒站了多久（秒）。"""
        return time.monotonic() - self._since

    def should_hand_off(self, con_full: bool, timeout: float = MAX_FIELD_SECONDS,
                        slot: int | None = None) -> tuple[bool, str]:
        """该不该换人。返回 ``(要不要换, 原因)``。

        判据（按优先级）：
        1. **协奏满** → 换（用户轴的核心信号）；
           但"慢卸载"位要多等 :data:`SLOW_UNLOAD_SECONDS`；
        2. **超时** → 换（兜底，避免任何信号失灵时卡死）。
        """
        here = self.current if slot is None else slot
        if con_full:
            if here in SLOW_UNLOAD_SLOTS and self.elapsed() < SLOW_UNLOAD_SECONDS:
                return False, f"slot{here} 慢卸载中（还差 {SLOW_UNLOAD_SECONDS - self.elapsed():.1f}s）"
            return True, f"slot{here} 协奏已满"
        if self.elapsed() >= timeout:
            return True, f"slot{here} 站场超时（{timeout:.0f}s）"
        return False, ""


def slot_of(char) -> int | None:
    """从 ok-ww 的角色对象上取**队伍位置**（1 起）。取不到返回 None。

    ok-ww 的 ``char.index`` 是 0 起的。
    """
    if char is None:
        return None
    index = getattr(char, "index", None)
    if isinstance(index, int) and index >= 0:
        return index + 1
    return None


def next_slot_target(chars, rotation: tuple[int, ...] = ROTATION):
    """按固定轴挑**下一个**该上场的人。

    :param chars: ok-ww 的 ``task.chars``（按队伍位置排，可能含 None）
    :param rotation: 循环顺序（队伍位置，1 起）
    :return: 目标角色对象，或 None（= 让人调用方沿用 ok-ww 的原逻辑）

    ⚠ 只在**能确定**的时候返回人：队伍不完整、位置对不上号时返回 None，
    让 ok-ww 的原调度兜底 —— 比硬切到一个猜的人安全。
    """
    if not chars:
        return None
    by_slot = {}
    for char in chars:
        slot = slot_of(char)
        if slot is not None:
            by_slot[slot] = char
    if not by_slot:
        return None
    # 按轴顺序找第一个**在场**的位置
    for slot in rotation:
        char = by_slot.get(slot)
        if char is not None:
            return char
    return None
