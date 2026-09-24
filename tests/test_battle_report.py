"""战斗报告的数据层单测。

★ 设计前提：**数字全部来自 ok-ww 自己的计数器**（``info['Combat Count']`` /
  ``info['Echo Count']`` / ``task.chars`` / ``task.aim_boss``），见 ``report.py`` 的模块
  文档。所以这里用**假 task 对象**就能把全部分支覆盖掉 —— 不需要游戏、不需要引擎。

重点盯四件事：

1. **取差值**：ok-ww 的 ``info`` 在同一进程内跨次累加，报告要的是"本次运行"；
2. **时长冻结**：停止之后不能再跟着墙上时钟走字；
3. **声骸两条分支**：识别出来（带图标）／没识别出来（档位名 + 标记）；
4. **名字转中文 + 头像匹配**：靠 ok-ww 的 i18n（``zh_CN/ok.po``）+ MyTools 角色数据。
"""

from __future__ import annotations

import pathlib
import sys
import unittest
from pathlib import Path

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.tools.game.auto_combat import report  # noqa: E402


def fake_char(class_name: str):
    """造一个"类名 = ok-ww 角色类名"的假角色对象（ok-ww 就是按类名翻译的）。"""
    return type(class_name, (), {})()


class FakeTask:
    """够 report.py 读的假任务对象。"""

    def __init__(self, *, info=None, chars=(), aim_boss="", boss="Other"):
        self.info = dict(info or {})
        self.chars = list(chars)
        self.aim_boss = aim_boss
        self.config = {"Boss": boss}


# --------------------------------------------------------------------- .po

class TestParsePo(unittest.TestCase):
    def test_basic_and_untranslated(self):
        table = report.parse_po('msgid "A"\nmsgstr "甲"\n\nmsgid "B"\nmsgstr ""\n')
        self.assertEqual(table.get("A"), "甲")
        self.assertNotIn("B", table, "没译文的条目不该进表（否则名字会变空）")

    def test_multiline_and_escapes(self):
        text = 'msgid "A"\nmsgstr ""\n"甲\\n乙"\n'
        self.assertEqual(report.parse_po(text).get("A"), "甲\n乙")

    def test_real_po_has_character_names(self):
        """真·ok-ww 的 i18n 必须能解析出角色中文名 —— 名字对不上，头像就全没了。"""
        table = report.zh_names()
        self.assertGreater(len(table), 100, "解析出的译文太少，可能 .po 格式变了")
        for english, chinese in (("Jinhsi", "今汐"), ("Camellya", "椿"), ("Chixia", "炽霞")):
            self.assertEqual(table.get(english), chinese, f"{english} 的译文不对")


# ------------------------------------------------------------------ 时长格式

class TestFormatDuration(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(report.format_duration(0), "00:00")
        self.assertEqual(report.format_duration(59), "00:59")
        self.assertEqual(report.format_duration(60), "01:00")
        self.assertEqual(report.format_duration(3599), "59:59")
        self.assertEqual(report.format_duration(3600), "1:00:00")
        self.assertEqual(report.format_duration(3661), "1:01:01")

    def test_negative_clamped(self):
        self.assertEqual(report.format_duration(-5), "00:00")


# -------------------------------------------------------------------- 取差值

class TestDelta(unittest.TestCase):
    def test_normal_delta(self):
        self.assertEqual(report._delta(7, 5), 2)

    def test_info_reset_falls_back_to_current(self):
        """万一下次运行把 info 重置了（当前 < 基线），直接用当前值，别出现负数。"""
        self.assertEqual(report._delta(3, 9), 3)

    def test_zero_baseline(self):
        self.assertEqual(report._delta(4, 0), 4)


class TestSnapshot(unittest.TestCase):
    def test_reads_counters(self):
        task = FakeTask(info={"Combat Count": 6, "Echo Count": 2})
        self.assertEqual(report.snapshot_counters(task), {"battles": 6, "echoes": 2})

    def test_missing_info_is_zero(self):
        self.assertEqual(report.snapshot_counters(FakeTask()), {"battles": 0, "echoes": 0})


# -------------------------------------------------------------------- 队伍

class TestTeam(unittest.TestCase):
    def test_english_to_chinese_and_avatar(self):
        team = report.resolve_team([fake_char("Jinhsi"), fake_char("Camellya")])
        self.assertEqual([m.name for m in team], ["今汐", "椿"])
        self.assertEqual(team[0].avatar, "avatars/今汐.png")
        self.assertTrue(team[0].resolved, "数据集里有这个角色，应标记为已对上（才有头像）")

    def test_mismatched_names_alias(self):
        """守岸人在 ok-ww 里类名是 ``ShoreKeeper``，但 .po 的键是 ``Shorekeeper``。"""
        team = report.resolve_team([fake_char("ShoreKeeper")])
        self.assertEqual(team[0].name, "守岸人")

    def test_unknown_char_keeps_english_and_no_avatar(self):
        team = report.resolve_team([fake_char("SomeNewChar")])
        self.assertEqual(team[0].name, "SomeNewChar")
        self.assertEqual(team[0].avatar, "")
        self.assertFalse(team[0].resolved)

    def test_skips_none(self):
        team = report.resolve_team([None, fake_char("Jinhsi"), None])
        self.assertEqual([m.name for m in team], ["今汐"])

    def test_empty(self):
        self.assertEqual(report.resolve_team(None), ())


# ------------------------------------------------------------------ 战斗声骸

class TestEcho(unittest.TestCase):
    def test_identified_uses_aim_boss_with_icon(self):
        target = report.resolve_echo(FakeTask(aim_boss="异构武装"))
        self.assertEqual(target.name, "异构武装")
        self.assertTrue(target.identified)
        self.assertEqual(target.icon, "echoes/异构武装.png")

    def test_unidentified_uses_profile_name(self):
        target = report.resolve_echo(FakeTask(aim_boss="", boss="Fenrico"))
        self.assertEqual(target.name, "Fenrico")
        self.assertFalse(target.identified, "没识别出来就必须标未识别")
        self.assertEqual(target.icon, "")

    def test_other_profile_is_unknown(self):
        target = report.resolve_echo(FakeTask(aim_boss="", boss="Other"))
        self.assertEqual(target.name, "未知")
        self.assertFalse(target.identified)


# ------------------------------------------------------------------ 报告本体

class TestReadReport(unittest.TestCase):
    def _report(self, **kwargs):
        task = kwargs.pop("task")
        params = {"baseline": {"battles": 5, "echoes": 1}, "started_at": 1000.0, "now": 1000.0}
        params.update(kwargs)
        return report.read_report(task, **params)

    def test_subtracts_baseline(self):
        task = FakeTask(info={"Combat Count": 8, "Echo Count": 3})
        result = self._report(task=task)
        self.assertEqual(result.battles, 3)
        self.assertEqual(result.echo_count, 2)

    def test_duration_grows_while_running(self):
        task = FakeTask()
        result = self._report(task=task, running=True, now=1252.0)
        self.assertAlmostEqual(result.seconds, 252.0)
        self.assertEqual(result.duration_text, "04:12")

    def test_duration_freezes_after_stop(self):
        """停止之后 now 再往前走，时长也必须钉在被停的那一刻。"""
        task = FakeTask()
        result = self._report(task=task, stopped_at=1252.0, now=99999.0)
        self.assertAlmostEqual(result.seconds, 252.0)
        self.assertFalse(result.running)

    def test_zero_duration_when_never_started(self):
        task = FakeTask()
        self.assertEqual(self._report(task=task, started_at=0.0).duration_text, "00:00")

    def test_full_snapshot(self):
        task = FakeTask(info={"Combat Count": 7, "Echo Count": 2},
                        chars=[fake_char("Jinhsi"), fake_char("Camellya")],
                        aim_boss="罗蕾莱")
        result = self._report(task=task, running=True, now=1200.0)
        self.assertEqual(result.battles, 2)
        self.assertEqual(result.echo_count, 1)
        self.assertEqual(result.echo.name, "罗蕾莱")
        self.assertTrue(result.echo.identified)
        self.assertEqual(result.team_text, "今汐、椿")
        self.assertEqual(result.duration_text, "03:20")

    def test_no_team_yet(self):
        result = self._report(task=FakeTask())
        self.assertEqual(result.team, ())
        self.assertEqual(result.team_text, "还没识别到")


# ------------------------------------------------------------- 拾取角标统计

class TestClassifyBadges(unittest.TestCase):
    def test_locked(self):
        self.assertEqual(report.classify_badges(["echo_locked"]), report.LOCKED)

    def test_dropped(self):
        self.assertEqual(report.classify_badges(["echo_dropped"]), report.DROPPED)

    def test_not_states_mean_neither(self):
        for names in (["echo_not_locked"], ["echo_not_dropped"],
                      ["echo_not_locked", "echo_not_dropped"]):
            self.assertEqual(report.classify_badges(names), report.NONE, names)

    def test_nothing_found_is_neither(self):
        """一个角标都没看到也算「都没」—— 区域要是错了，会在报告里表现为锁定/弃置恒 0。"""
        self.assertEqual(report.classify_badges([]), report.NONE)

    def test_locked_beats_dropped(self):
        """两个都匹配到时以「锁定」为准（锁定是用户最关心的那个数）。"""
        self.assertEqual(report.classify_badges(["echo_dropped", "echo_locked"]),
                         report.LOCKED)

    def test_ignores_empty_names(self):
        self.assertEqual(report.classify_badges(["", None]), report.NONE)


class TestPickupTally(unittest.TestCase):
    def setUp(self):
        report.reset_pickup_tally()
        self.addCleanup(report.reset_pickup_tally)

    def test_counts_by_state(self):
        for state in (report.LOCKED, report.LOCKED, report.DROPPED, report.NONE):
            report.tally_pickup(state)
        tally = report.pickup_tally()
        self.assertEqual((tally.locked, tally.dropped, tally.none), (2, 1, 1))
        self.assertEqual(tally.total, 4)

    def test_unknown_state_counts_as_neither(self):
        report.tally_pickup("莫名其妙的状态")
        self.assertEqual(report.pickup_tally().none, 1)

    def test_reset_clears(self):
        report.tally_pickup(report.LOCKED)
        report.reset_pickup_tally()
        self.assertEqual(report.pickup_tally().total, 0)

    def test_snapshot_is_a_copy(self):
        """``pickup_tally()`` 必须给副本 —— 否则任务线程一计数，界面手里的数就跟着跳。"""
        report.tally_pickup(report.LOCKED)
        snapshot = report.pickup_tally()
        report.tally_pickup(report.LOCKED)
        self.assertEqual(snapshot.locked, 1, "拿到的是同一个对象，被后来的计数改掉了")

    def test_report_carries_tally(self):
        """走一遍真实集成路径：计数 → read_report 读到。"""
        report.tally_pickup(report.LOCKED)
        result = report.read_report(FakeTask(), baseline={}, started_at=1000.0, now=1000.0)
        self.assertEqual(result.pickups.locked, 1)

    def test_report_accepts_injected_tally(self):
        injected = report.PickupTally(locked=7, dropped=1, none=2)
        result = report.read_report(FakeTask(), baseline={}, pickups=injected)
        self.assertEqual(result.pickups.locked, 7)
        self.assertEqual(result.pickups.total, 10)


if __name__ == "__main__":
    unittest.main(verbosity=2)
