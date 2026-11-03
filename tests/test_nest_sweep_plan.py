# -*- coding: utf-8 -*-
"""执行计划与勾选存盘（``src/core/nest_sweep/plan.py``）。

## 这个测试在保什么

用户要的原话是「**可以一键勾选全部，勾选的运行后，根据顺序一个一个去刷**」。
拆开就是三条必须成立的规矩：

1. **顺序 = 清单顺序**（勾选顺序不算数 —— 用户在文件里调 order 就是为了控制先后）
2. **只刷勾选的**（没勾的一个都不碰）
3. **勾选存得住**（重开程序还在，且清单改了不会错位）

第 3 条是这里最容易出错的：存下标的话，清单中间插一条会让
**勾的东西整体错位**，而且错得悄无声息。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.core.nest_sweep.catalog import (  # noqa: E402
    KIND_NEST,
    KIND_NIGHTMARE,
    SweepTarget,
)
from src.core.nest_sweep.plan import (  # noqa: E402
    build_plan,
    clean_selection,
    selected_targets,
    selection_summary,
)


def make_targets() -> tuple[SweepTarget, ...]:
    """一份小清单：2 个聚落 + 2 个梦魇，**已经按清单顺序排好**。"""
    return (
        SweepTarget(key="nest:A", name="聚落A", kind=KIND_NEST, order=1,
                    region="区域一", count=24, aliases=("A",)),
        SweepTarget(key="nest:B", name="聚落B", kind=KIND_NEST, order=2,
                    region="区域二", count=48),
        SweepTarget(key="nm:C", name="梦魇C", kind=KIND_NIGHTMARE, order=1,
                    region="区域三", count=36),
        SweepTarget(key="nm:D", name="梦魇D", kind=KIND_NIGHTMARE, order=2,
                    region="区域四", count=36),
    )


class TestBuildPlan(unittest.TestCase):
    """勾选 → 有序计划。"""

    def setUp(self):
        self.targets = make_targets()

    def test_order_follows_catalog_not_selection(self):
        """★★ 顺序按**清单**来，不按勾选顺序。

        ⚠ 这是本模块的核心承诺。用户勾选的先后（先点 B 再点 A）
        **不该**影响刷的先后 —— 那是由数据文件里的 order 决定的。
        """
        plan = build_plan(["nest:B", "nest:A"], self.targets)
        self.assertEqual([s.key for s in plan], ["nest:A", "nest:B"])

    def test_only_selected_included(self):
        """没勾的一个都不许进来。"""
        plan = build_plan(["nest:B"], self.targets)
        self.assertEqual([s.key for s in plan], ["nest:B"])
        self.assertEqual(len(plan), 1)

    def test_all_selected_by_kind_order(self):
        """一键全选：聚落在前、梦魇在后，各自按 order。"""
        every = [t.key for t in self.targets]
        plan = build_plan(every, self.targets)
        self.assertEqual([s.key for s in plan],
                         ["nest:A", "nest:B", "nm:C", "nm:D"])

    def test_empty_selection(self):
        for empty in ([], set(), None, ()):
            plan = build_plan(empty, self.targets)
            self.assertFalse(plan)
            self.assertEqual(len(plan), 0)
            self.assertIsNone(plan.first)

    def test_unknown_keys_ignored_but_order_stable(self):
        """清单里没有的 key 被忽略，**剩下的顺序不受影响**。"""
        plan = build_plan(["nest:B", "早就删掉的key", "nest:A"], self.targets)
        self.assertEqual([s.key for s in plan], ["nest:A", "nest:B"])

    def test_index_is_one_based_and_sequential(self):
        """``index`` 从 1 起、连续 —— 日志里"第 2/5 个"靠它。"""
        plan = build_plan(["nm:D", "nest:A"], self.targets)
        self.assertEqual([s.index for s in plan], [1, 2])
        self.assertEqual(plan.first.index, 1)

    def test_fallback_row_counts_within_kind(self):
        """★ 兜底行号**在每个分类内**从 1 数（指南里是两个页签）。

        ⚠ 如果跨分类连续编号，梦魇那一页的第 1 行会变成"第 3 行" ——
        兜底点击必然点错行。
        """
        plan = build_plan(["nest:B", "nm:D"], self.targets)
        rows = {s.key: s.fallback_row for s in plan}
        self.assertEqual(rows["nest:B"], 2)   # 聚落页的第 2 行
        self.assertEqual(rows["nm:D"], 2)     # 梦魇页的第 2 行（不是第 4 行！）

    def test_match_names_carried_through(self):
        """匹配名要带进计划 —— 任务侧靠它认行。"""
        plan = build_plan(["nest:A"], self.targets)
        self.assertIn("聚落A", plan.first.match_names)
        #: 附带信息也要带过去（界面显示区域、任务侧参考数量）
        self.assertEqual(plan.first.region, "区域一")
        self.assertEqual(plan.first.count, 24)

    def test_of_kind_and_describe(self):
        plan = build_plan([t.key for t in self.targets], self.targets)
        self.assertEqual(len(plan.of_kind(KIND_NEST)), 2)
        self.assertEqual(len(plan.of_kind(KIND_NIGHTMARE)), 2)
        self.assertEqual(plan.kinds(), (KIND_NEST, KIND_NIGHTMARE))
        self.assertIn("残像聚落 2", plan.describe())
        self.assertIn("梦魇残像 2", plan.describe())

    def test_step_describe_reads_well(self):
        plan = build_plan(["nest:A"], self.targets)
        text = plan.first.describe()
        self.assertIn("[1]", text)
        self.assertIn("残像聚落", text)
        self.assertIn("聚落A", text)


class TestCleanSelection(unittest.TestCase):
    """存盘前的清理。"""

    def setUp(self):
        self.targets = make_targets()

    def test_drops_unknown_keys(self):
        got = clean_selection(["nest:A", "早没了", "nm:C"], self.targets)
        self.assertEqual(got, ["nest:A", "nm:C"])

    def test_output_follows_catalog_order(self):
        """★ 输出按**清单顺序** —— 存盘内容才稳定。

        按勾选顺序存的话，同样勾这三个、点选先后不同，
        文件内容就不一样 —— 每次保存都"看起来改了东西"。
        """
        got = clean_selection(["nm:D", "nest:B", "nest:A"], self.targets)
        self.assertEqual(got, ["nest:A", "nest:B", "nm:D"])

    def test_build_plan_does_not_clean_but_ignores(self):
        """★★ 对比：**建计划**时不清理、只是不认它。

        这样"手滑删了一条又加回来"，勾选还在（不用重新点一遍）；
        而**保存**时才会真正清掉（:func:`clean_selection`），
        盘上不积垃圾。两者刻意不同。
        """
        stale = ["nest:A", "已经删掉的目标"]
        #: 建计划：只剩认得出的那个
        self.assertEqual([s.key for s in build_plan(stale, self.targets)],
                         ["nest:A"])
        #: 清理：消失的那个被去掉，留下的还在
        self.assertEqual(clean_selection(stale, self.targets), ["nest:A"])

    def test_garbage_input(self):
        self.assertEqual(clean_selection(None, self.targets), [])
        self.assertEqual(clean_selection(["", None], self.targets), [])


class TestHelpers(unittest.TestCase):
    """摘要与"已选对象"。"""

    def setUp(self):
        self.targets = make_targets()

    def test_selected_targets_in_catalog_order(self):
        got = selected_targets(["nm:D", "nest:A"], self.targets)
        self.assertEqual([t.key for t in got], ["nest:A", "nm:D"])

    def test_summary_when_nothing_selected(self):
        for empty in ([], None):
            self.assertEqual(selection_summary(empty, self.targets),
                             "未勾选任何目标")

    def test_summary_is_unified_no_kind_split(self):
        """★ 2026-10-13 用户要求「不再区分残像聚落/梦魇聚落，统一叫残像聚落」。

        所以摘要**只报个数**，不再拆成「残像聚落 2 · 梦魇残像 1」——
        用户看到的是一张统一的卡片墙，摘要再分两类会让人以为界面还分两段。
        """
        text = selection_summary(["nest:A", "nest:B", "nm:C"], self.targets)
        self.assertEqual(text, "已选 3 个")
        for word in ("残像聚落", "梦魇残像", "聚落"):
            with self.subTest(word=word):
                self.assertNotIn(word, text)

    def test_summary_is_stable_across_calls(self):
        """同一份勾选，摘要每次都一样（别用 set 遍历去拼字符串）。"""
        keys = ["nm:C", "nest:A"]
        first = selection_summary(keys, self.targets)
        for _ in range(5):
            self.assertEqual(selection_summary(keys, self.targets), first)


class TestRealCatalogIntegration(unittest.TestCase):
    """★ 走仓库里那份**真实清单**（不传 targets，让它自己读盘）。"""

    def test_everything_selected_yields_everything(self):
        from src.core.nest_sweep.catalog import load_catalog

        items = load_catalog()
        if not items:
            self.skipTest("清单为空")
        plan = build_plan([t.key for t in items])
        self.assertEqual(len(plan), len(items))
        #: 全选时顺序必须和清单**完全一致**
        self.assertEqual([s.key for s in plan], [t.key for t in items])

    def test_plan_matches_selection_count(self):
        from src.core.nest_sweep.catalog import load_catalog

        items = load_catalog()
        if len(items) < 2:
            self.skipTest("清单太短")
        picked = [items[0].key, items[-1].key]
        plan = build_plan(picked)
        self.assertEqual(len(plan), 2)
        self.assertEqual(plan.first.key, items[0].key)


if __name__ == "__main__":
    unittest.main()
