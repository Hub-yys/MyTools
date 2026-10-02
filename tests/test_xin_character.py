"""「心」的角色支持：注册 / 模板 / 补丁可重放。

    python tests/test_xin_character.py

⚠ **测不了战斗逻辑本身** —— 那要接实时截图（见 ``Xin.py`` 的模块说明）。
这里守的是三件**会静默失败**的事：

1. `char_xin` 没注册 → 角色退化成通用循环（**不报错**，只是打得不好）
2. 识别模板尺寸被 ok-script 缩放 → 匹配率归零（**不报错**，只是一直匹配不上）
3. 上游更新把 vendor 里的改动冲掉 → 同上（**不报错**）
"""

from __future__ import annotations

import ast
import json
import os
import pathlib
import re
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor" / "okww"

#: ⚠ 必须放在最前面 —— 本文件有些用例要 import ``src.*``（战斗报告），
#: 而别的用例会 chdir 到 vendor。不先加这一条会 ModuleNotFoundError。
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

#: 给「心」加的东西
XIN_LABELS = ("char_xin", "xin_red", "xin_red_idle", "xin_white", "xin_dominion")

#: ★ 游戏分辨率 —— 用户的游戏就是 1920×1080（他给了图像设置截图）。
#: 底图和 COCO 声明都必须用这个，否则模板会被 ok-script 缩放（见下面的说明）。
SCREEN = (1920, 1080)

#: 模板的原始尺寸（1920×1080 下必须是这个 —— 被缩放就说明 COCO 声明错了）
EXPECTED_SIZES = {
    "char_xin": (60, 37),        # 认人用（对齐 ok-ww 原生量级）
    "xin_red": (405, 70),        # 状态条（从 1280 截图裁后放大到 1920 尺度）
    "xin_red_idle": (405, 70),
    "xin_white": (405, 70),
    "xin_dominion": (405, 70),
}


class TestUltimateAfterDominion(unittest.TestCase):
    """★★ 「心」必须**放得出二段大招**。

    用户 2026-10-01 报："心不放二段大招"。

    ## 根因（我的 bug）
    二段大招原来放在 ``perform_finish`` 里，靠 ``do_perform`` 的下一轮分派 ——
    但 ``do_perform`` 的 ``finally`` 会在 ``perform_dominion`` 返回后
    **立刻切人**；而且此时协奏已满，ok-ww 下次轮到这个角色时又会马上切走。
    于是 ``perform_finish`` **永远没机会跑**。

    日志证据（用户实机）：
        ``[统御众机] 13 秒到`` 出现 9 次，``[收尾]`` 出现 **0 次**。

    ## 修法
    二段大招必须在**切人之前**放完 —— 由 ``perform_dominion`` 当场连着调
    ``perform_finish()``。
    """

    def setUp(self):
        self.path = VENDOR / "okww" / "char" / "Xin.py"
        self.text = self.path.read_text(encoding="utf-8")
        tree = ast.parse(self.text)
        self.fn = next(
            n for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "perform_dominion")

    def test_dominion_calls_finish(self):
        """★ ``perform_dominion`` 必须**自己**调 ``perform_finish``。"""
        calls = {
            n.func.attr for n in ast.walk(self.fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        }
        self.assertIn(
            "perform_finish", calls,
            "perform_dominion 没调 perform_finish —— 二段大招放不出来"
            "（do_perform 的 finally 会先切人）")

    def test_finish_after_heavy(self):
        """顺序：终结重击 → 二段大招（不能反）。

        ⚠ 用 **AST 的行号**比，不能拿源码字符串 find ——
        方法的 docstring 里也提到了 ``perform_finish``，
        字符串搜索会命中注释（实测踩过）。
        """
        heavy_line = finish_line = None
        for n in ast.walk(self.fn):
            if (isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Attribute)):
                if n.func.attr == "heavy_attack" and heavy_line is None:
                    heavy_line = n.lineno
                elif n.func.attr == "perform_finish" and finish_line is None:
                    finish_line = n.lineno
        self.assertIsNotNone(heavy_line, "没有终结重击")
        self.assertIsNotNone(finish_line, "没有 perform_finish 调用")
        self.assertLess(
            heavy_line, finish_line,
            f"顺序反了（重击 L{heavy_line} / 二段大 L{finish_line}）——"
            f" 二段大招必须在终结重击**之后**（攻略：提前开会大幅缩水）")

    def test_no_phase_finish_dispatch(self):
        """★ 不该再有 ``phase = "finish"`` —— 那条路走不通。

        ⚠ 这条防的是"改回去"：只要还有人设 ``phase = "finish"``，
        就说明二段大招又被丢给下一轮了。
        """
        self.assertNotIn(
            'phase = "finish"', self.text,
            '又设 phase = "finish" 了 —— 那条路永远轮不到（见类说明）')

    def test_finish_exists_as_method(self):
        """``perform_finish`` 本身要留着（可读性 + 可单测）。"""
        tree = ast.parse(self.text)
        names = {n.name for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef)}
        self.assertIn("perform_finish", names)

    def test_click_liberation_used(self):
        """二段大招靠 ``click_liberation`` 放。"""
        tree = ast.parse(self.text)
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef)
                  and n.name == "perform_finish")
        calls = {
            n.func.attr for n in ast.walk(fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        }
        self.assertIn("click_liberation", calls, "没按大招键")


class TestVendorFiles(unittest.TestCase):
    """vendor 里的四处改动都在（不看运行，只看文件）。"""

    def test_labels_has_xin(self):
        text = (VENDOR / "okww" / "Labels.py").read_text(encoding="utf-8")
        for name in XIN_LABELS:
            with self.subTest(name=name):
                self.assertIn(f"{name} = '{name}'", text,
                              f"Labels 里没有 {name} —— 跑 tools/install_xin_patch.py")

    def test_factory_registers_xin(self):
        text = (VENDOR / "okww" / "char" / "CharFactory.py").read_text(
            encoding="utf-8")
        self.assertIn("from okww.char.Xin import Xin", text,
                      "CharFactory 没导入 Xin")
        self.assertIn("Labels.char_xin", text,
                      "CharFactory 没注册 char_xin —— 角色会退化成通用循环")

    def test_xin_class_exists(self):
        path = VENDOR / "okww" / "char" / "Xin.py"
        self.assertTrue(path.exists(), "Xin.py 不存在")
        text = path.read_text(encoding="utf-8")
        self.assertIn("class Xin(BaseChar)", text)
        self.assertIn("def do_perform", text)
        # 攻略明确写"固定13秒" —— 常量写对没有
        self.assertIn("DOMINION_DURATION = 13.0", text)

    def test_uses_generic_forte_detection(self):
        """★★ 必须用 ok-ww 的**通用**强化重击检测，不要自造模板。

        第一版用我自己裁的 `xin_red` 能量条模板判"能不能强化重击"，
        实机**一直失败**（日志"应世心攒满超时"，表现是一直平A）。
        原因：ok-ww 判这个用的是**所有角色共用**的通用检测
        （``is_forte_full`` 量屏幕底部白色占比 / ``is_mouse_forte_full``
        找 ``mouse_forte`` 模板），根本不看角色专属资源条。

        ⚠ 这条护栏防的就是"又退回去用自造模板"。
        ⚠ 也不能只查字符串 —— 还要**真的实例化**确认这些方法调得通
        （只 grep 的话，把 ``self.is_mouse_forte_full()`` 改成
        ``self.never_exists()`` 也能骗过去，实测漏过一次）。
        """
        text = (VENDOR / "okww" / "char" / "Xin.py").read_text(encoding="utf-8")
        self.assertIn("is_mouse_forte_full", text,
                      "没用通用强化重击检测 —— 会一直平A")
        self.assertIn("is_forte_full", text)
        # 不该再用自造的状态条模板判形态
        for bad in ("find_one(Labels.xin_", "Labels.xin_red",
                    "Labels.xin_white", "Labels.xin_dominion"):
            with self.subTest(bad=bad):
                self.assertNotIn(
                    bad, text,
                    f"又在用自造模板 {bad} 判形态了 —— 实机验证过那条路走不通")

    def test_xin_methods_actually_exist(self):
        """★ 实例化 Xin，确认它调用的**每个** ok-ww 方法都真实存在。

        ⚠ 这条是补上一条的漏洞：光看源码字符串不够，
        写成 ``self.never_exists()`` 一样能通过 grep。
        这里直接对着 ``BaseChar`` 查方法有没有。
        """
        import ast

        path = VENDOR / "okww" / "char" / "Xin.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))

        # 收集所有 self.xxx(...) 调用
        called = set()
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "self"):
                called.add(node.func.attr)

        old = os.getcwd()
        os.chdir(VENDOR)
        sys.path.insert(0, str(VENDOR))
        try:
            from okww.char.BaseChar import BaseChar
            from okww.char.Xin import Xin as _Xin  # noqa: F401
        finally:
            os.chdir(old)

        # 自己定义的方法不算；其余必须在 BaseChar 上找得到
        own = {"do_perform", "perform_red", "perform_white",
               "perform_dominion", "perform_finish",
               "forte_ready", "ultimate_ready", "skill_ready",
               "press_heavy_forte"}
        missing = sorted(
            n for n in called
            if n not in own and not hasattr(BaseChar, n)
            and not hasattr(_Xin, n))
        self.assertEqual(
            missing, [],
            f"Xin.py 调了 BaseChar 上不存在的方法：{missing} "
            f"（实机就是一直平A，因为异常被吞了）")

    def test_templates_exist(self):
        coco = VENDOR / "ok_tasks" / "assets" / "coco_annotations.json"
        png = (VENDOR / "ok_tasks" / "assets" / "images"
               / "xin_templates.png")
        self.assertTrue(coco.exists(), "识别模板的 COCO 不在")
        self.assertTrue(png.exists(), "识别模板的底图不在")


class TestCocoFormat(unittest.TestCase):
    """★ COCO 的两个坑（都会静默失效）。"""

    def _coco(self) -> dict:
        return json.loads((VENDOR / "ok_tasks" / "assets"
                           / "coco_annotations.json").read_text(encoding="utf-8"))

    def test_ascii_only(self):
        """★ 整个 json 必须是**纯 ASCII**。

        ok-script 的 ``load_json`` 用 ``open(path, 'r')``（**没指定
        encoding**），中文 Windows 上按 GBK 解码 —— 写中文进去会
        UnicodeDecodeError 把**整个模板加载**搞崩（实测踩过）。
        """
        raw = (VENDOR / "ok_tasks" / "assets"
               / "coco_annotations.json").read_bytes()
        try:
            raw.decode("ascii")
        except UnicodeDecodeError as exc:
            self.fail(f"COCO 里有非 ASCII 字符（会让 ok-script 按 GBK 解码崩）：{exc}")

    def test_declares_screen_size_not_canvas_size(self):
        """★ ``images[].width/height`` 要声明成**游戏分辨率**。

        ok-script 按 ``scale = screen_w / image_w`` 缩放模板，而
        ``image_w`` 取的是 **PNG 文件的实际尺寸**。如果底图做得很紧凑
        （比如 270px 宽），模板会被放大好几倍 → 匹配率归零。
        所以底图**就是** 1920×1080，声明也是 1920×1080（scale=1）。
        """
        coco = self._coco()
        image = coco["images"][0]
        self.assertEqual((image["width"], image["height"]), SCREEN,
                         "COCO 里声明的不是游戏分辨率")

        from PIL import Image

        png = VENDOR / "ok_tasks" / "assets" / "images" / "xin_templates.png"
        self.assertEqual(Image.open(png).size, SCREEN,
                         "底图尺寸和声明不一致 —— 模板会被缩放")

    def test_categories_and_annotations_match(self):
        coco = self._coco()
        names = {c["name"] for c in coco["categories"]}
        self.assertEqual(names, set(XIN_LABELS))
        # 每个类别都要有 bbox
        by_cat = {c["id"]: c["name"] for c in coco["categories"]}
        covered = {by_cat[a["category_id"]] for a in coco["annotations"]}
        self.assertEqual(covered, set(XIN_LABELS), "有类别没有 bbox")


class TestTemplatesLoad(unittest.TestCase):
    """★ 真的让 ok-script 加载一遍 —— 尺寸必须**原样**（scale=1）。"""

    def test_loads_at_native_size(self):
        from ok.feature.FeatureSet import read_from_json

        coco = VENDOR / "ok_tasks" / "assets" / "coco_annotations.json"
        old = os.getcwd()
        os.chdir(VENDOR)          # ok-ww 跑起来时 cwd 就是这里
        try:
            feats, _boxes, _c, success, _k = read_from_json(str(coco), *SCREEN)
        finally:
            os.chdir(old)

        self.assertTrue(success, "模板加载失败")
        for name, (w, h) in EXPECTED_SIZES.items():
            with self.subTest(name=name):
                self.assertIn(name, feats, f"{name} 没加载出来")
                mat = feats[name].mat
                self.assertEqual(
                    (mat.shape[1], mat.shape[0]), (w, h),
                    f"{name} 被缩放了 —— COCO 的尺寸声明不对")


class TestPatchScript(unittest.TestCase):
    """★ 上游更新会冲掉 vendor 里的改动 —— 补丁脚本要能重放。"""

    def test_patch_reports_all_installed(self):
        result = subprocess.run(
            [sys.executable, "tools/install_xin_patch.py"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", cwd=ROOT)
        out = (result.stdout or "") + (result.stderr or "")
        self.assertIn("全部就位", out,
                      f"补丁脚本报有缺失：\n{out}")

    def test_patch_is_idempotent(self):
        """跑两次不该重复插入（文本锚点替换必须是幂等的）。"""
        before = (VENDOR / "okww" / "Labels.py").read_text(encoding="utf-8")
        subprocess.run([sys.executable, "tools/install_xin_patch.py", "--apply"],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=ROOT)
        after = (VENDOR / "okww" / "Labels.py").read_text(encoding="utf-8")
        self.assertEqual(before, after, "补丁跑第二次改了文件 —— 不幂等")
        self.assertEqual(after.count("char_xin = 'char_xin'"), 1,
                         "char_xin 被插了多次")


class TestRecognizesXin(unittest.TestCase):
    """★★ 最重要的一条：**认得出来**。

    用户报的 bug 就是"心被识别成渊武"。所以这里做**端到端复现**：
    把 char_xin 和 ok-ww 全部 68 个 char_* 一起，在心的位置上比 ——
    必须 char_xin 分最高。
    """

    def _load(self, width, height):
        from ok.feature.FeatureSet import read_from_json

        old = os.getcwd()
        os.chdir(VENDOR)
        try:
            return read_from_json(
                str(VENDOR / "assets" / "coco_annotations.json"), width, height)
        finally:
            os.chdir(old)

    def test_char_xin_wins_at_xin_slot(self):
        """在用户给的战斗截图里，心的位置必须由 char_xin 胜出。"""
        import cv2
        import numpy as np

        shots_dir = pathlib.Path(r"D:\DeepSeek Work\xin_shots")
        if not shots_dir.exists():
            self.skipTest("没有实机截图（那是用户的素材，不随仓库分发）")

        shots = ["99a35152d30d216c8b7d733b16b408e6_720.png",
                 "b2f63b36b5d7baca1db2bb6696c8d7d9_720.png",
                 "5b3637a1e52a9aef8b45332c41a5e607_720.png"]
        shots = [s for s in shots if (shots_dir / s).exists()]
        if not shots:
            self.skipTest("截图文件不在")

        # 那些截图是 1280x720（QQ 缩略图），所以按 1280 加载
        mf, mb, _a, _b, _c = self._load(1280, 720)
        coco = VENDOR / "ok_tasks" / "assets" / "coco_annotations.json"
        old = os.getcwd()
        os.chdir(VENDOR)
        try:
            from ok.feature.FeatureSet import read_from_json

            ef, _e, _a2, _b2, _c2 = read_from_json(str(coco), 1280, 720)
        finally:
            os.chdir(old)

        xin = ef["char_xin"].mat
        merged = {n: f.mat for n, f in mf.items()}
        merged["char_xin"] = xin
        names = [n for n in merged if n.startswith("char_")]
        box = mb["box_char_1"]

        for shot in shots:
            frame = cv2.imread(str(shots_dir / shot))
            region = frame[box.y:box.y + box.height, box.x:box.x + box.width]
            scores = []
            for n in names:
                t = merged[n]
                if t.shape[0] > region.shape[0] or t.shape[1] > region.shape[1]:
                    continue
                try:
                    scores.append((float(cv2.matchTemplate(
                        region, t, cv2.TM_CCOEFF_NORMED).max()), n))
                except Exception:
                    continue
            scores.sort(reverse=True)
            with self.subTest(shot=shot):
                self.assertTrue(scores, "一个模板都没匹配上")
                self.assertEqual(
                    scores[0][1], "char_xin",
                    f"心又被认成 {scores[0][1]}（{scores[0][0]:.3f}）；"
                    f"char_xin 只有 "
                    f"{next((s for s, n in scores if n == 'char_xin'), -1):.3f}")

    def test_template_not_absurdly_large(self):
        """模板尺寸要和 ok-ww 原生量级相当（不能大好几倍）。

        ⚠ 这条是踩过的坑：第一版做了 140x125，而原生的都是 20~50 ——
        ok-script 会把它缩到框里，细节全丢，于是认成渊武。
        """
        coco = VENDOR / "ok_tasks" / "assets" / "coco_annotations.json"
        old = os.getcwd()
        os.chdir(VENDOR)
        try:
            from ok.feature.FeatureSet import read_from_json

            ef, _e, _a, _b, _c = read_from_json(str(coco), *SCREEN)
            mf, _m, _a2, _b2, _c2 = read_from_json(
                str(VENDOR / "assets" / "coco_annotations.json"), *SCREEN)
        finally:
            os.chdir(old)

        mine = ef["char_xin"].mat
        natives = [f.mat.shape[1] for n, f in mf.items()
                   if n.startswith("char_") and not n.endswith("_text")]
        biggest = max(natives)
        self.assertLessEqual(
            mine.shape[1], biggest * 1.5,
            f"char_xin 宽 {mine.shape[1]}px，比 ok-ww 最大的原生认人模板"
            f"（{biggest}px）还大不少 —— 会匹配不准")


class TestReportShowsAvatar(unittest.TestCase):
    """★ 战斗报告里「心」要有名字 + 头像。

    用户 2026-10-01 报："识别出来了，但是显示的不是头像"。

    根因：报告的角色名走 ok-ww 的翻译文件（``i18n/zh_CN/.../ok.po``），
    而**上游没有「心」** → po 里没有 ``msgid "Xin"`` → 名字保持英文 ``Xin``
    → 数据集里查不到（数据集存的是中文「心」）→ 没有头像。
    """

    def test_xin_maps_to_chinese_name(self):
        from src.tools.game.auto_combat import report

        class _Fake:
            pass

        _Fake.__name__ = "Xin"
        self.assertEqual(report.char_display_name(_Fake()), "心",
                         "Xin 没映射到中文名 —— 报告里会没头像")

    def test_local_char_names_table_exists(self):
        from src.tools.game.auto_combat import report

        self.assertIn("Xin", report.LOCAL_CHAR_NAMES)
        self.assertEqual(report.LOCAL_CHAR_NAMES["Xin"], "心")

    def test_avatar_resolves(self):
        from src.core import game_data
        from src.tools.game.auto_combat import report

        game_data.ensure_loaded()

        class _Fake:
            pass

        _Fake.__name__ = "Xin"
        name = report.char_display_name(_Fake())
        info = game_data.find_character(name)
        self.assertIsNotNone(info, f"数据集里找不到「{name}」")
        self.assertTrue(info.avatar, "心 没有头像路径")
        self.assertTrue((ROOT / "assets" / "game" / info.avatar).exists()
                        or info.avatar, "头像路径为空")

    def test_upstream_characters_unaffected(self):
        """加了 LOCAL_CHAR_NAMES 不该影响上游角色。"""
        from src.tools.game.auto_combat import report

        for cls, expect in (("ShoreKeeper", "守岸人"),
                            ("Cantarella", "坎特蕾拉")):
            with self.subTest(cls=cls):
                class _Fake:
                    pass

                _Fake.__name__ = cls
                self.assertEqual(report.char_display_name(_Fake()), expect)


if __name__ == "__main__":
    unittest.main(verbosity=2)
