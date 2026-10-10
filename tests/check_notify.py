# -*- coding: utf-8 -*-
r"""消息通知：端到端功能验证（存储规则 / 页面 / 各来源接入）。

    .\.venv\Scripts\python.exe tests\check_notify.py
"""
from __future__ import annotations

import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append((name, bool(ok), detail))


def main() -> int:
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])

    from src.core import notifications as N
    from src.core import notify

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="notify-"))
    store = N.NotificationStore(tmp / "notifications.json")
    notify.set_store(store)

    # ── ① 存储规则 ────────────────────────────────────────────────
    print("① 存储规则（最多 10 条 / 每天清理 / 可手动清）")
    for i in range(1, 13):
        store.add(f"消息{i}", f"正文{i}")
    check("最多只留 10 条", len(store) == N.MAX_ITEMS, f"{len(store)} 条")
    check("新的在最前", store.items()[0].title == "消息12", store.items()[0].title)
    check("旧的被挤掉", "消息1" not in [n.title for n in store.items()])

    #: 跨天清理
    import json

    raw = json.loads((tmp / "notifications.json").read_text(encoding="utf-8"))
    raw["items"].insert(0, {"title": "昨天的", "body": "", "level": "info",
                            "stamp": "2020-01-01 08:00:00", "uid": "ancient"})
    (tmp / "notifications.json").write_text(
        json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    fresh = N.NotificationStore(tmp / "notifications.json")
    check("跨天的被自动清掉",
          "昨天的" not in [n.title for n in fresh.items()])

    #: 手动清理
    fresh.clear()
    check("手动清空生效", len(fresh) == 0 and not fresh.items())

    # ── ② 未读数 ──────────────────────────────────────────────────
    print()
    print("② 未读数（侧栏角标）")
    store2 = N.NotificationStore(tmp / "n2.json")
    notify.set_store(store2)
    check("空的时候未读 0", store2.unread_count() == 0)
    store2.add("甲")
    store2.add("乙")
    check("两条都未读", store2.unread_count() == 2, f"{store2.unread_count()}")
    store2.mark_all_read()
    check("标已读后归零", store2.unread_count() == 0)
    store2.add("丙")
    check("新增一条 → 未读 1（不是 3）", store2.unread_count() == 1,
          f"{store2.unread_count()}（下标法会算成 3）")
    store2.clear()
    check("清空后未读归零（不留假角标）", store2.unread_count() == 0)

    # ── ③ notify 模块 ─────────────────────────────────────────────
    print()
    print("③ 统一入口 notify")
    store3 = N.NotificationStore(tmp / "n3.json")
    notify.set_store(store3)
    n = notify.report_task_result("声骸自动强化", ok=True, detail="符合条件 3")
    check("成功 → 标题带「完成」", n is not None and "完成" in n.title, n.title if n else "")
    check("成功 → 级别是 success", n.level == N.LEVEL_SUCCESS, n.level)
    n2 = notify.report_task_result("声骸批量调频", ok=False, detail="找不到 强化并调谐")
    check("失败 → 标题带「失败」", "失败" in n2.title, n2.title)
    check("失败 → 级别是 error", n2.level == N.LEVEL_ERROR, n2.level)

    # ── ④ 宿主接入（工具跑完记消息）────────────────────────────────
    print()
    print("④ 工具任务结束 → 记消息（宿主 poll_done）")
    store4 = N.NotificationStore(tmp / "n4.json")
    notify.set_store(store4)

    from src.tools.game.auto_combat import okww_boot as OB

    class FakeTask:
        def __init__(self, info):
            self.info = info
            self.running = False
            self.enabled = False

    class FakeOK:
        pass

    host = OB.OkwwHost()
    host._ok = FakeOK()          #: 绕过引擎，只测记录这一段
    host._running_task = "声骸自动强化"
    task = FakeTask({"成功声骸数量": 3, "失败声骸数量": 39})
    host.find_task = lambda key: task      # type: ignore[method-assign]
    host.poll_done()
    check("成功的工具任务记了一条", len(store4) == 1, f"{len(store4)} 条")
    if len(store4):
        got = store4.items()[0]
        check("标题是「声骸自动强化 · 完成」",
              got.title == "声骸自动强化 · 完成", got.title)
        check("正文带统计", "符合条件 3" in got.body and "弃置 39" in got.body,
              got.body)

    #: 失败：ok-script 会写 info["Error"]
    store4.clear()
    host._running_task = "声骸批量调频"
    host.find_task = lambda key: FakeTask({"Error": "找不到 强化并调谐"})  # type: ignore[method-assign]
    host.poll_done()
    check("失败的工具有 error 级消息",
          len(store4) == 1 and store4.items()[0].level == N.LEVEL_ERROR,
          store4.items()[0].title if len(store4) else "（没有）")
    if len(store4):
        check("失败标题带「失败」", "失败" in store4.items()[0].title,
              store4.items()[0].title)
        check("失败正文带原因", "找不到" in store4.items()[0].body,
              store4.items()[0].body)

    #: 中文失败原因（我们自己的任务）
    store4.clear()
    host._running_task = "声骸自动强化"
    host.find_task = lambda key: FakeTask({"失败原因": "强化设置需要开启阶段放入!"})  # type: ignore[method-assign]
    host.poll_done()
    check("认得出中文的「失败原因」",
          len(store4) == 1 and "失败" in store4.items()[0].title,
          store4.items()[0].title if len(store4) else "（没有）")

    #: 自动暂停：既非成功也非失败
    store4.clear()
    host._running_task = "声骸自动强化"
    host.find_task = lambda key: FakeTask({                     # type: ignore[method-assign]
        "已自动停止": True, "自动停止原因": "出现符合条件的声骸（第 2 个）",
        "成功声骸数量": 2})
    host.poll_done()
    check("自动暂停单独成一类（不记成失败）",
          len(store4) == 1 and "自动暂停" in store4.items()[0].title,
          store4.items()[0].title if len(store4) else "（没有）")
    if len(store4):
        check("自动暂停级别是 info（不是 error）",
              store4.items()[0].level == N.LEVEL_INFO,
              store4.items()[0].level)

    #: 同一轮不能重复记（poll_done 每 300ms 调一次）
    n_before = len(store4)
    host.poll_done()
    check("同一次结束不会重复记", len(store4) == n_before,
          f"{n_before} → {len(store4)}")

    # ── ⑤ 页面 ────────────────────────────────────────────────────
    print()
    print("⑤ 消息页面")
    store5 = N.NotificationStore(tmp / "n5.json")
    from src.gui.notify_page import NoticeInterface, NoticeCard

    page = NoticeInterface(store=store5)
    check("空的时候显示空态", page.empty.isVisible() or not page.list_host.isVisible())
    check("空的时候「清空」是灰的", not page.clear_button.isEnabled())

    page.note("声骸自动强化 · 完成", "符合条件 3", level=N.LEVEL_SUCCESS)
    page.note("声骸批量调频 · 失败", "找不到 强化并调谐", level=N.LEVEL_ERROR)
    app.processEvents()
    cards = page.findChildren(NoticeCard)
    check("画出了 2 张卡片", len(cards) == 2, f"{len(cards)} 张")
    check("有内容时列表可见", page.list_host.isVisible() or not page.empty.isVisible())
    check("按钮文字带条数", "2" in page.clear_button.text(),
          page.clear_button.text())
    check("未读数是 2", page.unread_count() == 2, f"{page.unread_count()}")

    texts = " ".join(w.text() for c in cards
                     for w in c.findChildren(type(page.title)) if w.text())
    check("卡片里有标题", "声骸自动强化" in texts and "声骸批量调频" in texts,
          texts[:80])
    check("卡片里有正文", "符合条件 3" in texts and "找不到" in texts)
    check("卡片里有级别标记", "✔" in texts and "✖" in texts)

    page.mark_read()
    check("标已读后未读归零", page.unread_count() == 0)

    #: 清空（绕过确认框，直接调 store，界面刷新走 refresh）
    store5.clear()
    page.refresh()
    app.processEvents()
    check("清空后没有卡片了", not page.findChildren(NoticeCard))
    check("清空后按钮变灰", not page.clear_button.isEnabled())

    print()
    bad = [c for c in CHECKS if not c[1]]
    for name, ok, det in CHECKS:
        print("  [%s] %s%s" % ("PASS" if ok else "FAIL", name,
                               ("   " + det) if det else ""))
    print()
    print("共 %d 项，%d 项失败" % (len(CHECKS), len(bad)))
    print("★", "全部通过" if not bad else "⚠ 见上面的 FAIL")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
