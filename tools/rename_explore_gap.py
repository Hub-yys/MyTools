# -*- coding: utf-8 -*-
"""把 video_follow 整体改名成 explore_gap（用户要求：工具名统一叫「查缺补漏」）。

## 为什么要连**代码**一起改，而不只是改界面上的字

用户说的是工具名（``查缺补漏`` → ``查缺补漏``）。但代码里要是还叫
``video_follow``，以后看代码的人会以为这是两回事 ——
而这个项目的一贯要求是"命名跟随"。

而且**语义上本来就该叫这个**：跟着视频把缺的内容补上 = 查缺补漏。
（之前那个读官方接口的 ``explore_gap`` 已经删掉了，名字空出来了。）

## 改什么

======================================  ==========================================
旧                                       新
======================================  ==========================================
``src/core/explore_gap/``               ``src/core/explore_gap/``
``src/tools/game/explore_gap/``         ``src/tools/game/explore_gap/``
``MyToolsExploreGapTask``               ``MyToolsExploreGapTask``
``assets/icons/video_follow.png``        ``assets/icons/explore_gap.png``
``tests/*video_follow*``                 ``tests/*explore_gap*``
``ExploreGapTask`` / ``ExploreGapConfig``   ``ExploreGapTask`` / ``ExploreGapConfig``
======================================  ==========================================

⚠ **顺序很重要**：先改名字再改内容。反过来的话，替换会把新路径里的
``video_follow`` 又匹配一遍（虽然幂等，但容易看花眼）。
"""

from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding="utf-8")

#: 内容里的标识符替换（**长的先替换**，否则 ``ExploreGapTask`` 会被
#: ``Follow`` 之类的短规则先吃掉）
REPLACEMENTS = [
    # 类名 / 函数名
    ("MyToolsExploreGapTask", "MyToolsExploreGapTask"),
    ("ExploreGapTask", "ExploreGapTask"),
    ("ExploreGapConfig", "ExploreGapConfig"),
    ("ExploreGapState", "ExploreGapState"),
    ("ExploreGapTask", "ExploreGapTask"),
    ("ExploreGapPanel", "ExploreGapPanel"),
    ("ExploreGapTool", "ExploreGapTool"),
    ("VideoEntry", "VideoEntry"),                 #: 这个不用改（它指视频）
    ("exploreGap", "exploreGap"),
    # 模块路径
    ("tools.game.explore_gap", "tools.game.explore_gap"),
    ("core.explore_gap", "core.explore_gap"),
    ("game/explore_gap", "game/explore_gap"),
    ("core/explore_gap", "core/explore_gap"),
    ("explore_gap/", "explore_gap/"),
    # 界面文案
    ("查缺补漏", "查缺补漏"),
]

#: 文件名 / 目录名替换
PATH_REPLACEMENTS = [
    ("video_follow", "explore_gap"),
]


def rename_paths() -> list[str]:
    """先改**目录和文件名**（从深到浅，避免改一半路径失效）。"""
    done: list[str] = []
    #: 深路径先处理
    targets = sorted(
        [p for p in ROOT.rglob("*") if "video_follow" in p.name
         and ".git" not in p.parts and "__pycache__" not in p.parts],
        key=lambda p: len(p.parts), reverse=True)
    for path in targets:
        new_name = path.name
        for old, new in PATH_REPLACEMENTS:
            new_name = new_name.replace(old, new)
        if new_name == path.name:
            continue
        new_path = path.with_name(new_name)
        if new_path.exists():
            print(f"  ⚠ 已存在，跳过：{new_path}")
            continue
        path.rename(new_path)
        done.append(f"{path.relative_to(ROOT)} → {new_path.name}")
    return done


def rewrite_contents() -> list[str]:
    """再改**文件内容**。"""
    changed: list[str] = []
    for path in sorted(ROOT.rglob("*.py")):
        if ".git" in path.parts or "__pycache__" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        original = text
        for old, new in REPLACEMENTS:
            if old != new:
                text = text.replace(old, new)
        if text != original:
            path.write_text(text, encoding="utf-8")
            n = sum(1 for _ in re.finditer("|".join(
                re.escape(o) for o, nw in REPLACEMENTS if o != nw), original))
            changed.append(f"{path.relative_to(ROOT)}  ({n} 处)")
    return changed


def main() -> int:
    print("=" * 70)
    print("① 改目录 / 文件名")
    print("=" * 70)
    for line in rename_paths():
        print("  ", line)

    print()
    print("=" * 70)
    print("② 改文件内容")
    print("=" * 70)
    changed = rewrite_contents()
    for line in changed:
        print("  ", line)
    print(f"  共 {len(changed)} 个文件")

    print()
    print("=" * 70)
    print("③ 残留检查")
    print("=" * 70)
    leftovers = []
    for path in ROOT.rglob("*"):
        if ".git" in path.parts or "__pycache__" in path.parts:
            continue
        if "video_follow" in path.name or "FollowVideo" in path.name:
            leftovers.append(str(path.relative_to(ROOT)))
    for path in ROOT.rglob("*.py"):
        if ".git" in path.parts or "__pycache__" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for token in ("video_follow", "ExploreGapTask", "ExploreGapPanel",
                      "MyToolsExploreGapTask"):
            if token in text:
                leftovers.append(f"{path.relative_to(ROOT)} 含 {token}")
    if leftovers:
        print("  ⚠ 还有残留：")
        for item in leftovers[:40]:
            print("     ", item)
    else:
        print("  ✅ 没有残留")
    return 1 if leftovers else 0


if __name__ == "__main__":
    raise SystemExit(main())
