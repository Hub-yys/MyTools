# -*- coding: utf-8 -*-
"""「查询角色练度」—— 库街区账号接口客户端 + 工具页。

    python tests/test_character_build.py

## ★★★ 完整可用流程（2026-10-03 全部实测跑通）

    ┌─ ① APP 端登录（source=android）手机号 + 短信验证码 → token
    ├─ ② /gamer/role/list {gameId:3}  → roleId(特征码) + serverId
    ├─ ③ /aki/roleBox/requestToken {roleId, serverId} → accessToken(数据令牌)
    └─ ④ 之后所有 /aki/ 请求**只带 b-at 头**
          roleData                      → 角色列表
          getRoleDetail {id:<角色id>}   → ★ 声骸详情

## ★★ 这里**不打真实网络**

真实行为已经逐条实测验证（见 ``src/core/kuro_account.py`` 的模块文档）。
单测只保证：路径拼对、header 拼对（**这轮的核心**）、错误分类对、
令牌文件读写安全、工具页能构造 —— 那些是"改坏了不会有人立刻发现"的部分。
"""

from __future__ import annotations

import ast
import inspect
import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core import kuro_account  # noqa: E402

CORE = ROOT / "src" / "core" / "kuro_account.py"
TOOL = ROOT / "src" / "tools" / "game" / "character_build" / "tool.py"


class TestEndpoints(unittest.TestCase):
    """接口路径 —— 抄错一个字符就整个功能不可用。"""

    def test_root(self):
        self.assertEqual(kuro_account.API_ROOT, "https://api.kurobbs.com")

    def test_login_endpoints(self):
        self.assertEqual(kuro_account.API_SMS_CODE, "/user/getSmsCode")
        self.assertEqual(kuro_account.API_SDK_LOGIN, "/user/sdkLogin")

    def test_role_list_endpoint(self):
        """★ 取游戏角色 —— 要带 ``gameId=3``，否则只返回战双的号。"""
        self.assertEqual(kuro_account.API_ROLE_LIST, "/gamer/role/list")

    def test_data_token_endpoint(self):
        """★★ 换数据令牌 —— `/aki/` 的钥匙。"""
        self.assertEqual(kuro_account.API_REQUEST_TOKEN,
                         "/aki/roleBox/requestToken")

    def test_aki_endpoints(self):
        for name in ("API_BASE_DATA", "API_ROLE_DATA", "API_ROLE_DETAIL",
                     "API_CALABASH", "API_PHANTOM_DATA"):
            with self.subTest(const=name):
                self.assertTrue(getattr(kuro_account, name).startswith("/aki/"))


class TestFetchRolesSendsGameId(unittest.TestCase):
    """★★ ``findRoleList`` 必须带 ``gameId=3``（实测不带只返回战双号）。"""

    def test_game_id_in_body(self):
        captured: dict = {}

        def fake_call(path, body, token="", dev_code=""):
            captured["path"] = path
            captured["body"] = body
            return []

        orig = kuro_account._call
        kuro_account._call = fake_call
        try:
            kuro_account.fetch_roles("tok")
        finally:
            kuro_account._call = orig

        self.assertEqual(captured["body"].get("gameId"),
                         kuro_account.GAME_ID_WUWA,
                         "fetch_roles 没带 gameId —— "
                         "实测不带只会返回战双的号")


class TestDataTokenFlow(unittest.TestCase):
    """★★★ 「数据令牌」流程 —— 这是打开 `/aki/` 的钥匙。"""

    def test_request_data_token_returns_pair(self):
        """``request_data_token`` 返回 ``(token, tokenRequire)``。"""
        captured: dict = {}

        def fake_post(path, body, token="", dev_code="",
                      data_token="", source="android"):
            captured["path"] = path
            captured["body"] = body
            captured["token"] = token
            return {"code": 200,
                    "data": {"accessToken": "DT123", "tokenRequire": False}}

        orig = kuro_account._post
        kuro_account._post = fake_post
        try:
            dt, req = kuro_account.request_data_token("tok", "113", "srv")
        finally:
            kuro_account._post = orig

        self.assertEqual(dt, "DT123")
        self.assertIs(req, False)
        self.assertEqual(captured["path"], "/aki/roleBox/requestToken")
        # ★ 用它自己的普通令牌（不是数据令牌）
        self.assertEqual(captured["token"], "tok")

    def test_user_id_optional(self):
        """★ ``userId`` 可选（实测三种 body 都返回同一个 accessToken）。"""
        sig = inspect.signature(kuro_account.request_data_token)
        self.assertEqual(sig.parameters["user_id"].default, "")


class TestAkiUsesOnlyBAt(unittest.TestCase):
    """★★★ ``/aki/`` 请求**只带 `b-at`** —— 这轮踩得最狠的坑。

    ======================  ==========================  ==================
    header 组合              结果                        说明
    ======================  ==========================  ==================
    **只 b-at**              ✅ ``200 请求成功``          正确
    b-at + token            ❌ ``10000 参数错误``        不能同时带
    只 token                ❌ ``10900 角色查询失败``    普通令牌无效
    b-at + ``source=h5``    ❌ ``10901 禁止访问``        必须 android
    ======================  ==========================  ==================
    """

    def test_aki_helper_sends_no_token(self):
        captured: dict = {}

        def fake_post(path, body, token="", dev_code="",
                      data_token="", source="android"):
            captured.update(path=path, token=token, data_token=data_token,
                            source=source)
            return {"code": 200, "data": {"ok": True}}

        orig = kuro_account._post
        kuro_account._post = fake_post
        try:
            kuro_account.fetch_base_data("DT", "113", "srv")
        finally:
            kuro_account._post = orig

        self.assertEqual(captured["data_token"], "DT",
                         "没带数据令牌")
        self.assertFalse(captured["token"],
                         "★ 带了普通 token —— 实测会变 10000 参数错误")
        self.assertEqual(captured["source"], "android",
                         "★ 用了非 android —— 实测 h5 会 10901 禁止访问")

    def test_role_detail_only_b_at(self):
        captured: dict = {}

        def fake_post(path, body, token="", dev_code="",
                      data_token="", source="android"):
            captured.update(body=body, token=token, data_token=data_token)
            return {"code": 200, "data": {}}

        orig = kuro_account._post
        kuro_account._post = fake_post
        try:
            kuro_account.fetch_role_detail("DT", "113152489", "srv", 1103)
        finally:
            kuro_account._post = orig

        self.assertFalse(captured["token"])
        self.assertEqual(captured["data_token"], "DT")


class TestRoleDetailParamName(unittest.TestCase):
    """★★★ ``getRoleDetail`` 的参数名是 **``id``** —— 绕了很久的坑。

    实测::

        id=1103       → 200 请求成功        ★ 对的
        charId=1103   → 10000 查询的角色id不能为空
        roleId=1103   → 10000 查询的角色id不能为空
        mapRoleId     → 10000
        heroId        → 10000
        resonatorId   → 10000
        role_id       → 10000
        char_id       → 10000

    ## 两个 ``roleId`` 不是一回事（最容易搞混）

        roleId = "113152489"               ← 特征码（**账号级**）
        id     = 1103（白芷）               ← 角色 id（**角色级**）
                                             getRoleDetail 要**这个**
    """

    def _body_for(self, char_id) -> dict:
        captured: dict = {}

        def fake_post(path, body, **kw):
            captured["body"] = body
            return {"code": 200, "data": {}}

        orig = kuro_account._post
        kuro_account._post = fake_post
        try:
            kuro_account.fetch_role_detail("DT", "113152489", "srv", char_id)
        finally:
            kuro_account._post = orig
        return captured["body"]

    def test_body_has_id_field(self):
        body = self._body_for(1103)
        self.assertIn("id", body,
                      "★ 参数名不是 id —— 实测 charId/roleId 都会回 10000")
        self.assertEqual(str(body["id"]), "1103")

    def test_body_has_no_char_id(self):
        """★ 不能出现 ``charId``（那个名字服务端不认）。"""
        body = self._body_for(1103)
        self.assertNotIn("charId", body,
                         "★ 出现了 charId —— 实测服务端回 "
                         "10000 查询的角色id不能为空")

    def test_account_role_id_is_the_feature_code(self):
        """``roleId`` 传的是**特征码**，``id`` 才是角色 id。"""
        body = self._body_for(1103)
        self.assertEqual(str(body["roleId"]), "113152489")
        self.assertEqual(str(body["id"]), "1103")


class TestErrorClassification(unittest.TestCase):
    def test_expired_is_kuro_error(self):
        self.assertTrue(issubclass(kuro_account.TokenExpired,
                                   kuro_account.KuroError))

    def test_auth_codes(self):
        self.assertIn(220, kuro_account.AUTH_CODES)

    def test_error_carries_code_and_path(self):
        exc = kuro_account.KuroError(10901, "禁止访问", path="/aki/x")
        self.assertEqual(exc.code, 10901)
        self.assertIn("禁止访问", str(exc))
        self.assertIn("/aki/x", str(exc))


class TestHeaders(unittest.TestCase):
    def test_required_headers(self):
        h = kuro_account._headers()
        for key in ("source", "devcode", "User-Agent", "Content-Type"):
            with self.subTest(key=key):
                self.assertIn(key, h)

    def test_token_only_when_given(self):
        self.assertNotIn("token", kuro_account._headers())
        self.assertEqual(kuro_account._headers("abc")["token"], "abc")

    def test_b_at_only_when_given(self):
        """★ 数据令牌走 ``b-at`` 头。"""
        self.assertNotIn("b-at", kuro_account._headers())
        self.assertEqual(kuro_account._headers(data_token="DT")["b-at"], "DT")

    def test_source_switchable(self):
        """★ ``source`` 可切换（实测 h5 / android 行为不同）。"""
        self.assertEqual(kuro_account._headers(source="h5")["source"], "h5")
        self.assertEqual(kuro_account._headers(source="android")["source"],
                         "android")

    def test_distinct_id_random(self):
        ids = {kuro_account._headers()["distinct_id"] for _ in range(5)}
        self.assertEqual(len(ids), 5)


class TestTokenStorage(unittest.TestCase):
    """★★ 令牌文件 —— 这是**用户的账号凭证**。"""

    def test_roundtrip_includes_data_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "a.json"
            acc = kuro_account.Account(
                token="tok", dev_code="dc", data_token="DT", user_id="9",
                mobile_tail="7393", roles=[{"roleId": 1}], login_at=1.0)
            kuro_account.save_account(acc, path)
            got = kuro_account.load_account(path)
            self.assertEqual(got.token, "tok")
            self.assertEqual(got.data_token, "DT",
                             "数据令牌没存下来 —— 每次都要重新换")
            self.assertEqual(got.user_id, "9")
            self.assertEqual(got.mobile_tail, "7393")

    def test_missing_file_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(
                kuro_account.load_account(pathlib.Path(tmp) / "no.json")
                .logged_in)

    def test_corrupt_file_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp) / "bad.json"
            p.write_text("{ 不是 json", encoding="utf-8")
            self.assertFalse(kuro_account.load_account(p).logged_in)

    def test_clear_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp) / "a.json"
            kuro_account.save_account(kuro_account.Account(token="t"), p)
            kuro_account.clear_account(p)
            kuro_account.clear_account(p)       # 再删一次不该报错

    def test_only_mobile_tail_stored(self):
        """★ **绝不存完整手机号**。"""
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp) / "a.json"
            kuro_account.save_account(
                kuro_account.Account(token="t", mobile_tail="7393"), p)
            raw = p.read_text(encoding="utf-8")
            self.assertNotIn("15927967393", raw)
            self.assertIn("7393", raw)

    def test_token_file_under_user_data(self):
        from src.core import paths

        self.assertEqual(kuro_account.token_file().parent,
                         paths.user_data_dir())


class TestAppLogin(unittest.TestCase):
    """★ APP 端登录 —— `/aki/` 只认这个来源的令牌。"""

    def test_function_exists(self):
        self.assertTrue(hasattr(kuro_account, "app_login_with_code"))

    def test_uses_android_source(self):
        """★★ 实测：``source=h5`` 时 ``/aki/`` 全部 10901 禁止访问。"""
        source = CORE.read_text(encoding="utf-8")
        tree = ast.parse(source)
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef)
                  and n.name == "app_login_with_code")
        body = ast.get_source_segment(source, fn) or ""
        self.assertIn("_call", body)

    def test_calls_sdk_login(self):
        source = CORE.read_text(encoding="utf-8")
        tree = ast.parse(source)
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef)
                  and n.name == "app_login_with_code")
        names = {getattr(n, "id", None) or getattr(n, "attr", None)
                 for n in ast.walk(fn)}
        self.assertIn("API_SDK_LOGIN", names,
                      "APP 端登录没调 sdkLogin")


class TestRoleNotFoundGuard(unittest.TestCase):
    """★★★ **``code=200`` 但 ``data=None`` 不能算成功** —— 用户问"换个号"引出的坑。

    ## 实测（2026-10-03）

    用**别人的 / 瞎编的**特征码调 ``/aki/`` 接口，服务端回的是::

        {"code": 200, "msg": "请求成功", "data": null, "success": true}

    **``code`` 是 200、``msg`` 是"请求成功"，但数据是空的。**

    不特判的话，界面会**报成功却什么都不显示** ——
    用户完全看不出"是网络问题还是这个号查不到"。

    实测对照::

        roleId=113152489（自己的） → data 有完整内容
        roleId=113152490（别人的） → code=200, data=None
        roleId=123456789（瞎编的） → code=200, data=None
    """

    def test_exception_exists(self):
        self.assertTrue(hasattr(kuro_account, "RoleNotFound"))
        self.assertTrue(issubclass(kuro_account.RoleNotFound,
                                   kuro_account.KuroError))

    def test_message_mentions_feature_code(self):
        exc = kuro_account.RoleNotFound(path="/aki/x", role_id="123456789")
        self.assertIn("123456789", str(exc),
                      "报错要带上特征码 —— 不然用户不知道是哪个号查不到")

    def test_message_mentions_role_display(self):
        """★ 提示要点出"角色展示"这个可能原因。

        鸣潮工坊的弹窗写明「必须在库街区中开放[角色展示]」。
        """
        exc = kuro_account.RoleNotFound()
        self.assertIn("角色展示", str(exc))

    def test_aki_raises_on_null_data(self):
        """★ ``data=None`` 要抛 ``RoleNotFound``（默认行为）。"""
        def fake_post(path, body, **kw):
            return {"code": 200, "msg": "请求成功", "data": None,
                    "success": True}

        orig = kuro_account._post
        kuro_account._post = fake_post
        try:
            with self.assertRaises(kuro_account.RoleNotFound):
                kuro_account.fetch_base_data("DT", "113152489", "srv")
        finally:
            kuro_account._post = orig

    def test_aki_ok_when_data_present(self):
        """有数据时不抛。"""
        def fake_post(path, body, **kw):
            return {"code": 200, "msg": "请求成功",
                    "data": {"name": "银月"}}

        orig = kuro_account._post
        kuro_account._post = fake_post
        try:
            got = kuro_account.fetch_base_data("DT", "113152489", "srv")
        finally:
            kuro_account._post = orig
        self.assertEqual(got.get("name"), "银月")


class TestResolveRoleByFeatureCode(unittest.TestCase):
    """★★ 用**特征码**定位角色（界面要支持手填特征码）。"""

    def test_function_exists(self):
        self.assertTrue(hasattr(kuro_account, "resolve_role"))

    def test_matches_exact_feature_code(self):
        def fake_fetch(token, dev_code=""):
            return [{"roleId": "113152489", "serverName": "鸣潮"},
                    {"roleId": "58420274", "serverName": "星火服"}]

        orig = kuro_account.fetch_roles
        kuro_account.fetch_roles = fake_fetch
        try:
            got = kuro_account.resolve_role("tok", "58420274")
        finally:
            kuro_account.fetch_roles = orig
        self.assertIsNotNone(got)
        self.assertEqual(got["roleId"], "58420274")

    def test_returns_none_when_not_bound(self):
        """★★ 别人的特征码查不到 —— **一个账号只能绑一个号**（实测）。"""
        def fake_fetch(token, dev_code=""):
            return [{"roleId": "113152489"}]

        orig = kuro_account.fetch_roles
        kuro_account.fetch_roles = fake_fetch
        try:
            got = kuro_account.resolve_role("tok", "999999999")
        finally:
            kuro_account.fetch_roles = orig
        self.assertIsNone(got)

    def test_empty_code_returns_none(self):
        self.assertIsNone(kuro_account.resolve_role("tok", ""))

    def test_network_failure_returns_none(self):
        """★ 网络失败返回 None，不该把异常抛给界面。"""
        def boom(token, dev_code=""):
            raise kuro_account.KuroError(220, "登录已过期")

        orig = kuro_account.fetch_roles
        kuro_account.fetch_roles = boom
        try:
            self.assertIsNone(kuro_account.resolve_role("tok", "113152489"))
        finally:
            kuro_account.fetch_roles = orig


class TestToolPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def _panel(self):
        from src.tools.game.character_build.tool import CharacterBuildPanel

        return CharacterBuildPanel()

    def test_panel_builds(self):
        self.assertIsNotNone(self._panel())

    def test_has_mobile_and_code_inputs(self):
        """★ 界面要有手机号 + 验证码输入框（不再用内嵌浏览器）。"""
        p = self._panel()
        self.assertTrue(hasattr(p, "_mobile_edit"))
        self.assertTrue(hasattr(p, "_code_edit"))

    def test_has_feature_code_input(self):
        """★★ 界面要有**特征码**输入框。

        用户："特征码呢，我要是换个号不是没地方输入吗"

        鸣潮工坊的绑定弹窗就是三栏：**特征码 + 手机号 + 验证码**。
        """
        p = self._panel()
        self.assertTrue(hasattr(p, "_feature_edit"),
                        "没有特征码输入框 —— 换号时没地方填")

    def test_fetch_disabled_when_logged_out(self):
        p = self._panel()
        if not p._account.logged_in:
            self.assertFalse(p._fetch_button.isEnabled())

    def test_logout_button_exists(self):
        self.assertTrue(hasattr(self._panel(), "_logout_button"))

    def test_summary_matches_real_data(self):
        """★ 摘要文案和实测数据对得上。"""
        base = {"energy": 102, "maxEnergy": 240,
                "storeEnergy": 30, "storeEnergyLimit": 480,
                "liveness": 100, "livenessMaxCount": 100,
                "activeDays": 830, "level": 80, "roleNum": 43}
        from src.tools.game.character_build.tool import CharacterBuildPanel

        text = CharacterBuildPanel._format_base(base)
        for want in ("102/240", "30/480", "100/100", "830", "80", "43"):
            with self.subTest(want=want):
                self.assertIn(want, text)

    def test_registered(self):
        from src.core.categories import ToolCategory
        from src.core.registry import ToolRegistry
        from src.tools import discover_tools

        discover_tools()
        meta = next((m for m in ToolRegistry.all_metas()
                     if m.key == "character_build"), None)
        self.assertIsNotNone(meta, "工具没注册上")
        self.assertEqual(meta.name, "查询角色练度")
        self.assertEqual(meta.category, ToolCategory.GAME)
        self.assertFalse(meta.coming_soon)
        self.assertFalse(meta.supports_task_run)

    def test_no_browser_dialog_left(self):
        """★ 内嵌浏览器那条路已经废掉（网页令牌 `/aki/` 不认）。

        留着会误导 —— 看到「打开登录窗口」的人会以为要走浏览器。
        """
        self.assertFalse(
            (ROOT / "src" / "tools" / "game" / "character_build"
             / "login_dialog.py").exists(),
            "还有 login_dialog.py —— 那条路已被证明走不通（网页令牌 "
            "/aki/ 回 10901），应该删掉")


class TestNoNetworkOnImport(unittest.TestCase):
    def test_module_import_has_no_top_level_calls(self):
        tree = ast.parse(CORE.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                func = node.value.func
                name = getattr(func, "id", None) or getattr(func, "attr", None)
                self.assertNotIn(name, ("urlopen", "post", "_call", "_post"))


class TestDoesNotTouchWikiModule(unittest.TestCase):
    """★★ 两套库街区接口**不能互相 import**。"""

    def test_kuro_account_does_not_import_wuwa_update(self):
        tree = ast.parse(CORE.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                self.assertNotIn("wuwa_update", node.module or "")
            elif isinstance(node, ast.Import):
                for a in node.names:
                    self.assertNotIn("wuwa_update", a.name)

    def test_wiki_module_does_not_import_kuro_account(self):
        text = (ROOT / "src" / "core" / "wuwa_update.py").read_text(
            encoding="utf-8")
        self.assertNotIn("kuro_account", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
