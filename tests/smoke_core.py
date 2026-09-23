"""核心层冒烟测试——不需要 Qt 就能跑。

    python tests/smoke_core.py

验证的是"这套骨架对不对"：工具能不能被自动发现、分类归属对不对、
元信息是否完整。界面部分用 offscreen 跑不了，交给 eyes_on 去看。
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.core.categories import ALL_CATEGORIES, ToolCategory  # noqa: E402
from src.core.registry import ToolRegistry  # noqa: E402
from src.tools import discover_tools  # noqa: E402

_results: list[tuple[bool, str]] = []


def check(condition: bool, message: str) -> bool:
    _results.append((bool(condition), message))
    print(f"  [{'PASS' if condition else 'FAIL'}] {message}")
    return bool(condition)


def main() -> int:
    print("=== MyTools 核心层冒烟测试 ===")

    imported = discover_tools()
    check(len(imported) >= 2, f"自动发现工具模块 {len(imported)} 个")

    metas = ToolRegistry.all_metas()
    check(len(metas) > 0, f"共注册 {len(metas)} 个工具")

    keys = [m.key for m in metas]
    check(len(keys) == len(set(keys)), "key 无重复")
    check(all(m.key and m.name for m in metas), "每个工具都有 key 与 name")
    check(
        all(isinstance(m.category, ToolCategory) for m in metas),
        "每个工具都归属合法分类",
    )

    print("\n--- 分类分布 ---")
    for category in ALL_CATEGORIES:
        items = ToolRegistry.by_category(category)
        names = "、".join(m.name for m in items) or "（空）"
        check(True, f"{category.display_name}（{len(items)}）：{names}")

    check(
        bool(ToolRegistry.by_category(ToolCategory.GAME)),
        "游戏分类下有工具",
    )
    # 办公分类目前是空的（占位工具已删），所以这里不强制要求有内容

    print("\n--- 实例化 ---")
    for meta in metas:
        tool = ToolRegistry.make(meta.key)
        ok = check(tool is not None, f"{meta.name}: 可实例化")
        if ok:
            check(tool.meta().key == meta.key, f"{meta.name}: meta 一致")

    failed = [msg for ok, msg in _results if not ok]
    print(f"\n=== 结果：{len(_results) - len(failed)}/{len(_results)} 通过 ===")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
