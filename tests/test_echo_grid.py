"""声骸网格定位：3.7 声骸堆叠导致"强化完不能继续"的修正。

    python tests/test_echo_grid.py

## 问题（用户 2026-10-02 报）

"3.7 更新后，更新了声骸堆叠，导致强化好了一个声骸后，会自动跳到强化好的
声骸位置，从而不能继续强化到其他声骸了"

## 根因

ok-ww 的 ``EnhanceEchoTask.run()`` **从不主动选下一个声骸** ——
它假设"强化完 ESC 回列表，光标还在原位"。堆叠打破了这个假设：
强化好的被归类重排、光标被带过去 → ``is_0_level()`` 读到"不是 0 级"
→ **直接收工**。

## 修法

用户实测"滚动和方向键都不能移动光标，**只能鼠标点击**"
→ 在两个收尾动作后扫一遍网格，点第一个未强化的。

## ⚠ 这里测的是**几何和判定逻辑**（纯函数）

真正的图像匹配效果已经用**两张实机截图 × 全部格子**验证过
（见 ``tools/make_echo_stack_template.py`` 的说明）。
"""

from __future__ import annotations

import ast
import pathlib
import sys
import unittest

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.tools.game.echo_enhance import echo_grid  # noqa: E402

TASK = ROOT / "src" / "tools" / "game" / "echo_enhance" / "okww_task.py"
VENDOR_TASK = ROOT / "vendor" / "okww" / "okww" / "task" / "EnhanceEchoTask.py"


class TestGridGeometry(unittest.TestCase):
    """网格几何 —— 坐标要对得上截图。"""

    def test_covers_full_screen(self):
        """18 个格子的坐标都要落在屏幕内。"""
        for row, col in echo_grid.slots():
            rx, ry = echo_grid.card_center_relative(row, col)
            with self.subTest(slot=(row, col)):
                self.assertGreater(rx, 0.0)
                self.assertLess(rx, 1.0)
                self.assertGreater(ry, 0.0)
                self.assertLess(ry, 1.0)

    def test_grid_size(self):
        """6 列 × 3 排 = 18 格（用户第二张截图确认过）。"""
        self.assertEqual(echo_grid.COLS, 6)
        self.assertEqual(echo_grid.ROWS, 3)
        self.assertEqual(len(list(echo_grid.slots())), 18)

    def test_scan_order_is_row_major(self):
        """扫描顺序：从上到下、从左到右（先找上面的）。"""
        got = list(echo_grid.slots())
        self.assertEqual(got[0], (0, 0))
        self.assertEqual(got[1], (0, 1))
        self.assertEqual(got[5], (0, 5))
        self.assertEqual(got[6], (1, 0))
        self.assertEqual(got[17], (2, 5))

    def test_pitch_is_consistent(self):
        """相邻格子的间距必须一致 —— 不然点着点着就偏了。"""
        xs = [echo_grid.card_center_relative(0, c)[0]
              for c in range(echo_grid.COLS)]
        gaps = [round(xs[i + 1] - xs[i], 6) for i in range(len(xs) - 1)]
        self.assertEqual(len(set(gaps)), 1, f"列间距不一致: {gaps}")

        ys = [echo_grid.card_center_relative(r, 0)[1]
              for r in range(echo_grid.ROWS)]
        vgaps = [round(ys[i + 1] - ys[i], 6) for i in range(len(ys) - 1)]
        self.assertEqual(len(set(vgaps)), 1, f"行间距不一致: {vgaps}")

    def test_first_card_position(self):
        """第一张卡的中心 —— 和截图量出来的一致（166, 152.5 @1280x720）。"""
        rx, ry = echo_grid.card_center_relative(0, 0)
        self.assertAlmostEqual(rx * echo_grid.BASE_W, 166.25, delta=1.0)
        self.assertAlmostEqual(ry * echo_grid.BASE_H, 152.5, delta=1.0)

    def test_last_card_before_right_panel(self):
        """第 6 列不能越过右侧面板（面板从 x≈870 开始）。"""
        rx, _ry = echo_grid.card_center_relative(0, echo_grid.COLS - 1)
        self.assertLess(rx * echo_grid.BASE_W, 870,
                        "第 6 列跑到右侧面板里了")


class TestIconBox(unittest.TestCase):
    """★ 层叠图标的搜索框 —— 这里有个**必需**的 pad。"""

    def test_box_is_bigger_than_template(self):
        """★★ 搜索框必须**严格大于**模板。

        ⚠ 这是实测抓到的：搜索框 == 模板大小时，
        ``cv2.matchTemplate`` 只产出一个值、没有滑动余地，
        每张卡 1~2 像素的位置偏差就让得分从 1.00 掉到 0.36。

        实测（18 格）：pad=0 漏检 **7 格**；pad=6 漏检 **0 格**。
        """
        x1, y1, x2, y2 = echo_grid.icon_box_base(0, 0)
        w, h = x2 - x1, y2 - y1
        self.assertGreater(
            w, echo_grid.ICON_W,
            f"搜索框宽 {w} 不大于模板宽 {echo_grid.ICON_W} —— 没有滑动余量")
        self.assertGreater(
            h, echo_grid.ICON_H,
            f"搜索框高 {h} 不大于模板高 {echo_grid.ICON_H} —— 没有滑动余量")
        self.assertEqual(w, echo_grid.ICON_W + 2 * echo_grid.SEARCH_PAD)
        self.assertEqual(h, echo_grid.ICON_H + 2 * echo_grid.SEARCH_PAD)

    def test_search_pad_positive(self):
        self.assertGreater(echo_grid.SEARCH_PAD, 0,
                           "pad 必须是正数 —— pad=0 实测漏检 7 格")

    def test_box_inside_card(self):
        """搜索框不能超出卡片范围（否则会匹配到隔壁卡）。"""
        for row, col in echo_grid.slots():
            x1, y1, x2, y2 = echo_grid.icon_box_base(row, col)
            left = echo_grid.GRID_X0 + col * echo_grid.COL_PITCH
            top = echo_grid.GRID_Y0 + row * echo_grid.ROW_PITCH
            with self.subTest(slot=(row, col)):
                self.assertGreaterEqual(x1, left - 1)
                self.assertLessEqual(x2, left + echo_grid.CARD_W + 1)
                self.assertGreaterEqual(y1, top)
                self.assertLessEqual(y2, top + echo_grid.CARD_H)

    def test_boxes_do_not_overlap(self):
        """相邻格子的搜索框不能重叠 —— 否则会认错格。"""
        for row in range(echo_grid.ROWS):
            boxes = [echo_grid.icon_box_base(row, c)
                     for c in range(echo_grid.COLS)]
            for i in range(len(boxes) - 1):
                with self.subTest(row=row, col=i):
                    self.assertLess(boxes[i][2], boxes[i + 1][0],
                                    f"第{row}排 {i}和{i + 1} 的搜索框重叠了")


class TestThreshold(unittest.TestCase):
    """阈值要落在实测的空档里。"""

    def test_threshold_between_measured_ranges(self):
        """实测：未强化 0.887~1.000 / 已强化 0.047~0.085。

        阈值要在 0.085 和 0.887 之间 —— 两边都留余量。
        """
        self.assertGreater(echo_grid.THRESHOLD, 0.3,
                           f"阈值 {echo_grid.THRESHOLD} 太低，已强化（≈0.08）会误判")
        self.assertLess(echo_grid.THRESHOLD, 0.85,
                        f"阈值 {echo_grid.THRESHOLD} 太高，未强化（≈0.89）会漏判")

    def test_label_matches_template_generator(self):
        """模板名必须和生成脚本里的一致 —— 不一致就永远找不到。"""
        gen = (ROOT / "tools" / "make_echo_stack_template.py").read_text(
            encoding="utf-8")
        self.assertIn(f'LABEL = "{echo_grid.LABEL}"', gen,
                      f"生成脚本里的 LABEL 和 echo_grid.LABEL"
                      f"（{echo_grid.LABEL}）不一致")


class TestFindNextUnenhanced(unittest.TestCase):
    """扫描逻辑 —— 用假 task 测（不碰真 UI）。"""

    class _FakeTask:
        """只实现 find_one / box_of_screen_scaled，按格子编号回答。"""

        def __init__(self, unenhanced: set):
            self.unenhanced = unenhanced
            self.asked = []

        def box_of_screen_scaled(self, bw, bh, x1, y1, x2, y2, name=None):
            self.asked.append((x1, y1, x2, y2))
            return (x1, y1, x2, y2)

        def find_one(self, label, box=None, threshold=0):
            assert label == echo_grid.LABEL, label
            # 把 box 反推回格子：用 x1 找最近的一列
            x1 = box[0] + echo_grid.SEARCH_PAD - echo_grid.ICON_DX
            col = round((x1 - echo_grid.GRID_X0) / echo_grid.COL_PITCH)
            y1 = box[1] + echo_grid.SEARCH_PAD - echo_grid.ICON_DY
            row = round((y1 - echo_grid.GRID_Y0) / echo_grid.ROW_PITCH)
            idx = row * echo_grid.COLS + col
            return object() if idx in self.unenhanced else None

    def test_finds_first_in_scan_order(self):
        """★ 必须返回**扫描顺序上第一个**未强化的（从上到下、从左到右）。"""
        task = self._FakeTask({5, 2, 7})
        self.assertEqual(echo_grid.find_next_unenhanced(task), (0, 2))

    def test_finds_later_row(self):
        task = self._FakeTask({9})
        self.assertEqual(echo_grid.find_next_unenhanced(task), (1, 3))

    def test_returns_none_when_all_enhanced(self):
        """一屏全强化过 → 返回 None（让 ok-ww 正常收工）。"""
        task = self._FakeTask(set())
        self.assertIsNone(echo_grid.find_next_unenhanced(task))

    def test_returns_none_when_empty_grid(self):
        self.assertIsNone(echo_grid.find_next_unenhanced(self._FakeTask(set())))

    def test_stops_at_first_hit(self):
        """找到就停 —— 不该白扫剩下的格子。"""
        task = self._FakeTask({0, 1, 2, 3})
        echo_grid.find_next_unenhanced(task)
        self.assertEqual(len(task.asked), 1,
                         f"找到后还扫了 {len(task.asked)} 格 —— 应该只问 1 格")

    def test_uses_base_resolution(self):
        """★ 几何是 1280x720 量的 —— 交给 box_of_screen_scaled 时
        必须把基准分辨率传进去，让它做**唯一一次**缩放。"""
        calls = []

        class _T(self._FakeTask):
            def box_of_screen_scaled(self, bw, bh, *a, **k):
                calls.append((bw, bh))
                return super().box_of_screen_scaled(bw, bh, *a, **k)

        echo_grid.find_next_unenhanced(_T({0}))
        self.assertTrue(calls)
        self.assertEqual(calls[0], (echo_grid.BASE_W, echo_grid.BASE_H),
                         "传给 box_of_screen_scaled 的不是基准分辨率 —— "
                         "会导致双重缩放")


class TestWiredIntoTask(unittest.TestCase):
    """★ 接线：两个收尾动作都要调用定位。"""

    def setUp(self):
        self.text = TASK.read_text(encoding="utf-8")
        self.tree = ast.parse(self.text)

    def _method(self, name: str) -> ast.FunctionDef:
        for node in ast.walk(self.tree):
            if isinstance(node, ast.FunctionDef) and node.name == name:
                return node
        raise AssertionError(f"okww_task.py 里没有 {name}")

    def test_lock_calls_aim(self):
        """★ 上锁收尾后要把光标移回未强化的声骸。"""
        calls = {n.func.attr for n in ast.walk(self._method("lock_and_esc"))
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        self.assertIn("_aim_at_next_unenhanced", calls,
                      "lock_and_esc 没调 _aim_at_next_unenhanced —— "
                      "上锁后光标漂了就不会继续强化下一个")

    def test_trash_calls_aim(self):
        """★ 弃置收尾后同理。"""
        calls = {n.func.attr for n in ast.walk(self._method("trash_and_esc"))
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        self.assertIn("_aim_at_next_unenhanced", calls,
                      "trash_and_esc 没调 _aim_at_next_unenhanced")

    def test_calls_super_first(self):
        """必须先 ``super().xxx_and_esc()`` —— 否则 ok-ww 的收尾没做完就点格子。"""
        for name in ("lock_and_esc", "trash_and_esc"):
            with self.subTest(method=name):
                body = self._method(name)
                calls = [n for n in ast.walk(body)
                         if isinstance(n, ast.Call)]
                supers = [n for n in calls
                          if isinstance(n.func, ast.Attribute)
                          and n.func.attr == name]
                self.assertTrue(supers, f"{name} 没调 super().{name}()")

    def test_aim_is_robust(self):
        """★ 定位失败**不能**把整个任务搞崩 —— 要吞掉异常并返回 False。"""
        body = self._method("_aim_at_next_unenhanced")
        tries = [n for n in ast.walk(body) if isinstance(n, ast.Try)]
        self.assertTrue(tries, "_aim_at_next_unenhanced 没有 try —— "
                              "定位出错会中断整个强化任务")

    def test_uses_grid_module(self):
        """判定要复用 echo_grid（别在任务里手写坐标）。"""
        self.assertIn("echo_grid", self.text,
                      "okww_task.py 没引用 echo_grid")


class TestTemplateActuallyLoads(unittest.TestCase):
    """★★ 「模板真的被 ok-ww 加载了吗」—— 这里**踩过一个无声的坑**。

    ## 坑（2026-10-03 实机白做一次）

    我第一版把模板写成 ``ok_tasks/assets/echo_stack.json``，
    实机跑完**一次都没生效** —— 日志里连"堆叠修正"都没有，
    只有一行无声的::

        Merged 0 features from ok_tasks\\assets\\coco_annotations.json

    原因：ok-script 的 ``FeatureSet.process_data()`` 里
    **文件名是写死的**::

        ok_tasks_coco = os.path.join('ok_tasks', 'assets',
                                     'coco_annotations.json')

    **只读这一个**。别的名字一律不加载。

    → 所以模板必须**合并**进那个文件（走 ``tools/ok_tasks_assets.py``）。
    """

    COCO = (ROOT / "vendor" / "okww" / "ok_tasks" / "assets"
            / "coco_annotations.json")

    def test_no_stray_json_files(self):
        """★ 扩展目录里**不该有别的 json** —— 有就说明有人又写歪了。

        只要出现 ``echo_stack.json`` 这类文件，就说明模板没被合并进去，
        实机不会生效（而且**没有任何报错**）。
        """
        ext = self.COCO.parent
        if not ext.exists():
            self.skipTest("扩展目录不存在")
        stray = [p.name for p in ext.glob("*.json")
                 if p.name != "coco_annotations.json"]
        self.assertEqual(
            stray, [],
            f"扩展目录里有不该存在的 json：{stray} —— "
            f"ok-script 只读 coco_annotations.json，别的文件**不会被加载**"
            f"（实机无声失效）。用 tools/ok_tasks_assets.merge() 合并进去。")

    def test_icon_registered_in_the_one_file(self):
        """★ ``echo_stack_icon`` 必须在**那个唯一会被读的文件**里。"""
        import json

        data = json.loads(self.COCO.read_text(encoding="utf-8"))
        names = {c["name"] for c in data["categories"]}
        self.assertIn(
            echo_grid.LABEL, names,
            f"{echo_grid.LABEL} 不在 coco_annotations.json 里 —— "
            f"跑 tools/make_echo_stack_template.py 重新生成")
        # 图像条目也要在
        files = {i["file_name"] for i in data["images"]}
        self.assertIn("images/echo_stack.png", files,
                      "底图没登记进 images")

    def test_coexists_with_xin_templates(self):
        """★ 合并不能把「心」的模板挤掉（两套模板要共存）。"""
        import json

        data = json.loads(self.COCO.read_text(encoding="utf-8"))
        names = {c["name"] for c in data["categories"]}
        for wanted in ("char_xin", "echo_stack_icon"):
            with self.subTest(name=wanted):
                self.assertIn(wanted, names,
                              f"{wanted} 被挤掉了 —— 合并逻辑有 bug")

    def test_coco_is_pure_ascii(self):
        """★ 必须纯 ASCII —— ok-script 的 load_json 没指定 encoding。

        中文会 UnicodeDecodeError，把**整个模板加载**搞崩（实测踩过）。
        """
        raw = self.COCO.read_bytes()
        try:
            raw.decode("ascii")
        except UnicodeDecodeError as exc:
            self.fail(f"coco_annotations.json 里有非 ASCII 字符：{exc}")

    def test_loads_through_ok_script(self):
        """★★ 走 ok-script 的真实加载器 —— 这是最终判据。

        ⚠ 关键：**屏幕尺寸要用游戏真实分辨率**（1280×720）。
        ok-script 按 ``scale = min(屏幕/底图尺寸)`` 缩放模板，
        所以屏幕和底图**同尺寸**时模板才原样（scale=1）。

        实测（同一份 coco，不同屏幕）::

            屏幕 1280x720   → 模板 22x18   ✓ 原样（我们的场景）
            屏幕 1920x1080  → 模板 33x27   （被放大）
            屏幕  640x360   → 模板 11x9    （被缩小）

        ⚠ **json 里声明的 width/height 不参与缩放** ——
        真正决定缩放比的是 **PNG 文件的实际像素尺寸**。
        所以护栏守的是"底图实际尺寸 == 游戏分辨率"。
        """
        import logging
        import os

        logging.disable(logging.CRITICAL)
        v = str(ROOT / "vendor" / "okww")
        if v not in sys.path:
            sys.path.insert(0, v)
        old = os.getcwd()
        os.chdir(v)
        try:
            from ok.feature.FeatureSet import read_from_json

            feats, _b, _c, _ok, _k = read_from_json(
                str(self.COCO), echo_grid.BASE_W, echo_grid.BASE_H)
        finally:
            os.chdir(old)
            logging.disable(logging.NOTSET)

        self.assertIn(echo_grid.LABEL, feats,
                      f"{echo_grid.LABEL} 加载不出来 —— 实机会无声失效")
        mat = feats[echo_grid.LABEL].mat
        self.assertEqual(
            (mat.shape[1], mat.shape[0]),
            (echo_grid.ICON_W, echo_grid.ICON_H),
            f"模板在 {echo_grid.BASE_W}x{echo_grid.BASE_H} 下不是 "
            f"{echo_grid.ICON_W}x{echo_grid.ICON_H} —— 被缩放了。"
            f"检查底图 PNG 的实际像素尺寸是不是 {echo_grid.BASE_W}x"
            f"{echo_grid.BASE_H}")

    def test_base_image_has_screen_size(self):
        """★★ 底图的**实际像素尺寸**必须 == 游戏分辨率。

        这是决定"模板原不原样"的唯一因素（json 声明不参与）。
        底图做小了（比如紧凑拼图）→ ok-script 把模板放大好几倍
        → 匹配率归零（「心」的模板踩过：270 宽的底图让模板变成 539）。
        """
        from PIL import Image

        png = (self.COCO.parent / "images" / "echo_stack.png")
        self.assertTrue(png.exists(), f"底图不在：{png}")
        self.assertEqual(
            Image.open(png).size,
            (echo_grid.BASE_W, echo_grid.BASE_H),
            f"底图尺寸不是 {echo_grid.BASE_W}x{echo_grid.BASE_H} —— "
            f"ok-script 会缩放模板，匹配率会掉。"
            f"（⚠ 放大模板也不行 —— 实测得分从 0.99 掉到 0.36）")


    def test_template_is_not_blurry(self):
        """★ 模板得**清晰** —— 别把图标放大过再存。

        ⚠ 第一版我把 22x18 的图标放大到 33x27 再存，
        匹配得分从 **0.99 掉到 0.36**（放大再缩小 = 细节全丢）。

        判据：底图左上角那块（= 模板本体）的**相邻像素均差**。
        放大过的图会变平滑，这个值明显偏小。实测::

            原始 22x18（清晰）        38.94
            放大 2 倍再裁回           26.00
            放大 4 倍再裁回           12.30

        → 阈值取 **32**（卡在清晰和 2 倍放大之间）。

        ⚠ 这个 1.0 的初版阈值**抓不住放大**（实测护栏失效），
        所以改成量出来的 32。
        """
        from PIL import Image

        png = self.COCO.parent / "images" / "echo_stack.png"
        # 图标贴在底图左上角（生成脚本里 paste 到 (0,0)）
        icon = Image.open(png).convert("RGB").crop(
            (0, 0, echo_grid.ICON_W, echo_grid.ICON_H))
        arr = np.asarray(icon).astype(np.float64)
        lap = float(np.abs(np.diff(arr, axis=0)).mean())
        self.assertGreater(
            lap, 32.0,
            f"模板太平滑（相邻像素均差 {lap:.1f}，清晰的约 38.9）—— "
            f"可能被放大过。⚠ 必须**按裁剪时的分辨率存**"
            f"（实测放大后匹配得分 0.99→0.36）")


class TestVendorUntouched(unittest.TestCase):
    """★ 改动必须在 MyTools 自己的代码里 —— 不碰 vendor。

    改了 vendor 的话上游一更新就被冲掉（这个坑在「心」的模板上踩过）。
    """

    def test_vendor_has_no_stack_logic(self):
        text = VENDOR_TASK.read_text(encoding="utf-8")
        for bad in ("echo_stack_icon", "click_next_unenhanced", "_aim_at"):
            with self.subTest(bad=bad):
                self.assertNotIn(bad, text,
                                 f"vendor 的 EnhanceEchoTask 里出现了 {bad} —— "
                                 f"上游更新会冲掉")

    def test_grid_module_lives_in_mytools(self):
        self.assertTrue(
            (ROOT / "src" / "tools" / "game" / "echo_enhance"
             / "echo_grid.py").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
