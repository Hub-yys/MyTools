"""唤取记录（抽卡）分析：链接解析 + 统计 + 渲染的单元测试。

    python tests/test_gacha.py

网络请求不在这里测（喂假数据），但**链接解析**和**统计口径**是纯逻辑，
而且它们最容易算错（间隔、垫抽、出货率），所以覆盖得细一点。
"""

from __future__ import annotations

import os
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.core import gacha  # noqa: E402

#: 一条真实的唤取记录链接形状
GOOD_LINK = (
    "https://aki-gm-resources.aki-game.com/aki/gacha/index.html#/record?"
    "svr_id=SERVER123&player_id=PLAYER456&lang=zh-Hans"
    "&record_id=RECORD789&resources_id=POOL000"
)


def make_pool(name: str, seq, pool_name: str = "") -> gacha.PoolStats:
    """``seq`` 是**时间正序**的 ``[(星级, 时间), ...]``（第 0 项最早）。

    ⚠ 存进 ``pulls`` 时会**反转成"最新在前"** —— 那是接口的真实顺序
    （实测确认，见 :meth:`PoolStats.spans` 的说明）。``spans`` / ``current_pity``
    都是按"最新在前"写的，所以这里必须还原成那个方向，否则测的就不是真实数据。
    """
    label = pool_name or name
    oldest_first = [
        gacha.Pull(name=f"{star}星{i}", star=star, time=t, pool=label)
        for i, (star, t) in enumerate(seq)
    ]
    return gacha.PoolStats(name=name, pulls=list(reversed(oldest_first)))


def five_pool(segments, *, name="角色活动唤取", pool_type="1",
              kind="角色") -> gacha.PoolStats:
    """按"每段 = 前面垫 N 抽杂 + 1 抽金"造限定池。

    ``segments = [(金的名字, 前面垫几抽), ...]``（时间正序）。

    这样构造的好处：每段的 **span 就等于 filler+1**，
    期望值可以直接由构造推出，不用手算（手算必错，我错过两次）。
    """
    pulls, t = [], 0
    for gold, filler in segments:
        for _ in range(filler):
            pulls.append(gacha.Pull(name="杂", star=3, time=f"t{t:05d}",
                                    kind=kind))
            t += 1
        pulls.append(gacha.Pull(name=gold, star=5, time=f"t{t:05d}",
                                kind=kind))
        t += 1
    return gacha.PoolStats(name=name, pool_type=pool_type,
                           pulls=list(reversed(pulls)))


class TestPityAndUp(unittest.TestCase):
    """★ 大保底 / UP / 歪 —— 这是"数据分析不对"的**根因所在**。

    参考鸣潮工坊的实现，要维护**两个**计数：

    ==============  ====================  ==================
    字段            含义                  重置时机
    ==============  ====================  ==================
    ``span``        距离上一个**五星**     每个五星都重置
    ``cumulative``  距离上一次 **UP**      只有 UP 才重置
    ==============  ====================  ==================

    我第一版把两者混成一个（照抄了参考里"只有 UP 才重置"的那句），
    结果界面上的"第几抽"会变成累计值。
    """

    #: 正序：垫3->歪(维里奈) 垫7->UP(心) 垫12->歪(卡卡罗) 垫4->UP(锁暝) 垫20->UP(心)
    SEGS = [("维里奈", 3), ("心", 7), ("卡卡罗", 12), ("锁暝", 4), ("心", 20)]

    def _pool(self):
        return five_pool(self.SEGS)

    def test_span_is_gap_between_five_stars(self):
        """``span`` = 距离上一个**五星**，不管歪没歪都重置。"""
        pool = self._pool()
        expect = [filler + 1 for _n, filler in self.SEGS]
        self.assertEqual([f.span for f in pool.fives_analysis()], expect)

    def test_cumulative_carries_over_on_loss(self):
        """★ ``cumulative`` 歪了**继续累加**（大保底）。

        构造推演：
          维里奈(歪) = 4
          心(UP)     = 4 + 8  = 12   ← 继承上面歪掉那段
          卡卡罗(歪) = 13
          锁暝(UP)   = 13 + 5 = 18   ← 再继承
          心(UP)     = 21
        """
        pool = self._pool()
        self.assertEqual([f.cumulative for f in pool.fives_analysis()],
                         [4, 12, 13, 18, 21])

    def test_up_and_lost_flags(self):
        pool = self._pool()
        fives = pool.fives_analysis()
        self.assertEqual([f.is_50 for f in fives],
                         [False, True, False, True, True])
        self.assertEqual([f.is_lost for f in fives],
                         [True, False, True, False, False])

    def test_up_count_and_not_up_rate(self):
        pool = self._pool()
        self.assertEqual(pool.up_count(), 3)
        self.assertAlmostEqual(pool.not_up_rate(), 60.0)   # 3/5

    def test_average_per_up_is_total_over_ups(self):
        """每 UP 平均 = **总抽数 / UP 数**（歪掉的抽也算进去）。

        总 = 4+8+13+5+21 = 51，UP = 3 → 17.0
        """
        pool = self._pool()
        self.assertAlmostEqual(pool.average_per_up(), 51 / 3)

    def test_resident_pool_has_no_up_concept(self):
        """常驻池没有 UP/歪 —— 两个指标都返回 ``None``（不是 0）。

        返回 0 会被界面显示成"0.0%"，读起来像"每次都歪"，是误导。
        """
        pool = five_pool([("维里奈", 5), ("卡卡罗", 30)],
                         name="角色常驻唤取", pool_type="3")
        self.assertFalse(pool.is_limited_pool)
        self.assertIsNone(pool.not_up_rate())
        self.assertIsNone(pool.average_per_up())
        # 但 span 照常算（常驻池也要显示第几抽）
        self.assertEqual([f.span for f in pool.fives_analysis()], [6, 31])

    def test_limited_pool_types(self):
        """只有池 1（角色活动）/ 2（武器活动）算限定池。"""
        for ptype, limited in (("1", True), ("2", True), ("3", False),
                               ("4", False), ("5", False), ("6", False),
                               ("7", False)):
            with self.subTest(pool_type=ptype):
                pool = gacha.PoolStats(name="x", pool_type=ptype)
                self.assertEqual(pool.is_limited_pool, limited)


class TestLimitedJudgement(unittest.TestCase):
    """UP 判定的依据是**常驻名单**（不在名单里 = 限定）。"""

    def test_permanent_characters_are_not_limited(self):
        for name in ("维里奈", "凌阳", "鉴心", "安可", "卡卡罗"):
            with self.subTest(name=name):
                self.assertFalse(gacha.is_limited(name, "角色"),
                                 f"{name} 是常驻，不该算限定")

    def test_others_are_limited(self):
        for name in ("心", "锁暝", "绯雪", "爱弥斯"):
            with self.subTest(name=name):
                self.assertTrue(gacha.is_limited(name, "角色"))

    def test_blank_name_defaults_to_limited(self):
        """名字取不到时当**限定**：宁可不算"歪"，也不要把不歪率算低。"""
        self.assertTrue(gacha.is_limited("", "角色"))


class TestSpanColor(unittest.TestCase):
    """抽数条配色：低抽数绿（欧）、高抽数红（非）。"""

    def test_low_is_green_high_is_red(self):
        low = gacha.span_color(10)
        high = gacha.span_color(79)
        self.assertNotEqual(low, high)
        # 抽数越小越"绿"（G 分量更高）
        def greenish(hexcolor: str) -> int:
            return int(hexcolor[3:5], 16)

        self.assertGreater(greenish(low), greenish(high))

    def test_monotonic_thresholds_cover_everything(self):
        for span in (1, 40, 41, 60, 61, 73, 74, 80, 81, 200):
            with self.subTest(span=span):
                self.assertTrue(gacha.span_color(span).startswith("#"))


class TestCharacterOnlyCategories(unittest.TestCase):
    """★ 限定/常驻五星统计**只算角色**，不混武器。

    反推验证（用户截图）：``限定44 + 常驻19 = 63 = 五星数`` ——
    两个数加起来正好是总五星，说明统计的都是角色。
    把武器混进来会让两数之和超过总数。
    """

    def test_weapons_excluded(self):
        report = gacha.GachaReport(pools=[
            five_pool([("维里奈", 3), ("心", 7)], name="角色活动唤取",
                      pool_type="1", kind="角色"),
            five_pool([("千古洑流", 5)], name="武器活动唤取",
                      pool_type="2", kind="武器"),
        ])
        limited = [f.name for f in report.limited_fives()]
        permanent = report.permanent_fives()
        self.assertIn("心", limited)
        self.assertNotIn("千古洑流", limited, "武器不该进限定角色统计")
        self.assertNotIn("千古洑流", permanent, "武器不该进常驻角色统计")
        self.assertIn("维里奈", permanent)


class TestParseLink(unittest.TestCase):
    """★ 链接参数名和接口参数名**不一样**，这层映射错了就完全拉不到数据。"""

    def test_maps_all_params(self):
        params = gacha.parse_link(GOOD_LINK)
        self.assertEqual(params["serverId"], "SERVER123")
        self.assertEqual(params["playerId"], "PLAYER456")
        self.assertEqual(params["languageCode"], "zh-Hans")
        self.assertEqual(params["recordId"], "RECORD789")
        self.assertEqual(params["cardPoolId"], "POOL000")

    def test_rejects_empty(self):
        with self.assertRaises(gacha.GachaError):
            gacha.parse_link("")
        with self.assertRaises(gacha.GachaError):
            gacha.parse_link("   ")

    def test_rejects_other_site(self):
        with self.assertRaises(gacha.GachaError) as ctx:
            gacha.parse_link("https://www.bilibili.com/video/BV1xx")
        self.assertIn("唤取记录", str(ctx.exception))

    def test_rejects_missing_params(self):
        bad = (
            f"https://{gacha.LINK_HOST}/aki/gacha/index.html#/record?player_id=1"
        )
        with self.assertRaises(gacha.GachaError) as ctx:
            gacha.parse_link(bad)
        # 要指明**缺哪个**，不能只说"链接无效"
        self.assertIn("recordId", str(ctx.exception))

    def test_language_defaults(self):
        """链接里没带 lang 也能用（默认简体中文）。"""
        link = GOOD_LINK.replace("&lang=zh-Hans", "")
        self.assertEqual(gacha.parse_link(link)["languageCode"], "zh-Hans")

    def test_tolerates_trailing_anchor(self):
        params = gacha.parse_link(GOOD_LINK + "#/extra")
        self.assertEqual(params["playerId"], "PLAYER456")

    def test_pools_count(self):
        """7 个卡池都要有（和游戏里唤取记录的页签一致）。"""
        self.assertEqual(len(gacha.POOLS), 7)
        types = [t for t, _ in gacha.POOLS]
        self.assertEqual(types, ["1", "2", "3", "4", "5", "6", "7"])


class TestPullParsing(unittest.TestCase):
    def test_from_record_uses_rank_type(self):
        pull = gacha.Pull.from_record(
            {"name": "某角色", "rankType": 5, "resourceType": "角色",
             "time": "2026-09-30 12:00:00"}, "角色活动唤取")
        self.assertEqual(pull.name, "某角色")
        self.assertEqual(pull.star, 5)
        self.assertEqual(pull.kind, "角色")

    def test_from_record_tolerates_junk(self):
        """字段缺失/类型不对不能炸（接口偶尔给脏数据）。"""
        pull = gacha.Pull.from_record({}, "x")
        self.assertEqual(pull.name, "")
        self.assertEqual(pull.star, 3)
        pull2 = gacha.Pull.from_record({"rankType": "不是数字"}, "x")
        self.assertEqual(pull2.star, 3)
        pull3 = gacha.Pull.from_record(None, "x")
        self.assertEqual(pull3.star, 3)

    def test_falls_back_to_alternate_name_fields(self):
        pull = gacha.Pull.from_record({"resourceName": "某武器"}, "x")
        self.assertEqual(pull.name, "某武器")


class TestPoolStats(unittest.TestCase):
    def test_basic_counts(self):
        pool = make_pool("角色活动唤取", [
            (3, "t1"), (3, "t2"), (5, "t3"), (4, "t4"),
        ])
        self.assertEqual(pool.total, 4)
        self.assertEqual(pool.five_count, 1)
        self.assertEqual(len(pool.four_stars), 1)
        self.assertAlmostEqual(pool.rate(), 25.0)
        self.assertAlmostEqual(pool.average(), 4.0)

    def test_spans_are_ordered_oldest_first(self):
        """★ 间隔按**时间正序**算：先 3 抽出一金，再 5 抽出一金。"""
        pool = make_pool("角色活动唤取", [
            (3, "t1"), (3, "t2"), (5, "t3"),
            (3, "t4"), (3, "t5"), (3, "t6"), (3, "t7"), (5, "t8"),
        ])
        self.assertEqual(pool.spans(), [3, 5])

    def test_current_pity(self):
        """垫抽 = 最后一个五星**之后**抽了多少。"""
        pool = make_pool("角色活动唤取", [
            (3, "t1"), (5, "t2"), (3, "t3"), (3, "t4"),
        ])
        self.assertEqual(pool.current_pity(), 2)

    def test_five_star_spans_pairs_each_gold_with_its_cost(self):
        """★ 界面靠它给每个五星标"第几抽出"，必须和 spans() 对得上。"""
        pool = make_pool("角色活动唤取", [
            (3, "t1"), (3, "t2"), (5, "t3"),
            (3, "t4"), (3, "t5"), (3, "t6"), (3, "t7"), (5, "t8"),
        ])
        pairs = pool.five_star_spans()
        self.assertEqual([span for _pull, span in pairs], pool.spans())
        self.assertEqual([span for _pull, span in pairs], [3, 5])
        # 配对的必须是那两抽五星本身
        self.assertTrue(all(pull.star == 5 for pull, _ in pairs))
        self.assertEqual([pull.time for pull, _ in pairs], ["t3", "t8"])

    def test_pity_zero_right_after_five_star(self):
        pool = make_pool("角色活动唤取", [(3, "t1"), (5, "t2")])
        self.assertEqual(pool.current_pity(), 0)

    def test_pity_counts_all_when_no_five_star(self):
        pool = make_pool("角色活动唤取", [(3, "t1"), (3, "t2"), (4, "t3")])
        self.assertEqual(pool.current_pity(), 3)
        self.assertEqual(pool.five_count, 0)
        self.assertEqual(pool.spans(), [])
        self.assertEqual(pool.average(), 0.0)
        self.assertIsNone(pool.luck())

    def test_empty_pool_is_all_zero(self):
        pool = gacha.PoolStats(name="新手唤取")
        self.assertEqual(pool.total, 0)
        self.assertEqual(pool.rate(), 0.0)
        self.assertEqual(pool.current_pity(), 0)

    def test_luck_tiers(self):
        """★ 欧非评价按平均出货抽数 —— **越低越欧**。

        档位表读法：``平均 >= 阈值`` 就归那一档，第一个命中为准，
        所以**平均越小的档排在表尾**（越靠后越欧）。
        平均 20 抽 ⇒ 连 30 档都够不上 ⇒ 落到最后一档「策划亲儿子」（最欧）；
        平均 160 抽 ⇒ 命中 150 档「至尊非酋王」（最非）。
        """
        lucky = make_pool("a", [(5, "t1")] + [(3, f"x{i}") for i in range(19)])
        unlucky = make_pool("b", [(5, "t1")] + [(3, f"y{i}") for i in range(159)])
        self.assertAlmostEqual(lucky.average(), 20.0)
        self.assertAlmostEqual(unlucky.average(), 160.0)
        self.assertEqual(lucky.luck()[0], "策划亲儿子")
        self.assertEqual(unlucky.luck()[0], "至尊非酋王")

    def test_luck_boundaries(self):
        """边界：正好等于阈值时归**更高（更非）**那一档（``>=`` 的语义）。"""
        # 平均正好 30 抽 ⇒ 命中「欧皇」（30 档），不是「策划亲儿子」
        pool = make_pool("x", [(5, "t")] + [(3, f"z{i}") for i in range(29)])
        self.assertAlmostEqual(pool.average(), 30.0)
        self.assertEqual(pool.luck()[0], "欧皇")

    def test_luck_covers_every_positive_average(self):
        """任何正的平均抽数都要有档位（最后一档阈值 0，不该出现"无评价"）。"""
        for count in (1, 5, 29, 30, 59, 60, 149, 150, 300):
            with self.subTest(average=count):
                pool = make_pool("x", [(5, "t")] + [(3, f"z{i}") for i in range(count - 1)])
                self.assertIsNotNone(pool.luck())

    def test_luck_is_none_without_five_star(self):
        self.assertIsNone(make_pool("a", [(3, "t1"), (4, "t2")]).luck())


class TestGachaReport(unittest.TestCase):
    def _report(self) -> gacha.GachaReport:
        return gacha.GachaReport(player_id="P1", pools=[
            make_pool("角色活动唤取", [(3, "a1"), (5, "a2")]),
            make_pool("武器活动唤取", [(3, "b1"), (3, "b2"), (5, "b3")]),
            gacha.PoolStats(name="新手唤取"),          # 没抽过
        ])

    def test_totals_across_pools(self):
        report = self._report()
        self.assertEqual(report.total, 5)
        self.assertEqual(report.five_count, 2)
        self.assertAlmostEqual(report.rate(), 40.0)

    def test_active_pools_hides_empty(self):
        """★ 没抽过的池子不显示（否则界面一排全 0）。"""
        names = [p.name for p in self._report().active_pools()]
        self.assertEqual(names, ["角色活动唤取", "武器活动唤取"])

    def test_five_stars_sorted_newest_first(self):
        fives = self._report().all_five_stars()
        self.assertEqual(len(fives), 2)
        self.assertGreaterEqual(fives[0].time, fives[1].time)

    def test_empty_report(self):
        report = gacha.GachaReport()
        self.assertEqual(report.total, 0)
        self.assertEqual(report.rate(), 0.0)
        self.assertIsNone(report.luck())
        self.assertEqual(report.active_pools(), [])


class TestFetchErrors(unittest.TestCase):
    """网络层用假响应测（不打真接口）。"""

    def test_code_minus_one_mentions_reopening_page(self):
        """★ code=-1 = 记录过期 —— 提示必须告诉用户"去游戏里打开唤取记录页"。"""
        import json
        import unittest.mock as mock

        payload = json.dumps(
            {"code": -1, "message": "记录已过期"}).encode("utf-8")

        class FakeResponse:
            def read(self):
                return payload

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        with mock.patch("urllib.request.urlopen", return_value=FakeResponse()):
            with self.assertRaises(gacha.GachaError) as ctx:
                gacha.fetch_pool({"playerId": "1"}, "1")
        message = str(ctx.exception)
        self.assertIn("唤取记录", message)

    def test_success_returns_data(self):
        import json
        import unittest.mock as mock

        payload = json.dumps(
            {"code": 0, "message": "success",
             "data": [{"name": "x", "rankType": 5}]}).encode("utf-8")

        class FakeResponse:
            def read(self):
                return payload

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        with mock.patch("urllib.request.urlopen", return_value=FakeResponse()):
            data = gacha.fetch_pool({"playerId": "1"}, "1")
        self.assertEqual(len(data), 1)

    def test_network_error_becomes_gacha_error(self):
        import unittest.mock as mock

        with mock.patch("urllib.request.urlopen",
                        side_effect=OSError("断网了")):
            with self.assertRaises(gacha.GachaError) as ctx:
                gacha.fetch_pool({"playerId": "1"}, "1")
        self.assertIn("断网了", str(ctx.exception))


class TestWidgetRender(unittest.TestCase):
    """界面渲染：喂假报告，看统计块/分池行/五星行对不对。"""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def _widget(self):
        from PySide6.QtWidgets import QWidget

        from src.tools.game.gacha.tool import GachaWidget

        holder = QWidget()
        holder.resize(1200, 900)
        self._holders = getattr(self, "_holders", [])
        self._holders.append(holder)
        widget = GachaWidget()
        widget.setParent(holder)
        widget.resize(1200, 900)
        holder.show()
        self.app.processEvents()
        return widget

    def test_renders_report(self):
        widget = self._widget()
        report = gacha.GachaReport(pools=[
            make_pool("角色活动唤取", [(3, "a1"), (5, "a2")]),
            make_pool("武器活动唤取", [(5, "b1")]),
        ])
        widget.render(report)
        self.app.processEvents()

        self.assertEqual(widget.stat_total.value_label.text(), "3")
        self.assertEqual(widget.stat_fives.value_label.text(), "2")
        # 抽过的池子各一块
        self.assertEqual(widget.pools_box.count(), 2)

    def test_overview_shows_all_five_metrics(self):
        """★ 工坊那五个指标都要有：总抽 / 平均出金 / 不歪率 / 每UP角色 / 每UP武器。"""
        widget = self._widget()
        report = gacha.GachaReport(pools=[
            make_pool("角色活动唤取", [(3, "a1"), (5, "a2")]),
        ])
        widget.render(report)
        self.app.processEvents()
        for attr in ("stat_total", "stat_avg", "stat_not_up",
                     "stat_fives", "stat_up_char", "stat_up_weapon"):
            self.assertTrue(hasattr(widget, attr), f"少了 {attr}")

    def test_empty_report_shows_hint(self):
        widget = self._widget()
        widget.render(gacha.GachaReport())
        self.app.processEvents()
        self.assertEqual(widget.stat_total.value_label.text(), "0")
        # 没数据时给一句提示，而不是一片空白
        self.assertGreaterEqual(widget.pools_box.count(), 1)

    def test_bad_link_shows_message_not_crash(self):
        """粘错链接 → 界面上出提示，不弹异常。"""
        widget = self._widget()
        widget.link_edit.setText("https://www.bilibili.com/x")
        widget.start_fetch()                 # 不该抛
        self.app.processEvents()
        self.assertTrue(widget.status.text())

    def test_ui_text_has_no_markdown_stars(self):
        """★ 界面文案里**不能有 Markdown 星号**。

        Qt 的 QLabel/CaptionLabel **不解析 markdown** —— 写了 ``**加粗**``
        会原样显示成星号（实测踩过）。这类问题只能靠"渲染出来看一眼"发现，
        所以用测试钉住：界面上所有可见文字里不该出现 ``**``。
        """
        from qfluentwidgets import CaptionLabel

        widget = self._widget()
        offenders = [
            label.text()[:60]
            for label in widget.findChildren(CaptionLabel)
            if label.text() and "**" in label.text()
        ]
        self.assertEqual(offenders, [], f"界面文案里有 Markdown 星号：{offenders}")

    def test_page_has_grab_button_and_hint(self):
        """页面要有「获取抽卡记录」按钮 + 手动粘贴的兜底入口。

        用户 2026-09-30 要求："上面加个获取抽卡记录按钮，获取到后自动填充"。
        """
        widget = self._widget()
        self.assertTrue(hasattr(widget, "grab_button"), "少了「获取抽卡记录」按钮")
        self.assertIn("获取", widget.grab_button.text())
        # 手动粘贴那条路仍在（自动获取失败时的兜底）
        self.assertTrue(hasattr(widget, "link_edit"))
        self.assertTrue(hasattr(widget, "fetch_button"))

    def test_grab_success_fills_link_edit(self):
        """★ 获取到的链接要**自动填充**到输入框。"""
        widget = self._widget()
        sample = ("https://aki-gm-resources.aki-game.com/aki/gacha/"
                  "index.html#/record?svr_id=S&player_id=P&record_id=R"
                  "&resources_id=Q&platform=PC")
        widget._on_grabbed(sample)
        self.assertEqual(widget.link_edit.text(), sample)
        self.assertTrue(widget.grab_button.isEnabled(), "按钮要恢复可用")

    def test_grab_failure_keeps_manual_path(self):
        """自动获取失败 → 出提示，且输入框仍可用（走手动粘贴）。"""
        widget = self._widget()
        widget._on_grab_failed("没找到游戏日志")
        self.app.processEvents()
        self.assertTrue(widget.link_edit.isEnabled())
        self.assertTrue(widget.grab_button.isEnabled())

    def test_tool_is_not_coming_soon(self):
        """★ 别忘关 coming_soon —— 默认 True 会让它显示成"即将到来"占位页。"""
        from src.core.registry import ToolRegistry

        import src.tools as tools_pkg

        ToolRegistry.discover(tools_pkg)
        meta = ToolRegistry.get_meta("gacha")
        self.assertIsNotNone(meta, "gacha 工具没注册上")
        self.assertFalse(meta.coming_soon)


if __name__ == "__main__":
    unittest.main(verbosity=2)
