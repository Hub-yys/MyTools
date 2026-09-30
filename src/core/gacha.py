"""鸣潮「唤取记录」（抽卡记录）的拉取与统计。

用户在游戏里打开「唤取记录」页面并复制链接，粘贴到工具里，本模块解析出
参数 → 调库洛官方接口拉全部卡池 → 汇总成统计报告。

**纯逻辑**：不依赖 Qt，可以单测（见 ``tests/test_gacha.py``）。
网络请求单独抽成 :func:`fetch_pool`，测试里喂假响应。

## 接口（2026-09-30 实测可用）

    用户复制的链接形如：
    https://aki-gm-resources.aki-game.com/aki/gacha/index.html#/record?
        svr_id=xxx&player_id=xxx&lang=zh-Hans&record_id=xxx&resources_id=xxx

    接口：
    POST https://gmserver-api.aki-game2.com/gacha/record/query?<原查询串>&cardPoolType=N
    Body(JSON): {serverId, playerId, languageCode, recordId, cardPoolId, cardPoolType}

    ⚠ 链接里的参数名和**接口要的名字不一样**，要做这层映射（见 :data:`PARAM_ALIASES`）：
    ``svr_id``→``serverId``、``player_id``→``playerId``、``lang``→``languageCode``、
    ``record_id``→``recordId``、``resources_id``→``cardPoolId``。

    返回：``{"code": 0, "message": "success", "data": [...]}``
    ``code == -1`` 通常表示"记录过期/没打开唤取记录页"，不是网络问题。

## 卡池

7 个池子（:data:`POOLS`），逐个请求（接口一次只返回一个池）。
"""

from __future__ import annotations

import json
import ssl
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

#: 接口地址
QUERY_URL = "https://gmserver-api.aki-game2.com/gacha/record/query"

#: 用户复制出来的链接前缀（用来识别"这是不是唤取记录链接"）
LINK_HOST = "aki-gm-resources.aki-game.com"

#: 链接参数名 → 接口参数名。
#: ⚠ 两边名字**不一样**，这是最容易踩的坑：直接拿链接的参数名去请求会 query 不到。
PARAM_ALIASES = {
    "svr_id": "serverId",
    "player_id": "playerId",
    "lang": "languageCode",
    "record_id": "recordId",
    "resources_id": "cardPoolId",
}

#: 7 个卡池：``(cardPoolType, 显示名)``。
#: ⚠ 顺序即界面顺序（和游戏里「唤取记录」的页签顺序一致）。
POOLS: tuple[tuple[str, str], ...] = (
    ("1", "角色活动唤取"),
    ("2", "武器活动唤取"),
    ("3", "角色常驻唤取"),
    ("4", "武器常驻唤取"),
    ("5", "新手唤取"),
    ("6", "新手自选唤取"),
    ("7", "新手自选唤取（感恩定向唤取）"),
)

#: 五星保底抽数（角色池 / 武器池都是 80）
PITY_FIVE = 80
#: 四星保底（10 抽必出四星及以上）
PITY_FOUR = 10

#: 欧非评价：``(平均出货抽数下限, 称号, 颜色)`` —— 从大到小匹配。
#: 阈值参考鸣潮工坊那套（平均抽数越低越欧）。
LUCK_TIERS: tuple[tuple[float, str, str], ...] = (
    (150.0, "至尊非酋王", "#d9705a"),
    (120.0, "究极大非酋", "#c9705a"),
    (100.0, "非洲人", "#c8a86a"),
    (90.0, "亚洲人", "#b9b06a"),
    (60.0, "欧洲人", "#7fae72"),
    (30.0, "欧皇", "#5fae90"),
    (0.0, "策划亲儿子", "#5ee7ff"),
)


class GachaError(Exception):
    """拉取失败。消息是**写给用户看的**，不加异常类名前缀。"""


# --------------------------------------------------------------------- 链接解析


def parse_link(link: str) -> dict[str, str]:
    """把用户复制的唤取记录链接解析成接口参数。

    返回 ``{serverId, playerId, languageCode, recordId, cardPoolId}``。

    校验三件事（缺一不可，缺了就报清楚哪件）：
    1. 是 ``aki-gm-resources.aki-game.com`` 的链接；
    2. 带 ``player_id``（没有它就无法定位账号）；
    3. 带 ``record_id`` / ``resources_id``（没有它们接口读不到记录）。

    ⚠ 用户很可能粘错（粘成整页 HTML、或者别的站的链接），所以这里要
    给出**指明问题**的错误，而不是笼统的"链接无效"。
    """
    text = str(link or "").strip()
    if not text:
        raise GachaError("请先粘贴唤取记录链接（游戏里打开「唤取记录」页面复制）")
    if LINK_HOST not in text:
        raise GachaError(
            "这不像唤取记录链接 —— 它应该以 "
            f"https://{LINK_HOST}/ 开头。\n"
            "请在游戏里打开「唤取记录」页面，点右上角复制链接。"
        )

    # 取 ? 之后的部分（链接是 #/record?xxx 形式，问号在 # 后面）
    query = text.split("?", 1)[1] if "?" in text else ""
    if not query:
        raise GachaError("链接里没有参数 —— 请重新在游戏里复制一次")
    # 去掉可能的锚点尾巴
    query = query.split("#", 1)[0]
    raw = urllib.parse.parse_qs(query)

    def get(name: str) -> str:
        values = raw.get(name) or []
        return str(values[0]).strip() if values else ""

    params = {
        target: get(source) for source, target in PARAM_ALIASES.items()
    }
    missing = [k for k in ("playerId", "recordId", "cardPoolId") if not params[k]]
    if missing:
        raise GachaError(
            "链接不完整（缺 "
            + "、".join(missing)
            + "）—— 请重新在游戏里复制一次完整链接"
        )
    params.setdefault("languageCode", "zh-Hans")
    if not params.get("languageCode"):
        params["languageCode"] = "zh-Hans"
    return params


# --------------------------------------------------------------------- 数据模型


@dataclass
class Pull:
    """一条唤取记录（一次单抽）。"""

    #: 物品名（角色名 / 武器名）
    name: str = ""
    #: 星级：5 / 4 / 3
    star: int = 3
    #: ``"角色"`` / ``"武器"``
    kind: str = ""
    #: 时间字符串（接口原样返回）
    time: str = ""
    #: 属于哪个卡池（:data:`POOLS` 的显示名）
    pool: str = ""

    @classmethod
    def from_record(cls, record: dict, pool: str) -> "Pull":
        record = record if isinstance(record, dict) else {}
        name = str(
            record.get("name")
            or record.get("resourceName")
            or record.get("itemName")
            or ""
        ).strip()
        try:
            star = int(record.get("rankType") or record.get("star") or 3)
        except (TypeError, ValueError):
            star = 3
        return cls(
            name=name,
            star=star,
            kind=str(record.get("resourceType") or "").strip(),
            time=str(record.get("time") or "").strip(),
            pool=pool,
        )


@dataclass
class PoolStats:
    """一个卡池的统计。"""

    name: str = ""
    #: 该池全部记录（按接口顺序，通常是最新在前）
    pulls: list[Pull] = field(default_factory=list)

    # ---------------------------------------------------------------- 基础
    @property
    def total(self) -> int:
        return len(self.pulls)

    @property
    def five_stars(self) -> list[Pull]:
        return [p for p in self.pulls if p.star == 5]

    @property
    def four_stars(self) -> list[Pull]:
        return [p for p in self.pulls if p.star == 4]

    @property
    def five_count(self) -> int:
        return len(self.five_stars)

    def rate(self) -> float:
        """五星出货率（百分比）。没抽过返回 0。"""
        return (self.five_count / self.total * 100.0) if self.total else 0.0

    def average(self) -> float:
        """平均多少抽出一个五星。没出过返回 0。"""
        return (self.total / self.five_count) if self.five_count else 0.0

    def spans(self) -> list[int]:
        """每个五星**用掉多少抽**（含它自己），按**时间顺序**返回。

        ⚠ 前提：``self.pulls`` 是**最新在前**（接口就是这个顺序，见
        :meth:`Pull.from_record` 的使用处）。所以先 ``reversed`` 成时间正序
        再累计 —— 反过来算会把"第一金用了几抽"和"最后一金用了几抽"搞混。

        最后一个五星之后还没出的那些抽**不计入**（那是"当前垫抽"，
        见 :meth:`current_pity`）。
        """
        ordered = list(reversed(self.pulls))
        result: list[int] = []
        count = 0
        for pull in ordered:
            count += 1
            if pull.star == 5:
                result.append(count)
                count = 0
        return result

    def current_pity(self) -> int:
        """当前垫了多少抽还没出五星。

        ``self.pulls`` 是**最新在前**，所以从**头部**数到第一个五星为止 ——
        那一串就是"最后一次出金之后又抽的"。不用反转（反转了会从最早那头数，
        变成"第一金之前垫了多少"，完全不是一回事）。
        """
        count = 0
        for pull in self.pulls:
            if pull.star == 5:
                break
            count += 1
        return count

    def five_star_spans(self) -> list[tuple[Pull, int]]:
        """``[(五星, 它用掉多少抽), ...]``，按**时间顺序**。

        界面要给每个五星标"第几抽出"，直接用这个 —— 别在界面里重算一遍
        （两处各写一份，方向搞反了会静默显示错的数字）。
        """
        ordered = list(reversed(self.pulls))
        result: list[tuple[Pull, int]] = []
        count = 0
        for pull in ordered:
            count += 1
            if pull.star == 5:
                result.append((pull, count))
                count = 0
        return result

    def _tier(self, average: float) -> tuple[str, str]:
        """按平均出货抽数取评价 —— 阈值从大到小匹配，第一个命中的就是。

        ``LUCK_TIERS`` 最后一项的阈值是 0.0，所以**任何**正的平均抽数都会命中
        某一档，不需要额外的兜底分支。
        """
        for threshold, title, color in LUCK_TIERS:
            if average >= threshold:
                return title, color
        return LUCK_TIERS[-1][1], LUCK_TIERS[-1][2]   # pragma: no cover - 不可达

    def luck(self) -> tuple[str, str] | None:
        """欧非评价 ``(称号, 颜色)``；没出过五星返回 ``None``。

        按**平均出货抽数**评级（越低越欧），阈值见 :data:`LUCK_TIERS`。
        """
        average = self.average()
        if not average:
            return None
        return self._tier(average)


@dataclass
class GachaReport:
    """全部卡池的统计报告。"""

    player_id: str = ""
    pools: list[PoolStats] = field(default_factory=list)

    # ---------------------------------------------------------------- 汇总
    @property
    def total(self) -> int:
        return sum(p.total for p in self.pools)

    @property
    def five_count(self) -> int:
        return sum(p.five_count for p in self.pools)

    @property
    def four_count(self) -> int:
        return sum(len(p.four_stars) for p in self.pools)

    def rate(self) -> float:
        return (self.five_count / self.total * 100.0) if self.total else 0.0

    def average(self) -> float:
        return (self.total / self.five_count) if self.five_count else 0.0

    def all_five_stars(self) -> list[Pull]:
        """所有五星，按时间倒序（最新在前）。"""
        items = [p for pool in self.pools for p in pool.five_stars]
        return sorted(items, key=lambda p: p.time, reverse=True)

    def active_pools(self) -> list[PoolStats]:
        """抽过的池子（没抽过的不显示，免得界面一排全 0）。"""
        return [p for p in self.pools if p.total]

    def luck(self) -> tuple[str, str] | None:
        """整体欧非评价（按全部卡池合计的平均出货抽数）。

        ⚠ 复用 :meth:`PoolStats._tier`，别在这里再抄一遍阈值循环 ——
        两处各写一份，改阈值时必然漏掉一处。
        """
        if not self.five_count:
            return None
        return PoolStats._tier(self, self.average())


# --------------------------------------------------------------------- 拉取


def _ssl_context():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def fetch_pool(params: dict[str, str], pool_type: str,
               timeout: int = 30) -> list[dict]:
    """拉一个卡池的原始记录。失败抛 :class:`GachaError`（消息给用户看）。"""
    body = {
        "serverId": params.get("serverId", ""),
        "playerId": params.get("playerId", ""),
        "languageCode": params.get("languageCode", "zh-Hans"),
        "recordId": params.get("recordId", ""),
        "cardPoolId": params.get("cardPoolId", ""),
        "cardPoolType": str(pool_type),
    }
    # 查询串用**接口要的参数名**（不是链接里的原名）
    query = urllib.parse.urlencode({**body, "cardPoolType": str(pool_type)})
    request = urllib.request.Request(
        f"{QUERY_URL}?{query}",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout,
                                    context=_ssl_context()) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - 网络问题要变成给用户看的话
        raise GachaError(f"请求失败：{exc}") from exc

    if not isinstance(payload, dict):
        raise GachaError("接口返回了看不懂的内容")
    code = payload.get("code")
    if code == -1:
        raise GachaError(
            str(payload.get("message") or "读取失败")
            + "\n请在游戏里**打开「唤取记录」页面**后再复制链接重试"
            "（记录链接会过期）。"
        )
    if code not in (0, None):
        raise GachaError(str(payload.get("message") or f"接口返回 code={code}"))
    data = payload.get("data")
    return list(data) if isinstance(data, list) else []


def fetch_report(params: dict[str, str], log=lambda _m: None) -> GachaReport:
    """拉全部卡池并汇总成报告。

    ⚠ 一个池拉失败就**整体失败**（抛 :class:`GachaError`）—— 半份报告会
    让统计数字对不上，比直接报错更糟。
    """
    report = GachaReport(player_id=params.get("playerId", ""))
    for pool_type, display in POOLS:
        log(f"拉取「{display}」…")
        records = fetch_pool(params, pool_type)
        stats = PoolStats(name=display)
        stats.pulls = [Pull.from_record(r, display) for r in records]
        report.pools.append(stats)
        log(f"  {display}：{stats.total} 抽")
    return report
