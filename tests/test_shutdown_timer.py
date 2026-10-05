"""定时关机 + 「不再重复拉取」的回归测试。

    python tests/test_shutdown_timer.py

用户 2026-10-01 的两个反馈：

1. "这里为什么老是要拉取，我本地本来就是最新的"
   —— 有些声骸（活动/装饰类）**本来就没有技能说明**，只看"有没有正文"
   会让它们**每次更新都白拉一遍**。
2. "4C自动战斗增加设置定时关机的功能"
   —— 跑 N 分钟后关机，关机前提前提醒且可取消。

⚠ 这里**绝不真的关机**：``ShutdownTimer`` 是纯状态机，
``shutdown()`` 也不会在这些测试里被调用（要测也只测"平台不对时说失败"）。
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile
import unittest
import unittest.mock as mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.core import shutdown_timer, wuwa_update  # noqa: E402


class TestClampMinutes(unittest.TestCase):
    """分钟数的范围夹取。"""

    def test_zero_and_negative_mean_disabled(self):
        self.assertEqual(shutdown_timer.clamp_minutes(0), 0)
        self.assertEqual(shutdown_timer.clamp_minutes(-5), 0)

    def test_valid_values_pass_through(self):
        self.assertEqual(shutdown_timer.clamp_minutes(30), 30)
        self.assertEqual(shutdown_timer.clamp_minutes(1), 1)

    def test_clamps_to_max(self):
        self.assertEqual(shutdown_timer.clamp_minutes(99999),
                         shutdown_timer.MAX_MINUTES)

    def test_junk_is_disabled(self):
        for value in (None, "", "abc", [], {}):
            with self.subTest(value=value):
                self.assertEqual(shutdown_timer.clamp_minutes(value), 0)

    def test_float_string(self):
        """输入框里可能出现 "30.0" / " 30 "，都要认。"""
        self.assertEqual(shutdown_timer.clamp_minutes("30"), 30)
        self.assertEqual(shutdown_timer.clamp_minutes(" 30 "), 30)


class TestShutdownTimer(unittest.TestCase):
    """★ 纯状态机 —— 时间直接喂，不用真等 30 分钟。"""

    def test_disabled_when_zero(self):
        timer = shutdown_timer.ShutdownTimer(0)
        self.assertFalse(timer.enabled)
        self.assertFalse(timer.start(now=0))
        self.assertFalse(timer.active)

    def test_start_and_remaining(self):
        timer = shutdown_timer.ShutdownTimer(30)
        self.assertTrue(timer.start(now=0))
        self.assertTrue(timer.active)
        self.assertAlmostEqual(timer.remaining(now=0), 30 * 60)
        # 过了 10 分钟 → 还剩 20 分钟
        self.assertAlmostEqual(timer.remaining(now=600), 20 * 60)

    def test_remaining_text(self):
        timer = shutdown_timer.ShutdownTimer(30)
        timer.start(now=0)
        self.assertIn("分", timer.remaining_text(now=0))
        self.assertIn("秒", timer.remaining_text(now=30 * 60 - 45))

    def test_warn_fires_once_in_window(self):
        """★ 关机前提醒 —— **只报一次**（否则轮询会连着弹几十个框）。"""
        timer = shutdown_timer.ShutdownTimer(30, warn_seconds=60)
        timer.start(now=0)
        deadline = 30 * 60
        self.assertFalse(timer.should_warn(now=deadline - 120),
                         "还早，不该提醒")
        self.assertTrue(timer.should_warn(now=deadline - 30),
                        "进入提醒窗口了，该提醒")
        self.assertFalse(timer.should_warn(now=deadline - 10),
                         "提醒过就不该再报")

    def test_fire_once(self):
        timer = shutdown_timer.ShutdownTimer(10)
        timer.start(now=0)
        self.assertFalse(timer.should_fire(now=10 * 60 - 1))
        self.assertTrue(timer.should_fire(now=10 * 60))
        self.assertFalse(timer.should_fire(now=10 * 60 + 5),
                         "已经报过，不该重复触发")

    def test_cancel_works_at_any_stage(self):
        """★ 取消在任何阶段都有效（关机前一刻也来得及）。"""
        for offset in (0, 100, 10 * 60 - 5):
            with self.subTest(offset=offset):
                timer = shutdown_timer.ShutdownTimer(10)
                timer.start(now=0)
                timer.cancel()
                self.assertFalse(timer.active)
                self.assertFalse(timer.should_fire(now=10 * 60))
                self.assertEqual(timer.remaining(now=offset), 0.0)

    def test_restart_resets_warning(self):
        """重新启动 → 提醒状态重置（下次还得提醒）。"""
        timer = shutdown_timer.ShutdownTimer(10, warn_seconds=60)
        timer.start(now=0)
        timer.should_warn(now=10 * 60 - 10)
        self.assertTrue(timer.warned)
        timer.start(now=0)
        self.assertFalse(timer.warned)


class TestShutdownCommand(unittest.TestCase):
    """``shutdown()`` —— **不真的关机**，只验证它构造对了命令。"""

    def test_builds_windows_command(self):
        if sys.platform != "win32":
            self.skipTest("只在 Windows 上有意义")
        with mock.patch.object(shutdown_timer.subprocess, "run") as runner:
            runner.return_value = mock.Mock(returncode=0, stdout="", stderr="")
            ok, _message = shutdown_timer.shutdown(seconds=30)
        self.assertTrue(ok)
        command = runner.call_args[0][0]
        self.assertEqual(command[0], "shutdown")
        self.assertIn("/s", command)
        self.assertIn("30", command)

    def test_reports_failure_instead_of_pretending(self):
        """★ 命令失败要**如实报** —— 不能"假装关了"。

        用户以为电脑会关、结果没关（或者反过来），比报错糟得多。
        """
        if sys.platform != "win32":
            self.skipTest("只在 Windows 上有意义")
        with mock.patch.object(shutdown_timer.subprocess, "run") as runner:
            runner.return_value = mock.Mock(returncode=1, stdout="",
                                            stderr="拒绝访问")
            ok, message = shutdown_timer.shutdown()
        self.assertFalse(ok)
        self.assertIn("拒绝访问", message)

    def test_exception_becomes_failure(self):
        if sys.platform != "win32":
            self.skipTest("只在 Windows 上有意义")
        with mock.patch.object(shutdown_timer.subprocess, "run",
                               side_effect=OSError("找不到命令")):
            ok, message = shutdown_timer.shutdown()
        self.assertFalse(ok)
        self.assertIn("找不到命令", message)


class TestEchoSkillNoRefetch(unittest.TestCase):
    """★ 确认"没有技能"的声骸**不再重复拉取**。

    用户报"这里为什么老是要拉取，我本地本来就是最新的"——
    那十几个本来就没有技能说明的，每次更新都白拉一遍。
    """

    def _fetch(self, data: dict, records: list[dict]):
        """在临时数据文件上跑一次 _fetch_kurobbs_echo_skills。"""
        tmp = pathlib.Path(tempfile.mkdtemp()) / "wuwa_echo_skills.json"
        tmp.write_text(json.dumps({"echoes": data}, ensure_ascii=False),
                       encoding="utf-8")
        original = wuwa_update.SKILLS_FILE
        wuwa_update.SKILLS_FILE = tmp
        logs: list[str] = []
        try:
            with mock.patch.object(wuwa_update, "_kuro_page",
                                   return_value=(records, {})), \
                 mock.patch.object(wuwa_update, "_entry_id_from_record",
                                   return_value="9"), \
                 mock.patch.object(wuwa_update, "_kuro_entry_detail",
                                   return_value={}):
                result = wuwa_update._fetch_kurobbs_echo_skills(
                    logs.append, {})
        finally:
            wuwa_update.SKILLS_FILE = original
        return result, " ".join(logs)

    def test_marked_entries_are_skipped(self):
        """★ 标了 ``_skill_missing`` 的不再拉。"""
        result, logs = self._fetch(
            {
                "有正文": {"skill": "已经有的", "cooldown": "5秒"},
                "确认没有": {"skill": "", "cooldown": "",
                             "_skill_missing": True},
                "没查过": {"skill": "", "cooldown": ""},
            },
            [{"name": "有正文", "content": {"linkId": "1"}},
             {"name": "确认没有", "content": {"linkId": "2"}},
             {"name": "没查过", "content": {"linkId": "3"}}],
        )
        self.assertIn("需要补 1 个", logs,
                      f"应该只补「没查过」一个（日志：{logs}）")
        self.assertIn("确认无技能 1 个", logs)

    def test_plain_empty_is_still_fetched(self):
        """没有标记的空壳**仍要拉** —— 它们可能真能补上。"""
        _result, logs = self._fetch(
            {"空壳": {"skill": "", "cooldown": ""}},
            [{"name": "空壳", "content": {"linkId": "1"}}],
        )
        self.assertIn("需要补 1 个", logs)

    def test_missing_module_gets_marked(self):
        """详情里没有「声骸技能」模块 → 返回值里带标记（好让调用方存下来）。"""
        result, _logs = self._fetch(
            {}, [{"name": "没技能的", "content": {"linkId": "1"}}])
        self.assertIn("没技能的", result)
        self.assertTrue(result["没技能的"].get("_skill_missing"),
                        "确认没有技能的条目要带 _skill_missing 标记")


class TestApplyMarksMissing(unittest.TestCase):
    """``apply_updates`` 要把"确认没有"写进数据文件，且**不能覆盖已有正文**。"""

    def _apply(self, local: dict, fetched: dict) -> dict:
        tmp = pathlib.Path(tempfile.mkdtemp())
        skills_file = tmp / "wuwa_echo_skills.json"
        skills_file.write_text(json.dumps(local, ensure_ascii=False),
                               encoding="utf-8")
        snapshot = wuwa_update.RemoteSnapshot()
        snapshot.echo_skills = fetched
        original = wuwa_update.SKILLS_FILE
        wuwa_update.SKILLS_FILE = skills_file
        try:
            wuwa_update.apply_updates(
                snapshot, wuwa_update.UpdateReport(), log=lambda _m: None)
        finally:
            wuwa_update.SKILLS_FILE = original
        return json.loads(skills_file.read_text(encoding="utf-8"))

    def test_marks_confirmed_missing(self):
        out = self._apply(
            {"echoes": {"某声骸": {"skill": "", "cooldown": ""}}},
            {"某声骸": {"skill": "", "cooldown": "", "_skill_missing": True}},
        )
        self.assertTrue(out["echoes"]["某声骸"].get("_skill_missing"),
                        "确认没有的条目没被标记 —— 下次还会白拉")

    def test_never_overwrites_existing_text(self):
        """★ 绝不能用"没查到"去覆盖**已有的正文**（那是数据倒退）。"""
        out = self._apply(
            {"echoes": {"某声骸": {"skill": "重要说明", "cooldown": "5秒"}}},
            {"某声骸": {"skill": "", "cooldown": "", "_skill_missing": True}},
        )
        entry = out["echoes"]["某声骸"]
        self.assertEqual(entry["skill"], "重要说明", "已有正文被清空了")
        self.assertNotIn("_skill_missing", entry,
                         "有正文的不该被标成'没有技能'")

    def test_real_skill_clears_marker(self):
        """后来补到正文了 → 标记要作废（否则界面/数据自相矛盾）。"""
        out = self._apply(
            {"echoes": {"某声骸": {"skill": "", "cooldown": "",
                                   "_skill_missing": True}}},
            {"某声骸": {"skill": "补到了", "cooldown": "8秒"}},
        )
        entry = out["echoes"]["某声骸"]
        self.assertEqual(entry["skill"], "补到了")
        self.assertNotIn("_skill_missing", entry)


class TestShutdownCard(unittest.TestCase):
    """4C 页面上的定时关机设置。"""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def _widget(self):
        from PySide6.QtWidgets import QWidget

        from src.core import tool_settings
        from src.tools.game.auto_combat.tool import AutoCombatWidget

        settings_path = pathlib.Path(tempfile.mkdtemp()) / "settings.json"
        self._patcher = mock.patch.object(tool_settings, "settings_file",
                                          return_value=settings_path)
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

        class _Meta:
            key = "auto_combat"

        self._holder = QWidget()
        self._holder.resize(1200, 900)
        widget = AutoCombatWidget(_Meta())
        widget.setParent(self._holder)
        widget.resize(1200, 900)
        self._holder.show()
        self.app.processEvents()
        return widget

    def test_has_shutdown_controls(self):
        widget = self._widget()
        for name in ("shutdown_check", "shutdown_edit", "shutdown_state"):
            self.assertTrue(hasattr(widget, name), f"少了 {name}")

    def test_disabled_by_default(self):
        widget = self._widget()
        self.assertFalse(widget.shutdown_check.isChecked())
        self.assertEqual(widget._shutdown_minutes(), 0)

    def test_enabling_yields_minutes(self):
        widget = self._widget()
        widget.shutdown_check.setChecked(True)
        widget.shutdown_edit.setText("30")
        self.app.processEvents()
        self.assertEqual(widget._shutdown_minutes(), 30)

    def test_settings_persist(self):
        from src.core import tool_settings

        widget = self._widget()
        widget.shutdown_check.setChecked(True)
        widget.shutdown_edit.setText("45")
        self.app.processEvents()
        saved = tool_settings.load("auto_combat")
        self.assertTrue(saved.get("shutdown_enabled"))
        self.assertEqual(saved.get("shutdown_minutes"), 45)

    def test_junk_input_is_clamped_before_saving(self):
        """★ 脏输入**夹过再存** —— 别把 0 / 负数 / 乱码写进盘。"""
        from src.core import tool_settings

        widget = self._widget()
        widget.shutdown_check.setChecked(True)
        widget.shutdown_edit.setText("99999")
        self.app.processEvents()
        self.assertEqual(tool_settings.load("auto_combat")["shutdown_minutes"],
                         shutdown_timer.MAX_MINUTES)

    def test_stop_cancels_shutdown(self):
        """★ 手动「停止」要一并取消定时关机。

        不取消的话用户以为"停了就没事了"，结果到点电脑还是关了。
        """
        widget = self._widget()
        widget.shutdown_check.setChecked(True)
        widget.shutdown_edit.setText("30")
        widget._shutdown = shutdown_timer.ShutdownTimer(30)
        widget._shutdown.start()
        self.assertTrue(widget._shutdown.active)

        with mock.patch.object(widget._host, "stop_task", return_value=None):
            widget._on_stop()
        self.assertFalse(widget._shutdown.active,
                         "停止任务后定时关机没取消")

    def test_state_text_mentions_countdown(self):
        widget = self._widget()
        widget._shutdown = shutdown_timer.ShutdownTimer(30)
        widget._shutdown.start()
        widget._refresh_shutdown_state()
        self.assertIn("关机", widget.shutdown_state.text())


class TestNoConfirmJustShutdown(TestShutdownCard):
    """★★★ 到点**直接关机**，不再弹确认框（用户 2026-10-05）。

        用户（截图圈出「定时关机」卡片）::

            "这里改为不用确认，到时间就自动关机"

    ## ⚠⚠ 为什么原来的模态确认框不只是"烦"，而是**逻辑上是坏的**

    模态框只挡得住**调用方的代码**，``QTimer`` 轮询**照跑不误**::

        t=0     启动，deadline = 60
        t=1     should_warn → 弹模态框（用户还没点）
        t=61    should_fire → **True** ← 框还开着，电脑照样关了

    也就是说「取消关机」按钮**只有 60 秒有效期**，超时就点不动了 ——
    用户以为能取消，其实早就关了。

    改成"非模态通知 + 到点直接关"之后，这条时间线**不存在**了。

    （继承 :class:`TestShutdownCard` 复用它的 `_widget()` 装置。）
    """

    def test_no_modal_confirm_left(self):
        """★★★ 代码里**不许**再有那个模态确认框。"""
        import inspect

        from src.tools.game.auto_combat import tool as T

        self.assertFalse(
            hasattr(T.AutoCombatWidget, "_warn_before_shutdown"),
            "旧的模态确认方法还在")
        self.assertTrue(
            hasattr(T.AutoCombatWidget, "_notify_before_shutdown"),
            "没有新的非模态通知方法")

        src = inspect.getsource(T.AutoCombatWidget._notify_before_shutdown)
        self.assertNotIn("exec()", src,
                         "通知里还在 exec() —— 那就是模态框，会阻塞")

    def test_fires_without_asking(self):
        """★★★ 到点 → **直接**调关机，不问。"""
        import time

        widget = self._widget()
        calls: list[str] = []
        widget._do_shutdown = lambda: calls.append("shutdown")

        widget._shutdown = shutdown_timer.ShutdownTimer(1, warn_seconds=60)
        widget._shutdown.start()
        #: 通知已经发过（模拟"用户没理它"）
        widget._shutdown._warned = True
        widget._shutdown._deadline = time.monotonic() - 1

        widget._tick_shutdown()
        self.assertEqual(calls, ["shutdown"],
                         "到点了却没直接关机 —— 是不是又在等确认？")

    def test_warn_does_not_shutdown(self):
        """★ 进通知窗口时**只通知**，不关机。"""
        import time

        widget = self._widget()
        calls: list[str] = []
        widget._do_shutdown = lambda: calls.append("shutdown")

        widget._shutdown = shutdown_timer.ShutdownTimer(5, warn_seconds=60)
        widget._shutdown.start()
        widget._shutdown._deadline = time.monotonic() + 30   #: 还剩 30 秒

        widget._tick_shutdown()
        self.assertEqual(calls, [], "刚进通知窗口就关机了")

    def test_cancel_button_undoes_it(self):
        """★★★ 通知里的「取消」按钮**真的能撤掉**本次自动关机。

        ⚠ 去掉确认框之后，这是**唯一**的反悔路径 —— 必须好使。
        """
        from qfluentwidgets import HyperlinkButton

        widget = self._widget()
        widget._shutdown = shutdown_timer.ShutdownTimer(5, warn_seconds=60)
        widget._shutdown.start()
        self.assertTrue(widget._shutdown.active)

        widget._notify_before_shutdown()
        for _ in range(3):
            self.app.processEvents()

        btns = [b for b in widget.findChildren(HyperlinkButton)
                if b.text() == "取消"]
        self.assertTrue(btns, "通知里没有「取消」按钮")

        btns[0].click()
        self.assertFalse(widget._shutdown.active,
                         "点了取消但定时器还在跑 —— 会照样关机")

    def test_cancel_still_works_before_deadline(self):
        """★★ 通知发过之后、到点之前，取消仍然有效。

        （"到点直接关"意味着到点那一刻之后就没机会了，
        所以到点前必须一直有效。）
        """
        widget = self._widget()
        widget._shutdown = shutdown_timer.ShutdownTimer(5, warn_seconds=60)
        widget._shutdown.start()
        widget._shutdown._warned = True          #: 通知已发

        widget._cancel_shutdown("测试取消")
        self.assertFalse(widget._shutdown.active)
        self.assertIn("取消", widget.shutdown_state.text())

    def test_card_text_matches_new_behavior(self):
        """★★ 卡片**实际文案**不许再写"弹提醒 / 随时可以取消"。

        ⚠ 文案和实际行为不符比没文案更坑 —— 用户会以为还有个框在等他点。

        ⚠⚠ 别扫整个函数源码：**docstring 里会引用旧文案**（为了说明改了什么），
        那样会误报。这里只取**传给 ``ConfigCard`` 的那两行字面量**。
        """
        import inspect
        import re

        from src.tools.game.auto_combat import tool as T

        src = inspect.getsource(T.AutoCombatWidget._build_shutdown_card)
        #: 去掉 docstring（它是解释性文字，不是界面文案）
        body = re.sub(r'""".*?"""', "", src, flags=re.S)

        self.assertNotIn("随时可以取消", body,
                         "卡片文案还在说「随时可以取消」（确认框时代的话）")
        self.assertIn("弹通知", body, "卡片文案没说明会弹通知")
        self.assertIn("直接关机", body, "卡片文案没说明到点直接关")

    def test_state_line_matches_new_behavior(self):
        """★ 倒计时那行也不能再写"可取消"。"""
        widget = self._widget()
        widget._shutdown = shutdown_timer.ShutdownTimer(30)
        widget._shutdown.start()
        widget._refresh_shutdown_state()
        text = widget.shutdown_state.text()
        self.assertIn("直接关", text, f"状态行文案没更新：{text}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
