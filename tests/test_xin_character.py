"""「心」的角色支持：注册 / 模板 / 补丁可重放。

    python tests/test_xin_character.py

⚠ **测不了战斗逻辑本身** —— 那要接实时截图（见 ``Xin.py`` 的模块说明）。
这里守的是三件**会静默失败**的事：

1. `char_xin` 没注册 → 角色退化成通用循环（**不报错**，只是打得不好）
2. 识别模板尺寸被 ok-script 缩放 → 匹配率归零（**不报错**，只是一直匹配不上）
3. 上游更新把 vendor 里的改动冲掉 → 同上（**不报错**）
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor" / "okww"

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
