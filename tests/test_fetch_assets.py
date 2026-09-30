"""素材下载脚本（tools/fetch_wuwa_assets.py）的接线检查。

    python tests/test_fetch_assets.py

不打网络 —— 只检查**取数来源接对了**。

2026-09-30 用户报："这里明明已经有了套装图标，为什么不加上去？"
根因之一就在这个脚本：库街区兜底表只对 ``echoes`` 生效::

    kuro = kurobbs_icons() if kind == "echoes" else {}   # ← 套装被漏掉了

于是套装图标永远只走 bwiki，bwiki 没收录的那几套就一直是占位图。

这组用例把"三类都要走库街区兜底"钉住 —— 这类"只给一个分支接上"的
漏接很难在界面上看出来（图标就是缺着，不报错）。
"""

from __future__ import annotations

import ast
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SCRIPT = ROOT / "tools" / "fetch_wuwa_assets.py"


class TestKurobbsFallback(unittest.TestCase):
    """库街区兜底表要对**声骸和套装**都生效。"""

    @classmethod
    def setUpClass(cls):
        cls.source = SCRIPT.read_text(encoding="utf-8")

    def test_source_mentions_both_kinds(self):
        """★ 接线检查：``kurobbs_icons()`` 的取用条件里必须同时含
        ``echoes`` 和 ``sets``。

        直接查源码字符串 —— 因为这是"接线"问题，不是函数行为问题：
        函数本身没错，是**调用处的条件写窄了**。
        """
        line = next(
            (ln for ln in self.source.splitlines()
             if "kurobbs_icons()" in ln and "if " in ln),
            "",
        )
        self.assertTrue(line, "没找到 kurobbs_icons() 的取用条件，脚本结构变了？")
        self.assertIn("echoes", line, f"声骸没接库街区兜底：{line.strip()}")
        self.assertIn("sets", line, f"★ 套装没接库街区兜底：{line.strip()}")

    def test_kinds_table_has_sets(self):
        """KINDS 表里要有 sets 这一类（否则整个下载流程不会处理套装图标）。"""
        self.assertIn('"sets"', self.source)
        self.assertIn('"avatars"', self.source)
        self.assertIn('"echoes"', self.source)

    def test_script_still_parses(self):
        ast.parse(self.source)


class TestIconUrlSource(unittest.TestCase):
    """``icon_urls`` 里必须**同时**有套装和声骸的图标。"""

    def test_icon_urls_contain_set_icons(self):
        """★ 数据集里的套装名要能在 ``icon_urls`` 里查到。

        查不到就意味着"这套的图标只能靠占位图"。
        这里只要求**至少能查到几套**（不要求全覆盖 —— bwiki 那份可能补不上），
        因为断言"全覆盖"会让上游一缺数据就误报。
        """
        import json

        from src.core import game_data

        game_data.ensure_loaded()
        path = ROOT / "src" / "core" / "data" / "wuwa_echo_skills.json"
        urls = json.loads(path.read_text(encoding="utf-8")).get("icon_urls") or {}
        self.assertTrue(urls, "icon_urls 是空的")

        names = [s.name for s in game_data.ECHO_SETS]
        hits = [n for n in names if n in urls]
        self.assertGreaterEqual(
            len(hits), 3,
            f"{len(names)} 套里只有 {len(hits)} 套能在 icon_urls 里查到图标 —— "
            "套装图标没进这张表（是不是只取了 catalogue 1107？）",
        )

    def test_new_sets_have_icons_recorded(self):
        """3.7 的 3 套要有图标 URL（它们是靠 1219 那条路补上的）。"""
        import json

        path = ROOT / "src" / "core" / "data" / "wuwa_echo_skills.json"
        urls = json.loads(path.read_text(encoding="utf-8")).get("icon_urls") or {}
        for name in ("衔梦照世之心", "镜影流电之瞬", "茜染怀想之花"):
            with self.subTest(name=name):
                self.assertIn(name, urls, f"{name} 没有图标 URL")


if __name__ == "__main__":
    unittest.main(verbosity=2)
