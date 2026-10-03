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
import re
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core import kuro_account  # noqa: E402

TOOL = ROOT / "src" / "tools" / "game" / "character_build" / "tool.py"
PKG = ROOT / "src" / "tools" / "game" / "character_build" / "__init__.py"

#: 真正在用的 token key（和数据终端源码一致）。
#: ⚠ **不是** ``auth_token`` —— 那个是 App 桥用的，网页登录不写。
TOKEN_KEY_LITERAL = "token"


class TestGeeTestGuard(unittest.TestCase):
    """★★★ **本轮的核心修复** —— 用户："我手机没收到短信"。

    ## 事故经过（2026-10-03）

    我第一版 ``send_sms_code`` 只检查 ``code == 200``。而库街区要求人机验证时
    返回的**恰恰**是::

        {"code":200, "data":{"geeTest":true}, "msg":"请求成功", "success":true}

    **状态码和业务码都像成功**，短信却根本没发 —— 界面上写着"验证码已发送"，
    用户手机一条都没有。

    所以现在必须**额外检查 ``data.geeTest``**。
    """

    def test_real_response_raises(self):
        """★ 用**真实抓到的那条响应**验证（不是编的）。"""
        real = {"code": 200, "data": {"geeTest": True},
                "msg": "请求成功", "success": True,
                "traceId": "6d174dbb-e2f2-4962-9f72-aca9391ba450"}
        with self.assertRaises(kuro_account.NeedHumanVerify):
            kuro_account.check_sms_result(real)

    def test_plain_success_passes(self):
        """不要求人机验证时**不该**误报。"""
        ok = {"code": 200, "data": {"geeTest": False},
              "msg": "请求成功", "success": True}
        kuro_account.check_sms_result(ok)      # 不该抛

    def test_missing_data_field_passes(self):
        """没有 ``data`` 字段时按成功处理（不同版本可能不给）。"""
        kuro_account.check_sms_result({"code": 200, "msg": "请求成功"})

    def test_business_error_still_raises(self):
        with self.assertRaises(kuro_account.KuroError) as ctx:
            kuro_account.check_sms_result(
                {"code": 10000, "msg": "手机号格式有误"})
        self.assertEqual(ctx.exception.code, 10000)

    def test_need_human_verify_is_a_kuro_error(self):
        self.assertTrue(issubclass(kuro_account.NeedHumanVerify,
                                   kuro_account.KuroError))

    def test_message_says_sms_not_sent(self):
        """★ 提示必须**明说短信没发** —— 不然用户会一直等短信。"""
        exc = kuro_account.NeedHumanVerify()
        self.assertIn("没有发", str(exc))

    def test_send_sms_code_checks_geetest(self):
        """★ ``send_sms_code`` 本体也要查（不能只在纯函数里查）。

        ⚠ **必须用 AST 剥掉 docstring** —— 第一版我搜字符串 "geeTest"，
        而 ``send_sms_code`` 的**文档字符串里就写着 geeTest**
        （因为它记录的正是这个事故）→ 把代码删掉测试照样通过。
        （这个坑我在「心」那边踩过一次：**搜索式断言会被注释和 docstring 骗过**。）
        """
        source = (ROOT / "src" / "core" / "kuro_account.py").read_text(
            encoding="utf-8")
        tree = ast.parse(source)
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef)
                  and n.name == "send_sms_code")

        # ★ 只看**代码**：把 docstring 摘掉
        body = [stmt for stmt in fn.body
                if not (isinstance(stmt, ast.Expr)
                        and isinstance(stmt.value, ast.Constant)
                        and isinstance(stmt.value.value, str))]
        code = "\n".join(ast.get_source_segment(source, stmt) or ""
                         for stmt in body)

        self.assertIn("geeTest", code,
                      "send_sms_code 的**代码**里没检查 geeTest —— "
                      "又会把「要求人机验证」当成发送成功")
        self.assertIn("NeedHumanVerify", code,
                      "检查了却没抛 NeedHumanVerify")


class TestBrowserLogin(unittest.TestCase):
    """★ 内嵌浏览器登录（现在**真正在用**的路径）。"""

    def test_login_dialog_module_exists(self):
        self.assertTrue(
            (ROOT / "src" / "tools" / "game" / "character_build"
             / "login_dialog.py").exists())

    def test_local_storage_keys_are_the_real_ones(self):
        """★★★ **本轮的核心修复** —— 用户："刚登陆 怎么提示过期了"。

        ## 事故

        我第一版读 ``localStorage.auth_token`` —— **那是错的**。
        ``auth_token`` 是给 **App 桥**用的
        （``jsBridge.callHandler("getUserInfo")``），**网页登录根本不写它** ——
        读出来永远是空串，而我把空串当成"已拿到令牌"，服务器回 220。

        ## 真正在用的（从数据终端源码挖出来）

        数据终端自己的请求拦截器::

            e.headers.token   = localStorage.getItem("token") || "";
            e.headers.devCode = localStorage.getItem("REQUEST_IP") + ", "
                                + navigator.userAgent;
            e.headers.did     = ...

        → 所以 key 是 **``token``**，devCode 要**拼** ``REQUEST_IP`` + UA。
        """
        from src.tools.game.character_build import login_dialog

        self.assertEqual(login_dialog.TOKEN_KEY, "token",
                         "token 的 key 必须是 'token'")
        self.assertNotEqual(
            login_dialog.TOKEN_KEY, "auth_token",
            "auth_token 是 App 桥用的，网页登录不写它 —— "
            "读它永远是空串（这就是『刚登录就过期』的原因）")
        self.assertEqual(login_dialog.REQUEST_IP_KEY, "REQUEST_IP",
                         "devCode 的前半段来自 REQUEST_IP")

    def test_read_js_handles_the_real_keys(self):
        """★ 读取脚本要用**真 key**，且 devCode 要**真的拼起来**。

        ⚠ 第一版这条只断言脚本里出现 ``navigator.userAgent`` ——
        而 ``var ua = navigator.userAgent || ""`` 那**一行声明**就满足了，
        于是把 ``dev_code`` 改成不再拼 ua（退回旧行为）测试照样通过
        （实测突变时发现失效）。

        所以现在断言的是**赋值本身**：``dev_code`` 那一行必须用到 ``ua``。

        ⚠ ``auth_token`` 现在**允许出现** —— 它是「主 key 读不到时的兜底」
        （个别版本也许写那边）。但必须**不是主 key**。
        """
        from src.tools.game.character_build import login_dialog

        js = login_dialog._READ_JS
        self.assertIn(TOKEN_KEY_LITERAL, js)
        self.assertIn("REQUEST_IP", js)

        # ★ 主 key 必须是 ``token``，不能是 auth_token
        m = re.search(r'var\s+primary\s*=\s*localStorage\.getItem\(([^)]+)\)',
                      js)
        self.assertIsNotNone(m, "读取脚本里没有 primary 的赋值")
        self.assertIn(TOKEN_KEY_LITERAL, m.group(1),
                      f"主 key 不是 token（现在读的是 {m.group(1)}）—— "
                      f"auth_token 是 App 桥用的，网页登录不写它")

        # ★ dev_code 那一行必须真的拼 ua + ip
        #   ⚠ 表达式是个三元（``ip ? (ip + ", " + ua) : ua``），
        #     所以用**整行**判断，不能只截到第一个逗号。
        line = next((ln for ln in js.splitlines()
                     if "dev_code" in ln and ":" in ln), "")
        self.assertTrue(line, "读取脚本里没有 dev_code 赋值")
        self.assertIn("ua", line,
                      f"dev_code 没有拼 userAgent（现在写的是 {line.strip()!r}）"
                      f" —— 数据终端的拦截器是 "
                      f'REQUEST_IP + ", " + navigator.userAgent')
        self.assertIn("ip", line,
                      f"dev_code 没有用 REQUEST_IP（现在写的是 "
                      f"{line.strip()!r}）")

    def test_empty_token_is_not_login_success(self):
        """★★ 空 token **不能**当成登录成功。

        上一版读到空串也往下走 —— 日志写着"已拿到令牌"，
        服务器却说"登录已过期"，用户看到的就是自相矛盾的提示。

        ⚠ 用 AST 查：``_on_read`` 里必须有 ``if not token: ... return``
        （搜索字符串会被注释和变量名骗过 —— 这个坑踩过三次了）。
        """
        import ast as _ast

        source = (ROOT / "src" / "tools" / "game" / "character_build"
                  / "login_dialog.py").read_text(encoding="utf-8")
        tree = _ast.parse(source)
        fn = next(n for n in _ast.walk(tree)
                  if isinstance(n, _ast.FunctionDef) and n.name == "_on_read")

        # 找形如 ``if not <name>:`` 且体内有 return 的分支
        guarded = False
        for node in _ast.walk(fn):
            if not isinstance(node, _ast.If):
                continue
            test = node.test
            if not isinstance(test, _ast.UnaryOp):
                continue
            if not isinstance(test.op, _ast.Not):
                continue
            if not any(isinstance(s, _ast.Return) for s in node.body):
                continue
            # ``not token`` 里的名字必须是个变量（token 或其别名）
            name = getattr(test.operand, "id", "")
            if name and "token" in name.lower():
                guarded = True
                break

        self.assertTrue(
            guarded,
            "_on_read 里没有 `if not token: return` —— "
            "空令牌会被当成登录成功（上一版就是这么错的）")

    def test_uses_separate_profile(self):
        """★ 用**独立** profile —— 不碰用户平时的浏览器数据。

        ⚠ 第一版只断言源码里有 ``QWebEngineProfile`` 这个词，
        而 ``QWebEngineProfile.defaultProfile()`` **也含这个词** →
        换成默认 profile（会污染用户浏览器数据）测试照样通过。

        所以现在用 AST 查：必须**构造**一个带名字的 profile，
        且不能出现 ``defaultProfile``。
        """
        source = (ROOT / "src" / "tools" / "game" / "character_build"
                  / "login_dialog.py").read_text(encoding="utf-8")
        self.assertNotIn("defaultProfile", source,
                         "用了默认 profile —— 会读写用户平时的浏览器数据")

        tree = ast.parse(source)
        # 必须有一处 QWebEngineProfile(名字, ...) 的构造调用
        constructed = [
            n for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and (getattr(n.func, "id", "") == "QWebEngineProfile"
                 or getattr(n.func, "attr", "") == "QWebEngineProfile")
        ]
        self.assertTrue(constructed,
                        "没有自己构造 QWebEngineProfile —— 没隔离浏览器数据")
        self.assertTrue(PROFILE_NAME_CONST(source),
                        "profile 名字不是常量 —— 没法保证隔离")


def PROFILE_NAME_CONST(source: str) -> bool:
    """源码里有没有 ``PROFILE_NAME = "..."`` 这样的常量。"""
    import re

    return bool(re.search(r'^PROFILE_NAME\s*=\s*["\'][^"\']+["\']',
                          source, re.M))


class TestLoginDialogSource(unittest.TestCase):

    def test_login_url_is_the_forum_home(self):
        """★★★ **本轮的核心修复** —— 用户："这也没办法登陆啊"。

        我第一版把登录地址写成 ``https://www.kurobbs.com/`` ——
        那个地址会**跳转到 ``main.html``，页面上只有页脚**（版权信息、
        友情链接），**没有任何登录按钮**，用户打开窗口后无从下手。

        实测对比::

            https://www.kurobbs.com/          → 只有页脚，**无登录入口**
            https://www.kurobbs.com/mc/home/9 → ★ 有「立即登录」按钮

        → 所以地址必须是**论坛首页**。这条测试钉死它，防止又改回去。
        """
        from src.tools.game.character_build import login_dialog

        self.assertEqual(
            login_dialog.LOGIN_URL, "https://www.kurobbs.com/mc/home/9",
            "登录地址不对 —— 必须是论坛首页（根路径只有页脚，没有登录按钮）")
        self.assertNotEqual(
            login_dialog.LOGIN_URL.rstrip("/"), "https://www.kurobbs.com",
            "根路径没有登录入口，用户会无从下手")

    def test_auto_clicks_login_button(self):
        """★ 要**自动点**「立即登录」把弹窗拉出来。

        不点的话用户还得自己在页面顶部找那个按钮（SPA 渲染完才出现）。
        实测点完之后页面上会出现两个输入框：

            请输入手机号码
            请输入6位验证码
        """
        from src.tools.game.character_build import login_dialog

        js = login_dialog._CLICK_LOGIN_JS
        self.assertIn("立即登录", js)
        self.assertIn("click", js)

    def test_clicks_after_page_load(self):
        """★ 点击要真的**接在页面加载之后**，而且真的调用点击脚本。

        ⚠ 第一版这条只搜字符串 ``"_CLICK_LOGIN_JS"`` —— 而那个名字在
        ``_click_login`` 自己的**方法体里**就出现了，于是把
        ``_on_page_loaded`` 里那句 ``QTimer.singleShot(3000, self._click_login)``
        删掉，测试照样通过（**护栏失效**，实测抓到的）。

        所以现在用 AST 查**调用链**：
        ``_on_page_loaded`` 必须引用 ``_click_login``，
        且 ``_click_login`` 必须真的执行 ``_CLICK_LOGIN_JS``。
        """
        source = (ROOT / "src" / "tools" / "game" / "character_build"
                  / "login_dialog.py").read_text(encoding="utf-8")
        self.assertIn("loadFinished", source,
                      "没接 loadFinished —— 页面还没加载就点，按钮不存在")

        tree = ast.parse(source)

        def method(name):
            return next(
                (n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef) and n.name == name), None)

        loaded = method("_on_page_loaded")
        self.assertIsNotNone(loaded, "没有 _on_page_loaded")
        loaded_names = {
            getattr(n, "id", None) or getattr(n, "attr", None)
            for n in ast.walk(loaded)
        }
        self.assertIn(
            "_click_login", loaded_names,
            "★ _on_page_loaded 里没有引用 _click_login —— "
            "页面加载完不会自动点「立即登录」，用户还是找不到登录入口")

        click = method("_click_login")
        self.assertIsNotNone(click, "没有 _click_login")
        click_code = "\n".join(
            ast.get_source_segment(source, stmt) or ""
            for stmt in click.body
            if not (isinstance(stmt, ast.Expr)
                    and isinstance(stmt.value, ast.Constant)
                    and isinstance(stmt.value.value, str)))
        self.assertIn("_CLICK_LOGIN_JS", click_code,
                      "_click_login 没执行点击脚本")

    def test_login_url_is_correct_host(self):
        from src.tools.game.character_build import login_dialog

        self.assertTrue(login_dialog.LOGIN_URL.startswith("https://"))

    def test_account_from_browser(self):
        """★ 从浏览器拿到的东西能组装出 Account。"""
        acc = kuro_account.account_from_browser(
            "tok_abc", "dev_xyz", {"userName": "某人", "mobile": "13800138000"})
        self.assertEqual(acc.token, "tok_abc")
        self.assertEqual(acc.dev_code, "dev_xyz")
        self.assertEqual(acc.mobile_tail, "8000")
        self.assertTrue(acc.logged_in)

    def test_account_from_browser_rejects_empty_token(self):
        with self.assertRaises(kuro_account.KuroError):
            kuro_account.account_from_browser("", "dev")

    def test_account_from_browser_drops_full_mobile(self):
        """★★ **只留后 4 位** —— 完整号码不能留在 profile 里。"""
        acc = kuro_account.account_from_browser(
            "tok", "", {"mobile": "13800138000"})
        self.assertEqual(acc.mobile_tail, "8000")
        self.assertNotIn("mobile", acc.profile,
                         "完整手机号还留在 profile 里 —— 隐私问题")


class TestDevCodeIsDynamic(unittest.TestCase):
    """★ devCode 不能硬编码（实测官方网页版会写一个动态值）。"""

    def test_headers_accept_dev_code(self):
        h = kuro_account._headers("tok", "dynamic_dev_code")
        self.assertEqual(h["devcode"], "dynamic_dev_code")

    def test_falls_back_when_empty(self):
        h = kuro_account._headers("tok", "")
        self.assertEqual(h["devcode"], kuro_account.DEV_CODE_FALLBACK)

    def test_account_stores_dev_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "a.json"
            kuro_account.save_account(
                kuro_account.Account(token="t", dev_code="dyn"), path)
            self.assertEqual(kuro_account.load_account(path).dev_code, "dyn")


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
