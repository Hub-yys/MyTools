# -*- coding: utf-8 -*-
"""参考库目录管理的单元测试（**不碰真视频**）。

## 为什么这批测试重要

原设计里库是**一个固定文件名**，于是"上传第二个视频"会把第一个**覆盖**。
用户的原话是「我上传一个视频，你能跟着视频做」——
**一个视频 = 一条路线 = 一份库**，所以必须能共存。

而"共存"全靠命名规则，命名规则错了会**静默地互相覆盖**
（或者攒一目录的重复副本）—— 两种都不报错，只是慢慢变得不能用。
所以这里把规则的每条边界都钉住。

## 中文文件名

用户上传的视频大概率是中文名（"无光之森找宝箱.mp4"）。
**必须原样保留** —— 转拼音或哈希的话，用户在列表里认不出哪个是哪个。
"""

from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.core.explore_gap.catalog import (  # noqa: E402
    HASH_LEN,
    LEGACY_DIR_NAMES,
    LIB_DIR_NAME,
    MAX_STEM,
    VideoEntry,
    adopt_legacy_dir,
    forget,
    library_dir,
    library_path_for,
    list_entries,
    remember_source,
    sanitize_stem,
    short_hash,
    source_of,
)
from src.core.explore_gap.descriptor import DH, DW  # noqa: E402
from src.core.explore_gap.library import (  # noqa: E402
    ReferenceLibrary,
    save_library,
)


def fake_lib(count: int = 5) -> ReferenceLibrary:
    rng = np.random.default_rng(3)
    m = rng.random((count, DW * DH)).astype(np.float32)
    m /= np.linalg.norm(m, axis=1, keepdims=True)
    return ReferenceLibrary(matrix=m,
                            frames=np.arange(count, dtype=np.int64) * 15,
                            fps=30.0, src="F:/somewhere/video.mp4")


class TestSanitize(unittest.TestCase):
    def test_chinese_preserved(self):
        """★ 中文原样保留 —— 用户要能一眼认出哪个库是哪条路线。"""
        self.assertEqual(sanitize_stem("无光之森找宝箱"), "无光之森找宝箱")
        self.assertEqual(sanitize_stem("七丘声匣 3.7"), "七丘声匣_3.7")

    def test_illegal_chars_replaced(self):
        """非分隔符的非法字符 → ``_``。

        ⚠ 斜杠 / 反斜杠**不在这里测** —— 它们是**路径分隔符**，
        :func:`sanitize_stem` 会先按它们切分、只取最后一段
        （见 ``test_path_separators_split``）。把它们混在一起测
        会掩盖那个更重要的行为。
        """
        for bad in '<>:"|?*':
            with self.subTest(bad=bad):
                got = sanitize_stem(f"a{bad}b")
                self.assertNotIn(bad, got)
                self.assertIn("a", got)
                self.assertIn("b", got)

    def test_path_separators_split(self):
        """★ 路径分隔符 → **只取最后一段**（最安全的做法）。

        ``../../etc/passwd`` 这种输入，取最后一段就只剩下 ``passwd``
        —— 不残留任何 ``..``，也就没有目录穿越的可能。

        （我第一版实现是先替换非法字符再剥前导点，于是
        ``../etc/passwd`` 变成 ``.._etc_passwd`` → ``_etc_passwd``；
        虽然也安全，但名字里留了个没意义的下划线。）
        """
        self.assertEqual(sanitize_stem("a/b"), "b")
        self.assertEqual(sanitize_stem("a\\b"), "b")
        self.assertEqual(sanitize_stem("../../etc/passwd"), "passwd")
        self.assertEqual(sanitize_stem("D:/videos/攻略.mp4"), "攻略.mp4")

    def test_leading_dots_stripped(self):
        """前导点要去掉 —— 防目录穿越 + Windows 不允许。"""
        self.assertEqual(sanitize_stem(".."), "video")
        self.assertEqual(sanitize_stem("..."), "video")
        self.assertFalse(sanitize_stem(".hidden").startswith("."))

    def test_trailing_dot_space_stripped(self):
        self.assertEqual(sanitize_stem("name. "), "name")

    def test_whitespace_collapsed(self):
        self.assertEqual(sanitize_stem("a   b"), "a_b")

    def test_empty_becomes_placeholder(self):
        for empty in ("", "   ", "...", None):
            with self.subTest(empty=empty):
                self.assertEqual(sanitize_stem(empty), "video")

    def test_long_name_truncated(self):
        got = sanitize_stem("啊" * 200)
        self.assertLessEqual(len(got), MAX_STEM)
        self.assertTrue(got)

    def test_no_control_chars(self):
        self.assertNotIn("\x00", sanitize_stem("a\x00b"))


class TestShortHash(unittest.TestCase):
    def test_stable(self):
        """同一个输入永远同一个哈希（重复上传不攒副本）。"""
        self.assertEqual(short_hash("D:/a/b.mp4"), short_hash("D:/a/b.mp4"))

    def test_length(self):
        self.assertEqual(len(short_hash("x")), HASH_LEN)

    def test_different_for_different_input(self):
        self.assertNotEqual(short_hash("D:/a/b.mp4"), short_hash("E:/a/b.mp4"))

    def test_handles_unicode_and_none(self):
        self.assertTrue(short_hash("中文路径"))
        self.assertTrue(short_hash(""))


class TestLibraryPath(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_in_subdirectory(self):
        p = library_path_for("D:/v/a.mp4", self.dir)
        self.assertEqual(p.parent, library_dir(self.dir))
        self.assertEqual(p.suffix, ".npz")

    def test_name_uses_video_stem(self):
        p = library_path_for("D:/v/无光之森.mp4", self.dir)
        self.assertIn("无光之森", p.name)

    def test_same_video_same_path(self):
        """★ 同一个视频重复上传 → **同一个路径**（不攒副本）。"""
        a = library_path_for("D:/v/攻略.mp4", self.dir)
        b = library_path_for("D:/v/攻略.mp4", self.dir)
        self.assertEqual(a, b)

    def test_different_videos_same_name_no_clash(self):
        """★★ 同名但不同目录的两个视频**不能互相覆盖**。

        这是原设计的 bug：固定文件名时第二个会把第一个删掉。
        光按文件名也会撞，所以名字里带了源路径的短哈希。
        """
        a = library_path_for("D:/one/攻略.mp4", self.dir)
        b = library_path_for("E:/two/攻略.mp4", self.dir)
        self.assertNotEqual(a, b, "同名不同视频撞了 —— 会互相覆盖")

    def test_extension_variants_differ(self):
        a = library_path_for("D:/v/攻略.mp4", self.dir)
        b = library_path_for("D:/v/攻略.mkv", self.dir)
        self.assertNotEqual(a, b)

    def test_weird_names_still_valid_path(self):
        for name in ("a<b>c.mp4", "..\\..\\evil.mp4", "a" * 300 + ".mp4"):
            with self.subTest(name=name[:20]):
                p = library_path_for(f"D:/v/{name}", self.dir)
                #: 生成的路径必须**留在**库目录里（防穿越）
                self.assertEqual(p.parent, library_dir(self.dir))
                self.assertTrue(p.name)


class TestSourceSidecar(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_round_trip(self):
        lib = self.dir / "a.npz"
        lib.write_bytes(b"x")
        remember_source(lib, "D:/v/无光之森.mp4")
        self.assertEqual(source_of(lib), "D:/v/无光之森.mp4")

    def test_missing_sidecar_falls_back_to_npz(self):
        """没有 sidecar → 退回打开库读 ``src``（慢但正确）。"""
        lib = self.dir / "b.npz"
        save_library(fake_lib(3), lib)
        self.assertEqual(source_of(lib), "F:/somewhere/video.mp4")

    def test_broken_library_returns_empty(self):
        """库坏掉 + 没 sidecar → 返回空串（不抛）。"""
        lib = self.dir / "c.npz"
        lib.write_bytes(b"not an npz")
        self.assertEqual(source_of(lib), "")

    def test_empty_sidecar_falls_back(self):
        lib = self.dir / "d.npz"
        lib.write_bytes(b"x")
        lib.with_suffix(".src").write_text("", encoding="utf-8")
        self.assertEqual(source_of(lib), "")


class TestListEntries(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def _add(self, video: str, *, present: bool = True) -> Path:
        """造一个"已建库"的视频条目。"""
        path = library_path_for(video, self.dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        save_library(fake_lib(4), path)
        remember_source(path, video)
        return path

    def test_empty_dir(self):
        self.assertEqual(list_entries(self.dir), [])

    def test_lists_multiple(self):
        """★ 多个视频各自的库都要在（这就是"不覆盖"的验收）。"""
        self._add("D:/v/无光之森.mp4")
        self._add("D:/v/七丘.mp4")
        entries = list_entries(self.dir)
        self.assertEqual(len(entries), 2)
        names = {e.name for e in entries}
        self.assertEqual(names, {"无光之森", "七丘"})

    def test_sorted_by_name(self):
        self._add("D:/v/zeta.mp4")
        self._add("D:/v/alpha.mp4")
        names = [e.name for e in list_entries(self.dir)]
        self.assertEqual(names, sorted(names))

    def test_built_flag(self):
        self._add("D:/v/a.mp4")
        self.assertTrue(list_entries(self.dir)[0].built)

    def test_video_present_false_when_missing(self):
        """源视频不在了要标出来 —— 那意味着**定位会失效**。"""
        self._add("D:/绝对不存在的路径/v.mp4")
        entry = list_entries(self.dir)[0]
        self.assertFalse(entry.video_present)
        self.assertFalse(entry.runnable)
        self.assertIn("源视频不在", entry.status_text())

    def test_runnable_needs_both(self):
        """★ 能跑 = 库在 **且** 源视频在（库只存描述子）。"""
        self._add("D:/绝对不存在的路径/v.mp4")
        self.assertFalse(list_entries(self.dir)[0].runnable)

    def test_ignores_temp_files(self):
        self._add("D:/v/a.mp4")
        (library_dir(self.dir) / "junk.tmp.npz").write_bytes(b"x")
        self.assertEqual(len(list_entries(self.dir)), 1)


class TestVideoEntry(unittest.TestCase):
    def test_name_from_video(self):
        e = VideoEntry(video="D:/v/无光之森.mp4", library="x.npz",
                       built=True, video_present=True)
        self.assertEqual(e.name, "无光之森")

    def test_status_not_built(self):
        e = VideoEntry(video="v.mp4", library="x", built=False,
                       video_present=True)
        self.assertIn("还没建库", e.status_text())

    def test_status_ok(self):
        e = VideoEntry(video="v.mp4", library="x", built=True,
                       video_present=True, frames=100, minutes=1.5)
        text = e.status_text()
        self.assertIn("100", text)
        self.assertIn("1.5", text)


class TestForget(unittest.TestCase):
    """删库 —— ⚠ **绝不能动源视频**（那是用户的东西）。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_removes_library_and_siblings(self):
        video = self.dir / "v.mp4"
        video.write_bytes(b"fake video")
        lib = library_path_for(video, self.dir)
        lib.parent.mkdir(parents=True, exist_ok=True)
        save_library(fake_lib(3), lib)
        remember_source(lib, video)
        lib.with_suffix(".meta").write_text("3 0.5 15", encoding="utf-8")

        removed = forget(lib)
        self.assertGreaterEqual(len(removed), 2)
        self.assertFalse(lib.exists())
        self.assertFalse(lib.with_suffix(".src").exists())

    def test_does_not_touch_source_video(self):
        """★★ 源视频必须留着 —— 用户上传的东西不属于我们删。"""
        video = self.dir / "keep_me.mp4"
        video.write_bytes(b"fake video")
        lib = library_path_for(video, self.dir)
        lib.parent.mkdir(parents=True, exist_ok=True)
        save_library(fake_lib(2), lib)
        forget(lib)
        self.assertTrue(video.is_file(), "源视频被删了！")

    def test_idempotent(self):
        lib = self.dir / "nope.npz"
        self.assertEqual(forget(lib), [])
        self.assertEqual(forget(lib), [])


class TestCoexistence(unittest.TestCase):
    """★★★ 端到端：两个视频的库真的能**同时存在**且各自可读。

    这是本轮修复的核心验收 —— 原设计是一个固定文件名，
    第二个视频会把第一个覆盖掉。
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_two_videos_do_not_overwrite(self):
        v1 = self.dir / "路线A.mp4"
        v2 = self.dir / "路线B.mp4"
        v1.write_bytes(b"a")
        v2.write_bytes(b"b")

        p1 = library_path_for(v1, self.dir)
        p2 = library_path_for(v2, self.dir)
        p1.parent.mkdir(parents=True, exist_ok=True)
        save_library(fake_lib(6), p1)
        remember_source(p1, v1)
        save_library(fake_lib(9), p2)
        remember_source(p2, v2)

        #: ★ 两个库都在，而且**内容各是各的**
        self.assertTrue(p1.is_file())
        self.assertTrue(p2.is_file())
        from src.core.explore_gap.library import load_library

        self.assertEqual(len(load_library(p1)), 6)
        self.assertEqual(len(load_library(p2)), 9)

        entries = list_entries(self.dir)
        self.assertEqual(len(entries), 2)
        self.assertTrue(all(e.runnable for e in entries))

    def test_rebuild_same_video_reuses_slot(self):
        """同一个视频重建 → 覆盖自己那一份，**不新增**条目。"""
        v = self.dir / "路线.mp4"
        v.write_bytes(b"a")
        p = library_path_for(v, self.dir)
        p.parent.mkdir(parents=True, exist_ok=True)
        for count in (3, 7):
            save_library(fake_lib(count), p)
            remember_source(p, v)
        self.assertEqual(len(list_entries(self.dir)), 1)


class TestLegacyDirAdoption(unittest.TestCase):
    """★ 改名后**已有库不能丢**。

    工具从「跟着画面走」改名成「查缺补漏」时，库目录也跟着从
    ``video_follow/`` 变成 ``explore_gap/``。

    用户可能已经建过库（27 分钟视频要等 1~2 分钟）。直接换名字会让
    那些库从列表里"消失"，用户只能重传重扫 —— 这个继承就是为了避免
    白等那一两分钟。
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_constants(self):
        self.assertEqual(LIB_DIR_NAME, "explore_gap")
        self.assertIn("video_follow", LEGACY_DIR_NAMES)

    def test_adopts_old_dir(self):
        old = self.dir / LEGACY_DIR_NAMES[0]
        old.mkdir(parents=True)
        save_library(fake_lib(5), old / "a.npz")

        done = adopt_legacy_dir(self.dir)
        self.assertTrue(done, "该报告做过继承")
        self.assertTrue((library_dir(self.dir) / "a.npz").is_file())
        #: 老目录**留着**（复制不是移动）—— 万一新目录出问题还能兜底
        self.assertTrue((old / "a.npz").is_file(), "老目录该保留")

    def test_adopted_library_readable(self):
        """继承过来的库要**真的能用**（不是空壳）。"""
        from src.core.explore_gap.library import load_library

        old = self.dir / LEGACY_DIR_NAMES[0]
        old.mkdir(parents=True)
        save_library(fake_lib(7), old / "a.npz")
        adopt_legacy_dir(self.dir)
        self.assertEqual(len(load_library(library_dir(self.dir) / "a.npz")), 7)

    def test_no_legacy_dir_is_noop(self):
        self.assertEqual(adopt_legacy_dir(self.dir), [])

    def test_does_not_overwrite_existing_new_dir(self):
        """★ 新目录已经存在 → **不继承**（绝不拿旧的覆盖新的）。

        用户改名后可能已经在新目录里建了新库；这时再把老目录盖上去
        等于把他的新工作删了。
        """
        new = library_dir(self.dir)
        new.mkdir(parents=True)
        save_library(fake_lib(3), new / "new.npz")
        old = self.dir / LEGACY_DIR_NAMES[0]
        old.mkdir(parents=True)
        save_library(fake_lib(9), old / "old.npz")

        self.assertEqual(adopt_legacy_dir(self.dir), [])
        self.assertFalse((new / "old.npz").exists(), "不该把老库盖进来")
        self.assertTrue((new / "new.npz").is_file(), "新库该还在")

    def test_list_entries_adopts_automatically(self):
        """★ 列列表时**自动**继承 —— 用户不该为此多做一步。"""
        old = self.dir / LEGACY_DIR_NAMES[0]
        old.mkdir(parents=True)
        save_library(fake_lib(4), old / "a.npz")
        remember_source(old / "a.npz", "D:/v/旧视频.mp4")

        entries = list_entries(self.dir)
        self.assertEqual(len(entries), 1, "继承过来的库该出现在列表里")

    def test_adopt_tolerates_broken_copy(self):
        """拷贝失败不该抛（不挡启动）。"""
        #: 老目录是个文件而不是目录 → 跳过
        (self.dir / LEGACY_DIR_NAMES[0]).write_bytes(b"x")
        self.assertEqual(adopt_legacy_dir(self.dir), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
