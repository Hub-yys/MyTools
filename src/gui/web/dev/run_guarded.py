"""★ **外部恢复包装器** —— 跑会写用户数据的测试脚本，无论成败都恢复。

## 为什么需要它（2026-11-02 的教训）

我两次因为测试脚本写坏 / 残留用户数据：

* 第一次：用真实 `loadouts.json` 验证「读写对称」，把 `echoSet` 写空了
* 第二次：测试脚本用 ``os._exit(0)`` 提前退出，``finally`` 被跳过，
  ``UserDataGuard.restore()`` 没执行 → 数据里多了条测试配置

``try/finally`` **不可靠**：``finally`` 里有异常、进程被 kill、``os._exit``，
``restore()`` 都不会执行。

## 这个包装器怎么保证

.. code:: text

   父进程（本脚本）
     ├─ ① 备份 data/*.json 到临时目录
     ├─ ② 用 subprocess 跑测试脚本（子进程）
     └─ ③ **子进程结束后必定恢复**（不管退出码 / 崩溃 / 被 kill）

**恢复发生在父进程** —— 子进程怎么死都不影响父进程执行 ③。
（除非父进程自己被 kill，但那已经超出任何应用层方案的能力。）

## 用法

.. code:: powershell

   # 跑测试，自动恢复用户数据
   .venv\\Scripts\\python.exe src\\gui\\web\\dev\\run_guarded.py src\\gui\\web\\dev\\web_shell_p12.py

   # 透传参数
   .venv\\Scripts\\python.exe src\\gui\\web\\dev\\run_guarded.py my_test.py --only foo

   # 不恢复（调试用，慎用）
   .venv\\Scripts\\python.exe src\\gui\\web\\dev\\run_guarded.py --no-restore my_test.py

退出码 = 子进程的退出码（恢复失败时返回 1 并明确报出来）。
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

#: 仓库根（``src/gui/web/dev/`` 往上三层是 ``MyTools/``）
ROOT = Path(__file__).resolve().parents[4]


def _user_data_dir() -> Path:
    sys.path.insert(0, str(ROOT))
    from src.core import paths  # noqa: PLC0415

    return Path(paths.user_data_dir())


def _snapshot_files(root: Path) -> list[Path]:
    """``data/*.json`` —— 全部可能被测试改到的文件。

    ⚠ 不维护白名单：白名单漏一项就是一次数据丢失
    （``backup_guard`` 的注释里也写着这一点）。
    """
    if not root.is_dir():
        return []
    return sorted(root.glob("*.json"))


def _file_entries(path: Path) -> int:
    """粗略数一下「条目数」，用于恢复后自检。"""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return -1
    if isinstance(raw, dict):
        lists = [v for v in raw.values() if isinstance(v, list)]
        return len(lists[0]) if lists else len(raw)
    if isinstance(raw, list):
        return len(raw)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="外部恢复包装器：跑测试，无论成败都恢复用户数据")
    parser.add_argument("script", nargs="?", help="要跑的测试脚本")
    parser.add_argument("script_args", nargs=argparse.REMAINDER,
                        help="透传给脚本的参数")
    parser.add_argument("--no-restore", action="store_true",
                        help="不恢复（调试用；数据可能被测试改掉）")
    args = parser.parse_args(argv)

    if not args.script:
        parser.print_help()
        return 2

    script = Path(args.script)
    if not script.is_absolute():
        script = (Path.cwd() / script).resolve()
    if not script.is_file():
        print(f"[guard] 测试脚本不存在：{script}", file=sys.stderr)
        return 2

    data_dir = _user_data_dir()
    files = _snapshot_files(data_dir)
    if not files:
        print(f"[guard] ⚠ 没找到任何 data/*.json（{data_dir}）—— 直接跑，不备份",
              file=sys.stderr)
        return subprocess.call([sys.executable, str(script), *args.script_args])

    backup_dir = Path(tempfile.mkdtemp(prefix="mytools_guard_"))
    before: dict[str, int] = {}
    for src in files:
        try:
            shutil.copy2(src, backup_dir / src.name)
            before[src.name] = _file_entries(src)
        except OSError as exc:
            print(f"[guard] ⚠ 备份失败 {src.name}：{exc}", file=sys.stderr)

    print(f"[guard] 已备份 {len(before)} 个数据文件（{data_dir.name}/*.json）")
    started = time.time()
    code = 1
    try:
        #: ★ 子进程**继承 stdio**，输出直接给用户看
        code = subprocess.call(
            [sys.executable, str(script), *args.script_args])
    except KeyboardInterrupt:
        print("\n[guard] 测试被中断", file=sys.stderr)
        code = 130
    finally:
        elapsed = time.time() - started
        print(f"[guard] 测试结束（退出码 {code}，{elapsed:.1f}s）")
        if args.no_restore:
            print(f"[guard] ⚠ --no-restore：数据**未恢复**，备份在 {backup_dir}")
            return code
        # ══════════════════════════════════════════════════════════════
        #  ★ 恢复在这里 —— **父进程**执行，子进程怎么死都到得了
        # ══════════════════════════════════════════════════════════════
        restored = 0
        failed: list[str] = []
        for name in before:
            src = backup_dir / name
            dst = data_dir / name
            try:
                shutil.copy2(src, dst)
                restored += 1
            except OSError as exc:
                failed.append(f"{name}: {exc}")
        #: 测试期间**新建**的 data/*.json 要删掉（恢复原状）
        removed = 0
        for path in _snapshot_files(data_dir):
            if path.name in before:
                continue
            try:
                path.unlink()
                removed += 1
            except OSError as exc:
                failed.append(f"删除 {path.name}: {exc}")

        #: 自检：条目数要和备份时一致
        mismatched: list[str] = []
        for name, count in before.items():
            now = _file_entries(data_dir / name)
            if count >= 0 and now != count:
                mismatched.append(f"{name}: 备份时 {count} → 现在 {now}")

        print(f"[guard] 已恢复 {restored} 个文件"
              + (f"，删掉 {removed} 个测试新建文件" if removed else ""))
        if failed:
            print("[guard] 🔴 恢复失败：", file=sys.stderr)
            for item in failed:
                print(f"        {item}", file=sys.stderr)
            print(f"[guard] 备份仍保留：{backup_dir}", file=sys.stderr)
            return 1
        if mismatched:
            print("[guard] 🔴 恢复后条目数对不上：", file=sys.stderr)
            for item in mismatched:
                print(f"        {item}", file=sys.stderr)
            print(f"[guard] 备份仍保留：{backup_dir}", file=sys.stderr)
            return 1
        shutil.rmtree(backup_dir, ignore_errors=True)
        print("[guard] 数据自检通过（条目数一致）")
    return code


if __name__ == "__main__":
    sys.exit(main())
