# ⚠ LEGACY（2026-09-23）：本模块属于 MyTools **自写**的声骸强化实现，已不是主路径。
# 强化流程现在整段走 ok-ww 引擎（echo_enhance/okww_task.py + auto_combat/okww_boot.py），
# 判定条件走 echo_enhance/stats.py。保留它只是因为还有测试覆盖它；
# **不要在新代码里引用**，也不要照着它改流程。
"""批量强化声骸的流程状态机。

流程参照 ok-ww 的 ``EnhanceEchoTask``：

    背包(声骸界面, 已过滤+按等级排序)
      └─ 循环:
           点「培养」→ 点「阶段放入」→ 点「强化并调谐」→ 关弹窗
           → OCR 读词条 → 判定
                ├ 不合格 → 弃置(按 Z)  [默认关闭] / 或按 DRY-RUN 只记录
                ├ 合格且满 5 条 → 上锁(按 C)
                └ 还不满 → 继续强化
           按 ESC 回到列表, 处理下一个

三个安全设计：
* ``dry_run=True``：**只截屏识别判定，不点任何东西**。用它验证相对坐标和识别是否正确。
* ``allow_discard=False``（默认）：不执行弃置。弃置会真的分解声骸，需要显式开启。
* ``should_stop``：外部可随时叫停（界面上的「停止」按钮）。
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from .controller import GameWindow, WindowNotFound
from .reader import EchoReader, OcrLine
from .stats import EchoStat, JudgeConfig, judge

#: 界面上各操作点的相对区域 (x1, y1, x2, y2)，坐标沿用 ok-ww 的 16:9 基准。
REGION_ENHANCE_BUTTON = (0.82, 0.86, 0.97, 0.96)   # 「培养」
REGION_LEVEL_ZERO = (0.65, 0.35, 1.00, 0.57)       # 0 级时这里有「声骸技能」
REGION_ADD_MATERIAL = (0.09, 0.60, 0.38, 0.86)     # 「阶段放入」
REGION_CONFIRM = (0.10, 0.88, 0.29, 0.96)          # 「强化并调谐」
REGION_POPUP = (0.24, 0.18, 0.75, 0.98)            # 调谐成功之类的弹窗

#: 三个按钮的文字（OCR 可能把文字拆开，所以用包含匹配）
TEXT_ENHANCE = "培养"
TEXT_ADD_MATERIAL = "阶段放入"
TEXT_CONFIRM = "强化并调谐"
TEXT_CONFIRM_FALLBACK = "强化"
TEXT_LEVEL_ZERO = "声骸技能"

#: 弹窗文字。**必须够长够具体**：原来那条 `re.compile("点击任")` 是 3 字前缀匹配，
#: 界面上别处只要出现"点击任…"就会被当成弹窗，然后去点它的中心坐标（位置不对就是误触）。
_POPUP_PATTERNS = (
    re.compile("调谐成功"),
    re.compile("点击任意位置"),
    re.compile("不再提示"),
)

DEFAULT_TIMEOUT = 5.0


@dataclass
class RunnerStats:
    """一轮运行的结果统计。"""

    enhanced: int = 0          # 处理过的声骸数
    kept: int = 0              # 符合条件并上锁
    discarded: int = 0         # 弃置
    skipped: int = 0           # 未开启弃置而跳过的
    skip_reasons: list[str] = field(default_factory=list)

    def summary(self) -> str:
        text = f"处理 {self.enhanced} 个：符合 {self.kept}，弃置 {self.discarded}"
        if self.skipped:
            text += f"，跳过 {self.skipped}（未开启弃置）"
        return text


class RunnerStopped(RuntimeError):
    """被外部叫停。"""


class EchoRunner:
    def __init__(
        self,
        window: GameWindow,
        reader: EchoReader,
        judge_config: JudgeConfig,
        *,
        allow_discard: bool = False,
        dry_run: bool = False,
        max_count: int = 0,
        log: Callable[[str], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
        settle: float = 0.8,
    ):
        self.window = window
        self.reader = reader
        self.judge_config = judge_config
        self.allow_discard = allow_discard
        self.dry_run = dry_run
        self.max_count = max_count
        self.settle = settle
        self._log_fn = log or (lambda msg: None)
        self._should_stop = should_stop or (lambda: False)

    # ---------------------------------------------------------------- 工具
    def _log(self, message: str) -> None:
        self._log_fn(message)

    def _check_stop(self) -> None:
        if self._should_stop():
            raise RunnerStopped("已停止")

    def _sleep(self, seconds: float) -> None:
        """可中断的等待。"""
        deadline = time.time() + seconds
        while time.time() < deadline:
            self._check_stop()
            time.sleep(0.05)

    def _ocr_region(self, region: tuple[float, float, float, float]) -> tuple[list[OcrLine], np.ndarray]:
        """截图并 OCR 指定区域，返回 (行, 整帧)。坐标已换算回窗口相对值。"""
        frame = self.window.grab()
        height, width = frame.shape[:2]
        x1, y1, x2, y2 = region
        crop = frame[int(y1 * height): int(y2 * height), int(x1 * width): int(x2 * width)]
        lines = self.reader.ocr_lines(crop)

        span_x = (x2 - x1) * width or 1.0
        span_y = (y2 - y1) * height or 1.0
        converted = [
            OcrLine(
                text=ln.text,
                score=ln.score,
                x=x1 + ln.x / span_x * (x2 - x1),
                y=y1 + ln.y / span_y * (y2 - y1),
                width=ln.width / span_x * (x2 - x1),
                height=ln.height / span_y * (y2 - y1),
            )
            for ln in lines
        ]
        return converted, frame

    def _find_text(
        self,
        region: tuple[float, float, float, float],
        wanted: str,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> OcrLine | None:
        """在区域里找含指定文字的 OCR 行。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            self._check_stop()
            lines, _ = self._ocr_region(region)
            for line in lines:
                if wanted in line.text:
                    return line
            time.sleep(0.25)
        return None

    def _click_text(
        self,
        region: tuple[float, float, float, float],
        wanted: str,
        timeout: float = DEFAULT_TIMEOUT,
        after_sleep: float = 0.5,
    ) -> bool:
        line = self._find_text(region, wanted, timeout)
        if line is None:
            return False
        if self.dry_run:
            self._log(f"[DRY-RUN] 本会点击「{wanted}」({line.x:.3f}, {line.y:.3f})")
            return True
        self.window.click(line.x + line.width / 2, line.y + line.height / 2, after_sleep=after_sleep)
        return True

    # ---------------------------------------------------------------- 界面状态
    def on_echo_panel(self) -> bool:
        """当前是否在声骸面板（靠「培养」按钮判断）。"""
        return self._find_text(REGION_ENHANCE_BUTTON, TEXT_ENHANCE, timeout=1.5) is not None

    def at_level_zero(self) -> bool:
        """当前声骸是不是 0 级。"""
        return self._find_text(REGION_LEVEL_ZERO, TEXT_LEVEL_ZERO, timeout=1.5) is not None

    # ---------------------------------------------------------------- 单步动作
    def _dismiss_popups(self, timeout: float = 2.0) -> None:
        """关掉「调谐成功」「不再提示」这类弹窗。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            self._check_stop()
            lines, _ = self._ocr_region(REGION_POPUP)
            hit = None
            for line in lines:
                if any(p.search(line.text) for p in _POPUP_PATTERNS):
                    hit = line
                    break
            if hit is None:
                return
            if self.dry_run:
                self._log(f"[DRY-RUN] 本会关闭弹窗「{hit.text}」")
                return
            self.window.click(hit.x + hit.width / 2, hit.y + hit.height / 2, after_sleep=1.0)

    def _enter_enhance_panel(self) -> None:
        """从声骸列表进入强化界面：连点「培养」，直到它从画面上消失。

        「培养」**只在声骸列表页存在**，进入强化界面后就没了 —— 消失即代表已经进去了。
        （对应 ok-ww 的 ``while ... click 培养 ... if not enhance: break``。）

        ⚠ 这一步**每个声骸只做一次**。以前它被放在"每次强化"里，于是第 2 次强化时
        人已经站在强化界面、画面上没有「培养」，5 秒超时后抛错 —— 表现就是
        **"只强化一次就停"**（实测日志：`第 1 次强化 → 判定 continue → 第 2 次强化 →
        找不到「培养」按钮`）。
        """
        self._log("  进入强化界面（点「培养」）")
        deadline = time.time() + DEFAULT_TIMEOUT
        clicked = False
        while time.time() < deadline:
            self._check_stop()
            if self._click_text(REGION_ENHANCE_BUTTON, TEXT_ENHANCE,
                                timeout=1.0, after_sleep=0.4):
                clicked = True
                continue
            if clicked:
                return                      # 「培养」没了 = 已经进到强化界面
            time.sleep(0.2)
        if not clicked:
            raise RuntimeError("找不到「培养」按钮，确认游戏停在声骸面板")

    def _enhance_one_stage(self) -> None:
        """强化**一个阶段**：阶段放入 → 强化并调谐 → 关弹窗。

        **不含「培养」** —— 进界面是每个声骸一次的事，见 :meth:`_enter_enhance_panel`。
        """
        # 「阶段放入」可能要连点几次才把材料填满
        clicked = False
        deadline = time.time() + DEFAULT_TIMEOUT
        while time.time() < deadline:
            if self._click_text(REGION_ADD_MATERIAL, TEXT_ADD_MATERIAL, timeout=1.0, after_sleep=0.3):
                clicked = True
            else:
                if clicked:
                    break
                time.sleep(0.2)
        if not clicked:
            raise RuntimeError(
                "找不到「阶段放入」。请在游戏「强化设置」里勾选「阶段放入」"
            )

        if not self._click_text(REGION_CONFIRM, TEXT_CONFIRM, timeout=DEFAULT_TIMEOUT, after_sleep=1.5):
            if self._find_text(REGION_CONFIRM, TEXT_CONFIRM_FALLBACK, timeout=1.0):
                raise RuntimeError("请到游戏「强化设置」里勾选「同步调谐」")
            raise RuntimeError("找不到「强化并调谐」按钮")
        self._dismiss_popups()

    def _read_current_stats(self) -> list[EchoStat]:
        """读当前声骸已调谐出的词条。"""
        frame = self.window.grab()
        stats, lines = self.reader.read_stats(frame)
        self._log(f"  读到词条 {len(stats)} 条：" + "、".join(str(s) for s in stats))
        if not stats and lines:
            self._log("  (OCR 看到了文字但没能配成词条：" + "、".join(str(x) for x in lines[:8]) + ")")
        return stats

    def _mark_keep(self) -> None:
        if self.dry_run:
            self._log("[DRY-RUN] 本会按 C 上锁")
            return
        self.window.press("c", after_sleep=1.0)

    def _mark_discard(self) -> None:
        if self.dry_run:
            self._log("[DRY-RUN] 本会按 Z 弃置")
            return
        self.window.press("z", after_sleep=1.0)

    #: 回列表时最多按几次 ESC。**加这个上限是因为它也是"出错回收"的兜底动作**：
    #: 万一游戏根本不在声骸界面（比如已经被切到主菜单），无限按 ESC 会一路把
    #: 游戏的菜单按出来。正常情况按 1~2 次就回到列表了。
    MAX_ESC_PRESSES = 6

    def _back_to_list(self) -> None:
        if self.dry_run:
            return
        for _ in range(self.MAX_ESC_PRESSES):
            self._check_stop()
            self.window.press("esc", after_sleep=0.5)
            if self.on_echo_panel():
                return
        raise RuntimeError("按 ESC 后没能回到声骸列表")

    # ---------------------------------------------------------------- 主流程
    def process_one_echo(self, stats_out: RunnerStats) -> str:
        """处理当前这一个声骸，返回 'keep' / 'discard' / 'skip'。"""
        attempt = 0
        if not self.dry_run:
            # ★ 进强化界面：每个声骸**只做一次**（演练模式不点任何东西，跳过）
            self._enter_enhance_panel()
        while True:
            self._check_stop()
            attempt += 1
            self._log(f"  第 {attempt} 次强化")
            self._enhance_one_stage()
            stats = self._read_current_stats()
            result = judge(stats, self.judge_config)
            self._log(f"  判定：{result}")

            if result.action == "discard":
                if self.allow_discard or self.dry_run:
                    self._mark_discard()
                    self._back_to_list()
                    stats_out.discarded += 1
                    stats_out.skip_reasons.append(result.reason)
                    return "discard"

                self._log("  ⚠ 判定为弃置，但当前未开启「允许弃置」，跳过不处理")
                stats_out.skipped += 1
                stats_out.skip_reasons.append(result.reason)
                self._back_to_list()
                return "skip"

            if result.action == "lock":
                self._mark_keep()
                self._back_to_list()
                stats_out.kept += 1
                return "keep"

            if self.dry_run:
                self._log("[DRY-RUN] 停止：演练模式不继续强化下一个阶段")
                return "skip"

            if attempt >= 8:
                raise RuntimeError(
                    "同一个声骸连续强化 8 次还没出结果，已中止 —— "
                    "多半是 OCR 一直读不到词条（先确认游戏分辨率为 16:9，"
                    "或跑一次「探测背包界面」看看文字认没认出来）"
                )

    def run(self) -> RunnerStats:
        """主循环：一直处理到没有 0 级声骸，或被叫停。"""
        stats = RunnerStats()
        try:
            self._main_loop(stats)
        except RunnerStopped:
            raise
        except Exception:
            # 出错时**尽力把画面收回声骸列表**：否则游戏被丢在强化界面里，
            # 下一次运行会直接报「没检测到声骸面板」，用户得自己去按 ESC。
            if not self.dry_run:
                try:
                    self._log("出错后尝试按 ESC 回到声骸列表…")
                    self._back_to_list()
                except Exception:  # noqa: BLE001 - 兜底动作失败不该盖掉原始报错
                    self._log("  （没能自动回到列表，请手动按 ESC）")
            raise
        self._log("汇总：" + stats.summary())
        return stats

    def _main_loop(self, stats: RunnerStats) -> None:
        if not self.dry_run:
            if self.window.find() is None:
                raise WindowNotFound(
                    "没找到《鸣潮》窗口。请先打开游戏，并用**窗口模式**（无边框窗口）"
                )
            self._log(f"窗口：{self.window.describe()}")
            if not self.window.bring_to_front():
                self._log("  ⚠ 游戏窗口没能置前（被别的窗口压着 / 权限不足）"
                          "—— 截图与点击可能落到别的窗口上")
            self._sleep(0.5)
            # 权限自检：游戏以管理员身份运行时（鸣潮带 ACE 反外挂，必然如此），
            # 普通权限的工具一个输入都发不出去，而且 keybd_event 是**静默**失败。
            # 先试一下，失败立刻给人话，别等第一次点击才炸。
            self._log("自检：确认能向游戏窗口发送输入…")
            self.window.verify_input_allowed()
            self._log("  ✓ 输入可用")

        if not self.on_echo_panel():
            raise RuntimeError(
                "没检测到声骸面板。请先：背包(B) → 声骸 → 用过滤器筛出要强化的 → "
                "按等级升序排序，停在列表界面再点运行"
            )

        while True:
            self._check_stop()
            if self.max_count and stats.enhanced >= self.max_count:
                self._log(f"达到设定的数量上限 {self.max_count}，结束")
                break

            if not self.at_level_zero():
                self._log("没有 0 级声骸了，任务结束")
                break

            stats.enhanced += 1
            outcome = self.process_one_echo(stats)
            self._log(f"#{stats.enhanced} → {outcome}")

            if self.dry_run:
                self._log("演练模式只处理一个样本，结束")
                break

            if outcome == "skip":
                # 不合格但没开弃置：这个声骸还在列表原地，再转一圈只会重复处理它，
                # 所以这里必须停下来（既不误删，也不空转）。
                self._log(
                    "遇到不符合条件的声骸，但未开启「允许弃置」，任务停止。"
                    "要么勾选弃置，要么先手动处理掉这一个再重跑。"
                )
                break
