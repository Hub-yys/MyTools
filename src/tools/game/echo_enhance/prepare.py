# ⚠ LEGACY（2026-09-23）：本模块属于 MyTools **自写**的声骸强化实现，已不是主路径。
# 强化流程现在整段走 ok-ww 引擎（echo_enhance/okww_task.py + auto_combat/okww_boot.py），
# 判定条件走 echo_enhance/stats.py。保留它只是因为还有测试覆盖它；
# **不要在新代码里引用**，也不要照着它改流程。
"""任务流程「开始」步里的**准备动作**：把游戏停到"可以直接强化"的界面。

    按 B 打开背包
      └─ 切到「声骸」页签
           └─ 打开过滤器，筛出未调谐（0 级）的声骸
                └─ 按等级升序排序
                     └─ 停在声骸列表 —— 强化工具从这里接手

⚠ **现状：只有「按 B」这一步是确定的。**
游戏里「声骸页签 / 过滤器 / 排序」的按钮文字和位置，我这边**没有真实界面数据**，
所以 :data:`PREP_STEPS` 里那几步的 ``text`` / ``region`` 是**待校准的占位值**，
``verified=False`` —— 默认**直接跳过**，绝不去点游戏里任何不确定的地方
（猜错坐标可能触发分解、弃置这类破坏性操作，不能赌）。

跳过的同时会自动跑 :meth:`EchoPrep.probe`：把当前画面截图 + OCR 出来的每一行
「序号 + 文字 + 相对坐标 + 像素坐标」落到 ``data/probe/``，并且**在截图上画出框和序号**
—— 拿这一张图 + 一个 txt 就能把 ``PREP_STEPS`` 里的文本和区域填成真的。

为什么参考实现没做这几步：ok-ww 的说明就写着
「点击B进入背包, 在过滤器中选择需要强化的声骸, 并按照等级从0排序后开始」，
运行时只断言「必须在背包声骸界面过滤后开始!」—— 它也是让用户手动筛的。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

import numpy as np

from ....core import paths
from .controller import GameWindow, WindowNotFound
from .reader import EchoReader, OcrLine

#: 探测产物落这里（用户数据目录下的 probe/，见 core/paths.py）
DEFAULT_PROBE_DIR = paths.user_data_dir() / "probe"


@dataclass(frozen=True)
class PrepAction:
    """准备动作的一项。

    ``verified=False`` = **还没校准**（文本/区域是占位值）：默认跳过、不点游戏。
    校准方式：跑一次探测，照着 ``data/probe/probe-*.png`` + ``.txt`` 把
    ``region`` / ``text`` 填成真的，然后把 ``verified`` 改成 True。
    """

    kind: str                                   # "press" / "click_text"
    label: str                                  # 日志里的说明
    key: str = ""                               # kind="press" 的按键名
    region: tuple[float, float, float, float] = ()   # kind="click_text" 的搜索区域（相对坐标）
    text: str = ""                              # kind="click_text" 要找的文字（包含匹配）
    verified: bool = False
    wait: float = 0.8                           # 动作之后的等待（游戏要时间响应）
    note: str = ""


#: 准备步骤表。**只有第一项是已校准的**，其余等探测结果回来再填。
PREP_STEPS: tuple[PrepAction, ...] = (
    PrepAction(
        "press", "打开背包", key="b", verified=True, wait=1.8,
        note="背包本来就是开着的时，这一下会把它关掉（暂时没法判断背包状态，"
             "校准完过滤器步骤后可以靠页签文字先判一次）",
    ),
    PrepAction(
        "click_text", "切到「声骸」页签",
        region=(0.02, 0.08, 0.30, 0.92), text="声骸",
        note="待校准：背包左侧页签里「声骸」的实际位置",
    ),
    PrepAction(
        "click_text", "打开过滤器",
        region=(0.70, 0.02, 1.00, 0.14), text="筛选",
        note="待校准：过滤器按钮在背包右上角还是右下角，文字是「筛选」还是「过滤器」",
    ),
    PrepAction(
        "click_text", "筛出「未调谐」声骸",
        region=(0.15, 0.10, 0.85, 0.95), text="未调谐",
        note="待校准：过滤器面板里「未调谐 / 未强化」那一项的文字",
    ),
    PrepAction(
        "click_text", "确认筛选",
        region=(0.50, 0.80, 0.98, 0.98), text="确认",
        note="待校准：过滤器面板的确定/应用按钮",
    ),
    PrepAction(
        "click_text", "按等级升序排序",
        region=(0.65, 0.10, 1.00, 0.60), text="等级",
        note="待校准：排序方式里「等级」那一项（要的是升序，0 级在最前）",
    ),
)


@dataclass
class ProbeResult:
    """一次探测的产物。"""

    png_path: Path
    txt_path: Path
    lines: int = 0
    pending: tuple[str, ...] = ()       # 这次跳过、还等着校准的步骤

    def summary(self) -> str:
        text = f"探测完成：{self.lines} 行文字 → {self.txt_path.name}"
        if self.pending:
            text += f"（{len(self.pending)} 个准备步骤待校准）"
        return text


class EchoPrep:
    """「开始」步的准备动作：开背包 → （校准后）筛选 → 必要时探测。"""

    def __init__(
        self,
        window: GameWindow | None = None,
        reader: EchoReader | None = None,
        *,
        log: Callable[[str], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
        probe_dir: Path | str | None = None,
        force_probe: bool = False,
        steps: tuple[PrepAction, ...] | None = None,
    ):
        self.window = window
        self.reader = reader
        self.probe_dir = Path(probe_dir) if probe_dir else DEFAULT_PROBE_DIR
        self.force_probe = force_probe
        self.steps = steps if steps is not None else PREP_STEPS
        self._log_fn = log or (lambda _msg: None)
        self._should_stop = should_stop or (lambda: False)

    # ---------------------------------------------------------------- 工具
    def _log(self, message: str) -> None:
        self._log_fn(message)

    def _check_stop(self) -> None:
        if self._should_stop():
            raise RuntimeError("已停止")

    def _get_window(self) -> GameWindow:
        window = self.window or GameWindow()
        self.window = window
        return window

    def _get_reader(self) -> EchoReader:
        if self.reader is None:
            self.reader = EchoReader()
        return self.reader

    # ---------------------------------------------------------------- 主流程
    def run(self) -> ProbeResult | None:
        """跑准备动作。

        返回 ``None`` = 所有步骤都校准好了、按流程走完；
        返回 :class:`ProbeResult` = 有步骤还没校准（跳过了），顺便出了探测产物。
        """
        window = self._get_window()
        if window.find() is None:
            raise WindowNotFound(
                "没找到《鸣潮》窗口。请先打开游戏，并用**窗口模式**（无边框窗口）"
            )
        self._log(f"窗口：{window.describe()}")
        if not window.bring_to_front():
            # 探测最怕这个：抓到的其实是"当前前台那个窗口"（实测拍到过 MyTools 自己）
            self._log("  ⚠ 游戏窗口没能置前 —— 探测结果可能是别的窗口的画面，先点一下游戏再试")
        self._check_stop()

        pending: list[PrepAction] = []
        for step in self.steps:
            self._check_stop()
            if not step.verified:
                pending.append(step)
                continue
            if step.kind == "press":
                self._log(f"准备：{step.label}（按 {step.key.upper()}）")
                window.press(step.key, after_sleep=step.wait)
            elif step.kind == "click_text":
                self._log(f"准备：{step.label}（点「{step.text}」）")
                if not self._click_text(window, step):
                    raise RuntimeError(
                        f"准备步骤「{step.label}」没找到文字「{step.text}」，"
                        f"确认游戏停在能操作的状态"
                    )
            else:
                raise ValueError(f"不认识的准备动作类型：{step.kind}")

        if pending:
            self._log("以下准备步骤还没校准，已跳过（不会去点游戏里不确定的位置）：")
            for step in pending:
                self._log(f"  · {step.label} —— {step.note or '待校准'}")

        if pending or self.force_probe:
            return self.probe(window, pending=tuple(step.label for step in pending))
        return None

    # ---------------------------------------------------------------- 点击
    def _click_text(self, window: GameWindow, step: PrepAction) -> bool:
        line = self._find_text(window, step.region, step.text, timeout=3.0)
        if line is None:
            return False
        window.click(line.x + line.width / 2, line.y + line.height / 2, after_sleep=step.wait)
        return True

    def _find_text(
        self,
        window: GameWindow,
        region: tuple[float, float, float, float],
        wanted: str,
        timeout: float = 3.0,
    ) -> OcrLine | None:
        """在相对区域里 OCR，找含指定文字的行（坐标换算回 0~1 相对值）。

        这套"按区域 OCR + 相对坐标换算"在 ``runner.py`` 里也有一份
        （那边还要顺带返回整帧做别的用）。等准备步骤校准完，两处可以合成一个工具函数。
        """
        reader = self._get_reader()
        deadline = time.time() + timeout
        while time.time() < deadline:
            self._check_stop()
            frame = window.grab()
            height, width = frame.shape[:2]
            x1, y1, x2, y2 = region
            crop = frame[int(y1 * height): int(y2 * height), int(x1 * width): int(x2 * width)]
            lines = reader.ocr_lines(crop)
            # crop 内的像素坐标 → 整帧的相对坐标（和 runner._ocr_region 同一套算法）
            span_x = (x2 - x1) * width or 1.0
            span_y = (y2 - y1) * height or 1.0
            for line in lines:
                if wanted and wanted in line.text:
                    return OcrLine(
                        text=line.text,
                        score=line.score,
                        x=x1 + line.x / span_x * (x2 - x1),
                        y=y1 + line.y / span_y * (y2 - y1),
                        width=line.width / span_x * (x2 - x1),
                        height=line.height / span_y * (y2 - y1),
                    )
            time.sleep(0.25)
        return None

    # ---------------------------------------------------------------- 探测
    def probe(self, window: GameWindow | None = None,
              pending: tuple[str, ...] = ()) -> ProbeResult:
        """截当前画面 → OCR → 落盘「画了框和序号的 png」+「序号/文本/坐标的 txt」。

        这两个文件就是校准 ``PREP_STEPS`` 用的原始数据。
        ``pending`` 是这次因为没校准而跳过的步骤，记进结果里方便日志和界面提示。
        """
        window = window or self._get_window()
        self._log(f"探测当前界面：截图 + OCR，结果写到 {self.probe_dir}")
        frame = window.grab()
        height, width = frame.shape[:2]
        lines = sorted(self._get_reader().ocr_lines(frame), key=lambda ln: (ln.y, ln.x))

        out_dir = Path(self.probe_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        png_path = out_dir / f"probe-{stamp}.png"
        txt_path = out_dir / f"probe-{stamp}.txt"

        # 图上画框 + 序号，和 txt 里的序号一一对应。
        # 画框只是给人看的，失败了照样把原始截图存下来。
        marked = frame.copy()
        drew = False
        try:
            import cv2

            for index, line in enumerate(lines, 1):
                x1, y1 = int(line.x), int(line.y)
                x2, y2 = int(line.x + line.width), int(line.y + line.height)
                cv2.rectangle(marked, (x1, y1), (x2, y2), (0, 0, 255), 2)
                cv2.putText(marked, str(index), (x1, max(12, y1 - 4)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1, cv2.LINE_AA)
            drew = True
        except Exception:  # noqa: BLE001
            self._log("  （画框失败，存的是原始截图）")

        try:
            import cv2

            # imencode + tofile：路径含中文时 cv2.imwrite 会失败，这个写法不会
            cv2.imencode(".png", marked if drew else frame)[1].tofile(str(png_path))
        except Exception as exc:  # noqa: BLE001 - 截图存不下来就只留文本，别把整步搞崩
            self._log(f"  ⚠ 截图保存失败：{exc}")

        rows = [
            f"# 窗口 {width}x{height}  共 {len(lines)} 行文字",
            "# 序号 | 文本 | 相对坐标 x,y,w,h（0~1）| 像素坐标 x,y,w,h",
        ]
        for index, line in enumerate(lines, 1):
            rel = (line.x / width, line.y / height, line.width / width, line.height / height)
            rows.append(
                "%3d | %s | %.4f,%.4f,%.4f,%.4f | %d,%d,%d,%d | %.2f"
                % (index, line.text, rel[0], rel[1], rel[2], rel[3],
                   line.x, line.y, line.width, line.height, line.score)
            )
        txt_path.write_text("\n".join(rows) + "\n", encoding="utf-8")

        self._log(f"  截图（画了框和序号）：{png_path}")
        self._log(f"  文字与坐标：{txt_path}")
        return ProbeResult(png_path, txt_path, len(lines), pending)
