# -*- coding: utf-8 -*-
"""扫荡残像聚落 —— **卡片布局**的回归测试。

## 这个测试在保什么

用户为了"卡片长得对不对"来回改了 **六轮**，每一轮的问题都很具体：

| 轮次 | 用户说的 | 根因 |
|---|---|---|
| ③ | 居中 | 套装在上、名字在下但没居中 |
| ④ | 排列要整齐 | 套装数量不等（7/6/1 套）→ 卡片高度不一 |
| ⑤ | 名称在上，按钮在下 | 勾选框跟名字**并排**，把名字推右了 |
| ⑤ | 没有对齐 / 这个位置偏了 | 量的是**控件**，眼睛看的是**指示器** |
| ⑥ | 没修啊，还是不对齐 | **行距漂移**（41/42 vs 40/41）+ 单套卡起点偏 4px |

**这些全部是"看起来没对齐"而不是"报错"** —— 所以要靠测试钉住，
不能靠下次谁再肉眼看一遍。

## ⚠ 这个测试要 Qt

没有 Qt（headless CI / 没装 PySide6）时**整类跳过**，不报失败 ——
布局是界面的事，不该让纯逻辑环境挂掉。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    from PySide6.QtWidgets import QApplication, QLabel, QWidget

    _HAS_QT = True
except Exception:                                    # noqa: BLE001
    _HAS_QT = False

if _HAS_QT:
    from src.core.nest_sweep import load_catalog
    from src.tools.game.nest_sweep.tool import (
        SET_ICON_SIZE,
        SET_ROW_GAP,
        TargetCard,
    )


@unittest.skipUnless(_HAS_QT, "需要 PySide6")
class TestCardAlignment(unittest.TestCase):
    """卡片的几何一致性 —— 用户改了六轮的那个"对齐"。"""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.cards = []
        for target in load_catalog():
            #: ⚠ **必须勾上** —— 未勾选的 CheckBox 是**灰色描边空框**，
            #:   青色检测找不到它（实测：只有第 1 张卡碰巧通过了）。
            card = TargetCard(target, True, lambda *a: None)
            card.setFixedWidth(355)
            card.show()
            cls.cards.append(card)
        for _ in range(10):
            cls.app.processEvents()

    @classmethod
    def tearDownClass(cls):
        for card in cls.cards:
            card.hide()
            card.deleteLater()

    # ---------------------------------------------------------- 几何工具
    @staticmethod
    def _icons(card):
        """卡片里的套装图标（固定成 SET_ICON_SIZE 的 QLabel）。"""
        return [w for w in card.findChildren(QLabel)
                if w.width() == SET_ICON_SIZE]

    @staticmethod
    def _points(card):
        return sorted({(lb.mapTo(card, lb.rect().topLeft()).x(),
                        lb.mapTo(card, lb.rect().topLeft()).y())
                       for lb in TestCardAlignment._icons(card)})

    # ---------------------------------------------------------- ① 行距
    def test_row_pitch_is_identical_across_cards(self):
        """★★ 行距必须处处相同 —— 这是「没修啊，还是不对齐」那条。

        修之前实测：6 套的卡行距 41/42、7 套的 40/41（差 1~2px 就看得出来）。
        根因是**固定高度和实际内容高度对不上**，Qt 把差额摊到各行上。
        """
        pitches = set()
        for card in self.cards:
            ys = sorted({y for _x, y in self._points(card)})
            for i in range(len(ys) - 1):
                pitches.add(ys[i + 1] - ys[i])
        self.assertEqual(
            len(pitches), 1,
            f"行距不一致：{sorted(pitches)}（各卡的套装行必须等距）")

    def test_first_row_starts_at_same_y(self):
        """★★ 所有卡的第一行必须在**同一个 y** 上（顶对齐）。

        修之前：**1 套的卡起点 y=18，多套的是 14**（差 4px）。
        根因：``QVBoxLayout`` 把剩余空间摊给子项，单行卡那一行被拉高，
        图标在拉高的 chip 里垂直居中就往下跑了。
        —— 修法是补**等高的空行**，而不是只 ``addSpacing``。
        """
        firsts = {min(y for _x, y in self._points(c)) for c in self.cards}
        self.assertEqual(len(firsts), 1,
                         f"第一行 y 不一致：{sorted(firsts)}")

    def test_card_height_follows_content(self):
        """★★ 卡片高度**跟随内容**（套装少的卡就该矮）。

        ⚠ 这条**推翻了第 ④ 轮那条**「所有卡片等高」——

        * 第 ④ 轮用户说「排列要整齐」→ 我做成"所有卡等高"（固定 4 行）
        * 第 ⑨ 轮用户说「这种只有一种的，卡片自适应所需，内容并且居中」
          → 明确**不要**等高了：1 套的卡就该是 1 套那么高

        现在保的是"**矮卡确实矮**"，以及"同行矮卡的内容居中"
        （见 ``test_card_content_is_vertically_centered``）。
        """
        by_count: dict[int, set] = {}
        for card in self.cards:
            by_count.setdefault(len(card.target.sets), set()).add(card.height())
        #: 1 套的卡必须**明显矮于** 7 套的卡
        if 1 in by_count and 7 in by_count:
            one = min(by_count[1])
            seven = max(by_count[7])
            self.assertLess(one, seven,
                            f"1 套的卡({one}) 不比 7 套的卡({seven}) 矮 —— "
                            f"自适应没生效")
        #: 同一套装数量的卡片必须等高（否则同类之间还是参差）
        for count, hs in by_count.items():
            with self.subTest(sets=count):
                self.assertEqual(len(hs), 1,
                                 f"{count} 套的卡片高度不一致：{sorted(hs)}")

    # ---------------------------------------------------------- ② 居中
    def test_name_text_is_centered(self):
        """★ 名字文字必须落在卡片中线上。

        ⚠ 量的是**看得见的文字**，不是控件外框 ——
        ``widget.grab()`` 出的图比控件大，要按比例换算回控件坐标。
        """
        import numpy as np
        import cv2

        for card in self.cards:
            nl = card.name_label
            p = ROOT / f"_tmp_name_{card.target.key.replace(':', '_')}.png"
            nl.grab().save(str(p))
            buf = np.fromfile(str(p), dtype=np.uint8)
            p.unlink(missing_ok=True)
            im = cv2.imdecode(buf, cv2.IMREAD_COLOR)
            gray = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
            cols = np.where((gray < 150).any(axis=0))[0]
            if not len(cols):
                continue
            ratio = nl.width() / im.shape[1]
            centre = nl.x() + (cols.min() + cols.max()) / 2 * ratio
            with self.subTest(name=card.target.name):
                self.assertLess(abs(centre - card.width() / 2), 2.0,
                                f"{card.target.name} 的名字没居中"
                                f"（偏移 {centre - card.width() / 2:+.1f}px）")

    def test_checkbox_indicator_is_centered(self):
        """★★ 勾选框的**指示器**必须落在中线上。

        ⚠ 这就是「这个位置偏了」那条：``CheckBox("")`` 的指示器
        **画在固定的左侧位置**（实测中心离控件左缘 ~10.5px，与宽度无关），
        控件居中时指示器**偏左约 4px**。所以要靠 ``CHECK_NUDGE`` 垫。

        ⚠ 指示器是**青绿色**（teal，HSV 的 H≈90）—— 只找"蓝色"(H 100-135)
        会一个都找不到（我在这上面白跑过一轮）。
        """
        import numpy as np
        import cv2

        for card in self.cards:
            ck = card.check
            p = ROOT / f"_tmp_check_{card.target.key.replace(':', '_')}.png"
            ck.grab().save(str(p))
            buf = np.fromfile(str(p), dtype=np.uint8)
            p.unlink(missing_ok=True)
            im = cv2.imdecode(buf, cv2.IMREAD_COLOR)
            hsv = cv2.cvtColor(im, cv2.COLOR_BGR2HSV)
            mark = ((hsv[:, :, 0] > 75) & (hsv[:, :, 0] < 135) &
                    (hsv[:, :, 1] > 60) & (hsv[:, :, 2] > 100))
            xs = np.where(mark.any(axis=0))[0]
            if not len(xs):
                self.fail(f"{card.target.name} 找不到勾选框指示器")
            ratio = ck.width() / im.shape[1]
            centre = ck.x() + (xs.min() + xs.max()) / 2 * ratio
            with self.subTest(name=card.target.name):
                self.assertLess(abs(centre - card.width() / 2), 2.0,
                                f"{card.target.name} 的勾选框没居中"
                                f"（偏移 {centre - card.width() / 2:+.1f}px）")

    # ---------------------------------------------------------- ③ 列对齐
    def test_set_columns_are_aligned_across_rows(self):
        """★★ 套装的两列必须**列位置固定** —— 每张卡、每一行都一样。

        ⚠⚠ 这是用户**第 8 轮**说的「还是没对齐啊」的根因，
        而且是我改动前**自己就能复现**的：

        ::

            改前（每行一个 QHBoxLayout，列宽由内容决定）:
                梦枢天罗  第2列 x = [181, 181, 129]   ★ 漂移 52px
                落渊南丘  第2列 x = [181, 181, 129]   ★ 漂移 52px
                陷足流川  第2列 x = [181, 181, 181]   ✔ 齐（恰好内容一样宽）

        用户说「陷足流川这是对齐，为什么**不参考**这些呢」——
        他指的参照物就是恰好没漂的那张。改成 ``QGridLayout`` 之后
        **列宽由整列最宽的决定**，所有行必然同 x。

        ⚠ 只量「行距一致」是不够的（我前几轮就是这么漏掉的）——
        行距可以完全一致，列却仍在漂。
        """
        if not _HAS_QT:
            self.skipTest("需要 PySide6")
        from src.tools.game.nest_sweep.tool import SET_ICON_SIZE

        seen: dict[int, set] = {}
        for card in self.cards:
            icons = [lb for lb in card.findChildren(QLabel)
                     if lb.width() == SET_ICON_SIZE]
            rows: dict[int, list[int]] = {}
            for lb in icons:
                p = lb.mapTo(card, lb.rect().topLeft())
                rows.setdefault(p.y(), []).append(p.x())
            for ys, xs in rows.items():
                for i, x in enumerate(sorted(xs)):
                    seen.setdefault(i, set()).add(x)

        self.assertTrue(seen, "一个套装图标都没找到")
        for col, xs in sorted(seen.items()):
            with self.subTest(column=col + 1):
                self.assertEqual(
                    len(xs), 1,
                    f"第 {col + 1} 列的 x 有 {len(xs)} 种 {sorted(xs)} —— "
                    f"列位置在漂（用户说的「没对齐」）")

    # ---------------------------------------------------------- ④ 高度算式
    def test_block_height_matches_layout_math(self):
        """★ 套装区高度必须**精确等于**实际内容高度（**按实际行数**）。

        对不上时 Qt 会把差额摊到各行上 → 行距漂移（见上面那条）。
        这条把算式钉住，免得以后有人只改 ``SET_ROW_GAP`` 忘了另一边。

        ⚠ 第 ⑨ 轮起高度**按实际行数**算（不再是固定 4 行）——
        用户原话：「这种只有一种的，卡片自适应所需，内容并且居中」。
        所以这里对 1/2/3/4 行都验一遍。
        """
        for rows in (0, 1, 2, 3, 4, 5):
            with self.subTest(rows=rows):
                if rows <= 0:
                    expect = 2
                else:
                    expect = (2 + rows * SET_ICON_SIZE
                              + (rows - 1) * SET_ROW_GAP)
                self.assertEqual(TargetCard._sets_block_height(rows), expect)

    def test_rows_follow_the_set_count(self):
        """★ 行数必须跟着套装数量走（这就是「自适应所需」）。"""
        from src.tools.game.nest_sweep.tool import SET_COLUMNS

        for count in range(0, 9):
            with self.subTest(count=count):
                sets = tuple(f"套装{i}" for i in range(count))
                expect = ((count + SET_COLUMNS - 1) // SET_COLUMNS
                          if count else 0)
                self.assertEqual(TargetCard._sets_rows(sets), expect)

    def test_single_set_card_is_shorter_than_full_card(self):
        """★★ 只有 1 套的卡必须**明显矮于** 7 套的卡。

        ⚠ 这正是用户第 ⑨ 轮圈出来的问题：那 5 张梦魇卡各自
        留了 **3 行空白**（约 105px 的洞）。改前两者的「套装区高度」
        是一模一样的（都按固定 4 行算）——
        现在必须拉开差距。
        """
        from src.tools.game.nest_sweep.tool import SET_ICON_SIZE

        one = TargetCard._sets_block_height(TargetCard._sets_rows(("甲",)))
        seven = TargetCard._sets_block_height(
            TargetCard._sets_rows(tuple(f"套装{i}" for i in range(7))))
        self.assertLess(one, seven)
        #: 差得足够明显（至少 2 行）
        self.assertGreaterEqual(seven - one, 2 * SET_ICON_SIZE,
                                "1 套和 7 套的套装区高度差不够（还是留大洞）")

    def test_card_content_is_vertically_centered(self):
        """★★ 卡片内容要**垂直居中**（用户第 ⑨ 轮的另一半要求）。

        同行卡片被 ``QGridLayout`` 拉成等高，矮卡不加 stretch 就会
        **顶着上边、下面留洞**。判据：上下两侧的空白大致相等。

        ⚠ **必须把卡片"拉高"才能测** —— 单独摆一张卡时它会缩到自然高度，
        上下留白天然相等，测不出居中与否。
        （我第一版就是这么写的，注入 bug 之后**没抓到** ——
        这个测试本身是假的。用 ``setMinimumHeight`` 模拟网格拉高才有效。）
        """
        if not _HAS_QT:
            self.skipTest("需要 PySide6")
        from PySide6.QtWidgets import QWidget

        for card in self.cards:
            #: 模拟"被同行的高卡片拉高"：多给 120px
            natural = card.sizeHint().height()
            card.setFixedHeight(natural + 120)
            card.show()
            for _ in range(5):
                self.app.processEvents()

            blocks = [b for b in card.findChildren(QWidget)
                      if b.width() > 0 and b.height() > 0]
            tops, bots = [], []
            for b in blocks:
                g = b.mapTo(card, b.rect().topLeft())
                if g.y() < 0 or g.y() + b.height() > card.height():
                    continue
                tops.append(g.y())
                bots.append(g.y() + b.height())
            if not tops:
                continue
            top_gap = min(tops)
            bottom_gap = card.height() - max(bots)
            with self.subTest(name=card.target.name):
                self.assertLessEqual(
                    abs(top_gap - bottom_gap), 36,
                    f"{card.target.name} 内容没居中：上留白 {top_gap}px、"
                    f"下留白 {bottom_gap}px（差 {abs(top_gap - bottom_gap)}px）")
            #: 测完还原，免得影响其他测试
            card.setMinimumHeight(0)
            card.setMaximumHeight(16777215)
            card.adjustSize()


if __name__ == "__main__":
    unittest.main()
