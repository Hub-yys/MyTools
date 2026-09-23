"""游戏客户端检查的单元测试。

匹配函数是纯逻辑；``check()`` 里的枚举要读真实环境，所以：
* 否定分支用一个"绝不存在的关键字"来验，结果稳定；
* 肯定分支拿**当前跑的 python 进程**当替身（进程名 python.exe），验证枚举真的通了
  —— 比 mock 掉枚举更有说服力。
"""

from __future__ import annotations

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.core.game_client import (  # noqa: E402
    WUWA,
    ClientSpec,
    check,
    list_process_names,
    process_hit,
    window_hit,
)


class TestMatch(unittest.TestCase):
    def test_window_hit_chinese(self):
        self.assertTrue(window_hit("鸣潮", WUWA.window_keywords))

    def test_window_hit_english_case_insensitive(self):
        self.assertTrue(window_hit("WUTHERING WAVES CLIENT", WUWA.window_keywords))

    def test_window_hit_miss(self):
        self.assertFalse(window_hit("记事本", WUWA.window_keywords))
        self.assertFalse(window_hit("", WUWA.window_keywords))

    def test_process_hit_full_path(self):
        path = r"C:\Games\Wuthering Waves\Client\Binaries\Win64\Client-Win64-Shipping.exe"
        self.assertTrue(process_hit(path, WUWA.process_names))

    def test_process_hit_case_insensitive(self):
        self.assertTrue(process_hit("client-win64-shipping.EXE", WUWA.process_names))

    def test_process_hit_is_exact_basename(self):
        # 只比文件名、且要完全相等：名字里多一截的别的程序不该被认成游戏
        self.assertFalse(process_hit("Client-Win64-Shipping-Helper.exe", WUWA.process_names))
        self.assertFalse(process_hit("Client-Win64-Shipping.exe.bak", WUWA.process_names))
        self.assertFalse(process_hit("notepad.exe", WUWA.process_names))

    def test_wuwa_keywords_match_controller(self):
        """两边判据必须同一套。

        这里判"客户端在跑"、``controller`` 判"能不能抓图"，不一致就会出现
        "检查通过但抓不到窗口"的错位。
        """
        from src.tools.game.echo_enhance.controller import WINDOW_KEYWORDS

        self.assertEqual(set(WUWA.window_keywords), set(WINDOW_KEYWORDS))


class TestCheck(unittest.TestCase):
    def test_none_spec_is_not_running(self):
        self.assertFalse(check(None).running)

    def test_absent_client_is_not_running(self):
        spec = ClientSpec(
            display_name="不存在的东西",
            window_keywords=("ZZZ-绝不存在的窗口-ZZZ",),
            process_names=("zzz-not-exist.exe",),
        )
        status = check(spec)
        self.assertFalse(status.running)
        self.assertIn("没找到", status.detail)
        self.assertIn("不存在的东西", status.describe())

    def test_real_enumeration_finds_this_python(self):
        """肯定分支：拿当前 python 进程当替身，证明进程枚举真的通了。"""
        if not list_process_names():
            self.skipTest("本机枚举不到进程（非 Windows 或没装 pywin32）")
        spec = ClientSpec(
            display_name="本机 python",
            window_keywords=("ZZZ-绝不存在的窗口-ZZZ",),
            process_names=("python.exe",),
        )
        status = check(spec)
        self.assertTrue(status.running, status.detail)
        self.assertEqual(status.matched_by, "进程")


if __name__ == "__main__":
    unittest.main(verbosity=2)
