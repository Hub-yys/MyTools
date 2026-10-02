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
    #: 放完终结重击后等二段大招的窗口
    FINISH_TIMEOUT = 5.0
    #: 普攻节奏
    ATTACK_INTERVAL = 0.12

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        #: 走到哪一步（跨 do_perform 调用保持）
        self.phase = "red"          # red / white / dominion / finish
        #: 统御开始的时刻
        self.dominion_start = -1.0

    def reset_state(self):
        super().reset_state()
        self.phase = "red"
        self.dominion_start = -1.0

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
        """统御众机：固定 13 秒爆发 → 终结重击【镇寰宇】 → **二段大招**。

        ⚠ 2026-10-01 修的 bug（用户报"心不放二段大招"）：二段大招原来放在
        :meth:`perform_finish` 里，但 ``do_perform`` 的 ``finally`` 会在
        ``perform_dominion`` 返回后**立刻切人** —— 而且此时协奏已满，
        ok-ww 下次轮到这个角色时又会马上切走，``perform_finish`` 永远没机会跑
        （日志里 ``[收尾]`` 一次都没出现，但 ``[统御众机] 13 秒到`` 出现了 9 次）。

        **所以二段大招必须在切人之前放完** —— 也就是在本方法里连着做完。
        """
        start = self.dominion_start if self.dominion_start > 0 else time.time()
        left = self.DOMINION_DURATION - self.time_elapsed_accounting_for_freeze(start)
        self.logger.info(f"Xin: [统御众机] 开始，剩 {left:.1f} 秒")

        while self.time_elapsed_accounting_for_freeze(start) < self.DOMINION_DURATION:
            self.cycle_start()
            self.click()
            self.cycle_sleep(self.ATTACK_INTERVAL)

        self.logger.info("Xin: [统御众机] 13 秒到 → 终结重击【镇寰宇】")
        self.heavy_attack(2.0)

        # ★ 紧接着放二段大招 —— **不能留到下一轮**（见方法说明）
        self.perform_finish()

    # ------------------------------------------------------------------ 收尾
    def perform_finish(self):
        """终结重击后放二段大招（终结爆发），然后回红狐。

        ⚠ 这个方法由 :meth:`perform_dominion` **当场调用**，
        不再靠 ``do_perform`` 的下一轮分派 —— 那样永远轮不到（见上）。
        保留成独立方法只是为了可读性和**可单测**。
        """
        self.logger.info("Xin: [收尾] 找二段大招")
        start = time.time()
        clicked = False
        while self.time_elapsed_accounting_for_freeze(start) < self.FINISH_TIMEOUT:
            if self.click_liberation():
                self.logger.info("Xin: [收尾] 二段大招（终结爆发）已放")
                clicked = True
                break
            self.cycle_sleep(0.1)
        if not clicked:
            self.logger.warning("Xin: [收尾] 二段大招没放出去")

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
