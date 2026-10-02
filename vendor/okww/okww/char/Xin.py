"""「心」（心月狐）的 4C 刷声骸战斗逻辑（**单人流**）。

## ⚠ 这个文件的来历

**不是 ok-ww 官方写的** —— 上游还没有这个角色。MyTools 按用户提供的
游戏内机制截图 + 攻略实现。

* 机制：[心月狐攻略（TapTap）](https://www.taptap.cn/moment/854657182002580468)、
  [心 全方位培养攻略](https://niubi.wiki/2026/09/17/141732/)
* 识别模板（认人）见 ``tools/make_xin_templates.py``

## 机制（攻略原文提炼）

    应世相（红狐）  能量「应世心」上限 100
        普攻 / E / 变奏入场 攒应世心 → 攒满解锁**强化重击【镇红尘】**
        放【镇红尘】 → 解锁**一段大招** → 开大进照世相

    照世相（白狐）  能量「照世心」上限 300（只能白狐形态攒）
        攒满 → **强化共鸣技能** → 进【统御众机】，**持续固定 13 秒**
        统御期间普攻升级，持续消耗照世心
        照世心耗尽 → **终结重击【镇寰宇】** → 解锁**二段大招**
        ⚠ **必须打完终结重击**才能开二段大，提前开伤害大幅缩水
        二段大收尾 → 回红狐

## ★ 为什么用 ok-ww 的**通用检测**，而不是自造角色专属模板

第一版我用自己裁的"能量条模板"（紫条/金条）判断形态 —— **实机一直失败**
（日志："应世心攒满超时"，表现就是**一直平A**）。查下来两个原因：

1. **方向错了**：ok-ww 判"能不能强化重击"用的是**所有角色共用**的通用检测
   （``is_forte_full`` 量屏幕底部固定区域的白色像素占比；
   ``is_mouse_forte_full`` 找 ``mouse_forte`` 模板），
   **根本不看角色的专属资源条**。ok-ww 自己的角色（Encore / Changli /
   Danjin）用的都是这两个。
2. 我裁模板时**把游戏背景一起裁进去了** —— 背景一变就不匹配。

所以现在**不依赖任何自造模板**，只用 ok-ww 验证过的原语：

============================  ================================
方法                           含义
============================  ================================
``is_mouse_forte_full()``      强化重击可用（找通用 mouse_forte）
``is_forte_full()``            同上，另一种实现（像素占比）
``heavy_click_forte(fun)``     能量满时按重击（ok-ww 标准写法）
``liberation_available()``     共鸣解放（大招）可用
``resonance_available()``      共鸣技能（E）可用
``is_con_full()``              协奏能量满
============================  ================================

**统御众机的 13 秒**按**计时**走（攻略明确写"持续固定13秒"）——
这是最可靠的信号，不需要识图。

⚠ **本文件从未在实机跑通** —— 第一次跑请把 ``data/okww/logs/`` 的日志发回来。
每次行动都会打日志（``Xin: ...``），照着能看出卡在哪一步。
"""

import time

from okww.char.BaseChar import BaseChar, SwitchPriority


class Xin(BaseChar):
    """「心」——单人流循环（不依赖队友，全程站场）。"""

    #: 红狐攒应世心的最长等待（超时就用当前状态硬推进，不卡死）
    RED_GAIN_TIMEOUT = 14.0
    #: 白狐攒照世心的最长等待
    WHITE_GAIN_TIMEOUT = 18.0
    #: 统御众机：攻略明确"持续固定13秒"
    DOMINION_DURATION = 13.0
    #: 终结重击之后、去按二段大之前的**收招等待**（秒）。
    #:
    #: ⚠ 2026-10-02 加的：二段大是在【镇寰宇】**打完那一刻**才解锁的
    #:   （攻略：「消耗完全部照心值后，重击替换为镇世，**随后**解锁
    #:   第二阶段共鸣解放」）。不留这点时间的话，去按大招会连续
    #:   `clicked liberation but no effect`（实机日志出现过 4 连）。
    HEAVY_SETTLE = 1.5
    #: 放完终结重击后等二段大招的窗口。
    #: ⚠ 放宽到 8 秒：动画 + 解锁判定需要时间，太短会白白错过。
    FINISH_TIMEOUT = 8.0
    #: 普攻节奏
    ATTACK_INTERVAL = 0.12

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        #: 走到哪一步（跨 do_perform 调用保持）
        self.phase = "red"          # red / white / dominion / finish
        #: 统御开始的时刻
        self.dominion_start = -1.0
        #: ★ 这是一次**战斗内**要跨越 reset_state 保留的形态状态。
        #:   见 :meth:`reset_state` 的说明。
        self._phase_kept = None

    def reset_state(self):
        """★ 重置入场状态 —— 但**形态 phase 不能丢**。

        ## ⚠ 2026-10-02 修的第三个 bug（一个根因解释了两个现象）

        ``BaseChar.reset_state`` 的文档写得很清楚：

            这是队伍**重新识别**时刷新的字段。
            "Do not store long-term combat decisions only in these fields;
             they are refreshed whenever the team is re-read from the screen."

        ok-ww 每次 ``combat_once()``（每场战斗）都会 ``load_chars()``
        → 对每个角色调 ``reset_state()``。我原来在里面把 ``self.phase``
        设回 ``"red"`` —— 于是：

        * **白狐/统御形态被清掉**，下一次 ``do_perform`` 又从
          ``perform_red`` 开始（日志里形态序列反复出现
          ``白狐 → 红狐 → 白狐``，72 次一段大、61 次白狐重新攒能）；
        * 攒照世心的进度**永远接不上** → 看起来就是"打满金色能量后
          一直普攻"（因为每次都从红狐重来）。

        **修法**：``phase`` 在 ``reset_state`` 时**保留**（存在
        ``_phase_kept`` 里），只有**新一轮循环从头**时才清。

        注意区分两件事：
        * ``has_intro`` / ``current_con`` 这些**入场**状态 —— 该清（父类在做）
        * ``phase``（我打到哪个形态了）—— **不该清**，那是战斗进程
        """
        # 先备份形态 —— super() 不碰它，但保险起见先存下来
        kept = getattr(self, "phase", "red")
        kept_start = getattr(self, "dominion_start", -1.0)
        super().reset_state()
        self._phase_kept = kept
        self.phase = kept
        self.dominion_start = kept_start

    # ------------------------------------------------------------------ 工具
    def forte_ready(self) -> bool:
        """强化重击能不能放 —— 用 ok-ww 的**通用**检测。

        ⚠ 这里**不用**自造的 xin_* 模板（第一版就是那么错的，见模块说明）。
        """
        try:
            if self.is_mouse_forte_full():
                return True
        except Exception:  # noqa: BLE001 - 某个检测不可用不该让整轮崩
            pass
        try:
            return bool(self.is_forte_full())
        except Exception:  # noqa: BLE001
            return False

    def ultimate_ready(self) -> bool:
        try:
            return bool(self.liberation_available())
        except Exception:  # noqa: BLE001
            return False

    def skill_ready(self) -> bool:
        try:
            return bool(self.resonance_available())
        except Exception:  # noqa: BLE001
            return False

    def press_heavy_forte(self) -> bool:
        """能量满时按强化重击。返回是否按了。

        ``heavy_click_forte`` 是 ok-ww 的标准写法：它只在 ``check_fun()``
        为真时按下鼠标，并等能量耗尽再松开。
        """
        try:
            return bool(self.heavy_click_forte(check_fun=self.is_mouse_forte_full))
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(f"Xin: heavy_click_forte 失败 {exc}")
            return False

    # ------------------------------------------------------------------ 主循环
    def do_perform(self):
        """一轮行动。ok-ww 每次轮到这个角色站场都会调它。

        ⚠ 三个形态是**严格顺序**推进的，由 ``self.phase`` 记住走到哪。
        「收尾」（二段大招）**不在这里分派** —— 它由
        :meth:`perform_dominion` 当场连着做完（见那个方法的说明）。
        """
        try:
            if self.phase == "white":
                self.perform_white()
            elif self.phase == "dominion":
                self.perform_dominion()
            else:
                self.perform_red()
        finally:
            self.switch_next_char()

    # ------------------------------------------------------------------ 红狐
    def perform_red(self):
        """应世相：攒应世心 → 强化重击【镇红尘】 → 一段大招。"""
        self.logger.info("Xin: [红狐] 开始攒应世心")
        self.wait_intro(1.2)
        self.click_echo(time_out=0)

        start = time.time()
        got_heavy = False
        while self.time_elapsed_accounting_for_freeze(start) < self.RED_GAIN_TIMEOUT:
            self.cycle_start()
            if self.forte_ready():
                self.logger.info("Xin: [红狐] 能量满 → 强化重击【镇红尘】")
                got_heavy = self.press_heavy_forte()
                break
            # E 好了就丢（攒能快）
            if self.skill_ready():
                self.click_resonance()
            self.click()
            self.cycle_sleep(self.ATTACK_INTERVAL)

        if not got_heavy:
            # 没检测到满：**不卡死**，用当前状态硬推进（宁可打得不完美，
            # 也不要原地站 14 秒什么都不干）
            self.logger.warning(
                "Xin: [红狐] 没检测到能量满 —— 按时间硬推进（重击+大招）")
            self.heavy_attack(1.0)

        # 一段大招（放完进白狐）
        start = time.time()
        while self.time_elapsed_accounting_for_freeze(start) < 4.0:
            if self.click_liberation():
                self.logger.info("Xin: [红狐] 一段大招已开 → 进白狐形态")
                self.phase = "white"
                return
            self.cycle_sleep(0.1)
        self.logger.warning("Xin: [红狐] 大招没放出去，下一轮重试")

    # ------------------------------------------------------------------ 白狐
    def perform_white(self):
        """照世相：攒照世心 → 强化共鸣技能 → 进统御众机。"""
        self.logger.info("Xin: [白狐] 开始攒照世心")
        start = time.time()
        while self.time_elapsed_accounting_for_freeze(start) < self.WHITE_GAIN_TIMEOUT:
            self.cycle_start()
            # 白狐形态下 E 就是"强化共鸣技能"的入口
            if self.skill_ready() and self.forte_ready():
                self.logger.info("Xin: [白狐] 照世心满 → 强化 E 进统御众机")
                self.click_resonance()
                self.phase = "dominion"
                self.dominion_start = time.time()
                return
            if self.skill_ready():
                self.click_resonance()
            self.click()
            self.cycle_sleep(self.ATTACK_INTERVAL)

        # 超时也进统御（按时间推进，别卡死）
        self.logger.warning("Xin: [白狐] 照世心攒满超时 —— 按时间进统御")
        self.click_resonance()
        self.phase = "dominion"
        self.dominion_start = time.time()

    # ------------------------------------------------------------------ 统御
    def perform_dominion(self):
        """统御众机：打空照世心 → 终结重击【镇寰宇】 → **二段大招**。

        ## ⚠ 2026-10-02 的第三处修（用户报"打满金色能量后一直普攻"）

        原来这里是**盲等 13 秒**：``while 时间 < 13: 平A``。
        但用户实测的机制是：

            进统御众机 → **攻击消耗照世心** → **耗尽后**重击才变成
            【镇寰宇】 → 打完才解锁二段大

        也就是说"能不能放终结重击"取决于**照世心有没有耗尽**，
        不是"过了几秒"。盲等有两个坏处：
        * 照世心早早耗尽时，还在白等剩下的秒数（浪费输出窗口）；
        * 13 秒还没耗尽时，强行放重击 —— 打出来的不是【镇寰宇】，
          自然也就解锁不了二段大（这正是"亮了但按不生效"的来源）。

        **改法**：像 :meth:`perform_red` 那样**检测信号** ——
        照世心耗尽 / 重击就绪就停手，13 秒只当**兜底上限**。

        ⚠ 二段大招必须在**切人之前**放完（``do_perform`` 的 ``finally``
        会立刻切人，协奏已满时下次又马上被切走）。
        """
        start = self.dominion_start if self.dominion_start > 0 else time.time()
        left = self.DOMINION_DURATION - self.time_elapsed_accounting_for_freeze(start)
        self.logger.info(f"Xin: [统御众机] 开始，剩 {left:.1f} 秒")

        while self.time_elapsed_accounting_for_freeze(start) < self.DOMINION_DURATION:
            self.cycle_start()
            # ★ 照世心耗尽（重击就绪）就停手 —— 别再白打
            if self.forte_ready():
                elapsed = self.time_elapsed_accounting_for_freeze(start)
                self.logger.info(
                    f"Xin: [统御众机] 照世心已耗尽（第 {elapsed:.1f} 秒）→ 停手")
                break
            self.click()
            self.cycle_sleep(self.ATTACK_INTERVAL)
        else:
            self.logger.info("Xin: [统御众机] 13 秒到（兜底上限）")

        self.logger.info("Xin: [统御众机] 放终结重击【镇寰宇】")
        self.heavy_attack(2.0)

        # ★ 等重击的**收招动画**走完 —— 二段大是在【镇寰宇】**打完那一刻**
        #   才解锁的（攻略：「消耗完全部照心值后，重击替换为镇世，
        #   **随后**解锁第二阶段共鸣解放」）。
        #   ⚠ 2026-10-02 修的第二个 bug：原来这里紧接着就去找大招，
        #   结果日志里连续 4 次 `clicked liberation but no effect` ——
        #   因为全落在动画期间，大招还没解锁。
        self.logger.info(f"Xin: [统御众机] 等重击收招（{self.HEAVY_SETTLE} 秒）")
        self.sleep(self.HEAVY_SETTLE)

        # ★ 紧接着放二段大招 —— **不能留到下一轮**（见方法说明）
        self.perform_finish()

    # ------------------------------------------------------------------ 收尾
    def perform_finish(self):
        """终结重击后放二段大招（终结爆发），然后回红狐。

        ⚠ 这个方法由 :meth:`perform_dominion` **当场调用**，
        不再靠 ``do_perform`` 的下一轮分派 —— 那样永远轮不到（见上）。
        保留成独立方法只是为了可读性和**可单测**。

        ## ⚠ 2026-10-02 修的第二个 bug

        原来这里是"闷头按 5 秒" ``click_liberation()``。实机日志显示
        连续 4 次 ``clicked liberation but no effect`` —— 因为那会儿
        重击的收招动画还没走完、二段大**还没解锁**，按了也白按。

        现在改成：**先等 ``liberation_available()`` 说"亮"了再按**，
        并且在窗口内**反复重试**（解锁可能有延迟）。
        """
        self.logger.info("Xin: [收尾] 等二段大招解锁")
        start = time.time()
        clicked = False
        attempts = 0
        saw_ready = False
        while self.time_elapsed_accounting_for_freeze(start) < self.FINISH_TIMEOUT:
            if self.ultimate_ready():
                saw_ready = True
                attempts += 1
                if self.click_liberation():
                    self.logger.info(
                        f"Xin: [收尾] 二段大招（终结爆发）已放"
                        f"（第 {attempts} 次尝试）")
                    clicked = True
                    break
                self.logger.info(
                    f"Xin: [收尾] 第 {attempts} 次按了大招但没生效，重试")
            self.cycle_sleep(0.2)
        if not clicked:
            # ⚠ 这两种情况的**原因完全不同**，日志里必须分得清：
            #   saw_ready=False → 大招**从来没亮过**（识别问题 / 没解锁）
            #   saw_ready=True  → 亮了但按下去不生效（按键问题 / 动画期）
            if saw_ready:
                self.logger.warning(
                    f"Xin: [收尾] 二段大招亮了但按不生效"
                    f"（{self.FINISH_TIMEOUT:.0f} 秒内试了 {attempts} 次）")
            else:
                self.logger.warning(
                    f"Xin: [收尾] 二段大招**一直没亮**"
                    f"（{self.FINISH_TIMEOUT:.0f} 秒内 liberation_available "
                    f"始终为假）—— 可能是还没解锁，或大招图标没被识别到")

        self.phase = "red"
        self.dominion_start = -1.0
        self.logger.info("Xin: 本轮循环结束 → 回红狐")

    # ------------------------------------------------------------------ 切换
    def get_switch_priority(self, current_char=None, has_intro=False,
                            target_low_con=False):
        """统御众机期间别被切走 —— 那是 13 秒爆发窗口，切了就断。

        ⚠ 收尾（二段大招）也在这段里，同样不能被打断。
        """
        if self.phase == "dominion":
            return SwitchPriority.NO
        return super().get_switch_priority(current_char, has_intro,
                                           target_low_con)
