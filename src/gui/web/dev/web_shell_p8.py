# -*- coding: utf-8 -*-
"""验收 P8：⑥ 角色练度的三处数据缺口。

## 背景（lead 和 page-converter 逐项核对旧界面 ⑥ 发现的）

旧界面「查询角色练度」有 5 张卡，Web 版缺数据：

| # | 缺什么 | 影响 |
|---|---|---|
| ① | `base` 的 6 个账号概览字段 | ② 账号概览那行全空 |
| ② | `rolePicUrl`（立绘） | 角色卡只有方形头像，不是旧界面的竖长立绘 |
| ③ | 登录卡数据 | ① 登录卡没法照抄外观 |

数据**都在** `kuro_练度.json` / `kuro_account.json` 里，只是接口没返回。

## 验什么

1. `base` 的 6 项（体力/单质/活跃度/天数/等级/角色数）—— **对照 lead 给的实际值**
2. 每个角色都有 `picUrl`（立绘）**和** `iconUrl`（头像）两个
3. `picUrl` 是**远程 URL**（不是本地文件，页面不用 media_server）
4. `loginInfo` 的手机号**已脱敏**（只有后 4 位）

## ⚠ 只读

全部只读缓存文件，不写盘。
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
sys.path.insert(0, _HERE)
os.chdir(_ROOT)
os.environ.setdefault("QT_LOGGING_RULES", "qt.multimedia.*=false")

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


#: ★ lead 给的旧界面实机值（用来证明算的是同一份数据）
_EXPECT_BASE = {
    "energy": 89,            # 结晶波片 89/240
    "maxEnergy": 240,
    "storeEnergy": 61,       # 结晶单质 61/480
    "storeEnergyLimit": 480,
    "liveness": 100,         # 活跃度 100/100
    "livenessMaxCount": 100,
    "activeDays": 59,        # 游戏天数
    "level": 67,             # 联觉等级
    "roleNum": 21,           # 解锁角色
}


def main() -> int:
    b = WebBridge()
    c = json.loads(b.getCharacterBuildCache())

    if not c.get("ok"):
        ok("cache_ok", False,
           f"reason={c.get('reason')} message={c.get('message')}")
        return finish()

    ok("cache_ok", True, f"{c.get('count')} 个角色")

    # ══════════════════════════════════════════════════════════════
    # ① base —— 旧界面 ② 账号概览那 6 项
    # ══════════════════════════════════════════════════════════════
    base = c.get("base") or {}
    ok("base_present", bool(base),
       f"字段 = {sorted(base.keys())}")

    for field, want in _EXPECT_BASE.items():
        got = base.get(field)
        ok(f"base_{field}", got == want,
           f"{field} = {got!r}（旧界面实机 = {want}）")

    #: 旧界面显示成「89/240」这种，两个数都得有
    ok("base_energy_pair",
       base.get("maxEnergy", 0) > 0
       and 0 <= base.get("energy", 0) <= base.get("maxEnergy", 0),
       f"{base.get('energy')}/{base.get('maxEnergy')}（结晶波片）")
    ok("base_store_pair",
       base.get("storeEnergyLimit", 0) > 0
       and 0 <= base.get("storeEnergy", 0) <= base.get("storeEnergyLimit", 0),
       f"{base.get('storeEnergy')}/{base.get('storeEnergyLimit')}（结晶单质）")
    ok("base_liveness_pair",
       base.get("livenessMaxCount", 0) > 0,
       f"{base.get('liveness')}/{base.get('livenessMaxCount')}（活跃度）")

    #: 旧界面还显示了世界等级 / 成就，一并验
    ok("base_world_level", base.get("worldLevel", 0) > 0,
       f"worldLevel = {base.get('worldLevel')}")
    ok("base_achievement", base.get("achievementCount", 0) > 0,
       f"achievementCount = {base.get('achievementCount')}")

    #: 结晶单质的名字是库街区给的（「结晶单质」）
    ok("base_store_title",
       bool(base.get("storeEnergyTitle")),
       f"storeEnergyTitle = {base.get('storeEnergyTitle')!r}")

    # ══════════════════════════════════════════════════════════════
    # ② 角色立绘 rolePicUrl
    # ══════════════════════════════════════════════════════════════
    chars = c.get("characters") or []
    if not chars:
        ok("characters_present", False, "没有角色")
        return finish()

    missing_pic = [x["name"] for x in chars if not x.get("picUrl")]
    missing_icon = [x["name"] for x in chars if not x.get("iconUrl")]
    ok("all_characters_have_picUrl", not missing_pic,
       f"{len(chars)} 个角色全部有立绘" if not missing_pic
       else f"缺立绘 = {missing_pic}")
    ok("all_characters_have_iconUrl", not missing_icon,
       f"{len(chars)} 个角色全部有头像" if not missing_icon
       else f"缺头像 = {missing_icon}")

    #: ★★ picUrl 和 iconUrl 必须是**不同的** URL（一个是立绘一个是方形头像）
    same = [x["name"] for x in chars
            if x.get("picUrl") and x.get("picUrl") == x.get("iconUrl")]
    ok("picUrl_differs_from_iconUrl", not same,
       "立绘和头像是两个不同的 URL" if not same
       else f"这两个字段一样 = {same}")

    #: ★★★ picUrl 是**远程 URL**（库街区 CDN）—— 页面直接 <img src>，不用挂载
    remote = [x["name"] for x in chars
              if x.get("picUrl") and not str(x["picUrl"]).startswith("http")]
    ok("picUrl_is_remote_url", not remote,
       f"样例 = {chars[0].get('picUrl', '')[:75]}"
       if not remote else f"非 http 开头 = {remote}")

    ok("picUrl_is_kuro_cdn",
       "kurobbs.com" in str(chars[0].get("picUrl", "")),
       f"域名 = {str(chars[0].get('picUrl', '')).split('/')[2] if '/' in str(chars[0].get('picUrl', '')) else '?'}"
       f"（库街区 CDN，不属于本地 assets）")

    #: 和 lead 说的字段名对得上（旧界面用 rolePicUrl）
    from src.core import paths

    raw = json.loads((paths.user_data_dir() / "kuro_练度.json")
                     .read_text(encoding="utf-8"))
    raw0 = (raw.get("roleList") or [{}])[0]
    ok("picUrl_matches_source_field",
       str(chars[0].get("picUrl")) == str(raw0.get("rolePicUrl") or ""),
       "接口的 picUrl == 缓存的 rolePicUrl（没有自己拼）")

    # ══════════════════════════════════════════════════════════════
    # ③ loginInfo —— 登录卡（手机号必须脱敏）
    # ══════════════════════════════════════════════════════════════
    login = c.get("loginInfo") or {}
    ok("loginInfo_present", bool(login),
       f"字段 = {sorted(login.keys())}")

    ok("loginInfo_gameId",
       bool(login.get("gameId")),
       f"gameId = {login.get('gameId')!r}（旧界面显示的特征码）")
    ok("loginInfo_loggedIn",
       isinstance(login.get("loggedIn"), bool),
       f"loggedIn = {login.get('loggedIn')}")

    #: ★★ 手机号必须**只有后 4 位** —— 完整号码不该进前端
    tail = str(login.get("phoneTail") or "")
    masked = str(login.get("phoneMasked") or "")
    ok("loginInfo_phone_tail_only_4",
       len(tail) == 4 and tail.isdigit(),
       f"phoneTail = {tail!r}（库里存的就是 4 位）")
    ok("loginInfo_phone_masked",
       masked.startswith("****") and masked.endswith(tail) if tail else True,
       f"phoneMasked = {masked!r}（页面直接显示这个）")

    #: ★ 整个返回体里不该出现 11 位手机号
    blob = json.dumps(c, ensure_ascii=False)
    import re

    long_phones = re.findall(r"\b1[3-9]\d{9}\b", blob)
    ok("no_full_phone_number_in_payload", not long_phones,
       "返回体里没有完整手机号" if not long_phones
       else f"⚠ 发现完整号码 = {long_phones}")

    #: 登录时间（可选展示）
    if login.get("loginAt"):
        ok("loginInfo_loginAt_format",
           len(str(login["loginAt"])) >= 10 and "-" in str(login["loginAt"]),
           f"loginAt = {login.get('loginAt')!r}")

    return finish()


def finish() -> int:
    print()
    print("=" * 70)
    print("结果：" + ("全部通过" if not FAILS else "失败 " + str(FAILS)))
    print("=" * 70)
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
