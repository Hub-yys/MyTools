# -*- coding: utf-8 -*-
"""自动更新的测试。

## ⚠ 全程**不碰真网络**

所有网络调用都被换成假的（``_get_json`` / ``urlopen``）——
测试要能在**断网机器**上跑，也不能因为 GitHub 抽风就红。

只有 :class:`TestVersions` 是纯函数，其余都 monkeypatch。
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

#: ★★★ 测试里**关掉自动检查更新**。
#:
#: ⚠⚠ 不关的话，每个 ``MainWindow()`` 都会在 3 秒后起一个**真网络线程**；
#: 测试跑完一堆窗口正在被回收，后台线程却还在 ``setThemeColor()`` ——
#: ``qfluentwidgets`` 遍历弱引用字典时撞上 GC，抛::
#:
#:     RuntimeError: dictionary changed size during iteration
#:
#: 而且是**时红时不红**、极难查（实测卡了很久）。
#: 需要验自动检查的那两条测试会自己临时清掉这个变量。
os.environ["MYTOOLS_NO_AUTO_UPDATE"] = "1"


class TestVersions(unittest.TestCase):
    """★★★ 版本比较 —— **不能按字符串比**。

    ``"0.10.0" < "0.9.0"`` 在字符串上是 True，但版本上 **0.10 更新**。
    按字符串比的话，``0.10.0`` 发布时用户**永远收不到更新**。
    """

    def test_parse_version(self):
        from src.core import updater as U

        self.assertEqual(U.parse_version("0.5.3"), (0, 5, 3))
        self.assertEqual(U.parse_version("v0.5.3"), (0, 5, 3))
        self.assertEqual(U.parse_version("  v1.2.3-beta "), (1, 2, 3))
        self.assertEqual(U.parse_version("1"), (1,))
        self.assertEqual(U.parse_version(""), ())
        self.assertEqual(U.parse_version("abc"), ())
        self.assertEqual(U.parse_version(None), ())

    def test_newer_basic(self):
        from src.core import updater as U

        self.assertTrue(U.is_newer("0.6.0", "0.5.3"))
        self.assertFalse(U.is_newer("0.5.3", "0.5.3"))
        self.assertFalse(U.is_newer("0.5.2", "0.5.3"))

    def test_newer_double_digit(self):
        """★★★ ``0.10.0`` 要比 ``0.9.0`` 新（字符串比会判错）。"""
        from src.core import updater as U

        self.assertTrue(U.is_newer("0.10.0", "0.9.0"),
                        "0.10.0 被判成不比 0.9.0 新 —— 用字符串比了")
        self.assertTrue(U.is_newer("0.9.0", "0.8.9"))
        self.assertTrue(U.is_newer("1.0.0", "0.99.99"))
        self.assertTrue(U.is_newer("0.100.0", "0.99.0"))

    def test_string_compare_would_be_wrong(self):
        """★ 把"字符串比的坑"直接钉住（证明上面那条不是巧合）。"""
        self.assertTrue("0.10.0" < "0.9.0",
                        "Python 字符串比较的行为变了？那这条测试要重写")

    def test_newer_pads_short_versions(self):
        """★ 段数不一样也能比（短的**补 0**）。

        ⚠ ``0.6`` 和 ``0.6.0`` 是**同一个版本** —— 不算更新
        （我第一版把这条写反了，测试当场指出来）。
        """
        from src.core import updater as U

        self.assertFalse(U.is_newer("0.6", "0.6.0"))
        self.assertFalse(U.is_newer("0.6.0", "0.6"),
                         "0.6.0 和 0.6 是同一个版本")
        self.assertTrue(U.is_newer("0.6.1", "0.6"))
        self.assertTrue(U.is_newer("0.6.0", "0.5"))

    def test_unparsable_is_never_newer(self):
        """★ 解析不了 → **不当有更新**（宁可漏报，不可误报）。"""
        from src.core import updater as U

        for bad_latest in ("", "abc", None, "v"):
            with self.subTest(latest=bad_latest):
                self.assertFalse(U.is_newer(bad_latest, "0.5.3"))
        for bad_cur in ("", "abc", None):
            with self.subTest(current=bad_cur):
                self.assertFalse(U.is_newer("0.6.0", bad_cur))


class TestPickAsset(unittest.TestCase):
    """★★ 从 release 的 assets 里挑出**安装包**。"""

    def test_prefers_setup_exe(self):
        """★★ 优先挑 ``*Setup*.exe``（Inno 安装包）。

        ⚠ ``other.exe`` 故意排在**前面** —— 否则"优先"这个行为
        测不出来（它本来就是第一个）。
        """
        from src.core import updater as U

        assets = [
            {"name": "source.zip", "browser_download_url": "http://x/s.zip",
             "size": 10},
            #: ★ 普通 exe 排前面
            {"name": "other.exe", "browser_download_url": "http://x/o.exe",
             "size": 5},
            #: ★ 安装包排后面 —— 应该还是挑它
            {"name": "MyToolsSetup-0.6.0.exe",
             "browser_download_url": "http://x/setup.exe", "size": 999},
        ]
        url, size = U.pick_asset(assets)
        self.assertEqual(url, "http://x/setup.exe",
                         "没优先挑 Setup 那个 exe（挑到了排前面的普通 exe）")
        self.assertEqual(size, 999)

    def test_setup_match_is_case_insensitive(self):
        """★ ``SETUP`` / ``Setup`` 都该认出来。"""
        from src.core import updater as U

        for name in ("AppSETUP-1.0.exe", "AppSetup-1.0.exe",
                     "app_setup_1.0.EXE"):
            with self.subTest(name=name):
                url, _ = U.pick_asset([
                    {"name": "plain.exe",
                     "browser_download_url": "http://x/p.exe", "size": 1},
                    {"name": name,
                     "browser_download_url": "http://x/s.exe", "size": 2},
                ])
                self.assertEqual(url, "http://x/s.exe")

    def test_falls_back_to_any_exe(self):
        from src.core import updater as U

        url, size = U.pick_asset(
            [{"name": "a.exe", "browser_download_url": "http://x/a.exe",
              "size": 7}])
        self.assertEqual(url, "http://x/a.exe")
        self.assertEqual(size, 7)

    def test_ignores_non_exe(self):
        from src.core import updater as U

        url, size = U.pick_asset(
            [{"name": "a.zip", "browser_download_url": "http://x/a.zip",
              "size": 7}])
        self.assertEqual((url, size), ("", 0))

    def test_empty_and_garbage(self):
        from src.core import updater as U

        for bad in ([], None, [None], [{}], [{"name": None}]):
            with self.subTest(assets=bad):
                self.assertEqual(U.pick_asset(bad), ("", 0))

    def test_size_garbage_does_not_crash(self):
        from src.core import updater as U

        url, size = U.pick_asset(
            [{"name": "a.exe", "browser_download_url": "http://x/a.exe",
              "size": "不是数字"}])
        self.assertEqual(url, "http://x/a.exe")
        self.assertEqual(size, 0)


class TestCheckForUpdate(unittest.TestCase):
    """★★★ 检查更新 —— 全部用假网络。"""

    def setUp(self):
        from src.core import updater as U

        self.U = U
        self._orig = U._get_json

    def tearDown(self):
        self.U._get_json = self._orig

    def _fake(self, payload):
        self.U._get_json = lambda url, timeout=None: payload

    def test_has_update(self):
        self._fake({
            "tag_name": "v0.6.0",
            "body": "修了 A、加了 B",
            "assets": [{"name": "WutheringWavesToolsSetup-0.6.0.exe",
                        "browser_download_url": "http://x/s.exe",
                        "size": 1234}],
        })
        info = self.U.check_for_update("0.5.3")
        self.assertTrue(info.ok)
        self.assertTrue(info.has_update)
        self.assertEqual(info.latest, "v0.6.0")
        self.assertEqual(info.url, "http://x/s.exe")
        self.assertEqual(info.size, 1234)
        self.assertIn("修了 A", info.notes)

    def test_no_update(self):
        self._fake({"tag_name": "v0.5.3", "assets": []})
        info = self.U.check_for_update("0.5.3")
        self.assertTrue(info.ok)
        self.assertFalse(info.has_update)

    def test_older_remote_is_not_update(self):
        """★ 远端比本地**旧** → 不算更新（用户装的是新版）。"""
        self._fake({"tag_name": "v0.5.0", "assets": []})
        info = self.U.check_for_update("0.5.3")
        self.assertTrue(info.ok)
        self.assertFalse(info.has_update)

    def test_404_means_no_release_not_error(self):
        """★★ 仓库**还没有任何 release** → 不算错误（很常见）。

        ⚠ 这条很重要：新仓库刚建时 GitHub 就是回 404，
        不该让界面显示"检查失败"吓用户。
        """
        import urllib.error

        def _boom(url, timeout=None):
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

        self.U._get_json = _boom
        info = self.U.check_for_update("0.5.3")
        self.assertTrue(info.ok, "404 被当成错误了")
        self.assertFalse(info.has_update)
        self.assertEqual(info.error, "")

    def test_http_error_is_reported(self):
        import urllib.error

        def _boom(url, timeout=None):
            raise urllib.error.HTTPError(url, 403, "rate limited", {}, None)

        self.U._get_json = _boom
        info = self.U.check_for_update("0.5.3")
        self.assertFalse(info.ok)
        self.assertIn("403", info.error)
        self.assertFalse(info.has_update)

    def test_network_error_does_not_raise(self):
        """★★★ 断网 / GitHub 抽风 **不能抛异常**（界面会炸）。"""
        import urllib.error

        def _boom(url, timeout=None):
            raise urllib.error.URLError("getaddrinfo failed")

        self.U._get_json = _boom
        info = self.U.check_for_update("0.5.3")
        self.assertFalse(info.ok)
        self.assertFalse(info.has_update)
        self.assertTrue(info.error)

    def test_any_exception_does_not_raise(self):
        """★ 兜底：连"想不到的异常"也不能抛出去。"""
        def _boom(url, timeout=None):
            raise ValueError("谁知道会出什么")

        self.U._get_json = _boom
        info = self.U.check_for_update("0.5.3")
        self.assertFalse(info.ok)
        self.assertFalse(info.has_update)

    def test_current_version_comes_from_app_config(self):
        """★★ 当前版本从 ``app_config`` 拿（**唯一真源**）。

        ⚠ 项目之前出过"安装包 0.3.0 / 界面 0.1.0 对不上"的事 ——
        版本号只许有一处定义。
        """
        from src.app_config import APP_VERSION

        from src.core import updater as U

        self.assertEqual(U._current_version(), str(APP_VERSION))


class TestDownloadName(unittest.TestCase):
    def test_download_name(self):
        from src.core.updater import ReleaseInfo

        self.assertEqual(
            ReleaseInfo(url="http://x/a/Setup-0.6.0.exe").download_name,
            "Setup-0.6.0.exe")
        #: 带 query 的也要能取对
        self.assertEqual(
            ReleaseInfo(url="http://x/a/Setup.exe?token=abc").download_name,
            "Setup.exe")
        self.assertEqual(ReleaseInfo().download_name, "")


class TestDownload(unittest.TestCase):
    """★ 下载（用假的 HTTP 响应）。"""

    def setUp(self):
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        from src.core import updater as U

        self.U = U
        self._orig = U.urllib.request.urlopen

    def tearDown(self):
        self.U.urllib.request.urlopen = self._orig
        self._tmp.cleanup()

    def _fake_response(self, chunks, total=None):
        class _Resp:
            def __init__(self):
                self._chunks = list(chunks)
                self.headers = {}
                if total is not None:
                    self.headers["Content-Length"] = str(total)

            def read(self, _n=None):
                return self._chunks.pop(0) if self._chunks else b""

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        return _Resp()

    def test_download_writes_file(self):
        data = b"x" * 1000
        self.U.urllib.request.urlopen = (
            lambda req, timeout=None, context=None:
            self._fake_response([data], total=len(data)))

        seen: list[tuple[int, int]] = []
        path = self.U.download("http://x/Setup.exe",
                               dest_dir=self._tmp.name,
                               on_progress=lambda d, t: seen.append((d, t)))
        self.assertTrue(path.exists())
        self.assertEqual(path.read_bytes(), data)
        self.assertEqual(path.name, "Setup.exe")
        self.assertTrue(seen, "进度回调没被调用")
        self.assertEqual(seen[-1], (len(data), len(data)))

    def test_download_no_url_raises(self):
        with self.assertRaises(RuntimeError):
            self.U.download("")

    def test_download_failure_raises_runtime_error(self):
        """★ 下载失败抛 ``RuntimeError``（界面好接）。"""
        def _boom(req, timeout=None, context=None):
            raise OSError("连接被重置")

        self.U.urllib.request.urlopen = _boom
        with self.assertRaises(RuntimeError) as ctx:
            self.U.download("http://x/Setup.exe", dest_dir=self._tmp.name)
        self.assertIn("下载失败", str(ctx.exception))

    def test_progress_callback_error_does_not_break_download(self):
        """★ 进度回调抛异常**不该**弄挂下载本身。"""
        data = b"y" * 500
        self.U.urllib.request.urlopen = (
            lambda req, timeout=None, context=None:
            self._fake_response([data], total=len(data)))

        def _bad_progress(_d, _t):
            raise ValueError("界面回调炸了")

        path = self.U.download("http://x/Setup.exe",
                               dest_dir=self._tmp.name,
                               on_progress=_bad_progress)
        self.assertEqual(path.read_bytes(), data)


class TestUpdateCard(unittest.TestCase):
    """★ 界面卡片（offscreen，不碰网络）。

    ⚠⚠ **判可见性要用 ``isHidden()``，不是 ``isVisible()``**

    父控件没 ``show()`` 时 Qt 的 ``isVisible()`` **恒为 False** ——
    测试里根本判不出来（这是我在皮肤那边踩过一次的同一个坑）。
    ``isHidden()`` 看的是"这个控件自己有没有被显式藏起来"，正合适。

    下面的 ``_shown()`` 就是这个意思。
    """

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    @staticmethod
    def _shown(widget) -> bool:
        """控件自己有没有被显示（不受父控件影响）。"""
        return not widget.isHidden()

    def setUp(self):
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        from src.core import ui_state

        self._orig = ui_state.UiState
        path = Path(self._tmp.name) / "ui.json"

        class _Temp(ui_state.UiState):
            def __init__(self, *_a, **_k):
                super().__init__(path)

        ui_state.UiState = _Temp

    def tearDown(self):
        from src.core import ui_state

        ui_state.UiState = self._orig
        self._tmp.cleanup()

    def test_card_shows_current_version(self):
        from src.app_config import APP_VERSION

        from src.gui.update_card import build_update_card

        card = build_update_card()
        self.assertIn(str(APP_VERSION), card.version_label.text())

    def test_install_button_hidden_until_update_found(self):
        """★★ 没查到更新之前，「下载并安装」**不该**露出来。"""
        from src.gui.update_card import build_update_card

        card = build_update_card()
        self.assertFalse(self._shown(card.install_btn),
                         "还没检查就把安装按钮露出来了")

    def test_no_update_path_shows_latest(self):
        """★ 查到"已是最新" → 状态文字说清楚，且不露安装按钮。"""
        from src.core import updater as U
        from src.gui.update_card import build_update_card

        card = build_update_card()
        card._on_checked(U.ReleaseInfo(ok=True, current="0.5.3",
                                       latest="v0.5.3", has_update=False))
        self.assertIn("最新", card.status.text())
        self.assertFalse(self._shown(card.install_btn))

    def test_update_path_shows_install_button(self):
        """★★ 查到有更新 → 露安装按钮 + 显示更新说明。"""
        from src.core import updater as U
        from src.gui.update_card import build_update_card

        card = build_update_card()
        card._on_checked(U.ReleaseInfo(
            ok=True, current="0.5.3", latest="v0.6.0", has_update=True,
            notes="修了 A", url="http://x/s.exe", size=10 * 1024 * 1024))
        self.assertIn("0.6.0", card.status.text())
        self.assertTrue(self._shown(card.install_btn),
                        "有更新却没露安装按钮")
        self.assertTrue(self._shown(card.notes), "更新说明没显示")
        self.assertIn("修了 A", card.notes.text())

    def test_error_path_shows_message(self):
        """★ 检查失败 → 显示错误，且**不露**安装按钮。"""
        from src.core import updater as U
        from src.gui.update_card import build_update_card

        card = build_update_card()
        card._on_checked(U.ReleaseInfo(ok=False, current="0.5.3",
                                       error="连不上 GitHub"))
        self.assertIn("连不上", card.status.text())
        self.assertFalse(self._shown(card.install_btn))

    def test_auto_check_is_always_on(self):
        """★★★ 自动检查**一直开着** —— 开关已经去掉（用户 2026-10-05）。

            用户（截图圈出那个勾选框）："这个不用显示出来"

        ⚠ 第一版有个勾选框，测试还验"能关掉、能存下来"——
        现在那个框**不在界面上**了，所以：

          * `auto_check_enabled()` **恒为 True**
          * 界面上**不许**再有那个勾选框（否则用户又看见了）
        """
        from PySide6.QtWidgets import QCheckBox

        from src.gui.update_card import build_update_card

        card = build_update_card()
        self.assertTrue(card.auto_check_enabled(), "自动检查该一直开着")

        #: 就算硬调 set_auto_check(False)，也还是开着
        card.set_auto_check(False)
        self.assertTrue(build_update_card().auto_check_enabled(),
                        "还能被关掉 —— 但界面上已经没有开关了，"
                        "用户会找不到地方打开")

        #: 界面上不该再有那个勾选框
        boxes = [c for c in card.findChildren(QCheckBox)
                 if "自动检查" in (c.text() or "")]
        self.assertEqual(boxes, [],
                         "「启动时自动检查」勾选框还在 —— 用户要求去掉")

    def test_config_page_has_no_update_card(self):
        """★★★ 更新卡**不该**再塞在配置页里（用户要求放侧栏）。

        用户 2026-10-05（截图圈出侧栏那一列）::

            "侧边栏的检查更新呢"

        ⚠⚠ 第一版把卡片塞进**配置页** —— 位置不对，已删。
        """
        from src.gui.config_interface import ConfigInterface

        page = ConfigInterface()
        self.assertFalse(
            hasattr(page, "update_card"),
            "配置页里还挂着更新卡 —— 用户要的是侧栏导航项")

    def test_update_page_is_scroll_area(self):
        """★★ 更新页必须是 ``ScrollArea`` + ``setWidget``。

        ⚠ 用裸 ``QWidget`` 会**整页不显示**（100x30、切过去是空白）——
        皮肤页第一版就栽在这。
        """
        from qfluentwidgets import ScrollArea

        from src.gui.update_card import build_update_page

        page = build_update_page()
        self.assertIsInstance(page, ScrollArea,
                              "更新页不是 ScrollArea —— 整页会不显示")
        self.assertIsNotNone(page.widget(),
                             "没 setWidget(view) —— 整页会被压扁")

    def test_main_window_has_update_nav_item(self):
        """★★★ 主窗口侧栏有「检查更新」这一项。"""
        from src.gui.main_window import MainWindow

        w = MainWindow()
        self.assertIsNotNone(getattr(w, "update_interface", None),
                             "主窗口没有检查更新页")

    def test_update_nav_icon_is_registered(self):
        """★ ``UPDATE`` 图标键要在 ``compat._ICON_CANDIDATES`` 里。

        ⚠ ``resolve_icon`` 缺键时会**降级**成默认图标（不报错）——
        所以光看"界面能不能起来"抓不住这个回归，得**直接查那张表**。
        """
        from src.gui import compat

        self.assertIn("UPDATE", compat._ICON_CANDIDATES,
                      "compat 里没注册 UPDATE 图标键")
        icon = compat.resolve_icon("UPDATE")
        self.assertIsNotNone(icon, "UPDATE 图标解析不出来")

    def test_icon_candidates_has_no_duplicate_keys(self):
        """★★★ ``_ICON_CANDIDATES`` 里**不许有重复的键**。

        ⚠⚠ 我 2026-10-05 踩过：以为要"新增" ``UPDATE`` 键，
        其实**早就有了** —— 我加的那条在后面，dict **静默覆盖**了前一条，
        源码里看着有两条、实际只有一条生效。

        Python 的 dict 字面量对重复键**不报错**（后写胜），
        所以只能靠**扫源码**抓。
        """
        import re
        from pathlib import Path

        from src.gui import compat

        text = Path(compat.__file__).read_text(encoding="utf-8")
        #: 抓 `"KEY": (...)` 这种行（只看那张表那一段）
        start = text.index("_ICON_CANDIDATES")
        end = text.index("}", text.index("{", start))
        block = text[start:end]
        keys = re.findall(r'^\s*"([A-Z_]+)"\s*:', block, re.M)
        dupes = {k for k in keys if keys.count(k) > 1}
        self.assertEqual(
            dupes, set(),
            f"_ICON_CANDIDATES 里有重复的键 {sorted(dupes)} —— "
            f"dict 会静默覆盖，源码里看着两条实际只生效一条")

    def test_open_update_page_switches(self):
        """★★ 切到更新页**真的切过去**（页面要变大、可见）。

        ⚠ 必须用 ``switchTo``（``setCurrentItem`` 只高亮侧栏不切页）。
        """
        from src.gui.main_window import MainWindow

        w = MainWindow()
        w.resize(1000, 700)
        w.show()
        for _ in range(4):
            self.app.processEvents()
        w.open_update_page()
        for _ in range(4):
            self.app.processEvents()
        page = w.update_interface
        self.assertTrue(page.isVisible(), "切过去了但页面不可见")
        self.assertGreater(page.width(), 300,
                           f"页面还是 {page.width()} 宽 —— 没真的切过去")


class TestMainWindowAutoCheck(unittest.TestCase):
    """★ 启动时静默检查。"""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        from src.core import ui_state

        self._orig = ui_state.UiState
        path = Path(self._tmp.name) / "ui.json"

        class _Temp(ui_state.UiState):
            def __init__(self, *_a, **_k):
                super().__init__(path)

        ui_state.UiState = _Temp

    def tearDown(self):
        from src.core import ui_state

        ui_state.UiState = self._orig
        self._tmp.cleanup()

    def test_in_test_mode_detection(self):
        """★★★ 测试模式要**自动认出来**（不靠每个测试文件自觉）。

        ## ⚠⚠ 为什么（2026-10-05 实测）

        自动检查更新会在窗口建好后 **3 秒**起一个**真网络线程**。
        我一开始加了个 ``MYTOOLS_NO_AUTO_UPDATE`` 环境变量，
        **但得每个测试文件自己记着设** —— 结果 7 个建 ``MainWindow``
        的测试文件里只有 1 个设了，其余 6 个照样起线程。

        → 改成自动认。这里验三种情况。
        """
        import os
        import sys

        from src.gui import main_window as MW

        #: ① 显式环境变量
        orig = os.environ.get("MYTOOLS_NO_AUTO_UPDATE")
        try:
            os.environ["MYTOOLS_NO_AUTO_UPDATE"] = "1"
            self.assertTrue(MW._in_test_mode(), "环境变量没认出来")
        finally:
            if orig is None:
                os.environ.pop("MYTOOLS_NO_AUTO_UPDATE", None)
            else:
                os.environ["MYTOOLS_NO_AUTO_UPDATE"] = orig

        #: ② 本测试文件本身就在 tests/ 下 —— 应该被认出来
        #:    （`python tests/test_updater.py` 时 argv[0] 就是它）
        self.assertTrue(MW._in_test_mode(),
                        "在 tests/ 下跑却没认出测试模式")

    def test_main_window_has_auto_check_hooks(self):
        from src.gui.main_window import MainWindow

        w = MainWindow()
        for name in ("_maybe_auto_check_update", "_auto_check_update",
                     "_on_auto_checked"):
            with self.subTest(name=name):
                self.assertTrue(hasattr(w, name), f"主窗口少了 {name}")

    def test_auto_check_disabled_skips(self):
        """★★ 自动检查**一直开着**，所以启动时总会去查。

        ⚠ 原来这条测的是"关掉开关就不查" —— 但那个开关
        已经被用户去掉了（"这个不用显示出来"），
        所以现在改测"**没有任何设置能阻止它查**"。

        ⚠⚠ 测试环境下 ``_maybe_auto_check_update()`` 会被
        ``_in_test_mode()`` **自动拦掉**（那是故意的 —— 见那里的说明）。
        要验"它真的会去查"，得**临时把测试模式那几个判据也骗过去**。
        """
        import os

        from src.core import ui_state
        from src.gui import main_window as MW

        #: 塞个旧值（以前关过）—— 现在也该**照样查**
        ui_state.UiState().set("update_auto_check", False)

        scheduled: list[bool] = []

        def _fake_single_shot(_ms, fn=None):
            scheduled.append(True)

        import PySide6.QtCore as QtCore

        #: ⚠⚠ 必须**原样还回去**（包括它是 staticmethod 这件事）——
        #: 还成普通函数的话，别的测试再调它就带上 self，报奇怪的错
        orig = QtCore.QTimer.__dict__["singleShot"]
        orig_env = os.environ.pop("MYTOOLS_NO_AUTO_UPDATE", None)
        orig_detect = MW._in_test_mode
        try:
            MW._in_test_mode = lambda: False      #: 骗过"测试模式"判定
            w = MW.MainWindow()
            w._skip_auto_update = False
            QtCore.QTimer.singleShot = staticmethod(_fake_single_shot)
            w._maybe_auto_check_update()
        finally:
            QtCore.QTimer.singleShot = orig
            MW._in_test_mode = orig_detect
            if orig_env is not None:
                os.environ["MYTOOLS_NO_AUTO_UPDATE"] = orig_env

        self.assertTrue(scheduled,
                        "旧设置里关过就真的不查了 —— 但界面上没开关可打开")

    def test_silent_when_no_update(self):
        """★★★ 没更新时**什么都不做**（不许打扰）。"""
        from src.core import updater as U
        from src.gui.main_window import MainWindow

        w = MainWindow()
        hits: list[str] = []
        w.set_update_badge = lambda v="": hits.append(v)

        w._on_auto_checked(U.ReleaseInfo(ok=True, current="1.0.0",
                                         latest="v1.0.0", has_update=False))
        self.assertEqual(hits, [], "没更新还提示了")

    def test_badge_when_update_found(self):
        """★★★ 有更新 → 侧栏那一项显示**黄字**。

        用户 2026-10-05（截图圈出侧栏「检查更新」）::

            "有更新时，这里小黄字提示有更新即可"

        ⚠ 原来是弹 **InfoBar**（右上角浮一条）—— 用户觉得多余，
        改成侧栏直接显示黄字（位置固定、不打断）。
        """
        from src.core import updater as U
        from src.gui.main_window import MainWindow

        w = MainWindow()
        hits: list[str] = []
        w.set_update_badge = lambda v="": hits.append(v)

        w._on_auto_checked(U.ReleaseInfo(ok=True, current="1.0.0",
                                         latest="v1.1.0", has_update=True))
        self.assertEqual(hits, ["v1.1.0"],
                         "有更新却没在侧栏提示")

    def test_badge_sets_text_and_color(self):
        """★★★ 提示要**真的写进导航项**：文字带版本号 + 颜色是黄的。

        ## ⚠⚠ 两个坑（摸源码才搞清）

        **① 必须用 ``setText()``，不能赋值 ``item.text``**
        ``text`` 是基类**方法**，赋值会覆盖它 →
        ``paintEvent`` 里 ``self.text()`` 报
        ``'str' object is not callable`` → **界面一画就崩**。

        **② 颜色不是 QSS，是 ``setTextColor``**
        导航项是自绘的，写 ``styleSheet("color: ...")`` **没用**。
        """
        from src.core import skins
        from src.gui.main_window import UPDATE_BADGE_COLOR, MainWindow
        from PySide6.QtWidgets import QWidget

        skins.apply_skin(skins.DEFAULT_SKIN, save=True)
        w = MainWindow()
        w.set_update_badge("v1.1.0")

        item = w.navigationInterface.widget(
            w.update_interface.objectName())
        self.assertIsNotNone(item, "找不到「检查更新」导航项")
        inner = item.findChild(QWidget)
        target = inner if inner is not None else item

        self.assertIn("v1.1.0", target.text(),
                      f"导航项文字没带版本号：{target.text()!r}")
        self.assertEqual(target.lightTextColor.name().lower(),
                         UPDATE_BADGE_COLOR.lower(),
                         "导航项文字不是黄的")
        #: ⚠ text 必须还是**可调用**的（被赋值就崩了）
        self.assertTrue(callable(target.text),
                        "text 被赋成字符串了 —— paintEvent 会崩")

    def test_badge_clears(self):
        """★★ 传空 → 恢复默认文字和颜色。"""
        from src.core import skins
        from src.gui.main_window import MainWindow
        from PySide6.QtWidgets import QWidget

        skins.apply_skin(skins.DEFAULT_SKIN, save=True)
        w = MainWindow()
        w.set_update_badge("v1.1.0")
        w.set_update_badge("")

        item = w.navigationInterface.widget(
            w.update_interface.objectName())
        inner = item.findChild(QWidget)
        target = inner if inner is not None else item
        self.assertEqual(target.text(), "检查更新",
                         f"提示没清掉：{target.text()!r}")
        self.assertEqual(target.lightTextColor.name().lower(), "#000000",
                         "颜色没恢复默认")
        self.assertTrue(callable(target.text), "text 被赋成字符串了")


class TestThemeColorGcRace(unittest.TestCase):
    """★★★ ``setThemeColor`` 撞上 GC 要能自愈。

    ## 这个 ``RuntimeError`` 是 qfluentwidgets 的 bug，不是我们的

    它内部遍历**弱引用字典**::

        for widget, file in list(styleSheetManager.items()):

    正好有窗口被 GC 回收时，字典大小变了::

        RuntimeError: dictionary changed size during iteration

    **实测**：测试里连着建/销毁一堆 ``MainWindow`` 时，
    ``tests/test_updater.py`` 里一条用例**稳定复现** ——
    每个测试都会 ``apply_skin``，前面的窗口正好在那时候被回收。

    生产环境窗口少、几乎撞不上，但**测试里必现**，
    而且报错完全指不到"皮肤"上，极难查。
    """

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def test_retries_on_gc_race(self):
        """★★★ 撞一次"字典变了"要**自己重试**，最后成功。"""
        from src.core import skins

        calls: list[str] = []

        def _flaky(color, save=False):
            calls.append(color)
            if len(calls) == 1:
                raise RuntimeError("dictionary changed size during iteration")

        skins._set_theme_color(_flaky, "#123456")
        self.assertEqual(len(calls), 2, "没重试（应该试两次就成功）")

    def test_gives_up_gracefully(self):
        """★★ 一直失败也**不该把界面弄崩**（记日志、继续走）。"""
        from src.core import skins

        calls: list[str] = []

        def _always(color, save=False):
            calls.append(color)
            raise RuntimeError("dictionary changed size during iteration")

        skins._set_theme_color(_always, "#123456", tries=3)
        self.assertEqual(len(calls), 3, "没按 tries 次数重试")

    def test_other_runtime_errors_still_raise(self):
        """★ 别的 ``RuntimeError`` **照抛**（别把真错误也吞了）。"""
        from src.core import skins

        def _boom(color, save=False):
            raise RuntimeError("控件已销毁")

        with self.assertRaises(RuntimeError):
            skins._set_theme_color(_boom, "#123456")

    def test_apply_skin_survives_the_race(self):
        """★★★ 真调一次 ``apply_skin`` —— 底层撞竞态也不该冒泡出来。"""
        from src.core import skins

        #: 把 setThemeColor 换成"第一次必炸"的
        import qfluentwidgets

        real = qfluentwidgets.setThemeColor
        calls: list[int] = []

        def _flaky(color, save=False):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("dictionary changed size during iteration")
            return real(color, save=save)

        orig = skins.__dict__.get("setThemeColor")
        try:
            #: ``apply_skin`` 里是 ``from qfluentwidgets import setThemeColor``
            #: 之后当参数传进去的 —— 直接换掉那个模块属性即可
            qfluentwidgets.setThemeColor = _flaky
            self.assertTrue(skins.apply_skin(skins.DEFAULT_SKIN,
                                             save=False))
        finally:
            qfluentwidgets.setThemeColor = real
            if orig is not None:
                skins.setThemeColor = orig


class TestInstallQuitPath(unittest.TestCase):
    """★★★ 装更新前要**干净地退出**（不能裸 ``app.quit()``）。

    ## ⚠⚠ 这是我修过的一个真 bug

    ``install()`` 原来在启动安装包之后只调 ``app.quit()`` ——
    那只是**退出事件循环**，**不触发** ``MainWindow.closeEvent``。
    而那个函数负责三件要命的事：

      * **停掉在跑的任务**（否则 ok-ww 引擎留在半死不活的状态）
      * **清理系统托盘图标**（否则托盘残留一个死图标）
      * 真正关掉窗口

    在本场景里尤其要命：安装包要**覆盖安装目录的文件**，
    引擎还占着的话，Inno 的 Restart Manager 会检测到"文件正在使用"，
    多弹一个"要不要关掉它"的框。

    → 必须走 ``quit_app()``（它置 ``_force_quit`` 再 ``close()``，
    ``closeEvent`` 看到标志就跳过确认框、直接收尾）。
    """

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def test_install_quits_through_quit_app(self):
        """★★★ ``install()`` 要调 ``quit_app()``，**不是**裸 ``app.quit()``。"""
        from PySide6.QtWidgets import QApplication

        import src.core.updater as U
        from src.gui.update_card import build_update_page

        page = build_update_page()
        card = page.card
        card._installer = "fake-installer.exe"

        class _FakeWindow:
            def __init__(self):
                self.quit_called = False

            def quit_app(self):
                self.quit_called = True

        fake = _FakeWindow()
        orig_launch = U.launch_installer
        orig_tops = QApplication.topLevelWidgets
        U.launch_installer = lambda _p: None
        QApplication.topLevelWidgets = staticmethod(lambda: [fake])
        try:
            card.install()
        finally:
            U.launch_installer = orig_launch
            QApplication.topLevelWidgets = orig_tops

        self.assertTrue(fake.quit_called,
                        "install() 没走 quit_app() —— 托盘和任务都不收尾，"
                        "装包时可能撞上「文件正在使用」")

    def test_install_survives_missing_launcher(self):
        """★ 启动安装包失败 → 显示错误，**别退出**（用户还能重试）。"""
        import src.core.updater as U
        from src.gui.update_card import build_update_page

        page = build_update_page()
        card = page.card
        card._installer = "nope.exe"

        def _boom(_p):
            raise RuntimeError("找不到文件")

        orig = U.launch_installer
        U.launch_installer = _boom
        try:
            card.install()                     #: 不该抛出来
        finally:
            U.launch_installer = orig
        self.assertIn("失败", card.status.text())

    def test_install_without_path_is_noop(self):
        """★ 没下载好就不该动（别拿空路径去 startfile）。"""
        import src.core.updater as U
        from src.gui.update_card import build_update_page

        page = build_update_page()
        card = page.card
        card._installer = ""

        hits: list[str] = []
        orig = U.launch_installer
        U.launch_installer = lambda p: hits.append(str(p))
        try:
            card.install()
        finally:
            U.launch_installer = orig
        self.assertEqual(hits, [], "没有安装包却去启动了")


class TestInstallerAutoUpdateFlags(unittest.TestCase):
    """★★ 安装包脚本（``installer/mytools.iss``）的自动更新相关配置。

    ## ⚠⚠ 我一度**说错过**这件事

    我 grep 了 ``.iss`` 没找到 ``CloseApplications``，就断言
    "没写这个指令 → 装包时会报文件正在使用"。

    **查了官方文档才发现它默认就是 ``yes``**：https://jrsoftware.org/is6help/topic_setup_closeapplications.htm

    → 现在**显式**写出来，并在注释里说明"别改成 force"。
    """

    @classmethod
    def setUpClass(cls):
        cls.path = Path(ROOT) / "installer" / "mytools.iss"

    def test_iss_exists(self):
        self.assertTrue(self.path.exists(), "找不到 installer/mytools.iss")

    def test_close_applications_is_yes_not_force(self):
        """★★★ 必须是 ``yes``，**不能是 ``force``**。

        ⚠ ``force`` 会**强杀**进程 —— 而本程序退出时要收尾
        （停 ok-ww 引擎任务、清理托盘），强杀会把它留在半死不活的状态。
        """
        text = self.path.read_text(encoding="utf-8-sig")
        self.assertIn("CloseApplications=yes", text,
                      "没显式写 CloseApplications=yes（默认虽是 yes，"
                      "但显式写下来才不会被人顺手改掉）")
        self.assertNotIn("CloseApplications=force", text,
                         "用了 force —— 会强杀进程，引擎收不了尾")

    def test_restart_applications_enabled(self):
        """★ 装完要自动把程序拉起来（配合 postinstall）。"""
        text = self.path.read_text(encoding="utf-8-sig")
        self.assertIn("RestartApplications=yes", text,
                      "装完没自动重启 —— 用户会以为程序没了")

    def test_run_section_has_postinstall(self):
        """★ ``[Run]`` 里要有装完启动的项（不然重启不会发生）。"""
        text = self.path.read_text(encoding="utf-8-sig")
        run_idx = text.find("[Run]")
        self.assertGreater(run_idx, 0, "没有 [Run] 段")
        self.assertIn("postinstall", text[run_idx:],
                      "[Run] 里没有 postinstall —— 装完不会自动启动")


class TestPublishScript(unittest.TestCase):
    """★ 发布脚本（发 Release 用的）—— 静态检查，不真跑。"""

    @classmethod
    def setUpClass(cls):
        cls.path = Path(ROOT) / "dist" / "publish_release.ps1"

    def test_script_exists(self):
        self.assertTrue(self.path.exists(),
                        "没有 dist/publish_release.ps1 —— 用户收不到更新")

    def test_script_has_utf8_bom(self):
        """★★★ ``.ps1`` **必须有 UTF-8 BOM**。

        ⚠⚠ PowerShell 5.1 读**无 BOM** 的 ``.ps1`` 会按 **ANSI** 解码 ——
        中文注释和字符串全变乱码 → **语法错误、整个脚本跑不起来**。
        实测踩过：写完没 BOM，报的是
        ``Unexpected token '鍒涘缓'``（"创建"的乱码）。
        """
        raw = self.path.read_bytes()
        self.assertEqual(
            raw[:3], b"\xef\xbb\xbf",
            "publish_release.ps1 没有 UTF-8 BOM —— PowerShell 会把中文读成乱码")

    def test_script_reads_version_from_app_config(self):
        """★★ 版本号从 ``app_config.py`` 读（**唯一真源**）。"""
        text = self.path.read_text(encoding="utf-8-sig")
        self.assertIn("app_config.py", text,
                      "没从 app_config.py 读版本号")
        self.assertIn("APP_VERSION", text)

    def test_script_uses_env_token(self):
        """★★ token 从环境变量读 —— **不落盘**。"""
        text = self.path.read_text(encoding="utf-8-sig")
        self.assertIn("GITHUB_TOKEN", text)
        #: 不许把 token 写死在脚本里
        self.assertNotIn("ghp_", text.replace('"ghp_xxxxxxxxxxxx"', ""))

    def test_script_targets_the_right_repo(self):
        text = self.path.read_text(encoding="utf-8-sig")
        self.assertIn("Hub-yys/MyTools", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
