# -*- coding: utf-8 -*-
"""官方攻略站客户端（``src/core/wuwa_guide.py``）—— 推荐属性 = 达标标准。

    python tests/test_wuwa_guide.py

## 这套接口是**第三套**，别和前两套混

============================  ==========================  ==============
用途                           域名                         认证
============================  ==========================  ==============
图鉴                            ``api.kurobbs.com/wiki``    公开
**我的账号数据**                ``api.kurobbs.com/aki``     数据令牌
**官方推荐标准（本模块）**      ``guide-server.aki-game``   **公开**
============================  ==========================  ==============

## 这里**不打真实网络**

真实响应已经实测验证过（见下），单测用**真实结构的 fixture** 保证：
字段名没写错、解析没写错、错误处理不炸。

实测样例（2026-10-05）::

    白芷（1103）  共鸣效率 >=260.0% / 治疗效果加成 >=40.0% / 生命 >=24000
    今汐（1311）  暴击 >=70.0% / 暴击伤害 >=260.0% / 共鸣效率 >=120.0%
    守岸人（1505）共鸣效率 >=230.0% / 生命 >=45000
"""

from __future__ import annotations

import ast
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core import wuwa_guide as G  # noqa: E402

CORE = ROOT / "src" / "core" / "wuwa_guide.py"


def _strategy_fixture() -> dict:
    """一份**真实结构**的攻略详情（照抄接口返回）。"""
    return {
        "id": 10228,
        "role": {"roleGbId": "1311", "star": 5},
        "roleAttribute": {
            "items": [
                {
                    "gbId": "8-2",
                    "pictureUrl": "https://guide-res.aki-game.com/a.png",
                    "texts": [{"language": "zh-Hans", "name": "暴击"}],
                    "recommendAmount": "70.0%",
                    "operation": 6,
                    "currentAmount": "0.0%",
                    "isFinished": False,
                },
                {
                    "gbId": "9-2",
                    "pictureUrl": "https://guide-res.aki-game.com/b.png",
                    "texts": [{"language": "zh-Hans", "name": "暴击伤害"}],
                    "recommendAmount": "260.0%",
                    "operation": 6,
                    "currentAmount": "0.0%",
                    "isFinished": False,
                },
                {
                    "gbId": "11-2",
                    "pictureUrl": "https://guide-res.aki-game.com/c.png",
                    "texts": [{"language": "zh-Hans", "name": "共鸣效率"}],
                    "recommendAmount": "120.0%",
                    "operation": 6,
                    "currentAmount": "0.0%",
                    "isFinished": False,
                },
            ],
            "isFinished": False,
        },
        "echo": {"main": {"echoProps": {"gbId": "60002255"}}},
        "weapon": {"weapon": {"gbId": "21050024"}},
        "roleSkill": {"addPointSequence": []},
        "teammate": {"members": []},
    }


class TestEndpoints(unittest.TestCase):
    """接口路径和域名 —— 抄错一个字符整个功能就没了。"""

    def test_api_root(self):
        self.assertEqual(G.API_ROOT, "https://guide-server.aki-game.com")

    def test_endpoints(self):
        self.assertEqual(G.API_INTRO_LIST, "/introduction/list")
        self.assertEqual(G.API_INTRO_INFO, "/introduction/info")
        self.assertEqual(G.API_ROLE_INFO, "/role/info")

    def test_language_header(self):
        """★ 实测缺 ``x-language`` 拿不到中文。"""
        h = G._headers()
        self.assertEqual(h.get("x-language"), "zh-Hans")

    def test_headers_have_referer(self):
        """★ 实测要带 ``Referer``（否则可能被拒）。"""
        h = G._headers()
        self.assertIn("Referer", h)
        self.assertIn("mcguide", h["Referer"])


class TestParamName(unittest.TestCase):
    """★★★ 参数名是 **``roleGbId``** —— 这轮踩得最狠的坑。

    ====================  ==========================
    参数                   实测结果
    ====================  ==========================
    **``roleGbId``**      ✅ ``200 ok``
    ``roleId``            ❌ ``500 server error``
    ``role_id``           ❌ ``500``
    ``id``                ❌ ``500``
    ====================  ==========================
    """

    def test_uses_role_gb_id(self):
        captured: dict = {}

        def fake_get(path, params, **kw):
            captured["path"] = path
            captured["params"] = params
            return {"code": 200, "message": "ok", "data": []}

        orig = G._get
        G._get = fake_get
        try:
            G.fetch_strategy_id(1311)
        finally:
            G._get = orig

        self.assertIn("roleGbId", captured["params"],
                      "★ 参数名不是 roleGbId —— 实测会回 500")
        self.assertNotIn("roleId", captured["params"])
        self.assertNotIn("role_id", captured["params"])
        self.assertEqual(captured["path"], "/introduction/list")

    def test_strategy_id_param(self):
        captured: dict = {}

        def fake_get(path, params, **kw):
            captured["params"] = params
            return {"code": 200, "data": {}}

        orig = G._get
        G._get = fake_get
        try:
            G.fetch_strategy(1311, 10228)
        finally:
            G._get = orig
        #: ⚠ roleGbId 和 id **都要**给
        self.assertEqual(str(captured["params"].get("roleGbId")), "1311")
        self.assertEqual(str(captured["params"].get("id")), "10228")


class TestParseAmount(unittest.TestCase):
    def test_percent(self):
        self.assertEqual(G.parse_amount("70.0%"), 70.0)

    def test_plain_number(self):
        self.assertEqual(G.parse_amount("2200"), 2200.0)
        self.assertEqual(G.parse_amount("50000"), 50000.0)

    def test_thousand_separator(self):
        self.assertEqual(G.parse_amount("50,000"), 50000.0)

    def test_garbage(self):
        for bad in ("", None, "abc", "—", "%"):
            with self.subTest(bad=bad):
                self.assertIsNone(G.parse_amount(bad))

    def test_unit_of(self):
        self.assertEqual(G.unit_of("70.0%"), "%")
        self.assertEqual(G.unit_of("2200"), "")
        self.assertEqual(G.unit_of(""), "")


class TestParseRecommendAttrs(unittest.TestCase):
    """★★ 从攻略详情里解析「推荐属性」—— 这是**达标标准**。"""

    def test_parses_all_items(self):
        attrs = G.parse_recommend_attrs(_strategy_fixture())
        self.assertEqual([a["name"] for a in attrs],
                         ["暴击", "暴击伤害", "共鸣效率"])
        self.assertEqual([a["value"] for a in attrs], [70.0, 260.0, 120.0])
        self.assertEqual([a["symbol"] for a in attrs], ["≥", "≥", "≥"])

    def test_keeps_raw_text(self):
        """★ 原始字符串要留着（界面上直接显示"≥70.0%"）。"""
        attrs = G.parse_recommend_attrs(_strategy_fixture())
        self.assertEqual(attrs[0]["recommend"], "70.0%")
        self.assertEqual(attrs[0]["unit"], "%")

    def test_icon_url(self):
        attrs = G.parse_recommend_attrs(_strategy_fixture())
        self.assertTrue(attrs[0]["icon_url"].startswith("https://"))

    def test_empty_and_garbage(self):
        """★ 空数据不该崩。"""
        for bad in ({}, {"roleAttribute": None}, {"roleAttribute": {}},
                    {"roleAttribute": {"items": None}},
                    {"roleAttribute": {"items": [None, 1, "x"]}}):
            with self.subTest(bad=str(bad)[:40]):
                self.assertEqual(G.parse_recommend_attrs(bad), [])

    def test_skips_items_without_name(self):
        """没名字的条目跳过（实测偶尔有占位项）。"""
        got = G.parse_recommend_attrs({"roleAttribute": {"items": [
            {"recommendAmount": "1%", "texts": []},
            {"texts": [{"language": "zh-Hans", "name": "攻击"}],
             "recommendAmount": "2200"},
        ]}})
        self.assertEqual([a["name"] for a in got], ["攻击"])

    def test_absolute_value_has_no_unit(self):
        """★ 绝对值属性（生命/攻击）不该被当成百分比。"""
        got = G.parse_recommend_attrs({"roleAttribute": {"items": [
            {"texts": [{"name": "生命"}], "recommendAmount": "24000"},
        ]}})
        self.assertEqual(got[0]["value"], 24000.0)
        self.assertEqual(got[0]["unit"], "")

    def test_operation_maps_to_symbol(self):
        """★★★ ``operation`` → 符号 —— **这张表是从官方 JS 挖出来的**。

        ## 为什么单列一条（2026-10-05 我猜错过）

        官方页面把数字映射成符号::

            [{label:"=",  value: de.Equality},
             {label:">",  value: de.GreaterThan},
             {label:"≥",  value: de.GreaterThanOrEqual},
             {label:"≠",  value: de.Inequality},
             {label:"<",  value: de.LessThan},
             {label:"≤",  value: de.LessThanOrEqual}]

            Equality=1  Inequality=2  LessThan=3
            GreaterThan=4  LessThanOrEqual=5  GreaterThanOrEqual=6

        ⚠⚠ **我第一版猜的**：``4 → "<="``、``5 → ">"`` —— **两个都错**。
        结果安可（``operation=4``）被判成"暴击要 ≤65%"，
        而实际是"**暴击要 >65%**"。

        **猜枚举值不可靠，必须挖源码。**
        """
        self.assertEqual(G.OPERATION_SYMBOLS[1], "=")
        self.assertEqual(G.OPERATION_SYMBOLS[2], "≠")
        self.assertEqual(G.OPERATION_SYMBOLS[3], "<")
        self.assertEqual(G.OPERATION_SYMBOLS[4], ">",
                         "★ 4 是 '>' 不是 '<='（我第一版就错在这）")
        self.assertEqual(G.OPERATION_SYMBOLS[5], "≤",
                         "★ 5 是 '≤' 不是 '>'")
        self.assertEqual(G.OPERATION_SYMBOLS[6], "≥")

    def test_symbol_via_parse(self):
        for op, sym in ((3, "<"), (4, ">"), (5, "≤"), (6, "≥"),
                        (1, "="), (2, "≠")):
            with self.subTest(op=op):
                got = G.parse_recommend_attrs({"roleAttribute": {"items": [
                    {"texts": [{"name": "x"}], "recommendAmount": "1",
                     "operation": op}]}})
                self.assertEqual(got[0]["symbol"], sym)

    def test_unknown_operation_defaults_to_ge(self):
        got = G.parse_recommend_attrs({"roleAttribute": {"items": [
            {"texts": [{"name": "x"}], "recommendAmount": "1",
             "operation": 999}]}})
        self.assertEqual(got[0]["symbol"], "≥")


class TestMeets(unittest.TestCase):
    """★★ ``meets`` —— 按官方符号判达标（**不能写死"越大越好"**）。"""

    def test_greater_or_equal(self):
        self.assertTrue(G.meets(70, 70, "≥"))
        self.assertTrue(G.meets(71, 70, "≥"))
        self.assertFalse(G.meets(69, 70, "≥"))

    def test_greater_than_is_strict(self):
        """★ ``>`` 是**严格**大于（安可那条就是这个）。"""
        self.assertFalse(G.meets(250, 250, ">"))
        self.assertTrue(G.meets(250.1, 250, ">"))

    def test_less_or_equal(self):
        self.assertTrue(G.meets(5, 6, "≤"))
        self.assertFalse(G.meets(7, 6, "≤"))

    def test_equality(self):
        self.assertTrue(G.meets(5, 5, "="))
        self.assertFalse(G.meets(5, 6, "="))

    def test_unknown_symbol_is_not_a_problem(self):
        """★ 不认识的符号 → 当成达标（不瞎报问题）。"""
        for bad in ("", None, "???", "≥≥"):
            with self.subTest(bad=bad):
                self.assertTrue(G.meets(1, 999, bad))


class TestErrorHandling(unittest.TestCase):
    def test_business_error_raises(self):
        def fake_get(path, params, **kw):
            return {"code": 500, "message": "server error"}

        orig = G._get
        G._get = fake_get
        try:
            with self.assertRaises(G.GuideError) as cm:
                G.fetch_strategy_id(1311)
        finally:
            G._get = orig
        self.assertEqual(cm.exception.code, 500)
        self.assertIn("server error", str(cm.exception))

    def test_error_carries_path(self):
        def fake_get(path, params, **kw):
            return {"code": 500, "message": "x"}

        orig = G._get
        G._get = fake_get
        try:
            with self.assertRaises(G.GuideError) as cm:
                G.fetch_role_info(1311)
        finally:
            G._get = orig
        self.assertIn("/role/info", str(cm.exception))

    def test_fetch_recommend_never_raises(self):
        """★★ 一个角色查不到不该让**整个拉取**失败。

        实测 43 个角色都有攻略，但官方随时可能加新角色而还没出攻略 ——
        那时应该返回空 ``attrs``，不是抛异常。
        """
        def boom(*a, **kw):
            raise G.GuideError(500, "server error")

        orig = G.fetch_strategy_id
        G.fetch_strategy_id = boom
        try:
            got = G.fetch_recommend(9999)
        finally:
            G.fetch_strategy_id = orig
        self.assertEqual(got["attrs"], [])
        self.assertIsNone(got["strategy_id"])

    def test_fetch_recommend_handles_no_strategy(self):
        orig = G.fetch_strategy_id
        G.fetch_strategy_id = lambda *a, **kw: None
        try:
            got = G.fetch_recommend(9999)
        finally:
            G.fetch_strategy_id = orig
        self.assertEqual(got["attrs"], [])


class TestNoNetworkOnImport(unittest.TestCase):
    def test_module_import_has_no_top_level_calls(self):
        tree = ast.parse(CORE.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                func = node.value.func
                name = getattr(func, "id", None) or getattr(func, "attr", None)
                self.assertNotIn(name, ("urlopen", "_get", "_call"))


class TestSeparateFromOtherModules(unittest.TestCase):
    """★ 三套接口**不能互相 import**（各管各的）。"""

    def test_guide_does_not_import_others(self):
        tree = ast.parse(CORE.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                self.assertNotIn("kuro_account", mod)
                self.assertNotIn("wuwa_update", mod)
            elif isinstance(node, ast.Import):
                names = " ".join(a.name for a in node.names)
                self.assertNotIn("kuro_account", names)
                self.assertNotIn("wuwa_update", names)

    def test_others_do_not_import_guide(self):
        for name in ("kuro_account.py", "wuwa_update.py"):
            with self.subTest(module=name):
                text = (ROOT / "src" / "core" / name).read_text(
                    encoding="utf-8")
                self.assertNotIn("wuwa_guide", text,
                                 f"{name} 不该依赖攻略站模块")


if __name__ == "__main__":
    unittest.main(verbosity=2)
