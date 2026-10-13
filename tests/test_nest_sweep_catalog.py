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
    catalog_by_kind,
    catalog_path,
    find_target,
    load_catalog,
    parse_catalog,
    parse_target,
)


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

    def test_sorted_by_kind_then_order_then_name(self):
        """分类（聚落在前）→ order → 名称。"""
        raw = {"targets": [
            {"name": "N2", "kind": KIND_NIGHTMARE, "order": 1},
            {"name": "P2", "kind": KIND_NEST, "order": 2},
            {"name": "P1", "kind": KIND_NEST, "order": 1},
        ]}
        got = [t.name for t in parse_catalog(raw)]
        self.assertEqual(got, ["P1", "P2", "N2"])

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


if __name__ == "__main__":
    unittest.main()
