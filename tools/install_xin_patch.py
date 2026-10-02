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

#: ★ 守岸人「能量条满了就放重击」——**修 ok-ww 上游的一个 bug**。
#:
#: ## 上游的写法（有 bug）
#:
#:     if not self.click_resonance():
#:         self.heavy_click_forte(self.is_mouse_forte_full)
#:
#: ``click_resonance()`` 返回的是**元组** ``(clicked, duration, has_animation)``
#: —— 元组**永远是真值**，所以 ``not 元组`` **永远是 False**，
#: 那句重击是**死代码**。用户实测："ok-ww 的守岸人不释放重击"。
#:
#: 对照 ok-ww 自己的 **Changli**（同样是"攒满→重击"型），写的是
#: ``self.heavy_click_forte(check_fun=self.is_mouse_forte_full)`` ——
#: **无条件调用**（函数内部自己判断能量满没满）。这才是正确用法。
#:
#: ## 怎么修的
#:
#: 摘掉那个 ``if not ...`` 包装，改成无条件调用 —— 和 Changli 一致。
#: ``heavy_click_forte`` 内部会先查 ``check_fun()``（能量满没满），
#: 没满就什么都不做，所以无条件调用是安全的。
SK_NEEDLE = (
    "        if not self.click_resonance():\n"
    "            self.heavy_click_forte(self.is_mouse_forte_full)\n"
)
SK_BLOCK = (
    "        # ★ MyTools 修的 ok-ww bug（2026-10-01）：原来写成\n"
    "        #   ``if not self.click_resonance(): heavy_click_forte(...)``，\n"
    "        #   而 click_resonance() 返回的是**元组**（永远真值）——\n"
    "        #   于是重击成了**死代码**，守岸人永远不放重击。\n"
    "        #   改成无条件调用（heavy_click_forte 内部自己判断能量满没满），\n"
    "        #   和 ok-ww 自己的 Changli 写法一致。\n"
    "        self.click_resonance()\n"
    "        self.heavy_click_forte(check_fun=self.is_mouse_forte_full)\n"
)
SK_ALREADY = "self.heavy_click_forte(check_fun=self.is_mouse_forte_full)"

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
                    "（「心」的支持 + 守岸人重击 bug 修复）")
    parser.add_argument("--apply", action="store_true", help="真的写文件")
    args = parser.parse_args(argv[1:])

    print(f"vendor: {VENDOR}")
    print()
    results = []
    for path, needle, block, already, label in (
        (LABELS, LABELS_ANCHOR, LABELS_BLOCK, "char_xin", "Labels 常量"),
        (FACTORY, IMPORT_NEEDLE, IMPORT_BLOCK, IMPORT_ALREADY,
         "CharFactory import"),
        (FACTORY, REGISTER_NEEDLE, REGISTER_BLOCK, REGISTER_ANCHOR,
         "CharFactory 注册"),
    ):
        ok, message = _patch(path, needle, block, already=already,
                             label=label, apply=args.apply)
        print("  ", message)
        results.append(ok)

    # 守岸人那处是**替换**（原来的写法有 bug）—— 单独处理
    ok, message = _patch_replace(
        SHOREKEEPER, SK_NEEDLE, SK_BLOCK, already=SK_ALREADY,
        label="守岸人重击 bug 修复", apply=args.apply)
    print("  ", message)
    results.append(ok)

    # 另外两处是"新文件"，不靠补丁
    print()
    for path, label in (
        (VENDOR / "okww" / "char" / "Xin.py", "Xin.py 战斗逻辑"),
        (VENDOR / "ok_tasks" / "assets" / "coco_annotations.json", "识别模板"),
    ):
        mark = "✓" if path.exists() else "✗"
        print(f"   {mark} {label}: {path.relative_to(ROOT)}")
        results.append(path.exists())

    print()
    if all(results):
        print("★ 全部就位。")
        return 0
    print("★ 有缺失 —— 上面标 · 的加 --apply 安装；标 ✗ 的要看是不是上游改结构了。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
