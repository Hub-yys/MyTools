# -*- coding: utf-8 -*-
r"""声骸自动强化：**符合条件自动停止 + 通知 + 结果卡片** 的功能验证。

这个脚本干三件事（都不碰游戏、不碰真引擎）：
  ① 用**真实判定引擎**验 `qualifies` 的语义（含用户强调的排除项）；
  ② 用一个**假任务对象**走一遍自动停止链路（_finalize_echo → _auto_stop_if_needed）；
  ③ 用**真实 Qt** 建报告卡，验证卡片里真的有声骸图 + 词条。

    .\.venv\Scripts\python.exe tests\check_echo_autostop.py
"""
from __future__ import annotations

import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append((name, bool(ok), detail))


# --------------------------------------------------------------- ① 判定语义
def check_qualifies() -> None:
    from src.tools.game.echo_enhance import stats as S

    cfg = S.JudgeConfig(
        core_stats=frozenset({S.CRIT, S.CRIT_DMG, "攻击"}),
        optional_stats=frozenset(), min_valid_count=3,
        enable_max_roll_lock=True, enable_auto_stop=True)

    def q(items):
        return S.qualifies([S.EchoStat(n, v) for n, v in items], cfg)

    def acts(items):
        return S.judge([S.EchoStat(n, v) for n, v in items], cfg)

    #: ★★ 用户明确要求排除的那一类：满值但词条数不够
    perfect_only = [("暴击", 10.5), ("暴击伤害", 15.0), ("防御", 70),
                    ("防御百分比", 6.4), ("生命", 430)]
    r = acts(perfect_only)
    check("满暴击但有效词条不够 → judge 会 lock（有意的保护）",
          r.action == "lock" and r.code == "max_roll", f"{r.action}/{r.code}")
    check("★★ 但 qualifies=False（不触发自动停止）", q(perfect_only) is False)

    perfect_dmg_only = [("暴击伤害", 21.0), ("暴击", 7.5), ("防御", 70),
                        ("防御百分比", 6.4), ("生命", 430)]
    check("★★ 满爆伤但有效词条不够 → qualifies=False", q(perfect_dmg_only) is False)

    #: 真正符合条件的（普通达标）
    good = [("暴击", 9.9), ("暴击伤害", 15.0), ("攻击", 30),
            ("防御", 70), ("生命", 430)]
    check("普通达标（无满值）→ qualifies=True", q(good) is True)

    #: 满值 **且** 词条数够 → 算
    good_perfect = [("暴击", 10.5), ("暴击伤害", 15.0), ("攻击", 30),
                    ("防御", 70), ("生命", 430)]
    check("满暴击且有效 3 条 → qualifies=True", q(good_perfect) is True)

    #: 双爆低于下限 → 不算（即使满值保护上锁了）
    low_crit = [("暴击", 10.5), ("暴击伤害", 13.8), ("攻击", 30),
                ("防御", 70), ("生命", 430)]
    check("满暴击但爆伤低于下限 → qualifies=False", q(low_crit) is False)

    #: 中途（未满 5 条）时不能拿 qualifies 当真 —— 这是 _remember_judgement 的前提
    mid = [("暴击", 10.5)]
    check("未读满时 qualifies 只表示「还没淘汰」",
          q(mid) is True, "剩 4 孔，仍可能凑齐")

    #: 中途就已经废了（暴击低于下限）
    dead = [("暴击", 6.3)]
    check("中途已废（暴击 6.3）→ qualifies=False", q(dead) is False)

    #: 关掉满值保护时，qualifies 的判据不该跟着变
    cfg_nomax = S.JudgeConfig(
        core_stats=frozenset({S.CRIT, S.CRIT_DMG, "攻击"}),
        min_valid_count=3, enable_max_roll_lock=False)
    check("关掉满值保护后 qualifies 结论一致",
          S.qualifies([S.EchoStat(n, v) for n, v in perfect_only], cfg_nomax)
          is False)


# ------------------------------------------------- ② 自动停止链路（假任务）
def check_auto_stop_chain() -> None:
    """把 MyToolsEnhanceEchoTask 的方法**拆出来单独调**，不真跑 ok-ww。

    ⚠ 直接实例化那个类会拉起 ok-ww 的整条依赖（executor / config / OCR），
    没必要 —— 用 ``types.SimpleNamespace`` + 手动绑方法即可。
    """
    import types

    from src.tools.game.echo_enhance import okww_task as OT
    from src.tools.game.echo_enhance import stats as S

    def make_task(*, enable_auto_stop=True):
        """造一个只有在自动停止链路里用到的字段的假任务。"""
        paused = {"n": 0}
        t = types.SimpleNamespace()
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

        #: 这几个是继承来的，替换成假的
        t.info_set = lambda k, v: t.info.__setitem__(k, v)
        t.info_get = lambda k, d=None: t.info.get(k, d)
        t.log_info = lambda msg, **kw: t.logs.append(msg)
        t.log_error = lambda msg, **kw: t.logs.append("ERR " + msg)
        t.log_debug = lambda msg, **kw: None
        t.pause = lambda: paused.__setitem__("n", paused["n"] + 1)
        t._find_echo_screenshot = lambda: "fake.png"
        t._paused = paused
        #: 绑真实方法
        for name in ("_remember_judgement", "_record_qualifying",
                     "_finalize_echo", "_auto_stop_if_needed"):
            setattr(t, name, types.MethodType(
                getattr(OT.MyToolsEnhanceEchoTask, name), t))
        return t

    def feed(t, items, *, full=True):
        st = [S.EchoStat(n, v) for n, v in items]
        t._last_present = list(st)
        t._remember_judgement(list(st), full=full)

    good = [("暴击", 9.9), ("暴击伤害", 15.0), ("攻击", 30),
            ("防御", 70), ("生命", 430)]
    good_perfect = [("暴击", 10.5), ("暴击伤害", 15.0), ("攻击", 30),
                    ("防御", 70), ("生命", 430)]
    perfect_only = [("暴击", 10.5), ("暴击伤害", 15.0), ("防御", 70),
                    ("防御百分比", 6.4), ("生命", 430)]

    #: ── 场景 A：普通达标上锁 → 应该暂停 + 记录
    t = make_task()
    feed(t, good)
    hit = t._finalize_echo(kept=True)
    stopped = t._auto_stop_if_needed(hit)
    check("A 普通达标 → finalize 返回 True（符合条件）", hit is True)
    check("A 触发了暂停", stopped is True and t._paused["n"] == 1,
          f"paused={t._paused['n']}")
    check("A 记进了「符合条件的声骸」", len(t.qualifying_echoes) == 1,
          f"{t.qualifying_echoes}")
    check("A 记录了词条", t.qualifying_echoes
          and t.qualifying_echoes[0]["stats"], "")
    check("A 记录了图片名", t.qualifying_echoes
          and t.qualifying_echoes[0]["image"] == "fake.png", "")
    check("A 逐声骸记了 perfect 标记（不在卡片区用全局计数近似）",
          t.qualifying_echoes and t.qualifying_echoes[0]["perfect"] is False, "")
    check("A 写了自动停止原因", bool(t.info.get("自动停止原因")), "")
    check("A 写了已自动停止标记", t.info.get("已自动停止") is True, "")
    check("A 打了通知日志", any("已暂停任务" in m for m in t.logs), "")

    #: ── 场景 B：满暴击但词条数不够 → **不该**暂停（用户明确要求）
    t = make_task()
    feed(t, perfect_only)
    hit = t._finalize_echo(kept=True)
    stopped = t._auto_stop_if_needed(hit)
    check("★★ B 满值但词条不够 → finalize 返回 False", hit is False)
    check("★★ B **没有**暂停", stopped is False and t._paused["n"] == 0,
          f"paused={t._paused['n']}")
    check("B **没有**记进符合条件清单", not t.qualifying_echoes, "")

    #: ── 场景 C：关掉开关 → 符合条件也不暂停
    t = make_task(enable_auto_stop=False)
    feed(t, good)
    hit = t._finalize_echo(kept=True)
    stopped = t._auto_stop_if_needed(hit)
    check("C 开关关掉 → 不暂停", stopped is False and t._paused["n"] == 0, "")
    check("C 但**仍然记录**了符合条件（报告要展示）",
          len(t.qualifying_echoes) == 1, "")

    #: ── 场景 D：弃置的声骸 → 不暂停、不记录
    t = make_task()
    feed(t, [("暴击", 6.3)])
    hit = t._finalize_echo(kept=False)
    stopped = t._auto_stop_if_needed(hit)
    check("D 弃置 → 不暂停不记录",
          stopped is False and not t.qualifying_echoes, "")

    #: ── 场景 E：中途未满 5 条时**不**触发（避免误停）
    t = make_task()
    feed(t, [("暴击", 10.5), ("暴击伤害", 15.0)], full=False)
    hit = t._finalize_echo(kept=True)
    check("E 未读满 5 条 → 不算符合条件（不误停）", hit is False, "")

    #: ── 场景 F：满值 **且** 词条数够 → perfect 标记必须是 True
    t = make_task()
    feed(t, good_perfect)                 # 满暴击 10.5 + 有效 3 条
    t._perfect_seen = True                #: check_echo_stats 里出满值时会置这个
    t._finalize_echo(kept=True)
    check("F 满值且达标 → perfect 标记为 True",
          t.qualifying_echoes and t.qualifying_echoes[0]["perfect"] is True,
          f"{t.qualifying_echoes}")

    #: ── 场景 G：两个声骸，一个满值一个不满 → 标记要**各自独立**
    t = make_task()
    feed(t, good)                         # ① 普通达标
    t._finalize_echo(kept=True)
    feed(t, good_perfect)                 # ② 满值且达标
    t._perfect_seen = True
    t._finalize_echo(kept=True)
    flags = [e["perfect"] for e in t.qualifying_echoes]
    check("G 两个声骸的 perfect 标记各自独立", flags == [False, True], f"{flags}")


# ------------------------------------------------- ③ 报告卡片（真 Qt）
def check_echo_cards() -> None:
    import tempfile

    from PySide6.QtWidgets import QApplication, QLabel

    app = QApplication.instance() or QApplication([])

    from src.core import paths
    from src.tools.game.echo_enhance import tool as T

    #: 造一张真的小图放进 success 目录，验证卡片真的把它画出来了
    tmp = tempfile.TemporaryDirectory()
    folder = pathlib.Path(tmp.name) / "okww" / "screenshots" / "success"
    folder.mkdir(parents=True)
    png = folder / "12-00-00.000_1_original.png"
    try:
        from PySide6.QtGui import QColor, QPixmap

        pm = QPixmap(200, 180)
        pm.fill(QColor("#3d4148"))
        assert pm.save(str(png)), "造测试图失败"
    except Exception as exc:  # noqa: BLE001
        check("造测试图", False, str(exc))
        tmp.cleanup()
        return

    orig = paths.user_data_dir
    paths.user_data_dir = lambda: pathlib.Path(tmp.name)
    try:
        item = {"index": 1, "stats": ["暴击 10.5", "暴击伤害 21", "攻击 30"],
                "image": png.name}
        card = T.QualifyingEchoCard(item, index=1, is_perfect=True)

        labels = card.findChildren(QLabel)
        pixmaps = [w for w in labels if w.pixmap() and not w.pixmap().isNull()]
        check("卡片里有声骸图", bool(pixmaps), f"{len(pixmaps)} 张")

        texts = " ".join(w.text() for w in card.findChildren(QLabel) if w.text())
        check("卡片里有词条", "暴击 10.5" in texts and "攻击 30" in texts, texts[:80])

        #: 找不到图时**不留空洞**，但词条还在
        missing = T.QualifyingEchoCard(
            {"index": 2, "stats": ["暴击 9.9"], "image": "不存在.png"}, index=2)
        m_labels = missing.findChildren(QLabel)
        m_pix = [w for w in m_labels if w.pixmap() and not w.pixmap().isNull()]
        m_text = " ".join(w.text() for w in m_labels if w.text())
        check("缺图时不画占位图", not m_pix, f"{len(m_pix)} 张")
        check("缺图时词条仍在", "暴击 9.9" in m_text, m_text[:60])
    finally:
        paths.user_data_dir = orig
        tmp.cleanup()


def main() -> int:
    print("=" * 70)
    print("① 判定语义（qualifies）")
    print("=" * 70)
    check_qualifies()
    for name, ok, det in CHECKS:
        print("  [%s] %s%s" % ("PASS" if ok else "FAIL", name,
                               ("   " + det) if det else ""))
    n1 = len(CHECKS)

    print()
    print("=" * 70)
    print("② 自动停止链路（假任务，不碰引擎）")
    print("=" * 70)
    check_auto_stop_chain()
    for name, ok, det in CHECKS[n1:]:
        print("  [%s] %s%s" % ("PASS" if ok else "FAIL", name,
                               ("   " + det) if det else ""))
    n2 = len(CHECKS)

    print()
    print("=" * 70)
    print("③ 结果报告卡片（真 Qt）")
    print("=" * 70)
    check_echo_cards()
    for name, ok, det in CHECKS[n2:]:
        print("  [%s] %s%s" % ("PASS" if ok else "FAIL", name,
                               ("   " + det) if det else ""))

    print()
    bad = [c for c in CHECKS if not c[1]]
    print("共 %d 项，%d 项失败" % (len(CHECKS), len(bad)))
    print("★", "全部通过" if not bad else "⚠ 见上面的 FAIL")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
