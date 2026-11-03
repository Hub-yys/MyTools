# -*- coding: utf-8 -*-
"""打包完整性 —— ``ok_tasks`` 扩展资源必须进包。

## 为什么要有这个文件（2026-10-09 实机翻车）

用户报：**「清宵/达妮娅/莫宁」这队不能自动战斗**。

日志里的真相::

    File ".../vendor/okww/okww/char/CharFactory.py", line 203, in get_char_by_pos
        char = task.find_best_match_in_box(box, char_names, threshold=0.6)
    ValueError: FeatureSet: Labels.XXX not found in featureDict

## 根因：打包漏了 ``vendor/okww/ok_tasks/``

``ok_tasks/assets/coco_annotations.json`` 是 ok-ww 的**官方扩展点**，
``FeatureSet.read_from_json`` 按**相对路径**去 merge 它。
我们自造的扩展特征就放那儿。

``mytools.spec`` 只收了 ``assets/`` 和 ``i18n/`` —— **漏了 ok_tasks**。
于是打包版里那些特征不在特征表。

## ⚠ 为什么"缺一个特征"会让**所有队伍**都打不了

``get_char_by_pos`` 是拿 ``char_names``（**整张角色表**）一次性
``find_best_match_in_box`` 的；``find_one_feature`` 遇到任何一个名字不在
``featureDict`` 里就 ``raise``。所以缺一个 → **任何队伍**都认不出人，
跟队伍里站的是谁完全无关（用户自然以为是"这几个角色有问题"）。

实测那次日志里 **162 次** ``not found`` + **156 次**
``CombatCheck:do_check_in_combat`` 连环报错。

## ⚠ 2026-10-25：「心」改用 ok-ww 官方实现

``ok_tasks/assets`` 里原来自造的 5 个 ``xin_*`` / ``char_xin`` 特征已删，
现在只剩 ``echo_stack_icon``（声骸堆叠图标）。**但 ``ok_tasks`` 目录本身
仍然必须打包** —— 这个文件钉的就是这条。

## 这个文件钉什么

spec 和 check_build 里都必须**点名** ok_tasks —— 光靠"datas 里加了一行"
不够，``check_build.py`` 才是构建后真正会拦下来的那道闸。
"""

from __future__ import annotations

import pathlib
import re
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SPEC = ROOT / "packaging" / "mytools.spec"
CHECK = ROOT / "packaging" / "check_build.py"
OK_TASKS = ROOT / "vendor" / "okww" / "ok_tasks"


def _list_literal(path: pathlib.Path, name: str) -> list[str]:
    """取出 ``name = [...]`` 这个列表里的**字符串字面量**（忽略注释）。

    ## ⚠ 为什么要解析而不是 ``assertIn`` 全文

    我第一版直接 ``assertIn("ok_tasks/assets/coco_annotations.json", 全文)``。
    护栏验证时发现：把那一行**从 REQUIRED_DATA 里删掉**，测试**照样通过** ——
    因为它在我写的**注释**里也出现过（"FeatureSet 按相对路径找
    ok_tasks/assets/coco_annotations.json 并合并"）。

    → 只认真正的列表元素，注释一律剥掉。
    """
    text = path.read_text(encoding="utf-8")
    start = text.index(f"{name} = [")
    end = text.index("]", start)
    body = text[start:end]
    out = []
    for line in body.splitlines():
        code = line.split("#", 1)[0]           #: 剥掉行尾注释
        out.extend(re.findall(r'"([^"]+)"', code))
    return out


class TestOkTasksIsPackaged(unittest.TestCase):
    """★ spec 要把 ok_tasks 当数据收进去。"""

    def test_source_exists(self):
        """先确认源文件在（不在的话下面几条会"假通过"）。"""
        coco = OK_TASKS / "assets" / "coco_annotations.json"
        self.assertTrue(coco.is_file(), f"源文件不在：{coco}")
        #: ⚠ 2026-10-25：「心」改用官方实现后，``xin_templates.png`` 已删，
        #: ok_tasks/assets 只剩 ``echo_stack.png``（声骸堆叠图标）。
        png = OK_TASKS / "assets" / "images" / "echo_stack.png"
        self.assertTrue(png.is_file(), f"源文件不在：{png}")

    def test_spec_collects_ok_tasks(self):
        """★★ spec 的 datas 里必须有 ok_tasks。

        ⚠ 匹配**元组形式**（``(str(OKWW / "ok_tasks"), "vendor/okww/ok_tasks")``），
        不是光查 "ok_tasks" 这个词 —— 那个词在我的注释里也有，
        删掉真代码测试也照样过（护栏验证抓到的，见 :func:`_list_literal`）。
        """
        spec = SPEC.read_text(encoding="utf-8")
        self.assertRegex(
            spec, r'\(str\(OKWW\s*/\s*"ok_tasks"\),\s*"vendor/okww/ok_tasks"\)',
            "mytools.spec 里没有把 ok_tasks 收进 datas —— "
            "打包版会认不出任何角色")

    def test_check_build_requires_ok_tasks(self):
        """★★★ check_build 必须点名 ok_tasks 的源文件（构建后拦一道）。

        ⚠ 只查目录不够 —— 少了具体的 json/png 一样是"目录在、模板缺"。

        ⚠ 2026-10-25：「心」改用官方实现后，点名的是
        ``echo_stack.png``（不再有 ``xin_templates.png``）。

        ⚠ 用 :func:`_list_literal` 解析，不 ``assertIn`` 全文 ——
        否则注释里的同名文字会让这条测试**假通过**。
        """
        required = _list_literal(CHECK, "REQUIRED_DATA")
        for want in ("vendor/okww/ok_tasks/assets/coco_annotations.json",
                     "vendor/okww/ok_tasks/assets/images/echo_stack.png"):
            with self.subTest(want=want):
                self.assertIn(want, required,
                              f"check_build 的 REQUIRED_DATA 里没有 {want}"
                              f"（现有 {len(required)} 项）")

    def test_coco_actually_contains_echo_stack_icon(self):
        """★★ 源 coco 里真的定义了 ``echo_stack_icon``（否则是白收）。

        ⚠ 2026-10-25：「心」改用 ok-ww 官方实现后，``char_xin`` 已从这里删掉，
        ``ok_tasks/assets`` 只剩 ``echo_stack_icon``（声骸堆叠图标，在用的）。
        这条测的是「ok_tasks 真的被收集进来了」，用还在的那个当代表即可。
        """
        import json

        coco = OK_TASKS / "assets" / "coco_annotations.json"
        data = json.loads(coco.read_text(encoding="utf-8"))
        names = {c.get("name") for c in (data.get("categories") or [])
                 if isinstance(c, dict)}
        self.assertIn(
            "echo_stack_icon", names,
            f"ok_tasks 的 coco 里没有 echo_stack_icon（有：{sorted(names)}）")

    def test_ok_tasks_features_are_used(self):
        """★★★ 反向确认：``ok_tasks`` 里的特征，CharFactory 或别处**真的要用**。

        这条是"为什么缺了它全盘皆输"的护栏：特征表是全表匹配的，
        只要 ``char_names`` 里有，每次认人都会去查。

        ⚠ 2026-10-25 起 ``ok_tasks`` 只剩下 ``echo_stack_icon``
        （「心」已改用官方 ``char_hsin``）。它在 ``echo_enhance`` 里用，
        不在 ``CharFactory`` —— 所以这里查的是"整个 src 有没有提它"。
        """
        vendored = ROOT / "vendor" / "okww"
        if not vendored.is_dir():
            self.skipTest("vendor 不在（纯数据仓库）")
        #: 用的人可能在 src/ 或 vendor/okww/okww/ 里
        hits = []
        for base in (ROOT / "src", vendored / "okww"):
            if not base.is_dir():
                continue
            for p in base.rglob("*.py"):
                try:
                    if "echo_stack_icon" in p.read_text(encoding="utf-8"):
                        hits.append(str(p.relative_to(ROOT)))
                except OSError:
                    continue
        self.assertTrue(
            hits,
            "没有任何代码在用 echo_stack_icon —— "
            "那 ok_tasks 这个扩展目录就是白收的，应该删掉")


class TestPackagedAppSymptomsCovered(unittest.TestCase):
    """★ 把"用户实际看到的现象"和代码对上，防止又被误判成"角色不支持"。"""

    def test_recognition_is_table_wide_not_per_character(self):
        """★★ 识别是**整表**匹配 —— 一个模板缺失 → 所有队伍都认不出。

        ⚠ 这条不是为了查实现细节，而是钉住**归因方向**：
        用户报的是"这三个角色不行"，真因却是"任何角色都不行"。
        下次再遇到类似症状，先看模板齐不齐，别去改角色逻辑。
        """
        vendored = ROOT / "vendor" / "okww"
        if not vendored.is_dir():
            self.skipTest("vendor 不在")
        src = (vendored / "okww" / "char" / "CharFactory.py").read_text(
            encoding="utf-8")
        self.assertIn("find_best_match_in_box(box, char_names", src,
                      "get_char_by_pos 的匹配方式变了 —— "
                      "「一个模板缺失就全盘失效」这个结论可能不再成立，"
                      "请重新评估本文件的说明")

    def test_team_characters_are_registered(self):
        """★ 清宵/达妮娅/莫宁 本身在 ok-ww 里是**注册好的**（不是不支持）。"""
        vendored = ROOT / "vendor" / "okww"
        if not vendored.is_dir():
            self.skipTest("vendor 不在")
        src = (vendored / "okww" / "char" / "CharFactory.py").read_text(
            encoding="utf-8")
        for label in ("char_qingxiao", "char_denia", "char_moning"):
            with self.subTest(label=label):
                self.assertIn(label, src,
                              f"{label} 没在 CharFactory 注册")


if __name__ == "__main__":
    unittest.main()
