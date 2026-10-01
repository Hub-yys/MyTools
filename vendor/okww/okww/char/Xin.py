"""「心」（心月狐）的 4C 刷声骸战斗逻辑（**单人流**）。

## ⚠ 这个文件的来历 —— 先看这里

**它不是 ok-ww 官方写的**，是 MyTools 按用户提供的机制说明 + 攻略实现的。
上游（ok-ww）**还没有**这个角色（我核对过：上游 `src/char` 里没有 Xin，
`char_*` 模板 67 个里也没有 `char_xin`）。

**机制来源**：
* 用户提供的游戏内「角色机制」截图 + 实机战斗截图
* 攻略：[心月狐攻略（TapTap）](https://www.taptap.cn/moment/854657182002580468)、
  [心 全方位培养攻略](https://niubi.wiki/2026/09/17/141732/)

## 机制（攻略原文提炼）

心有两形态，**必须按顺序走完，中途开二段大会大幅缩水**：

    应世相（红狐）  能量「应世心」上限 100
        普攻 / E / 变奏入场 攒应世心
        攒满 → 解锁强化重击【镇红尘】
        放【镇红尘】 → 解锁**一段大招**

    照世相（白狐）  能量「照世心」上限 300（**只能在白狐形态攒**）
        白狐形态攒满 → 放强化 E → 进【统御众机】，**固定 13 秒**
        统御期间普攻升级，持续消耗照世心
        照世心耗尽 → 打**终结重击【镇寰宇】**
        ⚠ **打完终结重击**才能解锁**二段大招**
        二段大招 = 终结爆发，打完回红狐

极简版（攻略原话）：
> 红狐攒应世心 → 强化重击开一段大变白狐；白狐攒照世心，
> 强化E开启 13s 统御爆发，终结重击后放二段大收尾。

## 判断形态的办法

用 ok-ww 的模板匹配看角色血条上方的能量条（模板见
``tools/make_xin_templates.py``）：

======================  ==========================
模板                     表示
======================  ==========================
``xin_red``              红狐-紫条（攒能中/满了）
``xin_red_idle``         红狐-白条（常态/低能量）
``xin_white``            白狐-金条（一段大已开）
``xin_dominion``         统御众机-金柱（爆发窗口）
======================  ==========================

⚠ 模板按 **1920×1080**（用户的游戏分辨率）生成。换分辨率要重跑生成脚本。
⚠ **本文件从未在实机验证过** —— 第一次跑请盯着看，有异常把
``data/okww/logs/`` 当天的日志发回来。

## 认人（char_xin）是怎么做出来的

ok-ww 本来**没有**心这个角色，所以它认不出 → 退化成 ``BaseChar`` 的通用循环。
``char_xin`` 模板是 MyTools 自己加的，做法见
``tools/make_xin_templates.py`` 的 ``_build_avatar`` —— 关键是**自标定尺度**：
用户的截图过了 QQ 压缩，不是 1:1 游戏像素，所以拿 ok-ww 认得出的
守岸人当"尺子"反推真实比例（实测 1.01），再按这个尺度裁心的头像。

实测：心的位置 char_xin **0.95~0.96**，其他所有模板 ≤0.62 → 稳定认出。
"""

import time

from okww.Labels import Labels
from okww.char.BaseChar import BaseChar, SwitchPriority


class Xin(BaseChar):
    """「心」——单人流循环（不依赖队友，全程站场）。"""

    #: 红狐攒应世心的上限时间（超了就放弃，避免卡死）
    FORTE_GAIN_TIMEOUT = 20.0
    #: 白狐攒照世心的上限时间
    WHITE_GAIN_TIMEOUT = 25.0
    #: 统御众机的固定持续时间（攻略："持续固定13秒"）
    DOMINION_DURATION = 13.0
    #: 统御里打完终结重击后的收尾等待
    FINISH_TIMEOUT = 6.0
    #: 普攻节奏
    ATTACK_INTERVAL = 0.12

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        #: 本轮循环走到哪一步（跨 do_perform 调用保持）
        self.phase = "red"          # red / white / dominion / finish

    def reset_state(self):
        super().reset_state()
        self.phase = "red"

    # ------------------------------------------------------------------ 主循环
    def do_perform(self):
        """一轮行动。

        ok-ww 会反复调它（每次上场时）。这里按"当前形态"分派 ——
        机制是**严格顺序**的，所以用 ``self.phase`` 记住走到哪了。
        """
        if self.phase == "red":
            self.perform_red()
        elif self.phase == "white":
            self.perform_white()
        elif self.phase == "dominion":
            self.perform_dominion()
        else:
            self.perform_finish()
        self.switch_next_char()

    # ------------------------------------------------------------------ 红狐
    def perform_red(self):
        """应世相：攒应世心 → 强化重击【镇红尘】 → 一段大招。

        攒能手段：普攻 + 共鸣技能（E）。有变奏入场时也涨。
        """
        self.wait_intro(1.2)
        # 声骸技能先甩掉（不占后面节奏）
        self.click_echo(time_out=0)

        start = time.time()
        heavy_done = False
        while self.time_elapsed_accounting_for_freeze(start) < self.FORTE_GAIN_TIMEOUT:
            self.cycle_start()
            # 能强化重击了 → 放【镇红尘】
            if self.heavy_available():
                self.logger.info("Xin: 应世心已满 → 强化重击【镇红尘】")
                self.heavy_attack(1.5)
                heavy_done = True
                break
            # 顺手丢 E（攒能快）
            self.click_resonance()
            self.click()
            self.cycle_sleep(self.ATTACK_INTERVAL)

        if not heavy_done:
            # 超时没攒满：不硬撑，交给下一轮（避免站场卡死）
            self.logger.warning("Xin: 应世心攒满超时，本轮放弃")
            return

        # 一段大招（放完就进白狐形态）
        if self.click_liberation():
            self.logger.info("Xin: 一段大招已开 → 进白狐形态")
            self.phase = "white"
            self.task.next_frame()

    def heavy_available(self) -> bool:
        """能不能打强化重击 —— 看能量条是不是紫条（``xin_red``）。

        ⚠ 这是一个**近似**判断：模板只能区分"紫条 / 白条 / 金条"，
        区分不了"紫条 80% 还是 100%"。所以真到边界时靠
        ``heavy_attack`` 自己失败重试 —— 见 :meth:`perform_red` 的循环。
        """
        return bool(self.task.find_one(Labels.xin_red, threshold=0.75))

    # ------------------------------------------------------------------ 白狐
    def perform_white(self):
        """照世相：攒照世心 → 强化 E → 进统御众机。"""
        start = time.time()
        while self.time_elapsed_accounting_for_freeze(start) < self.WHITE_GAIN_TIMEOUT:
            self.cycle_start()
            # 有强化 E（能进统御）了就按
            if self.resonance_available():
                self.logger.info("Xin: 照世心已满 → 强化 E 进统御众机")
                self.click_resonance()
                self.phase = "dominion"
                self.dominion_start = time.time()
                self.task.next_frame()
                return
            self.click()
            self.cycle_sleep(self.ATTACK_INTERVAL)
        self.logger.warning("Xin: 照世心攒满超时")

    # ------------------------------------------------------------------ 统御
    def perform_dominion(self):
        """统御众机：固定 13 秒爆发 → 榨干照世心 → 终结重击【镇寰宇】。"""
        start = getattr(self, "dominion_start", time.time())
        self.logger.info("Xin: 统御众机开始（13 秒爆发窗口）")

        while self.time_elapsed_accounting_for_freeze(start) < self.DOMINION_DURATION:
            self.cycle_start()
            self.click()
            self.cycle_sleep(self.ATTACK_INTERVAL)

        # 照世心耗尽 → 终结重击
        self.logger.info("Xin: 统御结束 → 终结重击【镇寰宇】")
        self.heavy_attack(2.0)
        self.phase = "finish"
        self.task.next_frame()

    # ------------------------------------------------------------------ 收尾
    def perform_finish(self):
        """终结重击后放**二段大招**（终结爆发），然后回红狐。

        ⚠ 攻略强调：**必须打完终结重击**才能开二段大，
        提前开会大幅缩水 —— 所以这个阶段紧跟在 :meth:`perform_dominion` 之后。
        """
        start = time.time()
        clicked = False
        while self.time_elapsed_accounting_for_freeze(start) < self.FINISH_TIMEOUT:
            if not clicked and self.click_liberation():
                self.logger.info("Xin: 二段大招（终结爆发）已放")
                clicked = True
                break
            self.click()
            self.cycle_sleep(self.ATTACK_INTERVAL)

        # 回红狐，下一轮重新开始
        self.phase = "red"

    # ------------------------------------------------------------------ 切换
    def get_switch_priority(self, current_char=None, has_intro=False,
                            target_low_con=False):
        """统御众机期间**别被切走** —— 那是 13 秒爆发窗口，切了就断。

        ``SwitchPriority.NO`` = 调度器不会选这个角色下场
        （看 ``BaseChar.get_switch_priority`` 的约定：值越小越不该被切）。
        """
        if self.phase == "dominion":
            return SwitchPriority.NO
        return super().get_switch_priority(current_char, has_intro,
                                           target_low_con)
