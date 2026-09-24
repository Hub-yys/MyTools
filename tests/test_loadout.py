"""配置模型 + 本地存储的单元测试。

    python tests/test_loadout.py
    或在 PyCharm 里右键 Run 'Unittests in test_loadout.py'

覆盖：必填校验、JSON 往返、增删改查、**角色占用查询（一角色一条的界面规则）**、
文件缺失/损坏时的容错。
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
from src.core.loadout import (  # noqa: E402
    COST_SECTIONS,
    DEFAULT_QUALITIES,
    DEFAULT_STATUS,
    QUALITY_CHOICES,
    STATUS_CHOICES,
    EchoPick,
    Loadout,
    LoadoutStore,
    normalize_qualities,
    normalize_status,
)


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

    def test_validate_allows_missing_cost_picks(self):
        """★ 2026-09-28 用户要求：**1C / 3C / 4C 都可以不填，不校验必填**。

        以前清空某一档会报「3C 声骸为必填项」（截图里拦人的那条），现在必须放行。
        """
        loadout = make_loadout()
        for cost, _label in COST_SECTIONS:
            loadout.clear_picks(cost)
        self.assertEqual(loadout.validate(), [], "各档都不填时应该放行")

    def test_validate_allows_single_missing_cost(self):
        """只清掉一档也不能报错 —— 用户可能只想限制其中一档。"""
        loadout = make_loadout()
        loadout.clear_picks(3)
        self.assertEqual(loadout.validate(), [])
        loadout.clear_picks(1)
        self.assertEqual(loadout.validate(), [])

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

    def test_validate_single_piece_set_needs_nothing_extra(self):
        """1 件套只有一档 —— 各档都不填同样放行（不再有"必填档位"这个概念）。"""
        loadout = make_loadout()
        loadout.clear_picks(1)
        self.assertEqual(loadout.validate(), [])

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
        # 数据集里没有的角色 → 头像留空、不崩。
        # ⚠ 界面层已经不让选了（``LoadoutDialog.validate`` 会拦"不是一个角色"），
        #   这条测的是**老数据 / 手改过 JSON** 那种情况还得能显示。
        item = self.store.add(make_loadout(character="查无此人"))
        self.assertEqual(item.avatar, "")

    def test_same_character_can_still_be_loaded(self):
        """⚠ 存储层**允许**同一角色多条 —— 这是给**老数据**留的路。

        "一个角色只能有一条"是**界面层的规则**（用户 2026-09-26 要求，见
        ``LoadoutDialog.validate``）：旧版允许一个角色配多套思路，
        那些文件必须照常读得出来、显示得出来，用户自己决定删哪条。
        所以这里断言的是"装得下"，不是"该允许"。
        """
        self.store.add(make_loadout())
        self.store.add(make_loadout())
        self.assertEqual(len(self.store.by_character("爱弥斯")), 2)
        self.assertEqual(len({i.id for i in self.store.all()}), 2)

    def test_occupied_characters(self):
        """★ 界面用这个把"一角色一条"做成下拉里选不到 + 保存前校验。"""
        self.store.add(make_loadout(character="爱弥斯"))
        self.store.add(make_loadout(character="绯雪"))
        self.assertEqual(self.store.occupied_characters(), {"爱弥斯", "绯雪"})
        self.assertTrue(self.store.has_character("爱弥斯"))
        self.assertFalse(self.store.has_character("清宵"))

    def test_occupied_characters_skips_blank(self):
        """角色为空的（坏数据）不算占用 —— 否则空角色名会把下拉堵死。"""
        self.store.add(make_loadout(character=""))
        self.assertEqual(self.store.occupied_characters(), set())

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

class TestFilterRows(unittest.TestCase):
    """★ 「筛选」面板里的**状态**和**品质**（用户 2026-09-26 指出配置漏了这两项）。

    游戏那块面板四行：状态 / 品质 / 合鸣（= 套装）/ 主音属性。
    合鸣和各档主属性本来就有（``echo_set`` + 各档 ``picks`` 的属性），
    这两行是补的：

    * **状态** —— 单选，已弃置 / 已锁定 / 未标记；
    * **品质** —— 多选，二~五星，**默认只勾五星**。
    """

    def test_defaults(self):
        item = Loadout()
        self.assertEqual(item.status, DEFAULT_STATUS)
        self.assertEqual(item.qualities, DEFAULT_QUALITIES)
        # ★ 2026-09-28 用户批注"默认已锁定"：新增配置时状态勾的就是它
        self.assertEqual(DEFAULT_STATUS, "已锁定")          # 期望值自己写，别调 helper
        self.assertEqual(DEFAULT_QUALITIES, ("五星",))
        self.assertEqual(STATUS_CHOICES, ("已弃置", "已锁定", "未标记"))
        self.assertEqual(QUALITY_CHOICES, ("二星", "三星", "四星", "五星"))

    def test_roundtrip(self):
        item = Loadout(character="绯雪", status="已锁定",
                       qualities=("四星", "五星"))
        restored = Loadout.from_dict(item.to_dict())
        self.assertEqual(restored.status, "已锁定")
        self.assertEqual(restored.qualities, ("四星", "五星"))

    def test_legacy_json_without_the_two_fields_gets_defaults(self):
        """老数据没有这两个字段 → 给默认（已锁定 / 五星），不能炸、也不能空着。"""
        old = {"id": "abc", "character": "绯雪", "echo_set": "凝夜白霜",
               "picks": {}, "updated_at": "2026-09-01 10:00:00"}
        item = Loadout.from_dict(old)
        self.assertEqual(item.status, DEFAULT_STATUS)
        self.assertEqual(item.qualities, ("五星",))

    def test_unknown_status_falls_back_to_default(self):
        self.assertEqual(Loadout.from_dict({"status": "乱写的"}).status, DEFAULT_STATUS)
        self.assertEqual(normalize_status(None), DEFAULT_STATUS)
        self.assertEqual(normalize_status("已弃置"), "已弃置")

    def test_unknown_quality_is_dropped(self):
        item = Loadout.from_dict({"qualities": ["五星", "十星", "四星"]})
        self.assertEqual(item.qualities, ("四星", "五星"), "不认识的丢掉、顺序按固定表")

    def test_empty_quality_list_is_kept_empty(self):
        """★ 用户把勾全取消了就是「一个都不勾」——不该被悄悄塞回默认的五星。"""
        self.assertEqual(Loadout.from_dict({"qualities": []}).qualities, ())
        self.assertEqual(normalize_qualities([]), ())

    def test_wrong_type_falls_back_to_default(self):
        self.assertEqual(normalize_qualities("五星"), DEFAULT_QUALITIES)
        self.assertEqual(Loadout.from_dict({"qualities": "五星"}).qualities,
                         DEFAULT_QUALITIES)

    def test_saved_file_has_the_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = LoadoutStore(pathlib.Path(tmp) / "loadouts.json")
            store.add(Loadout(character="绯雪", status="已锁定",
                              qualities=("五星",)))
            raw = (pathlib.Path(tmp) / "loadouts.json").read_text(encoding="utf-8")
            self.assertIn('"status": "已锁定"', raw)
            self.assertIn('"qualities"', raw)
            again = LoadoutStore(pathlib.Path(tmp) / "loadouts.json")
            got = again.all()[0]
            self.assertEqual(got.status, "已锁定")
            self.assertEqual(got.qualities, ("五星",))


class TestFilterRowsUI(unittest.TestCase):
    """状态 / 品质两行在弹框里要能**回填 → 收集**走一圈（Qt，用 offscreen）。"""

    @classmethod
    def setUpClass(cls):
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])
        cls._holders = []

    def _dialog(self, item):
        from PySide6.QtWidgets import QWidget

        from src.gui.loadout_dialog import LoadoutDialog

        # ⚠ MaskDialogBase 必须有 parent，否则构造就崩（老坑）。
        #   而且 parent 要**留住引用** —— holder 被 GC 掉会把子控件一起删，
        #   再访问就 `Internal C++ object already deleted`（实测踩过）。
        holder = QWidget()
        holder.resize(900, 700)
        self._holders.append(holder)
        dialog = LoadoutDialog(holder, item)
        self.app.processEvents()
        return dialog

    def test_restore_and_collect(self):
        item = Loadout(character="绯雪", status="已锁定", qualities=("四星", "五星"))
        dialog = self._dialog(item)

        self.assertTrue(dialog.status_buttons["已锁定"].isChecked(),
                        "回填要把状态选中")
        self.assertTrue(dialog.quality_boxes["四星"].isChecked())
        self.assertTrue(dialog.quality_boxes["五星"].isChecked())
        self.assertFalse(dialog.quality_boxes["三星"].isChecked())

        # 改一改再收回来
        dialog.status_buttons["未标记"].setChecked(True)
        dialog.quality_boxes["三星"].setChecked(True)
        dialog.quality_boxes["四星"].setChecked(False)
        dialog._collect()
        self.assertEqual(dialog.loadout.status, "未标记")
        self.assertEqual(dialog.loadout.qualities, ("三星", "五星"))

    def test_status_is_single_select(self):
        """状态是单选：点第二个，第一个要自动松开（游戏里那行是单选圈）。"""
        dialog = self._dialog(Loadout(character="绯雪"))
        self.assertTrue(dialog.status_buttons["已锁定"].isChecked(), "默认已锁定")
        dialog.status_buttons["已弃置"].setChecked(True)
        self.app.processEvents()
        self.assertFalse(dialog.status_buttons["已锁定"].isChecked(),
                         "单选组没生效 —— 会出现两个同时选中的怪状态")
        self.assertTrue(dialog.status_buttons["已弃置"].isChecked())

    def test_defaults_are_shown_for_old_data(self):
        """老配置打开时界面要有默认值（不是"一个都没选"）。"""
        dialog = self._dialog(Loadout(character="绯雪"))
        self.assertTrue(dialog.status_buttons["已锁定"].isChecked())
        self.assertTrue(dialog.quality_boxes["五星"].isChecked())
        self.assertFalse(dialog.quality_boxes["二星"].isChecked())


if __name__ == "__main__":
    unittest.main(verbosity=2)
