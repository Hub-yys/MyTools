"""「开始」步准备动作（开背包 + 探测）的单元测试（假窗口 + 假 OCR）。

    python tests/test_echo_prep.py

验证的是：
* 已校准的步骤真的按了键 / 点了位置，且**点的相对坐标换算正确**（区域 → 整帧）；
* 没校准的步骤**一个都不点**（这是安全底线：不确定的坐标绝不落地）；
* 探测把「截图 + 每行文字的相对/像素坐标」落盘，格式能被校准直接使用；
* 窗口找不到 / 外部叫停时行为明确。

验证不了的是真实游戏里那些按钮到底在哪 —— 那要靠探测结果校准，见 prepare.py 顶部。
"""

from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.core.loadout import DEFAULT_STATUS  # noqa: E402
from src.tools.game.echo_enhance.controller import WindowNotFound  # noqa: E402
from src.tools.game.echo_enhance.prepare import (  # noqa: E402
    PREP_STEPS,
    EchoPrep,
    PrepAction,
)
from src.tools.game.echo_enhance.reader import OcrLine  # noqa: E402

FRAME_H, FRAME_W = 1080, 1920


def _pick(stat: str):
    """造一条「某档声骸 + 一条主属性」的选择（给 build_filter_steps 的用例用）。"""
    from src.core.loadout import EchoPick
    return EchoPick(echo="示例声骸", stats=(stat,))


class FakeWindow:
    """假游戏窗口：记录按键/点击，画面给一张黑图。"""

    def __init__(self, found: bool = True):
        self.keys: list[str] = []
        self.clicks: list[tuple[float, float]] = []
        #: 光标移动与滚轮（"列表比一屏长"时要用，见 _scroll_list）
        self.moved: list[tuple[float, float]] = []
        self.scrolls: list[int] = []
        self._found = found

    def find(self):
        return 12345 if self._found else None

    def describe(self):
        return "FakeWindow"

    def bring_to_front(self):
        pass

    def refresh_rect(self):
        """假客户区：1920x1080（16:9）。

        `EchoPrep.run()` 会先查画面比例（2026-09-27），所以假窗口也得给得出尺寸。
        """
        from src.tools.game.echo_enhance.controller import ClientRect
        return ClientRect(0, 0, FRAME_W, FRAME_H)

    def move_cursor(self, relative_x, relative_y):
        """滚轮要先把光标挪到列表上 —— 假的记一下就好。"""
        self.moved.append((relative_x, relative_y))

    def scroll(self, clicks):
        """假滚轮：记下来，好断言"到底滚没滚"。"""
        self.scrolls.append(clicks)

    def grab(self):
        return np.zeros((FRAME_H, FRAME_W, 3), dtype=np.uint8)

    def press(self, key, after_sleep=0.3):
        self.keys.append(key)

    def click(self, x, y, after_sleep=0.3):
        self.clicks.append((x, y))


class FakeReader:
    """假 OCR：返回预先摆好的行（坐标是**裁剪图内**的像素坐标）。"""

    def __init__(self, lines: list[OcrLine] | None = None):
        self.lines = lines or []
        self.calls = 0

    def ocr_lines(self, frame):
        self.calls += 1
        return list(self.lines)


def line(text: str, x: float, y: float, w: float = 100.0, h: float = 40.0) -> OcrLine:
    return OcrLine(text=text, score=0.99, x=x, y=y, width=w, height=h)


def echo_page_line() -> OcrLine:
    """「已经停在声骸页」的标记：左上角那行「声骸 494/3000」。

    ★ 2026-09-27：`PREP_STEPS[0]`（按 B）现在带 ``expect="声骸"`` 验证 ——
    按完 B 必须看到它，否则报错停下（那是对的，游戏停在别的分类时点漏斗会全错位）。
    所以假环境的 OCR **必须**先有这行字：要模拟真实画面，而不是把验证去掉。
    """
    return line("声骸 494/3000", 10, 8, 180, 26)


class TestPrepSteps(unittest.TestCase):
    def test_default_table_has_only_bag_opening_calibrated(self):
        """安全底线：除了"按 B"，其它步骤都还没校准、不会真去点。"""
        verified = [s.label for s in PREP_STEPS if s.verified]
        self.assertEqual(verified, ["打开背包"])
        # ⚠ 这里的意图是"**没校准的绝不点**"，不是"必须是按文字找" ——
        #   未校准的步骤里可以有按坐标点的（"打开过滤器"就是：漏斗没有文字）。
        #   2026-09-27 把断言从 "都是 click_text" 改成这个更本质的形式。
        self.assertTrue(all(not s.verified for s in PREP_STEPS[1:]))
        self.assertFalse(any(s.text == "" for s in PREP_STEPS[1:]
                             if s.kind == "click_text"))


class TestPrepRun(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.probe_dir = pathlib.Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_default_steps_only_open_the_bag(self):
        """没挂配置时的兜底**只按 B** —— 不替用户决定筛选条件。

        ★ 2026-09-27：原来这里还有「开过滤器 / 筛未调谐 / 确认筛选 / 按等级排序」
        四步。用户手动截来的「筛选面板打开后」画面证明其中**两步是凭空假设的**：
        面板的「状态」只有 已弃置/已锁定/未标记（**没有「未调谐」**），
        而且**没有「确认」按钮**（选完即时生效）。删掉后兜底就只剩这一步。
        """
        window = FakeWindow()
        prep = EchoPrep(window=window, reader=FakeReader([echo_page_line()]),
                        probe_dir=self.probe_dir)
        result = prep.run()

        self.assertEqual(window.keys, ["b"], "只应该按了一次 B")
        self.assertEqual(window.clicks, [], "兜底不该点任何东西")
        self.assertIsNone(result, "全都校准好了 → 不该再产出探测")
        self.assertEqual(len(PREP_STEPS), 1, "兜底就该只有「按 B」这一步")

    def test_all_verified_runs_through_without_probe(self):
        window = FakeWindow()
        steps = (
            PrepAction("press", "打开背包", key="b", verified=True, wait=0.0),
        )
        prep = EchoPrep(window=window, reader=FakeReader([]), probe_dir=self.probe_dir,
                        steps=steps)
        self.assertIsNone(prep.run(), "全校准好了就不该再出探测产物")
        self.assertEqual(window.keys, ["b"])
        self.assertEqual(list(self.probe_dir.iterdir()), [])

    def test_clicked_coordinates_are_converted_from_region(self):
        """区域 (0.5,0.5,1.0,1.0) 里的一行 → 点它的中心，坐标要换算回整帧。

        裁剪图 960x540，行在裁剪图里的 (300,200,100,40)：
            相对 x = 0.5 + 300/960*0.5 = 0.65625，宽 = 100/960*0.5 = 0.052083
        所以点中心 = 0.682292；y 同理 = 0.703704。
        """
        window = FakeWindow()
        reader = FakeReader([line("声骸", 300, 200, 100, 40)])
        steps = (
            PrepAction("click_text", "切到声骸页签", region=(0.5, 0.5, 1.0, 1.0),
                       text="声骸", verified=True, wait=0.0),
        )
        prep = EchoPrep(window=window, reader=reader, probe_dir=self.probe_dir, steps=steps)
        self.assertIsNone(prep.run())
        self.assertEqual(len(window.clicks), 1)
        x, y = window.clicks[0]
        self.assertAlmostEqual(x, 0.682292, places=5)
        self.assertAlmostEqual(y, 0.703704, places=5)

    def test_missing_text_raises_instead_of_clicking_blind(self):
        window = FakeWindow()
        steps = (
            PrepAction("click_text", "切到声骸页签", region=(0.5, 0.5, 1.0, 1.0),
                       text="声骸", verified=True, wait=0.0),
        )
        prep = EchoPrep(window=window, reader=FakeReader([line("武器", 300, 200)]),
                        probe_dir=self.probe_dir, steps=steps)
        with self.assertRaises(RuntimeError) as ctx:
            prep.run()
        self.assertIn("没找到文字", str(ctx.exception))
        self.assertEqual(window.clicks, [], "找不到就绝不能乱点")

    def test_window_not_found(self):
        prep = EchoPrep(window=FakeWindow(found=False), reader=FakeReader([]),
                        probe_dir=self.probe_dir)
        with self.assertRaises(WindowNotFound):
            prep.run()

    def test_stop_request_aborts(self):
        prep = EchoPrep(window=FakeWindow(), reader=FakeReader([]),
                        probe_dir=self.probe_dir, should_stop=lambda: True)
        with self.assertRaises(RuntimeError) as ctx:
            prep.run()
        self.assertIn("已停止", str(ctx.exception))


class TestProbeOutput(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.probe_dir = pathlib.Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _probe(self, lines):
        """跑一次探测。

        ⚠ 假 OCR 里固定**先放一行"已在声骸页"的标记**（见 :func:`echo_page_line`）——
        `PREP_STEPS[0]`（按 B）带 ``expect="声骸"`` 验证，缺了它第 1 步就会报错停下。
        """
        logs: list[str] = []
        prep = EchoPrep(window=FakeWindow(),
                        reader=FakeReader([echo_page_line()] + list(lines)),
                        probe_dir=self.probe_dir, log=logs.append, force_probe=True)
        return prep, prep.run(), logs

    def test_writes_png_and_txt(self):
        prep, result, logs = self._probe([line("声骸", 100, 200), line("筛选", 1500, 60)])
        self.assertTrue(result.png_path.exists())
        self.assertTrue(result.txt_path.exists())
        self.assertGreater(result.png_path.stat().st_size, 1000, "截图不该是空文件")
        # 2 条自己的 + 1 条"已在声骸页"标记
        self.assertEqual(result.lines, 3)
        self.assertTrue(any("探测" in line for line in logs))

    def test_txt_has_relative_and_pixel_coordinates(self):
        prep, result, _logs = self._probe([line("声骸", 960, 540, 96, 54)])
        text = result.txt_path.read_text(encoding="utf-8")
        lines = text.splitlines()
        self.assertIn("窗口 1920x1080", lines[0])
        # 第 3 行起是文字条目（前 2 行是文件头）；按坐标挑出 y=540 那条
        row = next(r for r in lines[2:] if "960,540,96,54" in r)
        self.assertIn("声骸", row)
        self.assertIn("0.5000,0.5000,0.0500,0.0500", row)

    def test_lines_sorted_top_to_bottom(self):
        prep, result, _logs = self._probe([
            line("下面", 100, 900),
            line("上面", 100, 100),
        ])
        rows = result.txt_path.read_text(encoding="utf-8").splitlines()[2:]
        # rows[0] 是"已在声骸页"标记（y=8，最上面），所以要跳过它看后面两行
        self.assertIn("上面", rows[1])
        self.assertIn("下面", rows[2])





class TestTaskPrepWiring(unittest.TestCase):
    """★ 任务「开始」步的准备动作接线（用户 2026-09-26 第 (1) 条）：

    > 可以按照声骸筛选配置，按 B 打开背包筛选指定的声骸

    这条盯的是**接线**：`create_task_prep` 要
    ① 读得到编排里挂的「角色声骸筛选配置」并把目标打进日志；
    ② 把 `EchoPrep`（按 B + 未校准步骤跳过 + 探针）交给流程。
    真实点击能不能成，取决于校准 —— 那部分见 prepare.py 顶部。
    """

    def _capture_logs(self, options, *, loadout=None):
        from src.core import loadout as loadout_mod
        from src.tools.game.echo_enhance.tool import EchoEnhanceTool

        logs: list[str] = []
        original = loadout_mod.LoadoutStore
        try:
            if loadout is None:
                loadout_mod.LoadoutStore = lambda *a, **k: _EmptyStore()
            else:
                loadout_mod.LoadoutStore = lambda *a, **k: _OneStore(loadout)
            prep = EchoEnhanceTool().create_task_prep(options, logs.append, lambda: False)
        finally:
            loadout_mod.LoadoutStore = original
        return prep, logs

    def test_prep_returns_echo_prep(self):
        """准备动作要真的交回一个 EchoPrep（不是 None = 什么都不做）。"""
        prep, _ = self._capture_logs({})
        self.assertIsInstance(prep, EchoPrep)

    def test_prep_reads_bound_loadout_target(self):
        """挂了筛选配置 → 日志里要写出**这次要筛的目标**（套装 + 各档声骸）。"""
        loadout = _make_loadout("绯雪")
        prep, logs = self._capture_logs(
            {"config_keys": [loadout.id], "config_kinds": ["loadout"],
             "configs": ["绯雪-声骸筛选"]},
            loadout=loadout)
        joined = "\n".join(logs)
        self.assertIn("绯雪", joined, joined)
        self.assertIn(loadout.echo_set, joined, f"要点出套装：{joined}")
        self.assertIsInstance(prep, EchoPrep)

    def test_prep_without_bound_loadout_says_so(self):
        """没挂筛选配置 → 明确说一声"自己筛"，不能装没事。"""
        _prep, logs = self._capture_logs({})
        self.assertTrue(any("没挂" in line for line in logs), logs)

    def test_prep_ignores_other_config_kinds(self):
        """挂的是**强化配置**时不该被当成筛选目标。"""
        from src.core.echo_profile import EchoProfile

        _prep, logs = self._capture_logs(
            {"config_keys": [EchoProfile(name="绯雪").id],
             "config_kinds": ["echo_profile"]})
        self.assertTrue(any("没挂" in line for line in logs), logs)

    def test_unverified_steps_are_never_clicked(self):
        """安全底线：没校准的步骤一个都不点（假窗口跑一遍，只有按 B 落地）。"""
        prep, _ = self._capture_logs({})
        window = FakeWindow()
        prep.window = window
        prep.reader = FakeReader([echo_page_line()])
        with tempfile.TemporaryDirectory() as tmp:
            prep.probe_dir = pathlib.Path(tmp)
            prep.run()
        self.assertEqual(window.keys, ["b"], "只该按 B")
        self.assertEqual(window.clicks, [], "未校准的步骤一个都不许点")


class _EmptyStore:
    def get(self, _key):
        return None


class _OneStore:
    def __init__(self, item):
        self._item = item

    def get(self, key):
        return self._item if str(key) == getattr(self._item, "id", "") else None


def _make_loadout(character: str):
    """造一条填得完整的筛选配置（用数据集里真实存在的套装 / 声骸）。"""
    from src.core.game_data import CONFIGURABLE_ECHO_SETS, find_echo_set
    from src.core.loadout import Loadout

    info = max(CONFIGURABLE_ECHO_SETS, key=lambda s: len(s.by_cost(4)))
    loadout = Loadout(character=character, echo_set=info.name)
    for cost in (4, 3, 1):
        items = info.by_cost(cost)
        if items:
            loadout.add_pick(cost, items[0], items[0].stats[0])
    return loadout

class TestFilterSteps(unittest.TestCase):
    """★ 按「角色声骸筛选配置」生成准备步骤（用户 2026-09-26 第 (1) 条）。

    游戏那块「筛选」面板四行 ↔ 配置字段：
    状态（单选）/ 品质（多选）/ 合鸣（= 套装）/ 主音属性。
    这里盯前三个 —— 主音属性是另一个弹窗，还没做（见 prepare.py 的说明）。
    """

    def _steps(self, **kw):
        from src.core.loadout import Loadout
        from src.tools.game.echo_enhance.prepare import build_filter_steps
        return build_filter_steps(Loadout(character="绯雪", **kw))

    def test_first_step_is_press_b(self):
        steps = self._steps()
        self.assertEqual((steps[0].kind, steps[0].key), ("press", "b"))

    def test_status_quality_set_come_from_the_config(self):
        steps = self._steps(status="已锁定", qualities=("四星", "五星"),
                            echo_set="雪落无声之愿")
        texts = [s.text for s in steps]
        self.assertIn("已锁定", texts, "状态要按配置选")
        self.assertIn("四星", texts, "品质勾了几个就要点几个")
        self.assertIn("五星", texts)
        self.assertIn("雪落无声之愿", texts, "合鸣要按配置里的套装选")

    def test_default_status_and_quality_are_used(self):
        """配置没设过 → 用默认（**已锁定** / 五星），别漏掉这两行。

        ⚠ 默认状态 2026-09-28 从「未标记」改成「已锁定」（用户批注"默认已锁定"）——
        断言要跟着 :data:`~src.core.loadout.DEFAULT_STATUS` 走，别再写死字符串。
        """
        texts = [s.text for s in self._steps()]
        self.assertIn(DEFAULT_STATUS, texts)
        self.assertIn("五星", texts)

    def test_no_echo_set_means_no_set_steps(self):
        """没选套装 → 不该生成"点开合鸣 / 选套装"两步（点了也没得选）。"""
        steps = self._steps()
        self.assertFalse(any(s.text == "合鸣" for s in steps))

    def test_sort_step_is_last(self):
        steps = self._steps(echo_set="雪落无声之愿")
        self.assertIn("等级顺序", steps[-1].text,
                      "最后一步必须是排序 —— ok-ww 只处理列表第一个，0 级得在最前")

    # ---- 导航步骤的校准（2026-09-27：用户报"没有筛选就直接强化"时揪出来的）----
    def test_echo_tab_point_is_gone(self):
        """★ `ECHO_TAB_POINT` 不该再存在 —— 它指向的是**错的图标**。

        原来有一步「切到「声骸」页签」，按坐标点 `(0.031, 0.296)`，注释写的是
        "背包左侧图标列第 2 个"。用探测截图核对后发现：按 B 之后**已经**在声骸
        分类（左上角就是「声骸 494/3000」），而那个坐标实测落在**左侧全局功能
        菜单的手套图标**上 —— 点下去会把界面切走。
        """
        from src.tools.game.echo_enhance import prepare
        self.assertFalse(hasattr(prepare, "ECHO_TAB_POINT"),
                         "那个坐标是错的（落在左侧全局菜单上），删了就别再放回来")

    def test_no_page_tab_step(self):
        steps = self._steps(echo_set="雪落无声之愿")
        labels = [s.label for s in steps]
        self.assertFalse(any("页签" in lb for lb in labels), labels)

    def test_click_at_only_uses_reviewed_points(self):
        """★ **所有**按坐标点的步骤只能用"核对过的坐标"（遍历，别点名写死）。

        纯图标按钮没有文字、只能按坐标点 —— 猜错可能触发分解/弃置这类破坏性
        操作。所以把"允许的坐标"收成一张白名单，多出一个就红。
        """
        from src.tools.game.echo_enhance import prepare
        allowed = {
            prepare.FILTER_BTN_POINT,      # 底部漏斗（探测截图核对过）
            prepare.FILTER_CLOSE_POINT,    # 筛选面板右上角关闭
        }
        for step in self._steps(echo_set="雪落无声之愿"):
            if step.kind == "click_at":
                self.assertIn(step.point, allowed,
                              f"「{step.label}」用了没核对过的坐标 {step.point}")

    def test_press_b_verifies_we_landed_on_echo_page(self):
        """★ 「按 B」这步必须**验证**真的进了声骸页。

        它是唯一的导航步骤：万一游戏停在别的分类，后面点漏斗就全错位。
        验「声骸」在不在左上角，不在就报错停 —— 比继续瞎点强。
        """
        from src.tools.game.echo_enhance import prepare
        first = self._steps()[0]
        self.assertEqual(first.expect, prepare.ECHO_PAGE_TEXT)
        self.assertEqual(first.expect_region, prepare.ECHO_PAGE_REGION)

    def test_missing_loadout_hint_says_no_auto_filter(self):
        """★ 没挂筛选配置时，提示要说清**后果**（不会自动筛），别只说"请自己筛好"。"""
        src = (ROOT / "src/tools/game/echo_enhance/tool.py").read_text(
            encoding="utf-8")
        self.assertIn("不会自动筛选", src)

    def test_echo_set_step_is_marked_scrollable(self):
        """★ 「合鸣选套装」那步必须带 ``scroll=True``（2026-09-27 用户要求）。

        合鸣一共 **34 套**，那个下拉列表一屏只露 7 项左右。
        不滚着找的话，排在后面的套装永远找不到 —— 报「没找到文字」，
        可手动滚一下明明就有。
        """
        steps = self._steps(echo_set="雪落无声之愿")
        picker = next(s for s in steps if s.label.startswith("合鸣选"))
        self.assertTrue(picker.scroll, "没标 scroll → 不会滚着找")
        self.assertEqual(picker.text, "雪落无声之愿")

    def test_only_the_list_steps_scroll(self):
        """★ 别的步骤**不该**滚 —— 在"状态行"上滚滚轮是纯粹的破坏。"""
        for step in self._steps(echo_set="雪落无声之愿"):
            if step.scroll:
                self.assertIn("合鸣", step.label,
                              f"只有合鸣列表那步该滚，可「{step.label}」也标了")

    def test_open_echo_set_dropdown_waits_for_the_target_set(self):
        """★ 点完「合鸣」必须**验证目标套装已经出现在列表里**（2026-09-27）。

        实测那个下拉列表点完之后要 **6 秒以上**才把 7 项渲染全：
        失败那一刻抓到的区域里**只有第一项**，而失败之后几秒的探测里 7 项全在。

        所以这一步不能只靠"固定 sleep"，得挂上 ``expect``：
        等到目标套装真的出现（最多 FIND_TEXT_TIMEOUT 秒）再往下走。
        """
        steps = self._steps(echo_set="雪落无声之愿")
        opener = next(s for s in steps if "合鸣" in s.label and s.kind == "click_text"
                      and s.expect)
        self.assertEqual(opener.expect, "雪落无声之愿")
        from src.tools.game.echo_enhance import prepare
        self.assertEqual(opener.expect_region, prepare.ECHO_SET_LIST_REGION)

    def test_open_dropdown_and_pick_step_both_scroll(self):
        """★ 「打开合鸣下拉」和「合鸣选…」两步**都**要滚着找（2026-09-27）。

        这是补的一个真实缺陷：合鸣 34 套、一屏只露 7 项，
        用户换角色后目标「长路启航之星」排在列表下方。

        * 「合鸣选…」标了 scroll（上一轮加的）；
        * 但「打开合鸣下拉」的 ``expect`` 验证**没标** → 它用的查找不滚动
          → 8 秒等不到目标 → **直接报错，连会滚的那一步都走不到**。

        所以两步都得标。只标一个 = 前面那道门先把人拦在外面。
        """
        steps = self._steps(echo_set="长路启航之星")
        opener = next(s for s in steps if s.label.startswith("打开「合鸣」"))
        picker = next(s for s in steps if s.label.startswith("合鸣选"))
        self.assertTrue(opener.scroll, "「打开合鸣下拉」的验证没标 scroll → 会提前超时")
        self.assertTrue(picker.scroll, "「合鸣选套装」没标 scroll → 找不到后面的套装")
        self.assertEqual(opener.expect, "长路启航之星")

    # ---- 主音属性（4C/3C/1C 那个小窗）----
    def test_main_stat_filter_name_mapping(self):
        """★ 我们的主属性名 → 游戏里的说法（这几个词不一样，别用拼接糊过去）。"""
        from src.tools.game.echo_enhance.prepare import main_stat_filter_name as f
        self.assertEqual(f("暴击"), "主属性暴击率")
        self.assertEqual(f("暴击伤害"), "主属性暴击伤害")
        self.assertEqual(f("治疗加成"), "主属性治疗效果加成")
        self.assertEqual(f("攻击百分比"), "主属性攻击力百分比")
        self.assertEqual(f("防御百分比"), "主属性防御力百分比")
        self.assertEqual(f("生命百分比"), "主属性生命值百分比")
        # 没在表里的走前缀
        self.assertEqual(f("共鸣效率"), "主属性共鸣效率")
        self.assertEqual(f("冷凝伤害加成"), "主属性冷凝伤害加成")
        self.assertEqual(f(""), "")

    def test_main_stats_by_cost_uses_the_config(self):
        """每档要筛的主属性 = 该档声骸上勾的属性的并集。"""
        from src.core.loadout import EchoPick, Loadout
        item = Loadout(character="绯雪")
        item.set_picks(4, [EchoPick(echo="a", stats=("暴击伤害",))])
        item.set_picks(3, [EchoPick(echo="b", stats=("攻击百分比", "共鸣效率"))])
        item.set_picks(1, [EchoPick(echo="c", stats=("生命百分比",))])
        self.assertEqual(item.main_stats_by_cost(),
                         {4: ("暴击伤害",), 3: ("攻击百分比", "共鸣效率"),
                          1: ("生命百分比",)})

    def test_main_stat_steps_follow_the_config(self):
        """★ 4C/3C/1C 三个页签都要点到，每个属性都要按游戏里的说法去点。"""
        steps = self._steps(
            echo_set="雪落无声之愿",
            picks={4: [_pick("暴击伤害")],
                   3: [_pick("攻击百分比"), _pick("共鸣效率")],
                   1: [_pick("生命百分比")]})
        texts = [s.text for s in steps]
        for cost in (4, 3, 1):
            self.assertIn(f"Cost{cost}", texts, f"{cost}C 这一档没去点页签")
        for label in ("主属性暴击伤害", "主属性攻击力百分比",
                      "主属性共鸣效率", "主属性生命值百分比"):
            self.assertIn(label, texts, f"没去点「{label}」")

    def test_main_stat_modal_is_verified_both_ways(self):
        """小窗要验"开了"和"关了" —— 没开就报错，没关也报错。"""
        steps = self._steps(echo_set="雪落无声之愿",
                            picks={4: [_pick("暴击伤害")]})
        open_step = next(s for s in steps if s.text == "添加主属性筛选")
        self.assertEqual(open_step.expect, "主音属性筛选")
        self.assertFalse(open_step.expect_absent, "开的这步要验「出现」")
        close_step = next(s for s in steps if s.text == "确认")
        self.assertTrue(close_step.expect_absent, "确认这步要验小窗「消失」")

    def test_no_main_stat_steps_when_config_has_no_picks(self):
        """配置没选声骸 → 不该生成主音属性那一串（点了也没意义）。"""
        texts = [s.text for s in self._steps()]
        self.assertNotIn("添加主属性筛选", texts)

    def test_icon_clicks_have_verification(self):
        """★ 两个**没有文字、只能按坐标点**的图标，必须配"点完验证"。"""
        steps = self._steps()
        icon_steps = [s for s in steps if s.kind == "click_at"]
        self.assertGreaterEqual(len(icon_steps), 2, "至少要切页签 + 开筛选两个坐标点击")
        for step in icon_steps:
            self.assertTrue(step.expect, f"「{step.label}」没配点完验证")
            self.assertTrue(step.expect_region, f"「{step.label}」没配验证区域")


class TestClickAtAndVerify(unittest.TestCase):
    """按坐标点 + 点完验证的运行时行为（假窗口 + 假 OCR）。"""

    def _prep(self, steps, reader_lines=()):
        from src.tools.game.echo_enhance.prepare import EchoPrep
        window = FakeWindow()
        prep = EchoPrep(window=window, reader=FakeReader(list(reader_lines)),
                        log=lambda _m: None)
        prep.steps = steps
        with tempfile.TemporaryDirectory() as tmp:
            prep.probe_dir = pathlib.Path(tmp)
            return prep, window

    def _click_at_step(self, expect="", expect_region=(0.0, 0.0, 1.0, 1.0)):
        from src.tools.game.echo_enhance.prepare import PrepAction
        return PrepAction("click_at", "点个图标", point=(0.25, 0.75), verified=True,
                          wait=0.0, expect=expect, expect_region=expect_region)

    def test_clicks_the_point(self):
        prep, window = self._prep([self._click_at_step()])
        prep.run()
        self.assertEqual(window.clicks, [(0.25, 0.75)], "要按相对坐标点那个位置")

    def test_verify_passes_when_text_found(self):
        prep, window = self._prep([self._click_at_step(expect="品质")],
                                  [line("品质", 100, 100)])
        prep.run()
        self.assertEqual(len(window.clicks), 1)

    def test_verify_fails_loudly_when_text_missing(self):
        """★ 点完验证没看到预期文字 → **报错停下**，不能"以为点上了"继续往下。"""
        prep, _window = self._prep([self._click_at_step(expect="品质")], [])
        with self.assertRaises(RuntimeError) as ctx:
            prep.run()
        message = str(ctx.exception)
        self.assertIn("品质", message)
        self.assertIn("没看到", message)
        # ★ 报错要带"当时那个区域里看到了什么" —— 否则分不清是坐标不对还是画面不对
        self.assertIn("OCR", message)
        # ★ 也要带步号，用户好对数
        self.assertIn("第 1/1 步", message)

    def test_failure_dump_leaves_the_scene(self):
        """★ 失败时**自动把现场存下来**（2026-09-27）。

        以前报错只有一句「没看到「品质」」，用户手上没别的，我这边只能回头追问
        "能不能截个图"，一个坐标来回好几轮 —— 而那次真因就是 `FILTER_BTN_POINT`
        的 y 偏了 0.09（点到图标下方的空白处了），**一张"点完之后"的截图一眼就能看出来**。
        """
        prep, _window = self._prep([self._click_at_step(expect="品质")], [])
        with self.assertRaises(RuntimeError) as ctx:
            prep.run()
        message = str(ctx.exception)
        # 说清"我是在哪找的" —— 坐标 or 区域，至少得有一个
        self.assertTrue("我点的坐标" in message or "区域里找" in message, message)
        # 现场已存，并给出路径
        self.assertIn("失败现场已存", message)
        self.assertTrue(list(pathlib.Path(prep.probe_dir).glob("probe-*.txt")),
                        "说了已存，但产物没落盘")

    def test_absent_verification(self):
        """``expect_absent=True``：要求文字**消失**（"关掉筛选面板"那步靠它验）。"""
        from src.tools.game.echo_enhance.prepare import PrepAction
        step = PrepAction("click_at", "关掉面板", point=(0.5, 0.5), verified=True,
                          wait=0.0, expect="品质", expect_region=(0.0, 0.0, 1.0, 1.0),
                          expect_absent=True)
        # 画面上「品质」还在 → 说明没关掉，应当报错
        prep, _w = self._prep([step], [line("品质", 100, 100)])
        with self.assertRaises(RuntimeError) as ctx:
            prep.run()
        self.assertIn("仍然看得到", str(ctx.exception))
        # 画面上没有 → 通过
        prep2, window2 = self._prep([step], [])
        prep2.run()
        self.assertEqual(len(window2.clicks), 1)

    def test_unknown_kind_raises(self):
        from src.tools.game.echo_enhance.prepare import PrepAction
        prep, _window = self._prep([PrepAction("乱写的", "x", verified=True)])
        with self.assertRaises(ValueError):
            prep.run()



class TestResolutionWarning(unittest.TestCase):
    """画面比例/尺寸检查（2026-09-27 用户问"换台电脑分辨率不一样还能跑吗"）。

    下面所有区域都是**相对坐标（0~1）**，所以：

    * **同比例的尺寸变化**（1080p → 1440p / 720p）→ 位置比例不变，**照样准**；
    * **比例变了**（16:10 / 21:9 / 4:3）→ 面板相对位置**整体错位**，而且
      **不会报错** —— 那才是最难查的。

    所以宁可先把比例卡住、停下说清楚，也不要拿错位坐标去点游戏。
    """

    def _warn(self, w, h):
        from src.tools.game.echo_enhance.prepare import resolution_warning
        return resolution_warning(w, h)

    def test_16_9_sizes_pass(self):
        """ok-ww 支持的那几档 + 常见 16:9，都该放行。"""
        for w, h in ((1280, 720), (1600, 900), (1920, 1080), (2560, 1440), (3840, 2160)):
            self.assertIsNone(self._warn(w, h), f"{w}x{h} 是 16:9，不该拦")

    def test_other_aspects_warn(self):
        """16:10 / 21:9 / 5:4 一律拦下 —— 相对坐标在这几种下会整体错位。

        ⚠ 这里只挑**尺寸够大**的：太小的会先撞上"太小"那条（那也是对的，
        只是测不到本意）。
        """
        for w, h in ((1920, 1200), (2560, 1080), (3440, 1440), (1280, 1024)):
            msg = self._warn(w, h)
            self.assertIsNotNone(msg, f"{w}x{h} 不是 16:9，该拦")
            self.assertIn(f"{w}:{h}", str(msg))

    def test_too_small_warns(self):
        """16:9 但太小（ok-ww 自己要求 >=1280x720）。"""
        self.assertIsNotNone(self._warn(1024, 576))
        # 4:3 且太小 → 先报"太小"（先卡尺寸再卡比例，顺序无所谓，别漏就行）
        self.assertIsNotNone(self._warn(1024, 768))

    def test_zero_size_warns(self):
        """窗口最小化时读到 0 —— **不许当成通过**。"""
        self.assertIsNotNone(self._warn(0, 0))
        self.assertIsNotNone(self._warn(0, 1080))

    def test_message_tells_user_what_to_do(self):
        """报错要说清"为什么"和"怎么办"，不能只说"比例不对"。"""
        msg = str(self._warn(1920, 1200))
        self.assertIn("16:9", msg)
        self.assertIn("错位", msg)
        self.assertIn("1920x1080", msg)      # 给出可用的档位


class TestScrollToFindInList(unittest.TestCase):
    """「列表比一屏长」时**滚着找**（2026-09-27 用户要求）。

    合鸣一共 **34 套**，那个下拉列表一屏只露 7 项左右。用户换角色后
    目标套装「长路启航之星」排在列表下方 —— 不滚就永远找不到。
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.probe_dir = pathlib.Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _prep(self, window, lines):
        from src.tools.game.echo_enhance import prepare
        return prepare.EchoPrep(window=window, reader=FakeReader(lines),
                                probe_dir=self.probe_dir)

    def test_scrolls_and_stops_when_list_stops_changing(self):
        """★ 内容不变 ⇒ 说明滚到底了，别再空转。

        假 OCR 每次都给同一行 → 第 1 轮找不到就滚一次，第 2 轮发现
        内容没变，**立刻停**（不会傻滚满 MAX_LIST_SCROLLS 次）。
        """
        from src.tools.game.echo_enhance import prepare
        window = FakeWindow()
        prep = self._prep(window, [line("冥途夜行之灯", 10, 10)])
        old = prepare.LIST_FIND_TIMEOUT
        prepare.LIST_FIND_TIMEOUT = 0.05          # 别让测试真等
        try:
            found = prep._find_text_in_list(window, (0.62, 0.44, 1.00, 0.94), "目标套装")
        finally:
            prepare.LIST_FIND_TIMEOUT = old
        self.assertIsNone(found)
        # _scroll_list 一次会滚两下（给游戏逐帧处理的机会）
        self.assertEqual(len(window.scrolls), 2, "该滚一次就停，实际滚了 %d 下" % len(window.scrolls))
        self.assertEqual(len(window.moved), 1, "滚之前必须先把光标挪到列表上")

    def test_cursor_is_moved_onto_the_list_before_scrolling(self):
        """★ 滚轮只作用于**光标底下**的控件 —— 不挪光标就会滚错地方。"""
        from src.tools.game.echo_enhance import prepare
        window = FakeWindow()
        prep = self._prep(window, [line("别的", 10, 10)])
        old = prepare.LIST_FIND_TIMEOUT
        prepare.LIST_FIND_TIMEOUT = 0.05
        try:
            prep._find_text_in_list(window, (0.60, 0.40, 1.00, 0.90), "目标")
        finally:
            prepare.LIST_FIND_TIMEOUT = old
        self.assertTrue(window.moved, "没挪光标就滚了")
        mx, my = window.moved[0]
        self.assertTrue(0.60 <= mx <= 1.00 and 0.40 <= my <= 0.90,
                        f"光标落在 {mx:.2f},{my:.2f}，不在列表区域里")
        self.assertTrue(all(c < 0 for c in window.scrolls), "该往下滚（负数）")

    def test_finds_the_target_if_it_shows_up(self):
        """★ 目标真出现了就得找到（别一直在滚）。"""
        from src.tools.game.echo_enhance import prepare
        window = FakeWindow()
        prep = self._prep(window, [line("目标套装", 10, 10)])
        old = prepare.LIST_FIND_TIMEOUT
        prepare.LIST_FIND_TIMEOUT = 0.5
        try:
            found = prep._find_text_in_list(window, (0.62, 0.44, 1.00, 0.94), "目标套装")
        finally:
            prepare.LIST_FIND_TIMEOUT = old
        self.assertIsNotNone(found, "目标明明在第一屏却没找到")
        self.assertEqual(window.scrolls, [], "第一屏就有，不该滚")


class TestVerifyAlsoScrolls(unittest.TestCase):
    """★ 「点完验证」也要滚着找（2026-09-27 补的真实缺陷）。

     原来一律调不滚动的 ，于是「打开合鸣下拉」那步的
     在目标排在列表后面时 8 秒超时直接报错 ——
    **连会滚的「合鸣选…」都走不到**。用户换角色后目标
    「长路启航之星」正好在列表下方，就是这么卡住的。

    这条**直接盯  走哪条分支**（上面那组测的是
     本身，改坏  它们不会红）。
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.probe_dir = pathlib.Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _prep(self):
        from src.tools.game.echo_enhance import prepare
        return prepare.EchoPrep(window=FakeWindow(), reader=FakeReader([]),
                                probe_dir=self.probe_dir)

    def test_verify_uses_scrolling_find_when_step_says_scroll(self):
        from src.tools.game.echo_enhance.prepare import PrepAction
        prep = self._prep()
        step = PrepAction("click_text", "打开「合鸣」下拉", region=(0.63, 0.38, 1.0, 0.46),
                          text="合鸣", verified=True,
                          expect="目标套装", expect_region=(0.62, 0.44, 1.0, 0.94),
                          scroll=True)
        calls = []
        prep._find_text_in_list = lambda *a, **k: (calls.append("scroll"), None)[1]
        prep._find_text = lambda *a, **k: (calls.append("plain"), None)[1]
        self.assertFalse(prep._verify(prep.window, step))
        self.assertEqual(calls, ["scroll"], "scroll=True 的步骤必须走滚着找")

    def test_verify_does_not_scroll_when_step_does_not(self):
        from src.tools.game.echo_enhance.prepare import PrepAction
        prep = self._prep()
        step = PrepAction("click_text", "打开「筛选」面板", region=(0.62, 0.10, 1.0, 0.75),
                          text="筛选", verified=True,
                          expect="品质", expect_region=(0.62, 0.10, 1.0, 0.75))
        calls = []
        prep._find_text_in_list = lambda *a, **k: (calls.append("scroll"), None)[1]
        prep._find_text = lambda *a, **k: (calls.append("plain"), None)[1]
        self.assertFalse(prep._verify(prep.window, step))
        self.assertEqual(calls, ["plain"], "没标 scroll 的步骤不该滚")

    def test_verify_true_when_no_expect(self):
        """没配 expect 的步骤直接算通过（别去 OCR 白花时间）。"""
        from src.tools.game.echo_enhance.prepare import PrepAction
        prep = self._prep()
        self.assertTrue(prep._verify(prep.window, PrepAction("press", "按 B", key="b")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
