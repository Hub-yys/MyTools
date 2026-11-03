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

#: 战斗方式存在 ``tool_settings`` 里的键
COMBAT_STYLE_KEY = "auto_combat_style"

#: ★★★ 拾取提示框上的「已锁定」角标 —— 我们自己做的特征（2026-10-28）。
#:
#: ## 为什么不能用 ok-ww 自带的 echo_locked
#:
#: ``echo_locked`` / ``echo_not_locked`` / ``echo_dropped`` / ``echo_not_dropped``
#: 是 **声骸强化界面**的图标（ok-ww 只在 ``EnhanceEchoTask`` 里用它们，
#: bbox 在屏幕上方的 UI 面板内，横向长条样式 25x28）。
#:
#: 而拾取声骸时左下/左侧弹出的提示框里的锁图标是
#: **绿色圆环 + 白色锁形图案**，28x30，实测用 echo_locked 匹配分数 = 0。
#:
#: 所以从用户录屏里裁出这个图标，做成独立特征 ``pickup_locked``
#: （已注册进 coco，见 assets/images/pickup_locked_full.png）。
#:
#: 实测：提示框出现的 2.8 秒内 score 0.906~1.000 稳定命中，
#: 提示框消失后 score 0.000，**零误报**。
PICKUP_LOCKED_FEATURE = "pickup_locked"


def read_combat_style() -> str:
    """读用户选的战斗方式；读不到 / 坏值 → ``smart``。

    ⚠ **绝不抛异常** —— 在任务 ``__init__`` 里调，抛了 4C 就起不来。
    """
    try:
        from ....core import tool_settings  # noqa: PLC0415

        raw = (tool_settings.load(COMBAT_STYLE_KEY) or {}).get("style")
    except Exception:  # noqa: BLE001 - 设置读不出来按默认
        return rotation.DEFAULT_STYLE
    return rotation.normalize_style(raw)


class MyToolsFarmEchoTask(FarmEchoTask):
    """ok-ww 的 4C 刷声骸 + 拾取角标计数 + **可选**的战斗方式。

    ## 战斗方式（用户 2026-10-25 要求加回来）

    ==========  ==========================================================
    smart        **智能切换** —— ok-ww 原生调度。**默认**，也是唯一推荐。
    rotation     **轮切** —— 固定轴 3→2→1（:mod:`~.rotation` 实现）。
    combo        **合轴** —— 待定，当前等同 smart。
    ==========  ==========================================================

    ⚠ **默认必须是 smart**：用户实测固定轴不如 ok-ww。
    ⚠ smart / combo 下 ``_choose_switch_target`` **直接走 super()** ——
      等价于这个方法不存在，完全等价于 ok-ww 原版。
    """

    #: ★★★ 拾取提示框上「锁定角标」的搜索区域（相对屏幕坐标）。
    #:
    #: ## 2026-10-28 用用户录屏实测定位
    #:
    #: 锁图标（绿圆环 + 白锁形）在整帧的 **(119, 578)**，尺寸 28x30。
    #: 换算式::
    #:
    #:     x: 119/1920 = 0.062    y: 578/1080 = 0.535
    #:
    #: 提示框出现时有滑入动画（x 从 94 → 119，漂移 25px），
    #: 所以左右各留余量。实测搜索区域::
    #:
    #:     像素: x 57~181   y 545~642
    #:     相对: (0.030, 0.505, 0.095, 0.595)
    #:
    #: 这正好是用户说的「左边靠中间的位置」。
    PICKUP_BOX = (0.030, 0.505, 0.095, 0.595)
    #: 匹配阈值 —— pickup_locked 实测 0.906~1.000，0.7 足够稳且零误报
    PICKUP_THRESHOLD = 0.7
    #: ★★ 拾取后最多找多久（秒）。
    #:
    #: ## 实测数据（2026-10-28 录屏）
    #:
    #: 提示框持续 **2.8 秒**（399.6s → 402.4s）。
    #: 所以 0.2 秒窗口**太短，会漏掉** —— 拾取瞬间提示框还没画出来。
    #: 现在给 1.5 秒：足够覆盖提示框出现，又不会拖太久。
    #:
    #: ## ⚠ 战斗期间不会调这个
    #:
    #: :meth:`incr_drop` 只在「真的捡到声骸」时读（见那个方法的注释），
    #: 战斗中每轮的战斗检查路径会被 ``_pickup_in_combat_check`` 挡掉，
    #: 所以这里等 1.5 秒**不影响战斗**。
    PICKUP_WAIT = 1.5
    #: 每次重试之间的间隔
    PICKUP_POLL = 0.15

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        #: 战斗方式 —— 任务实例创建时读一次（运行中改下拉框不生效，UI 会锁住）
        self.combat_style = read_combat_style()
        #: 只有轮切用得到
        self.rotation_state = rotation.RotationState()

    # ------------------------------------------------------------------ 战斗方式
    def _choose_switch_target(self, current_char, has_intro,
                              target_low_con=False):
        """按用户选的战斗方式决定要不要接管切人。

        ## 只有 ``rotation``（轮切）会接管

        ``smart`` / ``combo`` **直接调 ``super()``** —— 完全是 ok-ww
        原版行为。默认状态下这个方法等价于"不存在"，不会改变任何战斗逻辑。
        """
        if self.combat_style != rotation.STYLE_ROTATION:
            #: 智能切换 / 合轴 → 不干预，交回 ok-ww
            return super()._choose_switch_target(current_char, has_intro,
                                                 target_low_con)

        chars = [c for c in getattr(self, "chars", []) or [] if c is not None]
        if len(chars) != len(rotation.ROTATION):
            #: 队伍不完整 → 轴没意义，交回 ok-ww
            return super()._choose_switch_target(current_char, has_intro,
                                                 target_low_con)

        state = self.rotation_state
        here = rotation.slot_of(current_char)
        if here is not None:
            #: 轴跟着**实际**在场的人走（漂移容错）
            state.resync(here)

        should_go, why = state.should_hand_off(
            con_full=self._con_is_full(current_char), slot=here)
        if not should_go:
            #: 还没到换人时机 → 不换（返回同一个，ok-ww 会打条 debug）
            return current_char

        want = state.advance()
        target = self._char_at_slot(want)
        if target is None or target is current_char:
            #: 找不到目标 —— 别硬切，交回 ok-ww
            self.log_debug(f"轮切：{want} 号位没有可用角色，交回 ok-ww 调度")
            return super()._choose_switch_target(current_char, has_intro,
                                                 target_low_con)
        self.log_info(f"轮切：{why} → 换到 {want} 号位")
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
        """★★★ 拾取计数钩子 —— 只统计「锁定 / 弃置」，且**不能在战斗中阻塞**。

        ## 两个互相冲突的需求

        1. **战斗期间不能阻塞**（2026-10-26 教训：角色被打死）
           ``FarmEchoTask.on_combat_check`` 里每轮战斗都会调 ``incr_drop``。
           在那里读角标 = 每轮多花 0.2 秒模板匹配 → 角色站桩 → 死。

        2. **锁定声骸必须能计数**（用户 2026-10-27）
           4C 刷本全程在副本里（日志确认 ``in_realm: True``），
           之前用 ``_in_realm`` 一刀切跳过 → 统计永远是 0。

        ## 怎么区分（关键）

        ``incr_drop`` 有三个调用点，性质完全不同：

        ==========================  =============================  ==========
        调用点                       场景                           要不要读
        ==========================  =============================  ==========
        FarmEchoTask L88            ``on_combat_check`` 战斗中每轮     **不读**
        FarmEchoTask L209           打完怪 ``walk_find_echo`` 后捡    **要读**
        FarmEchoTask L440           Fenrico Boss 循环间隙             **要读**
        ==========================  =============================  ==========

        第 1 条由 ``FarmEchoTask`` 设置 ``_pickup_in_combat_check`` 标志来标记
        （见那边的注释）。第 2、3 条不设标志 —— 那时角色正在低头捡东西，
        本来就不输出，读 0.2 秒完全没影响。

        ## 顺带

        ``pick_f(handle_claim=True)`` 返回的 ``dropped`` 在战斗中几乎总是 False，
        所以就算不跳过，实际也很少进到读角标那一步 —— 但保险起见还是要挡。
        """
        super().incr_drop(dropped)
        if not dropped:
            return
        #: ⚠ 只有「战斗中每轮的拾取检查」这条路径要跳过（读角标会阻塞）
        if getattr(self, "_pickup_in_combat_check", False):
            return
        #: 真正捡到声骸的时刻 —— 安全，正常读角标做统计
        report.tally_pickup(self.read_pickup_state())

    # ------------------------------------------------------------------ 读角标
    def read_pickup_state(self) -> str:
        """读拾取提示框上的锁定角标，返回 :data:`report.LOCKED` / ``NONE``。

        ## 2026-10-28 实测修正

        之前用 ok-ww 的 ``echo_locked`` 等 4 个特征，**永远匹配不到** ——
        那些是声骸强化界面的图标，不是拾取提示上的。

        现在改用自制的 ``pickup_locked`` 特征（从用户录屏裁的模板）::

            特征: pickup_locked   绿圆环 + 白锁形图案   28x30
            位置: 整帧 (119, 578)  ← 用户说的「左边靠中间」
            实测: 提示框在的 2.8 秒 score 0.906~1.000
                  提示框不在时 score 0.000（零误报）

        ## 关于「弃置」

        拾取提示框上**只有锁定角标**，没有弃置角标 —— 游戏的自动弃置是在
        背包里判定的，拾取瞬间不显示。所以这里只能统计「锁定」，
        ``DROPPED`` 暂不产出（报告里会一直显示 0，这是如实的）。

        ## 在 :data:`PICKUP_WAIT` 秒内反复找

        提示框有滑入动画 + 可能比拾取动作晚一点画出来，
        所以给 1.5 秒窗口轮询（实测提示框持续 2.8 秒，足够覆盖）。
        """
        deadline = time.time() + self.PICKUP_WAIT
        try:
            while time.time() < deadline:
                box = self.box_of_screen(*self.PICKUP_BOX)
                hit = self.find_best_match_in_box(
                    box, [PICKUP_LOCKED_FEATURE],
                    threshold=self.PICKUP_THRESHOLD)
                if hit is not None:
                    self.log_debug(
                        f"拾取角标命中：{getattr(hit, 'name', '?')} "
                        f"score={getattr(hit, 'confidence', 0):.3f}")
                    return report.LOCKED
                self.sleep(self.PICKUP_POLL)
        except Exception as e:  # noqa: BLE001 - 读不到角标绝不能把刷声骸打断
            self.log_debug("读取拾取角标失败：%s: %s" % (type(e).__name__, e))
            return report.NONE
        return report.NONE
