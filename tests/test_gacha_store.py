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

    def test_same_second_order_follows_interface(self):
        """★★★ **同一秒内要按接口原顺序**（2026-10-05 第三次修这个统计）。

        ## 为什么

        接口把**一次十连的 10 条放在同一秒**，而且**列表是有序的**。
        抽数的段边界（"这个金花了几抽"）**依赖同秒内的先后**。

        只按 ``time`` 排的话，同秒的 10 条是**任意顺序** →
        五星在十连里的位置错 → 每段差 2~3 抽
        （实测：我 23/26/25 抽，用户截图 25/24/28）。

        → 存 ``_seq``（接口列表下标）当第二排序关键字。
        """
        batch = [rec(f"物品{i}", 5 if i == 4 else 3, "T1", i)
                 for i in range(10)]
        self.history.merge(batch, pool_type="1", pool_name="P", at="now")
        got = [r["name"] for r in self.history.all_records()]
        #: 接口最新在前、_seq=0 是最新的；倒序后应是从 _seq=9 到 0
        self.assertEqual(got, [f"物品{i}" for i in range(9, -1, -1)],
                         "同一秒内的顺序没保住 —— 段边界会算错")

    def test_seq_is_stored(self):
        """★ ``_seq`` 要真的存进去（下次排序才有得用）。"""
        self.history.merge([rec("a", 3, "t1", 1), rec("b", 3, "t1", 2)],
                           pool_type="1", pool_name="P", at="now")
        seqs = sorted(int(r["_seq"]) for r in self.history.records.values())
        self.assertEqual(seqs, [0, 1])

    def test_same_second_span_is_correct(self):
        """★★★ **端到端**：十连里第 5 条出金 → 那一段就是 5 抽。

        ⚠ 这条直接对应"差 2~3 抽"那个现象。
        """
        from src.core import gacha

        #: 一次十连：第 5 条（下标 4）是五星
        batch = [rec(f"物品{i}", 5 if i == 4 else 3, "T1", i)
                 for i in range(10)]
        self.history.merge(batch, pool_type="1", pool_name="P", at="now")
        rows = self.history.all_records()
        pulls = [gacha.Pull.from_record(r, "1") for r in rows]
        stats = gacha.PoolStats(name="P", pool_type="1", pulls=pulls)
        spans = [s for _p, s in stats.five_star_spans()]
        self.assertEqual(spans, [5],
                         f"段抽数算错了（{spans}）—— 同秒顺序没保住")

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
