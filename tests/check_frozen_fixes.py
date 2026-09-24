"""打包版修复验证。

① **提权清单**：WutheringWavesTools.exe 里必须嵌着 requireAdministrator（否则改了 spec 也没生效）
② **首启动播种顺序**：main.py 必须"先播种、再导入依赖数据的模块"，并且按这个顺序
   真的能把数据读进内存（模拟打包后第一次运行：用户数据目录是空的）

⚠ 为什么不用"直接启动打包版"来验：exe 现在**要求管理员**，无人值守启动会卡在
UAC 确认框上（沙箱既看不到也点不了）。所以这里拆成"清单存在性"+"等价的首启动流程"
两步来验，第三步（真机双击）留给用户。
"""

from __future__ import annotations

import ast
import pathlib
import sys
import tempfile
from pathlib import Path

#: ⚠ 别写成绝对路径。这里原来硬编码了 ``D:/AI WorkSpace/workbuddy/MyTools``，
#: 项目一改名（WorkSpace → AI Work/MyTools）整个脚本就 FileNotFoundError，
#: 而且**挂得很难看**：第 ① 步报 FAIL、第 ② 步直接崩。
#: 其余检查脚本都用 ``__file__`` 反推，跟它们保持一致。
ROOT = Path(__file__).resolve().parents[1]

#: ⚠ PyInstaller 的产物**不在 dist\ 里**。package.ps1 有意把它放到
#: build\stage\（`--distpath $StageDir`），dist\ 只留给对外产物（安装包本身），
#: 免得那堆 _internal\ 被人误发出去。这里以前指着 dist\WutheringWavesTools\，
#: 所以第 ① 步永远 FAIL「先跑 package.ps1」—— 其实包早就打好了。
EXE = ROOT / "build" / "stage" / "WutheringWavesTools" / "WutheringWavesTools.exe"

failures: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        failures.append(msg)


def check_manifest() -> None:
    print("--- ① 打包版是否带 requireAdministrator 清单 ---")
    if not EXE.exists():
        check(False, f"找不到 {EXE}（先跑 package.ps1）")
        return
    raw = EXE.read_bytes()
    size_mb = len(raw) / 1048576
    has_admin = b"requireAdministrator" in raw
    has_level = b"requestedExecutionLevel" in raw
    print(f"  体积 {size_mb:.1f} MB")
    check(has_level, "清单里有 requestedExecutionLevel")
    check(has_admin, "清单要求 requireAdministrator（双击会弹 UAC → 以管理员运行）")
    # 反证：不该同时出现 asInvoker 作为 requestedExecutionLevel 的值
    check(b'level="asInvoker"' not in raw, "没有残留 asInvoker（那等于没提权）")


def check_main_order() -> None:
    print("--- ② main.py 的导入顺序 ---")
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    main_fn = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "main"
    )
    lines = source.splitlines()

    ensure_line = None
    src_imports: list[tuple[int, str]] = []
    for node in main_fn.body:                      # 只看 main() 顶层的语句
        if isinstance(node, ast.Assign) and "ensure_user_data" in ast.unparse(node):
            ensure_line = node.lineno
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            text = lines[node.lineno - 1].strip()
            if text.startswith(("from src", "import src")):
                src_imports.append((node.lineno, text))

    check(ensure_line is not None, f"main() 里调了 ensure_user_data（第 {ensure_line} 行）")
    print(f"  src.* 导入：")
    for lineno, text in sorted(src_imports):
        flag = "← 在播种之前（只允许这一个）" if (ensure_line and lineno < ensure_line) else ""
        print(f"    L{lineno:<4} {text}  {flag}")

    allowed_before = {"from src.core import paths"}
    offenders = [
        (lineno, text) for lineno, text in src_imports
        if ensure_line and lineno < ensure_line and text not in allowed_before
    ]
    check(
        not offenders,
        f"播种之前只导入了 paths（越界的：{offenders or '无'}）",
    )
    for lineno, text in src_imports:
        if ensure_line and lineno > ensure_line:
            check(True, f"L{lineno} {text} 在播种之后 ✔")


def check_first_run_simulation() -> None:
    """模拟打包后第一次运行：用户数据目录为空 → 先播种 → 再导入数据模块。"""
    print("--- ③ 等价的首启动流程（空用户数据目录）---")

    from src.core import paths

    tmp = tempfile.TemporaryDirectory()
    base = Path(tmp.name)
    try:
        # 伪装成"打包版"：用户数据目录指向一个空目录
        paths.is_frozen = lambda: True
        paths.user_data_dir = lambda: base
        paths.game_data_dir = lambda: base / "game_data"
        paths.log_file = lambda: base / "mytools.log"

        seeded = paths.ensure_user_data()
        check(len(seeded) >= 8, f"播种了 {len(seeded)} 个文件（应含 4 个图鉴 JSON + 配置种子）")
        check((base / "game_data" / "wuwa_echo_sets.json").exists(), "图鉴 JSON 已落到用户目录")

        # 关键：**播种之后**才导入（main.py 就是这么排的）
        from src.core import game_data

        game_data.reload_data()          # 换到临时目录后重读，模拟"这个进程第一次读"
        characters = len(game_data.CHARACTERS)
        sets = len(game_data.ECHO_SETS)
        echoes = sum(len(v) for v in game_data.ECHOES_BY_COST.values())
        print(f"  角色 {characters} / 套装 {sets} / 声骸 {echoes}")
        check(characters > 0 and sets > 0, "首次运行内存里就有数据（不再是空白资源库）")
        check(characters == 58 and sets == 34, f"数量和开发态一致（58/34，实际 {characters}/{sets}）")
    finally:
        # 收拾现场：把 paths 的伪装撤掉，数据换回真实目录
        import importlib

        importlib.reload(paths)
        from src.core import game_data as gd

        gd.DATA_ROOT = gd.paths.game_data_dir()
        gd.reload_data()
        tmp.cleanup()
    print(f"  还原后：角色 {len(gd.CHARACTERS)} / 套装 {len(gd.ECHO_SETS)}")


def main() -> int:
    check_manifest()
    check_main_order()
    check_first_run_simulation()
    print(f"\n=== 结果：{'全部通过' if not failures else f'{len(failures)} 项失败'} ===")
    for item in failures:
        print(f"  - {item}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
