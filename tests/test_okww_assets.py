# -*- coding: utf-8 -*-
"""★ 两个回归测试（2026-10-24）：

1. **ok-ww 素材要和代码同步** —— 升级代码后 `CharFactory` 引用了新角色
   （`Hsin`/`Suoming`），素材里没有对应模板就会在运行时抛
   ``ValueError: FeatureSet: Labels.char_hsin not found``，
   把整个 4C 任务炸掉（表现："进去就重新挑战"）。
2. **点启动就立刻最小化** —— 原来等 `task_started` 信号（任务真正起来
   才发），引擎 boot 期间窗口不动，用户以为没反应。

## 为什么这两条都要用"数据自洽"的测法

第 1 条不能靠"跑一次游戏"验证（CI 里没有游戏），只能静态比对
**代码引用的 feature 名** vs **素材里声明的 category**。
这正是当初漏掉的那一层：代码和素材各自都对，**合起来对不上**。
"""

from __future__ import annotations

import ast
import json
import pathlib
import re
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

VENDOR = ROOT / "vendor" / "okww"
ANN = VENDOR / "assets" / "coco_annotations.json"
OKT_ANN = VENDOR / "ok_tasks" / "assets" / "coco_annotations.json"
FACTORY = VENDOR / "okww" / "char" / "CharFactory.py"
TOOL = ROOT / "src" / "tools" / "game" / "auto_combat" / "tool.py"
MW = ROOT / "src" / "gui" / "main_window.py"


def _feature_names() -> set[str]:
    """素材里声明了哪些 feature（assets + ok_tasks 两处）。"""
    names: set[str] = set()
    for path in (ANN, OKT_ANN):
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for cat in data.get("categories") or []:
            if isinstance(cat, dict) and cat.get("name"):
                names.add(cat["name"])
    return names


class TestAssetsMatchCode(unittest.TestCase):
    """★★ 素材必须覆盖代码引用的所有 feature（升级同步的核心）。"""

    def test_char_factory_labels_all_have_templates(self):
        """★★ ``CharFactory`` 里每个 ``Labels.char_xxx`` 都要有模板。

        ## 这条拦的是什么（真实事故）

        2026-10-24 把 ok-ww 代码升到上游最新，`CharFactory` 里多了
        `Hsin` / `Suoming` 两个角色，但素材还是 9/25 的旧版 ——
        缺 `char_hsin` / `char_suoming`。

        运行时 `load_chars()` →
        ``ValueError: FeatureSet: Labels.char_hsin not found in featureDict``
        → **整个 4C 任务崩掉**。用户看到的是"进去就重新挑战"，
        而日志里那行 ValueError 埋在几百行 INFO 中间，很难发现。

        ⚠ 这条必须**同时查 assets 和 ok_tasks** —— 有些扩展特征
        （例如 ``echo_stack_icon``）在 ``ok_tasks/assets/`` 里。
        """
        have = _feature_names()
        src = FACTORY.read_text(encoding="utf-8")
        used = sorted(set(re.findall(r"Labels\.(char_\w+)", src)))
        self.assertGreater(len(used), 10, "没扫到 char_* label，正则可能失效")

        missing = [n for n in used if n not in have]
        self.assertEqual(
            missing, [],
            f"CharFactory 引用了但素材里没有的模板：{missing}\n"
            f"（升级 ok-ww 后必须同步 assets/images 和 coco_annotations.json，"
            f"否则运行时会 ValueError: not found in featureDict）")

    def test_annotations_point_to_existing_images(self):
        """★ 每条 annotation 的 ``image_id`` 都要能对上 images 表。"""
        data = json.loads(ANN.read_text(encoding="utf-8"))
        img_ids = {i.get("id") for i in data.get("images") or []
                   if isinstance(i, dict)}
        bad = [a.get("category_id") for a in data.get("annotations") or []
               if isinstance(a, dict) and a.get("image_id") not in img_ids]
        self.assertEqual(bad, [],
                         f"{len(bad)} 条 annotation 指向不存在的 image_id —— "
                         f"合并上游数据时 id 对错了")

    def test_bbox_within_image_bounds(self):
        """★★ bbox 不能超出所属图片尺寸。

        ⚠ 这条是**上次合并出错时抓出来的**：直接搬上游 annotation
        但 image_id 含义不同，bbox 落到了尺寸差一倍的图上
        （2048 宽的图配了 x=3552 的框）→ 模板加载出来是空白。
        """
        data = json.loads(ANN.read_text(encoding="utf-8"))
        imgs = {i["id"]: i for i in data.get("images") or []
                if isinstance(i, dict) and i.get("id")}
        cats = {c["id"]: c.get("name") for c in data.get("categories") or []
                if isinstance(c, dict)}
        bad = []
        for a in data.get("annotations") or []:
            if not isinstance(a, dict):
                continue
            img = imgs.get(a.get("image_id"))
            bb = a.get("bbox") or []
            if not img or len(bb) < 4:
                continue
            w, h = img.get("width"), img.get("height")
            if not w or not h:
                continue
            x, y, bw, bh = (float(v) for v in bb[:4])
            if x + bw > w + 1 or y + bh > h + 1:
                bad.append(cats.get(a.get("category_id")))
        self.assertEqual(bad, [],
                         f"bbox 超出图片范围的 feature：{bad[:10]}")

    def test_all_template_images_present(self):
        """★ images 表里声明的每张图都要真的在磁盘上。"""
        data = json.loads(ANN.read_text(encoding="utf-8"))
        root = VENDOR / "assets"
        missing = [i.get("file_name") for i in data.get("images") or []
                   if isinstance(i, dict) and i.get("file_name")
                   and not (root / i["file_name"]).exists()]
        self.assertEqual(sorted(set(missing)), [],
                         f"缺图片文件：{sorted(set(missing))}")


class TestNoAutoMinimizeOnStart(unittest.TestCase):
    """★★ 点「启动」**不许**自动最小化窗口（2026-10-25 用户要求撤掉）。

    ## 用户原话

    > 还是不行，我不知道你在干什么，是不是我让你加的启动后要最下化的问题？
    > 你先把这个去掉

    ## 为什么当初会加（以及为什么是我理解错了）

    用户 2026-10-24 说的是：**「不再最小化到托盘栏，而是直接最小化」** ——
    那是让**关闭/托盘**的行为从「藏到托盘」改成「缩到任务栏」。

    我却把它扩大成「点启动立刻最小化 + 抢游戏前台」，还另起了一个
    ``_go_background_now()`` 绕开信号时序。这条链子后来很可能干扰了
    ok-ww 自己的窗口/抓屏（WGC 对窗口状态敏感），所以必须删掉。

    ⚠ 这两个方法**一个都不该再出现** —— 别再"加回来优化体验"。
    """

    def _method(self, name: str, cls: str = "AutoCombatWidget"):
        tree = ast.parse(TOOL.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == cls:
                for sub in node.body:
                    if isinstance(sub, ast.FunctionDef) and sub.name == name:
                        return sub
        return None

    def test_on_start_does_not_minimize(self):
        """★ ``_on_start`` 不许调最小化。"""
        fn = self._method("_on_start")
        self.assertIsNotNone(fn, "找不到 _on_start")
        calls = {
            n.func.attr
            for n in ast.walk(fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        }
        self.assertNotIn(
            "_go_background_now", calls,
            "_on_start 又在启动时最小化了 —— 用户明确要求去掉"
            "（「是不是我让你加的启动后要最小化的问题？你先把这个去掉」）")

    def test_go_background_helper_gone(self):
        """★ ``_go_background_now`` 必须已删除。"""
        self.assertIsNone(
            self._method("_go_background_now"),
            "_go_background_now 还在 —— 它整条都是自造的，应该删掉")

    def test_main_window_methods_gone(self):
        """★★ ``MainWindow`` 里那两个方法（最小化+抢前台）也必须删。"""
        tree = ast.parse(MW.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.ClassDef)
                    and node.name == "MainWindow"):
                continue
            names = {m.name for m in node.body
                     if isinstance(m, ast.FunctionDef)}
            for banned in ("go_background_to_game", "_focus_game"):
                self.assertNotIn(
                    banned, names,
                    f"MainWindow.{banned} 还在 —— 启动后自动最小化/抢前台"
                    f"是用户要求撤掉的")
            return
        self.fail("找不到 MainWindow")

    def test_task_started_not_connected_to_minimize(self):
        """★ ``task_started`` 不许再连到最小化。"""
        src = MW.read_text(encoding="utf-8")
        self.assertNotIn(
            "task_started.connect(self.go_background_to_game)", src,
            "task_started 还连着 go_background_to_game —— 任务一启动就缩窗口")


if __name__ == "__main__":
    unittest.main(verbosity=2)
