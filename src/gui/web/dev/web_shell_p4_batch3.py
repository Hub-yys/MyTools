# -*- coding: utf-8 -*-
"""验收 P4 第三批：抽卡分析 + 角色练度缓存。

## 覆盖

* ``analyzeGacha(link)`` —— 链接解析同步校验（三种必填参数）、
  异步受理、``busy`` 互斥
* ``getCharacterBuildCache()`` —— 读 ``data/kuro_练度.json``（21 个角色）
* ``getCharacterBuildDetail(roleId)`` —— 单角色详情

⚠ **不打真实网络**：``analyzeGacha`` 只用**非法链接**验同步校验，
以及一个**格式正确但参数假**的链接验"能受理"（线程会失败，但不阻塞）。
"""

from __future__ import annotations

import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", "..", ".."))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)
os.environ.setdefault("QT_LOGGING_RULES", "qt.multimedia.*=false")

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])
import src.tools as tools_pkg  # noqa: E402

tools_pkg.discover_tools()

from src.core.web_bridge import WebBridge  # noqa: E402

FAILS: list[str] = []


def ok(tag: str, cond: bool, note: str = "") -> None:
    print(f"[{'PASS' if cond else 'FAIL'}] {tag}  {note}")
    if not cond:
        FAILS.append(tag)


def pump(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def main() -> int:
    b = WebBridge()

    # ══════════════════════════════════════════════════════════════
    # analyzeGacha —— 链接校验（同步，不该起线程）
    # ══════════════════════════════════════════════════════════════
    r = json.loads(b.analyzeGacha(""))
    ok("gacha_empty_link",
       r.get("ok") is False and r.get("reason") == "bad_link",
       f"message = {str(r.get('message'))[:80]!r}")

    r = json.loads(b.analyzeGacha("https://example.com/foo"))
    ok("gacha_wrong_host",
       r.get("ok") is False and r.get("reason") == "bad_link",
       f"message = {str(r.get('message'))[:90]!r}")
    #: 错误信息必须**指明问题**（Qt 版就是这么写的）
    ok("gacha_wrong_host_helpful",
       "唤取记录" in str(r.get("message", ""))
       or "aki-game" in str(r.get("message", "")),
       f"message 有引导语 = {str(r.get('message'))[:100]!r}")

    r = json.loads(b.analyzeGacha(
        "https://aki-gm-resources.aki-game.com/#/record?foo=bar"))
    ok("gacha_missing_params",
       r.get("ok") is False and r.get("reason") == "bad_link",
       f"message = {str(r.get('message'))[:100]!r}")

    #: 缺参数时要报出**缺哪些**
    msg = str(r.get("message") or "")
    ok("gacha_missing_params_names_them",
       "playerId" in msg or "recordId" in msg or "cardPoolId" in msg,
       f"点名缺失参数 = {msg[:110]!r}")

    #: 校验失败不该起线程
    ok("gacha_bad_link_no_thread", b._gacha_running is False,
       f"_gacha_running={b._gacha_running}")

    # ══════════════════════════════════════════════════════════════
    # analyzeGacha —— 合法格式能受理（线程会失败，但不阻塞）
    # ══════════════════════════════════════════════════════════════
    #: ⚠ 参数名必须用 ``PARAM_ALIASES`` 里的**真实键名**：
    #: ``player_id`` / ``record_id`` / ``resources_id``（后者映射到 cardPoolId）。
    #: 写成 ``card_pool_id`` 会被判 missing cardPoolId。
    fake_link = (
        "https://aki-gm-resources.aki-game.com/#/record"
        "?player_id=__fake__&record_id=__fake__&resources_id=__fake__"
        "&svr_id=1&lang=zh-Hans"
    )
    r = json.loads(b.analyzeGacha(fake_link))
    ok("gacha_valid_format_accepted",
       r.get("ok") is True,
       json.dumps(r, ensure_ascii=False)[:120])

    if r.get("ok"):
        #: 立刻再调 → busy
        r2 = json.loads(b.analyzeGacha(fake_link))
        ok("gacha_busy", r2.get("ok") is False
           and r2.get("reason") == "busy",
           json.dumps(r2, ensure_ascii=False)[:110])

        #: 等它失败（假参数会一定失败）—— 最多 60 秒
        events: list[dict] = []
        b.event.connect(
            lambda raw: events.append(json.loads(raw))
            if json.loads(raw).get("name") == "gachaAnalyzed" else None)

        def wait_done(timeout_s: float = 60.0) -> bool:
            loop = QEventLoop()

            def poll():
                if not b._gacha_running:
                    loop.quit()

            t = QTimer()
            t.setInterval(200)
            t.timeout.connect(poll)
            t.start()
            stop = QTimer()
            stop.setSingleShot(True)
            stop.timeout.connect(loop.quit)
            stop.start(int(timeout_s * 1000))
            loop.exec()
            t.stop()
            return not b._gacha_running

        finished = wait_done()
        ok("gacha_thread_settled", finished,
           f"线程结束 = {finished}（假参数必然失败，这是预期的）")
        if finished and events:
            payload = events[0].get("data") or {}
            ok("gacha_event_shape",
               payload.get("ok") is True or "message" in payload,
               json.dumps(payload, ensure_ascii=False)[:130])

    # ══════════════════════════════════════════════════════════════
    # getCharacterBuildCache
    # ══════════════════════════════════════════════════════════════
    cache = json.loads(b.getCharacterBuildCache())
    if cache.get("reason") == "no_cache":
        ok("build_cache", True,
           "本机没有缓存文件（跳过内容断言，但接口正确返回 no_cache）")
    else:
        ok("build_cache_ok", cache.get("ok") is True,
           f"updatedAt={cache.get('updatedAt')!r} "
           f"nickname={cache.get('nickname')!r}")

        chars = cache.get("characters") or []
        ok("build_cache_characters", len(chars) == 21,
           f"{len(chars)} 个角色（实测缓存里是 21 个）")

        if chars:
            c0 = chars[0]
            ok("build_cache_char_fields",
               all(k in c0 for k in ("roleId", "name", "level", "star",
                                     "attribute", "iconUrl")),
               f"字段 = {sorted(c0.keys())}")
            ok("build_cache_char_has_name", bool(c0.get("name")),
               f"样例 = {json.dumps({k: c0[k] for k in ('roleId','name','level','star')}, ensure_ascii=False)}")

        ok("build_cache_detail_ids",
           isinstance(cache.get("detailIds"), list)
           and len(cache["detailIds"]) > 0,
           f"detailIds = {cache.get('detailIds')}")

        #: ★ 体积控制：不能把 1.2 MB 全塞给页面
        size = len(json.dumps(cache, ensure_ascii=False).encode())
        ok("build_cache_payload_size", size < 200_000,
           f"{size / 1024:.0f} KB（原始缓存 1.2 MB，必须精简）")

        # ══════════════════════════════════════════════════════════
        # getCharacterBuildDetail
        # ══════════════════════════════════════════════════════════
        ids = cache.get("detailIds") or []
        if ids:
            d = json.loads(b.getCharacterBuildDetail(str(ids[0])))
            ok("build_detail_ok", d.get("ok") is True,
               f"roleId={ids[0]} keys={sorted(d.keys())}")
            ok("build_detail_has_data",
               d.get("detail") is not None or d.get("standard") is not None,
               f"detail={'有' if d.get('detail') else '无'} "
               f"standard={'有' if d.get('standard') else '无'}")

        r = json.loads(b.getCharacterBuildDetail("__no_such_role__"))
        ok("build_detail_not_found",
           r.get("ok") is False and r.get("reason") == "not_found",
           f"available 前 3 = {(r.get('available') or [])[:3]}")
        ok("build_detail_not_found_lists_available",
           isinstance(r.get("available"), list) and len(r["available"]) > 0,
           f"{len(r.get('available') or [])} 个可选")

    r = json.loads(b.getCharacterBuildDetail(""))
    ok("build_detail_empty_id",
       r.get("ok") is False and r.get("reason") == "empty", "")

    print()
    print("=" * 66)
    print("结果：" + ("全部通过" if not FAILS else "失败 " + str(FAILS)))
    print("=" * 66)
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
