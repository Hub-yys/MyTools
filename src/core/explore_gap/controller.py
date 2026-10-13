# -*- coding: utf-8 -*-
"""闭环决策 —— **纯函数**：给状态，出动作。

## 为什么决策要单独抽出来、还要是纯函数

它是"会不会把路线毁掉"的那一层。混在"读屏幕 / 发按键"里就没法测 ——
而这条路径**没法在离线环境验证**（要真游戏）。所以::

    决策（本模块）  = 纯函数，喂状态出动作 → 能穷举单测
    执行（ok-ww）  = 按键/转向，离线测不了 → 靠决策层兜住

## 状态机

::

    LOCATING ──定位成功──→ FOLLOWING ──到达终点──→ DONE
        │                     │
        │ 连续失败            │ 连续测不准
        ▼                     ▼
     LOST（报错停下）      DRIFTED（停下等用户/重定位）

## ★★ 核心安全原则

**测不准就停，绝不用垃圾值乱动。**

实测（p4.mp4）：大偏离下相位相关返回过 1201.9px、743px 这种垃圾值。
照着它转，等于把整条路线走废。所以::

    peak < 闸门  → 丢弃这一帧（不产生任何动作）
    连续丢弃 N 次 → 判定"跟丢了"，停下来报错

**通过率下降不是变差，是安全阀在工作**（见 locator 模块文档）。

## 动作只有两种

1. **纠偏**：横向偏离 → 转视角 / 平移
2. **前进**：偏离足够小 → 照参考往下走

### ⚠ 为什么不做"纵向"纠偏

实测里纵向偏离（``dy``）远小于横向，且游戏里"前后"是靠走的 ——
用视角去纠纵向只会把画面转花。所以 ``dy`` 只用于**判断**，不产生动作。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .locator import PEAK_MIN


class ActionKind(Enum):
    """控制器能产生的动作。"""

    #: 还没定位上，继续看
    WAIT = "wait"
    #: 偏离过大 → 转向/平移纠偏
    CORRECT = "correct"
    #: 偏离够小 → 按参考往前走
    ADVANCE = "advance"
    #: ★ **照视频按键**（F / 空格 / 长按 E…）—— 「做一样的操作」
    KEY = "key"
    #: 到达参考末尾
    DONE = "done"
    #: 跟丢了 —— 停下来让上层报错（**不要硬纠**）
    LOST = "lost"


@dataclass(frozen=True)
class Action:
    """一个决策结果。"""

    kind: ActionKind
    #: 纠偏量（像素，正=当前画面需要往右移回参考，即视角左转）；
    #: 只有 :attr:`ActionKind.CORRECT` 有意义
    dx: float = 0.0
    #: ★ 要按的键（只有 :attr:`ActionKind.KEY` 有意义）
    key: str = ""
    #: ★ 按多久（秒）—— 长按机关靠它
    seconds: float = 0.0
    #: ★ 这次按键的原始提示（日志/报告要能回查"当时视频里写的是什么"）
    key_text: str = ""
    #: 为什么这么决定（日志 / 报告用，别删 —— 排查全靠它）
    reason: str = ""

    @property
    def is_terminal(self) -> bool:
        return self.kind in (ActionKind.DONE, ActionKind.LOST)


@dataclass(frozen=True)
class ExploreGapConfig:
    """闭环参数（默认值全部来自实测）。"""

    #: ★ 可信度闸门（locator.PEAK_MIN 的实测值）
    peak_min: float = PEAK_MIN
    #: 偏离小于等于它就算"对齐了"，可以前进（像素）
    #:
    #: 实测：3~40px 全部能过闸门且残差 ~0，所以工作点取 40。
    #:
    #: ## ⚠⚠ 这个阈值**同时**是"该不该纠偏"的分界 —— 只有一个阈值
    #:
    #: 我原来还写了个 ``correct_px=60``，于是 40~60 之间成了"谁也不管"
    #: 的区间：不前进（超了 align）、不纠偏（没超 correct）、只 WAIT，
    #: 而 WAIT 不改变任何状态 → **下一帧还是 WAIT** → 永久死锁。
    #:
    #: 闭环仿真实测：起始偏航 41px 时 **600 帧全 WAIT、0 次推进** ——
    #: 机器站在那儿一动不动。而且 41px 是很容易落进去的区间。
    #:
    #: 死区当初是想"避免在边界上反复横跳"，但那个担心是错的：
    #: 纠偏量 ``dx`` 约等于当前偏离量，纠一次就把它减掉了
    #: （``shift=45 → dx≈45 → shift→0``），本来就单调收敛，不会震荡。
    #:
    #: → 所以**只留这一个阈值**：超了就纠，没超就前进。
    #:   任何时候都不存在"无事可做"的状态。
    align_px: float = 40.0
    #: 连续多少次测不准就判定跟丢
    #:
    #: 实测可用率 ~90%，所以偶发测不准是**正常**的，不能一测不准就报错。
    lost_after: int = 15
    #: 连续多少次定位不到就判定跟丢
    miss_after: int = 10
    #: ★ **照视频按键**开不开。
    #:
    #: 关掉的话就退回"只会转视角 + 一直按 W" —— 遇到飞/解谜/长按机关/
    #: 对话分支全都会卡住（那正是这一版要补的东西）。
    #: 默认开；跑没有按键表的旧库时自动跳过（见 ``decide``）。
    press_keys: bool = True


@dataclass
class ExploreGapState:
    """跨帧的累计状态。"""

    #: ★ 当前在参考库里的位置（下标）。
    #:
    #: ## ⚠⚠ 这个字段由**定位**驱动，不是"我们自己数的步数"
    #:
    #: 原来只有执行器在推进它（``index += 1`` per advance），
    #: 那是**开环计数** —— 走快了 / 走慢了 / 被怪击退 / 中途停下看风景，
    #: 它都会漂。而按键表是"视频第几帧按什么键"，拿一个漂掉的数去查
    #: 就会在错的时间按键（在机关门前按跳跃、在平地上按对话）。
    #:
    #: 现在 ``decide`` 每帧用 ``fix.index``（**定位到的**位置）覆盖它 ——
    #: 定位是每帧重新对齐的，不累积误差。
    index: int = 0
    #: 连续测不准次数
    unclear: int = 0
    #: 连续定位失败次数
    miss: int = 0
    #: 已经走了多少步
    steps: int = 0
    #: 累计纠偏量（正负相抵后）
    total_dx: float = 0.0
    #: ★ 一共按了多少次键（照视频按的）—— 报告里要显示
    keys_pressed: int = 0
    #: 决策历史（最近若干条，给报告用）
    history: list[str] = field(default_factory=list)

    def note(self, text: str, *, keep: int = 40) -> None:
        self.history.append(text)
        if len(self.history) > keep:
            del self.history[:-keep]


def decide(
    fix,
    state: ExploreGapState,
    config: ExploreGapConfig,
    *,
    library_len: int,
    schedule=None,
) -> Action:
    """★ **核心决策**：给一次测量，出下一个动作。

    :param fix: :class:`~.locator.Fix`，或 ``None``（这一帧没测出来）
    :param state: 跨帧累计状态（**会被就地更新**）
    :param config: 闭环参数
    :param library_len: 参考库总长（判终点用）
    :param schedule: ★ 视频的**按键表**（:class:`~.keys.KeySchedule`）。
        给了就会在"走到视频按过键的那一刻"输出 ``KEY`` 动作 ——
        这才是"照视频做一样的操作"。不给 = 旧行为（只转视角 + 前进）。

    :return: :class:`Action`

    ## 决策顺序（顺序本身是设计，别调换）

    1. **没测出来** → 计数；超限判跟丢，否则 ``WAIT``
    2. **测出来但过不了闸门** → 计数；超限判跟丢，否则 ``WAIT``
    3. ★ **走到视频按过键的位置** → ``KEY``（照视频按）
    4. **偏离 > align_px** → ``CORRECT``（按 ``dx`` 撤销）
    5. **否则** → ``ADVANCE``

    ⚠ **只有三个"做事"的分支**（KEY / CORRECT / ADVANCE），且它们覆盖了
    所有情况 —— 中间**没有**死区。以前有过一个 40~60px 的死区，
    结果是永久死锁（见 :class:`ExploreGapConfig.align_px` 的说明）。

    ``WAIT`` 只在"这一帧没测准"时出现，而那种情况**有计数器兜底**，
    不会永远等下去。

    ## ★★ 为什么按键排在纠偏**前面**

    视频里按 F 的那一刻，通常是"人已经站到机关前了"。
    这时**先按键、再纠偏**是对的：机关一旦触发，画面会变（门开了、
    对话弹出来），再按旧参考去纠偏本来就没意义。

    反过来（先纠偏再按键）会怎样：纠偏要多花几帧，等纠完画面早已
    不是视频那一帧了，按键时机就错过了 —— 机关不开。
    """
    # ── ① 这一帧没测出来（定位失败 / 相位相关失败）
    if fix is None:
        state.miss += 1
        state.note(f"定位失败 x{state.miss}")
        if state.miss >= config.miss_after:
            return Action(ActionKind.LOST,
                          reason=f"连续 {state.miss} 帧定位不到 —— 可能不在"
                                 f"参考路线上（换场景了 / 没走到起点）")
        return Action(ActionKind.WAIT, reason=f"第 {state.miss} 次定位失败")

    #: 定位上了 → 清定位失败计数
    state.miss = 0
    state.steps += 1

    # ── ② 过不了闸门 = 测不准 → **丢弃，绝不采信**
    if not fix.trusted:
        state.unclear += 1
        state.note(f"测不准 peak={fix.peak:.3f} x{state.unclear}")
        if state.unclear >= config.lost_after:
            return Action(
                ActionKind.LOST,
                reason=(f"连续 {state.unclear} 帧测不准（可信度低于 "
                        f"{config.peak_min}）—— 画面已偏离太远，"
                        f"硬纠会照着无效值乱动，所以停下"))
        return Action(ActionKind.WAIT,
                      reason=f"可信度 {fix.peak:.3f} 不足，等下一帧")

    #: 测准了 → 清测不准计数
    state.unclear = 0
    shift = fix.shift

    #: ★ 把"我现在走到视频第几帧"记下来 —— 这是按键表的查询键。
    #: ⚠ 用 ``fix.index``（**定位到的**位置）而不是 ``state.index``
    #: （我们自己数的步数）。两者会漂：走快了/走慢了/被击退，
    #: 自己数的步数就不准了，而定位是每帧重新对齐的、不会累积误差。
    if fix.index >= 0:
        state.index = fix.index

    # ── ③ ★ 走到视频按过键的位置 → 照视频按
    if config.press_keys and schedule is not None:
        presses = schedule.presses_for(state.index)
        if presses:
            #: 只按第一个（同一帧有多个提示时，按最靠前的那个；
            #: 一次按键之后画面就会变，剩下的下一帧再说 —— 这也是
            #: 视频里的实际顺序）
            press = presses[0]
            state.keys_pressed += 1
            state.note(f"按键 {press.label}（{press.text}）@ {state.index}")
            return Action(
                ActionKind.KEY,
                key=press.key,
                seconds=press.seconds,
                key_text=press.text,
                reason=(f"视频在参考帧 {state.index} 处按了 {press.label}"
                        f"（提示原文「{press.text}」）"))

    # ── ④ 偏离超过阈值 → 纠偏（撤销量 = dx，交给执行方施加 -dx）
    if shift > config.align_px:
        state.total_dx += fix.dx
        state.note(f"纠偏 dx={fix.dx:+.1f} shift={shift:.1f}")
        return Action(
            ActionKind.CORRECT,
            dx=fix.dx,
            reason=(f"偏离 {shift:.0f}px 超过 {config.align_px:.0f}px，"
                    f"按 -dx 撤销"))

    # ── ⑤ 对齐了 → 前进（覆盖剩余全部情况）
    state.note(f"对齐 shift={shift:.1f} → 前进")
    return Action(ActionKind.ADVANCE,
                  reason=f"偏离 {shift:.0f}px 在容许范围内")


def at_end(state: ExploreGapState, library_len: int, *,
           tolerance: int = 2) -> bool:
    """参考路线是不是走完了。"""
    return state.index >= max(0, library_len - tolerance)
