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


class TestEchoIssues(unittest.TestCase):
    """★★ 声骸"待优化"判定 —— 第一版只报**客观事实**。

    ====================  ============================================
    规则                  说明
    ====================  ============================================
    **等级没满**           有声骸 ``level < 25``
    **套装不统一**         5 个声骸的套装名不止一种
    **COST 配比不对**      不是 4-3-3-1-1
    **有效词条太少**       副词条里 ``valid=true`` 的总数 < 10
    ====================  ============================================

    ⚠ 这些**不掺主观"好不好"** —— 等用户给了按角色的标准再改。
    """

    @staticmethod
    def _detail(items) -> dict:
        return {"phantomData": {"equipPhantomList": items}}

    @staticmethod
    def _item(cost, level=25, fetter="隐世回光", valid=2, name="x"):
        return {
            "cost": cost, "level": level, "quality": 5,
            "phantomProp": {"name": name},
            "fetterDetail": {"name": fetter},
            "mainProps": [{"attributeName": "攻击",
                           "attributeValue": "18.0%", "valid": True}],
            "subProps": [{"attributeName": f"c{i}",
                          "attributeValue": "1%",
                          "valid": i < valid} for i in range(5)],
        }

    def _issues(self, items):
        from src.tools.game.character_build.tool import CharacterBuildPanel

        return CharacterBuildPanel._echo_issues(self._detail(items))

    def test_good_echoes_no_issues(self):
        """满级 + 同套装 + COST 4-3-3-1-1 + 有效词条够 → 没问题。"""
        items = [self._item(c, valid=3) for c in (4, 3, 3, 1, 1)]
        self.assertEqual(self._issues(items), [])

    def test_detects_not_max_level(self):
        items = [self._item(c, level=20, valid=3) for c in (4, 3, 3, 1, 1)]
        self.assertTrue(any("没满级" in x for x in self._issues(items)))

    def test_mixed_sets_alone_is_not_a_problem(self):
        """★★★ **混搭本身不是问题**（那条"套装不统一"已删）。

        用户 2026-10-05（截图圈出千咲属性全绿却进「未达标」）：
        "达标的怎么进了未达标的？"

        千咲官方推荐的就是 **3+2 混搭** —— "不统一"根本不是问题，
        **对不上官方组合**才是（见 :class:`TestEchoSetComparison`）。

        ⚠ 这条原来叫 ``test_detects_mixed_sets``，断言"混搭要报错" ——
        **那是错的**，改过来了。
        """
        items = [self._item(c, valid=3, fetter="A" if c == 4 else "B")
                 for c in (4, 3, 3, 1, 1)]
        self.assertEqual([x for x in self._issues(items) if "套装" in x], [],
                         "混搭被报成问题了 —— 3+2 是合法配装")

    def test_detects_wrong_cost(self):
        """★ COST 不是 4-3-3-1-1 要报出来（实测见过别的配比）。"""
        items = [self._item(c, valid=3) for c in (4, 4, 1, 1, 1)]
        self.assertTrue(any("COST" in x for x in self._issues(items)))

    def test_cost_order_does_not_matter(self):
        """★ COST 只看**组成**，排序无关。"""
        items = [self._item(c, valid=3) for c in (1, 4, 1, 3, 3)]
        self.assertEqual([x for x in self._issues(items) if "COST" in x], [])

    def test_valid_substat_rule_is_gone(self):
        """★★ "有效词条 < 10" 这条规则**删掉了**。

        ⚠ 那个 10 是**我瞎定的** —— 用户 2026-10-05 给了官方攻略站，
        现在改用**官方推荐属性**（每个角色各自的达标线）判定。

        → 所以"词条少"本身**不再**是问题（除非官方标准里有）。
        """
        items = [self._item(c, valid=1) for c in (4, 3, 3, 1, 1)]
        self.assertEqual(
            [x for x in self._issues(items) if "有效词条" in x], [],
            "「有效词条 < 10」这条瞎定的规则还在 —— 应该改用官方标准")

    def test_empty_detail(self):
        self.assertTrue(self._issues([]))


class TestCachePersistence(unittest.TestCase):
    """★★ 数据持久化 —— 重启后直接显示上次结果，不用重拉。

    ## ⚠⚠ 测试**绝不能**写用户的真实缓存

    2026-10-03 我踩过：一个探索脚本直接调 ``tool.save_cache(假数据)``，
    把用户辛苦拉到的**真实缓存覆盖**成了 ``角色1..角色43`` ——
    用户打开工具看到的就是假数据。

    所以这里的每个用例都::

        setUp    → 把缓存路径**改到临时目录**
        tearDown → 还原

    并且有一条测试专门钉住"路径能被替换"这件事。
    """

    def setUp(self):
        import tempfile

        from src.tools.game.character_build import tool as T

        self.T = T
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = T.cache_file
        T.cache_file = lambda: pathlib.Path(self._tmp.name) / "c.json"

    def tearDown(self):
        self.T.cache_file = self._orig
        self._tmp.cleanup()

    def test_save_and_load(self):
        self.T.save_cache({"at": "x", "base": {"energy": 1}})
        self.assertEqual(self.T.load_cache().get("base", {}).get("energy"), 1)

    def test_load_missing_returns_empty(self):
        self.assertEqual(self.T.load_cache(), {})

    def test_load_corrupt_returns_empty(self):
        p = self.T.cache_file()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{ 坏的", encoding="utf-8")
        self.assertEqual(self.T.load_cache(), {})

    def test_clear_removes_file(self):
        self.T.save_cache({"a": 1})
        self.assertTrue(self.T.cache_file().exists())
        self.T.clear_cache()
        self.assertFalse(self.T.cache_file().exists())

    def test_cache_path_is_redirectable(self):
        """★★ 钉住"缓存路径可替换" —— 否则上面那些用例会写用户的真文件。

        ⚠ 这个检查**必须在 setUp 之外**做一次（用真实路径对比），
        所以特意用模块级函数而不是 self。
        """
        from src.core import paths
        from src.tools.game.character_build import tool as T

        real = paths.user_data_dir() / "kuro_练度.json"
        #: setUp 里已把路径改到临时目录 → 两者必须不同
        self.assertNotEqual(
            self.T.cache_file(), real,
            "cache_file 没被替换 —— 测试会写用户真实的缓存文件！"
            "（2026-10-03 就是这样把用户的真数据覆盖成假数据的）")
        #: 但"真实位置"的推导必须是对的（不然测的是空气）
        self.assertEqual(real.name, "kuro_练度.json")
        self.assertEqual(T.CACHE_NAME, "kuro_练度.json")


class TestFetchThreadPartial(unittest.TestCase):
    """★★ 43 个角色 = 43 次请求，**要几十秒** —— 不能等全拉完才有画面。

    ## 用户的真实遭遇（2026-10-03）

    日志停在 `正在拉声骸详情（43 个角色）…` 之后没下文 ——
    **没跑完就被关掉了**，`succeeded` 从没发出 → **缓存从没写**
    → 下次打开还是"没数据"。

    所以现在：
      * 每 5 个角色 ``progress.emit`` 一次（看得到进度在动）
      * 同时 ``partial.emit`` 把**已有数据**交给界面
      * 中途被打断也**已经存了一部分**
    """

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def test_has_partial_signal(self):
        from src.tools.game.character_build.tool import FetchThread

        self.assertTrue(hasattr(FetchThread, "partial"),
                        "没有 partial 信号 —— 拉到一半界面看不到东西")

    def test_has_stop(self):
        from src.tools.game.character_build.tool import FetchThread

        self.assertTrue(hasattr(FetchThread, "stop"))

    def test_saves_progressively(self):
        """★ 中途就要落盘（不然被打断就白拉了）。

        ⚠⚠ **必须把令牌路径也挡到临时目录**：
        ``FetchThread`` 结尾会调 ``kuro_account.save_account(acc)`` ——
        第一版只挡了 ``cache_file``，结果假账号 ``token="t"`` /
        ``roles=[{'roleId': '1'}]`` 被**写进用户真实的令牌文件**，
        界面上特征码变成空、手机号也没了。
        """
        import tempfile
        import time

        from src.core import kuro_account as K
        from src.tools.game.character_build import tool as T

        tmp = tempfile.TemporaryDirectory()
        orig_file = T.cache_file
        orig_token = K.token_file          # ★ 令牌也要挡
        T.cache_file = lambda: pathlib.Path(tmp.name) / "c.json"
        K.token_file = lambda: pathlib.Path(tmp.name) / "acc.json"

        saved = {"n": 0}
        orig_save = T.save_cache

        def counting_save(payload):
            saved["n"] += 1
            orig_save(payload)

        #: 把网络调用换成假的
        origs = {}
        for name, val in (
            ("request_data_token", lambda *a, **k: ("DT", False)),
            ("fetch_base_data", lambda *a, **k: {"name": "x"}),
            ("fetch_role_data", lambda *a, **k: {
                "roleList": [{"roleId": i, "roleName": f"c{i}", "level": 90}
                             for i in range(1, 13)]}),
            ("fetch_role_detail", lambda *a, **k: {"phantomData": {}}),
        ):
            origs[name] = getattr(K, name)
            setattr(K, name, val)

        T.save_cache = counting_save
        try:
            acc = K.Account(token="t", roles=[{"roleId": "1", "serverId": "s",
                                               "roleName": "x", "gameId": 3}])
            th = T.FetchThread(acc, "")
            done = {"v": False}
            th.succeeded.connect(lambda _p: done.__setitem__("v", True))
            th.start()
            deadline = time.time() + 10
            while not done["v"] and time.time() < deadline:
                self.app.processEvents()
                time.sleep(0.02)
            self.assertTrue(done["v"], "线程没跑完")
            self.assertGreater(saved["n"], 1,
                               "只在最后存了一次 —— 中途被打断就白拉了")
        finally:
            T.save_cache = orig_save
            T.cache_file = orig_file
            K.token_file = orig_token          # ★ 还原令牌路径
            for name, val in origs.items():
                setattr(K, name, val)
            tmp.cleanup()


class TestNoTestWritesUserData(unittest.TestCase):
    """★★★ **测试绝不能写用户的真实数据**（令牌 / 缓存）。

    ## 2026-10-03 连续踩了两次

    1. 探索脚本 `save_cache(假数据)` → 把用户拉到的**真实缓存**覆盖成
       `角色1..角色43`
    2. `test_saves_progressively` 只挡了 `cache_file`，**没挡 `token_file`**
       → `FetchThread` 结尾的 `save_account(acc)` 把假账号
       （`token="t"`、`roles=[{'roleId': '1'}]`）**写进了真实令牌文件**
       → 用户界面上特征码变成空、手机号也没了

    ## 这条测试做什么

    把**真实路径**记下来，跑完整个模块后检查：那两个文件**不该被创建**。
    靠 `tearDownModule` 在模块结束时断言。
    """

    def test_real_paths_are_known(self):
        from src.core import paths
        from src.tools.game.character_build import tool as T

        self.assertEqual(T.cache_file.__module__,
                         "src.tools.game.character_build.tool")
        self.assertTrue(str(paths.user_data_dir()))


def tearDownModule() -> None:
    """★ 模块跑完检查：用户的真实令牌 / 缓存**没被测试碰过**。

    ⚠ 这个方法读的是**真实路径**，所以必须在所有测试（含它们的
    ``tearDown``）都跑完、路径被还原之后执行。
    """
    import logging

    logging.disable(logging.CRITICAL)
    try:
        from src.core import paths

        real_dir = paths.user_data_dir()
        for name in ("kuro_account.json", "kuro_练度.json"):
            path = real_dir / name
            if path.exists():
                #: 存在是正常的（用户自己的数据）—— 只警告"内容像测试数据"
                try:
                    text = path.read_text(encoding="utf-8")
                    if '"token": "t"' in text or '"roleId": "1"' in text:
                        logging.disable(logging.NOTSET)
                        raise AssertionError(
                            f"★ 用户真实文件 {path} 里出现了**测试数据**"
                            f"（token='t' / roleId='1'）—— "
                            f"某个测试没把路径挡到临时目录！")
                except UnicodeDecodeError:
                    pass
    finally:
        logging.disable(logging.NOTSET)


class TestIconCache(unittest.TestCase):
    """★ 图标缓存 —— 详情页要图文并茂就得先把接口给的 ``iconUrl`` 拿下来。"""

    def test_local_path_is_stable_and_unique(self):
        from src.core import icon_cache as IC

        u1 = "https://x/a/1.png"
        u2 = "https://x/a/2.png"
        self.assertEqual(IC.local_path(u1), IC.local_path(u1),
                         "同一个 URL 必须映射到同一路径")
        self.assertNotEqual(IC.local_path(u1), IC.local_path(u2),
                            "不同 URL 撞名了")

    def test_rejects_non_http(self):
        from src.core import icon_cache as IC

        self.assertIsNone(IC.ensure(""))
        self.assertIsNone(IC.ensure("not-a-url"))
        self.assertIsNone(IC.ensure("/local/path.png"),
                          "本地路径不该被当 URL 下载")

    def test_pixmap_missing_returns_null(self):
        from src.core import icon_cache as IC

        pix = IC.pixmap("https://example.invalid/nope.png", 16)
        self.assertTrue(pix.isNull(), "缓存里没有却返回了非空 pixmap")

    def test_collect_urls_from_detail(self):
        """★ 从详情里收集所有 ``iconUrl``（属性/技能/共鸣链/武器/声骸）。"""
        from src.core import icon_cache as IC

        detail = {
            "role": {"roleIconUrl": "https://x/role.png"},
            "roleAttributeList": [
                {"attributeName": "攻击", "iconUrl": "https://x/attr.png"}],
            "skillList": [
                {"skill": {"name": "a", "iconUrl": "https://x/skill.png"}}],
            "chainList": [{"name": "b", "iconUrl": "https://x/chain.png"}],
            "weaponData": {"weapon": {"weaponIcon": "https://x/w.png"}},
            "phantomData": {"equipPhantomList": [{
                "phantomProp": {"iconUrl": "https://x/echo.png"},
                "fetterDetail": {"iconUrl": "https://x/set.png"},
                "mainProps": [{"iconUrl": "https://x/m.png"}],
                "subProps": [{"iconUrl": "https://x/s.png"}],
            }]},
        }
        urls = IC.collect_urls(detail)
        for want in ("role", "attr", "skill", "chain", "w", "echo", "set",
                     "m", "s"):
            with self.subTest(want=want):
                self.assertTrue(any(u.endswith(f"/{want}.png") for u in urls),
                                f"漏了 {want}.png（收到 {urls}）")

    def test_collect_urls_handles_garbage(self):
        from src.core import icon_cache as IC

        self.assertEqual(IC.collect_urls(None), [])
        self.assertEqual(IC.collect_urls({}), [])
        self.assertEqual(IC.collect_urls({"skills": "不是列表"}), [])


class TestDetailView(unittest.TestCase):
    """★★ 详情页 —— **图文并茂**（用户给的官方参考图）。"""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    @staticmethod
    def _detail():
        return {
            "role": {"roleName": "白芷", "level": 90,
                     "attributeName": "冷凝", "weaponTypeName": "音感仪"},
            "roleAttributeList": [
                {"attributeName": "生命", "attributeValue": "27550",
                 "iconUrl": "https://x/1.png"}],
            "weaponData": {
                "level": 90, "resonLevel": 2,
                "weapon": {"weaponName": "奇幻变奏", "weaponStarLevel": 4,
                           "weaponIcon": "https://x/w.png"},
                "mainPropList": [{"attributeName": "攻击",
                                  "attributeValue": "337"}],
            },
            "equipPhantomAddPropList": [
                {"attributeName": "攻击", "attributeValue": "1071"}],
            "phantomData": {
                "cost": 12,
                "equipPhantomList": [{
                    "cost": 4, "level": 25,
                    "phantomProp": {"name": "无归的谬误",
                                    "iconUrl": "https://x/e.png"},
                    "fetterDetail": {"name": "隐世回光"},
                    "mainProps": [{"attributeName": "治疗效果加成",
                                   "attributeValue": "26.4%",
                                   "valid": True}],
                    "subProps": [
                        {"attributeName": "暴击伤害",
                         "attributeValue": "12.6%", "valid": True},
                        {"attributeName": "防御",
                         "attributeValue": "9.0%", "valid": False}],
                }],
            },
            "skillList": [{"level": 10, "skill": {
                "name": "应急预案", "iconUrl": "https://x/s.png"}}],
            "chainList": [{"name": "极简与繁复", "order": 1,
                           "unlocked": True, "description": "回复能量"}],
        }

    def _texts(self, view):
        from PySide6.QtWidgets import QLabel

        return [w.text() for w in view.findChildren(QLabel) if w.text()]

    def test_shows_all_sections(self):
        """★ 官方参考图里的每一块都要有。"""
        from src.tools.game.character_build.detail_view import EchoDetailView

        view = EchoDetailView()
        view.show_detail(self._detail())
        joined = " ".join(self._texts(view))
        for want in ("白芷", "共鸣者属性", "生命", "武器", "奇幻变奏",
                     "属性展示", "声骸", "推荐辅音词条命中",
                     "装配声骸详情", "无归的谬误", "技能", "共鸣链"):
            with self.subTest(want=want):
                self.assertIn(want, joined, f"详情页缺「{want}」")

    def test_hit_badge_counts_valid_substats(self):
        """★★ 命中大数字 = 标了 ``valid`` 的副词条总数（官方那个黄色数字）。"""
        from src.tools.game.character_build.detail_view import EchoDetailView

        view = EchoDetailView()
        view.show_detail(self._detail())
        texts = self._texts(view)
        self.assertIn("1", texts,
                      "命中数不对（这条数据里只有 1 条 valid）")

    def test_no_check_marks_and_hits_are_highlighted(self):
        """★★ 副词条：**不画 ✓/·**，命中的**整行黄底**。

        用户 2026-10-04（截图圈出那列勾）："（这是）什么？去掉，
        命中的词条黄色高亮就行"

        ⚠ 我原来在每行前面画了个 ``✓`` / ``·`` —— 用户看不懂也不需要，
        要的是**底色区分**（和官方一致）。
        """
        from PySide6.QtWidgets import QWidget

        from src.tools.game.character_build import detail_view as DV
        from src.tools.game.character_build.detail_view import EchoDetailView

        view = EchoDetailView()
        view.show_detail(self._detail())

        #: ★ 1. 不该再有 ✓ / · 标记
        marks = [t for t in self._texts(view) if t.strip() in ("✓", "·")]
        self.assertEqual(marks, [],
                         f"还有 ✓/· 标记 —— 用户要求去掉（找到 {marks}）")

        #: ★ 2. 命中行必须有黄底
        hit_rows = [w for w in view.findChildren(QWidget)
                    if DV.SUB_HIT_BG in (w.styleSheet() or "")]
        self.assertTrue(hit_rows, "命中的副词条没黄色高亮")

        #: ★ 3. 未命中的行**不能**用黄底（否则等于没区分）
        for w in view.findChildren(QWidget):
            css = w.styleSheet() or ""
            if DV.SUB_BG in css:
                self.assertNotIn(DV.SUB_HIT_BG, css)

    def test_each_section_is_its_own_card(self):
        """★★ 每一块都要是**独立卡片**（深色标题栏 + 内容区）。

        用户 2026-10-04（截图圈出「共鸣者属性」「武器」「属性展示」三个标题）：
        "这些都分别做成一个卡片，别放在一起，下面的也是"

        ⚠ 我原来只画了一个加粗小标题，所有区块直接堆在同一个白底上 ——
        视觉上糊成一片，用户要求**每块各自成卡片**。
        """
        from PySide6.QtWidgets import QLabel, QWidget

        from src.tools.game.character_build import detail_view as DV
        from src.tools.game.character_build.detail_view import EchoDetailView

        view = EchoDetailView()
        view.show_detail(self._detail())

        #: ★ 每个期望的区块都要有自己的**深色标题栏**
        heads = [w.text() for w in view.findChildren(QLabel)
                 if DV.SECTION_HEAD_BG in (w.styleSheet() or "")]
        for want in ("共鸣者属性", "武器", "属性展示", "声骸",
                     "推荐辅音词条命中", "装配声骸详情", "技能", "共鸣链"):
            with self.subTest(want=want):
                self.assertTrue(any(want in h for h in heads),
                                f"「{want}」没有独立卡片（找到 {heads}）")

        #: ★ 卡片容器本身要有边框 / 圆角
        cards = [w for w in view.findChildren(QWidget)
                 if DV.SECTION_BORDER in (w.styleSheet() or "")]
        self.assertGreaterEqual(len(cards), 8,
                                f"卡片数不对（{{len(cards)}} 个）—— "
                                f"区块又被堆在一起了")

    def test_section_header_is_dark(self):
        """★ 标题栏得是**深色**（官方那种），不是白底黑字。"""
        from src.tools.game.character_build import detail_view as DV

        def lum(hex_color: str) -> float:
            h = hex_color.lstrip("#")
            r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
            return (0.299 * r + 0.587 * g + 0.114 * b) / 255

        self.assertLess(lum(DV.SECTION_HEAD_BG), 0.5,
                        "标题栏不够深 —— 官方是深灰底白字")
        self.assertGreater(lum(DV.SECTION_HEAD_FG), 0.5,
                           "标题栏文字不够亮")
        self.assertGreater(lum(DV.SECTION_BG), 0.8,
                           "内容区不是浅色底")

    def test_main_props_are_not_highlighted(self):
        """★★ 声骸**主属性不铺黄底**。

        用户 2026-10-04（截图圈出主属性那两行）："主属性就不用高亮了"

        ⚠ 原来主属性也铺淡黄，和"命中的副词条"**撞色**，看不出哪个是哪个。
        现在只有命中的副词条才黄底。
        """
        from src.tools.game.character_build import detail_view as DV

        self.assertNotEqual(DV.MAIN_BG, DV.SUB_HIT_BG,
                            "主属性和命中副词条还是同一个颜色 —— 分不清")

    def test_no_empty_icon_boxes(self):
        """★★ 没图标的地方**不能留空方块**。

        用户 2026-10-04（截图圈出副词条前面那排空方块）："这个方框去掉"

        根因：**``subProps`` 没有 ``iconUrl`` 字段**（接口不给），
        而我原来不管有没有图都摆个 ``size×size`` 的空 QLabel。

        → 现在 ``_icon_label`` 没图返回 ``None``，调用方跳过。
        """
        from PySide6.QtWidgets import QLabel

        from src.tools.game.character_build import detail_view as DV
        from src.tools.game.character_build.detail_view import EchoDetailView

        view = EchoDetailView()
        view.show_detail(self._detail())

        #: ★ 数"正方形小图但 pixmap 为空"的控件 —— 那就是空方块
        boxes = [w.width() for w in view.findChildren(QLabel)
                 if w.pixmap() is not None and w.pixmap().isNull()
                 and w.width() == w.height() and 8 <= w.width() <= 80]
        #: 允许 1 个：命中大数字那个圆徽章（它不是图标）
        self.assertLessEqual(len(boxes), 1,
                             f"还有 {len(boxes)} 个空方块：{boxes}")

    def test_icon_label_returns_none_without_image(self):
        """★ ``_icon_label`` 没图必须返回 ``None``（不是空 QLabel）。

        ⚠ 判断"有没有图"**不能用** ``lab.size().isEmpty()`` ——
        刚建出来的 QLabel 尺寸是 ``(100, 30)``，永远不 empty（我踩过）。
        """
        from src.tools.game.character_build import detail_view as DV

        self.assertIsNone(DV._icon_label("", 16),
                          "空 URL 该返回 None")
        self.assertIsNone(
            DV._icon_label("https://example.invalid/nope.png", 16),
            "缓存里没有的图该返回 None")

    def test_substats_reuse_icons_by_name(self):
        """★★ 副词条没 ``iconUrl`` 时，按**属性名**复用主属性的同名图标。

        ⚠ 光测 ``_build_icon_index`` 本身不够 —— 把 ``_phantom_card``
        里的 ``fallback=`` 删掉，那种测试照样通过（实测突变时发现）。
        所以这里**也查渲染出来的结果**。

        ⚠ 但测试环境里那些假 URL 从没下载过 —— 光看"有没有图"会假失败。
        所以这里**造一个真的缓存文件**再断言。
        """
        import json
        import tempfile

        from PySide6.QtGui import QPixmap
        from PySide6.QtWidgets import QLabel

        from src.core import icon_cache as IC
        from src.tools.game.character_build.detail_view import (
            EchoDetailView,
            _build_icon_index,
        )

        #: 造一个 1x1 的真 PNG 到缓存里（用 Qt 生成，避免依赖 PIL）
        tmp = tempfile.TemporaryDirectory()
        orig_root = IC.icon_root
        IC.icon_root = lambda: pathlib.Path(tmp.name)
        try:
            url = "https://x/atk.png"
            path = IC.local_path(url)
            path.parent.mkdir(parents=True, exist_ok=True)
            pix = QPixmap(8, 8)
            pix.fill()
            self.assertTrue(pix.save(str(path)), "造测试图标失败")

            detail = {
                "role": {"roleName": "测试", "level": 90},
                #: ★ 故意**不给** roleAttributeList —— 那份也会渲染同名图标，
                #:   留着就分不清"图是副词条来的还是属性区来的"了
                #:   （第一版就是这么写的，突变时护栏失效）。
                "phantomData": {"cost": 12, "equipPhantomList": [{
                    "cost": 4, "level": 25,
                    "phantomProp": {"name": "声骸A"},
                    "fetterDetail": {"name": "套装A"},
                    #: ★ 主属性带图标 —— 这是副词条**唯一**能复用到的来源
                    "mainProps": [{"attributeName": "攻击",
                                   "attributeValue": "44%",
                                   "iconUrl": url}],
                    #: ★ 副词条**故意不带** iconUrl（接口真实行为）
                    "subProps": [{"attributeName": "攻击",
                                  "attributeValue": "10.1%",
                                  "valid": True}],
                }]},
            }
            idx = _build_icon_index(detail)
            self.assertEqual(idx.get("攻击"), url,
                             "索引没建对（属性名 → iconUrl）")

            view = EchoDetailView()
            view.show_detail(detail)
            #: 一张声骸卡：主属性 1 个图 + 副词条 1 个图 = 2
            #: 如果副词条没复用上，就只剩 1 个
            imgs = [w for w in view.findChildren(QLabel)
                    if w.pixmap() is not None and not w.pixmap().isNull()]
            self.assertGreaterEqual(
                len(imgs), 2,
                f"副词条那行没复用图标（只有 {len(imgs)} 个图）—— "
                f"说明 _phantom_card 没用 icon_index 兜底")
        finally:
            IC.icon_root = orig_root
            tmp.cleanup()

    def test_hit_rows_actually_differ_from_miss_rows(self):
        """★ 命中 / 未命中的底色必须是**两个不同的颜色**。"""
        from src.tools.game.character_build import detail_view as DV

        self.assertNotEqual(DV.SUB_HIT_BG, DV.SUB_BG,
                            "命中色和未命中色一样 —— 等于没高亮")

    def test_shows_issues(self):
        from src.tools.game.character_build.detail_view import EchoDetailView

        view = EchoDetailView()
        view.show_detail(self._detail(), ["套装不统一（2 种）"])
        self.assertIn("套装不统一", " ".join(self._texts(view)))

    def test_shows_all_chain_descriptions(self):
        """★★ **每条共鸣链**都能点开看说明。

        用户 2026-10-05："共鸣链数据能拿到吗" → 能。

        ⚠ 之后又要求（截图圈出标题列表）："删掉" ——
        那一串 `1 雨洗千山皆入画 未激活` 不要了，**只留图标**。
        所以这条测试改成查"每条都有一个可点图标"。
        """
        import tempfile

        from PySide6.QtGui import QPixmap
        from PySide6.QtWidgets import QLabel

        from src.core import icon_cache as IC
        from src.tools.game.character_build.detail_view import EchoDetailView

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        orig = IC.icon_root
        IC.icon_root = lambda: pathlib.Path(tmp.name)
        self.addCleanup(lambda: setattr(IC, "icon_root", orig))
        p = IC.local_path("https://x/c.png")
        p.parent.mkdir(parents=True, exist_ok=True)
        pix = QPixmap(8, 8)
        pix.fill()
        pix.save(str(p))

        detail = self._detail()
        detail["chainList"] = [
            {"order": i, "name": f"链{i}", "unlocked": i <= 3,
             "description": f"链{i}的说明文字",
             "iconUrl": "https://x/c.png"}
            for i in range(1, 7)
        ]
        view = EchoDetailView()
        view.show_detail(detail)

        #: ★ 每条链一个可点图标（标题列表已按用户要求删掉）
        clickable = [w for w in view.findChildren(QLabel)
                     if w.mousePressEvent.__name__ == "_toggle"
                     and w.property("expandKey")]
        self.assertGreaterEqual(len(clickable), 6,
                                f"可点的链只有 {len(clickable)} 条")

    def test_marks_locked_chains(self):
        """★ 未解锁的共鸣链要能看出来（**压暗**，不是黄底）。

        ⚠ 原来查的是文字"未激活" —— 用户后来把那一列标题**删掉了**
        （截图圈出那一列：「删掉」），改成看**图标的压暗样式**。
        """
        import tempfile

        from PySide6.QtGui import QPixmap
        from PySide6.QtWidgets import QLabel, QWidget

        from src.core import icon_cache as IC
        from src.tools.game.character_build import detail_view as DV
        from src.tools.game.character_build.detail_view import EchoDetailView

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        orig = IC.icon_root
        IC.icon_root = lambda: pathlib.Path(tmp.name)
        self.addCleanup(lambda: setattr(IC, "icon_root", orig))
        p = IC.local_path("https://x/c.png")
        p.parent.mkdir(parents=True, exist_ok=True)
        pix = QPixmap(8, 8)
        pix.fill()
        pix.save(str(p))

        detail = self._detail()
        detail["chainList"] = [
            {"order": 1, "name": "甲", "unlocked": True,
             "description": "开了", "iconUrl": "https://x/c.png"},
            {"order": 2, "name": "乙", "unlocked": False,
             "description": "没开", "iconUrl": "https://x/c.png"},
        ]
        view = EchoDetailView()
        view.show_detail(detail)

        #: 未解锁的那个图标被压暗
        dimmed = [w for w in view.findChildren(QLabel)
                  if "opacity" in (w.styleSheet() or "")]
        self.assertTrue(dimmed, "未解锁的链条目没压暗")

        #: 已解锁的**黄底**，未解锁的**没有**
        cells = [w for w in view.findChildren(QWidget)
                 if w.objectName() == "chainCell"]
        self.assertEqual(len(cells), 2, f"链条目数不对（{len(cells)}）")
        yellow = [c for c in cells if DV.SELECT_BG in (c.styleSheet() or "")]
        self.assertEqual(len(yellow), 1,
                         "黄底应该只有已激活那一个")

    def test_chain_names_available_via_click(self):
        """★ 标题删了，但点图标仍能看到是哪条（面板标题里有名字）。"""
        import tempfile

        from PySide6.QtGui import QPixmap
        from PySide6.QtWidgets import QLabel, QWidget

        from src.core import icon_cache as IC
        from src.tools.game.character_build.detail_view import EchoDetailView

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        orig = IC.icon_root
        IC.icon_root = lambda: pathlib.Path(tmp.name)
        self.addCleanup(lambda: setattr(IC, "icon_root", orig))
        p = IC.local_path("https://x/c.png")
        p.parent.mkdir(parents=True, exist_ok=True)
        pix = QPixmap(8, 8)
        pix.fill()
        pix.save(str(p))

        detail = self._detail()
        detail["chainList"] = [
            {"order": 3, "name": "链名丙", "unlocked": True,
             "description": "丙说明", "iconUrl": "https://x/c.png"},
        ]
        view = EchoDetailView()
        view.show_detail(detail)
        clickable = [w for w in view.findChildren(QLabel)
                     if w.mousePressEvent.__name__ == "_toggle"
                     and w.property("expandKey")]
        self.assertTrue(clickable, "共鸣链图标不可点")
        clickable[0].mousePressEvent(None)
        panels = [w for w in view.findChildren(QWidget)
                  if w.objectName() == "expandPanel"]
        texts = [t.text() for w in panels
                 for t in w.findChildren(QLabel) if t.text()]
        self.assertTrue(any("链名丙" in t for t in texts),
                        f"点开后看不到是哪条链（{texts}）")

    def test_unlocked_chains_are_yellow(self):
        """★★ 已激活的共鸣链图标 → **黄底高亮**。

        用户 2026-10-05（截图圈出共鸣链图标行）："已激活这里黄色高亮"

        ⚠ 我原来只是"未解锁的灰掉" —— 在深色底上差别不明显，
        用户要求把**已激活的**点亮。
        """
        import tempfile

        from PySide6.QtGui import QPixmap
        from PySide6.QtWidgets import QWidget

        from src.core import icon_cache as IC
        from src.tools.game.character_build import detail_view as DV
        from src.tools.game.character_build.detail_view import EchoDetailView

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        orig = IC.icon_root
        IC.icon_root = lambda: pathlib.Path(tmp.name)
        self.addCleanup(lambda: setattr(IC, "icon_root", orig))
        p = IC.local_path("https://x/c.png")
        p.parent.mkdir(parents=True, exist_ok=True)
        pix = QPixmap(8, 8)
        pix.fill()
        pix.save(str(p))

        detail = self._detail()
        detail["chainList"] = [
            {"order": 1, "name": "开着的", "unlocked": True,
             "description": "甲", "iconUrl": "https://x/c.png"},
            {"order": 2, "name": "锁着的", "unlocked": False,
             "description": "乙", "iconUrl": "https://x/c.png"},
        ]
        view = EchoDetailView()
        view.show_detail(detail)

        cells = [w for w in view.findChildren(QWidget)
                 if w.objectName() == "chainCell"]
        self.assertEqual(len(cells), 2, f"共鸣链格子数不对（{len(cells)}）")
        yellow = [c for c in cells if DV.SELECT_BG in (c.styleSheet() or "")]
        self.assertEqual(len(yellow), 1,
                         f"黄底格子应该正好 1 个（已激活那个），"
                         f"实际 {len(yellow)}")

    def test_no_chain_title_list(self):
        """★★ 共鸣链**不再列那一串标题**。

        用户 2026-10-05（截图圈出 `1 雨洗千山皆入画 未激活` 那一列）：
        "删掉"

        → 图标本身就是"哪条"的表示，文字多余；说明点开看。
        """
        from src.tools.game.character_build.detail_view import EchoDetailView

        detail = self._detail()
        detail["chainList"] = [
            {"order": 1, "name": "链名甲", "unlocked": True,
             "description": "甲说明", "iconUrl": ""},
            {"order": 2, "name": "链名乙", "unlocked": False,
             "description": "乙说明", "iconUrl": ""},
        ]
        view = EchoDetailView()
        view.show_detail(detail)
        texts = self._texts(view)
        for want in ("链名甲", "链名乙", "未激活"):
            with self.subTest(want=want):
                self.assertFalse(any(want in t for t in texts),
                                 f"共鸣链标题列表还在（{want}）")

    def test_skill_descriptions_available(self):
        """★★ 技能的文字说明**能展开看到**。

        用户 2026-10-05::

            "技能详情…能拿到吗"                          ← 能
            "点击的时候，往下展开说明，不是弹出说明"        ← 交互

        ⚠ 这条原来是查 tooltip 的 —— 后来改成**就地展开**
        （见 :class:`TestInlineExpand`），所以改成查展开区里有没有说明。
        """
        import tempfile

        from PySide6.QtGui import QPixmap
        from PySide6.QtWidgets import QLabel, QWidget

        from src.core import icon_cache as IC
        from src.tools.game.character_build.detail_view import EchoDetailView

        tmp = tempfile.TemporaryDirectory()
        orig_root = IC.icon_root
        IC.icon_root = lambda: pathlib.Path(tmp.name)
        try:
            url = "https://x/skill.png"
            path = IC.local_path(url)
            path.parent.mkdir(parents=True, exist_ok=True)
            pix = QPixmap(8, 8)
            pix.fill()
            self.assertTrue(pix.save(str(path)), "造测试图标失败")

            detail = self._detail()
            detail["skillList"] = [{
                "level": 10,
                "skill": {"name": "应急预案", "type": "共鸣技能",
                          "description": "呼唤忧昙攻击目标，造成冷凝伤害。",
                          "iconUrl": url},
            }]
            view = EchoDetailView()
            view.show_detail(detail)

            #: 说明文字在共用面板里（初始隐藏，但点开就有）
            areas = [w for w in view.findChildren(QWidget)
                     if w.objectName() == "expandPanel"]
            self.assertTrue(areas, "技能没有共用说明面板")
            texts = [t.text() for a in areas
                     for t in a.findChildren(QLabel) if t.text()]
            #: ⚠ 说明**点了才写进面板** —— 所以这里先点一下
            clickable = [w for w in view.findChildren(QLabel)
                         if w.mousePressEvent.__name__ == "_toggle"
                         and w.property("expandKey")]
            self.assertTrue(clickable, "技能没有可点控件")
            clickable[0].mousePressEvent(None)
            texts = [t.text() for a in areas
                     for t in a.findChildren(QLabel) if t.text()]
            self.assertTrue(any("呼唤忧昙" in t for t in texts),
                            f"技能说明没写进面板（{texts[:4]}）")
        finally:
            IC.icon_root = orig_root
            tmp.cleanup()

    def test_clear_resets(self):
        from src.tools.game.character_build.detail_view import EchoDetailView

        view = EchoDetailView()
        view.show_detail(self._detail())
        view.clear()
        self.assertNotIn("白芷", " ".join(self._texts(view)))

    def test_handles_empty_detail(self):
        """★ 空数据不该崩。"""
        from src.tools.game.character_build.detail_view import EchoDetailView

        view = EchoDetailView()
        view.show_detail({})
        view.show_detail({"role": {}, "phantomData": {}})


class TestToolIcon(unittest.TestCase):
    """★ 工具图标要和另外 5 个**同一套风格**。

    用户："这个图标不能设计跟前面的风格一样吗"

    现有 5 个都是 ``assets/icons/*.png``（512x512、深色圆角底 + 金边 +
    发光紫线条），我这个原来没有 ``icon_path``，所以显示成灰色 FluentIcon。
    """

    def test_has_icon_path(self):
        from src.core import registry
        from src.tools import discover_tools

        discover_tools()
        meta = next((m for m in registry.ToolRegistry.all_metas()
                     if m.key == "character_build"), None)
        self.assertIsNotNone(meta)
        self.assertTrue(meta.icon_path, "没有 icon_path —— 会显示成灰色图标")

    def test_icon_file_exists_and_is_square(self):
        import pathlib as _p

        from src.core import paths

        path = paths.resource_dir("assets", "icons", "character_build.png")
        self.assertTrue(_p.Path(path).is_file(), f"图标文件不在：{path}")

    def test_all_game_tools_have_icons(self):
        """★ 同一分类下的工具**都要有**自定义图标（风格统一）。"""
        import pathlib as _p

        from src.core import registry
        from src.tools import discover_tools

        discover_tools()
        missing = [m.name for m in registry.ToolRegistry.all_metas()
                   if not (m.icon_path and _p.Path(m.icon_path).is_file())]
        self.assertEqual(missing, [],
                         f"这些工具没有自定义图标（风格会不统一）：{missing}")


class TestNoStyleCascade(unittest.TestCase):
    """★★★ **带 border/background 的样式必须写选择器**。

    ## 用户报的问题（2026-10-04）

    用户（截图圈出技能 / 共鸣链那一排**空方框**）：
    "这个怎么是空白，能拿到数据吗，不能的话就干掉吧"

    ## 根因不是数据，是 **Qt 样式级联**

    数据是好的 —— 图标全在缓存里、``pixmap`` 也不空（实测 77 个）。

    但 Qt 的样式表**不写选择器**时会套到**所有子控件**上::

        card.setStyleSheet("background: white; border: 1px solid ...")
        #                              ↑ 没有 #objectName / QClassName

    于是每个图标 QLabel 都被画上"白底 + 1px 边框 + 圆角"，
    看着就是一排空方框（pixmap 其实在底下，被盖住了）。

    写成 ``#sectionCard { ... }`` 就只作用于那个控件本身。

    ## 这条测试做什么

    **静态扫描**源码里所有 ``setStyleSheet(...)`` ——
    凡是含 ``border`` / ``background`` 又**不带选择器**的，直接失败。
    """

    def test_no_unscoped_border_or_background(self):
        import re

        src = (ROOT / "src" / "tools" / "game" / "character_build"
               / "detail_view.py").read_text(encoding="utf-8")
        offenders: list[tuple[int, str]] = []

        for m in re.finditer(r"setStyleSheet\(\s*", src):
            #: 取这次调用的第一个字符串字面量（够用了 —— 都是 f-string 开头）
            tail = src[m.end():m.end() + 200]
            lit = re.match(r'f?["\']([^"\']*)', tail)
            if not lit:
                continue
            css = lit.group(1)
            if "border" not in css and "background" not in css:
                continue
            #: 带选择器 = 以 # / . / 类名 开头，或者紧跟着 {
            head = css.strip()
            scoped = (head.startswith(("#", "."))
                      or re.match(r"^[A-Za-z]\w*\s*\{", head))
            if not scoped:
                line = src[:m.start()].count("\n") + 1
                offenders.append((line, css[:60]))

        self.assertEqual(
            offenders, [],
            "这些 setStyleSheet 含 border/background 但**没写选择器** —— "
            f"会级联到所有子控件（图标会被涂成空方框）：{offenders}")

    def test_section_card_is_scoped(self):
        """★ 实锤一次：``_section`` 建出来的卡片样式必须带选择器。"""
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])  # noqa: F841

        from src.tools.game.character_build.detail_view import _section

        card, _box = _section("测试")
        css = card.styleSheet()
        self.assertIn("#", css,
                      f"卡片样式没写选择器（{css[:60]}）—— 会级联到图标上")
        self.assertIn("{", css, "没有 {{ }} 包裹，选择器不生效")


class TestTextIsAlwaysColored(unittest.TestCase):
    """★★★ 详情页里**每个带文字的标签都要显式给 ``color``**。

    ## ⚠⚠ 用户 2026-10-06 连报两次

        "这里又出现了深色皮肤 深色字体 看不见"
        "这里字压根看不见" / "这里也是很丑"

    根因反复是同一类：``setStyleSheet`` 里**没写 ``color``** ——
    于是文字继承到一个在深色玻璃底上几乎看不见的色。

    还有个更隐蔽的写法错误::

        color: inherit      ← **QSS 不支持 `inherit`**！
                              会被当成无效值**整条丢掉**，
                              结果和"没写"一样

    ## 这条测试做什么

    **静态扫描**（跟 :class:`TestNoStyleCascade` 一个套路）——
    别只修用户报的那两处，把同类一次找齐。
    """

    @staticmethod
    def _literals(src: str):
        """把每次 ``setStyleSheet(...)`` 的**拼接字面量**拼起来。

        ⚠⚠ 窗口要**开够大**（护栏验证时发现的问题）::

            原来只取 ``tail[:180]`` —— 多行 f-string 的**后半截**
            （正是 ``color: {dim_color()};`` 那一段）落在窗口外，
            于是"写死 #888"的突变**扫不到**，护栏失效。

        → 取到**这一条语句结束**为止（遇到下一个 ``setStyleSheet`` 或
        超过 1200 字符就停）。
        """
        import re

        for m in re.finditer(r"setStyleSheet\(\s*", src):
            #: 到下一次 setStyleSheet 为止（或 1200 字符封顶）
            nxt = src.find("setStyleSheet(", m.end())
            end = min(nxt if nxt > 0 else len(src), m.end() + 1200)
            tail = src[m.end():end]
            lits = re.findall(r'f?["\']([^"\']*)["\']', tail)
            if not lits:
                continue
            yield src[:m.start()].count("\n") + 1, " ".join(lits)

    def test_no_font_size_without_color(self):
        """★★★ 设了字号却**没设颜色** = 深色皮肤上会隐形。"""
        src = (ROOT / "src" / "tools" / "game" / "character_build"
               / "detail_view.py").read_text(encoding="utf-8")
        bad: list[tuple[int, str]] = []
        for line, css in self._literals(src):
            if "font-size" in css and "color" not in css:
                bad.append((line, css[:70]))
        self.assertEqual(
            bad, [],
            "这些 setStyleSheet 设了 font-size 却没设 color —— "
            f"深色皮肤上文字会隐形：{bad}")

    def test_no_css_inherit_keyword(self):
        """★★★ **QSS 不支持 ``inherit``** —— 写了等于没写。

        ⚠ 这是最容易骗过眼睛的写法：看着"我明明设了颜色"，
        实际 Qt 把整条规则丢掉，颜色还是继承来的那个。
        """
        src = (ROOT / "src" / "tools" / "game" / "character_build"
               / "detail_view.py").read_text(encoding="utf-8")
        bad: list[tuple[int, str]] = []
        for line, css in self._literals(src):
            if "inherit" in css:
                bad.append((line, css[:70]))
        self.assertEqual(
            bad, [],
            f"这些样式用了 QSS 不支持的 `inherit`（会被丢掉）：{bad}")

    def test_no_hardcoded_dark_gray_text(self):
        """★★★ 文字色**不许写死中性灰**（``#666`` / ``#888`` 这类）。

        ⚠ 它们在浅色底上还行，**深色皮肤上就读不清了** ——
        用户 2026-10-06 报的"这里字压根看不见"就是这个。

        ## ⚠⚠ 阈值取多少（护栏验证时调过）

        第一版我取 ``lum < 110`` —— **抓不住 ``#888``**（它的亮度是
        **136**）。而用户看到的正是 ``#888`` 那种太淡的字::

            #666 → lum 102
            #888 → lum 136   ← 第一版漏了它

        → 阈值提到 **200**：中性灰只要不是**接近白**的，一律要求走皮肤色。

        ⚠ 只查**中性灰**（三通道接近）—— 有彩色的色（比如官方那种
        金棕 ``#8a6d1a``、达标绿、未达标红）是**有意的设计色**，不在此列。
        """
        import re

        src = (ROOT / "src" / "tools" / "game" / "character_build"
               / "detail_view.py").read_text(encoding="utf-8")
        bad: list[tuple[int, str]] = []
        for line, css in self._literals(src):
            for m in re.finditer(r"color:\s*(#[0-9a-fA-F]{3,6})\b", css):
                hexv = m.group(1).lstrip("#")
                if len(hexv) == 3:
                    hexv = "".join(c * 2 for c in hexv)
                if len(hexv) != 6:
                    continue
                r, g, b = (int(hexv[i:i + 2], 16) for i in (0, 2, 4))
                lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
                is_gray = max(r, g, b) - min(r, g, b) < 24
                #: 中性灰 且 不够亮 → 深色皮肤上会糊
                if is_gray and lum < 200:
                    bad.append((line, css[:70]))
                    break
        self.assertEqual(
            bad, [],
            f"这些文字色写死了中性灰 —— 深色皮肤上读不清：{bad}")

    def test_helpers_read_from_skin(self):
        """★★ ``text_color()`` / ``dim_color()`` 要真的从皮肤取色。"""
        from src.core import skins
        from src.tools.game.character_build import detail_view as dv

        skins.apply_skin("deepglass", save=False)
        self.assertEqual(dv.text_color(), skins.active_skin()["text"])
        self.assertEqual(dv.dim_color(), skins.active_skin()["dim"])

        #: ★ 浅色皮肤下也得对（别只对一个皮肤正确）
        skins.apply_skin("mist", save=False)
        self.assertEqual(dv.text_color(), skins.active_skin()["text"])
        self.assertNotEqual(dv.text_color(), dv.dim_color())


class TestScrollbarIsStyled(unittest.TestCase):
    """★★★ 滚动条**不许是原生外观**（用户 2026-10-06："这个滑轮组件很丑"）。

    ## ⚠⚠ 这里踩过一个语法坑

    我第一版写成::

        QScrollBar::vertical::handle { ... }     ← **错**！Qt 不认
        QScrollBar::handle:vertical { ... }      ← 对

    Qt 的语法是 ``::子控件:方向``，**方向伪状态要放在子控件后面**。
    写反了整条规则被丢掉 —— 界面上还是那个原生滚动条（一条都没生效）。
    """

    def test_qss_has_scrollbar_rules(self):
        from src.core import skins

        qss = skins.build_qss(skins.skin_by_id("deepglass"))
        for sel in ("QScrollBar:vertical", "QScrollBar::handle:vertical",
                    "QScrollBar::handle:horizontal",
                    "QScrollBar::add-line:vertical",
                    "QScrollBar::sub-line:horizontal",
                    "QScrollBar::corner"):
            self.assertIn(sel, qss, f"滚动条 QSS 少了 {sel}")

    def test_no_reversed_selector_order(self):
        """★★★ 选择器**方向不能写反**（我犯过的错）。"""
        from src.core import skins

        qss = skins.build_qss(skins.skin_by_id("deepglass"))
        self.assertNotIn(
            "QScrollBar::vertical::", qss,
            "用了 `QScrollBar::vertical::xxx` —— Qt 不认，整条规则会被丢掉")
        self.assertNotIn("QScrollBar::horizontal::", qss,
                         "用了 `QScrollBar::horizontal::xxx` —— Qt 不认")

    def test_arrows_are_removed(self):
        """★ 两端的箭头按钮要去掉（原生那个最丑的部分）。"""
        from src.core import skins

        qss = skins.build_qss(skins.skin_by_id("darkglass")
                              if skins.skin_by_id("darkglass")
                              else skins.skin_by_id("deepglass"))
        self.assertIn("add-line", qss)
        #: 宽度设 0 才是"去掉"的标准做法（display:none 有时不生效）
        self.assertRegex(qss, r"add-line:vertical[^}]*width:\s*0",
                         "箭头按钮没设成 0 宽 —— 还会显示")

    def test_scrollbar_follows_skin(self):
        """★★★ 滑块颜色**跟着皮肤走**（别又写死）。

        ## ⚠⚠ 断言必须**只看滚动条那一段**（护栏验证时改的）

        第一版我写的是 ``assertIn(skin['border'], qss)`` —— **太宽**：
        ``skin['border']`` 在 ``CardWidget`` 那行也出现，所以把滑块
        写死成 ``#cccccc`` 之后**照样通过**（护栏失效）。

        → 把 QSS 里 ``QScrollBar`` 之后那段**单独抠出来**再断言。
        """
        from src.core import skins

        for sid in ("mist", "deepglass"):
            with self.subTest(skin=sid):
                skin = skins.skin_by_id(sid)
                qss = skins.build_qss(skin)
                #: 只取滚动条那一段
                idx = qss.find("QScrollBar")
                self.assertGreater(idx, 0, "QSS 里没有滚动条规则")
                seg = qss[idx:]
                border = skin.get("border") or ""
                if border:
                    self.assertIn(border, seg,
                                  f"「{skin['name']}」的滑块没用皮肤边框色"
                                  f"（滚动条段：{seg[:80]}）")

    def test_scrollbar_is_thinner_than_default(self):
        """★ 宽度要**比原生细**（原生约 15px，太粗）。"""
        import re

        from src.core import skins

        qss = skins.build_qss(skins.skin_by_id("deepglass"))
        m = re.search(r"QScrollBar:vertical\s*\{[^}]*width:\s*(\d+)px", qss)
        self.assertIsNotNone(m, "没设纵向滚动条宽度")
        self.assertLess(int(m.group(1)), 12,
                        f"滚动条 {m.group(1)}px 太粗（原生约 15px）")


class TestExcludedRoles(unittest.TestCase):
    """★★ **漂泊者（主角）彻底不显示**。

    用户 2026-10-05："把漂泊者除开"

    我问过"要哪种显示方式"，用户明确选了
    「**彻底不显示（从列表里删掉）**」—— 所以是**整个从列表里过滤掉**：
    卡片、详情、计数都不算他。

    ⚠ 我第一版做成了"还在列表里、只是不参与达标判定" ——
    用户截图回来说"漂泊者还是有"，那不是他要的。
    **所以这条测试要同时钉住"列表里没有"和"计数不算他"。**

    为什么排除他：主角**必练**（主线一直带着），不像别的角色那样
    "要不要练"需要判断；而且他那套声骸往往是最早配的。
    """

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def _panel(self):
        from src.tools.game.character_build.tool import CharacterBuildPanel

        return CharacterBuildPanel()

    @staticmethod
    def _bad_echo_detail(name: str) -> dict:
        """一份"声骸很差"的详情（普通人拿它必被判未达标）。"""
        return {
            "role": {"roleName": name, "level": 90},
            "phantomData": {"equipPhantomList": [
                {"cost": 4, "level": 1,
                 "fetterDetail": {"name": "A"},
                 "phantomProp": {"name": "x"},
                 "mainProps": [], "subProps": []}]},
        }

    def test_is_excluded_matches_name(self):
        from src.tools.game.character_build import tool as T

        self.assertTrue(T.is_excluded({"roleName": "漂泊者"}))
        self.assertFalse(T.is_excluded({"roleName": "白芷"}))
        self.assertFalse(T.is_excluded({}))
        self.assertFalse(T.is_excluded(None))

    def test_excluded_constant(self):
        """★ 按**名字**排除（不是 roleId）。

        主角以后可能出别的属性版本 → roleId 会变、名字不会。
        """
        from src.tools.game.character_build import tool as T

        self.assertIn("漂泊者", T.EXCLUDED_ROLE_NAMES)

    def test_visible_roles_filters_rover(self):
        from src.tools.game.character_build import tool as T

        got = T.visible_roles([
            {"roleId": 1310, "roleName": "漂泊者"},
            {"roleId": 1103, "roleName": "白芷"},
        ])
        self.assertEqual([r["roleName"] for r in got], ["白芷"])

    def test_rover_not_in_list_at_all(self):
        """★★ **列表里根本没有漂泊者**（用户要的就是这个）。"""
        p = self._panel()
        p._data = {
            "roleList": [
                {"roleId": 1310, "roleName": "漂泊者", "level": 90},
                {"roleId": 1103, "roleName": "白芷", "level": 90},
            ],
            "details": {"1310": self._bad_echo_detail("漂泊者"),
                        "1103": self._bad_echo_detail("白芷")},
        }
        p._selected = "1103"
        p._render(p._data)

        ids = [c._cid for c in p._cards]
        self.assertNotIn("1310", ids, "漂泊者还在列表里 —— 用户要删掉它")
        self.assertIn("1103", ids, "白芷该在")

    def test_rover_not_counted_in_stats(self):
        """★★ 计数也**不算**漂泊者（"共 N 个" / "待优化 N 个"）。"""
        p = self._panel()
        p._data = {
            "roleList": [
                {"roleId": 1310, "roleName": "漂泊者", "level": 90},
                {"roleId": 1103, "roleName": "白芷", "level": 90},
            ],
            "details": {"1310": self._bad_echo_detail("漂泊者"),
                        "1103": self._bad_echo_detail("白芷")},
        }
        p._selected = "1103"
        p._render(p._data)
        hint = p._roles_hint.text()
        #: 两个角色、都"声骸很差" —— 但只该算白芷一个
        self.assertIn("共 1 个", hint,
                      f"总数把漂泊者算进去了（{hint}）")
        self.assertIn("待优化 1 个", hint,
                      f"待优化数把漂泊者算进去了（{hint}）")

    def test_rover_not_default_selected(self):
        """★ 默认选中的不能是漂泊者（他被滤掉了）。"""
        p = self._panel()
        p._data = {
            "roleList": [
                {"roleId": 1103, "roleName": "白芷", "level": 90},
                {"roleId": 1310, "roleName": "漂泊者", "level": 90},
            ],
            "details": {"1103": self._bad_echo_detail("白芷"),
                        "1310": self._bad_echo_detail("漂泊者")},
        }
        p._selected = ""
        p._render(p._data)
        #: 倒序后漂泊者排第一，但他被滤掉了 → 该选白芷
        self.assertEqual(p._selected, "1103",
                         "默认选中了漂泊者 —— 应该选滤掉他之后的第一个")

    def test_rover_not_in_unmet_filter(self):
        """★ 「未达标」筛选里不该出现漂泊者。"""
        p = self._panel()
        p._data = {
            "roleList": [
                {"roleId": 1310, "roleName": "漂泊者", "level": 90},
                {"roleId": 1103, "roleName": "白芷", "level": 90},
            ],
            "details": {"1310": self._bad_echo_detail("漂泊者"),
                        "1103": self._bad_echo_detail("白芷")},
        }
        p._selected = "1103"
        p._filter_box.setCurrentText("未达标")
        p._render(p._data)
        self.assertEqual([c._cid for c in p._cards], ["1103"])


class TestStandardComparison(unittest.TestCase):
    """★★★ 用**官方推荐属性**判达标（用户 2026-10-05 给出的标准）。

    用户给了官方攻略站的截图和链接::

        属性        当前数值    推荐数值
        暴击        78.4%       ≥70.0%  ✓
        暴击伤害    281.0%      ≥260.0% ✓
        共鸣效率    128.4%      ≥120.0% ✓

    数据来源 :mod:`src.core.wuwa_guide`（每个角色的标准都不同）::

        白芷      共鸣效率 ≥260.0% / 治疗效果加成 ≥40.0% / 生命 ≥24000
        今汐      暴击 ≥70.0% / 暴击伤害 ≥275.0% / 共鸣技能伤害加成 ≥20.0%
        安可      暴击 >65.0% / 暴击伤害 >250.0%     ← 注意是严格大于

    ⚠ 这条测试替代了原来"有效词条 < 10"那条**瞎定的**规则。
    """

    @staticmethod
    def _detail_with_attrs(attrs: dict) -> dict:
        """造一份带 ``roleAttributeList`` 的详情（够跑判定）。

        ⚠ ``equipPhantomList`` **不能是空的** —— 空了会先短路成
        "没拿到声骸数据"，属性那段就轮不到跑（第一版就栽在这）。
        这里给一套**结构完美**的声骸（满级 / 同套装 / COST 4-3-3-1-1），
        这样判定里只有"属性达标"这一项会出结果。
        """
        def item(cost):
            return {
                "cost": cost, "level": 25, "quality": 5,
                "phantomProp": {"name": "声骸"},
                "fetterDetail": {"name": "套装"},
                "mainProps": [{"attributeName": "攻击",
                               "attributeValue": "1%", "valid": True}],
                "subProps": [{"attributeName": "x",
                              "attributeValue": "1%", "valid": True}],
            }

        return {
            "role": {"roleName": "测试", "level": 90},
            "roleAttributeList": [
                {"attributeName": k, "attributeValue": v}
                for k, v in attrs.items()
            ],
            "phantomData": {"cost": 12,
                            "equipPhantomList": [item(c)
                                                 for c in (4, 3, 3, 1, 1)]},
        }

    @staticmethod
    def _standard(pairs) -> dict:
        return {"attrs": [
            {"name": n, "recommend": f"{v}%", "value": v, "unit": "%",
             "symbol": sym, "operation": 6}
            for n, sym, v in pairs
        ]}

    def _issues(self, attrs, pairs):
        from src.tools.game.character_build.tool import CharacterBuildPanel

        return CharacterBuildPanel._echo_issues(
            self._detail_with_attrs(attrs), self._standard(pairs))

    def test_meets_standard_no_issue(self):
        got = self._issues({"暴击": "78.4%", "暴击伤害": "281.0%"},
                           [("暴击", "≥", 70.0), ("暴击伤害", "≥", 260.0)])
        self.assertEqual(got, [])

    def test_below_standard_is_reported(self):
        got = self._issues({"暴击": "55.0%"}, [("暴击", "≥", 70.0)])
        self.assertTrue(any("暴击" in x and "70" in x for x in got),
                        f"没报出暴击不达标（{got}）")

    def test_strict_greater_than(self):
        """★★ 安可那条是 ``>65%`` —— **等于不算过**。

        ⚠ 这就是我第一版猜错枚举值的地方（把 ``4`` 当成 ``<=``）。
        """
        #: 正好 65 → > 不满足
        got = self._issues({"暴击": "65.0%"}, [("暴击", ">", 65.0)])
        self.assertTrue(any("暴击" in x for x in got),
                        "正好等于不该算过（> 是严格大于）")
        #: 65.1 → 过
        got2 = self._issues({"暴击": "65.1%"}, [("暴击", ">", 65.0)])
        self.assertEqual(got2, [])

    def test_absolute_value_standard(self):
        """★ 绝对值属性（生命/攻击）也能比。"""
        got = self._issues({"生命": "22166"}, [("生命", "≥", 24000.0)])
        self.assertTrue(any("生命" in x for x in got))
        got2 = self._issues({"生命": "24000"}, [("生命", "≥", 24000.0)])
        self.assertEqual(got2, [])

    def test_skips_attributes_not_on_panel(self):
        """★ 面板里没有的属性**跳过**（不瞎报）。"""
        got = self._issues({"暴击": "80.0%"},
                           [("暴击", "≥", 70.0), ("重击伤害加成", "≥", 20.0)])
        self.assertEqual(got, [], "面板里没有的属性不该被报成不达标")

    def test_no_standard_is_fine(self):
        """★ 没拿到标准（官方没出攻略）→ 不报属性问题。"""
        from src.tools.game.character_build.tool import CharacterBuildPanel

        detail = self._detail_with_attrs({"暴击": "10.0%"})
        for std in (None, {}, {"attrs": []}):
            with self.subTest(std=std):
                self.assertEqual(
                    CharacterBuildPanel._echo_issues(detail, std), [])

    def test_no_attrs_is_fine(self):
        """★ 面板里一个属性都没有 → 不报属性问题（但结构性检查照跑）。"""
        from src.tools.game.character_build.tool import CharacterBuildPanel

        detail = self._detail_with_attrs({})
        got = CharacterBuildPanel._echo_issues(
            detail, self._standard([("暴击", "≥", 70.0)]))
        self.assertEqual([x for x in got if "暴击" in x], [],
                         "没有属性面板数据时不该报属性不达标")

    def test_attr_map_parses_percent_and_plain(self):
        from src.tools.game.character_build import tool as T

        got = T._attr_map(self._detail_with_attrs(
            {"暴击": "78.4%", "生命": "15465", "坏的": "abc"}))
        self.assertEqual(got.get("暴击"), 78.4)
        self.assertEqual(got.get("生命"), 15465.0)
        self.assertNotIn("坏的", got, "解析不了的不该进 map")


class TestInlineExpand(unittest.TestCase):
    """★★ 技能 / 共鸣链：**点击往下展开**说明（不是弹窗），初始不显示。

    用户 2026-10-05::

        "技能、共鸣链，点击的时候，往下展开说明，不是弹出说明，
         初始不点击的时候，不展示任何说明"

    ⚠ 我原来做的是 ``_show_text_dialog``（弹窗）——
    用户要的是**就地往下展开**。
    """

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def _view(self):
        from src.tools.game.character_build.detail_view import EchoDetailView

        detail = {
            "role": {"roleName": "测试", "level": 90},
            "skillList": [
                {"level": 10, "skill": {
                    "name": "应急预案", "type": "共鸣技能",
                    "description": "呼唤忧昙攻击目标。", "iconUrl": ""}},
            ],
            "chainList": [
                {"order": 1, "name": "极简与繁复", "unlocked": True,
                 "description": "每消耗1点念意回复2.5点能量。",
                 "iconUrl": ""},
            ],
            "phantomData": {"cost": 12, "equipPhantomList": []},
        }
        view = EchoDetailView()
        view.show_detail(detail)
        return view

    @staticmethod
    def _areas(view):
        """共用说明面板（技能一块 + 共鸣链一块）。

        ⚠ 原来是 `expandArea`（**每条一个框**）——
        用户后来要求改成**共用一块**（见 TestSharedExpandPanel）。
        """
        from PySide6.QtWidgets import QWidget

        return [w for w in view.findChildren(QWidget)
                if w.objectName() == "expandPanel"]

    def test_areas_exist(self):
        """★ 技能 + 共鸣链各有一块**共用**说明面板。

        ⚠ 这里原来断言 ``expandArea``（每条一个框）——
        用户后来要求改成**共用一块**（见 :class:`TestSharedExpandPanel`），
        所以改成查 ``expandPanel``。
        """
        view = self._view()
        self.assertGreaterEqual(len(self._areas(view)), 2,
                                "没找到展开说明面板")

    def test_areas_hidden_initially(self):
        """★★ **初始一个说明都不显示**。"""
        view = self._view()
        shown = [a for a in self._areas(view) if a.isVisible()]
        self.assertEqual(shown, [],
                         f"有 {len(shown)} 块说明初始就显示了 —— 用户要求隐藏")

    def test_not_a_dialog(self):
        """★★ 说明是**就地展开**，不是弹窗。

        ⚠ 我第一版做的是弹窗 —— 用户明确说"不是弹出说明"。
        而且弹窗会**阻塞自动化测试**（``exec()`` 卡住），
        实测护栏验证时就是这样超时的。
        """
        import inspect

        from src.tools.game.character_build import detail_view as DV

        for fn in (DV._skills_block, DV._chains_block):
            with self.subTest(fn=fn.__name__):
                src = inspect.getsource(fn)
                self.assertNotIn("_show_text_dialog", src,
                                 f"{fn.__name__} 还在弹窗")

    def test_no_blocking_dialog_anywhere(self):
        """★★ 整个模块**不该有** ``QDialog`` / ``exec()`` —— 会卡住测试。"""
        text = (ROOT / "src" / "tools" / "game" / "character_build"
                / "detail_view.py").read_text(encoding="utf-8")
        self.assertNotIn("QDialog", text,
                         "detail_view 里有 QDialog —— 弹窗会阻塞测试")
        self.assertNotIn(".exec()", text,
                         "detail_view 里有 exec() —— 会阻塞")

    def test_toggle_shows_and_hides(self):
        """★ 点一下展开、再点收起。"""
        from src.tools.game.character_build.detail_view import (
            _bind_toggle,
            _expand_area,
        )
        from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

        host = QWidget()
        box = QVBoxLayout(host)
        lbl = QLabel("点我", host)
        box.addWidget(lbl)
        area = _expand_area(host, "标题", "说明文字")
        box.addWidget(area)
        host.show()
        self.app.processEvents()

        self.assertFalse(area.isVisible(), "初始就该隐藏")
        _bind_toggle(lbl, area)
        lbl.mousePressEvent(None)
        self.assertTrue(area.isVisible(), "点一下该展开")
        lbl.mousePressEvent(None)
        self.assertFalse(area.isVisible(), "再点该收起")

    def test_expand_area_is_scoped(self):
        """★ 说明区样式要带选择器（否则会套到子控件上——之前踩过）。"""
        from PySide6.QtWidgets import QWidget

        view = self._view()
        areas = self._areas(view)
        self.assertTrue(areas)
        for a in areas:
            css = a.styleSheet()
            self.assertIn("#expandPanel", css,
                          f"说明面板样式没写选择器：{css[:50]}")


class TestGapHint(unittest.TestCase):
    """★★ 属性不足时：**红色高亮 + 括号说明差多少**。

    用户 2026-10-05::

        "哪条属性不足的，红色高亮显示，并加个括号说明差多少"
    """

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    @staticmethod
    def _detail(attrs: dict) -> dict:
        return {
            "role": {"roleName": "测试", "level": 90},
            "roleAttributeList": [
                {"attributeName": k, "attributeValue": v}
                for k, v in attrs.items()],
            "phantomData": {"cost": 12, "equipPhantomList": []},
        }

    @staticmethod
    def _standard(pairs) -> dict:
        return {"attrs": [
            {"name": n, "recommend": f"{v}%", "value": v, "unit": "%",
             "symbol": sym, "icon_url": ""}
            for n, sym, v in pairs]}

    def _view(self, attrs, pairs):
        from src.tools.game.character_build.detail_view import EchoDetailView

        view = EchoDetailView()
        view.show_detail(self._detail(attrs), None,
                         self._standard(pairs))
        return view

    @staticmethod
    def _texts(view):
        from PySide6.QtWidgets import QLabel

        return [w.text() for w in view.findChildren(QLabel) if w.text()]

    def test_gap_shown_for_failing_attr(self):
        """★★ 不足的那条要写「（差 N）」并在最前面标红。"""
        from src.tools.game.character_build import detail_view as DV

        view = self._view({"共鸣效率": "222.6%"},
                          [("共鸣效率", "≥", 260.0)])
        texts = self._texts(view)
        self.assertTrue(any(t.startswith("（差") for t in texts),
                        f"没写差额（{texts[:8]}）")
        self.assertIn("（差 37.4%）", texts)

        #: ★ 当前值 / 属性名 要标红
        reds = [w.text() for w in view.findChildren(
            __import__("PySide6.QtWidgets", fromlist=["QLabel"]).QLabel)
            if DV.BAD_FG in (w.styleSheet() or "") and w.text()]
        self.assertIn("共鸣效率", reds, f"属性名没标红（{reds[:6]}）")

    def test_no_gap_when_meets(self):
        """★ 达标的**不写差额**，也不标红。"""
        from src.tools.game.character_build import detail_view as DV
        from PySide6.QtWidgets import QLabel

        view = self._view({"暴击": "80.0%"}, [("暴击", "≥", 70.0)])
        texts = self._texts(view)
        self.assertFalse(any(t.startswith("（差") for t in texts),
                         f"达标了还写差额（{texts[:8]}）")
        reds = [w.text() for w in view.findChildren(QLabel)
                if DV.BAD_FG in (w.styleSheet() or "") and w.text()]
        self.assertEqual(reds, [], f"达标了还标红（{reds}）")

    def test_gap_uses_absolute_difference(self):
        """★ 差额取**绝对值** —— 符号可能是 ``>`` / ``≤`` 等各种方向。"""
        from src.tools.game.character_build.detail_view import EchoDetailView

        #: >65 而当前 60 → 差 5
        view = EchoDetailView()
        view.show_detail(self._detail({"暴击": "60.0%"}), None,
                         self._standard([("暴击", ">", 65.0)]))
        self.assertIn("（差 5%）", self._texts(view))

    def test_missing_attr_is_not_red(self):
        """★ 面板里**没有**这个属性 → 显示「—」但**不标红**
        （那不算"不达标"，是没数据）。"""
        from src.tools.game.character_build import detail_view as DV
        from PySide6.QtWidgets import QLabel

        view = self._view({"暴击": "80.0%"},
                          [("暴击", "≥", 70.0), ("重击伤害加成", "≥", 20.0)])
        texts = self._texts(view)
        self.assertIn("—", texts, "缺的属性该显示「—」")
        #: 缺的那条不该产生差额
        self.assertFalse(any(t.startswith("（差") for t in texts))
        #: 属性名不该因为"缺"而标红
        reds = [w.text() for w in view.findChildren(QLabel)
                if DV.BAD_FG in (w.styleSheet() or "")]
        self.assertNotIn("重击伤害加成", reds)


class TestEchoSetComparison(unittest.TestCase):
    """★★★ 套装要看**官方推荐的组合**，不是"必须统一"。

    用户 2026-10-05（截图圈出千咲：**属性全绿却进了「未达标」**）::

        "达标的怎么进了未达标的？"

    ## 根因 ①：我自己发明的"套装不统一"规则

    ::

        千咲实际:  命理崩毁之弦 ×3 + 幽夜隐匿之帷 ×2   ← 3+2 混搭
        官方推荐:  命理崩毁之弦 ×3 + 幽夜隐匿之帷 ×2   ← **一模一样**

    **3+2 是完全合法的配装**，官方攻略里就是这么推荐的。
    "不统一"根本不是问题 —— **对不上官方组合**才是。

    ## 根因 ②：官方数据里**同名套装会出现两次**

    ::

        千咲（3+2）:
            {"echoSet": 3, "name": "命理崩毁之弦"}
            {"echoSet": 2, "name": "幽夜隐匿之帷"}

        椿 / 维里奈（5 件套）:
            {"echoSet": 5, "name": "轻云出月"}
            {"echoSet": 2, "name": "轻云出月"}     ← ★ **同名！**

    后一条只是"2 件套效果"的附带说明，**不是"再要 2 件"**。
    我第一版没去重 → "椿"被算成 `{"轻云出月": 2}` →
    报"现在 ×5，推荐 ×2" —— **29 个角色全被误判**。

    → 同名取**最大值**才对。
    """

    @staticmethod
    def _standard(sets) -> dict:
        """``sets`` = ``[(名字, 件数), ...]``（照官方结构造）。"""
        return {"echo": {"main": {"echoSetEffects": [
            {"echoSet": n, "echoSetGroupGameBusinessId": str(i),
             "texts": [{"language": "zh-Hans", "name": name}]}
            for i, (name, n) in enumerate(sets, start=1)
        ]}}}

    @staticmethod
    def _items(sets) -> list:
        """``sets`` = ``[(名字, 件数), ...]`` → 声骸列表。

        ⚠ 件数之和必须是 5（COST 4-3-3-1-1），否则会先被 COST 规则报错。
        """
        costs = [4, 3, 3, 1, 1]
        out = []
        i = 0
        for name, n in sets:
            for _ in range(n):
                out.append({"cost": costs[i], "level": 25, "quality": 5,
                            "phantomProp": {"name": "x"},
                            "fetterDetail": {"name": name},
                            "mainProps": [], "subProps": []})
                i += 1
        return out

    def _issues(self, actual, recommended):
        from src.tools.game.character_build import tool as T

        detail = {"role": {"roleName": "T", "level": 90},
                  "roleAttributeList": [],
                  "phantomData": {"cost": 12,
                                  "equipPhantomList": self._items(actual)}}
        return T.CharacterBuildPanel._echo_issues(
            detail, self._standard(recommended))

    def test_recommended_counts(self):
        """★ 同名套装要**取最大值**（5 件套会同时给 5 和 2）。"""
        from src.tools.game.character_build import tool as T

        got = T._recommended_set_counts(self._standard(
            [("轻云出月", 5), ("轻云出月", 2)]))
        self.assertEqual(got, {"轻云出月": 5},
                         "同名没去重 —— 5 件套会被算成 2 件")

    def test_mixed_3_plus_2_is_fine(self):
        """★★ 3+2 混搭**对上官方推荐就是对的**（千咲那个 bug）。"""
        got = self._issues(
            [("命理崩毁之弦", 3), ("幽夜隐匿之帷", 2)],
            [("命理崩毁之弦", 3), ("幽夜隐匿之帷", 2)])
        self.assertEqual(got, [], f"合法的 3+2 被判成问题（{got}）")

    def test_five_piece_is_fine(self):
        """★★ **5 件套不报错**（官方给 5 和 2 两条同名记录）。"""
        got = self._issues([("轻云出月", 5)], [("轻云出月", 5), ("轻云出月", 2)])
        self.assertEqual(got, [], f"5 件套被判成问题（{got}）")

    def test_wrong_set_is_reported(self):
        """★ 用了**别的套装**才该报（洛可可那种）。"""
        got = self._issues([("幽夜隐匿之帷", 5)], [("轻云出月", 5)])
        self.assertTrue(any("套装" in x for x in got),
                        f"用错套装没报（{got}）")

    def test_wrong_mix_is_reported(self):
        """★ 混搭但**搭配不对**也要报（弗洛洛那种）。"""
        got = self._issues(
            [("失序彼岸之梦", 3), ("幽夜隐匿之帷", 2)],
            [("失序彼岸之梦", 3), ("沉日劫明", 2)])
        self.assertTrue(any("套装" in x for x in got),
                        f"搭配不对没报（{got}）")

    def test_order_does_not_matter(self):
        """★ 套装顺序无关（只看**组合**）。"""
        got = self._issues(
            [("幽夜隐匿之帷", 2), ("命理崩毁之弦", 3)],
            [("命理崩毁之弦", 3), ("幽夜隐匿之帷", 2)])
        self.assertEqual(got, [])

    def test_no_recommendation_is_not_an_issue(self):
        """★ 拿不到官方套装 → 不比、不瞎报。"""
        from src.tools.game.character_build import tool as T

        detail = {"role": {}, "roleAttributeList": [],
                  "phantomData": {"cost": 12,
                                  "equipPhantomList": self._items(
                                      [("随便什么", 5)])}}
        for std in (None, {}, {"echo": None}, {"echo": {"main": None}},
                    {"echo": {"main": {"echoSetEffects": []}}}):
            with self.subTest(std=str(std)[:30]):
                got = T.CharacterBuildPanel._echo_issues(detail, std)
                self.assertEqual([x for x in got if "套装" in x], [])

    def test_uniform_echoes_not_reported(self):
        """★★ 单套装也**不该**因为"不统一"被报（那条规则已删）。"""
        got = self._issues([("隐世回光", 5)], [("隐世回光", 5), ("隐世回光", 2)])
        self.assertEqual([x for x in got if "统一" in x], [],
                         "「套装不统一」那条瞎定的规则又回来了")


class TestUnleveledFilter(unittest.TestCase):
    """★★★ 「未练」= **没有声骸 OR 等级未满 90 级**。

    用户 2026-10-05（截图圈出下拉框）::

        "去掉未满90级分类，只保留未练分类，
         未练就是没有声骸或者等级未满90级的"

    ## 演进过程

    1. "达标/未达标"                    → 两态
    2. "增加一个分类，等级（未满90级的）" → 加「未满90级」
    3. "40级的应该进**未练**的分类"     → 加「未练」（没声骸数据）
    4. ★ **"去掉未满90级分类，只保留未练分类，
       未练就是没有声骸或者等级未满90级的"** → **合并成一个**

    ## ⚠ 之前的 bug（用户第 3 步报的）

    ``flagged`` 只遍历 ``details`` → 没声骸数据的角色 ``issues`` 是
    ``None``（假）→ 落进「达标」。**"没数据" ≠ "达标"**。
    """

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def _panel(self):
        from src.tools.game.character_build.tool import CharacterBuildPanel

        return CharacterBuildPanel()

    @staticmethod
    def _good_detail(name: str) -> dict:
        """一份**结构完美**的声骸（满级 / 同套装 / COST 4-3-3-1-1）。"""
        def item(cost):
            return {
                "cost": cost, "level": 25, "quality": 5,
                "phantomProp": {"name": "声骸"},
                "fetterDetail": {"name": "套装"},
                "mainProps": [{"attributeName": "攻击",
                               "attributeValue": "1%", "valid": True}],
                "subProps": [{"attributeName": "x",
                              "attributeValue": "1%", "valid": True}],
            }

        return {"role": {"roleName": name, "level": 90},
                "roleAttributeList": [],
                "phantomData": {"cost": 12,
                                "equipPhantomList": [item(c)
                                                     for c in (4, 3, 3, 1, 1)]}}

    def test_filter_choices_merged(self):
        """★★ **「未满90级」删掉了，只剩「未练」**（用户第 4 步要求）。"""
        from src.tools.game.character_build import tool as T

        self.assertIn("未练", T.FILTER_CHOICES)
        self.assertNotIn("未满90级", T.FILTER_CHOICES,
                         "「未满90级」没删掉 —— 用户要求并进「未练」")
        self.assertEqual(tuple(T.FILTER_CHOICES),
                         ("全部", "未达标", "达标", "未练"))

    def test_is_unleveled_definition(self):
        """★★ 「未练」定义：**没数据 OR 未满90级**。"""
        from src.tools.game.character_build import tool as T

        #: 没数据 → 未练（不管几级）
        self.assertTrue(T.is_unleveled({"level": 90}, False))
        self.assertTrue(T.is_unleveled({"level": 40}, False))
        #: 有数据但没满级 → 未练
        self.assertTrue(T.is_unleveled({"level": 40}, True))
        #: 有数据且满级 → 不是未练
        self.assertFalse(T.is_unleveled({"level": 90}, True))
        self.assertFalse(T.is_unleveled({"level": 95}, True))
        #: 坏值不崩
        self.assertFalse(T.is_unleveled({"level": "abc"}, True))

    def _four_cases(self):
        """四种组合：满级/低级 × 有数据/没数据。"""
        return {
            "roleList": [
                {"roleId": 1, "roleName": "满级有数据", "level": 90},
                {"roleId": 2, "roleName": "低级有数据", "level": 40},
                {"roleId": 3, "roleName": "满级没数据", "level": 90},
                {"roleId": 4, "roleName": "低级没数据", "level": 40},
            ],
            "details": {"1": self._good_detail("满级有数据"),
                        "2": self._good_detail("低级有数据")},
        }

    def test_unleveled_covers_both_conditions(self):
        """★★★ 「未练」要**同时**包含"低级有数据"和"没数据"两种。"""
        p = self._panel()
        p._data = self._four_cases()
        p._selected = "1"
        p._filter_box.setCurrentText("未练")
        p._render(p._data)
        ids = sorted(c._cid for c in p._cards)
        self.assertEqual(ids, ["2", "3", "4"],
                         "「未练」没收全 —— 该是「低级有数据 + 没数据」两种")

    def test_low_level_with_data_is_unleveled(self):
        """★★★ **有数据但没满级**的也算「未练」（合并后的新行为）。

        ⚠ 合并前它既不在「未练」（那时只看有没有数据），
        也不在「未满90级」时会被算进去 —— 两个分类语义重叠，用户要求合并。
        """
        p = self._panel()
        p._data = self._four_cases()
        p._selected = "1"
        p._filter_box.setCurrentText("未练")
        p._render(p._data)
        self.assertIn("2", [c._cid for c in p._cards],
                      "「低级有数据」没进「未练」")

    def test_ok_requires_data_and_max_level(self):
        """★★ 「达标」要**有数据 + 没问题 + 满级**三条都满足。"""
        p = self._panel()
        p._data = self._four_cases()
        p._selected = "1"
        p._filter_box.setCurrentText("达标")
        p._render(p._data)
        self.assertEqual([c._cid for c in p._cards], ["1"],
                         "「达标」该只有「满级且数据没问题」那个")

    def test_no_data_is_not_ok(self):
        """★★★ **没数据 ≠ 达标**（用户第 3 步报的 bug）。"""
        p = self._panel()
        p._data = self._four_cases()
        p._selected = "1"
        p._filter_box.setCurrentText("达标")
        p._render(p._data)
        ids = [c._cid for c in p._cards]
        self.assertNotIn("3", ids, "没数据的跑进「达标」了")
        self.assertNotIn("4", ids, "没数据的跑进「达标」了")

    def test_three_states_are_disjoint(self):
        """★★ 三态**互不重叠**、合起来等于全部。"""
        p = self._panel()
        p._data = self._four_cases()
        p._selected = "1"
        seen: set[str] = set()
        for choice in ("未练", "未达标", "达标"):
            p._filter_box.setCurrentText(choice)
            p._render(p._data)
            ids = {c._cid for c in p._cards}
            self.assertFalse(ids & seen,
                             f"「{choice}」和别的分类重叠：{ids & seen}")
            seen |= ids
        self.assertEqual(seen, {"1", "2", "3", "4"},
                         f"三态合起来不等于全部（{seen}）")


class TestLevelFilter(unittest.TestCase):
    """★ `is_below_max_level` / `MAX_LEVEL`（等级判定的底层）。

    ⚠ 原来这条类是测「未满90级」**下拉分类**的 ——
    用户 2026-10-05 要求把它**并进「未练」**，
    所以现在只剩底层函数的测试（筛选行为见
    :class:`TestUnleveledFilter`）。
    """

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def _panel(self):
        from src.tools.game.character_build.tool import CharacterBuildPanel

        return CharacterBuildPanel()

    def test_filter_choices(self):
        """⚠ 「未满90级」已并进「未练」（用户 2026-10-05 要求）。"""
        from src.tools.game.character_build import tool as T

        self.assertNotIn("未满90级", T.FILTER_CHOICES,
                         "「未满90级」该并进「未练」了")

    def test_max_level_constant(self):
        from src.tools.game.character_build import tool as T

        self.assertEqual(T.MAX_LEVEL, 90)

    def test_is_below_max_level(self):
        from src.tools.game.character_build import tool as T

        self.assertTrue(T.is_below_max_level({"level": 40}))
        self.assertTrue(T.is_below_max_level({"level": "80"}))
        self.assertFalse(T.is_below_max_level({"level": 90}))
        self.assertFalse(T.is_below_max_level({"level": 91}))
        #: 缺字段 / 坏值不该崩
        self.assertFalse(T.is_below_max_level({}))
        self.assertFalse(T.is_below_max_level(None))
        self.assertFalse(T.is_below_max_level({"level": "abc"}))

    def test_unleveled_filter_includes_low_level(self):
        """★★ 「未练」也要收**等级没满**的（合并后的行为）。

        ⚠ 原来这条叫 ``test_filters_by_level``，用的是「未满90级」下拉 ——
        那个分类已经并进「未练」了。
        """
        p = self._panel()
        p._data = {
            "roleList": [
                {"roleId": 1, "roleName": "满级", "level": 90},
                {"roleId": 2, "roleName": "四十", "level": 40},
                {"roleId": 3, "roleName": "八十", "level": 80},
            ],
            "details": {},          #: 都没数据 → 三个都算"未练"
        }
        p._selected = "1"
        p._filter_box.setCurrentText("未练")
        p._render(p._data)
        self.assertEqual(sorted(c._cid for c in p._cards),
                         ["1", "2", "3"],
                         "「未练」该把低等级的也收进来")

    def test_unleveled_filter_combines_with_search(self):
        """★ 筛选和搜索能叠加。"""
        p = self._panel()
        p._data = {
            "roleList": [
                {"roleId": 1, "roleName": "安可", "level": 40},
                {"roleId": 2, "roleName": "白芷", "level": 40},
                {"roleId": 3, "roleName": "安可", "level": 90},
            ],
            "details": {},
        }
        p._selected = "1"
        p._filter_box.setCurrentText("未练")
        p._search_edit.setText("安可")
        p._render(p._data)
        self.assertEqual(sorted(c._cid for c in p._cards), ["1", "3"],
                         "筛选+搜索叠加不对")


class TestSelectedTileHighlight(unittest.TestCase):
    """★★ 选中的角色格子 = **下方一条黄色粗线**。

    用户 2026-10-05（截图圈出格子**下方**那条横线）::

        "点到那个，哪个下方加一个黄色高亮的粗线"

    ⚠ 改过两次：

      1. 原来蓝色**边框** → 用户说"黄色高亮"
      2. 我做成**整卡黄底** → 用户要的是**下方一条粗线**，卡片本身别变色
    """

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def _panel(self):
        from src.tools.game.character_build.tool import CharacterBuildPanel

        return CharacterBuildPanel()

    @staticmethod
    def _bar_of(tile):
        """格子底部那条横条控件（黄 or 透明）。

        ⚠ 按 ``objectName`` 找 —— 别用"高度等于 SELECT_BAR_H"去猜，
        别的控件也可能正好那么高（我第一版就是这么写的，找不到）。
        """
        from PySide6.QtWidgets import QWidget

        for w in tile.findChildren(QWidget):
            if w.objectName() == "selectBar":
                return w
        return None

    @classmethod
    def _is_selected_bar(cls, tile) -> bool:
        """这个格子底部的横条是不是**黄色**（而不是透明）。"""
        from src.tools.game.character_build import detail_view as DV

        bar = cls._bar_of(tile)
        return bool(bar and DV.SELECT_BORDER in (bar.styleSheet() or ""))

    def test_selected_tile_has_yellow_underline(self):
        """★★ 选中的格子：**下方黄色粗线**，且**只有它一个**有。

        ⚠⚠ 用 ``border-bottom`` 做过一版 —— 线会被挤到格子**最底边**，
        实测截图里**几乎看不见**。现在改成**单独的横条控件**，
        高度和位置都可控（这条测试也顺带钉住了"是控件不是边框"）。
        """
        from PySide6.QtWidgets import QWidget

        from src.tools.game.character_build import detail_view as DV

        p = self._panel()
        p._data = {
            "roleList": [
                {"roleId": 1, "roleName": "甲", "level": 90},
                {"roleId": 2, "roleName": "乙", "level": 90},
            ],
            "details": {},
        }
        p._selected = "2"
        p._render(p._data)

        #: ★ 必须是**独立控件**（不是 border-bottom）
        for c in p._cards:
            self.assertIsNotNone(self._bar_of(c),
                                 "格子底部没有横条控件 —— "
                                 "是不是又用 border-bottom 了？")

        sel = [c for c in p._cards if self._is_selected_bar(c)]
        self.assertEqual(len(sel), 1, "选中的格子没有下方黄线")
        self.assertEqual(sel[0]._cid, "2", "加线的不是选中的那个")
        #: 黄线要够粗（用户说"粗线"）
        self.assertGreaterEqual(DV.SELECT_BAR_H, 3,
                                "线太细 —— 用户要的是粗线")

    def test_unselected_bar_is_transparent_but_present(self):
        """★ 没选中的格子：横条**占位但透明**。

        ⚠ 必须留同样高度 —— 否则选中的格子会比别人高，整行**会跳**。
        """
        from src.tools.game.character_build import detail_view as DV

        p = self._panel()
        p._data = {
            "roleList": [
                {"roleId": 1, "roleName": "甲", "level": 90},
                {"roleId": 2, "roleName": "乙", "level": 90},
            ],
            "details": {},
        }
        p._selected = "1"
        p._render(p._data)
        others = [c for c in p._cards if c._cid != "1"]
        self.assertTrue(others)
        for c in others:
            bar = self._bar_of(c)
            self.assertIsNotNone(bar, "没选中的格子没有占位横条")
            self.assertIn("transparent", bar.styleSheet() or "",
                          "没选中的横条不是透明的")
            self.assertEqual(bar.height(), DV.SELECT_BAR_H,
                             "占位横条高度不一致 —— 整行会跳")

    def test_no_full_card_highlight(self):
        """★★ 卡片本身**不再整块变色**（用户要的是下方一条线）。

        ⚠ 我上一版做成整卡黄底（``background: SELECT_BG``）——
        用户截图圈的是**下方那条线**。
        """
        from src.tools.game.character_build import detail_view as DV

        p = self._panel()
        p._data = {
            "roleList": [{"roleId": 1, "roleName": "甲", "level": 90}],
            "details": {},
        }
        p._selected = "1"
        p._render(p._data)
        css = p._cards[0].styleSheet()
        self.assertNotIn(f"background: {DV.SELECT_BG}", css,
                         "卡片还是整块黄底 —— 应该只加下方那条线")
    def test_bar_color_is_yellow(self):
        """★ 线是**黄**的（不是原来的蓝，也不是几乎白）。

        用 RGB 判断：黄色 = R/G 高、**B 明显低**。
        """
        from src.tools.game.character_build import detail_view as DV

        h = DV.SELECT_BORDER.lstrip("#")
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
        self.assertGreater(r, 180, f"红分量太低：{DV.SELECT_BORDER}")
        self.assertGreater(g, 130, f"绿分量太低：{DV.SELECT_BORDER}")
        self.assertLess(b, r - 100,
                        f"蓝分量相对红太高（{DV.SELECT_BORDER}）—— 不像黄色")

    def test_flagged_name_still_red(self):
        """★ 未达标 → 名字标红（和"选中"是两回事，互不干扰）。"""
        from src.tools.game.character_build import detail_view as DV
        from PySide6.QtWidgets import QLabel

        p = self._panel()
        p._data = {
            "roleList": [{"roleId": 1, "roleName": "甲", "level": 90}],
            #: 声骸很差 → 会被判未达标
            "details": {"1": {
                "role": {"roleName": "甲", "level": 90},
                "phantomData": {"equipPhantomList": [
                    {"cost": 4, "level": 1,
                     "fetterDetail": {"name": "A"},
                     "phantomProp": {"name": "x"},
                     "mainProps": [], "subProps": []}]}}},
        }
        p._selected = "1"
        p._render(p._data)
        self.assertEqual(len(p._cards), 1)
        reds = [w.text() for w in p._cards[0].findChildren(QLabel)
                if DV.BAD_FG in (w.styleSheet() or "")]
        self.assertIn("甲", reds, "未达标的名字没标红")


class TestSharedExpandPanel(unittest.TestCase):
    """★★ 技能 / 共鸣链：**共用一块面板**，一次只显示一条，再点关闭。

    用户 2026-10-05（截图圈出技能区和共鸣链区）::

        "这里点到哪个技能，展示哪个，占满整个红框，
         再次点击该技能就是关闭展开"
        "共鸣链这里也是跟上面一样"

    ⚠ 我上一版是**每条一个展开框** —— 用户要的是**一块共用的**，
    点谁换谁，再点同一条就关掉。
    """

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    @staticmethod
    def _detail(url: str) -> dict:
        """⚠ 说明挂在**图标控件**上，没图标就没控件（见"空方块"那次修复），
        所以测试得先造一个真缓存图，再把 URL 塞进来。"""
        return {
            "role": {"roleName": "测试", "level": 90},
            "skillList": [
                {"level": 10, "skill": {
                    "name": "技能甲", "type": "常态攻击",
                    "description": "甲的说明", "iconUrl": url}},
                {"level": 10, "skill": {"name": "技能乙", "type": "共鸣技能",
                                        "description": "乙的说明",
                                        "iconUrl": url}},
            ],
            "chainList": [
                {"order": 1, "name": "链甲", "unlocked": True,
                 "description": "链甲的说明", "iconUrl": url},
                {"order": 2, "name": "链乙", "unlocked": True,
                 "description": "链乙的说明", "iconUrl": url},
            ],
            "phantomData": {"cost": 12, "equipPhantomList": []},
        }

    @staticmethod
    def _panels(view):
        from PySide6.QtWidgets import QWidget

        return [w for w in view.findChildren(QWidget)
                if w.objectName() == "expandPanel"]

    def _view(self):
        """造一个真图标 + 渲染，返回 ``view``。"""
        import tempfile

        from PySide6.QtGui import QPixmap

        from src.core import icon_cache as IC
        from src.tools.game.character_build.detail_view import EchoDetailView

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        orig = IC.icon_root
        IC.icon_root = lambda: pathlib.Path(tmp.name)
        self.addCleanup(lambda: setattr(IC, "icon_root", orig))

        url = "https://x/icon.png"
        path = IC.local_path(url)
        path.parent.mkdir(parents=True, exist_ok=True)
        pix = QPixmap(8, 8)
        pix.fill()
        pix.save(str(path))

        view = EchoDetailView()
        view.show_detail(self._detail(url))
        return view

    @staticmethod
    def _clickables(view):
        """所有绑了展开开关的控件。"""
        from PySide6.QtWidgets import QLabel

        return [w for w in view.findChildren(QLabel)
                if w.mousePressEvent.__name__ == "_toggle"
                and w.property("expandKey")]

    def test_one_panel_per_block(self):
        """★★ 技能块 / 共鸣链块**各只有一块**面板（不是每条一个）。"""
        view = self._view()
        panels = self._panels(view)
        self.assertEqual(len(panels), 2,
                         f"应该是 2 块共用面板（技能+共鸣链），"
                         f"实际 {len(panels)} 块")

    def test_panels_hidden_initially(self):
        """★★ 初始一块都不显示。"""
        view = self._view()
        for p in self._panels(view):
            self.assertFalse(p.isVisible(), "初始有面板显示了")
            self.assertEqual(str(p.property("expandShown") or ""), "",
                             "初始就有展开状态")

    @staticmethod
    def _shown_key(panel) -> str:
        """面板当前展示的是哪一条（**不看 isVisible**）。

        ⚠ 父窗口没 ``show()`` 时 ``isVisible()`` 永远是 False ——
        测试里判不出来，所以状态记在 ``expandShown`` 属性上。
        """
        return str(panel.property("expandShown") or "")

    def test_click_shows_panel_with_that_content(self):
        """★★ 点某一条 → 面板显示**那一条**的内容。"""
        from PySide6.QtWidgets import QLabel

        view = self._view()
        panel = self._panels(view)[0]         #: 技能块的
        target = next(
            (w for w in self._clickables(view)
             if "技能乙" in str(w.property("expandKey"))), None)
        self.assertIsNotNone(target, "没找到「技能乙」的可点控件")

        target.mousePressEvent(None)
        self.assertIn("技能乙", self._shown_key(panel),
                      "点了没展开")
        texts = [t.text() for t in panel.findChildren(QLabel)]
        self.assertTrue(any("技能乙" in t for t in texts),
                        f"面板里不是点的那条（{texts}）")
        self.assertTrue(any("乙的说明" in t for t in texts),
                        f"说明没写进面板（{texts}）")

    def test_click_again_closes(self):
        """★★ **再点同一条 → 关闭**（用户明确要求）。"""
        view = self._view()
        panel = self._panels(view)[0]
        target = self._clickables(view)[0]
        target.mousePressEvent(None)
        self.assertNotEqual(self._shown_key(panel), "", "第一次点没展开")
        target.mousePressEvent(None)           #: 再点同一条
        self.assertEqual(self._shown_key(panel), "",
                         "再点同一条没关闭")

    def test_click_another_switches(self):
        """★★ 点**另一条** → 内容换成那条（互斥，不会两块都开）。"""
        from PySide6.QtWidgets import QLabel

        view = self._view()
        panel = self._panels(view)[0]
        clickable = self._clickables(view)
        self.assertGreaterEqual(len(clickable), 2, "技能不够两条")
        clickable[0].mousePressEvent(None)
        first = panel.findChildren(QLabel)[0].text()
        clickable[1].mousePressEvent(None)
        second = panel.findChildren(QLabel)[0].text()
        self.assertNotEqual(first, second, "点另一条没换内容")
        #: 只有**一块**面板处于展开状态（互斥）
        opened = [p for p in self._panels(view)
                  if self._shown_key(p)]
        self.assertEqual(len(opened), 1, "同时开了多块面板")

    def test_chains_use_same_pattern(self):
        """★ 共鸣链也是共用一块面板（用户："共鸣链这里也是跟上面一样"）。"""
        from PySide6.QtWidgets import QLabel

        view = self._view()
        panels = self._panels(view)
        self.assertEqual(len(panels), 2, "共鸣链没有共用面板")
        chain_panel = panels[1]
        target = next(
            (w for w in self._clickables(view)
             if "链甲" in str(w.property("expandKey"))), None)
        self.assertIsNotNone(target, "没找到共鸣链的可点控件")
        target.mousePressEvent(None)
        self.assertIn("链甲", self._shown_key(chain_panel))
        texts = [t.text() for t in chain_panel.findChildren(QLabel)]
        self.assertTrue(any("链甲的说明" in t for t in texts),
                        f"共鸣链说明没写进面板（{texts}）")


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

        ⚠ 我一度**删掉了**它（以为"登录自动获取"就够），
        用户当场纠正："气死了，乱改，特征码呢"。
        **特征码必须留着** —— 留空才自动。
        """
        p = self._panel()
        self.assertTrue(hasattr(p, "_feature_edit"),
                        "没有特征码输入框 —— 换号时没地方填")
        self.assertFalse(p._feature_edit.isHidden(),
                         "特征码输入框被藏起来了 —— 用户要看得见")

    def test_inputs_are_remembered(self):
        """★ 特征码 / 手机号要**记住上次的值**（用户：登录一次后默认保存）。

        ⚠ 光测 ``_remember_inputs()`` 本身不够 —— 把调用点从
        ``_on_logged_in`` 里删掉，那种测试照样通过（实测突变时发现）。
        所以这里**也查调用点**。
        """
        import ast as _ast

        p = self._panel()
        self.assertTrue(hasattr(p, "_remember_inputs"))
        self.assertTrue(hasattr(p, "_restore_inputs"))

        # ★ 调用点：_on_logged_in 里必须调它
        src = TOOL.read_text(encoding="utf-8")
        tree = _ast.parse(src)
        fn = next((n for n in _ast.walk(tree)
                   if isinstance(n, _ast.FunctionDef)
                   and n.name == "_on_logged_in"), None)
        self.assertIsNotNone(fn, "没有 _on_logged_in")
        names = {getattr(n, "id", None) or getattr(n, "attr", None)
                 for n in _ast.walk(fn)}
        self.assertIn("_remember_inputs", names,
                      "登录成功后没调 _remember_inputs —— 下次打开不会回填")

        #: 存 → 读 往返（走临时设置文件，别污染用户配置）
        import tempfile

        from src.core import tool_settings as TS
        from src.tools.game.character_build import tool as T

        tmp = tempfile.TemporaryDirectory()
        orig = TS.settings_file
        TS.settings_file = lambda: pathlib.Path(tmp.name) / "s.json"
        try:
            p._feature_edit.setText("113152489")
            p._mobile_edit.setText("15927967393")
            p._remember_inputs()
            saved = TS.load(T.SETTINGS_KEY)
            self.assertEqual(saved.get("feature_code"), "113152489")
            self.assertEqual(saved.get("mobile"), "15927967393")
            #: ★ 验证码**不该**被存（一次性的）
            self.assertNotIn("code", saved,
                             "验证码被存下来了 —— 那个是一次性的")
        finally:
            TS.settings_file = orig
            tmp.cleanup()

    def test_has_refresh_button(self):
        """★ 「刷新数据」按钮（用户要求：登录后自动拉，之后能手动刷）。

        ⚠ 第一版只断言 ``hasattr(p, "_refresh_button")`` —— 而
        ``PushButton("刷新数据", card)`` **构造时就设了 parent**，
        所以把 ``addWidget`` 删掉按钮依然存在，测试照样通过
        （实测突变时发现失效）。

        ⚠ 第二版从 ``p`` 往下找布局 —— 但 ``CharacterBuildPanel`` 是
        ``ScrollArea``，**它自己没有 layout**（内容在 ``p.widget()`` 里），
        所以怎么找都找不到。

        现在改成**找父链上有没有那个卡片**：
        按钮的祖先里必须出现 ``_buildLoginCard`` 建的那个 ``CardWidget``。
        """
        p = self._panel()
        btn = getattr(p, "_refresh_button", None)
        self.assertIsNotNone(btn, "没有刷新按钮")

        #: 往上走，收集祖先类型
        chain: list[str] = []
        node = btn
        for _ in range(10):
            parent = node.parent()
            if parent is None:
                break
            chain.append(type(parent).__name__)
            node = parent
        self.assertIn("CardWidget", chain,
                      f"「刷新数据」按钮不在任何卡片里（父链 {chain}）—— "
                      f"说明没被 addWidget 进布局，界面上看不到")

    def test_log_is_collapsed_by_default(self):
        """★ 日志默认折叠 —— 用户说"日志后台写"。

        ⚠ 第一版断言 ``not p._log.isVisible()`` —— 而窗口没 ``show()`` 时
        **所有控件 ``isVisible()`` 都是 False**，把日志改成展开也照样通过
        （实测突变时发现失效）。

        所以改用 ``isHidden()`` —— 它反映的是**显式隐藏**，和窗口显没显示无关。
        """
        p = self._panel()
        self.assertTrue(p._log.isHidden(),
                        "日志没被显式隐藏 —— 应该默认折叠，写在后台")

    def test_has_character_row(self):
        """★ 要有共鸣者列表（一行横向滚动）。"""
        p = self._panel()
        self.assertTrue(hasattr(p, "_roles_row"))
        self.assertTrue(hasattr(p, "_cards"))

    def test_has_search_box(self):
        """★ 搜索框（用户："加个下拉列表搜索"）。"""
        p = self._panel()
        self.assertTrue(hasattr(p, "_search_edit"),
                        "没有搜索框")

    def test_has_filter_dropdown(self):
        """★ 筛选下拉（用户先后要求过「未达标/达标」→「未满90级」→「未练」）。

        ⚠ 最新（2026-10-05）：**「未满90级」删掉，并进「未练」**——
        "未练就是没有声骸或者等级未满90级的"。
        """
        from src.tools.game.character_build.tool import FILTER_CHOICES

        p = self._panel()
        self.assertTrue(hasattr(p, "_filter_box"), "没有筛选下拉")
        for want in ("全部", "未达标", "达标", "未练"):
            self.assertIn(want, tuple(FILTER_CHOICES))
        self.assertNotIn("未满90级", tuple(FILTER_CHOICES),
                         "「未满90级」该并进「未练」了")

    def test_search_filters_by_name(self):
        """★ 搜索能按名字过滤。"""
        p = self._panel()
        p._data = {
            "roleList": [
                {"roleId": 1, "roleName": "安可", "level": 90,
                 "attributeName": "热熔", "weaponTypeName": "音感仪"},
                {"roleId": 2, "roleName": "白芷", "level": 90,
                 "attributeName": "冷凝", "weaponTypeName": "音感仪"},
            ],
            "details": {},
        }
        p._search_edit.setText("安可")
        p._render(p._data)
        self.assertEqual(len(p._cards), 1)

    def test_search_filters_by_attribute_and_weapon(self):
        """★ 搜索也能按**属性 / 武器**过滤（不止名字）。"""
        p = self._panel()
        p._data = {
            "roleList": [
                {"roleId": 1, "roleName": "安可", "level": 90,
                 "attributeName": "热熔", "weaponTypeName": "音感仪"},
                {"roleId": 2, "roleName": "忌炎", "level": 90,
                 "attributeName": "气动", "weaponTypeName": "长刃"},
            ],
            "details": {},
        }
        p._search_edit.setText("气动")
        p._render(p._data)
        self.assertEqual(len(p._cards), 1, "按属性搜索没生效")

        p._search_edit.setText("长刃")
        p._render(p._data)
        self.assertEqual(len(p._cards), 1, "按武器搜索没生效")

    def test_filter_unmet_only(self):
        """★ 「未达标」只显示有问题的。"""
        p = self._panel()

        def item(cost, valid):
            return {"cost": cost, "level": 25,
                    "fetterDetail": {"name": "A"},
                    "phantomProp": {"name": "x"},
                    "mainProps": [{"attributeName": "攻击",
                                   "attributeValue": "1%", "valid": True}],
                    "subProps": [{"attributeName": f"c{i}",
                                  "attributeValue": "1%",
                                  "valid": i < valid} for i in range(5)]}

        good = {"phantomData": {"equipPhantomList":
                                [item(c, 3) for c in (4, 3, 3, 1, 1)]}}
        bad = {"phantomData": {"equipPhantomList": [item(4, 0)]}}
        p._data = {
            "roleList": [
                {"roleId": 1, "roleName": "好", "level": 90},
                {"roleId": 2, "roleName": "差", "level": 90},
            ],
            "details": {"1": good, "2": bad},
        }
        p._filter_box.setCurrentText("未达标")
        p._render(p._data)
        self.assertEqual(len(p._cards), 1, "「未达标」筛选不对")

        p._filter_box.setCurrentText("达标")
        p._render(p._data)
        self.assertEqual(len(p._cards), 1, "「达标」筛选不对")

    def test_roles_are_single_scrollable_row(self):
        """★★ 共鸣者列表：**只占一行，放不下就横向滑动**。

        用户："一个就展示所有共鸣者，展示不全，可以滑动"

        ⚠ 我先后试过 **6 列小格子**（名字被压两行）和 **2 列大卡片**
        （一屏看不了几个），又试过 **8 列换行**（43 个铺了 6 行，
        把下面的详情区挤出屏幕）—— 用户都不满意。

        正解：``QScrollArea(横向) + QHBoxLayout``，**永远只占一行**。
        """
        p = self._panel()
        self.assertTrue(hasattr(p, "_roles_scroll"),
                        "没有横向滚动容器")
        #: 纵向滚动条必须关掉（否则会换行/撑高）
        from PySide6.QtCore import Qt

        self.assertEqual(p._roles_scroll.verticalScrollBarPolicy(),
                         Qt.ScrollBarPolicy.ScrollBarAlwaysOff,
                         "纵向滚动条没关 —— 列表会撑成多行")
        self.assertEqual(p._roles_scroll.horizontalScrollBarPolicy(),
                         Qt.ScrollBarPolicy.ScrollBarAsNeeded,
                         "横向滚动条不是 AsNeeded —— 放不下就没法滑")
        #: 高度必须是**固定的一行**
        from src.tools.game.character_build import tool as T

        self.assertLessEqual(p._roles_scroll.maximumHeight(),
                             T.TILE_H + 40,
                             "列表容器太高 —— 会挤掉详情区")

    def test_all_roles_go_in_one_row(self):
        """★ 所有角色都在**同一行**（不是网格）。"""
        p = self._panel()
        p._data = {
            "roleList": [{"roleId": i, "roleName": f"角色{i}", "level": 90}
                         for i in range(20)],
            "details": {},
        }
        p._selected = "19"       # 挡掉"默认选中第一个"的干扰
        p._render(p._data)
        self.assertEqual(len(p._cards), 20)
        #: 一行容器里应该有 20 个格子 + 1 个 stretch
        self.assertEqual(p._roles_row.count(), 21,
                         "不是全在一行里")

    def test_roles_sorted_newest_first(self):
        """★★ 角色按**最新获得顺序倒序**排列。

        用户 2026-10-04："角色按最新获得顺序倒序排序"

        ## 接口没有"获得时间"字段

        实测 ``roleList`` 一项的字段只有::

            acronym / attributeId / attributeName / breach /
            chainUnlockNum / isMainRole / level / roleIconUrl / roleId /
            roleName / rolePicUrl / roleSkin / starLevel /
            totalSkillLevel / weaponTypeId / weaponTypeName

        **没有 getTime / obtainTime 之类。**

        但 ``roleList`` 返回的**原始顺序就是游戏里的顺序** ——
        实测后两位并不递增（1402,1202,1103,1602,…），说明不是按 roleId 数值排，
        而是按游戏内顺序。所以**反转原始列表**就是"最新获得在前"。

        ⚠ 别再按 ``level`` / ``roleName`` 排 —— 那会打乱游戏顺序。
        """
        p = self._panel()
        p._data = {
            "roleList": [
                {"roleId": 1, "roleName": "最早", "level": 90},
                {"roleId": 2, "roleName": "中间", "level": 1},
                {"roleId": 3, "roleName": "最新", "level": 50},
            ],
            "details": {},
        }
        p._selected = "3"        # 挡掉"默认选中第一个"的干扰
        p._render(p._data)
        self.assertEqual([c._cid for c in p._cards], ["3", "2", "1"],
                         "没按最新获得倒序 —— 顺序反了或按别的字段排了")

    def test_first_role_selected_by_default(self):
        """★★ 没选角色时，**默认显示排在第一位的那个**。

        用户 2026-10-04："未选择角色时，默认显示排在第一位的角色"
        """
        p = self._panel()
        p._data = {
            "roleList": [
                {"roleId": 1, "roleName": "最早", "level": 90},
                {"roleId": 9, "roleName": "最新", "level": 90},
            ],
            "details": {"9": {
                "role": {"roleName": "最新", "level": 90},
                "phantomData": {"cost": 12, "equipPhantomList": []},
            }},
        }
        p._selected = ""
        p._render(p._data)

        #: 倒序后"最新"排第一 → 应该自动选中它
        self.assertEqual(p._selected, "9",
                         "没默认选中排在第一位的角色")
        from PySide6.QtWidgets import QLabel

        texts = [w.text() for w in p._detail.findChildren(QLabel) if w.text()]
        self.assertTrue(any("最新" in t for t in texts),
                        f"详情没自动显示第一个角色（{texts[:4]}）")

    def test_render_terminates_without_recursion(self):
        """★ 自动选中会让 ``_render`` 跑两遍，但**必须停**。

        ``_show_detail`` 结尾会再调一次 ``_render``（刷新选中高亮）——
        而 ``_render`` 里又有"默认选中第一个"。看上去像会无限递归。

        ⚠ 我一度加了个 ``_rendering`` 锁，后来**实测发现根本不会递归**：
        第一次进来就把 ``_selected`` 设上了，第二次那个分支不再成立 ——
        实测 **2 次就停**。锁是多余的，删掉了。

        这条测试钉住"会停"这件事（递归会 ``RecursionError``）。
        """
        p = self._panel()
        p._data = {
            "roleList": [{"roleId": 1, "roleName": "A", "level": 90}],
            "details": {"1": {"role": {"roleName": "A", "level": 90},
                              "phantomData": {}}},
        }
        p._selected = ""

        orig_render = type(p)._render
        calls = {"n": 0}

        def counting(_self, *args, **kwargs):
            calls["n"] += 1
            if calls["n"] > 20:
                raise RecursionError("_render 递归了")
            return orig_render(_self, *args, **kwargs)

        type(p)._render = counting
        try:
            p._render(p._data)
        finally:
            type(p)._render = orig_render

        self.assertEqual(p._selected, "1")
        self.assertLessEqual(calls["n"], 4,
                             f"_render 调了 {calls['n']} 次 —— 像在递归")

    def test_lazy_icon_plate_is_dark(self):
        """★★ 技能 / 共鸣链图标区必须是**深色底**。

        用户 2026-10-04（截图圈出技能/共鸣链那片空白）：
        "这个怎么是空白，能拿到数据吗"

        ## 查了很久：数据是好的，图标是**纯白色**

        · 图标都在缓存里（技能 217、共鸣链 186，一个不缺）
        · ``pixmap()`` 也不空（``isNull()=False``），控件 ``visible=True``
        · 但那些图是**纯白线条**（实测平均色 ``(255,255,255)``）——
          画在**白卡片**上等于隐形

        官方的技能区是深色底，所以白图标才显眼。

        ⚠ 所以这条断言的是**亮度**，不是颜色字符串 ——
        换个差不多深的色不该失败，改成白底/浅色必须失败。
        """
        from src.tools.game.character_build import detail_view as DV

        def lum(hex_color: str) -> float:
            h = hex_color.lstrip("#")
            r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
            return (0.299 * r + 0.587 * g + 0.114 * b) / 255

        self.assertLess(lum(DV.ICON_PLATE_BG), 0.55,
                        f"图标区底色太亮（{DV.ICON_PLATE_BG}）—— "
                        f"白色图标会看不见")
        self.assertGreater(lum(DV.ICON_PLATE_FG), 0.6,
                           "深色底上的文字要浅色")

    def test_skill_and_chain_blocks_use_dark_plate(self):
        """★ 技能 / 共鸣链块**实际用上了**深色底（不是只定义了常量）。"""
        from src.tools.game.character_build import detail_view as DV

        skills = [{"level": 10, "skill": {"name": "a",
                                          "iconUrl": "https://x/s.png"}}]
        chains = [{"name": "c", "order": 1, "unlocked": True,
                   "iconUrl": "https://x/c.png"}]

        sk = DV._skills_block(skills, None)
        self.assertIn(DV.ICON_PLATE_BG, sk.styleSheet(),
                      "技能块没用深色底 —— 白图标会隐形")

        ch = DV._chains_block(chains, None)
        #: 共鸣链的深色底在里面的 plate 上
        found = any(DV.ICON_PLATE_BG in (w.styleSheet() or "")
                    for w in ch.findChildren(type(ch)))
        self.assertTrue(found, "共鸣链块没用深色底")
        """★ 所有角色都在**同一行**（不是网格）。"""
        p = self._panel()
        p._data = {
            "roleList": [{"roleId": i, "roleName": f"角色{i}", "level": 90}
                         for i in range(20)],
            "details": {},
        }
        p._render(p._data)
        self.assertEqual(len(p._cards), 20)
        #: 一行容器里应该有 20 个格子 + 1 个 stretch
        self.assertEqual(p._roles_row.count(), 21,
                         "不是全在一行里")

    def test_tile_shows_avatar_and_name(self):
        """★ 格子 = 头像 + 名字（用户："文字+图片"）。"""
        from PySide6.QtWidgets import QLabel

        from src.tools.game.character_build.detail_view import CharacterTile

        role = {"roleId": 1, "roleName": "今汐", "level": 90,
                "attributeName": "衍射", "weaponTypeName": "长刃",
                "chainUnlockNum": 6}
        tile = CharacterTile(role)
        texts = [w.text() for w in tile.findChildren(QLabel)]
        self.assertTrue(any("今汐" in t for t in texts),
                        f"格子上没有名字（{texts}）")
        self.assertTrue(any("Lv" in t for t in texts),
                        f"格子上没有等级（{texts}）")

    def test_tile_marks_flagged(self):
        """★ 未达标的格子名字标红。"""
        from PySide6.QtWidgets import QLabel

        from src.tools.game.character_build.detail_view import CharacterTile

        role = {"roleId": 1, "roleName": "千咲", "level": 90}
        tile = CharacterTile(role, flagged=True)
        reds = [w for w in tile.findChildren(QLabel)
                if "c42b1c" in (w.styleSheet() or "")]
        self.assertTrue(reds, "未达标的格子没标红")

    def test_clicking_tile_shows_detail(self):
        """★★ 点格子 → 展示详情（用户："点击后才展示详情"）。"""
        p = self._panel()
        p._data = {
            "roleList": [{"roleId": 1103, "roleName": "白芷", "level": 90}],
            "details": {"1103": {
                "role": {"roleName": "白芷", "level": 90},
                "phantomData": {"cost": 12, "equipPhantomList": []},
            }},
        }
        p._render(p._data)
        p._show_detail("1103")
        from PySide6.QtWidgets import QLabel

        texts = [w.text() for w in p._detail.findChildren(QLabel) if w.text()]
        self.assertTrue(any("白芷" in t for t in texts),
                        f"点了格子但详情没显示（{texts[:6]}）")
        self.assertEqual(p._selected, "1103",
                         "没记住选中的是谁（格子不会高亮）")

    def test_feature_code_not_filled_with_junk(self):
        """★★ 特征码回填只认**像特征码**的值。

        2026-10-03：我的测试脚本往令牌文件写了假 ``roles``
        （``roleId: '1'``），界面就回填了一个 `1`，
        用户问"填个1是啥意思"。

        → 现在只认**纯数字且 >= 6 位**的。
        """
        import tempfile

        from src.core import kuro_account as K
        from src.tools.game.character_build import tool as T

        tmp = tempfile.TemporaryDirectory()
        orig_token = K.token_file
        orig_settings = T.tool_settings.settings_file
        K.token_file = lambda: pathlib.Path(tmp.name) / "acc.json"
        T.tool_settings.settings_file = lambda: pathlib.Path(tmp.name) / "s.json"
        try:
            #: 假账号（roleId='1'）—— 不该被回填
            K.save_account(K.Account(
                token="t", roles=[{"roleId": "1", "roleName": "x"}]))
            p = T.CharacterBuildPanel()
            self.assertEqual(p._feature_edit.text(), "",
                             "假的 roleId('1') 被回填了")

            #: 真特征码 → 应该回填
            K.save_account(K.Account(
                token="t",
                roles=[{"roleId": "113152489", "roleName": "银月"}]))
            p2 = T.CharacterBuildPanel()
            self.assertEqual(p2._feature_edit.text(), "113152489")
        finally:
            K.token_file = orig_token
            T.tool_settings.settings_file = orig_settings
            tmp.cleanup()

    def test_render_shows_cards(self):
        """★ 给数据能渲染出角色卡片。"""
        p = self._panel()
        p._data = {
            "at": "x",
            "base": {"energy": 1, "maxEnergy": 2},
            "roleList": [{"roleId": 1103, "roleName": "白芷", "level": 90,
                          "attributeName": "冷凝", "weaponTypeName": "音感仪",
                          "chainUnlockNum": 6, "starLevel": 4}],
            "details": {},
        }
        p._render(p._data)
        self.assertEqual(len(p._cards), 1)

    def test_refresh_disabled_when_logged_out(self):
        """未登录时「刷新数据」要禁用。

        ⚠ 原来叫 ``test_fetch_disabled_when_logged_out`` ——
        而「获取数据」按钮**已经被删掉**（用户要求：登录后自动拉），
        这条测试跟着改。
        """
        p = self._panel()
        if not p._account.logged_in:
            self.assertFalse(p._refresh_button.isEnabled())

    def test_no_fetch_button(self):
        """★ 「获取数据」按钮**不该存在**（用户："登录自动拉，为什么还有"）。

        登录后自动拉，之后想重拉点「刷新数据」—— 三个按钮太多了。
        """
        p = self._panel()
        self.assertFalse(hasattr(p, "_fetch_button"),
                         "「获取数据」按钮还在 —— 用户要求删掉（登录后自动拉）")

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
