# -*- coding: utf-8 -*-
"""打包后自检：**构建产物里到底有没有该有的东西**。

为什么需要它：2026-09-22 就在这儿翻的车 —— 界面能开、窗口正常、不报错，
但侧栏「工具（暂无）」、日志里 0 个工具。原因是插件式自动发现（pkgutil.walk_packages）
扫的是文件系统，而打包后代码在压缩归档里、磁盘上没有 .py。这类问题**一路静默**，
跑到界面上才发现太晚了。

这个脚本在 PyInstaller 之后、Inno 之前跑，直接查构建目录：
* 归档（PYZ）里有没有本项目的模块 —— 查 build 目录里的 PYZ toc；
* 解包目录里有没有该在的**数据**（资源 / 种子 / OCR 模型 / 插件源码）。

用法：python packaging/check_build.py [产物目录 build/stage/WutheringWavesTools]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = (Path(sys.argv[1]) if len(sys.argv) > 1
        else ROOT / "build" / "stage" / "WutheringWavesTools")
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
    "src.tools.game.auto_combat.okww_farm",    # 4C 刷声骸的 MyTools 子类（ok 侧按名字 import）
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
    # 工具图标（2026-09-30 起五个工具都自带图标，都要在）
    "assets/icons/echo_enhance.png",
    "assets/icons/auto_combat.png",
    "assets/icons/echo_change.png",
    "assets/icons/gacha.png",
    "assets/icons/wuwa_library_update.png",
    "data/loadouts.json",
    "src/core/data/wuwa_echo_sets.json",
    "src/core/data/wuwa_weapons.json",         # 武器图鉴（2026-09-30 新增）
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
    # ⚠⚠ 2026-10-09 实机翻车：漏了 ok_tasks → **自动战斗全部认不出角色**。
    #    FeatureSet 按**相对路径**找 ok_tasks/assets/coco_annotations.json 并合并；
    #    找不到 → 扩展特征不在特征表 → find_best_match_in_box(整张角色表) 直接
    #    raise ValueError → 任何队伍都开不了战斗（界面上一片正常，只在日志里报）。
    #
    # ⚠ 2026-10-25：「心」改用 ok-ww 官方实现后，``xin_templates.png`` 已删，
    #   这里改点名 ``echo_stack.png``（声骸堆叠图标，仍在用）。
    "vendor/okww/ok_tasks/assets/coco_annotations.json",
    "vendor/okww/ok_tasks/assets/images/echo_stack.png",
    # ⚠⚠ 2026-11-04：之前这里一条 Web 界面都没有 —— 打出来的包
    #   ``src/gui/web_shell.py`` 的 ``WEB_DIR`` 指向不存在的目录，
    #   ``web_base_url()`` 校验不到 index.html 抛异常、``create_shell()`` 捕获后
    #   **静默退回旧 Qt 界面**。用户装的正式版一直在跑老界面，全程零报错。
    "src/gui/web/index.html",
    "src/gui/web/js/app.js",
    "src/gui/web/css/base.css",
    "src/gui/web/css/glass.css",
    "src/gui/web/css/pages/pages.css",
    # ⚠⚠ 2026-11-04（用户问「这个才300MB？我壁纸不久很大了吗」时查到）：
    #   ffmpeg 没进包 → 安装版**一个壁纸都放不出来**。
    #   两条事实叠在一起：① QtWebEngine 6.11.2 不带 H.264 解码器
    #   （``canPlayType('video/mp4; codecs="avc1.640028"')`` 返回空串），
    #   而创意工坊那 7 张壁纸全是 H.264 的 mp4；② 必须先转成 VP9 webm，
    #   这件事只有 ffmpeg 能做（``core/webm_transcode.py``）。
    #   缺了它，7 张卡全显示「缺 ffmpeg」，点了没反应 —— 而且**全程不报错**。
    "tools/ffmpeg.exe",
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
check((DIST / "WutheringWavesTools.exe").is_file(), "WutheringWavesTools.exe 存在")

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
