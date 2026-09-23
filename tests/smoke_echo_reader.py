"""声骸读取 + 判定 的端到端冒烟测试（合成图，不需要游戏）。

    python tests/smoke_echo_reader.py

流程和真实运行时完全一致：
    合成/载入画面 → EchoReader 裁区域 + OCR → 配对成词条 → judge 判定
只是画面是画出来的，不是从游戏截的。所以它验证的是"识别→解析→判定"的链路，
验证不了"游戏画面长什么样、相对坐标对不对"——那部分必须接真游戏联调。
"""

from __future__ import annotations

import pathlib
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.tools.game.echo_enhance.reader import DEFAULT_STATS_REGION, EchoReader  # noqa: E402
from src.tools.game.echo_enhance.stats import CRIT, CRIT_DMG, JudgeConfig, judge  # noqa: E402

_failures: list[str] = []
SHOT_DIR = ROOT / "tests" / "_shots"


def check(condition: bool, message: str) -> None:
    print(f"  [{'PASS' if condition else 'FAIL'}] {message}")
    if not condition:
        _failures.append(message)


def load_font(size: int):
    for candidate in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf"):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    raise SystemExit("找不到中文字体")


def make_panel(rows: list[tuple[str, str]], width: int = 1920, height: int = 1080) -> np.ndarray:
    """画一张"声骸面板"：词条落在 DEFAULT_STATS_REGION 覆盖的区域内。"""
    img = Image.new("RGB", (width, height), (26, 28, 32))
    draw = ImageDraw.Draw(img)

    x1, y1, x2, y2 = DEFAULT_STATS_REGION
    region_top = y1 * height
    region_left = x1 * width
    region_w = (x2 - x1) * width

    font = load_font(30)
    line_h = ((y2 - y1) * height) / 6.0
    name_x = region_left + region_w * 0.05
    value_x = region_left + region_w * 0.72

    for i, (name, value) in enumerate(rows):
        y = region_top + line_h * (i + 0.3)
        draw.text((name_x, y), name, font=font, fill=(236, 238, 240))
        draw.text((value_x, y), value, font=font, fill=(236, 238, 240))

    return np.array(img)


def save(frame: np.ndarray, name: str) -> None:
    SHOT_DIR.mkdir(parents=True, exist_ok=True)
    Image.fromarray(frame).save(SHOT_DIR / name)


def main() -> int:
    print("=== 声骸读取 + 判定 端到端（合成图）===")

    reader = EchoReader()

    # ---------------------------------------------------------- 用例 1：合格声骸
    print("\n--- 用例 1：双爆达标、有效词条足够 → 应保留 ---")
    good_rows = [
        ("暴击", "10.5%"),
        ("暴击伤害", "21.0%"),
        ("攻击百分比", "11.6%"),
        ("共鸣效率", "10.0%"),
        ("普攻伤害加成", "11.6%"),
    ]
    frame = make_panel(good_rows)
    save(frame, "echo_panel_good.png")

    stats, lines = reader.read_stats(frame)
    print(f"  OCR 原始行 {len(lines)} 条: {[str(x) for x in lines]}")
    print(f"  解析出词条 {len(stats)} 条: {[str(s) for s in stats]}")

    check(len(stats) == 5, f"5 条词条全部解析出来（实际 {len(stats)}）")
    names = {s.name for s in stats}
    check(CRIT in names and CRIT_DMG in names, "暴击/暴击伤害都能识别")

    cfg = JudgeConfig(
        core_stats=frozenset({CRIT, CRIT_DMG}),
        optional_stats=frozenset({"攻击百分比", "共鸣效率"}),
        crit_min=7.5,
        crit_dmg_min=15.0,
        min_valid_count=3,
    )
    result = judge(stats, cfg)
    print(f"  判定: {result}")
    check(result.action == "lock", f"应判为保留（实际 {result.action}）")
    check(result.crit is not None and abs(result.crit - 10.5) < 0.01
          and result.crit_dmg is not None and abs(result.crit_dmg - 21.0) < 0.01,
          f"双爆应为 暴击10.5 / 爆伤21.0（实际 {result.crit} / {result.crit_dmg}）")

    # ---------------------------------------------------------- 用例 2：双爆太低
    print("\n--- 用例 2：双爆不达标 → 应弃置 ---")
    bad_rows = [
        ("暴击", "6.3%"),
        ("暴击伤害", "12.6%"),
        ("攻击", "40"),
        ("生命", "470"),
        ("防御", "40"),
    ]
    frame2 = make_panel(bad_rows)
    save(frame2, "echo_panel_bad.png")

    stats2, lines2 = reader.read_stats(frame2)
    print(f"  解析出词条 {len(stats2)} 条: {[str(s) for s in stats2]}")
    result2 = judge(stats2, cfg)
    print(f"  判定: {result2}")
    check(result2.action == "discard", f"应判为弃置（实际 {result2.action}）")
    check("双爆不达标" in result2.reason, "弃置原因指出是双爆不达标")

    # ---------------------------------------------------------- 用例 3：区域裁剪
    print("\n--- 用例 3：区域外的文字不该被读到 ---")
    img = Image.fromarray(make_panel(good_rows))
    draw = ImageDraw.Draw(img)
    draw.text((60, 60), "声骸技能", font=load_font(30), fill=(236, 238, 240))
    frame3 = np.array(img)
    stats3, _ = reader.read_stats(frame3)
    check(len(stats3) == 5, f"区域外的标题没干扰解析（实际 {len(stats3)} 条）")

    print(f"\n=== 结果：{'全部通过' if not _failures else f'{len(_failures)} 项失败'} ===")
    for item in _failures:
        print(f"  - {item}")
    return 1 if _failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
