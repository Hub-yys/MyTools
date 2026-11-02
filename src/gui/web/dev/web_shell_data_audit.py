# -*- coding: utf-8 -*-
"""★ 用户数据审计：``data/*.json`` vs 打包备份 —— 随时能跑。

## 为什么需要这个（2026-11-02）

同一天两次数据事故之后，lead 指出：

> 两次事故说明**「我们不知道哪些文件被动过」这件事本身很危险**。

所以这个脚本做一件事：**把 LIVE 和备份逐字节比对，把差异列清楚**。
以后任何"我是不是弄坏了什么"的疑问，跑一次就有答案。

## 怎么读结果

============================  ==========================================
类别                           含义
============================  ==========================================
``=`` 完全一致                 没被动过（MD5 逐字节相同）
``≠`` 内容不同                 **需要看摘要判断是"用户后来的正常改动"
                              还是"被测试改坏了"**
``+`` 只在 LIVE                新增文件（用户数据或测试产物）
``-`` 只在备份                **⚠ LIVE 缺了这个文件 —— 可能真的丢了**
============================  ==========================================

## ⚠ 判断「不一样」是正常还是事故

**不能只看 MD5 不同就惊慌。** 正常的用户数据一直在变：

* ``kuro_练度.json`` —— 用户重新登录一次就会更新（角色数可能变多**也可能变少**）
* ``loadouts.json`` / ``echo_profiles.json`` —— 用户增删配置
* ``tool_settings.json`` —— 用户改设置
* 带时间戳的字段（``updated_at`` / ``at``）每次操作都会变

### ★ 关键判据是「**文件时间**」+「条目数」

**2026-11-02 我在这上面误报过一次**：审计脚本看到
``kuro_练度.json`` 从 43 角色变成 21 角色，直接标「⚠⚠ 条目变少了」。

实际上：

```
LIVE   2026-10-14 21:03:58   21 个角色   ← 用户那天重新登录拉的
BACKUP 2026-10-09 21:12:51   43 个角色   ← 打包时的旧快照
```

**LIVE 比备份新** → 那是用户后来的正常操作，不是丢失。
「角色数变少」完全可能是用户换了号、或者库街区那次只返回了 21 个。

所以判定规则是：

=============================  ==========================================
情况                             判断
=============================  ==========================================
LIVE **比备份新**                  条目变少 = **正常**（用户后来的操作）
LIVE **比备份旧**、条目变少        **⚠⚠ 可疑 —— 可能真的丢了**
时间相同（同一次写入）              条目变少 = **⚠ 可疑**
=============================  ==========================================

**这才是能减少误报的判据。** 只看条目数会让每次正常的数据更新都报警，
报警多了就没人看了 —— 那比没有审计更糟。

## 为什么还要保留「条目数」这一维

因为**它是唯一能反映"内容少了"的量化指标**。
MD5 不同只能说明"变了"，变了可能是加也可能是减 ——
而"减"才是事故的特征。

## 用法

.. code:: powershell

    .venv\\Scripts\\python.exe src\\gui\\web\\dev\\web_shell_data_audit.py

    # 只看有问题的（不看一致的那些）
    .venv\\Scripts\\python.exe src\\gui\\web\\dev\\web_shell_data_audit.py --brief
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

#: 打包备份目录（PyInstaller onedir 布局）。
#:
#: ⚠ 相对路径写死是为了**不 import src.core**（审计脚本应该能在
#: 「代码本身有问题」的情况下也能跑）。
_BACKUP_DIRS: tuple[Path, ...] = (
    Path(_ROOT) / "build" / "stage" / "WutheringWavesTools" / "_internal" / "data",
    Path(_ROOT) / "dist" / "WutheringWavesTools" / "_internal" / "data",
)

#: 不算用户数据的文件（测试产物 / 缓存），差异不用关心
_IGNORE_PREFIX = ("_",)          #: _pages_verify.json / _web_shell_*.json
_IGNORE_NAMES = frozenset({"config.json"})   #: qfluentwidgets 自己的配置


def md5_of(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def entry_counts(path: Path) -> dict[str, int]:
    """尽力数出每个顶层 key 的"条目数"，用于判断有没有少东西。

    只数 list / dict-of-list 这种明确的集合；标量不管。
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    if not isinstance(raw, dict):
        return {"<root>": len(raw)} if isinstance(raw, list) else {}
    out: dict[str, int] = {}
    for key, value in raw.items():
        if isinstance(value, list):
            out[key] = len(value)
        elif isinstance(value, dict):
            #: dict-of-list（如 gacha 的 records: {pool: [...]}）
            lists = [v for v in value.values() if isinstance(v, list)]
            if lists:
                out[key] = sum(len(v) for v in lists)
    return out


def summarize(path: Path) -> str:
    """一行摘要（``profiles:5`` / ``roleList:21 details:21``）。"""
    counts = entry_counts(path)
    if not counts:
        return "（无集合型数据）"
    return " ".join(f"{k}:{v}" for k, v in list(counts.items())[:6])


def skipped(name: str) -> bool:
    """测试产物 / 第三方配置，不参与审计。"""
    return name.startswith(_IGNORE_PREFIX) or name in _IGNORE_NAMES


def _fmt_time(ts: float) -> str:
    """时间戳 → ``2026-10-14 21:03``（看差异用，不用秒）。"""
    import datetime

    try:
        return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    except Exception:  # noqa: BLE001
        return "?"


def main() -> int:
    brief = "--brief" in sys.argv or "-b" in sys.argv

    live_dir = Path(_ROOT) / "data"
    backup_dir = next((d for d in _BACKUP_DIRS if d.is_dir()), None)

    print("=" * 96)
    print("用户数据审计")
    print("=" * 96)
    print(f"LIVE   : {live_dir}")
    print(f"BACKUP : {backup_dir or '（没找到打包备份，只能看 LIVE）'}")
    print()

    if not live_dir.is_dir():
        print("!! data/ 目录不存在")
        return 1

    live_files = {p.name for p in live_dir.glob("*.json")
                  if p.is_file() and not skipped(p.name)}
    backup_files = ({p.name for p in backup_dir.glob("*.json")
                     if p.is_file() and not skipped(p.name)}
                    if backup_dir else set())

    same: list[str] = []
    differ: list[tuple[str, Path, Path]] = []
    only_live: list[str] = []
    only_backup: list[str] = []

    for name in sorted(live_files | backup_files):
        lp = live_dir / name
        bp = (backup_dir / name) if backup_dir else None
        if lp.is_file() and bp is not None and bp.is_file():
            (same if md5_of(lp) == md5_of(bp) else differ).append(
                name if md5_of(lp) == md5_of(bp) else (name, lp, bp))
        elif lp.is_file():
            only_live.append(name)
        elif bp is not None and bp.is_file():
            only_backup.append(name)

    # ── 一致 ──
    if not brief:
        print(f"--- 完全一致（{len(same)}）---")
        for name in same:
            print(f"  = {name}")
        print()

    # ── 不同：判据是「文件时间」+「条目数」 ──
    print(f"--- ★ 内容不同（{len(differ)}）---")
    suspicious: list[str] = []
    for name, lp, bp in differ:
        live_counts = entry_counts(lp)
        backup_counts = entry_counts(bp)
        live_sum = summarize(lp)
        backup_sum = summarize(bp)

        live_mtime = lp.stat().st_mtime
        backup_mtime = bp.stat().st_mtime

        #: 找出"条目变少了"的 key
        shrunk: list[tuple[str, int, int]] = []
        for key, backup_n in backup_counts.items():
            live_n = live_counts.get(key)
            if live_n is not None and live_n < backup_n:
                shrunk.append((key, backup_n, live_n))

        #: ★ 关键判据：LIVE 比备份**新** → 条目变少是用户的正常操作
        #: （2026-11-02 我在这上面误报过：kuro_练度 43→21，其实是
        #:  用户 10-14 自己重新登录拉的，文件比备份新 5 天）
        live_is_newer = live_mtime > backup_mtime + 60      # 留 1 分钟余量

        if shrunk and live_is_newer:
            flag = "  ✓ 正常（LIVE 比备份新，是用户后来的操作）"
        elif shrunk:
            flag = "  ⚠⚠ 条目变少了，且 LIVE 不比备份新 —— 请人工核对！"
            suspicious.append(name)
        else:
            flag = ""

        print(f"  ≠ {name}{flag}")
        print(f"      LIVE   {lp.stat().st_size:>10,} B   {live_sum}")
        print(f"      BACKUP {bp.stat().st_size:>10,} B   {backup_sum}")
        if shrunk:
            for key, b, l in shrunk:
                verdict = "正常" if live_is_newer else "**可疑**"
                print(f"      · {key}: {b} → {l}（{verdict}）")
            print(f"      时间：LIVE {_fmt_time(live_mtime)} / "
                  f"BACKUP {_fmt_time(backup_mtime)}")
    print()

    # ── 只在一边 ──
    if only_live:
        print(f"--- 只在 LIVE（新增，{len(only_live)}）---")
        for name in only_live:
            lp = live_dir / name
            print(f"  + {name:<28} {lp.stat().st_size:>10,} B   {summarize(lp)}")
        print()

    if only_backup:
        print(f"--- ⚠ 只在 BACKUP（LIVE 缺了，{len(only_backup)}）---")
        for name in only_backup:
            bp = (backup_dir / name) if backup_dir else None
            size = bp.stat().st_size if bp else 0
            print(f"  - {name:<28} {size:>10,} B   "
                  f"{summarize(bp) if bp else ''}")
        print()

    # ── 结论 ──
    print("=" * 96)
    if suspicious:
        print(f"⚠⚠ 有 {len(suspicious)} 个文件的条目**比备份少**：{suspicious}")
        print("    → 可能是事故，也可能是用户自己删的。请人工核对。")
    elif only_backup:
        print(f"⚠ 有 {len(only_backup)} 个文件在 LIVE 里不见了：{only_backup}")
    else:
        print("✓ 没有发现「条目变少」或「文件丢失」的迹象。")
        if differ:
            print(f"  （{len(differ)} 个文件内容不同，但条目数没少 —— "
                  f"正常，用户数据一直在变）")
    print("=" * 96)
    return 1 if (suspicious or only_backup) else 0


if __name__ == "__main__":
    raise SystemExit(main())
