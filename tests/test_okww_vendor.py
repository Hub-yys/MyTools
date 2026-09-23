# -*- coding: utf-8 -*-
"""vendored ok-ww 的完整性测试。

* 包可整体导入（改名 src → okww 后没有漏网的引用）
* 宿主配置：路径全是绝对路径、任务走 okww.* 、不带自动更新
* ok-ww 原生任务配置的形态（页面按它渲染，MyTools 不发明参数）
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor" / "okww"

#: 宿主配置里**属于 MyTools 自己**的任务模块（不是 vendored ok-ww 的东西）。
#: 它本该是 `src.*` —— 上面那条"必须改成 okww.*"的规则针对的是从 vendor 搬进来的
#: 代码（原包名 src，改成 okww 才不会和 MyTools 的 src 撞名）。
#: 见 src/tools/game/echo_enhance/okww_task.py（ok-ww 流程 + MyTools 判定条件）。
OWN_TASKS = {"src.tools.game.echo_enhance.okww_task"}

sys.path.insert(0, str(VENDOR))


class TestVendorIntegrity(unittest.TestCase):
    def test_vendor_tree_exists(self):
        for rel in ("okww/task/FarmEchoTask.py", "okww/task/AutoCombatTask.py",
                    "okww/task/BaseCombatTask.py", "okww/char/BaseChar.py",
                    "okww/combat/CombatCheck.py", "config.py",
                    "assets/coco_annotations.json", "assets/echo_model/echo.onnx"):
            self.assertTrue((VENDOR / rel).is_file(), "缺少 " + rel)

    def test_all_modules_import(self):
        import importlib
        import pkgutil
        import okww

        mods = [m.name for m in pkgutil.walk_packages(okww.__path__, "okww.")]
        self.assertGreater(len(mods), 80, "okww 模块数异常：%d" % len(mods))
        bad = []
        for name in mods:
            try:
                importlib.import_module(name)
            except ImportError as e:
                if "openvino" in str(e):
                    continue  # OpenVinoYolo8Detect：没装 openvino，宿主配置不会用到它
                bad.append((name, str(e)))
            except Exception as e:  # noqa: BLE001
                bad.append((name, "%s: %s" % (type(e).__name__, e)))
        self.assertEqual(bad, [], "模块导入失败：%s" % bad)

    def test_no_src_leftover(self):
        for py in VENDOR.rglob("*.py"):
            text = py.read_text(encoding="utf-8", newline="")
            for token in ("from src.", "from src import", "import src.",
                          "'" + "src.", '"' + "src."):
                self.assertNotIn(token, text, "%s 仍引用 %s" % (py, token))


class TestHostConfig(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from src.tools.game.auto_combat.okww_boot import build_config
        cls.config = build_config()

    def test_paths_are_absolute(self):
        import os
        tm = self.config["template_matching"]["coco_feature_json"]
        self.assertTrue(os.path.isabs(tm), "coco 路径必须是绝对路径：%s" % tm)
        self.assertTrue(Path(tm).is_file(), "coco_annotations.json 不存在")
        for key in ("config_folder", "log_file", "screenshots_folder"):
            self.assertTrue(os.path.isabs(self.config[key]),
                            "%s 必须是绝对路径" % key)

    def test_headless_no_gui_no_update(self):
        self.assertNotIn("gui", self.config, "不能带 gui 配置（否则 OK 会创建 Qt 窗口）")
        self.assertIsNone(self.config.get("update_pyappify"),
                          "宿主必须禁用 ok-ww 的自动更新")
        self.assertIs(self.config.get("check_mutex"), False)

    def test_tasks_renamed_to_okww(self):
        for task_list in ("onetime_tasks", "trigger_tasks"):
            for entry in self.config.get(task_list, []):
                self.assertTrue(entry[0].startswith("okww.") or entry[0] in OWN_TASKS,
                                "%s 里的任务没改名：%s" % (task_list, entry[0]))
        scene = self.config["scene"]
        self.assertEqual(scene[0], "okww.scene.WWScene",
                         "scene 没改名：%s" % scene)

    def test_ocr_uses_onnxruntime_backend(self):
        params = self.config["ocr"]["params"]
        self.assertIs(params["use_openvino"], False, "本机没装 openvino")
        self.assertEqual(self.config["ocr"]["lib"], "onnxocr")

    def test_tasks_exposed_to_page(self):
        from src.tools.game.auto_combat.okww_boot import TASKS
        onetime = {e[1] for e in self.config["onetime_tasks"]}
        trigger = {e[1] for e in self.config["trigger_tasks"]}
        self.assertIn(TASKS["4C 刷声骸"], onetime)
        self.assertIn(TASKS["自动战斗"], trigger)


class TestOkwwNativeOptions(unittest.TestCase):
    """页面渲染的是 ok-ww 自己定义的参数 —— 用它的源码直接验证，不启动引擎。"""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(VENDOR))
        from ok.util.GlobalConfig import GlobalConfig
        from src.tools.game.auto_combat.okww_boot import _load_vendor_config_module
        vc = _load_vendor_config_module()

        class FakeExecutor:
            global_config = GlobalConfig(
                [vc.key_config_option, vc.char_config_option, vc.monthly_card_config_option])
            config = {"ocr": {}}
            scene = None
            feature_set = None
            text_fix = {}

        class FakeApp:
            locale = "en_US"

            def tr(self, m):
                return m

            def tr(self, m):
                return m

        cls.executor = FakeExecutor
        from okww.task.AutoCombatTask import AutoCombatTask
        from okww.task.FarmEchoTask import FarmEchoTask
        cls.farm = FarmEchoTask(FakeExecutor(), FakeApp())
        cls.combat = AutoCombatTask(FakeExecutor(), FakeApp())

    def test_farm_echo_native_options(self):
        keys = set(self.farm.default_config)
        for name in ("Boss", "Teleport to Boss", "Repeat Farm Count",
                     "Echo Pickup Method", "Use Liberation"):
            self.assertIn(name, keys)
        # 页面按 config_type 渲染下拉
        self.assertEqual(self.farm.config_type["Boss"]["type"], "drop_down")
        self.assertIn("Other", self.farm.config_type["Boss"]["options"])

    def test_auto_combat_native_options(self):
        keys = set(self.combat.default_config)
        for name in ("Auto Target", "Use Liberation",
                     "Switch to Healer before and after Combat"):
            self.assertIn(name, keys)
        self.assertIsInstance(self.combat.default_config["Auto Target"], bool)

    def test_page_renders_nothing_invented(self):
        """页面可渲染的参数必须完全来自 ok-ww 的 default_config。"""
        from src.tools.game.auto_combat.tool import AutoCombatWidget  # noqa: F401  # 可导入
        rendered = set(self.farm.default_config) | set(self.combat.default_config)
        self.assertNotIn("红色下限", rendered, "自造参数混进来了")
        self.assertNotIn("普攻间隔", rendered, "自造参数混进来了")


class TestLogCleanup(unittest.TestCase):
    """日志按日期分区由 ok-script 做（ok-ww.YYYY-MM-DD.log，保留 7 天）；
    这里测宿主的月度兜底清理。"""

    def test_clean_old_logs(self):
        import os
        import time
        from src.tools.game.auto_combat.okww_boot import clean_old_logs

        import tempfile
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            old = d / "ok-ww.2026-08-01.log"
            new = d / "ok-ww.2026-09-23.log"
            err = d / "ok-ww_error.log"
            for f in (old, new, err):
                f.write_text("x", encoding="utf-8")
            past = time.time() - 40 * 86400
            os.utime(old, (past, past))

            removed = clean_old_logs(d, days=31)
            self.assertEqual(removed, 1, "只该删 40 天前那份")
            self.assertFalse(old.exists())
            self.assertTrue(new.exists(), "当天日志不能删")
            self.assertTrue(err.exists(), "error 日志没过期也不能删")

    def test_clean_missing_dir(self):
        from src.tools.game.auto_combat.okww_boot import clean_old_logs
        self.assertEqual(clean_old_logs(Path(r"D:/__no_such_dir__")), 0)


if __name__ == "__main__":
    unittest.main()
