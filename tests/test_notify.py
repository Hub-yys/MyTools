# -*- coding: utf-8 -*-
"""侧栏「消息通知」的单元测试。

用户 2026-10-10 的要求::

    "左侧边栏增加消息通知功能，用来储存最近发的通知，最多储存10条，
     每天自动清理，也可手动清理，每个任务完成/失败都要进行通知，
     声骸批量调频、声骸自动强化等工具完成/失败时也要通知"

逐条对应：

* 最多 10 条          → :class:`TestStoreRules`
* 每天自动清理        → :class:`TestStoreRules.test_prunes_other_days`
* 手动清理            → :class:`TestStoreRules.test_clear`
* 侧栏 + 未读角标      → :class:`TestSidebarBadge`
* 任务流程完成/失败    → :class:`TestTaskFlowNotice`
* 工具（调频/强化）完成/失败 → :class:`TestToolTaskNotice`

    .\\.venv\\Scripts\\python.exe -m unittest tests.test_notify
"""

from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.core import notifications as N  # noqa: E402
from src.core import notify  # noqa: E402


class _TempStore(unittest.TestCase):
    """给每个测试一个**独立**的临时存储（别碰用户真实的消息历史）。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = pathlib.Path(self.tmp.name) / "notifications.json"

    def store(self) -> N.NotificationStore:
        return N.NotificationStore(self.path)


class TestStoreRules(_TempStore):
    """★ 用户明说的三条存储规则。"""

    def test_keeps_at_most_ten(self):
        """★★ 最多 10 条 —— 超了丢**最旧的**（新的永远进得来）。"""
        s = self.store()
        for i in range(1, 16):
            s.add(f"消息{i}")
        self.assertEqual(len(s.items()), N.MAX_ITEMS)
        titles = [n.title for n in s.items()]
        self.assertEqual(titles[0], "消息15", "最新的应该在第一条")
        self.assertNotIn("消息1", titles, "最旧的应该被挤掉")
        self.assertIn("消息6", titles, "应保留最近 10 条（6..15）")

    def test_newest_first(self):
        s = self.store()
        for i in (1, 2, 3):
            s.add(f"第{i}条")
        self.assertEqual([n.title for n in s.items()],
                         ["第3条", "第2条", "第1条"])

    def test_prunes_other_days(self):
        """★★ 每天自动清理：**只留当天的**。

        ⚠ 判据是"日期不同"而不是"超过 24 小时"（见模块文档）——
        所以这里塞一条**很旧**的和一条**昨天**的，两条都该没。
        """
        from datetime import date, timedelta

        yesterday = (date.today() - timedelta(days=1)).isoformat()
        s = self.store()
        s.add("今天的")
        #: 直接往盘上塞旧数据（模拟"昨天用过，今天再打开"）
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        raw["items"].extend([
            {"title": "昨天的", "body": "", "level": "info",
             "stamp": f"{yesterday} 23:50:00", "uid": "y1"},
            {"title": "很久以前的", "body": "", "level": "info",
             "stamp": "2020-01-01 08:00:00", "uid": "old1"},
        ])
        self.path.write_text(json.dumps(raw, ensure_ascii=False),
                             encoding="utf-8")

        fresh = self.store()          #: 重新读 = 模拟程序再次打开
        titles = [n.title for n in fresh.items()]
        self.assertIn("今天的", titles)
        self.assertNotIn("昨天的", titles, "昨天的没被自动清理")
        self.assertNotIn("很久以前的", titles)

    def test_prune_runs_on_every_add(self):
        """★★ 加新消息时也要清 —— 否则昨天的会占着那 10 个名额。

        ⚠⚠ 这条**必须让"昨天的数据"在 ``load()`` 之后才出现**，
        否则测不出 ``add`` 里那次清理：``load`` 自己就会清一遍，
        于是"重新读盘 → add"这条路上，add 清不清结果都一样
        （护栏验证时发现我第一版就是这么写的 —— **假绿**）。

        真实场景是：程序**开着**的时候跨了天（昨晚 23:59 跑到今早 00:01），
        内存里还留着昨天的条目，这时来一条新消息。
        这里就直接操作内存里的 ``_items`` 来模拟那一刻。
        """
        from datetime import date, timedelta

        yesterday = (date.today() - timedelta(days=1)).isoformat()
        s = self.store()
        s.add("今天早些时候的")

        #: ★ 手动把内存里的条目改成"昨天的"（= 跨天那一刻的真实状态）
        for item in s._items:                       # noqa: SLF001 - 就是为了造这个场景
            item.stamp = f"{yesterday} 23:59:00"
        self.assertTrue(any(n.day == yesterday for n in s._items),
                        "前提没造出来：内存里应该有昨天的条目")

        s.add("今天的新消息")                        #: ← 跨天后的第一条

        #: ⚠⚠ **第一件事就读 ``unread_count()``**，别先调 ``items()`` ——
        #: ``items()`` 自己会 ``_prune``，一旦先调它，后面再断言就晚了
        #: （护栏验证抓到过两次：第一次我用了 items、第二次虽然加了这条
        #:   但排在 items 后面，都让"add 不清理"蒙混过关）。
        #:
        #: ``unread_count()`` **不** prune，反映的是 add 之后的**真实**状态；
        #: 侧栏角标读的就是它 —— add 不清理的话角标会显示 2（含昨天的）。
        self.assertEqual(s.unread_count(), 1,
                         "add() 之后立即读未读数，昨天的还占着 —— "
                         "侧栏角标会虚高")

        days = {n.day for n in s.items()}
        self.assertEqual(days, {date.today().isoformat()},
                         f"新消息进来后，昨天的还占着名额：{days}")
        self.assertEqual([n.title for n in s.items()], ["今天的新消息"])

    def test_clear(self):
        s = self.store()
        s.add("甲")
        s.add("乙")
        n = s.clear()
        self.assertEqual(n, 2)
        self.assertEqual(s.items(), [])

    def test_clear_persists(self):
        s = self.store()
        s.add("甲")
        s.clear()
        self.assertEqual(self.store().items(), [], "清空没落盘")

    def test_remove_one(self):
        s = self.store()
        a = s.add("甲")
        s.add("乙")
        self.assertTrue(s.remove(a.uid))
        self.assertEqual([n.title for n in s.items()], ["乙"])
        self.assertFalse(s.remove("不存在的 id"))

    def test_survives_corrupt_file(self):
        """★ 文件坏了当作空的 —— 绝不能让消息历史把程序搞崩。"""
        self.path.write_text("{这不是 json", encoding="utf-8")
        s = self.store()
        self.assertEqual(s.items(), [])
        s.add("还能用")
        self.assertEqual(len(s.items()), 1)

    def test_skips_bad_entries(self):
        """★ 坏条目丢掉，**不连累**好条目。"""
        s = self.store()
        s.add("好的")
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        raw["items"].insert(0, "这不是个字典")
        raw["items"].insert(1, {"title": ""})          #: 没标题
        raw["items"].insert(2, {"body": "没标题也没用"})
        self.path.write_text(json.dumps(raw, ensure_ascii=False),
                             encoding="utf-8")
        titles = [n.title for n in self.store().items()]
        self.assertIn("好的", titles)
        self.assertEqual(len(titles), 1, f"坏条目没被丢掉：{titles}")

    def test_level_falls_back_to_info(self):
        """★ 认不出的级别退回 info（别让界面拿到一个画不出来的级别）。"""
        s = self.store()
        s.add("级别乱写", level="天知道")
        self.assertEqual(s.items()[0].level, N.LEVEL_INFO)


class TestUnread(_TempStore):
    """★ 未读数（侧栏角标的数据源）。"""

    def test_empty_is_zero(self):
        self.assertEqual(self.store().unread_count(), 0)

    def test_all_unread_at_first(self):
        s = self.store()
        s.add("甲")
        s.add("乙")
        self.assertEqual(s.unread_count(), 2)

    def test_mark_all_read(self):
        s = self.store()
        s.add("甲")
        s.mark_all_read()
        self.assertEqual(s.unread_count(), 0)

    def test_only_new_ones_are_unread(self):
        """★★ 标已读后**新增的**才算未读 —— 这条是"下标法"会算错的场景。

        用下标记"读到第几条"的话，新消息插到头部会让所有下标后移，
        于是"已读 2 条"变成"还有 2 条未读"（假未读）。
        """
        s = self.store()
        s.add("老的1")
        s.add("老的2")
        s.mark_all_read()
        s.add("新的")
        self.assertEqual(s.unread_count(), 1,
                         "只有新增那 1 条该算未读")

    def test_clear_resets_unread(self):
        """★ 手动清空后不留假角标（否则侧栏顶着"3 条未读"却一条都点不出来）。"""
        s = self.store()
        s.add("甲")
        s.add("乙")
        s.clear()
        self.assertEqual(s.unread_count(), 0)

    def test_unread_survives_reload(self):
        s = self.store()
        s.add("甲")
        s.mark_all_read()
        s.add("乙")
        self.assertEqual(self.store().unread_count(), 1,
                         "未读状态没落盘")


class TestNotifyEntry(_TempStore):
    """★ 统一入口：标题/级别**不收散在各调用点**。"""

    def setUp(self):
        super().setUp()
        self._orig = notify.store()
        notify.set_store(self.store())
        self.addCleanup(lambda: notify.set_store(self._orig))

    def test_success_and_failure_levels(self):
        good = notify.report_task_result("声骸自动强化", ok=True)
        bad = notify.report_task_result("声骸批量调频", ok=False)
        self.assertEqual(good.level, N.LEVEL_SUCCESS)
        self.assertEqual(bad.level, N.LEVEL_ERROR)

    def test_titles_are_uniform(self):
        """★ 标题格式统一 —— 用户在列表里扫一眼就知道哪个工具什么结局。"""
        notify.report_task_result("声骸自动强化", ok=True)
        notify.report_task_result("声骸批量调频", ok=False)
        titles = [n.title for n in notify.store().items()]
        self.assertIn("声骸自动强化 · 完成", titles)
        self.assertIn("声骸批量调频 · 失败", titles)

    def test_detail_is_kept(self):
        notify.report_task_result("X", ok=True, detail="符合条件 3 · 弃置 39")
        self.assertIn("符合条件 3", notify.store().items()[0].body)

    def test_blank_name_falls_back(self):
        n = notify.report_task_result("", ok=True)
        self.assertTrue(n.title.startswith("任务"))

    def test_never_raises(self):
        """★★ 记不上消息**绝不能**把任务搞崩（这是它唯一的兜底职责）。"""
        class Boom(N.NotificationStore):
            def add(self, *a, **kw):
                raise RuntimeError("磁盘满了")

        notify.set_store(Boom(self.path))
        self.assertIsNone(notify.report("随便"))
        self.assertIsNone(notify.report_task_result("X", ok=False))


class TestToolTaskNotice(_TempStore):
    """★★ 工具任务（声骸批量调频 / 声骸自动强化…）完成/失败都要记。

    测的是宿主 ``poll_done`` 里那一段 —— 所有 ok-ww 工具页跑完都经过它。
    """

    def setUp(self):
        super().setUp()
        self._orig = notify.store()
        notify.set_store(self.store())
        self.addCleanup(lambda: notify.set_store(self._orig))

        from src.tools.game.auto_combat import okww_boot as OB

        self.OB = OB

    def _host_with(self, key: str, info: dict):
        """造一个"刚跑完任务"的宿主（不碰真引擎）。"""
        class FakeTask:
            def __init__(self):
                self.info = info
                self.running = False
                self.enabled = False

        host = self.OB.OkwwHost()
        host._ok = object()
        host._running_task = key
        task = FakeTask()
        host.find_task = lambda k: task
        return host

    def test_success_records(self):
        self._host_with("声骸自动强化",
                        {"成功声骸数量": 3, "失败声骸数量": 39}).poll_done()
        items = notify.store().items()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "声骸自动强化 · 完成")
        self.assertIn("符合条件 3", items[0].body)

    def test_english_error_key(self):
        """★ ok-script 抛异常时写的是 ``info["Error"]``（见 TaskExecutor.execute）。"""
        self._host_with("声骸批量调频",
                        {"Error": "找不到 强化并调谐"}).poll_done()
        items = notify.store().items()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].level, N.LEVEL_ERROR)
        self.assertIn("找不到", items[0].body)

    def test_chinese_failure_reason(self):
        """★ 我们自己的任务写的是中文 ``失败原因`` —— 两个都要认。

        只认一个的话另一类任务的失败会被**记成完成**（比不记还误导）。
        """
        self._host_with("声骸自动强化",
                        {"失败原因": "强化设置需要开启阶段放入!"}).poll_done()
        items = notify.store().items()
        self.assertEqual(items[0].level, N.LEVEL_ERROR)
        self.assertIn("阶段放入", items[0].body)

    def test_auto_stop_is_its_own_kind(self):
        """★ 「自动暂停」既非成功也非失败，**不能记成失败**（会吓人）。"""
        self._host_with("声骸自动强化", {
            "已自动停止": True,
            "自动停止原因": "出现符合条件的声骸（第 2 个）",
            "成功声骸数量": 2}).poll_done()
        items = notify.store().items()
        self.assertEqual(len(items), 1)
        self.assertIn("自动暂停", items[0].title)
        self.assertEqual(items[0].level, N.LEVEL_INFO)

    def test_error_wins_over_auto_stop(self):
        """★ 两个标记都在时，**错误优先**（真出错了别报成"暂停"）。"""
        self._host_with("X", {"Error": "崩了", "已自动停止": True}).poll_done()
        self.assertEqual(notify.store().items()[0].level, N.LEVEL_ERROR)

    def test_no_double_record(self):
        """★★ ``poll_done`` 每 300ms 调一次 —— **不能重复记**。"""
        host = self._host_with("声骸自动强化", {"成功声骸数量": 1})
        host.poll_done()
        n1 = len(notify.store())
        host.poll_done()
        host.poll_done()
        self.assertEqual(len(notify.store()), n1,
                         "同一次任务结束被记了多次")

    def test_counts_line_skips_missing(self):
        """★ 没有的统计键**一个字都不编**（"成功 0 个"会很误导）。"""
        line = self.OB._counts_line({"成功声骸数量": 2})
        self.assertIn("符合条件 2", line)
        self.assertNotIn("弃置", line)
        self.assertEqual(self.OB._counts_line({}), "")
        self.assertEqual(self.OB._counts_line({"Error": "x"}), "")


class TestTaskFlowNotice(unittest.TestCase):
    """★ 任务**流程**（「任务」页那条链）完成/失败也要记。"""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._orig = notify.store()
        notify.set_store(N.NotificationStore(
            pathlib.Path(self.tmp.name) / "n.json"))
        self.addCleanup(lambda: notify.set_store(self._orig))

    def _flow_thread(self, name: str):
        """造一个只带 ``_finish`` 所需字段的流程线程（不真跑工具）。"""
        import types

        from src.gui.tasks_interface import FlowRunThread

        t = types.SimpleNamespace()
        t.flow = types.SimpleNamespace(name=name)
        t.report = types.SimpleNamespace()
        t.report_ready = types.SimpleNamespace(
            emit=lambda *_: None)
        t._finish = types.MethodType(FlowRunThread._finish, t)
        return t

    def test_flow_success(self):
        """流程成功 → 记一条「完成」。

        ⚠ 直接调 ``_on_finished`` 太重（要真窗口）；这里验的是
        **它调的那个统一入口**在流程语境下拼出来的标题。
        """
        notify.report_task_result("我的流程", ok=True, detail="步骤都过了")
        item = notify.store().items()[0]
        self.assertEqual(item.title, "我的流程 · 完成")
        self.assertEqual(item.level, N.LEVEL_SUCCESS)

    def test_flow_failure(self):
        notify.report_task_result("我的流程", ok=False, detail="工具实例化失败")
        item = notify.store().items()[0]
        self.assertEqual(item.title, "我的流程 · 失败")
        self.assertEqual(item.level, N.LEVEL_ERROR)

    def test_user_stop_is_its_own_kind(self):
        """★★ 用户**主动停止**不该记成"失败" —— 走**真实的**回调。

        ⚠⚠ 这条必须调 ``TaskRowCard._on_stopped_or_failed`` 本体。
        我第一版直接调 ``notify.report(...)`` 自己拼标题 ——
        那等于**在测试里重写了一遍被测逻辑**：把实现改回"记成失败"，
        测试照样通过（护栏验证抓到的假绿）。

        ⚠ 为什么不该记成失败：标题和正文会自相矛盾
        （标题「失败」+ 正文「用户主动停止」），用户在消息列表里
        看到"失败"会以为出了故障。
        """
        import types

        from src.gui.tasks_interface import TaskRowCard

        t = types.SimpleNamespace()
        t.flow = types.SimpleNamespace(name="我的流程")
        t.status_label = types.SimpleNamespace(setText=lambda *_: None)
        t._set_running = lambda *_: None
        t._page = types.SimpleNamespace(note_running=lambda *_: None)
        t.window = lambda: None
        TaskRowCard._on_stopped_or_failed(t, "已停止")

        items = notify.store().items()
        self.assertEqual(len(items), 1, "没记消息")
        item = items[0]
        self.assertIn("已停止", item.title)
        self.assertNotIn("失败", item.title, "主动停止被记成了失败")
        self.assertEqual(item.level, N.LEVEL_INFO,
                         "主动停止用了 error 级（会显示成红色失败）")

    def test_real_failure_still_recorded_as_failure(self):
        """★ 真出错时**仍然**记成失败（别为了修上面那条把真失败也吞了）。"""
        import types

        from src.gui.tasks_interface import TaskRowCard

        t = types.SimpleNamespace()
        t.flow = types.SimpleNamespace(name="我的流程")
        t.status_label = types.SimpleNamespace(setText=lambda *_: None)
        t._set_running = lambda *_: None
        t._page = types.SimpleNamespace(note_running=lambda *_: None)
        t.window = lambda: None
        TaskRowCard._on_stopped_or_failed(t, "RuntimeError: 工具炸了")

        item = notify.store().items()[0]
        self.assertIn("失败", item.title, "真失败没记成失败")
        self.assertEqual(item.level, N.LEVEL_ERROR)


class TestSidebarBadge(unittest.TestCase):
    """★★ 侧栏「消息」那一项：未读数角标 + 选中后清掉。

    用户 2026-10-10："**左侧边栏**增加消息通知功能" ——
    入口在侧栏，所以"侧栏能不能看出有几条没看"是这个功能的门面。

    ## ⚠⚠ 窗口**整类共用一个**（不是每个测试建一个）

    建一次 ``MainWindow`` 实测约 **5 秒**（它就是一棵很重的树）。
    4 条测试各建一个 = 20 秒，而且正是 ``test_skins`` 那次的教训：
    **攒着不销毁的顶层窗口会让 ``app.setStyleSheet`` 越来越慢**
    （详见 ``test_skins._destroy_toplevels``）。

    → 用 ``setUpClass`` 建一个、``tearDownClass`` 销毁；
    每条测试在 ``setUp`` 里把 store **清空**即可（状态隔离靠清数据，
    不靠重建窗口）。
    """

    #: 整个类共用
    _win = None

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    @classmethod
    def tearDownClass(cls):
        """销毁共用的窗口 —— 别留给后面的测试类（那会拖慢整个套件）。"""
        if cls._win is not None:
            cls._win.close_without_prompt()
            cls._win = None
        try:
            from tests.test_skins import _destroy_toplevels
        except Exception:                 # noqa: BLE001 - 拿不到就算了
            return
        _destroy_toplevels()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)

        #: ★ store 每条测试**换新的**（状态隔离），窗口共用
        self._orig = notify.store()
        notify.set_store(N.NotificationStore(self.root / "n.json"))
        self.addCleanup(lambda: notify.set_store(self._orig))

        if TestSidebarBadge._win is None:
            from src.core.ui_state import UiState
            from src.gui.main_window import MainWindow

            win = MainWindow(ui_state=UiState(self.root / "ui.json"))
            win._skip_auto_update = True
            TestSidebarBadge._win = win
        self.win = TestSidebarBadge._win

        #: ⚠ 窗口是共用的 → 它里面的页面还指着**上一个** store。
        #: 不重新指过来的话，本条的 `note()` 会写进上一个临时文件
        #: （已经随着 TemporaryDirectory 被删了），断言全是假的。
        self.win.notice_interface.store = notify.store()
        self.win.notice_interface.refresh()
        self.win.refresh_notice_badge()
        self.app.processEvents()

    def _nav_text(self) -> str:
        """侧栏「消息」那一项**实际画出来的文字**。"""
        item = self.win.navigationInterface.widget(
            self.win.notice_interface.objectName())
        inner = item.findChild(type(item))
        target = inner if inner is not None else item
        return str(target.text())

    def test_badge_shows_unread(self):
        """★★ 有未读 → 侧栏显示「消息 · N」。"""
        self.win.notice_interface.note("甲")
        self.win.notice_interface.note("乙")
        self.win.refresh_notice_badge()
        self.app.processEvents()
        self.assertEqual(self._nav_text(), "消息 · 2",
                         "侧栏没显示未读数")

    def test_badge_clears_after_read(self):
        """★ 读过之后角标要没（不然一直挂着"2 条未读"却点不出东西）。"""
        self.win.notice_interface.note("甲")
        self.win.refresh_notice_badge()
        self.win._on_notice_selected(True)
        self.app.processEvents()
        self.assertEqual(self._nav_text(), "消息")

    def test_no_badge_when_empty(self):
        self.win.refresh_notice_badge()
        self.app.processEvents()
        self.assertEqual(self._nav_text(), "消息")

    def test_selected_false_does_not_mark_read(self):
        """⚠ ``selectedChanged`` 每选中/取消各发一次 —— 取消时**不能**标已读。

        不过滤的话"点开又立刻切走"会把消息标成已读，用户回来什么都没了。
        """
        self.win.notice_interface.note("甲")
        self.win._on_notice_selected(False)
        self.assertEqual(self.win.notice_interface.unread_count(), 1,
                         "取消选中时把消息标成已读了")


class TestNoRealFilePollution(unittest.TestCase):
    """★★★ 建窗口**不许**碰用户真实的 ``notifications.json``。

    ## ⚠⚠ 这条是被真事故逼出来的（2026-10-10）

    我第一版 ``NoticeInterface`` 里写的是 ``store or NotificationStore()`` ——
    那个默认值会**新建一个指向用户真实文件的 store**。后果：

      * 测试里每建一次 ``MainWindow`` 就往用户真实文件里写消息
        （实测跑完一轮测试，``data/notifications.json`` 里躺着
         "甲 / 乙" 这些测试数据）；
      * 更糟的是界面和记录方会成为**两份 store** ——
        工具那边 ``core.notify`` 记了消息，页面上却看不见
        （各写各的文件）。

    本仓在这类问题上栽过好几次（测试改掉用户本地皮肤设置、
    写坏 ``gacha_history.json``），所以单独钉一条。
    """

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def test_page_uses_the_shared_store(self):
        """★★ 页面默认要用**进程级单例**（和记录方同一份）。"""
        import tempfile

        from src.core import notify
        from src.gui.notify_page import NoticeInterface

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        mine = N.NotificationStore(pathlib.Path(tmp.name) / "n.json")
        orig = notify.store()
        notify.set_store(mine)
        self.addCleanup(lambda: notify.set_store(orig))

        page = NoticeInterface()          #: **不传** store —— 走默认值
        self.addCleanup(lambda: (page.setParent(None), page.deleteLater()))
        self.assertIs(page.store, mine,
                      "页面自己新建了一个 store —— 会和记录方各写各的")

    def test_window_does_not_touch_real_file(self):
        """★★★ 建 ``MainWindow`` 不能往用户真实的文件里写。

        做法：把单例指向临时文件，建窗口 + 记一条，
        然后断言**真实文件**（``core.paths.user_data_dir()`` 下那个）
        没有被创建 / 没有被改动。
        """
        import tempfile

        from src.core import notify, paths
        from src.core.ui_state import UiState

        real = paths.user_data_dir() / "notifications.json"
        before = real.read_bytes() if real.is_file() else None

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = pathlib.Path(tmp.name)
        orig = notify.store()
        notify.set_store(N.NotificationStore(root / "n.json"))
        self.addCleanup(lambda: notify.set_store(orig))

        from src.gui.main_window import MainWindow

        win = MainWindow(ui_state=UiState(root / "ui.json"))
        win._skip_auto_update = True
        self.addCleanup(win.close_without_prompt)
        win.notice_interface.note("测试消息", "不该进用户文件")
        self.app.processEvents()

        after = real.read_bytes() if real.is_file() else None
        self.assertEqual(before, after,
                         f"用户真实文件被测试改了：{real}")


class TestNoticePage(unittest.TestCase):
    """★ 侧栏「消息」页面本身。"""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = N.NotificationStore(
            pathlib.Path(self.tmp.name) / "n.json")

    def _page(self):
        from src.gui.notify_page import NoticeInterface

        page = NoticeInterface(store=self.store)
        self.addCleanup(lambda: (page.setParent(None), page.deleteLater()))
        return page

    def test_empty_state(self):
        page = self._page()
        self.assertFalse(page.list_host.isVisible())
        self.assertFalse(page.clear_button.isEnabled(),
                         "没消息时「清空」该是灰的")

    def test_cards_are_built(self):
        from src.gui.notify_page import NoticeCard

        page = self._page()
        page.note("甲 · 完成", "正文甲", level=N.LEVEL_SUCCESS)
        page.note("乙 · 失败", "正文乙", level=N.LEVEL_ERROR)
        self.app.processEvents()
        self.assertEqual(len(page.findChildren(NoticeCard)), 2)

    def test_card_follows_skin(self):
        """★★ 卡片颜色必须**跟皮肤**（本仓有三次"深色皮肤下字看不见"）。"""
        from PySide6.QtWidgets import QLabel

        from src.core import skins
        from src.gui.notify_page import NoticeCard

        for sid in ("mist", "deepglass"):
            with self.subTest(skin=sid):
                skins.apply_skin(sid, save=False)
                page = self._page()
                page.note("甲 · 完成", "正文")
                self.app.processEvents()
                cards = page.findChildren(NoticeCard)
                self.assertTrue(cards, "没建出卡片")
                sheets = " ".join((w.styleSheet() or "")
                                  for w in cards[0].findChildren(QLabel))
                expect = skins.active_skin()["text"]
                self.assertIn(expect, sheets,
                              f"{sid}：卡片文字没用当前皮肤的颜色")

    def test_mark_read_clears_unread(self):
        page = self._page()
        page.note("甲")
        self.assertEqual(page.unread_count(), 1)
        page.mark_read()
        self.assertEqual(page.unread_count(), 0)

    def test_note_emits_changed(self):
        """★ 记一条要通知外面（主窗口靠它刷侧栏角标）。"""
        page = self._page()
        seen = []
        page.changed.connect(lambda: seen.append(1))
        page.note("甲")
        self.assertTrue(seen, "note() 没发 changed —— 侧栏角标不会更新")

    def test_refresh_drops_old_cards(self):
        from src.gui.notify_page import NoticeCard

        page = self._page()
        page.note("甲")
        self.app.processEvents()
        self.store.clear()
        page.refresh()
        self.app.processEvents()
        self.assertEqual(page.findChildren(NoticeCard), [],
                         "清空后旧卡片还留着")


if __name__ == "__main__":
    unittest.main(verbosity=2)
