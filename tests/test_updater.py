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

    def test_auto_check_defaults_on_and_persists(self):
        """★★ 「启动时自动检查」默认**开**，且开关能存下来。"""
        from src.gui.update_card import build_update_card

        card = build_update_card()
        self.assertTrue(card.auto_check_enabled(), "默认该是开的")

        card.set_auto_check(False)
        card2 = build_update_card()
        self.assertFalse(card2.auto_check_enabled(), "关掉之后没存下来")

        card2.set_auto_check(True)
        self.assertTrue(build_update_card().auto_check_enabled())

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

    def test_main_window_has_auto_check_hooks(self):
        from src.gui.main_window import MainWindow

        w = MainWindow()
        for name in ("_maybe_auto_check_update", "_auto_check_update",
                     "_on_auto_checked"):
            with self.subTest(name=name):
                self.assertTrue(hasattr(w, name), f"主窗口少了 {name}")

    def test_auto_check_disabled_skips(self):
        """★★ 关掉开关后，启动**不该**去查（不打扰用户）。"""
        from src.core import ui_state
        from src.gui.main_window import MainWindow

        ui_state.UiState().set("update_auto_check", False)
        w = MainWindow()
        called: list[bool] = []
        w._auto_check_update = lambda: called.append(True)
        w._maybe_auto_check_update()
        #: 关掉时不该排定时器 → 立刻检查 called 还是空
        self.assertEqual(called, [], "关掉了还去查")

    def test_silent_when_no_update(self):
        """★★★ 没更新时**什么都不做**（不许弹提示骚扰）。"""
        from src.core import updater as U
        from src.gui.main_window import MainWindow

        w = MainWindow()
        #: 把 InfoBar 换成探针 —— 调用了就说明弹了
        import qfluentwidgets

        hits: list[str] = []
        orig = getattr(qfluentwidgets, "InfoBar", None)
        try:
            class _Probe:
                @staticmethod
                def new(**_kw):
                    hits.append("shown")

                    class _B:
                        def show(self):
                            pass
                    return _B()
            qfluentwidgets.InfoBar = _Probe

            w._on_auto_checked(U.ReleaseInfo(ok=True, current="0.5.3",
                                             latest="v0.5.3",
                                             has_update=False))
            self.assertEqual(hits, [], "没更新还弹提示了")
        finally:
            if orig is not None:
                qfluentwidgets.InfoBar = orig

    def test_prompts_when_update_found(self):
        """★★★ 有更新时**才**提示。"""
        from src.core import updater as U
        from src.gui.main_window import MainWindow

        w = MainWindow()
        import qfluentwidgets

        hits: list[str] = []
        orig = getattr(qfluentwidgets, "InfoBar", None)
        try:
            class _Probe:
                @staticmethod
                def new(**kw):
                    hits.append(str(kw.get("content") or ""))

                    class _B:
                        def show(self):
                            pass
                    return _B()
            qfluentwidgets.InfoBar = _Probe

            w._on_auto_checked(U.ReleaseInfo(ok=True, current="0.5.3",
                                             latest="v0.6.0",
                                             has_update=True))
            self.assertTrue(hits, "有更新却没提示")
            self.assertIn("0.6.0", hits[0])
        finally:
            if orig is not None:
                qfluentwidgets.InfoBar = orig


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
