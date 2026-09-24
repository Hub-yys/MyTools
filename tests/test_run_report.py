"""运行报告（本轮 + 累计统计）的单元测试。

    python tests/test_run_report.py

覆盖用户 2026-09-28 的两条要求：

* **本轮报告** —— 统计本轮声骸符合条件锁定的、弃置的数量；
* **所有任务的累计统计** —— 跨轮次累加，且**重启不丢**（持久化）。
"""

from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.core.run_report import (  # noqa: E402
    FlowRunResult,
    RoundReport,
    RunReportStore,
    TotalStats,
    flow_result_from_summary,
)
from src.tools.game.echo_enhance.stats import format_result_report  # noqa: E402


def _result(name: str, locked: int, dropped: int, checked: int = 0,
            ok: bool = True, note: str = "") -> FlowRunResult:
    return FlowRunResult(name=name, locked=locked, dropped=dropped,
                         checked=checked, ok=ok, note=note)


class TestRoundReport(unittest.TestCase):
    """本轮报告的合计与明细。"""

    def test_totals_sum_every_step(self):
        """一轮里好几个工具步骤 → 合计要把它们加起来。"""
        report = RoundReport(flow_name="爱弥斯声骸自动强化")
        report.items.append(_result("爱弥斯-声骸筛选", 0, 0))
        report.items.append(_result("声骸自动强化", 3, 7, checked=10))
        self.assertEqual(report.locked, 3)
        self.assertEqual(report.dropped, 7)
        self.assertEqual(report.checked, 10)
        self.assertEqual(report.summary(), "符合条件锁定 3 · 弃置 7")

    def test_empty_round_is_empty(self):
        report = RoundReport()
        self.assertTrue(report.is_empty())
        self.assertEqual(report.summary(), "符合条件锁定 0 · 弃置 0")

    def test_lines_show_each_step(self):
        report = RoundReport()
        report.items.append(_result("声骸自动强化", 2, 5))
        report.items.append(_result("别的工具", 0, 0, ok=False, note="不支持自动运行"))
        lines = report.lines()
        self.assertEqual(len(lines), 2)
        self.assertIn("锁定 2 · 弃置 5", lines[0])
        self.assertIn("不支持自动运行", lines[1])

    def test_roundtrip(self):
        report = RoundReport(flow_name="测试", started_at="t0", finished_at="t1",
                             ok=False, note="已停止")
        report.items.append(_result("强化", 1, 2, checked=3))
        restored = RoundReport.from_dict(report.to_dict())
        self.assertEqual(restored.flow_name, "测试")
        self.assertEqual(restored.note, "已停止")
        self.assertFalse(restored.ok)
        self.assertEqual(restored.locked, 1)
        self.assertEqual(restored.dropped, 2)

    def test_from_dict_tolerates_garbage(self):
        restored = RoundReport.from_dict({"items": "不是列表"})
        self.assertEqual(restored.items, [])
        self.assertTrue(restored.is_empty())


class TestFlowResultFromSummary(unittest.TestCase):
    """★ 数字来自工具 ``.summary()`` 的文本 —— 锁定 = 成功数，弃置 = 失败数。"""

    def test_reads_counts_from_tool_report(self):
        summary = format_result_report(checked=10, kept=4, dropped=6)
        result = flow_result_from_summary("声骸自动强化", summary)
        self.assertEqual(result.locked, 4)
        self.assertEqual(result.dropped, 6)
        self.assertEqual(result.checked, 10)
        self.assertTrue(result.ok)

    def test_unparseable_summary_records_zero(self):
        """解析不出来就记 0 —— **不猜**（宁可少一行，也不编错的数字）。"""
        result = flow_result_from_summary("某工具", "完成了")
        self.assertEqual(result.locked, 0)
        self.assertEqual(result.dropped, 0)
        self.assertEqual(result.checked, 0)

    def test_failure_note_is_kept(self):
        result = flow_result_from_summary("某工具", "", ok=False, note="工具实例化失败")
        self.assertFalse(result.ok)
        self.assertEqual(result.note, "工具实例化失败")


class TestTotalStats(unittest.TestCase):
    """累计统计的累加。"""

    def test_add_accumulates(self):
        stats = TotalStats()
        first = RoundReport(finished_at="t1")
        first.items.append(_result("强化", 2, 3, checked=5))
        stats.add(first)
        second = RoundReport(finished_at="t2")
        second.items.append(_result("强化", 1, 4, checked=5))
        stats.add(second)

        self.assertEqual(stats.locked, 3)
        self.assertEqual(stats.dropped, 7)
        self.assertEqual(stats.checked, 10)
        self.assertEqual(stats.rounds, 2)
        self.assertEqual(stats.updated_at, "t2")

    def test_reset(self):
        stats = TotalStats(locked=5, dropped=6, checked=11, rounds=2)
        stats.reset()
        self.assertEqual(stats.to_dict()["locked"], 0)
        self.assertEqual(stats.rounds, 0)

    def test_from_dict_tolerates_garbage(self):
        stats = TotalStats.from_dict({"locked": "abc", "dropped": -5, "rounds": None})
        self.assertEqual(stats.locked, 0)
        self.assertEqual(stats.dropped, 0)
        self.assertEqual(stats.rounds, 0)


class TestStore(unittest.TestCase):
    """持久化：**重启不丢**（用户明确要求累计统计要留下来）。"""

    def test_missing_file_is_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RunReportStore(pathlib.Path(tmp) / "echo_run_stats.json")
            stats = store.load()
            self.assertEqual(stats.locked, 0)
            self.assertEqual(stats.rounds, 0)

    def test_add_round_persists_across_reload(self):
        """★ 关键护栏：写完之后**新建一个 store** 还能读到（＝重启不丢）。"""
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "echo_run_stats.json"
            report = RoundReport(flow_name="测试", finished_at="2026-09-28 10:00:00")
            report.items.append(_result("声骸自动强化", 3, 7, checked=10))

            RunReportStore(path).add_round(report)

            again = RunReportStore(path).load()
            self.assertEqual(again.locked, 3)
            self.assertEqual(again.dropped, 7)
            self.assertEqual(again.checked, 10)
            self.assertEqual(again.rounds, 1)

    def test_rounds_accumulate_across_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "echo_run_stats.json"
            store = RunReportStore(path)
            for locked, dropped in ((1, 2), (3, 4)):
                report = RoundReport(finished_at="t")
                report.items.append(_result("强化", locked, dropped))
                store.add_round(report)

            stats = RunReportStore(path).load()
            self.assertEqual((stats.locked, stats.dropped), (4, 6))
            self.assertEqual(stats.rounds, 2)

    def test_file_is_readable_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "echo_run_stats.json"
            report = RoundReport(finished_at="t")
            report.items.append(_result("强化", 1, 1))
            RunReportStore(path).add_round(report)

            raw = json.loads(path.read_text(encoding="utf-8"))
            self.assertIn("total", raw)
            self.assertEqual(raw["total"]["locked"], 1)

    def test_corrupt_file_falls_back_to_zero(self):
        """文件坏了不该把任务页搞崩 —— 当作从零开始。"""
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "echo_run_stats.json"
            path.write_text("{ 这不是 json", encoding="utf-8")
            self.assertEqual(RunReportStore(path).load().locked, 0)

    def test_non_dict_json_falls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "echo_run_stats.json"
            path.write_text("[1, 2, 3]", encoding="utf-8")
            self.assertEqual(RunReportStore(path).load().rounds, 0)

    def test_reset_persists(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "echo_run_stats.json"
            store = RunReportStore(path)
            report = RoundReport(finished_at="t")
            report.items.append(_result("强化", 5, 5))
            store.add_round(report)

            store.reset()
            self.assertEqual(RunReportStore(path).load().locked, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
