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


class TestLoadIsPureRead(unittest.TestCase):
    """★★★ ``load()`` **绝不写盘** —— 只有明确的写路径才改数据。

    ## ⚠⚠ 这是实测踩出来的（2026-10-06）

    原来的 ``load()`` 里做了**自愈**：发现重复就 ``save()``。
    功能上没错，但副作用很隐蔽 —— 实测后果::

        跑 tests/smoke_gui.py（会真的建 GachaWidget）
        → 打开页面 → _render_from_history() → load()
        → 自愈触发 → **偷偷改了用户的 data/gacha_history.json**
        （用户 1131 条老数据被写上了 playerId）

    用户看到的是"我没点过分析，数据怎么变了"。

    → 现在：``load`` 纯读；``load_and_repair`` 才写。
    """

    def _store_with_stale_key(self, tmp):
        """建一个"键过期"的历史（模拟老版本的库）。"""
        path = pathlib.Path(tmp) / "h.json"
        hist = gacha_store.GachaHistory()
        #: ⚠ 故意用**过期的键** —— 记录本身没问题，但键不是 record_key 算的
        hist.records["STALE|1|心|t1|1"] = {
            "name": "心", "time": "t1", "resourceId": 1,
            "qualityLevel": 5, "pool_type": "1", "pool": "P",
        }
        store = gacha_store.GachaHistoryStore(path)
        store.save(hist)
        return store, path

    def test_load_does_not_write(self):
        """★★★ 读一次，文件**一个字节都不能变**。"""
        with tempfile.TemporaryDirectory() as tmp:
            store, path = self._store_with_stale_key(tmp)
            before = path.read_text(encoding="utf-8")
            mtime = path.stat().st_mtime_ns

            store.load()

            self.assertEqual(path.read_text(encoding="utf-8"), before,
                             "load() 把文件改了 —— 打开界面就会改用户数据")
            self.assertEqual(path.stat().st_mtime_ns, mtime,
                             "load() 写了盘（时间戳变了）")

    def test_load_and_repair_does_write(self):
        """★★ 明确要修的时候才会写（用户点「分析」走这条）。"""
        with tempfile.TemporaryDirectory() as tmp:
            store, path = self._store_with_stale_key(tmp)
            before = path.read_text(encoding="utf-8")

            history = store.load_and_repair()

            self.assertNotEqual(path.read_text(encoding="utf-8"), before,
                                "load_and_repair() 没把修复落盘")
            #: 键应该被重算成带账号前缀的
            self.assertIn("|1|心|t1|1", list(history.records)[0])

    def test_repair_is_idempotent(self):
        """★ 修两次结果一样（第二次没有可改的 → 0）。"""
        with tempfile.TemporaryDirectory() as tmp:
            store, _path = self._store_with_stale_key(tmp)
            first = store.load_and_repair().repair()
            second = store.load_and_repair().repair()
            self.assertEqual(first, 0, "第一次已经修过了，不该再有改动")
            self.assertEqual(second, 0)

    def test_repair_returns_zero_on_healthy_data(self):
        """★ 健康的库上 ``repair()`` 不该动任何东西。"""
        history = gacha_store.GachaHistory()
        history.merge([rec("心", 5, "t1", 1)], pool_type="1",
                      pool_name="P", at="now", player_id="111")
        self.assertEqual(history.repair(), 0)

    def test_load_missing_file_still_returns_empty(self):
        """★ 文件不存在 → 空历史，不报错（原行为不能破）。"""
        with tempfile.TemporaryDirectory() as tmp:
            store = gacha_store.GachaHistoryStore(
                pathlib.Path(tmp) / "nope.json")
            self.assertEqual(len(store.load()), 0)


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


class TestMultiAccount(unittest.TestCase):
    """★★★ **多账号隔离**（用户 2026-10-06："我要是换个账户了呢"）。

    ## 原来的问题

    身份键只有 ``(池子, 物品, 时间, resourceId)`` —— **没有账号**。后果：

    * 换账号后**旧记录不会清掉** → 两个号的抽卡**混在一起统计**；
    * A / B 两号有**一样的抽卡**（同池同物品同秒）→ 被去重成一条，**少算**。

    用户选了「方案 A：按账号分开存」——
    ``playerId`` 进身份键，换号自动切到那个号的数据。
    """

    def setUp(self):
        self.history = gacha_store.GachaHistory()

    def _merge(self, rows, who):
        return self.history.merge(rows, pool_type="1", pool_name="P",
                                  at="now", player_id=who)

    def test_same_pull_different_accounts_both_kept(self):
        """★★★ 两个号**完全一样的抽卡**必须各存一条（原来会互相吞）。

        这是这次要修的核心：不加账号维度的话，第二条会被去重成"重复"。
        """
        a = rec("心", 5, "2026-01-01 10:00:00", 1311)
        b = rec("心", 5, "2026-01-01 10:00:00", 1311)
        self._merge([a], "111")
        added = self._merge([b], "222")
        self.assertEqual(added, 1, "另一个号的同一条抽卡被吞掉了")
        self.assertEqual(len(self.history), 2)

    def test_records_are_isolated_by_account(self):
        """★★★ ``all_records(账号)`` 只看那个号的记录。"""
        self._merge([rec("心", 5, "t1", 1)], "111")
        self._merge([rec("绯雪", 5, "t2", 2)], "222")
        self.assertEqual(len(self.history.all_records("111")), 1)
        self.assertEqual(len(self.history.all_records("222")), 1)
        self.assertEqual(
            self.history.all_records("111")[0]["name"], "心",
            "账号 A 看到了 B 的记录")

    def test_players_lists_all_accounts(self):
        """★ 能列出库里有哪些账号（界面要显示/切换）。"""
        self._merge([rec("心", 5, "t1", 1)], "111")
        self._merge([rec("心", 5, "t2", 2), rec("a", 3, "t3", 3)], "222")
        #: 按记录数从多到少
        self.assertEqual(self.history.players(), ["222", "111"])

    def test_player_count(self):
        self._merge([rec("心", 5, "t1", 1)], "111")
        self._merge([rec("a", 3, "t2", 2), rec("b", 3, "t3", 3)], "222")
        self.assertEqual(self.history.player_count("222"), 2)
        self.assertEqual(self.history.player_count("111"), 1)
        self.assertEqual(self.history.player_count("999"), 0)

    def test_same_account_refetch_dedupes(self):
        """★★ 同一个号重新拉同一批 → 仍然不重复入库。"""
        rows = [rec("心", 5, "t1", 1)]
        self._merge(rows, "111")
        self.assertEqual(self._merge(rows, "111"), 0)

    def test_unknown_account_is_legacy(self):
        """★ 没给账号 → 归到 ``__legacy__``（**不猜**成别的号）。"""
        self._merge([rec("心", 5, "t1", 1)], "")
        self.assertEqual(self.history.players(), [gacha_store._LEGACY_PLAYER])

    def test_legacy_claim_moves_records(self):
        """★★★ 老数据（没有账号）能被认领给当前账号。"""
        self._merge([rec("心", 5, "t1", 1)], "")
        self.assertEqual(self.history.player_count("111"), 0)
        claimed = self.history.claim_legacy("111")
        self.assertEqual(claimed, 1)
        self.assertEqual(self.history.player_count("111"), 1)
        self.assertNotIn(gacha_store._LEGACY_PLAYER, self.history.players())

    def test_legacy_claim_rekeys_records(self):
        """★★★ 认领之后**身份键必须重算**。

        ## ⚠⚠ 这条是护栏验证时发现"没测到"才补的

        我把 ``claim_legacy`` 里那行 ``self.rekey_all()`` 去掉后，
        **测试照样全过** —— 说明原来根本没有测试覆盖这件事。

        ## 为什么必须重算

        ``records`` 是 ``{身份键: 记录}``，而键的**第一段就是账号**。
        认领改了 ``playerId`` 却不动键的话，下次 ``merge`` 会算出
        "新键不在库里" → 把同一条**再存一份** ——
        正是我修过的"复制记录"那个 bug 的翻版::

            认领前:  __legacy__|1|心|t1|1  →  {键: 记录}
            认领后:  111|1|心|t1|1         →  键得跟着变

        做法：直接**断言键里带上了新账号**，再用"再 merge 同一条
        会不会新增"来验端到端。
        """
        self._merge([rec("心", 5, "t1", 1)], "")
        self.history.claim_legacy("111")

        keys = list(self.history.records)
        self.assertEqual(keys, ["111|1|心|t1|1"],
                         f"认领后键没重算（{keys}）")

        #: 端到端：同一条再 merge 一次**不能**新增
        added = self._merge([rec("心", 5, "t1", 1)], "111")
        self.assertEqual(added, 0,
                         "认领后键没重算 → 同一条被当成新的又存了一份")
        self.assertEqual(len(self.history), 1)

    def test_legacy_claim_skipped_when_account_has_data(self):
        """★★★ 这个号**已经有自己的数据**时不认领。

        ⚠ 否则会把老数据硬塞给一个已经有很多记录的号（可能是误操作），
        两个号的数据就混了 —— 正是这次要防的事。
        """
        self._merge([rec("心", 5, "t1", 1)], "111")
        self._merge([rec("杂", 3, "t9", 9)], "")
        claimed = self.history.claim_legacy("111")
        self.assertEqual(claimed, 0, "不该认领")
        self.assertEqual(self.history.player_count("111"), 1)
        self.assertIn(gacha_store._LEGACY_PLAYER, self.history.players())

    def test_claim_with_empty_id_is_noop(self):
        self._merge([rec("心", 5, "t1", 1)], "")
        self.assertEqual(self.history.claim_legacy(""), 0)

    def test_merge_triggers_legacy_claim(self):
        """★★ 认领是**自动**的 —— 拉一次就完成，用户不用手动做什么。"""
        self._merge([rec("心", 5, "t1", 1)], "")          #: 老数据
        self._merge([rec("杂", 3, "t2", 2)], "111")       #: 新版本第一次拉
        self.assertEqual(self.history.player_count("111"), 2,
                         "老数据没被自动认领")

    def test_account_label_is_short(self):
        """★ 界面上显示短名（playerId 是长数字，铺一长串不好看）。"""
        self.assertEqual(gacha_store.account_label("113152489"), "…152489")
        self.assertEqual(gacha_store.account_label("12345"), "12345")
        self.assertEqual(gacha_store.account_label(""), "未知账号")
        self.assertEqual(
            gacha_store.account_label(gacha_store._LEGACY_PLAYER), "未知账号")

    def test_snapshot_remembers_account(self):
        """★★ 历史快照要记住是**哪个号**拉的（切号后要能分辨）。"""
        self.history.add_snapshot(gacha_store.PullSnapshot(
            at="2026-01-01", total=10, five=1, added=10, player_id="111"))
        data = self.history.to_dict()
        back = gacha_store.GachaHistory.from_dict(data)
        self.assertEqual(back.snapshots[0].player_id, "111")

    def test_old_snapshot_without_account_still_loads(self):
        """★ 老快照没有 ``playerId`` → 空串，不能崩。"""
        snap = gacha_store.PullSnapshot.from_dict(
            {"at": "2026-01-01", "total": 5, "five": 0, "added": 5})
        self.assertEqual(snap.player_id, "")
        self.assertEqual(snap.total, 5)

    def test_report_from_records_scoped_to_account(self):
        """★★★ **端到端**：报告只统计指定账号的抽数。

        ⚠ 这条直接对应"换号后两个号混在一起"那个 bug。
        """
        from src.core import gacha

        self._merge([rec("心", 5, "t1", 1), rec("a", 3, "t2", 2)], "111")
        self._merge([rec("绯雪", 5, "t3", 3)], "222")

        r1 = gacha.report_from_records(self.history.all_records("111"),
                                       player_id="111")
        r2 = gacha.report_from_records(self.history.all_records("222"),
                                       player_id="222")
        self.assertEqual(r1.total, 2, f"账号 111 的总抽数不对（{r1.total}）")
        self.assertEqual(r2.total, 1, f"账号 222 的总抽数不对（{r2.total}）")


class TestDropUnknownSnapshots(unittest.TestCase):
    """★★★ 「未知账号」的历史快照要能删掉（用户 2026-10-06）。

        用户（截图圈出那三行）::

            "未知账号的干掉"

    ## 那些是什么

    升级到多账号版本**之前**留下的快照 —— 那时 ``PullSnapshot`` 还没有
    ``player_id`` 字段，读回来是空串，界面显示成「未知账号」。

    ⚠ 里面还夹着**错误数据**：``total=2018`` 那条是修"复制记录" bug
    之前拍的（当时库里真有 2018 条重复记录）。留着会让用户以为
    "我曾经抽了 2018 抽"。

    ## ⚠ 为什么不"猜"它属于当前账号

    猜的话就是把 2018 那个错数字认领给用户 —— 比显示「未知账号」更糟。
    """

    def setUp(self):
        self.history = gacha_store.GachaHistory()

    def _snap(self, at: str, pid: str, total: int = 10) -> None:
        self.history.add_snapshot(gacha_store.PullSnapshot(
            at=at, total=total, five=1, added=1, player_id=pid))

    def test_drops_only_unknown(self):
        """★★★ 只删"没有账号"的，认得出账号的**一条不动**。

        ⚠ ``add_snapshot`` 是 **insert(0)**（最新的在前）—— 所以
        按 t1,t2,t3,t4 顺序加进去，列表是 ``[t4, t3, t2, t1]``。
        用 ``sorted`` 比内容，别被顺序绕进去（我第一次就写错了）。
        """
        self._snap("t1", "111")
        self._snap("t2", "")
        self._snap("t3", "222")
        self._snap("t4", "")

        removed = self.history.drop_unknown_snapshots()

        self.assertEqual(removed, 2)
        self.assertEqual(sorted(s.at for s in self.history.snapshots),
                         ["t1", "t3"], "删多或删错了")
        #: 顺带钉住"认得出账号的都还在"
        self.assertTrue(all(s.player_id for s in self.history.snapshots))

    def test_drop_is_idempotent(self):
        """★ 删两次，第二次没得删。"""
        self._snap("t1", "")
        self.assertEqual(self.history.drop_unknown_snapshots(), 1)
        self.assertEqual(self.history.drop_unknown_snapshots(), 0)

    def test_drop_keeps_records_intact(self):
        """★★★ **记录一条都不能少** —— 删的只是"某次拉取累计到多少"
        那几行流水，不是抽卡记录本身。"""
        self.history.merge([rec("心", 5, "t1", 1)], pool_type="1",
                           pool_name="P", at="now", player_id="111")
        self._snap("t1", "")
        before = len(self.history)

        self.history.drop_unknown_snapshots()

        self.assertEqual(len(self.history), before, "记录被误删了")
        self.assertEqual(self.history.player_count("111"), 1)

    def test_repair_includes_drop(self):
        """★★ ``repair()`` 要把这条也带上（用户点「分析」时自动清）。"""
        self._snap("t1", "")
        self.assertGreater(self.history.repair(), 0,
                           "repair() 没处理未知账号的快照")
        self.assertEqual(len(self.history.snapshots), 0)

    def test_empty_history_is_safe(self):
        """★ 空历史不报错。"""
        self.assertEqual(self.history.drop_unknown_snapshots(), 0)


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
