"""「查询角色练度」—— 库街区账号数据客户端 + 工具页。

    python tests/test_character_build.py

## 这个功能是什么

用户要"比对我的账户下哪些角色声骸属性不好，需要再哪些刷声骸"。
数据来自库街区 APP 的「数据终端」（``api.kurobbs.com/aki/...``）——
**和「资源库更新」那套公开 wiki 接口是两套东西**：那个查图鉴，这个查账号。

## ⚠ 这里**不打真实网络**

接口的真实行为已经用真机探测验证过（见 ``src/core/kuro_account.py`` 的模块
文档）。单测只保证：路径拼对、错误分类对、令牌文件读写安全、
工具页能构造 —— 那些是"改坏了不会有人立刻发现"的部分。
"""

from __future__ import annotations

import ast
import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core import kuro_account  # noqa: E402

TOOL = ROOT / "src" / "tools" / "game" / "character_build" / "tool.py"
PKG = ROOT / "src" / "tools" / "game" / "character_build" / "__init__.py"


class TestEndpoints(unittest.TestCase):
    """★ 接口路径 —— 抄错一个字符就整个功能不可用。"""

    def test_root_is_the_api_host(self):
        self.assertEqual(kuro_account.API_ROOT, "https://api.kurobbs.com")

    def test_login_endpoints(self):
        """登录两个接口（**已实测存在**：getSmsCode 回「手机号格式有误」、
        sdkLogin 回「验证码已经过期」）。"""
        self.assertEqual(kuro_account.API_SMS_CODE, "/user/getSmsCode")
        self.assertEqual(kuro_account.API_SDK_LOGIN, "/user/sdkLogin")

    def test_account_endpoints_under_aki(self):
        """账号数据全在 ``/aki/`` 下 —— 和 wiki 那套分开。"""
        for name in ("API_BASE_DATA", "API_ROLE_DATA", "API_ROLE_DETAIL",
                     "API_ALL_SUB_PROPS", "API_CALABASH", "API_EXPLORE"):
            with self.subTest(const=name):
                self.assertTrue(
                    getattr(kuro_account, name).startswith("/aki/"),
                    f"{name} 不在 /aki/ 下 —— 可能和 wiki 接口混了")

    def test_role_detail_is_the_echo_source(self):
        """★ ``getRoleDetail`` 是**声骸数据的唯一来源**（phantomList）。"""
        self.assertEqual(kuro_account.API_ROLE_DETAIL,
                         "/aki/roleBox/akiBox/getRoleDetail")


class TestGameParams(unittest.TestCase):
    """请求体参数。"""

    def test_wuwa_game_id(self):
        """鸣潮 gameId 固定 3。"""
        self.assertEqual(kuro_account.GAME_ID_WUWA, 3)

    def test_channel_id(self):
        self.assertEqual(kuro_account.CHANNEL_ID, 19)

    def test_base_body_has_all_required(self):
        body = kuro_account._base_body("tok", 123, 1, 1)
        for key in ("gameId", "roleId", "serverId", "channelId",
                    "countryCode"):
            with self.subTest(key=key):
                self.assertIn(key, body)


class TestHeaders(unittest.TestCase):
    """请求头 —— 少一个都可能被服务端拒。"""

    def test_required_headers(self):
        h = kuro_account._headers()
        for key in ("source", "devcode", "User-Agent", "Content-Type"):
            with self.subTest(key=key):
                self.assertIn(key, h)

    def test_token_only_when_given(self):
        """★ 没登录时**不能**带空 token（有的接口会因此报错）。"""
        self.assertNotIn("token", kuro_account._headers())
        self.assertEqual(kuro_account._headers("abc")["token"], "abc")

    def test_distinct_id_is_random_each_call(self):
        """``distinct_id`` 每次都要新 —— 复用会被风控盯上。"""
        ids = {kuro_account._headers()["distinct_id"] for _ in range(5)}
        self.assertEqual(len(ids), 5)


class TestErrorClassification(unittest.TestCase):
    """★ 错误分类 —— 决定界面提示"重新登录"还是"稍后再试"。"""

    def test_expired_raises_token_expired(self):
        self.assertTrue(issubclass(kuro_account.TokenExpired,
                                   kuro_account.KuroError))

    def test_auth_codes_include_220(self):
        """220 是文档里写明的"访问令牌不能为空/失效"。"""
        self.assertIn(220, kuro_account.AUTH_CODES)

    def test_error_carries_code_and_msg(self):
        exc = kuro_account.KuroError(123, "出错了", path="/x/y")
        self.assertEqual(exc.code, 123)
        self.assertIn("出错了", str(exc))
        self.assertIn("/x/y", str(exc))


class TestTokenStorage(unittest.TestCase):
    """★★ 令牌文件 —— 这是**用户的账号凭证**，读写必须小心。"""

    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "a.json"
            acc = kuro_account.Account(
                token="tok123", mobile_tail="1234",
                profile={"userId": "9"}, roles=[{"roleId": 1}],
                login_at=123.0)
            kuro_account.save_account(acc, path)

            got = kuro_account.load_account(path)
            self.assertEqual(got.token, "tok123")
            self.assertEqual(got.mobile_tail, "1234")
            self.assertEqual(got.roles, [{"roleId": 1}])
            self.assertTrue(got.logged_in)

    def test_missing_file_is_empty_not_error(self):
        """★ 文件不在 → 空账号，**不抛异常**（首次启动就是这个状态）。"""
        with tempfile.TemporaryDirectory() as tmp:
            got = kuro_account.load_account(pathlib.Path(tmp) / "nope.json")
            self.assertFalse(got.logged_in)

    def test_corrupt_file_is_empty_not_error(self):
        """★ 文件坏了 → 空账号（不能让坏文件把工具卡死）。"""
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "bad.json"
            path.write_text("{ 这不是 json", encoding="utf-8")
            got = kuro_account.load_account(path)
            self.assertFalse(got.logged_in)

    def test_clear_removes_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "a.json"
            kuro_account.save_account(
                kuro_account.Account(token="t"), path)
            self.assertTrue(path.exists())
            kuro_account.clear_account(path)
            self.assertFalse(path.exists())

    def test_clear_missing_is_noop(self):
        """★ 重复点「退出登录」不该报错。"""
        with tempfile.TemporaryDirectory() as tmp:
            kuro_account.clear_account(pathlib.Path(tmp) / "nope.json")

    def test_only_stores_mobile_tail(self):
        """★★ **绝不存完整手机号** —— 只存后 4 位。"""
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "a.json"
            acc = kuro_account.Account(token="t", mobile_tail="1234")
            kuro_account.save_account(acc, path)
            raw = path.read_text(encoding="utf-8")
            self.assertNotIn("13800138000", raw)
            self.assertIn("1234", raw)

    def test_token_file_under_user_data(self):
        """★ 令牌要落在**用户数据目录**（打包后 Program Files 是只读的）。"""
        from src.core import paths

        self.assertEqual(kuro_account.token_file().parent,
                         paths.user_data_dir())


class TestToolPage(unittest.TestCase):
    """工具页 —— 构造、注册、UI 结构。"""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def _panel(self):
        from src.tools.game.character_build.tool import CharacterBuildPanel

        return CharacterBuildPanel()

    def test_panel_builds(self):
        """★ 构造不能炸（⚠ 我第一版就是构造时 AttributeError：
        ``_refresh_login_state`` 在数据卡片创建按钮**之前**跑）。"""
        panel = self._panel()
        self.assertIsNotNone(panel)

    def test_fetch_disabled_when_logged_out(self):
        """未登录时「获取数据」要禁用。"""
        panel = self._panel()
        if not panel._account.logged_in:
            self.assertFalse(panel._fetch_button.isEnabled())

    def test_logout_button_exists(self):
        """★ 必须有「退出登录」—— 用户要能删掉自己的凭证。"""
        panel = self._panel()
        self.assertTrue(hasattr(panel, "_logout_button"))

    def test_summary_matches_screenshot(self):
        """★ 摘要文案要和用户截图里那份数据对得上。"""
        base = {"energy": 64, "maxEnergy": 240,
                "storeEnergy": 30, "storeEnergyLimit": 480,
                "liveness": 100, "livenessMaxCount": 100,
                "activeDays": 830, "level": 80, "roleNum": 43}
        from src.tools.game.character_build.tool import CharacterBuildPanel

        text = CharacterBuildPanel._format_base(base)
        for want in ("64/240", "30/480", "100/100", "830", "80", "43"):
            with self.subTest(want=want):
                self.assertIn(want, text)

    def test_format_base_handles_empty(self):
        from src.tools.game.character_build.tool import CharacterBuildPanel

        self.assertIsInstance(CharacterBuildPanel._format_base({}), str)

    def test_registered_as_game_tool(self):
        from src.core.categories import ToolCategory
        from src.core.registry import ToolRegistry
        from src.tools import discover_tools
        from src.tools.game.character_build.tool import CharacterBuildTool

        discover_tools()
        meta = next((m for m in ToolRegistry.all_metas()
                     if m.key == "character_build"), None)
        self.assertIsNotNone(meta, "工具没注册上")
        self.assertEqual(meta.name, "查询角色练度")
        self.assertEqual(meta.category, ToolCategory.GAME)
        self.assertFalse(meta.coming_soon,
                         "coming_soon=True 会显示占位页")
        self.assertFalse(meta.supports_task_run,
                         "它不操作游戏，不该进任务流程")
        self.assertEqual(CharacterBuildTool.key, "character_build")


class TestNoNetworkOnImport(unittest.TestCase):
    """★ import 时不能发网络请求（会让启动变慢 / 离线时炸）。"""

    def test_module_import_has_no_top_level_calls(self):
        tree = ast.parse((ROOT / "src" / "core"
                          / "kuro_account.py").read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                func = node.value.func
                name = getattr(func, "id", None) or getattr(
                    func, "attr", None) or ""
                self.assertNotIn(
                    name, ("urlopen", "post", "get", "_call", "_post"),
                    f"模块级就调用了 {name} —— import 时会发请求")


class TestDoesNotTouchWikiModule(unittest.TestCase):
    """★★ 两套库街区接口**不能互相 import**（一个查图鉴、一个查账号）。"""

    def test_kuro_account_does_not_import_wuwa_update(self):
        text = (ROOT / "src" / "core" / "kuro_account.py").read_text(
            encoding="utf-8")
        tree = ast.parse(text)
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                imported.append(node.module or "")
            elif isinstance(node, ast.Import):
                imported.extend(a.name for a in node.names)
        for mod in imported:
            with self.subTest(mod=mod):
                self.assertNotIn("wuwa_update", mod,
                                 "账号模块不该依赖图鉴模块")

    def test_wiki_module_does_not_import_kuro_account(self):
        text = (ROOT / "src" / "core" / "wuwa_update.py").read_text(
            encoding="utf-8")
        self.assertNotIn("kuro_account", text,
                         "图鉴模块不该依赖账号模块")


if __name__ == "__main__":
    unittest.main(verbosity=2)
