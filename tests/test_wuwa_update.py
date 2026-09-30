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

from src.core.wuwa_update import (
    RemoteSnapshot,
    _merge_characters_data,
    _merge_sets_data,
    check_updates,
)


def _local_chars() -> dict:
    return {
        "characters": [
            {"name": "景燃", "rarity": 5, "element": "热熔", "weapon": "长刃"},
            {"name": "绯雪", "rarity": 5, "element": "冷凝", "weapon": "迅刀"},
        ],
    }


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


class TestCheckUpdatesCharacters(unittest.TestCase):
    """★ 新角色检测（用户 2026-09-28："新角色的数据（能选到新角色）"）。"""

    def test_new_character_detected(self):
        snapshot = RemoteSnapshot()
        snapshot.sets = {"凝夜白霜": _local()["sets"][0]["effects"]}
        snapshot.characters = {"景燃": {}, "新角色甲": {}, "新角色乙": {}}
        report = check_updates(snapshot, local_sets=_local(),
                               local_characters=_local_chars())
        self.assertEqual(report.new_characters, ["新角色甲", "新角色乙"])
        self.assertTrue(report.has_updates, "有新角色就算有更新")
        self.assertIn("新角色", report.summary())

    def test_no_new_character(self):
        snapshot = RemoteSnapshot()
        snapshot.sets = {"凝夜白霜": _local()["sets"][0]["effects"]}
        snapshot.characters = {"景燃": {}, "绯雪": {}}
        report = check_updates(snapshot, local_sets=_local(),
                               local_characters=_local_chars())
        self.assertEqual(report.new_characters, [])
        self.assertFalse(report.has_updates)

    def test_characters_alone_count_as_remote_data(self):
        """★ 只有角色拉到、其它全空时**不算** remote_empty。

        否则"wiki 声骸页挂了但角色页正常"会被误报成"什么都没取到"。
        """
        snapshot = RemoteSnapshot()
        snapshot.characters = {"景燃": {"element": "热熔"}}
        report = check_updates(snapshot, local_sets=_local(),
                               local_characters=_local_chars())
        self.assertFalse(report.remote_empty)

    def test_truly_empty_remote_still_reported(self):
        report = check_updates(RemoteSnapshot(), local_sets=_local(),
                               local_characters=_local_chars())
        self.assertTrue(report.remote_empty)


class TestMergeCharactersData(unittest.TestCase):
    """角色合并：**只增不减**，且不拿空值覆盖本地已有信息。"""

    def test_appends_new_character(self):
        local = _local_chars()
        snapshot = RemoteSnapshot()
        snapshot.characters = {"新角色甲": {"rarity": 0, "element": "衍射",
                                            "weapon": "长刃"}}
        self.assertTrue(_merge_characters_data(local, snapshot))
        names = [c["name"] for c in local["characters"]]
        self.assertIn("新角色甲", names)
        self.assertEqual(len(names), 3)

    def test_keeps_existing_characters(self):
        """★ 远端漏了某个已有角色时**不能删** —— 删了用户已存的配置会指向不存在的角色。"""
        local = _local_chars()
        snapshot = RemoteSnapshot()
        snapshot.characters = {"景燃": {"element": "热熔", "weapon": "长刃"}}
        _merge_characters_data(local, snapshot)
        names = [c["name"] for c in local["characters"]]
        self.assertIn("绯雪", names, "远端没返回的角色必须保留")

    def test_empty_remote_field_does_not_erase_local(self):
        """远端 field 为空串时保留本地的 —— 别把已有信息清掉。"""
        local = _local_chars()
        snapshot = RemoteSnapshot()
        snapshot.characters = {"绯雪": {"element": "", "weapon": ""}}
        _merge_characters_data(local, snapshot)
        fx = next(c for c in local["characters"] if c["name"] == "绯雪")
        self.assertEqual(fx["element"], "冷凝")
        self.assertEqual(fx["weapon"], "迅刀")

    def test_rarity_zero_does_not_overwrite_known(self):
        """★ wiki 的稀有度常返回 0 —— 绝不能拿 0 覆盖本地已知星级。"""
        local = _local_chars()
        snapshot = RemoteSnapshot()
        snapshot.characters = {"景燃": {"rarity": 0, "element": "热熔",
                                        "weapon": "长刃"}}
        _merge_characters_data(local, snapshot)
        jr = next(c for c in local["characters"] if c["name"] == "景燃")
        self.assertEqual(jr["rarity"], 5, "0 星不能覆盖已知的 5 星")

    def test_rarity_fills_when_local_unknown(self):
        local = {"characters": [{"name": "甲", "rarity": 0,
                                 "element": "", "weapon": ""}]}
        snapshot = RemoteSnapshot()
        snapshot.characters = {"甲": {"rarity": 4, "element": "气动",
                                      "weapon": "臂铠"}}
        _merge_characters_data(local, snapshot)
        self.assertEqual(local["characters"][0]["rarity"], 4)

    def test_non_empty_change_updates_value(self):
        """远端给了**不同且非空**的武器 → 以远端为准（wiki 修正过）。"""
        local = _local_chars()
        snapshot = RemoteSnapshot()
        snapshot.characters = {"景燃": {"element": "热熔", "weapon": "佩枪"}}
        _merge_characters_data(local, snapshot)
        jr = next(c for c in local["characters"] if c["name"] == "景燃")
        self.assertEqual(jr["weapon"], "佩枪")

    def test_idempotent(self):
        """跑两次不该有变化（否则每次检查都报"有更新"）。"""
        local = _local_chars()
        snapshot = RemoteSnapshot()
        snapshot.characters = {"新角色甲": {"element": "衍射", "weapon": "长刃"}}
        self.assertTrue(_merge_characters_data(local, snapshot))
        self.assertFalse(_merge_characters_data(local, snapshot))

    def test_empty_snapshot_is_noop(self):
        local = _local_chars()
        before = len(local["characters"])
        self.assertFalse(_merge_characters_data(local, RemoteSnapshot()))
        self.assertEqual(len(local["characters"]), before)

    def test_marks_fetched_when_added(self):
        local = _local_chars()
        snapshot = RemoteSnapshot()
        snapshot.characters = {"新角色甲": {"element": "衍射", "weapon": "长刃"}}
        _merge_characters_data(local, snapshot)
        self.assertTrue(local.get("_fetched"))

    def test_handles_broken_entries(self):
        """名单里混进非 dict（手改坏了）也不该炸。"""
        local = {"characters": [{"name": "景燃", "rarity": 5}, "坏数据", None]}
        snapshot = RemoteSnapshot()
        snapshot.characters = {"新角色甲": {"element": "衍射", "weapon": "长刃"}}
        _merge_characters_data(local, snapshot)
        names = [c["name"] for c in local["characters"] if isinstance(c, dict)]
        self.assertIn("新角色甲", names)


if __name__ == "__main__":
    unittest.main(verbosity=2)
