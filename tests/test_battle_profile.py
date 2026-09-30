"""「角色战斗」配置 —— 数据层 + 界面接线。

    python tests/test_battle_profile.py

用户 2026-09-30 要求新增这一类配置：

    角色（下拉列表选择）；角色头像（与角色联动）；
    角色技能快捷键：声骸技能（默认 Q）、共鸣技能（默认 E）、共鸣解放（默认 R）；
    角色链路 +− 按钮，最大 6 最小 0；角色战斗脚本

★ 用户明确说"**先只存不跑**" —— 所以这里只验证"存得住、读得回、界面能编辑"，
**不该**出现任何按键执行相关的断言。
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.core import battle_profile as bp  # noqa: E402


class TestDefaults(unittest.TestCase):
    """默认值 —— 用户点名了三个快捷键。"""

    def test_skill_key_defaults(self):
        self.assertEqual(bp.DEFAULT_SKILL_KEYS["echo"], "Q")
        self.assertEqual(bp.DEFAULT_SKILL_KEYS["resonance"], "E")
        self.assertEqual(bp.DEFAULT_SKILL_KEYS["liberation"], "R")

    def test_new_profile_uses_defaults(self):
        profile = bp.BattleProfile(name="绯雪")
        self.assertEqual(profile.key_of("echo"), "Q")
        self.assertEqual(profile.key_of("resonance"), "E")
        self.assertEqual(profile.key_of("liberation"), "R")
        self.assertEqual(profile.chain, 0)
        self.assertEqual(profile.script, "")

    def test_chain_bounds_are_zero_to_six(self):
        self.assertEqual(bp.MIN_CHAIN, 0)
        self.assertEqual(bp.MAX_CHAIN, 6)


class TestChainClamp(unittest.TestCase):
    """★ 链路范围 0~6（用户要求："最大为 6 最小为 0"）。"""

    def test_clamps_high(self):
        self.assertEqual(bp.clamp_chain(99), 6)

    def test_clamps_low(self):
        self.assertEqual(bp.clamp_chain(-5), 0)

    def test_keeps_valid(self):
        for value in range(0, 7):
            with self.subTest(value=value):
                self.assertEqual(bp.clamp_chain(value), value)

    def test_junk_becomes_zero(self):
        for value in (None, "", "abc", [], {}):
            with self.subTest(value=value):
                self.assertEqual(bp.clamp_chain(value), 0)

    def test_constructor_clamps(self):
        """构造时也要夹 —— 手改过 JSON 的值不能越界。"""
        self.assertEqual(bp.BattleProfile(name="x", chain=99).chain, 6)
        self.assertEqual(bp.BattleProfile(name="x", chain=-3).chain, 0)


class TestSkillKeys(unittest.TestCase):
    """快捷键的规范化。"""

    def test_lowercase_becomes_upper(self):
        """``q`` 和 ``Q`` 是同一个键 —— 统一存大写，免得看着像两个。"""
        profile = bp.BattleProfile(name="x", skill_keys={"echo": "q"})
        self.assertEqual(profile.key_of("echo"), "Q")

    def test_empty_falls_back_to_default(self):
        """★ 空格子要回落到默认值。

        存成空串的话界面上那一格是空的，用户会以为坏了。
        """
        profile = bp.BattleProfile(name="x", skill_keys={"echo": ""})
        self.assertEqual(profile.key_of("echo"), "Q")

    def test_missing_keys_get_defaults(self):
        """老数据缺某个键 → 补默认值（三个格子都要有内容）。"""
        profile = bp.BattleProfile(name="x", skill_keys={"echo": "F"})
        self.assertEqual(profile.key_of("echo"), "F")
        self.assertEqual(profile.key_of("resonance"), "E")
        self.assertEqual(profile.key_of("liberation"), "R")

    def test_junk_skill_keys_dict(self):
        profile = bp.BattleProfile(name="x", skill_keys="不是字典")
        self.assertEqual(profile.key_of("echo"), "Q")

    def test_keys_text(self):
        profile = bp.BattleProfile(name="x")
        self.assertEqual(profile.keys_text,
                         "声骸技能 Q · 共鸣技能 E · 共鸣解放 R")


class TestStore(unittest.TestCase):
    """持久化 + 一角色一条。"""

    def _store(self):
        tmp = tempfile.mkdtemp()
        return bp.BattleProfileStore(pathlib.Path(tmp) / "battle_profiles.json")

    def test_roundtrip(self):
        store = self._store()
        store.add(bp.BattleProfile(name="绯雪", chain=4, script="Q E R\nloop"))
        reloaded = self._store()
        reloaded._path = store._path          # 同一个文件
        reloaded.load()
        profile = reloaded.get("绯雪")
        self.assertIsNotNone(profile)
        self.assertEqual(profile.chain, 4)
        self.assertEqual(profile.script, "Q E R\nloop")

    def test_one_profile_per_character(self):
        """★ 一个角色只能有一条（和另两类一致）。"""
        store = self._store()
        self.assertTrue(store.add(bp.BattleProfile(name="绯雪")))
        self.assertFalse(store.add(bp.BattleProfile(name="绯雪")),
                         "同一个角色加了两条")

    def test_remove_to_empty(self):
        store = self._store()
        store.add(bp.BattleProfile(name="绯雪"))
        self.assertTrue(store.remove("绯雪"))
        self.assertEqual(len(store), 0)

    def test_rename_rejects_taken(self):
        store = self._store()
        store.add(bp.BattleProfile(name="绯雪"))
        store.add(bp.BattleProfile(name="爱弥斯"))
        self.assertFalse(store.rename("绯雪", "爱弥斯"),
                         "改成已被占用的角色应该被拒")

    def test_occupied_characters(self):
        store = self._store()
        store.add(bp.BattleProfile(name="绯雪"))
        self.assertEqual(store.occupied_characters(), {"绯雪"})

    def test_by_id(self):
        store = self._store()
        profile = bp.BattleProfile(name="绯雪")
        store.add(profile)
        self.assertIsNotNone(store.by_id(profile.id))
        self.assertIsNone(store.by_id("不存在的id"))

    def test_stable_id_minted_and_saved(self):
        """★ 老数据（没有 id）要补发并**立刻落盘**。

        不落盘的话每次启动都换一个新 id，任务流程里指向它的步骤
        就永远找不到这条配置（echo_profile 踩过同一个坑）。
        """
        tmp = pathlib.Path(tempfile.mkdtemp())
        path = tmp / "battle_profiles.json"
        path.write_text(json.dumps({"profiles": [{"name": "绯雪"}]},
                                   ensure_ascii=False), encoding="utf-8")
        store = bp.BattleProfileStore(path)
        self.assertEqual(len(store), 1)
        raw = json.loads(path.read_text(encoding="utf-8"))
        self.assertTrue(raw["profiles"][0].get("id"), "id 没落盘")

    def test_corrupt_file_is_empty(self):
        tmp = pathlib.Path(tempfile.mkdtemp())
        path = tmp / "battle_profiles.json"
        path.write_text("{ 不是 json", encoding="utf-8")
        self.assertEqual(len(bp.BattleProfileStore(path)), 0)

    def test_nameless_entries_dropped(self):
        tmp = pathlib.Path(tempfile.mkdtemp())
        path = tmp / "battle_profiles.json"
        path.write_text(json.dumps({"profiles": [
            {"name": ""}, {"name": "绯雪"}]}, ensure_ascii=False),
            encoding="utf-8")
        store = bp.BattleProfileStore(path)
        self.assertEqual(store.names(), ["绯雪"])


class TestDescribe(unittest.TestCase):
    """列表行的摘要。"""

    def test_describe_mentions_keys_and_chain(self):
        text = bp.BattleProfile(name="x", chain=3).describe()
        self.assertIn("Q", text)
        self.assertIn("链路 3", text)

    def test_describe_reports_empty_script(self):
        self.assertIn("脚本（空）", bp.BattleProfile(name="x").describe())

    def test_describe_counts_script_lines(self):
        profile = bp.BattleProfile(name="x", script="第一行\n第二行")
        self.assertIn("脚本 2 行", profile.describe())


class TestConfigTypes(unittest.TestCase):
    """★ 第三类要接进「配置类型」那套（否则新增时选不到、任务里认不出）。"""

    def test_type_registered(self):
        from src.gui.config_names import CONFIG_TYPES, TYPE_BATTLE_PROFILE

        self.assertIn(TYPE_BATTLE_PROFILE, CONFIG_TYPES)

    def test_type_suffix(self):
        from src.gui.config_names import TYPE_BATTLE_PROFILE, type_suffix

        self.assertEqual(type_suffix(TYPE_BATTLE_PROFILE), "-战斗")

    def test_display_name(self):
        from src.gui.config_names import TYPE_BATTLE_PROFILE, config_display_name

        self.assertEqual(
            config_display_name(TYPE_BATTLE_PROFILE, "绯雪"), "绯雪-战斗")

    def test_kind_roundtrip(self):
        """kind ↔ 类型名 双向都要通。

        ⚠ 反向表漏一项的话，那种配置在任务里会**静默显示成筛选配置**。
        """
        from src.gui.config_names import (
            KIND_BATTLE_PROFILE, TYPE_BATTLE_PROFILE,
            kind_of_type, kind_type_name)

        self.assertEqual(kind_of_type(TYPE_BATTLE_PROFILE), KIND_BATTLE_PROFILE)
        self.assertEqual(kind_type_name(KIND_BATTLE_PROFILE), TYPE_BATTLE_PROFILE)

    def test_empty_kind_still_means_loadout(self):
        """老流程没存 kind —— 仍要当筛选（别被这次改动带偏）。"""
        from src.gui.config_names import TYPE_LOADOUT, kind_type_name

        self.assertEqual(kind_type_name(""), TYPE_LOADOUT)


class TestConfigPage(unittest.TestCase):
    """配置页上的接线。"""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def _page(self):
        from PySide6.QtWidgets import QWidget

        from src.gui.config_interface import ConfigInterface

        self._holder = QWidget()
        self._holder.resize(1200, 900)
        page = ConfigInterface()
        page.setParent(self._holder)
        page.resize(1200, 900)
        # 用临时存储，别碰真实用户数据
        page.battles = bp.BattleProfileStore(
            pathlib.Path(tempfile.mkdtemp()) / "battle_profiles.json")
        page._holder = self._holder
        self._holder.show()
        self.app.processEvents()
        return page

    def test_page_has_battle_store(self):
        page = self._page()
        self.assertTrue(hasattr(page, "battles"))

    def test_add_and_render_row(self):
        from src.gui.config_interface import BattleProfileRow

        page = self._page()
        page.battles.add(bp.BattleProfile(name="绯雪", chain=2))
        page.reload()
        self.app.processEvents()
        rows = page.findChildren(BattleProfileRow)
        self.assertEqual(len(rows), 1)
        self.assertIn("链路 2", rows[0].summary.text())

    def test_subtitle_counts_battle(self):
        page = self._page()
        page.battles.add(bp.BattleProfile(name="绯雪"))
        page.reload()
        self.app.processEvents()
        self.assertIn("角色战斗", page.subtitle.text())

    def test_search_filters_battle_rows(self):
        """搜索也要管这一类（三类的名字都是角色名）。"""
        from src.gui.config_interface import BattleProfileRow

        page = self._page()
        page.battles.add(bp.BattleProfile(name="绯雪"))
        page.battles.add(bp.BattleProfile(name="爱弥斯"))
        page.reload()
        page.search_edit.setText("绯雪")
        self.app.processEvents()
        rows = page.findChildren(BattleProfileRow)
        self.assertEqual(len(rows), 1, "搜索没过滤战斗配置")
        self.assertEqual(rows[0].profile.name, "绯雪")

    def test_row_width_applied(self):
        """新行也要拿到摘要宽度（否则换行文字高度算不准）。"""
        from src.gui.config_interface import BattleProfileRow

        page = self._page()
        page.battles.add(bp.BattleProfile(name="绯雪"))
        page.reload()
        self.app.processEvents()
        rows = page.findChildren(BattleProfileRow)
        self.assertTrue(rows)
        self.assertGreater(rows[0].summary.width(), 100)


class TestDialog(unittest.TestCase):
    """编辑弹框：默认值 / 链路 +− / 头像联动 / 只读。"""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def _dialog(self, **kwargs):
        from PySide6.QtWidgets import QWidget

        from src.gui.battle_profile_ui import BattleProfileDialog

        self._holder = QWidget()
        self._holder.resize(900, 800)
        dialog = BattleProfileDialog(self._holder, **kwargs)
        dialog.setParent(self._holder)
        self._holder.show()
        self.app.processEvents()
        return dialog

    def test_default_keys_in_edits(self):
        dialog = self._dialog()
        self.assertEqual(dialog.key_edits["echo"].text(), "Q")
        self.assertEqual(dialog.key_edits["resonance"].text(), "E")
        self.assertEqual(dialog.key_edits["liberation"].text(), "R")

    def test_chain_step_and_clamp(self):
        """★ +/− 每次 1，且夹在 0~6。"""
        dialog = self._dialog()
        self.assertEqual(dialog.chain_value, 0)
        dialog._step_chain(1)
        self.assertEqual(dialog.chain_value, 1)
        for _ in range(20):
            dialog._step_chain(1)
        self.assertEqual(dialog.chain_value, 6)
        for _ in range(20):
            dialog._step_chain(-1)
        self.assertEqual(dialog.chain_value, 0)

    def test_chain_buttons_disable_at_bounds(self):
        """到边界灰掉按钮 —— 点了没反应会让人以为坏了。"""
        dialog = self._dialog()
        self.assertFalse(dialog.chain_minus.isEnabled(), "0 时减号该灰掉")
        self.assertTrue(dialog.chain_plus.isEnabled())
        for _ in range(10):
            dialog._step_chain(1)
        self.assertFalse(dialog.chain_plus.isEnabled(), "6 时加号该灰掉")
        self.assertTrue(dialog.chain_minus.isEnabled())

    def test_avatar_follows_character(self):
        """★ 头像与角色联动。"""
        from qfluentwidgets import IconWidget

        dialog = self._dialog()
        dialog.characterBox.setText("绯雪")
        self.app.processEvents()
        first = dialog.avatar_holder.findChildren(IconWidget)
        self.assertTrue(first, "选了角色却没显示头像")
        key_before = first[0].getIcon().cacheKey()

        dialog.characterBox.setText("爱弥斯")
        self.app.processEvents()
        second = dialog.avatar_holder.findChildren(IconWidget)
        self.assertTrue(second)
        self.assertNotEqual(second[0].getIcon().cacheKey(), key_before,
                            "换了角色但头像没跟着变")

    def test_result_profile_reads_widgets(self):
        dialog = self._dialog()
        dialog.characterBox.setText("绯雪")
        dialog.key_edits["echo"].setText("F")
        dialog._step_chain(1)
        dialog.script_edit.setPlainText("Q E R")
        profile = dialog.result_profile()
        self.assertEqual(profile.name, "绯雪")
        self.assertEqual(profile.key_of("echo"), "F")
        self.assertEqual(profile.chain, 1)
        self.assertEqual(profile.script, "Q E R")

    def test_editing_existing_fills_widgets(self):
        existing = bp.BattleProfile(name="绯雪", chain=5,
                                    skill_keys={"echo": "F"},
                                    script="已有脚本")
        dialog = self._dialog(profile=existing)
        self.assertEqual(dialog.characterBox.text(), "绯雪")
        self.assertEqual(dialog.key_edits["echo"].text(), "F")
        self.assertEqual(dialog.chain_value, 5)
        self.assertEqual(dialog.script_edit.toPlainText(), "已有脚本")

    def test_read_only_disables_editing(self):
        existing = bp.BattleProfile(name="绯雪")
        dialog = self._dialog(profile=existing, read_only=True)
        self.assertFalse(dialog.script_edit.isEnabled())
        self.assertFalse(dialog.key_edits["echo"].isEnabled())
        self.assertFalse(dialog.chain_plus.isEnabled())
        self.assertFalse(dialog.chain_minus.isEnabled())

    def test_taken_characters_excluded_and_rejected(self):
        """已被别的配置占用的角色：候选里没有，手打也会被拦。"""
        from src.core.game_data import character_choice_error

        dialog = self._dialog(taken_chars=("爱弥斯",))
        names = [text for text, _icon in dialog.characterBox._all]
        self.assertNotIn("爱弥斯", names)
        dialog.characterBox.setText("爱弥斯")
        self.assertFalse(dialog.validate(), "占用的角色不该通过校验")
        self.assertTrue(dialog.errorLabel.isVisible())
        # 共用同一份校验规则（不是自己又写一套）
        self.assertIsNotNone(
            character_choice_error("爱弥斯", {"爱弥斯"}, bp.MAX_NAME_LENGTH))


if __name__ == "__main__":
    unittest.main(verbosity=2)
