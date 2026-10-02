"""守岸人必须**会放重击**（修 ok-ww 上游的一个 bug）。

    python tests/test_shorekeeper_heavy.py

## 上游的 bug

ok-ww 原版 ``ShoreKeeper.do_perform`` 写的是::

    if not self.click_resonance():
        self.heavy_click_forte(self.is_mouse_forte_full)

``click_resonance()`` 返回的是**元组** ``(clicked, duration, has_animation)``
—— 元组**永远是真值**，所以 ``not 元组`` **永远是 False**，
那句重击是**死代码**。用户实测："ok-ww 的守岸人不释放重击"。

## 修法

摘掉 ``if not ...`` 包装，改成无条件调用 ——
和 ok-ww 自己的 **Changli**（同样是"攒满→重击"型）写法一致：

    self.click_resonance()
    self.heavy_click_forte(check_fun=self.is_mouse_forte_full)

``heavy_click_forte`` 内部会先调 ``check_fun()``（能量满没满），
没满就什么都不做，所以无条件调用是安全的。

⚠ 这处改动在 **vendor/** 里 —— 上游更新会冲掉，
靠 ``tools/install_xin_patch.py`` 重放（和「心」的支持同一套机制）。
"""

from __future__ import annotations

import ast
import pathlib
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor" / "okww"
SK = VENDOR / "okww" / "char" / "ShoreKeeper.py"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _do_perform_node(text: str) -> ast.FunctionDef:
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "do_perform":
            return node
    raise AssertionError("ShoreKeeper.py 里没有 do_perform")


class TestHeavyAttackIsCalled(unittest.TestCase):
    """★ 重击必须是**无条件调用**，不能被 if 包着。"""

    def setUp(self):
        self.text = SK.read_text(encoding="utf-8")
        self.fn = _do_perform_node(self.text)

    def test_heavy_click_forte_present(self):
        calls = [
            n for n in ast.walk(self.fn)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "heavy_click_forte"
        ]
        self.assertTrue(calls, "do_perform 里根本没有 heavy_click_forte —— "
                               "守岸人不会放重击")

    def test_not_wrapped_in_if(self):
        """★★ 这条就是那个 bug 的护栏。

        上游原来写成 ``if not self.click_resonance(): heavy_click_forte(...)``
        —— ``click_resonance()`` 返回元组（永远真值），
        所以重击**永远执行不到**。
        """
        ifs = [n for n in ast.walk(self.fn) if isinstance(n, ast.If)]
        for node in ifs:
            for sub in ast.walk(node):
                if (isinstance(sub, ast.Call)
                        and isinstance(sub.func, ast.Attribute)
                        and sub.func.attr == "heavy_click_forte"):
                    line = self.text.splitlines()[sub.lineno - 1].strip()
                    self.fail(
                        f"heavy_click_forte 又被 if 包住了（L{sub.lineno}: "
                        f"{line}）—— 那就是上游的 bug：click_resonance() "
                        f"返回元组、永远真值，重击成了死代码")

    def test_passes_check_fun(self):
        """要传 ``check_fun`` —— 它内部靠这个判断能量满没满。"""
        for node in ast.walk(self.fn):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "heavy_click_forte"):
                kwargs = {k.arg for k in node.keywords}
                self.assertIn(
                    "check_fun", kwargs,
                    "heavy_click_forte 没传 check_fun —— 它会用默认值，"
                    "可能和守岸人的能量条检测不一致")

    def test_resonance_still_called(self):
        """E 不能因为修 bug 被删掉。"""
        names = {
            n.func.attr for n in ast.walk(self.fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        }
        for want in ("click_resonance", "click_liberation", "click_echo"):
            with self.subTest(want=want):
                self.assertIn(want, names, f"{want} 不见了")


class TestPatchScript(unittest.TestCase):
    """★ 这处改动在 vendor 里 —— 上游更新会冲掉，补丁脚本要能重放。"""

    def test_patch_reports_all_installed(self):
        result = subprocess.run(
            [sys.executable, "tools/install_xin_patch.py"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", cwd=ROOT)
        out = (result.stdout or "") + (result.stderr or "")
        self.assertIn("全部就位", out, f"补丁脚本报有缺失：\n{out}")

    def test_patch_mentions_shorekeeper(self):
        result = subprocess.run(
            [sys.executable, "tools/install_xin_patch.py"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", cwd=ROOT)
        out = (result.stdout or "") + (result.stderr or "")
        self.assertIn("守岸人", out,
                      "补丁脚本没管守岸人 —— 上游更新后重击 bug 会回来")

    def test_patch_is_idempotent(self):
        """跑两次不该把代码插重复。"""
        before = SK.read_text(encoding="utf-8")
        subprocess.run(
            [sys.executable, "tools/install_xin_patch.py", "--apply"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", cwd=ROOT)
        after = SK.read_text(encoding="utf-8")
        self.assertEqual(before, after, "补丁跑第二次改了文件 —— 不幂等")

        # ⚠ 只数**真代码**里的调用 —— 注释里提到 heavy_click_forte 不算
        #   （第一版数了整个文本，被注释里的说明骗了）
        calls = [
            n for n in ast.walk(_do_perform_node(after))
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "heavy_click_forte"
        ]
        self.assertEqual(len(calls), 1,
                         f"do_perform 里有 {len(calls)} 处 heavy_click_forte "
                         f"调用（应该只有 1 处）")


if __name__ == "__main__":
    unittest.main(verbosity=2)
