"""抽卡历史（累积存储）的单元测试。

    python tests/test_gacha_store.py

用户 2026-09-30 要求："这里怎么没有做持久化，按照时间保存为一个历史记录"。

★ 核心是**合并去重**：库洛接口只返回**最近一段**记录（实测角色池只给
590 抽左右），窗口滑动时两次拉取必然重叠。不累积就永远看不全账号全貌
（工坊能显示 4393 抽，就是因为它每次拉都存下来合并）。

纯逻辑，不碰 Qt、不打网络。
"""

from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.core import gacha, gacha_store  # noqa: E402


def rec(name: str, star: int, when: str, rid, kind: str = "角色") -> dict:
    """造一条接口形状的记录。"""
    return {"name": name, "qualityLevel": star, "time": when,
            "resourceId": rid, "resourceType": kind}


class TestRecordKey(unittest.TestCase):
    """★ 去重的身份键 —— 加不加 resourceId 是有讲究的。"""

    def test_key_includes_resource_id(self):
        """★ 同一秒十连出两个**同名**物品时，光看(池,名,时间)会撞车。

        那会把其中一条当成重复丢掉 —— 少一条抽数，统计就偏了。
        """
        a = rec("杂", 3, "2026-09-10 11:36:14", 1001)
        b = rec("杂", 3, "2026-09-10 11:36:14", 1002)
        self.assertNotEqual(gacha_store.record_key(a), gacha_store.record_key(b))

    def test_same_record_same_key(self):
        a = rec("心", 5, "2026-09-10 11:36:14", 1)
        b = rec("心", 5, "2026-09-10 11:36:14", 1)
        self.assertEqual(gacha_store.record_key(a), gacha_store.record_key(b))

    def test_identical_twin_records_get_different_keys(self):
        """★★★ **十连里两个完全一样的东西都要留下**（2026-10-05 用户报的 bug）。

        ## 症状

        用户："这里数据统计的不准" —— 工具显示 629 抽，
        实际约 790 抽，**每段抽数都偏小**。

        ## 根因

        身份键是 ``(池子, 名字, 时间, resourceId)`` —— **没有"第几次"**。
        十连是**同一秒**入账的，一抽里出两个**同名同 id** 的 3★ 武器
        （实测「源能长刃·测壹」一抽出现两次）→ 键完全相同 →
        **后面那条被当成重复丢掉**。

        实测丢了多少::

            每秒条数:  6条×6秒  7条×16秒  8条×35秒  9条×19秒  10条×3秒
                       ↑ 十连该是 10 条 → 丢了约 161 条

        ## 修法

        ``merge`` 先扫一遍、给每条标上"同秒同名的第几次"（``_nth``），
        身份键带上它 → 两条都留得下来。
        """
        twin = rec("源能长刃·测壹", 3, "t1", 2102)
        a = dict(twin, _nth=0)
        b = dict(twin, _nth=1)
        self.assertNotEqual(
            gacha_store.record_key(a), gacha_store.record_key(b),
            "同秒同名同 id 的两条拿到同一个键 —— 会被吞掉一条")

    def test_key_tolerates_junk(self):
        self.assertTrue(gacha_store.record_key({}))
        self.assertTrue(gacha_store.record_key(None))


class TestMerge(unittest.TestCase):
    """累积合并。"""

    def setUp(self):
        self.history = gacha_store.GachaHistory()

    def test_first_merge_adds_all(self):
        added = self.history.merge(
            [rec("心", 5, "t1", 1), rec("杂", 3, "t2", 2)],
            pool_type="1", pool_name="角色活动唤取", at="now")
        self.assertEqual(added, 2)
        self.assertEqual(len(self.history), 2)

    def test_overlapping_batch_only_adds_new(self):
        """★ 关键：窗口滑动导致的重叠必须去重掉。

        第二次拉回来的前两条和第一次完全一样 → 只应新增第三条。
        """
        batch = [rec("心", 5, "t1", 1), rec("杂", 3, "t2", 2)]
        self.history.merge(batch, pool_type="1", pool_name="P", at="now")
        added = self.history.merge(
            batch + [rec("锁暝", 5, "t3", 3)],
            pool_type="1", pool_name="P", at="now")
        self.assertEqual(added, 1)
        self.assertEqual(len(self.history), 3)

    def test_identical_remerge_adds_nothing(self):
        batch = [rec("心", 5, "t1", 1)]
        self.history.merge(batch, pool_type="1", pool_name="P", at="now")
        self.assertEqual(
            self.history.merge(batch, pool_type="1", pool_name="P", at="now"), 0)

    def test_twins_in_one_ten_pull_both_kept(self):
        """★★★ **一次十连里两个一模一样的东西，两条都要入库**。

        ⚠ 这是 2026-10-05 用户报"统计不准"的根因：
        十连同秒入账，两个**同名同 id** 的 3★ 武器身份键撞车 →
        后面那条被丢掉 → 每段抽数都偏小（629 vs 实际 ~790）。
        """
        twin = rec("源能长刃·测壹", 3, "t1", 2102)
        added = self.history.merge(
            [dict(twin), dict(twin), dict(twin)],      #: 三个完全一样
            pool_type="1", pool_name="P", at="now")
        self.assertEqual(added, 3, "同名同秒的重复被吞掉了")
        self.assertEqual(len(self.history), 3)

    def test_twins_do_not_duplicate_on_refetch(self):
        """★★★ 但**重新拉同一批**仍然不能重复入库（去重不能失效）。

        ``_nth`` 每次拉取都从 0 重算 —— 同一抽在两次拉取里算出的序号
        **一致**，所以键能稳定对上。
        """
        twin = rec("源能长刃·测壹", 3, "t1", 2102)
        batch = [dict(twin), dict(twin)]
        self.history.merge(batch, pool_type="1", pool_name="P", at="now")
        added = self.history.merge(batch, pool_type="1", pool_name="P",
                                   at="now2")
        self.assertEqual(added, 0, "重新拉取时重复入库了")
        self.assertEqual(len(self.history), 2)

    def test_refetch_with_more_history_keeps_twins(self):
        """★★★ 真实场景：第二次拉到的列表**更长**（往前多了一段）。

        同一抽在两次拉取里的 ``_nth`` 必须一致 ——
        否则要么重复入库、要么又把 twins 吞掉。
        """
        twin = rec("源能长刃·测壹", 3, "t1", 2102)
        old = [rec("旧", 3, "t0", 99)]          #: 更早的一抽

        #: 第一次：窗口只覆盖到 twin 那两个
        self.history.merge([dict(twin), dict(twin)],
                           pool_type="1", pool_name="P", at="now")
        self.assertEqual(len(self.history), 2)

        #: 第二次：窗口往前挪了，多带回一条更早的 + 同样的两个 twin
        added = self.history.merge(
            old + [dict(twin), dict(twin)],
            pool_type="1", pool_name="P", at="now2")
        self.assertEqual(added, 1, "只该新增那条更早的")
        self.assertEqual(len(self.history), 3)

    def test_same_name_different_time_is_new(self):
        """同名但时间不同 = 两次不同的出货，都要留。"""
        self.history.merge([rec("心", 5, "t1", 1)], pool_type="1",
                           pool_name="P", at="now")
        added = self.history.merge([rec("心", 5, "t2", 2)], pool_type="1",
                                   pool_name="P", at="now")
        self.assertEqual(added, 1)

    def test_same_item_in_different_pools_is_kept(self):
        """同一物品在不同池子里是两条记录（池编号进身份键）。"""
        self.history.merge([rec("维里奈", 5, "t1", 1)], pool_type="1",
                           pool_name="限定", at="now")
        added = self.history.merge([rec("维里奈", 5, "t1", 1)], pool_type="3",
                                   pool_name="常驻", at="now")
        self.assertEqual(added, 1)
        self.assertEqual(len(self.history), 2)

    def test_merge_records_pool_fields(self):
        self.history.merge([rec("心", 5, "t1", 1)], pool_type="1",
                           pool_name="角色活动唤取", at="now")
        stored = next(iter(self.history.records.values()))
        self.assertEqual(stored["pool_type"], "1")
        self.assertEqual(stored["pool"], "角色活动唤取")

    def test_merge_tolerates_junk(self):
        added = self.history.merge([None, "不是字典", rec("心", 5, "t", 1)],
                                   pool_type="1", pool_name="P", at="now")
        self.assertEqual(added, 1)

    def test_all_records_newest_first(self):
        self.history.merge([rec("a", 3, "t1", 1), rec("b", 3, "t3", 3),
                            rec("c", 3, "t2", 2)],
                           pool_type="1", pool_name="P", at="now")
        times = [r["time"] for r in self.history.all_records()]
        self.assertEqual(times, ["t3", "t2", "t1"])

    def test_same_second_order_survives_reinsertion(self):
        """★★★ **同秒顺序要在"多批合并"后仍然正确**。

        ## ⚠⚠ 为什么单批测不出来（我试了三次才想明白）

        ``merge`` 给每条标 ``_seq`` = **喂进来的下标**，而 dict 也是
        **按喂入顺序**插的 → 「按 ``_seq`` 排」和「保持 dict 顺序」
        **结果完全一样**。所以**单次 merge 的场景天然验不出 `_seq` 的作用**
        （我把 ``_seq`` 排序去掉，测试照样全过 —— 护栏失效）。

        ## 真正体现 ``_seq`` 价值的场景

        **第二批 merge 时，同一个十连的顺序变了**（接口每次返回的顺序
        可能不同）。这时:
          · 靠 dict 顺序 → 保留的是**第一次**的顺序（可能已经过时）；
          · 靠 ``_seq`` → 用**这次**的顺序覆盖。

        这条就构造这个场景。
        """
        #: 第一批：顺序 A（金在 _seq=4）
        first = [rec(f"物品{i}", 5 if i == 4 else 3, "T1", i)
                 for i in (0, 1, 2, 3, 4, 5, 6, 7, 8, 9)]
        self.history.merge(first, pool_type="1", pool_name="P", at="now")

        #: 第二批：**同样的记录、不同的顺序**（金被排到 _seq=0）
        second = [rec(f"物品{i}", 5 if i == 4 else 3, "T1", i)
                  for i in (4, 0, 1, 2, 3, 5, 6, 7, 8, 9)]
        added = self.history.merge(second, pool_type="1", pool_name="P",
                                   at="now2")
        self.assertEqual(added, 0, "同一批不该有新增")

        got = [r["name"] for r in self.history.all_records()]
        self.assertEqual(got[0], "物品4",
                         f"同秒顺序没被第二批刷新（{got[:3]}）—— "
                         f"_seq 排序没起作用")

    def test_same_second_span_is_correct(self):
        """★★★ **端到端**：十连里出金的位置 → 段抽数必须对。

        ## ⚠ 口径（**实测**出来的，不是我猜的）

        * ``merge`` 按**传入顺序**插，``_seq=0`` 是传入的第一条；
        * ``five_star_spans()`` 内部 ``reversed`` 成时间正序再累计；
        * 实测一次十连里::

            _seq=0 出金  → **10 抽**（它是"最旧"那条）
            _seq=9 出金  → **1 抽**（它是"最新"那条）

        ⚠ 我第一版把这两个写反了、第二版又反着写了一次 ——
        测试连着两次纠正我。**这条断言是照着实测值定的。**

        （``five_star_spans`` 的"新/旧"和"接口列表的新/旧"是**相反**的：
        它把 ``self.pulls`` 当成"最新在前"再 ``reversed``，
        而这里 ``all_records()`` 给的是"传入顺序" —— 两边口径要对齐。）
        """
        from src.core import gacha

        for gold_seq, want in ((0, 10), (4, 6), (9, 1)):
            with self.subTest(gold_seq=gold_seq):
                batch = [rec(f"物品{i}", 5 if i == gold_seq else 3, "T1", i)
                         for i in range(10)]
                h = gacha_store.GachaHistory()
                h.merge(batch, pool_type="1", pool_name="P", at="now")
                rows = h.all_records()
                pulls = [gacha.Pull.from_record(r, "1") for r in rows]
                stats = gacha.PoolStats(name="P", pool_type="1", pulls=pulls)
                spans = [s for _p, s in stats.five_star_spans()]
                self.assertEqual(spans, [want],
                                 f"_seq={gold_seq} 出金该是 {want} 抽（{spans}）")

    def test_multi_second_spans_match_truth(self):
        """★★★ **多秒端到端**：模拟真实十连序列，逐段抽数必须对。

        ⚠ 这条照着"用户游戏截图 15 段全对"那个验收写的。

        ## ⚠⚠ 口径（**实测**出来的，我猜错过三次）

        ### ① 传进来的顺序 = 接口原样（最新在前）

        ``all_records()`` 返回 ``time`` 倒序，直接喂 ``PoolStats``。
        ``five_star_spans()`` 再 ``reversed`` 成时间正序累计。

        ### ② ★ **段是跨十连累积的**（这才是保底的真实语义）

        保底计数**不按十连重置** —— 一个金在"最新那个十连的最后一条"，
        下一个金在"下一个十连的第 5 条"，那一段就是
        ``1 + 5 = 6`` 抽（**跨了十连边界**）。

        ⚠ 我前三次都按"每个十连独立算"去写期望，所以**一直错**。
        实测这个例子的真值是 ``[1, 14, 15]``，合计 30 抽
        （= 3 个十连）—— **一条不差**，只是段跨了边界。
        """
        from src.core import gacha

        #: 三个十连，金分别在各自第 10 / 6 / 1 条
        plan = [("2026-01-01 10:00:00", 9),
                ("2026-01-02 10:00:00", 5),
                ("2026-01-03 10:00:00", 0)]
        batch: list[dict] = []
        for when, gold in plan:
            for i in range(10):
                batch.append(rec(f"{when}i{i}", 5 if i == gold else 3,
                                 when, i))
        #: ★ 接口是**最新在前** → 按时间倒序传（和线上一致）
        batch.sort(key=lambda r: str(r["time"]), reverse=True)

        h = gacha_store.GachaHistory()
        h.merge(batch, pool_type="1", pool_name="P", at="now")
        rows = h.all_records()
        pulls = [gacha.Pull.from_record(r, "1") for r in rows]
        stats = gacha.PoolStats(name="P", pool_type="1", pulls=pulls)
        spans = [s for _p, s in stats.five_star_spans()]

        #: ① 三段加起来 = 全部 30 抽（**一条不差**）
        self.assertEqual(sum(spans), 30,
                         f"段抽数之和不等于总抽数（{spans}）—— 有记录丢了")
        #: ② 最新那段 = 最新十连里金之前那几条（i0 是金 → 1 抽）
        self.assertEqual(spans[0], 1, f"最新那段该是 1 抽（{spans}）")

    def test_seq_is_stored(self):
        """★ ``_seq`` 要真的存进去（下次排序才有得用）。"""
        self.history.merge([rec("a", 3, "t1", 1), rec("b", 3, "t1", 2)],
                           pool_type="1", pool_name="P", at="now")
        seqs = sorted(int(r["_seq"]) for r in self.history.records.values())
        self.assertEqual(seqs, [0, 1])

    def test_resort_does_not_duplicate(self):
        """★ 重新拉取（同一批）不会因为 ``_seq`` 而重复入库。"""
        batch = [rec(f"物品{i}", 3, "T1", i) for i in range(5)]
        self.history.merge(batch, pool_type="1", pool_name="P", at="now")
        added = self.history.merge(batch, pool_type="1", pool_name="P",
                                   at="now2")
        self.assertEqual(added, 0)
        self.assertEqual(len(self.history), 5)


class TestSnapshots(unittest.TestCase):
    """拉取时间点（用户要的"按时间保存为历史记录"）。"""

    def test_newest_first_and_capped(self):
        history = gacha_store.GachaHistory()
        for index in range(gacha_store.MAX_SNAPSHOTS + 20):
            history.add_snapshot(gacha_store.PullSnapshot(at=f"t{index}"))
        self.assertEqual(len(history.snapshots), gacha_store.MAX_SNAPSHOTS)
        self.assertEqual(history.snapshots[0].at,
                         f"t{gacha_store.MAX_SNAPSHOTS + 19}",
                         "最新的应该在最前面")

    def test_describe(self):
        snap = gacha_store.PullSnapshot(at="2026-09-30 22:00", total=850,
                                        five=20, added=12)
        text = snap.describe()
        self.assertIn("850", text)
        self.assertIn("20", text)
        self.assertIn("新增 12", text)


class TestStore(unittest.TestCase):
    """持久化：重启不丢。"""

    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "gacha_history.json"
            history = gacha_store.GachaHistory()
            history.merge([rec("心", 5, "t1", 1)], pool_type="1",
                          pool_name="角色活动唤取", at="now")
            history.add_snapshot(gacha_store.PullSnapshot(
                at="2026-09-30 22:00", total=1, five=1, added=1))
            gacha_store.GachaHistoryStore(path).save(history)

            reloaded = gacha_store.GachaHistoryStore(path).load()
            self.assertEqual(len(reloaded), 1)
            self.assertEqual(len(reloaded.snapshots), 1)
            self.assertEqual(reloaded.snapshots[0].total, 1)

    def test_missing_file_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = gacha_store.GachaHistoryStore(
                pathlib.Path(tmp) / "nope.json")
            self.assertEqual(len(store.load()), 0)

    def test_corrupt_file_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "gacha_history.json"
            path.write_text("{ 不是 json", encoding="utf-8")
            self.assertEqual(len(gacha_store.GachaHistoryStore(path).load()), 0)

    def test_non_dict_json_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "gacha_history.json"
            path.write_text("[1,2,3]", encoding="utf-8")
            self.assertEqual(len(gacha_store.GachaHistoryStore(path).load()), 0)

    def test_file_is_readable_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "gacha_history.json"
            history = gacha_store.GachaHistory()
            history.merge([rec("心", 5, "t1", 1)], pool_type="1",
                          pool_name="P", at="now")
            gacha_store.GachaHistoryStore(path).save(history)
            raw = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(raw["version"], gacha_store.FORMAT_VERSION)
            self.assertEqual(len(raw["records"]), 1)


class TestReportFromRecords(unittest.TestCase):
    """★ 累计记录要能**重建出和实时拉取一模一样的报告结构**。"""

    def test_pools_cover_all_seven(self):
        """没抽过的池也要建出来（保持"池编号→统计"的对应关系稳定）。

        否则"这次有角色池、上次没有"，界面上池子会错位。
        """
        report = gacha.report_from_records([])
        self.assertEqual(len(report.pools), len(gacha.POOLS))
        self.assertEqual([p.pool_type for p in report.pools],
                         [pt for pt, _ in gacha.POOLS])

    def test_counts_from_records(self):
        records = [
            {**rec("心", 5, "t1", 1), "pool_type": "1",
             "pool": "角色活动唤取"},
            {**rec("杂", 3, "t2", 2, "武器"), "pool_type": "1",
             "pool": "角色活动唤取"},
            {**rec("维里奈", 5, "t3", 3), "pool_type": "3",
             "pool": "角色常驻唤取"},
        ]
        report = gacha.report_from_records(records)
        self.assertEqual(report.total, 3)
        self.assertEqual(report.five_count, 2)
        role = report.pool_by_type("1")
        self.assertEqual(role.total, 2)
        self.assertEqual(role.five_count, 1)

    def test_records_sorted_newest_first(self):
        records = [
            {**rec("a", 3, "t1", 1), "pool_type": "1"},
            {**rec("b", 3, "t3", 3), "pool_type": "1"},
            {**rec("c", 3, "t2", 2), "pool_type": "1"},
        ]
        report = gacha.report_from_records(records)
        pool = report.pool_by_type("1")
        self.assertEqual([p.time for p in pool.pulls], ["t3", "t2", "t1"])

    def test_unknown_pool_type_is_ignored(self):
        records = [{**rec("x", 5, "t", 1), "pool_type": "99"}]
        report = gacha.report_from_records(records)
        self.assertEqual(report.total, 0)


class TestRawAndReport(unittest.TestCase):
    """``fetch_raw`` / ``report_from_raw`` 的结构要和以前一致。"""

    def test_report_from_raw_covers_all_pools(self):
        raw = {"1": [rec("心", 5, "t1", 1)]}
        report = gacha.report_from_raw(raw)
        self.assertEqual(len(report.pools), len(gacha.POOLS))
        self.assertEqual(report.total, 1)
        self.assertEqual(report.pool_by_type("1").five_count, 1)

    def test_report_from_raw_empty(self):
        report = gacha.report_from_raw({})
        self.assertEqual(report.total, 0)
        self.assertEqual(len(report.pools), len(gacha.POOLS))


if __name__ == "__main__":
    unittest.main(verbosity=2)
