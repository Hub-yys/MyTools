# -*- coding: utf-8 -*-
"""静态检查：桥接层里**漏写 `self.`** 的调用。

## 为什么需要这个

2026-11-02 我接真引擎时把 ``_single_tool_flow`` 写成类方法却按模块级调用，
``runTask()`` **100% 崩**（``NameError``）。而 ``py_compile`` 完全抓不到 ——
语法是对的，只有真调用才炸。

lead 的原话：「建议加一个『所有 bridge 方法冒烟调用』的测试」。

这个脚本做两件事：

1. **静态扫描**：AST 找出「方法体内裸调用一个类方法名」的地方
   （= 漏了 ``self.``）
2. **冒烟调用**：每个 ``@Slot`` 方法都用合理的假参数调一次，
   抓 ``NameError`` / ``AttributeError`` / ``TypeError``

## 跑法

.. code:: powershell

    .venv\\Scripts\\python.exe src\\gui\\web\\dev\\web_shell_smoke.py
"""

from __future__ import annotations

import ast
import inspect
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", "..", ".."))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)
os.environ.setdefault("QT_LOGGING_RULES", "qt.multimedia.*=false")

TARGET = os.path.join(_ROOT, "src", "core", "web_bridge.py")

FAILS: list[str] = []


def ok(tag: str, cond: bool, note: str = "") -> None:
    print(f"[{'PASS' if cond else 'FAIL'}] {tag}  {note}")
    if not cond:
        FAILS.append(tag)


# ══════════════════════════════════════════════════════════════════════════
#  1) 静态扫描：漏 self.
# ══════════════════════════════════════════════════════════════════════════
def scan_missing_self(path: str) -> list[tuple[str, str, int]]:
    """找出「类方法内裸调用另一个类方法」的地方（即漏了 ``self.``）。"""
    tree = ast.parse(open(path, encoding="utf-8").read())

    cls_methods: set[str] = set()
    mod_funcs: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    cls_methods.add(item.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            mod_funcs.add(node.name)

    #: 模块级有同名函数 → 裸调用是合法的（Python 会找到全局那个）
    suspicious: list[tuple[str, str, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for item in node.body:
            if not isinstance(item, ast.FunctionDef):
                continue
            for sub in ast.walk(item):
                if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name):
                    name = sub.func.id
                    #: 裸调用，且这个名字既是类方法又没有同名模块函数
                    if name in cls_methods and name not in mod_funcs:
                        suspicious.append((item.name, name, sub.lineno))
    return suspicious


# ══════════════════════════════════════════════════════════════════════════
#  2) 冒烟调用：每个 Slot 都真调一次
# ══════════════════════════════════════════════════════════════════════════
#: 方法名 → 假参数列表。新加方法忘了登记会 FAIL（强制补上）。
SMOKE_ARGS: dict[str, list] = {
    "getTools": [],
    "getNav": [],
    "getAppInfo": [],
    "currentPage": [],
    "getSkin": [],
    "getSkinList": [],
    "getWallpaper": [],
    "getStatus": [],
    "getFlowList": [],
    "getConfigList": [],
    "getLibraryData": [],
    "ping": [],
    "frontendReady": [],
    "stopTask": [],
    #: 带参数的
    "switchPage": ["home"],
    "windowAction": ["minimize"],
    #: ⚠ 2026-11-04 起 **不能传空串** —— 空串是「关闭壁纸」的正经操作，
    #: 会写 ``data/wallpaper.json`` 把用户的壁纸选择清掉。
    #: 传一个不存在的 id：扫完壁纸就 ``not_found`` 早失败，不落盘。
    "setWallpaper": ["__smoke_missing__"],
    "runTask": ["__smoke_missing__"],   #: 不存在的工具 → 明确报错
    #: ★ 2026-11-04 「指定声骸强化」走的新 Slot（runTask 的带参数版）
    "runTaskWith": ["__smoke_missing__", ""],
    "runFlow": ["__smoke_missing__"],
    "setSkin": ["__smoke_missing__"],
    #: ★ 写接口 —— 用**非法**参数让它早失败，绝不真改用户数据
    "setConfig": ['{"kind":"__bad__","data":{}}'],
    "deleteConfig": ["__bad__", "__none__"],
    "saveFlow": ['{"name":"","steps":[]}'],     #: 校验不过 → invalid
    #: ★★ P4 新接口（2026-11-02）
    "getOkwwState": [],                          #: 只读，安全
    "getToolSettings": ["echo_change"],          #: 只读，安全
    "runOkwwTask": ['{"taskKey":"__no_such_task__"}'],  #: 不存在的任务 → 早失败
    "stopOkwwTask": [],                          #: 没引擎时返回 idle，安全
    "checkLibraryUpdate": [],                    #: 见 SMOKE_SKIP（会打网络）
    "applyLibraryUpdate": [],                    #: 没 check 过 → not_checked
    "setToolSettings": ['{"toolKey":"__bad__","settings":{}}'],
    #: ★ P4 第三批（2026-11-02）
    "getCharacterBuildCache": [],                #: 只读缓存文件，安全
    "getCharacterBuildDetail": ["__no_such__"],  #: 不存在的 roleId → 早失败
    "analyzeGacha": [""],                        #: 空链接 → bad_link，同步早失败
    #: ★ P4 第二批（2026-11-02）—— 扫荡
    "getNestSweepData": [],                      #: 只读清单，安全
    "setNestSweepSelection": [],                 #: ⚠ 见 SMOKE_SKIP（会写用户勾选）
    #: ★ P5 ⑤ —— 抽卡历史
    "getGachaHistory": [],                       #: 只读，安全
    "clearGachaHistory": [],                     #: ⚠ 见 SMOKE_SKIP（清用户数据）
    #: ★ P5 —— 继续 / 强化历史（2026-11-02）
    #: ⚠ 2026-11-04：「跳过」（okwwSkipEcho）已按用户要求删除，这里不再登记。
    "getEchoEnhanceHistory": [],                 #: 只读历史文件，安全
    "okwwResumeTask": [],                        #: 无引擎时返回 idle，安全
    #: ★ P6 —— 4C 历史 / 定时关机（2026-11-02）
    "getCombatHistory": [],                      #: 只读历史文件，安全
    "getShutdownTimer": [],                      #: 只读设置，安全
    "setShutdownTimer": [],                      #: ⚠ 见 SMOKE_SKIP（会写设置）
    #: ★ P7 —— 抽卡总览（欧皇卡的 6 个数字）
    "getGachaOverview": [],                      #: 只读缓存，安全
    #: ★ P9 —— 配置页「新增/编辑」弹框的角色下拉
    "getCharacterOptions": [],                   #: 只读角色清单，安全
    #: ★ P10 —— 无边框窗口的拖拽
    "startWindowDrag": [],                       #: 只发信号让系统接管拖动，安全
    #: ★ P12 —— 声骸套装（LoadoutDialog 的 4C/3C/1C）
    "getEchoSetList": [],                        #: 只读套装清单，安全
    "getEchoSetDetail": ["__no_such_set__"],     #: 不存在的名字 → not_found，安全
    #: ★ P13 —— 抽卡页逐条出金列表
    "getGachaPoolDetail": [],                    #: 只读缓存，安全
    #: ★ P14 —— 任务页「按选项新增」（2026-11-03）
    "getNewFlowOptions": [],                     #: 只读：任务类型/级别/角色清单
    "createFlowFromOptions": ['{"character":"__no_such__"}'],
    #:  ↑ 角色不存在 → bad_character 早失败，不落盘
    "deleteFlow": ["__smoke_missing__"],         #: 不存在的 id → not_found
    #: ★ P14 —— 任务页「运行报告」（2026-11-03）
    "getRunReport": [],                          #: 只读：本轮 + 累计
    "resetRunReport": [],                        #: ⚠ 见 SMOKE_SKIP（清用户累计统计）
    #: ★ P15 —— 无边框窗口最大化状态（2026-11-03）
    "getWindowState": [],                        #: 只读：问宿主 isMaximized()，安全
    #: ★ P16 —— 库街区「退出登录」（2026-11-03）
    "kuroLogout": [],                            #: ⚠ 见 SMOKE_SKIP（删登录令牌 + 练度缓存）
}

#: 冒烟时**跳过**的方法 —— 会真的打网络 / 拉引擎 / 覆盖用户数据。
#:
#: ## ★★ 分类规则（2026-11-02 数据事故的教训，写新方法时照这张表）
#:
#: ============================  ==========================================
#: 操作类型                       冒烟里怎么处理
#: ============================  ==========================================
#: 只读                           直接调（``SMOKE_ARGS`` 给空/假参数）
#: 写但幂等 / 只动自己建的数据      直接调（+ 专项测试用 ``backup_guard``）
#: 写且**会覆盖用户数据**          加入本集合 + 专项测试 + ``backup_guard``
#: 打网络 / 拉引擎                 加入本集合
#: ============================  ==========================================
#:
#: 判定"会不会覆盖用户数据"最简单的办法：**问它写不写 ``data/*.json``**。
#: 写就要跳过。
#:
#: ⚠ 跳过的项在结果里**明确列出来**，不是静默忽略 ——
#: 否则「33 个方法全部无异常」会让人误以为 35 个都测了。
SMOKE_SKIP: set[str] = {
    #: 真发 HTTP 拉库街区（几十秒）—— 冒烟不该打人家服务器
    "checkLibraryUpdate",
    #: ★ 会**覆盖用户真实的扫荡勾选**（实测本机有 10 个勾选项）。
    #: 它把 ``tool_settings.json`` 的 ``nest_sweep.selected`` 整个改写。
    "setNestSweepSelection",
    #: ★ P5 ⑤ —— 会**清空用户的抽卡历史**（``data/gacha_history.json``）
    "clearGachaHistory",
    #: ★ P6 —— 会写 ``tool_settings.json`` 的 ``auto_combat`` 键
    #: （用户的定时关机设置）。虽然只动两个字段，但那是**用户设置**。
    "setShutdownTimer",
    #: ★ P14 —— 会把 ``data/run_stats.json`` 的「所有任务累计」清零
    #: （用户的累计统计，跑了几十轮才有）。本轮报告不动，但累计是用户数据。
    "resetRunReport",
    #: ★ P16 —— 会删库街区的登录令牌文件 + ``data/kuro_练度.json`` 缓存。
    #: 等于把用户踢下线，冒烟绝对不该干这个。
    "kuroLogout",
}

#: 这些方法会真的启动引擎 / 改用户数据 —— 早期的不完整清单，
#: 保留是为了兼容；实际跳过逻辑走上面的 ``SMOKE_SKIP``。
DANGEROUS = {"runTask", "runTaskWith", "runFlow", "stopTask", "setSkin",
             "setWallpaper", "setConfig", "deleteConfig", "saveFlow"}


def main() -> int:
    # ── 静态扫描 ──────────────────────────────────────────────────
    bad = scan_missing_self(TARGET)
    ok("static_no_missing_self", not bad,
       f"发现 {bad}" if bad else "没有漏 self. 的裸调用")

    # ── 编译 ──────────────────────────────────────────────────────
    import py_compile

    try:
        py_compile.compile(TARGET, doraise=True)
        ok("compile", True, "")
    except py_compile.PyCompileError as exc:
        ok("compile", False, str(exc)[:200])
        return finish()

    # ── 冒烟调用 ──────────────────────────────────────────────────
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    import src.tools as tools_pkg

    tools_pkg.discover_tools()

    from src.core.web_bridge import WebBridge

    bridge = WebBridge()

    #: 找出所有 @Slot 方法
    slots: list[str] = []
    for name, member in inspect.getmembers(WebBridge, inspect.isfunction):
        if name.startswith("_"):
            continue
        src = inspect.getsource(member)
        if "@Slot" in src:
            slots.append(name)
    slots.sort()

    ok("found_slots", len(slots) >= 20, f"{len(slots)} 个 @Slot: {slots}")

    #: 每个 Slot 都必须在 SMOKE_ARGS 里登记
    unregistered = [s for s in slots if s not in SMOKE_ARGS]
    ok("all_slots_registered", not unregistered,
       f"未登记 = {unregistered}（新方法请在 SMOKE_ARGS 补一行）"
       if unregistered else f"{len(slots)} 个都有登记")

    #: 逐个调用（危险的用"不存在的参数"让它早失败，不真干活）
    errored: list[str] = []
    skipped: list[str] = []
    for name in slots:
        args = SMOKE_ARGS.get(name)
        if args is None:
            continue
        if name in SMOKE_SKIP:
            skipped.append(name)
            continue
        try:
            raw = getattr(bridge, name)(*args)
            #: 返回值必须能 JSON 解析（桥接层契约）
            if isinstance(raw, str) and raw:
                json.loads(raw)
        except json.JSONDecodeError as exc:
            errored.append(f"{name}: 返回的不是合法 JSON ({exc})")
        except Exception as exc:  # noqa: BLE001
            errored.append(f"{name}: {type(exc).__name__}: {exc}")

    ok("smoke_all_slots", not errored,
       "; ".join(errored) if errored
       else f"{len(slots) - len(skipped)} 个方法全部无异常"
            + (f"，跳过 {len(skipped)} 个危险方法: {skipped}" if skipped else ""))

    return finish()


def finish() -> int:
    print()
    print("=" * 64)
    print("结果：" + ("全部通过" if not FAILS else "失败 " + str(FAILS)))
    print("=" * 64)
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
