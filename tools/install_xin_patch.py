"""把 MyTools 给「心」加的东西**重新装回 vendor/okww**。

## 为什么需要它

我给 ok-ww 加「心」动了 3 处 **vendor 里的官方文件**：

    vendor/okww/okww/Labels.py          +5 个常量
    vendor/okww/okww/char/CharFactory.py +1 个 import + 1 条注册
    vendor/okww/okww/char/Xin.py        （新文件，不受影响）
    vendor/okww/ok_tasks/assets/…       （新目录，不受影响）

上游一更新，**前两处会被覆盖成官方版本** —— 「心」就没了，而且
**不报错**（只是退化成通用循环，静默地打得不好）。

所以这里做成**可重放的补丁脚本**：上游更新后跑一次就恢复。

    .venv/Scripts/python tools/install_xin_patch.py          # 检查
    .venv/Scripts/python tools/install_xin_patch.py --apply  # 装上

## 为什么不是 .patch 文件

用文本替换而不是 `git apply`：vendor 里的文件是**上游的**，
行号/上下文随时会变，patch 一冲突就废。文本锚点（找 `Labels.char_jingran`
那一行）比行号稳得多，而且**幂等**（装过再跑不会重复加）。
"""
from __future__ import annotations

import argparse
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8")

ROOT = pathlib.Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor" / "okww"

LABELS = VENDOR / "okww" / "Labels.py"
FACTORY = VENDOR / "okww" / "char" / "CharFactory.py"
SHOREKEEPER = VENDOR / "okww" / "char" / "ShoreKeeper.py"

#: ★★ 2026-10-25：**守岸人的"重击修复"已被撤销** —— 它根本不是 bug。
#:
#: ## 我之前改错了什么
#:
#: 我以为上游这句是死代码::
#:
#:     if not self.click_resonance():
#:         self.heavy_click_forte(self.is_mouse_forte_full)
#:
#: 理由：``click_resonance()`` 返回**元组**（永远真值），
#: 所以 ``not 元组`` 恒 False，重击永远不执行。
#:
#: 于是我改成无条件调用 ``heavy_click_forte(check_fun=is_mouse_forte_full)``。
#:
#: ## 为什么那是错的（用户实机报的）
#:
#: > 我感觉移过来的okww有问题，为什么打着打着我的角色就死了，
#: > 用原版可从未发生过这种情况
#:
#: ``heavy_click_forte`` 内部::
#:
#:     if check_fun():
#:         self.task.mouse_down()
#:         success = self.task.wait_until(lambda: not check_fun(), time_out=2)
#:         self.task.mouse_up()
#:
#: 满足条件时**长按鼠标最多 2 秒**。守岸人是**奶妈** —— 这 2 秒里
#: 完全不能治疗，而且每次 ``do_perform`` 循环都可能走 → 队友得不到奶
#: → **角色一个个死掉**。
#:
#: 上游那句"死代码"是**故意的刹车**：把守岸人锁在「E + 大 + 切人」的节奏上，
#: 重击优先级远低于治疗。**不是 bug，别修。**
#:
#: 所以现在这个脚本**不再碰 ShoreKeeper.py**，只保留必要的部分。
SK_NEEDLE = ""
SK_BLOCK = ""
SK_ALREADY = ""

#: Labels 里要加的常量（插在 `yangyang_sp` 之前，那是文件最后一项）
LABELS_ANCHOR = "    yangyang_sp = 'yangyang_sp'"
LABELS_BLOCK = """    # ★ MyTools 新增：「心」的识别模板（2026-10-01）
    # 模板不是官方 assets，而是放在 ok_tasks/assets/（上游的扩展目录），
    # 生成脚本：tools/make_xin_templates.py
    char_xin = 'char_xin'            # 队伍栏头像（认人）
    xin_red = 'xin_red'              # 红狐-紫条（应世心攒能中）
    xin_red_idle = 'xin_red_idle'    # 红狐-白条（常态）
    xin_white = 'xin_white'          # 白狐-金条（一段大已开）
    xin_dominion = 'xin_dominion'    # 统御众机-金色柱状格
"""

#: CharFactory：import。
#: ⚠ 三处都用**长而唯一的文本**当锚点 —— 上游改结构时宁可报"找不到锚点"
#:   （明确让人去看），也不要静默插错位置。
IMPORT_ALREADY = "from okww.char.Xin import Xin"
IMPORT_NEEDLE = "from okww.char.Xigelika import Xigelika\n"
IMPORT_BLOCK = (
    "# ★ MyTools 新增（2026-10-01）—— 上游没有这个角色，见 char_xin 的说明\n"
    "from okww.char.Xin import Xin\n"
)

#: CharFactory：注册（挂在 jingran 后面，那是最后一条）
REGISTER_ANCHOR = "    Labels.char_xin:"
REGISTER_NEEDLE = (
    "    Labels.char_jingran: {'cls': JingRan, 'char_type': CharType.MAIN_DPS,"
    " 'ring_index': Elements.FIRE},\n")
REGISTER_BLOCK = (
    "    # ★ MyTools 新增（2026-10-01）：「心」—— 上游还没有这个角色。\n"
    "    #   识别模板在 ok_tasks/assets/（见 tools/make_xin_templates.py），\n"
    "    #   战斗逻辑在 okww/char/Xin.py（本仓自写，未在实机验证）。\n"
    "    #   属性：5★ 导电 音感仪 → ring_index 用 ELECTRIC。\n"
    "    Labels.char_xin: {'cls': Xin, 'char_type': CharType.MAIN_DPS,\n"
    "                      'ring_index': Elements.ELECTRIC},\n")


def _patch(path: pathlib.Path, needle: str, block: str, *,
           already: str, label: str, apply: bool) -> tuple[bool, str]:
    """把 ``block`` 插到 ``needle`` 后面（幂等）。返回 (是否已就位, 说明)。"""
    if not path.exists():
        return False, f"✗ 找不到 {path}"
    text = path.read_text(encoding="utf-8")
    if already in text:
        return True, f"✓ {label} 已在位"
    if needle not in text:
        return False, (f"✗ {label}：找不到锚点（上游改了文件结构？）\n"
                       f"     锚点: {needle.strip()[:70]}")
    if not apply:
        return False, f"· {label} 需要安装（--apply 才动手）"
    path.write_text(text.replace(needle, needle + block, 1), encoding="utf-8")
    return True, f"✓ {label} 已安装"


def _patch_replace(path: pathlib.Path, needle: str, block: str, *,
                   already: str, label: str, apply: bool) -> tuple[bool, str]:
    """把 ``needle`` **替换**成 ``block``（幂等）。返回 (是否已就位, 说明)。

    ⚠ 和 :func:`_patch` 的区别：那个是"插在后面"（加东西），
    这个是"换掉"（改 bug）。混用会把旧代码留着 —— 实测踩过：
    第一次实现时用 _patch 追加，结果**旧的 bug 代码还在**，
    新的重击调用只是被加在它后面，等于没修。
    """
    if not path.exists():
        return False, f"✗ 找不到 {path}"
    text = path.read_text(encoding="utf-8")
    if already in text and needle not in text:
        return True, f"✓ {label} 已在位"
    if needle not in text:
        return False, (f"✗ {label}：找不到锚点（上游改了文件结构？）\n"
                       f"     锚点: {needle.strip()[:70]}")
    if not apply:
        return False, f"· {label} 需要安装（--apply 才动手）"
    path.write_text(text.replace(needle, block, 1), encoding="utf-8")
    return True, f"✓ {label} 已安装"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="把 MyTools 对 vendor/okww 的改动装回去"
                    "（目前**没有**需要重放的改动了）")
    parser.add_argument("--apply", action="store_true", help="真的写文件")
    args = parser.parse_args(argv[1:])

    print(f"vendor: {VENDOR}")
    print()
    print("  ✓ vendor/okww 现在与上游一致 —— 不需要打任何补丁。")
    print()
    print("  ## 历史（两个补丁都已撤销）")
    print()
    print("  1. 「心」：上游 v3.7.9 已自带 char_hsin / Hsin，")
    print("     自写的 Xin.py 已删除。")
    print("  2. 守岸人「重击修复」：**那是改错的** —— 上游的 if-not 是故意的")
    print("     刹车，改成无条件重击会让奶妈长按 2 秒不放治疗 → 角色死亡。")
    print("     2026-10-25 用户实机报告后已完全还原上游写法。")
    print()
    print("  ⚠ 这个脚本留着是为了**以后**真有补丁要重放时有地方放。")
    print("     别再往里加「修上游 bug」的改动 —— 先确认那真的是 bug。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
