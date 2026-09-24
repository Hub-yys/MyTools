"""用**真实探测数据**核对准备动作里的区域/文字对不对。

## 为什么需要它（2026-09-27）

同一天连着栽了两次，都是"区域/坐标跟实际界面对不上"，而**两次都不报错**：

1. `ECHO_TAB_POINT = (0.031, 0.296)` —— 注释写"背包左侧第 2 个图标是声骸页签"，
   实际那个位置是**左侧全局菜单的手套图标**；
2. `FILTER_BTN_POINT = (0.173, 0.988)` —— y 偏了 0.09（≈95px），点下去落在
   **漏斗图标下方的空白处**，于是筛选面板根本没打开；
   `SORT_REGION` 的 y 起点 0.93 更是**把「等级顺序」整行文字漏在外面**（实际在 0.885~0.905）。

这些坐标都是"照用户截图量的"，**但从没拿真实画面核对过**。
而工具本来就会生成探测数据（截图 + OCR 的每行文字/坐标），
那就不该再靠人眼量 —— 直接拿数据对。

## 怎么判 —— 三级，**只有能确证的才叫失败**

* **PASS**：文字出现了，且中心落在 ``region`` 里 → 区域至少能罩住它；
* **WARN**：文字出现了但**不在**区域里。⚠ **不判失败** —— 同一个词会出现在
  不同界面（实测「合鸣」在**声骸详情页**里也有，位置和筛选面板里那行完全不同），
  所以这可能只是"碰上了别的界面里的同名文字"。列出来让人看一眼；
* **SKIP**：这次探测的画面里根本没有该文字（比如"品质"要筛选面板打开后才有），
  单独列出来 —— 免得让人误以为"全验过了"。

## 数据从哪来

``data/probe/probe-*.txt``（工具在"有未校准步骤"或"失败留痕"时自动生成）。
没有数据时**跳过**（不算失败）—— 这脚本是"有现场就顺手核一遍"，不是必跑的前置。
"""

from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PROBE_DIR = ROOT / "data" / "probe"

#: ` 12 | 文字 | 0.5,0.4,0.1,0.05 | 960,432,192,54 | 0.99`
_ROW = re.compile(r"^\s*\d+\s*\|\s*(?P<text>.*?)\s*\|\s*"
                  r"(?P<rel>[\d.]+,[\d.]+,[\d.]+,[\d.]+)\s*\|")

CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append((name, ok, detail))


class OcrLine:
    __slots__ = ("text", "x", "y", "w", "h")

    def __init__(self, text: str, rel: str):
        self.text = text
        x, y, w, h = (float(v) for v in rel.split(","))
        self.x, self.y, self.w, self.h = x, y, w, h

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2


def parse_probe(path: pathlib.Path) -> list[OcrLine]:
    out: list[OcrLine] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        if raw.startswith("#"):
            continue
        m = _ROW.match(raw)
        if m:
            out.append(OcrLine(m.group("text"), m.group("rel")))
    return out


def in_region(ln: OcrLine, region) -> bool:
    x0, y0, x1, y1 = region
    return x0 <= ln.cx <= x1 and y0 <= ln.cy <= y1


def collect_click_text_steps():
    """所有需要核对的「文字 + 区域」对。**两类都要收**：

    * ``kind="click_text"`` —— 要**点**的那个文字（``text`` / ``region``）；
    * 任何步骤的**点完验证** —— ``expect`` / ``expect_region``
      （「按 B 之后必须在左上角看到『声骸』」就挂在这里，属于 ``press`` 步骤）。

    ⚠ 第一版只收了 ``click_text``，于是 ``ECHO_PAGE_REGION`` 这种挂在
    ``press.expect`` 上的区域**根本没被检查** —— 反证时才发现这个盲点。

    ⚠⚠ **必须用用户真实的筛选配置来生成步骤**（2026-09-27 又栽一次）：
    「主音属性」那几步只在配置里有 ``picks`` 时才生成。第一版拿一个**空配置**
    去生成，那些步骤压根不存在 → 检查报"0 失败"，可流程正卡在
    「添加主属性筛选」那步。**拿空样例去核对，等于没核对。**
    """
    from src.core.loadout import Loadout, LoadoutStore
    from src.tools.game.echo_enhance.prepare import PREP_STEPS, build_filter_steps

    steps = list(PREP_STEPS)
    try:
        real = LoadoutStore().all()
    except Exception:  # noqa: BLE001 - 配置读不出来就退到空配置，别让脚本崩
        real = []
    sources = real or [Loadout(character="绯雪", echo_set="雪落无声之愿")]
    for lo in sources:
        steps += list(build_filter_steps(lo))

    out = []
    for s in steps:
        if s.kind == "click_text" and s.text and s.region:
            out.append((f"点「{s.text}」（{s.label}）", s.text, s.region))
        if s.expect and s.expect_region and not s.expect_absent:
            out.append((f"验证「{s.expect}」在区域里（{s.label}）",
                        s.expect, s.expect_region))
    return out


def main() -> int:
    probes = sorted(PROBE_DIR.glob("probe-*.txt"))
    if not probes:
        print("没有探测数据（data/probe/*.txt）→ 跳过核对。")
        print("（跑一次任务流程、或让准备动作失败一次，就会自动生成。）")
        return 0
    path = probes[-1]
    lines = parse_probe(path)
    print(f"探测数据：{path.name}（{len(lines)} 行文字）")
    print()

    check("探测数据不是空的（否则下面是在空集合上空转）", len(lines) > 0,
          f"{len(lines)} 行")

    targets = collect_click_text_steps()
    check("确实收到了要核对的步骤", len(targets) >= 2, f"{len(targets)} 个「文字+区域」对")

    covered = 0
    uncovered: list[str] = []
    warned: list[tuple[str, str]] = []
    for label, text, region in targets:
        hits = [ln for ln in lines if text in ln.text]
        if not hits:
            uncovered.append(label)
            continue
        covered += 1
        where = [(round(h.cx, 3), round(h.cy, 3)) for h in hits]
        detail = f"「{text}」在 {where}，区域 {tuple(round(v, 3) for v in region)}"
        if any(in_region(ln, region) for ln in hits):
            check(f"★ 区域能罩住「{text}」（{label}）", True, detail)
        else:
            warned.append((label, detail))

    check("至少有一条步骤被真验到（覆盖率不为 0）", covered > 0,
          f"覆盖 {covered} / 共 {len(targets)}")

    if warned:
        print()
        print(f"以下 {len(warned)} 条：该文字出现了但**不在**区域里。"
              "（不判失败 —— 同名文字可能来自**别的界面**，比如「合鸣」在"
              "声骸详情页里也有。若确认是同一处，就该修 region。）")
        for name, detail in warned:
            print(f"  ⚠ {name}\n     {detail}")

    if uncovered:
        print()
        print(f"以下 {len(uncovered)} 条在**这次探测的画面里**找不到目标文字，未核对"
              "（不是失败 —— 它们要等对应的界面出现才能验）：")
        for name in uncovered:
            print(f"  · {name}")

    print()
    width = max(len(n) for n, _, _ in CHECKS)
    failed = 0
    for name, ok, detail in CHECKS:
        print(f"{name:<{width}} {'PASS' if ok else 'FAIL'}  {detail[:110]}")
        if not ok:
            failed += 1
    print()
    print(f"{len(CHECKS)} 项检查，{failed} 项失败")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
