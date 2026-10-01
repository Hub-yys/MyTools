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

    def test_kurobbs_is_used_for_every_kind(self):
        """★ 接线检查：``kurobbs_icons()`` 要**对所有类别**生效。

        ⚠ 这里曾经是个 bug：取用条件写成了
        ``kurobbs_icons() if kind in ("echoes", "sets") else {}`` ——
        **只给两个分支接上**，于是武器图标永远只走 bwiki、缺的一直是占位图。

        2026-10-01 用户要求"只从库街区拿"之后，条件已经**整个去掉**了
        （无条件取用），比"列全类别"更强 —— 所以这条断言也升级成：
        **不该再有 if 条件卡着它**。
        """
        lines = [ln.strip() for ln in self.source.splitlines()
                 if "kurobbs_icons()" in ln and "def " not in ln]
        self.assertTrue(lines, "没找到 kurobbs_icons() 的取用处，脚本结构变了？")
        for line in lines:
            with self.subTest(line=line):
                self.assertNotIn(
                    "if kind", line,
                    f"还在按类别挑着用库街区（会漏掉某一类）：{line}")

    def test_wiki_only_queried_when_needed(self):
        """★ 库街区全覆盖时**不该再去查 wiki 列表**。

        那是一次分页请求，查了也用不上（纯浪费、还慢）。
        """
        self.assertIn("need_wiki", self.source,
                      "没有'按需查 wiki'的判断，会每次白查一遍")

    def test_kinds_table_has_sets(self):
        """KINDS 表里要有 sets 这一类（否则整个下载流程不会处理套装图标）。"""
        self.assertIn('"sets"', self.source)
        self.assertIn('"avatars"', self.source)
        self.assertIn('"echoes"', self.source)

    def test_kinds_table_has_weapons(self):
        """★ 2026-09-30 新增武器：抽卡卡片墙要显示武器图。"""
        self.assertIn('"weapons"', self.source)
        self.assertIn("_weapon_items", self.source)

    def test_script_still_parses(self):
        ast.parse(self.source)


class TestKurobbsCatalogueIds(unittest.TestCase):
    """库街区 catalogueId 映射（抽卡卡片墙的素材来源）。"""

    def test_mapping_covers_all_four(self):
        """1105 角色 / 1106 武器 / 1107 声骸 / 1219 套装 —— 四个都要在。"""
        from tools import fetch_wuwa_assets as fwa

        for cid, label in (("1105", "角色"), ("1106", "武器"),
                           ("1107", "声骸"), ("1219", "套装")):
            with self.subTest(cid=cid):
                self.assertEqual(fwa.KUROBBS_CATALOGUES.get(cid), label)

    def test_weapon_items_use_weapon_catalogue(self):
        """★ 武器清单要问 catalogue 1106，**不能**从 icon_urls 里猜。

        icon_urls 是混在一起的（角色/武器/声骸都有），分不出哪个是武器 ——
        我第一版就是那么写的，会把声骸名也当成武器去查。
        """
        import inspect

        from tools import fetch_wuwa_assets as fwa

        source = inspect.getsource(fwa._weapon_items)
        self.assertIn("1106", source, "武器清单没走武器 catalogue")


class TestIconUrlsCoverage(unittest.TestCase):
    """``icon_urls`` 要覆盖抽卡卡片墙需要的三类素材。"""

    def _urls(self) -> dict:
        import json

        path = ROOT / "src" / "core" / "data" / "wuwa_echo_skills.json"
        return json.loads(path.read_text(encoding="utf-8")).get("icon_urls") or {}

    def test_has_characters(self):
        """角色头像 URL（卡片墙要显示角色图）。"""
        urls = self._urls()
        chars = [n for n in ("清宵", "维里奈", "安可", "凌阳") if n in urls]
        self.assertGreaterEqual(len(chars), 3,
                                f"角色图标没进 icon_urls：{chars}")

    def test_has_weapons(self):
        """★ 武器图 URL（用户要求"这些换成图片"）。"""
        urls = self._urls()
        weapons = [n for n in ("千古洑流", "云琅") if n in urls]
        self.assertGreaterEqual(len(weapons), 1,
                                f"武器图标没进 icon_urls：{weapons}")

    def test_has_sets(self):
        """套装图标（之前修过的 bug，别退回去）。"""
        urls = self._urls()
        for name in ("衔梦照世之心", "镜影流电之瞬", "茜染怀想之花"):
            with self.subTest(name=name):
                self.assertIn(name, urls)


class TestEchoIconUrlsCoverage(unittest.TestCase):
    """★ 每个声骸在 ``icon_urls`` 里都要有 URL —— 否则图鉴/配置页那一列是空的。

    用户 2026-09-30 报："这里的图像为什么还是没加上？"（配置页选声骸那一列）
    根因：3.7 新增的 3 套套装带来了 6 个新声骸，我给**套装**下了图标，
    却**没给这些新声骸下** —— 那 6 行的声骸图标是空的。

    这条钉住"数据里的每个声骸都有图源"，别再漏。
    """

    def test_every_echo_has_a_url(self):
        import json

        from src.core import game_data

        game_data.ensure_loaded()
        path = ROOT / "src" / "core" / "data" / "wuwa_echo_skills.json"
        urls = json.loads(path.read_text(encoding="utf-8")).get("icon_urls") or {}

        missing = [
            echo.name
            for items in game_data.ECHOES_BY_COST.values()
            for echo in items
            if echo.name not in urls
        ]
        self.assertEqual(
            missing, [],
            f"{len(missing)} 个声骸没有图标 URL（配置页/图鉴会显示空白）：{missing[:8]}")


class TestIconFilesPresent(unittest.TestCase):
    """★ 图标**文件**是否已下载到本地（``assets/game/``）。

    ⚠ 这条只在**本机下过素材**时才有意义 —— ``assets/game/`` 是游戏素材、
    不入库（`.gitignore`），克隆仓库后本来就缺。所以拿一个"肯定有"的文件
    当探针：**只要角色头像下过**，就说明这台机器跑过 fetch_wuwa_assets，
    那声骸图标也该齐。

    这正是那个 bug 能被发现的地方：套装图标下过了（说明跑过脚本），
    但新声骸的图没下 —— 靠"逐条比对数据 vs 磁盘"才看得出来。
    """

    def _assets_root(self):
        return ROOT / "assets" / "game"

    def test_no_echo_icon_files_missing(self):
        from src.core import game_data

        game_data.ensure_loaded()
        root = self._assets_root()

        avatars = root / "avatars"
        if not avatars.is_dir() or not any(avatars.glob("*.png")):
            self.skipTest("本机没下过素材（assets/game 不入库，属正常）")

        missing = [
            echo.name
            for items in game_data.ECHOES_BY_COST.values()
            for echo in items
            if not (root / echo.icon).exists()
        ]
        self.assertEqual(
            missing, [],
            f"{len(missing)} 个声骸图标文件缺失（跑 "
            f"`python tools/fetch_wuwa_assets.py --only echoes` 补）："
            f"{missing[:8]}")

    def test_no_weapon_icon_files_missing(self):
        from src.core import game_data

        game_data.ensure_loaded()
        root = self._assets_root()
        if not (root / "weapons").is_dir():
            self.skipTest("本机没下过武器图")
        missing = [w.name for w in game_data.WEAPONS
                   if not (root / w.icon).exists()]
        self.assertEqual(missing, [],
                         f"{len(missing)} 个武器图标缺失：{missing[:8]}")


class TestAutoDownloadOnUpdate(unittest.TestCase):
    """★ 「资源库更新」要**自己把缺的图补上**，不能只写 URL。

    用户 2026-09-30 报："资源库已经更新了，这图片为什么没自动补上？"

    根因：更新流程**只写图标 URL、从不下载图片** —— 下载一直是
    ``tools/fetch_wuwa_assets.py`` 那个手动脚本干的。于是"数据更新了、
    图还是空的"。现在 ``apply_updates`` 里加了 ``_download_missing_icons()``。
    """

    def test_update_calls_download_step(self):
        """★ 接线检查：``apply_updates`` 必须调用补图那一步。"""
        import inspect

        from src.core import wuwa_update

        source = inspect.getsource(wuwa_update.apply_updates)
        self.assertIn("_download_missing_icons", source,
                      "更新流程没补图 —— 又会'数据更新了图还是空的'")

    def test_download_step_runs_after_reload(self):
        """★ 补图必须在 ``reload_data()`` **之后**。

        要先拿到**新的**声骸/套装/武器名单才知道缺哪些图；
        顺序反了就是拿旧名单算，新图照样补不上。
        """
        import inspect

        from src.core import wuwa_update

        source = inspect.getsource(wuwa_update.apply_updates)
        reload_at = source.find("reload_data()")
        download_at = source.find("_download_missing_icons")
        self.assertGreater(reload_at, -1, "没找到 reload_data()")
        self.assertGreater(download_at, -1, "没找到补图那步")
        self.assertLess(reload_at, download_at,
                        "补图在 reload_data() 之前 —— 会拿旧名单算")

    def test_icon_urls_exposed_for_downloader(self):
        """``game_data.ICON_URLS`` 要能被补图逻辑读到（角色/武器/声骸都要有）。"""
        from src.core import game_data

        game_data.ensure_loaded()
        self.assertTrue(game_data.ICON_URLS, "ICON_URLS 是空的")
        for name in ("解形煞", "云琅"):
            with self.subTest(name=name):
                self.assertIn(name, game_data.ICON_URLS)

    def test_missing_files_are_downloaded(self):
        """★ 端到端：删掉一张图 → 补图那步要把它下回来（内容一致）。

        ⚠ 这条会**真的下载**（约一秒）。没有网/没素材时 skip。
        """
        import hashlib

        from src.core import assets, game_data, wuwa_update

        game_data.ensure_loaded()
        root = assets.assets_root()
        if not (root / "avatars").is_dir():
            self.skipTest("本机没下过素材")

        # 挑一张有 URL 的声骸图，备份后删掉
        victim = None
        for items in game_data.ECHOES_BY_COST.values():
            for echo in items:
                if game_data.ICON_URLS.get(echo.name) and (root / echo.icon).exists():
                    victim = echo
                    break
            if victim:
                break
        if victim is None:
            self.skipTest("找不到可用于测试的声骸图")

        path = root / victim.icon
        original = path.read_bytes()
        digest = hashlib.sha256(original).hexdigest()
        path.unlink()
        try:
            wuwa_update._download_missing_icons(log=lambda _m: None)
            self.assertTrue(path.exists(), f"{victim.name} 没被自动补回来")
            after = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(after, digest, "补回来的图和原来不一致")
        finally:
            if not path.exists():          # 下载失败也要还原，别留个坑
                path.write_bytes(original)

    def test_existing_files_are_not_overwritten(self):
        """★ 已有的图**绝不能覆盖** —— 用户可能自己换过图。

        README 里就写着"换成自己的图：直接覆盖同名文件"，
        自动补图要是覆盖回去，等于把用户的替换毁了。

        ⚠ 要测的是 :func:`~src.core.assets.ensure_assets` **本身**的保护，
        不能走 ``_download_missing_icons`` —— 那个函数在"什么都不缺"时
        会**提前返回**，测的就不是保护逻辑了（我第一版就这么写的，
        结果把保护删掉测试居然还通过）。
        所以这里**直接喂一个文件已存在**的清单给 ensure_assets。
        """
        from src.core import assets, game_data

        game_data.ensure_loaded()
        root = assets.assets_root()
        if not (root / "avatars").is_dir():
            self.skipTest("本机没下过素材")

        # 挑一张有 URL 的声骸图，写成"用户自己换的"假图
        victim = None
        for items in game_data.ECHOES_BY_COST.values():
            for echo in items:
                if game_data.ICON_URLS.get(echo.name):
                    victim = echo
                    break
            if victim:
                break
        if victim is None:
            self.skipTest("找不到有 URL 的声骸")

        path = root / victim.icon
        original = path.read_bytes() if path.exists() else None
        marker = b"\x89PNG\r\n\x1a\n" + b"USER_REPLACED_THIS" * 4
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(marker)
        try:
            # 直接把"这张已有"的清单喂进去 —— 必须跳过
            done, _failed = assets.ensure_assets(
                {victim.icon: game_data.ICON_URLS[victim.name]},
                log=lambda _m: None)
            self.assertEqual(done, 0, "已经存在的图不该被下载")
            self.assertEqual(path.read_bytes(), marker,
                             "已有的图被覆盖了！用户的替换被毁")
        finally:
            if original is not None:
                path.write_bytes(original)      # 还原真图
            else:
                path.unlink(missing_ok=True)


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
