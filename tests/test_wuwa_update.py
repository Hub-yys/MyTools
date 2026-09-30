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


class TestKuroOnlySets(unittest.TestCase):
    """★ 库街区独有的套装（bwiki 还没收录的）必须也能被发现并建出来。

    2026-09-30 用户报："现在更新了 3 套新的声骸套装，我怎么没看到呢"。
    实测：3.7 的「衔梦照世之心 / 镜影流电之瞬 / 茜染怀想之花」库街区
    **已经有**（37 套），bwiki 还停在上个版本（34 套）。
    而代码**只拿 bwiki 的『声骸合鸣』页当套装名单** → 报「套装没有变化」，
    库街区明明带回了这些套装及其声骸，却整批被忽略。

    这组用例把"库街区也是套装名单的来源"钉住。
    """

    def test_check_reports_kuro_only_set(self):
        snapshot = RemoteSnapshot()
        snapshot.sets = {"凝夜白霜": _local()["sets"][0]["effects"]}   # bwiki 只有老套装
        snapshot.echoes_kuro = {"新套装甲": {4: ["某声骸"]}}            # 库街区有新的
        report = check_updates(snapshot, local_sets=_local())
        self.assertIn("新套装甲", report.new_sets)
        self.assertTrue(report.has_updates)

    def test_merge_creates_kuro_only_set(self):
        """★ 关键：库街区独有的套装要被**建出来**。

        不建的话，它带的声骸会在 _union_echoes 里因为"找不到这个套装"
        而**整批丢掉** —— 那正是新套装的声骸一条都进不来的原因。
        """
        local = _local()
        snapshot = RemoteSnapshot()
        snapshot.echoes_kuro = {"新套装甲": {4: ["某4C"], 1: ["某1C"]}}
        self.assertTrue(_merge_sets_data(local, snapshot))

        entry = next((s for s in local["sets"] if s["name"] == "新套装甲"), None)
        self.assertIsNotNone(entry, "库街区独有的套装必须被建出来")
        names = {e["name"] for e in entry["echoes"]}
        self.assertLessEqual({"某4C", "某1C"}, names, "它的声骸也要一起进来")
        # 效果文字留空（bwiki 才是效果来源），由手工补录兜底
        self.assertEqual(entry["effects"], [])

    def test_existing_set_effects_untouched(self):
        """已有套装被库街区提到时，效果文字不能被清空。"""
        local = _local()
        snapshot = RemoteSnapshot()
        snapshot.echoes_kuro = {"凝夜白霜": {1: ["新声骸甲"]}}
        _merge_sets_data(local, snapshot)
        first = local["sets"][0]
        self.assertEqual(first["effects"], [{"pieces": 2, "text": "冷凝伤害提升10%"}])
        self.assertIn("新声骸甲", {e["name"] for e in first["echoes"]})

    def test_duplicate_not_reported_twice(self):
        """同一个套装 bwiki 和库街区都有 → 只报一次（别在摘要里重复）。"""
        snapshot = RemoteSnapshot()
        snapshot.sets = {"新套装甲": [{"pieces": 2, "text": "x"}]}
        snapshot.echoes_kuro = {"新套装甲": {4: ["某声骸"]}}
        report = check_updates(snapshot, local_sets=_local())
        self.assertEqual(report.new_sets, ["新套装甲"])


class TestSetIcons(unittest.TestCase):
    """★ 套装图标要走**另一个 catalogue**（1219），不能只从声骸那份（1107）拿。

    2026-09-30 用户报："这里明明已经有了套装图标，为什么不加上去？"
    根因：``icon_urls`` 只从 catalogue 1107（声骸）取，而**套装图标在 1219**，
    所以套装图标永远是缺的、只能退化成占位图。
    """

    def test_kuro_page_maps_catalogue_ids(self):
        """catalogueId 映射表要写对：网页 URL 的 ``sid`` 才是 catalogueId。

        传 ``fid``（1099）会返回 0 条且 ``code=200``（**静默空**），
        很容易被误判成"这类没数据"。
        """
        import inspect

        from src.core import wuwa_update

        source = inspect.getsource(wuwa_update._kuro_page)
        for cid in ("1105", "1106", "1107", "1219"):
            self.assertIn(cid, source, f"catalogueId 映射里少了 {cid}")

    def test_set_icons_merged_from_1219(self):
        """套装图标记录要能被并进 ``icon_urls``（用假页面测，不打网络）。"""
        import unittest.mock as mock

        from src.core import wuwa_update

        echo_page = (
            [{"name": "某声骸", "content": {"contentUrl": "http://x/echo.png",
                                          "relateTagIds": []}}],
            {},
        )
        set_page = (
            [
                {"name": "新套装甲",
                 "content": {"contentUrl": "http://x/setA.png"}},
                {"name": "某声骸", "content": {"contentUrl": "http://x/evil.png"}},
            ],
            {},
        )

        def fake_page(cid, log):
            return set_page if str(cid) == "1219" else echo_page

        with mock.patch.object(wuwa_update, "_kuro_page", side_effect=fake_page):
            _by_set, icon_urls = wuwa_update._fetch_kurobbs(lambda _m: None)

        self.assertEqual(icon_urls.get("新套装甲"), "http://x/setA.png")
        # ⚠ 重名时**声骸那份优先**，不能被套装页覆盖
        self.assertEqual(icon_urls.get("某声骸"), "http://x/echo.png")

    def test_missing_set_icons_are_tolerated(self):
        """套装图标那一页拉失败**不该让整次更新挂掉**（图标是锦上添花）。"""
        import unittest.mock as mock

        from src.core import wuwa_update

        echo_page = ([], {})

        def fake_page(cid, log):
            if str(cid) == "1219":
                raise RuntimeError("这一页挂了")
            return echo_page

        with mock.patch.object(wuwa_update, "_kuro_page", side_effect=fake_page):
            _by_set, icon_urls = wuwa_update._fetch_kurobbs(lambda _m: None)
        self.assertEqual(icon_urls, {})


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
