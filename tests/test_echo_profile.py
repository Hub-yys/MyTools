"""「角色声骸强化」配置（``src/core/echo_profile.py``）单测。

这层是纯逻辑（不依赖 Qt），所以能直接把边界情况钉死：

* ★ **和「声骸自动强化」工具的设置无关** —— 没有 active / 设为当前这种概念
  （用户 2026-09-26 明确否掉了把两者绑在一起的设计）；
* ★ **名字就是角色名**：一个角色只能有一条，重名（＝重复角色）必须拒绝；
* ★ **不再有「默认」那条** —— 不种子，而且启动时会把遗留的「默认」清掉
  （用户 2026-09-26 明确："去掉种子并删掉已有的「默认」"）；
* **名字有长度上限** —— 超长名字会把列表行撑破；
* **坏数据不许把列表打崩**。
"""

from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.core.echo_profile import (  # noqa: E402
    LEGACY_DEFAULT_NAME,
    MAX_NAME_LENGTH,
    EchoProfile,
    EchoProfileStore,
)


def store_in(tmp: str) -> EchoProfileStore:
    return EchoProfileStore(path=pathlib.Path(tmp) / "echo_profiles.json")


class TestNoCouplingWithTool(unittest.TestCase):
    """★ 这类配置和强化工具的设置**无关** —— 别把"当前使用"那套概念加回来。

    曾经实现过 `active` + 「设为当前」（把配置写进 tool_settings），
    用户明确否掉了：两者互不影响。
    """

    def test_store_has_no_active_concept(self):
        store = EchoProfileStore(path=pathlib.Path("x.json"))
        for attr in ("active", "set_active"):
            self.assertFalse(hasattr(store, attr),
                             f"不该再有 {attr} —— 那是「配置即工具规则」的设计")

    def test_store_never_writes_tool_settings(self):
        """仓库源码里不该**调用** ``tool_settings.save``。

        ⚠ 只查调用（``save(`` / ``load(``），别按"出现 tool_settings"来判 ——
        注释里说明"文件放在 tool_settings 旁边"是正常且必要的
        （我第一版就是这么写的，被这条用例的正确版本纠了回来）。
        唯一允许的接触是取路径：``tool_settings.settings_file()``。
        """
        src = (ROOT / "src/core/echo_profile.py").read_text(
            encoding="utf-8", errors="replace")
        for banned in ("tool_settings.save(", "tool_settings.load("):
            self.assertNotIn(banned, src, f"仓库不该调用 {banned}")
        # 取路径的那处必须在，否则隔离会失效（见
        # TestPathSharesToolSettingsDir）
        self.assertIn("tool_settings.settings_file()", src)

    def test_tool_page_has_no_profile_selector(self):
        """强化工具页上不该有"用哪条配置"的**选择器**（那等于把两者绑起来）。"""
        src = (ROOT / "src/tools/game/echo_enhance/tool.py").read_text(
            encoding="utf-8", errors="replace")
        for banned in ("profile_box", "_on_profile_changed", "_sync_active_profile"):
            self.assertNotIn(banned, src, f"工具页不该出现 {banned}")

    def test_tool_page_only_READS_echo_profiles(self):
        """★ 工具页可以**读**强化配置，但**绝不许写**。

        两条用户要求要能并存：

        * 2026-09-26 早先："角色声骸强化配置与声骸自动强化工具的配置**无关**"
          —— 配置页改东西不能动工具页、反之亦然，没有"设为当前 / 自动同步"那套；
        * 2026-09-26 晚些："**声骸自动工具会启用声骸强化配置的条件进行强化**"
          —— 编排里**显式挂**了哪条配置，这次运行就用它的条件。

        并存的关键是：**读**是显式的、只在流程里挂了那一条时才发生；
        绝不能"读进来又写回去"。所以这条护栏禁的是**写**。

        ⚠ 本用例原来禁的是"源码里不许出现 ``EchoProfileStore``"——太粗暴，
        在"挂配置就生效"这个需求下直接把正确实现也拦了。改成只禁写。
        """
        src = (ROOT / "src/tools/game/echo_enhance/tool.py").read_text(
            encoding="utf-8", errors="replace")
        for banned in ("store.save(", "store.add(", "store.update(",
                       "store.rename(", "store.remove(",
                       "profile.save(", "profile.settings ="):
            self.assertNotIn(banned, src, f"工具页不该写强化配置：{banned}")
        # 反证这条护栏不是空转：读路径确实在（不然"禁写"没有意义）
        self.assertIn("by_id(", src, "工具页应当按稳定 id 读配置")
        self.assertIn("ECHO_PROFILE_KIND", src,
                      "应当按配置类型认出「强化配置」")

    def test_run_settings_prefer_bound_profile(self):
        """★ 编排里挂了强化配置 → 用它的条件；没挂 → 回退工具页设置。

        用户 2026-09-26："声骸自动工具会启用声骸强化配置的条件进行强化"。
        """
        from src.tools.game.echo_enhance.settings import EchoSettings
        from src.tools.game.echo_enhance.tool import EchoEnhanceTool

        tool = EchoEnhanceTool()
        logs: list[str] = []
        with tempfile.TemporaryDirectory() as tmp:
            store = EchoProfileStore(path=pathlib.Path(tmp) / "echo_profiles.json")
            profile = EchoProfile(name="绯雪", settings={
                "core_stats": ["暴击", "暴击伤害", "攻击百分比"],
                # ⚠ min_valid_count 要落在**合法范围**里：核心 3 条、没勾可选 → 范围就是 3~3，
                #   写 4 会被引擎正确钳成 3（第一版我写 4、断言 4，红了一次）
                "min_valid_count": 3, "crit_min": 9.5, "crit_dmg_min": 21.0})
            store.add(profile)

            original = EchoProfileStore
            try:
                # 让工具里的按需导入拿到我们这个临时仓库
                import src.core.echo_profile as mod
                mod.EchoProfileStore = lambda *a, **k: store

                bound = {"configs": ["绯雪-声骸强化"], "config_keys": [profile.id],
                         "config_kinds": ["echo_profile"]}
                settings, source = tool._settings_for_run(bound, logs.append)
            finally:
                mod.EchoProfileStore = original

        # 双爆下限是**自由数值**，最能证明"用的是配置里那套"（4 条里它不会被钳）
        self.assertEqual(settings.crit_min, 9.5, "应当用了配置里的条件")
        self.assertEqual(settings.crit_dmg_min, 21.0)
        self.assertEqual(settings.min_valid_count, 3)
        self.assertIn("绯雪", source, f"来源说明里要点出是哪条配置：{source}")

        # 没挂配置 → 退回工具页那份（不该炸）
        fallback, source2 = EchoEnhanceTool()._settings_for_run({}, logs.append)
        self.assertEqual(fallback.to_dict(), EchoSettings.load().to_dict())
        self.assertIn("工具页", source2)

        # 挂了但配置已经不在了 → 回退 + 明确说一声
        gone, source3 = EchoEnhanceTool()._settings_for_run(
            {"configs": ["早就删了的"], "config_keys": ["不存在的id"],
             "config_kinds": ["echo_profile"]}, logs.append)
        self.assertIn("工具页", source3)
        self.assertTrue(any("找不到" in line for line in logs),
                        f"配置没了要说一声：{logs}")

    def test_run_settings_ignore_other_config_kinds(self):
        """挂了**别的类型**的配置（比如筛选配置）不该被当成强化条件。"""
        from src.tools.game.echo_enhance.tool import EchoEnhanceTool

        with tempfile.TemporaryDirectory() as tmp:
            store = EchoProfileStore(path=pathlib.Path(tmp) / "echo_profiles.json")
            profile = EchoProfile(name="绯雪", settings={"min_valid_count": 5})
            store.add(profile)
            import src.core.echo_profile as mod
            original = mod.EchoProfileStore
            try:
                mod.EchoProfileStore = lambda *a, **k: store
                _, source = EchoEnhanceTool()._settings_for_run(
                    {"config_keys": [profile.id], "config_kinds": ["loadout"]},
                    lambda _m: None)
            finally:
                mod.EchoProfileStore = original
        self.assertIn("工具页", source, f"筛选配置不该被当成强化条件：{source}")


class TestProfileDescribe(unittest.TestCase):
    def test_summary_mentions_key_settings(self):
        p = EchoProfile(name="刷4C", settings={
            "core_stats": ["暴击", "暴击伤害"],
            "crit_min": 7.5, "crit_dmg_min": 15.0, "min_valid_count": 3,
        })
        text = p.describe()
        self.assertIn("暴击", text)
        self.assertIn("7.5", text)
        self.assertIn("15", text)
        self.assertIn("3", text)

    def test_empty_settings_does_not_crash(self):
        """空/坏 settings 也要能显示 —— 老数据或手改过的文件都可能长这样。"""
        self.assertTrue(EchoProfile(name="x", settings={}).describe())
        self.assertTrue(EchoProfile(name="x").describe())

    def test_missing_keys_use_defaults(self):
        text = EchoProfile(name="x", settings={"core_stats": ["暴击"]}).describe()
        self.assertIn("7.5", text)
        self.assertIn("15", text)


class TestNameIsCharacter(unittest.TestCase):
    """★ 名字就是角色名（2026-09-26 晚）。

    这么改的直接原因：行上的头像是拿名字去 ``find_character`` 查的，
    名字一旦是自由文本（用户实测输入"绯雪声骸强化配置"）→ 查不到 → **头像消失**。
    """

    def test_blank_name_stays_blank(self):
        """⚠ 空名字**不再兜底成「默认」** —— 那会凭空造出一条不是角色的配置。"""
        self.assertEqual(EchoProfile(name="   ").name, "")
        self.assertEqual(EchoProfile(name="").name, "")

    def test_name_is_trimmed(self):
        self.assertEqual(EchoProfile(name="  绯雪  ").name, "绯雪")

    def test_name_is_capped(self):
        """超长名字要截断 —— 否则列表行会被撑破（用户截图那个问题）。"""
        long_name = "非" * (MAX_NAME_LENGTH + 20)
        self.assertEqual(len(EchoProfile(name=long_name).name), MAX_NAME_LENGTH)

    def test_blank_name_entry_is_dropped_on_load(self):
        """名字空的条目在界面上既没头像也点不出东西 —— 当坏数据丢掉。"""
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "echo_profiles.json"
            path.write_text(json.dumps({
                "profiles": [{"name": "", "settings": {}}, {"name": "绯雪"}],
            }), encoding="utf-8")
            store = EchoProfileStore(path=path)
            store.load()
            self.assertEqual(store.names(), ["绯雪"])


class TestStoreCrud(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = store_in(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def add(self, name, **kw):
        return self.store.add(EchoProfile(name=name, settings=kw or {}))

    def test_empty_store(self):
        self.store.load()
        self.assertEqual(len(self.store), 0)
        self.assertEqual(self.store.names(), [])

    def test_add_and_persist(self):
        self.add("A")
        self.add("B")
        again = store_in(self._tmp.name)
        again.load()
        self.assertEqual(again.names(), ["A", "B"])

    def test_duplicate_name_rejected(self):
        """★ 名字就是角色 —— 重复＝同一个角色有两条配置，必须拒绝。"""
        self.assertTrue(self.add("A"))
        self.assertFalse(self.add("A"), "同一角色只能有一条")
        self.assertEqual(len(self.store), 1)

    def test_blank_name_rejected(self):
        self.assertFalse(self.add(""))
        self.assertFalse(self.add("   "))
        self.assertEqual(len(self.store), 0)

    def test_rename(self):
        self.add("A")
        self.assertTrue(self.store.rename("A", "B"))
        self.assertEqual(self.store.names(), ["B"])

    def test_rename_to_existing_rejected(self):
        """换成另一个**已被占用**的角色要拒绝。"""
        self.add("A")
        self.add("B")
        self.assertFalse(self.store.rename("A", "B"))

    def test_rename_blank_rejected(self):
        self.add("A")
        self.assertFalse(self.store.rename("A", "   "))

    def test_remove(self):
        self.add("A")
        self.add("B")
        self.assertTrue(self.store.remove("B"))
        self.assertEqual(self.store.names(), ["A"])

    def test_can_remove_last_one(self):
        """★ 可以删到一条不剩 —— 用户 2026-09-26 要求。"""
        self.add("A")
        self.assertTrue(self.store.remove("A"))
        self.assertEqual(len(self.store), 0)
        self.assertEqual(self.store.names(), [])

    def test_occupied_characters(self):
        """界面用这个把"一角色一条"做成下拉里选不到。"""
        self.add("绯雪")
        self.add("清宵")
        self.assertEqual(self.store.occupied_characters(), {"绯雪", "清宵"})

    def test_duplicate(self):
        self.add("A", core_stats=["暴击"])
        self.assertTrue(self.store.duplicate("A", "A副本"))
        self.assertEqual(self.store.get("A副本").settings["core_stats"], ["暴击"])


class TestNoDefaultProfile(unittest.TestCase):
    """★ 不再有「默认」那条（用户 2026-09-26 明确）。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = store_in(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_missing_file_does_not_seed_anything(self):
        """第一次跑：文件不存在也**不种子**（老版本会种一条「默认」）。"""
        self.store.load()
        self.assertEqual(len(self.store), 0)

    def test_deleted_all_are_not_resurrected(self):
        """★ 删光之后**不能下次启动又冒出来**。

        现在根本没有种子逻辑了，所以"重载 → 还是空的"是必然的；
        这条留着是防回归 —— 谁要是把种子加回来，这里会红。
        """
        self.store.add(EchoProfile(name="绯雪"))
        self.store.remove("绯雪")
        self.assertTrue(self.store.path.exists(), "删空后文件应当还在（只是列表为空）")

        again = store_in(self._tmp.name)
        again.load()
        self.assertEqual(len(again), 0, "重载应当是空的")

    def test_purge_removes_legacy_default(self):
        """★ 启动时要把遗留的「默认」清掉。"""
        self.store.add(EchoProfile(name=LEGACY_DEFAULT_NAME))
        self.store.add(EchoProfile(name="绯雪"))
        self.assertTrue(self.store.purge_legacy_default())
        self.assertEqual(self.store.names(), ["绯雪"])

    def test_purge_is_written_to_disk(self):
        """清理要落盘 —— 否则下次启动又读回来了。"""
        self.store.add(EchoProfile(name=LEGACY_DEFAULT_NAME))
        self.store.purge_legacy_default()
        again = store_in(self._tmp.name)
        again.load()
        self.assertEqual(again.names(), [])

    def test_purge_is_noop_when_absent(self):
        """没有「默认」时什么都不做、也不报错（正常情况每次都走这条）。"""
        self.store.add(EchoProfile(name="绯雪"))
        self.assertFalse(self.store.purge_legacy_default())
        self.assertEqual(self.store.names(), ["绯雪"])

    def test_purge_keeps_other_profiles(self):
        """⚠ 只认**恰好叫「默认」**的那条，别误伤别的角色。"""
        self.store.add(EchoProfile(name="默认角色"))
        self.store.add(EchoProfile(name="绯雪"))
        self.store.purge_legacy_default()
        self.assertEqual(sorted(self.store.names()), ["绯雪", "默认角色"])

    def test_purge_does_not_touch_tool_settings(self):
        """★ 清理「默认」**不能**顺手改工具页的设置 —— 两者无关（用户明确）。

        老实现的种子是"从工具页设置复制"，清理不能反过来写回去。
        """
        src = (ROOT / "src/core/echo_profile.py").read_text(
            encoding="utf-8", errors="replace")
        start = src.index("def purge_legacy_default")
        end = src.find("\n    def ", start + 10)
        body = src[start:end if end > 0 else len(src)]
        for banned in ("tool_settings.save(", "tool_settings.load("):
            self.assertNotIn(banned, body, f"清理不该调用 {banned}")


class TestBadData(unittest.TestCase):
    """坏文件不许把界面打崩。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = pathlib.Path(self._tmp.name) / "echo_profiles.json"

    def tearDown(self):
        self._tmp.cleanup()

    def test_broken_json(self):
        self.path.write_text("{ 这不是 json", encoding="utf-8")
        store = EchoProfileStore(path=self.path)
        store.load()
        self.assertEqual(len(store), 0)

    def test_wrong_shape(self):
        self.path.write_text(json.dumps(["不是对象"]), encoding="utf-8")
        store = EchoProfileStore(path=self.path)
        store.load()
        self.assertEqual(len(store), 0)

    def test_items_with_bad_entries(self):
        """坏项丢掉、好项照常读出来 —— 不抛就行。"""
        self.path.write_text(json.dumps({
            "profiles": ["不是对象", {"name": "A"}],
        }), encoding="utf-8")
        store = EchoProfileStore(path=self.path)
        store.load()
        self.assertEqual(store.names(), ["A"], "没有名字的坏项应当被丢掉")

    def test_legacy_active_key_is_ignored(self):
        """老文件里若还留着 ``active`` 字段，读的时候直接忽略（不再有意义）。"""
        self.path.write_text(json.dumps({
            "active": "A", "profiles": [{"name": "A"}],
        }), encoding="utf-8")
        store = EchoProfileStore(path=self.path)
        store.load()
        self.assertEqual(store.names(), ["A"])


class TestStableId(unittest.TestCase):
    """★ 每条配置有个**稳定 id**（2026-09-26 加）。

    为什么需要：名字就是角色名、**会变**（用户换角色 = 改名），
    而任务流程里的步骤要指向"这一条配置"、并在改名后跟着变。
    存名字的话用户一改名，流程里那一步就找不到配置了（实测踩过）。
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = store_in(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_new_profile_gets_id(self):
        p = EchoProfile(name="绯雪")
        self.assertTrue(p.id, "新建时必须分配 id")
        self.assertNotEqual(p.id, EchoProfile(name="绯雪").id, "两条的 id 不能撞")

    def test_id_survives_rename(self):
        """★ 改名（＝换角色）不能把 id 换掉 —— 这正是它存在的理由。"""
        self.store.add(EchoProfile(name="绯雪"))
        before = self.store.get("绯雪").id
        self.assertTrue(self.store.rename("绯雪", "清宵"))
        self.assertEqual(self.store.get("清宵").id, before)

    def test_by_id_lookup(self):
        self.store.add(EchoProfile(name="绯雪"))
        item = self.store.get("绯雪")
        self.assertIs(self.store.by_id(item.id), item)
        self.assertIsNone(self.store.by_id("不存在的 id"))
        self.assertIsNone(self.store.by_id(""))

    def test_legacy_file_without_id_is_migrated_and_persisted(self):
        """★ 老文件没有 id → 补发并**立刻落盘**。

        不落盘的话每次启动都换一个新 id，流程里指向它的步骤就永远找不到它。
        """
        path = pathlib.Path(self._tmp.name) / "echo_profiles.json"
        path.write_text(json.dumps({
            "profiles": [{"name": "绯雪", "created": "2026-09-01 10:00:00",
                          "settings": {"min_valid_count": 3}}],
        }, ensure_ascii=False), encoding="utf-8")

        first = EchoProfileStore(path=path)
        first.load()
        got = first.get("绯雪").id
        self.assertTrue(got, "老数据要被补上 id")
        self.assertIn('"id"', path.read_text(encoding="utf-8"),
                      "补发的 id 必须当场落盘")

        second = EchoProfileStore(path=path)
        second.load()
        self.assertEqual(second.get("绯雪").id, got, "重读一遍 id 不能变")

    def test_migration_keeps_settings(self):
        """补 id 不能动到用户的设置。"""
        path = pathlib.Path(self._tmp.name) / "echo_profiles.json"
        path.write_text(json.dumps({
            "profiles": [{"name": "绯雪", "settings": {"min_valid_count": 5}}],
        }, ensure_ascii=False), encoding="utf-8")
        store = EchoProfileStore(path=path)
        store.load()
        self.assertEqual(store.get("绯雪").settings["min_valid_count"], 5)


class TestPathSharesToolSettingsDir(unittest.TestCase):
    """★ 配置文件必须跟 ``tool_settings`` **同目录**。

    那些 GUI 检查脚本靠 monkeypatch ``tool_settings.settings_file`` 做隔离；
    路径跟着它走才会自动被隔离覆盖 —— 否则测试会往**真实用户数据**里写文件。
    """

    def test_default_path_follows_tool_settings(self):
        from src.core import tool_settings
        from src.core.echo_profile import profiles_file

        original = tool_settings.settings_file
        try:
            tool_settings.settings_file = lambda: pathlib.Path("/tmp/xyz/tool_settings.json")
            self.assertEqual(profiles_file().parent, pathlib.Path("/tmp/xyz"))
        finally:
            tool_settings.settings_file = original


if __name__ == "__main__":
    unittest.main(verbosity=2)
