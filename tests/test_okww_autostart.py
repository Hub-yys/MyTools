"""ok-ww 引擎的自启：程序启动时默认拉起。

用户要求（2026-09-24）："ok-ww 引擎改成启动该应用时，就默认启动"。

这几条断言要防的是三件事：

1. 有人把 ``main.py`` 里那行 ``QTimer.singleShot`` 顺手删了 → 自启**静默失效**，
   界面上完全看不出来（只会觉得"怎么又要手点"）；
2. 自启把异常抛出去 → **整个程序启动失败**。这是最坏的：引擎起不来（比如游戏没开、
   OCR 模型缺文件）无论如何不该拖垮界面；
3. 自启被安排在 ``window.show()`` 之前 → ``boot()`` 会 ``os.chdir`` 到 vendor 目录，
   启动阶段的相对路径解析会被带跑偏。
"""

from __future__ import annotations

import pathlib
import sys
import unittest
from pathlib import Path

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import main as app_main  # noqa: E402
from src.tools.game.auto_combat import okww_boot  # noqa: E402


class TestAutostartWiring(unittest.TestCase):
    def test_delay_is_positive(self):
        self.assertIsInstance(okww_boot.AUTOSTART_DELAY_MS, int)
        self.assertGreater(okww_boot.AUTOSTART_DELAY_MS, 0,
                           "延迟为 0 会和主窗口首帧抢；boot 里还有 os.chdir")

    def test_main_schedules_autostart_after_show(self):
        src = (ROOT / "main.py").read_text(encoding="utf-8")
        call = "QTimer.singleShot(AUTOSTART_DELAY_MS, _autostart_okww_engine)"
        self.assertIn(call, src, "main() 里没排自启 —— 引擎不会默认启动了")
        self.assertLess(src.index("window.show()"), src.index(call),
                        "自启必须排在 window.show() 之后（boot 会 os.chdir）")


class TestAutostartBehaviour(unittest.TestCase):
    """用假宿主替换 get_host：不碰真引擎，只验"该不该 boot / 出错怎么办"。"""

    def setUp(self):
        self._orig_get_host = okww_boot.get_host
        self._orig_auto = okww_boot.autostart_engine
        self.addCleanup(self._restore)

    def _restore(self):
        okww_boot.get_host = self._orig_get_host
        okww_boot.autostart_engine = self._orig_auto

    def test_engine_boots_host(self):
        calls = []

        class FakeHost:
            def boot(self):
                calls.append(1)

        okww_boot.get_host = lambda: FakeHost()
        okww_boot.autostart_engine()
        self.assertEqual(calls, [1], "自启必须真的去 boot 引擎")

    def test_engine_swallows_errors(self):
        class BoomHost:
            def boot(self):
                raise RuntimeError("故意炸")

        okww_boot.get_host = lambda: BoomHost()
        okww_boot.autostart_engine()          # 不该抛

    def test_main_hook_calls_engine(self):
        calls = []
        okww_boot.autostart_engine = lambda: calls.append(1)
        app_main._autostart_okww_engine()
        self.assertEqual(calls, [1])

    def test_main_hook_swallows_errors(self):
        def boom():
            raise RuntimeError("故意炸")

        okww_boot.autostart_engine = boom
        app_main._autostart_okww_engine()     # 不该抛


if __name__ == "__main__":
    unittest.main(verbosity=2)
