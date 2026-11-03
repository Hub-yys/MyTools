# -*- coding: utf-8 -*-
"""目标清单的解析与排序（``src/core/nest_sweep/catalog.py``）。

## 这个测试在保什么

清单是**用户手改的文件**，所以它的容错本身就是功能：

* 一条写坏了**不能**让整个工具页变空（那是"改了没生效"的经典体验）
* ``order`` 相同时顺序必须**确定**（否则每次刷新卡片顺序都在跳）
* ``key`` 重复必须挡住（否则"勾一个另一个跟着亮"）
* 名称匹配要**长的优先**（``梦魇·刺玫菇（稚形）`` vs ``梦魇·刺玫菇``）
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.core.nest_sweep.catalog import (  # noqa: E402
    KIND_NEST,
    KIND_NIGHTMARE,
    SweepTarget,
    _version_key,
    catalog_by_kind,
    catalog_path,
    find_target,
    load_catalog,
    parse_catalog,
    parse_target,
)


def _ver_tuple(text: str) -> tuple:
    """把版本号变成**可正序比**的元组（复用生产代码的解析，但不取负）。

    :func:`catalog._version_key` 返回的是"取负版"（为了倒序），
    这里取回来方便断言"版本非递增"。
    """
    _flag, *rest = _version_key(text)
    return tuple(-n for n in rest)


class TestParseTarget(unittest.TestCase):
    """单条记录的解析。"""

    def test_minimal_record(self):
        """只写 name 也能用 —— 其余字段全有默认值。"""
        target = parse_target({"name": "某聚落"})
        self.assertIsNotNone(target)
        self.assertEqual(target.name, "某聚落")
        self.assertEqual(target.kind, KIND_NEST)
        #: key 自动派生：``分类:名称``
        self.assertEqual(target.key, f"{KIND_NEST}:某聚落")
        self.assertTrue(target.verified)

    def test_no_name_is_rejected(self):
        """没有名字的记录直接丢掉（没有名字就没法显示、也没法匹配）。"""
        self.assertIsNone(parse_target({"kind": KIND_NEST}))
        self.assertIsNone(parse_target({"name": "   "}))
        self.assertIsNone(parse_target("不是字典"))

    def test_bad_kind_falls_back_to_nest(self):
        """分类写错**不丢记录**，退化成 nest。

        ⚠ 这是刻意的：用户加新条目时最容易忘的就是 kind，
        丢掉会让人以为"我改了但没生效"，而退化成 nest 至少看得见。
        """
        target = parse_target({"name": "X", "kind": "nightmares"})
        self.assertEqual(target.kind, KIND_NEST)

    def test_aliases_accept_string_and_list(self):
        """别名两种写法都收：数组、或逗号 / 顿号分隔的字符串。"""
        from_list = parse_target({"name": "X", "aliases": ["A", "B"]})
        self.assertEqual(from_list.aliases, ("A", "B"))
        from_text = parse_target({"name": "X", "aliases": "A、B，C"})
        self.assertEqual(from_text.aliases, ("A", "B", "C"))

    def test_verified_only_false_marks_unverified(self):
        """只有**显式**写 false 才算未核对。

        缺字段的老数据按"已核对"处理 —— 否则用户自己加的条目
        会莫名其妙挂满「待核对」角标。
        """
        self.assertTrue(parse_target({"name": "X"}).verified)
        self.assertTrue(parse_target({"name": "X", "verified": True}).verified)
        self.assertFalse(parse_target({"name": "X", "verified": False}).verified)

    def test_count_survives_garbage(self):
        """数量写坏了退回 0，不抛异常。"""
        self.assertEqual(parse_target({"name": "X", "count": "abc"}).count, 0)
        self.assertEqual(parse_target({"name": "X", "count": -5}).count, 0)


class TestMatchNames(unittest.TestCase):
    """匹配名列表 —— 长的必须排在前面（这条错了会刷错目标）。"""

    def test_longest_first(self):
        """★ ``梦魇·刺玫菇（稚形）`` 必须排在 ``梦魇·刺玫菇`` 前面。

        否则拿短名先比，稚形那一行会被判成普通刺玫菇 ——
        **勾了 A 却去刷了 B**，而且界面上完全看不出来。
        """
        target = parse_target({
            "name": "梦魇·刺玫菇（稚形）",
            "aliases": ["梦魇·刺玫菇", "刺玫菇"],
        })
        names = target.match_names()
        self.assertEqual(names[0], "梦魇·刺玫菇（稚形）")
        #: 全都要在，且确实是按长度倒序
        self.assertIn("梦魇·刺玫菇", names)
        self.assertIn("刺玫菇", names)
        self.assertEqual(list(names), sorted(names, key=len, reverse=True))

    def test_duplicates_and_blanks_dropped(self):
        """本名和别名重复、空串都要去掉。"""
        target = parse_target({"name": "X", "aliases": ["X", "", "  ", "Y"]})
        self.assertEqual(target.match_names(), ("X", "Y"))


class TestParseCatalog(unittest.TestCase):
    """整份清单的解析。"""

    def test_sorted_by_version_desc_then_order_then_name(self):
        """★ 2026-10-13 用户要求：「整体按照聚落出的时间顺序倒叙排序」。

        即**越新的版本排越前**；同一版本内才看 ``order``、再看名称。
        以前是「先分类（聚落在前）、再 order」，现在品类**不打乱**。
        """
        raw = {"targets": [
            {"name": "旧", "kind": KIND_NIGHTMARE, "version": "2.5", "order": 1},
            {"name": "新", "kind": KIND_NEST, "version": "3.7", "order": 1},
            {"name": "中", "kind": KIND_NEST, "version": "3.0", "order": 1},
        ]}
        got = [t.name for t in parse_catalog(raw)]
        self.assertEqual(got, ["新", "中", "旧"])

    def test_same_version_uses_order_then_name(self):
        """同一版本内：order 小的在前，order 相同按名称。"""
        raw = {"targets": [
            {"name": "B", "version": "3.0", "order": 2},
            {"name": "A", "version": "3.0", "order": 1},
            {"name": "D", "version": "3.0", "order": 2},
            {"name": "C", "version": "3.0", "order": 2},
        ]}
        self.assertEqual([t.name for t in parse_catalog(raw)],
                         ["A", "B", "C", "D"])

    def test_version_compared_numerically_not_as_text(self):
        """★★ 版本号必须**按数字**比，不能比字符串。

        ``"2.10" < "2.5"`` 在字符串序里成立 —— 但 2.10 明显更新。
        真版本号迟早会出现两位数小版本（2.10 / 3.10），那时字符串序就错了，
        而且**错得毫无提示**（只是顺序看着有点怪）。
        """
        raw = {"targets": [
            {"name": "二五", "version": "2.5"},
            {"name": "二十", "version": "2.10"},
            {"name": "三九", "version": "3.9"},
            {"name": "三十", "version": "3.10"},
        ]}
        self.assertEqual([t.name for t in parse_catalog(raw)],
                         ["三十", "三九", "二十", "二五"])

    def test_no_version_goes_last(self):
        """没有版本号的排**最后**（不是最前）。

        它们在数据文件里通常是"还没核实的新条目"，
        排最前会盖住有据可查的那些。
        """
        raw = {"targets": [
            {"name": "没版本"},
            {"name": "有二五", "version": "2.5"},
        ]}
        self.assertEqual([t.name for t in parse_catalog(raw)],
                         ["有二五", "没版本"])

    def test_same_order_is_deterministic(self):
        """★ ``order`` 相同时按名称排 —— 顺序必须**确定**。

        只按 order 排的话顺序取决于 JSON 书写顺序：看起来能用，
        但每次读都可能不一样，卡片会莫名其妙地跳。
        """
        raw = {"targets": [
            {"name": "丙", "order": 0},
            {"name": "甲", "order": 0},
            {"name": "乙", "order": 0},
        ]}
        got = [t.name for t in parse_catalog(raw)]
        self.assertEqual(got, sorted(["甲", "乙", "丙"]))
        #: 读两遍结果必须一样
        self.assertEqual(got, [t.name for t in parse_catalog(raw)])

    def test_real_catalog_is_newest_first(self):
        """★ 真清单：第一张卡片必须是**最新版本**那一处（3.7 梦枢天罗）。"""
        items = load_catalog()
        if not items:
            self.skipTest("清单为空")
        self.assertEqual(items[0].name, "梦枢天罗残像聚落")
        #: 版本号必须**非递增**
        versions = [_ver_tuple(t.version) for t in items]
        self.assertEqual(versions, sorted(versions, reverse=True),
                         f"版本没有倒序: {[t.version for t in items]}")

    def test_same_order_is_deterministic(self):
        """★ ``order`` 相同时按名称排 —— 顺序必须**确定**。

        只按 order 排的话顺序取决于 JSON 书写顺序：看起来能用，
        但每次读都可能不一样，卡片会莫名其妙地跳。
        """
        raw = {"targets": [
            {"name": "丙", "order": 0},
            {"name": "甲", "order": 0},
            {"name": "乙", "order": 0},
        ]}
        got = [t.name for t in parse_catalog(raw)]
        self.assertEqual(got, sorted(["甲", "乙", "丙"]))
        #: 读两遍结果必须一样
        self.assertEqual(got, [t.name for t in parse_catalog(raw)])

    def test_duplicate_key_dropped(self):
        """★ key 撞车必须挡住。

        存盘按 key 记勾选 —— 重复 key 会让"勾了这条，那条也亮"，
        是个很难查的怪现象。
        """
        raw = {"targets": [
            {"key": "same", "name": "第一个"},
            {"key": "same", "name": "第二个"},
        ]}
        got = parse_catalog(raw)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0].name, "第一个")

    def test_one_bad_record_does_not_kill_the_rest(self):
        """★ 一条写坏**不能**让整份清单作废。"""
        raw = {"targets": [
            {"name": "好的"},
            "整个不是字典",
            {"没有名字": True},
            {"name": "也好"},
        ]}
        got = parse_catalog(raw)
        self.assertEqual({t.name for t in got}, {"好的", "也好"})

    def test_garbage_input(self):
        """完全不是清单形状时返回空，不抛异常。"""
        for bad in (None, "字符串", [], {"targets": "不是列表"}, {}):
            self.assertEqual(parse_catalog(bad), ())


class TestRealCatalog(unittest.TestCase):
    """★ 走**仓库里那份真实数据**，不是自己造的样例。"""

    def setUp(self):
        self.items = load_catalog()

    def test_bundled_catalog_loads(self):
        """随程序分发的那份必须能读出来、且非空。"""
        self.assertTrue(catalog_path().is_file(),
                        "缺少数据文件：%s" % catalog_path())
        self.assertGreater(len(self.items), 0, "清单是空的，工具页会一片空白")

    def test_both_kinds_present(self):
        """残像聚落和梦魇残像**两类都要有**（用户要的是"都展示"）。"""
        kinds = {t.kind for t in self.items}
        self.assertIn(KIND_NEST, kinds)
        self.assertIn(KIND_NIGHTMARE, kinds)

    def test_keys_unique(self):
        keys = [t.key for t in self.items]
        self.assertEqual(len(keys), len(set(keys)), "清单里有重复 key")

    def test_every_entry_has_match_names(self):
        """每条都得能匹配（名字非空）。"""
        for target in self.items:
            self.assertTrue(target.match_names(), target.key)

    def test_aliases_cover_both_xiang_spellings(self):
        """★ 官方写法是「残**象**聚落」，用户和 ok-ww 用「残**像**聚落」。

        两条别名都得在，否则一个字之差就会让任务在指南里**找不到那一行**。
        """
        for target in self.items:
            joined = "".join(target.match_names())
            if "残像聚落" in joined:
                self.assertIn("残象聚落", joined,
                              "%s 缺「残象聚落」写法" % target.name)

    def test_grouping_keeps_both_groups(self):
        grouped = catalog_by_kind(self.items)
        self.assertIn(KIND_NEST, grouped)
        self.assertIn(KIND_NIGHTMARE, grouped)

    def test_find_target(self):
        first = self.items[0]
        self.assertIs(find_target(first.key, self.items), first)
        self.assertIsNone(find_target("不存在的 key", self.items))


class TestLoadFailureModes(unittest.TestCase):
    """读盘的各种坏情况 —— 一律返回空，**不抛异常**。"""

    def test_missing_file(self):
        missing = Path(tempfile.gettempdir()) / "绝不存在的清单_12345.json"
        self.assertEqual(load_catalog(missing), ())

    def test_broken_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "broken.json"
            path.write_text("{ 这不是合法 JSON", encoding="utf-8")
            self.assertEqual(load_catalog(path), ())

    def test_valid_json_wrong_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "wrong.json"
            path.write_text(json.dumps(["一个数组"]), encoding="utf-8")
            self.assertEqual(load_catalog(path), ())


class TestSweepTargetHelpers(unittest.TestCase):
    """目标对象上的小工具。"""

    def test_kind_name(self):
        self.assertEqual(SweepTarget("k", "n", KIND_NEST).kind_name, "残像聚落")
        self.assertEqual(SweepTarget("k", "n", KIND_NIGHTMARE).kind_name, "梦魇残像")

    def test_unknown_kind_falls_back_to_raw(self):
        """分类名查不到时显示原样，不是空白。"""
        self.assertEqual(SweepTarget("k", "n", "custom").kind_name, "custom")


class TestTargetSets(unittest.TestCase):
    """★ 目标「能出哪些声骸套装」—— 用户 2026-10-13 要求卡片显示图标+名称。

    数据来自**用户给的游戏内截图**（一手来源），不是攻略站。
    """

    def test_sets_default_is_empty_not_fabricated(self):
        """没写 sets = **不知道**，不是「没有套装」。

        空元组在界面上表现为「不画那一条」，而不是画一个「0 套」——
        后者看起来像「这里什么都不掉」。
        """
        self.assertEqual(SweepTarget("k", "n").sets, ())

    def test_parse_sets_from_list(self):
        t = parse_target({"name": "X", "sets": ["甲", "乙", "丙"]})
        self.assertEqual(t.sets, ("甲", "乙", "丙"))

    def test_parse_sets_from_string(self):
        """手写时逗号 / 顿号分隔也该认（和 aliases 同一套解析）。"""
        t = parse_target({"name": "X", "sets": "甲、乙, 丙"})
        self.assertEqual(t.sets, ("甲", "乙", "丙"))

    def test_parse_sets_drops_blanks(self):
        t = parse_target({"name": "X", "sets": ["甲", "", "  ", "乙"]})
        self.assertEqual(t.sets, ("甲", "乙"))

    def test_parse_sets_wrong_type_is_empty(self):
        """写错类型不能炸（数据文件是手改的）。"""
        for bad in (123, {"a": 1}, None):
            with self.subTest(bad=bad):
                t = parse_target({"name": "X", "sets": bad})
                self.assertEqual(t.sets, ())

    def test_sets_survive_the_real_catalog(self):
        """★ 真清单里**三组**聚落的套装必须对（用户 2026-10-13 确认）。

        分组：① 梦枢天罗 = 落渊南丘（6 套）
              ② 盲望之塌 = 复生丘原 = 陷足流川（7 套）
              ③ 5 处梦魇聚落各 1 套
        """
        targets = {t.name: t for t in load_catalog()}
        six = ("茜染怀想之花", "衔梦照世之心", "镜影流电之瞬",
               "羽落空尘之歌", "清邪荡煞之心", "冥途夜行之灯")
        seven = ("雪落无声之愿", "剪心辑梦之影", "长路启航之星",
                 "斑驳粉饰之沫", "听唤语义之愿", "逆光跃彩之约",
                 "星构寻辉之环")
        solo = {
            "千殁沉岛梦魇聚落": ("失序彼岸之梦",),
            "潮痕岩滩梦魇聚落": ("息界同调之律",),
            "受蚀地梦魇聚落": ("荣斗铸锋之冠",),
            "三王峰梦魇聚落": ("焚羽猎魔之影",),
            "穗波市梦魇聚落": ("命理崩毁之弦",),
        }
        #: ① 两处同样的 6 套
        for name in ("梦枢天罗残像聚落", "落渊南丘残像聚落"):
            with self.subTest(name=name):
                self.assertEqual(targets[name].sets, six)
        #: ② 三处同样的 7 套
        for name in ("盲望之塌残像聚落", "复生丘原残像聚落",
                     "陷足流川残像聚落"):
            with self.subTest(name=name):
                self.assertEqual(targets[name].sets, seven)
        #: ③ 梦魇各 1 套
        for name, want in solo.items():
            with self.subTest(name=name):
                self.assertEqual(targets[name].sets, want)

    def test_no_target_is_missing_sets(self):
        """★ 现在**每一处都有** sets —— 用户把三组都给了。

        留空会被界面当成「不知道」而**不画那一条**，
        所以这条守住"别漏填"（漏了不会报错，只是卡片上少一块）。
        """
        for t in load_catalog():
            with self.subTest(target=t.name):
                self.assertTrue(t.sets, f"{t.name} 没有 sets")

    def test_every_named_set_exists_in_the_set_database(self):
        """★ 引用的套装名必须**真的存在于** ``wuwa_echo_sets.json``。

        写错一个字 → 界面拿不到图标（只剩名字）、用户也搜不到那个套装，
        而且**全程不报错**。
        """
        data = json.loads(
            (ROOT / "src" / "core" / "data" / "wuwa_echo_sets.json")
            .read_text(encoding="utf-8"))
        known = {s["name"] for s in data["sets"]}

        for t in load_catalog():
            for name in t.sets:
                with self.subTest(target=t.name, echo_set=name):
                    self.assertIn(name, known,
                                  f"{t.name} 引用了不存在的套装「{name}」")

    def test_three_groups_stay_identical(self):
        """★ 用户明确说过"这几处一致"，数据必须**一直**一致。

        ① 梦枢天罗 = 落渊南丘（6 套）
        ② 盲望之塌 = 复生丘原 = 陷足流川（7 套）

        ⚠ 别小看这条：**改其中一个而忘了另一个**，界面上会显示两套不同的
        套装清单，而用户以为它们本来就该一样 —— 那会直接导致"刷错地方"。
        """
        groups = [
            ("梦枢天罗残像聚落", "落渊南丘残像聚落"),
            ("盲望之塌残像聚落", "复生丘原残像聚落", "陷足流川残像聚落"),
        ]
        by_name = {t.name: t for t in load_catalog()}
        for group in groups:
            with self.subTest(group=group):
                first = by_name[group[0]].sets
                for other in group[1:]:
                    self.assertEqual(
                        by_name[other].sets, first,
                        f"{other} 和 {group[0]} 的套装不一致"
                        f"（用户说过这几处应该一样）")

    def test_counts_corrected_from_the_screenshot(self):
        """★ 用户截图补全的两处每日数量（此前三路检索都查不到）。

        截图原文：「落渊南丘残像聚落 已击败残象 0/41」
                  「梦枢天罗残像聚落 已击败残象 0/48」
        """
        targets = {t.name: t for t in load_catalog()}
        self.assertEqual(targets["落渊南丘残像聚落"].count, 41)
        self.assertEqual(targets["梦枢天罗残像聚落"].count, 48)


if __name__ == "__main__":
    unittest.main()
