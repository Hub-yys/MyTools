"""武器图鉴的数据与界面接线检查。

    python tests/test_weapons.py

用户 2026-09-30 要求："把武器图也放到资源库，资源库新增分类，武器图鉴"。

武器数据在 ``src/core/data/wuwa_weapons.json``（从库街区 catalogue 1106 整理），
由 ``game_data.WEAPONS`` 加载；界面在资源库页的「武器图鉴」分区。
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.core import game_data  # noqa: E402

DATA_FILE = ROOT / "src" / "core" / "data" / "wuwa_weapons.json"


class TestWeaponData(unittest.TestCase):
    """数据文件本身。"""

    @classmethod
    def setUpClass(cls):
        game_data.ensure_loaded()

    def test_file_exists_and_is_valid_json(self):
        self.assertTrue(DATA_FILE.exists(), "少了 wuwa_weapons.json")
        raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        self.assertIsInstance(raw.get("weapons"), list)

    def test_weapons_loaded(self):
        self.assertGreater(len(game_data.WEAPONS), 100,
                           f"武器太少（{len(game_data.WEAPONS)}），数据没加载上？")

    def test_every_weapon_has_name_and_rarity(self):
        for weapon in game_data.WEAPONS:
            with self.subTest(name=weapon.name):
                self.assertTrue(weapon.name)
                self.assertIn(weapon.rarity, (1, 2, 3, 4, 5),
                              f"{weapon.name} 星级异常：{weapon.rarity}")

    def test_types_are_known_weapons(self):
        """类型必须是游戏里的五种之一（数据映射错了会冒出怪值）。"""
        allowed = {"长刃", "迅刀", "佩枪", "臂铠", "音感仪"}
        bad = {w.type for w in game_data.WEAPONS if w.type not in allowed}
        self.assertEqual(bad, set(), f"出现了未知武器类型：{bad}")

    def test_names_unique(self):
        names = [w.name for w in game_data.WEAPONS]
        self.assertEqual(len(names), len(set(names)), "武器名有重复")

    def test_icon_path_is_derived(self):
        """★ 图标路径**按名字推导**，不存进数据文件。

        存两份迟早对不上（角色那边也是这么处理的）。
        """
        weapon = game_data.WEAPONS[0]
        self.assertEqual(weapon.icon, f"weapons/{weapon.name}.png")

    def test_tagline_mentions_rarity_type_stat(self):
        with_stat = next((w for w in game_data.WEAPONS if w.stat), None)
        self.assertIsNotNone(with_stat, "没有一把武器有主词条？")
        self.assertIn("星", with_stat.tagline)
        self.assertIn(with_stat.type, with_stat.tagline)


class TestWeaponLibrarySection(unittest.TestCase):
    """资源库页要有「武器图鉴」分区。"""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])
        game_data.ensure_loaded()

    def _page(self):
        from PySide6.QtWidgets import QWidget

        from src.gui.library_interface import WuwaLibraryInterface

        holder = QWidget()
        holder.resize(1200, 900)
        self._holders = getattr(self, "_holders", [])
        self._holders.append(holder)
        page = WuwaLibraryInterface()
        page.setParent(holder)
        page.resize(1200, 900)
        holder.show()
        self.app.processEvents()
        return page

    def test_section_exists_with_title(self):
        """★ 分区标题要写「武器图鉴（N）」。"""
        from PySide6.QtWidgets import QLabel

        from src.gui.widgets import CollapsibleCard

        page = self._page()
        titles = []
        for card in page.findChildren(CollapsibleCard):
            for label in card.findChildren(QLabel):
                text = label.text()
                if text.startswith("武器图鉴"):
                    titles.append(text)
        self.assertTrue(titles, "资源库里没有「武器图鉴」分区")

    def test_rows_rendered(self):
        """每个武器一行（_WeaponRow）。"""
        from src.gui.library_interface import _WeaponRow

        page = self._page()
        rows = page.findChildren(_WeaponRow)
        self.assertEqual(len(rows), len(game_data.WEAPONS),
                         "武器行数和数据对不上")

    def test_weapon_row_shows_name_and_tagline(self):
        """每行要显示**名字 + 星级·类型·主词条**（不是光一个名字）。"""
        from PySide6.QtWidgets import QLabel

        from src.gui.library_interface import _WeaponRow

        page = self._page()
        rows = page.findChildren(_WeaponRow)
        self.assertTrue(rows, "没有武器行")
        row = rows[0]
        texts = [lb.text() for lb in row.findChildren(QLabel)]
        self.assertIn(row.weapon.name, texts, f"行里没有武器名：{texts}")
        self.assertTrue(
            any(row.weapon.type in t for t in texts),
            f"行里没显示类型（{row.weapon.type}）：{texts}")

    def test_grouped_by_type(self):
        """★ 按武器类型分组（长刃 / 迅刀 / …），和声骸按 COST 分组一个思路。"""
        from PySide6.QtWidgets import QLabel

        from src.gui.widgets import CollapsibleCard

        page = self._page()
        card = None
        for candidate in page.findChildren(CollapsibleCard):
            if any(lb.text().startswith("武器图鉴")
                   for lb in candidate.findChildren(QLabel)):
                card = candidate
                break
        self.assertIsNotNone(card, "没找到武器图鉴分区")

        groups = [lb.text() for lb in card.findChildren(QLabel)
                  if lb.text().endswith("）") and "星" not in lb.text()]
        for expected in ("长刃", "迅刀", "佩枪", "臂铠", "音感仪"):
            with self.subTest(group=expected):
                self.assertTrue(any(g.startswith(expected) for g in groups),
                                f"少了「{expected}」分组：{groups}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
