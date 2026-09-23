"""配置模型 + 本地存储的单元测试。

    python tests/test_loadout.py
    或在 PyCharm 里右键 Run 'Unittests in test_loadout.py'

覆盖：必填校验、JSON 往返、增删改查、同一角色多条、文件缺失/损坏时的容错。
"""

from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.core.game_data import CONFIGURABLE_ECHO_SETS, find_echo_set  # noqa: E402
from src.core.loadout import EchoPick, Loadout, LoadoutStore  # noqa: E402


def set_with_many_4c():
    """找一套 4C 有多个声骸的套装 —— 测多选要用。

    写死套装名/声骸名不行：数据集是从 wiki 刷的，内容会变（凝夜白霜的 4C 就只有 1 个）。
    """
    return max(CONFIGURABLE_ECHO_SETS, key=lambda s: len(s.by_cost(4)))


def make_loadout(character: str = "爱弥斯", echo_set: str = "凝夜白霜") -> Loadout:
    """造一条填得完整的配置。"""
    loadout = Loadout(character=character, echo_set=echo_set)
    info = find_echo_set(echo_set)
    if info is not None:
        for cost in (4, 3, 1):
            items = info.by_cost(cost)
            if items:
                loadout.add_pick(cost, items[0], items[0].stats[0])
    return loadout


class TestModel(unittest.TestCase):
    def test_validate_passes_when_complete(self):
        self.assertEqual(make_loadout().validate(), [])

    def test_validate_needs_character(self):
        loadout = make_loadout(character="")
        self.assertIn("角色为必填项", loadout.validate())

    def test_validate_needs_echo_set(self):
        loadout = Loadout(character="爱弥斯", echo_set="")
        errors = loadout.validate()
        self.assertIn("请先选择声骸套装", errors)
        # 套装都没选时不该再报三条"声骸必填"，否则提示会糊成一片
        self.assertEqual(len(errors), 1)

    def test_validate_needs_every_cost_pick(self):
        loadout = make_loadout()
        loadout.clear_picks(3)
        errors = loadout.validate()
        self.assertIn("3C 声骸为必填项", errors)

    def test_validate_needs_stat_of_pick(self):
        loadout = make_loadout()
        first = find_echo_set("凝夜白霜").by_cost(4)[0]
        loadout.clear_picks(4)
        loadout.add_pick(4, first, stats=())
        self.assertIn(f"4C 声骸「{first.name}」还没选属性", loadout.validate())

    def test_validate_rejects_unknown_set(self):
        loadout = make_loadout()
        loadout.echo_set = "不存在的套装"
        self.assertTrue(any("不在数据集里" in e for e in loadout.validate()))

    def test_pick_describe(self):
        self.assertEqual(EchoPick().describe(), "未选")
        self.assertEqual(EchoPick("鸣钟之龟", "暴击").describe(), "鸣钟之龟（暴击）")
        self.assertEqual(EchoPick("鸣钟之龟").describe(), "鸣钟之龟")

    def test_multi_stat_pick(self):
        """属性多选：一条声骸同时要几条主词条。"""
        pick = EchoPick("鸣钟之龟", ("暴击", "暴击伤害"))
        self.assertEqual(pick.describe(), "鸣钟之龟（暴击、暴击伤害）")
        self.assertEqual(pick.stat, "暴击", "兼容读取返回第一条")
        # 字符串自动转单元素元组（防手滑）
        self.assertEqual(EchoPick("鸣钟之龟", "暴击").stats, ("暴击",))

    def test_summary_mentions_all_costs(self):
        text = make_loadout().summary()
        for token in ("凝夜白霜", "4C", "3C", "1C"):
            self.assertIn(token, text)

    def test_dict_roundtrip(self):
        original = make_loadout()
        original.id = "abc123"
        original.updated_at = "2026-09-21 16:00:00"
        restored = Loadout.from_dict(original.to_dict())

        self.assertEqual(restored.character, original.character)
        self.assertEqual(restored.echo_set, original.echo_set)
        self.assertEqual(restored.id, original.id)
        # picks 的 key 走 JSON 会变字符串，还原时必须是 int
        self.assertEqual(sorted(restored.picks), [1, 3, 4])
        self.assertEqual(
            [p.echo for p in restored.picks_of(4)],
            [p.echo for p in original.picks_of(4)],
        )
        self.assertEqual(
            [p.stats for p in restored.picks_of(4)],
            [p.stats for p in original.picks_of(4)],
        )

    def test_from_dict_tolerates_garbage(self):
        restored = Loadout.from_dict(
            {"picks": {"xx": {"echo": "a"}, "4": "不是字典", "3": [1, 2]}}
        )
        self.assertEqual(restored.picks, {})
        self.assertEqual(restored.character, "")

    def test_multiple_picks_per_cost(self):
        # 需求变更：每档可以多选
        info = set_with_many_4c()
        picks = info.by_cost(4)
        self.assertGreaterEqual(len(picks), 2, f"{info.name} 的 4C 不足两个，测不了多选")

        loadout = make_loadout(echo_set=info.name)
        loadout.clear_picks(4)          # make_loadout 已经塞了一条，先清空
        for item in picks:
            loadout.add_pick(4, item, item.stats[0])
        self.assertEqual([p.echo for p in loadout.picks_of(4)], [p.name for p in picks])
        self.assertEqual(loadout.validate(), [])
        self.assertIn(picks[0].name, loadout.summary())

    def test_validate_needs_at_least_one_per_cost(self):
        loadout = make_loadout()
        loadout.clear_picks(1)
        self.assertIn("1C 声骸为必填项", loadout.validate())

    def test_old_single_pick_format_still_loads(self):
        # 老版本每档存的是单条 dict，新版是 list —— 两种都要能读
        loadout = Loadout.from_dict(
            {
                "character": "爱弥斯",
                "echo_set": "凝夜白霜",
                "picks": {
                    "4": {"echo": "鸣钟之龟", "stat": "暴击"},
                    "3": [{"echo": "霜天猎手", "stat": "攻击百分比"}],
                    "1": [],
                },
            }
        )
        self.assertEqual([p.echo for p in loadout.picks_of(4)], ["鸣钟之龟"])
        # 老格式单属性 → 读成单元素元组
        self.assertEqual([p.stats for p in loadout.picks_of(4)], [("暴击",)])
        self.assertEqual([p.echo for p in loadout.picks_of(3)], ["霜天猎手"])
        self.assertEqual(loadout.picks_of(1), [])

    def test_roundtrip_keeps_multiple_picks(self):
        info = set_with_many_4c()
        loadout = make_loadout(echo_set=info.name)
        second = info.by_cost(4)[1]
        loadout.add_pick(4, second, second.stats[1])
        restored = Loadout.from_dict(loadout.to_dict())
        self.assertEqual(len(restored.picks_of(4)), 2)
        self.assertEqual([p.echo for p in restored.picks_of(4)][1], second.name)
        self.assertEqual([p.stats for p in restored.picks_of(4)][1], (second.stats[1],))

    def test_custom_avatar_overrides_synced_one(self):
        loadout = make_loadout(character="爱弥斯")
        loadout.sync_avatar()
        self.assertEqual(loadout.display_avatar, "avatars/爱弥斯.png")
        loadout.custom_avatar = "C:/pics/my.png"
        self.assertEqual(loadout.display_avatar, "C:/pics/my.png")
        self.assertEqual(loadout.avatar, "avatars/爱弥斯.png", "联动头像不该被覆盖掉")

    def test_custom_avatar_roundtrip(self):
        loadout = make_loadout()
        loadout.custom_avatar = "C:/pics/my.png"
        restored = Loadout.from_dict(loadout.to_dict())
        self.assertEqual(restored.custom_avatar, "C:/pics/my.png")
        self.assertEqual(restored.display_avatar, "C:/pics/my.png")

    def test_from_dict_accepts_empty(self):
        self.assertEqual(Loadout.from_dict({}).picks, {})


class TestStore(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = pathlib.Path(self._tmp.name) / "loadouts.json"
        self.store = LoadoutStore(self.path)

    def tearDown(self):
        self._tmp.cleanup()

    def test_add_assigns_id_and_time(self):
        item = self.store.add(make_loadout())
        self.assertTrue(item.id)
        self.assertTrue(item.updated_at)
        self.assertEqual(len(self.store), 1)

    def test_add_syncs_avatar(self):
        item = self.store.add(make_loadout(character="爱弥斯"))
        self.assertEqual(item.avatar, "avatars/爱弥斯.png")

    def test_avatar_empty_when_character_unknown(self):
        # 手输一个数据集里没有的角色：允许保存，但头像留空
        item = self.store.add(make_loadout(character="查无此人"))
        self.assertEqual(item.avatar, "")

    def test_same_character_can_have_many(self):
        self.store.add(make_loadout())
        self.store.add(make_loadout())
        self.assertEqual(len(self.store.by_character("爱弥斯")), 2)
        self.assertEqual(len({i.id for i in self.store.all()}), 2)

    def test_update(self):
        item = self.store.add(make_loadout())
        item.echo_set = "熔山裂谷"
        self.assertTrue(self.store.update(item))
        reloaded = LoadoutStore(self.path).get(item.id)
        self.assertEqual(reloaded.echo_set, "熔山裂谷")

    def test_update_unknown_id_returns_false(self):
        self.assertFalse(self.store.update(make_loadout()))

    def test_remove(self):
        item = self.store.add(make_loadout())
        self.assertTrue(self.store.remove(item.id))
        self.assertEqual(len(self.store), 0)
        self.assertFalse(self.store.remove(item.id))

    def test_persist_and_reload(self):
        item = self.store.add(make_loadout())
        fresh = LoadoutStore(self.path)
        self.assertEqual(len(fresh), 1)
        restored = fresh.get(item.id)
        self.assertEqual(restored.echo_set, "凝夜白霜")
        self.assertEqual(restored.picks_of(4)[0].stats, ("暴击",))

    def test_missing_file_is_empty(self):
        self.assertEqual(len(self.store), 0)
        self.assertFalse(self.path.exists())

    def test_corrupted_file_is_empty(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("{ 这不是 json", encoding="utf-8")
        self.assertEqual(len(LoadoutStore(self.path)), 0)

    def test_bad_record_is_skipped(self):
        payload = {"version": 1, "loadouts": ["字符串", 42, make_loadout().to_dict()]}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        store = LoadoutStore(self.path)
        self.assertEqual(len(store), 1)

    def test_accepts_bare_list_format(self):
        # 老/手写的文件可能直接是数组
        payload = [make_loadout().to_dict()]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        self.assertEqual(len(LoadoutStore(self.path)), 1)

    def test_all_sorted_by_updated_at_desc(self):
        first = self.store.add(make_loadout())
        second = self.store.add(make_loadout(character="今汐"))
        first.updated_at = "2026-09-21 10:00:00"
        second.updated_at = "2026-09-21 12:00:00"
        self.assertEqual([i.id for i in self.store.all()], [second.id, first.id])

    def test_saved_file_is_readable_json(self):
        self.store.add(make_loadout())
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(raw["version"], 1)
        self.assertEqual(len(raw["loadouts"]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
