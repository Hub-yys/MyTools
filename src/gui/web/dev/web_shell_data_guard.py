# -*- coding: utf-8 -*-
"""验证 `EchoProfileStore.save()` 的护栏：拒绝把**非空文件写成空**。

## 背景（2026-11-02 事故）

用户 5 条「角色声骸强化配置」被清空。根因是 ``__init__`` 不读盘 →
``add()`` 往空列表加 → ``save()`` 整文件覆盖。

修了两层：

1. ``__init__`` 补 ``load()``（根治）
2. ``save()`` 加护栏：磁盘有数据 + 内存为空 → **拒绝写**（兜底）

这个脚本验证第 2 层真的生效。**会真的读写用户文件，但会备份恢复。**
"""

from __future__ import annotations

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
sys.path.insert(0, _HERE)
os.chdir(_ROOT)

from backup_guard import UserDataGuard  # noqa: E402

FAILS: list[str] = []


def ok(tag: str, cond: bool, note: str = "") -> None:
    print(f"[{'PASS' if cond else 'FAIL'}] {tag}  {note}")
    if not cond:
        FAILS.append(tag)


def count_profiles() -> int:
    from src.core import paths

    p = paths.user_data_dir() / "echo_profiles.json"
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        items = raw.get("profiles") if isinstance(raw, dict) else None
        return len(items) if isinstance(items, list) else -1
    except (OSError, json.JSONDecodeError):
        return -2


def main() -> int:
    guard = UserDataGuard()
    guard.start()
    try:
        return _run()
    finally:
        guard.restore()
        print(f"[INFO] 已恢复，当前 profiles = {count_profiles()}")


def _run() -> int:
    from src.core.echo_profile import EchoProfile, EchoProfileStore

    base = count_profiles()
    print(f"[INFO] 起始 profiles = {base}")
    if base <= 0:
        ok("need_data", False, "没有真实数据可测（请先确保 users 有配置）")
        return 1

    # ── 1. __init__ 会自动读盘 ──────────────────────────────────
    store = EchoProfileStore()
    ok("init_autoloads", len(store._items) == base,
       f"__init__ 后 _items = {len(store._items)}（应 = {base}）")

    # ── 2. add 不会冲掉已有的 ───────────────────────────────────
    try:
        store.add(EchoProfile(name="__guard_test"))
        after_add = count_profiles()
        ok("add_preserves_existing", after_add == base + 1,
           f"add 后 = {after_add}（应 = {base + 1}）")
        #: 清掉测试条目
        EchoProfileStore().remove("__guard_test")
        ok("remove_restores", count_profiles() == base,
           f"remove 后 = {count_profiles()}（应 = {base}）")
    except Exception as exc:  # noqa: BLE001
        ok("add_preserves_existing", False, f"{type(exc).__name__}: {exc}")

    # ── 3. ★ 护栏：内存空了但文件有数据 → 拒绝写 ────────────────
    bad = EchoProfileStore()
    bad._items = []          #: 模拟"没 load 就写"的坏状态
    bad.save()               #: 应该被拦住
    after_bad = count_profiles()
    ok("save_guard_blocks_empty_overwrite", after_bad == base,
       f"掏空后强行 save → 文件仍是 {after_bad} 条（应 = {base}，未被覆盖）")

    # ── 4. 显式 clear() 仍然可以真的清空 ────────────────────────
    #: （只验证 API 存在 + 不会崩，不真的清——最后 guard 会恢复，
    #:   但为了不让人误会，这里只断言方法存在）
    ok("has_explicit_clear", hasattr(EchoProfileStore, "clear"),
       "提供 clear() 作为显式清空入口")

    # ── 5. 文件最终完好 ────────────────────────────────────────
    ok("final_data_intact", count_profiles() == base,
       f"最终 {count_profiles()} 条（应 = {base}）")

    print()
    print("=" * 64)
    print("结果：" + ("全部通过" if not FAILS else "失败 " + str(FAILS)))
    print("=" * 64)
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
