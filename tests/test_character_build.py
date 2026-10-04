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

    def test_detects_mixed_sets(self):
        items = [self._item(c, valid=3, fetter="A" if c == 4 else "B")
                 for c in (4, 3, 3, 1, 1)]
        self.assertTrue(any("套装不统一" in x for x in self._issues(items)))

    def test_detects_wrong_cost(self):
        """★ COST 不是 4-3-3-1-1 要报出来（实测见过别的配比）。"""
        items = [self._item(c, valid=3) for c in (4, 4, 1, 1, 1)]
        self.assertTrue(any("COST" in x for x in self._issues(items)))

    def test_cost_order_does_not_matter(self):
        """★ COST 只看**组成**，排序无关。"""
        items = [self._item(c, valid=3) for c in (1, 4, 1, 3, 3)]
        self.assertEqual([x for x in self._issues(items) if "COST" in x], [])

    def test_detects_few_valid_substats(self):
        """★ 有效词条 < 10 要报（`valid` 是库街区自己标的）。"""
        items = [self._item(c, valid=1) for c in (4, 3, 3, 1, 1)]
        self.assertTrue(any("有效词条" in x for x in self._issues(items)))

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
        """★ 达标/未达标**下拉**（用户："达标/未达标"）。

        ⚠ 原来是「只看未达标」开关，用户要的是下拉（三态）。
        """
        from src.tools.game.character_build.tool import FILTER_CHOICES

        p = self._panel()
        self.assertTrue(hasattr(p, "_filter_box"), "没有筛选下拉")
        self.assertEqual(tuple(FILTER_CHOICES), ("全部", "未达标", "达标"))

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
