# -*- coding: utf-8 -*-
"""★ 标题栏：图标和文字之间要留间距（2026-10-24 用户要求）。

## 用户原话

> 这里文字和图标太紧凑了，隔开一点
> （圈的是左上角「鸣潮工具箱」）

## 实测的「改之前」

``FluentTitleBar`` 把图标和标题插进同一个 ``hBoxLayout``，
而那个布局 ``spacing() == 0``::

    图标 geom = QRect(0, 15, 18, 18)     → 右缘 17
    文字 geom = QRect(18, 15, 60, 17)    → 左缘 18
    ⇒ 间隙 = 0px

所以两个元素真的贴在一起。

## 这条测什么

用 **AST** 确认 ``_setup_title_bar_spacing`` 真的设了 spacing
（不查字符串 —— 注释里也会提到 ``setSpacing``）。
"""

from __future__ import annotations

import ast
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MW = ROOT / "src" / "gui" / "main_window.py"


class TestTitleBarSpacing(unittest.TestCase):
    #: ⚠ ``main_window.py`` 里有**多个** ``__init__``（好几个类）——
    #:   只按名字找会拿到第一个不相关的。所以必须限定在 MainWindow 里。
    CLASS = "MainWindow"

    def _method(self, name: str):
        tree = ast.parse(MW.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == self.CLASS:
                for sub in node.body:
                    if (isinstance(sub, ast.FunctionDef)
                            and sub.name == name):
                        return sub
        return None

    def test_method_exists(self):
        self.assertIsNotNone(
            self._method("_setup_title_bar_spacing"),
            "没有 _setup_title_bar_spacing —— 图标和文字又会贴在一起")

    def test_sets_spacing(self):
        """★ 方法里必须真的调 ``setSpacing``。"""
        fn = self._method("_setup_title_bar_spacing")
        self.assertIsNotNone(fn)
        calls = [ast.unparse(n) for n in ast.walk(fn)
                 if isinstance(n, ast.Call)]
        self.assertTrue(any("setSpacing" in c for c in calls),
                        f"没调 setSpacing：{calls}")

    def test_gap_is_positive(self):
        """★ 间距常量必须 > 0（设成 0 等于没改）。"""
        tree = ast.parse(MW.read_text(encoding="utf-8"))
        gap = None
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if getattr(t, "id", "") == "TITLE_BAR_ICON_GAP":
                        gap = node.value.value
        self.assertIsNotNone(gap, "找不到 TITLE_BAR_ICON_GAP 常量")
        self.assertGreater(gap, 0, f"TITLE_BAR_ICON_GAP = {gap}，应该 > 0")

    def test_called_from_init(self):
        """★ ``__init__`` 里必须真的调它 —— 不调等于没改。"""
        fn = self._method("__init__")
        self.assertIsNotNone(fn)
        #: ⚠ 别用 ``ast.unparse(n)`` 然后再 ``in`` 判断 ——
        #:   unparse 对 ``self._setup_title_bar_spacing()`` 会输出
        #:   ``self._setup_title_bar_spacing()``，但外层 Call 的
        #:   unparse 只到 func 为止，容易漏。直接看 Attribute 名最稳。
        names = {
            n.func.attr
            for n in ast.walk(fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        }
        self.assertIn(
            "_setup_title_bar_spacing", names,
            "__init__ 里没有调用 _setup_title_bar_spacing —— 间距不会生效")

    def test_failure_does_not_break_startup(self):
        """★ 设间距失败不该让界面打不开（换皮肤 / 结构不同）。"""
        src = MW.read_text(encoding="utf-8")
        tree = ast.parse(src)
        fn = None
        for node in ast.walk(tree):
            if (isinstance(node, ast.FunctionDef)
                    and node.name == "_setup_title_bar_spacing"):
                fn = node
        self.assertIsNotNone(fn)
        has_try = any(isinstance(n, ast.Try) for n in ast.walk(fn))
        self.assertTrue(has_try,
                        "_setup_title_bar_spacing 没有 try/except —— "
                        "纯美化失败不该让界面打不开")


if __name__ == "__main__":
    unittest.main(verbosity=2)
