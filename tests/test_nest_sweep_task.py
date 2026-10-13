# -*- coding: utf-8 -*-
"""ok-ww 接线 + 名称匹配（``src/tools/game/nest_sweep/okww_task.py``）。

## 这个测试在保什么

两件在最坏情况下会**静默出错**的事：

1. **名称匹配** —— 匹配错了会去刷**另一个目标**，而界面上完全看不出来
   （用户勾了 A，机器刷了 B）。保三条：长的优先、两种"象/像"都认、太短不反向。
2. **接线** —— 漏写注册表时界面显示"找不到任务"但**不报错**。
   本项目在声骸调频那边就是漏了这一步（见 README「接线」）。

## ⚠ 这个测试**不导入 Qt**

``okww_task`` 运行时才 import ok-ww（PEP 562 懒构造），所以纯函数部分
在没装 ok-ww、没有 Qt 的环境里也能测 —— 那正是它这么设计的原因。
"""

from __future__ import annotations

import ast
import importlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.tools.game.nest_sweep import okww_task  # noqa: E402


class TestNormalize(unittest.TestCase):
    """比较用归一化 —— 把 OCR 的花样压平。"""

    def test_drops_punctuation_and_space(self):
        """``·`` / 空格 / 全角空格全都去掉，只留实义字符。"""
        self.assertEqual(okww_task._normalize("梦魇·无冠者"), "梦魇无冠者")
        self.assertEqual(okww_task._normalize("梦魇 无冠者"), "梦魇无冠者")
        self.assertEqual(okww_task._normalize("梦魇　无冠者"), "梦魇无冠者")
        self.assertEqual(okww_task._normalize("梦魇.无冠者"), "梦魇无冠者")

    def test_keeps_digits_and_latin(self):
        """数字和字母要留着（``0/24`` 那种计数、``COST`` 这类词）。"""
        self.assertEqual(okww_task._normalize("0/24"), "024")
        self.assertEqual(okww_task._normalize("COST 4"), "COST4")

    def test_empty(self):
        for empty in ("", None, "   ", "···"):
            self.assertEqual(okww_task._normalize(empty), "")


class TestNameHit(unittest.TestCase):
    """★ 三层定位的第一层：名称匹配。"""

    def test_exact_containment(self):
        """行文字里含候选名 —— 常态（行里还有数量和状态词）。"""
        got = okww_task._name_hit("落渊南丘残像聚落 0/24 前往",
                                  ["落渊南丘残像聚落"])
        self.assertEqual(got, "落渊南丘残像聚落")

    def test_longest_wins_even_when_input_is_unsorted(self):
        """★★ 长的必须先命中，**即使候选没排序**。

        实测过这个 bug：候选按 ``['梦魇·刺玫菇', '梦魇·刺玫菇（稚形）']``
        传进来时，短名是长名的子串 → 先命中短名 →
        **勾了稚形却去刷了普通那个**，而且界面上看不出来。

        ``match_names()`` 确实已经排过序，但这条钉住的是
        "``_name_hit`` 自己不依赖调用方"。
        """
        unsorted = ["梦魇·刺玫菇", "梦魇·刺玫菇（稚形）"]
        self.assertEqual(okww_task._name_hit("梦魇·刺玫菇（稚形） 0/36", unsorted),
                         "梦魇·刺玫菇（稚形）")
        #: 反过来：普通那一行**不该**被判成稚形
        self.assertEqual(okww_task._name_hit("梦魇·刺玫菇 0/36", unsorted),
                         "梦魇·刺玫菇")

    def test_both_xiang_spellings(self):
        """★ 官方写「残**象**聚落」，用户/ok-ww 写「残**像**聚落」。

        两种写法都必须命中 —— 一个字之差会让任务在指南里找不到那一行。
        """
        candidates = ["残像聚落·拉海洛", "残象聚落·拉海洛"]
        self.assertTrue(okww_task._name_hit("残象聚落·拉海洛 0/48", candidates))
        self.assertTrue(okww_task._name_hit("残像聚落·拉海洛 0/48", candidates))

    def test_reverse_match_when_ocr_reads_half(self):
        """OCR 只读到半截时，反向匹配也要能认出来。"""
        self.assertEqual(okww_task._name_hit("落渊南丘", ["落渊南丘残像聚落"]),
                         "落渊南丘残像聚落")

    def test_reverse_match_needs_min_length(self):
        """★ 太短的不许反向匹配。

        行文字只有两个字时，"它是我要找的那行的前缀"纯属巧合 ——
        放行会让**随便一行短文字都命中**，那就等于没匹配。
        """
        self.assertEqual(okww_task._name_hit("落渊", ["落渊南丘残像聚落"]), "")
        self.assertLess(len("落渊"), okww_task._MIN_REVERSE)

    def test_aliases_tried_in_order(self):
        """本名认不出来时，别名要能兜住。"""
        got = okww_task._name_hit("拉海洛 0/48", ["残像聚落·拉海洛", "拉海洛"])
        self.assertEqual(got, "拉海洛")

    def test_no_match(self):
        for row in ("完全不相干的字", "", "0/24"):
            self.assertEqual(okww_task._name_hit(row, ["落渊南丘残像聚落"]), "")

    def test_empty_candidates(self):
        self.assertEqual(okww_task._name_hit("随便什么", []), "")
        self.assertEqual(okww_task._name_hit("随便什么", None), "")

    def test_real_catalog_names_all_matchable(self):
        """★ 走**真实清单**：每个目标的每个匹配名都要能被自己命中。

        这条能抓住"别名里写了错字"这类问题 —— 那种错在界面上看不出来，
        只有任务真跑起来才会表现为"找不到那一行"。
        """
        from src.core.nest_sweep import load_catalog

        for target in load_catalog():
            for name in target.match_names():
                got = okww_task._name_hit(name, target.match_names())
                self.assertTrue(got, "%s 的名字「%s」匹配不上自己" % (target.key, name))


class TestTaskClassLazy(unittest.TestCase):
    """★ 任务类的**懒构造**（PEP 562）。"""

    def test_import_does_not_touch_okww(self):
        """import 本模块**不该**把 ok-ww 拉进来（那会让没装 ok-ww 的环境整个失败）。

        ``registry.discover()`` 会 import 工具包下所有模块 ——
        如果本模块在 import 时就要 ok-ww，没装 ok-ww 的环境
        **一个工具都发现不了**（而不是少了这一个）。

        ## ⚠⚠ 这条测试原来**依赖测试顺序**（2026-10-13 修）

        原写法是直接断言进程级状态::

            importlib.reload(okww_task)
            self.assertNotIn("okww", sys.modules, ...)

        ``sys.modules`` 是**进程级**的，而这条测试**自己不清理**。
        于是只要同一次运行里**别的**测试先 import 过 ok-ww
        （``test_okww_vendor`` 或那个"真起引擎"的验收就会），
        它就**必挂** —— 单独跑过、全量跑挂。

        实测复现：先在进程里 ``import okww`` 再跑这条 → 挂。

        ## 改成怎么测

        不该看"进程里有没有 okww"（那被别人污染），
        而该看**本模块自己做了什么**：重新加载之后，
        确认 ``okww_task`` 的懒构造**没有被触发**
        （即任务类属性还没被求值），
        并且模块里**没有**对 ok-ww 的**顶层 import**。
        """
        #: ① 静态判据：模块顶层不该有 import okww（AST 判，最可靠）
        src = Path(okww_task.__file__).read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in tree.body:                      #: 只看**模块顶层**
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
                self.assertNotIn(
                    "okww", [n.split(".")[0] for n in names],
                    "okww_task 顶层 import 了 ok-ww —— 没装 ok-ww 的环境会整个失败")
            elif isinstance(node, ast.ImportFrom):
                mod = (node.module or "").split(".")[0]
                self.assertNotEqual(
                    mod, "okww",
                    "okww_task 顶层 from okww import ... —— 同上")

        #: ② 动态判据：重新加载后，懒构造**没被触发**
        #:    （``__getattr__`` 命中后会把类缓存进 ``globals()[TASK_CLASS_NAME]``，
        #:     所以"没被触发"= 模块命名空间里没有那个类名）
        importlib.reload(okww_task)
        cached = getattr(okww_task, "TASK_CLASS_NAME", None)
        self.assertTrue(cached, "模块里没有 TASK_CLASS_NAME 常量")
        self.assertNotIn(
            cached, vars(okww_task),
            f"import 之后 {cached} 就被构造了 —— 懒构造失效")

        #: ③ 真去取一次任务类，这时才该碰 ok-ww
        #:    ⚠ 只有装了 ok-ww 才测得到（没装时 __getattr__ 会抛，那也算对）
        try:
            cls = okww_task.MyToolsNestSweepTask
        except Exception:                           # noqa: BLE001
            return                                  #: 没装 ok-ww → 抛是预期行为
        self.assertIsNotNone(cls)

    def test_unknown_attribute_raises(self):
        """只认任务类名，别的属性照常抛 AttributeError。"""
        with self.assertRaises(AttributeError):
            _ = okww_task.压根不存在的属性  # noqa: B018

    def test_task_class_name_constant(self):
        """★ 这个常量必须和注册表里的类名**逐字一致**。"""
        from src.tools.game.auto_combat.okww_boot import TASKS

        self.assertEqual(okww_task.TASK_CLASS_NAME, "MyToolsNestSweepTask")
        self.assertEqual(TASKS["扫荡残像聚落"], okww_task.TASK_CLASS_NAME)

    def test_language_gate_cleared_in_source(self):
        """★★ ``supported_languages = []`` 必须写在类体里。

        ## 为什么不直接 ``build_task_class()`` 看属性

        那会把 ok-ww → ok-script → **Qt** 整条链拉进来。本仓的单测
        刻意不这么干（无头环境里 Qt 起不来，见 README 的 ``QT_QPA_PLATFORM``
        那段）—— 真引擎里验这件事的是 ``check_okww_registration.py``。

        所以这里用 **AST 静态检查**：类体里必须有 ``supported_languages = []``。
        这条拦的是本项目**踩过三次**的坑：宿主 headless → ``app.locale`` 是
        ``en_US`` → ok-script 的 ``init_tasks()`` **静默不注册**声明了
        ``["zh_CN"]`` 的任务 → 界面上一切正常、点启动却"找不到任务"。
        """
        source = Path(okww_task.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)

        cleared: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for stmt in node.body:
                if not isinstance(stmt, ast.Assign):
                    continue
                targets = [t.id for t in stmt.targets if isinstance(t, ast.Name)]
                if "supported_languages" not in targets:
                    continue
                #: 必须是空列表 —— ``["zh_CN"]`` 那种会被静默跳过
                if isinstance(stmt.value, ast.List) and not stmt.value.elts:
                    cleared.append(node.name)

        self.assertIn("MyToolsNestSweepTask", cleared,
                      "任务类里没有写 supported_languages = []，"
                      "宿主 headless 环境下这个任务会被 ok-script 静默跳过")


class TestTabMapping(unittest.TestCase):
    """分类 → 指南页签的映射。"""

    def test_both_kinds_mapped(self):
        from src.core.nest_sweep import KIND_NEST, KIND_NIGHTMARE

        self.assertIn(KIND_NEST, okww_task.TAB_OF_KIND)
        self.assertIn(KIND_NIGHTMARE, okww_task.TAB_OF_KIND)

    def test_matches_okww_boss_book_names(self):
        """页签代号要和 ok-ww ``open_boss_book`` 认识的一致。

        ⚠ 写错不会报错 —— ``open_boss_book`` 会走到 ``else`` 分支
        抛 ``unknown_lang``，或者更糟：点到别的页签上。
        """
        #: ok-ww 认的代号（见 BaseWWTask.open_boss_book）
        known = {"ningsu", "moni", "qiangdi", "wuyin", "zhange", "canxiang", "mengyan"}
        for tab in okww_task.TAB_OF_KIND.values():
            self.assertIn(tab, known, "ok-ww 不认识页签代号 %s" % tab)


class TestCountRegex(unittest.TestCase):
    """``0/24`` 计数器的正则。"""

    def test_matches_guide_counter(self):
        for text, expect in (("0/24", ("0", "24")), ("0/48", ("0", "48")),
                             ("0 / 36", ("0", "36")), ("0/41", ("0", "41")),
                             ("24/24", ("24", "24"))):
            match = okww_task.COUNT_RE.search(text)
            self.assertIsNotNone(match, text)
            self.assertEqual(match.groups(), expect)

    def test_does_not_match_other_numbers(self):
        """不该把别处的数字当成计数器。"""
        self.assertIsNone(okww_task.COUNT_RE.search("前往"))
        self.assertIsNone(okww_task.COUNT_RE.search("123456"))


class TestKnownDailyCaps(unittest.TestCase):
    """每日数量 —— 数据文件里的 count 要落在已知的几种上限里。

    已知上限（官方公告 + 日站交叉验证）：普通聚落 24 / 困难聚落 48 /
    梦魇聚落 36 / 另有一处 41。写错不会报错，只会让"今天刷完了吗"
    这个佐证失效 —— 所以钉一条。
    """

    KNOWN = {24, 36, 41, 48}

    def test_counts_are_known_values(self):
        from src.core.nest_sweep import KIND_NIGHTMARE, load_catalog

        for target in load_catalog():
            if not target.count:
                continue
            self.assertIn(target.count, self.KNOWN,
                          "%s 的数量 %d 不在已知上限里" % (target.name, target.count))

    def test_nightmares_are_36(self):
        """梦魇聚落的每日上限是 **36**（日站实测），不是 24/48。

        ⚠ 这两类的上限**不一样** —— 把 36 当成聚落的上限会让
        "今天刷完了吗"判断整个错位。
        """
        from src.core.nest_sweep import KIND_NIGHTMARE, load_catalog

        for target in load_catalog():
            if target.kind == KIND_NIGHTMARE and target.count:
                self.assertEqual(target.count, 36, target.name)


if __name__ == "__main__":
    unittest.main()
