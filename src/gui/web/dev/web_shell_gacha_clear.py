# -*- coding: utf-8 -*-
"""验证 `clearGachaHistory` 的**后端强制确认**（2026-11-02，lead 要求）。

## 为什么需要后端防护

清空抽卡历史是**不可逆**操作。前端二次确认是好习惯，但前端可以被绕过：

* 页面脚本出错 / 用户手滑
* 控制台直接 `Bridge.call('clearGachaHistory')`
* 将来别的前端接这套桥

所以后端要求 `confirm_token="DELETE"`，**不传就一个字节都不写**。

## ★★★ 本脚本用**临时文件**，绝不碰用户真实数据

    2026-11-02 事故二：第一版这个脚本**真的清空了**用户的
    ``gacha_history.json``（549 KB），而当时 ``backup_guard`` 的清单里
    没有这个文件 → 恢复不了 → 只能从打包备份找回。

    教训：验"能清空"这类**正向破坏路径**，应该用临时文件跑同一条代码路径，
    而不是动真数据。

做法：``bridge._gacha_store_path = tmpdir / "gacha_history.json"`` ——
之后所有 `getGachaHistory` / `clearGachaHistory` 都作用于临时文件。

**额外还验证**：真实用户数据在整个测试前后**逐字节不变**。

## 验什么

1. 不传 / 传空 / 传错 / 大小写不对 → `needs_confirm`，临时文件**不变**
2. 传对的 → 真清空，返回 `cleared` 条数
3. 空历史时清空 → `{ok: true, cleared: 0}`（不报错）
4. ★ **用户真实文件全程没被碰**（hash 比对）
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", "..", ".."))
sys.path.insert(0, _ROOT)
sys.path.insert(0, _HERE)
os.chdir(_ROOT)
os.environ.setdefault("QT_LOGGING_RULES", "qt.multimedia.*=false")

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])
import src.tools as tools_pkg  # noqa: E402

tools_pkg.discover_tools()

from src.core import gacha_store  # noqa: E402
from src.core.web_bridge import WebBridge  # noqa: E402

FAILS: list[str] = []


def ok(tag: str, cond: bool, note: str = "") -> None:
    print(f"[{'PASS' if cond else 'FAIL'}] {tag}  {note}")
    if not cond:
        FAILS.append(tag)


def real_hash() -> str:
    """**用户真实** gacha_history.json 的 sha256 前 16 位。"""
    try:
        path = gacha_store.GachaHistoryStore().path
        if not path.is_file():
            return "MISSING"
        return hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    except Exception:  # noqa: BLE001
        return "ERROR"


def real_count() -> int:
    """用户真实历史有几条（只读，不写）。"""
    try:
        return len(list(
            gacha_store.GachaHistoryStore().load().snapshots or []))
    except Exception:  # noqa: BLE001
        return -1


def main() -> int:
    # ══════════════════════════════════════════════════════════════
    # 0) 记下用户真实数据的状态（后面每一步都要比对）
    # ══════════════════════════════════════════════════════════════
    user_hash = real_hash()
    user_count = real_count()
    print(f"[INFO] 用户真实数据：hash={user_hash} snapshots={user_count}")
    print("[INFO] **本测试全程用临时文件，不碰它**")

    # ══════════════════════════════════════════════════════════════
    # 1) 造一个临时历史文件（3 条快照、2 个账号 —— 覆盖聚合场景）
    # ══════════════════════════════════════════════════════════════
    tmpdir = Path(tempfile.mkdtemp(prefix="gacha_test_"))
    tmp_path = tmpdir / "gacha_history.json"
    store = gacha_store.GachaHistoryStore(path=tmp_path)

    history = gacha_store.GachaHistory()
    history.snapshots = [
        gacha_store.PullSnapshot(
            player_id="111111", at="2026-10-14 21:07:33",
            total=960, five=21, added=960),
        gacha_store.PullSnapshot(
            player_id="111111", at="2026-09-02 10:00:00",
            total=800, five=18, added=800),
        gacha_store.PullSnapshot(
            player_id="222222", at="2026-10-06 20:09:03",
            total=1131, five=24, added=1131),
    ]
    store.save(history)

    fixtures = len(store.load().snapshots)
    ok("fixture_created", fixtures == 3,
       f"临时文件 {fixtures} 条快照（2 个账号）")
    ok("fixture_isolated",
       str(store.path) != str(gacha_store.GachaHistoryStore().path),
       f"临时路径 = {tmp_path.name}，和用户真实路径不同")

    tmp_bytes = tmp_path.read_bytes()

    #: ★ 让桥接层作用于临时文件
    b = WebBridge()
    b._gacha_store_path = tmp_path

    # ══════════════════════════════════════════════════════════════
    # 2) getGachaHistory 读的是临时文件
    # ══════════════════════════════════════════════════════════════
    h = json.loads(b.getGachaHistory())
    ok("get_reads_tmp", h.get("ok") is True,
       f"count={h.get('count')} snapshotCount={h.get('snapshotCount')}")
    ok("get_counts_tmp_snapshots", h.get("snapshotCount") == 3,
       f"snapshotCount={h.get('snapshotCount')}（临时文件的 3 条）")
    #: 3 条快照 → 3 组（111111 的 2026-10 / 2026-09 各一组，222222 的 2026-10 一组）
    ok("get_aggregates_by_month", h.get("count") == 3,
       f"聚合后 {h.get('count')} 组（3 条快照分属 2 个账号/2 个月 → 3 组）")
    #: 账号优先、组内月份倒序
    items = h.get("items") or []
    if items:
        #: ⚠ 账号之间的顺序是「最近月份倒序，同月按 player_id 倒序」——
        #: 这是 ``group_by_account_month`` 的**既有规则**（旧模块就是这样），
        #: 我不改它。这里只验「同一账号的月份挨在一起」这个**结构性质**。
        acct_seq: list[str] = []
        for x in items:
            if not acct_seq or acct_seq[-1] != x["playerId"]:
                acct_seq.append(x["playerId"])
        ok("get_accounts_not_interleaved",
           len(acct_seq) == len(set(acct_seq)),
           f"账号出现顺序 = {acct_seq}（同一账号不该被打断）")
        #: 同账号内月份倒序
        same_acct = [x["yearMonth"] for x in items if x["playerId"] == "111111"]
        ok("get_months_desc_in_account",
           same_acct == sorted(same_acct, reverse=True),
           f"111111 的月份 = {same_acct}（应倒序）")

    # ══════════════════════════════════════════════════════════════
    # 3) 不传令牌 → 拒绝，临时文件**一个字节都不变**
    # ══════════════════════════════════════════════════════════════
    for tag, arg in (("no_token", None),
                     ("empty_token", ""),
                     ("space_token", "   "),
                     ("wrong_token", "yes"),
                     ("case_wrong", "delete"),
                     ("partial", "DELE")):
        r = json.loads(b.clearGachaHistory() if arg is None
                       else b.clearGachaHistory(arg))
        ok(f"reject_{tag}",
           r.get("ok") is False and r.get("reason") == "needs_confirm",
           f"reason={r.get('reason')} pending={r.get('pending')}")
        ok(f"pending_{tag}", r.get("pending") == 3,
           f"pending={r.get('pending')}（应 = 3）")
        ok(f"bytes_unchanged_{tag}", tmp_path.read_bytes() == tmp_bytes,
           "临时文件一个字节都没变")

    #: message 必须说清「不可恢复」+ 怎么确认
    r = json.loads(b.clearGachaHistory())
    msg = str(r.get("message") or "")
    ok("message_warns_irreversible",
       "无法恢复" in msg or "不可恢复" in msg,
       f"message = {msg[:70]!r}")
    ok("message_tells_token", "DELETE" in msg,
       "message 里告诉怎么确认")

    # ══════════════════════════════════════════════════════════════
    # 4) ★ 传对令牌 → **临时文件**真的清空
    # ══════════════════════════════════════════════════════════════
    r = json.loads(b.clearGachaHistory("DELETE"))
    ok("confirm_clears", r.get("ok") is True,
       f"ok={r.get('ok')} cleared={r.get('cleared')}")
    ok("confirm_reports_count", r.get("cleared") == 3,
       f"cleared={r.get('cleared')}（应 = 3）")
    ok("confirm_actually_cleared", len(store.load().snapshots) == 0,
       f"临时文件清空后 = {len(store.load().snapshots)} 条")

    # ══════════════════════════════════════════════════════════════
    # 5) 已经是空的了 → 不报错
    # ══════════════════════════════════════════════════════════════
    r = json.loads(b.clearGachaHistory())
    ok("empty_history_no_confirm_needed",
       r.get("ok") is True and r.get("cleared") == 0,
       json.dumps(r, ensure_ascii=False)[:120])

    r = json.loads(b.clearGachaHistory("DELETE"))
    ok("empty_history_double_clear",
       r.get("ok") is True and r.get("cleared") == 0,
       json.dumps(r, ensure_ascii=False)[:90])

    # ══════════════════════════════════════════════════════════════
    # 6) ★★★ 用户真实数据**全程没被碰**
    # ══════════════════════════════════════════════════════════════
    ok("user_data_hash_unchanged", real_hash() == user_hash,
       f"用户 gacha_history.json hash {user_hash} → {real_hash()}")
    ok("user_data_count_unchanged", real_count() == user_count,
       f"用户 history {user_count} → {real_count()} 条")

    #: 清理临时目录
    try:
        import shutil

        shutil.rmtree(tmpdir, ignore_errors=True)
    except Exception:  # noqa: BLE001
        pass

    print()
    print("=" * 70)
    print("结果：" + ("全部通过" if not FAILS else "失败 " + str(FAILS)))
    print("=" * 70)
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
