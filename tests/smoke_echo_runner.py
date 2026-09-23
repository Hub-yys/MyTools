"""强化流程状态机测试（假窗口 + 假识别器，不需要游戏）。

    python tests/smoke_echo_runner.py

验证的是"判定 → 动作"的映射是否正确：
    合格且满级   → 按 C 上锁
    不合格       → 开弃置时按 Z；没开就跳过（绝不误删）
    演练模式     → 一个键都不按
    外部叫停     → 能中断

验证不了的是真实坐标、真实截图、游戏是否买账——那必须接真游戏。
"""

from __future__ import annotations

import pathlib
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.tools.game.echo_enhance.controller import InputBlocked  # noqa: E402
from src.tools.game.echo_enhance.reader import OcrLine  # noqa: E402
from src.tools.game.echo_enhance.runner import (  # noqa: E402
    REGION_ADD_MATERIAL,
    REGION_CONFIRM,
    REGION_ENHANCE_BUTTON,
    REGION_LEVEL_ZERO,
    EchoRunner,
    RunnerStopped,
)
from src.tools.game.echo_enhance.stats import CRIT, CRIT_DMG, EchoStat, JudgeConfig  # noqa: E402

_failures: list[str] = []


def check(condition: bool, message: str) -> None:
    print(f"  [{'PASS' if condition else 'FAIL'}] {message}")
    if not condition:
        _failures.append(message)


class FakeWindow:
    """假的游戏窗口：记录所有点击/按键，画面用一张黑图糊弄。

    它还要**忠实模拟界面状态**，否则测不出 bug：

    * 点「培养」→ 进入强化界面，画面上就没有「培养」了（这正是"只强化一次"的根源）；
    * 按 ESC → 回到声骸列表，「培养」又出现。
    """

    def __init__(self, on_finish=None, reader=None):
        self.clicks: list[tuple[float, float]] = []
        self.keys: list[str] = []
        self.closed = False
        #: 上锁/弃置之后回调，用来模拟"这个声骸处理完了，列表往下走"
        self.on_finish = on_finish
        #: 用来切换"画面上有没有培养"（见类注释）
        self.reader = reader
        #: 权限自检是否通过（False 模拟"游戏跑在管理员权限下，工具被 UIPI 拦"）
        self.input_allowed = True

    def verify_input_allowed(self):
        if not self.input_allowed:
            raise InputBlocked("（测试）权限不足：游戏以管理员身份运行")

    def find(self):
        return 12345

    def describe(self):
        return "FakeWindow"

    def bring_to_front(self):
        return True

    def refresh_rect(self):
        pass

    def grab(self):
        # 只要形状对就行，OCR 被假识别器接管了
        return np.zeros((1080, 1920, 3), dtype=np.uint8)

    def click(self, x, y, after_sleep=0.3):
        self.clicks.append((x, y))
        x1, y1, x2, y2 = REGION_ENHANCE_BUTTON
        if self.reader is not None and x1 <= x <= x2 and y1 <= y <= y2:
            self.reader.enhance_visible = False      # 进了强化界面，「培养」消失

    def press(self, key, after_sleep=0.3):
        self.keys.append(key)
        if key == "esc" and self.reader is not None:
            self.reader.enhance_visible = True       # ESC 回到列表，「培养」回来
        if key in ("c", "z") and self.on_finish is not None:
            self.on_finish()

    def close(self):
        self.closed = True


class FakeReader:
    """假的识别器：按调用次数依次吐出预设的词条。

    ``finished`` 置位后就不再报告"0 级声骸"——模拟列表已经走到尽头，
    否则主循环会一直认为还有 0 级声骸可强化，测试就死循环了。
    """

    def __init__(self, stats_sequence: list[list[EchoStat]]):
        self.sequence = stats_sequence
        self.calls = 0
        self.finished = False
        #: 「培养」只在**声骸列表页**存在（进了强化界面就没了）
        self.enhance_visible = True

    def ocr_lines(self, frame):
        """界面上的按钮文字：让所有 _find_text 都能命中。"""
        lines = [
            OcrLine("阶段放入", 0.99, 0.15, 0.65, 0.2, 0.05),
            OcrLine("强化并调谐", 0.99, 0.15, 0.90, 0.2, 0.05),
        ]
        if self.enhance_visible:
            lines.append(OcrLine("培养", 0.99, 0.85, 0.88, 0.1, 0.05))
        if not self.finished:
            lines.append(OcrLine("声骸技能", 0.99, 0.70, 0.40, 0.15, 0.05))
        return lines

    def read_stats(self, frame):
        index = min(self.calls, len(self.sequence) - 1)
        self.calls += 1
        return self.sequence[index], []


def make_config() -> JudgeConfig:
    return JudgeConfig(
        core_stats=frozenset({CRIT, CRIT_DMG}),
        optional_stats=frozenset({"攻击百分比"}),
        crit_min=7.5,
        crit_dmg_min=15.0,
        min_valid_count=3,
    )


GOOD = [
    EchoStat(CRIT, 10.5),
    EchoStat(CRIT_DMG, 21.0),
    EchoStat("攻击百分比", 11.6),
    EchoStat("共鸣效率", 10.0),
    EchoStat("普攻伤害加成", 11.6),
]
BAD = [
    EchoStat(CRIT, 6.3),
    EchoStat(CRIT_DMG, 12.6),
    EchoStat("攻击", 40),
    EchoStat("生命", 470),
    EchoStat("防御", 40),
]


def enhance_clicks(window: FakeWindow) -> list[tuple[float, float]]:
    """落在「培养」区域里的点击（用来断言"进界面只做一次"）。"""
    x1, y1, x2, y2 = REGION_ENHANCE_BUTTON
    return [(x, y) for x, y in window.clicks if x1 <= x <= x2 and y1 <= y <= y2]


def build(stats_seq, *, allow_discard=False, dry_run=False, stop=None):
    reader = FakeReader(stats_seq)
    # 上锁/弃置之后让"0 级声骸"消失，模拟列表走到尽头
    window = FakeWindow(on_finish=lambda: setattr(reader, "finished", True), reader=reader)
    logs: list[str] = []
    runner = EchoRunner(
        window,
        reader,
        make_config(),
        allow_discard=allow_discard,
        dry_run=dry_run,
        max_count=3,  # 安全网：万一逻辑没收敛也不能把测试跑死
        log=logs.append,
        should_stop=stop or (lambda: False),
        settle=0.05,
    )
    return runner, window, logs


def main() -> int:
    print("=== 流程状态机测试（假窗口）===")

    # ---------------------------------------------------------- 1. 合格 → 上锁
    print("\n--- 用例 1：合格声骸 → 上锁，不弃置 ---")
    runner, window, logs = build([GOOD])
    stats = runner.run()
    print(f"  keys={window.keys}  clicks={len(window.clicks)}")
    check("c" in window.keys, "按了 C 上锁")
    check("z" not in window.keys, "没有误按 Z 弃置")
    check(stats.kept == 1 and stats.discarded == 0, f"统计正确 {stats.summary()}")

    # ---------------------------------------------------------- 2. 不合格 + 未开弃置
    print("\n--- 用例 2：不合格但未开启弃置 → 只跳过 ---")
    runner, window, logs = build([BAD], allow_discard=False)
    stats = runner.run()
    print(f"  keys={window.keys}")
    check("z" not in window.keys, "没开弃置时绝不按 Z")
    check(stats.skipped == 1, f"记为跳过（实际 skipped={stats.skipped}）")
    check(stats.enhanced == 1, "遇到跳过后立即停止，不会重复处理同一个声骸")
    check(bool(stats.skip_reasons), "记录了弃置原因")

    # ---------------------------------------------------------- 3. 不合格 + 开弃置
    print("\n--- 用例 3：不合格且开启弃置 → 按 Z ---")
    runner, window, logs = build([BAD], allow_discard=True)
    stats = runner.run()
    print(f"  keys={window.keys}")
    check("z" in window.keys, "按了 Z 弃置")
    check(stats.discarded == 1, f"统计正确（实际 {stats.discarded}）")

    # ---------------------------------------------------------- 4. 演练模式
    print("\n--- 用例 4：演练模式 → 一个键都不按 ---")
    runner, window, logs = build([GOOD], dry_run=True)
    runner.run()
    print(f"  clicks={window.clicks}  keys={window.keys}")
    check(not window.clicks, "演练模式没有点击")
    check(not window.keys, "演练模式没有按键")
    check(any("[DRY-RUN]" in line for line in logs), "日志里有 DRY-RUN 标注")

    # ---------------------------------------------------------- 5. 逐步强化
    print("\n--- 用例 5：先不合格继续、后合格 → 中间要连续强化 ---")
    partial = [EchoStat(CRIT, 10.5), EchoStat("攻击百分比", 11.6)]
    runner, window, logs = build([partial, GOOD])
    stats = runner.run()
    print(f"  reader 读取次数={runner.reader.calls}  点「培养」次数={len(enhance_clicks(window))}")
    check(runner.reader.calls >= 2, "词条分两次读取（模拟逐级调谐）")
    check(stats.kept == 1, "最终上锁")
    # ★ 回归："只强化一次就停"的根因是「培养」被塞进了每次强化里 ——
    #   「培养」只在列表页存在，所以第二次强化必然找不到它。
    check(len(enhance_clicks(window)) == 1, "一个声骸只点一次「培养」（进界面只做一次）")
    check("esc" in window.keys, "处理完回到列表（按了 ESC）")

    # ---------------------------------------------------------- 6. 叫停
    print("\n--- 用例 6：外部叫停 ---")
    runner, window, logs = build([GOOD], stop=lambda: True)
    try:
        runner.run()
        check(False, "应该抛出 RunnerStopped")
    except RunnerStopped:
        check(True, "停止请求能中断流程")

    # ---------------------------------------------------------- 7. 权限自检
    print("\n--- 用例 7：权限不足 → 立刻报错，一个点击都不发 ---")
    runner, window, logs = build([GOOD])
    window.input_allowed = False
    try:
        runner.run()
        check(False, "权限不足时应该抛 InputBlocked")
    except InputBlocked as exc:
        check("管理员" in str(exc) or "权限" in str(exc), f"报错是人话（{exc}）")
    check(not window.clicks, "一次点击都没发出去（不会假装跑了）")

    # ---------------------------------------------------------- 8. 出错回收
    print("\n--- 用例 8：界面不对 → 报错 + 尽力按 ESC 收回列表 ---")
    runner, window, logs = build([GOOD])
    runner.reader.enhance_visible = False        # 画面上根本没有「培养」
    try:
        runner.run()
        check(False, "应当抛出 RuntimeError")
    except InputBlocked:
        check(False, "不该是权限问题")
    except RuntimeError as exc:
        check("声骸面板" in str(exc), f"报错说清了原因（{exc}）")
    check("esc" in window.keys, "出错后尽力按 ESC 把游戏收回列表")

    print(f"\n=== 结果：{'全部通过' if not _failures else f'{len(_failures)} 项失败'} ===")
    for item in _failures:
        print(f"  - {item}")
    return 1 if _failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
