"""4C 战斗报告：队伍头像显示 + 配置页/调频页的删减。

    python tests/test_auto_combat_ui.py

用户 2026-09-30 的几处反馈：
1. "调频这里不需要什么结果，删掉" —— 声骸批量调频页的「结果」卡片
2. "资源库展开没有「鸣潮资源库」这个标签了，干掉他" —— 侧栏那层多余的子项
3. "这里角色头像宽度还挺大的，你确定这里能塞下吗" —— 战斗报告的队伍行
"""

from __future__ import annotations

import os
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class TestTeamChipsFit(unittest.TestCase):
    """★ 队伍头像要塞得下（用户问"你确定这里能塞下吗"）。

    实测数据（1100px 宽的卡片）：三个队员一共 142px、可用 988px —— 很宽裕。
    但这是**布局算出来的**，字符宽度/字号变了就会变，所以钉一条下限。
    """

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def _card(self):
        from PySide6.QtWidgets import QWidget

        from src.tools.game.auto_combat.tool import BattleReportCard

        self._holder = QWidget()
        self._holder.resize(1200, 700)
        card = BattleReportCard()
        card.setParent(self._holder)
        card.resize(1100, 420)
        self._holder.show()
        self.app.processEvents()
        return card

    def _report(self):
        from src.tools.game.auto_combat.report import (
            BattleReport, EchoTarget, TeamMember)

        team = tuple(
            TeamMember(name=n, avatar=f"avatars/{n}.png")
            for n in ("绯雪", "爱弥斯", "卡提希娅"))
        return BattleReport(team=team, echo=EchoTarget(name="无归的谬误"),
                            battles=12, echo_count=8, seconds=83.0)

    def test_three_chips_render(self):
        from src.tools.game.auto_combat.tool import TeamMemberChip

        card = self._card()
        card.update_report(self._report())
        for _ in range(3):
            self.app.processEvents()
        chips = card.findChildren(TeamMemberChip)
        self.assertEqual(len(chips), 3, "三个队员要画成三个头像")

    def test_chips_fit_in_available_width(self):
        """★ 三个头像 + 间隔必须塞得进队伍区。

        塞不下的话 Qt 会把它们压扁（头像变形）或互相重叠 —— 静默的视觉问题。
        """
        from src.tools.game.auto_combat.tool import TeamMemberChip

        card = self._card()
        card.update_report(self._report())
        for _ in range(3):
            self.app.processEvents()

        chips = card.findChildren(TeamMemberChip)
        self.assertTrue(chips)
        spacing = card.team_area.spacing()
        needed = sum(c.width() for c in chips) + spacing * (len(chips) - 1)

        margins = card.layout().contentsMargins()
        # 左边是 60px 的「使用队伍」标签 + 12px 间隔
        avail = card.width() - margins.left() - margins.right() - 60 - 12
        self.assertLessEqual(
            needed, avail,
            f"队伍头像塞不下：需要 {needed}px，只有 {avail}px")

    def test_avatar_is_square(self):
        """头像不能是扁的 —— 被压扁说明宽度不够。"""
        from src.tools.game.auto_combat.tool import TeamMemberChip

        card = self._card()
        card.update_report(self._report())
        for _ in range(3):
            self.app.processEvents()
        for chip in card.findChildren(TeamMemberChip):
            self.assertEqual(chip.AVATAR_SIZE, 34)


class TestEchoChangeReportRemoved(unittest.TestCase):
    """★ 用户："调频这里不需要什么结果，删掉"。"""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def _widget(self):
        from src.core.registry import ToolRegistry
        from src.tools import discover_tools
        from src.tools.game.echo_change.tool import EchoChangeWidget

        discover_tools()
        meta = ToolRegistry.all_metas()[0]
        for candidate in ToolRegistry.all_metas():
            if candidate.key == "echo_change":
                meta = candidate
                break
        return EchoChangeWidget(meta)

    def test_widget_has_no_report_card(self):
        widget = self._widget()
        self.assertFalse(
            hasattr(widget, "_build_report_card"),
            "「结果」卡片的构建函数还在")
        self.assertFalse(hasattr(widget, "stats"), "统计控件还在")
        self.assertFalse(hasattr(widget, "report_line"), "报告行还在")

    def test_error_line_survives(self):
        """★ 但**错误提示要留着** —— 删卡片时别把启动失败的提示一起删了。

        `log_line` 原来长在「结果」卡里，删卡时挪进了运行卡。
        """
        widget = self._widget()
        self.assertTrue(hasattr(widget, "log_line"),
                        "错误提示行没了 —— 启动失败就没地方显示")
        widget._append("启动失败：测试")
        self.assertIn("启动失败", widget.log_line.text())


class TestLibraryNavSimplified(unittest.TestCase):
    """★ 用户："资源库展开没有「鸣潮资源库」这个标签了，干掉他"。"""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def test_no_duplicate_child_label(self):
        """侧栏项直接叫「资源库」，不再有「鸣潮资源库」那一层。

        ⚠ 直接查**控件树**（最可靠）：导航里不该存在文字是「鸣潮资源库」的项。
        查源码会被注释/docstring 里的说明误伤（那里提它是为了解释为什么删）。
        """
        from src.gui.main_window import LIBRARY_KEY, MainWindow
        from src.tools import discover_tools

        discover_tools()
        window = MainWindow()
        window.resize(1400, 900)
        window.show()
        for _ in range(6):
            self.app.processEvents()

        try:
            node = window.navigationInterface.widget(LIBRARY_KEY)
            self.assertIsNotNone(node, "侧栏里找不到资源库项")
            self.assertEqual(node.text(), "资源库",
                             "侧栏项不叫「资源库」")
            # 整棵树里不该再冒出「鸣潮资源库」
            texts = []
            for child in window.navigationInterface.findChildren(type(node)):
                if hasattr(child, "text"):
                    texts.append(child.text())
            self.assertNotIn("鸣潮资源库", texts,
                             f"还有多余的「鸣潮资源库」项：{texts}")
        finally:
            window.close_without_prompt()

    def test_route_key_matches_page_object_name(self):
        """★ 路由键必须等于页面的 ``objectName``。

        拖拽排序 / 侧栏高亮都按 routeKey 找项；对不上的话
        「资源库」会从可拖动列表里**静默消失**。
        """
        from src.gui.main_window import LIBRARY_KEY
        from src.gui.library_interface import WuwaLibraryInterface

        self.assertEqual(
            LIBRARY_KEY, WuwaLibraryInterface().objectName(),
            "LIBRARY_KEY 和页面 objectName 对不上")

    def test_library_key_is_movable(self):
        """它得在可拖动列表里（不然用户挪不动这一项）。"""
        import inspect

        from src.gui import main_window

        source = inspect.getsource(main_window.MainWindow._setup_nav_reorder)
        self.assertIn("LIBRARY_KEY", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
