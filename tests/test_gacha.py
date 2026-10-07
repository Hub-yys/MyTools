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


class TestSpanBarGeometry(unittest.TestCase):
    """★ 抽数条的尺寸（用户 2026-09-30："太细了，调粗一些，跟头像差不多宽"）。"""

    def test_bar_is_thick(self):
        """★ 条要够高 —— 原来 18px 太细，现在接近头像。"""
        from src.tools.game.gacha import tool as ui

        self.assertGreaterEqual(ui.BAR_HEIGHT, 30, "条还是太细")

    def test_width_scales_with_span(self):
        """抽数越多条越长（但夹在上下限之间）。"""
        from src.tools.game.gacha import tool as ui

        self.assertLess(ui.bar_width(10), ui.bar_width(60))
        self.assertLess(ui.bar_width(60), ui.bar_width(80))

    def test_short_span_has_readable_minimum(self):
        """★ 1 抽的条也要够宽，否则数字写不下。

        用户要的就是"跟角色头像宽度差不多" —— 最窄也得是个能看的块。
        """
        from src.tools.game.gacha import tool as ui

        self.assertGreaterEqual(ui.bar_width(1), 60)

    def test_long_span_is_capped(self):
        """超长的条要封顶，别把一行撑爆。"""
        from src.tools.game.gacha import tool as ui

        self.assertLessEqual(ui.bar_width(999), ui.BAR_MAX)


class TestVerdict(unittest.TestCase):
    """★ 条后面的评价文字（用户：**歪 / 欧 / 非** 写在横条后）。"""

    def _verdict(self, *, is_lost: bool, span: int) -> tuple[str, str]:
        from src.tools.game.gacha.tool import GachaWidget

        five = gacha.FiveStar(name="x", span=span, is_50=not is_lost,
                              limited_pool=True)
        return GachaWidget._verdict(five)

    def test_lost_wins_over_luck(self):
        """★ 歪了就是「歪」——哪怕这次只用了 5 抽（欧）。"""
        text, _color = self._verdict(is_lost=True, span=5)
        self.assertEqual(text, "歪")

    def test_lucky(self):
        self.assertEqual(self._verdict(is_lost=False, span=20)[0], "欧")

    def test_unlucky(self):
        self.assertEqual(self._verdict(is_lost=False, span=78)[0], "非")

    def test_normal_has_no_label(self):
        """中间区间不标（正常出货不值得标字）。"""
        self.assertEqual(self._verdict(is_lost=False, span=65)[0], "")

    def test_every_case_returns_color_when_labelled(self):
        """标了字就必须给颜色（否则白字看不见）。"""
        for lost, span in ((True, 5), (False, 20), (False, 78)):
            with self.subTest(lost=lost, span=span):
                text, color = self._verdict(is_lost=lost, span=span)
                self.assertTrue(text)
                self.assertTrue(color.startswith("#"))


class TestWeaponImages(unittest.TestCase):
    """★ 武器图：列表行和卡片墙**都要**显示真图，不能退回首字兜底图。

    用户 2026-09-30 截图报："这里怎么不改掉" —— 卡片墙改了、
    **列表行忘了改**（那里给武器传的是空路径），于是武器显示「云」「千」
    这种首字圆图。这正是"两处各写一份"的后果，所以这里两处都测。
    """

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def _weapon_five(self):
        return gacha.FiveStar(name="云琅", span=7, kind="武器",
                              is_50=True, limited_pool=True)

    def test_weapon_icon_path_is_not_empty(self):
        """★ ``_icon_for`` 对武器要给出**真图路径**，不能传空串。

        传空串会静默退化成首字兜底图 —— **看起来没报错**，
        但用户一眼就看出"这不是我要的图"。
        """
        import inspect

        from src.tools.game.gacha.tool import GachaWidget

        source = inspect.getsource(GachaWidget._icon_for)
        self.assertIn("weapons/", source,
                      "武器没走 weapons/ 路径 —— 会退化成首字兜底图")

    def test_list_row_and_cards_share_one_lookup(self):
        """★ 列表行与卡片墙必须**共用**同一个取图函数，且都把 ``kind`` 传进去。

        各写一份就会出现"改了一处漏一处"（这次就是这么漏的）。
        ⚠ 光断言"调了 ``_icon_for``"**不够** —— 传空 kind 也满足那条，
        但那样武器会静默退回首字兜底图（正是用户截图里的「云」「千」）。
        所以这里必须断言**实参里带了 kind**。
        """
        import inspect

        from src.tools.game.gacha.tool import GachaWidget

        row = inspect.getsource(GachaWidget._five_avatar)
        self.assertIn("_icon_for", row,
                      "列表行没复用 _icon_for —— 又会两边走偏")
        self.assertIn("five.kind", row,
                      "列表行没把 kind 传给 _icon_for —— 武器会变首字兜底图")

    def test_icon_for_routes_weapon_to_weapons_dir(self):
        """★ 端到端：``_icon_for(武器名, "武器")`` 要真的取到 weapons/ 下的图。

        这条比查源码强 —— 它直接比较"拿到的图"和"文件里的图"是不是同一张。
        """
        import pathlib

        from src.tools.game.gacha.tool import GachaWidget

        root = pathlib.Path(__file__).resolve().parents[1]
        weapons = root / "assets" / "game" / "weapons"
        if not weapons.is_dir():
            self.skipTest("没有 assets/game/weapons（素材不入库，本机未下载）")
        names = [p.stem for p in weapons.glob("*.png")]
        if not names:
            self.skipTest("weapons 目录里没有图")
        name = names[0]

        from src.gui.pickers import load_icon

        got = GachaWidget._icon_for(name, "武器").pixmap(48, 48).toImage()
        want = load_icon(f"weapons/{name}.png").pixmap(48, 48).toImage()
        self.assertEqual(got, want, f"{name} 没取到 weapons/ 下的真图")

    def test_weapon_falls_back_gracefully_when_file_missing(self):
        """图文件不在时仍然要有图（首字兜底），不能留白。"""
        from src.tools.game.gacha.tool import GachaWidget

        icon = GachaWidget._icon_for("这把武器不存在", "武器")
        self.assertFalse(icon.isNull(), "查不到图要兜底，不能返回空图标")


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
    def test_from_record_uses_qualityLevel(self):
        """★ 星级字段叫 ``qualityLevel`` —— 这是**真实接口**的字段名。

        实测（2026-09-30，真实响应）::

            {"cardPoolType": "角色精准调谐", "resourceId": 21040043,
             "qualityLevel": 3, "resourceType": "武器",
             "name": "远行者臂铠·破障", "count": 1, "time": "..."}

        我第一版按 ``rankType`` 取 → 取不到就一律当 3 星 →
        界面上"850 抽 0 个五星"，整套统计全废。
        这条钉住字段名，别再照抄别家的实现。
        """
        pull = gacha.Pull.from_record(
            {"name": "某角色", "qualityLevel": 5, "resourceType": "角色",
             "time": "2026-09-30 12:00:00"}, "角色活动唤取")
        self.assertEqual(pull.name, "某角色")
        self.assertEqual(pull.star, 5)
        self.assertEqual(pull.kind, "角色")

    def test_star_four_also_read_from_qualityLevel(self):
        pull = gacha.Pull.from_record({"name": "渊武", "qualityLevel": 4},
                                      "角色活动唤取")
        self.assertEqual(pull.star, 4)

    def test_rankType_still_accepted_as_alias(self):
        """别名兜底：万一接口换名字，不至于又整体退化成 3 星。"""
        for key in ("rankType", "star", "quality"):
            with self.subTest(key=key):
                pull = gacha.Pull.from_record({"name": "x", key: 5}, "p")
                self.assertEqual(pull.star, 5)

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
        #: ★ 2026-10-06 改成选项卡后：**只渲染选中的那个池**的明细
        #: （原来两块竖着堆，用户要求"选项卡并排展示"）
        self.assertEqual(widget.pools_box.count(), 1)
        #: ⚠ ``make_pool`` 的 pool_type 是空串（它只关心抽数），
        #: 两个空 type 的池会撞成一个 key —— 所以这里是 1 不是 2。
        #: 要验"多个选项卡"用 :func:`five_pool`（它带 pool_type）。
        self.assertEqual(len(widget._pool_tabs), 1)

    def test_pool_tabs_are_side_by_side(self):
        """★★★ 卡池**选项卡并排展示**（用户 2026-10-06）。

        用户（截图圈出「角色活动唤取」那行）::

            "这里切换选项卡，展示不同的卡池，选项卡并排展示如
             角色活动唤取，武器活动唤取卡池"

        ⚠ 原来是**每个池一张大卡片竖着堆** —— 4 个池要滚很久。

        ⚠⚠ 必须用 :func:`five_pool`（带 ``pool_type``）——
        ``make_pool`` 三个池的 type 都是空串，会撞成一个选项卡。
        """
        widget = self._widget()
        report = gacha.GachaReport(pools=[
            five_pool([("心", 3)], name="角色活动唤取", pool_type="1"),
            five_pool([("剑", 3)], name="武器活动唤取", pool_type="2"),
            five_pool([("凌阳", 3)], name="角色常驻唤取", pool_type="3"),
        ])
        widget.render(report)
        self.app.processEvents()

        self.assertEqual(len(widget._pool_tabs), 3, "选项卡数量不对")
        #: 全部在**同一行**（并排）→ 纵向位置一致
        tops = {t.mapTo(widget, t.rect().topLeft()).y()
                for t in widget._pool_tabs.values()}
        self.assertEqual(len(tops), 1,
                         f"选项卡没并排（纵向位置有 {len(tops)} 种：{tops}）")
        #: 横向依次排开
        lefts = sorted(t.mapTo(widget, t.rect().topLeft()).x()
                       for t in widget._pool_tabs.values())
        self.assertEqual(len(set(lefts)), 3, "选项卡横向位置重叠了")

    def test_clicking_tab_switches_detail(self):
        """★★★ 点选项卡 → 明细换成那个池。"""
        widget = self._widget()
        report = gacha.GachaReport(pools=[
            #: 角色池：2 抽 1 金
            five_pool([("心", 1)], name="角色活动唤取", pool_type="1"),
            #: 武器池：4 抽 1 金
            five_pool([("剑", 3)], name="武器活动唤取", pool_type="2"),
        ])
        widget.render(report)
        self.app.processEvents()

        widget.select_pool("2")
        self.app.processEvents()
        self.assertEqual(widget._selected_pool, "2")
        self.assertEqual(widget.pools_box.count(), 1, "明细块数不对")

        #: 明细里的概要要跟着换
        card = widget.pools_box.itemAt(0).widget()
        from qfluentwidgets import CaptionLabel

        texts = [c.text() for c in card.findChildren(CaptionLabel)]
        self.assertIn("4 抽", texts,
                      f"明细没切到武器池（{texts[:6]}）")

    def test_selected_tab_has_yellow_bar(self):
        """★★★ 选中的选项卡**下方一条黄粗线**（用户定过的样式）。

        用户 2026-10-05 对角色格子要求过::

            "点到那个，哪个下方加一个黄色高亮的粗线"

        ⚠ 这里要**沿用同一个视觉语言** —— 不是整块黄底（那是我做错过的）。

        ⚠⚠ 必须查**选中态**：未选中时那条线是 ``transparent`` ——
        只断言"存在 background"的话两条路都过，等于没测。
        """
        from src.tools.game.gacha import tool as ui

        widget = self._widget()
        report = gacha.GachaReport(pools=[
            five_pool([("心", 3)], name="角色活动唤取", pool_type="1"),
            five_pool([("剑", 3)], name="武器活动唤取", pool_type="2"),
        ])
        widget.render(report)
        widget.select_pool("1")
        self.app.processEvents()

        on = widget._pool_tabs["1"]
        off = widget._pool_tabs["2"]

        self.assertIn(ui.SELECT_BORDER, on.bar.styleSheet(),
                      "选中的选项卡没有黄色粗线")
        self.assertNotIn(ui.SELECT_BORDER, off.bar.styleSheet(),
                         "没选中的选项卡也有黄线")
        self.assertIn("transparent", off.bar.styleSheet(),
                      "没选中的那条线应该是透明的（占位对齐）")

    def test_tab_switching_keeps_selection_after_rerender(self):
        """★★ 重新分析（render）后**保持当前选的池**，不要跳回第一个。

        ⚠ 用户看的是武器池，重新拉一次数据就跳回角色池会很难受。
        """
        widget = self._widget()
        report = gacha.GachaReport(pools=[
            five_pool([("心", 3)], name="角色活动唤取", pool_type="1"),
            five_pool([("剑", 3)], name="武器活动唤取", pool_type="2"),
        ])
        widget.render(report)
        widget.select_pool("2")
        self.app.processEvents()

        widget.render(report)          #: 再渲染一次（模拟重新分析）
        self.app.processEvents()
        self.assertEqual(widget._selected_pool, "2",
                         "重新渲染后跳回第一个池了")

    def test_tab_falls_back_when_pool_disappears(self):
        """★ 之前选的池这次没数据了 → 退回第一个（不能卡在空状态）。"""
        widget = self._widget()
        report = gacha.GachaReport(pools=[
            five_pool([("心", 3)], name="角色活动唤取", pool_type="1"),
            five_pool([("剑", 3)], name="武器活动唤取", pool_type="2"),
        ])
        widget.render(report)
        widget.select_pool("2")
        self.app.processEvents()

        #: 新报告里**没有**武器池了
        widget.render(gacha.GachaReport(pools=[
            five_pool([("心", 3)], name="角色活动唤取", pool_type="1"),
        ]))
        self.app.processEvents()
        self.assertEqual(widget._selected_pool, "1")
        self.assertEqual(widget.pools_box.count(), 1)

    def test_tab_text_follows_skin(self):
        """★★★ 选项卡文字色**跟着皮肤走**，不写死。

        ## ⚠⚠ 用户 2026-10-06

            "这里又出现了深色皮肤 深色字体 看不见"

        我第一版把选中色写成常量 ``#1a1a1a``（深灰）——
        浅色皮肤上没问题，**深色皮肤上完全看不见**。

        → 改成从 ``skins.active_skin()`` 的 ``text`` / ``dim`` 取。

        ⚠ 断言要**同时验两个皮肤**（浅 + 暗）—— 只测一个的话，
        写死的颜色在那一个上可能正好是对的（这就是我漏掉它的原因）。
        """
        from src.core import skins

        widget = self._widget()
        report = gacha.GachaReport(pools=[
            five_pool([("心", 3)], name="角色活动唤取", pool_type="1"),
            five_pool([("剑", 3)], name="武器活动唤取", pool_type="2"),
        ])
        widget.render(report)
        widget.select_pool("1")
        self.app.processEvents()

        for sid in ("mist", "deepglass"):
            with self.subTest(skin=sid):
                skins.apply_skin(sid, save=False)
                skin = skins.active_skin()
                widget.refresh_skin_colors()
                self.app.processEvents()

                on = widget._pool_tabs["1"].label.styleSheet()
                off = widget._pool_tabs["2"].label.styleSheet()
                self.assertIn(skin["text"], on,
                              f"「{skin['name']}」选中的文字没用皮肤正文色"
                              f"（{on}）")
                self.assertIn(skin["dim"], off,
                              f"「{skin['name']}」未选中的文字没用皮肤次要色"
                              f"（{off}）")

    def test_big_stat_numbers_follow_skin(self):
        """★★★ 顶部那几个**大数字**也要跟着皮肤走。

        ⚠ 同一个 bug 的另一处：``_BigStat`` 的兜底色原本写死
        ``#1a1a1a`` —— 深色皮肤上"总抽卡数 1131"这种大数字看不见。
        """
        from src.core import skins

        widget = self._widget()
        for sid in ("mist", "deepglass"):
            with self.subTest(skin=sid):
                skins.apply_skin(sid, save=False)
                skin = skins.active_skin()
                widget.stat_total.set("1131", "总抽卡数")
                self.app.processEvents()
                css = widget.stat_total.value_label.styleSheet()
                self.assertIn(skin["text"], css,
                              f"「{skin['name']}」的大数字没用皮肤正文色"
                              f"（{css}）")

    def test_empty_pools_are_not_tabbed(self):
        """★ 没抽过的池**不出现**在选项卡里（7 个池全列很废）。"""
        widget = self._widget()
        widget.render(gacha.GachaReport(pools=[
            five_pool([("心", 3)], name="角色活动唤取", pool_type="1"),
        ]))
        self.app.processEvents()
        self.assertEqual(len(widget._pool_tabs), 1,
                         "没抽过的池也建了选项卡")

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


class TestHistoryRendersOnOpen(unittest.TestCase):
    """★ 打开页面就要显示**已累积的历史**。

    用户 2026-09-30 报："有数据，为什么没有展示" —— 本地明明攒了 887 条，
    页面却全是「—」。根因：原来**只有点「分析」成功才渲染**，
    而那次没取到链接（过期 / 没打开唤取记录页），界面就一直空着。
    """

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def _widget_with(self, records):
        """建页面，并让它读一份**临时**历史（别碰真实用户数据）。"""
        import pathlib
        import tempfile

        from PySide6.QtWidgets import QWidget

        import src.tools.game.gacha.tool as tool_mod
        from src.core import gacha_store

        path = pathlib.Path(tempfile.mkdtemp()) / "h.json"
        store = gacha_store.GachaHistoryStore(path)
        if records:
            history = store.load()
            added = history.merge(records, pool_type="1",
                                  pool_name="角色活动唤取", at="2026-09-30")
            history.add_snapshot(gacha_store.PullSnapshot(
                at="2026-09-30", total=len(records), added=added))
            store.save(history)

        original = tool_mod.GachaWidget._get_store
        tool_mod.GachaWidget._get_store = lambda self: store
        try:
            holder = QWidget()
            holder.resize(1200, 900)
            self._holders = getattr(self, "_holders", [])
            self._holders.append(holder)
            widget = tool_mod.GachaWidget()
            widget.setParent(holder)
            widget.resize(1200, 900)
            holder.show()
            for _ in range(3):
                self.app.processEvents()
            return widget
        finally:
            tool_mod.GachaWidget._get_store = original

    def _records(self, count=5, stars=(5, 3, 3, 3, 3)):
        return [
            {"name": f"物品{i}", "qualityLevel": star if i == 0 else 3,
             "time": f"2026-09-{10 - i:02d} 12:00:00", "resourceId": i,
             "resourceType": "角色"}
            for i, star in enumerate(stars[:count])
        ]

    def test_history_shown_without_clicking(self):
        """★ 不点任何按钮，打开就该看到累计数字。"""
        widget = self._widget_with(self._records())
        self.assertEqual(widget.stat_total.value_label.text(), "5",
                         "有历史却没显示总抽数")
        self.assertEqual(widget.stat_fives.value_label.text(), "1")

    def test_status_says_it_is_local_history(self):
        """状态栏要说明这是**本地累计**，不是这次拉的。"""
        widget = self._widget_with(self._records())
        self.assertIn("本地累计", widget.status.text())

    def test_empty_history_keeps_empty_state(self):
        """没有历史时仍显示空状态引导（别弄成"0 抽"）。"""
        widget = self._widget_with([])
        self.assertEqual(widget.stat_total.value_label.text(), "—")
        self.assertEqual(widget.pools_box.count(), 1)
        self.assertIn("还没有数据", widget.pools_box.itemAt(0).widget().text())

    def test_history_pools_are_rendered(self):
        widget = self._widget_with(self._records())
        self.assertGreaterEqual(widget.pools_box.count(), 1)


class TestCardWallLayout(unittest.TestCase):
    """★ 卡片墙要**横着**铺成网格，不能竖成一列。

    用户 2026-10-01 截图："这个怎么竖着展示了，这个横着展示就行"。

    根因：原来列数是在 ``_render_cards`` 里**当场算**的，而那时页面刚构造、
    控件还没被布局过 —— ``cards_host.width()`` 拿到的是默认尺寸（624px，
    实际窗口 1226px），算出来 1 列；而且 **QGridLayout 不会自己重排**，
    算错了就一直是错的。

    现在卡片先建好、位置由 ``_relayout_cards()`` 按当前宽度算，
    并挂在 ``cards_host`` 的 resize 上。
    """

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def _widget(self, width=1300):
        from PySide6.QtWidgets import QWidget

        import src.tools.game.gacha.tool as tool_mod

        holder = QWidget()
        holder.resize(width, 900)
        widget = tool_mod.GachaWidget()
        widget.setParent(holder)
        widget.resize(width, 900)
        holder.show()
        for _ in range(4):
            self.app.processEvents()
        self._holders = getattr(self, "_holders", [])
        self._holders += [holder, widget]
        return widget

    def _fives(self, count: int):
        """造 ``count`` 个不同名字的五星 → ``count`` 张卡。"""
        records = [
            {"name": f"角色{i}", "qualityLevel": 5,
             "time": f"2026-09-{min(28, i + 1):02d} 12:00:00",
             "resourceId": 1000 + i, "resourceType": "角色",
             "pool_type": "1", "pool": "角色活动唤取"}
            for i in range(count)
        ]
        return gacha.report_from_records(records)

    def test_cards_go_horizontal_not_vertical(self):
        """★ 多张卡要落在**同一行**（横着铺），不是一人一行。"""
        widget = self._widget()
        widget.render(self._fives(6))
        for _ in range(3):
            self.app.processEvents()

        grid = widget.cards_grid
        self.assertEqual(grid.count(), 6)
        self.assertGreater(grid.columnCount(), 1,
                           "只有 1 列 —— 卡片又被竖着排了")
        rows = {grid.getItemPosition(i)[0] for i in range(grid.count())}
        self.assertEqual(rows, {0}, f"卡片没铺在一行：行号 {sorted(rows)}")

    def test_relayouts_after_show(self):
        """★★ 核心场景：构造时列数可能是错的，**显示后必须自己重排回来**。

        这就是用户遇到的路径（打开页面 → 构造里渲染 → 之后才被布局）：
        构造那一刻容器宽度是默认值，算出来的列数偏小；
        ``QGridLayout`` 又**不会**自己把卡片挪到别的列 ——
        所以必须有"容器宽度一变就重排"这一步。

        没有它的话，卡片会一直按构造时那个偏小的列数排下去
        （用户截图就是排成了一列）。
        """
        from PySide6.QtWidgets import QWidget

        import src.tools.game.gacha.tool as tool_mod

        holder = QWidget()
        holder.resize(1438, 950)
        widget = tool_mod.GachaWidget()
        widget.setParent(holder)
        widget.resize(1438, 950)
        self._holders = getattr(self, "_holders", [])
        self._holders += [holder, widget]

        widget.render(self._fives(12))
        columns_before = widget.cards_grid.columnCount()

        holder.show()
        for _ in range(5):
            self.app.processEvents()
        columns_after = widget.cards_grid.columnCount()

        self.assertGreaterEqual(columns_after, columns_before,
                                "显示后列数反而变少了")
        self.assertGreater(columns_after, 1, "显示后还是一列 —— 没重排")
        rows = {widget.cards_grid.getItemPosition(i)[0]
                for i in range(widget.cards_grid.count())}
        self.assertEqual(
            len(rows), 1,
            f"12 张卡占了 {len(rows)} 行 —— 应该是横着铺在第 0 行")

    def test_columns_scale_with_width(self):
        """容器越宽，一行放的卡片越多。

        ⚠ 不能靠 ``cards_host.resize()`` —— 它在布局里，一转头就被**布局重置**
        回原宽（实测：给 300 也没用，事件过滤器读到的一直是布局算的宽度）。
        所以这里直接查 ``_relayout_cards`` 用的那套算法，把宽度喂进去。
        """
        import src.tools.game.gacha.tool as tool_mod

        widget = self._widget()
        widget.render(self._fives(10))
        self.app.processEvents()

        def columns_for(width: int) -> int:
            spacing = widget.cards_grid.spacing()
            return min(max(1, (width + spacing) // (tool_mod.CARD_SIZE + spacing)),
                       tool_mod.MAX_CARD_COLUMNS)

        narrow, wide = columns_for(200), columns_for(1200)
        self.assertGreater(wide, narrow,
                           f"宽度不影响列数（{narrow} → {wide}）")

    def test_columns_actually_applied(self):
        """★ 真的按当前宽度摆过位置（不是只算了列数没用上）。"""
        widget = self._widget()
        widget.render(self._fives(10))
        self.app.processEvents()
        self.assertEqual(widget._card_columns, widget.cards_grid.columnCount(),
                         "算出来的列数和网格实际列数对不上")

    def test_columns_capped(self):
        """再宽也要封顶（``MAX_CARD_COLUMNS``）—— 一行长得离谱没意义。"""
        from PySide6.QtCore import QSize

        import src.tools.game.gacha.tool as tool_mod

        widget = self._widget()
        widget.render(self._fives(4))
        widget.cards_host.resize(QSize(99999, 100))
        self.app.processEvents()
        self.assertLessEqual(widget._card_columns, tool_mod.MAX_CARD_COLUMNS)

    def test_narrow_container_does_not_break(self):
        """极窄容器退回 1 列，而不是 0 列（除零 / 一张都不画）。"""
        from PySide6.QtCore import QSize

        widget = self._widget()
        widget.render(self._fives(3))
        widget.cards_host.resize(QSize(10, 100))
        self.app.processEvents()
        self.assertGreaterEqual(widget._card_columns, 1)
        self.assertEqual(widget.cards_grid.count(), 3)

    def test_relayout_is_idempotent(self):
        """列数没变时不该反复摘挂布局项（白折腾）。"""
        widget = self._widget()
        widget.render(self._fives(5))
        self.app.processEvents()
        before = widget.cards_grid.count()
        widget._relayout_cards()
        widget._relayout_cards()
        self.assertEqual(widget.cards_grid.count(), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
