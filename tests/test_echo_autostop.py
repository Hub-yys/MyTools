# -*- coding: utf-8 -*-
"""「出现符合条件的声骸 → 自动停止 + 通知 + 结果卡片」的单元测试。

用户 2026-10-10 的要求::

    "声骸自动强化增加出现符合条件声骸自动停止
     （**不包括出现满爆击/满暴伤，但是词条数不符合的**），并通知，
     同意做成启用/不启用，另外结果报告符合条件的要完整展示声骸图，
     以卡片形式展示"

## ⚠⚠ 本文件里最重要的是「排除项」那几条

``judge`` 的「满值保护」是**最高优先且会短路** —— 出了满暴击/满爆伤就直接
返回 ``lock``，**双爆下限 / 核心属性 / 有效词条数根本没跑**。所以::

    上锁了  ≠  符合条件

一个"满暴击但有效词条只有 1 条"的声骸照样会被上锁（那是有意的保护），
但它**不该**触发自动停止。这条测试就是把那个区分钉死。

    .\\.venv\\Scripts\\python.exe tests\\test_echo_autostop.py
"""

from __future__ import annotations

import pathlib
import sys
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.tools.game.echo_enhance import okww_task as OT  # noqa: E402
from src.tools.game.echo_enhance import stats as S  # noqa: E402
from src.tools.game.echo_enhance.settings import EchoSettings  # noqa: E402


def st(*pairs) -> list:
    return [S.EchoStat(n, v) for n, v in pairs]


#: 核心 = 双爆 + 攻击，下限 3 —— 这样「有效词条数」才**真的**卡得住
#: （只勾双爆时 effective_min_valid_count 会被夹到 2，"有效 2 条"反而是达标的，
#:   那样测"词条数不够"就是白测。这个坑我踩过一次。）
CFG = S.JudgeConfig(
    core_stats=frozenset({S.CRIT, S.CRIT_DMG, "攻击"}),
    optional_stats=frozenset(),
    min_valid_count=3,
)

#: 满暴击，但有效词条只有 2 条（双爆）
PERFECT_BUT_SHORT = st(("暴击", S.MAX_CRIT), ("暴击伤害", 15.0), ("防御", 70),
                       ("防御百分比", 6.4), ("生命", 430))
#: 普通达标（无满值），有效 3 条
GOOD = st(("暴击", 9.9), ("暴击伤害", 15.0), ("攻击", 30),
          ("防御", 70), ("生命", 430))
#: 满暴击 **且** 有效 3 条
GOOD_PERFECT = st(("暴击", S.MAX_CRIT), ("暴击伤害", 15.0), ("攻击", 30),
                  ("防御", 70), ("生命", 430))


class TestQualifies(unittest.TestCase):
    """★ :func:`stats.qualifies` 的语义。"""

    def test_plain_good_qualifies(self):
        self.assertTrue(S.qualifies(GOOD, CFG))

    def test_perfect_and_enough_qualifies(self):
        self.assertTrue(S.qualifies(GOOD_PERFECT, CFG))

    def test_perfect_but_too_few_valid_does_not_qualify(self):
        """★★★ 用户明确要求排除的那一类。

        满暴击 → ``judge`` 会 ``lock``（满值保护，有意的），但有效词条数不够
        → **不算符合条件**，不该触发自动停止。
        """
        result = S.judge(PERFECT_BUT_SHORT, CFG)
        self.assertEqual(result.action, "lock",
                         "前提：满值保护确实把它上锁了")
        self.assertEqual(result.code, "max_roll",
                         "前提：走的是满值保护那条短路规则")
        self.assertFalse(
            S.qualifies(PERFECT_BUT_SHORT, CFG),
            "满值但词条数不够的声骸被当成「符合条件」了 —— "
            "用户明确要求排除这一类")

    def test_perfect_crit_dmg_but_too_few_valid_does_not_qualify(self):
        """★ 满爆伤（另一半）同样要排除。"""
        items = st(("暴击伤害", S.MAX_CRIT_DMG), ("暴击", 7.5), ("防御", 70),
                   ("防御百分比", 6.4), ("生命", 430))
        self.assertEqual(S.judge(items, CFG).action, "lock")
        self.assertFalse(S.qualifies(items, CFG))

    def test_perfect_but_crit_dmg_below_min_does_not_qualify(self):
        """★ 满暴击、但爆伤低于下限 → 也不算（满值保护压过了下限检查）。"""
        items = st(("暴击", S.MAX_CRIT), ("暴击伤害", 13.8), ("攻击", 30),
                   ("防御", 70), ("生命", 430))
        self.assertFalse(S.qualifies(items, CFG))

    def test_missing_core_does_not_qualify(self):
        """★ 核心属性凑不齐（双爆有、缺攻击，且没孔了）→ 不算。"""
        items = st(("暴击", 9.9), ("暴击伤害", 15.0), ("防御", 70),
                   ("防御百分比", 6.4), ("生命", 430))
        self.assertFalse(S.qualifies(items, CFG))

    def test_not_full_is_not_conclusive(self):
        """⚠ 没读满 5 条时 ``qualifies`` 只表示"还没被淘汰"，**不能**拿去触发停止。

        这条钉的是调用方的约束（``_remember_judgement`` 里 ``full`` 那个参数）——
        满暴击单独出现时还剩 4 孔，完全可能凑齐。
        """
        self.assertTrue(S.qualifies(st(("暴击", S.MAX_CRIT)), CFG),
                        "只剩 1 条时应该是「还有希望」（真实调用点靠 full 把关）")

    def test_dead_early_does_not_qualify(self):
        """★ 中途就废了（暴击低于下限）→ 立刻为 False。"""
        self.assertFalse(S.qualifies(st(("暴击", 6.3)), CFG))

    def test_independent_of_max_roll_lock_switch(self):
        """★ 关掉满值保护不该改变 ``qualifies`` 的结论。

        （它在实现上是"临时关掉再判一次"，所以这条同时证明了那个做法没副作用。）
        """
        import dataclasses

        off = dataclasses.replace(CFG, enable_max_roll_lock=False)
        for items in (GOOD, GOOD_PERFECT, PERFECT_BUT_SHORT):
            with self.subTest(items=[str(s) for s in items]):
                self.assertEqual(S.qualifies(items, CFG),
                                 S.qualifies(items, off))


class TestSettingsFlag(unittest.TestCase):
    """★ 启用/不启用 这个开关要能存盘、能往返。"""

    def test_default_is_on(self):
        """用户主动要的功能 —— 默认开着，不想要的人自己关。"""
        self.assertTrue(EchoSettings().enable_auto_stop)

    def test_roundtrip(self):
        for want in (True, False):
            with self.subTest(want=want):
                s = EchoSettings(enable_auto_stop=want)
                self.assertEqual(EchoSettings.from_dict(s.to_dict()).enable_auto_stop,
                                 want)

    def test_missing_key_falls_back_to_default(self):
        """★ 老配置文件（没这个键）不能崩，落回默认。"""
        raw = EchoSettings().to_dict()
        raw.pop("enable_auto_stop")
        self.assertTrue(EchoSettings.from_dict(raw).enable_auto_stop)

    def test_garbage_value_falls_back_to_default(self):
        raw = EchoSettings().to_dict()
        raw["enable_auto_stop"] = "yes please"
        self.assertTrue(EchoSettings.from_dict(raw).enable_auto_stop,
                        "非布尔值应该落回默认，而不是当成 True 硬转")

    def test_flows_into_judge_config(self):
        """★★ 开关必须流到 ``JudgeConfig`` —— 任务只被注入这一个对象。

        流不过去的话，界面上关了也照样停（``task.judge_config`` 里是默认值）。
        """
        self.assertFalse(
            EchoSettings(enable_auto_stop=False).to_judge_config().enable_auto_stop)
        self.assertTrue(
            EchoSettings(enable_auto_stop=True).to_judge_config().enable_auto_stop)

    def test_judge_config_roundtrip(self):
        cfg = EchoSettings(enable_auto_stop=False).to_judge_config()
        self.assertFalse(EchoSettings.from_judge_config(cfg).enable_auto_stop)

    def test_describe_mentions_it(self):
        """日志里要能看出这次到底开没开（否则排查时无从判断）。"""
        self.assertIn("自动停", EchoSettings(enable_auto_stop=True).describe())
        self.assertIn("关", EchoSettings(enable_auto_stop=False).describe())


def _init_fake_state(t, *, enable_auto_stop: bool = True):
    """给``t`` 装上"自动停止链路"用到的全部字段 + 假依赖。

    抽出来是为了让 :func:`_fake_task`（``SimpleNamespace`` 版）和
    "真类实例"版（``__new__`` 绕过 ``__init__`` 那种）**共用同一套字段**，
    免得两处各写一份、改一处漏一处。
    """
    t.info = {}
    t.judge_config = S.JudgeConfig(
        core_stats=frozenset({S.CRIT, S.CRIT_DMG, "攻击"}),
        min_valid_count=3, enable_auto_stop=enable_auto_stop)
    t.qualifying_echoes = []
    t.auto_stop_count = 0
    t._qualifying_now = False
    t._perfect_seen = False
    t._last_present = []
    t.perfect_echoes = 0
    t.logs = []
    #: ⚠ 叫 ``pause_count`` 不叫 ``paused`` —— 后者是 ok-ww ``BaseTask`` 上的
    #: **只读 property**，在真实例上赋值会 ``AttributeError``（踩过一次）
    t.pause_count = 0

    def _pause():
        t.pause_count += 1

    t.info_set = lambda k, v: t.info.__setitem__(k, v)
    t.info_get = lambda k, d=None: t.info.get(k, d)
    t.log_info = lambda msg, **kw: t.logs.append(msg)
    t.log_error = lambda msg, **kw: t.logs.append("ERR " + msg)
    t.log_debug = lambda msg, **kw: None
    t.pause = _pause
    t._find_echo_screenshot = lambda: "x.png"
    return t


def _fake_task(*, enable_auto_stop: bool = True):
    """造一个只带"自动停止链路"所需字段的假任务。

    ⚠ 不实例化 ``MyToolsEnhanceEchoTask``：那会拉起 ok-ww 的整条依赖
    （executor / config / OCR 模型），单测里既慢又脆。
    用 ``SimpleNamespace`` + 手动绑方法就够了 —— 被测的就是那几个方法本身。

    ⚠ 但**要测 ``lock_and_esc`` 那种内部用零参 ``super()`` 的方法**时，
    必须用 ``__new__`` 造真实例 —— 见
    :meth:`TestAutoStopChain.test_lock_and_esc_wires_the_verdict_through`。
    """
    t = types.SimpleNamespace()
    _init_fake_state(t, enable_auto_stop=enable_auto_stop)
    for name in ("_remember_judgement", "_record_qualifying",
                 "_finalize_echo", "_auto_stop_if_needed"):
        setattr(t, name, types.MethodType(
            getattr(OT.MyToolsEnhanceEchoTask, name), t))
    return t


def _feed(t, items, *, full=True):
    t._last_present = list(items)
    t._remember_judgement(list(items), full=full)


class TestAutoStopChain(unittest.TestCase):
    """★★★ 自动停止链路（``_finalize_echo`` → ``_auto_stop_if_needed``）。

    ⚠ 这里**显式传参**而不是让 ``_auto_stop_if_needed`` 自己读
    ``_qualifying_now``：我第一版就是"结算时清零、随后再去读"——
    那个字段永远是 False，**自动停止彻底失效**（而且是静默失效，
    因为没有任何东西会因此报错）。所以下面的测试全都盯着"真的暂停了没有"。
    """

    def test_qualifying_echo_pauses_and_records(self):
        """★ 符合条件 → 暂停 + 记录（走 ``_finalize_echo`` + ``_auto_stop_if_needed``）。"""
        t = _fake_task()
        _feed(t, GOOD)                  #: 先喂词条（= check_echo_stats 干的活）
        hit = t._finalize_echo(kept=True)
        stopped = t._auto_stop_if_needed(hit)
        self.assertTrue(hit, "符合条件的声骸应该返回 True")
        self.assertTrue(stopped, "应该触发暂停")
        self.assertEqual(t.pause_count, 1, "pause() 应该被调一次")
        self.assertEqual(len(t.qualifying_echoes), 1, "应该记进符合条件清单")
        self.assertTrue(t.info.get("已自动停止"), "应该写下已停止标记")
        self.assertTrue(t.info.get("自动停止原因"), "应该写下停止原因")
        self.assertTrue(any("已暂停任务" in m for m in t.logs),
                        f"应该打通知日志（{t.logs}）")

    def test_lock_and_esc_wires_the_verdict_through(self):
        """★★★ ``lock_and_esc`` 必须把「是否符合条件」**真的传下去**。

        ⚠⚠ 这条是护栏验证逼出来的。上面那条测试自己手动调
        ``_finalize_echo`` + ``_auto_stop_if_needed(hit)`` ——
        哪怕 ``lock_and_esc`` 里传的是写死的 ``False``，上面那条**照样通过**
        （它根本没走 ``lock_and_esc``）。

        所以这里**走真实的 ``lock_and_esc``**：用 ``__new__`` 造一个
        **真是本类实例**的对象（绕过 ``__init__``，不拉起 ok-ww 的依赖链），
        再把继承来的 ``EnhanceEchoTask.lock_and_esc``（会去点游戏上锁）
        换成一个只记调用的假货。

        ⚠ 必须用真实例：``lock_and_esc`` 里那句零参 ``super()`` 要求
        ``isinstance(obj, 本类)`` —— 拿 ``SimpleNamespace`` 顶替会
        直接 ``TypeError: obj must be an instance or subtype of type``
        （我第一版就是那么写的）。

        要抓的是那个静默失效：**先清零 `_qualifying_now`、随后再去读** ——
        自动停止彻底不工作，且没有任何东西会报错。
        """
        import unittest.mock as mock

        t = OT.MyToolsEnhanceEchoTask.__new__(OT.MyToolsEnhanceEchoTask)
        _init_fake_state(t)
        _feed(t, GOOD)
        t._aim_at_next_unenhanced = lambda: False
        called = {"n": 0}

        def fake_super(self_):
            called["n"] += 1

        with mock.patch.object(OT.EnhanceEchoTask, "lock_and_esc", fake_super):
            t.lock_and_esc()

        self.assertEqual(called["n"], 1, "继承来的 lock_and_esc 没被调到")
        self.assertEqual(t.pause_count, 1,
                         "走真实 lock_and_esc 时没触发暂停 —— "
                         "多半是「结论没传下去」或「先清零后读」的顺序 bug")
        self.assertEqual(len(t.qualifying_echoes), 1,
                         "走真实 lock_and_esc 时没记进符合条件清单")

    def test_records_stats_and_image_and_perfect_flag(self):
        """★ 记录里要有词条 + 图名 + **逐声骸**的满属性标记。"""
        t = _fake_task()
        _feed(t, GOOD_PERFECT)
        t._perfect_seen = True          #: 这个声骸出了满值
        t._finalize_echo(kept=True)
        entry = t.qualifying_echoes[0]
        self.assertTrue(entry["stats"], "没记词条 —— 卡片就没内容了")
        self.assertEqual(entry["image"], "x.png")
        self.assertTrue(entry["perfect"], "满属性标记应该是 True")

    def test_perfect_flag_is_per_echo_not_global(self):
        """★★ 满属性标记必须**逐声骸**，不能拿全局计数近似。

        ⚠⚠ 顺序很要紧 —— 护栏验证时发现我第一版用了
        「先普通、后满值」，那个顺序下**两种实现结果一样**（都是
        ``[False, True]``），所以测试是假的、抓不住退化。

        真正能区分的是**满值在前**：

            ① 满值达标 → 逐声骸 True   / 全局计数 True （都 1）
            ② 普通达标 → 逐声骸 **False** / 全局计数 **True** ← 这里分岔

        因为全局计数只增不减，第二个声骸会被误标成满属性。
        """
        t = _fake_task()
        _feed(t, GOOD_PERFECT)          # ① 满值且达标
        t._perfect_seen = True
        t._finalize_echo(kept=True)
        _feed(t, GOOD)                  # ② 普通达标（没出满值）
        t._finalize_echo(kept=True)

        flags = [e["perfect"] for e in t.qualifying_echoes]
        self.assertEqual(flags, [True, False],
                         "满属性标记不是逐声骸的 —— "
                         "第二个（普通达标的）被第一个的满值传染了")

    def test_perfect_but_short_does_not_pause(self):
        """★★★ 核心需求：满值但词条数不够 → **不暂停、不记录**。"""
        t = _fake_task()
        _feed(t, PERFECT_BUT_SHORT)
        hit = t._finalize_echo(kept=True)
        stopped = t._auto_stop_if_needed(hit)
        self.assertFalse(hit)
        self.assertFalse(stopped, "满值但词条数不够的不该触发自动停止")
        self.assertEqual(t.pause_count, 0)
        self.assertEqual(t.qualifying_echoes, [], "也不该进符合条件清单")

    def test_switch_off_does_not_pause_but_still_records(self):
        """★ 关掉开关 → 不暂停；但**仍然记录**（报告照样要展示声骸）。"""
        t = _fake_task(enable_auto_stop=False)
        _feed(t, GOOD)
        hit = t._finalize_echo(kept=True)
        stopped = t._auto_stop_if_needed(hit)
        self.assertFalse(stopped)
        self.assertEqual(t.pause_count, 0)
        self.assertEqual(len(t.qualifying_echoes), 1,
                         "关掉自动停止不该连报告内容一起丢")

    def test_discarded_echo_never_pauses(self):
        t = _fake_task()
        _feed(t, st(("暴击", 6.3)))
        hit = t._finalize_echo(kept=False)
        self.assertFalse(t._auto_stop_if_needed(hit))
        self.assertEqual(t.pause_count, 0)
        self.assertEqual(t.qualifying_echoes, [])

    def test_not_full_does_not_pause(self):
        """★ 没读满 5 条时**不**触发（否则满暴击一出现就误停）。"""
        t = _fake_task()
        _feed(t, st(("暴击", S.MAX_CRIT), ("暴击伤害", 15.0)), full=False)
        hit = t._finalize_echo(kept=True)
        self.assertFalse(hit, "未读满 → 结论未定，不算符合条件")

    def test_early_dead_stays_dead(self):
        """★ 中途就废了（暴击 6.3）→ 后面即使读满也不能翻回 True。"""
        t = _fake_task()
        _feed(t, st(("暴击", 6.3)), full=False)
        self.assertFalse(t._qualifying_now)
        _feed(t, st(("暴击", 6.3), ("暴击伤害", 15.0), ("攻击", 30),
                    ("防御", 70), ("生命", 430)), full=True)
        self.assertFalse(t._finalize_echo(kept=True),
                         "中途已废的声骸被翻成了符合条件")

    def test_reset_clears_state(self):
        """★ ``run()`` 里那一串复位必须把新状态也清掉（跨轮不残留）。"""
        t = _fake_task()
        _feed(t, GOOD)
        t._perfect_seen = True
        t._finalize_echo(kept=True)
        self.assertTrue(t.qualifying_echoes)
        #: 模拟 run() 的复位（照抄真实代码那几行）
        t.qualifying_echoes = []
        t.auto_stop_count = 0
        t._qualifying_now = False
        t._perfect_seen = False
        hit = t._finalize_echo(kept=True)
        self.assertFalse(hit, "复位后不该还留着上一轮的结论")


class TestScreenshotLookup(unittest.TestCase):
    """★ 找声骸截图（按**文件名**，不存绝对路径）。"""

    def test_finds_by_index_and_returns_name_only(self):
        import tempfile

        from src.core import paths

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        folder = pathlib.Path(tmp.name) / "okww" / "screenshots" / "success"
        folder.mkdir(parents=True)
        (folder / "12-00-00.000_3_original.png").write_bytes(b"x")

        orig = paths.user_data_dir
        paths.user_data_dir = lambda: pathlib.Path(tmp.name)
        self.addCleanup(lambda: setattr(paths, "user_data_dir", orig))

        t = _fake_task()
        t.info["成功声骸数量"] = 3
        setattr(t, "_find_echo_screenshot", types.MethodType(
            OT.MyToolsEnhanceEchoTask._find_echo_screenshot, t))
        got = t._find_echo_screenshot()
        self.assertEqual(got, "12-00-00.000_3_original.png",
                         "应该只返回文件名（绝对路径搬目录就失效）")

    def test_missing_returns_empty(self):
        import tempfile

        from src.core import paths

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        orig = paths.user_data_dir
        paths.user_data_dir = lambda: pathlib.Path(tmp.name)
        self.addCleanup(lambda: setattr(paths, "user_data_dir", orig))

        t = _fake_task()
        setattr(t, "_find_echo_screenshot", types.MethodType(
            OT.MyToolsEnhanceEchoTask._find_echo_screenshot, t))
        self.assertEqual(t._find_echo_screenshot(), "",
                         "找不到应该给空串，让卡片退化成纯文字")


class TestReportCards(unittest.TestCase):
    """★★ 结果报告的声骸卡片（用户要求：完整展示声骸图）。"""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def _with_fake_data_dir(self):
        import tempfile

        from src.core import paths

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        orig = paths.user_data_dir
        paths.user_data_dir = lambda: pathlib.Path(tmp.name)
        self.addCleanup(lambda: setattr(paths, "user_data_dir", orig))
        return pathlib.Path(tmp.name)

    def _make_png(self, folder, name):
        from PySide6.QtGui import QColor, QPixmap

        folder.mkdir(parents=True, exist_ok=True)
        pm = QPixmap(120, 100)
        pm.fill(QColor("#3d4148"))
        self.assertTrue(pm.save(str(folder / name)), "造测试图失败")
        return name

    def test_card_shows_image_and_stats(self):
        from PySide6.QtWidgets import QLabel

        from src.tools.game.echo_enhance import tool as T

        root = self._with_fake_data_dir()
        name = self._make_png(root / "okww" / "screenshots" / "success", "a_1_original.png")

        card = T.QualifyingEchoCard(
            {"index": 1, "stats": ["暴击 10.5", "攻击 30"], "image": name},
            index=1)
        self.assertTrue(
            any(w.pixmap() and not w.pixmap().isNull()
                for w in card.findChildren(QLabel)),
            "卡片里没有声骸图")
        text = " ".join(w.text() for w in card.findChildren(QLabel) if w.text())
        self.assertIn("暴击 10.5", text)
        self.assertIn("攻击 30", text)

    def test_card_without_image_has_no_empty_placeholder(self):
        """★ 缺图时不摆空框（本仓老规矩），但词条必须还在。"""
        from PySide6.QtWidgets import QLabel

        from src.tools.game.echo_enhance import tool as T

        self._with_fake_data_dir()
        card = T.QualifyingEchoCard(
            {"index": 2, "stats": ["暴击 9.9"], "image": "missing.png"}, index=2)
        self.assertFalse(
            [w for w in card.findChildren(QLabel)
             if w.pixmap() and not w.pixmap().isNull()],
            "缺图时不该画占位图")
        text = " ".join(w.text() for w in card.findChildren(QLabel) if w.text())
        self.assertIn("暴击 9.9", text)

    def test_perfect_badge_only_when_flagged(self):
        """★ 「满属性」标记只在 ``perfect=True`` 时出现。"""
        from PySide6.QtWidgets import QLabel

        from src.tools.game.echo_enhance import tool as T

        self._with_fake_data_dir()
        on = T.QualifyingEchoCard({"index": 1, "stats": [], "perfect": True},
                                  index=1, is_perfect=True)
        off = T.QualifyingEchoCard({"index": 1, "stats": []},
                                   index=1, is_perfect=False)
        self.assertIn("满属性",
                      " ".join(w.text() for w in on.findChildren(QLabel)))
        self.assertNotIn("满属性",
                         " ".join(w.text() for w in off.findChildren(QLabel)))

    def test_area_hidden_when_no_qualifying(self):
        """★ 没有符合条件的声骸时，卡片区整块隐藏（不占位）。

        ⚠⚠ **不能断言 ``isVisible()``**：父控件没 ``show()`` 时，
        Qt 的 ``isVisible()`` **永远是 False** —— 哪怕刚调过
        ``setVisible(True)``。护栏验证时发现我第一版就是这么写的，
        结果"把隐藏改成显示"测试**照样通过**（假绿）。

        改成查 ``isHidden()``（反映**显式**隐藏状态，与父窗口无关 ——
        本仓 ``_bind_exclusive`` 的注释里也记着同一个坑）。
        """
        from PySide6.QtWidgets import QVBoxLayout, QWidget

        from src.tools.game.echo_enhance import tool as T

        self._with_fake_data_dir()
        #: 造一个最小宿主：只调 _update_echo_cards，不建整个工具页
        holder = T.EchoEnhanceWidget.__new__(T.EchoEnhanceWidget)
        holder.echo_area = QWidget()
        holder.echo_box = QVBoxLayout(holder.echo_area)
        #: ⚠⚠ 指纹要预置成**非空**，否则空 items 算出来的 key 也是 ``()``
        #: → 命中"内容没变"那条短路 → **根本走不到 setVisible**
        #: （护栏验证抓到的：我第一版预置 ``()``，于是把隐藏改成显示测试照样过）
        holder._echo_key = ("占位",)

        holder._update_echo_cards([])
        self.assertTrue(holder.echo_area.isHidden(),
                        "没有符合条件的声骸时，卡片区应该被显式隐藏")

        #: 有内容时要显式显示（否则报告里永远看不到声骸卡）
        holder._update_echo_cards(
            [{"index": 1, "stats": ["暴击 1"], "image": ""}])
        self.assertFalse(holder.echo_area.isHidden(),
                         "有符合条件的声骸时，卡片区不该还藏着")

    def test_content_fingerprint_avoids_rebuild(self):
        """★ 内容没变时**不重建**（每 300ms 重建会让图片一直闪）。"""
        from src.tools.game.echo_enhance import tool as T

        self._with_fake_data_dir()
        holder = T.EchoEnhanceWidget.__new__(T.EchoEnhanceWidget)
        from PySide6.QtWidgets import QVBoxLayout, QWidget

        holder.echo_area = QWidget()
        holder.echo_box = QVBoxLayout(holder.echo_area)
        holder._echo_key = ()

        items = [{"index": 1, "stats": ["暴击 1"], "image": ""}]
        holder._update_echo_cards(items)
        first = holder.echo_box.count()
        holder._update_echo_cards(list(items))        #: 同样的内容
        self.assertEqual(holder.echo_box.count(), first,
                         "内容没变却重建了控件（图片会闪）")


if __name__ == "__main__":
    unittest.main(verbosity=2)
