# -*- coding: utf-8 -*-
"""打包后自检：**构建产物里到底有没有该有的东西**。

为什么需要它：2026-09-22 就在这儿翻的车 —— 界面能开、窗口正常、不报错，
但侧栏「工具（暂无）」、日志里 0 个工具。原因是插件式自动发现（pkgutil.walk_packages）
扫的是文件系统，而打包后代码在压缩归档里、磁盘上没有 .py。这类问题**一路静默**，
跑到界面上才发现太晚了。

这个脚本在 PyInstaller 之后、Inno 之前跑，直接查构建目录：
* 归档（PYZ）里有没有本项目的模块 —— 查 build 目录里的 PYZ toc；
* 解包目录里有没有该在的**数据**（资源 / 种子 / OCR 模型 / 插件源码）。

用法：python packaging/check_build.py [产物目录 dist/MyTools]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "dist" / "MyTools"
INTERNAL = DIST / "_internal"

#: 归档里必须存在的本项目模块（插件式发现的模块尤其要列上 —— 它们最容易漏）
REQUIRED_IN_ARCHIVE = [
    "src.core.registry",
    "src.core.wuwa_update",              # 只被插件模块 import，最典型的漏网之鱼
    "src.core.game_data",
    "src.tools.game.echo_enhance.tool",
    "src.tools.game.echo_enhance.runner",
    "src.tools.data.wuwa_library_update",
    "src.tools.game.auto_combat.tool",
    "src.tools.game.auto_combat.okww_boot",    # 4C 自动战斗宿主
    "src.tools.game.echo_enhance.okww_task",   # 声骸强化的 MyTools 子类（ok 侧按名字 import）
    "src.tools.game.auto_combat.okww_boot",    # ok-ww 引擎宿主
    "ok.core.start_controller",          # ok-script（ok-ww 引擎宿主依赖）
    "ok.task.TaskExecutor",
    "okww.task.FarmEchoTask",            # vendored ok-ww（AGPL-3.0）
    "okww.task.EnhanceEchoTask",         # 声骸强化流程本体（MyTools 子类的基类）
    "okww.task.AutoCombatTask",
    "okww.task.BaseCombatTask",
]

#: 解包目录里必须存在的数据（相对 _internal）
REQUIRED_DATA = [
    "assets/game/avatars",
    "assets/icons/echo_enhance.png",
    "assets/icons/auto_combat.png",
    "data/loadouts.json",
    "src/core/data/wuwa_echo_sets.json",
    "src/tools/game/echo_enhance/tool.py",     # 给 walk_packages 扫的源码副本
    "src/tools/game/auto_combat/tool.py",
    "onnxocr/models/ppocrv5/det/det.onnx",
    "onnxocr/models/ppocrv5/rec/rec.onnx",
    "onnxocr/models/ppocrv5/ppocrv5_dict.txt",
    "vendor/okww/assets/coco_annotations.json",  # ok-ww 模板框架
    "vendor/okww/assets/echo_model/echo.onnx",
    "vendor/okww/config.py",                     # 宿主 importlib 按路径加载
    "vendor/okww/okww/task/FarmEchoTask.py",
    "vendor/okww/i18n/zh_CN/LC_MESSAGES/ok.mo",
]

FAILURES: list[str] = []


def check(cond: bool, msg: str) -> None:
    print("  [%s] %s" % ("PASS" if cond else "FAIL", msg))
    if not cond:
        FAILURES.append(msg)


def read_pyz_modules() -> set[str]:
    """从构建目录的 PYZ toc 里读出归档包含的模块名。"""
    tocs = sorted((ROOT / "build").glob("**/PYZ-00.toc"))
    names: set[str] = set()
    for toc in tocs:
        text = toc.read_text(encoding="utf-8", errors="replace")
        names |= set(re.findall(r"'([\w.]+)'", text))
    return names


print("=" * 68)
print("打包自检：%s" % DIST)
print("=" * 68)

check(DIST.is_dir(), "产物目录存在")
check((DIST / "MyTools.exe").is_file(), "MyTools.exe 存在")

print("-- 归档里的本项目模块 --")
modules = read_pyz_modules()
check(bool(modules), "读到了 PYZ 清单（%d 个名字）" % len(modules))
for name in REQUIRED_IN_ARCHIVE:
    check(name in modules, "归档含 %s" % name)

print("-- 解包目录里的数据 --")
for rel in REQUIRED_DATA:
    check((INTERNAL / rel).exists(), "存在 %s" % rel)

print("-- 插件目录（walk_packages 要扫得到）--")
plugin_pys = list((INTERNAL / "src" / "tools").rglob("*.py"))
check(len(plugin_pys) >= 5, "src/tools 下有 %d 个 .py（要 >=5）" % len(plugin_pys))

# 不该带的东西
leftovers = [p.name for p in INTERNAL.glob("*") if p.name in ("__pycache__", ".git")]
check(not leftovers, "没有夹带源码仓库垃圾（%s）" % leftovers)

print()
if FAILURES:
    print("自检不通过，共 %d 项：" % len(FAILURES))
    for item in FAILURES:
        print("  ✗ %s" % item)
    sys.exit(1)
print("自检通过：归档模块与数据都齐")
