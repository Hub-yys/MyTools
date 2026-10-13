# -*- coding: utf-8 -*-
"""「查缺补漏」ok-ww 接线的单元测试（**不启动引擎**）。

## 这一层最容易出的两类问题

**① 导入期就要求 ok-ww 在场。**
   模块级 ``class X(WWOneTimeTask)`` 会让 import 本包时就 import ok-ww。
   而 ``src.tools`` 的自动发现会 import 每个工具包 —— 于是一个
   **没装 ok-ww 的环境会整个工具包都扫不出来**（界面显示"暂无工具"）。

**② 基类选错 → 实例化直接崩。**
   ``okww.task.WWOneTimeTask`` 是**混入类，没有 ``__init__``**::

       class WWOneTimeTask:
           def run(self): ...

   而 ok-script 用 ``class_(executor=..., app=...)`` 实例化，
   单继承它就会::

       TypeError: object.__init__() takes exactly one argument

   这个错**只有在真引擎里才暴露** —— 所以有一条测试专门盯它
   （``test_instantiates_like_ok_script_does``）。

## 为什么这批测试不启动引擎

``tests/check_okww_registration.py`` 已经会**真起 ok-ww 引擎**
验证注册（那个慢、且有副作用）。这里只验"接线本身对不对"，
用假基类就够了 —— 快，而且改坏了立刻知道。
"""

from __future__ import annotations

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.tools.game.explore_gap import okww_task as ot  # noqa: E402


class TestLazyAttribute(unittest.TestCase):
    """★ 导入本模块**不能**碰 ok-ww。"""

    def test_import_does_not_load_okww(self):
        """import 本模块时不该把 okww 拉进来。

        ⚠ 这条要在一个干净的子解释器里验 —— 同一进程里别的测试
        （或其它工具）可能已经把 okww 导入了，那样测不出问题。
        """
        import subprocess                          # noqa: PLC0415

        code = (
            "import sys; sys.path.insert(0, r'%s');"
            "import src.tools.game.explore_gap.okww_task as m;"
            "print('OKWW_LOADED' if any(k.startswith('okww') or k == 'ok' "
            "for k in sys.modules) else 'CLEAN')"
        ) % str(ROOT)
        run = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=120,
            cwd=str(ROOT))
        self.assertIn("CLEAN", run.stdout,
                      f"import 本模块时把 ok-ww 拉进来了：{run.stdout} "
                      f"{run.stderr[-500:]}")

    def test_unknown_attribute_raises(self):
        with self.assertRaises(AttributeError):
            getattr(ot, "不是这个模块的东西")

    def test_task_class_name_exported(self):
        self.assertEqual(ot.TASK_CLASS_NAME, "MyToolsExploreGapTask")

    def test_no_stale_single_file_constant(self):
        """★ 旧的"固定文件名"常量必须**没了**。

        原来 ``LIB_FILENAME = "video_follow_ref.npz"`` 是**一个固定文件**
        —— 于是上传第二个视频会把第一个的库**覆盖**掉。
        现在按视频分开存（``catalog.library_path_for``）。
        这个常量要是又回来，说明有人把共存改回去了。
        """
        self.assertFalse(hasattr(ot, "LIB_FILENAME"),
                         "固定文件名又回来了 —— 会覆盖别的视频的库")
        self.assertTrue(hasattr(ot, "pick_library"))

    def test_import_stays_cheap(self):
        """import 本模块不该碰文件系统 / ok-ww。"""
        import subprocess                              # noqa: PLC0415

        code = (
            "import sys; sys.path.insert(0, r'%s');"
            "import src.tools.game.explore_gap.okww_task as m;"
            "print('OKWW' if any(k.startswith('okww') for k in sys.modules) "
            "else 'CLEAN')"
        ) % str(ROOT)
        run = subprocess.run([sys.executable, "-c", code],
                             capture_output=True, text=True, timeout=120,
                             cwd=str(ROOT))
        self.assertIn("CLEAN", run.stdout)


class TestMakeClass(unittest.TestCase):
    """用假基类验接线逻辑（不碰真 ok-ww）。"""

    def _bases(self):
        """造一对假基类，模仿 ok-ww 的双继承结构。"""

        class FakeMixin:                       #: 对应 WWOneTimeTask
            def helper(self):
                return "mixin"

        class FakeTask:                        #: 对应 BaseCombatTask → ok.Task
            def __init__(self, executor=None, app=None):
                self.executor = executor
                self.app = app

            def log_info(self, msg, notify=False):
                self.logs = getattr(self, "logs", [])
                self.logs.append(msg)

            def sleep(self, seconds):
                pass

        return (FakeMixin, FakeTask)

    def test_class_builds(self):
        cls = ot._make_class(self._bases())
        self.assertTrue(isinstance(cls, type))
        self.assertEqual(cls.__name__, "MyToolsExploreGapTask")

    def test_instantiates_like_ok_script_does(self):
        """★★ 回归：ok-script 用 ``class_(executor=..., app=...)`` 实例化。

        单继承一个没有 ``__init__`` 的混入类就会炸
        ``TypeError: object.__init__() takes exactly one argument``。
        这条钉住"基类得包含一个真的 Task 基类"。
        """
        cls = ot._make_class(self._bases())
        try:
            inst = cls(executor="E", app="A")
        except TypeError as exc:
            self.fail(f"实例化失败（就是真引擎里那个错）：{exc}")
        self.assertEqual(inst.executor, "E")
        self.assertEqual(inst.app, "A")

    def test_language_gate_is_cleared(self):
        """★★ ``supported_languages`` 必须清空。

        ok-ww 原版任务多声明 ``["zh_CN"]``，而宿主 headless →
        ``app.locale`` 是 ``en_US`` → ``init_tasks()`` **静默跳过**它
        → 界面一切正常、点启动却找不到任务。
        """
        cls = ot._make_class(self._bases())
        inst = cls(executor="E", app="A")
        self.assertEqual(inst.supported_languages, [],
                         "语言门禁没清空 —— 任务会被静默跳过")

    def test_has_name_and_description(self):
        cls = ot._make_class(self._bases())
        inst = cls(executor="E", app="A")
        self.assertTrue(inst.name)
        self.assertIn("查缺补漏", inst.name)
        self.assertTrue(inst.description)

    def test_run_without_library_reports_clearly(self):
        """没有参考库 → 给一句人话，**不抛**。"""
        cls = ot._make_class(self._bases())
        inst = cls(executor="E", app="A")
        inst.config = {"参考库": str(ROOT / "绝对不存在的参考库.npz")}
        inst.run()                                  #: 不该抛
        self.assertIn("参考库", inst.stop_reason)
        self.assertTrue(any("参考库" in m for m in getattr(inst, "logs", [])))

    def test_run_reports_error_not_raise(self):
        """跑的时候出意外 → 记 stop_reason + 日志，**不把引擎带崩**。"""
        cls = ot._make_class(self._bases())
        inst = cls(executor="E", app="A")
        #: 指一个存在但坏掉的文件 —— load_library 会抛
        bad = ROOT / "data" / "_bad_such_lib.npz"
        bad.parent.mkdir(parents=True, exist_ok=True)
        bad.write_bytes(b"not an npz at all")
        try:
            inst.config = {"参考库": str(bad)}
            inst.run()                              #: 不该抛
            self.assertTrue(inst.stop_reason)
        finally:
            bad.unlink(missing_ok=True)


class TestToolRegistration(unittest.TestCase):
    def test_tool_registered_with_icon(self):
        #: ⚠ ``from src.core.registry import registry``（**类**的别名），
        #: 不是 ``from src.core import registry``（那是模块，没有这些方法）。
        from src.core.registry import registry
        from src.tools import discover_tools

        discover_tools()
        meta = registry.get_meta("explore_gap")
        self.assertIsNotNone(meta, "explore_gap 没注册上")
        self.assertFalse(meta.coming_soon)
        self.assertTrue(meta.icon_path, "缺自定义图标（风格会不统一）")
        self.assertTrue(pathlib.Path(meta.icon_path).is_file(),
                        f"图标文件不在：{meta.icon_path}")

    def test_widget_is_not_placeholder(self):
        """``create_widget`` 要真能造出面板（构造失败会被兜成占位页）。"""
        import os                                  # noqa: PLC0415

        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication  # noqa: PLC0415
        from qfluentwidgets import (                # noqa: PLC0415
            Theme,
            setTheme,
        )

        from src.core.registry import registry      # noqa: PLC0415
        from src.gui.widgets import ComingSoonWidget  # noqa: PLC0415
        from src.tools import discover_tools        # noqa: PLC0415

        discover_tools()
        app = QApplication.instance() or QApplication([])
        #: ⚠ 两种主题下各构造一次 —— 能抓到"深色下写死浅色底"那类问题的
        #: 构造期版本（渲染期的问题由截图脚本抓）。
        for theme in (Theme.LIGHT, Theme.DARK):
            with self.subTest(theme=theme):
                setTheme(theme)
                tool = registry.make("explore_gap")
                self.assertIsNotNone(tool)
                widget = tool.create_widget()
                self.assertIsNotNone(widget)
                self.assertNotIsInstance(widget, ComingSoonWidget)
                widget.deleteLater()
                app.processEvents()


if __name__ == "__main__":
    unittest.main(verbosity=2)
