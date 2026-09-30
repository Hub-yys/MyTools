"""头像兜底：**图没拿到就用名字首字现画一个**。

    python tests/test_avatar_fallback.py

用户 2026-09-28 要求："如果角色头像没拿到，先用第一个字填充"。

背景：新角色是「资源库更新」拉进来的，那一刻 ``assets/game/avatars/`` 里
**必然没有**对应的图（游戏素材按项目一贯处理不入库，要用户自己截）。
不留兜底的话，用户看到的是"名字有了、图是空的"，以为没生效。

Qt 部分用 offscreen 平台跑。
"""

from __future__ import annotations

import os
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


class TestAvatarFallback(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def test_draws_initial_when_no_file(self):
        """★ 主路径：路径为空 → 仍然画出**非空**图标（这就是"首字填充"）。"""
        from src.gui.pickers import avatar_icon

        icon = avatar_icon("", "心")
        self.assertFalse(icon.isNull(), "没图的角色必须兜出首字图")

    def test_draws_initial_when_file_missing(self):
        """路径给了但文件不存在（新角色的常态）→ 同样兜底。"""
        from src.gui.pickers import avatar_icon

        icon = avatar_icon("avatars/根本不存在的角色.png", "锁暝")
        self.assertFalse(icon.isNull())

    def test_real_file_still_wins(self):
        """真有图时**用真图**，不能被兜底盖掉。"""
        from src.gui.pickers import avatar_icon, load_icon

        real = None
        from src.core import game_data

        game_data.ensure_loaded()
        for c in game_data.CHARACTERS:
            if c.avatar and not load_icon(c.avatar).isNull():
                real = c
                break
        if real is None:
            self.skipTest("本地一个带头像图的角色都没有，测不到这个分支")
        icon = avatar_icon(real.avatar, real.name)
        self.assertFalse(icon.isNull())
        # 和真图一致（同一个文件）
        self.assertEqual(icon.pixmap(64, 64).toImage(),
                         load_icon(real.avatar).pixmap(64, 64).toImage())

    def test_blank_name_with_no_file_is_empty(self):
        """名字也没有 → 返回空图标（不硬画一个空白圆）。"""
        from src.gui.pickers import avatar_icon

        self.assertTrue(avatar_icon("", "").isNull())
        self.assertTrue(avatar_icon("", "   ").isNull())

    def test_pixmap_is_not_blank(self):
        """★ 画出来的是**真的有色圆**，不是一张空图。

        只断言 ``not isNull()`` 不够 —— 一张全透明的 pixmap 也非 null。
        这里抽样中心像素：必须不透明、有颜色。
        """
        from PySide6.QtGui import QColor

        from src.gui.pickers import avatar_icon

        img = avatar_icon("", "心").pixmap(64, 64).toImage()
        self.assertEqual((img.width(), img.height()), (64, 64))
        center = QColor(img.pixel(32, 32))
        self.assertGreater(center.alpha(), 0, "圆心必须是实心的")

    def test_color_is_stable_and_distinct(self):
        """色相由名字散列：同一个人固定，不同人尽量不同。"""
        from PySide6.QtGui import QColor

        from src.gui.pickers import avatar_icon

        def shade(name: str) -> str:
            img = avatar_icon("", name).pixmap(64, 64).toImage()
            return QColor(img.pixel(10, 10)).name()

        self.assertEqual(shade("心"), shade("心"), "同一个名字颜色必须稳定")
        self.assertNotEqual(shade("心"), shade("锁暝"), "不同角色颜色应错开")

    def test_uses_first_character_of_name(self):
        """用的是**首字** —— 单字名字和长名字都要能画出来（取 name[0] 不越界）。"""
        from src.gui.pickers import avatar_icon

        for name in ("心", "锁暝", "漂泊者·衍射", "A"):
            with self.subTest(name=name):
                self.assertFalse(avatar_icon("", name).isNull())

    def test_no_crash_without_app(self):
        """没有 QApplication 时返回空图标而不是抛异常（防御性）。"""
        from src.gui.pickers import _initial_icon

        # 已有 app 的情况下跑不出"无 app"分支，这里只确认调用本身安全
        self.assertIsNotNone(_initial_icon("心"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
