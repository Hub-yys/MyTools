# -*- coding: utf-8 -*-
"""★★★ 守岸人（ShoreKeeper）**必须保持 ok-ww 原版写法** —— 不许"修"那句 if。

    python tests/test_shorekeeper_heavy.py

## 用户 2026-10-25 的实机反馈

> 我感觉移过来的okww有问题，为什么打着打着我的角色就死了，
> 用原版可从未发生过这种情况

## 根因：我把上游的"故意刹车"当成了 bug

上游 ``ShoreKeeper.do_perform`` 末尾::

    if not self.click_resonance():
        self.heavy_click_forte(self.is_mouse_forte_full)
    self.switch_next_char()

``click_resonance()`` 返回**元组** ``(clicked, duration, has_animation)``，
元组永远真值 → ``not 元组`` 恒 False → 那句重击**永远不执行**。

看起来像死代码 bug，我 2026-10-01 把它改成了::

    self.click_resonance()
    self.heavy_click_forte(check_fun=self.is_mouse_forte_full)   # 无条件

## 为什么那是错的

``heavy_click_forte`` 内部::

    if check_fun():
        self.task.mouse_down()
        success = self.task.wait_until(lambda: not check_fun(), time_out=2)
        self.task.mouse_up()

满足条件时**长按鼠标最多 2 秒**。守岸人是**奶妈** ——
这 2 秒里完全不能治疗，而且 ``do_perform`` 每轮都可能走这个分支
→ 队友得不到奶 → **角色一个个死掉**。

上游那句"死代码"其实是**故意的刹车**：把守岸人锁在
「E + 大 + 切人」的节奏上，重击优先级远低于治疗。

## 这个文件守什么

1. ``if not self.click_resonance():`` 这层包装**必须在**
2. ``heavy_click_forte`` 必须在那个 ``if`` 的**里面**
3. 不许出现 ``heavy_click_forte(check_fun=...)`` 这种无条件写法
4. 补丁脚本不许再把它装回去
"""

from __future__ import annotations

import ast
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SK = ROOT / "vendor" / "okww" / "okww" / "char" / "ShoreKeeper.py"

#: 本机 ok-ww 的同一份文件（有就逐语句对比，没有就只用断言）
REF_SK = pathlib.Path(
    r"D:\ok-ww\data\apps\ok-ww\working\src\char\ShoreKeeper.py")


def _class() -> ast.ClassDef:
    tree = ast.parse(SK.read_text(encoding="utf-8"))
    return next(n for n in tree.body
                if isinstance(n, ast.ClassDef) and n.name == "ShoreKeeper")


def _do_perform() -> ast.FunctionDef:
    for m in _class().body:
        if isinstance(m, ast.FunctionDef) and m.name == "do_perform":
            return m
    raise AssertionError("找不到 do_perform")


class TestDoPerformKeepsUpstreamGuard(unittest.TestCase):
    """★★★ 核心：那句 ``if not self.click_resonance()`` 必须保留。"""

    def test_if_not_guard_exists(self):
        """★ 必须有 ``if not self.click_resonance():`` 这层包装。"""
        node = _do_perform()
        guards = [n for n in ast.walk(node)
                  if isinstance(n, ast.If)
                  and "click_resonance" in ast.unparse(n.test)
                  and "not" in ast.unparse(n.test)]
        self.assertTrue(
            guards,
            "守岸人的 do_perform 里**没有** ``if not self.click_resonance():`` "
            "这层保护 —— 有人把它当成 bug 修掉了。\n"
            "⚠ 那句不是死代码，是**故意的刹车**：守岸人是奶妈，"
            "无条件重击会让她长按 2 秒不放治疗 → 队友死亡。\n"
            "（2026-10-25 用户实机报过这个问题）")

    def test_heavy_attack_inside_guard(self):
        """★ ``heavy_click_forte`` 必须在那个 ``if`` 的**里面**。"""
        node = _do_perform()
        found_inside = False
        for n in ast.walk(node):
            if not (isinstance(n, ast.If)
                    and "click_resonance" in ast.unparse(n.test)):
                continue
            for inner in ast.walk(n):
                if (isinstance(inner, ast.Call)
                        and isinstance(inner.func, ast.Attribute)
                        and inner.func.attr == "heavy_click_forte"):
                    found_inside = True
        self.assertTrue(
            found_inside,
            "``heavy_click_forte`` 不在 ``if not click_resonance()`` 里面 —— "
            "那就变成了无条件重击（会让奶妈不放治疗）")

    def test_no_unconditional_check_fun_call(self):
        """★★ 不许出现我改过的那种写法 ``heavy_click_forte(check_fun=...)``。"""
        node = _do_perform()
        for n in ast.walk(node):
            if not (isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "heavy_click_forte"):
                continue
            kws = {k.arg for k in n.keywords}
            self.assertNotIn(
                "check_fun", kws,
                "又用了 ``heavy_click_forte(check_fun=...)`` —— "
                "这是我 2026-10-01 改错的那个写法（导致角色死亡）")

    def test_switch_next_char_last(self):
        """★ 最后一句必须是 ``switch_next_char()``（ok-ww 的节奏）。"""
        node = _do_perform()
        last = node.body[-1]
        self.assertIsInstance(last, ast.Expr)
        call = last.value
        self.assertIsInstance(call, ast.Call)
        self.assertEqual(getattr(call.func, "attr", ""), "switch_next_char")


class TestMatchesLocalOkww(unittest.TestCase):
    """★★ 如果有本机 ok-ww，就直接逐语句对比（最硬的证据）。"""

    def test_do_perform_identical(self):
        if not REF_SK.exists():
            self.skipTest("本机 ok-ww 不在")

        def code_of(path: pathlib.Path) -> str:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            cls = next(n for n in tree.body
                       if isinstance(n, ast.ClassDef)
                       and n.name == "ShoreKeeper")
            fn = next(m for m in cls.body
                      if isinstance(m, ast.FunctionDef)
                      and m.name == "do_perform")
            body = [n for n in fn.body
                    if not (isinstance(n, ast.Expr)
                            and isinstance(n.value, ast.Constant)
                            and isinstance(n.value.value, str))]
            return ast.unparse(
                ast.Module(body=body, type_ignores=[])).replace("src.", "okww.")

        self.assertEqual(
            code_of(REF_SK), code_of(SK),
            "do_perform 和本机 ok-ww 不一致 —— 我们不该改守岸人的战斗逻辑")

    def test_methods_identical(self):
        if not REF_SK.exists():
            self.skipTest("本机 ok-ww 不在")

        def methods(path: pathlib.Path) -> set[str]:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            cls = next(n for n in tree.body
                       if isinstance(n, ast.ClassDef)
                       and n.name == "ShoreKeeper")
            return {m.name for m in cls.body
                    if isinstance(m, ast.FunctionDef)}

        self.assertEqual(methods(REF_SK), methods(SK),
                         "守岸人的方法集合和 ok-ww 不一致")


class TestPatchScriptIsInert(unittest.TestCase):
    """★ 补丁脚本**不许**再往 vendor 里塞守岸人改动。"""

    def test_patch_does_not_touch_shorekeeper(self):
        patch = ROOT / "tools" / "install_xin_patch.py"
        if not patch.exists():
            self.skipTest("补丁脚本不存在")
        text = patch.read_text(encoding="utf-8")
        self.assertNotIn(
            "SK_BLOCK = (", text,
            "补丁脚本里还有守岸人改动的代码块 —— "
            "跑一次就会把『无条件重击』装回去，会导致角色死亡")


if __name__ == "__main__":
    unittest.main(verbosity=2)
