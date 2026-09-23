"""首启动：种子数据播种 + 游戏数据就地重载。

这两个是「装到别的电脑上资源库是空的」那条 bug 的两半：

* ``main.py`` 必须**先**把种子数据拷到用户数据目录，**再**导入任何 ``src.*`` 子模块；
* ``game_data`` 必须能被**就地重载** —— 别的模块是 ``from ... import CHARACTERS``
  把名字拿走的，重新赋值模块属性它们看不到（所以内部用可变容器 + ``[:] =``）。
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

from src.core import game_data, paths  # noqa: E402


class TestSeedUserData(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)
        self.seed = base / "seed_game_data"
        self.seed.mkdir()
        (self.seed / "wuwa_characters.json").write_text('{"characters": []}', encoding="utf-8")
        (self.seed / "wuwa_echo_sets.json").write_text('{"sets": []}', encoding="utf-8")
        self.target = base / "userdata"

        # 把三个路径函数指到临时目录（绝不碰用户真正的配置）
        for name, value in (
            ("resource_dir", lambda *parts: self.seed if parts == ("src", "core", "data")
             else base / "no_such_dir"),
            ("game_data_dir", lambda: self.target / "game_data"),
            ("user_data_dir", lambda: self.target),
        ):
            original = getattr(paths, name)
            setattr(paths, name, value)
            self.addCleanup(setattr, paths, name, original)

    def test_first_run_copies_seeds(self):
        copied = paths.ensure_user_data()
        self.assertEqual(len(copied), 2, f"应该拷 2 个文件，实际 {copied}")
        self.assertTrue((self.target / "game_data" / "wuwa_characters.json").exists())
        self.assertTrue((self.target / "game_data" / "wuwa_echo_sets.json").exists())

    def test_second_run_copies_nothing(self):
        paths.ensure_user_data()
        self.assertEqual(paths.ensure_user_data(), [])

    def test_existing_file_is_never_overwritten(self):
        paths.ensure_user_data()
        mine = self.target / "game_data" / "wuwa_echo_sets.json"
        mine.write_text('{"mine": true}', encoding="utf-8")
        paths.ensure_user_data()
        self.assertEqual(json.loads(mine.read_text(encoding="utf-8")), {"mine": True},
                         "用户改过的数据不该被种子覆盖")

    def test_missing_seed_dir_is_not_an_error(self):
        """种子目录不存在（比如开发态的另一种布局）时不能抛异常。"""
        original = paths.resource_dir
        paths.resource_dir = lambda *parts: Path(self._tmp.name) / "不存在"
        self.addCleanup(setattr, paths, "resource_dir", original)
        self.assertEqual(paths.ensure_user_data(), [])


class TestReloadDataInPlace(unittest.TestCase):
    """``reload_data()`` 必须让 ``from ... import`` 抄走的名字也看到新数据。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / "wuwa_characters.json").write_text(
            json.dumps({"characters": [{"name": "测试角色", "rarity": 5, "element": "热熔"}]},
                       ensure_ascii=False),
            encoding="utf-8",
        )
        (self.root / "wuwa_echo_sets.json").write_text(
            json.dumps({"sets": [{"name": "测试套装", "effects": [{"pieces": 2, "text": "攻击+10%"}]}]},
                       ensure_ascii=False),
            encoding="utf-8",
        )
        (self.root / "wuwa_set_versions.json").write_text(
            json.dumps({"versions": {"测试套装": "9.9"}}, ensure_ascii=False), encoding="utf-8"
        )
        (self.root / "wuwa_echo_skills.json").write_text('{"echoes": {}}', encoding="utf-8")

        self._original_root = game_data.DATA_ROOT

        def restore():
            game_data.DATA_ROOT = self._original_root
            game_data.reload_data()          # 把真实数据装回来

        self.addCleanup(restore)
        game_data.DATA_ROOT = self.root

    def test_reload_refreshes_imported_names(self):
        # 模拟别的模块：把名字抄走（library_interface.py 就是这么写的）
        imported_characters = game_data.CHARACTERS
        imported_sets = game_data.ECHO_SETS

        before = game_data.DATA_VERSION
        game_data.reload_data()

        self.assertEqual([c.name for c in imported_characters], ["测试角色"],
                         "抄走名字的模块必须也能看到重载后的数据（否则界面还是旧的）")
        self.assertEqual([s.name for s in imported_sets], ["测试套装"])
        self.assertEqual(imported_sets[0].version, "9.9")
        self.assertEqual(game_data.DATA_VERSION, before + 1, "版本号要 +1 让界面知道该重建")
        self.assertIs(imported_characters, game_data.CHARACTERS, "必须是同一个容器对象")

    def test_echoes_by_cost_and_meta_refresh(self):
        echoes = game_data.ECHOES_BY_COST
        meta = game_data.DATA_META
        game_data.reload_data()
        self.assertIs(echoes, game_data.ECHOES_BY_COST)
        self.assertIs(meta, game_data.DATA_META)
        self.assertEqual(sum(len(v) for v in echoes.values()), 0)
        self.assertEqual(meta.get("fetched"), "")

    def test_ensure_loaded_noop_when_data_present(self):
        game_data.reload_data()
        self.assertTrue(game_data.is_loaded())
        version = game_data.DATA_VERSION
        self.assertFalse(game_data.ensure_loaded(), "已经有数据就不该再读盘")
        self.assertEqual(game_data.DATA_VERSION, version)

    def test_ensure_loaded_reads_when_empty(self):
        """模拟"导入时数据还没播种"：内存空 → ensure_loaded 救回来。"""
        game_data.CHARACTERS.clear()
        game_data.ECHO_SETS.clear()
        self.assertFalse(game_data.is_loaded())
        self.assertTrue(game_data.ensure_loaded())
        self.assertEqual([c.name for c in game_data.CHARACTERS], ["测试角色"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
