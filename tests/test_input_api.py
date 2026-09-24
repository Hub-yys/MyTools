"""输入层 API 的参数个数 + 报错归因（2026-09-27 事故单测）。

## 事故

用户按提示**已经用管理员身份运行**了，仍然"运行任务失败"。日志里的真因是：

    File ".../echo_enhance/controller.py", line 337, in press
        win32api.keybd_event(vk, 0, win32con.KEYEVENTF_KEYUP, 0, 0)
    TypeError: keybd_event() takes at most 4 arguments (5 given)

``keybd_event`` 是 **4** 个参数，照着隔壁 ``mouse_event`` 的 5 个抄，多传了一个。

## 但真正害人的不是这个 TypeError，是它被"洗白"了

``_wrap_input_error`` 原来**无条件**把任何异常翻译成"权限不足"，
于是上面那句变成了：

    权限不足：游戏以管理员身份运行，本工具权限比它低…
    （本工具 管理员级）
    本工具已经是管理员权限，仍然被拦 —— 这多半是游戏反外挂（ACE）拦下了合成输入

用户照着提示重新提权、去查反外挂、去怀疑输入方式，**全白费**。
日志里明明写着 ``takes at most 4 arguments (5 given)``，正是那一句最有用却最被埋没。

所以这里守两件事：

1. 代码自身的错误（``TypeError`` 之类）**不许**被归因成权限问题；
2. ``keybd_event`` 的参数个数别超上限。

## ⚠ 参数个数的"事实来源"是 pywin32，不是微软官方签名

两者**不一致**，抄错就反过来把正确代码判成错的。本机实测（2026-09-27）：

| API | 官方 C 签名 | pywin32 实际 |
|---|---|---|
| ``keybd_event`` | 4 | 最多 4（5 个 → TypeError） |
| ``mouse_event`` | 5 | **4、5 都接受**（宽松，不能拿"必须 5"当护栏） |
| ``SetCursorPos`` | 2（x, y） | **正好 1**（要传 tuple；传 2 个反而 TypeError） |

``SetCursorPos`` 那行尤其能说明问题：项目里 3 处 ``SetCursorPos((x, y))`` 是**对的**，
但若照官方签名写成"必须 2 个"，护栏就会报 3 个假 FAIL。
"""

from __future__ import annotations

import ast
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.tools.game.echo_enhance import controller  # noqa: E402

#: 参数个数的**上限**（pywin32 实测）。超过 → 调用当场 TypeError。
MAX_ARGS = {
    "keybd_event": 4,
}

#: 参数个数必须**正好等于**（pywin32 实测；注意不是官方签名的个数）。
EXACT_ARGS = {
    "SetCursorPos": 1,      # 要传 (x, y) 元组，不是两个参数
}


class TestProgrammingErrorsAreNotBlamedOnPermission(unittest.TestCase):
    """代码自身的错误不能被包装成"权限不足"。"""

    def test_typeerror_is_not_input_blocked(self):
        """★ 本次事故的核心：参数个数错 → 必须暴露成代码问题。"""
        exc = TypeError("keybd_event() takes at most 4 arguments (5 given)")
        wrapped = controller._wrap_input_error("按键 B", exc)

        self.assertNotIsInstance(wrapped, controller.InputBlocked)
        # 原始文本必须留着 —— 它才是真正能定位问题的那句
        self.assertIn("takes at most 4 arguments", str(wrapped))
        # 而且不能反过来去怪用户权限
        self.assertNotIn("反外挂", str(wrapped))
        self.assertNotIn("管理员身份运行", str(wrapped))

    def test_attribute_error_is_not_input_blocked(self):
        """函数名打错（AttributeError）同理 —— 别拿权限糊过去。"""
        wrapped = controller._wrap_input_error(
            "点击", AttributeError("module has no attribute 'SetCurorPos'"))
        self.assertNotIsInstance(wrapped, controller.InputBlocked)
        self.assertIn("SetCurorPos", str(wrapped))

    def test_permission_error_still_input_blocked(self):
        """★ 反向：真的发不出去时**仍然**要报权限，别矫枉过正。"""
        wrapped = controller._wrap_input_error(
            "按键 B", PermissionError(5, "拒绝访问。"))
        self.assertIsInstance(wrapped, controller.InputBlocked)

    def test_zero_winerror_still_input_blocked(self):
        """pywin32 的 ``(0, 'SetCursorPos', 'No error message is available')``。

        错误码 0 是 UIPI 在输入层直接拒了（不给说明），必须保留翻译。
        """
        wrapped = controller._wrap_input_error(
            "移动光标", OSError(0, "SetCursorPos", "No error message is available"))
        self.assertIsInstance(wrapped, controller.InputBlocked)

    def test_programming_error_types_cover_the_usual_suspects(self):
        """归因表是**常量**，且覆盖住常见的"代码写错了"。

        别让后来人为了消掉某个 FAIL 把 TypeError 从这里删掉。
        """
        for cls in (TypeError, AttributeError, ValueError, NameError, IndexError):
            self.assertIn(cls, controller._PROGRAMMING_ERRORS,
                          f"{cls.__name__} 应被认定为代码错误")
        # RuntimeError 不在里面：InputBlocked 就是它的子类，收进来会误伤
        self.assertNotIn(RuntimeError, controller._PROGRAMMING_ERRORS)


class TestWin32CallArities(unittest.TestCase):
    """扫源码，核对 ``win32api`` / ``win32gui`` 调用的参数个数。"""

    @staticmethod
    def _calls():
        found = []
        for path in sorted((ROOT / "src").rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if not (isinstance(func, ast.Attribute)
                        and isinstance(func.value, ast.Name)
                        and func.value.id in ("win32api", "win32gui",
                                              "win32process")):
                    continue
                # ``f(*args)`` 数不出个数，标出来让人工看，别静默放过
                starred = any(isinstance(a, ast.Starred) for a in node.args)
                found.append((func.value.id, func.attr, len(node.args),
                              f"{path.relative_to(ROOT)}:{node.lineno}", starred))
        return found

    def test_at_least_one_call_scanned(self):
        """★ 前置：真的扫到了调用点。

        否则下面两条是在**空集合**上空转 —— 全绿但什么都没验。
        """
        calls = self._calls()
        self.assertGreater(len(calls), 5, f"只扫到 {len(calls)} 个 win32 调用点")

    def test_keybd_event_within_arity(self):
        """★ 本次事故那一行：``keybd_event`` 不许超 4 个参数。"""
        bad = [where for mod, name, argc, where, starred in self._calls()
               if name == "keybd_event" and not starred
               and argc > MAX_ARGS["keybd_event"]]
        self.assertEqual(bad, [],
                         f"keybd_event 最多 {MAX_ARGS['keybd_event']} 个参数，"
                         f"超了：{bad}")

    def test_set_cursor_pos_exact_arity(self):
        """★ ``SetCursorPos`` 在 pywin32 里是**1** 个（tuple），不是官方的 2 个。"""
        bad = [where for mod, name, argc, where, starred in self._calls()
               if name == "SetCursorPos" and not starred
               and argc != EXACT_ARGS["SetCursorPos"]]
        self.assertEqual(bad, [],
                         f"SetCursorPos 要传 {EXACT_ARGS['SetCursorPos']} 个"
                         f"（元组）参数，不对的：{bad}")

    def test_no_starred_win32_calls(self):
        """``f(*args)`` 会让上面的核对失效 —— 真出现就让人来看一眼。"""
        starred = [where for *_rest, where, starred in
                   ((m, n, c, w, s) for m, n, c, w, s in self._calls()) if starred]
        self.assertEqual(starred, [], f"这些调用用了 *args，静态核对照不到：{starred}")


class TestArityFactsStillHold(unittest.TestCase):
    """上面那几张表是**从 API 实测来的**，这里顺手验它还成立。

    哪天 pywin32 升级改了容忍度，这两条会红 —— 提醒去更新表，
    而不是让护栏悄悄变成误报源。
    """

    @unittest.skipUnless(sys.platform == "win32", "只在 Windows 上有这些 API")
    def test_keybd_event_rejects_five_args(self):
        """上限 4 是真的：传 5 个当场 TypeError。

        参数绑定阶段就抛，**根本没执行到系统调用**，所以无副作用。
        （vk=0 也不是有效虚拟键。）
        """
        import win32api

        with self.assertRaises(TypeError):
            win32api.keybd_event(0, 0, 0, 0, 0)

    @unittest.skipUnless(sys.platform == "win32", "只在 Windows 上有这些 API")
    def test_set_cursor_pos_rejects_two_args(self):
        """★ 反向的坑：``SetCursorPos`` 传 2 个**反而** TypeError。

        所以护栏不能照官方签名要求 2 个参数。
        """
        import win32api

        with self.assertRaises(TypeError):
            win32api.SetCursorPos(0, 0)      # 绑定阶段就抛，不会移动光标


if __name__ == "__main__":
    unittest.main(verbosity=2)
