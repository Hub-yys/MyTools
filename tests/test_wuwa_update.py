"""wuwa_update 核心逻辑的单元测试（纯数据操作，不碰网络）。

网络抓取没法在单测里稳定复现，但「对比」和「合并」是纯函数 ——
喂假快照就能测：新套装 / 效果变化 / 新声骸 / 并集不删已有条目。
"""

from __future__ import annotations

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.core.wuwa_update import RemoteSnapshot, _merge_sets_data, check_updates


def _local() -> dict:
    return {
        "sets": [
            {
                "name": "凝夜白霜",
                "effects": [{"pieces": 2, "text": "冷凝伤害提升10%"}],
                "echoes": [
                    {"name": "冻巣陆行鲸", "cost": 4},
                    {"name": "霜刃豹", "cost": 3},
                ],
            },
        ],
    }


def _snapshot() -> RemoteSnapshot:
    snapshot = RemoteSnapshot()
    snapshot.sets = {
        # 已有套装，效果没变
        "凝夜白霜": [{"pieces": 2, "text": "冷凝伤害提升10%"}],
        # 已有套装，效果变了
        # （分开两个快照测，见各用例）
    }
    return snapshot


class TestCheckUpdates(unittest.TestCase):
    def test_no_updates(self):
        snapshot = RemoteSnapshot()
        snapshot.sets = {"凝夜白霜": _local()["sets"][0]["effects"]}
        report = check_updates(snapshot, local_sets=_local())
        self.assertFalse(report.has_updates)
        self.assertIn("已是最新", report.summary())

    def test_new_set_detected(self):
        snapshot = _snapshot()
        snapshot.sets["新套装"] = [{"pieces": 2, "text": "x"}]
        report = check_updates(snapshot, local_sets=_local())
        self.assertTrue(report.has_updates)
        self.assertEqual(report.new_sets, ["新套装"])

    def test_effect_change_detected(self):
        snapshot = _snapshot()
        snapshot.sets["凝夜白霜"] = [{"pieces": 2, "text": "冷凝伤害提升15%"}]
        report = check_updates(snapshot, local_sets=_local())
        self.assertEqual(report.effect_changed, ["凝夜白霜"])
        self.assertEqual(report.new_sets, [])

    def test_new_echo_from_both_sources_reported_once(self):
        snapshot = _snapshot()
        snapshot.echoes_bwiki = {"凝夜白霜": {1: ["新声骸甲"]}}
        snapshot.echoes_kuro = {"凝夜白霜": {1: ["新声骸甲", "新声骸乙"]}}
        report = check_updates(snapshot, local_sets=_local())
        # 同一个名字两个源都有 → 只报一次；名字带上来源标注
        self.assertEqual(len(report.new_echoes), 2)
        self.assertTrue(any(n.startswith("新声骸甲") for n in report.new_echoes))
        self.assertTrue(any(n.startswith("新声骸乙") for n in report.new_echoes))


class TestMergeSetsData(unittest.TestCase):
    def test_append_new_set(self):
        local = _local()
        snapshot = RemoteSnapshot()
        snapshot.sets = {"新套装": [{"pieces": 5, "text": "y"}]}
        self.assertTrue(_merge_sets_data(local, snapshot))
        names = [s["name"] for s in local["sets"]]
        self.assertIn("新套装", names)

    def test_union_keeps_existing_echoes(self):
        local = _local()
        snapshot = RemoteSnapshot()
        snapshot.echoes_bwiki = {"凝夜白霜": {1: ["新声骸甲"]}}
        _merge_sets_data(local, snapshot)
        echoes = {e["name"] for e in local["sets"][0]["echoes"]}
        # 老条目一个不能少，新条目要进来
        self.assertLessEqual({"冻巣陆行鲸", "霜刃豹", "新声骸甲"}, echoes)

    def test_union_across_sources_with_unknown_cost(self):
        """cost=0 的条目（记录没打 COST 标）要按名字归到正确档位。"""
        local = _local()
        snapshot = RemoteSnapshot()
        # 「霜刃豹」在本地是 3C；库街区没给档位（cost=0）
        snapshot.echoes_kuro = {"凝夜白霜": {0: ["霜刃豹", "全新声骸"]}}
        _merge_sets_data(local, snapshot)
        by_cost = {}
        for entry in local["sets"][0]["echoes"]:
            by_cost.setdefault(entry["cost"], set()).add(entry["name"])
        self.assertIn("霜刃豹", by_cost.get(3, set()), "已有条目的档位不能被改")
        # 全新名字查不到档位 → 落 4C 桶（兜底行为）
        self.assertIn("全新声骸", by_cost.get(4, set()))

    def test_marks_fetched_date(self):
        local = _local()
        snapshot = RemoteSnapshot()
        _merge_sets_data(local, snapshot)
        self.assertTrue(local.get("_fetched"), "合并后应该刷新 _fetched 日期")


if __name__ == "__main__":
    unittest.main(verbosity=2)
