"""工具设置的存盘（``src/core/tool_settings.py``）+ 声骸设置（``settings.py``）单测。

其中 ``TestTaskRunnerUsesSavedSettings`` 是**回归测试**：
它钉住"从任务页运行"用的必须是工具页存下来的那套判定规则，
而不是代码里的 ``JudgeConfig()`` 默认值 —— 之前就是这里没生效，
表现是"任务根本没按我配的规则筛选声骸"。
"""

from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.core import tool_settings  # noqa: E402
from src.tools.game.echo_enhance import settings as echo_settings  # noqa: E402
from src.tools.game.echo_enhance.settings import EchoSettings  # noqa: E402
from src.tools.game.echo_enhance.stats import CRIT, CRIT_DMG, JudgeConfig  # noqa: E402


class _TempSettingsFile(unittest.TestCase):
    """把设置文件指到临时目录 —— 绝不碰用户真正的配置。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "tool_settings.json"
        original = tool_settings.settings_file
        tool_settings.settings_file = lambda: self.path
        self.addCleanup(setattr, tool_settings, "settings_file", original)


class TestToolSettingsStore(_TempSettingsFile):
    def test_round_trip(self):
        self.assertEqual(tool_settings.load_all(), {})
        tool_settings.save("demo", {"a": 1})
        self.assertEqual(tool_settings.load("demo"), {"a": 1})
        self.assertTrue(self.path.exists())

    def test_other_keys_are_kept(self):
        tool_settings.save("one", {"a": 1})
        tool_settings.save("two", {"b": 2})
        self.assertEqual(tool_settings.load("one"), {"a": 1})
        self.assertEqual(tool_settings.load("two"), {"b": 2})

    def test_broken_file_is_tolerated(self):
        self.path.write_text("{ 这不是 json", encoding="utf-8")
        self.assertEqual(tool_settings.load_all(), {})
        self.assertEqual(tool_settings.load("demo"), {})

    def test_missing_key_returns_empty(self):
        self.assertEqual(tool_settings.load("never_saved"), {})

    def test_written_file_is_utf8_and_readable(self):
        tool_settings.save("demo", {"中文": "值"})
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(raw["demo"]["中文"], "值")


class TestEchoSettings(_TempSettingsFile):
    def test_defaults_match_the_ui(self):
        s = EchoSettings()
        self.assertEqual(set(s.core_stats), {CRIT, CRIT_DMG})
        self.assertEqual(s.optional_stats, ())
        self.assertTrue(s.enable_crit_check)
        self.assertTrue(s.enable_max_roll_lock)
        self.assertEqual(s.min_valid_count, 3)

    def test_save_then_load(self):
        original = EchoSettings(
            core_stats=(CRIT, CRIT_DMG, "攻击百分比"),
            optional_stats=("共鸣效率",),
            crit_min=8.5,
            crit_dmg_min=17.0,
            enable_crit_check=False,
            enable_max_roll_lock=False,
            min_valid_count=5,
        )
        original.save()
        self.assertEqual(EchoSettings.load(), original)

    def test_judge_config_matches_settings(self):
        s = EchoSettings(
            core_stats=(CRIT, CRIT_DMG, "攻击百分比"),
            optional_stats=("共鸣效率", "生命百分比"),
            crit_min=9.0,
            crit_dmg_min=18.0,
            enable_crit_check=False,
            enable_max_roll_lock=False,
            min_valid_count=4,
        )
        cfg = s.to_judge_config()
        self.assertEqual(cfg.core_stats, frozenset({CRIT, CRIT_DMG, "攻击百分比"}))
        self.assertEqual(cfg.optional_stats, frozenset({"共鸣效率", "生命百分比"}))
        self.assertEqual(cfg.crit_min, 9.0)
        self.assertEqual(cfg.crit_dmg_min, 18.0)
        self.assertFalse(cfg.enable_crit_check)
        self.assertFalse(cfg.enable_max_roll_lock)
        self.assertEqual(cfg.min_valid_count, 4)

    def test_round_trip_through_judge_config(self):
        cfg = JudgeConfig(optional_stats=frozenset({"共鸣效率"}), min_valid_count=2)
        s = EchoSettings.from_judge_config(cfg)
        self.assertEqual(s.to_judge_config().valid_stats, cfg.valid_stats)
        self.assertEqual(s.min_valid_count, cfg.min_valid_count)

    # ------------------------------------------------------------ 坏数据兜底
    def test_broken_dict_falls_back(self):
        s = EchoSettings.from_dict({
            "core_stats": "不是列表",
            "optional_stats": None,
            "crit_min": "七点五",
            "crit_dmg_min": None,
            "enable_crit_check": "yes",       # 不是 bool → 用默认
            "enable_max_roll_lock": 1,        # 同上
            "min_valid_count": 99,
        })
        self.assertEqual(set(s.core_stats), {CRIT, CRIT_DMG})
        self.assertEqual(s.optional_stats, ())
        self.assertEqual(s.crit_min, echo_settings.DEFAULT_CRIT_MIN)
        self.assertEqual(s.crit_dmg_min, echo_settings.DEFAULT_CRIT_DMG_MIN)
        self.assertTrue(s.enable_crit_check)
        self.assertTrue(s.enable_max_roll_lock)
        self.assertEqual(s.min_valid_count, 5)        # 夹到上限

    def test_unknown_stat_names_are_dropped(self):
        s = EchoSettings.from_dict({"core_stats": ["不存在的属性", CRIT], "optional_stats": ["双爆"]})
        self.assertEqual(set(s.core_stats), {CRIT, CRIT_DMG})
        self.assertEqual(s.optional_stats, ())       # 可选属性里不该有双爆

    def test_crit_always_forced_into_core(self):
        s = EchoSettings.from_dict({"core_stats": ["攻击百分比"]})
        self.assertTrue({CRIT, CRIT_DMG} <= set(s.core_stats))

    def test_describe_mentions_rules(self):
        text = EchoSettings(optional_stats=("共鸣效率",), min_valid_count=4).describe()
        self.assertIn("有效词条 ≥4", text)
        self.assertIn("共鸣效率", text)
        self.assertIn("满值保护：开", text)


class TestTaskRunnerUsesSavedSettings(_TempSettingsFile):
    """★ 回归：任务流程运行必须用工具页存下来的规则。"""

    def test_runner_config_comes_from_disk(self):
        from src.tools.game.echo_enhance.tool import EchoEnhanceTool

        saved = EchoSettings(
            core_stats=(CRIT, CRIT_DMG, "攻击百分比"),
            optional_stats=("共鸣效率",),
            crit_min=9.5,
            crit_dmg_min=19.0,
            enable_crit_check=True,
            enable_max_roll_lock=False,
            min_valid_count=5,
        )
        saved.save()

        logs: list[str] = []
        tool = EchoEnhanceTool()
        runner = tool.create_task_runner({}, logs.append, lambda: False)
        self.assertIsNotNone(runner)

        config = runner.judge_config
        self.assertEqual(config.min_valid_count, 5, "任务运行没读工具页的有效词条数")
        self.assertFalse(config.enable_max_roll_lock, "任务运行没读工具页的满值保护开关")
        self.assertEqual(config.crit_min, 9.5)
        self.assertIn("共鸣效率", config.optional_stats)
        self.assertIn("攻击百分比", config.core_stats)

        # 日志里要能看出"按什么规则跑的"
        joined = "\n".join(logs)
        self.assertIn("有效词条 ≥5", joined)
        self.assertIn("判定配置", joined)

    def test_defaults_when_nothing_saved(self):
        from src.tools.game.echo_enhance.tool import EchoEnhanceTool

        tool = EchoEnhanceTool()
        runner = tool.create_task_runner({}, lambda _m: None, lambda: False)
        self.assertEqual(runner.judge_config, JudgeConfig())


if __name__ == "__main__":
    unittest.main(verbosity=2)
