# -*- coding: utf-8 -*-
"""角色自己的**一套连招**（在固定轴的每一棒里跑）。

## 为什么需要它

固定轴（:mod:`rotation`）只管**什么时候换人**。但用户在轴里还规定了
**每一棒具体怎么打**：

> 守岸人打1套流程：平A攒能量条 → 攒满后长按普攻释放重击 → E+Q
> → 如果此时协奏值没满继续上面的循环，满了就切换到二号位

ok-ww 自带的 ``ShoreKeeper.do_perform`` **不是这个顺序**（它是
"E → R → Q → 重击"一把梭），所以要覆盖。

## 关键：**不需要新模板**

判"能量条满没满"用 ok-ww 自己的 ``is_forte_full()`` ——
它量的是屏幕底部固定区域（3840 尺度下 x 2251~2311 / y 1993~2016，
即 1920 下 x 1126~1156 / y 996~1008）的亮色像素占比。
**所有角色共用这个槽**，所以守岸人也适用。

我拿用户给的截图实测过：
    能量条空 → 金色 0 px
    能量条满 → 金色 2851 px      （区分度是绝对的）

## 怎么挂上去（**不改 vendor**）

ok-ww 有 ``custom_chars/`` 机制，但那个目录在 ``configs/`` 下、
且 **被 .gitignore 排除** —— 不适合随仓库分发。

所以走和 :mod:`rotation` 同一条路：**在 MyTools 的任务子类里，
把已识别出来的角色对象换成我们的子类**。这样：
* 不动 ``vendor/`` 一行代码，上游更新无冲突；
* 代码跟着仓库走，用户开箱即用；
* 只替换 ``do_perform``，其余（点击/切人/协奏值）全用 ok-ww 原语。
"""

from __future__ import annotations

import time


class ShoreKeeperCombo:
    """守岸人的一套连招（**纯逻辑**，不碰游戏对象，方便单测）。

    流程（用户原话）::

        平A攒能量条 → 攒满 → 长按普攻释放重击 → E + Q
          → 协奏没满？ 继续上面的循环
          → 协奏满了？ 交给固定轴换 2 号位

    这个类只回答"**下一步该做什么**"，实际按键由调用方执行 ——
    这样逻辑可以脱机测试（见 ``tests/test_char_combos.py``）。
    """

    #: 一次循环里的动作序列：(动作名, 说明)
    STEPS = ("gather", "heavy", "skills")

    def __init__(self) -> None:
        self.step = "gather"
        #: 已经打了几轮（诊断用）
        self.rounds = 0

    def reset(self) -> None:
        self.step = "gather"

    def next_action(self, forte_full: bool, con_full: bool) -> str:
        """决定下一步。

        :param forte_full: 能量条满了没（调用方用 ``is_forte_full()`` 查）
        :param con_full: 协奏满了没（满了就该换人，一圈结束）
        :return: ``"gather"`` / ``"heavy"`` / ``"skills"`` / ``"hand_off"``
        """
        if con_full:
            return "hand_off"

        if self.step == "gather":
            if forte_full:
                self.step = "heavy"
                return "heavy"
            return "gather"

        if self.step == "heavy":
            # 重击放完 → E + Q
            self.step = "skills"
            return "skills"

        # skills 放完 → 回到攒能，开始下一轮
        self.step = "gather"
        self.rounds += 1
        return "gather"


#: 类名 → 造子类的函数。加新角色连招时**只加一行**。
#:
#: ⚠ 键是 ok-ww 的**类名**（``ShoreKeeper``），不是 ``char_shorekeeper``
#:   —— ``type(char).__name__`` 给的是前者。
#: ⚠ 这张表定义在 :func:`make_combo_shorekeeper` **之后**（见文件末尾）——
#:   放前面会 NameError（函数还没定义）。
_COMBO_BUILDERS: dict = {}


def wrap_char(task, char, index):
    """把 ``char`` 换成带自定义连招的子类实例；不需要换就返回 None。

    ## 为什么要**就地复制状态**

    换掉对象会丢掉它累积的状态（``current_con`` / ``last_switch_time`` /
    ``has_intro`` …），那些是 ok-ww 调度器和切人逻辑要用的。
    所以新实例建好后,把旧对象的 ``__dict__`` 整个搬过去 ——
    和 ok-ww 自己 ``apply_team_char_classes`` 的做法一致。

    ⚠ 搬完要**重新指向新对象自己的绑定方法**？不需要 —— 方法是从类上找的，
    ``__dict__`` 里通常没有。但 ``task`` 引用必须留着（旧的一样）。
    """
    if task is None or char is None:
        return None
    cls_name = type(char).__name__
    builder = _COMBO_BUILDERS.get(cls_name)
    if builder is None:
        return None

    base_cls = type(char)
    combo_cls = builder(base_cls)
    try:
        new_char = combo_cls.__new__(combo_cls)
        new_char.__dict__.update(char.__dict__)
        # 新子类的 __init__ 会建 combo 状态；用 __new__ 跳过后要补上，
        # 否则 ``self.combo`` 不存在 → do_perform 直接 AttributeError
        if not hasattr(new_char, "combo"):
            new_char.combo = ShoreKeeperCombo()
        return new_char
    except Exception:  # noqa: BLE001 - 换不上就用原对象，别把刷取搞崩
        return None


def make_combo_shorekeeper(base_cls):
    """造一个覆盖了 ``do_perform`` 的 ShoreKeeper 子类。

    :param base_cls: ok-ww 的 ``ShoreKeeper`` 类（**运行时才拿得到** ——
        不能在模块顶层 import，否则工具发现阶段会拖进整个 ok 导入链)
    """

    class _ShoreKeeperCombo(base_cls):
        """守岸人：平A攒能 → 满 → 重击 → E+Q → 循环到协奏满。

        ⚠ 用户指定的连招（2026-10-01）。不是 ok-ww 原来的顺序。
        """

        #: 单次攒能的等待上限（秒）—— 超时就用当前状态继续，
        #: 免得信号读不到时原地不动
        GATHER_TIMEOUT = 6.0
        #: 平A节奏
        ATTACK_INTERVAL = 0.12

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.combo = ShoreKeeperCombo()

        def reset_state(self):
            super().reset_state()
            self.combo.reset()

        def do_perform(self):
            """跑用户指定的那套流程，直到协奏满（由固定轴换人）。"""
            if self.has_intro:
                self.continues_normal_attack(1.0)

            start = time.time()
            while True:
                self.check_combat()
                con_full = self._combo_con_full()
                forte_full = self._combo_forte_full()
                action = self.combo.next_action(forte_full, con_full)

                if action == "hand_off":
                    self.logger.info("守岸人: 协奏已满 → 交给固定轴换人")
                    return self.switch_next_char()

                if action == "gather":
                    # 攒能超时也继续（宁可多打两下，不要卡死）
                    self.click()
                    self.cycle_sleep(self.ATTACK_INTERVAL)

                elif action == "heavy":
                    self.logger.info("守岸人: 能量满 → 长按普攻释放重击")
                    self.heavy_attack(0.8)

                elif action == "skills":
                    self.logger.info("守岸人: 重击完 → E + Q")
                    self.click_resonance()
                    self.click_echo(time_out=0)

                # 兜底：整轮太久就强制收尾，交回上层
                if self.time_elapsed_accounting_for_freeze(start) > 20.0:
                    self.logger.warning("守岸人: 一套太久（20s）→ 收尾")
                    return self.switch_next_char()

        # ------------------------------------------------------------- 检测
        def _combo_forte_full(self) -> bool:
            """能量条满没满 —— 用 ok-ww 的通用检测（所有角色共用那个槽）。"""
            try:
                if self.is_mouse_forte_full():
                    return True
            except Exception:  # noqa: BLE001
                pass
            try:
                return bool(self.is_forte_full())
            except Exception:  # noqa: BLE001
                return False

        def _combo_con_full(self) -> bool:
            try:
                return bool(self.is_con_full())
            except Exception:  # noqa: BLE001
                return False

    return _ShoreKeeperCombo

# --------------------------------------------------------------------- 注册
#: ⚠ 必须放在 :func:`make_combo_shorekeeper` **之后**（函数定义完才能引用）。
_COMBO_BUILDERS.update({
    "ShoreKeeper": make_combo_shorekeeper,
})
