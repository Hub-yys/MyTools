"""改名迁移：老用户数据目录（MyTools）→ 新名字（WutheringWavesTools）。

2026-09-24 把工具改名成 WutheringWavesTools / 鸣潮工具箱，用户数据目录名跟着变了。
**这一步有真实风险**：目录名一改，老目录里的配置（装备/任务流程/设置）就"读不到"了 ——
文件还在磁盘上，但程序看不见，用户体感就是"我的配置全没了"。

所以有三条必须守住的性质，下面逐条断言：

1. 新目录不存在时，**整树继承**老目录；
2. 新目录已存在时**什么都不做** —— 绝不能拿旧文件回头覆盖新配置；
3. 用**复制**而不是移动：老目录原样留着当兜底；
4. 继承必须**早于**种子播种，否则种子会以为"目录是空的"而铺一套默认值。
"""

from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.core import paths  # noqa: E402


class _TempCase(unittest.TestCase):
    """把 paths 里的路径函数指向临时目录（绝不碰用户真正的配置）。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.target = self.base / "WutheringWavesTools"

    def patch(self, name: str, value) -> None:
        original = getattr(paths, name)
        setattr(paths, name, value)
        self.addCleanup(setattr, paths, name, original)

    def make_legacy(self) -> Path:
        legacy = self.base / "MyTools"
        (legacy / "game_data").mkdir(parents=True, exist_ok=True)
        (legacy / "loadouts.json").write_text('{"mine": true}', encoding="utf-8")
        (legacy / "game_data" / "wuwa_characters.json").write_text(
            '{"characters": []}', encoding="utf-8"
        )
        return legacy


class TestMigrateLegacyUserData(_TempCase):
    def test_copies_whole_tree_when_target_missing(self):
        legacy = self.make_legacy()
        done = paths.migrate_legacy_user_data(self.base, self.target)

        self.assertEqual(done, ["MyTools/ → WutheringWavesTools/"])
        self.assertEqual(
            json.loads((self.target / "loadouts.json").read_text(encoding="utf-8")),
            {"mine": True},
        )
        self.assertTrue((self.target / "game_data" / "wuwa_characters.json").is_file())
        # 老目录必须原样留着（复制而不是移动）
        self.assertTrue(legacy.is_dir(), "老目录不能被删/被搬空")
        self.assertTrue((legacy / "loadouts.json").is_file())

    def test_does_nothing_when_target_exists(self):
        """新目录已经有东西 = 用户已经在用新名字了，绝不能拿旧文件覆盖回去。"""
        self.make_legacy()
        self.target.mkdir()
        mine = self.target / "loadouts.json"
        mine.write_text('{"newer": true}', encoding="utf-8")

        self.assertEqual(paths.migrate_legacy_user_data(self.base, self.target), [])
        self.assertEqual(
            json.loads(mine.read_text(encoding="utf-8")), {"newer": True},
            "新配置被旧文件覆盖了 —— 这正是最不能发生的事",
        )
        self.assertFalse((self.target / "game_data").exists(), "不该拷任何东西进来")

    def test_no_legacy_dir_is_not_an_error(self):
        """从没装过老版本（全新用户）时不能抛异常。"""
        self.assertEqual(paths.migrate_legacy_user_data(self.base, self.target), [])
        self.assertFalse(self.target.exists())

    def test_first_existing_legacy_name_wins(self):
        """按 legacy_names 顺序取第一个存在的目录，只迁一次。"""
        (self.base / "OldName").mkdir()
        (self.base / "OldName" / "a.json").write_text("{}", encoding="utf-8")
        self.make_legacy()

        done = paths.migrate_legacy_user_data(
            self.base, self.target, ("OldName", "MyTools")
        )
        self.assertEqual(done, ["OldName/ → WutheringWavesTools/"])
        self.assertTrue((self.target / "a.json").is_file())
        self.assertFalse((self.target / "loadouts.json").exists(), "只该迁第一个命中的")

    def test_legacy_names_include_former_name(self):
        """改名前用的名字必须在名单里，否则老用户的配置永远读不回来。"""
        self.assertIn("MyTools", paths.LEGACY_APP_NAMES)


class TestMigrationRunsBeforeSeeding(_TempCase):
    """继承必须早于种子播种 —— 顺序反了，种子会铺一套默认值挡在旧配置前面。"""

    def setUp(self):
        super().setUp()
        self.seed = self.base / "seed"
        self.seed.mkdir()
        (self.seed / "wuwa_echo_sets.json").write_text('{"sets": []}', encoding="utf-8")
        # 种子里**也**有一份 loadouts.json，用来验"迁移来的那份没被覆盖"
        (self.base / "data_seed").mkdir()
        (self.base / "data_seed" / "loadouts.json").write_text(
            '{"default": true}', encoding="utf-8"
        )

        self.patch("is_frozen", lambda: True)
        self.patch("_local_appdata", lambda: self.base)
        self.patch("user_data_dir", lambda: self.target)
        self.patch("game_data_dir", lambda: self.target / "game_data")

        def fake_resource_dir(*parts: str) -> Path:
            if parts == ("src", "core", "data"):
                return self.seed
            if parts == ("data",):
                return self.base / "data_seed"
            return self.base / "no_such_dir"

        self.patch("resource_dir", fake_resource_dir)

    def test_migrated_config_survives_and_seeds_fill_the_rest(self):
        self.make_legacy()
        copied = paths.ensure_user_data()

        target = self.target
        self.assertEqual(
            json.loads((target / "loadouts.json").read_text(encoding="utf-8")),
            {"mine": True},
            "迁移来的配置被种子覆盖了 —— 说明迁移没跑在播种前面",
        )
        self.assertTrue((target / "game_data" / "wuwa_characters.json").is_file(),
                        "迁移来的图鉴应该在")
        self.assertTrue((target / "game_data" / "wuwa_echo_sets.json").is_file(),
                        "种子里新增的文件应该补齐")
        self.assertEqual(copied, ["game_data/wuwa_echo_sets.json"],
                         f"只该补种子新增的那个，实际 {copied}")

    def test_first_run_without_legacy_still_seeds(self):
        """全新用户（没有老目录）走原路径：该播的种一个不少。"""
        copied = paths.ensure_user_data()
        # 顶层文件的报告串带用户数据目录名（paths.ensure_user_data 的既有写法），
        # 子目录里的带子目录名 —— 这里照实断言，别把它当"应该长什么样"。
        self.assertEqual(
            sorted(copied),
            ["WutheringWavesTools/loadouts.json", "game_data/wuwa_echo_sets.json"],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
