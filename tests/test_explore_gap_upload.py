# -*- coding: utf-8 -*-
"""「上传视频」的界面行为测试（**不弹真对话框、不建真库**）。

## 为什么这批测试重要

用户的原话是「**我上传一个视频**，你能跟着视频做」——
所以"上传"是这个工具的入口动作。入口坏了整个工具就没法用。

而上传有**两条路**，两条都必须能走通、而且判断必须一致：

    ① 拖进来（drag & drop）
    ② 点按钮选文件 / 粘路径

⚠ 两条路各写一份"这文件是不是视频"的判断，迟早会不一致
（一个收 mkv、一个不收）。所以两条路都走
:func:`src.tools.game.explore_gap.tool.looks_like_video` ——
这批测试就是钉这一点的。

## 怎么测（不碰真实文件系统之外的东西）

拖放事件用合成的 ``QDropEvent`` 喂进去 —— **不启动真拖拽**
（真拖拽要鼠标、要窗口管理器，CI 上跑不了）。
"""

from __future__ import annotations

import os
import pathlib
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QMimeData, QPoint, Qt, QUrl  # noqa: E402
from PySide6.QtGui import QDropEvent                    # noqa: E402
from PySide6.QtWidgets import QApplication              # noqa: E402

from src.tools.game.explore_gap.tool import (          # noqa: E402
    VIDEO_FILTER,
    VIDEO_SUFFIXES,
    DropZone,
    ExploreGapPanel,
    looks_like_video,
)

_app = QApplication.instance() or QApplication([])


def drop_event(paths: list[str]) -> tuple[QDropEvent, QMimeData]:
    """合成一个"拖进来"的事件（不启动真拖拽）。

    :return: ``(事件, mime)`` —— ★ **必须把 mime 一起返回**。

    ## ⚠⚠ 为什么要返回 mime（踩过的坑）

    ``QDropEvent`` **不持有** ``QMimeData`` 的所有权。只返回事件的话，
    mime 在 :func:`drop_event` 返回时就被 Python 回收了，之后
    ``event.mimeData()`` 拿到的是一个**裸 QObject**（没有 ``hasUrls``）——::

        AttributeError: 'PySide6.QtCore.QObject' object has no attribute 'hasUrls'

    这个错看着像"事件构造得不对"，其实是**生命周期**问题：
    我在函数里单独跑同样的代码是对的（那里 mime 还活着），
    放进测试函数就炸。所以调用方要接住并**留着**这个引用::

        event, _mime = drop_event([...])
        zone.dropEvent(event)

    （另一个坑：``Qt`` 必须**在文件顶部**导入。我第一版写在函数下面，
    参数错位后 QMimeData 被当成 pos，报的还是同一个 hasUrls 错。）
    """
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(p) for p in paths])
    event = QDropEvent(QPoint(10, 10), Qt.MoveAction, mime,
                       Qt.LeftButton, Qt.NoModifier)
    return event, mime


class TestLooksLikeVideo(unittest.TestCase):
    """★ 两条上传路共用的判断 —— 只此一份。"""

    def test_accepts_common_formats(self):
        for suffix in VIDEO_SUFFIXES:
            with self.subTest(suffix=suffix):
                self.assertTrue(looks_like_video(f"a{suffix}"))

    def test_case_insensitive(self):
        for name in ("a.MP4", "a.Mp4", "a.MKV"):
            with self.subTest(name=name):
                self.assertTrue(looks_like_video(name))

    def test_rejects_non_video(self):
        for name in ("a.txt", "a.png", "a.json", "a", "a.mp4.bak"):
            with self.subTest(name=name):
                self.assertFalse(looks_like_video(name))

    def test_rejects_empty(self):
        self.assertFalse(looks_like_video(""))
        self.assertFalse(looks_like_video(None))

    def test_chinese_name_ok(self):
        self.assertTrue(looks_like_video("无光之森找宝箱.mp4"))

    def test_filter_covers_all_suffixes(self):
        """选择框的过滤器要把所有收的格式都列上。

        不然会出现"拖进来能收、点按钮选不到"的怪事。
        """
        for suffix in VIDEO_SUFFIXES:
            with self.subTest(suffix=suffix):
                self.assertIn(suffix, VIDEO_FILTER)


class TestDropZone(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.zone = DropZone()
        self.addCleanup(self.zone.deleteLater)
        self.got: list[str] = []
        self.zone.dropped.connect(self.got.append)

    def _video(self, name: str = "a.mp4") -> str:
        p = self.dir / name
        p.write_bytes(b"fake")
        return str(p)

    def test_drop_emits_path(self):
        path = self._video()
        event, _mime = drop_event([path])
        self.zone.dropEvent(event)
        self.assertEqual(self.got, [path])

    def test_drop_non_video_ignored(self):
        p = self.dir / "note.txt"
        p.write_bytes(b"x")
        event, _mime = drop_event([str(p)])
        self.zone.dropEvent(event)
        self.assertEqual(self.got, [], "非视频不该被收下")

    def test_drop_nonexistent_ignored(self):
        event, _mime = drop_event([str(self.dir / "没有这个.mp4")])
        self.zone.dropEvent(event)
        self.assertEqual(self.got, [])

    def test_drop_picks_video_among_others(self):
        """★ 一次拖多个文件时，要挑出那个**视频**。

        只取 ``urls()[0]`` 的话，用户拖了"说明.txt + 攻略.mp4"
        就会因为第一个是 txt 而整个拒绝。
        """
        txt = self.dir / "说明.txt"
        txt.write_bytes(b"x")
        video = self._video("攻略.mp4")
        event, _mime = drop_event([str(txt), video])
        self.zone.dropEvent(event)
        self.assertEqual(self.got, [video])

    def test_drop_empty_ignored(self):
        mime = QMimeData()
        event = QDropEvent(QPoint(0, 0), Qt.MoveAction, mime,
                           Qt.LeftButton, Qt.NoModifier)
        self.zone.dropEvent(event)
        self.assertEqual(self.got, [])
    def test_drag_enter_accepts_video(self):
        path = self._video()

        class Ev:
            def __init__(self, mime):
                self._mime = mime
                self.accepted = False

            def mimeData(self):
                return self._mime

            def acceptProposedAction(self):
                self.accepted = True

            def ignore(self):
                self.accepted = False

        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(path)])
        ev = Ev(mime)
        self.zone.dragEnterEvent(ev)
        self.assertTrue(ev.accepted, "拖视频进来时该接受（不然光标显示禁止）")

    def test_drag_enter_rejects_non_video(self):
        p = self.dir / "x.txt"
        p.write_bytes(b"x")

        class Ev:
            def __init__(self, mime):
                self._mime = mime
                self.accepted = True

            def mimeData(self):
                return self._mime

            def acceptProposedAction(self):
                self.accepted = True

            def ignore(self):
                self.accepted = False

        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(p))])
        ev = Ev(mime)
        self.zone.dragEnterEvent(ev)
        self.assertFalse(ev.accepted)


class TestPanelUpload(unittest.TestCase):
    """面板上的"上传"—— 状态与按钮使能。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.panel = ExploreGapPanel()
        self.addCleanup(self.panel.deleteLater)

    def _video(self, name: str = "攻略.mp4") -> str:
        p = self.dir / name
        p.write_bytes(b"fake")
        return str(p)

    def test_build_disabled_until_video_chosen(self):
        """没选视频时"开始建库"该是灰的（别让用户点了才报错）。"""
        self.assertFalse(self.panel.build_button.isEnabled())
        self.panel.on_video_chosen(self._video())
        self.assertTrue(self.panel.build_button.isEnabled())

    def test_choosing_fills_path_and_status(self):
        path = self._video("无光之森来找宝箱.mp4")
        self.panel.on_video_chosen(path)
        self.assertEqual(self.panel.video_edit.text(), path)
        self.assertIn("无光之森来找宝箱.mp4", self.panel.build_status.text())

    def test_non_video_rejected(self):
        p = self.dir / "note.txt"
        p.write_bytes(b"x")
        self.panel.on_video_chosen(str(p))
        self.assertFalse(self.panel.build_button.isEnabled(),
                         "非视频不该启用建库")

    def test_missing_file_rejected(self):
        self.panel.on_video_chosen(str(self.dir / "没有.mp4"))
        self.assertFalse(self.panel.build_button.isEnabled())

    def test_typed_path_enables_button(self):
        """直接粘路径也要能用（有些用户就这么干）。"""
        path = self._video()
        self.panel.video_edit.setText(path)
        self.assertTrue(self.panel.build_button.isEnabled())

    def test_typed_garbage_disables_button(self):
        self.panel.video_edit.setText("D:/没有这个文件.mp4")
        self.assertFalse(self.panel.build_button.isEnabled())

    def test_drop_zone_wired_to_panel(self):
        """★ 拖放区必须真的接到面板的上传逻辑上。

        控件之间没接上是很典型的"看着都对、拖了没反应"。
        """
        path = self._video()
        self.panel.drop_zone.dropped.emit(path)
        self.assertEqual(self.panel.video_edit.text(), path)

    def test_start_build_without_video_does_not_start(self):
        """没视频时点建库 → 只提示，**不起线程**。"""
        self.panel.video_edit.setText("")
        self.panel._pending_video = ""
        self.panel.start_build()
        self.assertIsNone(self.panel._thread)

    def test_start_build_with_missing_file_does_not_start(self):
        self.panel.video_edit.setText(str(self.dir / "没有.mp4"))
        self.panel.start_build()
        self.assertIsNone(self.panel._thread)


class TestPanelList(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        #: 把用户数据目录指到临时目录 —— **绝不碰真实配置**
        from src.core import paths                        # noqa: PLC0415

        original = paths.user_data_dir
        paths.user_data_dir = lambda: self.dir
        self.addCleanup(setattr, paths, "user_data_dir", original)
        self.panel = ExploreGapPanel()
        self.addCleanup(self.panel.deleteLater)

    def test_empty_state(self):
        self.panel.refresh_list()                          #: 不该抛

    def test_lists_entries(self):
        from src.core.explore_gap.catalog import (        # noqa: PLC0415
            library_path_for,
            remember_source,
        )
        from src.core.explore_gap.library import (        # noqa: PLC0415
            ReferenceLibrary,
            save_library,
        )
        import numpy as np                                 # noqa: PLC0415
        from src.core.explore_gap.descriptor import DH, DW  # noqa: PLC0415

        video = self.dir / "路线.mp4"
        video.write_bytes(b"fake")
        lib = library_path_for(video, self.dir)
        lib.parent.mkdir(parents=True, exist_ok=True)
        m = np.random.default_rng(1).random((4, DW * DH)).astype(np.float32)
        save_library(ReferenceLibrary(
            matrix=m, frames=np.arange(4, dtype=np.int64) * 15,
            fps=30.0, src=str(video)), lib)
        remember_source(lib, video)

        self.panel.refresh_list()
        #: 列表里该多出一个 VideoRow
        from src.tools.game.explore_gap.tool import VideoRow  # noqa: PLC0415

        rows = self.panel._list_host.findChildren(VideoRow)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].entry.name, "路线")


if __name__ == "__main__":
    unittest.main(verbosity=2)
