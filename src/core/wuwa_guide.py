# -*- coding: utf-8 -*-
"""鸣潮**官方攻略站**（mcguide）客户端 —— 拿「角色推荐属性」（练度达标标准）。

## 这是第三套接口了，别混

============================  ====================================  ==============
用途                           前缀                                  认证
============================  ====================================  ==============
图鉴数据                       ``api.kurobbs.com/wiki/...``          公开
**我的账号数据**               ``api.kurobbs.com/aki/...``           数据令牌
**官方推荐标准（本模块）**      ``guide-server.aki-game.com``         **公开**
============================  ====================================  ==============

三者互不依赖。拼起来才是"练度对比"：**我的数值** vs **官方推荐数值**。

## 为什么需要它（用户 2026-10-05 给的链接）

用户给了官方攻略站的链接，截图里是「属性推荐」::

    暴击      ≥70.0%
    暴击伤害  ≥260.0%
    共鸣效率  ≥120.0%

**这就是"哪些声骸该重刷"的判据** —— 而且是**每个角色各不相同**的::

    白芷      共鸣效率 260.0% / 治疗效果加成 40.0% / 生命 24000
    今汐      暴击 70.0% / 暴击伤害 275.0% / 共鸣技能伤害加成 20.0%
    守岸人     共鸣效率 230.0% / 生命 45000
    弗洛洛     暴击 95.0% / 暴击伤害 275.0% / 攻击 2100

（我原来自己拍了个"有效词条 < 10 算差"——那没有依据。）

## 接口（全部 GET，无需登录）

    GET /introduction/list?roleGbId=<角色id>
        → data[0].id 就是 strategy_id

    GET /introduction/info?roleGbId=<角色id>&id=<strategy_id>
        → data.roleAttribute.items[]   ★ 推荐属性（达标线）
          data.echo                   推荐声骸 + 套装
          data.weapon                 推荐武器
          data.roleSkill              技能加点顺序
          data.teammate               配队

    GET /role/info?roleGbId=<角色id>
        → 技能（含完整描述和演示视频）/ 立绘

## ★★ 参数名的坑（实测）

============================  ==========================
参数                          结果
============================  ==========================
**``roleGbId``**              ✅ **200 ok**
``roleId`` / ``role_id``      ❌ 500 server error
``id``                        ❌ 500
============================  ==========================

``roleGbId`` = **游戏内的角色 id**（白芷 1103 / 今汐 1311）——
和 :mod:`src.core.kuro_account` 的 ``roleList[].roleId`` **是同一个**。
⚠ 和**特征码**不是一回事（那个是账号级的）。

## ★ 接口域名是怎么找到的

首页 HTML 只有 3579 字符（SPA 壳）。真域名在 ``main-*.js`` 的
``import.meta.env`` 里::

    VITE_WAVES_GUIDE_CN:  "https://guide-server.aki-game.com"   ← ★ 真 API
    VITE_APP_AXIOS_BASE_URL_CN_FIRST: ".../aki-gm-resources-back..."  ← 不是 API
    VITE_APP_BASE_URL: "/wutheringWavesGuides/"                 ← 只是路由 base

**弯路**：先猜 ``aki-gm-resources-back``（一直 OSS ``NoSuchKey``），
又猜 ``mcguide.kurogames.com``（SPA 对任何路径都回 200，是假象）。
→ **教训：先挖 env 里的域名常量，别猜。**
"""

from __future__ import annotations

import json
import logging
import ssl
import urllib.error
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

#: CN 主站（实测可用）
API_ROOT = "https://guide-server.aki-game.com"
#: CN 备用站
API_ROOT_BACKUP = "https://guide-server-1.aki-game.com"

#: 攻略列表（拿 strategy_id）
API_INTRO_LIST = "/introduction/list"
#: 攻略详情（★ 推荐属性在这里）
API_INTRO_INFO = "/introduction/info"
#: 角色基础信息（技能 / 立绘）
API_ROLE_INFO = "/role/info"

TIMEOUT = 25

#: 默认语言
LANG_DEFAULT = "zh-Hans"

#: 业务成功码
CODE_OK = 200

#: 请求头（实测缺 ``x-language`` 会拿不到中文）
_BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
               "AppleWebKit/537.36 (KHTML, like Gecko) "
               "Chrome/126.0 Safari/537.36")

#: ★★ ``operation`` 字段 → 比较符。
#:
#: ## 这张表是**从 JS 里挖出来的**，不是猜的（2026-10-05）
#:
#: 官方页面把 ``operation`` 数字映射成符号显示::
#:
#:     [{label:"=",  value: de.Equality},
#:      {label:">",  value: de.GreaterThan},
#:      {label:"≥",  value: de.GreaterThanOrEqual},
#:      {label:"≠",  value: de.Inequality},
#:      {label:"<",  value: de.LessThan},
#:      {label:"≤",  value: de.LessThanOrEqual}]
#:
#: 枚举值（也在 JS 里）::
#:
#:     Equality = 1    Inequality = 2    LessThan = 3
#:     GreaterThan = 4    LessThanOrEqual = 5    GreaterThanOrEqual = 6
#:
#: ⚠⚠ **我第一版猜错了两个** —— 以为 ``4`` 是 ``<=``、``5`` 是 ``>``。
#: 结果安可（``operation=4``）被判成"暴击要 ≤65%"，
#: 而实际是"**暴击要 >65%**"。**猜枚举值是不可靠的，必须挖源码。**
OPERATION_SYMBOLS = {
    1: "=",
    2: "≠",
    3: "<",
    4: ">",
    5: "≤",
    6: "≥",
}

#: 比较符 → Python 运算（判达标用）
SYMBOL_TESTS = {
    "=": lambda have, need: abs(have - need) < 1e-9,
    "≠": lambda have, need: abs(have - need) >= 1e-9,
    "<": lambda have, need: have < need,
    ">": lambda have, need: have > need,
    "≤": lambda have, need: have <= need,
    "≥": lambda have, need: have >= need,
}


def meets(have: float, need: float, symbol: str) -> bool:
    """按官方给的比较符判断是否达标。

    ⚠ 不写死"越大越好" —— 官方真的有 ``>`` / ``<`` / ``≤`` 这些方向。
    """
    test = SYMBOL_TESTS.get(str(symbol or "").strip())
    if test is None:
        return True                            #: 不认识的符号 → 不当问题
    return bool(test(have, need))


class GuideError(Exception):
    """攻略站接口出错（业务码非 200 / 网络失败）。"""

    def __init__(self, code, message: str = "", path: str = "") -> None:
        self.code = code
        self.path = path
        super().__init__(f"[{code}] {message}"
                         + (f"（{path}）" if path else ""))


def _headers(lang: str = LANG_DEFAULT) -> dict:
    return {
        "User-Agent": _BROWSER_UA,
        "Referer": "https://mcguide.kurogames.com/",
        "Origin": "https://mcguide.kurogames.com",
        "Accept": "application/json, text/plain, */*",
        "x-language": lang or LANG_DEFAULT,
    }


def _get(path: str, params: dict, *, lang: str = LANG_DEFAULT,
         timeout: int = TIMEOUT,
         root: str = API_ROOT) -> dict:
    """GET 一个接口，返回**完整 JSON**（调用方自己看 ``code``）。"""
    query = urllib.parse.urlencode(
        {k: v for k, v in (params or {}).items() if v is not None})
    url = f"{root}{path}" + (f"?{query}" if query else "")
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        req = urllib.request.Request(url, headers=_headers(lang))
        with urllib.request.urlopen(req, timeout=timeout,
                                    context=ctx) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        raise GuideError(exc.code, "HTTP 错误", path=path) from exc
    except Exception as exc:                   # noqa: BLE001
        raise GuideError(None, f"{type(exc).__name__}: {exc}",
                         path=path) from exc


def _call(path: str, params: dict, *, lang: str = LANG_DEFAULT,
          timeout: int = TIMEOUT, root: str = API_ROOT) -> object:
    """GET 并检查业务码，返回 ``data``。"""
    payload = _get(path, params, lang=lang, timeout=timeout, root=root)
    code = payload.get("code")
    if code != CODE_OK:
        raise GuideError(code, str(payload.get("message") or ""),
                         path=path)
    return payload.get("data")


# ------------------------------------------------------------------ 攻略

def fetch_strategy_id(role_gb_id, *, lang: str = LANG_DEFAULT,
                      timeout: int = TIMEOUT) -> int | None:
    """拿某个角色的**攻略 id**（= 用户链接里的 ``strategy_id``）。

    一个角色可能有多篇攻略，这里取**第一篇**（实测就是官方推荐那篇）。
    """
    data = _call(API_INTRO_LIST, {"roleGbId": role_gb_id},
                 lang=lang, timeout=timeout)
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and item.get("id"):
                return int(item["id"])
    return None


def fetch_strategy(role_gb_id, strategy_id, *,
                   lang: str = LANG_DEFAULT,
                   timeout: int = TIMEOUT) -> dict:
    """拿一篇攻略的完整详情。

    ⚠ ``id`` 和 ``roleGbId`` **都要**给（只给 id 实测也能通，但别省）。
    """
    data = _call(API_INTRO_INFO,
                 {"roleGbId": role_gb_id, "id": strategy_id},
                 lang=lang, timeout=timeout)
    return data if isinstance(data, dict) else {}


# ------------------------------------------------- 推荐属性（★ 达标标准）

def parse_recommend_attrs(strategy: dict) -> list[dict]:
    """从攻略详情里取出**推荐属性**（"达标线"）。

    返回::

        [{"name": "暴击", "recommend": "70.0%", "value": 70.0,
          "unit": "%", "current": "0.0%", "is_finished": False,
          "operation": 6, "symbol": ">=", "icon_url": "https://..."}]

    ## 原始结构（实测）

    ::

        data.roleAttribute.items[] = {
          "gbId": "8-2",
          "pictureUrl": "https://guide-res.aki-game.com/...",
          "texts": [{"language": "zh-Hans", "name": "暴击"}],
          "recommendAmount": "70.0%",    ← ★ 推荐值
          "currentAmount": "0.0%",       ← 当前值（未登录时是 0）
          "isFinished": false,           ← 官方自己算的"达标了没"
          "operation": 6,                ← 6 = ">="
        }
    """
    items = ((strategy or {}).get("roleAttribute") or {}).get("items") or []
    out: list[dict] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        name = ""
        for t in it.get("texts") or []:
            if isinstance(t, dict) and t.get("name"):
                name = str(t["name"])
                break
        if not name:
            continue
        rec_raw = str(it.get("recommendAmount") or "").strip()
        cur_raw = str(it.get("currentAmount") or "").strip()
        operation = it.get("operation")
        out.append({
            "name": name,
            "recommend": rec_raw,
            "value": parse_amount(rec_raw),
            "unit": unit_of(rec_raw),
            "current": cur_raw,
            "current_value": parse_amount(cur_raw),
            "is_finished": bool(it.get("isFinished")),
            "operation": operation,
            "symbol": OPERATION_SYMBOLS.get(operation, "≥"),
            "icon_url": str(it.get("pictureUrl") or ""),
            "gb_id": str(it.get("gbId") or ""),
        })
    return out


def parse_amount(text: str) -> float | None:
    """``"70.0%"`` → ``70.0``；``"2200"`` → ``2200.0``；解析不了返回 ``None``。

    ⚠ ``%`` 会**去掉**（返回值不区分百分比和绝对值 ——
    单位看 :func:`unit_of`）。
    """
    s = str(text or "").strip().replace("%", "").replace(",", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def unit_of(text: str) -> str:
    """``"70.0%"`` → ``"%"``；``"2200"`` → ``""``。"""
    return "%" if "%" in str(text or "") else ""


# ------------------------------------------------------- 便捷：一次拿全

def fetch_recommend(role_gb_id, *,
                    lang: str = LANG_DEFAULT,
                    timeout: int = TIMEOUT) -> dict:
    """一个角色的**推荐标准**（属性 + 声骸 + 武器 + 技能加点）。

    :return: ``{"role_gb_id", "strategy_id", "attrs": [...],
                "echo", "weapon", "role_skill", "teammate"}``
        —— 查不到攻略时 ``attrs`` 为空（**不抛异常**，
        因为有些角色官方还没出攻略，不该因此让整个拉取失败）。
    """
    result = {"role_gb_id": str(role_gb_id), "strategy_id": None,
              "attrs": [], "echo": None, "weapon": None,
              "role_skill": None, "teammate": None}
    try:
        sid = fetch_strategy_id(role_gb_id, lang=lang, timeout=timeout)
    except GuideError as exc:
        logger.debug("攻略列表失败 %s：%s", role_gb_id, exc)
        return result
    if not sid:
        return result
    result["strategy_id"] = sid
    try:
        strategy = fetch_strategy(role_gb_id, sid, lang=lang,
                                  timeout=timeout)
    except GuideError as exc:
        logger.debug("攻略详情失败 %s/%s：%s", role_gb_id, sid, exc)
        return result

    result["attrs"] = parse_recommend_attrs(strategy)
    result["echo"] = strategy.get("echo")
    result["weapon"] = strategy.get("weapon")
    result["role_skill"] = strategy.get("roleSkill")
    result["teammate"] = strategy.get("teammate")
    return result


def fetch_role_info(role_gb_id, *, lang: str = LANG_DEFAULT,
                    timeout: int = TIMEOUT) -> dict:
    """角色基础信息（技能含**完整描述**和演示视频 / 立绘）。"""
    data = _call(API_ROLE_INFO, {"roleGbId": role_gb_id},
                 lang=lang, timeout=timeout)
    return data if isinstance(data, dict) else {}
